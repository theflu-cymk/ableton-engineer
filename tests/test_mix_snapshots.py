"""Mix snapshots: save the balance, refuse a stale Set, restore exactly."""

import os
import tempfile
import unittest
from unittest import mock

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeSend, FakeTrack, build_song
from enableton.manifest import load_manifest
from enableton.modes import load_modes
from enableton.plans.executor import _clean

from Enableton.errors import ScriptError


def snapshot_song():
    song = build_song()
    song.master_track = FakeTrack("Master", volume=0.85)
    song.return_tracks = [FakeTrack("Reverb", volume=0.6)]
    song.tracks[0].sends = [FakeSend(0.3, "Reverb")]
    return song


class FrozenVolumeTrack:
    """A track whose fader Live would refuse, to prove a failed restore reverts."""

    def __init__(self, name, volume):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "volume", volume)
        object.__setattr__(self, "pan", 0.0)
        object.__setattr__(self, "mute", False)
        object.__setattr__(self, "solo", False)
        object.__setattr__(self, "sends", [])

    def __setattr__(self, name, value):
        if name == "volume":
            raise RuntimeError("fader frozen")
        object.__setattr__(self, name, value)


class MixSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(
            os.environ, {"APPDATA": self._tmp.name, "HOME": self._tmp.name}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.song = snapshot_song()
        self.adapter = FakeAdapter(self.song)

    def save(self):
        return self.adapter.call("mix.snapshot_save", {})

    def test_save_captures_every_track_and_the_master(self):
        saved = self.save()
        self.assertRegex(saved["snapshot_id"], r"^m_[0-9a-f]{8}$")
        self.assertTrue(saved["path"].startswith(self._tmp.name))
        self.assertTrue(os.path.isfile(saved["path"]))
        self.assertEqual(saved["counts"]["tracks"], 3)
        self.assertEqual(saved["counts"]["returns"], 1)
        self.assertEqual(saved["unreadable"], [])

        drums = saved["tracks"][0]
        self.assertEqual(drums["name"], "Drums")
        self.assertEqual(drums["volume"], 0.82)
        self.assertEqual(drums["sends"][0]["name"], "Reverb")
        self.assertEqual(drums["sends"][0]["value"], 0.3)

        reverb = saved["tracks"][3]
        self.assertEqual(reverb["kind"], "return")
        self.assertEqual(reverb["name"], "Reverb")
        self.assertEqual(saved["master"]["volume"], 0.85)

    def test_dry_run_reports_changes_without_writing(self):
        saved = self.save()
        self.song.tracks[0].volume = 0.5
        self.song.master_track.volume = 0.4

        result = self.adapter.call("mix.snapshot_restore", {"snapshot_id": saved["snapshot_id"]})
        self.assertTrue(result["dry_run"])
        fields = {(row["kind"], row["field"]) for row in result["changes"]}
        self.assertEqual(fields, {("track", "volume"), ("master", "volume")})
        self.assertAlmostEqual(self.song.tracks[0].volume, 0.5)
        self.assertAlmostEqual(self.song.master_track.volume, 0.4)

    def test_apply_restores_and_its_undo_returns_exactly(self):
        saved = self.save()
        drums = self.song.tracks[0]
        drums.volume = 0.5
        drums.pan = 0.4
        drums.mute = True
        drums.sends[0].value = 0.9
        self.song.master_track.volume = 0.4

        applied = self.adapter.call(
            "mix.snapshot_restore", {"snapshot_id": saved["snapshot_id"], "dry_run": False}
        )
        self.assertEqual(len(applied["changes"]), 5)
        self.assertAlmostEqual(drums.volume, 0.82)
        self.assertAlmostEqual(drums.pan, 0.0)
        self.assertFalse(drums.mute)
        self.assertAlmostEqual(drums.sends[0].value, 0.3)
        self.assertAlmostEqual(self.song.master_track.volume, 0.85)

        back = self.adapter.call(
            "mix.snapshot_restore", {"restore": applied["undo"], "dry_run": False}
        )
        self.assertEqual(back["compared"], len(applied["undo"]))
        self.assertAlmostEqual(drums.volume, 0.5)
        self.assertAlmostEqual(drums.pan, 0.4)
        self.assertTrue(drums.mute)
        self.assertAlmostEqual(drums.sends[0].value, 0.9)
        self.assertAlmostEqual(self.song.master_track.volume, 0.4)

    def test_a_renamed_track_refuses_the_whole_restore(self):
        saved = self.save()
        self.song.tracks[0].name = "Drums old"
        self.song.tracks[0].volume = 0.5

        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "mix.snapshot_restore", {"snapshot_id": saved["snapshot_id"], "dry_run": False}
            )
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertIn("nothing was written", ctx.exception.message)
        self.assertAlmostEqual(self.song.tracks[0].volume, 0.5)

    def test_a_removed_track_refuses_the_whole_restore(self):
        saved = self.save()
        self.song.tracks.pop(0)
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "mix.snapshot_restore", {"snapshot_id": saved["snapshot_id"], "dry_run": False}
            )
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")

    def test_a_failed_write_reverts_what_it_already_changed(self):
        saved = self.save()
        first = self.song.tracks[0]
        first.volume = 0.5
        self.song.tracks[1] = FrozenVolumeTrack("Bass layer", 0.33)

        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "mix.snapshot_restore", {"snapshot_id": saved["snapshot_id"], "dry_run": False}
            )
        self.assertEqual(ctx.exception.code, "LIVE_ERROR")
        self.assertGreaterEqual(ctx.exception.detail["reverted"], 1)
        self.assertAlmostEqual(first.volume, 0.5)

    def test_a_bad_or_unknown_id_is_refused(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("mix.snapshot_restore", {"snapshot_id": "../../escape"})
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("mix.snapshot_restore", {"snapshot_id": "m_0000aaaa"})
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

    def test_id_and_undo_token_are_mutually_exclusive(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "mix.snapshot_restore",
                {"snapshot_id": "m_0000aaaa", "restore": [{"field": "volume", "value": 0.5}]},
            )
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_the_applied_payload_matches_its_preflight(self):
        saved = self.save()
        self.song.tracks[0].volume = 0.5
        args = {"snapshot_id": saved["snapshot_id"]}
        self.assertEqual(
            _clean(self.adapter.call("mix.snapshot_restore", dict(args))),
            _clean(self.adapter.call("mix.snapshot_restore", dict(args, dry_run=False))),
        )

    def test_a_set_without_a_master_track_saves_what_it_has(self):
        adapter = FakeAdapter(build_song())
        saved = adapter.call("mix.snapshot_save", {})
        self.assertIsNone(saved["master"])
        self.assertIn("no master track", saved["master_reason"])

        adapter.song.tracks[0].volume = 0.5
        restored = adapter.call(
            "mix.snapshot_restore", {"snapshot_id": saved["snapshot_id"], "dry_run": False}
        )
        self.assertEqual(len(restored["changes"]), 1)


class MixSnapshotCatalogueTests(unittest.TestCase):
    def test_declared_with_the_right_write_flags(self):
        manifest = load_manifest()
        save = manifest["mix_snapshot_save"]
        self.assertEqual(save.cmd, "mix.snapshot_save")
        self.assertFalse(save.writes)
        restore = manifest["mix_snapshot_restore"]
        self.assertEqual(restore.cmd, "mix.snapshot_restore")
        self.assertTrue(restore.writes)
        self.assertTrue(restore.reversible)

    def test_both_are_loaded_by_mix(self):
        modes = load_modes(load_manifest())
        mix = modes.get("mix")
        self.assertIn("mix_snapshot_save", mix.tools)
        self.assertIn("mix_snapshot_restore", mix.tools)
        self.assertLessEqual(len(mix.tools), 34)


if __name__ == "__main__":
    unittest.main()

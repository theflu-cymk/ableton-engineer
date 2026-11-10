import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeClip, build_song

from Enableton.errors import ScriptError


class TrackPanTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()

    def test_dry_run_does_not_change_a_pan(self):
        result = self.adapter.call(
            "tracks.set_pan", {"tracks": ["Drums"], "pan": 0.25, "dry_run": True}
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["changes"][0]["from"], 0.0)
        self.assertEqual(result["changes"][0]["to"], 0.25)
        self.assertEqual(self.adapter.song.tracks[0].pan, 0.0)

    def test_apply_and_restore_are_exact(self):
        result = self.adapter.call(
            "tracks.set_pan", {"tracks": ["Drums"], "pan": 0.25, "dry_run": False}
        )
        self.assertAlmostEqual(self.adapter.song.tracks[0].pan, 0.25)
        restored = self.adapter.call(
            "tracks.set_pan", {"restore": result["undo"], "dry_run": False}
        )
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.adapter.song.tracks[0].pan, 0.0)

    def test_pan_range_and_track_names_are_validated(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("tracks.set_pan", {"pan": 1.5, "dry_run": True})
        self.assertEqual(ctx.exception.code, "BAD_ARGS")
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("tracks.set_pan", {"tracks": ["Missing"], "pan": 0.0})
        self.assertEqual(ctx.exception.code, "NOT_FOUND")


class ClipRenameTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.adapter = FakeAdapter(self.song)

    def test_dry_run_leaves_an_arrangement_clip_unchanged(self):
        result = self.adapter.call(
            "clips.rename",
            {"track": "Drums", "clip": "drums 1", "name": "intro", "dry_run": True},
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["changes"][0]["from"], "drums 1")
        self.assertEqual(self.song.tracks[0].arrangement_clips[0].name, "drums 1")

    def test_apply_rename_and_restore_the_arrangement_clip(self):
        result = self.adapter.call(
            "clips.rename",
            {"track": "Drums", "clip": "drums 1", "name": "intro", "dry_run": False},
        )
        self.assertEqual(self.song.tracks[0].arrangement_clips[0].name, "intro")
        restored = self.adapter.call(
            "clips.rename", {"restore": result["undo"], "dry_run": False}
        )
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.song.tracks[0].arrangement_clips[0].name, "drums 1")

    def test_session_slot_resolves_a_session_clip(self):
        result = self.adapter.call(
            "clips.rename",
            {
                "track": "Drums", "clip": "drums A", "name": "verse",
                "location": "session", "slot": 0, "dry_run": False,
            },
        )
        self.assertEqual(result["changes"][0]["location"], "session")
        self.assertEqual(self.song.tracks[0].clip_slots[0].clip.name, "verse")

    def test_duplicate_arrangement_names_are_refused(self):
        self.song.tracks[0].arrangement_clips.append(
            FakeClip("drums 1", 100.0, 108.0, True)
        )
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "clips.rename",
                {"track": "Drums", "clip": "drums 1", "name": "intro"},
            )
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")

    def test_unknown_clip_is_typed(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "clips.rename", {"track": "Drums", "clip": "missing", "name": "x"}
            )
        self.assertEqual(ctx.exception.code, "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()

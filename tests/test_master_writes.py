"""The master fader write: dry run, apply, read-back, restore."""

import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeTrack, build_song
from enableton.manifest import load_manifest
from enableton.modes import load_modes
from enableton.plans.executor import PlanExecutor, Step, _clean

from Enableton.errors import ScriptError


class _StubScratch:
    def ensure(self):
        return "scratch.als"


def master_song(volume=0.85):
    song = build_song()
    song.master_track = FakeTrack("Master", volume=volume)
    return song


class MasterGainTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter(master_song())

    def test_dry_run_reports_the_change_without_writing(self):
        result = self.adapter.call("master.set_gain", {"value": 0.5})
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["changes"][0]["from"], 0.85)
        self.assertEqual(result["changes"][0]["to"], 0.5)
        self.assertEqual(result["undo"], [{"value": 0.85}])
        self.assertAlmostEqual(self.adapter.song.master_track.volume, 0.85)

    def test_apply_read_back_and_exact_restore(self):
        applied = self.adapter.call("master.set_gain", {"value": 0.5, "dry_run": False})
        self.assertAlmostEqual(self.adapter.song.master_track.volume, 0.5)

        back = self.adapter.call("master.set_gain", {"value": 0.5})
        self.assertEqual(back["changes"][0]["from"], 0.5)

        restored = self.adapter.call(
            "master.set_gain", {"restore": applied["undo"], "dry_run": False}
        )
        self.assertEqual(restored["restored"], 1)
        self.assertAlmostEqual(self.adapter.song.master_track.volume, 0.85)

    def test_value_outside_the_fader_range_is_refused(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("master.set_gain", {"value": 1.5})
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertAlmostEqual(self.adapter.song.master_track.volume, 0.85)

    def test_a_set_without_a_master_track_reports_unsupported(self):
        adapter = FakeAdapter(build_song())
        with self.assertRaises(ScriptError) as ctx:
            adapter.call("master.set_gain", {"value": 0.5})
        self.assertEqual(ctx.exception.code, "UNSUPPORTED")

    def test_restore_cannot_be_combined_with_a_value(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("master.set_gain", {"restore": [{"value": 0.5}], "value": 0.4})
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_the_applied_payload_matches_its_preflight(self):
        args = {"value": 0.5}
        self.assertEqual(
            _clean(self.adapter.call("master.set_gain", args)),
            _clean(self.adapter.call("master.set_gain", dict(args, dry_run=False))),
        )

    def test_the_write_applies_through_the_executor(self):
        outcome = PlanExecutor(self.adapter, scratch=_StubScratch()).apply([
            Step("master_set_gain", {"value": 0.5}),
        ])
        self.assertTrue(outcome["applied"])
        self.assertAlmostEqual(self.adapter.song.master_track.volume, 0.5)


class MasterCatalogueTests(unittest.TestCase):
    def test_declared_as_a_reversible_write(self):
        tool = load_manifest()["master_set_gain"]
        self.assertEqual(tool.cmd, "master.set_gain")
        self.assertTrue(tool.writes)
        self.assertTrue(tool.reversible)

    def test_loaded_by_mix(self):
        modes = load_modes(load_manifest())
        self.assertIn("master_set_gain", modes.get("mix").tools)
        self.assertLessEqual(len(modes.get("mix").tools), 34)


if __name__ == "__main__":
    unittest.main()

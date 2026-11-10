"""M2 write safety, independent of the GUI: preflight, copy, apply, restore."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from enableton.live.fake import FakeAdapter
from enableton.plans import PlanError, PlanExecutor, Step


class FailSecondApply(FakeAdapter):
    """Let the preflight pass, apply one step, then fail the second applied call."""

    def __init__(self, song):
        super().__init__(song)
        self.applied = 0

    def call(self, cmd, args=None, timeout_ms=None):
        args = args or {}
        if cmd == "tracks.gain_stage" and not args.get("dry_run", True):
            self.applied += 1
            if self.applied == 2:
                raise RuntimeError("synthetic second-step failure")
        return super().call(cmd, args, timeout_ms=timeout_ms)


class PlanSafetyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.root), True)
        self.source = self.root / "fortnight.als"
        self.source.write_bytes(b"original set bytes")
        self.backups = self.root / "backups"
        self.adapter = FakeAdapter()
        self.adapter.song.file_path = str(self.source)
        self.steps = [
            Step("tracks_gain_stage", {"tracks": ["Drums"], "headroom_db": -6}),
        ]

    def executor(self, adapter=None):
        return PlanExecutor(adapter or self.adapter, set_path=str(self.source),
                            backup_root=str(self.backups))

    def test_dry_run_trace_matches_apply_and_makes_a_copy_before_writing(self):
        executor = self.executor()

        preflight = executor.run(self.steps)
        self.assertFalse(self.backups.exists(), "a dry run must not make the safety copy")

        applied = executor.apply(self.steps)

        self.assertTrue(applied["applied"])
        self.assertEqual(preflight["trace"], applied["trace"])
        self.assertTrue(os.path.isfile(applied["scratch_copy"]))
        self.assertEqual(Path(applied["scratch_copy"]).read_bytes(), self.source.read_bytes())
        self.assertLess(self.adapter.song.tracks[0].volume, 0.82)

    def test_a_missing_set_path_refuses_before_any_write(self):
        before = self.adapter.song.tracks[0].volume
        executor = PlanExecutor(self.adapter, set_path=None, backup_root=str(self.backups))

        with self.assertRaises(PlanError) as ctx:
            executor.apply(self.steps)

        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertEqual(self.adapter.song.tracks[0].volume, before)

    def test_a_failed_second_step_restores_the_first_step_exactly(self):
        adapter = FailSecondApply(self.adapter.song)
        before = {track.name: track.volume for track in adapter.song.tracks}
        steps = [
            Step("tracks_gain_stage", {"tracks": ["Drums"], "headroom_db": -6}),
            Step("tracks_gain_stage", {"tracks": ["Bass layer"], "headroom_db": -6}),
        ]

        outcome = self.executor(adapter).apply(steps)

        self.assertFalse(outcome["applied"])
        self.assertEqual(outcome["error"]["type"], "RuntimeError")
        self.assertTrue(outcome["restore"]["ok"])
        self.assertEqual(
            {track.name: track.volume for track in adapter.song.tracks},
            before,
        )
        self.assertTrue(os.path.isfile(outcome["scratch_copy"]))

    def test_applying_the_same_plan_twice_is_a_no_op(self):
        executor = self.executor()

        first = executor.apply(self.steps)
        after_first = self.adapter.song.tracks[0].volume
        second = executor.apply(self.steps)

        self.assertTrue(first["applied"])
        self.assertTrue(second["already_applied"])
        self.assertFalse(second["applied"])
        self.assertEqual(self.adapter.song.tracks[0].volume, after_first)

    def test_restore_rejects_an_out_of_range_track(self):
        from Enableton.errors import ScriptError

        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("tracks.gain_stage", {
                "restore": [{"track_index": 99, "volume": 0.5}],
                "dry_run": False,
            })

        self.assertEqual(ctx.exception.code, "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()

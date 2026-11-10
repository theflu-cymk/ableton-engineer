"""Real handler tests for clips_duplicate_range, including transactional rollback."""

import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeClip, FakeTrack
from enableton.plans import PlanExecutor, Step

from Enableton.errors import ScriptError


class FailSecondDuplicate(FakeAdapter):
    """Let both dry runs pass, then fail the second applied duplicate."""

    def __init__(self, song):
        super().__init__(song)
        self.applied = 0

    def call(self, cmd, args=None, timeout_ms=None):
        args = args or {}
        if cmd == "clips.duplicate_range" and not args.get("dry_run", True):
            self.applied += 1
            if self.applied == 2:
                raise RuntimeError("synthetic duplicate failure")
        return super().call(cmd, args, timeout_ms=timeout_ms)


class DuplicateRangeTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.drums = self.adapter.song.tracks[0]

    def duplicate(self, **args):
        base = {
            "tracks": ["Drums"],
            "from_bar": 1,
            "to_bar": 2,
            "destination_bar": 5,
        }
        base.update(args)
        return self.adapter.call("clips.duplicate_range", base)

    def test_dry_run_predicts_without_changing_the_arrangement(self):
        before = [(clip.name, clip.start_time, clip.end_time) for clip in self.drums.arrangement_clips]

        result = self.duplicate()

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["undo"], [])
        self.assertEqual(
            [(row["clip"], row["from"], row["to"]) for row in result["changes"]],
            [("drums 1", 0.0, 16.0)],
        )
        self.assertEqual(
            [(clip.name, clip.start_time, clip.end_time) for clip in self.drums.arrangement_clips],
            before,
        )

    def test_apply_matches_the_dry_run_and_undo_restores_the_exact_clip_list(self):
        before = [(clip.name, clip.start_time, clip.end_time) for clip in self.drums.arrangement_clips]
        preview = self.duplicate()

        applied = self.duplicate(dry_run=False)

        self.assertFalse(applied["dry_run"])
        self.assertEqual(applied["changes"], preview["changes"])
        self.assertEqual(len(applied["undo"]), 1)
        self.assertEqual(
            [(clip.name, clip.start_time, clip.end_time) for clip in self.drums.arrangement_clips],
            sorted(before + [("drums 1", 16.0, 32.0)], key=lambda row: row[1]),
        )

        restored = self.adapter.call(
            "clips.duplicate_range",
            {"restore": applied["undo"], "dry_run": False},
        )

        self.assertEqual(restored["restored"], 1)
        self.assertEqual(restored["missing"], [])
        self.assertEqual(
            [(clip.name, clip.start_time, clip.end_time) for clip in self.drums.arrangement_clips],
            before,
        )

    def test_the_window_is_half_open_and_keeps_relative_offsets(self):
        track = FakeTrack(
            "Edges",
            arrangement_clips=[
                FakeClip("before", 0.0, 4.0),
                FakeClip("inside", 4.0, 8.0),
                FakeClip("at end", 8.0, 12.0),
            ],
        )
        self.adapter.song.tracks = [track]

        result = self.duplicate(tracks=["Edges"], from_bar=2, to_bar=3, destination_bar=10)

        self.assertEqual([row["clip"] for row in result["changes"]], ["inside"])
        self.assertEqual(result["changes"][0]["to"], 36.0)

    def test_plan_executor_matches_traces_and_makes_a_scratch_copy_before_writing(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)
        source = root / "scratch.als"
        source.write_bytes(b"original set bytes")
        self.adapter.song.file_path = str(source)
        executor = PlanExecutor(self.adapter, set_path=str(source), backup_root=str(root / "backups"))
        steps = [Step("clips_duplicate_range", {
            "tracks": ["Drums"], "from_bar": 1, "to_bar": 2, "destination_bar": 5,
        })]

        preflight = executor.run(steps)
        applied = executor.apply(steps)

        self.assertTrue(applied["applied"])
        self.assertEqual(preflight["trace"], applied["trace"])
        self.assertTrue(Path(applied["scratch_copy"]).is_file())
        self.assertEqual(Path(applied["scratch_copy"]).read_bytes(), source.read_bytes())
        self.assertEqual(len(self.drums.arrangement_clips), 3)

    def test_a_failed_second_duplicate_restores_the_first_one_exactly(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)
        source = root / "scratch.als"
        source.write_bytes(b"original set bytes")
        self.adapter.song.file_path = str(source)
        before = [(clip.name, clip.start_time, clip.end_time) for clip in self.drums.arrangement_clips]
        adapter = FailSecondDuplicate(self.adapter.song)
        executor = PlanExecutor(adapter, set_path=str(source), backup_root=str(root / "backups"))
        steps = [
            Step("clips_duplicate_range", {
                "tracks": ["Drums"], "from_bar": 1, "to_bar": 2, "destination_bar": 5,
            }),
            Step("clips_duplicate_range", {
                "tracks": ["Drums"], "from_bar": 1, "to_bar": 2, "destination_bar": 17,
            }),
        ]

        outcome = executor.apply(steps)

        self.assertFalse(outcome["applied"])
        self.assertEqual(outcome["error"]["type"], "RuntimeError")
        self.assertTrue(outcome["restore"]["ok"])
        self.assertEqual(
            [(clip.name, clip.start_time, clip.end_time) for clip in self.drums.arrangement_clips],
            before,
        )

    def test_repeating_the_same_plan_is_a_no_op(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)
        source = root / "scratch.als"
        source.write_bytes(b"original set bytes")
        self.adapter.song.file_path = str(source)
        executor = PlanExecutor(self.adapter, set_path=str(source), backup_root=str(root / "backups"))
        steps = [Step("clips_duplicate_range", {
            "tracks": ["Drums"], "from_bar": 1, "to_bar": 2, "destination_bar": 5,
        })]

        first = executor.apply(steps)
        second = executor.apply(steps)

        self.assertTrue(first["applied"])
        self.assertTrue(second["already_applied"])
        self.assertFalse(second["applied"])
        self.assertEqual(len(self.drums.arrangement_clips), 3)

    def test_an_unavailable_duplicate_reports_a_reason_instead_of_pretending(self):
        self.drums.duplicate_clip_to_arrangement = None

        result = self.duplicate(tracks=["Drums"])

        self.assertEqual(result["changes"], [])
        self.assertEqual(result["skipped"][0]["track"], "Drums")
        self.assertIn("cannot duplicate", result["skipped"][0]["reason"])

    def test_restore_rejects_a_range_and_missing_created_clip_is_reported(self):
        with self.assertRaises(ScriptError) as ctx:
            self.duplicate(restore=[], from_bar=1)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

        result = self.adapter.call("clips.duplicate_range", {
            "restore": [{"track_index": 0, "name": "gone", "start": 123.0}],
            "dry_run": False,
        })
        self.assertEqual(result["restored"], 0)
        self.assertEqual(result["missing"][0]["start"], 123.0)

    def test_restore_rejects_an_out_of_range_track(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.duplicate_range", {
                "restore": [{"track_index": 99, "start": 0.0}],
                "dry_run": False,
            })
        self.assertEqual(ctx.exception.code, "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()

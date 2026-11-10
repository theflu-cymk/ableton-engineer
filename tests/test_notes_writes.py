"""The notes write tools: dry run, apply, exact restore and closed arguments."""

import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeClip, FakeNote, build_song

from Enableton.errors import ScriptError


class NotesWriteTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.adapter = FakeAdapter(self.song)
        self.track = "Drums"
        self.clip = self.add_clip("gate midi", [
            FakeNote(36, 0.13, 0.2, 100),
            FakeNote(40, 0.37, 0.2, 80),
            FakeNote(43, 0.62, 0.4, 60),
        ])

    def add_clip(self, name, notes):
        clip = FakeClip(name, 0.0, 4.0, True, notes=notes)
        self.song.tracks[0].arrangement_clips.append(clip)
        return clip

    def read(self, clip="gate midi"):
        return self.adapter.call("notes.read", {"track": self.track, "clip": clip})

    def write(self, tool, **args):
        args.setdefault("track", self.track)
        args.setdefault("clip", "gate midi")
        return self.adapter.call(tool, args)

    def restore(self, tool, result):
        return self.adapter.call(tool, {"restore": result["undo"], "dry_run": False})

    def test_quantize_dry_run_apply_and_exact_restore(self):
        before = self.read()

        preview = self.write("notes.quantize", grid=0.25, dry_run=True)
        self.assertTrue(preview["dry_run"])
        self.assertEqual(self.read(), before)

        applied = self.write("notes.quantize", grid=0.25, dry_run=False)
        self.assertEqual([note["start"] for note in self.read()["notes"]], [0.25, 0.25, 0.5])
        self.assertEqual(applied["moved"], 3)

        restored = self.restore("notes.quantize", applied)
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.read(), before)

    def test_quantize_strength_blends_toward_the_grid(self):
        applied = self.write("notes.quantize", grid=0.25, strength=0.5, dry_run=False)
        starts = [round(note["start"], 4) for note in self.read()["notes"]]
        self.assertEqual(starts, [0.19, 0.31, 0.56])
        self.restore("notes.quantize", applied)

    def test_transform_changes_pitch_velocity_and_duration(self):
        before = self.read()
        applied = self.write(
            "notes.transform", transpose=2, velocity_scale=0.5, duration_scale=2,
            dry_run=False,
        )
        notes = self.read()["notes"]
        self.assertEqual([note["pitch"] for note in notes], [38, 42, 45])
        self.assertEqual([note["velocity"] for note in notes], [50, 40, 30])
        self.assertEqual([note["duration"] for note in notes], [0.4, 0.4, 0.8])
        self.restore("notes.transform", applied)
        self.assertEqual(self.read(), before)

    def test_transform_refuses_a_pitch_outside_the_range(self):
        self.add_clip("top", [FakeNote(127, 0.0, 1.0, 100)])
        with self.assertRaises(ScriptError) as ctx:
            self.write("notes.transform", clip="top", transpose=1)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")
        self.assertEqual(self.read("top")["notes"][0]["pitch"], 127)

    def test_humanize_is_seeded_and_restores(self):
        before = self.read()
        applied = self.write(
            "notes.humanize", timing=0.02, velocity=10, seed=7, dry_run=False
        )
        first = self.read()
        self.assertEqual(applied["seed"], 7)
        self.assertTrue(all(
            abs(note["start"] - original["start"]) <= 0.02 + 1e-9
            for note, original in zip(first["notes"], before["notes"])
        ))
        self.restore("notes.humanize", applied)

        again = self.write(
            "notes.humanize", timing=0.02, velocity=10, seed=7, dry_run=False
        )
        self.assertEqual(self.read(), first)
        self.restore("notes.humanize", again)
        self.assertEqual(self.read(), before)

    def test_strum_orders_chords_up_and_down(self):
        self.add_clip("chord", [
            FakeNote(36, 0.0, 0.5, 100),
            FakeNote(40, 0.0, 0.5, 100),
            FakeNote(43, 0.0, 0.5, 100),
        ])

        up = self.write(
            "notes.strum", clip="chord", offset=0.05, direction="up", dry_run=False
        )
        starts = {note["pitch"]: note["start"] for note in self.read("chord")["notes"]}
        self.assertEqual(starts, {36: 0.0, 40: 0.05, 43: 0.1})
        self.restore("notes.strum", up)

        down = self.write(
            "notes.strum", clip="chord", offset=0.05, direction="down", dry_run=False
        )
        starts = {note["pitch"]: note["start"] for note in self.read("chord")["notes"]}
        self.assertEqual(starts, {43: 0.0, 40: 0.05, 36: 0.1})
        self.restore("notes.strum", down)

    def test_replace_writes_a_whole_vector_and_restores(self):
        before = self.read()
        applied = self.write("notes.replace", notes=[
            {"pitch": 60, "start": 0.0, "duration": 1.0, "velocity": 90},
            {"pitch": 64, "start": 1.0, "duration": 0.5},
        ], dry_run=False)
        self.assertEqual(self.read()["total"], 2)
        self.assertEqual(applied["notes_before"], 3)
        self.assertEqual(applied["notes_after"], 2)
        self.restore("notes.replace", applied)
        self.assertEqual(self.read(), before)

    def test_scale_lock_moves_to_the_nearest_scale_tone(self):
        self.add_clip("out of key", [
            FakeNote(61, 0.0, 0.5, 100),
            FakeNote(66, 0.5, 0.5, 100),
            FakeNote(70, 1.0, 0.5, 100),
        ])
        applied = self.write(
            "notes.scale_lock", clip="out of key", root="C", scale="major", dry_run=False
        )
        notes = self.read("out of key")["notes"]
        self.assertEqual([note["pitch"] for note in notes], [60, 65, 69])
        self.assertTrue(all(note["pitch"] % 12 in {0, 2, 4, 5, 7, 9, 11} for note in notes))
        self.restore("notes.scale_lock", applied)

    def test_live_set_notes_appends_so_writes_clear_first(self):
        clip = self.song.tracks[0].arrangement_clips[-1]
        self.assertEqual(len(clip.notes), 3)
        clip.set_notes(((60, 0.0, 1.0, 100, False),))
        self.assertEqual(len(clip.notes), 4)
        before = self.read()

        applied = self.write("notes.replace", notes=[
            {"pitch": 61, "start": 0.0, "duration": 1.0, "velocity": 90},
        ], dry_run=False)
        self.assertEqual(self.read()["total"], 1)
        self.assertEqual(self.read()["notes"][0]["pitch"], 61)
        self.restore("notes.replace", applied)
        self.assertEqual(self.read(), before)

    def test_replace_with_an_empty_vector_clears_the_clip(self):
        before = self.read()
        applied = self.write("notes.replace", notes=[], dry_run=False)
        self.assertEqual(self.read()["total"], 0)
        self.restore("notes.replace", applied)
        self.assertEqual(self.read(), before)

    def test_invalid_arguments_write_nothing(self):
        before = self.read()
        cases = [
            ("notes.transform", {}),
            ("notes.replace", {"notes": [{"pitch": 200, "start": 0, "duration": 1}]}),
            ("notes.quantize", {"grid": 0}),
            ("notes.scale_lock", {"scale": "chromatic"}),
        ]
        for tool, args in cases:
            with self.assertRaises(ScriptError, msg=tool) as ctx:
                self.write(tool, dry_run=False, **args)
            self.assertEqual(ctx.exception.code, "BAD_ARGS", tool)
        self.assertEqual(self.read(), before)

    def test_restore_reports_a_missing_clip_instead_of_failing(self):
        token = [{
            "track_index": 1, "location": "arrangement", "slot": None, "start": 999.0,
            "clip": "gone", "notes": [],
        }]
        result = self.adapter.call("notes.quantize", {"restore": token, "dry_run": False})
        self.assertEqual(result["restored"], 0)
        self.assertEqual(len(result["missing"]), 1)


if __name__ == "__main__":
    unittest.main()

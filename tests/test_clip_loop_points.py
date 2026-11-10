import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeClip, build_song

from Enableton.errors import ScriptError


class ClipLoopPointTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.track = self.song.tracks[1]  # Bass layer
        self.clip = self.track.arrangement_clips[0]
        self.clip.warping = True
        self.clip.looping = True
        self.clip.loop_start = 1.0
        self.clip.loop_end = 16.0
        self.adapter = FakeAdapter(self.song)

    def args(self, **overrides):
        base = {
            "track": "Bass layer", "clip": "bass", "location": "arrangement",
            "loop_start": 0.0, "loop_end": 8.0,
        }
        base.update(overrides)
        return base

    def test_dry_run_leaves_loop_points_unchanged(self):
        result = self.adapter.call("clips.fix_loop_points", self.args(dry_run=True))
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["from"], {"loop_start": 1.0, "loop_end": 16.0})
        self.assertEqual(result["to"], {"loop_start": 0.0, "loop_end": 8.0})
        self.assertTrue(result["looping"])
        self.assertEqual((self.clip.loop_start, self.clip.loop_end), (1.0, 16.0))

    def test_apply_and_restore_are_exact(self):
        applied = self.adapter.call("clips.fix_loop_points", self.args(dry_run=False))
        self.assertEqual((self.clip.loop_start, self.clip.loop_end), (0.0, 8.0))
        self.assertEqual(len(applied["undo"]), 1)

        restored = self.adapter.call("clips.fix_loop_points", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual((self.clip.loop_start, self.clip.loop_end), (1.0, 16.0))

    def test_midi_clips_accept_loop_points(self):
        clip = self.song.tracks[0].arrangement_clips[0]
        clip.loop_start = 2.0
        clip.loop_end = 6.0
        applied = self.adapter.call("clips.fix_loop_points", {
            "track": "Drums", "clip": "drums 1", "location": "arrangement",
            "loop_start": 0.0, "loop_end": 4.0, "dry_run": False,
        })
        self.assertEqual((clip.loop_start, clip.loop_end), (0.0, 4.0))
        restored = self.adapter.call("clips.fix_loop_points", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual((clip.loop_start, clip.loop_end), (2.0, 6.0))

    def test_session_slot_resolves_and_restores(self):
        clip = self.track.clip_slots[1].clip
        clip.warping = True
        clip.loop_start = 1.0
        clip.loop_end = 8.0
        applied = self.adapter.call("clips.fix_loop_points", {
            "track": "Bass layer", "clip": "bass drop", "location": "session", "slot": 1,
            "loop_start": 2.0, "loop_end": 6.0, "dry_run": False,
        })
        self.assertEqual((clip.loop_start, clip.loop_end), (2.0, 6.0))
        restored = self.adapter.call("clips.fix_loop_points", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual((clip.loop_start, clip.loop_end), (1.0, 8.0))

    def test_unwarped_audio_is_unavailable_with_a_reason(self):
        clip = FakeClip("unwarped", 0.0, 8.0)
        self.track.arrangement_clips.append(clip)
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.fix_loop_points", self.args(clip="unwarped"))
        self.assertEqual(ctx.exception.code, "UNSUPPORTED")
        self.assertIn("warp the clip", ctx.exception.message)

    def test_bounds_are_typed_and_checked_against_length(self):
        cases = (
            {"loop_start": -1.0, "loop_end": 4.0},
            {"loop_start": 4.0, "loop_end": 4.0},
            {"loop_start": 0.0, "loop_end": 33.0},
            {"loop_start": True, "loop_end": 4.0},
        )
        for overrides in cases:
            with self.assertRaises(ScriptError, msg=repr(overrides)) as ctx:
                self.adapter.call("clips.fix_loop_points", self.args(**overrides))
            self.assertEqual(ctx.exception.code, "BAD_ARGS", overrides)

    def test_duplicate_clip_names_are_refused(self):
        self.track.arrangement_clips.append(
            FakeClip("bass", 100.0, 108.0, warping=True, loop_end=8.0)
        )
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.fix_loop_points", self.args())
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")

    def test_restore_reports_a_missing_clip_and_rejects_a_selection(self):
        result = self.adapter.call("clips.fix_loop_points", {
            "restore": [{
                "track_index": 1, "location": "arrangement", "start": 999.0,
                "loop_start": 0.0, "loop_end": 4.0,
            }],
            "dry_run": False,
        })
        self.assertEqual(result["restored"], 0)
        self.assertEqual(result["missing"][0]["start"], 999.0)

        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.fix_loop_points", {
                "restore": [{"track_index": 1, "location": "arrangement",
                             "loop_start": 0.0, "loop_end": 4.0}],
                "clip": "bass",
            })
        self.assertEqual(ctx.exception.code, "BAD_ARGS")


if __name__ == "__main__":
    unittest.main()

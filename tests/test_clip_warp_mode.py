import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeClip, build_song

from Enableton.errors import ScriptError


class ClipWarpModeTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.track = self.song.tracks[1]  # Bass layer, audio clips
        self.clip = self.track.arrangement_clips[0]
        self.clip.warping = True
        self.clip.warp_mode = 4
        self.adapter = FakeAdapter(self.song)

    def args(self, **overrides):
        base = {
            "track": "Bass layer", "clip": "bass", "location": "arrangement",
            "mode": 0,
        }
        base.update(overrides)
        return base

    def test_dry_run_leaves_the_mode_unchanged(self):
        result = self.adapter.call("clips.set_warp_mode", self.args(dry_run=True))
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["from"], 4)
        self.assertEqual(result["to"], 0)
        self.assertEqual(result["from_name"], "complex")
        self.assertEqual(self.clip.warp_mode, 4)

    def test_apply_and_restore_are_exact(self):
        applied = self.adapter.call("clips.set_warp_mode", self.args(dry_run=False))
        self.assertEqual(self.clip.warp_mode, 0)
        self.assertTrue(applied["warping"])
        self.assertEqual(len(applied["undo"]), 1)

        restored = self.adapter.call("clips.set_warp_mode", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.clip.warp_mode, 4)

    def test_mode_names_are_accepted(self):
        applied = self.adapter.call("clips.set_warp_mode", self.args(mode="re-pitch", dry_run=False))
        self.assertEqual(self.clip.warp_mode, 3)
        self.assertEqual(applied["to_name"], "re-pitch")
        restored = self.adapter.call("clips.set_warp_mode", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.clip.warp_mode, 4)

    def test_session_slot_resolves_a_session_clip(self):
        session = self.track.clip_slots[1].clip
        session.warping = True
        session.warp_mode = 2
        applied = self.adapter.call("clips.set_warp_mode", {
            "track": "Bass layer", "clip": "bass drop", "location": "session", "slot": 1,
            "mode": "beats", "dry_run": False,
        })
        self.assertEqual(session.warp_mode, 0)
        self.assertEqual(applied["location"], "session")
        restored = self.adapter.call("clips.set_warp_mode", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(session.warp_mode, 2)

    def test_midi_clips_are_unavailable_with_a_reason(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.set_warp_mode", {
                "track": "Drums", "clip": "drums 1", "mode": 0,
            })
        self.assertEqual(ctx.exception.code, "UNSUPPORTED")
        self.assertIn("MIDI clips", ctx.exception.message)

    def test_invalid_modes_are_typed(self):
        for mode in (7, True, "nonsense"):
            with self.assertRaises(ScriptError, msg=repr(mode)) as ctx:
                self.adapter.call("clips.set_warp_mode", self.args(mode=mode))
            self.assertEqual(ctx.exception.code, "BAD_ARGS", mode)

    def test_duplicate_clip_names_are_refused(self):
        self.track.arrangement_clips.append(
            FakeClip("bass", 100.0, 108.0, warping=True, warp_mode=0)
        )
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.set_warp_mode", self.args())
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")

    def test_restore_missing_clip_is_reported(self):
        result = self.adapter.call("clips.set_warp_mode", {
            "restore": [{
                "track_index": 1, "location": "arrangement", "start": 999.0, "mode": 4,
            }],
            "dry_run": False,
        })
        self.assertEqual(result["restored"], 0)
        self.assertEqual(result["missing"][0]["start"], 999.0)

    def test_restore_rejects_a_selection(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.set_warp_mode", {
                "restore": [{"track_index": 1, "location": "arrangement", "mode": 4}],
                "clip": "bass",
            })
        self.assertEqual(ctx.exception.code, "BAD_ARGS")


if __name__ == "__main__":
    unittest.main()

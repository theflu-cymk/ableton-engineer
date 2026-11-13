import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeClip, FakeWarpMarker, build_song

from Enableton.errors import ScriptError


class ClipWarpingTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.track = self.song.tracks[1]  # Bass layer, audio clips
        self.clip = self.track.arrangement_clips[0]
        self.clip.warping = True
        self.adapter = FakeAdapter(self.song)

    def args(self, **overrides):
        base = {
            "track": "Bass layer", "clip": "bass", "location": "arrangement",
            "enabled": False,
        }
        base.update(overrides)
        return base

    def test_dry_run_leaves_warping_unchanged(self):
        result = self.adapter.call("clips.set_warping", self.args(dry_run=True))
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["from"])
        self.assertFalse(result["to"])
        self.assertTrue(self.clip.warping)

    def test_apply_and_restore_are_exact(self):
        applied = self.adapter.call("clips.set_warping", self.args(dry_run=False))
        self.assertFalse(self.clip.warping)
        self.assertTrue(applied["from"])
        self.assertFalse(applied["to"])
        self.assertEqual(len(applied["undo"]), 1)

        restored = self.adapter.call("clips.set_warping", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertTrue(self.clip.warping)

    def test_warp_can_be_turned_back_on(self):
        self.clip.warping = False
        applied = self.adapter.call("clips.set_warping", self.args(enabled=True, dry_run=False))
        self.assertTrue(self.clip.warping)
        self.assertFalse(applied["from"])
        self.assertTrue(applied["to"])
        restored = self.adapter.call("clips.set_warping", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertFalse(self.clip.warping)

    def test_session_slot_resolves_a_session_clip(self):
        session = self.track.clip_slots[1].clip
        session.warping = True
        applied = self.adapter.call("clips.set_warping", {
            "track": "Bass layer", "clip": "bass drop", "location": "session", "slot": 1,
            "enabled": False, "dry_run": False,
        })
        self.assertFalse(session.warping)
        self.assertEqual(applied["location"], "session")
        restored = self.adapter.call("clips.set_warping", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertTrue(session.warping)

    def test_midi_clips_are_unavailable_with_a_reason(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.set_warping", {
                "track": "Drums", "clip": "drums 1", "enabled": False,
            })
        self.assertEqual(ctx.exception.code, "UNSUPPORTED")
        self.assertIn("MIDI clips", ctx.exception.message)

    def test_enabled_must_be_boolean(self):
        for value in (1, "yes", None):
            with self.assertRaises(ScriptError, msg=repr(value)) as ctx:
                self.adapter.call("clips.set_warping", self.args(enabled=value))
            self.assertEqual(ctx.exception.code, "BAD_ARGS", value)
        args = self.args()
        args.pop("enabled")
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.set_warping", args)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_duplicate_clip_names_are_refused(self):
        self.track.arrangement_clips.append(
            FakeClip("bass", 100.0, 108.0, warping=True)
        )
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.set_warping", self.args())
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")

    def test_restore_missing_clip_is_reported(self):
        result = self.adapter.call("clips.set_warping", {
            "restore": [{
                "track_index": 1, "location": "arrangement", "start": 999.0, "warping": True,
            }],
            "dry_run": False,
        })
        self.assertEqual(result["restored"], 0)
        self.assertEqual(result["missing"][0]["start"], 999.0)

    def test_restore_rejects_a_selection(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.set_warping", {
                "restore": [{"track_index": 1, "location": "arrangement", "warping": True}],
                "clip": "bass",
            })
        self.assertEqual(ctx.exception.code, "BAD_ARGS")


class WarpMapTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.track = self.song.tracks[1]
        self.clip = self.track.arrangement_clips[0]
        self.clip.warping = True
        self.clip.file_path = r"C:\audio\vocal.wav"
        self.clip.start_marker = 0.0
        self.clip.end_marker = 4.0
        self.clip.sample_length = 48000 * 4
        self.clip.sample_rate = 48000
        self.clip.warp_markers = [
            FakeWarpMarker(0.0, 0.0),
            FakeWarpMarker(1.0, 1.0),
            FakeWarpMarker(2.0, 2.0),
            FakeWarpMarker(4.0, 4.0),
        ]
        self.adapter = FakeAdapter(self.song)

    def select(self):
        return {"track": "Bass layer", "clip": "bass", "location": "arrangement"}

    def test_map_reads_source_bounds_and_seconds(self):
        result = self.adapter.call("clips.warp_map", self.select())
        self.assertEqual(result["file_path"], r"C:\audio\vocal.wav")
        self.assertEqual(result["start_marker"], 0.0)
        self.assertEqual(result["end_marker"], 4.0)
        self.assertEqual(result["markers"][1]["sample_time"], 1.0)

    def test_apply_replaces_markers_and_bounds_then_restores(self):
        args = self.select()
        args.update({
            "markers": [
                {"beat_time": 1.0, "sample_time": 0.8},
                {"beat_time": 2.0, "sample_time": 1.6},
                {"beat_time": 3.0, "sample_time": 2.4},
            ],
            "start_marker": 0.5,
            "end_marker": 3.5,
            "replace": True,
            "dry_run": False,
        })
        applied = self.adapter.call("clips.apply_warp_map", args)
        self.assertEqual(applied["marker_count"], 5)
        self.assertEqual(applied["start_marker"], 0.5)
        self.assertEqual(applied["end_marker"], 3.5)
        self.assertEqual([round(row.beat_time, 3) for row in self.clip.warp_markers],
                         [0.0, 1.0, 2.0, 3.0, 4.0])

        restored = self.adapter.call("clips.apply_warp_map", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.clip.start_marker, 0.0)
        self.assertEqual(self.clip.end_marker, 4.0)
        self.assertEqual([round(row.beat_time, 3) for row in self.clip.warp_markers],
                         [0.0, 1.0, 2.0, 4.0])

    def test_dry_run_does_not_change_the_clip(self):
        result = self.adapter.call("clips.apply_warp_map", {
            **self.select(),
            "markers": [{"beat_time": 1.0, "sample_time": 0.8}],
            "start_marker": 0.5,
            "end_marker": 3.5,
        })
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.clip.start_marker, 0.0)
        self.assertEqual([round(row.beat_time, 3) for row in self.clip.warp_markers],
                         [0.0, 1.0, 2.0, 4.0])


if __name__ == "__main__":
    unittest.main()

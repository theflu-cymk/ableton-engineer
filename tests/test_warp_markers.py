"""Warp-marker writes: dry run, grid snap, restore and the large-move guard."""

import unittest

import support  # noqa: F401
from Enableton.errors import ScriptError
from enableton.live.fake import FakeAdapter, FakeClip, FakeTrack, FakeWarpMarker, build_song


class WarpMarkerWriteTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.track = self.song.tracks[1]  # Bass layer, audio clips
        self.clip = self.track.arrangement_clips[0]
        self.clip.warping = True
        self.clip.warp_markers = [
            FakeWarpMarker(0.0, 0.0),
            FakeWarpMarker(1.1, 1.1),
            FakeWarpMarker(2.0, 2.0),
            FakeWarpMarker(3.0, 3.0),
        ]
        self.adapter = FakeAdapter(self.song)

    def beats(self):
        return [round(marker.beat_time, 6) for marker in self.clip.warp_markers]

    def test_dry_run_names_the_move_and_leaves_markers_alone(self):
        result = self.adapter.call(
            "clips.align_warp_markers",
            {"track": "Bass layer", "grid": 0.25, "dry_run": True},
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["clips"], 1)
        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["changes"][0]["marker"], 1.1)
        self.assertEqual(result["changes"][0]["to"], 1.0)
        self.assertEqual(self.beats(), [0.0, 1.1, 2.0, 3.0])

    def test_apply_and_restore_are_exact(self):
        applied = self.adapter.call(
            "clips.align_warp_markers",
            {"track": "Bass layer", "grid": 0.25, "dry_run": False},
        )
        self.assertEqual(self.beats(), [0.0, 1.0, 2.0, 3.0])
        self.assertEqual(applied["moved"], 1)

        restored = self.adapter.call(
            "clips.align_warp_markers",
            {"restore": applied["undo"], "dry_run": False},
        )
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.beats(), [0.0, 1.1, 2.0, 3.0])

    def test_first_and_hidden_last_markers_are_not_moved(self):
        self.clip.warp_markers = [
            FakeWarpMarker(0.1, 0.0),
            FakeWarpMarker(1.1, 1.1),
            FakeWarpMarker(3.1, 3.1),
        ]
        result = self.adapter.call(
            "clips.align_warp_markers",
            {"track": "Bass layer", "grid": 0.25, "dry_run": True},
        )
        self.assertEqual([row["marker"] for row in result["changes"]], [1.1])

    def test_a_move_larger_than_max_shift_is_reported_not_applied(self):
        result = self.adapter.call(
            "clips.align_warp_markers",
            {"track": "Bass layer", "grid": 0.25, "max_shift": 0.01, "dry_run": False},
        )
        self.assertEqual(result["moved"], 0)
        self.assertTrue(any("max_shift" in row["reason"] for row in result["skipped"]))
        self.assertEqual(self.beats(), [0.0, 1.1, 2.0, 3.0])

    def test_unwarped_audio_is_skipped(self):
        self.clip.warping = False
        result = self.adapter.call(
            "clips.align_warp_markers",
            {"track": "Bass layer", "grid": 0.25, "dry_run": False},
        )
        self.assertEqual(result["moved"], 0)
        self.assertIn("skipped", result)


class WarpMatchTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.reference = FakeTrack(
            "Drum bus",
            arrangement_clips=[FakeClip(
                "drum loop", 0.0, 8.0, warping=True,
                warp_markers=[
                    FakeWarpMarker(0.0), FakeWarpMarker(1.0),
                    FakeWarpMarker(2.0), FakeWarpMarker(4.0),
                ],
            )],
        )
        self.layer = FakeTrack(
            "Bass layer",
            arrangement_clips=[FakeClip(
                "bass", 0.0, 8.0, warping=True,
                warp_markers=[
                    FakeWarpMarker(0.0), FakeWarpMarker(1.12),
                    FakeWarpMarker(2.0), FakeWarpMarker(4.0),
                ],
            )],
        )
        self.song.tracks = [self.reference, self.layer]
        self.adapter = FakeAdapter(self.song)

    def marker_beats(self):
        clip = self.layer.arrangement_clips[0]
        return [round(marker.beat_time, 6) for marker in clip.warp_markers]

    def test_auto_reference_is_the_drum_track_and_dry_run_does_not_write(self):
        result = self.adapter.call("clips.warp_match", {"dry_run": True})
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["reference"]["track"], "Drum bus")
        self.assertEqual(result["reference"]["source"], "auto")
        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["changes"][0]["marker"], 1.12)
        self.assertEqual(result["changes"][0]["to"], 1.0)
        self.assertEqual(self.marker_beats(), [0.0, 1.12, 2.0, 4.0])

    def test_apply_then_restore_is_exact(self):
        applied = self.adapter.call("clips.warp_match", {"dry_run": False})
        self.assertEqual(self.marker_beats(), [0.0, 1.0, 2.0, 4.0])
        restored = self.adapter.call(
            "clips.warp_match", {"restore": applied["undo"], "dry_run": False}
        )
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.marker_beats(), [0.0, 1.12, 2.0, 4.0])

    def test_named_reference_compares_clips_in_arrangement_beats(self):
        clip = self.layer.arrangement_clips[0]
        clip.start_time = 32.0
        clip.end_time = 40.0
        self.reference.arrangement_clips.append(FakeClip(
            "drum loop late", 32.0, 40.0, warping=True,
            warp_markers=[FakeWarpMarker(0.0), FakeWarpMarker(1.0)],
        ))
        result = self.adapter.call(
            "clips.warp_match", {"reference_track": "Drum bus", "dry_run": True}
        )
        self.assertEqual(result["reference"]["source"], "named")
        self.assertEqual(result["changes"][0]["marker"], 1.12)
        self.assertEqual(result["changes"][0]["reference"], 33.0)

    def test_no_readable_reference_is_a_precondition_failure(self):
        for track in self.song.tracks:
            for clip in track.arrangement_clips:
                clip.warp_markers = []
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.warp_match", {"dry_run": True})
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertIn("transient", ctx.exception.message)

    def test_a_move_that_would_cross_an_adjacent_marker_is_reported(self):
        self.layer.arrangement_clips[0].warp_markers = [
            FakeWarpMarker(0.0), FakeWarpMarker(1.0),
            FakeWarpMarker(1.9), FakeWarpMarker(2.0),
        ]
        self.reference.arrangement_clips[0].warp_markers = [
            FakeWarpMarker(0.0), FakeWarpMarker(1.0),
            FakeWarpMarker(2.05, 2.05), FakeWarpMarker(4.0),
        ]
        result = self.adapter.call("clips.warp_match", {"dry_run": True})
        self.assertEqual(result["moved"], 0)
        self.assertTrue(any("cross" in row["reason"] for row in result["skipped"]))


if __name__ == "__main__":
    unittest.main()

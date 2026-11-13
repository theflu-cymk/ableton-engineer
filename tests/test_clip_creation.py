"""Creation primitives used to build an empty Set from measured source files."""

import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, build_song


class CreationTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.adapter = FakeAdapter(self.song)

    def test_create_audio_dry_run_does_not_touch_the_set(self):
        before = len(self.song.tracks[2].arrangement_clips)
        result = self.adapter.call("clips.create_audio", {
            "track": "Vocal chop",
            "file_path": r"C:\samples\kick.wav",
            "start_beat": 16.0,
        })
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(self.song.tracks[2].arrangement_clips), before)

    def test_create_audio_names_and_warps_the_new_clip_then_restores(self):
        result = self.adapter.call("clips.create_audio", {
            "track": "Vocal chop",
            "file_path": r"C:\samples\kick.wav",
            "start_beat": 16.0,
            "name": "KICK",
            "warping": True,
            "looping": False,
            "dry_run": False,
        })
        self.assertEqual(result["clip"], "KICK")
        self.assertEqual(result["start"], 16.0)
        clip = self.song.tracks[2].arrangement_clips[0]
        self.assertTrue(clip.warping)
        self.assertFalse(clip.looping)

        restored = self.adapter.call("clips.create_audio", {
            "restore": result["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.song.tracks[2].arrangement_clips, [])

    def test_create_midi_names_then_restores_the_new_clip(self):
        result = self.adapter.call("clips.create_midi", {
            "track": "Drums",
            "start_beat": 16.0,
            "length_beats": 8.0,
            "name": "BASS",
            "dry_run": False,
        })
        self.assertEqual(result["clip"], "BASS")
        self.assertEqual(result["start"], 16.0)
        self.assertEqual(result["length"], 8.0)
        self.assertEqual(len(self.song.tracks[0].arrangement_clips), 3)

        restored = self.adapter.call("clips.create_midi", {
            "restore": result["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(len(self.song.tracks[0].arrangement_clips), 2)

    def test_tracks_create_appends_and_configures_an_audio_track(self):
        result = self.adapter.call("tracks.create", {
            "kind": "audio", "name": "DRUMS", "color": 0x00AA33, "index": 3,
            "dry_run": False,
        })
        self.assertEqual(result["index"], 3)
        self.assertEqual(result["tracks"], 4)
        self.assertEqual(self.song.tracks[3].name, "DRUMS")
        self.assertFalse(self.song.tracks[3].is_midi)


if __name__ == "__main__":
    unittest.main()

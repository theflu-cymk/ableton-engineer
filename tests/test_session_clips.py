"""Session layer parity: launch state, Session creation, delete, handoff and view switching."""

import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, build_song
from enableton.tools import run_tool

from Enableton.errors import ScriptError


class SessionClipTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.adapter = FakeAdapter(self.song)

    def test_fire_and_stop_change_launch_state(self):
        slot = self.song.tracks[0].clip_slots[0]
        fired = self.adapter.call("clips.fire", {"track": "Drums", "slot": 0})
        self.assertTrue(fired["fired"])
        self.assertEqual(fired["clip"], "drums A")
        self.assertTrue(slot.clip.is_playing)

        stopped = self.adapter.call("clips.stop", {"track": "Drums", "slot": 0})
        self.assertTrue(stopped["stopped"])
        self.assertFalse(slot.clip.is_playing)

    def test_launch_acknowledgements_do_not_expose_a_quantized_readback(self):
        fired = run_tool("clips_fire", {"track": "Drums", "slot": 0}, self.adapter)
        self.assertTrue(fired["fired"])
        self.assertNotIn("is_playing", fired)

        stopped = run_tool("clips_stop", {"track": "Drums", "slot": 0}, self.adapter)
        self.assertTrue(stopped["stopped"])
        self.assertNotIn("is_playing", stopped)

    def test_fire_refuses_an_empty_slot(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.fire", {"track": "Drums", "slot": 1})
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")

    def test_session_delete_needs_confirmation_and_removes_the_clip(self):
        slot = self.song.tracks[0].clip_slots[0]
        preview = self.adapter.call(
            "clips.delete", {"track": "Drums", "location": "session", "slot": 0}
        )
        self.assertEqual(preview["count"], 1)
        self.assertIsNotNone(slot.clip)

        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.delete", {
                "track": "Drums", "location": "session", "slot": 0, "dry_run": False,
            })
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertIsNotNone(slot.clip)

        applied = self.adapter.call("clips.delete", {
            "track": "Drums", "location": "session", "slot": 0,
            "dry_run": False, "confirm": True,
        })
        self.assertEqual(applied["count"], 1)
        self.assertFalse(applied["reversible"])
        self.assertIsNone(slot.clip)

    def test_arrangement_delete_by_name_then_start(self):
        applied = self.adapter.call("clips.delete", {
            "track": "Drums", "location": "arrangement", "clip": "drums 1",
            "start": 0, "dry_run": False, "confirm": True,
        })
        self.assertEqual(applied["deleted"][0]["clip"], "drums 1")
        self.assertEqual(
            [clip.name for clip in self.song.tracks[0].arrangement_clips],
            ["drums 2"],
        )

    def test_duplicate_session_clip_to_arrangement_and_restore(self):
        applied = self.adapter.call("clips.duplicate_to_arrangement", {
            "track": "Drums", "slot": 0, "to_bar": 2, "name": "drums A arrangement",
            "dry_run": False,
        })
        self.assertEqual(applied["changes"][0]["to_start"], 4.0)
        clips = self.song.tracks[0].arrangement_clips
        created = [clip for clip in clips if clip.name == "drums A arrangement"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].length, 8.0)

        restored = self.adapter.call("clips.duplicate_to_arrangement", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(
            [clip.name for clip in self.song.tracks[0].arrangement_clips],
            ["drums 1", "drums 2"],
        )

    def test_duplicate_refuses_an_occupied_arrangement_start(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.duplicate_to_arrangement", {
                "track": "Drums", "slot": 0, "to_bar": 1,
            })
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")

    def test_create_session_midi_then_restore(self):
        applied = self.adapter.call("clips.create_session_midi", {
            "track": "Drums", "slot": 1, "length_beats": 8, "name": "new loop",
            "dry_run": False,
        })
        self.assertEqual(applied["clip"], "new loop")
        slot = self.song.tracks[0].clip_slots[1]
        self.assertEqual(slot.clip.name, "new loop")
        self.assertEqual(slot.clip.length, 8.0)

        restored = self.adapter.call("clips.create_session_midi", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertIsNone(slot.clip)

    def test_create_session_audio_then_restore(self):
        applied = self.adapter.call("clips.create_session_audio", {
            "track": "Vocal chop", "slot": 0, "file_path": r"C:\samples\vox.wav",
            "name": "vox loop", "warping": True, "looping": False, "dry_run": False,
        })
        self.assertEqual(applied["clip"], "vox loop")
        slot = self.song.tracks[2].clip_slots[0]
        self.assertEqual(slot.clip.name, "vox loop")
        self.assertTrue(slot.clip.warping)
        self.assertFalse(slot.clip.looping)

        restored = self.adapter.call("clips.create_session_audio", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertIsNone(slot.clip)

    def test_switch_view(self):
        result = run_tool(
            "transport_switch_view", {"view": "arrangement"}, self.adapter
        )
        self.assertEqual(result["view"], "arrangement")
        self.assertEqual(self.song.view.current, "Arranger")

        result = run_tool("transport_switch_view", {"view": "session"}, self.adapter)
        self.assertEqual(result["view"], "session")
        self.assertEqual(self.song.view.current, "Session")

    def test_track_inspect_returns_the_full_track_row(self):
        result = run_tool("tracks_inspect", {"track": "Bass layer"}, self.adapter)
        self.assertEqual(result["track"]["name"], "Bass layer")
        self.assertEqual(len(result["track"]["session"]), 3)
        self.assertEqual(result["counts"]["tracks"], 3)


if __name__ == "__main__":
    unittest.main()

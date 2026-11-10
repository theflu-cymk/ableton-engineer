"""notes_read: one clip's notes, paging, and honest unavailable answers."""

import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeClip, build_song

from Enableton.errors import ScriptError


class UnreadableClip:
    """A MIDI clip whose note vectors both fail, to prove zero and unreadable differ."""

    name = "broken notes"
    start_time = 0.0
    end_time = 4.0
    is_midi_clip = True

    def get_all_notes_extended(self):
        raise RuntimeError("extended failed")

    @property
    def notes(self):
        raise RuntimeError("legacy failed")


class NotesReadTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.adapter = FakeAdapter(self.song)

    def read(self, **args):
        return self.adapter.call("notes.read", args)

    def test_reads_session_notes_in_time_order_with_the_source(self):
        result = self.read(track="Drums", clip="drums A", location="session", slot=0)

        self.assertTrue(result["notes_available"])
        self.assertEqual(result["source"], "notes")
        self.assertEqual(result["location"], "session")
        self.assertEqual(result["slot"], 0)
        self.assertIsNone(result["start"])
        self.assertEqual(result["total"], 3)
        self.assertEqual([note["pitch"] for note in result["notes"]], [36, 38, 36])
        self.assertEqual(result["notes"][0], {
            "pitch": 36, "start": 0.0, "duration": 1.0, "velocity": 110, "mute": False,
        })
        self.assertIsNone(result["next_offset"])

    def test_paging_is_stable_and_reports_the_next_offset(self):
        first = self.read(track="Drums", clip="drums A", location="session", slot=0, limit=2)
        self.assertEqual(len(first["notes"]), 2)
        self.assertEqual(first["next_offset"], 2)

        second = self.read(
            track="Drums", clip="drums A", location="session", slot=0, offset=2, limit=2
        )
        self.assertEqual(len(second["notes"]), 1)
        self.assertEqual(second["notes"][0]["pitch"], 36)
        self.assertIsNone(second["next_offset"])

    def test_an_empty_midi_clip_is_readable_and_zero(self):
        result = self.read(track="Drums", clip="drums 1")
        self.assertTrue(result["notes_available"])
        self.assertEqual(result["source"], "notes")
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["notes"], [])
        self.assertEqual(result["location"], "arrangement")
        self.assertEqual(result["start"], 0.0)

    def test_a_non_midi_clip_is_unavailable_with_a_reason(self):
        result = self.read(track="Bass layer", clip="bass")
        self.assertFalse(result["notes_available"])
        self.assertEqual(result["reason"], "clip is not a MIDI clip")
        self.assertEqual(result["notes"], [])
        self.assertEqual(result["total"], 0)

    def test_an_unreadable_note_vector_is_unavailable_not_zero(self):
        self.song.tracks[0].arrangement_clips.append(UnreadableClip())
        result = self.read(track="Drums", clip="broken notes")
        self.assertFalse(result["notes_available"])
        self.assertIn("extended failed", result["reason"])
        self.assertIn("legacy failed", result["reason"])
        self.assertEqual(result["notes"], [])

    def test_duplicate_clip_names_are_refused(self):
        self.song.tracks[0].arrangement_clips.append(FakeClip("drums 1", 100.0, 116.0, True))
        with self.assertRaises(ScriptError) as ctx:
            self.read(track="Drums", clip="drums 1")
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")

    def test_unknown_clip_and_bad_arguments_are_typed(self):
        with self.assertRaises(ScriptError) as ctx:
            self.read(track="Drums", clip="missing")
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

        with self.assertRaises(ScriptError) as ctx:
            self.read(track="", clip="drums 1")
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

        with self.assertRaises(ScriptError) as ctx:
            self.read(track="Drums", clip="drums 1", limit=0)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")


if __name__ == "__main__":
    unittest.main()

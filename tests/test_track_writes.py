import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeClip, FakeSend, FakeSong, FakeTrack, build_song

from Enableton.errors import ScriptError


class TrackPanTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()

    def test_dry_run_does_not_change_a_pan(self):
        result = self.adapter.call(
            "tracks.set_pan", {"tracks": ["Drums"], "pan": 0.25, "dry_run": True}
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["changes"][0]["from"], 0.0)
        self.assertEqual(result["changes"][0]["to"], 0.25)
        self.assertEqual(self.adapter.song.tracks[0].pan, 0.0)

    def test_apply_and_restore_are_exact(self):
        result = self.adapter.call(
            "tracks.set_pan", {"tracks": ["Drums"], "pan": 0.25, "dry_run": False}
        )
        self.assertAlmostEqual(self.adapter.song.tracks[0].pan, 0.25)
        restored = self.adapter.call(
            "tracks.set_pan", {"restore": result["undo"], "dry_run": False}
        )
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.adapter.song.tracks[0].pan, 0.0)

    def test_pan_range_and_track_names_are_validated(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("tracks.set_pan", {"pan": 1.5, "dry_run": True})
        self.assertEqual(ctx.exception.code, "BAD_ARGS")
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("tracks.set_pan", {"tracks": ["Missing"], "pan": 0.0})
        self.assertEqual(ctx.exception.code, "NOT_FOUND")


class TrackSendTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.song.return_tracks = [FakeTrack("A-Reverb"), FakeTrack("B-Delay")]
        self.song.tracks[0].sends = [FakeSend(0.1), FakeSend(0.2)]
        self.adapter = FakeAdapter(self.song)

    def test_dry_run_apply_and_restore_are_exact(self):
        preview = self.adapter.call("tracks.set_sends", {
            "track": "Drums", "sends": {"A-Reverb": 0.35}, "dry_run": True,
        })
        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["changes"][0]["from"], 0.1)
        self.assertEqual(preview["changes"][0]["to"], 0.35)
        self.assertEqual(self.song.tracks[0].sends[0].value, 0.1)

        applied = self.adapter.call("tracks.set_sends", {
            "track": "Drums", "sends": {"A-Reverb": 0.35}, "dry_run": False,
        })
        self.assertAlmostEqual(self.song.tracks[0].sends[0].value, 0.35)
        self.assertEqual(applied["undo"][0]["send"], "A-Reverb")

        restored = self.adapter.call("tracks.set_sends", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.song.tracks[0].sends[0].value, 0.1)
        self.assertEqual(self.song.tracks[0].sends[1].value, 0.2)

    def test_track_list_exposes_colour_and_sends(self):
        self.song.tracks[0].color = 0x8BC0FF
        page = self.adapter.call("track.list", {})
        drums = [item for item in page["items"] if item["name"] == "Drums"][0]
        self.assertEqual(drums["color"], 0x8BC0FF)
        self.assertEqual(drums["sends"], {"A-Reverb": 0.1, "B-Delay": 0.2})

    def test_unknown_send_duplicate_return_and_range_are_typed(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("tracks.set_sends", {
                "track": "Drums", "sends": {"C-Chorus": 0.2},
            })
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("tracks.set_sends", {
                "track": "Drums", "sends": {"A-Reverb": 1.5},
            })
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

        self.song.return_tracks.append(FakeTrack("A-Reverb"))
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("tracks.set_sends", {
                "track": "Drums", "sends": {"A-Reverb": 0.2},
            })
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")


class TrackNameColorTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.adapter = FakeAdapter(self.song)

    def test_dry_run_leaves_name_and_colour_unchanged(self):
        result = self.adapter.call("tracks.name_and_color", {
            "track": "Drums", "name": "GATE DRUMS", "color": 0xFF0000,
            "dry_run": True,
        })
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.song.tracks[0].name, "Drums")
        self.assertEqual(self.song.tracks[0].color, 0)

    def test_apply_and_restore_are_exact(self):
        self.song.tracks[0].color = 0x8BC0FF
        applied = self.adapter.call("tracks.name_and_color", {
            "track": "Drums", "name": "GATE DRUMS", "color": 0xFF0000,
            "dry_run": False,
        })
        self.assertEqual(self.song.tracks[0].name, "GATE DRUMS")
        self.assertEqual(self.song.tracks[0].color, 0xFF0000)
        self.assertEqual(len(applied["undo"]), 1)

        restored = self.adapter.call("tracks.name_and_color", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.song.tracks[0].name, "Drums")
        self.assertEqual(self.song.tracks[0].color, 0x8BC0FF)

    def test_track_index_resolves_a_duplicate_name(self):
        self.song.tracks[1].name = "Drums"
        applied = self.adapter.call("tracks.name_and_color", {
            "track_index": 1, "name": "Bass layer", "dry_run": False,
        })
        self.assertEqual(self.song.tracks[0].name, "Drums")
        self.assertEqual(self.song.tracks[1].name, "Bass layer")
        restored = self.adapter.call("tracks.name_and_color", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.song.tracks[0].name, "Drums")
        self.assertEqual(self.song.tracks[1].name, "Drums")

    def test_name_and_colour_are_validated(self):
        for args, code in (
            ({"track": "Drums"}, "BAD_ARGS"),
            ({"track": "Drums", "track_index": 0, "name": "x"}, "BAD_ARGS"),
            ({"track": "Drums", "name": ""}, "BAD_ARGS"),
            ({"track": "Drums", "color": 16777216}, "BAD_ARGS"),
            ({"track": "Drums", "color": -1}, "BAD_ARGS"),
            ({"track": "Missing", "name": "x"}, "NOT_FOUND"),
            ({"track_index": 99, "name": "x"}, "NOT_FOUND"),
        ):
            with self.assertRaises(ScriptError, msg=repr(args)) as ctx:
                self.adapter.call("tracks.name_and_color", args)
            self.assertEqual(ctx.exception.code, code, args)


class ClipRenameTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.adapter = FakeAdapter(self.song)

    def test_dry_run_leaves_an_arrangement_clip_unchanged(self):
        result = self.adapter.call(
            "clips.rename",
            {"track": "Drums", "clip": "drums 1", "name": "intro", "dry_run": True},
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["changes"][0]["from"], "drums 1")
        self.assertEqual(self.song.tracks[0].arrangement_clips[0].name, "drums 1")

    def test_apply_rename_and_restore_the_arrangement_clip(self):
        result = self.adapter.call(
            "clips.rename",
            {"track": "Drums", "clip": "drums 1", "name": "intro", "dry_run": False},
        )
        self.assertEqual(self.song.tracks[0].arrangement_clips[0].name, "intro")
        restored = self.adapter.call(
            "clips.rename", {"restore": result["undo"], "dry_run": False}
        )
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.song.tracks[0].arrangement_clips[0].name, "drums 1")

    def test_session_slot_resolves_a_session_clip(self):
        result = self.adapter.call(
            "clips.rename",
            {
                "track": "Drums", "clip": "drums A", "name": "verse",
                "location": "session", "slot": 0, "dry_run": False,
            },
        )
        self.assertEqual(result["changes"][0]["location"], "session")
        self.assertEqual(self.song.tracks[0].clip_slots[0].clip.name, "verse")

    def test_duplicate_arrangement_names_are_refused(self):
        self.song.tracks[0].arrangement_clips.append(
            FakeClip("drums 1", 100.0, 108.0, True)
        )
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "clips.rename",
                {"track": "Drums", "clip": "drums 1", "name": "intro"},
            )
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")

    def test_unknown_clip_is_typed(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "clips.rename", {"track": "Drums", "clip": "missing", "name": "x"}
            )
        self.assertEqual(ctx.exception.code, "NOT_FOUND")


class TrackDeleteTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.adapter = FakeAdapter(self.song)

    def test_dry_run_reports_contents_and_deletes_nothing(self):
        result = self.adapter.call("tracks.delete", {"track": "Vocal chop", "dry_run": True})
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(result["contents"]["track"], "Vocal chop")
        self.assertEqual(result["contents"]["arrangement_clips"], 0)
        self.assertEqual(len(self.song.tracks), 3)

    def test_an_apply_without_confirm_is_refused_and_nothing_is_deleted(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("tracks.delete", {"track": "Vocal chop", "dry_run": False})
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertEqual(len(self.song.tracks), 3)

    def test_a_confirmed_delete_removes_only_that_track(self):
        result = self.adapter.call(
            "tracks.delete", {"track": "Bass layer", "confirm": True, "dry_run": False}
        )
        self.assertEqual(result["deleted"]["track"], "Bass layer")
        self.assertEqual([track.name for track in self.song.tracks], ["Drums", "Vocal chop"])

    def test_a_single_track_set_is_refused(self):
        adapter = FakeAdapter(FakeSong(tracks=[FakeTrack("Only")]))
        with self.assertRaises(ScriptError) as ctx:
            adapter.call("tracks.delete", {"track": "Only", "confirm": True, "dry_run": False})
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")

    def test_an_unknown_track_index_is_typed(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("tracks.delete", {"track_index": 9, "dry_run": True})
        self.assertEqual(ctx.exception.code, "NOT_FOUND")


class CleanEmptyTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.adapter = FakeAdapter(self.song)

    def test_dry_run_lists_the_empty_track_and_deletes_nothing(self):
        result = self.adapter.call("tracks.clean_empty", {"dry_run": True})
        self.assertEqual([row["track"] for row in result["empty"]], ["Vocal chop"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(self.song.tracks), 3)

    def test_an_apply_without_confirm_writes_nothing(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("tracks.clean_empty", {"dry_run": False})
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertEqual(len(self.song.tracks), 3)

    def test_a_confirmed_apply_deletes_only_the_empty_track(self):
        result = self.adapter.call("tracks.clean_empty", {"confirm": True, "dry_run": False})
        self.assertEqual(result["count"], 1)
        self.assertEqual([track.name for track in self.song.tracks], ["Drums", "Bass layer"])

    def test_naming_a_track_that_holds_clips_refuses_the_batch(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "tracks.clean_empty", {"tracks": ["Drums"], "confirm": True, "dry_run": False}
            )
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertEqual(len(self.song.tracks), 3)

    def test_a_set_of_only_empty_tracks_is_refused(self):
        adapter = FakeAdapter(FakeSong(tracks=[FakeTrack("a"), FakeTrack("b")]))
        with self.assertRaises(ScriptError) as ctx:
            adapter.call("tracks.clean_empty", {"confirm": True, "dry_run": False})
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")


if __name__ == "__main__":
    unittest.main()

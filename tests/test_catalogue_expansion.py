"""The M4 catalogue expansion: locators, clip edits, track duplication and routing.

These run against the fake LOM, which is honest about its limits: a green test here means the
handlers are internally consistent, not that Live accepts the write. The real gate for each of
these tools is a call against the loaded build on `SCRATCH fortnight`.
"""

import unittest

import support  # noqa: F401
from enableton.live.fake import (
    FakeAdapter,
    FakeLocator,
    FakeScene,
    build_song,
)
from enableton.manifest import load_manifest

from Enableton.errors import ScriptError


NEW_TOOLS = (
    "sections_create_locators",
    "sections_delete",
    "sections_scenes_from_sections",
    "clips_copy",
    "clips_transpose",
    "clips_clear",
    "tracks_duplicate",
    "tracks_set_routing",
    "mix_routing_report",
    "library_folders",
    "library_browse",
)


class CatalogueExpansionTests(unittest.TestCase):
    def test_every_new_tool_is_declared(self):
        catalogue = load_manifest()
        for name in NEW_TOOLS:
            self.assertIn(name, catalogue)

    def test_new_tools_declare_the_expected_commands(self):
        catalogue = load_manifest()
        self.assertEqual(catalogue["sections_create_locators"].cmd, "sections.create_locators")
        self.assertEqual(catalogue["clips_copy"].cmd, "clips.copy")
        self.assertEqual(catalogue["tracks_duplicate"].cmd, "tracks.duplicate")
        self.assertEqual(catalogue["mix_routing_report"].cmd, "mix.routing_report")
        self.assertEqual(catalogue["library_browse"].cmd, "library.browse")
        self.assertFalse(catalogue["mix_routing_report"].writes)
        self.assertFalse(catalogue["library_browse"].writes)


class LocatorTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()

    def test_create_dry_run_has_no_effect(self):
        preview = self.adapter.call("sections.create_locators", {
            "sections": [{"name": "intro", "bar": 1}, {"name": "drop", "bar": 5}],
        })
        self.assertTrue(preview["dry_run"])
        self.assertEqual([item["time"] for item in preview["created"]], [0.0, 16.0])
        self.assertEqual(self.adapter.song.locators, [])

    def test_create_apply_and_restore(self):
        applied = self.adapter.call("sections.create_locators", {
            "sections": [{"name": "intro", "bar": 1}, {"name": "drop", "bar": 5}],
            "dry_run": False,
        })
        self.assertEqual(
            [(locator.name, locator.time) for locator in self.adapter.song.locators],
            [("intro", 0.0), ("drop", 16.0)],
        )
        self.assertEqual(len(applied["undo"]), 2)

        self.adapter.call("sections.create_locators", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(self.adapter.song.locators, [])

    def test_create_refuses_an_occupied_beat(self):
        self.adapter.song.locators.append(FakeLocator("existing", 0.0))
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "sections.create_locators", {"sections": [{"name": "intro", "bar": 1}]}
            )
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertEqual(self.adapter.song.locators[0].name, "existing")

    def test_create_puts_the_playhead_back(self):
        self.adapter.song.current_song_time = 7.5
        self.adapter.call("sections.create_locators", {
            "sections": [{"name": "mark", "bar": 3}], "dry_run": False,
        })
        self.assertAlmostEqual(self.adapter.song.current_song_time, 7.5)

    def test_delete_by_name_and_restore(self):
        song = self.adapter.song
        song.locators = [FakeLocator("intro", 0.0), FakeLocator("drop", 16.0)]
        song.current_song_time = 4.0

        result = self.adapter.call(
            "sections.delete", {"names": ["intro"], "dry_run": False}
        )
        self.assertEqual(
            [(locator.name, locator.time) for locator in song.locators],
            [("drop", 16.0)],
        )
        self.assertAlmostEqual(song.current_song_time, 4.0)

        self.adapter.call("sections.delete", {"restore": result["undo"], "dry_run": False})
        self.assertEqual(
            [(locator.name, locator.time) for locator in song.locators],
            [("intro", 0.0), ("drop", 16.0)],
        )

    def test_delete_reports_the_same_count_in_dry_and_apply(self):
        song = self.adapter.song
        song.locators = [FakeLocator("intro", 0.0), FakeLocator("drop", 16.0)]
        preview = self.adapter.call("sections.delete", {"names": ["intro"]})
        applied = self.adapter.call(
            "sections.delete", {"names": ["intro"], "dry_run": False}
        )
        self.assertEqual(preview["deleted"], 1)
        self.assertEqual(applied["deleted"], 1)

    def test_delete_all_is_one_selector_with_others(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("sections.delete", {"all": True, "names": ["x"]})
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_scenes_from_sections_skips_existing_names(self):
        song = self.adapter.song
        song.locators = [FakeLocator("intro", 0.0), FakeLocator("drop", 16.0)]
        song.scenes = [FakeScene("intro")]

        result = self.adapter.call(
            "sections.scenes_from_sections", {"dry_run": False}
        )
        self.assertEqual([scene.name for scene in song.scenes], ["intro", "drop"])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["name"], "intro")

        self.adapter.call(
            "sections.scenes_from_sections", {"restore": result["undo"], "dry_run": False}
        )
        self.assertEqual([scene.name for scene in song.scenes], ["intro"])


class LocatorMoveTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.song = self.adapter.song
        self.song.locators = [FakeLocator("intro", 0.0), FakeLocator("drop", 16.0)]

    def test_dry_run_lists_the_move_and_changes_nothing(self):
        preview = self.adapter.call("sections.move", {"name": "intro", "to_bar": 9})
        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["moved"]["to_bar"], 9.0)
        self.assertEqual(
            [(locator.name, locator.time) for locator in self.song.locators],
            [("intro", 0.0), ("drop", 16.0)],
        )

    def test_apply_moves_the_marker_keeps_its_name_and_restores(self):
        self.song.current_song_time = 7.5
        applied = self.adapter.call(
            "sections.move", {"name": "intro", "to_bar": 9, "dry_run": False}
        )
        self.assertEqual(
            [(locator.name, locator.time) for locator in self.song.locators],
            [("drop", 16.0), ("intro", 32.0)],
        )
        self.assertEqual(len(applied["undo"]), 1)
        self.assertAlmostEqual(self.song.current_song_time, 7.5)

        self.adapter.call("sections.move", {"restore": applied["undo"], "dry_run": False})
        self.assertEqual(
            [(locator.name, locator.time) for locator in self.song.locators],
            [("intro", 0.0), ("drop", 16.0)],
        )

    def test_occupied_destination_is_refused(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "sections.move", {"bar": 1, "to_bar": 5, "dry_run": False}
            )
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertEqual(len(self.song.locators), 2)

    def test_duplicate_name_is_ambiguous(self):
        self.song.locators.append(FakeLocator("intro", 32.0))
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("sections.move", {"name": "intro", "to_bar": 9})
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")


class TrackExpansionTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()

    def test_duplicate_preview_names_the_new_indices(self):
        preview = self.adapter.call("tracks.duplicate", {"track": "Drums", "count": 2})
        self.assertEqual([item["track_index"] for item in preview["created"]], [1, 2])
        self.assertEqual(len(self.adapter.song.tracks), 3)

    def test_duplicate_apply_and_restore(self):
        song = self.adapter.song
        before = [track.name for track in song.tracks]
        applied = self.adapter.call(
            "tracks.duplicate", {"track": "Drums", "count": 2, "dry_run": False}
        )
        self.assertEqual(
            [track.name for track in song.tracks][:3], ["Drums", "Drums", "Drums"]
        )
        self.adapter.call(
            "tracks.duplicate", {"restore": applied["undo"], "dry_run": False}
        )
        self.assertEqual([track.name for track in song.tracks], before)

    def test_set_routing_changes_and_restores(self):
        applied = self.adapter.call("tracks.set_routing", {
            "track": "Bass layer", "output_type": "Sends Only", "dry_run": False,
        })
        self.assertEqual(
            self.adapter.song.tracks[1].output_routing_type.display_name, "Sends Only"
        )
        self.assertEqual(applied["changes"][0]["from"], "Master")

        self.adapter.call(
            "tracks.set_routing", {"restore": applied["undo"], "dry_run": False}
        )
        self.assertEqual(
            self.adapter.song.tracks[1].output_routing_type.display_name, "Master"
        )

    def test_unknown_routing_name_lists_the_options(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "tracks.set_routing", {"track": "Drums", "output_type": "Nowhere"}
            )
        self.assertEqual(ctx.exception.code, "NOT_FOUND")
        self.assertIn("Master", str(ctx.exception))


class ClipEditTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()

    def test_copy_session_clip_and_restore(self):
        drums = self.adapter.song.tracks[0]
        applied = self.adapter.call("clips.copy", {
            "track": "Drums", "clip": "drums A", "location": "session", "slot": 0,
            "to_slot": 1, "dry_run": False,
        })
        self.assertEqual(drums.clip_slots[1].clip.name, "drums A")
        self.assertEqual(drums.clip_slots[1].clip.notes[0].pitch, 36)

        self.adapter.call("clips.copy", {"restore": applied["undo"], "dry_run": False})
        self.assertIsNone(drums.clip_slots[1].clip)

    def test_copy_refuses_an_occupied_slot(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.copy", {
                "track": "Bass layer", "clip": "bass drop", "location": "session",
                "slot": 1, "to_slot": 1,
            })
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")

    def test_copy_arrangement_clip_and_restore(self):
        drums = self.adapter.song.tracks[0]
        applied = self.adapter.call("clips.copy", {
            "track": "Drums", "clip": "drums 1", "to_bar": 13, "dry_run": False,
        })
        starts = sorted(float(clip.start_time) for clip in drums.arrangement_clips)
        self.assertEqual(starts, [0.0, 32.0, 48.0])

        self.adapter.call("clips.copy", {"restore": applied["undo"], "dry_run": False})
        starts = sorted(float(clip.start_time) for clip in drums.arrangement_clips)
        self.assertEqual(starts, [0.0, 32.0])

    def test_transpose_midi_and_restore(self):
        clip = self.adapter.song.tracks[0].clip_slots[0].clip
        before = sorted(note.pitch for note in clip.notes)
        applied = self.adapter.call("clips.transpose", {
            "track": "Drums", "clip": "drums A", "location": "session", "slot": 0,
            "semitones": 12, "dry_run": False,
        })
        self.assertEqual(sorted(note.pitch for note in clip.notes), [p + 12 for p in before])

        self.adapter.call("clips.transpose", {"restore": applied["undo"], "dry_run": False})
        self.assertEqual(sorted(note.pitch for note in clip.notes), before)

    def test_transpose_refuses_out_of_range_pitch(self):
        clip = self.adapter.song.tracks[0].clip_slots[0].clip
        clip.notes[0].pitch = 127
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.transpose", {
                "track": "Drums", "clip": "drums A", "location": "session", "slot": 0,
                "semitones": 4,
            })
        self.assertEqual(ctx.exception.code, "BAD_ARGS")
        self.assertEqual(clip.notes[0].pitch, 127)

    def test_clear_midi_and_restore(self):
        clip = self.adapter.song.tracks[0].clip_slots[0].clip
        before = len(clip.notes)
        applied = self.adapter.call("clips.clear", {
            "track": "Drums", "clip": "drums A", "location": "session", "slot": 0,
            "dry_run": False,
        })
        self.assertEqual(clip.notes, [])
        self.assertEqual(applied["cleared"], before)

        self.adapter.call("clips.clear", {"restore": applied["undo"], "dry_run": False})
        self.assertEqual(len(clip.notes), before)

    def test_clear_audio_is_unavailable_with_a_reason(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("clips.clear", {
                "track": "Bass layer", "clip": "bass drop", "location": "session", "slot": 1,
            })
        self.assertEqual(ctx.exception.code, "UNSUPPORTED")
        self.assertIn("audio", str(ctx.exception))


class RoutingReportTests(unittest.TestCase):
    def test_reports_display_names_and_option_counts(self):
        result = FakeAdapter().call("mix.routing_report", {})
        self.assertEqual(result["total"], len(build_song().tracks))
        row = result["items"][0]
        self.assertEqual(row["name"], "Drums")
        self.assertEqual(row["input_type"], "All Ins")
        self.assertEqual(row["input_channel"], "All Channels")
        self.assertEqual(row["output_type"], "Master")
        self.assertEqual(row["output_types"], 2)
        self.assertEqual(result["flagged"], [])

    def test_paging_is_stable(self):
        first = FakeAdapter().call("mix.routing_report", {"limit": 2})
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(first["next_offset"], 2)


class LibraryTests(unittest.TestCase):
    def test_folders_reports_missing_categories_with_reasons(self):
        result = FakeAdapter().call("library.folders", {})
        names = {row["category"] for row in result["categories"]}
        self.assertEqual(
            names,
            {"sounds", "user_library", "instruments", "audio_effects", "midi_effects"},
        )
        missing = {row["name"] for row in result["missing"]}
        self.assertIn("samples", missing)
        for row in result["missing"]:
            self.assertTrue(row["reason"])

    def test_browse_walks_by_name(self):
        result = FakeAdapter().call("library.browse", {"path": "sounds/Bass"})
        self.assertEqual(result["path"], "Sounds/Bass")
        self.assertEqual(result["children"][0]["name"], "Sub Bass.adv")
        self.assertTrue(result["children"][0]["is_loadable"])
        self.assertFalse(result["children"][0]["is_folder"])

    def test_browse_unknown_step_is_not_found(self):
        with self.assertRaises(ScriptError) as ctx:
            FakeAdapter().call("library.browse", {"path": "sounds/Nope"})
        self.assertEqual(ctx.exception.code, "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()

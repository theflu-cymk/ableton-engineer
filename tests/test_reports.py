"""Reports are pure functions of the snapshot (spec §7, §8).

These tests are about honesty as much as arithmetic: sections come from clip density because
the Set has no locators, peaks are declared unmeasured, and "unused" names only what is
observable.
"""

import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, build_song
from enableton.reports import ReportError, levels, structure, summary_from_snapshot, unused


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.data = self.adapter.call("snapshot.get", {})

    # -- the payload itself ------------------------------------------------
    def test_snapshot_carries_the_whole_shape(self):
        data = self.data
        self.assertEqual(data["song"]["tempo"], 140.0)
        self.assertEqual(data["song"]["signature"], [4, 4])
        self.assertEqual(data["counts"]["tracks"], 3)
        self.assertEqual(data["counts"]["scenes"], 3)
        self.assertEqual(data["counts"]["arrangement_clips"], 3)
        self.assertEqual(data["counts"]["session_clips"], 2)
        self.assertEqual(data["counts"]["devices"], 3)
        self.assertTrue(data["captured"]["locators_available"])

    def test_track_rows_carry_kind_group_and_session(self):
        drums = self.data["tracks"][0]
        self.assertEqual(drums["name"], "Drums")
        self.assertEqual(drums["kind"], "midi")
        self.assertEqual(drums["session"]["filled"], 1)
        self.assertEqual(drums["session"]["empty"], 2)
        self.assertEqual([d["class"] for d in drums["devices"]], ["Eq8", "GlueCompressor"])
        self.assertFalse(drums["devices"][0]["plugin"])

    def test_summary_is_compact(self):
        summary = summary_from_snapshot(self.data)
        self.assertEqual(summary["tracks"], 3)
        self.assertEqual(summary["time_signature"], [4, 4])
        self.assertNotIn("tracks_detail", summary)

    # -- structure ---------------------------------------------------------
    def test_sections_come_from_arrangement_density(self):
        report = structure(self.data, {})
        self.assertEqual(report["bars"], 16)
        self.assertEqual(report["sections"]["total"], 2, "a gap of four bars splits sections")
        first, second = report["sections"]["items"]
        self.assertEqual((first["start_bar"], first["end_bar"]), (1, 4))
        self.assertEqual((second["start_bar"], second["end_bar"]), (9, 16))

    def test_structure_says_how_many_sections_are_named(self):
        report = structure(self.data, {})
        self.assertEqual(report["signals"]["named_sections"], 0)
        self.assertEqual(report["signals"]["duplicate_track_names"], {})

    def test_structure_pages_tracks_and_sections_separately(self):
        report = structure(self.data, {"offset": 1, "limit": 1,
                                       "section_offset": 1, "section_limit": 1})
        self.assertEqual([row["name"] for row in report["tracks"]["items"]], ["Bass layer"])
        self.assertEqual(report["tracks"]["next_offset"], 2)
        self.assertEqual([s["start_bar"] for s in report["sections"]["items"]], [9])

    def test_duplicate_names_are_flags_not_assumptions(self):
        song = build_song()
        song.tracks[1].name = "Drums"
        data = FakeAdapter(song).call("snapshot.get", {})
        self.assertEqual(structure(data, {})["signals"]["duplicate_track_names"],
                         {"Drums": [0, 1]})

    # -- unused ------------------------------------------------------------
    def test_unused_names_the_empty_material(self):
        report = unused(self.data, {})
        self.assertEqual(report["tracks_without_clips"], ["Vocal chop"])
        self.assertEqual(report["tracks_without_devices"], ["Vocal chop"])
        self.assertEqual(report["scenes_without_clips"], [2])
        self.assertEqual(report["empty_session_slots"], 7)
        self.assertNotIn("never_launched", report)

    # -- levels ------------------------------------------------------------
    def test_levels_reports_faders_without_inventing_peaks(self):
        report = levels(self.data, {})
        self.assertEqual(report["total"], 3)
        drums = report["items"][0]
        self.assertAlmostEqual(drums["volume"], 0.82)
        self.assertFalse(report["peaks"]["measured"])
        self.assertIn("mix_meter_poll", report["peaks"]["note"])

    def test_levels_flags_silent_and_muted_tracks(self):
        song = build_song()
        song.tracks[2].volume = 0.0
        song.tracks[1].mute = True
        report = levels(FakeAdapter(song).call("snapshot.get", {}), {})
        self.assertEqual(report["flags"]["silent"], ["Vocal chop"])
        self.assertEqual(report["flags"]["muted"], ["Bass layer"])

    def test_levels_pages(self):
        report = levels(self.data, {"offset": 2, "limit": 5})
        self.assertEqual([row["name"] for row in report["items"]], ["Vocal chop"])
        self.assertIsNone(report["next_offset"])

    # -- argument discipline ----------------------------------------------
    def test_bad_arguments_are_rejected(self):
        for args in ({"limit": 0}, {"offset": -1}, {"bogus": 1}, {"limit": True}):
            with self.assertRaises(ReportError, msg=repr(args)):
                structure(self.data, args)
        with self.assertRaises(ReportError):
            unused(self.data, {"anything": 1})


class ToolRouterTests(unittest.TestCase):
    """A tool's output must match its description, whatever the command returns."""

    def setUp(self):
        self.adapter = FakeAdapter()

    def test_status_returns_the_compact_summary(self):
        from enableton.tools import run_tool

        result = run_tool("ableton_status", {}, self.adapter)
        self.assertEqual(result["tracks"], 3)
        self.assertEqual(result["time_signature"], [4, 4])
        self.assertNotIn("tracks_detail", result)

    def test_unknown_tool_is_a_typed_error(self):
        from enableton.protocol.codes import LiveError
        from enableton.tools import run_tool

        with self.assertRaises(LiveError) as ctx:
            run_tool("tracks_teleport", {}, self.adapter)
        self.assertEqual(ctx.exception.code, "UNKNOWN_COMMAND")

    def test_bad_report_arguments_become_bad_args(self):
        from enableton.protocol.codes import LiveError
        from enableton.tools import run_tool

        with self.assertRaises(LiveError) as ctx:
            run_tool("inspect_structure", {"limit": 0}, self.adapter)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_a_write_invalidates_the_snapshot(self):
        from enableton.state.snapshot import SnapshotCache
        from enableton.tools import run_tool

        cache = SnapshotCache(self.adapter)
        cache.get()
        epoch = cache.epoch

        run_tool("tracks_gain_stage", {"dry_run": False}, self.adapter, cache=cache)

        self.assertEqual(cache.epoch, epoch + 1)
        self.assertLess(self.adapter.song.tracks[0].volume, 0.82)

    def test_a_read_does_not_invalidate(self):
        from enableton.state.snapshot import SnapshotCache
        from enableton.tools import run_tool

        cache = SnapshotCache(self.adapter)
        cache.get()
        epoch = cache.epoch

        run_tool("inspect_unused", {}, self.adapter, cache=cache)

        self.assertEqual(cache.epoch, epoch)


if __name__ == "__main__":
    unittest.main()

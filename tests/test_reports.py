"""Reports are pure functions of the snapshot (spec §7, §8).

These tests are about honesty as much as arithmetic: sections come from clip density because
the Set has no locators, peaks are declared unmeasured, and "unused" names only what is
observable.
"""

import os
import shutil
import tempfile
import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, build_song
from enableton.reports import (
    ReportError, levels, mix_headroom, notes_overlaps, structure, summary_from_snapshot,
    unused, warp_check,
)


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

    def test_summary_passes_the_locator_count_through_and_flags_readability(self):
        data = dict(self.data)
        data["captured"] = {"locators_available": False}
        summary = summary_from_snapshot(data)
        self.assertEqual(summary["locators"], 0, "an empty read is still the reported count")
        self.assertFalse(summary["locators_available"])

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


def _clip(start, end):
    return {"name": "clip", "start": start, "end": end, "length": end - start, "midi": False}


def _warp_clip(name="clip", warping=True, warp_mode=0, warp_mode_name="beats", markers=2, **extra):
    clip = {
        "name": name,
        "start": 0.0,
        "end": 4.0,
        "length": 4.0,
        "midi": False,
        "warping": warping,
        "warp_mode": warp_mode,
        "warp_mode_name": warp_mode_name,
        "warp_markers": markers,
    }
    clip.update(extra)
    return clip


def _midi_clip(name="clip", note_count=2, overlaps=(), truncated=False, **extra):
    clip = {
        "name": name,
        "start": 0.0,
        "end": 4.0,
        "length": 4.0,
        "midi": True,
        "note_count": note_count,
        "note_overlaps": list(overlaps),
        "note_overlaps_truncated": truncated,
    }
    clip.update(extra)
    return clip


def _track(index, name=None, kind="audio", clips=(), session=0, devices=0,
           volume=0.85, volume_str="0.0 dB"):
    return {
        "index": index,
        "name": name or "track%d" % index,
        "kind": kind,
        "group": None,
        "volume": volume,
        "volume_str": volume_str,
        "pan": 0.0,
        "mute": False,
        "solo": False,
        "arm": False,
        "devices": [{"index": i, "name": "d", "class": "Eq8", "plugin": False,
                     "active": True} for i in range(devices)],
        "session": {"filled": session, "empty": 0, "clips": []},
        "arrangement": list(clips),
    }


def _snapshot(tracks):
    return {
        "song": {"name": "set", "tempo": 120.0, "signature": [4, 4],
                 "is_playing": False, "current_song_time": 0.0},
        "tracks": list(tracks),
        "scenes": [],
        "locators": [],
        "counts": {
            "tracks": len(tracks), "returns": 0, "scenes": 0, "locators": 0,
            "arrangement_clips": sum(len(t["arrangement"]) for t in tracks),
            "session_clips": sum(t["session"]["filled"] for t in tracks),
            "devices": sum(len(t["devices"]) for t in tracks),
            "empty_session_slots": 0,
        },
        "captured": {"locators_available": True},
    }


class RealShapeTests(unittest.TestCase):
    """Regressions found by reading Crust Wumble (17 tracks, 315 arrangement clips) for real.

    Every one of these passed a green suite first. The fake Set was too tidy to contain a clip
    ending mid-bar, a clip long enough for its bar incidences to outnumber clips, a fader at
    Live's 0.85 unity, or return tracks that hold no clips by design.
    """

    def test_bars_reach_the_bar_the_last_clip_ends_in(self):
        report = structure(_snapshot([_track(0, clips=[_clip(0.0, 383.99)])]), {})
        section = report["sections"]["items"][0]
        self.assertEqual(report["bars"], 96)
        self.assertEqual(section["end_bar"], 96, "bars must agree with the section printed")

    def test_section_clips_count_clips_not_bar_incidences(self):
        report = structure(_snapshot([_track(0, clips=[_clip(0.0, 16.0), _clip(16.0, 20.0)])]), {})
        section = report["sections"]["items"][0]
        self.assertEqual(section["clips"], 2)
        self.assertEqual(section["clip_spans"], 5, "4 bars plus 1 bar of incidence")
        self.assertEqual(section["clips"], report["signals"]["arrangement_clips"])

    def test_unity_flag_reads_the_display_string(self):
        data = _snapshot([
            _track(0, name="unity", volume=0.85, volume_str="0.0 dB"),
            _track(1, name="trimmed", volume=0.72, volume_str="-5.2 dB"),
        ])
        self.assertEqual(levels(data, {})["flags"]["at_unity"], ["unity"])

    def test_unity_flag_falls_back_to_the_fader_curve(self):
        data = _snapshot([_track(0, name="unity", volume=0.85, volume_str=None)])
        self.assertEqual(levels(data, {})["flags"]["at_unity"], ["unity"])

    def test_return_tracks_are_buses_not_waste(self):
        data = _snapshot([
            _track(0, name="14-Audio"),
            _track(1, name="A-Reverb", kind="return"),
            _track(2, name="B-Delay", kind="return"),
        ])
        report = unused(data, {})
        self.assertEqual(report["tracks_without_clips"], ["14-Audio"])
        self.assertEqual(report["total"], 1)

    def test_structure_surfaces_devices_inside_racks(self):
        rack = _track(0, devices=1)
        rack["devices"][0]["chains"] = [[{"name": "EQ", "class": "Eq8", "plugin": False,
                                           "active": True, "depth": 1}]]
        report = structure(_snapshot([rack]), {})
        row = report["tracks"]["items"][0]
        self.assertEqual(row["devices"], 1, "top-level stays top-level")
        self.assertEqual(row["devices_total"], 2)
        self.assertEqual(report["signals"]["devices_total"], 2)

    def test_master_chain_counts_towards_the_set_total(self):
        data = _snapshot([_track(0, devices=1)])
        data["master_track"] = {"available": True, "device_count": 6, "devices": []}
        report = structure(data, {})
        self.assertEqual(report["signals"]["devices_master"], 6)
        self.assertEqual(
            report["signals"]["devices_total"], 7,
            "Crust Wumble read 102 until the 6 master devices were added",
        )


class WarpCheckTests(unittest.TestCase):
    def test_counts_warp_state_and_modes(self):
        data = _snapshot([
            _track(0, name="drums", clips=[
                _warp_clip("a", warp_mode=4, warp_mode_name="complex", markers=3),
            ]),
            _track(1, name="bass", clips=[_warp_clip("b", warping=False, markers=2)]),
        ])
        report = warp_check(data, {})

        self.assertEqual(report["total"], 2)
        self.assertEqual(report["summary"]["audio_clips"], 2)
        self.assertEqual(report["summary"]["warping_on"], 1)
        self.assertEqual(report["summary"]["warping_off"], 1)
        self.assertEqual(report["summary"]["flagged"], 0)
        self.assertEqual(
            report["summary"]["by_flag"],
            {"markers_unreadable": 0, "no_markers": 0, "mode_unknown": 0},
        )
        self.assertEqual(report["summary"]["modes"], {"beats": 1, "complex": 1})
        self.assertEqual(report["summary"]["warp_markers"], 5)

    def test_flags_only_provable_defects(self):
        data = _snapshot([
            _track(0, clips=[
                _warp_clip("unreadable", markers=None,
                           warp_markers_reason="warp_markers: RuntimeError: nope"),
                _warp_clip("empty", markers=0),
                _warp_clip("mystery", warp_mode=6, warp_mode_name=None),
            ]),
        ])
        report = warp_check(data, {})
        rows = {row["clip"]: row for row in report["items"]}

        self.assertEqual(rows["unreadable"]["flags"], ["markers_unreadable"])
        self.assertEqual(rows["empty"]["flags"], ["no_markers"])
        self.assertEqual(rows["mystery"]["flags"], ["mode_unknown"])
        self.assertIn("RuntimeError", rows["unreadable"]["warp_markers_reason"])
        self.assertEqual(report["summary"]["flagged"], 3)
        self.assertEqual(
            report["summary"]["by_flag"],
            {"markers_unreadable": 1, "no_markers": 1, "mode_unknown": 1},
        )
        self.assertEqual(report["summary"]["unreadable"], 1)
        self.assertEqual(report["summary"]["modes"], {"beats": 2, "unknown": 1})

    def test_includes_session_clips_with_their_slot(self):
        track = _track(0, name="sessions")
        track["session"] = {"filled": 1, "empty": 0, "clips": [_warp_clip("loop", slot=3)]}
        report = warp_check(_snapshot([track]), {})
        row = report["items"][0]

        self.assertEqual((row["location"], row["slot"], row["clip"]), ("session", 3, "loop"))

    def test_pages(self):
        data = _snapshot([_track(0, clips=[_warp_clip("a"), _warp_clip("b"), _warp_clip("c")])])
        report = warp_check(data, {"offset": 1, "limit": 1})

        self.assertEqual([row["clip"] for row in report["items"]], ["b"])
        self.assertEqual(report["next_offset"], 2)
        self.assertEqual(report["total"], 3)

    def test_bad_arguments_are_rejected(self):
        data = _snapshot([])
        for args in ({"limit": 0}, {"offset": -1}, {"bogus": 1}):
            with self.assertRaises(ReportError, msg=repr(args)):
                warp_check(data, args)


class HeadroomTests(unittest.TestCase):
    def _data(self):
        return _snapshot([
            _track(0, name="hot", volume=1.0, volume_str="+3.0 dB"),
            _track(1, name="unity", volume=0.85, volume_str="0.0 dB"),
            _track(2, name="trim", volume=0.5, volume_str="-12.0 dB"),
            _track(3, name="unknown", volume=0.7, volume_str=None),
        ])

    def test_reports_fader_trim_and_refuses_to_invent_headroom(self):
        report = mix_headroom(self._data(), {})

        self.assertEqual(report["total"], 4)
        self.assertEqual(report["summary"]["faders_measured"], 3)
        self.assertEqual(report["summary"]["faders_unmeasured"], 1)
        self.assertEqual(report["summary"]["at_unity"], ["unity"])
        self.assertEqual(report["summary"]["above_unity"], ["hot"])
        self.assertEqual(report["summary"]["below_unity"], ["trim"])
        self.assertEqual(report["summary"]["fader_span_db"], {"min": -12.0, "max": 3.0})
        self.assertFalse(report["headroom"]["measured"])
        self.assertIn("mix_meter_poll", report["headroom"]["requires"])
        self.assertFalse(report["master"]["available"])
        self.assertIn("master", report["master"]["reason"].lower())

    def test_pages(self):
        report = mix_headroom(self._data(), {"offset": 1, "limit": 2})

        self.assertEqual([row["name"] for row in report["items"]], ["unity", "trim"])
        self.assertEqual(report["next_offset"], 3)
        self.assertEqual(report["total"], 4)

    def test_bad_arguments_are_rejected(self):
        data = self._data()
        for args in ({"limit": 0}, {"offset": -1}, {"bogus": 1}):
            with self.assertRaises(ReportError, msg=repr(args)):
                mix_headroom(data, args)


class NotesOverlapTests(unittest.TestCase):
    def _pair(self, pitch=60):
        return {
            "pitch": pitch,
            "first": {"start": 0.0, "duration": 1.0, "velocity": 100, "mute": False},
            "second": {"start": 0.5, "duration": 1.0, "velocity": 90, "mute": False},
            "overlap": 0.5,
        }

    def _with_notes(self, tracks):
        data = _snapshot(tracks)
        data["captured"]["notes_available"] = True
        return data

    def test_pages_pairs_and_summarises_pitch(self):
        data = self._with_notes([
            _track(0, name="drums", clips=[
                _midi_clip("loop", note_count=3, overlaps=[self._pair(), self._pair(64)]),
            ]),
        ])

        report = notes_overlaps(data, {"limit": 1})

        self.assertEqual(report["total"], 2)
        self.assertEqual(report["next_offset"], 1)
        self.assertEqual(report["summary"]["notes_read"], 3)
        self.assertEqual(report["summary"]["overlaps"], 2)
        self.assertEqual(report["summary"]["clips_with_overlaps"], 1)
        self.assertEqual(report["summary"]["by_pitch"], {"60": 1, "64": 1})
        self.assertTrue(report["summary"]["complete"])
        self.assertEqual(report["items"][0]["first"]["start"], 0.0)
        self.assertEqual(report["items"][0]["location"], "arrangement")

    def test_a_snapshot_without_note_data_is_unavailable_not_empty(self):
        report = notes_overlaps(_snapshot([
            _track(0, clips=[_midi_clip("loop")]),
        ]), {})

        self.assertEqual(report["total"], 0)
        self.assertFalse(report["summary"]["note_data_available"])
        self.assertIn("restart", report["unavailable"]["reason"])

    def test_a_clip_that_could_not_be_read_keeps_its_own_reason(self):
        data = _snapshot([_track(0, clips=[_midi_clip("loop")])])
        data["captured"]["notes_reason"] = "Drums / loop: note read failed: notes: attribute absent"

        report = notes_overlaps(data, {})

        self.assertFalse(report["summary"]["note_data_available"])
        self.assertIn("attribute absent", report["unavailable"]["reason"])
        self.assertNotIn("reinstall", report["unavailable"]["reason"])

    def test_truncation_and_unreadable_notes_make_the_result_incomplete(self):
        data = self._with_notes([
            _track(0, name="drums", clips=[
                _midi_clip("truncated", note_count=4, overlaps=[self._pair()], truncated=True),
                _midi_clip("broken", note_count=None, note_overlaps_reason="notes: RuntimeError: no"),
            ]),
        ])

        report = notes_overlaps(data, {})

        self.assertEqual(report["summary"]["truncated_clips"], 1)
        self.assertEqual(report["summary"]["unreadable_clips"], 1)
        self.assertFalse(report["summary"]["complete"])
        self.assertEqual({warning["kind"] for warning in report["warnings"]},
                         {"overlaps_truncated", "notes_unreadable"})

    def test_bad_arguments_are_rejected(self):
        data = self._with_notes([])
        for args in ({"limit": 0}, {"offset": -1}, {"bogus": 1}):
            with self.assertRaises(ReportError, msg=repr(args)):
                notes_overlaps(data, args)


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

        scratch_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, scratch_dir, True)
        set_path = os.path.join(scratch_dir, "fortnight.als")
        with open(set_path, "wb") as handle:
            handle.write(b"fake als")
        self.adapter.song.file_path = set_path

        cache = SnapshotCache(self.adapter)
        cache.get()
        epoch = cache.epoch

        result = run_tool(
            "tracks_gain_stage",
            {"dry_run": False},
            self.adapter,
            cache=cache,
            backup_root=os.path.join(scratch_dir, "backups"),
        )

        self.assertEqual(cache.epoch, epoch + 1)
        self.assertLess(self.adapter.song.tracks[0].volume, 0.82)
        self.assertTrue(os.path.isfile(result["scratch_copy"]))

    def test_mix_headroom_runs_from_the_snapshot(self):
        from enableton.tools import run_tool

        result = run_tool("mix_headroom", {}, self.adapter)

        self.assertEqual(result["summary"]["tracks"], 3)
        self.assertFalse(result["headroom"]["measured"])

    def test_warp_check_runs_from_the_snapshot(self):
        from enableton.tools import run_tool

        result = run_tool("clips_warp_check", {}, self.adapter)

        self.assertEqual(result["summary"]["audio_clips"], 2)
        self.assertEqual(result["summary"]["flagged"], 2)

    def test_notes_overlaps_runs_from_the_snapshot(self):
        from enableton.tools import run_tool

        result = run_tool("notes_overlaps", {}, self.adapter)

        self.assertEqual(result["summary"]["midi_clips"], 3)
        self.assertEqual(result["summary"]["overlaps"], 1)
        self.assertEqual(result["total"], 1)

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

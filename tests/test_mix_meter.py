"""Meter polling against the fake LOM.

A green test here means the handler samples across ticks, keeps the highest reading it saw and
reports a missing meter instead of a zero. It does not prove Live 12.2.5 returns these attributes
on this build; that gate is a real `mix_meter_poll` call on `SCRATCH fortnight`.
"""

import unittest
from unittest import mock

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeSong, FakeTrack
from enableton.manifest import load_manifest
from enableton.modes import load_modes

from Enableton import dispatch
from Enableton.errors import ScriptError
from Enableton.handlers import mix as mix_handler


class TickingSong(FakeSong):
    """A Set whose instantaneous meters keep rising between display ticks."""

    def tick(self):
        super().tick()
        for track in list(self.tracks) + list(self.return_tracks):
            track.output_meter_left = min(1.0, track.output_meter_left + 0.1)
            track.output_meter_right = min(1.0, track.output_meter_right + 0.05)


class NoMeters:
    name = "Mystery"


class LevelOnly:
    """A build that exposes the peak-hold level but not the instantaneous pair."""

    name = "Held"
    output_meter_level = 0.42


class InstantOnly:
    """A build that exposes instantaneous meters but no peak-hold level."""

    name = "Instant"
    output_meter_left = 0.5
    output_meter_right = 0.6


def make_song():
    song = FakeSong(
        tracks=[
            FakeTrack("Drums", output_meter_level=0.5, output_meter_left=0.3,
                      output_meter_right=0.4),
            FakeTrack("Bass", output_meter_level=0.2, output_meter_left=0.1,
                      output_meter_right=0.15),
        ],
        return_tracks=[
            FakeTrack("Reverb", output_meter_level=0.25, output_meter_left=0.2,
                      output_meter_right=0.2),
        ],
    )
    song.master_track = FakeTrack(
        "Master", output_meter_level=0.9, output_meter_left=0.8, output_meter_right=0.75
    )
    return song


class MeterPollTests(unittest.TestCase):
    def test_reads_tracks_returns_and_the_master(self):
        result = FakeAdapter(make_song()).call("mix.meter_poll", {"ms": 0})
        self.assertEqual(
            [item["kind"] for item in result["items"]],
            ["track", "track", "return", "master"],
        )
        self.assertEqual(
            [item["name"] for item in result["items"]],
            ["Drums", "Bass", "Reverb", "Master"],
        )
        self.assertTrue(all(item["available"] for item in result["items"]))
        self.assertEqual(result["summary"]["master_peak"], 0.8)
        self.assertAlmostEqual(result["summary"]["master_headroom_db"], 1.94, places=2)
        self.assertEqual(result["summary"]["at_or_over_0db"], [])
        self.assertEqual(result["samples"], 2)  # always at least two display ticks

    def test_peak_is_the_highest_observed_not_the_latest(self):
        song = TickingSong(tracks=[FakeTrack("Riser", output_meter_left=0.2,
                                             output_meter_right=0.2)])
        ticks = iter([0.0, 0.05, 0.1])
        with mock.patch.object(mix_handler, "_clock", lambda: next(ticks)):
            result = FakeAdapter(song).call("mix.meter_poll", {"tracks": [0], "ms": 100})
        item = result["items"][0]
        self.assertEqual(item["samples"], 3)
        self.assertEqual(item["peak"], 0.4)
        self.assertEqual(item["left"], 0.4)
        self.assertEqual(result["sampled_ms"], 100.0)

    def test_zero_readings_are_measured_not_unavailable(self):
        song = FakeSong(tracks=[FakeTrack("Silent")])
        result = FakeAdapter(song).call("mix.meter_poll", {"ms": 0})
        item = result["items"][0]
        self.assertTrue(item["available"])
        self.assertEqual(item["peak"], 0.0)
        self.assertIn("not playing", " ".join(result["notes"]))

    def test_unavailable_meter_carries_the_reason(self):
        song = FakeSong(tracks=[NoMeters()])
        result = FakeAdapter(song).call("mix.meter_poll", {"ms": 0})
        item = result["items"][0]
        self.assertFalse(item["available"])
        self.assertIn("output_meter_level", item["reason"])
        self.assertEqual(result["summary"]["unavailable"], 1)

    def test_level_only_track_peaks_from_the_held_level(self):
        song = FakeSong(tracks=[LevelOnly()])
        item = FakeAdapter(song).call("mix.meter_poll", {"ms": 0})["items"][0]
        self.assertTrue(item["available"])
        self.assertEqual(item["peak"], 0.42)
        self.assertEqual(item["peak_source"], "output_meter_level")
        self.assertIsNone(item["left"])

    def test_instant_only_track_reports_the_missing_level(self):
        song = FakeSong(tracks=[InstantOnly()])
        item = FakeAdapter(song).call("mix.meter_poll", {"ms": 0})["items"][0]
        self.assertTrue(item["available"])
        self.assertEqual(item["peak"], 0.6)
        self.assertEqual(item["peak_source"], "output_meter_left/right")
        self.assertIn("output_meter_level", item["level_reason"])

    def test_selects_by_name_case_insensitively_and_by_index(self):
        adapter = FakeAdapter(make_song())
        by_name = adapter.call("mix.meter_poll", {"tracks": ["drums"], "ms": 0})
        self.assertEqual([item["name"] for item in by_name["items"]], ["Drums"])
        by_index = adapter.call("mix.meter_poll", {"tracks": [1], "ms": 0})
        self.assertEqual([item["name"] for item in by_index["items"]], ["Bass"])

    def test_the_same_track_is_polled_once(self):
        result = FakeAdapter(make_song()).call(
            "mix.meter_poll", {"tracks": ["Drums", 0], "ms": 0}
        )
        self.assertEqual([item["name"] for item in result["items"]], ["Drums"])

    def test_ambiguous_or_missing_names_are_refused(self):
        song = FakeSong(tracks=[FakeTrack("Drums"), FakeTrack("Drums")])
        with self.assertRaises(ScriptError) as ctx:
            FakeAdapter(song).call("mix.meter_poll", {"tracks": ["Drums"], "ms": 0})
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")

        with self.assertRaises(ScriptError) as ctx:
            FakeAdapter(make_song()).call("mix.meter_poll", {"tracks": ["Nope"], "ms": 0})
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

    def test_bad_arguments_are_refused(self):
        song = make_song()
        for args in (
            {"ms": -1},
            {"ms": 5001},
            {"ms": "100"},
            {"ms": True},
            {"tracks": []},
            {"tracks": "Drums"},
            {"tracks": [True]},
            {"tracks": [99]},
            {"tempo": 120},
        ):
            with self.assertRaises(ScriptError, msg=str(args)):
                dispatch.call("mix.meter_poll", args, song)

    def test_empty_set_reports_no_items(self):
        result = FakeAdapter(FakeSong()).call("mix.meter_poll", {"ms": 0})
        self.assertEqual(result["items"], [])
        self.assertEqual(result["summary"]["measured"], 0)
        self.assertEqual(result["summary"]["master_peak"], None)

    def test_catalogue_and_modes_expose_the_poll(self):
        catalogue = load_manifest()
        tool = catalogue["mix_meter_poll"]
        self.assertEqual(tool.cmd, "mix.meter_poll")
        self.assertFalse(tool.writes)
        self.assertEqual(set(tool.input["properties"]), {"tracks", "ms"})
        self.assertGreaterEqual(tool.timeout_ms, 5000)

        modes = load_modes(catalogue)
        self.assertIn("mix_meter_poll", modes.get("mix").tools)
        self.assertIn("mix_meter_poll", modes.get("inspect").tools)


if __name__ == "__main__":
    unittest.main()

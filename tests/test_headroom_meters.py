"""Measured headroom from a meter-poll payload, against the fake LOM.

These prove the join and the refusal rules. They do not prove Live's meter values; that gate is a
real `mix_headroom` call while `SCRATCH fortnight` is playing.
"""

import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeSong, FakeTrack
from enableton.tools import run_tool


def make_song(playing=True):
    song = FakeSong(
        tracks=[
            FakeTrack("Drums", output_meter_level=0.5, output_meter_left=0.4,
                      output_meter_right=0.5),
            FakeTrack("Bass", output_meter_level=0.2, output_meter_left=0.1,
                      output_meter_right=0.2),
        ],
        return_tracks=[
            FakeTrack("Reverb", output_meter_level=0.25, output_meter_left=0.25,
                      output_meter_right=0.25),
        ],
    )
    song.master_track = FakeTrack(
        "Main", output_meter_level=0.8, output_meter_left=0.8, output_meter_right=0.7
    )
    song.is_playing = playing
    return song


class HeadroomMeterTests(unittest.TestCase):
    def test_measured_master_headroom(self):
        result = run_tool("mix_headroom", {}, FakeAdapter(make_song()))
        headroom = result["headroom"]

        self.assertTrue(headroom["measured"])
        self.assertEqual(headroom["source"], "mix_meter_poll")
        self.assertTrue(headroom["playing"])
        self.assertEqual(headroom["master_peak"], 0.8)
        self.assertAlmostEqual(headroom["master_headroom_db"], 1.94, places=2)
        self.assertEqual(result["master"]["meter"]["available"], True)
        self.assertAlmostEqual(result["master"]["meter"]["headroom_db"], 1.94, places=2)

    def test_row_peaks_and_return_join(self):
        result = run_tool("mix_headroom", {}, FakeAdapter(make_song()))
        rows = {row["name"]: row for row in result["items"]}

        self.assertEqual(rows["Drums"]["peak"], 0.5)
        self.assertEqual(rows["Drums"]["peak_db"], -6.02)
        self.assertEqual(rows["Reverb"]["peak"], 0.25)
        self.assertTrue(rows["Reverb"]["peak_available"])
        self.assertEqual(result["summary"]["loudest"], {"name": "Drums", "peak": 0.5})

    def test_stopped_set_reports_why_headroom_is_unmeasured(self):
        song = make_song(playing=False)
        for track in list(song.tracks) + list(song.return_tracks) + [song.master_track]:
            track.output_meter_level = 0.0
            track.output_meter_left = 0.0
            track.output_meter_right = 0.0

        result = run_tool("mix_headroom", {}, FakeAdapter(song))
        headroom = result["headroom"]

        self.assertFalse(headroom["measured"])
        self.assertFalse(headroom["playing"])
        self.assertIn("not playing", headroom["reason"])
        self.assertIsNone(headroom["master_headroom_db"])

    def test_measure_false_skips_the_poll(self):
        class CountingAdapter(FakeAdapter):
            def __init__(self, song):
                super().__init__(song)
                self.commands = []

            def call(self, cmd, args=None, timeout_ms=None):
                self.commands.append(cmd)
                return super().call(cmd, args, timeout_ms)

        adapter = CountingAdapter(make_song())
        result = run_tool("mix_headroom", {"measure": False}, adapter)

        self.assertEqual(adapter.commands, ["snapshot.get"])
        self.assertFalse(result["headroom"]["measured"])
        self.assertEqual(result["headroom"]["requires"], "mix_meter_poll")

    def test_playing_silence_has_no_master_headroom_number(self):
        song = make_song()
        for track in list(song.tracks) + list(song.return_tracks) + [song.master_track]:
            track.output_meter_level = 0.0
            track.output_meter_left = 0.0
            track.output_meter_right = 0.0

        result = run_tool("mix_headroom", {}, FakeAdapter(song))

        self.assertTrue(result["headroom"]["measured"])
        self.assertIsNone(result["headroom"]["master_headroom_db"])


if __name__ == "__main__":
    unittest.main()

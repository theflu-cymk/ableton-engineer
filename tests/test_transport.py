import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeSong
from enableton.tools import run_tool

from Enableton.errors import ScriptError


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()

    def test_play_from_a_bar_sets_the_playhead(self):
        result = run_tool("transport_play", {"from_bar": 3}, self.adapter)
        self.assertTrue(result["is_playing"])
        self.assertEqual(self.adapter.song.current_song_time, 8.0)

    def test_stop_reports_the_transport_is_stopped(self):
        self.adapter.song.is_playing = True
        result = run_tool("transport_stop", {}, self.adapter)
        self.assertFalse(result["is_playing"])
        self.assertFalse(self.adapter.song.is_playing)

    def test_locate_moves_without_starting_playback(self):
        result = run_tool("transport_locate", {"bar": 5}, self.adapter)
        self.assertEqual(result["bar"], 5.0)
        self.assertEqual(result["position_beats"], 16.0)
        self.assertFalse(result["is_playing"])
        self.assertEqual(self.adapter.song.current_song_time, 16.0)

    def test_locate_returns_the_target_when_live_readback_lags(self):
        class DeferredSong(FakeSong):
            @property
            def current_song_time(self):
                return 0.5

            @current_song_time.setter
            def current_song_time(self, value):
                self.pending_position = value

        song = DeferredSong()
        result = run_tool("transport_locate", {"bar": 3}, FakeAdapter(song))
        self.assertEqual(result["position_beats"], 8.0)
        self.assertEqual(song.pending_position, 8.0)

    def test_set_tempo_reports_previous_and_new_bpm(self):
        result = run_tool("transport_set_tempo", {"tempo": 140}, self.adapter)
        self.assertEqual(result["from"], 140.0)
        self.assertEqual(result["to"], 140.0)
        self.assertEqual(self.adapter.song.tempo, 140.0)

    def test_set_tempo_rejects_out_of_range(self):
        with self.assertRaises(ScriptError) as ctx:
            run_tool("transport_set_tempo", {"tempo": 10}, self.adapter)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_set_loop_updates_bounds_and_can_disable_the_loop(self):
        result = run_tool(
            "transport_set_loop",
            {"enabled": True, "start_bar": 2, "end_bar": 6},
            self.adapter,
        )
        self.assertTrue(result["enabled"])
        self.assertEqual(self.adapter.song.loop_start, 4.0)
        self.assertEqual(self.adapter.song.loop_length, 16.0)

        result = run_tool("transport_set_loop", {"enabled": False}, self.adapter)
        self.assertFalse(result["enabled"])
        self.assertFalse(self.adapter.song.loop)
        self.assertEqual(self.adapter.song.loop_start, 4.0)

    def test_set_loop_rejects_an_incomplete_range(self):
        with self.assertRaises(ScriptError) as ctx:
            run_tool(
                "transport_set_loop",
                {"enabled": True, "start_bar": 2},
                self.adapter,
            )
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_set_loop_rejects_an_empty_range(self):
        with self.assertRaises(ScriptError) as ctx:
            run_tool(
                "transport_set_loop",
                {"enabled": True, "start_bar": 6, "end_bar": 6},
                self.adapter,
            )
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_transport_args_are_closed(self):
        with self.assertRaises(ScriptError) as ctx:
            run_tool("transport_stop", {"bar": 2}, self.adapter)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")


if __name__ == "__main__":
    unittest.main()

"""Resample capture against the fake LOM.

A green test here means the handler verifies the routing readback before arming, records across
display ticks, restores the routing and arm, removes the temporary clip and returns a WAV path the
PCM analyzer can read. It does not prove Live 12.2.5 accepts ``input_routing_type = Resampling``
or creates the clip; that gate is a real call on ``SCRATCH fortnight``.
"""

import os
import struct
import tempfile
import unittest
import wave

import support  # noqa: F401
from enableton.live.fake import (
    FakeAdapter, FakeClip, FakeClipSlot, FakeRouting, FakeSong, FakeTrack,
)
from enableton.manifest import load_manifest
from enableton.modes import load_modes
from enableton.tools import run_tool

from Enableton.errors import ScriptError


def write_wav(path, amplitude=16384, frames=4410, rate=44100):
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack("<h", amplitude) * frames)


def capture_track(**overrides):
    values = {
        "name": "Unused",
        "input_routing_type": FakeRouting("Ext. In", "ExtIn"),
        "input_routing_channel": FakeRouting("1", "Input1"),
        "available_input_routing_types": [
            FakeRouting("Ext. In", "ExtIn"), FakeRouting("Resampling", "Resampling"),
        ],
        "available_input_routing_channels": [FakeRouting("1", "Input1")],
        "clip_slots": [FakeClipSlot(), FakeClipSlot()],
    }
    values.update(overrides)
    return FakeTrack(**values)


def make_song(path):
    track = capture_track()
    song = FakeSong(tracks=[FakeTrack("Synth", is_midi=True), track])
    song.recorded_file = path
    return song, track


class StubbornTrack(FakeTrack):
    """A build that accepts the routing setter and silently keeps the old value."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stuck = FakeRouting("Ext. In", "ExtIn")

    @property
    def input_routing_type(self):
        return self._stuck

    @input_routing_type.setter
    def input_routing_type(self, value):
        pass


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "Recording.wav")
        write_wav(self.path)
        self.song, self.track = make_song(self.path)
        self.adapter = FakeAdapter(self.song)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_plans_without_touching_the_set(self):
        result = self.adapter.call("mix.resample_capture", {"track": "Unused"})
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["audible"])
        self.assertTrue(result["ready"])
        self.assertEqual(result["routing"]["target"]["name"], "Resampling")
        self.assertEqual(result["will_record"]["slot"], 0)
        self.assertFalse(self.track.arm)
        self.assertEqual(self.track.input_routing_type.identifier, "ExtIn")
        self.assertFalse(self.track.clip_slots[0].has_clip)

    def test_apply_records_a_wav_and_restores_state(self):
        result = self.adapter.call(
            "mix.resample_capture", {"track": "Unused", "ms": 250, "dry_run": False}
        )
        self.assertFalse(result["dry_run"])
        self.assertTrue(result["recorded"])
        self.assertEqual(result["file_path"], self.path)
        self.assertGreater(result["file_bytes"], 44)
        self.assertTrue(result["file_ready"])
        self.assertEqual(result["routing"]["readback"]["name"], "Resampling")
        self.assertTrue(result["routing"]["restored"])
        self.assertTrue(result["arm"]["restored"])
        self.assertTrue(result["clip_removed"])
        self.assertTrue(result["restore"]["ok"])
        self.assertEqual(self.track.input_routing_type.identifier, "ExtIn")
        self.assertFalse(self.track.arm)
        self.assertFalse(self.track.clip_slots[0].has_clip)
        self.assertGreaterEqual(result["ticks"], 1)

    def test_failed_arm_is_refused_before_recording(self):
        stubborn = StubbornTrack(
            "Unused",
            available_input_routing_types=[FakeRouting("Resampling", "Resampling")],
            clip_slots=[FakeClipSlot()],
        )
        song = FakeSong(tracks=[stubborn])
        song.recorded_file = self.path
        with self.assertRaises(ScriptError) as ctx:
            FakeAdapter(song).call(
                "mix.resample_capture", {"track": "Unused", "ms": 250, "dry_run": False}
            )
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertIn("did not take", ctx.exception.message)
        self.assertFalse(stubborn.arm)
        self.assertFalse(stubborn.clip_slots[0].has_clip)

    def test_refuses_while_playing(self):
        self.song.is_playing = True
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "mix.resample_capture", {"track": "Unused", "ms": 250, "dry_run": False}
            )
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertFalse(self.track.arm)
        self.assertEqual(self.track.input_routing_type.identifier, "ExtIn")

    def test_refuses_an_occupied_slot_and_offers_an_empty_one(self):
        self.track.clip_slots[0].clip = FakeClip("Existing")
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("mix.resample_capture", {"track": "Unused", "slot": 0})
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertIn("empty slots: 1", ctx.exception.message)

        default = self.adapter.call("mix.resample_capture", {"track": "Unused"})
        self.assertEqual(default["will_record"]["slot"], 1)

    def test_refuses_a_midi_track(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("mix.resample_capture", {"track": 0})
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertIn("MIDI", ctx.exception.message)

    def test_bad_arguments_are_refused(self):
        for args in (
            {"track": "Unused", "ms": 249},
            {"track": "Unused", "ms": 10001},
            {"track": "Unused", "ms": True},
            {"track": "Unused", "slot": -1},
            {"track": "Unused", "slot": 9},
            {"track": 99},
            {"track": "Unused", "tempo": 120},
        ):
            with self.assertRaises(ScriptError, msg=str(args)):
                self.adapter.call("mix.resample_capture", args)

        with self.assertRaises(ScriptError):
            self.adapter.call("mix.resample_capture", {})

    def test_run_tool_attaches_the_pcm_analysis(self):
        result = run_tool(
            "mix_resample_capture",
            {"track": "Unused", "ms": 250, "dry_run": False},
            adapter=self.adapter,
        )
        self.assertTrue(result["recorded"])
        self.assertTrue(result["analysis"]["measured"])
        self.assertEqual(result["analysis"]["sample_rate_hz"], 44100)
        self.assertAlmostEqual(result["analysis"]["sample_peak"], 0.5, places=3)
        self.assertAlmostEqual(result["analysis"]["headroom_db"], 6.02, places=1)

    def test_catalogue_and_modes_expose_the_capture(self):
        catalogue = load_manifest()
        tool = catalogue["mix_resample_capture"]
        self.assertEqual(tool.cmd, "mix.resample_capture")
        self.assertTrue(tool.writes)
        self.assertEqual(
            set(tool.input["properties"]), {"track", "slot", "ms", "dry_run"}
        )
        self.assertGreaterEqual(tool.timeout_ms, 11000)

        modes = load_modes(catalogue)
        self.assertIn("mix_resample_capture", modes.get("mix").tools)


if __name__ == "__main__":
    unittest.main()

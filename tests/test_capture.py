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
from unittest import mock

import support  # noqa: F401
from enableton import tools
from enableton.audio_analysis import AudioAnalysisError
from enableton.live.fake import (
    FakeAdapter, FakeClip, FakeClipSlot, FakeRouting, FakeScene, FakeSong, FakeTrack,
)
from enableton.manifest import load_manifest
from enableton.modes import load_modes
from enableton.tools import run_tool

from Enableton.errors import ScriptError
from Enableton.handlers import capture as capture_handler


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


class Live125RoutingTrack:
    """A fake track whose input routing behaves like Live 12.2.5 after Resampling.

    Two facts came out of the real gate: choosing Resampling replaces the input menu with
    resampling sources, so Ext. In disappears from ``available_input_routing_types``, and
    assigning the proxy captured beforehand raises ``Invalid routing type`` rather than restoring
    it. The fake enforces both so a restore that only works on the fake fails here.
    """

    def __init__(self, inner, offer_no_input=True):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_offer_no_input", offer_no_input)
        object.__setattr__(self, "_type", FakeRouting("Ext. In", "ExtIn"))
        options = [FakeRouting("Ext. In", "ExtIn"), FakeRouting("Resampling", "Resampling")]
        if offer_no_input:
            options.append(FakeRouting("No Input", "NoInput"))
        object.__setattr__(self, "_available", options)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __setattr__(self, name, value):
        if name != "input_routing_type":
            setattr(self._inner, name, value)
            return
        label = getattr(value, "display_name", str(value))
        labels = [option.display_name for option in self._available]
        if label not in labels:
            raise ValueError("Invalid routing type")
        object.__setattr__(self, "_type", self._available[labels.index(label)])
        if label == "Resampling":
            after = [FakeRouting("Resampling", "Resampling")]
            if self._offer_no_input:
                after.append(FakeRouting("No Input", "NoInput"))
            object.__setattr__(self, "_available", after)

    @property
    def input_routing_type(self):
        return self._type

    @property
    def available_input_routing_types(self):
        return self._available


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
        self.assertIsNone(result["will_record"]["scene"])
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

    def test_scene_launch_records_the_mix(self):
        self.song.scenes = [FakeScene("intro", 0, self.song)]
        result = self.adapter.call(
            "mix.resample_capture",
            {"track": "Unused", "scene": 0, "ms": 250, "dry_run": False},
        )
        self.assertEqual(result["scene"], 0)
        self.assertTrue(result["recorded"])
        self.assertTrue(result["routing"]["restored"])
        self.assertTrue(result["restore"]["ok"])
        self.assertFalse(self.song.is_playing)

        planned = self.adapter.call("mix.resample_capture", {"track": "Unused", "scene": 0})
        self.assertEqual(planned["will_record"]["scene"]["index"], 0)

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
            {"track": "Unused", "scene": -1},
            {"track": "Unused", "scene": 9},
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

    def test_analysis_retries_a_locked_wav(self):
        locked = AudioAnalysisError(
            "cannot read WAV file: [Errno 13] Permission denied: 'x.wav'"
        )
        with mock.patch.object(
            tools, "analyze_wave", side_effect=[locked, {"measured": True}]
        ), mock.patch.object(tools.time, "sleep") as sleep:
            result = tools._with_analysis({"recorded": True, "file_path": "x.wav"})
        self.assertTrue(result["analysis"]["measured"])
        sleep.assert_called_once_with(0.5)

    def test_catalogue_and_modes_expose_the_capture(self):
        catalogue = load_manifest()
        tool = catalogue["mix_resample_capture"]
        self.assertEqual(tool.cmd, "mix.resample_capture")
        self.assertTrue(tool.writes)
        self.assertEqual(
            set(tool.input["properties"]), {"track", "slot", "scene", "ms", "dry_run"}
        )
        self.assertGreaterEqual(tool.timeout_ms, 11000)

        modes = load_modes(catalogue)
        self.assertIn("mix_resample_capture", modes.get("mix").tools)

    def _degraded_song(self, offer_no_input=True):
        inner = FakeTrack("Scratch", clip_slots=[FakeClipSlot()])
        track = Live125RoutingTrack(inner, offer_no_input=offer_no_input)
        song = FakeSong(tracks=[track])
        song.recorded_file = self.path
        return song, track, inner

    def test_restore_degrades_to_no_input_when_live_drops_the_type(self):
        song, track, inner = self._degraded_song()
        result = FakeAdapter(song).call(
            "mix.resample_capture", {"track": "Scratch", "ms": 250, "dry_run": False}
        )
        self.assertTrue(result["recorded"])
        self.assertFalse(result["routing"]["restored"])
        self.assertTrue(result["routing"]["degraded"])
        self.assertEqual(result["routing"]["applied"], "No Input")
        # readback is what Live reported while the capture was armed; the fallback the restore
        # actually landed on is carried by "applied" and by the degraded entry.
        self.assertEqual(result["routing"]["readback"]["name"], "Resampling")
        self.assertEqual(result["restore"]["problems"], [])
        self.assertEqual(result["restore"]["degraded"][0]["field"], "input type")
        self.assertIn("Invalid routing type", result["restore"]["degraded"][0]["reason"])
        self.assertTrue(result["arm"]["restored"])
        self.assertFalse(inner.arm)
        self.assertEqual(track.input_routing_type.display_name, "No Input")
        self.assertTrue(
            any("could not be restored exactly" in note for note in result["notes"])
        )

    def test_arm_is_restored_when_no_routing_fallback_exists(self):
        song, track, inner = self._degraded_song(offer_no_input=False)
        result = FakeAdapter(song).call(
            "mix.resample_capture", {"track": "Scratch", "ms": 250, "dry_run": False}
        )
        self.assertTrue(result["recorded"])
        self.assertFalse(result["routing"]["restored"])
        self.assertFalse(result["routing"]["degraded"])
        self.assertTrue(result["restore"]["problems"])
        self.assertTrue(result["arm"]["restored"])
        self.assertFalse(inner.arm)

    def test_file_bytes_waits_for_the_size_to_stabilise(self):
        sizes = [327680, 393216, 556112, 556112, 556112]
        with mock.patch.object(
            capture_handler.os.path, "getsize", side_effect=sizes + [556112] * 40
        ):
            result = FakeAdapter(self.song).call(
                "mix.resample_capture", {"track": "Unused", "ms": 250, "dry_run": False}
            )
        self.assertTrue(result["file_ready"])
        self.assertTrue(result["file_bytes_stable"])
        self.assertEqual(result["file_bytes"], 556112)


if __name__ == "__main__":
    unittest.main()

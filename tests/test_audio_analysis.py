import math
import os
import tempfile
import unittest
import wave

import support  # noqa: F401
from enableton.audio_analysis import AudioAnalysisError, analyze_wave


class AudioAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = os.path.join(self.temp_dir.name, "test.wav")

    def _write_wave(self, samples, *, channels=1, sample_width=2, sample_rate=4):
        with wave.open(self.path, "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(sample_width)
            output.setframerate(sample_rate)
            output.writeframes(samples)

    def test_measures_duration_peak_rms_and_dc_for_pcm16(self):
        values = (-32768, 0, 16384, 32767)
        samples = b"".join(
            value.to_bytes(2, "little", signed=True) for value in values
        )
        self._write_wave(samples)
        with open(self.path, "rb") as source:
            original = source.read()

        report = analyze_wave(self.path)

        with open(self.path, "rb") as source:
            self.assertEqual(source.read(), original)
        self.assertTrue(report["measured"])
        self.assertEqual(report["format"], "PCM")
        self.assertEqual(report["sample_rate_hz"], 4)
        self.assertEqual(report["bits_per_sample"], 16)
        self.assertEqual(report["frames"], 4)
        self.assertEqual(report["samples"], 4)
        self.assertEqual(report["duration_s"], 1.0)
        self.assertEqual(report["sample_peak"], 1.0)
        self.assertEqual(report["peak_dbfs"], 0.0)
        self.assertEqual(report["headroom_db"], 0.0)
        expected_rms = math.sqrt((1 + 0.25 + (32767 / 32768) ** 2) / 4)
        expected_dc = (-1 + 0 + 0.5 + 32767 / 32768) / 4
        self.assertAlmostEqual(report["rms"], expected_rms)
        self.assertAlmostEqual(report["dc_offset"], expected_dc)
        self.assertFalse(report["silent"])

    def test_measures_only_the_requested_frame_aligned_window(self):
        values = (-32768, 0, 16384, 32767)
        samples = b"".join(
            value.to_bytes(2, "little", signed=True) for value in values
        )
        self._write_wave(samples)
        with open(self.path, "rb") as source:
            original = source.read()

        report = analyze_wave(self.path, window_s=(0.25, 0.75))

        self.assertEqual(report["frames"], 2)
        self.assertEqual(report["samples"], 2)
        self.assertEqual(report["duration_s"], 0.5)
        self.assertEqual(report["source_duration_s"], 1.0)
        self.assertEqual(report["window_s"], [0.25, 0.75])
        self.assertEqual(report["frame_offset"], 1)
        self.assertEqual(report["sample_peak"], 0.5)
        self.assertAlmostEqual(report["rms"], math.sqrt(0.125))
        self.assertEqual(report["dc_offset"], 0.25)
        with open(self.path, "rb") as source:
            self.assertEqual(source.read(), original)

    def test_window_boundaries_snap_to_nearest_sample_frame(self):
        values = (-32768, 0, 16384, 32767)
        self._write_wave(b"".join(value.to_bytes(2, "little", signed=True) for value in values))

        report = analyze_wave(self.path, window_s=(0.13, 0.88))

        self.assertEqual(report["window_s"], [0.25, 1.0])
        self.assertEqual(report["frames"], 3)
        self.assertEqual(report["sample_peak"], 32767 / 32768)

    def test_rejects_invalid_or_out_of_range_windows(self):
        self._write_wave(b"\x00\x00" * 4)
        for window in (
            (),
            (0,),
            (0, 0),
            (-0.25, 0.25),
            (0.25, 1.25),
            (0.75, 0.5),
            (True, 0.5),
            (0, float("inf")),
            ("0", "1"),
        ):
            with self.subTest(window=window), self.assertRaises(AudioAnalysisError):
                analyze_wave(self.path, window_s=window)

    def test_stereo_dc_offsets_do_not_cancel_each_other(self):
        samples = b"".join(
            value.to_bytes(2, "little", signed=True)
            for frame in ((16384, -16384), (16384, -16384))
            for value in frame
        )
        self._write_wave(samples, channels=2)

        report = analyze_wave(self.path)

        self.assertEqual(report["dc_offset_by_channel"], [0.5, -0.5])
        self.assertEqual(report["dc_offset"], 0.5)

    def test_stereo_channel_metrics_remain_separate(self):
        samples = b"".join(
            value.to_bytes(2, "little", signed=True)
            for frame in ((32767, 0), (0, 16384))
            for value in frame
        )
        self._write_wave(samples, channels=2)

        report = analyze_wave(self.path)

        left, right = report["per_channel"]
        self.assertAlmostEqual(left["sample_peak"], 32767 / 32768)
        self.assertAlmostEqual(left["rms"], (32767 / 32768) / math.sqrt(2))
        self.assertAlmostEqual(right["sample_peak"], 0.5)
        self.assertAlmostEqual(right["rms"], 0.5 / math.sqrt(2))
        self.assertAlmostEqual(left["dc_offset"], 32767 / 32768 / 2)
        self.assertEqual(right["dc_offset"], 0.25)

    def test_decodes_unsigned_pcm8(self):
        self._write_wave(bytes((0, 128, 255)), sample_width=1, sample_rate=3)

        report = analyze_wave(self.path)

        self.assertEqual(report["sample_peak"], 1.0)
        self.assertAlmostEqual(report["dc_offset"], 1 / 384)
        self.assertAlmostEqual(report["duration_s"], 1.0)

    def test_decodes_signed_pcm24(self):
        samples = (-8388608).to_bytes(3, "little", signed=True)
        samples += (4194304).to_bytes(3, "little", signed=True)
        self._write_wave(samples, sample_width=3, sample_rate=2)

        report = analyze_wave(self.path)

        self.assertEqual(report["bits_per_sample"], 24)
        self.assertEqual(report["sample_peak"], 1.0)
        self.assertAlmostEqual(report["rms"], math.sqrt(0.625))
        self.assertEqual(report["dc_offset"], 0.25)

    def test_decodes_signed_pcm32(self):
        samples = (-2147483648).to_bytes(4, "little", signed=True)
        samples += (1073741824).to_bytes(4, "little", signed=True)
        self._write_wave(samples, sample_width=4, sample_rate=2)

        report = analyze_wave(self.path)

        self.assertEqual(report["bits_per_sample"], 32)
        self.assertEqual(report["sample_peak"], 1.0)
        self.assertAlmostEqual(report["rms"], math.sqrt(0.625))
        self.assertEqual(report["dc_offset"], 0.25)

    def test_silence_has_no_finite_dbfs_or_headroom_claim(self):
        self._write_wave(b"\x00\x00\x00\x00")

        report = analyze_wave(self.path)

        self.assertTrue(report["silent"])
        self.assertIsNone(report["peak_dbfs"])
        self.assertIsNone(report["rms_dbfs"])
        self.assertIsNone(report["headroom_db"])

    def test_rejects_non_wav_input_with_a_specific_error(self):
        with open(self.path, "wb") as output:
            output.write(b"not a wav")

        with self.assertRaisesRegex(AudioAnalysisError, "cannot read WAV"):
            analyze_wave(self.path)

    def test_rejects_missing_file_with_a_specific_error(self):
        with self.assertRaisesRegex(AudioAnalysisError, "cannot read WAV"):
            analyze_wave(os.path.join(self.temp_dir.name, "missing.wav"))

    def test_rejects_empty_wav(self):
        self._write_wave(b"")

        with self.assertRaisesRegex(AudioAnalysisError, "no audio frames"):
            analyze_wave(self.path)

    def test_rejects_truncated_partial_frame(self):
        self._write_wave(b"\x01\x00")
        with open(self.path, "rb+") as output:
            output.seek(-1, os.SEEK_END)
            output.truncate()

        with self.assertRaisesRegex(AudioAnalysisError, "partial audio frame"):
            analyze_wave(self.path)


if __name__ == "__main__":
    unittest.main()

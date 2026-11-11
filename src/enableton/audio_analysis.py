"""Read-only measurements for uncompressed PCM WAV files.

These file measurements do not access Ableton Live and are not LUFS, spectral, or meter
measurements.
"""

from __future__ import annotations

import math
import os
import wave
from collections.abc import Sequence
from typing import Any


class AudioAnalysisError(ValueError):
    """The WAV file is valid enough to open but cannot be measured safely."""


def _decode_sample(data: bytes, sample_width: int) -> int:
    if sample_width == 1:
        return data[0] - 128
    return int.from_bytes(data, byteorder="little", signed=True)


def _dbfs(amplitude: float) -> float | None:
    return 20.0 * math.log10(amplitude) if amplitude > 0.0 else None


def _window_frames(
    window_s: Sequence[float] | None,
    sample_rate: int,
    total_frames: int,
) -> tuple[int, int]:
    if window_s is None:
        return 0, total_frames
    if (
        not isinstance(window_s, Sequence)
        or isinstance(window_s, (str, bytes))
        or len(window_s) != 2
    ):
        raise AudioAnalysisError("window_s must be a (start_seconds, end_seconds) pair")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in window_s
    ):
        raise AudioAnalysisError("window_s values must be finite numbers")
    start_s, end_s = (float(value) for value in window_s)
    if not math.isfinite(start_s) or not math.isfinite(end_s):
        raise AudioAnalysisError("window_s values must be finite numbers")

    duration_s = total_frames / sample_rate
    if start_s < 0 or end_s <= start_s or end_s > duration_s:
        raise AudioAnalysisError(
            f"window_s must satisfy 0 <= start < end <= source duration ({duration_s:.9g}s)"
        )
    start_frame = round(start_s * sample_rate)
    end_frame = round(end_s * sample_rate)
    if end_frame <= start_frame:
        raise AudioAnalysisError("window_s is shorter than one sample frame")
    return start_frame, end_frame


def analyze_wave(
    path: str | os.PathLike[str],
    window_s: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Measure an entire PCM WAV or bounded [start, end) window without modifying it."""
    try:
        source = wave.open(os.fspath(path), "rb")
    except (OSError, wave.Error, EOFError) as exc:
        raise AudioAnalysisError(f"cannot read WAV file: {exc}") from exc

    with source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        declared_frames = source.getnframes()

        if source.getcomptype() != "NONE":
            raise AudioAnalysisError("only uncompressed PCM WAV files are supported")
        if channels < 1 or sample_rate < 1:
            raise AudioAnalysisError("WAV must have at least one channel and a positive sample rate")
        if sample_width not in (1, 2, 3, 4):
            raise AudioAnalysisError(f"unsupported PCM sample width: {sample_width} bytes")
        if declared_frames < 1:
            raise AudioAnalysisError("WAV contains no audio frames")

        frame_width = channels * sample_width
        start_frame, end_frame = _window_frames(window_s, sample_rate, declared_frames)
        frames_to_read = end_frame - start_frame
        try:
            source.setpos(start_frame)
        except (wave.Error, EOFError) as exc:
            raise AudioAnalysisError(f"cannot seek to WAV window: {exc}") from exc

        scale = float(1 << (sample_width * 8 - 1))
        channel_sums = [0.0] * channels
        channel_squares = [0.0] * channels
        channel_peaks = [0.0] * channels
        sample_count = 0
        frames_read = 0
        sum_squares = 0.0
        peak = 0.0

        while frames_read < frames_to_read:
            try:
                block = source.readframes(min(8192, frames_to_read - frames_read))
            except (OSError, wave.Error, EOFError) as exc:
                raise AudioAnalysisError(f"cannot read WAV audio frames: {exc}") from exc
            if not block:
                raise AudioAnalysisError(f"WAV ends before requested window frame {end_frame}")
            if len(block) % frame_width:
                raise AudioAnalysisError("WAV data ends in a partial audio frame")
            block_frames = len(block) // frame_width
            for frame_index in range(block_frames):
                frame_offset = frame_index * frame_width
                for channel in range(channels):
                    start = frame_offset + channel * sample_width
                    sample = _decode_sample(block[start : start + sample_width], sample_width)
                    normalized = sample / scale
                    channel_sums[channel] += normalized
                    channel_squares[channel] += normalized * normalized
                    channel_peaks[channel] = max(channel_peaks[channel], abs(normalized))
                    sum_squares += normalized * normalized
                    peak = max(peak, abs(normalized))
                    sample_count += 1
            frames_read += block_frames

        if window_s is None and frames_read != declared_frames:
            raise AudioAnalysisError(
                f"WAV declares {declared_frames} frames but contains {frames_read}"
            )

    peak_dbfs = _dbfs(peak)
    rms = math.sqrt(sum_squares / sample_count)
    dc_by_channel = [total / frames_read for total in channel_sums]
    per_channel = []
    for channel in range(channels):
        channel_peak = channel_peaks[channel]
        channel_rms = math.sqrt(channel_squares[channel] / frames_read)
        per_channel.append(
            {
                "sample_peak": channel_peak,
                "peak_dbfs": _dbfs(channel_peak),
                "rms": channel_rms,
                "rms_dbfs": _dbfs(channel_rms),
                "dc_offset": dc_by_channel[channel],
            }
        )
    return {
        "measured": True,
        "format": "PCM",
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "bits_per_sample": sample_width * 8,
        "frames": frames_read,
        "samples": sample_count,
        "duration_s": frames_read / sample_rate,
        "source_duration_s": declared_frames / sample_rate,
        "window_s": [start_frame / sample_rate, end_frame / sample_rate],
        "frame_offset": start_frame,
        "sample_peak": peak,
        "peak_dbfs": peak_dbfs,
        "headroom_db": -peak_dbfs if peak_dbfs is not None else None,
        "rms": rms,
        "rms_dbfs": _dbfs(rms),
        "dc_offset": max(abs(offset) for offset in dc_by_channel),
        "dc_offset_by_channel": dc_by_channel,
        "per_channel": per_channel,
        "silent": peak == 0.0,
    }

"""Reference-track measurements for the producer workflow.

The basic pass uses the stdlib WAV reader and is always available. The advanced pass is optional:
if numpy, soundfile and pyloudnorm are installed it adds integrated LUFS, band balance, spectral
centroid and a stereo correlation. Missing optional packages produce an explicit unavailable block,
never a fabricated measurement.
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, Optional, Sequence

from .audio_analysis import AudioAnalysisError, analyze_wave
from .reports import ReportError


def _window(args: Dict[str, Any]) -> Optional[Sequence[float]]:
    value = args.get("window_s")
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise ReportError("window_s must be a [start, end] pair")
    return value


def _flag(profile: Dict[str, Any]) -> list[str]:
    flags = []
    peak = profile.get("peak_dbfs")
    if peak is not None and peak > -0.1:
        flags.append("near_clipping")
    if profile.get("silent"):
        flags.append("silent")
    if profile.get("channels") == 1:
        flags.append("mono")
    return flags


def _basic(path: str, window_s: Optional[Sequence[float]]) -> Dict[str, Any]:
    try:
        wave = analyze_wave(path, window_s=window_s)
    except AudioAnalysisError as exc:
        raise ReportError(str(exc)) from exc
    peak = wave.get("peak_dbfs")
    rms = wave.get("rms_dbfs")
    crest = None if peak is None or rms is None else round(peak - rms, 2)
    channels = [row for row in wave.get("per_channel") or []]
    balance = None
    if len(channels) == 2:
        left, right = channels[0].get("rms"), channels[1].get("rms")
        if left and right and left > 0 and right > 0:
            balance = round(20.0 * math.log10(left / right), 2)
    return {
        "measured": True,
        "source": "PCM WAV",
        "sample_rate_hz": wave.get("sample_rate_hz"),
        "channels": wave.get("channels"),
        "bits_per_sample": wave.get("bits_per_sample"),
        "duration_s": wave.get("duration_s"),
        "sample_peak": wave.get("sample_peak"),
        "peak_dbfs": peak,
        "rms_dbfs": rms,
        "crest_db": crest,
        "headroom_db": wave.get("headroom_db"),
        "dc_offset": wave.get("dc_offset"),
        "stereo_balance_db": balance,
        "silent": wave.get("silent"),
    }


def _advanced(path: str, window_s: Optional[Sequence[float]]) -> Dict[str, Any]:
    try:
        import numpy as np  # type: ignore
        import pyloudnorm as pyln  # type: ignore
        import soundfile as sf  # type: ignore
    except Exception as exc:  # noqa: BLE001 - optional analysis packages
        return {
            "measured": False,
            "reason": "optional analysis packages are missing: %s" % exc,
            "install": "uv run --with numpy --with soundfile --with pyloudnorm ...",
        }

    try:
        audio, sample_rate = sf.read(path, always_2d=True, dtype="float32")
        if audio.size == 0:
            raise ValueError("audio contains no frames")
        if window_s is not None:
            start = max(0, int(round(float(window_s[0]) * sample_rate)))
            end = min(len(audio), int(round(float(window_s[1]) * sample_rate)))
            if end <= start:
                raise ValueError("window_s is shorter than one sample frame")
            audio = audio[start:end]
        meter = pyln.Meter(sample_rate)
        lufs = float(meter.integrated_loudness(audio))
        if not math.isfinite(lufs):
            lufs = None

        mono = audio.mean(axis=1)
        max_samples = min(len(mono), int(sample_rate * 30))
        mono = mono[:max_samples]
        frame = 2048
        if len(mono) < frame:
            mono = np.pad(mono, (0, frame - len(mono)))
        hop = 1024
        frames = np.lib.stride_tricks.sliding_window_view(mono, frame)[::hop]
        window = np.hanning(frame).astype(np.float32)
        spectrum = np.abs(np.fft.rfft(frames * window, axis=1)).mean(axis=0)
        freqs = np.fft.rfftfreq(frame, 1.0 / sample_rate)
        total = float(np.sum(spectrum ** 2)) or 1.0
        bands = {
            "sub_20_60": (20, 60),
            "bass_60_120": (60, 120),
            "low_mid_120_500": (120, 500),
            "mid_500_2k": (500, 2000),
            "high_mid_2k_6k": (2000, 6000),
            "air_6k_20k": (6000, 20000),
        }
        band_energy = {}
        for name, (low, high) in bands.items():
            mask = (freqs >= low) & (freqs < high)
            energy = float(np.sum(spectrum[mask] ** 2))
            band_energy[name] = round(10.0 * math.log10(max(energy / total, 1e-12)), 2)
        centroid = float(np.sum(freqs * spectrum) / (float(np.sum(spectrum)) or 1.0))

        stereo = None
        if audio.shape[1] >= 2:
            left = audio[:, 0]
            right = audio[:, 1]
            denominator = float(np.sum(left * left) + np.sum(right * right))
            correlation = (
                float(2.0 * np.sum(left * right) / denominator) if denominator else None
            )
            mid = (left + right) / 2.0
            side = (left - right) / 2.0
            mid_rms = float(np.sqrt(np.mean(mid * mid)))
            side_rms = float(np.sqrt(np.mean(side * side)))
            side_mid_db = (
                round(20.0 * math.log10(max(side_rms, 1e-12) / max(mid_rms, 1e-12)), 2)
                if mid_rms else None
            )
            stereo = {
                "correlation": None if correlation is None else round(correlation, 3),
                "side_mid_db": side_mid_db,
            }

        return {
            "measured": True,
            "integrated_lufs": None if lufs is None else round(lufs, 2),
            "sample_peak_dbfs": round(20.0 * math.log10(max(float(np.max(np.abs(audio))), 1e-12)), 2),
            "true_peak": "unavailable",
            "spectral_centroid_hz": round(centroid, 1),
            "band_energy_db": band_energy,
            "stereo": stereo,
            "analyzed_s": round(min(len(audio) / sample_rate, 30.0), 3),
        }
    except Exception as exc:  # noqa: BLE001 - optional analysis must not break the tool
        return {"measured": False, "reason": "advanced analysis failed: %s" % exc}


def _profile(path: str, window_s: Optional[Sequence[float]]) -> Dict[str, Any]:
    basic = _basic(path, window_s)
    advanced = _advanced(path, window_s)
    profile = dict(basic)
    profile["advanced"] = advanced
    profile["flags"] = _flag(basic)
    return profile


def _deltas(current: Dict[str, Any], reference: Dict[str, Any]) -> Dict[str, Any]:
    deltas = {}
    for key in ("peak_dbfs", "rms_dbfs", "crest_db", "integrated_lufs"):
        a = current.get(key)
        b = reference.get(key)
        if a is None or b is None:
            continue
        deltas[key] = round(float(a) - float(b), 2)
    return deltas


def reference_analyze(args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Measure one reference WAV, optionally comparing another file to it."""
    args = dict(args or {})
    unknown = sorted(set(args) - {"path", "compare_to", "window_s"})
    if unknown:
        raise ReportError("unknown argument(s): %s" % ", ".join(unknown))
    path = args.get("path")
    if not isinstance(path, str) or not path:
        raise ReportError("path must be a non-empty file path")
    if not os.path.isfile(path):
        raise ReportError("reference file does not exist: %s" % path)
    window_s = _window(args)
    profile = _profile(path, window_s)
    result = {
        "status": "available",
        "path": path,
        "window_s": list(window_s) if window_s is not None else None,
        "profile": profile,
        "limitations": [
            "Basic measurements are PCM WAV only.",
            "No integrated LUFS or spectral bands are claimed unless advanced is measured.",
            "This is a measurement report, not an audition or a mastering decision.",
        ],
    }
    compare_to = args.get("compare_to")
    if compare_to is not None:
        if not isinstance(compare_to, str) or not compare_to:
            raise ReportError("compare_to must be a non-empty file path")
        if not os.path.isfile(compare_to):
            raise ReportError("comparison file does not exist: %s" % compare_to)
        other = _profile(compare_to, window_s)
        result["comparison"] = {
            "path": compare_to,
            "profile": other,
            "deltas": _deltas(profile, other),
            "note": "Deltas are comparison values, not targets to match blindly.",
        }
    return result
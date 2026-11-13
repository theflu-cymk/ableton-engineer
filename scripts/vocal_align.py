#!/usr/bin/env python3
"""Measure the speed and offset between a vocal stem and a full-mix reference.

The output is a warp map for ``clips_apply_warp_map``: beat positions relative to the
vocal clip and source sample times in seconds.  It never changes Live or either audio
file.  The measurement is an onset cross-correlation, not a listening test.

Example
-------
uv run --with librosa --with soundfile --with scipy python scripts/vocal_align.py \
  --vocal "C:\\...\\Vocals ... 96bpm - Bmaj.mp3" \
  --reference "C:\\...\\fortnight (1).mp3" \
  --source-bpm 96 --target-bpm 120 \
  --reference-start-beat 9 --reference-end-beat 379 \
  --clip-start-beat 12 --out .tmp/vocal_alignment.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


def _load_librosa():
    try:
        import librosa
    except ImportError as exc:  # pragma: no cover - the command is the documentation
        raise SystemExit(
            "librosa is not installed; run this with "
            "`uv run --with librosa --with soundfile --with scipy python scripts/vocal_align.py ...`"
        ) from exc
    return librosa


def _onset_envelope(y: np.ndarray, sr: int, hop: int = 512) -> np.ndarray:
    librosa = _load_librosa()
    spectrum = np.abs(
        librosa.stft(librosa.effects.preemphasis(y), n_fft=2048, hop_length=hop)
    )
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    band = (freqs >= 250.0) & (freqs <= 5000.0)
    energy = spectrum[band].sum(axis=0)
    flux = np.diff(np.log1p(energy), prepend=np.log1p(energy[0]))
    flux = np.maximum(flux, 0.0)
    return (flux - flux.mean()) / (flux.std() + 1e-9)


def _best_lag(a: np.ndarray, b: np.ndarray, max_lag: int) -> tuple[int, float]:
    from scipy.signal import correlate, correlation_lags

    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    corr = correlate(b, a, mode="full", method="fft")
    lags = correlation_lags(len(b), len(a), mode="full")
    keep = np.abs(lags) <= max_lag
    values = corr[keep]
    lag_values = lags[keep]
    index = int(np.argmax(values))
    return int(lag_values[index]), float(values[index] / max(1, min(len(a), len(b))))


def _window_lags(
    a: np.ndarray,
    b: np.ndarray,
    hop: int,
    sr: int,
    window_s: float,
    step_s: float,
    max_lag: int,
) -> list[dict[str, float]]:
    from scipy.signal import correlate

    window = max(8, int(window_s * sr / hop))
    step = max(1, int(step_s * sr / hop))
    rows = []
    for start in range(0, min(len(a), len(b)) - window + 1, step):
        left = a[start:start + window]
        right = b[start:start + window]
        corr = correlate(right - right.mean(), left - left.mean(), mode="full", method="fft")
        lags = np.arange(-len(left) + 1, len(right))
        keep = np.abs(lags) <= max_lag
        index = int(np.argmax(corr[keep]))
        lag = int(lags[keep][index])
        if lag >= 0:
            x, y = left[:len(right) - lag], right[lag:]
        else:
            x, y = left[-lag:], right[:len(left) + lag]
        n = min(len(x), len(y))
        coefficient = float(np.corrcoef(x[:n], y[:n])[0, 1]) if n > 10 else 0.0
        rows.append({
            "at_s": round(start * hop / sr, 3),
            "lag_s": round(lag * hop / sr, 4),
            "corr": round(coefficient, 4),
        })
    return rows


def _number(value: Any, name: str) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise SystemExit("%s must be a number" % name)
    if not math.isfinite(value):
        raise SystemExit("%s must be finite" % name)
    return value


def build_map(args: argparse.Namespace) -> dict[str, Any]:
    librosa = _load_librosa()
    vocal_path = Path(args.vocal).expanduser()
    reference_path = Path(args.reference).expanduser()
    if not vocal_path.is_file():
        raise SystemExit("vocal file not found: %s" % vocal_path)
    if not reference_path.is_file():
        raise SystemExit("reference file not found: %s" % reference_path)

    sr = int(args.sample_rate)
    hop = 512
    source_bpm = _number(args.source_bpm, "source_bpm")
    target_bpm = _number(args.target_bpm, "target_bpm")
    if source_bpm <= 0 or target_bpm <= 0:
        raise SystemExit("source_bpm and target_bpm must be positive")
    rate = _number(args.rate, "rate") if args.rate is not None else target_bpm / source_bpm
    if rate <= 0:
        raise SystemExit("rate must be positive")

    vocal, _ = librosa.load(str(vocal_path), sr=sr, mono=True)
    reference, _ = librosa.load(str(reference_path), sr=sr, mono=True)
    if not len(vocal) or not len(reference):
        raise SystemExit("one of the files contains no audio")

    stretched = librosa.effects.time_stretch(vocal, rate=rate)
    left = _onset_envelope(stretched, sr, hop)
    right = _onset_envelope(reference, sr, hop)
    max_lag = int(args.max_lag_s * sr / hop)
    lag_frames, peak = _best_lag(left[:int(60 * sr / hop)], right[:int(60 * sr / hop)], max_lag)
    lag_s = lag_frames * hop / sr
    windows = _window_lags(left, right, hop, sr, args.window_s, args.step_s, max_lag)
    stable = [row["lag_s"] for row in windows if row["corr"] >= 0.2]
    offsets = stable or [row["lag_s"] for row in windows] or [lag_s]
    offset_s = float(np.median(offsets))
    drift_s = float(max(offsets) - min(offsets)) if offsets else 0.0

    bps = target_bpm / 60.0
    reference_start_beat = _number(args.reference_start_beat, "reference_start_beat")
    clip_start_beat = _number(args.clip_start_beat, "clip_start_beat")
    reference_offset_s = _number(args.reference_offset_s, "reference_offset_s")
    reference_end_beat = args.reference_end_beat
    if reference_end_beat is None:
        reference_end_beat = reference_start_beat + len(reference) / sr * bps
    reference_end_beat = _number(reference_end_beat, "reference_end_beat")
    if reference_end_beat <= clip_start_beat:
        raise SystemExit("reference_end_beat must be after clip_start_beat")

    start_marker = (clip_start_beat - reference_start_beat) + (reference_offset_s - offset_s) * bps
    # start_marker is the clip beat that plays at the clip's arrangement start;
    # end_marker therefore includes the same offset to end at reference_end_beat.
    end_marker = reference_end_beat - clip_start_beat + start_marker
    if end_marker <= start_marker:
        raise SystemExit("the reference ends before the vocal clip's usable range")
    if start_marker < -1e-6:
        raise SystemExit(
            "the vocal clip starts too early for this reference; move the clip later by %.3f beats "
            "and rerun" % (-start_marker)
        )
    start_marker = max(0.0, start_marker)

    duration = len(vocal) / sr
    markers = []
    position = start_marker if start_marker > 1e-6 else args.step_beats
    while position < end_marker - 1e-6:
        absolute_beat = clip_start_beat + (position - start_marker)
        reference_time = (
            reference_offset_s
            + (absolute_beat - reference_start_beat) / bps
        )
        source_time = (reference_time - offset_s) * rate
        if 0.0 <= source_time <= duration + 1e-9:
            markers.append({
                "beat_time": round(position, 6),
                "sample_time": round(source_time, 6),
            })
        position += args.step_beats

    # The last marker in Live's vector is a hidden anchor for the final segment.
    # Pin the audible end explicitly, otherwise that hidden old marker can still
    # stretch the last segment even after end_marker is shortened.
    end_reference_time = (
        reference_offset_s + (reference_end_beat - reference_start_beat) / bps
    )
    end_source_time = (end_reference_time - offset_s) * rate
    if not 0.0 <= end_source_time <= duration + 1e-9:
        raise SystemExit("the reference end maps outside the vocal source")
    markers.append({
        "beat_time": round(end_marker, 6),
        "sample_time": round(end_source_time, 6),
    })

    if len(markers) < 2:
        raise SystemExit("fewer than two usable markers; check the clip/reference range")

    warnings = []
    if peak < 0.2:
        warnings.append("low correlation; verify the take and tempo before applying")
    if drift_s > args.max_drift_s:
        warnings.append(
            "window lag varies by %.3f s; a constant-speed map may not stay aligned"
            % drift_s
        )
    if not stable:
        warnings.append("no window reached correlation 0.2; the offset is weak")
    if args.reference_end_beat is None:
        warnings.append("reference_end_beat was inferred from file duration; pass the clip end if trimmed")

    return {
        "vocal": str(vocal_path),
        "reference": str(reference_path),
        "source_bpm": source_bpm,
        "target_bpm": target_bpm,
        "rate": round(rate, 9),
        "duration_s": round(duration, 6),
        "reference_duration_s": round(len(reference) / sr, 6),
        "correlation": round(peak, 4),
        "lag_s": round(offset_s, 6),
        "lag_windows": windows,
        "lag_spread_s": round(drift_s, 6),
        "stable": bool(stable) and drift_s <= args.max_drift_s,
        "reference_start_beat": reference_start_beat,
        "reference_end_beat": reference_end_beat,
        "clip_start_beat": clip_start_beat,
        "start_marker": round(start_marker, 6),
        "end_marker": round(end_marker, 6),
        "markers": markers,
        "marker_count": len(markers),
        "warnings": warnings,
        "apply_args": {
            "markers": markers,
            "start_marker": round(start_marker, 6),
            "end_marker": round(end_marker, 6),
            "replace": True,
            "dry_run": True,
        },
        "method": "onset cross-correlation in the 250-5000 Hz band; constant-rate mapping",
        "limits": [
            "not a listening test",
            "constant-rate map; it does not correct per-phrase drift",
            "reference end must be supplied when the reference clip is trimmed",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure a vocal stem against a full-mix reference and emit a warp map."
    )
    parser.add_argument("--vocal", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--source-bpm", required=True)
    parser.add_argument("--target-bpm", required=True)
    parser.add_argument("--rate", default=None, help="Override target/source tempo ratio.")
    parser.add_argument("--reference-start-beat", required=True)
    parser.add_argument(
        "--reference-end-beat",
        default=None,
        help="Beat where the reference clip ends; required when the clip is trimmed.",
    )
    parser.add_argument("--reference-offset-s", default=0.0)
    parser.add_argument("--clip-start-beat", required=True)
    parser.add_argument("--step-beats", type=float, default=4.0)
    parser.add_argument("--window-s", type=float, default=20.0)
    parser.add_argument("--step-s", type=float, default=5.0)
    parser.add_argument("--max-lag-s", type=float, default=3.0)
    parser.add_argument("--max-drift-s", type=float, default=0.10)
    parser.add_argument("--sample-rate", type=int, default=22050)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.step_beats <= 0:
        raise SystemExit("step_beats must be positive")

    result = build_map(args)
    path = Path(args.out).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(path),
        "rate": result["rate"],
        "lag_s": result["lag_s"],
        "correlation": result["correlation"],
        "stable": result["stable"],
        "start_marker": result["start_marker"],
        "end_marker": result["end_marker"],
        "marker_count": result["marker_count"],
        "warnings": result["warnings"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

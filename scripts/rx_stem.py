#!/usr/bin/env python
"""Isolate or remove one RX 12 Music Rebalance stem without touching Live.

The plugin exposes exactly four music stems: Vocal, Bass, Drums and Other.
There is no Piano control; piano is inside Other and cannot be separated from it
by this plugin.

Examples:
    uv run --with pedalboard --with librosa --with soundfile python \
        scripts/rx_stem.py --plugin "path/to/RX 12 Music Rebalance.vst3" \
        --source "song.wav" --stem vocals --mode isolate

    ... --stem other --mode isolate       # includes piano, guitars, keys, etc.
    ... --stem vocals --mode remove       # residual mix with vocals muted
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from pedalboard import load_plugin

STEM_ALIASES = {
    "vocals": "vocal",
    "vocal": "vocal",
    "bass": "bass",
    "drums": "drums",
    "other": "other",
}
STEM_LABELS = {"vocal": "vocals", "bass": "bass", "drums": "drums", "other": "other"}


def _appdata() -> Path:
    root = os.environ.get("APPDATA")
    return Path(root) / "Enableton" if root else Path.home() / ".enableton"


def _safe_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" .")
    return value or "stem"


def _load_audio(path: Path) -> tuple[np.ndarray, int]:
    audio, sr = librosa.load(str(path), sr=None, mono=False)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=0)
    return np.asarray(audio, dtype=np.float32), int(sr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plugin",
        default=os.environ.get("ENABLETON_RX_PLUGIN"),
        help="path to RX 12 Music Rebalance.vst3 (or set ENABLETON_RX_PLUGIN)",
    )
    parser.add_argument("--source", required=True, help="absolute path to the WAV")
    parser.add_argument(
        "--stem",
        required=True,
        choices=sorted(STEM_ALIASES),
        help="vocals, bass, drums, other; there is no piano stem",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("isolate", "remove"),
        help="isolate the stem or mute it in the residual mix",
    )
    parser.add_argument("--out", help="output WAV; defaults under %%APPDATA%%\\Enableton\\stems")
    parser.add_argument("--start", type=float, help="optional start second; default full file")
    parser.add_argument("--duration", type=float, help="optional duration; default to end")
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=50.0,
        help="target stem sensitivity, 0-100 (default 50)",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace the output WAV")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        print(f"source not found: {source}", file=sys.stderr)
        return 2
    if not args.plugin:
        print(
            "RX 12 Music Rebalance path missing; pass --plugin or set ENABLETON_RX_PLUGIN",
            file=sys.stderr,
        )
        return 2
    plugin_path = Path(args.plugin).expanduser().resolve()
    if not plugin_path.is_file():
        print(f"RX 12 Music Rebalance not found: {plugin_path}", file=sys.stderr)
        return 2
    if not 0.0 <= args.sensitivity <= 100.0:
        print("--sensitivity must be between 0 and 100", file=sys.stderr)
        return 2

    key = STEM_ALIASES[args.stem]
    label = STEM_LABELS[key]
    audio, sr = _load_audio(source)
    total = audio.shape[1] / sr
    start = max(0.0, args.start or 0.0)
    if start >= total:
        print(f"--start {start} is past the end of the file", file=sys.stderr)
        return 2
    duration = total - start if args.duration is None else min(args.duration, total - start)
    if duration <= 0:
        print("duration must be positive", file=sys.stderr)
        return 2
    segment = audio[:, int(start * sr) : int((start + duration) * sr)].copy()

    plugin = load_plugin(str(plugin_path))
    plugin.quality = "Best / Offline"
    if hasattr(plugin, "global_bypass"):
        plugin.global_bypass = False

    # Start from a neutral four-stem balance, then use the plugin's own solo/mute.
    for stem_key in ("vocal", "bass", "drums", "other"):
        for suffix, value in (
            ("_gain_db", 0.0),
            ("_sensitivity", 50.0),
            ("_solo", False),
            ("_mute", False),
        ):
            name = f"{stem_key}{suffix}"
            if hasattr(plugin, name):
                setattr(plugin, name, value)
    setattr(plugin, f"{key}_sensitivity", args.sensitivity)
    if args.mode == "isolate":
        setattr(plugin, f"{key}_solo", True)
    else:
        setattr(plugin, f"{key}_mute", True)

    rendered = np.asarray(plugin.process(segment, sr, reset=True), dtype=np.float32)
    if rendered.ndim == 1:
        rendered = np.stack([rendered, rendered], axis=0)
    if rendered.shape[0] > 2:
        rendered = rendered[:2]
    rms = float(np.sqrt(np.mean(rendered**2)))
    peak = float(np.max(np.abs(rendered)))
    if args.mode == "isolate" and rms <= 1e-7:
        print(f"RX {label} stem is silent; refusing to write output", file=sys.stderr)
        return 2

    if args.out:
        out = Path(args.out).expanduser().resolve()
    else:
        suffix = "isolated" if args.mode == "isolate" else "removed"
        out = _appdata() / "stems" / f"{_safe_name(source.stem)} - {label} ({suffix}).wav"
    if out == source:
        print("refusing to overwrite the source WAV", file=sys.stderr)
        return 2
    if out.exists() and not args.overwrite:
        print(f"output exists; pass --overwrite: {out}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), rendered.T, sr, subtype="PCM_24")

    report = {
        "source_file": str(source),
        "output_file": str(out),
        "mode": args.mode,
        "stem": label,
        "piano_note": "No piano stem exists; piano is part of Other.",
        "plugin": str(plugin_path),
        "plugin_version": str(getattr(plugin, "version", "unknown")),
        "quality": str(getattr(plugin, "quality", "unknown")),
        "sample_rate_hz": sr,
        "channels": int(rendered.shape[0]),
        "duration_s": round(rendered.shape[1] / sr, 6),
        "window_s": [round(start, 6), round(start + duration, 6)],
        "sensitivity": args.sensitivity,
        "solo": {
            key: bool(getattr(plugin, f"{key}_solo", False))
            for key in ("vocal", "bass", "drums", "other")
        },
        "mute": {
            key: bool(getattr(plugin, f"{key}_mute", False))
            for key in ("vocal", "bass", "drums", "other")
        },
        "rms": round(rms, 8),
        "sample_peak": round(peak, 8),
    }
    report_path = out.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"output     {out}")
    print(f"report     {report_path}")
    print(f"mode       {args.mode} {label}")
    print(f"window     {start:.3f}–{start + duration:.3f}s  {duration:.3f}s")
    print(f"audio      {sr} Hz, {rendered.shape[0]} ch, RMS {rms:.6f}, peak {peak:.6f}")
    if key == "other":
        print("note       Other includes piano plus guitars/keys/other instruments; no piano-only stem.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Analyze a vocal WAV and render an optional conservative RX/Nectar repair chain.

This script does not touch Live and does not claim to have heard the result. It
analyzes the source, applies only the RX modules explicitly requested, and can
add a fixed Nectar level/compressor/de-esser chain. Pitch is applied only when a
key is supplied; Nectar Vocal Assistant has no exposed parameter and is left as a
manual UI step.

Examples:
    One command, using the saved recipe (key, thresholds, plug-in paths and source folder):

    uv run --with pedalboard --with librosa --with soundfile python \
        scripts/vocal_repair.py --auto

    Analyze only:

    uv run --with pedalboard --with librosa --with soundfile python \
        scripts/vocal_repair.py --source "vocal.wav" --analyze-only

    Manual chain override:

    ... --source "vocal.wav" \
        --rx-modules deplosive,mouth_declick,denoise,deess \
        --nectar --nectar-dir "C:\\Program Files\\Common Files\\VST3\\iZotope" \
        --key Dmin
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from pedalboard import load_plugin

RX_MODULES = {
    "declip": ("RX 12 De-clip.vst3", {
        "clipping_threshold": -1.0,
        "makeup_gain": 0.0,
        "quality": "High",
        "post_limiter": True,
    }),
    "deplosive": ("RX 12 De-plosive.vst3", {
        "sensitivity": 3.0,
        "strength": 3.0,
        "frequency_limit_hz": 120.0,
    }),
    "mouth_declick": ("RX 12 Mouth De-click.vst3", {
        "sensitivity": 3.0,
        "frequency_skew": 0.0,
    }),
    "denoise": ("RX 12 Voice De-noise.vst3", {
        "reduction": 6.0,
        "optimize_for": "Music",
        "adaptive_mode": True,
        "filter_type": "Surgical",
    }),
    "dereverb": ("RX 12 De-reverb.vst3", {
        "reduction": 3.0,
        "tail_length": 1.0,
        "artifact_smoothing": 9.0,
        "band_strength_low": 3.0,
        "band_strength_low_mid": 3.0,
        "band_strength_high_mid": 3.0,
        "band_strength_high": 3.0,
    }),
    "deess": ("RX 12 De-ess.vst3", {
        "threshold": -18.0,
        "cutoff_freq": 6500.0,
        "spectral_shaping": 50.0,
        "speed": "Fast",
    }),
}

NECTAR_MODULES = {
    "auto_level": ("Nectar 4 Auto-Level.vst3", {
        "alm_target_level_db": -18.0,
        "alm_strength": 30.0,
        "alm_range_db": 6.0,
        "alm_tame_noises": False,
    }),
    "compressor": ("Nectar 4 Compressor.vst3", {
        "comp_threshold_db": -18.0,
        "comp_ratio": 2.5,
        "comp_attack_ms": 10.0,
        "comp_release_ms": 100.0,
        "comp_auto_gain": False,
    }),
    "deesser": ("Nectar 4 DeEsser.vst3", {
        "deesser_frequency_hz": 6500.0,
        "deesser_threshold_db": -18.0,
        "deesser_listen": False,
    }),
    "pitch": ("Nectar 4 Pitch.vst3", {
        "pitch_speed_ms": 20.0,
        "pitch_strength": 50.0,
        "pitch_transposition_st": 0.0,
        "pitch_formant_preservation": True,
    }),
}

NOTE_NAMES = {
    "c": "C", "c#": "C#", "db": "C#", "d": "D", "d#": "D#", "eb": "D#",
    "e": "E", "f": "F", "f#": "F#", "gb": "F#", "g": "G", "g#": "G#",
    "ab": "G#", "a": "A", "a#": "A#", "bb": "A#", "b": "B",
}

# Nectar's Pitch root control uses the combined sharp/flat display labels, not "C#".
PITCH_ROOT_VALUES = {
    "C": "C",
    "C#": "C\u266f / D\u266d",
    "D": "D",
    "D#": "D\u266f / E\u266d",
    "E": "E",
    "F": "F",
    "F#": "F\u266f / G\u266d",
    "G": "G",
    "G#": "G\u266f / A\u266d",
    "A": "A",
    "A#": "A\u266f / B\u266d",
    "B": "B",
}


def _appdata() -> Path:
    root = os.environ.get("APPDATA")
    return Path(root) / "Enableton" if root else Path.home() / ".enableton"


DEFAULT_RECIPE_ID = "vocal_repair.minimal"


def _default_recipe_path() -> Path:
    return _appdata() / "vocal-repair" / "recipes" / f"{DEFAULT_RECIPE_ID}.json"


def _load_recipe(path: Path, explicit: bool) -> dict:
    if not path.is_file():
        if explicit:
            raise ValueError(f"recipe not found: {path}")
        return {}
    try:
        recipe = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read recipe {path}: {exc}") from exc
    if not isinstance(recipe, dict):
        raise ValueError(f"recipe must be a JSON object: {path}")
    if recipe.get("version") != 1:
        raise ValueError(f"unsupported recipe version in {path}")
    if not isinstance(recipe.get("id"), str) or not recipe["id"]:
        raise ValueError(f"recipe needs a non-empty id: {path}")
    return recipe


def _latest_source(recipe: dict) -> tuple[Path, str]:
    config = recipe.get("source") or {}
    latest_in = config.get("latest_in")
    if not latest_in:
        raise ValueError("no source supplied and the recipe has no source.latest_in")
    root = Path(os.path.expandvars(str(latest_in))).expanduser()
    if not root.is_dir():
        raise ValueError(f"recipe source directory not found: {root}")
    pattern = str(config.get("pattern") or "*.wav")
    extensions = {".wav", ".aif", ".aiff", ".flac"}
    files = [
        path for path in root.glob(pattern)
        if path.is_file() and path.suffix.lower() in extensions
    ]
    if not files:
        raise ValueError(f"no audio file in {root} matching {pattern!r}")
    newest = max(files, key=lambda path: path.stat().st_mtime)
    return newest, f"latest in {root} matching {pattern}"


def _auto_modules(metrics: dict, recipe: dict, nectar: bool, nectar_modules: list[str]) -> tuple[list[str], list[dict]]:
    rules = recipe.get("auto_rx") or {}
    modules: list[str] = []
    reasons: list[dict] = []

    if rules.get("declip_if_clipped", True) and metrics.get("clipped_samples", 0) > 0:
        modules.append("declip")
        reasons.append({"module": "declip", "selected": True, "reason": f"{metrics['clipped_samples']} clipped samples"})

    threshold = rules.get("denoise_if_noise_floor_dbfs_at_or_above", -50.0)
    noise_floor = metrics.get("noise_floor_dbfs")
    if threshold is not None and noise_floor is not None and noise_floor >= float(threshold):
        modules.append("denoise")
        reasons.append({"module": "denoise", "selected": True, "reason": f"noise floor {noise_floor} dBFS >= {threshold} dBFS"})

    sibilance_threshold = rules.get("deess_if_sibilance_share_at_or_above", 0.012)
    sibilance = metrics.get("sibilance_4k_10k_share")
    if sibilance_threshold is not None and sibilance is not None and sibilance >= float(sibilance_threshold):
        if nectar and "deesser" in nectar_modules:
            reasons.append({"module": "deess", "selected": False, "reason": "Nectar De-esser already covers sibilance"})
        else:
            modules.append("deess")
            reasons.append({"module": "deess", "selected": True, "reason": f"sibilance share {sibilance} >= {sibilance_threshold}"})

    return modules, reasons


def _recipe_output(source: Path, recipe: dict) -> Path:
    config = recipe.get("output") or {}
    directory = config.get("directory")
    root = Path(os.path.expandvars(str(directory))).expanduser() if directory else _appdata() / "vocal-repair"
    suffix = str(config.get("suffix") or " - repaired")
    return root / f"{_safe_name(source.stem)}{suffix}.wav"


def _free_output(path: Path) -> Path:
    if not path.exists():
        return path
    for number in range(2, 1000):
        candidate = path.with_name(f"{path.stem} {number}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError(f"could not find a free output name near {path}")


def _safe_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" .")
    return value or "vocal"


def _db(value: float) -> float | None:
    return round(20.0 * math.log10(value), 3) if value > 0 else None


def _plain(value):
    if isinstance(value, (str, bool, int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _metrics(audio: np.ndarray, sr: int) -> dict:
    mono = audio.mean(axis=0)
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio**2)))
    frames = librosa.util.frame(mono, frame_length=2048, hop_length=512)
    frame_rms = np.sqrt(np.mean(frames**2, axis=0))
    noise_floor = float(np.percentile(frame_rms, 20))
    spectrum = np.abs(librosa.stft(mono, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    power = spectrum**2
    total = float(power.sum()) + 1e-15

    def band(low: float, high: float) -> float:
        return float(power[(freqs >= low) & (freqs < high)].sum()) / total

    return {
        "duration_s": round(audio.shape[1] / sr, 6),
        "sample_rate_hz": sr,
        "channels": int(audio.shape[0]),
        "peak": round(peak, 8),
        "peak_dbfs": _db(peak),
        "clipped_samples": int(np.count_nonzero(np.abs(audio) >= 0.999)),
        "rms": round(rms, 8),
        "rms_dbfs": _db(rms),
        "crest_factor_db": round(_db(peak) - _db(rms), 3) if peak and rms else None,
        "dc_offset": round(float(np.mean(mono)), 8),
        "noise_floor_rms": round(noise_floor, 8),
        "noise_floor_dbfs": _db(noise_floor),
        "low_30_150_share": round(band(30, 150), 6),
        "sibilance_4k_10k_share": round(band(4000, 10000), 6),
        "high_10k_16k_share": round(band(10000, 16000), 6),
    }


def _load_audio(path: Path) -> tuple[np.ndarray, int]:
    audio, sr = librosa.load(str(path), sr=None, mono=False)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=0)
    return np.asarray(audio, dtype=np.float32), int(sr)


def _apply(plugin_path: Path, audio: np.ndarray, sr: int, attrs: dict) -> tuple[np.ndarray, dict]:
    plugin = load_plugin(str(plugin_path))
    applied = {}
    for key, value in attrs.items():
        if not hasattr(plugin, key):
            raise RuntimeError(f"{plugin_path.name}: parameter {key!r} is not exposed")
        setattr(plugin, key, value)
        applied[key] = _plain(getattr(plugin, key))
    out = np.asarray(plugin.process(audio, sr, reset=True), dtype=np.float32)
    if out.ndim == 1:
        out = np.stack([out, out], axis=0)
    if out.shape[0] > 2:
        out = out[:2]
    return out, {
        "plugin": plugin_path.name,
        "version": str(getattr(plugin, "version", "unknown")),
        "parameters": applied,
    }


def _parse_key(value: str | None) -> tuple[str, str | None]:
    if not value:
        return "NoKey", None
    cleaned = re.sub(r"\s+", "", value).lower().replace("minor", "min").replace("major", "maj")
    match = re.fullmatch(r"([a-g](?:#|b)?)(min|m|maj|major)?", cleaned)
    if not match or match.group(1) not in NOTE_NAMES:
        raise ValueError(f"unsupported key {value!r}; use e.g. Dmin, F#maj, C")
    root = NOTE_NAMES[match.group(1)]
    suffix = match.group(2)
    scale = "Minor" if suffix in ("min", "m") else "Major" if suffix in ("maj", "major") else "NoKey"
    return scale, root


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", help="vocal WAV; defaults to the newest recipe match")
    parser.add_argument(
        "--recipe",
        help="recipe JSON; with --auto defaults to the configured vocal-repair recipe",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="load the recipe, pick the newest matching source and select RX modules from measured metrics",
    )
    parser.add_argument("--rx-dir", help="RX VST3 directory (default: ENABLETON_RX_DIR or recipe)")
    parser.add_argument(
        "--nectar-dir",
        help="Nectar VST3 directory (default: ENABLETON_NECTAR_DIR or recipe)",
    )
    parser.add_argument(
        "--rx-modules",
        default=None,
        help="comma list overriding auto selection: declip,deplosive,mouth_declick,denoise,dereverb,deess",
    )
    parser.add_argument("--nectar", action="store_true", help="force the Nectar chain")
    parser.add_argument(
        "--no-nectar",
        action="store_true",
        help="disable the Nectar chain even when the recipe enables it",
    )
    parser.add_argument(
        "--no-pitch",
        action="store_true",
        help="disable Nectar Pitch even when the recipe or --key supplies one",
    )
    parser.add_argument(
        "--key",
        help=(
            "manually read key/scale for Nectar Pitch, e.g. Dmin; omit to skip tuning. "
            "Read the key from Auto-Key or Live Key; neither result is read by this script."
        ),
    )
    parser.add_argument(
        "--pitch-strength",
        type=float,
        default=None,
        help="0-100 (default: recipe value, else 50)",
    )
    parser.add_argument("--out")
    parser.add_argument("--start", type=float)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()

    recipe: dict = {}
    recipe_path: Path | None = None
    if args.recipe or args.auto:
        recipe_path = (
            Path(args.recipe).expanduser().resolve()
            if args.recipe
            else _default_recipe_path()
        )
        try:
            recipe = _load_recipe(recipe_path, explicit=True)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    if args.source:
        source = Path(args.source).expanduser().resolve()
        source_selection = "supplied with --source"
    elif recipe:
        try:
            source, source_selection = _latest_source(recipe)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    else:
        print("--source is required when no recipe supplies a source", file=sys.stderr)
        return 2
    if not source.is_file():
        print(f"source not found: {source}", file=sys.stderr)
        return 2

    pitch = recipe.get("pitch") or {}
    key = args.key or pitch.get("key")
    key_source = "--key" if args.key else (f"recipe {recipe_path}" if key else None)
    pitch_strength = (
        args.pitch_strength
        if args.pitch_strength is not None
        else float(pitch.get("strength", 50.0))
    )
    try:
        scale, root = _parse_key(key)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not 0.0 <= pitch_strength <= 100.0:
        print("--pitch-strength must be 0-100", file=sys.stderr)
        return 2

    nectar_config = recipe.get("nectar") or {}
    nectar_enabled = bool(args.nectar)
    if args.auto:
        nectar_enabled = bool(nectar_config.get("enabled", False))
    if args.no_nectar:
        nectar_enabled = False
    nectar_modules = [
        str(item)
        for item in (
            nectar_config.get("modules")
            or ["auto_level", "compressor", "deesser", "pitch"]
        )
    ]
    unknown_nectar = [item for item in nectar_modules if item not in NECTAR_MODULES]
    if unknown_nectar:
        print(
            f"recipe has unknown Nectar module(s): {', '.join(unknown_nectar)}",
            file=sys.stderr,
        )
        return 2
    pitch_enabled = not args.no_pitch and "pitch" in nectar_modules

    if args.rx_modules is not None:
        modules = [x.strip() for x in args.rx_modules.split(",") if x.strip()]
        modules_source = "--rx-modules (manual)"
    else:
        modules = []
        modules_source = "auto selection" if args.auto else "none"
    unknown = [x for x in modules if x not in RX_MODULES]
    if unknown:
        print(f"unknown RX module(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    audio, sr = _load_audio(source)
    total = audio.shape[1] / sr
    start = max(0.0, args.start or 0.0)
    duration = total - start if args.duration is None else min(args.duration, total - start)
    if duration <= 0:
        print("empty analysis/render window", file=sys.stderr)
        return 2
    segment = audio[:, int(start * sr) : int((start + duration) * sr)].copy()
    metrics = _metrics(segment, sr)

    auto_reasons: list[dict] = []
    if args.auto and args.rx_modules is None:
        modules, auto_reasons = _auto_modules(
            metrics, recipe, nectar_enabled, nectar_modules
        )

    report = {
        "recipe": (
            {"id": recipe.get("id"), "path": str(recipe_path)} if recipe else None
        ),
        "source_file": str(source),
        "source_selection": source_selection,
        "source_analysis": metrics,
        "window_s": [round(start, 6), round(start + duration, 6)],
        "modules_requested": modules,
        "modules_source": modules_source,
        "auto_selection": auto_reasons,
        "nectar_requested": nectar_enabled,
        "nectar_modules": nectar_modules if nectar_enabled else [],
        "key": key,
        "key_source": key_source,
        "pitch_scale": scale,
        "pitch_root": root,
        "pitch_strength": pitch_strength,
        "pitch_enabled": pitch_enabled,
        "pitch_applied": bool(
            nectar_enabled and key and scale != "NoKey" and pitch_enabled
        ),
        "vocal_assistant_exposed": False,
        "not_claimed": "No listening or artifact assessment was performed.",
        "missing_capabilities": [
            "Nectar Vocal Assistant is not exposed as a parameter; it remains a manual UI step.",
            "Auto-Key exposes only bypass; its detected key is display/Send-to-Auto-Tune only.",
            "Live Key's detected key is display-only; this build cannot read master-chain parameters.",
            "RX Repair Assistant proposal analysis is not reproducible through its VST3 controls.",
            "RX standalone spectral editing is not automated.",
            "Live cannot insert these plug-ins on this build; no Live device or clip was changed.",
        ],
        "chain": [],
    }

    if args.analyze_only or (not modules and not nectar_enabled):
        out = _appdata() / "vocal-repair" / f"{_safe_name(source.stem)} - analysis.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"analysis   {out}")
        print("no processing requested; source untouched")
        return 0

    processed = segment
    if modules:
        rx_dir_value = (
            args.rx_dir
            or os.environ.get("ENABLETON_RX_DIR")
            or (recipe.get("plugins") or {}).get("rx_dir")
        )
        if not rx_dir_value:
            print(
                "--rx-dir, ENABLETON_RX_DIR or a recipe plugins.rx_dir is required for RX modules",
                file=sys.stderr,
            )
            return 2
        rx_dir = Path(rx_dir_value).expanduser().resolve()
        for name in modules:
            filename, attrs = RX_MODULES[name]
            processed, info = _apply(rx_dir / filename, processed, sr, attrs)
            info["stage"] = name
            report["chain"].append(info)

    if nectar_enabled:
        nectar_dir_value = (
            args.nectar_dir
            or os.environ.get("ENABLETON_NECTAR_DIR")
            or (recipe.get("plugins") or {}).get("nectar_dir")
        )
        if not nectar_dir_value:
            print(
                "--nectar-dir, ENABLETON_NECTAR_DIR or a recipe plugins.nectar_dir is required for Nectar",
                file=sys.stderr,
            )
            return 2
        nectar_dir = Path(nectar_dir_value).expanduser().resolve()
        for name in ("auto_level", "compressor", "deesser"):
            if name not in nectar_modules:
                continue
            filename, attrs = NECTAR_MODULES[name]
            processed, info = _apply(nectar_dir / filename, processed, sr, attrs)
            info["stage"] = f"nectar:{name}"
            report["chain"].append(info)
        if pitch_enabled:
            if key and scale != "NoKey":
                filename, attrs = NECTAR_MODULES["pitch"]
                attrs = dict(attrs)
                attrs.update(
                    {
                        "pitch_root_note": PITCH_ROOT_VALUES[root],
                        "pitch_scale": scale,
                        "pitch_strength": pitch_strength,
                    }
                )
                processed, info = _apply(nectar_dir / filename, processed, sr, attrs)
                info["stage"] = "nectar:pitch"
                report["chain"].append(info)
            else:
                report["chain"].append(
                    {
                        "stage": "nectar:pitch",
                        "status": "skipped",
                        "reason": (
                            "no complete key/scale supplied; tuning would require assuming the song key"
                        ),
                    }
                )

    if args.out:
        output = Path(args.out).expanduser().resolve()
        if output.exists() and not args.overwrite:
            print(f"output exists; pass --overwrite: {output}", file=sys.stderr)
            return 2
    elif recipe:
        output = _recipe_output(source, recipe)
        if not args.overwrite:
            output = _free_output(output)
    else:
        output = _appdata() / "vocal-repair" / f"{_safe_name(source.stem)} - repaired.wav"
        if output.exists() and not args.overwrite:
            print(f"output exists; pass --overwrite: {output}", file=sys.stderr)
            return 2
    if output == source:
        print("refusing to overwrite the source WAV", file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), processed.T, sr, subtype="PCM_24")

    report["output_file"] = str(output)
    report["output_analysis"] = _metrics(processed, sr)
    report["not_claimed"] = (
        "No listening or artifact assessment was performed. This is a conservative "
        "candidate; the user must A/B it against the source."
    )
    report_path = output.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"source     {source}")
    if recipe:
        print(f"recipe     {recipe.get('id')}  {recipe_path}")
        print(f"selected   {', '.join(modules) or 'none'}  ({modules_source})")
    print(f"output     {output}")
    print(f"report     {report_path}")
    print(f"window     {start:.3f}–{start + duration:.3f}s  {duration:.3f}s")
    print(f"chain      {', '.join(item.get('stage', '?') for item in report['chain'])}")
    print(f"pitch      {'applied' if report['pitch_applied'] else 'skipped / no key'}")
    print(
        f"input      peak {report['source_analysis']['peak_dbfs']} dBFS, "
        f"RMS {report['source_analysis']['rms_dbfs']} dBFS"
    )
    print(
        f"output     peak {report['output_analysis']['peak_dbfs']} dBFS, "
        f"RMS {report['output_analysis']['rms_dbfs']} dBFS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Structural fingerprints for recipe contracts.

A fingerprint is a small set of values the snapshot can prove: tempo, counts and arrangement
length. It is deliberately not an audio render, LUFS measurement or spectral claim. Those belong
to the audio tiers and keep their own verification gates.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Dict, List


FINGERPRINT_METRICS = (
    "tempo_bpm",
    "track_count",
    "arrangement_clip_count",
    "session_clip_count",
    "clip_count",
    "note_count",
    "device_count",
    "bars",
)
COUNT_METRICS = {
    "track_count",
    "arrangement_clip_count",
    "session_clip_count",
    "clip_count",
    "note_count",
    "device_count",
    "bars",
}


class FingerprintError(ValueError):
    """A recipe fingerprint is malformed or names an unsupported metric."""


def _number(value: object, path: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FingerprintError(f"{path} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise FingerprintError(f"{path} must be a finite number at least {minimum:g}")
    return number


def parse_fingerprint(raw: object) -> Dict[str, Dict[str, float]]:
    """Validate and normalize an expected fingerprint without measuring anything."""
    if not isinstance(raw, Mapping):
        raise FingerprintError("fingerprint must be an object")
    if not raw:
        raise FingerprintError("fingerprint must contain at least one metric")

    parsed: Dict[str, Dict[str, float]] = {}
    for name, spec in raw.items():
        if name not in FINGERPRINT_METRICS:
            raise FingerprintError(
                "unknown metric %r; supported: %s" % (name, ", ".join(FINGERPRINT_METRICS))
            )
        tolerance = 0.0
        value = spec
        if isinstance(spec, Mapping):
            unknown = sorted(set(spec) - {"value", "tolerance"})
            if unknown:
                raise FingerprintError(
                    "%s has unknown key(s): %s" % (name, ", ".join(unknown))
                )
            if "value" not in spec:
                raise FingerprintError("%s needs a value" % name)
            value = spec["value"]
            if "tolerance" in spec:
                tolerance = _number(spec["tolerance"], "%s.tolerance" % name)

        number = _number(value, name, minimum=0.001 if name == "tempo_bpm" else 0.0)
        if name in COUNT_METRICS and not number.is_integer():
            raise FingerprintError("%s must be a whole number" % name)
        parsed[name] = {
            "value": int(number) if name in COUNT_METRICS else number,
            "tolerance": tolerance,
        }
    return parsed


def _beats_per_bar(song: Mapping[str, Any]) -> float:
    signature = song.get("signature") or [4, 4]
    try:
        numerator, denominator = int(signature[0]), int(signature[1])
    except (IndexError, TypeError, ValueError):
        return 4.0
    if numerator <= 0 or denominator <= 0:
        return 4.0
    return numerator * 4.0 / denominator


def _clips(track: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    clips: List[Mapping[str, Any]] = []
    clips.extend(track.get("arrangement") or [])
    clips.extend((track.get("session") or {}).get("clips") or [])
    return clips


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _session_count(track: Mapping[str, Any]) -> int:
    session = track.get("session") or {}
    filled = _int_or_none(session.get("filled"))
    if filled is not None:
        return filled
    return len(session.get("clips") or [])


def measure_snapshot(data: Mapping[str, Any]) -> Dict[str, Any]:
    """Measure the snapshot-only metrics a recipe can claim, with honest gaps."""
    song = data.get("song") or {}
    tracks = data.get("tracks") or []
    counts = data.get("counts") or {}
    metrics: Dict[str, float] = {}
    unavailable: Dict[str, str] = {}

    tempo = song.get("tempo")
    if isinstance(tempo, bool) or not isinstance(tempo, (int, float)) or tempo <= 0:
        unavailable["tempo_bpm"] = "the snapshot does not carry a positive tempo"
    else:
        metrics["tempo_bpm"] = float(tempo)

    arrangement = _int_or_none(counts.get("arrangement_clips"))
    if arrangement is None:
        arrangement = sum(len(track.get("arrangement") or []) for track in tracks)
    metrics["arrangement_clip_count"] = arrangement

    session = _int_or_none(counts.get("session_clips"))
    if session is None:
        session = sum(_session_count(track) for track in tracks)
    metrics["session_clip_count"] = session
    metrics["clip_count"] = arrangement + session

    track_count = _int_or_none(counts.get("tracks"))
    metrics["track_count"] = track_count if track_count is not None else len(tracks)

    devices = _int_or_none(counts.get("devices_total"))
    if devices is None:
        devices = sum(int(track.get("device_count") or 0) for track in tracks)
        devices += int((data.get("master_track") or {}).get("device_count") or 0)
    metrics["device_count"] = devices

    note_total = 0
    note_problem = None
    for track in tracks:
        for clip in _clips(track):
            if not clip.get("midi"):
                continue
            note_count = clip.get("note_count")
            if isinstance(note_count, bool) or not isinstance(note_count, int):
                note_problem = (
                    "a MIDI clip has no readable note count; re-read the snapshot after "
                    "note capture is available"
                )
                continue
            note_total += note_count
    if note_problem is None:
        metrics["note_count"] = note_total
    else:
        unavailable["note_count"] = note_problem

    per_bar = _beats_per_bar(song)
    end = 0.0
    for track in tracks:
        for clip in track.get("arrangement") or []:
            try:
                end = max(end, float(clip.get("end") or 0.0))
            except (TypeError, ValueError):
                continue
    metrics["bars"] = int(math.ceil(end / per_bar)) if end > 0 else 0

    return {"metrics": metrics, "unavailable": unavailable}


def compare_fingerprint(raw: object, measured: Mapping[str, Any]) -> Dict[str, Any]:
    """Compare expected values to measurements without turning a gap into a pass."""
    expected = parse_fingerprint(raw)
    actual_metrics = measured.get("metrics") or {}
    measured_unavailable = measured.get("unavailable") or {}

    rows = []
    matched = 0
    mismatched = 0
    missing = 0
    for name, spec in expected.items():
        actual = actual_metrics.get(name)
        if actual is None:
            missing += 1
            rows.append(
                {
                    "metric": name,
                    "expected": spec["value"],
                    "actual": None,
                    "tolerance": spec["tolerance"],
                    "delta": None,
                    "status": "unavailable",
                    "reason": measured_unavailable.get(name)
                    or "the snapshot does not carry this metric",
                }
            )
            continue

        delta = float(actual) - float(spec["value"])
        ok = abs(delta) <= float(spec["tolerance"]) + 1e-9
        if ok:
            matched += 1
        else:
            mismatched += 1
        rows.append(
            {
                "metric": name,
                "expected": spec["value"],
                "actual": actual,
                "tolerance": spec["tolerance"],
                "delta": round(delta, 6),
                "status": "match" if ok else "mismatch",
            }
        )

    if mismatched:
        status = "mismatch"
    elif missing == len(rows):
        status = "unavailable"
    elif missing:
        status = "partial"
    else:
        status = "match"

    return {
        "status": status,
        "matched": matched,
        "mismatched": mismatched,
        "unavailable": missing,
        "metrics": rows,
    }


__all__ = [
    "COUNT_METRICS",
    "FINGERPRINT_METRICS",
    "FingerprintError",
    "compare_fingerprint",
    "measure_snapshot",
    "parse_fingerprint",
]
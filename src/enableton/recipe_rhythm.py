"""Compile a rhythm recipe into a MIDI note vector for an explicit target clip.

This is deliberately a *MIDI rendering*, not a sample build. A rhythm recipe's ``slots`` describe
source material in the Browser; resolving those sources and placing audio is the job of a future
``recipe_build``. Until that exists, a slot may declare an optional MIDI ``pitch``, and the caller
must name an existing MIDI clip. The compiler then turns the text lanes into notes and leaves the
sample bindings visibly unresolved.

No Live object is touched here. The result is an ordinary ``notes_replace`` step, so the existing
plan preflight, scratch copy and undo path still own every write.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Sequence

from .recipe_patterns import GRID_STEPS, RecipePatternError, parse_step_pattern

#: Every grid this compiler renders. ``1/8T`` is three steps per beat, ``1/16T`` six.
SUPPORTED_GRIDS = tuple(GRID_STEPS)
#: The straight default, kept for callers that predate triplet grids.
SUPPORTED_GRID = "1/16"
DEFAULT_VELOCITY = 0.8
MAX_NOTES = 10000


class RhythmCompileError(ValueError):
    """A rhythm cannot become a note vector without inventing data or capability."""


def _number(value: object, path: str, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RhythmCompileError("%s must be a number" % path)
    number = float(value)
    if not math.isfinite(number) or number < low or number > high:
        raise RhythmCompileError("%s must be between %s and %s" % (path, low, high))
    return number


def _pitch(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 127:
        raise RhythmCompileError("%s must be an integer from 0 to 127" % path)
    return value


def _jitter(key: str) -> float:
    """A stable signed fraction in [-1, 1), so the same recipe renders identically."""
    digest = hashlib.blake2s(key.encode("utf-8"), digest_size=4).digest()
    return (int.from_bytes(digest, "big") / 0xFFFFFFFF) * 2.0 - 1.0


def _grid(recipe: Mapping[str, Any]) -> tuple[str, int]:
    """Return the recipe's declared grid and its steps per 4/4 bar."""
    tempo = recipe.get("tempo")
    if not isinstance(tempo, Mapping):
        raise RhythmCompileError("recipe.tempo must be an object")
    grid = tempo.get("grid")
    steps = GRID_STEPS.get(grid) if isinstance(grid, str) else None
    if steps is None:
        raise RhythmCompileError(
            "recipe.tempo.grid is %r; this compiler supports %s"
            % (grid, ", ".join(repr(name) for name in SUPPORTED_GRIDS))
        )
    return grid, steps


def _target_args(target: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "track": str(target["track"]),
        "clip": str(target["clip"]),
    }
    if "location" in target:
        out["location"] = str(target["location"])
    if "slot" in target:
        out["slot"] = int(target["slot"])
    return out


def render_rhythm(
    recipe: Mapping[str, Any],
    target: Mapping[str, Any],
    pitch_map: Optional[Mapping[str, Any]] = None,
    *,
    beats_per_bar: float = 4.0,
    set_tempo: Optional[float] = None,
    target_length: Optional[float] = None,
) -> Dict[str, Any]:
    """Return a ``notes_replace`` step plus a render summary, or raise a reason.

    ``target_length`` is in beats when the snapshot can prove it. A Session clip has no readable
    length in the snapshot; the result says ``length_checked: false`` rather than claiming the
    pattern fits.
    """
    if target.get("location") not in (None, "arrangement", "session"):
        raise RhythmCompileError("target.location must be 'arrangement' or 'session'")
    if target.get("location") == "arrangement" and "slot" in target:
        raise RhythmCompileError("target.slot only applies to a Session clip")
    if "slot" in target and (
        isinstance(target["slot"], bool)
        or not isinstance(target["slot"], int)
        or target["slot"] < 0
    ):
        raise RhythmCompileError("target.slot must be a non-negative integer")

    if not isinstance(beats_per_bar, (int, float)) or isinstance(beats_per_bar, bool):
        raise RhythmCompileError("beats_per_bar must be a number")
    beats_per_bar = float(beats_per_bar)
    if not math.isfinite(beats_per_bar) or beats_per_bar <= 0:
        raise RhythmCompileError("beats_per_bar must be positive")

    grid, steps_per_bar = _grid(recipe)
    step_beats = float(beats_per_bar) / steps_per_bar
    length_bars = recipe.get("length_bars")
    if (
        isinstance(length_bars, bool)
        or not isinstance(length_bars, int)
        or length_bars < 1
    ):
        raise RhythmCompileError("recipe.length_bars must be a positive integer")
    total_beats = float(length_bars) * beats_per_bar
    if target_length is not None:
        if (
            isinstance(target_length, bool)
            or not isinstance(target_length, (int, float))
            or not math.isfinite(float(target_length))
            or float(target_length) < 0
        ):
            raise RhythmCompileError("target length is not a finite non-negative number")
        if float(target_length) + 1e-6 < total_beats:
            raise RhythmCompileError(
                "target clip is %.4g beats long; this %d-bar recipe needs %.4g beats"
                % (float(target_length), length_bars, total_beats)
            )

    lanes = recipe.get("lanes") or []
    slots = recipe.get("slots") or []
    if not isinstance(lanes, list) or not lanes:
        raise RhythmCompileError("recipe.lanes must be a non-empty array")
    if not isinstance(slots, list) or not slots:
        raise RhythmCompileError("recipe.slots must be a non-empty array")

    slot_rows = {}
    for index, slot in enumerate(slots):
        if not isinstance(slot, Mapping):
            raise RhythmCompileError("recipe.slots[%d] must be an object" % index)
        name = slot.get("slot")
        if not isinstance(name, str) or not name:
            raise RhythmCompileError("recipe.slots[%d].slot must be a name" % index)
        slot_rows[name] = (index, slot)

    overrides = dict(pitch_map or {})
    for name, value in overrides.items():
        if not isinstance(name, str) or not name:
            raise RhythmCompileError("pitch_map keys must be non-empty strings")
        overrides[name] = _pitch(value, "pitch_map.%s" % name)

    notes: List[Dict[str, Any]] = []
    lane_rows: List[Dict[str, Any]] = []
    sample_rows: List[Dict[str, Any]] = []
    for lane_index, lane in enumerate(lanes):
        if not isinstance(lane, Mapping):
            raise RhythmCompileError("recipe.lanes[%d] must be an object" % lane_index)
        slot_name = lane.get("slot")
        if not isinstance(slot_name, str) or slot_name not in slot_rows:
            raise RhythmCompileError(
                "recipe.lanes[%d] references slot %r, which has no definition"
                % (lane_index, slot_name)
            )
        slot_index, slot = slot_rows[slot_name]
        mode = slot.get("mode")
        if mode != "hit":
            raise RhythmCompileError(
                "slot %r uses mode %r; MIDI compilation supports only 'hit' slots"
                % (slot_name, mode)
            )
        count = slot.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count != 1:
            raise RhythmCompileError(
                "slot %r asks for %r samples; a MIDI slot must select exactly one"
                % (slot_name, count)
            )

        if slot_name in overrides:
            pitch = overrides[slot_name]
        elif "pitch" in slot:
            pitch = _pitch(slot.get("pitch"), "recipe.slots[%d].pitch" % slot_index)
        else:
            raise RhythmCompileError(
                "slot %r has no pitch; add slots[].pitch or pass pitch_map"
                % slot_name
            )

        try:
            bars = parse_step_pattern(lane.get("pattern"), steps_per_bar)
        except (RecipePatternError, TypeError) as exc:
            raise RhythmCompileError(
                "recipe.lanes[%d].pattern: %s" % (lane_index, exc)
            ) from exc
        if length_bars % len(bars):
            raise RhythmCompileError(
                "lane %r has %d pattern bars, which do not divide %d recipe bars"
                % (slot_name, len(bars), length_bars)
            )

        velocity = _number(
            lane.get("velocity", DEFAULT_VELOCITY),
            "recipe.lanes[%d].velocity" % lane_index,
            low=0.0,
            high=1.0,
        )
        swing = _number(
            lane.get("swing", 0.0),
            "recipe.lanes[%d].swing" % lane_index,
            low=0.0,
            high=1.0,
        )
        if swing and grid != SUPPORTED_GRID:
            # Swing is a straight-grid idea: it delays every second 1/16. On a triplet grid the
            # off-beat steps already sit inside the beat, so applying it would smear the feel.
            raise RhythmCompileError(
                "recipe.lanes[%d].swing is defined on the straight 1/16 grid; grid %r "
                "already carries its own feel" % (lane_index, grid)
            )
        humanize = _number(
            lane.get("humanize", 0.0),
            "recipe.lanes[%d].humanize" % lane_index,
            low=0.0,
            high=0.5,
        )

        hits = 0
        for bar_index in range(length_bars):
            pattern = bars[bar_index % len(bars)]
            for step_index, symbol in enumerate(pattern):
                if symbol not in "xXo":
                    continue
                start = (bar_index * steps_per_bar + step_index) * step_beats
                if step_index % 2:
                    start += step_beats * swing * 0.5
                if humanize:
                    start += step_beats * humanize * _jitter(
                        "%s|%s|%d|%d|timing"
                        % (recipe.get("id", ""), slot_name, bar_index, step_index)
                    )
                start = max(0.0, min(start, total_beats - 1e-6))

                base = 127.0 * velocity
                if symbol == "X":
                    base *= 1.15
                elif symbol == "o":
                    base *= 0.55
                if humanize:
                    base += 24.0 * humanize * _jitter(
                        "%s|%s|%d|%d|velocity"
                        % (recipe.get("id", ""), slot_name, bar_index, step_index)
                    )
                note_velocity = max(1, min(127, int(round(base))))
                notes.append(
                    {
                        "pitch": pitch,
                        "start": round(start, 6),
                        "duration": round(step_beats * 0.9, 6),
                        "velocity": note_velocity,
                    }
                )
                hits += 1

        lane_rows.append(
            {
                "slot": slot_name,
                "pitch": pitch,
                "hits": hits,
                "pattern_bars": len(bars),
                "mode": mode,
            }
        )
        sample_rows.append(
            {
                "slot": slot_name,
                "mode": mode,
                "source": slot.get("from"),
                "select": slot.get("select"),
                "status": "unresolved",
                "reason": (
                    "MIDI rendering does not load a Browser sample; source selection belongs "
                    "to recipe_build"
                ),
            }
        )

    if not notes:
        raise RhythmCompileError("rhythm produced no notes; every lane is empty")
    if len(notes) > MAX_NOTES:
        raise RhythmCompileError(
            "rhythm produced %d notes; notes_replace accepts at most %d"
            % (len(notes), MAX_NOTES)
        )
    notes.sort(key=lambda note: (note["start"], note["pitch"], note["velocity"]))

    warnings = []
    if set_tempo is not None:
        try:
            set_tempo = float(set_tempo)
        except (TypeError, ValueError):
            set_tempo = None
    if set_tempo is not None and math.isfinite(set_tempo):
        recipe_tempo = recipe.get("tempo", {}).get("bpm")
        if isinstance(recipe_tempo, (int, float)) and not isinstance(recipe_tempo, bool):
            if abs(float(recipe_tempo) - set_tempo) > 0.5:
                warnings.append(
                    "recipe tempo is %g BPM but the Set is %g BPM; notes were placed on "
                    "the recipe's beat grid without changing transport"
                    % (float(recipe_tempo), set_tempo)
                )
    if target_length is None:
        warnings.append(
            "target clip length was not readable from the snapshot; verify the clip is at "
            "least %d bars long" % length_bars
        )

    target_args = _target_args(target)
    step = {
        "tool": "notes_replace",
        "args": {
            **target_args,
            "notes": notes,
        },
        "why": "Render %d bars of recipe %s into %s / %s"
        % (length_bars, recipe.get("id", ""), target_args["track"], target_args["clip"]),
    }
    return {
        "strategy": "midi_notes",
        "recipe_id": recipe.get("id"),
        "target": target_args,
        "bars": length_bars,
        "beats_per_bar": round(beats_per_bar, 6),
        "grid": grid,
        "steps_per_bar": steps_per_bar,
        "note_count": len(notes),
        "lanes": lane_rows,
        "samples": sample_rows,
        "tempo_bpm": recipe.get("tempo", {}).get("bpm"),
        "set_tempo_bpm": set_tempo,
        "length_checked": target_length is not None,
        "warnings": warnings,
        "step": step,
    }


__all__ = [
    "DEFAULT_VELOCITY",
    "MAX_NOTES",
    "RhythmCompileError",
    "SUPPORTED_GRID",
    "SUPPORTED_GRIDS",
    "render_rhythm",
]

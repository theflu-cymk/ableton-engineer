"""Routing reads and meter polling.

Routing is read live rather than folded into the snapshot: every read would pay for it on a large
Set, and only this report needs it. A track whose routing cannot be read carries the reason instead
of an empty string that would look like a track with no routing.

Meter polling is the one read that needs time. ``output_meter_level`` holds its peak for about a
second, while the instantaneous left and right meters move between display ticks, so the handler
samples on later ticks through ``Deferred`` rather than blocking Live's main thread. It reports the
highest instantaneous reading it actually saw; a missing meter is ``unavailable`` with the reason,
never a zero that would look like silence.
"""

from __future__ import annotations

import math
import time

from ..dispatch import check_args, command
from ..errors import Deferred, ScriptError
from ..routing import (
    attr as _attr,
    identifier as _identifier,
    index_of as _routing_index,
    label as _label,
)


def _track_kind(song, track):
    value = _attr(track, "track_type", None)
    if isinstance(value, str) and value:
        return value.lower()
    if track is _attr(song, "master_track", None):
        return "master"
    returns = list(_attr(song, "return_tracks", []) or [])
    if any(track is item for item in returns):
        return "return"
    if _attr(track, "is_foldable", False):
        return "group"
    if _attr(track, "has_midi_input", False) or _attr(track, "is_midi", False):
        return "midi"
    return "audio"


def _routing(track):
    row, problems = {}, []
    for key, source, options_attribute, count_key in (
        ("input_type", "input_routing_type", "available_input_routing_types", "input_types"),
        ("input_channel", "input_routing_channel", "available_input_routing_channels", "input_channels"),
        ("output_type", "output_routing_type", "available_output_routing_types", "output_types"),
        ("output_channel", "output_routing_channel", "available_output_routing_channels", "output_channels"),
    ):
        value = None
        missing_label = False
        try:
            value = getattr(track, source)
            row[key] = _label(value)
            identifier = _identifier(value)
            if identifier is not None:
                row[key + "_identifier"] = identifier
            if value is not None and row[key] is None:
                missing_label = True
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            row[key] = None
            problems.append("%s: %s" % (source, exc))
        try:
            options = list(getattr(track, options_attribute) or [])
            row[count_key] = len(options)
            current_index = _routing_index(options, value)
            if current_index is not None:
                row[key + "_index"] = current_index
        except Exception:
            row[count_key] = None
        # With zero selectable options there is no channel to choose and no index to
        # resolve; flagging the nameless current value would be a false positive on
        # tracks whose input exposes no channels.
        if missing_label and row.get(count_key) != 0 and key + "_index" not in row:
            problems.append(
                "%s: no display name, identifier or resolvable index; use %s_index"
                % (source, key)
            )
    if problems:
        row["reason"] = "; ".join(problems)
    return row


@command("mix.routing_report")
def routing_report(args, song):
    check_args(args, allowed=("offset", "limit"))
    offset = args.get("offset", 0)
    limit = args.get("limit", 200)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ScriptError("BAD_ARGS", "offset must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ScriptError("BAD_ARGS", "limit must be a positive integer")

    tracks = list(getattr(song, "tracks", []) or [])
    page = tracks[offset:offset + limit]
    items, flagged = [], []
    for index, track in enumerate(page, start=offset):
        entry = {
            "index": index,
            "name": str(_attr(track, "name", "") or ""),
            "type": _track_kind(song, track),
        }
        entry.update(_routing(track))
        items.append(entry)
        if entry.get("reason"):
            flagged.append(entry["name"])
        elif not entry.get("output_type"):
            flagged.append(entry["name"])

    next_offset = offset + len(page)
    return {
        "items": items,
        "total": len(tracks),
        "flagged": flagged,
        "next_offset": next_offset if next_offset < len(tracks) else None,
    }


# -- meter polling ------------------------------------------------------------

_DEFAULT_MS = 100
_MAX_MS = 5000
_MIN_SAMPLES = 2
_MAX_TICKS = 1024


def _clock():
    """Monotonic seconds. Separate so a test can advance the window without sleeping."""
    return time.monotonic()


def _meter_targets(song, wanted):
    """The tracks to meter: regular tracks, then returns, then the master.

    A name is resolved across all three groups and must identify exactly one object; an index
    addresses ``song.tracks`` only, the same way every other tool's index does.
    """
    tracks = list(_attr(song, "tracks", []) or [])
    returns = list(_attr(song, "return_tracks", []) or [])
    master = _attr(song, "master_track", None)

    entries = []
    for index, track in enumerate(tracks):
        entries.append({"kind": "track", "index": index, "track": track})
    for index, track in enumerate(returns):
        entries.append({"kind": "return", "index": index, "track": track})
    if master is not None:
        entries.append({"kind": "master", "index": None, "track": master})
    for entry in entries:
        entry["name"] = str(_attr(entry["track"], "name", "") or "")

    if wanted is None:
        return entries
    if not isinstance(wanted, list):
        raise ScriptError("BAD_ARGS", "tracks must be a list of names or indexes")
    if not wanted:
        raise ScriptError("BAD_ARGS", "tracks must not be empty")

    chosen, seen = [], set()
    for item in wanted:
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            raise ScriptError("BAD_ARGS", "tracks entries must be names or integer indexes")
        if isinstance(item, int):
            if item < 0 or item >= len(tracks):
                message = "no track at index %d" % (item,)
                if tracks:
                    message += "; indexes run 0..%d" % (len(tracks) - 1,)
                raise ScriptError("NOT_FOUND", message)
            entry = entries[item]
            key = ("track", item)
        else:
            if not item:
                raise ScriptError("BAD_ARGS", "track names must be non-empty")
            matches = [entry for entry in entries if entry["name"] == item]
            if not matches:
                matches = [
                    entry for entry in entries
                    if entry["name"].casefold() == item.casefold()
                ]
            if not matches:
                available = ", ".join(
                    "%s (%s)" % (entry["name"] or "<unnamed>", entry["kind"])
                    for entry in entries
                ) or "none"
                raise ScriptError(
                    "NOT_FOUND",
                    "no track named %r; available: %s" % (item, available),
                )
            if len(matches) > 1:
                raise ScriptError(
                    "AMBIGUOUS_REF",
                    "%d tracks are named %r; use a track index instead"
                    % (len(matches), item),
                )
            entry = matches[0]
            key = (entry["kind"], entry["index"])
        if key in seen:
            continue
        seen.add(key)
        chosen.append(entry)
    return chosen


def _read_meter(track, attribute):
    """One meter attribute, or None plus the reason it could not be read."""
    try:
        value = getattr(track, attribute)
    except Exception as exc:  # noqa: BLE001 - the reason is the answer
        return None, "%s: %s" % (attribute, exc)
    if value is None:
        return None, "%s returned None" % (attribute,)
    if isinstance(value, bool):
        return None, "%s is not a number" % (attribute,)
    try:
        return float(value), None
    except (TypeError, ValueError):
        return None, "%s is not a number" % (attribute,)


def _meter_rows(targets):
    return [
        {
            "kind": entry["kind"],
            "index": entry["index"],
            "name": entry["name"],
            "track": entry["track"],
            "level": None,
            "left": None,
            "right": None,
            "peak": None,
            "peak_source": None,
            "samples": 0,
            "reason": None,
            "level_reason": None,
        }
        for entry in targets
    ]


def _sample_meters(rows):
    """Read every meter once; keep the latest value and the highest one seen."""
    for row in rows:
        level, level_problem = _read_meter(row["track"], "output_meter_level")
        left, left_problem = _read_meter(row["track"], "output_meter_left")
        right, right_problem = _read_meter(row["track"], "output_meter_right")
        if level is not None:
            row["level"] = level
        elif row["level_reason"] is None:
            row["level_reason"] = level_problem
        if left is not None:
            row["left"] = left
        if right is not None:
            row["right"] = right

        instantaneous = [value for value in (left, right) if value is not None]
        if instantaneous:
            candidate, source = max(instantaneous), "output_meter_left/right"
        elif level is not None:
            candidate, source = level, "output_meter_level"
        else:
            candidate, source = None, None

        if candidate is None:
            if row["reason"] is None:
                row["reason"] = level_problem or left_problem or right_problem
            continue
        row["samples"] += 1
        row["reason"] = None
        if row["peak"] is None or candidate > row["peak"]:
            row["peak"] = candidate
            row["peak_source"] = source


def _rounded(value):
    return None if value is None else round(float(value), 6)


def _meter_report(rows, state, elapsed_ms):
    items = []
    for row in rows:
        item = {
            "kind": row["kind"],
            "index": row["index"],
            "name": row["name"],
            "available": row["peak"] is not None,
            "level": _rounded(row["level"]),
            "left": _rounded(row["left"]),
            "right": _rounded(row["right"]),
            "peak": _rounded(row["peak"]),
            "peak_source": row["peak_source"],
            "samples": row["samples"],
        }
        if row["peak"] is None:
            item["reason"] = row["reason"] or "no meter value was returned"
        elif row["level_reason"]:
            item["level_reason"] = row["level_reason"]
        items.append(item)

    measured = [item for item in items if item["available"]]
    loudest = max(measured, key=lambda item: item["peak"]) if measured else None
    master = next((item for item in items if item["kind"] == "master"), None)
    master_peak = master["peak"] if master is not None and master["available"] else None
    headroom = None
    if master_peak is not None and master_peak > 0:
        headroom = round(-20.0 * math.log10(master_peak), 2)

    notes = [
        "Meter values use Live's 0.0-1.0 scale, where 1.0 is 0 dBFS.",
        "peak is the highest instantaneous output_meter_left/right reading seen while "
        "sampling, not a true-peak measurement.",
    ]
    playing = bool(state.get("playing"))
    if not playing:
        notes.append(
            "Live was not playing, so a zero meter reading is not evidence of silence."
        )
    if master_peak == 0.0:
        notes.append(
            "The master meter read zero for the whole window, so its headroom is unknown."
        )

    return {
        "ms": state["ms"],
        "samples": state["samples"],
        "sampled_ms": elapsed_ms,
        "playing": playing,
        "items": items,
        "summary": {
            "measured": len(measured),
            "unavailable": len(items) - len(measured),
            "loudest": (
                {"name": loudest["name"], "peak": loudest["peak"]}
                if loudest is not None else None
            ),
            "at_or_over_0db": [
                item["name"] for item in measured if item["peak"] >= 1.0
            ],
            "master_peak": master_peak,
            "master_headroom_db": headroom,
        },
        "notes": notes,
    }


def _meter_step(state, song):
    """One display tick of the poll; defers until the window has elapsed."""
    now = _clock()
    if state["started"] is None:
        state["started"] = now
        state["playing"] = bool(_attr(song, "is_playing", False))
    _sample_meters(state["rows"])
    state["samples"] += 1
    elapsed_ms = (now - state["started"]) * 1000.0
    if state["samples"] < _MIN_SAMPLES or elapsed_ms < state["ms"]:
        if state["samples"] >= _MAX_TICKS:
            raise ScriptError(
                "TIMEOUT",
                "meter poll did not reach %s ms within %d display ticks"
                % (state["ms"], _MAX_TICKS),
            )
        return Deferred(lambda next_song: _meter_step(state, next_song))
    return _meter_report(state["rows"], state, round(elapsed_ms, 1))


@command("mix.meter_poll")
def meter_poll(args, song):
    check_args(args, allowed=("tracks", "ms"))
    ms = args.get("ms", _DEFAULT_MS)
    if isinstance(ms, bool) or not isinstance(ms, int) or ms < 0 or ms > _MAX_MS:
        raise ScriptError("BAD_ARGS", "ms must be an integer from 0 to %d" % (_MAX_MS,))

    targets = _meter_targets(song, args.get("tracks"))
    state = {
        "ms": ms,
        "rows": _meter_rows(targets),
        "samples": 0,
        "started": None,
        "playing": bool(_attr(song, "is_playing", False)),
    }
    if not targets:
        return _meter_report([], state, 0.0)
    return _meter_step(state, song)

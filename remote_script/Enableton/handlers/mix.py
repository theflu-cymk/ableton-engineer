"""Routing reads.

Routing is read live rather than folded into the snapshot: every read would pay for it on a large
Set, and only this report needs it. A track whose routing cannot be read carries the reason instead
of an empty string that would look like a track with no routing.
"""

from __future__ import annotations

from ..dispatch import check_args, command
from ..errors import ScriptError


def _attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _label(value):
    if value is None:
        return None
    for name in ("display_name", "name"):
        text = _attr(value, name, None)
        if isinstance(text, str) and text:
            return text
    text = str(value)
    return text or None


def _routing(track):
    row, problems = {}, []
    for key, source in (
        ("input_type", "input_routing_type"),
        ("input_channel", "input_routing_channel"),
        ("output_type", "output_routing_type"),
        ("output_channel", "output_routing_channel"),
    ):
        try:
            row[key] = _label(getattr(track, source))
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            row[key] = None
            problems.append("%s: %s" % (source, exc))
    for key, attribute in (
        ("input_types", "available_input_routing_types"),
        ("input_channels", "available_input_routing_channels"),
        ("output_types", "available_output_routing_types"),
        ("output_channels", "available_output_routing_channels"),
    ):
        try:
            row[key] = len(list(getattr(track, attribute) or []))
        except Exception:
            row[key] = None
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
            "type": str(_attr(track, "track_type", "") or "").lower(),
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

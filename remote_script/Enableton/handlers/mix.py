"""Routing reads.

Routing is read live rather than folded into the snapshot: every read would pay for it on a large
Set, and only this report needs it. A track whose routing cannot be read carries the reason instead
of an empty string that would look like a track with no routing.
"""

from __future__ import annotations

from ..dispatch import check_args, command
from ..errors import ScriptError
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

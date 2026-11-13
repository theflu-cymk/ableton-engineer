"""A/B take creation built on real track duplication.

The existing generation tools are catalogue-only, so this module deliberately does not call them.
It duplicates an already-working track, names the copies, and uses fader level as the A/B switch:
the source and all but the first take are lowered to zero. The audio is real and the operation is
reversible, but the takes start as identical copies; the producer edits each copy into a variation.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .protocol.codes import LiveError

_TAKE_RE = re.compile(r"^(?P<base>.+?)\s+take\s+(?P<take>\d+)$", re.IGNORECASE)


def _source(snapshot: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    tracks = list(snapshot.get("tracks") or [])
    name = args.get("track")
    index = args.get("track_index")
    if (name is None) == (index is None):
        raise LiveError("BAD_ARGS", "give exactly one of track or track_index")
    if index is not None:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise LiveError("BAD_ARGS", "track_index must be a non-negative integer")
        if index >= len(tracks):
            raise LiveError("NOT_FOUND", "no track at index %s" % index)
        return tracks[index]
    if not isinstance(name, str) or not name:
        raise LiveError("BAD_ARGS", "track must be a non-empty string")
    matches = [track for track in tracks if track.get("name") == name]
    if not matches:
        raise LiveError("NOT_FOUND", "no track named %r" % name)
    if len(matches) > 1:
        raise LiveError("AMBIGUOUS_REF", "%d tracks are named %r; use track_index" % (len(matches), name))
    return matches[0]


def _int_arg(args: Dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < low or value > high:
        raise LiveError("BAD_ARGS", "%s must be an integer from %d to %d" % (key, low, high))
    return value


def _rollback(
    adapter: Any,
    duplicate_undo: List[Dict[str, Any]],
    source_index: int,
    source_volume: Optional[float],
) -> Dict[str, Any]:
    report = {"duplicates_removed": 0, "source_volume_restored": False, "errors": []}
    if duplicate_undo:
        entries = [{"track_index": item["track_index"]} for item in duplicate_undo]
        try:
            adapter.call(
                "tracks.duplicate",
                {"restore": entries, "dry_run": False},
                timeout_ms=30000,
            )
            report["duplicates_removed"] = len(entries)
        except Exception as exc:  # noqa: BLE001 - rollback report, not a second failure
            report["errors"].append("duplicates: %s" % exc)
    if source_volume is not None:
        try:
            adapter.call(
                "tracks.set_volume",
                {"restore": [{"track_index": source_index, "volume": source_volume}], "dry_run": False},
                timeout_ms=8000,
            )
            report["source_volume_restored"] = True
        except Exception as exc:  # noqa: BLE001
            report["errors"].append("source volume: %s" % exc)
    return report


def create_takes(adapter: Any, cache: Any, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create named A/B track copies, with a dry run and an explicit rollback attempt."""
    args = dict(args or {})
    unknown = sorted(set(args) - {"track", "track_index", "count", "name_prefix", "dry_run"})
    if unknown:
        raise LiveError("BAD_ARGS", "unknown argument(s): %s" % ", ".join(unknown))
    dry_run = args.get("dry_run", True)
    if not isinstance(dry_run, bool):
        raise LiveError("BAD_ARGS", "dry_run must be true or false")
    count = _int_arg(args, "count", 2, 1, 8)
    snapshot = cache.get()
    source = _source(snapshot, args)
    source_name = str(source.get("name") or "")
    source_index = int(source.get("index") or 0)
    source_volume = source.get("volume")
    if source_volume is not None:
        try:
            source_volume = float(source_volume)
        except (TypeError, ValueError):
            source_volume = None
    prefix = args.get("name_prefix", "%s take" % source_name)
    if not isinstance(prefix, str) or not prefix.strip():
        raise LiveError("BAD_ARGS", "name_prefix must be a non-empty string")
    prefix = prefix.strip()

    duplicate_args: Dict[str, Any] = {"count": count, "dry_run": True}
    if args.get("track_index") is not None:
        duplicate_args["track_index"] = source_index
    else:
        duplicate_args["track"] = source_name
    preview = adapter.call("tracks.duplicate", duplicate_args, timeout_ms=10000)
    planned = list(preview.get("created") or [])
    names = ["%s %d" % (prefix, position + 1) for position in range(count)]
    if dry_run:
        return {
            "dry_run": True,
            "source": source_name,
            "source_index": source_index,
            "planned": [
                {"track_index": item.get("track_index"), "name": names[position]}
                for position, item in enumerate(planned)
            ],
            "volume_plan": {
                "source": 0.0 if source_volume is not None else None,
                "takes": [source_volume if position == 0 else 0.0 for position in range(count)],
            },
            "note": "Apply duplicates the tracks and leaves take 1 audible; takes are identical until you edit them.",
        }

    created: List[Dict[str, Any]] = []
    duplicate_undo: List[Dict[str, Any]] = []
    volume_tokens: List[Dict[str, Any]] = []
    source_changed = False
    try:
        applied = adapter.call(
            "tracks.duplicate",
            dict(duplicate_args, dry_run=False),
            timeout_ms=30000,
        )
        created = list(applied.get("created") or [])
        duplicate_undo = list(applied.get("undo") or [])
        if len(created) != count:
            raise LiveError("LIVE_ERROR", "Live created %d tracks, expected %d" % (len(created), count))
        for position, item in enumerate(created):
            index = int(item["track_index"])
            name = names[position]
            adapter.call(
                "tracks.name_and_color",
                {"track_index": index, "name": name, "dry_run": False},
                timeout_ms=8000,
            )
            item["name"] = name
        if source_volume is not None:
            muted = adapter.call(
                "tracks.set_volume",
                {"tracks": [source_name], "volume": 0.0, "dry_run": False},
                timeout_ms=8000,
            )
            source_changed = True
            volume_tokens.extend(muted.get("undo") or [])
            for position, item in enumerate(created):
                volume = source_volume if position == 0 else 0.0
                changed = adapter.call(
                    "tracks.set_volume",
                    {"tracks": [item["name"]], "volume": float(volume), "dry_run": False},
                    timeout_ms=8000,
                )
                volume_tokens.extend(changed.get("undo") or [])
        cache.invalidate()
    except Exception as exc:  # noqa: BLE001 - the caller needs the rollback report
        cache.invalidate()
        rollback = _rollback(
            adapter, duplicate_undo, source_index, source_volume if source_changed else None
        )
        raise LiveError(
            "LIVE_ERROR",
            "takes_create failed: %s" % exc,
            {"rollback": rollback, "created": created},
        )

    takes = [
        {
            "track_index": int(item["track_index"]),
            "name": item["name"],
            "active": position == 0,
            "volume": source_volume if position == 0 else 0.0,
        }
        for position, item in enumerate(created)
    ]
    return {
        "dry_run": False,
        "source": source_name,
        "source_index": source_index,
        "source_volume": source_volume,
        "takes": takes,
        "active": takes[0]["name"] if takes else None,
        "undo": {"duplicates": duplicate_undo, "volumes": volume_tokens},
        "note": "Take 1 is audible; the source and other takes are at fader zero. Edit copies, then A/B with tracks_set_volume.",
    }


def _take_names(args: Dict[str, Any]) -> List[str]:
    raw = args.get("takes")
    if not isinstance(raw, list) or not raw:
        raise LiveError("BAD_ARGS", "takes must be a non-empty list of exact take names")
    if len(raw) > 8:
        raise LiveError("BAD_ARGS", "takes is limited to 8 names")
    names: List[str] = []
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            raise LiveError("BAD_ARGS", "takes must contain non-empty names")
        name = value.strip()
        if name in names:
            raise LiveError("BAD_ARGS", "takes contains a duplicate name")
        names.append(name)
    return names


def _resolve_takes(snapshot: Dict[str, Any], names: List[str]) -> List[Dict[str, Any]]:
    tracks = list(snapshot.get("tracks") or [])
    rows: List[Dict[str, Any]] = []
    base: Optional[str] = None
    for name in names:
        matches = [track for track in tracks if track.get("name") == name]
        if not matches:
            raise LiveError("NOT_FOUND", "no track named %r" % (name,))
        if len(matches) > 1:
            raise LiveError("AMBIGUOUS_REF", "%d tracks are named %r; use unique take names" % (len(matches), name))
        row = matches[0]
        if str(row.get("kind") or "") == "return":
            raise LiveError("BAD_ARGS", "%r is a return track, not a take" % (name,))
        match = _TAKE_RE.match(name)
        if match is None:
            raise LiveError(
                "BAD_ARGS", "%r is not a take name; expected '<group> take <number>'" % (name,)
            )
        group = match.group("base").strip()
        if base is None:
            base = group
        elif group != base:
            raise LiveError("BAD_ARGS", "takes must belong to the same group")
        rows.append(row)
    return rows


def _volume_of(row: Dict[str, Any]) -> float:
    try:
        return float(row["volume"])
    except (KeyError, TypeError, ValueError):
        raise LiveError("UNSUPPORTED", "track %r has no readable volume" % (row.get("name"),))


def _resolve_active(names: List[str], active: Any) -> str:
    if isinstance(active, bool):
        raise LiveError("BAD_ARGS", "active must be a take name or a 1-based take number")
    if isinstance(active, int):
        if active < 1 or active > len(names):
            raise LiveError("BAD_ARGS", "active must be a 1-based take number in this group")
        return names[active - 1]
    if isinstance(active, str) and active in names:
        return active
    raise LiveError("BAD_ARGS", "active must be one of the takes, or a 1-based take number")


def select_takes(adapter: Any, cache: Any, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Make one take audible and lower the other takes to fader zero."""
    args = dict(args or {})
    unknown = sorted(set(args) - {"takes", "active", "volume", "dry_run"})
    if unknown:
        raise LiveError("BAD_ARGS", "unknown argument(s): %s" % ", ".join(unknown))
    dry_run = args.get("dry_run", True)
    if not isinstance(dry_run, bool):
        raise LiveError("BAD_ARGS", "dry_run must be true or false")
    names = _take_names(args)
    rows = _resolve_takes(cache.get(), names)
    active = _resolve_active(names, args.get("active"))
    volumes = {str(row["name"]): _volume_of(row) for row in rows}
    raw_volume = args.get("volume")
    if raw_volume is None:
        audible = [value for value in volumes.values() if value > 0.001]
        level = max(audible) if audible else 0.85
    else:
        if isinstance(raw_volume, bool):
            raise LiveError("BAD_ARGS", "volume must be a number from 0 to 1")
        try:
            level = float(raw_volume)
        except (TypeError, ValueError):
            raise LiveError("BAD_ARGS", "volume must be a number from 0 to 1")
        if level < 0.0 or level > 1.0:
            raise LiveError("BAD_ARGS", "volume must be a number from 0 to 1")

    changes = []
    for row in rows:
        name = str(row["name"])
        target = level if name == active else 0.0
        current = volumes[name]
        changes.append({
            "track": name,
            "track_index": int(row["index"]),
            "from": round(current, 4),
            "to": round(target, 4),
        })
    undo = [{"track_index": int(row["index"]), "volume": volumes[str(row["name"])]} for row in rows]
    note = "Selecting a take sets it audible and the other takes to fader zero; undo restores the prior faders."
    if dry_run:
        return {
            "dry_run": True,
            "group": _TAKE_RE.match(active).group("base").strip(),
            "active": active,
            "volume": round(level, 4),
            "changes": changes,
            "undo": [],
            "note": note,
        }

    try:
        adapter.call(
            "tracks.set_volume",
            {"tracks": names, "volume": 0.0, "dry_run": False},
            timeout_ms=8000,
        )
        adapter.call(
            "tracks.set_volume",
            {"tracks": [active], "volume": level, "dry_run": False},
            timeout_ms=8000,
        )
    except Exception as exc:  # noqa: BLE001 - report the failed write and try to restore
        rollback = {"restored": False, "errors": []}
        try:
            adapter.call(
                "tracks.set_volume",
                {"restore": undo, "dry_run": False},
                timeout_ms=8000,
            )
            rollback["restored"] = True
        except Exception as restore_exc:  # noqa: BLE001
            rollback["errors"].append(str(restore_exc))
        cache.invalidate()
        raise LiveError(
            "LIVE_ERROR",
            "takes_select failed: %s" % (exc,),
            {"rollback": rollback, "changes": changes},
        )

    cache.invalidate()
    return {
        "dry_run": False,
        "group": _TAKE_RE.match(active).group("base").strip(),
        "active": active,
        "volume": round(level, 4),
        "changes": changes,
        "undo": undo,
        "note": note,
    }


def discard_takes(adapter: Any, cache: Any, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Delete take tracks after an explicit confirmation; this is irreversible."""
    args = dict(args or {})
    unknown = sorted(set(args) - {"takes", "confirm", "dry_run"})
    if unknown:
        raise LiveError("BAD_ARGS", "unknown argument(s): %s" % ", ".join(unknown))
    dry_run = args.get("dry_run", True)
    if not isinstance(dry_run, bool):
        raise LiveError("BAD_ARGS", "dry_run must be true or false")
    names = _take_names(args)
    rows = _resolve_takes(cache.get(), names)
    if not dry_run and args.get("confirm") is not True:
        raise LiveError(
            "PRECONDITION_FAILED",
            "takes_discard deletes tracks and cannot be undone; an apply needs confirm: true",
        )

    ordered = sorted(rows, key=lambda row: int(row["index"]), reverse=True)
    deleted: List[Dict[str, Any]] = []
    try:
        for row in ordered:
            result = adapter.call(
                "tracks.delete",
                {"track_index": int(row["index"]), "confirm": True, "dry_run": dry_run},
                timeout_ms=8000,
            )
            deleted.extend(result.get("deleted") or [])
    except Exception as exc:  # noqa: BLE001 - deletion is irreversible; report the partial state
        if not dry_run:
            cache.invalidate()
        raise LiveError(
            "LIVE_ERROR",
            "takes_discard failed after %d deletion(s): %s" % (len(deleted), exc),
            {"deleted": deleted, "reversible": False},
        )

    if not dry_run:
        cache.invalidate()
    return {
        "dry_run": dry_run,
        "deleted": deleted,
        "count": len(deleted),
        "reversible": False,
        "requires_confirm": True,
        "undo": [],
        "note": "Deleted take tracks cannot be restored on this Live build.",
    }
"""A/B take creation built on real track duplication.

The existing generation tools are catalogue-only, so this module deliberately does not call them.
It duplicates an already-working track, names the copies, and uses fader level as the A/B switch:
the source and all but the first take are lowered to zero. The audio is real and the operation is
reversible, but the takes start as identical copies; the producer edits each copy into a variation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .protocol.codes import LiveError


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
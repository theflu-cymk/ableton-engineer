from __future__ import annotations

from ..dispatch import check_args, command
from ..errors import ScriptError


def _param(track, name, fallback):
    """Read a mixer parameter, falling back to a plain attribute on the fake backend."""
    mixer = getattr(track, "mixer_device", None)
    param = getattr(mixer, name, None) if mixer is not None else None
    if param is not None:
        value = getattr(param, "value", None)
        if value is not None:
            return float(value)
    return float(getattr(track, fallback, 0.0) or 0.0)


def _set_param(track, name, fallback, value):
    mixer = getattr(track, "mixer_device", None)
    param = getattr(mixer, name, None) if mixer is not None else None
    if param is not None:
        param.value = value
    else:
        setattr(track, fallback, value)


@command("track.list")
def list_tracks(args, song):
    check_args(args, allowed=("offset", "limit"))
    offset = int(args.get("offset", 0))
    limit = int(args.get("limit", 200))
    if offset < 0:
        raise ScriptError("BAD_ARGS", "offset must be >= 0")
    if limit < 1:
        raise ScriptError("BAD_ARGS", "limit must be >= 1")

    page = song.tracks[offset:offset + limit]
    items = []
    for index, track in enumerate(page, start=offset):
        items.append({
            "index": index,
            "name": track.name,
            "volume": round(_param(track, "volume", "volume"), 4),
            "pan": round(_param(track, "panning", "pan"), 3),
            "is_midi": bool(getattr(track, "is_midi", False)
                            or getattr(track, "has_midi_input", False)),
            "peak_db": getattr(track, "peak_db", None),
        })

    next_offset = offset + len(page)
    return {
        "items": items,
        "total": len(song.tracks),
        "next_offset": next_offset if next_offset < len(song.tracks) else None,
    }


@command("tracks.set_volume")
def set_volume(args, song):
    check_args(args, allowed=("tracks", "volume", "dry_run", "restore"))
    dry_run = bool(args.get("dry_run", True))
    restore = args.get("restore")
    if restore is not None:
        if args.get("tracks"):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with tracks")
        if not isinstance(restore, list):
            raise ScriptError("BAD_ARGS", "restore must be a list")
        changes = []
        for entry in reversed(restore):
            if not isinstance(entry, dict):
                raise ScriptError("BAD_ARGS", "restore entries must be objects")
            try:
                index = int(entry["track_index"])
                volume = float(entry["volume"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError("BAD_ARGS", "restore entries need track_index and volume")
            if index < 0 or index >= len(song.tracks):
                raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
            track = song.tracks[index]
            current = _param(track, "volume", "volume")
            if not dry_run:
                _set_param(track, "volume", "volume", volume)
            changes.append({
                "track": track.name,
                "track_index": index,
                "from": round(current, 4),
                "to": round(volume, 4),
            })
        return {"dry_run": dry_run, "restored": len(changes), "changes": changes}

    try:
        volume = float(args["volume"])
    except (KeyError, TypeError, ValueError):
        raise ScriptError("BAD_ARGS", "volume must be a number from 0 to 1")
    if volume < 0.0 or volume > 1.0:
        raise ScriptError("BAD_ARGS", "volume must be a number from 0 to 1")

    wanted = list(args.get("tracks") or [])
    if wanted:
        known = [track.name for track in song.tracks]
        missing = [name for name in wanted if name not in known]
        if missing:
            raise ScriptError("NOT_FOUND", "no track named %s" % ", ".join(missing))
        targets = [(index, track) for index, track in enumerate(song.tracks)
                   if track.name in wanted]
    else:
        targets = list(enumerate(song.tracks))

    changes, undo = [], []
    for index, track in targets:
        current = _param(track, "volume", "volume")
        changes.append({
            "track": track.name,
            "track_index": index,
            "from": round(current, 4),
            "to": round(volume, 4),
        })
        undo.append({"track_index": index, "volume": current})
        if not dry_run:
            _set_param(track, "volume", "volume", volume)
    return {"dry_run": dry_run, "changes": changes, "skipped": [], "undo": undo}


@command("tracks.gain_stage")
def gain_stage(args, song):
    check_args(args, allowed=("tracks", "headroom_db", "dry_run", "restore"))
    headroom_db = float(args.get("headroom_db", -6.0))
    dry_run = bool(args.get("dry_run", True))
    wanted = list(args.get("tracks") or [])

    # The executor replays a tool-owned undo token through this same command. A restore is
    # deliberately separate from a gain-stage calculation: it puts back the exact values the
    # previous call reported, not a new guess derived from a possibly changed peak.
    restore = args.get("restore")
    if restore is not None:
        if wanted:
            raise ScriptError("BAD_ARGS", "restore cannot be combined with tracks")
        if not isinstance(restore, list):
            raise ScriptError("BAD_ARGS", "restore must be a list")
        restored = []
        for entry in reversed(restore):
            if not isinstance(entry, dict):
                raise ScriptError("BAD_ARGS", "restore entries must be objects")
            try:
                index = int(entry["track_index"])
                volume = float(entry["volume"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError("BAD_ARGS", "restore entries need track_index and volume")
            if index < 0 or index >= len(song.tracks):
                raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
            track = song.tracks[index]
            current = _param(track, "volume", "volume")
            if not dry_run:
                _set_param(track, "volume", "volume", volume)
            restored.append({
                "track": track.name,
                "track_index": index,
                "from": round(current, 4),
                "to": round(volume, 4),
            })
        return {"dry_run": dry_run, "restored": len(restored), "changes": restored, "skipped": []}

    if wanted:
        known = [track.name for track in song.tracks]
        missing = [name for name in wanted if name not in known]
        if missing:
            raise ScriptError("NOT_FOUND", "no track named %s" % ", ".join(missing))
        targets = [(index, track) for index, track in enumerate(song.tracks)
                   if track.name in wanted]
    else:
        targets = list(enumerate(song.tracks))

    changes, skipped, undo = [], [], []
    for index, track in targets:
        peak = getattr(track, "peak_db", None)
        if peak is None:
            skipped.append(track.name)
            continue
        offset_db = headroom_db - float(peak)
        factor = 10.0 ** (offset_db / 20.0)
        current = _param(track, "volume", "volume")
        new_volume = max(0.0, min(1.0, current * factor))
        changes.append({
            "track": track.name,
            "track_index": index,
            "from": round(current, 4),
            "to": round(new_volume, 4),
            "offset_db": round(offset_db, 2),
        })
        undo.append({"track_index": index, "volume": current})
        if not dry_run:
            _set_param(track, "volume", "volume", new_volume)

    return {"dry_run": dry_run, "changes": changes, "skipped": skipped, "undo": undo}


@command("tracks.set_pan")
def set_pan(args, song):
    check_args(args, allowed=("tracks", "pan", "dry_run", "restore"))
    dry_run = bool(args.get("dry_run", True))
    restore = args.get("restore")
    if restore is not None:
        if args.get("tracks"):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with tracks")
        if not isinstance(restore, list):
            raise ScriptError("BAD_ARGS", "restore must be a list")
        changes = []
        for entry in reversed(restore):
            if not isinstance(entry, dict):
                raise ScriptError("BAD_ARGS", "restore entries must be objects")
            try:
                index = int(entry["track_index"])
                pan = float(entry["pan"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError("BAD_ARGS", "restore entries need track_index and pan")
            if index < 0 or index >= len(song.tracks):
                raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
            if pan < -1.0 or pan > 1.0:
                raise ScriptError("BAD_ARGS", "pan must be a number from -1 to 1")
            track = song.tracks[index]
            current = _param(track, "panning", "pan")
            if not dry_run:
                _set_param(track, "panning", "pan", pan)
            changes.append({
                "track": track.name,
                "track_index": index,
                "from": round(current, 4),
                "to": round(pan, 4),
            })
        return {"dry_run": dry_run, "restored": len(changes), "changes": changes}

    try:
        pan = float(args["pan"])
    except (KeyError, TypeError, ValueError):
        raise ScriptError("BAD_ARGS", "pan must be a number from -1 to 1")
    if pan < -1.0 or pan > 1.0:
        raise ScriptError("BAD_ARGS", "pan must be a number from -1 to 1")

    wanted = list(args.get("tracks") or [])
    if wanted:
        known = [track.name for track in song.tracks]
        missing = [name for name in wanted if name not in known]
        if missing:
            raise ScriptError("NOT_FOUND", "no track named %s" % ", ".join(missing))
        targets = [(index, track) for index, track in enumerate(song.tracks)
                   if track.name in wanted]
    else:
        targets = list(enumerate(song.tracks))

    changes, undo = [], []
    for index, track in targets:
        current = _param(track, "panning", "pan")
        changes.append({
            "track": track.name,
            "track_index": index,
            "from": round(current, 4),
            "to": round(pan, 4),
        })
        undo.append({"track_index": index, "pan": current})
        if not dry_run:
            _set_param(track, "panning", "pan", pan)
    return {"dry_run": dry_run, "changes": changes, "undo": undo}

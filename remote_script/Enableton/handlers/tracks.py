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
            "color": int(getattr(track, "color", 0) or 0),
            "is_midi": bool(getattr(track, "is_midi", False)
                            or getattr(track, "has_midi_input", False)),
            "peak_db": getattr(track, "peak_db", None),
        })
        sends, sends_reason = _send_map(song, track)
        items[-1]["sends"] = sends
        if sends_reason is not None:
            items[-1]["sends_reason"] = sends_reason

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


def _one_track(song, name):
    matches = [
        (index, track) for index, track in enumerate(song.tracks)
        if str(getattr(track, "name", "")) == name
    ]
    if not matches:
        raise ScriptError("NOT_FOUND", "no track named %r" % (name,))
    if len(matches) > 1:
        raise ScriptError(
            "AMBIGUOUS_REF",
            "%d tracks are named %r; rename one before editing it" % (len(matches), name),
        )
    return matches[0]


def _return_tracks(song):
    return list(getattr(song, "return_tracks", []) or [])


def _return_names(song):
    return [str(getattr(track, "name", "")) for track in _return_tracks(song)]


def _send_params(track):
    mixer = getattr(track, "mixer_device", None)
    sends = getattr(mixer, "sends", None) if mixer is not None else None
    if sends is None:
        sends = getattr(track, "sends", None)
    if sends is None:
        raise ScriptError("UNSUPPORTED", "track does not expose send parameters")
    return list(sends)


def _send_value(param):
    return float(getattr(param, "value", 0.0) or 0.0)


def _send_map(song, track):
    names = _return_names(song)
    try:
        params = _send_params(track)
    except ScriptError as exc:
        return {}, str(exc)
    return {
        names[index]: round(_send_value(params[index]), 4)
        for index in range(min(len(names), len(params)))
    }, None


@command("tracks.set_sends")
def set_sends(args, song):
    check_args(args, allowed=("track", "sends", "dry_run", "restore"))
    dry_run = bool(args.get("dry_run", True))
    restore = args.get("restore")
    if restore is not None:
        if "track" in args or "sends" in args:
            raise ScriptError("BAD_ARGS", "restore cannot be combined with track or sends")
        if not isinstance(restore, list) or not restore:
            raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
        changes = []
        for entry in reversed(restore):
            if not isinstance(entry, dict):
                raise ScriptError("BAD_ARGS", "restore entries must be objects")
            if isinstance(entry.get("value"), bool):
                raise ScriptError("BAD_ARGS", "restore value must be a number from 0 to 1")
            try:
                index = int(entry["track_index"])
                send_index = int(entry["send_index"])
                value = float(entry["value"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError(
                    "BAD_ARGS", "restore entries need track_index, send_index and value"
                )
            if value < 0.0 or value > 1.0:
                raise ScriptError("BAD_ARGS", "restore value must be a number from 0 to 1")
            if index < 0 or index >= len(song.tracks):
                raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
            track = song.tracks[index]
            params = _send_params(track)
            if send_index < 0 or send_index >= len(params):
                raise ScriptError("NOT_FOUND", "no send at index %s" % (send_index,))
            current = _send_value(params[send_index])
            if not dry_run:
                params[send_index].value = value
            changes.append({
                "track": str(getattr(track, "name", "")),
                "track_index": index,
                "send_index": send_index,
                "send": entry.get("send"),
                "from": round(current, 4),
                "to": round(value, 4),
            })
        return {"dry_run": dry_run, "restored": len(changes), "changes": changes}

    track_name = args.get("track")
    if not isinstance(track_name, str) or not track_name:
        raise ScriptError("BAD_ARGS", "track must be a non-empty string")
    sends = args.get("sends")
    if not isinstance(sends, dict) or not sends:
        raise ScriptError("BAD_ARGS", "sends must be a non-empty object")

    index, track = _one_track(song, track_name)
    params = _send_params(track)
    names = _return_names(song)
    changes, undo = [], []
    for send_name, raw_value in sends.items():
        if not isinstance(send_name, str) or not send_name:
            raise ScriptError("BAD_ARGS", "send names must be non-empty strings")
        matches = [position for position, name in enumerate(names) if name == send_name]
        if not matches:
            raise ScriptError("NOT_FOUND", "no return track named %r" % (send_name,))
        if len(matches) > 1:
            raise ScriptError(
                "AMBIGUOUS_REF",
                "%d return tracks are named %r; rename one before setting sends"
                % (len(matches), send_name),
            )
        send_index = matches[0]
        if send_index >= len(params):
            raise ScriptError(
                "NOT_FOUND", "track %r has no send parameter for %r" % (track_name, send_name)
            )
        if isinstance(raw_value, bool):
            raise ScriptError("BAD_ARGS", "send values must be numbers from 0 to 1")
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "send values must be numbers from 0 to 1")
        if value < 0.0 or value > 1.0:
            raise ScriptError("BAD_ARGS", "send values must be numbers from 0 to 1")
        current = _send_value(params[send_index])
        changes.append({
            "track": str(getattr(track, "name", "")),
            "track_index": index,
            "send": send_name,
            "send_index": send_index,
            "from": round(current, 4),
            "to": round(value, 4),
        })
        undo.append({
            "track_index": index,
            "send_index": send_index,
            "send": send_name,
            "value": current,
        })
        if not dry_run:
            params[send_index].value = value

    return {
        "dry_run": dry_run,
        "track": str(getattr(track, "name", "")),
        "track_index": index,
        "changes": changes,
        "undo": undo,
    }


@command("tracks.name_and_color")
def name_and_color(args, song):
    check_args(args, allowed=("track", "track_index", "name", "color", "dry_run", "restore"))
    dry_run = bool(args.get("dry_run", True))
    restore = args.get("restore")
    if restore is not None:
        if "track" in args or "track_index" in args or "name" in args or "color" in args:
            raise ScriptError(
                "BAD_ARGS", "restore cannot be combined with track, track_index, name or color"
            )
        if not isinstance(restore, list) or not restore:
            raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
        changes = []
        for entry in reversed(restore):
            if not isinstance(entry, dict):
                raise ScriptError("BAD_ARGS", "restore entries must be objects")
            try:
                index = int(entry["track_index"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError("BAD_ARGS", "restore entries need track_index")
            old_name = entry.get("name")
            old_color = entry.get("color")
            if old_name is None and old_color is None:
                raise ScriptError("BAD_ARGS", "restore entries need a name or color")
            if old_name is not None and (not isinstance(old_name, str) or not old_name):
                raise ScriptError("BAD_ARGS", "restore name must be a non-empty string")
            if old_color is not None and (
                not isinstance(old_color, int) or isinstance(old_color, bool)
                or old_color < 0 or old_color > 0xFFFFFF
            ):
                raise ScriptError(
                    "BAD_ARGS",
                    "restore color must be an integer from 0 to 16777215 (0xRRGGBB)",
                )
            if index < 0 or index >= len(song.tracks):
                raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
            track = song.tracks[index]
            current_name = str(getattr(track, "name", ""))
            current_color = int(getattr(track, "color", 0) or 0)
            if not dry_run:
                if old_name is not None:
                    track.name = old_name
                if old_color is not None:
                    track.color = old_color
            changes.append({
                "track": current_name,
                "track_index": index,
                "name": None if old_name is None else {
                    "from": current_name, "to": old_name,
                },
                "color": None if old_color is None else {
                    "from": current_color, "to": old_color,
                },
            })
        return {"dry_run": dry_run, "restored": len(changes), "changes": changes}

    has_track = "track" in args
    has_index = "track_index" in args
    if has_track == has_index:
        raise ScriptError("BAD_ARGS", "give exactly one of track or track_index")
    if has_track:
        track_name = args.get("track")
        if not isinstance(track_name, str) or not track_name:
            raise ScriptError("BAD_ARGS", "track must be a non-empty string")
        index, track = _one_track(song, track_name)
    else:
        raw_index = args.get("track_index")
        if (
            not isinstance(raw_index, int) or isinstance(raw_index, bool)
            or raw_index < 0
        ):
            raise ScriptError("BAD_ARGS", "track_index must be a non-negative integer")
        if raw_index >= len(song.tracks):
            raise ScriptError("NOT_FOUND", "no track at index %s" % (raw_index,))
        index = raw_index
        track = song.tracks[index]

    name = args.get("name")
    color = args.get("color")
    if name is None and color is None:
        raise ScriptError("BAD_ARGS", "give at least one of name or color")
    if name is not None and (not isinstance(name, str) or not name):
        raise ScriptError("BAD_ARGS", "name must be a non-empty string")
    if color is not None and (
        not isinstance(color, int) or isinstance(color, bool)
        or color < 0 or color > 0xFFFFFF
    ):
        raise ScriptError(
            "BAD_ARGS", "color must be an integer from 0 to 16777215 (0xRRGGBB)"
        )

    current_name = str(getattr(track, "name", ""))
    current_color = int(getattr(track, "color", 0) or 0)
    changes = []
    if name is not None:
        changes.append({"field": "name", "from": current_name, "to": name})
    if color is not None:
        changes.append({"field": "color", "from": current_color, "to": color})
    undo = [{"track_index": index, "name": current_name, "color": current_color}]
    if not dry_run:
        if name is not None:
            track.name = name
        if color is not None:
            track.color = color
    return {
        "dry_run": dry_run,
        "track": current_name,
        "track_index": index,
        "changes": changes,
        "undo": undo,
    }


@command("tracks.duplicate")
def duplicate(args, song):
    check_args(args, allowed=("track", "track_index", "count", "dry_run", "restore"))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(key in args for key in ("track", "track_index", "count")):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a duplicate")
        return _restore_duplicates(args, song, dry_run)

    has_track = "track" in args
    has_index = "track_index" in args
    if has_track == has_index:
        raise ScriptError("BAD_ARGS", "give exactly one of track or track_index")
    if has_track:
        track_name = args.get("track")
        if not isinstance(track_name, str) or not track_name:
            raise ScriptError("BAD_ARGS", "track must be a non-empty string")
        index, track = _one_track(song, track_name)
    else:
        raw_index = args.get("track_index")
        if isinstance(raw_index, bool) or not isinstance(raw_index, int) or raw_index < 0:
            raise ScriptError("BAD_ARGS", "track_index must be a non-negative integer")
        if raw_index >= len(song.tracks):
            raise ScriptError("NOT_FOUND", "no track at index %s" % (raw_index,))
        index = raw_index
        track = song.tracks[index]

    count = args.get("count", 1)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > 8:
        raise ScriptError("BAD_ARGS", "count must be an integer from 1 to 8")

    duplicate_track = getattr(song, "duplicate_track", None)
    if not callable(duplicate_track):
        raise ScriptError("UNSUPPORTED", "this Live build cannot duplicate a track")

    planned = [
        {"source": str(getattr(track, "name", "")), "source_index": index,
         "track_index": index + offset}
        for offset in range(1, count + 1)
    ]
    if dry_run:
        return {"dry_run": True, "created": planned, "undo": []}

    created, undo = [], []
    for offset in range(count):
        try:
            new_track = duplicate_track(index + offset)
        except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
            raise ScriptError(
                "LIVE_ERROR", "could not duplicate %r: %s"
                % (str(getattr(track, "name", "")), exc),
            )
        tracks = list(song.tracks)
        new_index = index + offset + 1
        for position, candidate in enumerate(tracks):
            if candidate is new_track:
                new_index = position
                break
        name = str(getattr(new_track, "name", "") or "")
        created.append({"name": name, "track_index": new_index,
                        "source": str(getattr(track, "name", ""))})
        undo.append({"track_index": new_index, "name": name})

    return {"dry_run": False, "created": created, "undo": undo}


def _restore_duplicates(args, song, dry_run):
    entries = args.get("restore")
    if not isinstance(entries, list) or not entries:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    checked = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        try:
            index = int(entry["track_index"])
        except (KeyError, TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "restore entries need track_index")
        checked.append((index, entry.get("name")))

    delete_track = getattr(song, "delete_track", None)
    if not callable(delete_track):
        raise ScriptError("UNSUPPORTED", "this Live build cannot delete a track")

    changes, missing = [], []
    # Descending index order: each delete shifts everything after it down by one.
    for index, wanted in sorted(checked, key=lambda pair: pair[0], reverse=True):
        tracks = list(song.tracks)
        if index < 0 or index >= len(tracks):
            missing.append({"track_index": index, "reason": "no track at that index"})
            continue
        track = tracks[index]
        name = str(getattr(track, "name", "") or "")
        if wanted is not None and name != str(wanted):
            missing.append(
                {"track_index": index, "reason": "the track at that index has a different name"}
            )
            continue
        if not dry_run:
            delete_track(track)
        changes.append({"track": name, "track_index": index})

    return {"dry_run": dry_run, "restored": len(changes), "changes": changes, "missing": missing}


def _track_clip_counts(track):
    """Clip counts, or (None, None) for a group track.

    Group, Main and Return tracks have no clip slots: Live raises "Main, Group and Return Tracks
    have no arrangement clips" when the attribute is read, which took down a whole clean_empty
    dry run on real 0.4.0. A group is never empty and is never deleted by the cleanup, because
    deleting it would take the tracks inside it too.
    """
    if getattr(track, "is_foldable", False):
        return None, None
    try:
        arrangement = len(list(getattr(track, "arrangement_clips", []) or []))
        slots = list(getattr(track, "clip_slots", []) or [])
    except Exception:  # noqa: BLE001 - group tracks raise rather than report empty
        return None, None
    session = 0
    for slot in slots:
        if getattr(slot, "has_clip", False) or getattr(slot, "clip", None) is not None:
            session += 1
    return arrangement, session


def _delete_track(song, index, expected_name):
    """Delete the track at ``index`` after checking Live removed that one and only that one.

    ``Song.delete_track`` takes the track object on this build. That is the path the M2 duplicate
    restore has already exercised on real Live, even though the LOM map describes an index.
    """
    delete_track = getattr(song, "delete_track", None)
    if not callable(delete_track):
        raise ScriptError("UNSUPPORTED", "this Live build cannot delete a track")
    tracks = list(song.tracks)
    if index < 0 or index >= len(tracks):
        raise ScriptError("NOT_FOUND", "no track at index %d" % (index,))
    track = tracks[index]
    name = str(getattr(track, "name", "") or "")
    if name != expected_name:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "index %d now holds %r, not %r" % (index, name, expected_name),
        )
    follower = None
    if index + 1 < len(tracks):
        follower = str(getattr(tracks[index + 1], "name", "") or "")
    before = len(tracks)
    try:
        delete_track(track)
    except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
        raise ScriptError("LIVE_ERROR", "Live refused to delete %r: %s" % (name, exc))
    after = list(song.tracks)
    if len(after) != before - 1:
        raise ScriptError(
            "LIVE_ERROR",
            "Live reported success but the track count went from %d to %d" % (before, len(after)),
        )
    if follower is not None and (
        index >= len(after)
        or str(getattr(after[index], "name", "") or "") != follower
    ):
        raise ScriptError(
            "LIVE_ERROR",
            "Live deleted a track but %r did not move into index %d" % (follower, index),
        )
    return {"track": name, "track_index": index}


@command("tracks.delete")
def delete(args, song):
    check_args(args, allowed=("track", "track_index", "confirm", "dry_run"))
    dry_run = bool(args.get("dry_run", True))
    has_track = "track" in args
    has_index = "track_index" in args
    if has_track == has_index:
        raise ScriptError("BAD_ARGS", "give exactly one of track or track_index")
    if has_track:
        wanted = args.get("track")
        if not isinstance(wanted, str) or not wanted:
            raise ScriptError("BAD_ARGS", "track must be a non-empty string")
        index, track = _one_track(song, wanted)
    else:
        raw = args.get("track_index")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ScriptError("BAD_ARGS", "track_index must be a non-negative integer")
        if raw >= len(song.tracks):
            raise ScriptError("NOT_FOUND", "no track at index %s" % (raw,))
        index = raw
        track = song.tracks[index]

    if len(song.tracks) <= 1:
        raise ScriptError(
            "PRECONDITION_FAILED", "the Set has one track and Live needs at least one"
        )

    name = str(getattr(track, "name", "") or "")
    if getattr(track, "is_foldable", False):
        raise ScriptError(
            "PRECONDITION_FAILED",
            "%r is a group track; deleting it would delete the tracks inside it, "
            "so delete those first" % (name,),
        )
    arrangement, session = _track_clip_counts(track)
    contents = {
        "track": name,
        "track_index": index,
        "arrangement_clips": arrangement,
        "session_clips": session,
    }
    if dry_run:
        return {
            "dry_run": True,
            "contents": contents,
            "confirmation_required": True,
            "undo": [],
        }
    if args.get("confirm") is not True:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "%r was not deleted: this Live build cannot put a track back, "
            "so an apply needs confirm: true" % (name,),
        )
    deleted = _delete_track(song, index, name)
    return {"dry_run": False, "deleted": deleted, "undo": []}


@command("tracks.clean_empty")
def clean_empty(args, song):
    check_args(args, allowed=("tracks", "confirm", "dry_run"))
    dry_run = bool(args.get("dry_run", True))
    wanted = args.get("tracks")
    if wanted is not None:
        if not isinstance(wanted, list) or not wanted:
            raise ScriptError("BAD_ARGS", "tracks must be a non-empty list of names")
        for name in wanted:
            if not isinstance(name, str) or not name:
                raise ScriptError("BAD_ARGS", "tracks must contain non-empty names")
        if len(set(wanted)) != len(wanted):
            raise ScriptError("BAD_ARGS", "tracks contains a duplicate name")
        rows = [_one_track(song, name) for name in wanted]
    else:
        rows = list(enumerate(song.tracks))

    empty, occupied = [], []
    for index, track in rows:
        name = str(getattr(track, "name", "") or "")
        arrangement, session = _track_clip_counts(track)
        row = {
            "track": name,
            "track_index": index,
            "arrangement_clips": arrangement,
            "session_clips": session,
        }
        (empty if arrangement == 0 and session == 0 else occupied).append(row)

    if len(song.tracks) - len(empty) < 1:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "that would leave no tracks, and Live needs at least one",
        )
    if wanted is not None and occupied:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "%s is not empty, so the batch was refused"
            % ", ".join(repr(row["track"]) for row in occupied),
        )

    empty.sort(key=lambda row: row["track_index"], reverse=True)
    if dry_run:
        return {
            "dry_run": True,
            "empty": empty,
            "count": len(empty),
            "confirmation_required": True,
            "undo": [],
        }
    if args.get("confirm") is not True:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "%d empty track(s) were not deleted: this cannot be undone, "
            "so an apply needs confirm: true" % (len(empty),),
        )
    deleted = [_delete_track(song, row["track_index"], row["track"]) for row in empty]
    return {"dry_run": False, "deleted": deleted, "count": len(deleted), "undo": []}


def _routing_name(obj):
    if obj is None:
        return None
    for name in ("display_name", "name"):
        value = getattr(obj, name, None)
        if isinstance(value, str) and value:
            return value
    text = str(obj)
    return text or None


def _routing_options(track, attribute, label):
    try:
        options = list(getattr(track, attribute) or [])
    except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
        raise ScriptError("UNSUPPORTED", "this Live build cannot read %s: %s" % (label, exc))
    if not options:
        raise ScriptError(
            "PRECONDITION_FAILED", "%r has no %s to choose from"
            % (str(getattr(track, "name", "")), label),
        )
    return options


def _pick_routing(options, wanted, label):
    matches = [option for option in options if _routing_name(option) == wanted]
    if not matches:
        matches = [
            option for option in options
            if str(_routing_name(option) or "").casefold() == str(wanted).casefold()
        ]
    if not matches:
        raise ScriptError(
            "NOT_FOUND", "no %s named %r; available: %s"
            % (label, wanted, ", ".join(sorted(str(_routing_name(o)) for o in options))),
        )
    if len(matches) > 1:
        raise ScriptError(
            "AMBIGUOUS_REF", "%d %s options are named %r" % (len(matches), label, wanted)
        )
    return matches[0]


_ROUTING_FIELDS = (
    ("input_type", "input_routing_type", "available_input_routing_types", "input type"),
    ("input_channel", "input_routing_channel", "available_input_routing_channels", "input channel"),
    ("output_type", "output_routing_type", "available_output_routing_types", "output type"),
    ("output_channel", "output_routing_channel", "available_output_routing_channels", "output channel"),
)


@command("tracks.set_routing")
def set_routing(args, song):
    check_args(args, allowed=(
        "track", "input_type", "input_channel", "output_type", "output_channel",
        "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(
            key in args
            for key in ("track", "input_type", "input_channel", "output_type", "output_channel")
        ):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with routing changes")
        return _restore_routing(args, song, dry_run)

    track_name = args.get("track")
    if not isinstance(track_name, str) or not track_name:
        raise ScriptError("BAD_ARGS", "track must be a non-empty string")
    if not any(key in args for key in ("input_type", "input_channel", "output_type", "output_channel")):
        raise ScriptError("BAD_ARGS", "give at least one routing change")
    index, track = _one_track(song, track_name)

    before = {field: _routing_name(getattr(track, attribute, None))
              for field, attribute, _options, _label in _ROUTING_FIELDS}
    changes = []
    for field, attribute, options_attribute, label in _ROUTING_FIELDS:
        wanted = args.get(field)
        if wanted is None:
            continue
        if not isinstance(wanted, str) or not wanted:
            raise ScriptError("BAD_ARGS", "%s must be a non-empty string" % (field,))
        choice = _pick_routing(
            _routing_options(track, options_attribute, label), wanted, label
        )
        changes.append({
            "field": field,
            "from": _routing_name(getattr(track, attribute, None)),
            "to": _routing_name(choice),
        })
        if not dry_run:
            try:
                setattr(track, attribute, choice)
            except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
                raise ScriptError(
                    "UNSUPPORTED", "this Live build cannot set %s: %s" % (label, exc)
                )

    return {
        "dry_run": dry_run,
        "track": str(getattr(track, "name", "")),
        "track_index": index,
        "changes": changes,
        "undo": [{"track_index": index, **before}],
    }


def _restore_routing(args, song, dry_run):
    entries = args.get("restore")
    if not isinstance(entries, list) or not entries:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    changes, missing = [], []
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        try:
            index = int(entry["track_index"])
        except (KeyError, TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "restore entries need track_index")
        if index < 0 or index >= len(song.tracks):
            raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
        track = song.tracks[index]
        restored = {}
        for field, attribute, options_attribute, label in _ROUTING_FIELDS:
            wanted = entry.get(field)
            if wanted is None:
                continue
            try:
                choice = _pick_routing(
                    _routing_options(track, options_attribute, label), str(wanted), label
                )
            except ScriptError as exc:
                missing.append({"track_index": index, "field": field, "reason": str(exc)})
                continue
            if not dry_run:
                try:
                    setattr(track, attribute, choice)
                except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
                    raise ScriptError(
                        "UNSUPPORTED", "this Live build cannot set %s: %s" % (label, exc)
                    )
            restored[field] = str(wanted)
        if restored:
            changes.append({
                "track": str(getattr(track, "name", "")),
                "track_index": index,
                "restored": restored,
            })

    return {"dry_run": dry_run, "restored": len(changes), "changes": changes, "missing": missing}

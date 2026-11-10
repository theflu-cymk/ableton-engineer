"""Arrangement clip writes.

``Track.duplicate_clip_to_arrangement(clip, destination_time)`` is the Live Object Model's
arrangement duplicate primitive; ``destination_time`` is in beats. The source positions read from
``Clip.start_time`` are beats too, so a bar range is converted once and the relative offsets are
preserved.

The handler owns its undo token: a duplicate knows the destination track, name and beat it created,
and the restore branch deletes exactly that clip. The plan executor replays the token only when a
later step fails.
"""

from __future__ import annotations

import math

from ..dispatch import check_args, command
from ..errors import ScriptError
from .structure import WARP_MODES


def _attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _beats_per_bar(song):
    numerator = _attr(song, "signature_numerator", 4)
    denominator = _attr(song, "signature_denominator", 4)
    try:
        numerator = int(numerator)
        denominator = int(denominator)
    except (TypeError, ValueError):
        return 4.0
    if numerator <= 0 or denominator <= 0:
        return 4.0
    return numerator * 4.0 / denominator


def _targets(song, wanted):
    if wanted:
        known = [track.name for track in song.tracks]
        missing = [name for name in wanted if name not in known]
        if missing:
            raise ScriptError("NOT_FOUND", "no track named %s" % ", ".join(missing))
        return [
            (index, track)
            for index, track in enumerate(song.tracks)
            if track.name in wanted
        ]
    return list(enumerate(song.tracks))


def _bar(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ScriptError("BAD_ARGS", "%s must be a number" % name)
    if value < 1:
        raise ScriptError("BAD_ARGS", "%s must be >= 1" % name)
    return value


def _restore(args, song, dry_run):
    entries = args.get("restore")
    if not isinstance(entries, list):
        raise ScriptError("BAD_ARGS", "restore must be a list")
    restored, missing = [], []
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        try:
            index = int(entry["track_index"])
            start = float(entry["start"])
        except (KeyError, TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "restore entries need track_index and start")
        if index < 0 or index >= len(song.tracks):
            raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
        track = song.tracks[index]
        wanted_name = entry.get("name")
        found = None
        for clip in list(_attr(track, "arrangement_clips", []) or []):
            if abs(float(_attr(clip, "start_time", 0.0) or 0.0) - start) > 0.001:
                continue
            if wanted_name is not None and str(_attr(clip, "name", "")) != str(wanted_name):
                continue
            found = clip
            break
        if found is None:
            missing.append({"track": track.name, "track_index": index, "start": start})
            continue
        delete = getattr(track, "delete_clip", None)
        if not callable(delete):
            raise ScriptError(
                "UNSUPPORTED", "this Live build cannot delete an arrangement clip"
            )
        found_name = str(_attr(found, "name", ""))
        if not dry_run:
            delete(found)
        restored.append({
            "track": track.name,
            "track_index": index,
            "clip": found_name,
            "start": round(start, 4),
        })
    return {
        "dry_run": dry_run,
        "restored": len(restored),
        "changes": restored,
        "missing": missing,
    }


@command("clips.duplicate_range")
def duplicate_range(args, song):
    check_args(args, allowed=(
        "tracks", "from_bar", "to_bar", "destination_bar", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(key in args for key in ("tracks", "from_bar", "to_bar", "destination_bar")):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a range")
        return _restore(args, song, dry_run)

    wanted = list(args.get("tracks") or [])
    from_bar = _bar(args.get("from_bar"), "from_bar")
    to_bar = _bar(args.get("to_bar"), "to_bar")
    destination_bar = _bar(args.get("destination_bar"), "destination_bar")
    if to_bar <= from_bar:
        raise ScriptError("BAD_ARGS", "to_bar must be greater than from_bar")

    beats_per_bar = _beats_per_bar(song)
    from_beat = (from_bar - 1.0) * beats_per_bar
    to_beat = (to_bar - 1.0) * beats_per_bar
    destination_beat = (destination_bar - 1.0) * beats_per_bar

    changes, skipped, undo = [], [], []
    for index, track in _targets(song, wanted):
        duplicate = getattr(track, "duplicate_clip_to_arrangement", None)
        if not callable(duplicate):
            skipped.append({
                "track": track.name,
                "track_index": index,
                "reason": "this Live build cannot duplicate an arrangement clip",
            })
            continue
        source_clips = list(_attr(track, "arrangement_clips", []) or [])
        for clip in source_clips:
            start = float(_attr(clip, "start_time", 0.0) or 0.0)
            if start < from_beat - 1e-9 or start >= to_beat - 1e-9:
                continue
            destination = destination_beat + (start - from_beat)
            length = float(_attr(clip, "end_time", start) or start) - start
            change = {
                "track": track.name,
                "track_index": index,
                "clip": str(_attr(clip, "name", "")),
                "from": round(start, 4),
                "to": round(destination, 4),
                "length": round(max(0.0, length), 4),
            }
            changes.append(change)
            if dry_run:
                continue
            try:
                created = duplicate(clip, destination)
            except Exception as exc:  # noqa: BLE001 - the caller needs the Live reason
                raise ScriptError(
                    "LIVE_ERROR", "could not duplicate %r: %s" % (change["clip"], exc)
                )
            created_start = float(_attr(created, "start_time", destination) or destination)
            created_name = str(_attr(created, "name", change["clip"]) or change["clip"])
            undo.append({
                "track_index": index,
                "name": created_name,
                "start": created_start,
            })

    return {
        "dry_run": dry_run,
        "changes": changes,
        "skipped": skipped,
        "undo": undo,
    }


def _one_track(song, name):
    matches = [
        (index, track) for index, track in enumerate(song.tracks)
        if str(_attr(track, "name", "")) == name
    ]
    if not matches:
        raise ScriptError("NOT_FOUND", "no track named %r" % (name,))
    if len(matches) > 1:
        raise ScriptError(
            "AMBIGUOUS_REF",
            "%d tracks are named %r; rename one before editing its clips" % (len(matches), name),
        )
    return matches[0]


def _clip_refs(track):
    rows = []
    for clip in list(_attr(track, "arrangement_clips", []) or []):
        rows.append(("arrangement", None, clip, float(_attr(clip, "start_time", 0.0) or 0.0)))
    for slot, holder in enumerate(list(_attr(track, "clip_slots", []) or [])):
        clip = _attr(holder, "clip", None)
        if clip is not None:
            rows.append(("session", slot, clip, None))
    return rows


def _resolve_clip(song, track_name, clip_name, location=None, slot=None):
    index, track = _one_track(song, track_name)
    matches = [
        row for row in _clip_refs(track)
        if str(_attr(row[2], "name", "")) == clip_name
    ]
    if location is not None:
        if location not in ("arrangement", "session"):
            raise ScriptError("BAD_ARGS", "location must be 'arrangement' or 'session'")
        matches = [row for row in matches if row[0] == location]
    if slot is not None:
        if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0:
            raise ScriptError("BAD_ARGS", "slot must be a non-negative integer")
        if location == "arrangement":
            raise ScriptError("BAD_ARGS", "slot only applies to session clips")
        matches = [row for row in matches if row[0] == "session" and row[1] == slot]
    if not matches:
        raise ScriptError("NOT_FOUND", "no clip named %r on %r" % (clip_name, track_name))
    if len(matches) > 1:
        raise ScriptError(
            "AMBIGUOUS_REF",
            "multiple clips named %r on %r; use location or slot" % (clip_name, track_name),
        )
    return index, track, matches[0]


def _restore_clip(track, location, slot, start):
    for row in _clip_refs(track):
        if row[0] != location:
            continue
        if location == "session" and row[1] == slot:
            return row[2]
        if location == "arrangement" and start is not None:
            if abs(float(row[3]) - float(start)) <= 0.001:
                return row[2]
    return None


@command("clips.rename")
def rename(args, song):
    check_args(args, allowed=("track", "clip", "name", "location", "slot", "dry_run", "restore"))
    dry_run = bool(args.get("dry_run", True))
    restore = args.get("restore")
    if restore is not None:
        if any(key in args for key in ("track", "clip", "name", "location", "slot")):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a rename")
        if not isinstance(restore, list):
            raise ScriptError("BAD_ARGS", "restore must be a list")
        changes, missing = [], []
        for entry in reversed(restore):
            if not isinstance(entry, dict):
                raise ScriptError("BAD_ARGS", "restore entries must be objects")
            try:
                index = int(entry["track_index"])
                location = str(entry["location"])
                name = str(entry["name"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError("BAD_ARGS", "restore entries need track_index, location and name")
            if index < 0 or index >= len(song.tracks):
                raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
            if location not in ("arrangement", "session"):
                raise ScriptError("BAD_ARGS", "restore location must be arrangement or session")
            start = entry.get("start")
            clip = _restore_clip(song.tracks[index], location, entry.get("slot"), start)
            if clip is None:
                missing.append({"track_index": index, "location": location, "slot": entry.get("slot"), "start": start})
                continue
            old = str(_attr(clip, "name", ""))
            if not dry_run:
                clip.name = name
            changes.append({
                "track": song.tracks[index].name,
                "track_index": index,
                "location": location,
                "slot": entry.get("slot") if location == "session" else None,
                "start": start if location == "arrangement" else None,
                "from": old,
                "to": name,
            })
        return {"dry_run": dry_run, "restored": len(changes), "changes": changes, "missing": missing}

    track_name = args.get("track")
    clip_name = args.get("clip")
    name = args.get("name")
    if not isinstance(track_name, str) or not track_name:
        raise ScriptError("BAD_ARGS", "track must be a non-empty string")
    if not isinstance(clip_name, str) or not clip_name:
        raise ScriptError("BAD_ARGS", "clip must be a non-empty string")
    if not isinstance(name, str):
        raise ScriptError("BAD_ARGS", "name must be a string")
    location = args.get("location")
    index, track, row = _resolve_clip(song, track_name, clip_name, location, args.get("slot"))
    old = str(_attr(row[2], "name", ""))
    if not dry_run:
        row[2].name = name
    undo = [{
        "track_index": index,
        "location": row[0],
        "slot": row[1],
        "start": row[3],
        "name": old,
    }]
    return {
        "dry_run": dry_run,
        "changes": [{
            "track": track.name,
            "track_index": index,
            "location": row[0],
            "slot": row[1],
            "start": row[3],
            "from": old,
            "to": name,
        }],
        "undo": undo,
    }


_WARP_MODE_BY_NAME = {
    name.replace("-", "_"): value for value, name in WARP_MODES.items()
}


def _warp_mode_value(value):
    if isinstance(value, bool):
        raise ScriptError("BAD_ARGS", "mode must be a warp-mode name or integer")
    if isinstance(value, int):
        if value not in WARP_MODES:
            raise ScriptError("BAD_ARGS", "unknown warp mode %s" % (value,))
        return value
    if isinstance(value, str):
        key = value.strip().lower().replace("-", "_").replace(" ", "_")
        if key not in _WARP_MODE_BY_NAME:
            raise ScriptError(
                "BAD_ARGS",
                "mode must be one of %s" % ", ".join(sorted(WARP_MODES.values())),
            )
        return _WARP_MODE_BY_NAME[key]
    raise ScriptError("BAD_ARGS", "mode must be a warp-mode name or integer")


def _warp_mode_state(clip):
    mode = _attr(clip, "warp_mode", None)
    if mode is None:
        raise ScriptError(
            "UNSUPPORTED", "clip %r does not expose a readable warp mode"
            % (str(_attr(clip, "name", "")),),
        )
    try:
        mode = int(mode)
    except (TypeError, ValueError):
        raise ScriptError(
            "UNSUPPORTED", "clip %r has an unreadable warp mode"
            % (str(_attr(clip, "name", "")),),
        )
    if mode not in WARP_MODES:
        raise ScriptError(
            "UNSUPPORTED", "clip %r has unknown warp mode %s"
            % (str(_attr(clip, "name", "")), mode),
        )
    return mode


@command("clips.set_warp_mode")
def set_warp_mode(args, song):
    check_args(args, allowed=(
        "track", "clip", "location", "slot", "mode", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restore = args.get("restore")
    if restore is not None:
        if any(key in args for key in ("track", "clip", "location", "slot", "mode")):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a clip selection")
        if not isinstance(restore, list) or not restore:
            raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
        changes, missing = [], []
        for entry in reversed(restore):
            if not isinstance(entry, dict):
                raise ScriptError("BAD_ARGS", "restore entries must be objects")
            try:
                track_index = int(entry["track_index"])
                location = str(entry["location"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError(
                    "BAD_ARGS", "restore entries need track_index and location"
                )
            mode = _warp_mode_value(entry.get("mode"))
            if track_index < 0 or track_index >= len(song.tracks):
                raise ScriptError("NOT_FOUND", "no track at index %s" % (track_index,))
            if location not in ("arrangement", "session"):
                raise ScriptError("BAD_ARGS", "restore location must be arrangement or session")
            track = song.tracks[track_index]
            clip = _restore_clip(track, location, entry.get("slot"), entry.get("start"))
            if clip is None:
                missing.append({
                    "track_index": track_index,
                    "location": location,
                    "slot": entry.get("slot"),
                    "start": entry.get("start"),
                })
                continue
            current = _warp_mode_state(clip)
            if not dry_run:
                clip.warp_mode = mode
            changes.append({
                "track": str(_attr(track, "name", "")),
                "track_index": track_index,
                "location": location,
                "slot": entry.get("slot") if location == "session" else None,
                "start": entry.get("start") if location == "arrangement" else None,
                "clip": str(_attr(clip, "name", "")),
                "from": current,
                "to": mode,
            })
        return {
            "dry_run": dry_run,
            "restored": len(changes),
            "changes": changes,
            "missing": missing,
        }

    track_name = args.get("track")
    clip_name = args.get("clip")
    if not isinstance(track_name, str) or not track_name:
        raise ScriptError("BAD_ARGS", "track must be a non-empty string")
    if not isinstance(clip_name, str) or not clip_name:
        raise ScriptError("BAD_ARGS", "clip must be a non-empty string")
    if "mode" not in args:
        raise ScriptError("BAD_ARGS", "mode is required")
    mode = _warp_mode_value(args.get("mode"))
    index, track, row = _resolve_clip(
        song, track_name, clip_name, args.get("location"), args.get("slot")
    )
    clip = row[2]
    if bool(_attr(clip, "is_midi_clip", False)):
        raise ScriptError("UNSUPPORTED", "MIDI clips have no warp mode")
    current = _warp_mode_state(clip)
    warping = bool(_attr(clip, "warping", False))
    if not dry_run:
        try:
            clip.warp_mode = mode
        except Exception as exc:  # noqa: BLE001 - the Live reason belongs in the error
            raise ScriptError(
                "LIVE_ERROR", "could not set warp mode on %r: %s" % (clip_name, exc)
            )
    return {
        "dry_run": dry_run,
        "track": str(_attr(track, "name", "")),
        "track_index": index,
        "location": row[0],
        "slot": row[1],
        "start": row[3],
        "clip": clip_name,
        "warping": warping,
        "from": current,
        "to": mode,
        "from_name": WARP_MODES.get(current),
        "to_name": WARP_MODES.get(mode),
        "undo": [{
            "track_index": index,
            "location": row[0],
            "slot": row[1],
            "start": row[3],
            "clip": clip_name,
            "mode": current,
        }],
    }


def _loop_value(value, name):
    if isinstance(value, bool):
        raise ScriptError("BAD_ARGS", "%s must be a number" % name)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ScriptError("BAD_ARGS", "%s must be a number" % name)
    if not math.isfinite(value) or value < 0:
        raise ScriptError("BAD_ARGS", "%s must be a finite non-negative number" % name)
    return value


def _clip_length(clip):
    length = _attr(clip, "length", None)
    if length is None:
        start = _attr(clip, "start_time", None)
        end = _attr(clip, "end_time", None)
        if start is None or end is None:
            raise ScriptError(
                "UNSUPPORTED", "clip %r has no readable length"
                % (str(_attr(clip, "name", "")),),
            )
        length = float(end) - float(start)
    try:
        length = float(length)
    except (TypeError, ValueError):
        raise ScriptError(
            "UNSUPPORTED", "clip %r has an unreadable length"
            % (str(_attr(clip, "name", "")),),
        )
    if not math.isfinite(length) or length <= 0:
        raise ScriptError(
            "UNSUPPORTED", "clip %r has no positive length"
            % (str(_attr(clip, "name", "")),),
        )
    return length


def _loop_state(clip):
    start = _attr(clip, "loop_start", None)
    end = _attr(clip, "loop_end", None)
    if start is None or end is None:
        raise ScriptError(
            "UNSUPPORTED", "clip %r does not expose loop_start and loop_end"
            % (str(_attr(clip, "name", "")),),
        )
    try:
        start = float(start)
        end = float(end)
    except (TypeError, ValueError):
        raise ScriptError(
            "UNSUPPORTED", "clip %r has unreadable loop points"
            % (str(_attr(clip, "name", "")),),
        )
    if not math.isfinite(start) or not math.isfinite(end):
        raise ScriptError(
            "UNSUPPORTED", "clip %r has non-finite loop points"
            % (str(_attr(clip, "name", "")),),
        )
    return start, end, bool(_attr(clip, "looping", False))


def _set_loop_points(clip, start, end):
    old_start = _attr(clip, "loop_start", None)
    old_end = _attr(clip, "loop_end", None)
    try:
        clip.loop_start = start
        clip.loop_end = end
    except Exception as exc:  # noqa: BLE001 - the Live reason belongs in the error
        try:
            if old_start is not None:
                clip.loop_start = old_start
            if old_end is not None:
                clip.loop_end = old_end
        except Exception:
            pass
        message = str(exc)
        if isinstance(exc, AttributeError) or "setter" in message:
            raise ScriptError(
                "UNSUPPORTED", "this Live build exposes clip loop points read-only: %s" % message
            )
        raise ScriptError(
            "LIVE_ERROR", "could not set loop points on %r: %s"
            % (str(_attr(clip, "name", "")), message),
        )


@command("clips.fix_loop_points")
def fix_loop_points(args, song):
    check_args(args, allowed=(
        "track", "clip", "location", "slot", "loop_start", "loop_end", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restore = args.get("restore")
    if restore is not None:
        if any(key in args for key in (
            "track", "clip", "location", "slot", "loop_start", "loop_end",
        )):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a clip selection")
        if not isinstance(restore, list) or not restore:
            raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
        changes, missing = [], []
        for entry in reversed(restore):
            if not isinstance(entry, dict):
                raise ScriptError("BAD_ARGS", "restore entries must be objects")
            try:
                track_index = int(entry["track_index"])
                location = str(entry["location"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError(
                    "BAD_ARGS", "restore entries need track_index and location"
                )
            target_start = _loop_value(entry.get("loop_start"), "loop_start")
            target_end = _loop_value(entry.get("loop_end"), "loop_end")
            if target_start >= target_end:
                raise ScriptError("BAD_ARGS", "loop_start must be less than loop_end")
            if track_index < 0 or track_index >= len(song.tracks):
                raise ScriptError("NOT_FOUND", "no track at index %s" % (track_index,))
            if location not in ("arrangement", "session"):
                raise ScriptError("BAD_ARGS", "restore location must be arrangement or session")
            track = song.tracks[track_index]
            clip = _restore_clip(track, location, entry.get("slot"), entry.get("start"))
            if clip is None:
                missing.append({
                    "track_index": track_index,
                    "location": location,
                    "slot": entry.get("slot"),
                    "start": entry.get("start"),
                })
                continue
            current_start, current_end, looping = _loop_state(clip)
            if not dry_run:
                _set_loop_points(clip, target_start, target_end)
            changes.append({
                "track": str(_attr(track, "name", "")),
                "track_index": track_index,
                "location": location,
                "slot": entry.get("slot") if location == "session" else None,
                "start": entry.get("start") if location == "arrangement" else None,
                "clip": str(_attr(clip, "name", "")),
                "looping": looping,
                "from": {"loop_start": current_start, "loop_end": current_end},
                "to": {"loop_start": target_start, "loop_end": target_end},
            })
        return {
            "dry_run": dry_run,
            "restored": len(changes),
            "changes": changes,
            "missing": missing,
        }

    track_name = args.get("track")
    clip_name = args.get("clip")
    if not isinstance(track_name, str) or not track_name:
        raise ScriptError("BAD_ARGS", "track must be a non-empty string")
    if not isinstance(clip_name, str) or not clip_name:
        raise ScriptError("BAD_ARGS", "clip must be a non-empty string")
    if "loop_start" not in args or "loop_end" not in args:
        raise ScriptError("BAD_ARGS", "loop_start and loop_end are required")
    target_start = _loop_value(args.get("loop_start"), "loop_start")
    target_end = _loop_value(args.get("loop_end"), "loop_end")
    if target_start >= target_end:
        raise ScriptError("BAD_ARGS", "loop_start must be less than loop_end")

    index, track, row = _resolve_clip(
        song, track_name, clip_name, args.get("location"), args.get("slot")
    )
    clip = row[2]
    midi = bool(_attr(clip, "is_midi_clip", False))
    warping = bool(_attr(clip, "warping", False))
    if not midi and not warping:
        raise ScriptError(
            "UNSUPPORTED",
            "unwarped audio clips expose loop points in seconds; warp the clip first",
        )
    length = _clip_length(clip)
    if target_start >= length or target_end > length + 0.001:
        raise ScriptError(
            "BAD_ARGS",
            "loop points must lie inside the clip (length %s beats)" % round(length, 4),
        )
    current_start, current_end, looping = _loop_state(clip)
    if not dry_run:
        _set_loop_points(clip, target_start, target_end)
    return {
        "dry_run": dry_run,
        "track": str(_attr(track, "name", "")),
        "track_index": index,
        "location": row[0],
        "slot": row[1],
        "start": row[3],
        "clip": clip_name,
        "length": round(length, 4),
        "warping": warping,
        "looping": looping,
        "from": {"loop_start": current_start, "loop_end": current_end},
        "to": {"loop_start": target_start, "loop_end": target_end},
        "undo": [{
            "track_index": index,
            "location": row[0],
            "slot": row[1],
            "start": row[3],
            "clip": clip_name,
            "loop_start": current_start,
            "loop_end": current_end,
        }],
    }

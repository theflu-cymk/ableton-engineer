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


def _resolve_clip(song, track_name, clip_name, location=None, slot=None, start=None):
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
    if start is not None:
        if isinstance(start, bool):
            raise ScriptError("BAD_ARGS", "start must be a number")
        try:
            start = float(start)
        except (TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "start must be a number")
        matches = [
            row for row in matches
            if row[0] == "arrangement" and row[3] is not None
            and abs(float(row[3]) - start) <= 0.001
        ]
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


def _track_arg(song, args):
    """Resolve a track by name or index for creation commands."""
    name = args.get("track")
    index = args.get("track_index")
    if (name is None) == (index is None):
        raise ScriptError("BAD_ARGS", "give exactly one of track or track_index")
    if name is not None:
        return _one_track(song, name)
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ScriptError("BAD_ARGS", "track_index must be a non-negative integer")
    tracks = list(_attr(song, "tracks", []) or [])
    if index >= len(tracks):
        raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
    return index, tracks[index]


def _audio_creator(track):
    direct = getattr(track, "create_audio_clip", None)
    if callable(direct):
        return direct
    for slot in list(_attr(track, "clip_slots", []) or []):
        creator = getattr(slot, "create_audio_clip", None)
        if callable(creator) and not bool(_attr(slot, "has_clip", False)):
            return slot
    return None


@command("clips.create_audio")
def create_audio(args, song):
    """Create one arrangement audio clip from an absolute file path."""
    check_args(args, allowed=(
        "track", "track_index", "file_path", "start_beat", "name", "warping",
        "looping", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restore = args.get("restore")
    if restore is not None:
        if any(key in args for key in (
            "track", "track_index", "file_path", "start_beat", "name", "warping", "looping",
        )):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a creation")
        if not isinstance(restore, list) or not restore:
            raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
        deleted, missing = [], []
        for entry in reversed(restore):
            if not isinstance(entry, dict):
                raise ScriptError("BAD_ARGS", "restore entries must be objects")
            try:
                index = int(entry["track_index"])
                start = float(entry["start"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError("BAD_ARGS", "restore entries need track_index and start")
            if index < 0 or index >= len(song.tracks):
                missing.append({"track_index": index, "start": start, "reason": "no track"})
                continue
            track = song.tracks[index]
            found = None
            for clip in list(_attr(track, "arrangement_clips", []) or []):
                if abs(float(_attr(clip, "start_time", 0.0) or 0.0) - start) <= 0.001:
                    found = clip
                    break
            if found is None:
                missing.append({"track_index": index, "start": start, "reason": "no clip"})
                continue
            remover = getattr(track, "delete_clip", None)
            if not callable(remover):
                missing.append({"track_index": index, "start": start,
                                "reason": "this Live build cannot delete an arrangement clip"})
                continue
            if not dry_run:
                remover(found)
            deleted.append({"track_index": index, "start": start})
        return {"dry_run": dry_run, "restored": len(deleted), "changes": deleted,
                "missing": missing}

    index, track = _track_arg(song, args)
    if bool(_attr(track, "is_midi", False)):
        raise ScriptError("UNSUPPORTED", "create_audio needs an audio track")
    file_path = args.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        raise ScriptError("BAD_ARGS", "file_path must be an absolute path")
    try:
        start = float(args["start_beat"])
    except (KeyError, TypeError, ValueError):
        raise ScriptError("BAD_ARGS", "start_beat must be a number")
    if not math.isfinite(start) or start < 0:
        raise ScriptError("BAD_ARGS", "start_beat must be finite and >= 0")
    name = args.get("name")
    if name is not None and (not isinstance(name, str) or not name):
        raise ScriptError("BAD_ARGS", "name must be a non-empty string when given")
    if dry_run:
        return {"dry_run": True, "track": str(_attr(track, "name", "")),
                "track_index": index, "file_path": file_path, "start_beat": start,
                "name": name}

    creator = _audio_creator(track)
    if creator is None:
        raise ScriptError(
            "UNSUPPORTED", "this Live build cannot create an audio clip from a file path"
        )
    try:
        if hasattr(creator, "create_audio_clip"):
            clip = creator.create_audio_clip(file_path)
            duplicate = getattr(track, "duplicate_clip_to_arrangement", None)
            if not callable(duplicate):
                creator.delete_clip()
                raise ScriptError(
                    "UNSUPPORTED", "this Live build cannot move a session clip into the arrangement"
                )
            clip = duplicate(clip, start)
            creator.delete_clip()
        else:
            clip = creator(file_path, start)
    except ScriptError:
        raise
    except Exception as exc:  # noqa: BLE001 - Live's reason is the answer
        raise ScriptError(
            "LIVE_ERROR", "could not create audio clip from %r: %s" % (file_path, exc)
        )
    if clip is None:
        candidates = [
            row for row in list(_attr(track, "arrangement_clips", []) or [])
            if abs(float(_attr(row, "start_time", 0.0) or 0.0) - start) <= 0.001
        ]
        clip = candidates[-1] if candidates else None
    if clip is None:
        raise ScriptError("LIVE_ERROR", "Live did not report the created clip")
    try:
        if name is not None:
            clip.name = name
        if args.get("warping") is not None:
            clip.warping = bool(args["warping"])
        if args.get("looping") is not None:
            clip.looping = bool(args["looping"])
    except Exception as exc:  # noqa: BLE001 - creation must not leave a half-configured clip
        try:
            remover = getattr(track, "delete_clip", None)
            if callable(remover):
                remover(clip)
        except Exception:
            pass
        raise ScriptError("LIVE_ERROR", "clip created but could not be configured: %s" % (exc,))
    return {
        "dry_run": False,
        "track": str(_attr(track, "name", "")),
        "track_index": index,
        "clip": str(_attr(clip, "name", "")),
        "file_path": _attr(clip, "file_path", file_path),
        "start": round(float(_attr(clip, "start_time", start) or start), 4),
        "end": round(float(_attr(clip, "end_time", start) or start), 4),
        "length": round(float(_attr(clip, "end_time", start) or start) - start, 4),
        "warping": bool(_attr(clip, "warping", False)),
        "undo": [{"track_index": index, "start": start, "name": name}],
    }


@command("clips.create_midi")
def create_midi(args, song):
    """Create one empty arrangement MIDI clip on a MIDI track."""
    check_args(args, allowed=(
        "track", "track_index", "start_beat", "length_beats", "name", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restore = args.get("restore")
    if restore is not None:
        if any(key in args for key in (
            "track", "track_index", "start_beat", "length_beats", "name",
        )):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a creation")
        if not isinstance(restore, list) or not restore:
            raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
        deleted, missing = [], []
        for entry in reversed(restore):
            if not isinstance(entry, dict):
                raise ScriptError("BAD_ARGS", "restore entries must be objects")
            try:
                index = int(entry["track_index"])
                start = float(entry["start"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError("BAD_ARGS", "restore entries need track_index and start")
            if index < 0 or index >= len(song.tracks):
                missing.append({"track_index": index, "start": start, "reason": "no track"})
                continue
            track = song.tracks[index]
            found = None
            for clip in list(_attr(track, "arrangement_clips", []) or []):
                if abs(float(_attr(clip, "start_time", 0.0) or 0.0) - start) <= 0.001:
                    found = clip
                    break
            if found is None:
                missing.append({"track_index": index, "start": start, "reason": "no clip"})
                continue
            remover = getattr(track, "delete_clip", None)
            if not callable(remover):
                missing.append({"track_index": index, "start": start,
                                "reason": "this Live build cannot delete an arrangement clip"})
                continue
            if not dry_run:
                remover(found)
            deleted.append({"track_index": index, "start": start})
        return {"dry_run": dry_run, "restored": len(deleted), "changes": deleted,
                "missing": missing}

    index, track = _track_arg(song, args)
    if not (bool(_attr(track, "is_midi", False))
            or bool(_attr(track, "has_midi_input", False))):
        raise ScriptError("UNSUPPORTED", "create_midi needs a MIDI track")
    try:
        start = float(args["start_beat"])
        length = float(args.get("length_beats", 16.0))
    except (KeyError, TypeError, ValueError):
        raise ScriptError("BAD_ARGS", "start_beat and length_beats must be numbers")
    if not math.isfinite(start) or start < 0:
        raise ScriptError("BAD_ARGS", "start_beat must be finite and >= 0")
    if not math.isfinite(length) or length <= 0:
        raise ScriptError("BAD_ARGS", "length_beats must be finite and > 0")
    name = args.get("name")
    if name is not None and (not isinstance(name, str) or not name):
        raise ScriptError("BAD_ARGS", "name must be a non-empty string when given")
    if dry_run:
        return {"dry_run": True, "track": str(_attr(track, "name", "")),
                "track_index": index, "start_beat": start, "length_beats": length,
                "name": name}

    creator = getattr(track, "create_midi_clip", None)
    if not callable(creator):
        raise ScriptError("UNSUPPORTED", "this Live build cannot create an arrangement MIDI clip")
    try:
        clip = creator(start, length)
    except Exception as exc:  # noqa: BLE001 - Live's reason is the answer
        raise ScriptError("LIVE_ERROR", "could not create MIDI clip: %s" % (exc,))
    if clip is None:
        candidates = [
            row for row in list(_attr(track, "arrangement_clips", []) or [])
            if abs(float(_attr(row, "start_time", 0.0) or 0.0) - start) <= 0.001
        ]
        clip = candidates[-1] if candidates else None
    if clip is None:
        raise ScriptError("LIVE_ERROR", "Live did not report the created MIDI clip")
    try:
        if name is not None:
            clip.name = name
    except Exception as exc:  # noqa: BLE001 - creation must not leave a half-configured clip
        try:
            remover = getattr(track, "delete_clip", None)
            if callable(remover):
                remover(clip)
        except Exception:
            pass
        raise ScriptError("LIVE_ERROR", "MIDI clip created but could not be named: %s" % (exc,))
    return {
        "dry_run": False,
        "track": str(_attr(track, "name", "")),
        "track_index": index,
        "clip": str(_attr(clip, "name", "")),
        "start": round(float(_attr(clip, "start_time", start) or start), 4),
        "end": round(float(_attr(clip, "end_time", start) or start), 4),
        "length": round(float(_attr(clip, "end_time", start) or start) - start, 4),
        "undo": [{"track_index": index, "start": start, "name": name}],
    }


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


def _warping_state(clip):
    warping = _attr(clip, "warping", None)
    if warping is None:
        raise ScriptError(
            "UNSUPPORTED",
            "clip %r does not expose a readable Warp switch"
            % (str(_attr(clip, "name", "")),),
        )
    return bool(warping)


@command("clips.set_warping")
def set_warping(args, song):
    check_args(args, allowed=(
        "track", "clip", "location", "slot", "enabled", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restore = args.get("restore")
    if restore is not None:
        if any(key in args for key in ("track", "clip", "location", "slot", "enabled")):
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
                    "BAD_ARGS",
                    "restore entries need track_index and location",
                )
            enabled = entry.get("warping")
            if not isinstance(enabled, bool):
                raise ScriptError("BAD_ARGS", "restore warping must be true or false")
            if track_index < 0 or track_index >= len(song.tracks):
                raise ScriptError("NOT_FOUND", "no track at index %s" % (track_index,))
            if location not in ("arrangement", "session"):
                raise ScriptError(
                    "BAD_ARGS", "restore location must be arrangement or session"
                )
            track = song.tracks[track_index]
            clip = _restore_clip(track, location, entry.get("slot"), entry.get("start"))
            if clip is None:
                missing.append({
                    "track_index": track_index,
                    "location": location,
                    "slot": entry.get("slot"),
                    "start": entry.get("start"),
                    "clip": entry.get("clip"),
                })
                continue
            current = _warping_state(clip)
            if not dry_run:
                try:
                    clip.warping = enabled
                except Exception as exc:  # noqa: BLE001 - the Live reason belongs in the error
                    raise ScriptError(
                        "LIVE_ERROR",
                        "could not restore Warp on %r: %s"
                        % (str(_attr(clip, "name", "")), exc),
                    )
            changes.append({
                "track": str(_attr(track, "name", "")),
                "track_index": track_index,
                "location": location,
                "slot": entry.get("slot") if location == "session" else None,
                "start": entry.get("start") if location == "arrangement" else None,
                "clip": str(_attr(clip, "name", "")),
                "from": current,
                "to": enabled,
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
    if "enabled" not in args:
        raise ScriptError("BAD_ARGS", "enabled is required")
    enabled = args.get("enabled")
    if not isinstance(enabled, bool):
        raise ScriptError("BAD_ARGS", "enabled must be true or false")
    index, track, row = _resolve_clip(
        song, track_name, clip_name, args.get("location"), args.get("slot")
    )
    clip = row[2]
    if bool(_attr(clip, "is_midi_clip", False)):
        raise ScriptError("UNSUPPORTED", "MIDI clips have no Warp switch")
    current = _warping_state(clip)
    if not dry_run:
        try:
            clip.warping = enabled
        except Exception as exc:  # noqa: BLE001 - the Live reason belongs in the error
            raise ScriptError(
                "LIVE_ERROR",
                "could not set Warp on %r: %s" % (clip_name, exc),
            )
    return {
        "dry_run": dry_run,
        "track": str(_attr(track, "name", "")),
        "track_index": index,
        "location": row[0],
        "slot": row[1],
        "start": row[3],
        "clip": clip_name,
        "from": current,
        "to": enabled,
        "undo": [{
            "track_index": index,
            "location": row[0],
            "slot": row[1],
            "start": row[3],
            "clip": clip_name,
            "warping": current,
        }],
    }


def _warp_float(value, name, default, low, high):
    if value is None:
        return default
    if isinstance(value, bool):
        raise ScriptError("BAD_ARGS", "%s must be a number" % name)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ScriptError("BAD_ARGS", "%s must be a number" % name)
    if not math.isfinite(value) or value < low or value > high:
        raise ScriptError(
            "BAD_ARGS", "%s must be between %s and %s" % (name, low, high)
        )
    return value


def _warp_marker_rows(clip):
    """Normalise Live's marker vector without assuming one Python shape.

    Live 12 exposes ``warp_markers`` as marker objects in a Remote Script, while Max and some
    bridge builds return dictionaries or a dict of parallel vectors. Reading all three shapes here
    keeps the write path from failing for a representation difference rather than an API gap.
    """
    try:
        raw = clip.warp_markers
    except Exception as exc:  # noqa: BLE001 - the reason is the answer
        raise ScriptError(
            "UNSUPPORTED",
            "clip %r does not expose readable warp markers: %s"
            % (str(_attr(clip, "name", "")), exc),
        )
    if raw is None:
        return []
    if isinstance(raw, dict):
        if "warp_markers" in raw:
            raw = raw.get("warp_markers") or []
        elif "beat_time" in raw:
            beats = raw.get("beat_time") or []
            samples = raw.get("sample_time") or []
            raw = [
                {"beat_time": beat, "sample_time": sample}
                for beat, sample in zip(beats, samples)
            ]
        else:
            raw = list(raw.values())
    rows = []
    for marker in raw or []:
        if isinstance(marker, dict):
            beat = marker.get("beat_time")
            sample = marker.get("sample_time")
        else:
            beat = _attr(marker, "beat_time", None)
            sample = _attr(marker, "sample_time", None)
        try:
            beat = float(beat)
        except (TypeError, ValueError):
            raise ScriptError(
                "UNSUPPORTED",
                "clip %r returned a warp marker without a readable beat_time"
                % (str(_attr(clip, "name", "")),),
            )
        if not math.isfinite(beat):
            raise ScriptError(
                "UNSUPPORTED",
                "clip %r returned a non-finite warp marker"
                % (str(_attr(clip, "name", "")),),
            )
        try:
            sample = None if sample is None else float(sample)
        except (TypeError, ValueError):
            sample = None
        rows.append({"beat_time": beat, "sample_time": sample})
    rows.sort(key=lambda row: row["beat_time"])
    return rows


def _map_number(value, name):
    if isinstance(value, bool):
        raise ScriptError("BAD_ARGS", "%s must be a number" % name)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ScriptError("BAD_ARGS", "%s must be a number" % name)
    if not math.isfinite(value):
        raise ScriptError("BAD_ARGS", "%s must be finite" % name)
    return value


def _clip_bounds(clip):
    start = _attr(clip, "start_marker", None)
    end = _attr(clip, "end_marker", None)
    if start is None or end is None:
        raise ScriptError(
            "UNSUPPORTED",
            "clip %r does not expose start_marker and end_marker"
            % (str(_attr(clip, "name", "")),),
        )
    try:
        start = float(start)
        end = float(end)
    except (TypeError, ValueError):
        raise ScriptError(
            "UNSUPPORTED", "clip %r has unreadable start/end markers"
            % (str(_attr(clip, "name", "")),),
        )
    if not math.isfinite(start) or not math.isfinite(end) or start >= end:
        raise ScriptError(
            "UNSUPPORTED", "clip %r has invalid start/end markers"
            % (str(_attr(clip, "name", "")),),
        )
    return start, end


def _clip_sample_limit(clip):
    length = _attr(clip, "sample_length", None)
    rate = _attr(clip, "sample_rate", None)
    try:
        length = None if length is None else float(length)
        rate = None if rate is None else float(rate)
    except (TypeError, ValueError):
        return None
    if length is None or rate is None or rate <= 0 or length <= 0:
        return None
    return length / rate


def _set_clip_bounds(clip, start, end):
    old_start, old_end = _clip_bounds(clip)
    if start >= end:
        raise ScriptError("BAD_ARGS", "start_marker must be less than end_marker")
    try:
        if end > old_end:
            clip.end_marker = end
        clip.start_marker = start
        clip.end_marker = end
    except Exception as exc:  # noqa: BLE001 - the Live reason belongs in the error
        try:
            clip.start_marker = old_start
            clip.end_marker = old_end
        except Exception:
            pass
        message = str(exc)
        if isinstance(exc, AttributeError) or "setter" in message:
            raise ScriptError(
                "UNSUPPORTED", "this Live build exposes clip bounds read-only: %s" % message
            )
        raise ScriptError(
            "LIVE_ERROR", "could not set clip bounds on %r: %s"
            % (str(_attr(clip, "name", "")), message),
        )


def _remove_interior_markers(clip, rows):
    remove = getattr(clip, "remove_warp_marker", None)
    if not callable(remove):
        raise ScriptError(
            "UNSUPPORTED",
            "this Live build does not expose Clip.remove_warp_marker",
        )
    for row in rows[1:-1]:
        remove(row["beat_time"])


def _add_markers(clip, markers):
    add = getattr(clip, "add_warp_marker", None)
    if not callable(add):
        raise ScriptError(
            "UNSUPPORTED",
            "this Live build does not expose Clip.add_warp_marker",
        )
    for marker in markers:
        add({"beat_time": marker["beat_time"], "sample_time": marker["sample_time"]})


def _restore_marker_state(clip, rows, start, end):
    """Put a captured marker vector and bounds back exactly."""
    current = _warp_marker_rows(clip)
    if current:
        _remove_interior_markers(clip, current)
    _add_markers(clip, rows[1:-1])
    _set_clip_bounds(clip, start, end)


def _validated_map_markers(clip, raw):
    if not isinstance(raw, list) or not raw:
        raise ScriptError("BAD_ARGS", "markers must be a non-empty list")
    limit = _clip_sample_limit(clip)
    markers = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "markers[%d] must be an object" % index)
        unknown = sorted(set(entry) - {"beat_time", "sample_time"})
        if unknown:
            raise ScriptError(
                "BAD_ARGS", "markers[%d] has unknown key(s): %s" % (index, ", ".join(unknown))
            )
        beat = _map_number(entry.get("beat_time"), "markers[%d].beat_time" % index)
        sample = _map_number(entry.get("sample_time"), "markers[%d].sample_time" % index)
        if sample < 0 or (limit is not None and sample > limit + 1e-6):
            raise ScriptError(
                "BAD_ARGS", "markers[%d].sample_time is outside the source" % index
            )
        if markers and beat <= markers[-1]["beat_time"] + 1e-9:
            raise ScriptError("BAD_ARGS", "markers must be sorted by increasing beat_time")
        markers.append({"beat_time": beat, "sample_time": sample})
    return markers


@command("clips.warp_map")
def warp_map(args, song):
    """Read one audio clip's source path, bounds and exact warp-marker map."""
    check_args(args, allowed=("track", "clip", "location", "slot"))
    track_name = args.get("track")
    clip_name = args.get("clip")
    if not isinstance(track_name, str) or not track_name:
        raise ScriptError("BAD_ARGS", "track must be a non-empty string")
    if not isinstance(clip_name, str) or not clip_name:
        raise ScriptError("BAD_ARGS", "clip must be a non-empty string")
    index, track, row = _resolve_clip(
        song, track_name, clip_name, args.get("location"), args.get("slot")
    )
    clip = row[2]
    if bool(_attr(clip, "is_midi_clip", False)):
        raise ScriptError("UNSUPPORTED", "MIDI clips have no warp map")
    rows = _warp_marker_rows(clip)
    try:
        start, end = _clip_bounds(clip)
    except ScriptError:
        start, end = None, None
    return {
        "track": str(_attr(track, "name", "")),
        "track_index": index,
        "location": row[0],
        "slot": row[1],
        "start": row[3],
        "clip": clip_name,
        "file_path": _attr(clip, "file_path", None),
        "warping": bool(_attr(clip, "warping", False)),
        "warp_mode": _attr(clip, "warp_mode", None),
        "start_marker": None if start is None else round(start, 6),
        "end_marker": None if end is None else round(end, 6),
        "sample_length": _attr(clip, "sample_length", None),
        "sample_rate": _attr(clip, "sample_rate", None),
        "markers": rows,
        "marker_count": len(rows),
    }


@command("clips.apply_warp_map")
def apply_warp_map(args, song):
    """Replace a clip's interior warp map and bounds, with exact restore."""
    check_args(args, allowed=(
        "track", "clip", "location", "slot", "markers", "start_marker", "end_marker",
        "replace", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restore = args.get("restore")
    if restore is not None:
        if any(key in args for key in (
            "track", "clip", "location", "slot", "markers", "start_marker", "end_marker",
            "replace",
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
                raise ScriptError("BAD_ARGS", "restore entries need track_index and location")
            if track_index < 0 or track_index >= len(song.tracks):
                raise ScriptError("NOT_FOUND", "no track at index %s" % (track_index,))
            if location not in ("arrangement", "session"):
                raise ScriptError("BAD_ARGS", "restore location must be arrangement or session")
            clip = _restore_clip(
                song.tracks[track_index], location, entry.get("slot"), entry.get("start")
            )
            if clip is None:
                missing.append({
                    "track_index": track_index,
                    "location": location,
                    "slot": entry.get("slot"),
                    "start": entry.get("start"),
                })
                continue
            rows = entry.get("markers")
            if not isinstance(rows, list) or not rows:
                raise ScriptError("BAD_ARGS", "restore entry needs a marker list")
            parsed = []
            for marker in rows:
                if not isinstance(marker, dict):
                    raise ScriptError("BAD_ARGS", "restore markers must be objects")
                parsed.append({
                    "beat_time": _map_number(marker.get("beat_time"), "marker beat"),
                    "sample_time": _map_number(marker.get("sample_time"), "marker sample"),
                })
            start = _map_number(entry.get("start_marker"), "start_marker")
            end = _map_number(entry.get("end_marker"), "end_marker")
            if start >= end:
                raise ScriptError("BAD_ARGS", "restore start_marker must be less than end_marker")
            if not dry_run:
                _restore_marker_state(clip, parsed, start, end)
            changes.append({
                "track": str(_attr(song.tracks[track_index], "name", "")),
                "track_index": track_index,
                "clip": str(_attr(clip, "name", "")),
                "markers": len(parsed),
                "start_marker": start,
                "end_marker": end,
            })
        return {"dry_run": dry_run, "restored": len(changes), "changes": changes,
                "missing": missing}

    track_name = args.get("track")
    clip_name = args.get("clip")
    if not isinstance(track_name, str) or not track_name:
        raise ScriptError("BAD_ARGS", "track must be a non-empty string")
    if not isinstance(clip_name, str) or not clip_name:
        raise ScriptError("BAD_ARGS", "clip must be a non-empty string")
    index, track, row = _resolve_clip(
        song, track_name, clip_name, args.get("location"), args.get("slot")
    )
    clip = row[2]
    if bool(_attr(clip, "is_midi_clip", False)):
        raise ScriptError("UNSUPPORTED", "MIDI clips have no warp map")
    if not bool(_attr(clip, "warping", False)):
        raise ScriptError("UNSUPPORTED", "turn Warp on before applying a warp map")
    old_rows = _warp_marker_rows(clip)
    if len(old_rows) < 2 or any(row.get("sample_time") is None for row in old_rows):
        raise ScriptError(
            "UNSUPPORTED",
            "clip %r has no readable marker sample times, so the change could not be undone"
            % (clip_name,),
        )
    old_start, old_end = _clip_bounds(clip)
    markers = _validated_map_markers(clip, args.get("markers"))
    start = old_start if args.get("start_marker") is None else _map_number(
        args.get("start_marker"), "start_marker"
    )
    end = old_end if args.get("end_marker") is None else _map_number(
        args.get("end_marker"), "end_marker"
    )
    if start < 0 or end <= start:
        raise ScriptError("BAD_ARGS", "bounds must satisfy 0 <= start_marker < end_marker")
    replace = bool(args.get("replace", True))
    first, last = old_rows[0]["beat_time"], old_rows[-1]["beat_time"]
    add = [
        marker for marker in markers
        if marker["beat_time"] > first + 1e-9
        and marker["beat_time"] < last - 1e-9
    ]
    skipped = len(markers) - len(add)
    if not add:
        raise ScriptError("BAD_ARGS", "no marker lies inside the clip's anchored range")
    if dry_run:
        return {
            "dry_run": True,
            "track": str(_attr(track, "name", "")),
            "track_index": index,
            "clip": clip_name,
            "replace": replace,
            "remove": len(old_rows[1:-1]) if replace else 0,
            "add": len(add),
            "skipped_boundaries": skipped,
            "from": {"start_marker": old_start, "end_marker": old_end,
                     "marker_count": len(old_rows)},
            "to": {"start_marker": start, "end_marker": end,
                   "marker_count": (len(old_rows) - len(old_rows[1:-1]) if replace
                                    else len(old_rows)) + len(add)},
        }
    try:
        if replace:
            _remove_interior_markers(clip, old_rows)
        _add_markers(clip, add)
        _set_clip_bounds(clip, start, end)
    except Exception as exc:  # noqa: BLE001 - rollback then report the Live reason
        try:
            _restore_marker_state(clip, old_rows, old_start, old_end)
        except Exception as rollback_exc:  # noqa: BLE001 - both failures matter
            raise ScriptError(
                "LIVE_ERROR",
                "warp map failed (%s) and rollback failed (%s)" % (exc, rollback_exc),
            )
        raise ScriptError("LIVE_ERROR", "could not apply warp map: %s" % (exc,))
    after = _warp_marker_rows(clip)
    new_start, new_end = _clip_bounds(clip)
    return {
        "dry_run": False,
        "track": str(_attr(track, "name", "")),
        "track_index": index,
        "clip": clip_name,
        "replace": replace,
        "removed": len(old_rows[1:-1]) if replace else 0,
        "added": len(add),
        "skipped_boundaries": skipped,
        "start_marker": round(new_start, 6),
        "end_marker": round(new_end, 6),
        "marker_count": len(after),
        "undo": [{
            "track_index": index,
            "location": row[0],
            "slot": row[1],
            "start": row[3],
            "clip": clip_name,
            "markers": old_rows,
            "start_marker": old_start,
            "end_marker": old_end,
        }],
    }


def _move_warp_marker(clip, beat, distance):
    move = getattr(clip, "move_warp_marker", None)
    if not callable(move):
        raise ScriptError(
            "UNSUPPORTED",
            "this Live build does not expose Clip.move_warp_marker; use Live's Warp "
            "marker handles, or install a Live build with the marker write API",
        )
    try:
        move(beat, distance)
    except Exception as exc:  # noqa: BLE001 - the Live reason belongs in the error
        raise ScriptError(
            "LIVE_ERROR",
            "could not move the warp marker at beat %s on %r: %s"
            % (round(beat, 4), str(_attr(clip, "name", "")), exc),
        )


def _warp_targets(song, args):
    has_name = "track" in args
    has_index = "track_index" in args
    if has_name and has_index:
        raise ScriptError("BAD_ARGS", "give at most one of track or track_index")
    if not has_name and not has_index:
        return list(enumerate(song.tracks))
    if has_name:
        name = args.get("track")
        if not isinstance(name, str) or not name:
            raise ScriptError("BAD_ARGS", "track must be a non-empty string")
        return [_one_track(song, name)]
    raw = args.get("track_index")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ScriptError("BAD_ARGS", "track_index must be a non-negative integer")
    if raw >= len(song.tracks):
        raise ScriptError("NOT_FOUND", "no track at index %s" % (raw,))
    return [(raw, song.tracks[raw])]


def _restore_warp(args, song, dry_run):
    entries = args.get("restore")
    if not isinstance(entries, list) or not entries:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    changes, missing = [], []
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        try:
            index = int(entry["track_index"])
            location = str(entry["location"])
            marker_beat = float(entry["marker_beat"])
            distance = float(entry["distance"])
        except (KeyError, TypeError, ValueError):
            raise ScriptError(
                "BAD_ARGS",
                "restore entries need track_index, location, marker_beat and distance",
            )
        if index < 0 or index >= len(song.tracks):
            missing.append({"track_index": index, "reason": "no track at that index"})
            continue
        if location not in ("arrangement", "session"):
            raise ScriptError("BAD_ARGS", "restore location must be arrangement or session")
        track = song.tracks[index]
        refs = _clip_refs(track)
        clip = None
        clip_index = entry.get("clip_index")
        if isinstance(clip_index, int) and not isinstance(clip_index, bool):
            if 0 <= clip_index < len(refs) and refs[clip_index][0] == location:
                clip = refs[clip_index][2]
        if clip is None:
            clip = _restore_clip(track, location, entry.get("slot"), entry.get("start"))
        if clip is None:
            missing.append({
                "track_index": index,
                "location": location,
                "slot": entry.get("slot"),
                "start": entry.get("start"),
                "clip": entry.get("clip"),
            })
            continue
        rows = _warp_marker_rows(clip)
        if not rows:
            missing.append({"track_index": index, "clip": str(_attr(clip, "name", "")),
                            "reason": "clip has no readable markers"})
            continue
        nearest = min(rows, key=lambda row: abs(row["beat_time"] - marker_beat))
        if abs(nearest["beat_time"] - marker_beat) > 0.01:
            missing.append({"track_index": index, "clip": str(_attr(clip, "name", "")),
                            "marker_beat": marker_beat, "reason": "marker no longer exists"})
            continue
        if not dry_run:
            _move_warp_marker(clip, nearest["beat_time"], -distance)
        changes.append({
            "track": str(_attr(track, "name", "")),
            "track_index": index,
            "clip": str(_attr(clip, "name", "")),
            "location": location,
            "marker": round(nearest["beat_time"], 4),
            "restored_by": round(-distance, 4),
        })
    return {"dry_run": dry_run, "restored": len(changes), "changes": changes, "missing": missing}


@command("clips.align_warp_markers")
def align_warp_markers(args, song):
    """Snap interior warp markers toward a grid across every warped audio clip.

    The command walks tracks and clips itself, so duplicate clip names are irrelevant. It never
    touches the first or the hidden last marker: those anchor the clip's boundaries. A marker
    farther than ``max_shift`` from the grid is reported rather than yanked, because a large move
    is a musical decision, not a cleanup.
    """
    check_args(args, allowed=(
        "track", "track_index", "grid", "max_shift", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(key in args for key in ("track", "track_index", "grid", "max_shift")):
            raise ScriptError(
                "BAD_ARGS", "restore cannot be combined with track, grid or max_shift"
            )
        return _restore_warp(args, song, dry_run)

    grid = _warp_float(args.get("grid"), "grid", 0.25, 0.03125, 16.0)
    max_shift = _warp_float(args.get("max_shift"), "max_shift", 0.25, 0.0, 4.0)
    changes, skipped, undo = [], [], []
    clips_moved, moved = 0, 0
    for track_index, track in _warp_targets(song, args):
        try:
            refs = _clip_refs(track)
        except Exception as exc:  # noqa: BLE001 - a group/return has no clip list
            skipped.append({"track": str(_attr(track, "name", "")),
                            "reason": "no addressable clip list: %s" % exc})
            continue
        for clip_index, (location, slot, clip, start) in enumerate(refs):
            if bool(_attr(clip, "is_midi_clip", False)):
                continue
            if not bool(_attr(clip, "warping", False)):
                continue
            name = str(_attr(clip, "name", ""))
            try:
                markers = _warp_marker_rows(clip)
            except ScriptError as exc:
                skipped.append({"track": str(_attr(track, "name", "")), "clip": name,
                                "reason": exc.message})
                continue
            if len(markers) < 3:
                skipped.append({"track": str(_attr(track, "name", "")), "clip": name,
                                "reason": "needs at least three markers (two boundaries and one interior)"})
                continue
            clip_changes = []
            for position in range(1, len(markers) - 1):
                beat = markers[position]["beat_time"]
                target = round(beat / grid) * grid
                distance = target - beat
                if abs(distance) <= 1e-9:
                    continue
                if abs(distance) > max_shift + 1e-9:
                    skipped.append({
                        "track": str(_attr(track, "name", "")), "clip": name,
                        "marker": round(beat, 4), "reason": "move exceeds max_shift",
                    })
                    continue
                if target < 0:
                    continue
                if not dry_run:
                    _move_warp_marker(clip, beat, distance)
                change = {
                    "track": str(_attr(track, "name", "")),
                    "track_index": track_index,
                    "clip": name,
                    "clip_index": clip_index,
                    "location": location,
                    "slot": slot,
                    "start": None if start is None else round(start, 4),
                    "marker": round(beat, 4),
                    "to": round(target, 4),
                    "distance": round(distance, 6),
                }
                clip_changes.append(change)
                undo.append({
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "location": location,
                    "slot": slot,
                    "start": None if start is None else round(start, 4),
                    "clip": name,
                    "marker_beat": round(target, 6),
                    "distance": distance,
                })
                moved += 1
            if clip_changes:
                clips_moved += 1
                changes.extend(clip_changes)
    return {
        "dry_run": dry_run,
        "grid": grid,
        "max_shift": max_shift,
        "clips": clips_moved,
        "moved": moved,
        "changes": changes,
        "skipped": skipped,
        "undo": undo,
    }


_REFERENCE_WORDS = ("drum", "kick", "perc", "beat", "break")


def _arrangement_marker_positions(track):
    """Reference transients in arrangement beats, not clip-relative beats."""
    positions = []
    for location, _slot, clip, start in _clip_refs(track):
        if location != "arrangement" or bool(_attr(clip, "is_midi_clip", False)):
            continue
        if not bool(_attr(clip, "warping", False)):
            continue
        try:
            markers = _warp_marker_rows(clip)
        except ScriptError:
            continue
        base = 0.0 if start is None else float(start)
        for marker in markers:
            positions.append(round(base + marker["beat_time"], 6))
    positions.sort()
    unique = []
    for position in positions:
        if not unique or abs(position - unique[-1]) > 1e-4:
            unique.append(position)
    return unique


def _pick_reference(song, args):
    has_name = "reference_track" in args
    has_index = "reference_track_index" in args
    if has_name and has_index:
        raise ScriptError("BAD_ARGS", "give at most one of reference_track or reference_track_index")
    if has_name:
        name = args.get("reference_track")
        if not isinstance(name, str) or not name:
            raise ScriptError("BAD_ARGS", "reference_track must be a non-empty string")
        index, track = _one_track(song, name)
        positions = _arrangement_marker_positions(track)
        if len(positions) < 2:
            raise ScriptError(
                "PRECONDITION_FAILED",
                "reference track %r has no readable warped audio markers; add transient markers "
                "to a drum or percussion clip first" % name,
            )
        return index, track, positions, "named"
    if has_index:
        index = args.get("reference_track_index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ScriptError("BAD_ARGS", "reference_track_index must be a non-negative integer")
        if index >= len(song.tracks):
            raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
        track = song.tracks[index]
        positions = _arrangement_marker_positions(track)
        if len(positions) < 2:
            raise ScriptError(
                "PRECONDITION_FAILED",
                "reference track %r has no readable warped audio markers"
                % (str(_attr(track, "name", "")),),
            )
        return index, track, positions, "index"

    candidates = []
    for index, track in enumerate(song.tracks):
        positions = _arrangement_marker_positions(track)
        if len(positions) < 2:
            continue
        name = str(_attr(track, "name", "")).lower()
        score = 2 if any(word in name for word in _REFERENCE_WORDS) else 1
        candidates.append((score, index, track, positions))
    if not candidates:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "no audio track has readable warp markers; add transient markers to the drum "
            "track or name the reference track explicitly",
        )
    candidates.sort(key=lambda row: (-row[0], row[1]))
    _score, index, track, positions = candidates[0]
    return index, track, positions, "auto"


@command("clips.warp_match")
def warp_match(args, song):
    """Match arrangement audio marker positions to a reference track's transients.

    The reference is a drum/percussion track's readable warp markers by default; the nearest
    reference marker within ``max_shift`` becomes the target for each interior marker. Matching is
    done in arrangement beats, so clips at different starts are compared on the same timeline.
    First and hidden last markers anchor each clip and are never moved. Session clips are skipped
    with a reason because their launch position is not an arrangement timestamp.
    """
    check_args(args, allowed=(
        "reference_track", "reference_track_index", "max_shift", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(key in args for key in (
            "reference_track", "reference_track_index", "max_shift",
        )):
            raise ScriptError(
                "BAD_ARGS", "restore cannot be combined with a reference or max_shift"
            )
        return _restore_warp(args, song, dry_run)

    max_shift = _warp_float(args.get("max_shift"), "max_shift", 0.25, 0.0, 4.0)
    reference_index, reference_track, reference_positions, source = _pick_reference(song, args)
    changes, skipped, undo = [], [], []
    clips_moved, moved = 0, 0
    for track_index, track in enumerate(song.tracks):
        if track_index == reference_index:
            continue
        try:
            refs = _clip_refs(track)
        except Exception as exc:  # noqa: BLE001 - a return/group has no clip list
            skipped.append({"track": str(_attr(track, "name", "")),
                            "reason": "no addressable clip list: %s" % exc})
            continue
        session_skipped = 0
        for clip_index, (location, slot, clip, start) in enumerate(refs):
            if location != "arrangement":
                session_skipped += 1
                continue
            if bool(_attr(clip, "is_midi_clip", False)):
                continue
            if not bool(_attr(clip, "warping", False)):
                continue
            name = str(_attr(clip, "name", ""))
            try:
                markers = _warp_marker_rows(clip)
            except ScriptError as exc:
                skipped.append({"track": str(_attr(track, "name", "")), "clip": name,
                                "reason": exc.message})
                continue
            if len(markers) < 3:
                skipped.append({"track": str(_attr(track, "name", "")), "clip": name,
                                "reason": "needs at least three markers (two boundaries and one interior)"})
                continue
            base = 0.0 if start is None else float(start)
            clip_changes = []
            for position in range(1, len(markers) - 1):
                beat = markers[position]["beat_time"]
                absolute = base + beat
                nearest = min(reference_positions, key=lambda point: abs(point - absolute))
                distance = nearest - absolute
                if abs(distance) <= 1e-9:
                    continue
                if abs(distance) > max_shift + 1e-9:
                    skipped.append({"track": str(_attr(track, "name", "")), "clip": name,
                                    "marker": round(beat, 4),
                                    "reason": "no reference marker within max_shift"})
                    continue
                target = beat + distance
                previous = markers[position - 1]["beat_time"]
                following = markers[position + 1]["beat_time"]
                if target <= previous + 1e-6 or target >= following - 1e-6:
                    skipped.append({"track": str(_attr(track, "name", "")), "clip": name,
                                    "marker": round(beat, 4),
                                    "reason": "move would cross an adjacent marker"})
                    continue
                if not dry_run:
                    _move_warp_marker(clip, beat, distance)
                change = {
                    "track": str(_attr(track, "name", "")),
                    "track_index": track_index,
                    "clip": name,
                    "clip_index": clip_index,
                    "location": location,
                    "slot": slot,
                    "start": None if start is None else round(start, 4),
                    "marker": round(beat, 4),
                    "to": round(target, 4),
                    "reference": round(nearest, 4),
                    "distance": round(distance, 6),
                }
                clip_changes.append(change)
                undo.append({
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "location": location,
                    "slot": slot,
                    "start": None if start is None else round(start, 4),
                    "clip": name,
                    "marker_beat": round(target, 6),
                    "distance": distance,
                })
                moved += 1
            if clip_changes:
                clips_moved += 1
                changes.extend(clip_changes)
        if session_skipped:
            skipped.append({
                "track": str(_attr(track, "name", "")),
                "reason": "%d Session clips skipped: launch position is not an arrangement timestamp"
                % session_skipped,
            })
    return {
        "dry_run": dry_run,
        "reference": {
            "track": str(_attr(reference_track, "name", "")),
            "track_index": reference_index,
            "source": source,
            "markers": len(reference_positions),
        },
        "clips": clips_moved,
        "moved": moved,
        "changes": changes,
        "skipped": skipped,
        "undo": undo,
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
    if not looping:
        raise ScriptError(
            "UNSUPPORTED",
            "clip %r is not looped; its loop points are its clip bounds, so changing them "
            "would truncate the clip. Enable loop on the clip first." % (clip_name,),
        )
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

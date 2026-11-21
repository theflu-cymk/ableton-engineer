"""Session clip launch, creation, deletion and arrangement handoff.

Live's Session surface is separate from Arrangement editing: a clip slot owns the clip, firing is a
transport action, and ``Track.duplicate_clip_to_arrangement`` is the only supported bridge from a
Session clip to the timeline. These handlers keep that distinction explicit instead of pretending a
Session clip is an arrangement clip with a different coordinate.

Every applied creation returns an undo token naming the exact object it made. Fire and stop have no
undo token: they change launch state, not Set data. Delete is irreversible on this build and says so
in its result; it therefore requires ``confirm: true`` for an apply.
"""

from __future__ import annotations

import math

from ..dispatch import check_args, command
from ..errors import ScriptError
from .clips import _attr, _beats_per_bar, _track_arg


def _slot(track, raw):
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ScriptError("BAD_ARGS", "slot must be a non-negative integer")
    slots = list(_attr(track, "clip_slots", []) or [])
    if raw >= len(slots):
        raise ScriptError(
            "NOT_FOUND", "track %r has no session slot %s" % (track.name, raw)
        )
    return raw, slots[raw]


def _clip_name(row):
    return str(_attr(row, "name", "") or "")


def _number(value, label):
    if isinstance(value, bool):
        raise ScriptError("BAD_ARGS", "%s must be a number" % (label,))
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ScriptError("BAD_ARGS", "%s must be a number" % (label,))
    if not math.isfinite(value):
        raise ScriptError("BAD_ARGS", "%s must be finite" % (label,))
    return value


def _optional_bool(args, key):
    value = args.get(key)
    if value is not None and not isinstance(value, bool):
        raise ScriptError("BAD_ARGS", "%s must be true or false" % (key,))
    return value


def _planned_audio_name(file_path, name):
    if name is not None:
        if not isinstance(name, str) or not name:
            raise ScriptError("BAD_ARGS", "name must be a non-empty string when given")
        return name
    return str(file_path).replace("\\", "/").rsplit("/", 1)[-1]


def _restore_session(args, song, dry_run):
    entries = args.get("restore")
    if not isinstance(entries, list) or not entries:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    deleted, missing = [], []
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        try:
            index = int(entry["track_index"])
            slot = int(entry["slot"])
        except (KeyError, TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "restore entries need track_index and slot")
        if index < 0 or index >= len(song.tracks):
            missing.append({"track_index": index, "slot": slot, "reason": "no track"})
            continue
        track = song.tracks[index]
        slots = list(_attr(track, "clip_slots", []) or [])
        if slot < 0 or slot >= len(slots):
            missing.append({"track_index": index, "slot": slot, "reason": "no slot"})
            continue
        clip = _attr(slots[slot], "clip", None)
        if clip is None:
            missing.append({"track_index": index, "slot": slot, "reason": "no clip"})
            continue
        wanted = entry.get("name")
        if wanted is not None and _clip_name(clip) != str(wanted):
            missing.append({
                "track_index": index,
                "slot": slot,
                "reason": "slot holds a different clip",
            })
            continue
        name = _clip_name(clip)
        if not dry_run:
            remover = getattr(slots[slot], "delete_clip", None)
            if not callable(remover):
                missing.append({
                    "track_index": index,
                    "slot": slot,
                    "reason": "this Live build cannot delete a session clip",
                })
                continue
            remover()
        deleted.append({
            "track": str(_attr(track, "name", "") or ""),
            "track_index": index,
            "slot": slot,
            "clip": name,
        })
    return {
        "dry_run": dry_run,
        "restored": len(deleted),
        "changes": deleted,
        "missing": missing,
    }


@command("clips.fire")
def fire(args, song):
    check_args(args, allowed=("track", "track_index", "slot"), required=("slot",))
    index, track = _track_arg(song, args)
    slot_index, slot = _slot(track, args.get("slot"))
    clip = _attr(slot, "clip", None)
    if clip is None:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "session slot %s on %r is empty; there is no clip to fire"
            % (slot_index, track.name),
        )
    launcher = getattr(slot, "fire", None)
    if not callable(launcher):
        raise ScriptError("UNSUPPORTED", "this Live build cannot fire a session clip")
    try:
        launcher()
    except Exception as exc:  # noqa: BLE001 - Live's reason is the answer
        raise ScriptError("LIVE_ERROR", "could not fire the clip: %s" % (exc,))
    playing = _attr(clip, "is_playing", None)
    return {
        "track": str(_attr(track, "name", "") or ""),
        "track_index": index,
        "slot": slot_index,
        "clip": _clip_name(clip),
        "fired": True,
        "is_playing": bool(playing) if playing is not None else None,
    }


@command("clips.stop")
def stop(args, song):
    check_args(args, allowed=("track", "track_index", "slot"), required=("slot",))
    index, track = _track_arg(song, args)
    slot_index, slot = _slot(track, args.get("slot"))
    clip = _attr(slot, "clip", None)
    stopper = getattr(slot, "stop", None)
    if not callable(stopper):
        raise ScriptError("UNSUPPORTED", "this Live build cannot stop a session clip")
    try:
        stopper()
    except Exception as exc:  # noqa: BLE001 - Live's reason is the answer
        raise ScriptError("LIVE_ERROR", "could not stop the clip: %s" % (exc,))
    playing = _attr(clip, "is_playing", None) if clip is not None else False
    return {
        "track": str(_attr(track, "name", "") or ""),
        "track_index": index,
        "slot": slot_index,
        "clip": _clip_name(clip) if clip is not None else None,
        "stopped": True,
        "is_playing": bool(playing) if playing is not None else False,
    }


def _arrangement_clip(track, name, start=None):
    if not isinstance(name, str) or not name:
        raise ScriptError("BAD_ARGS", "clip must be a non-empty string for an arrangement clip")
    matches = [
        clip for clip in list(_attr(track, "arrangement_clips", []) or [])
        if _clip_name(clip) == name
    ]
    if start is not None:
        start = _number(start, "start")
        matches = [
            clip for clip in matches
            if abs(float(_attr(clip, "start_time", 0.0) or 0.0) - start) <= 0.001
        ]
    if not matches:
        raise ScriptError(
            "NOT_FOUND", "no arrangement clip named %r on %r" % (name, track.name)
        )
    if len(matches) > 1:
        raise ScriptError(
            "AMBIGUOUS_REF",
            "multiple arrangement clips are named %r on %r; use start"
            % (name, track.name),
        )
    return matches[0]


@command("clips.delete")
def delete(args, song):
    check_args(args, allowed=(
        "track", "track_index", "location", "slot", "clip", "start", "confirm", "dry_run",
    ))
    dry_run = bool(args.get("dry_run", True))
    location = args.get("location")
    if location not in ("session", "arrangement"):
        raise ScriptError("BAD_ARGS", "location must be 'session' or 'arrangement'")
    index, track = _track_arg(song, args)

    if location == "session":
        if args.get("start") is not None:
            raise ScriptError("BAD_ARGS", "start only applies to arrangement clips")
        if args.get("slot") is None:
            raise ScriptError("BAD_ARGS", "slot is required for a session clip")
        slot_index, slot = _slot(track, args.get("slot"))
        clip = _attr(slot, "clip", None)
        if clip is None:
            return {
                "dry_run": dry_run,
                "deleted": [],
                "count": 0,
                "reversible": False,
                "requires_confirm": True,
                "undo": [],
            }
        name = _clip_name(clip)
        wanted = args.get("clip")
        if wanted is not None and str(wanted) != name:
            raise ScriptError(
                "PRECONDITION_FAILED",
                "session slot %s on %r holds %r, not %r"
                % (slot_index, track.name, name, wanted),
            )
        change = {
            "track": str(_attr(track, "name", "") or ""),
            "track_index": index,
            "location": "session",
            "slot": slot_index,
            "clip": name,
        }
        row = clip
    else:
        if args.get("slot") is not None:
            raise ScriptError("BAD_ARGS", "slot only applies to session clips")
        row = _arrangement_clip(track, args.get("clip"), args.get("start"))
        name = _clip_name(row)
        change = {
            "track": str(_attr(track, "name", "") or ""),
            "track_index": index,
            "location": "arrangement",
            "start": round(float(_attr(row, "start_time", 0.0) or 0.0), 4),
            "clip": name,
        }

    if not dry_run and args.get("confirm") is not True:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "%r was not deleted: this Live build has no exact undo for a clip delete, "
            "so an apply needs confirm: true" % (name,),
        )
    if not dry_run:
        if location == "session":
            remover = getattr(slot, "delete_clip", None)
            if not callable(remover):
                raise ScriptError(
                    "UNSUPPORTED", "this Live build cannot delete a session clip"
                )
            remover()
        else:
            remover = getattr(track, "delete_clip", None)
            if not callable(remover):
                raise ScriptError(
                    "UNSUPPORTED", "this Live build cannot delete an arrangement clip"
                )
            remover(row)

    return {
        "dry_run": dry_run,
        "deleted": [change],
        "count": 1,
        "reversible": False,
        "requires_confirm": True,
        "undo": [],
    }


def _restore_duplicate(args, song, dry_run):
    entries = args.get("restore")
    if not isinstance(entries, list) or not entries:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    deleted, missing = [], []
    for entry in reversed(entries):
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
        wanted = entry.get("name")
        found = None
        for clip in list(_attr(track, "arrangement_clips", []) or []):
            if abs(float(_attr(clip, "start_time", 0.0) or 0.0) - start) > 0.001:
                continue
            if wanted is not None and _clip_name(clip) != str(wanted):
                continue
            found = clip
            break
        if found is None:
            missing.append({"track_index": index, "start": start, "reason": "no clip"})
            continue
        name = _clip_name(found)
        if not dry_run:
            remover = getattr(track, "delete_clip", None)
            if not callable(remover):
                missing.append({
                    "track_index": index,
                    "start": start,
                    "reason": "this Live build cannot delete an arrangement clip",
                })
                continue
            remover(found)
        deleted.append({
            "track": str(_attr(track, "name", "") or ""),
            "track_index": index,
            "start": round(start, 4),
            "clip": name,
        })
    return {
        "dry_run": dry_run,
        "restored": len(deleted),
        "changes": deleted,
        "missing": missing,
    }


@command("clips.duplicate_to_arrangement")
def duplicate_to_arrangement(args, song):
    check_args(args, allowed=(
        "track", "track_index", "slot", "to_bar", "name", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(key in args for key in ("track", "track_index", "slot", "to_bar", "name")):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a duplicate")
        return _restore_duplicate(args, song, dry_run)

    if args.get("slot") is None:
        raise ScriptError("BAD_ARGS", "slot is required")
    index, track = _track_arg(song, args)
    slot_index, slot = _slot(track, args.get("slot"))
    clip = _attr(slot, "clip", None)
    if clip is None:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "session slot %s on %r is empty; there is no clip to duplicate"
            % (slot_index, track.name),
        )
    to_bar = _number(args.get("to_bar"), "to_bar")
    if to_bar < 1:
        raise ScriptError("BAD_ARGS", "to_bar must be >= 1")
    destination = (to_bar - 1.0) * _beats_per_bar(song)
    for other in list(_attr(track, "arrangement_clips", []) or []):
        if abs(float(_attr(other, "start_time", 0.0) or 0.0) - destination) <= 1e-6:
            raise ScriptError(
                "PRECONDITION_FAILED",
                "an arrangement clip already starts at bar %s; move it first" % (to_bar,),
            )

    if args.get("name") is None:
        planned_name = _clip_name(clip)
    else:
        planned_name = args.get("name")
        if not isinstance(planned_name, str) or not planned_name:
            raise ScriptError("BAD_ARGS", "name must be a non-empty string when given")
    change = {
        "track": str(_attr(track, "name", "") or ""),
        "track_index": index,
        "clip": planned_name,
        "from_location": "session",
        "from_slot": slot_index,
        "to_location": "arrangement",
        "to_bar": to_bar,
        "to_start": round(destination, 4),
    }
    if dry_run:
        return {"dry_run": True, "changes": [change], "undo": []}

    duplicate = getattr(track, "duplicate_clip_to_arrangement", None)
    if not callable(duplicate):
        raise ScriptError(
            "UNSUPPORTED", "this Live build cannot move a session clip into the arrangement"
        )
    try:
        created = duplicate(clip, destination)
    except Exception as exc:  # noqa: BLE001 - Live's reason is the answer
        raise ScriptError("LIVE_ERROR", "could not duplicate the clip: %s" % (exc,))
    if created is None:
        candidates = [
            row for row in list(_attr(track, "arrangement_clips", []) or [])
            if abs(float(_attr(row, "start_time", 0.0) or 0.0) - destination) <= 0.001
        ]
        created = candidates[-1] if candidates else None
    if created is None:
        raise ScriptError("LIVE_ERROR", "Live did not report the duplicated arrangement clip")
    try:
        created.name = planned_name
    except Exception as exc:  # noqa: BLE001 - do not leave a half-named clip behind
        try:
            remover = getattr(track, "delete_clip", None)
            if callable(remover):
                remover(created)
        except Exception:
            pass
        raise ScriptError("LIVE_ERROR", "clip created but could not be named: %s" % (exc,))

    return {
        "dry_run": False,
        "changes": [change],
        "undo": [{
            "location": "arrangement",
            "track_index": index,
            "start": destination,
            "name": planned_name,
        }],
    }


@command("clips.create_session_midi")
def create_session_midi(args, song):
    check_args(args, allowed=(
        "track", "track_index", "slot", "length_beats", "name", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(key in args for key in ("track", "track_index", "slot", "length_beats", "name")):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a creation")
        return _restore_session(args, song, dry_run)

    if args.get("slot") is None:
        raise ScriptError("BAD_ARGS", "slot is required")
    index, track = _track_arg(song, args)
    if not (bool(_attr(track, "is_midi", False))
            or bool(_attr(track, "has_midi_input", False))):
        raise ScriptError("UNSUPPORTED", "create_session_midi needs a MIDI track")
    slot_index, slot = _slot(track, args.get("slot"))
    if _attr(slot, "clip", None) is not None:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "session slot %s on %r is occupied; clear it first" % (slot_index, track.name),
        )
    length = _number(args.get("length_beats", 4.0), "length_beats")
    if length <= 0:
        raise ScriptError("BAD_ARGS", "length_beats must be > 0")
    planned_name = args.get("name")
    if planned_name is None:
        planned_name = "MIDI"
    elif not isinstance(planned_name, str) or not planned_name:
        raise ScriptError("BAD_ARGS", "name must be a non-empty string when given")

    preview = {
        "dry_run": dry_run,
        "track": str(_attr(track, "name", "") or ""),
        "track_index": index,
        "slot": slot_index,
        "clip": planned_name,
        "length_beats": length,
    }
    if dry_run:
        return preview

    creator = getattr(slot, "create_clip", None)
    if not callable(creator):
        raise ScriptError("UNSUPPORTED", "this Live build cannot create a session MIDI clip")
    try:
        clip = creator(length)
    except Exception as exc:  # noqa: BLE001 - Live's reason is the answer
        raise ScriptError("LIVE_ERROR", "could not create session MIDI clip: %s" % (exc,))
    if clip is None:
        clip = _attr(slot, "clip", None)
    if clip is None:
        raise ScriptError("LIVE_ERROR", "Live did not report the created session clip")
    try:
        clip.name = planned_name
    except Exception as exc:  # noqa: BLE001 - creation must not leave a half-configured clip
        try:
            slot.delete_clip()
        except Exception:
            pass
        raise ScriptError("LIVE_ERROR", "clip created but could not be named: %s" % (exc,))

    return dict(
        preview,
        dry_run=False,
        undo=[{"track_index": index, "slot": slot_index, "name": planned_name}],
    )


@command("clips.create_session_audio")
def create_session_audio(args, song):
    check_args(args, allowed=(
        "track", "track_index", "slot", "file_path", "name", "warping", "looping",
        "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(key in args for key in (
            "track", "track_index", "slot", "file_path", "name", "warping", "looping",
        )):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a creation")
        return _restore_session(args, song, dry_run)

    if args.get("slot") is None:
        raise ScriptError("BAD_ARGS", "slot is required")
    index, track = _track_arg(song, args)
    if bool(_attr(track, "is_midi", False)):
        raise ScriptError("UNSUPPORTED", "create_session_audio needs an audio track")
    slot_index, slot = _slot(track, args.get("slot"))
    if _attr(slot, "clip", None) is not None:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "session slot %s on %r is occupied; clear it first" % (slot_index, track.name),
        )
    file_path = args.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        raise ScriptError("BAD_ARGS", "file_path must be an absolute path")
    planned_name = _planned_audio_name(file_path, args.get("name"))
    warping = _optional_bool(args, "warping")
    looping = _optional_bool(args, "looping")

    preview = {
        "dry_run": dry_run,
        "track": str(_attr(track, "name", "") or ""),
        "track_index": index,
        "slot": slot_index,
        "clip": planned_name,
        "file_path": file_path,
    }
    if dry_run:
        return preview

    creator = getattr(slot, "create_audio_clip", None)
    if not callable(creator):
        raise ScriptError("UNSUPPORTED", "this Live build cannot create a session audio clip")
    try:
        clip = creator(file_path)
    except Exception as exc:  # noqa: BLE001 - Live's reason is the answer
        raise ScriptError("LIVE_ERROR", "could not create session audio clip: %s" % (exc,))
    if clip is None:
        clip = _attr(slot, "clip", None)
    if clip is None:
        raise ScriptError("LIVE_ERROR", "Live did not report the created session clip")
    try:
        clip.name = planned_name
        if warping is not None:
            clip.warping = warping
        if looping is not None:
            clip.looping = looping
    except Exception as exc:  # noqa: BLE001 - creation must not leave a half-configured clip
        try:
            slot.delete_clip()
        except Exception:
            pass
        raise ScriptError("LIVE_ERROR", "clip created but could not be configured: %s" % (exc,))

    return dict(
        preview,
        dry_run=False,
        undo=[{"track_index": index, "slot": slot_index, "name": planned_name}],
    )

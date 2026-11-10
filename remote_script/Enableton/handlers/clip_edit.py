"""Clip-level copy, transpose and clear.

Arrangement range duplication already lives in ``clips``; this module covers the moves that act on
one clip: copying a Session slot to another slot or an Arrangement clip to a later beat, shifting a
MIDI clip's pitches, and emptying a MIDI clip.

Each handler owns its undo token. A copy token names the object it created, so a rollback deletes
exactly that and nothing else. A note rewrite token holds the clip's whole vector, because
``set_notes`` appends rather than replaces and an inverse edit would not be exact.
"""

from __future__ import annotations

from ..dispatch import check_args, command
from ..errors import ScriptError
from .clips import _attr, _beats_per_bar, _resolve_clip


@command("clips.copy")
def copy_clip(args, song):
    check_args(args, allowed=(
        "track", "clip", "location", "slot", "to_track", "to_slot", "to_bar", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(key in args for key in (
            "track", "clip", "location", "slot", "to_track", "to_slot", "to_bar",
        )):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a copy")
        return _restore_copy(args, song, dry_run)

    index, track, row = _resolve_clip(
        song, args.get("track"), args.get("clip"), args.get("location"), args.get("slot")
    )
    location, slot, clip, start = row

    target_name = args.get("to_track", track.name)
    if not isinstance(target_name, str) or not target_name:
        raise ScriptError("BAD_ARGS", "to_track must be a non-empty string")
    if target_name == track.name:
        target_index, target = index, track
    else:
        matches = [
            (position, candidate)
            for position, candidate in enumerate(song.tracks)
            if str(_attr(candidate, "name", "")) == target_name
        ]
        if not matches:
            raise ScriptError("NOT_FOUND", "no track named %r" % (target_name,))
        if len(matches) > 1:
            raise ScriptError(
                "AMBIGUOUS_REF", "%d tracks are named %r" % (len(matches), target_name)
            )
        target_index, target = matches[0]

    to_slot = args.get("to_slot")
    to_bar = args.get("to_bar")
    if (to_slot is None) == (to_bar is None):
        raise ScriptError("BAD_ARGS", "give exactly one of to_slot or to_bar")

    clip_name = str(_attr(clip, "name", "") or "")

    if to_slot is not None:
        if location != "session":
            raise ScriptError(
                "UNSUPPORTED",
                "Live cannot copy an Arrangement clip into a Session slot; use to_bar",
            )
        if isinstance(to_slot, bool) or not isinstance(to_slot, int) or to_slot < 0:
            raise ScriptError("BAD_ARGS", "to_slot must be a non-negative integer")
        slots = list(_attr(target, "clip_slots", []) or [])
        if to_slot >= len(slots):
            raise ScriptError(
                "NOT_FOUND", "track %r has no session slot %s" % (target.name, to_slot)
            )
        destination = slots[to_slot]
        if _attr(destination, "clip", None) is not None:
            raise ScriptError(
                "PRECONDITION_FAILED",
                "session slot %s on %r is occupied; clear it first" % (to_slot, target.name),
            )
        change = {
            "track": target.name,
            "track_index": target_index,
            "clip": clip_name,
            "from_location": "session",
            "from_slot": slot,
            "to_location": "session",
            "to_slot": to_slot,
        }
        if dry_run:
            return {"dry_run": True, "changes": [change], "undo": []}

        source_slots = list(_attr(track, "clip_slots", []) or [])
        if slot is None or slot >= len(source_slots):
            raise ScriptError("NOT_FOUND", "the source session slot is no longer there")
        duplicate = getattr(source_slots[slot], "duplicate_clip_to", None)
        if not callable(duplicate):
            raise ScriptError(
                "UNSUPPORTED", "this Live build cannot duplicate a session clip"
            )
        try:
            duplicate(destination)
        except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
            raise ScriptError("LIVE_ERROR", "could not copy the clip: %s" % (exc,))
        created = _attr(destination, "clip", None)
        if created is None:
            raise ScriptError(
                "LIVE_ERROR", "Live did not create a clip in slot %s" % (to_slot,)
            )
        created_name = str(_attr(created, "name", "") or "")
        change["created"] = created_name
        return {
            "dry_run": False,
            "changes": [change],
            "undo": [{
                "location": "session",
                "track_index": target_index,
                "slot": to_slot,
                "name": created_name,
            }],
        }

    if location != "arrangement":
        raise ScriptError(
            "UNSUPPORTED",
            "Live cannot copy a Session clip onto the Arrangement; use to_slot",
        )
    if isinstance(to_bar, bool) or not isinstance(to_bar, (int, float)) or float(to_bar) < 1:
        raise ScriptError("BAD_ARGS", "to_bar must be a number >= 1")
    destination_beat = (float(to_bar) - 1.0) * _beats_per_bar(song)

    for other in list(_attr(target, "arrangement_clips", []) or []):
        other_start = float(_attr(other, "start_time", 0.0) or 0.0)
        if abs(other_start - destination_beat) <= 1e-6:
            raise ScriptError(
                "PRECONDITION_FAILED",
                "an arrangement clip already starts at bar %s; move it first" % (to_bar,),
            )

    change = {
        "track": target.name,
        "track_index": target_index,
        "clip": clip_name,
        "from_location": "arrangement",
        "from_start": round(float(start or 0.0), 4),
        "to_location": "arrangement",
        "to_start": round(destination_beat, 4),
        "to_bar": float(to_bar),
    }
    if dry_run:
        return {"dry_run": True, "changes": [change], "undo": []}

    duplicate = getattr(target, "duplicate_clip_to_arrangement", None)
    if not callable(duplicate):
        raise ScriptError(
            "UNSUPPORTED", "this Live build cannot duplicate an arrangement clip"
        )
    try:
        created = duplicate(clip, destination_beat)
    except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
        raise ScriptError("LIVE_ERROR", "could not copy the clip: %s" % (exc,))
    created_start = float(_attr(created, "start_time", destination_beat) or destination_beat)
    created_name = str(_attr(created, "name", "") or clip_name)
    return {
        "dry_run": False,
        "changes": [change],
        "undo": [{
            "location": "arrangement",
            "track_index": target_index,
            "start": created_start,
            "name": created_name,
        }],
    }


def _restore_copy(args, song, dry_run):
    entries = args.get("restore")
    if not isinstance(entries, list) or not entries:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    changes, missing = [], []
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        location = entry.get("location")
        if location not in ("arrangement", "session"):
            raise ScriptError("BAD_ARGS", "restore location must be arrangement or session")
        try:
            index = int(entry["track_index"])
        except (KeyError, TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "restore entries need track_index")
        if index < 0 or index >= len(song.tracks):
            raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
        track = song.tracks[index]

        slot = None
        found = None
        if location == "session":
            try:
                slot = int(entry["slot"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError("BAD_ARGS", "session restore entries need a slot")
            slots = list(_attr(track, "clip_slots", []) or [])
            if 0 <= slot < len(slots):
                found = _attr(slots[slot], "clip", None)
        else:
            try:
                start = float(entry["start"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError("BAD_ARGS", "arrangement restore entries need a start")
            wanted = entry.get("name")
            for candidate in list(_attr(track, "arrangement_clips", []) or []):
                candidate_start = float(_attr(candidate, "start_time", 0.0) or 0.0)
                if abs(candidate_start - start) > 0.001:
                    continue
                if wanted is not None and str(_attr(candidate, "name", "")) != str(wanted):
                    continue
                found = candidate
                break

        if found is None:
            missing.append({
                "location": location,
                "track_index": index,
                "slot": slot,
                "start": entry.get("start") if location == "arrangement" else None,
            })
            continue

        name = str(_attr(found, "name", "") or "")
        if not dry_run:
            if location == "session":
                slots[slot].delete_clip()
            else:
                delete = getattr(track, "delete_clip", None)
                if not callable(delete):
                    raise ScriptError(
                        "UNSUPPORTED", "this Live build cannot delete an arrangement clip"
                    )
                delete(found)
        changes.append({
            "location": location,
            "track": str(_attr(track, "name", "") or ""),
            "track_index": index,
            "slot": slot,
            "start": entry.get("start") if location == "arrangement" else None,
            "name": name,
        })

    return {
        "dry_run": dry_run,
        "restored": len(changes),
        "changes": changes,
        "missing": missing,
    }


@command("clips.transpose")
def transpose(args, song):
    check_args(args, allowed=(
        "track", "clip", "location", "slot", "semitones", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(key in args for key in ("track", "clip", "location", "slot", "semitones")):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a transpose")
        # notes owns the whole-vector undo token; importing it lazily keeps ``clips`` -> ``notes``
        # the only import direction between the two modules.
        from .notes import _restore_notes

        return _restore_notes(args, song, dry_run)

    semitones = args.get("semitones")
    if isinstance(semitones, bool) or not isinstance(semitones, int):
        raise ScriptError("BAD_ARGS", "semitones must be an integer")
    if semitones == 0:
        raise ScriptError("BAD_ARGS", "semitones must not be zero")
    if semitones < -48 or semitones > 48:
        raise ScriptError("BAD_ARGS", "semitones must be from -48 to 48")

    from .notes import _context, _result

    context = _context(args, song)
    notes, moved = [], 0
    for pitch, start, duration, velocity, mute in context["original"]:
        new_pitch = pitch + semitones
        if new_pitch < 0 or new_pitch > 127:
            raise ScriptError(
                "BAD_ARGS", "transpose would move pitch %d outside 0-127" % (pitch,)
            )
        if new_pitch != pitch:
            moved += 1
        notes.append([new_pitch, start, duration, velocity, mute])
    return _result(context, notes, dry_run, semitones=semitones, moved=moved)


@command("clips.clear")
def clear(args, song):
    check_args(args, allowed=("track", "clip", "location", "slot", "dry_run", "restore"))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(key in args for key in ("track", "clip", "location", "slot")):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a clip selection")
        from .notes import _restore_notes

        return _restore_notes(args, song, dry_run)

    _index, _track, row = _resolve_clip(
        song, args.get("track"), args.get("clip"), args.get("location"), args.get("slot")
    )
    clip = row[2]
    if not bool(_attr(clip, "is_midi_clip", False)):
        raise ScriptError(
            "UNSUPPORTED",
            "clip %r is audio; clearing it would delete audio this tool cannot restore. "
            "Delete it in Live, or copy it with clips_copy first."
            % (str(_attr(clip, "name", "")),),
        )

    from .notes import _context, _result

    context = _context(args, song)
    return _result(context, [], dry_run, cleared=len(context["original"]))

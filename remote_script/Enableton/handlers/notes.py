"""Read one MIDI clip's notes.

The note reader lives in ``structure`` because the snapshot's overlap report already depends on it;
this command exposes the same records for one clip instead of a Set-wide count. ``_read_notes``
distinguishes "no notes" from "could not read notes", and that distinction is preserved here: a
non-MIDI clip or a failed read returns ``notes_available: false`` with the reason, never an empty
list that looks like a clean clip.
"""

from __future__ import annotations

import math
import random

from ..dispatch import check_args, command
from ..errors import ScriptError
from .clips import _attr, _clip_refs, _resolve_clip
from .structure import _note_record, _read_notes

MAX_NOTES_LIMIT = 1000


@command("notes.read")
def read(args, song):
    check_args(args, allowed=("track", "clip", "location", "slot", "start", "offset", "limit"))

    track_name = args.get("track")
    clip_name = args.get("clip")
    if not isinstance(track_name, str) or not track_name:
        raise ScriptError("BAD_ARGS", "track must be a non-empty string")
    if not isinstance(clip_name, str) or not clip_name:
        raise ScriptError("BAD_ARGS", "clip must be a non-empty string")

    offset = args.get("offset", 0)
    limit = args.get("limit", 200)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ScriptError("BAD_ARGS", "offset must be a non-negative integer")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit < 1
        or limit > MAX_NOTES_LIMIT
    ):
        raise ScriptError("BAD_ARGS", "limit must be an integer from 1 to %d" % MAX_NOTES_LIMIT)

    index, track, row = _resolve_clip(
        song, track_name, clip_name, args.get("location"), args.get("slot"), args.get("start")
    )
    location, slot, clip, start = row

    result = {
        "track": str(_attr(track, "name", "")),
        "track_index": index,
        "clip": str(_attr(clip, "name", "")),
        "location": location,
        "slot": slot,
        "start": None if start is None else round(start, 4),
        "notes_available": True,
        "source": None,
        "total": 0,
        "offset": offset,
        "limit": limit,
        "notes": [],
        "next_offset": None,
    }

    if not bool(_attr(clip, "is_midi_clip", False)):
        result["notes_available"] = False
        result["reason"] = "clip is not a MIDI clip"
        return result

    try:
        raw, source = _read_notes(clip)
    except Exception as exc:  # noqa: BLE001 - the reason is the point
        result["notes_available"] = False
        result["reason"] = "note read failed: %s" % (exc,)
        return result

    notes = [_note_record(note) for note in (raw or [])]
    # Live's vectors are not promised in time order; sorting makes paging stable and readable.
    notes.sort(key=lambda note: (
        note["start"], note["pitch"], note["duration"], note["velocity"],
    ))

    page = notes[offset:offset + limit]
    end = offset + len(page)
    result.update({
        "source": source,
        "total": len(notes),
        "notes": page,
        "next_offset": end if end < len(notes) else None,
    })
    return result


# --- writes --------------------------------------------------------------
#
# Every write shares one undo shape: the clip's raw note vector before the edit, in
# ``[pitch, start, duration, velocity, mute]`` form. Live's ``Clip.set_notes`` **adds** notes to
# the clip rather than replacing the vector (confirmed against Live 12.2.5: writing the same
# vector twice doubled the count), so every write clears the clip first. The undo token is still
# a whole-vector restore, exact for these five fields, rather than an inverse of the first edit.

MAX_REPLACE_NOTES = 10000

SCALES = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "major_pentatonic": (0, 2, 4, 7, 9),
    "minor_pentatonic": (0, 3, 5, 7, 10),
    "blues": (0, 3, 5, 6, 7, 10),
}

ROOTS = {
    "C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4,
    "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9,
    "A#": 10, "BB": 10, "B": 11,
}


def _int_arg(args, key, default, low, high):
    value = args.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ScriptError("BAD_ARGS", "%s must be an integer" % key)
    if value < low or value > high:
        raise ScriptError("BAD_ARGS", "%s must be from %d to %d" % (key, low, high))
    return value


def _float_arg(args, key, default, low, high):
    raw = args.get(key, default)
    if isinstance(raw, bool):
        raise ScriptError("BAD_ARGS", "%s must be a number" % key)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ScriptError("BAD_ARGS", "%s must be a number" % key)
    if value < low or value > high:
        raise ScriptError("BAD_ARGS", "%s must be from %s to %s" % (key, low, high))
    return value


def _raw_notes(clip):
    """The exact vector, not the rounded report records, so a restore can be byte-faithful."""
    raw, source = _read_notes(clip)
    notes = []
    for note in raw or []:
        start = float(_attr(note, "start_time", 0.0) or 0.0)
        duration = _attr(note, "duration", None)
        if duration is None:
            end = _attr(note, "end_time", None)
            duration = 0.0 if end is None else float(end) - start
        notes.append([
            int(_attr(note, "pitch", 0) or 0),
            start,
            max(0.0, float(duration or 0.0)),
            int(_attr(note, "velocity", 0) or 0),
            bool(_attr(note, "mute", False)),
        ])
    return notes, source


def _clear_notes(clip):
    """Remove every note, because ``set_notes`` appends instead of replacing."""
    existing, _ = _raw_notes(clip)
    end = float(_attr(clip, "length", 0.0) or 0.0)
    if existing:
        end = max(end, max(note[1] + note[2] for note in existing))

    ranged = getattr(clip, "remove_notes_extended", None)
    if callable(ranged):
        # The window is derived from the actual notes, so it covers material past the loop end.
        ranged(0, 128, 0.0, end + 0.001)
        return

    extended = getattr(clip, "get_all_notes_extended", None)
    by_id = getattr(clip, "remove_notes_by_id", None)
    if callable(extended) and callable(by_id):
        ids = [int(_attr(note, "note_id", 0)) for note in extended()]
        if ids:
            by_id(ids)
        return

    raise ScriptError("UNSUPPORTED", "this Live build cannot clear clip notes")


def _write_notes(clip, notes):
    setter = getattr(clip, "set_notes", None)
    if not callable(setter):
        raise ScriptError("UNSUPPORTED", "this Live build cannot write clip notes")
    _clear_notes(clip)
    if notes:
        setter(tuple(
            (int(pitch), float(start), float(duration), int(velocity), bool(mute))
            for pitch, start, duration, velocity, mute in notes
        ))


def _validated_notes(value):
    if not isinstance(value, (list, tuple)):
        raise ScriptError("BAD_ARGS", "notes must be a list")
    if len(value) > MAX_REPLACE_NOTES:
        raise ScriptError("BAD_ARGS", "notes may hold at most %d entries" % MAX_REPLACE_NOTES)
    out = []
    for position, entry in enumerate(value):
        if isinstance(entry, dict):
            if not all(key in entry for key in ("pitch", "start", "duration")):
                raise ScriptError("BAD_ARGS", "note %d needs pitch, start and duration" % position)
            pitch = entry.get("pitch")
            start = entry.get("start")
            duration = entry.get("duration")
            velocity = entry.get("velocity", 100)
            mute = entry.get("mute", False)
        elif isinstance(entry, (list, tuple)) and len(entry) == 5:
            pitch, start, duration, velocity, mute = entry
        else:
            raise ScriptError(
                "BAD_ARGS", "note %d must be an object or a 5-item list" % position
            )
        if not isinstance(pitch, int) or isinstance(pitch, bool) or not 0 <= pitch <= 127:
            raise ScriptError(
                "BAD_ARGS", "note %d pitch must be an integer from 0 to 127" % position
            )
        try:
            start = float(start)
            duration = float(duration)
        except (TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "note %d start and duration must be numbers" % position)
        if start < 0 or duration < 0:
            raise ScriptError("BAD_ARGS", "note %d start and duration must be >= 0" % position)
        if not isinstance(velocity, int) or isinstance(velocity, bool) or not 0 <= velocity <= 127:
            raise ScriptError(
                "BAD_ARGS", "note %d velocity must be an integer from 0 to 127" % position
            )
        out.append([pitch, start, duration, velocity, bool(mute)])
    return out


def _context(args, song):
    track_name = args.get("track")
    clip_name = args.get("clip")
    if not isinstance(track_name, str) or not track_name:
        raise ScriptError("BAD_ARGS", "track must be a non-empty string")
    if not isinstance(clip_name, str) or not clip_name:
        raise ScriptError("BAD_ARGS", "clip must be a non-empty string")
    index, track, row = _resolve_clip(
        song, track_name, clip_name, args.get("location"), args.get("slot"), args.get("start")
    )
    location, slot, clip, start = row
    if not bool(_attr(clip, "is_midi_clip", False)):
        raise ScriptError("UNSUPPORTED", "clip is not a MIDI clip")
    if not callable(getattr(clip, "set_notes", None)):
        raise ScriptError("UNSUPPORTED", "this Live build cannot write clip notes")
    can_clear = (
        callable(getattr(clip, "get_all_notes_extended", None))
        and callable(getattr(clip, "remove_notes_by_id", None))
    ) or callable(getattr(clip, "remove_notes_extended", None))
    if not can_clear:
        raise ScriptError("UNSUPPORTED", "this Live build cannot clear clip notes")
    original, source = _raw_notes(clip)
    return {
        "index": index,
        "track": track,
        "clip": clip,
        "track_name": str(_attr(track, "name", "")),
        "clip_name": str(_attr(clip, "name", "")),
        "location": location,
        "slot": slot,
        "start": start,
        "original": original,
        "source": source,
    }


def _result(context, notes, dry_run, **detail):
    if not dry_run:
        _write_notes(context["clip"], notes)
    token = {
        "track_index": context["index"],
        "location": context["location"],
        "slot": context["slot"],
        "start": context["start"],
        "clip": context["clip_name"],
        "notes": context["original"],
    }
    payload = {
        "dry_run": dry_run,
        "track": context["track_name"],
        "track_index": context["index"],
        "clip": context["clip_name"],
        "location": context["location"],
        "slot": context["slot"],
        "start": None if context["start"] is None else round(context["start"], 4),
        "source": context["source"],
        "notes_before": len(context["original"]),
        "notes_after": len(notes),
        "undo": [token],
    }
    payload.update(detail)
    return payload


def _restore_target(track, location, slot, start, name):
    """Find the clip a token was made for. Start alone is not unique: two clips can share it."""
    for row in _clip_refs(track):
        if row[0] != location:
            continue
        if location == "session":
            if row[1] != slot:
                continue
        elif start is None or abs(float(row[3]) - float(start)) > 0.001:
            continue
        if name is not None and str(_attr(row[2], "name", "")) != str(name):
            continue
        return row[2]
    return None


def _restore_notes(args, song, dry_run):
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
        except (KeyError, TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "restore entries need track_index and location")
        if index < 0 or index >= len(song.tracks):
            raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
        if location not in ("arrangement", "session"):
            raise ScriptError("BAD_ARGS", "restore location must be arrangement or session")
        notes = _validated_notes(entry.get("notes"))
        track = song.tracks[index]
        clip = _restore_target(
            track, location, entry.get("slot"), entry.get("start"), entry.get("clip")
        )
        if clip is None:
            missing.append({
                "track_index": index,
                "location": location,
                "slot": entry.get("slot"),
                "start": entry.get("start"),
            })
            continue
        before, _ = _raw_notes(clip)
        if not dry_run:
            _write_notes(clip, notes)
        changes.append({
            "track": str(_attr(track, "name", "")),
            "track_index": index,
            "clip": str(_attr(clip, "name", "")),
            "location": location,
            "slot": entry.get("slot") if location == "session" else None,
            "start": entry.get("start") if location == "arrangement" else None,
            "from": len(before),
            "to": len(notes),
        })
    return {"dry_run": dry_run, "restored": len(changes), "changes": changes, "missing": missing}


def _restore_requested(args, song, dry_run, forbidden):
    if args.get("restore") is None:
        return None
    present = [key for key in forbidden if key in args]
    if present:
        raise ScriptError("BAD_ARGS", "restore cannot be combined with %s" % ", ".join(present))
    return _restore_notes(args, song, dry_run)


def _root_pitch(value):
    if isinstance(value, int) and not isinstance(value, bool):
        if 0 <= value <= 11:
            return value
        raise ScriptError("BAD_ARGS", "root must be 0-11 or a note name")
    if isinstance(value, str):
        key = value.strip().upper().replace("♯", "#").replace("♭", "B")
        if key in ROOTS:
            return ROOTS[key]
    raise ScriptError("BAD_ARGS", "root must be 0-11 or a note name such as C, F# or Eb")


def _nearest_in_scale(pitch, allowed):
    if pitch % 12 in allowed:
        return pitch
    for step in range(1, 7):
        # Ties move down, so the choice is deterministic and easy to reason about.
        for candidate in (pitch - step, pitch + step):
            if 0 <= candidate <= 127 and candidate % 12 in allowed:
                return candidate
    return pitch


@command("notes.quantize")
def quantize(args, song):
    check_args(args, allowed=(
        "track", "clip", "location", "slot", "grid", "strength", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restored = _restore_requested(
        args, song, dry_run, ("track", "clip", "location", "slot", "grid", "strength")
    )
    if restored is not None:
        return restored

    grid = _float_arg(args, "grid", 0.25, 0.03125, 16.0)
    strength = _float_arg(args, "strength", 1.0, 0.0, 1.0)
    context = _context(args, song)
    notes, moved, largest = [], 0, 0.0
    for pitch, start, duration, velocity, mute in context["original"]:
        target = math.floor(start / grid + 0.5) * grid
        new_start = max(0.0, start + (target - start) * strength)
        if abs(new_start - start) > 1e-9:
            moved += 1
            largest = max(largest, abs(new_start - start))
        notes.append([pitch, new_start, duration, velocity, mute])
    return _result(
        context, notes, dry_run,
        grid=grid, strength=strength, moved=moved, largest_shift=round(largest, 4),
    )


def _track_target(args, song):
    """Resolve one track by name or index without guessing at duplicate names."""
    has_name = "track" in args
    has_index = "track_index" in args
    if has_name == has_index:
        raise ScriptError("BAD_ARGS", "give exactly one of track or track_index")
    if has_name:
        name = args.get("track")
        if not isinstance(name, str) or not name:
            raise ScriptError("BAD_ARGS", "track must be a non-empty string")
        matches = [
            (index, track) for index, track in enumerate(song.tracks)
            if str(_attr(track, "name", "")) == name
        ]
        if not matches:
            raise ScriptError("NOT_FOUND", "no track named %r" % (name,))
        if len(matches) > 1:
            raise ScriptError(
                "AMBIGUOUS_REF",
                "%d tracks are named %r; use track_index" % (len(matches), name),
            )
        return matches[0]
    raw = args.get("track_index")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ScriptError("BAD_ARGS", "track_index must be a non-negative integer")
    if raw >= len(song.tracks):
        raise ScriptError("NOT_FOUND", "no track at index %s" % (raw,))
    return raw, song.tracks[raw]


def _find_align_clip(track, clip_index, location, slot, start, name):
    """Find the clip a restore token names, using the fields that disambiguate duplicates."""
    refs = _clip_refs(track)
    if clip_index is not None:
        try:
            position = int(clip_index)
        except (TypeError, ValueError):
            position = -1
        if 0 <= position < len(refs):
            where, slot_index, clip, clip_start = refs[position]
            if (
                where == location
                and (location != "session" or (slot is not None and int(slot) == slot_index))
                and (location != "arrangement" or start is None
                     or abs(clip_start - float(start)) <= 0.001)
                and (name is None or str(_attr(clip, "name", "")) == str(name))
            ):
                return clip
    for where, slot_index, clip, clip_start in refs:
        if where != location:
            continue
        if location == "session":
            if slot is None or int(slot) != slot_index:
                continue
        elif start is not None and abs(clip_start - float(start)) > 0.001:
            continue
        if name is not None and str(_attr(clip, "name", "")) != str(name):
            continue
        return clip
    return None


def _restore_align(args, song, dry_run):
    entries = args.get("restore")
    if not isinstance(entries, list) or not entries:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    changes, missing = [], []
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        try:
            index = int(entry["track_index"])
            location = entry["location"]
            notes = _validated_notes(entry.get("notes"))
        except (KeyError, TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "restore entries need track_index, location and notes")
        if location not in ("arrangement", "session"):
            raise ScriptError("BAD_ARGS", "restore location must be arrangement or session")
        if index < 0 or index >= len(song.tracks):
            missing.append({"track_index": index, "reason": "no track at that index"})
            continue
        track = song.tracks[index]
        clip = _find_align_clip(
            track, entry.get("clip_index"), location, entry.get("slot"),
            entry.get("start"), entry.get("clip"),
        )
        if clip is None:
            missing.append({
                "track_index": index,
                "location": location,
                "slot": entry.get("slot"),
                "start": entry.get("start"),
                "clip": entry.get("clip"),
            })
            continue
        if not dry_run:
            _write_notes(clip, notes)
        changes.append({
            "track": str(_attr(track, "name", "")),
            "track_index": index,
            "clip": str(_attr(clip, "name", "")),
            "location": location,
            "slot": entry.get("slot"),
            "notes": len(notes),
        })
    return {"dry_run": dry_run, "restored": len(changes), "changes": changes, "missing": missing}


@command("notes.align_track")
def align_track(args, song):
    """Quantize every MIDI clip on one track, without resolving clip names.

    Duplicate clip names are normal in layered Arrangements and make the single-clip commands
    ambiguous. This command walks the track's own clip list instead, so a one-click alignment
    never has to ask which of two identically named clips was meant.
    """
    check_args(args, allowed=(
        "track", "track_index", "grid", "strength", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(key in args for key in ("track", "track_index", "grid", "strength")):
            raise ScriptError(
                "BAD_ARGS", "restore cannot be combined with track, track_index, grid or strength"
            )
        return _restore_align(args, song, dry_run)

    index, track = _track_target(args, song)
    grid = _float_arg(args, "grid", 0.25, 0.03125, 16.0)
    strength = _float_arg(args, "strength", 1.0, 0.0, 1.0)
    try:
        refs = _clip_refs(track)
    except Exception as exc:  # noqa: BLE001 - group and return tracks have no clip list
        raise ScriptError(
            "UNSUPPORTED", "%r has no addressable clip list: %s" % (track.name, exc)
        )

    changes, undo, total_notes, total_moved = [], [], 0, 0
    for clip_index, (location, slot, clip, start) in enumerate(refs):
        if not bool(_attr(clip, "is_midi_clip", False)):
            continue
        raw, _source = _raw_notes(clip)
        if not raw:
            continue
        notes, moved, largest = [], 0, 0.0
        for pitch, note_start, duration, velocity, mute in raw:
            target = math.floor(note_start / grid + 0.5) * grid
            new_start = max(0.0, note_start + (target - note_start) * strength)
            if abs(new_start - note_start) > 1e-9:
                moved += 1
                largest = max(largest, abs(new_start - note_start))
            notes.append([pitch, new_start, duration, velocity, mute])
        if moved == 0:
            continue
        name = str(_attr(clip, "name", ""))
        changes.append({
            "clip": name,
            "clip_index": clip_index,
            "location": location,
            "slot": slot,
            "start": None if start is None else round(start, 4),
            "notes": len(raw),
            "moved": moved,
            "largest_shift": round(largest, 4),
        })
        undo.append({
            "track_index": index,
            "clip_index": clip_index,
            "location": location,
            "slot": slot,
            "start": None if start is None else round(start, 4),
            "clip": name,
            "notes": raw,
        })
        total_notes += len(raw)
        total_moved += moved
        if not dry_run:
            _write_notes(clip, notes)

    return {
        "dry_run": dry_run,
        "track": str(_attr(track, "name", "")),
        "track_index": index,
        "grid": grid,
        "strength": strength,
        "clips": len(changes),
        "notes": total_notes,
        "moved": total_moved,
        "changes": changes,
        "undo": undo,
    }


@command("notes.transform")
def transform(args, song):
    check_args(args, allowed=(
        "track", "clip", "location", "slot", "transpose", "velocity_scale",
        "velocity_offset", "duration_scale", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restored = _restore_requested(args, song, dry_run, (
        "track", "clip", "location", "slot", "transpose", "velocity_scale",
        "velocity_offset", "duration_scale",
    ))
    if restored is not None:
        return restored

    transpose = _int_arg(args, "transpose", 0, -48, 48)
    velocity_scale = _float_arg(args, "velocity_scale", 1.0, 0.0, 4.0)
    velocity_offset = _int_arg(args, "velocity_offset", 0, -127, 127)
    duration_scale = _float_arg(args, "duration_scale", 1.0, 0.125, 8.0)
    if (transpose == 0 and velocity_scale == 1.0
            and velocity_offset == 0 and duration_scale == 1.0):
        raise ScriptError(
            "BAD_ARGS",
            "give at least one of transpose, velocity_scale, velocity_offset or duration_scale",
        )

    context = _context(args, song)
    notes, changed = [], 0
    for pitch, start, duration, velocity, mute in context["original"]:
        new_pitch = pitch + transpose
        if new_pitch < 0 or new_pitch > 127:
            raise ScriptError(
                "BAD_ARGS", "transpose would move pitch %d outside 0-127" % (pitch,)
            )
        new_velocity = min(127, max(0, int(round(velocity * velocity_scale + velocity_offset))))
        new_duration = max(0.0, duration * duration_scale)
        if (new_pitch, new_velocity, new_duration) != (pitch, velocity, duration):
            changed += 1
        notes.append([new_pitch, start, new_duration, new_velocity, mute])
    return _result(
        context, notes, dry_run,
        transpose=transpose, velocity_scale=velocity_scale,
        velocity_offset=velocity_offset, duration_scale=duration_scale, changed=changed,
    )


@command("notes.humanize")
def humanize(args, song):
    check_args(args, allowed=(
        "track", "clip", "location", "slot", "timing", "velocity", "seed", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restored = _restore_requested(
        args, song, dry_run, ("track", "clip", "location", "slot", "timing", "velocity", "seed")
    )
    if restored is not None:
        return restored

    timing = _float_arg(args, "timing", 0.01, 0.0, 0.25)
    velocity = _int_arg(args, "velocity", 8, 0, 64)
    seed = _int_arg(args, "seed", 0, -2147483648, 2147483647)
    if timing == 0.0 and velocity == 0:
        raise ScriptError("BAD_ARGS", "timing and velocity cannot both be zero")

    rng = random.Random(seed)
    context = _context(args, song)
    notes, shifted, velocity_changed = [], 0, 0
    for pitch, start, duration, vel, mute in context["original"]:
        offset = rng.uniform(-timing, timing) if timing else 0.0
        change = rng.randint(-velocity, velocity) if velocity else 0
        new_start = max(0.0, start + offset)
        new_velocity = min(127, max(0, vel + change))
        if abs(new_start - start) > 1e-9:
            shifted += 1
        if new_velocity != vel:
            velocity_changed += 1
        notes.append([pitch, new_start, duration, new_velocity, mute])
    return _result(
        context, notes, dry_run,
        timing=timing, velocity=velocity, seed=seed,
        shifted=shifted, velocity_changed=velocity_changed,
    )


@command("notes.strum")
def strum(args, song):
    check_args(args, allowed=(
        "track", "clip", "location", "slot", "offset", "direction", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restored = _restore_requested(
        args, song, dry_run, ("track", "clip", "location", "slot", "offset", "direction")
    )
    if restored is not None:
        return restored

    offset = _float_arg(args, "offset", 0.02, 0.001, 0.5)
    direction = args.get("direction", "up")
    if direction not in ("up", "down"):
        raise ScriptError("BAD_ARGS", "direction must be 'up' or 'down'")

    context = _context(args, song)
    original = context["original"]
    groups = {}
    for index, note in enumerate(original):
        groups.setdefault(round(note[1], 6), []).append(index)
    notes = [list(note) for note in original]
    strummed = 0
    for indices in groups.values():
        if len(indices) < 2:
            continue
        order = sorted(indices, key=lambda index: original[index][0])
        if direction == "down":
            order.reverse()
        for rank, index in enumerate(order):
            if rank:
                notes[index][1] = original[index][1] + rank * offset
        strummed += 1
    return _result(context, notes, dry_run, offset=offset, direction=direction, groups=strummed)


@command("notes.replace")
def replace(args, song):
    check_args(args, allowed=(
        "track", "clip", "location", "slot", "start", "notes", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restored = _restore_requested(
        args, song, dry_run, ("track", "clip", "location", "slot", "start", "notes")
    )
    if restored is not None:
        return restored

    if "notes" not in args:
        raise ScriptError("BAD_ARGS", "missing argument(s): notes")
    notes = _validated_notes(args.get("notes"))
    context = _context(args, song)
    return _result(context, notes, dry_run, replaced=len(context["original"]))


@command("notes.scale_lock")
def scale_lock(args, song):
    check_args(args, allowed=(
        "track", "clip", "location", "slot", "root", "scale", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restored = _restore_requested(
        args, song, dry_run, ("track", "clip", "location", "slot", "root", "scale")
    )
    if restored is not None:
        return restored

    root = _root_pitch(args.get("root", "C"))
    scale = args.get("scale", "major")
    if not isinstance(scale, str) or scale not in SCALES:
        raise ScriptError(
            "BAD_ARGS", "scale must be one of: %s" % ", ".join(sorted(SCALES))
        )
    allowed = {(root + step) % 12 for step in SCALES[scale]}

    context = _context(args, song)
    notes, changed = [], 0
    for pitch, start, duration, velocity, mute in context["original"]:
        new_pitch = _nearest_in_scale(pitch, allowed)
        if new_pitch != pitch:
            changed += 1
        notes.append([new_pitch, start, duration, velocity, mute])
    return _result(context, notes, dry_run, root=root, scale=scale, changed=changed)

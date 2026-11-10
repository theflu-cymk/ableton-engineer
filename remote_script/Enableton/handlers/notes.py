"""Read one MIDI clip's notes.

The note reader lives in ``structure`` because the snapshot's overlap report already depends on it;
this command exposes the same records for one clip instead of a Set-wide count. ``_read_notes``
distinguishes "no notes" from "could not read notes", and that distinction is preserved here: a
non-MIDI clip or a failed read returns ``notes_available: false`` with the reason, never an empty
list that looks like a clean clip.
"""

from __future__ import annotations

from ..dispatch import check_args, command
from ..errors import ScriptError
from .clips import _attr, _resolve_clip
from .structure import _note_record, _read_notes

MAX_NOTES_LIMIT = 1000


@command("notes.read")
def read(args, song):
    check_args(args, allowed=("track", "clip", "location", "slot", "offset", "limit"))

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
        song, track_name, clip_name, args.get("location"), args.get("slot")
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

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

from ..dispatch import check_args, command
from ..errors import ScriptError


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
        if not dry_run:
            delete(found)
        restored.append({
            "track": track.name,
            "track_index": index,
            "clip": str(_attr(found, "name", "")),
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

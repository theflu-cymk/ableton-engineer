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


@command("tracks.gain_stage")
def gain_stage(args, song):
    check_args(args, allowed=("tracks", "headroom_db", "dry_run"))
    headroom_db = float(args.get("headroom_db", -6.0))
    dry_run = bool(args.get("dry_run", True))
    wanted = list(args.get("tracks") or [])

    if wanted:
        known = [track.name for track in song.tracks]
        missing = [name for name in wanted if name not in known]
        if missing:
            raise ScriptError("NOT_FOUND", "no track named %s" % ", ".join(missing))
        targets = [track for track in song.tracks if track.name in wanted]
    else:
        targets = list(song.tracks)

    changes, skipped = [], []
    for track in targets:
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
            "from": round(current, 4),
            "to": round(new_volume, 4),
            "offset_db": round(offset_db, 2),
        })
        if not dry_run:
            _set_param(track, "volume", "volume", new_volume)

    return {"dry_run": dry_run, "changes": changes, "skipped": skipped}

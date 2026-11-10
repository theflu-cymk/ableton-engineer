"""One read of the whole Set.

Every report is computed from this payload, so a question about a 77-track Set costs one round
trip instead of one per track. It is read-only and tolerant: a Live build that does not expose
locators reports ``locators_available: false`` rather than an empty list that looks like an
answer.

Attribute access is defensive because the LOM differs across Live versions and because the fake
backend must satisfy the same code path.
"""

from __future__ import annotations

from ..dispatch import check_args, command


def _attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _param(track, name):
    """Read a mixer parameter and its display string, if the backend exposes them."""
    mixer = _attr(track, "mixer_device")
    if mixer is None:
        return None, None
    param = _attr(mixer, name)
    if param is None:
        return None, None
    value = _attr(param, "value")
    text = None
    display = _attr(param, "str_for_value")
    if callable(display) and value is not None:
        try:
            text = str(display(value))
        except Exception:
            text = None
    return (None if value is None else float(value)), text


def _kind(track):
    if bool(_attr(track, "is_foldable", False)):
        return "group"
    if bool(_attr(track, "has_midi_input", False)):
        return "midi"
    return "audio"


def _devices(track):
    out = []
    for index, device in enumerate(_attr(track, "devices", []) or []):
        class_name = str(_attr(device, "class_name", "") or "")
        out.append(
            {
                "index": index,
                "name": str(_attr(device, "name", "")),
                "class": class_name,
                "plugin": class_name.endswith("PluginDevice"),
                "active": bool(_attr(device, "is_active", True)),
            }
        )
    return out


def _clip(clip):
    start = float(_attr(clip, "start_time", 0.0) or 0.0)
    end = float(_attr(clip, "end_time", start) or start)
    row = {
        "name": str(_attr(clip, "name", "")),
        "start": round(start, 4),
        "end": round(end, 4),
        "length": round(max(0.0, end - start), 4),
        "midi": bool(_attr(clip, "is_midi_clip", False)),
    }
    if not row["midi"]:
        row["warping"] = bool(_attr(clip, "warping", False))
    return row


def _session(track):
    slots = _attr(track, "clip_slots", []) or []
    filled = []
    for index, slot in enumerate(slots):
        clip = _attr(slot, "clip")
        if clip is None:
            continue
        filled.append(
            {
                "slot": index,
                "name": str(_attr(clip, "name", "")),
                "midi": bool(_attr(clip, "is_midi_clip", False)),
            }
        )
    return {"filled": len(filled), "empty": max(0, len(slots) - len(filled)), "clips": filled}


def _track_row(track, index, kind, group):
    volume, volume_str = _param(track, "volume")
    pan, _ = _param(track, "panning")
    if volume is None:
        volume = _attr(track, "volume")
    if pan is None:
        pan = _attr(track, "pan")
    return {
        "index": index,
        "name": str(_attr(track, "name", "")),
        "kind": kind,
        "group": group,
        "volume": None if volume is None else round(float(volume), 4),
        "volume_str": volume_str,
        "pan": None if pan is None else round(float(pan), 4),
        "mute": bool(_attr(track, "mute", False)),
        "solo": bool(_attr(track, "solo", False)),
        "arm": bool(_attr(track, "arm", False)),
        "devices": _devices(track),
        "session": _session(track),
        "arrangement": [_clip(c) for c in (_attr(track, "arrangement_clips", []) or [])],
    }


@command("snapshot.get")
def snapshot(args, song):
    check_args(args)

    main = list(_attr(song, "tracks", []) or [])
    returns = list(_attr(song, "return_tracks", []) or [])
    everything = main + returns
    index_of = {id(track): index for index, track in enumerate(everything)}

    rows = []
    for index, track in enumerate(main):
        group = _attr(track, "group_track")
        group_index = index_of.get(id(group)) if group is not None else _attr(track, "group_index")
        rows.append(_track_row(track, index, _kind(track), group_index))
    for offset, track in enumerate(returns):
        rows.append(_track_row(track, len(main) + offset, "return", None))

    scenes = []
    raw_scenes = _attr(song, "scenes", []) or []
    slots_by_track = [(track, _attr(track, "clip_slots", []) or []) for track in everything]
    for index, scene in enumerate(raw_scenes):
        filled = 0
        for _track, slots in slots_by_track:
            if index < len(slots) and _attr(slots[index], "clip") is not None:
                filled += 1
        scenes.append({"index": index, "name": str(_attr(scene, "name", "")), "filled": filled})

    raw_locators = _attr(song, "locators")
    locators = []
    for index, locator in enumerate(raw_locators or []):
        locators.append(
            {
                "index": index,
                "name": str(_attr(locator, "name", "")),
                "time": round(float(_attr(locator, "time", 0.0) or 0.0), 4),
            }
        )

    arrangement = sum(len(row["arrangement"]) for row in rows)
    session_clips = sum(row["session"]["filled"] for row in rows)
    devices = sum(len(row["devices"]) for row in rows)

    return {
        "song": {
            "name": str(_attr(song, "name", "untitled")),
            "tempo": round(float(_attr(song, "tempo", 120.0)), 4),
            "signature": [
                int(_attr(song, "signature_numerator", 4)),
                int(_attr(song, "signature_denominator", 4)),
            ],
            "is_playing": bool(_attr(song, "is_playing", False)),
            "current_song_time": round(float(_attr(song, "current_song_time", 0.0) or 0.0), 4),
            "loop": {
                "start": float(_attr(song, "loop_start", 0.0) or 0.0),
                "length": float(_attr(song, "loop_length", 0.0) or 0.0),
                "enabled": bool(_attr(song, "loop", False)),
            },
            "scene_count": len(scenes),
        },
        "tracks": rows,
        "scenes": scenes,
        "locators": locators,
        "counts": {
            "tracks": len(main),
            "returns": len(returns),
            "scenes": len(scenes),
            "locators": len(locators),
            "arrangement_clips": arrangement,
            "session_clips": session_clips,
            "devices": devices,
            "empty_session_slots": sum(row["session"]["empty"] for row in rows),
        },
        "captured": {"locators_available": raw_locators is not None},
    }

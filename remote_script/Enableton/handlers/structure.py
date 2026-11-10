"""One read of the whole Set.

Every report is computed from this payload, so a question about a 77-track Set costs one round
trip instead of one per track. It is read-only and tolerant: a Live build that does not expose
locators reports ``locators_available: false`` **with the reason the read failed** rather than an
empty list that looks like an answer.

Devices are read through rack chains, not just at track level: a Set's real device population is
mostly inside racks, and counting only the top level under-reports it by an order of magnitude.

Attribute access is defensive because the LOM differs across Live versions and because the fake
backend must satisfy the same code path.
"""

from __future__ import annotations

from ..dispatch import check_args, command
from ..errors import ScriptError


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


# Racks nest devices inside chains. Three levels covers racks-in-racks in practice; past the cap
# the row is marked truncated, so a capped tree can never be mistaken for a complete one.
MAX_DEVICE_DEPTH = 3

#: ``Clip.warp_mode`` is a documented enum. The raw integer stays in the payload as the
#: authoritative value; the name is only there so a report does not have to repeat this table.
#: Live 12.2.5 exposed 6 for the one Complex Pro clip in Crust Wumble; the LOM documents 5 as REX
#: and 6 as Complex Pro, so an earlier table that put Complex Pro at 5 was wrong.
WARP_MODES = {
    0: "beats",
    1: "tones",
    2: "texture",
    3: "re-pitch",
    4: "complex",
    5: "rex",
    6: "complex_pro",
}


def _device_row(device, index, depth):
    class_name = str(_attr(device, "class_name", "") or "")
    row = {
        "index": index,
        "name": str(_attr(device, "name", "")),
        "class": class_name,
        "plugin": class_name.endswith("PluginDevice"),
        "active": bool(_attr(device, "is_active", True)),
        "depth": depth,
    }
    chains = _attr(device, "chains")
    if chains:
        if depth + 1 > MAX_DEVICE_DEPTH:
            row["truncated"] = True
        else:
            row["chains"] = [
                [
                    _device_row(child, child_index, depth + 1)
                    for child_index, child in enumerate(_attr(chain, "devices", []) or [])
                ]
                for chain in chains
            ]
    return row


def _devices(track):
    return [
        _device_row(device, index, 0)
        for index, device in enumerate(_attr(track, "devices", []) or [])
    ]


def _count_devices(rows):
    total = 0
    for row in rows:
        total += 1
        for chain in row.get("chains") or []:
            total += _count_devices(chain)
    return total


def _master_devices(song):
    """The master chain's devices, read through the same walk as any track.

    ``song.master_track`` sits outside ``tracks`` and ``return_tracks``, so a snapshot that walks
    only those two silently drops everything on the master: Crust Wumble's file holds 108 device
    elements, 6 of them in ``MainTrack``. A missing attribute returns a reason, never a silent 0.
    """
    try:
        master = song.master_track
    except Exception as exc:  # noqa: BLE001 - the reason is the point
        return [], False, "master_track: %s: %s" % (type(exc).__name__, exc)
    if master is None:
        return [], False, "master_track: None"
    return _devices(master), True, None


def _warp_fields(clip, row):
    """Add warp state to an audio clip row.

    ``Clip.warp_markers`` is a Live-built vector and its length is the number of markers the clip
    actually has, so this counts without copying Marker objects into the payload. When the read
    fails the count is ``None`` and the reason travels beside it: zero markers and an unreadable
    vector are different answers, and a check that treated them alike would flag nothing.
    """
    row["warping"] = bool(_attr(clip, "warping", False))
    mode = _attr(clip, "warp_mode", None)
    try:
        mode = None if mode is None else int(mode)
    except (TypeError, ValueError):
        mode = None
    row["warp_mode"] = mode
    row["warp_mode_name"] = WARP_MODES.get(mode)
    try:
        markers = clip.warp_markers
    except Exception as exc:  # noqa: BLE001 - the reason is the point
        row["warp_markers"] = None
        row["warp_markers_reason"] = "warp_markers: %s: %s" % (type(exc).__name__, exc)
        return
    try:
        row["warp_markers"] = 0 if markers is None else len(markers)
    except Exception as exc:  # noqa: BLE001 - the reason is the point
        row["warp_markers"] = None
        row["warp_markers_reason"] = "warp_markers: %s: %s" % (type(exc).__name__, exc)


#: MIDI note collisions are captured as pairs, not as every note. This bounds a snapshot of a
#: dense drum Set while still naming the exact collisions a producer needs to see.
MAX_NOTE_OVERLAPS_TOTAL = 2000
NOTE_EPSILON = 1e-9


def _note_record(note):
    start = float(_attr(note, "start_time", 0.0) or 0.0)
    duration = _attr(note, "duration", None)
    if duration is None:
        end = _attr(note, "end_time", None)
        duration = 0.0 if end is None else float(end) - start
    return {
        "pitch": int(_attr(note, "pitch", 0) or 0),
        "start": round(start, 4),
        "duration": round(max(0.0, float(duration or 0.0)), 4),
        "velocity": int(_attr(note, "velocity", 0) or 0),
        "mute": bool(_attr(note, "mute", False)),
    }


def _read_notes(clip):
    """Return ``(notes, source)`` for one MIDI clip, or raise naming everything that failed.

    Live 11 and later read notes through ``get_all_notes_extended()``; ``Clip.notes`` is the legacy
    attribute, and on a build that does not expose it a ``getattr`` default turns "cannot read"
    into "this clip is empty". Crust Wumble showed exactly that: clips holding 412 and 799 notes
    came back as zero, with ``notes_available: true`` beside them. The source that answered
    travels with the count, so a zero is never ambiguous.
    """
    problems = []
    extended = getattr(clip, "get_all_notes_extended", None)
    if callable(extended):
        try:
            return list(extended()), "extended"
        except Exception as exc:  # noqa: BLE001 - fall back, but keep the reason
            problems.append("get_all_notes_extended: %s: %s" % (type(exc).__name__, exc))
    try:
        legacy = getattr(clip, "notes", None)
    except Exception as exc:  # noqa: BLE001 - the reason is the point
        problems.append("notes: %s: %s" % (type(exc).__name__, exc))
        legacy = None
    if legacy is not None:
        try:
            return list(legacy), "notes"
        except Exception as exc:  # noqa: BLE001 - the reason is the point
            problems.append("notes: %s: %s" % (type(exc).__name__, exc))
    else:
        problems.append("notes: attribute absent")
    raise RuntimeError("; ".join(problems))


def _note_overlaps(clip, budget):
    """Return ``(note_count, pairs, truncated, reason, source)`` for one MIDI clip.

    A chord is not an overlap: only notes of the same pitch whose time ranges intersect are
    reported. The pair list carries the two note positions and their intersection, so the report
    does not have to re-read Live. When the read fails, the count is ``None`` and the reason
    travels with it; zero notes and an unreadable note vector are different answers.
    """
    try:
        raw, source = _read_notes(clip)
        notes = [_note_record(note) for note in (raw or [])]
    except Exception as exc:  # noqa: BLE001 - the reason is the point
        return None, [], False, "note read failed: %s" % (exc,), None

    by_pitch = {}
    for note in notes:
        if note["duration"] > NOTE_EPSILON:
            by_pitch.setdefault(note["pitch"], []).append(note)

    pairs = []
    for pitch in sorted(by_pitch):
        active = []
        for note in sorted(by_pitch[pitch], key=lambda row: (row["start"], row["duration"], row["velocity"])):
            active = [
                row for row in active
                if row["start"] + row["duration"] > note["start"] + NOTE_EPSILON
            ]
            for other in active:
                overlap = min(
                    other["start"] + other["duration"], note["start"] + note["duration"]
                ) - max(other["start"], note["start"])
                if overlap <= NOTE_EPSILON:
                    continue
                if budget["remaining"] <= 0:
                    return len(notes), pairs, True, None, source
                pairs.append({
                    "pitch": pitch,
                    "first": other,
                    "second": note,
                    "overlap": round(overlap, 4),
                })
                budget["remaining"] -= 1
            active.append(note)
    return len(notes), pairs, False, None, source


def _note_fields(clip, row, budget):
    count, pairs, truncated, reason, source = _note_overlaps(clip, budget)
    row["note_count"] = count
    row["note_overlaps"] = pairs
    row["note_overlaps_truncated"] = truncated
    row["notes_source"] = source
    if reason is not None:
        row["note_overlaps_reason"] = reason


def _clip(clip, budget):
    start = float(_attr(clip, "start_time", 0.0) or 0.0)
    end = float(_attr(clip, "end_time", start) or start)
    row = {
        "name": str(_attr(clip, "name", "")),
        "start": round(start, 4),
        "end": round(end, 4),
        "length": round(max(0.0, end - start), 4),
        "midi": bool(_attr(clip, "is_midi_clip", False)),
    }
    if row["midi"]:
        _note_fields(clip, row, budget)
    else:
        _warp_fields(clip, row)
    return row


def _session(track, budget):
    slots = _attr(track, "clip_slots", []) or []
    filled = []
    for index, slot in enumerate(slots):
        clip = _attr(slot, "clip")
        if clip is None:
            continue
        entry = {
            "slot": index,
            "name": str(_attr(clip, "name", "")),
            "midi": bool(_attr(clip, "is_midi_clip", False)),
        }
        if entry["midi"]:
            _note_fields(clip, entry, budget)
        else:
            _warp_fields(clip, entry)
        filled.append(entry)
    return {"filled": len(filled), "empty": max(0, len(slots) - len(filled)), "clips": filled}


def _warp_totals(rows):
    """Marker count across every audio clip, and how many marker reads failed."""
    markers = 0
    unreadable = 0
    for row in rows:
        clips = list(row["arrangement"]) + list(row["session"]["clips"])
        for clip in clips:
            if clip.get("midi") or "warp_markers" not in clip:
                continue
            count = clip["warp_markers"]
            if count is None:
                unreadable += 1
            else:
                markers += count
    return markers, unreadable


def _note_totals(rows):
    """Count captured MIDI notes, collision pairs, truncation and unreadable clips.

    Also returns which API answered for the readable clips, and the first read failure, so the
    payload says *how* it knows a clip is empty instead of only that it thinks so.
    """
    notes_read = 0
    overlaps = 0
    truncated = 0
    unreadable = 0
    sources = {}
    reason = None
    for row in rows:
        clips = list(row["arrangement"]) + list(row["session"]["clips"])
        for clip in clips:
            if not clip.get("midi"):
                continue
            count = clip.get("note_count")
            if count is None:
                unreadable += 1
                if reason is None:
                    reason = "%s / %s: %s" % (
                        row.get("name"), clip.get("name"), clip.get("note_overlaps_reason")
                    )
            else:
                notes_read += count
            source = clip.get("notes_source")
            if source:
                sources[source] = sources.get(source, 0) + 1
            overlaps += len(clip.get("note_overlaps") or [])
            if clip.get("note_overlaps_truncated"):
                truncated += 1
    return notes_read, overlaps, truncated, unreadable, sources, reason


def _track_row(track, index, kind, group, budget):
    volume, volume_str = _param(track, "volume")
    pan, _ = _param(track, "panning")
    if volume is None:
        volume = _attr(track, "volume")
    if pan is None:
        pan = _attr(track, "pan")
    devices = _devices(track)
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
        "devices": devices,
        "device_count": _count_devices(devices),
        "session": _session(track, budget),
        "arrangement": [_clip(c, budget) for c in (_attr(track, "arrangement_clips", []) or [])],
    }


def _locator_source(song):
    """Return ``(locators, attribute_that_answered, reason_it_failed)``.

    Live 12 exposes ``Song.locators``; some builds answer on ``cue_points`` instead. When neither
    answers, the reason travels with the payload: an unreadable list must not be reported as an
    empty one, and "unavailable" without a reason is what this project forbids.
    """
    problems = []
    for name in ("locators", "cue_points"):
        try:
            return list(getattr(song, name) or []), name, None
        except Exception as exc:  # noqa: BLE001 - the reason is the point
            problems.append("%s: %s: %s" % (name, type(exc).__name__, exc))
    return [], None, "; ".join(problems)


@command("snapshot.get")
def snapshot(args, song):
    check_args(args)

    main = list(_attr(song, "tracks", []) or [])
    returns = list(_attr(song, "return_tracks", []) or [])
    everything = main + returns
    index_of = {id(track): index for index, track in enumerate(everything)}

    budget = {"remaining": MAX_NOTE_OVERLAPS_TOTAL}
    rows = []
    for index, track in enumerate(main):
        group = _attr(track, "group_track")
        group_index = index_of.get(id(group)) if group is not None else _attr(track, "group_index")
        rows.append(_track_row(track, index, _kind(track), group_index, budget))
    for offset, track in enumerate(returns):
        rows.append(_track_row(track, len(main) + offset, "return", None, budget))

    scenes = []
    raw_scenes = _attr(song, "scenes", []) or []
    slots_by_track = [(track, _attr(track, "clip_slots", []) or []) for track in everything]
    for index, scene in enumerate(raw_scenes):
        filled = 0
        for _track, slots in slots_by_track:
            if index < len(slots) and _attr(slots[index], "clip") is not None:
                filled += 1
        scenes.append({"index": index, "name": str(_attr(scene, "name", "")), "filled": filled})

    raw_locators, locator_attr, locator_reason = _locator_source(song)
    locators = []
    for index, locator in enumerate(raw_locators):
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
    devices_total = sum(row["device_count"] for row in rows)
    master_devices, master_available, master_reason = _master_devices(song)
    master_total = _count_devices(master_devices)
    warp_markers, warp_unreadable = _warp_totals(rows)
    (notes_read, note_overlaps, note_truncated, notes_unreadable,
     notes_sources, notes_reason) = _note_totals(rows)
    file_path = _attr(song, "file_path", None)

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
            "file_path": str(file_path) if file_path else None,
        },
        "tracks": rows,
        "master_track": {
            "available": master_available,
            "devices": master_devices,
            "device_count": master_total,
        },
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
            "devices_master": master_total,
            "devices_total": devices_total + master_total,
            "warp_markers": warp_markers,
            "warp_markers_unreadable": warp_unreadable,
            "notes_read": notes_read,
            "note_overlaps": note_overlaps,
            "note_overlaps_truncated": note_truncated,
            "notes_unreadable": notes_unreadable,
            "notes_sources": notes_sources,
            "empty_session_slots": sum(row["session"]["empty"] for row in rows),
        },
        "captured": {
            "locators_available": locator_attr is not None,
            "locators_attribute": locator_attr,
            "locators_reason": locator_reason,
            "master_available": master_available,
            "master_reason": master_reason,
            "notes_available": notes_unreadable == 0,
            "notes_reason": notes_reason,
        },
    }


def _track_ref(song, args):
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
                "%d tracks are named %r; rename one before editing its devices"
                % (len(matches), name),
            )
        return matches[0]

    index = args.get("track_index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ScriptError("BAD_ARGS", "track_index must be a non-negative integer")
    if index >= len(song.tracks):
        raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
    return index, song.tracks[index]


def _device_ref(track, args):
    devices = list(_attr(track, "devices", []) or [])
    has_name = "device" in args
    has_index = "device_index" in args
    if has_name == has_index:
        raise ScriptError("BAD_ARGS", "give exactly one of device or device_index")
    if has_index:
        index = args.get("device_index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ScriptError("BAD_ARGS", "device_index must be a non-negative integer")
        if index >= len(devices):
            raise ScriptError("NOT_FOUND", "no device at index %s" % (index,))
        return index, devices[index]

    name = args.get("device")
    if not isinstance(name, str) or not name:
        raise ScriptError("BAD_ARGS", "device must be a non-empty string")
    matches = [
        (index, device) for index, device in enumerate(devices)
        if str(_attr(device, "name", "")) == name
    ]
    if not matches:
        raise ScriptError("NOT_FOUND", "no device named %r" % (name,))
    if len(matches) > 1:
        raise ScriptError(
            "AMBIGUOUS_REF",
            "%d devices are named %r; use device_index" % (len(matches), name),
        )
    return matches[0]


def _active_state(device):
    value = _attr(device, "is_active", None)
    if value is None:
        raise ScriptError(
            "UNSUPPORTED",
            "device %r does not expose is_active on this Live build"
            % (str(_attr(device, "name", "")),),
        )
    return bool(value)


def _set_active(device, active):
    try:
        device.is_active = active
    except Exception as exc:  # noqa: BLE001 - the Live reason belongs in the error
        raise ScriptError(
            "LIVE_ERROR",
            "could not change device %r: %s"
            % (str(_attr(device, "name", "")), exc),
        )


@command("devices.bypass")
def bypass(args, song):
    check_args(args, allowed=(
        "track", "track_index", "device", "device_index", "bypass", "dry_run", "restore",
    ))
    dry_run = bool(args.get("dry_run", True))
    restore = args.get("restore")
    if restore is not None:
        if any(key in args for key in ("track", "track_index", "device", "device_index", "bypass")):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a device selection")
        if not isinstance(restore, list) or not restore:
            raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
        changes = []
        for entry in reversed(restore):
            if not isinstance(entry, dict):
                raise ScriptError("BAD_ARGS", "restore entries must be objects")
            try:
                track_index = int(entry["track_index"])
                device_index = int(entry["device_index"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError(
                    "BAD_ARGS", "restore entries need track_index and device_index"
                )
            active = entry.get("active")
            if not isinstance(active, bool):
                raise ScriptError("BAD_ARGS", "restore active must be a boolean")
            if track_index < 0 or track_index >= len(song.tracks):
                raise ScriptError("NOT_FOUND", "no track at index %s" % (track_index,))
            track = song.tracks[track_index]
            devices = list(_attr(track, "devices", []) or [])
            if device_index < 0 or device_index >= len(devices):
                raise ScriptError("NOT_FOUND", "no device at index %s" % (device_index,))
            device = devices[device_index]
            current = _active_state(device)
            if not dry_run:
                _set_active(device, active)
            changes.append({
                "track": str(_attr(track, "name", "")),
                "track_index": track_index,
                "device": str(_attr(device, "name", "")),
                "device_index": device_index,
                "from": current,
                "to": active,
            })
        return {"dry_run": dry_run, "restored": len(changes), "changes": changes}

    bypass_requested = args.get("bypass")
    if not isinstance(bypass_requested, bool):
        raise ScriptError("BAD_ARGS", "bypass must be a boolean")
    track_index, track = _track_ref(song, args)
    device_index, device = _device_ref(track, args)
    current = _active_state(device)
    target = not bypass_requested
    if not dry_run:
        _set_active(device, target)
    return {
        "dry_run": dry_run,
        "track": str(_attr(track, "name", "")),
        "track_index": track_index,
        "device": str(_attr(device, "name", "")),
        "device_index": device_index,
        "bypass": bypass_requested,
        "from": current,
        "to": target,
        "active": target,
        "undo": [{
            "track_index": track_index,
            "device_index": device_index,
            "active": current,
        }],
    }

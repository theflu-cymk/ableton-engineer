"""Device-chain edits: parameters, macros, order and removal.

Live exposes a device's parameters as one vector, and a rack's macros are parameters in that same
vector. Every resolution here is strict: a name matching several devices is ``AMBIGUOUS_REF`` with
the candidate indexes, because two EQ Eights on one chain is normal and "the first one" would edit
the wrong device.

``devices.delete`` is the one tool here that this build cannot undo: ``Track.insert_device`` arrives
in Live 12.3, so a removed device cannot be put back programmatically on 12.2.5. It therefore
refuses to apply without ``confirm: true`` and declares ``reversible: false``.
"""

from __future__ import annotations

import math

from ..dispatch import check_args, command
from ..errors import ScriptError
from .library import _browser, _children, _item_row

#: Macros are named "Macro 1" … "Macro 16" by Live, and only racks have them.
MAX_MACRO = 16

#: Presets live under the device categories; samples and packs are not device presets.
PRESET_CATEGORIES = ("instruments", "audio_effects", "midi_effects")

MAX_LIMIT = 200

#: A browse that matched the whole library must not walk it. Eight device folders is already more
#: than one question needs, and the count is reported so a capped answer cannot look complete.
MAX_SCAN = 2000  # safety stop for a hostile browser tree, never a page size


def _attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScriptError("BAD_ARGS", "%s must be a number" % (label,))
    value = float(value)
    if not math.isfinite(value):
        raise ScriptError("BAD_ARGS", "%s must be a finite number" % (label,))
    return value


def _track(song, args):
    name = args.get("track")
    index = args.get("track_index")
    if (name is None) == (index is None):
        raise ScriptError("BAD_ARGS", "give exactly one of track or track_index")
    tracks = list(_attr(song, "tracks", []) or [])
    if name is not None:
        if not isinstance(name, str) or not name:
            raise ScriptError("BAD_ARGS", "track must be a non-empty string")
        matches = [
            (position, track) for position, track in enumerate(tracks)
            if str(_attr(track, "name", "")) == name
        ]
        if not matches:
            raise ScriptError("NOT_FOUND", "no track named %r" % (name,))
        if len(matches) > 1:
            raise ScriptError(
                "AMBIGUOUS_REF",
                "%d tracks are named %r; use track_index instead" % (len(matches), name),
            )
        return matches[0]
    if isinstance(index, bool) or not isinstance(index, int):
        raise ScriptError("BAD_ARGS", "track_index must be an integer")
    if index < 0 or index >= len(tracks):
        raise ScriptError("NOT_FOUND", "no track at index %s" % (index,))
    return index, tracks[index]


def _devices(track):
    return list(_attr(track, "devices", []) or [])


def _device(track, args):
    name = args.get("device")
    index = args.get("device_index")
    if (name is None) == (index is None):
        raise ScriptError("BAD_ARGS", "give exactly one of device or device_index")
    devices = _devices(track)
    if name is not None:
        if not isinstance(name, str) or not name:
            raise ScriptError("BAD_ARGS", "device must be a non-empty string")
        matches = [
            (position, device) for position, device in enumerate(devices)
            if str(_attr(device, "name", "")) == name
        ]
        if not matches:
            raise ScriptError(
                "NOT_FOUND",
                "no device named %r on track %r"
                % (name, str(_attr(track, "name", "") or "")),
            )
        if len(matches) > 1:
            raise ScriptError(
                "AMBIGUOUS_REF",
                "%d devices are named %r at indexes %s; use device_index"
                % (len(matches), name, ", ".join(str(position) for position, _ in matches)),
            )
        return matches[0]
    if isinstance(index, bool) or not isinstance(index, int):
        raise ScriptError("BAD_ARGS", "device_index must be an integer")
    if index < 0 or index >= len(devices):
        raise ScriptError("NOT_FOUND", "no device at index %s" % (index,))
    return index, devices[index]


def _parameters(device):
    return list(_attr(device, "parameters", []) or [])


def _parameter_at(device, index, wanted):
    parameters = _parameters(device)
    if index < 0 or index >= len(parameters):
        raise ScriptError("NOT_FOUND", "no parameter at index %s" % (index,))
    parameter = parameters[index]
    if wanted is not None and str(_attr(parameter, "name", "") or "") != str(wanted):
        raise ScriptError(
            "NOT_FOUND",
            "the parameter at index %s is now %r, not %r"
            % (index, str(_attr(parameter, "name", "") or ""), wanted),
        )
    return parameter


def _writable(parameter):
    enabled = _attr(parameter, "is_enabled", True)
    if enabled is not None and not bool(enabled):
        raise ScriptError(
            "PRECONDITION_FAILED",
            "parameter %r is disabled; Live will not accept a value for it"
            % (str(_attr(parameter, "name", "") or ""),),
        )


def _bounded(value, parameter):
    low = _attr(parameter, "min", None)
    high = _attr(parameter, "max", None)
    if isinstance(low, (int, float)) and not isinstance(low, bool) and value < float(low) - 1e-9:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "value %s is below %r's minimum %s"
            % (value, str(_attr(parameter, "name", "") or ""), low),
        )
    if isinstance(high, (int, float)) and not isinstance(high, bool) and value > float(high) + 1e-9:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "value %s is above %r's maximum %s"
            % (value, str(_attr(parameter, "name", "") or ""), high),
        )
    return value


def _display(parameter, value):
    formatter = _attr(parameter, "str_for_value", None)
    if not callable(formatter):
        return None
    try:
        return str(formatter(value))
    except Exception:
        return None


def _quantised(value, parameter):
    """Snap a quantised parameter to the step Live will actually store.

    Live keeps a quantised parameter as an integer index, so asking for 1.5 on a three-way switch
    silently lands on 2. Snapping here means the dry run names the value that will be written, so
    the applied result can still match the preflight the executor approved.
    """
    if not bool(_attr(parameter, "is_quantized", False)):
        return value
    snapped = float(round(value))
    items = _attr(parameter, "value_items", None)
    if isinstance(items, (list, tuple)) and items:
        snapped = max(0.0, min(float(len(items) - 1), snapped))
    return snapped


def _write(parameter, value):
    """Write one parameter and refuse to claim a value Live did not store.

    Any remaining difference after the write means the applied result no longer matches the dry
    run, so it is a Live error rather than a rounding detail.
    """
    try:
        parameter.value = value
    except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
        raise ScriptError(
            "UNSUPPORTED", "this Live build refused the parameter write: %s" % (exc,)
        )
    read_back = float(_attr(parameter, "value", value) or 0.0)
    if abs(read_back - value) > 1e-6 * max(1.0, abs(value)):
        raise ScriptError(
            "LIVE_ERROR",
            "Live read back %s after being asked for %s on %r"
            % (read_back, value, str(_attr(parameter, "name", "") or "")),
        )
    return read_back


def _restore_parameters(entries, song, dry_run):
    if not isinstance(entries, list) or not entries:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    changes, missing = [], []
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        try:
            track_index = int(entry["track_index"])
            device_index = int(entry["device_index"])
            parameter_index = int(entry["parameter_index"])
            value = float(entry["value"])
        except (KeyError, TypeError, ValueError):
            raise ScriptError(
                "BAD_ARGS",
                "restore entries need track_index, device_index, parameter_index and value",
            )
        tracks = list(_attr(song, "tracks", []) or [])
        if track_index < 0 or track_index >= len(tracks):
            missing.append({"track_index": track_index, "reason": "no track at that index"})
            continue
        track = tracks[track_index]
        devices = _devices(track)
        if device_index < 0 or device_index >= len(devices):
            missing.append(
                {"track_index": track_index, "device_index": device_index,
                 "reason": "no device at that index"}
            )
            continue
        device = devices[device_index]
        wanted_device = entry.get("device")
        if wanted_device is not None and str(_attr(device, "name", "") or "") != wanted_device:
            missing.append(
                {"track_index": track_index, "device_index": device_index,
                 "reason": "the device at that index is now %r"
                           % (str(_attr(device, "name", "") or ""),)}
            )
            continue
        try:
            parameter = _parameter_at(device, parameter_index, entry.get("parameter"))
        except ScriptError as exc:
            missing.append(
                {"track_index": track_index, "device_index": device_index,
                 "parameter_index": parameter_index, "reason": str(exc)}
            )
            continue
        _bounded(value, parameter)
        if not dry_run:
            _write(parameter, value)
        changes.append({
            "track": str(_attr(track, "name", "") or ""),
            "track_index": track_index,
            "device": str(_attr(device, "name", "") or ""),
            "device_index": device_index,
            "parameter": str(_attr(parameter, "name", "") or ""),
            "parameter_index": parameter_index,
            "to": value,
        })
    return {
        "dry_run": dry_run,
        "restored": len(changes),
        "changes": changes,
        "missing": missing,
    }


@command("devices.set_parameter")
def set_parameter(args, song):
    check_args(
        args,
        allowed=(
            "track", "track_index", "device", "device_index",
            "parameter", "parameter_index", "value", "dry_run", "restore",
        ),
    )
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        overlapping = [
            key for key in (
                "track", "track_index", "device", "device_index",
                "parameter", "parameter_index", "value",
            )
            if key in args
        ]
        if overlapping:
            raise ScriptError(
                "BAD_ARGS", "restore cannot be combined with %s" % ", ".join(overlapping)
            )
        return _restore_parameters(args.get("restore"), song, dry_run)

    if "value" not in args:
        raise ScriptError("BAD_ARGS", "missing argument(s): value")
    track_index, track = _track(song, args)
    device_index, device = _device(track, args)
    parameter_index, parameter = _resolve_parameter(device, args)
    value = _quantised(_bounded(_number(args.get("value"), "value"), parameter), parameter)
    _writable(parameter)

    current = float(_attr(parameter, "value", 0.0) or 0.0)
    change = {
        "track": str(_attr(track, "name", "") or ""),
        "track_index": track_index,
        "device": str(_attr(device, "name", "") or ""),
        "device_index": device_index,
        "parameter": str(_attr(parameter, "name", "") or ""),
        "parameter_index": parameter_index,
        "from": current,
        "to": value,
        "display_from": _display(parameter, current),
        "display_to": _display(parameter, value),
    }
    undo = [{
        "track_index": track_index,
        "device_index": device_index,
        "device": change["device"],
        "parameter_index": parameter_index,
        "parameter": change["parameter"],
        "value": current,
    }]
    if not dry_run:
        _write(parameter, value)
    return {"dry_run": dry_run, "changes": [change], "undo": undo}


def _resolve_parameter(device, args):
    name = args.get("parameter")
    index = args.get("parameter_index")
    if (name is None) == (index is None):
        raise ScriptError("BAD_ARGS", "give exactly one of parameter or parameter_index")
    parameters = _parameters(device)
    if name is not None:
        if not isinstance(name, str) or not name:
            raise ScriptError("BAD_ARGS", "parameter must be a non-empty string")
        matches = [
            (position, parameter) for position, parameter in enumerate(parameters)
            if str(_attr(parameter, "name", "") or "") == name
        ]
        if not matches:
            raise ScriptError(
                "NOT_FOUND",
                "device %r has no parameter named %r"
                % (str(_attr(device, "name", "") or ""), name),
            )
        if len(matches) > 1:
            raise ScriptError(
                "AMBIGUOUS_REF",
                "%d parameters are named %r at indexes %s; use parameter_index"
                % (len(matches), name, ", ".join(str(position) for position, _ in matches)),
            )
        return matches[0]
    if isinstance(index, bool) or not isinstance(index, int):
        raise ScriptError("BAD_ARGS", "parameter_index must be an integer")
    if index < 0 or index >= len(parameters):
        raise ScriptError("NOT_FOUND", "no parameter at index %s" % (index,))
    return index, parameters[index]


@command("devices.set_macro")
def set_macro(args, song):
    check_args(
        args,
        allowed=(
            "track", "track_index", "device", "device_index",
            "macro", "value", "dry_run", "restore",
        ),
    )
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        overlapping = [
            key for key in ("track", "track_index", "device", "device_index", "macro", "value")
            if key in args
        ]
        if overlapping:
            raise ScriptError(
                "BAD_ARGS", "restore cannot be combined with %s" % ", ".join(overlapping)
            )
        return _restore_parameters(args.get("restore"), song, dry_run)

    macro = args.get("macro")
    if isinstance(macro, bool) or not isinstance(macro, int):
        raise ScriptError("BAD_ARGS", "macro must be an integer from 1 to 16")
    if macro < 1 or macro > MAX_MACRO:
        raise ScriptError("BAD_ARGS", "macro must be an integer from 1 to 16")
    if "value" not in args:
        raise ScriptError("BAD_ARGS", "missing argument(s): value")

    track_index, track = _track(song, args)
    device_index, device = _device(track, args)
    klass = str(_attr(device, "class_name", "") or "")
    if not klass.endswith("GroupDevice"):
        raise ScriptError(
            "UNSUPPORTED",
            "device %r is %s, not a rack; macros exist on racks only"
            % (str(_attr(device, "name", "") or ""), klass or "not a rack"),
        )
    # Live puts Macro 1..16 at parameter indexes 1..16 (index 0 is Device On), whatever names the
    # user gave them. Resolving by the literal name "Macro N" failed on the first real rack whose
    # macros were renamed, because Live reports the custom names instead.
    parameters = _parameters(device)
    if macro >= len(parameters):
        raise ScriptError(
            "UNSUPPORTED",
            "rack %r exposes %d parameters, so it has no Macro %d"
            % (str(_attr(device, "name", "") or ""), len(parameters), macro),
        )
    parameter_index, parameter = macro, parameters[macro]
    value = _quantised(_bounded(_number(args.get("value"), "value"), parameter), parameter)
    _writable(parameter)

    current = float(_attr(parameter, "value", 0.0) or 0.0)
    change = {
        "track": str(_attr(track, "name", "") or ""),
        "track_index": track_index,
        "device": str(_attr(device, "name", "") or ""),
        "device_index": device_index,
        "macro": macro,
        "parameter": str(_attr(parameter, "name", "") or ""),
        "parameter_index": parameter_index,
        "from": current,
        "to": value,
    }
    undo = [{
        "track_index": track_index,
        "device_index": device_index,
        "device": change["device"],
        "parameter_index": parameter_index,
        "parameter": str(_attr(parameter, "name", "") or ""),
        "value": current,
    }]
    if not dry_run:
        _write(parameter, value)
    return {"dry_run": dry_run, "changes": [change], "undo": undo}


def _move(song, track, device, to_index, from_index=None):
    """Move a device with whichever primitive this Live build exposes.

    12.2.5 has no ``Track.move_device``; ``Song.move_device(device, target, position)`` is the one
    that works there, and it indexes the chain *before* the device is taken out. A forward move
    therefore lands one index short: the real 0.3.6 gate saw ``2 -> 3`` do nothing and ``2 -> 4``
    land at 3. The track form, where a build has it, takes the final index. Both paths verify where
    the device actually landed, so a move that did not happen is an error rather than a report.

    ``from_index`` is the index the caller resolved the device at. It cannot be recovered here by
    identity: Live returns a fresh proxy on every ``track.devices`` access, so ``item is device``
    is false on the real build and the forward correction silently collapsed to a no-op. That is
    exactly how the first 0.3.7 gate failed.
    """
    name = str(_attr(device, "name", "") or "")
    devices = _devices(track)
    count = len(devices)
    start = from_index
    if start is None:
        for index, item in enumerate(devices):
            if item is device:
                start = index
                break
    if start is None:
        start = to_index

    mover = _attr(track, "move_device", None)
    song_mover = _attr(song, "move_device", None)
    if callable(mover):
        attempts = [to_index]
    elif callable(song_mover):
        attempts = [to_index + 1, to_index] if to_index > start else [to_index]
    else:
        raise ScriptError("UNSUPPORTED", "this Live build cannot reorder devices")

    landed = [str(_attr(item, "name", "") or "") for item in _devices(track)]
    failure = None
    for position in attempts:
        if position < 0 or position > count:
            continue
        try:
            if callable(mover):
                mover(device, position)
            else:
                song_mover(device, track, position)
        except Exception as exc:  # noqa: BLE001 - try the next position, report the last reason
            failure = exc
            continue
        landed = [str(_attr(item, "name", "") or "") for item in _devices(track)]
        if to_index < len(landed) and landed[to_index] == name:
            return to_index
    raise ScriptError(
        "LIVE_ERROR",
        "Live did not move %r to index %d; the chain now holds %s%s"
        % (name, to_index, ", ".join(landed) if landed else "nothing",
           " (%s)" % (failure,) if failure is not None else ""),
    )


@command("devices.move")
def move(args, song):
    check_args(
        args,
        allowed=("track", "track_index", "device", "device_index", "to_index", "dry_run", "restore"),
    )
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        overlapping = [
            key for key in ("track", "track_index", "device", "device_index", "to_index")
            if key in args
        ]
        if overlapping:
            raise ScriptError(
                "BAD_ARGS", "restore cannot be combined with %s" % ", ".join(overlapping)
            )
        return _restore_moves(args.get("restore"), song, dry_run)

    track_index, track = _track(song, args)
    device_index, device = _device(track, args)
    to_index = args.get("to_index")
    if isinstance(to_index, bool) or not isinstance(to_index, int):
        raise ScriptError("BAD_ARGS", "to_index must be an integer")
    count = len(_devices(track))
    if to_index < 0 or to_index >= count:
        raise ScriptError(
            "BAD_ARGS", "to_index must be from 0 to %d on this track" % (count - 1,)
        )

    name = str(_attr(device, "name", "") or "")
    change = {
        "track": str(_attr(track, "name", "") or ""),
        "track_index": track_index,
        "device": name,
        "class": str(_attr(device, "class_name", "") or ""),
        "from_index": device_index,
        "to_index": to_index,
    }
    if to_index == device_index:
        return {"dry_run": dry_run, "changes": [change], "undo": []}

    undo = [{
        "track_index": track_index,
        "device_index": to_index,
        "device": name,
        "to_index": device_index,
    }]
    if not dry_run:
        _move(song, track, device, to_index, device_index)
        landed = _devices(track)
        if len(landed) != count:
            raise ScriptError(
                "LIVE_ERROR",
                "the chain held %d devices before the move and %d after" % (count, len(landed)),
            )
        moved = landed[to_index]
        if str(_attr(moved, "name", "") or "") != name:
            raise ScriptError(
                "LIVE_ERROR",
                "Live did not move %r to index %d; index %d holds %r"
                % (name, to_index, to_index, str(_attr(moved, "name", "") or "")),
            )
    return {"dry_run": dry_run, "changes": [change], "undo": undo}


def _restore_moves(entries, song, dry_run):
    if not isinstance(entries, list) or not entries:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    changes, missing = [], []
    tracks = list(_attr(song, "tracks", []) or [])
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        try:
            track_index = int(entry["track_index"])
            device_index = int(entry["device_index"])
            to_index = int(entry["to_index"])
        except (KeyError, TypeError, ValueError):
            raise ScriptError(
                "BAD_ARGS", "restore entries need track_index, device_index and to_index"
            )
        if track_index < 0 or track_index >= len(tracks):
            missing.append({"track_index": track_index, "reason": "no track at that index"})
            continue
        track = tracks[track_index]
        devices = _devices(track)
        if device_index < 0 or device_index >= len(devices):
            missing.append(
                {"track_index": track_index, "device_index": device_index,
                 "reason": "no device at that index"}
            )
            continue
        device = devices[device_index]
        wanted = entry.get("device")
        if wanted is not None and str(_attr(device, "name", "") or "") != wanted:
            missing.append(
                {"track_index": track_index, "device_index": device_index,
                 "reason": "the device at that index is now %r"
                           % (str(_attr(device, "name", "") or ""),)}
            )
            continue
        if to_index < 0 or to_index >= len(devices):
            missing.append(
                {"track_index": track_index, "to_index": to_index,
                 "reason": "no index to move to"}
            )
            continue
        if dry_run:
            changes.append({"track_index": track_index, "device": wanted,
                            "from_index": device_index, "to_index": to_index})
            continue
        _move(song, track, device, to_index, device_index)
        changes.append({"track_index": track_index, "device": wanted,
                        "from_index": device_index, "to_index": to_index})
    return {
        "dry_run": dry_run,
        "restored": len(changes),
        "changes": changes,
        "missing": missing,
    }


@command("devices.delete")
def delete(args, song):
    check_args(
        args,
        allowed=("track", "track_index", "device", "device_index", "confirm", "dry_run"),
    )
    dry_run = bool(args.get("dry_run", True))
    track_index, track = _track(song, args)
    device_index, device = _device(track, args)
    name = str(_attr(device, "name", "") or "")
    row = {
        "track": str(_attr(track, "name", "") or ""),
        "track_index": track_index,
        "device": name,
        "class": str(_attr(device, "class_name", "") or ""),
        "device_index": device_index,
    }

    if not dry_run and args.get("confirm") is not True:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "deleting a device cannot be undone by this build, because insert_device needs Live "
            "12.3; pass confirm: true to delete it",
        )
    if dry_run:
        return {
            "dry_run": True, "deleted": [row], "count": 1,
            "reversible": False, "requires_confirm": True,
        }

    remover = _attr(track, "delete_device", None)
    if not callable(remover):
        raise ScriptError("UNSUPPORTED", "this Live build cannot delete a device")
    before = len(_devices(track))
    try:
        remover(device_index)
    except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
        raise ScriptError("LIVE_ERROR", "Live refused the delete: %s" % (exc,))
    after = len(_devices(track))
    if after != before - 1:
        raise ScriptError(
            "LIVE_ERROR",
            "the chain held %d devices before the delete and %d after" % (before, after),
        )
    return {
        "dry_run": False, "deleted": [row], "count": 1,
        "reversible": False, "requires_confirm": True,
    }


@command("devices.browse_presets")
def browse_presets(args, song):
    check_args(args, allowed=("device", "category", "offset", "limit"))
    device = args.get("device")
    if device is not None and (not isinstance(device, str) or not device.strip()):
        raise ScriptError("BAD_ARGS", "device must be a non-empty string when given")
    category = args.get("category")
    if category is not None and category not in PRESET_CATEGORIES:
        raise ScriptError(
            "BAD_ARGS",
            "category must be one of %s" % ", ".join(PRESET_CATEGORIES),
        )
    offset = args.get("offset", 0)
    limit = args.get("limit", 50)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ScriptError("BAD_ARGS", "offset must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > MAX_LIMIT:
        raise ScriptError("BAD_ARGS", "limit must be an integer from 1 to %d" % MAX_LIMIT)

    browser = _browser(song)
    wanted = device.strip().lower() if device else None
    searched, folders, missing, problems = [], [], [], []
    seen = 0
    for name in ((category,) if category else PRESET_CATEGORIES):
        searched.append(name)
        try:
            root = getattr(browser, name)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            missing.append({"category": name, "reason": str(exc)})
            continue
        if root is None:
            missing.append({"category": name, "reason": "this Live build does not expose it"})
            continue
        try:
            children = _children(root)
        except ScriptError as exc:
            missing.append({"category": name, "reason": str(exc)})
            continue
        for child in children:
            label = str(_attr(child, "name", "") or "")
            seen += 1
            if seen > MAX_SCAN:
                problems.append("stopped after %d preset folders" % MAX_SCAN)
                break
            if wanted is not None and label.lower() != wanted:
                continue
            # Live marks a device's preset folder with is_folder False while still giving it
            # children, so a name match must not require is_folder. Requiring it reported EQ Eight
            # as missing on a real browser that holds it.
            folders.append((name, label, child))
        if problems:
            break

    if wanted is not None and len(folders) > 1:
        raise ScriptError(
            "AMBIGUOUS_REF",
            "%d preset folders are named %r (%s); pass category to choose one"
            % (len(folders), device.strip(), ", ".join(name for name, _, _ in folders)),
        )
    if wanted is not None and not folders:
        raise ScriptError(
            "NOT_FOUND",
            "no preset folder named %r under %s (%d folders read)"
            % (device.strip(), ", ".join(searched), seen),
        )

    if wanted is not None:
        rows = []
        for name, label, item in folders:
            try:
                children = _children(item)
            except ScriptError as exc:
                rows.append({
                    "category": name, "folder": label, "name": "", "is_folder": False,
                    "is_loadable": False, "uri": "", "reason": str(exc),
                })
                continue
            for child in children:
                row = _item_row(child)
                row.update({"category": name, "folder": label})
                rows.append(row)
        page = rows[offset:offset + limit]
        total = len(rows)
    else:
        # child_count costs one browser read per folder, so only the page pays it.
        page = []
        for name, label, item in folders[offset:offset + limit]:
            row = _item_row(item)
            try:
                row["child_count"] = len(_children(item))
            except ScriptError as exc:
                row["child_count"] = None
                row["reason"] = str(exc)
            row.update({"category": name, "folder": label})
            page.append(row)
        total = len(folders)

    next_offset = offset + len(page)
    return {
        "device": device,
        "categories": searched,
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset if next_offset < total else None,
        "missing": missing,
        "notes": problems,
    }


@command("devices.read_parameters")
def read_parameters(args, song):
    """List one device's parameters, paged, with the exact names a write needs.

    ``devices.set_parameter`` takes a parameter by name, which is only usable if the caller can see
    the names; without this read, finding "Stereo Width" means probing indexes until the refusals
    spell it out.
    """
    check_args(
        args,
        allowed=("track", "track_index", "device", "device_index", "offset", "limit"),
    )
    offset = args.get("offset", 0)
    limit = args.get("limit", 64)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ScriptError("BAD_ARGS", "offset must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > MAX_LIMIT:
        raise ScriptError("BAD_ARGS", "limit must be an integer from 1 to %d" % (MAX_LIMIT,))

    track_index, track = _track(song, args)
    device_index, device = _device(track, args)
    parameters = _parameters(device)
    page = parameters[offset:offset + limit]
    items = []
    for position, parameter in enumerate(page, start=offset):
        value = float(_attr(parameter, "value", 0.0) or 0.0)
        enabled = _attr(parameter, "is_enabled", True)
        items.append({
            "index": position,
            "name": str(_attr(parameter, "name", "") or ""),
            "value": value,
            "display": _display(parameter, value),
            "min": _attr(parameter, "min", None),
            "max": _attr(parameter, "max", None),
            "quantised": bool(_attr(parameter, "is_quantized", False)),
            "enabled": True if enabled is None else bool(enabled),
        })
    next_offset = offset + len(items)
    return {
        "track": str(_attr(track, "name", "") or ""),
        "track_index": track_index,
        "device": str(_attr(device, "name", "") or ""),
        "device_index": device_index,
        "class": str(_attr(device, "class_name", "") or ""),
        "items": items,
        "total": len(parameters),
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset if next_offset < len(parameters) else None,
    }

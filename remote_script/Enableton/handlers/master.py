"""The master fader.

One write, and it is the one the mix reports cannot read: the snapshot carries the master device
chain but not its fader, so `mix_levels_report` names the master as unmeasured. The fader lives on
`song.master_track.mixer_device.volume`, outside `tracks` and `return_tracks`, and is normalised
0..1 exactly like a track fader.

The payload is identical in dry-run and apply modes. The executor compares the applied trace with
the preflight, so a field that appears only when applying would make every apply fail its own
preflight, and a read-back that disagrees with the request is a Live error rather than a rounding.
"""

from __future__ import annotations

import math

from ..dispatch import check_args, command
from ..errors import ScriptError


def _attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _master(song):
    master = _attr(song, "master_track", None)
    if master is None:
        raise ScriptError("UNSUPPORTED", "this Live build exposes no master track")
    mixer = _attr(master, "mixer_device", None)
    parameter = _attr(mixer, "volume", None) if mixer is not None else None
    return master, parameter


def _read(master, parameter):
    if parameter is not None:
        value = _attr(parameter, "value", None)
    else:
        value = _attr(master, "volume", None)
    if value is None:
        raise ScriptError("UNSUPPORTED", "the master track exposes no readable volume")
    return float(value)


def _range(parameter):
    low = _attr(parameter, "min", 0.0) if parameter is not None else 0.0
    high = _attr(parameter, "max", 1.0) if parameter is not None else 1.0
    if not isinstance(low, (int, float)) or isinstance(low, bool):
        low = 0.0
    if not isinstance(high, (int, float)) or isinstance(high, bool):
        high = 1.0
    return float(low), float(high)


def _display(parameter, value):
    if parameter is None:
        return None
    formatter = _attr(parameter, "str_for_value", None)
    if not callable(formatter):
        return None
    try:
        return str(formatter(value))
    except Exception:
        return None


def _write(master, parameter, value):
    if parameter is not None:
        try:
            parameter.value = value
        except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
            raise ScriptError(
                "UNSUPPORTED", "this Live build refused the master fader write: %s" % (exc,)
            )
    else:
        try:
            master.volume = value
        except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
            raise ScriptError(
                "UNSUPPORTED", "this Live build refused the master fader write: %s" % (exc,)
            )
    read_back = _read(master, parameter)
    if abs(read_back - value) > 1e-6 * max(1.0, abs(value)):
        raise ScriptError(
            "LIVE_ERROR",
            "Live read back %s after being asked for %s on the master fader"
            % (read_back, value),
        )
    return read_back


def _value(args):
    raw = args.get("value")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ScriptError("BAD_ARGS", "value must be a number from 0 to 1")
    value = float(raw)
    if not math.isfinite(value):
        raise ScriptError("BAD_ARGS", "value must be a finite number from 0 to 1")
    return value


@command("master.set_gain")
def set_gain(args, song):
    check_args(args, allowed=("value", "dry_run", "restore"))
    dry_run = bool(args.get("dry_run", True))
    master, parameter = _master(song)

    restore = args.get("restore")
    if restore is not None:
        if "value" in args:
            raise ScriptError("BAD_ARGS", "restore cannot be combined with value")
        if not isinstance(restore, list) or not restore:
            raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
        changes = []
        for entry in reversed(restore):
            if not isinstance(entry, dict):
                raise ScriptError("BAD_ARGS", "restore entries must be objects")
            try:
                value = float(entry["value"])
            except (KeyError, TypeError, ValueError):
                raise ScriptError("BAD_ARGS", "restore entries need value")
            low, high = _range(parameter)
            if value < low - 1e-9 or value > high + 1e-9:
                raise ScriptError(
                    "PRECONDITION_FAILED",
                    "restore value %s is outside the master fader's range %s..%s"
                    % (value, low, high),
                )
            current = _read(master, parameter)
            changes.append({
                "from": round(current, 4),
                "to": round(value, 4),
                "display_from": _display(parameter, current),
                "display_to": _display(parameter, value),
            })
            if not dry_run:
                _write(master, parameter, value)
        return {
            "dry_run": dry_run,
            "restored": len(changes),
            "changes": changes,
            "missing": [],
        }

    if "value" not in args:
        raise ScriptError("BAD_ARGS", "missing argument(s): value")
    value = _value(args)
    low, high = _range(parameter)
    if value < low - 1e-9 or value > high + 1e-9:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "value %s is outside the master fader's range %s..%s" % (value, low, high),
        )

    current = _read(master, parameter)
    change = {
        "from": round(current, 4),
        "to": round(value, 4),
        "display_from": _display(parameter, current),
        "display_to": _display(parameter, value),
    }
    if not dry_run:
        _write(master, parameter, value)
    return {"dry_run": dry_run, "changes": [change], "undo": [{"value": current}]}

"""Mix snapshots: the whole balance, kept outside the Set.

A mix is a state, not a file: faders, pans, sends, mutes and solos across every track and return,
plus the master fader the snapshot cannot see. `mix.snapshot_save` captures that state and writes a
small JSON file beside the plans, so a later process can restore it; `mix.snapshot_restore` applies
a saved snapshot, or its own undo token, field by field.

Two safety rules shape the code:

- A restore is refused, with nothing written, when the Set no longer matches the snapshot's track
  names at the same indexes. Index-only matching would quietly move the vocal's fader because two
  tracks were reordered, which is worse than refusing.
- The restore preflights every target before its first write, and a write that fails reverts the
  fields this call already changed. A failed restore must not leave half a mix behind.

The payload is identical in dry-run and apply modes because the executor compares an applied trace
with its preflight.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from ..dispatch import check_args, command
from ..errors import ScriptError

SNAPSHOT_RE = re.compile(r"^m_[0-9a-f]{8}$")
NUMBER_TOLERANCE = 1e-6
FIELDS = ("volume", "pan", "mute", "solo", "send")


def _root():
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "Enableton" / "mix"
    return Path.home() / ".enableton" / "mix"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _param(track, name):
    """The mixer parameter for ``name``, or ``None`` on a backend that exposes a plain attribute."""
    mixer = getattr(track, "mixer_device", None)
    if mixer is None:
        return None
    parameter = getattr(mixer, name, None)
    if parameter is None or getattr(parameter, "value", None) is None:
        return None
    return parameter


def _read_number(track, name, fallback):
    """Read a normalised value, or raise ``ValueError`` rather than inventing a zero."""
    parameter = _param(track, name)
    if parameter is not None:
        return float(parameter.value), parameter
    value = getattr(track, fallback, None)
    if value is None:
        raise ValueError("this track exposes no %s" % (name,))
    return float(value), None


def _display(parameter, value):
    if parameter is None:
        return None
    formatter = getattr(parameter, "str_for_value", None)
    if not callable(formatter):
        return None
    try:
        return str(formatter(value))
    except Exception:
        return None


def _range(parameter):
    if parameter is None:
        return 0.0, 1.0
    low = getattr(parameter, "min", 0.0)
    high = getattr(parameter, "max", 1.0)
    if not isinstance(low, (int, float)) or isinstance(low, bool):
        low = 0.0
    if not isinstance(high, (int, float)) or isinstance(high, bool):
        high = 1.0
    return float(low), float(high)


def _send_params(track):
    mixer = getattr(track, "mixer_device", None)
    sends = getattr(mixer, "sends", None) if mixer is not None else None
    if sends is None:
        sends = getattr(track, "sends", None)
    if sends is None:
        raise ValueError("this track exposes no send parameters")
    return list(sends)


def _send_names(song, track, count):
    returns = list(getattr(song, "return_tracks", []) or [])
    names = [str(getattr(item, "name", "") or "") for item in returns]
    params = []
    try:
        params = _send_params(track)
    except ValueError:
        params = []
    return [
        names[index] if index < len(names) and names[index]
        else str(getattr(params[index], "name", "") or "") if index < len(params)
        else "Send %d" % (index + 1)
        for index in range(count)
    ]


def _capture_track(song, kind, index, track, unreadable):
    row = {
        "kind": kind,
        "index": index,
        "name": str(getattr(track, "name", "") or ""),
        "volume": None,
        "volume_display": None,
        "pan": None,
        "pan_display": None,
        "sends": [],
        "mute": None,
        "solo": None,
    }
    for field, source, fallback in (("volume", "volume", "volume"), ("pan", "panning", "pan")):
        try:
            value, parameter = _read_number(track, source, fallback)
        except (ValueError, TypeError) as exc:
            unreadable.append("%s %d %s: %s" % (kind, index, field, exc))
            continue
        row[field] = value
        row[field + "_display"] = _display(parameter, value)
    try:
        params = _send_params(track)
    except ValueError as exc:
        unreadable.append("%s %d sends: %s" % (kind, index, exc))
        params = []
    names = _send_names(song, track, len(params))
    for send_index, parameter in enumerate(params):
        value = getattr(parameter, "value", None)
        if value is None:
            unreadable.append("%s %d send %d: no value" % (kind, index, send_index))
            continue
        row["sends"].append({
            "index": send_index,
            "name": names[send_index],
            "value": float(value),
            "display": _display(parameter, value),
        })
    for field in ("mute", "solo"):
        value = getattr(track, field, None)
        if value is None:
            unreadable.append("%s %d %s: no value" % (kind, index, field))
            continue
        row[field] = bool(value)
    return row


def _capture_master(song, unreadable):
    master = getattr(song, "master_track", None)
    if master is None:
        return None, "this Live build exposes no master track"
    try:
        value, parameter = _read_number(master, "volume", "volume")
    except (ValueError, TypeError) as exc:
        unreadable.append("master volume: %s" % (exc,))
        return None, str(exc)
    return {
        "name": str(getattr(master, "name", "") or "Master"),
        "volume": value,
        "volume_display": _display(parameter, value),
    }, None


def _capture(song):
    tracks = list(getattr(song, "tracks", []) or [])
    returns = list(getattr(song, "return_tracks", []) or [])
    unreadable = []
    rows = []
    for kind, pool in (("track", tracks), ("return", returns)):
        for index, track in enumerate(pool):
            rows.append(_capture_track(song, kind, index, track, unreadable))
    master, master_reason = _capture_master(song, unreadable)
    return {
        "tracks": rows,
        "master": master,
        "master_reason": master_reason,
        "unreadable": unreadable,
        "counts": {
            "tracks": len(tracks),
            "returns": len(returns),
            "sends": sum(len(row["sends"]) for row in rows),
            "fields": sum(
                1 for row in rows for field in ("volume", "pan", "mute", "solo")
                if row[field] is not None
            ) + (1 if master is not None else 0),
        },
    }


def _allocate():
    for _ in range(20):
        candidate = "m_" + secrets.token_hex(4)
        if not (_root() / (candidate + ".json")).exists():
            return candidate
    raise ScriptError("INTERNAL", "could not allocate a mix snapshot id")


@command("mix.snapshot_save")
def snapshot_save(args, song):
    check_args(args, allowed=())
    captured = _capture(song)
    snapshot_id = _allocate()
    payload = {"snapshot_id": snapshot_id, "created_at": _now_iso()}
    payload.update(captured)

    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / (snapshot_id + ".json")
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(temporary), str(path))
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise ScriptError("INTERNAL", "could not store the mix snapshot: %s" % (exc,))

    return {
        "snapshot_id": snapshot_id,
        "created_at": payload["created_at"],
        "path": str(path),
        "tracks": captured["tracks"],
        "master": captured["master"],
        "master_reason": captured["master_reason"],
        "counts": captured["counts"],
        "unreadable": captured["unreadable"],
    }


def _load(snapshot_id):
    if not isinstance(snapshot_id, str) or not SNAPSHOT_RE.match(snapshot_id):
        raise ScriptError("BAD_ARGS", "snapshot_id must look like 'm_0123abcd'")
    path = _root() / (snapshot_id + ".json")
    if not path.is_file():
        raise ScriptError("NOT_FOUND", "no mix snapshot with id %r" % (snapshot_id,))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScriptError("INTERNAL", "could not read mix snapshot %r: %s" % (snapshot_id, exc))
    if not isinstance(payload, dict) or payload.get("snapshot_id") != snapshot_id:
        raise ScriptError("INTERNAL", "mix snapshot %r is malformed" % (snapshot_id,))
    if not isinstance(payload.get("tracks"), list):
        raise ScriptError("INTERNAL", "mix snapshot %r has no tracks" % (snapshot_id,))
    return payload


def _entries_from_snapshot(snapshot):
    entries = []
    for row in snapshot.get("tracks") or []:
        if not isinstance(row, dict):
            raise ScriptError("INTERNAL", "mix snapshot has a malformed track row")
        base = {
            "kind": row.get("kind", "track"),
            "index": row.get("index"),
            "name": row.get("name"),
        }
        for field in ("volume", "pan", "mute", "solo"):
            if row.get(field) is not None:
                entries.append(dict(base, field=field, value=row[field]))
        for send in row.get("sends") or []:
            if isinstance(send, dict) and send.get("value") is not None:
                entries.append(dict(
                    base, field="send", send_index=send.get("index"), value=send["value"],
                    send=send.get("name"),
                ))
    master = snapshot.get("master")
    if isinstance(master, dict) and master.get("volume") is not None:
        entries.append({
            "kind": "master", "index": None, "name": master.get("name") or "Master",
            "field": "volume", "value": master["volume"],
        })
    return entries


def _entries_from_undo(restore):
    if not isinstance(restore, list) or not restore:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    entries = []
    for entry in restore:
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        field = entry.get("field")
        if field not in FIELDS:
            raise ScriptError("BAD_ARGS", "restore field must be one of %s" % ", ".join(FIELDS))
        value = entry.get("value")
        if field in ("mute", "solo"):
            if not isinstance(value, bool):
                raise ScriptError("BAD_ARGS", "restore value for %s must be true or false" % (field,))
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScriptError("BAD_ARGS", "restore value for %s must be a number" % (field,))
        row = {
            "kind": entry.get("kind"),
            "index": entry.get("index"),
            "name": entry.get("name"),
            "field": field,
            "value": entry.get("value"),
            "send_index": entry.get("send_index"),
        }
        if field == "send" and row["send_index"] is None:
            raise ScriptError("BAD_ARGS", "restore entries for a send need send_index")
        entries.append(row)
    return entries


def _pool(song, kind):
    if kind == "track":
        return list(getattr(song, "tracks", []) or [])
    if kind == "return":
        return list(getattr(song, "return_tracks", []) or [])
    raise ScriptError("BAD_ARGS", "restore kind must be track, return or master")


def _number_value(field, raw, parameter=None):
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("%s value must be a number" % (field,))
    value = float(raw)
    low, high = _range(parameter)
    if value < low - 1e-9 or value > high + 1e-9:
        raise ValueError("%s value %s is outside %s..%s" % (field, value, low, high))
    return value


def _resolve(song, entries):
    """Turn restore entries into get/set pairs, refusing the whole list on the first mismatch."""
    ops, problems = [], []
    for entry in entries:
        kind = entry.get("kind")
        label = "%s %s" % (kind, entry.get("index"))
        try:
            if kind == "master":
                master = getattr(song, "master_track", None)
                if master is None:
                    problems.append("%s: this Live build exposes no master track" % (label,))
                    continue
                if entry["field"] != "volume":
                    problems.append("%s: the master track has no %s" % (label, entry["field"]))
                    continue
                try:
                    current, parameter = _read_number(master, "volume", "volume")
                except (ValueError, TypeError) as exc:
                    problems.append("%s: %s" % (label, exc))
                    continue
                target = _number_value("volume", entry["value"], parameter)

                def getter(_master=master, _parameter=parameter):
                    return _read_number(_master, "volume", "volume")[0]

                def setter(value, _master=master, _parameter=parameter):
                    _write_number(_master, "volume", "volume", value)

                ops.append({
                    "kind": "master", "index": None,
                    "name": str(getattr(master, "name", "") or "Master"),
                    "field": "volume", "send_index": None, "send": None,
                    "from": current, "value": target, "parameter": parameter,
                    "get": getter, "set": setter,
                })
                continue

            pool = _pool(song, kind)
            index = entry.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                problems.append("%s: index must be an integer" % (label,))
                continue
            if index < 0 or index >= len(pool):
                problems.append(
                    "%s: this Set has %d %s(s); the snapshot has one at index %d"
                    % (label, len(pool), kind, index)
                )
                continue
            track = pool[index]
            current_name = str(getattr(track, "name", "") or "")
            wanted_name = entry.get("name")
            if wanted_name is not None and str(wanted_name) != current_name:
                problems.append(
                    "%s: the snapshot says %r, the Set says %r"
                    % (label, str(wanted_name), current_name)
                )
                continue

            field = entry["field"]
            if field == "send":
                send_index = entry.get("send_index")
                if isinstance(send_index, bool) or not isinstance(send_index, int) or send_index < 0:
                    problems.append("%s: send_index must be a non-negative integer" % (label,))
                    continue
                try:
                    params = _send_params(track)
                except ValueError as exc:
                    problems.append("%s: %s" % (label, exc))
                    continue
                if send_index >= len(params):
                    problems.append(
                        "%s: the snapshot sends to %d return(s), this track has %d"
                        % (label, send_index + 1, len(params))
                    )
                    continue
                parameter = params[send_index]
                current = float(getattr(parameter, "value", 0.0) or 0.0)
                target = _number_value("send", entry["value"], parameter)
                send_name = entry.get("send")

                def getter(_p=parameter):
                    return float(getattr(_p, "value", 0.0) or 0.0)

                def setter(value, _p=parameter):
                    _write_number(_p, None, None, value)

                ops.append({
                    "kind": kind, "index": index, "name": current_name,
                    "field": "send", "send_index": send_index, "send": send_name,
                    "from": current, "value": target, "parameter": parameter,
                    "get": getter, "set": setter,
                })
                continue

            if field in ("mute", "solo"):
                if not isinstance(entry["value"], bool):
                    problems.append("%s: %s value must be true or false" % (label, field))
                    continue
                current = bool(getattr(track, field, False))
                target = bool(entry["value"])

                def getter(_t=track, _f=field):
                    return bool(getattr(_t, _f, False))

                def setter(value, _t=track, _f=field):
                    try:
                        setattr(_t, _f, bool(value))
                    except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
                        raise ScriptError(
                            "UNSUPPORTED", "this Live build refused %s: %s" % (_f, exc)
                        )

                ops.append({
                    "kind": kind, "index": index, "name": current_name,
                    "field": field, "send_index": None, "send": None,
                    "from": current, "value": target, "parameter": None,
                    "get": getter, "set": setter,
                })
                continue

            if field not in ("volume", "pan"):
                problems.append("%s: %s cannot be restored" % (label, field))
                continue
            source, fallback = ("volume", "volume") if field == "volume" else ("panning", "pan")
            try:
                current, parameter = _read_number(track, source, fallback)
            except (ValueError, TypeError) as exc:
                problems.append("%s: %s" % (label, exc))
                continue
            try:
                target = _number_value(field, entry["value"], parameter)
            except ValueError as exc:
                problems.append("%s: %s" % (label, exc))
                continue

            def getter(_t=track, _s=source, _f=fallback):
                return _read_number(_t, _s, _f)[0]

            def setter(value, _t=track, _s=source, _f=fallback):
                _write_number(_t, _s, _f, value)

            ops.append({
                "kind": kind, "index": index, "name": current_name,
                "field": field, "send_index": None, "send": None,
                "from": current, "value": target, "parameter": parameter,
                "get": getter, "set": setter,
            })
        except ScriptError:
            raise
        except Exception as exc:  # noqa: BLE001 - report, never guess
            problems.append("%s: %s" % (label, exc))
    return ops, problems


def _write_number(target, name, fallback, value):
    """Write one mixer parameter, falling back to a plain attribute on the fake backend."""
    parameter = target if name is None else _param(target, name)
    try:
        if parameter is not None:
            parameter.value = value
        elif name is not None:
            setattr(target, fallback, value)
        else:
            raise AttributeError("no writable parameter")
    except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
        raise ScriptError(
            "UNSUPPORTED",
            "this Live build refused the %s write: %s" % (fallback or "send", exc),
        )


def _same(current, target):
    if isinstance(current, bool) or isinstance(target, bool):
        return bool(current) == bool(target)
    return abs(float(current) - float(target)) <= NUMBER_TOLERANCE * max(1.0, abs(float(target)))


def _change_row(op, current, target):
    row = {
        "kind": op["kind"],
        "index": op["index"],
        "name": op["name"],
        "field": op["field"],
        "from": current if isinstance(current, bool) else float(current),
        "to": target if isinstance(target, bool) else float(target),
        "display_from": None,
        "display_to": None,
    }
    if op["field"] == "send":
        row["send_index"] = op["send_index"]
        row["send"] = op["send"]
    if not isinstance(current, bool):
        row["display_from"] = _display(op["parameter"], float(current))
        row["display_to"] = _display(op["parameter"], float(target))
    return row


def _undo_row(op, current):
    row = {
        "kind": op["kind"],
        "index": op["index"],
        "name": op["name"],
        "field": op["field"],
        "value": current if isinstance(current, bool) else float(current),
    }
    if op["field"] == "send":
        row["send_index"] = op["send_index"]
    return row


@command("mix.snapshot_restore")
def snapshot_restore(args, song):
    check_args(args, allowed=("snapshot_id", "restore", "dry_run"))
    dry_run = bool(args.get("dry_run", True))
    has_id, has_restore = "snapshot_id" in args, "restore" in args
    if has_id == has_restore:
        raise ScriptError("BAD_ARGS", "give either snapshot_id or restore, not both")

    if has_id:
        snapshot = _load(args["snapshot_id"])
        entries = _entries_from_snapshot(snapshot)
        unreadable = [str(item) for item in snapshot.get("unreadable") or []]
        snapshot_id = snapshot["snapshot_id"]
    else:
        entries = _entries_from_undo(args["restore"])
        unreadable = []
        snapshot_id = None

    ops, problems = _resolve(song, entries)
    if problems:
        shown = "; ".join(problems[:5])
        more = "" if len(problems) <= 5 else " (and %d more)" % (len(problems) - 5)
        raise ScriptError(
            "PRECONDITION_FAILED",
            "this Set no longer matches the snapshot; nothing was written: %s%s"
            % (shown, more),
            {"mismatched": problems},
        )

    changes, undo, pending = [], [], []
    for op in ops:
        current = op["get"]()
        undo.append(_undo_row(op, current))
        if _same(current, op["value"]):
            continue
        changes.append(_change_row(op, current, op["value"]))
        pending.append((op, current))

    reverted = 0
    if not dry_run and pending:
        applied = []
        try:
            for op, current in pending:
                op["set"](op["value"])
                applied.append((op, current))
                read_back = op["get"]()
                if not _same(read_back, op["value"]):
                    raise ScriptError(
                        "LIVE_ERROR",
                        "Live read back %s after being asked for %s on %s %s"
                        % (read_back, op["value"], op["kind"], op["field"]),
                    )
        except Exception as failure:  # noqa: BLE001 - the original failure is the answer
            for op, current in reversed(applied):
                try:
                    op["set"](current)
                    reverted += 1
                except Exception:  # noqa: BLE001 - the original failure is the answer
                    pass
            raise ScriptError(
                "LIVE_ERROR",
                "the restore failed after %d field(s) (%s); %d were reverted"
                % (len(applied), failure, reverted),
                {"reverted": reverted, "attempted": len(applied), "changes": changes},
            )

    return {
        "dry_run": dry_run,
        "snapshot_id": snapshot_id,
        "compared": len(ops),
        "changes": changes,
        "undo": undo,
        "unreadable": unreadable,
        "reverted": reverted,
    }

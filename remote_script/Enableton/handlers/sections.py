"""Locator writes, and the scenes built from them.

Live's LOM has no ``create_locator(time)``. A cue is toggled at the playhead with
``Song.set_or_delete_cue()``, which means the same call creates *and* deletes: writing a cue where
one already exists would silently remove the user's marker. Every write here therefore reads the
locator list first, refuses an occupied beat, moves the playhead only to a beat it is about to
write, and puts the playhead back afterwards.

``Locator.time`` has no setter on Live 12.2.5, so moving a marker is a delete plus a create. This
module does not offer a move, because it cannot do one.
"""

from __future__ import annotations

from ..dispatch import check_args, command
from ..errors import ScriptError
from .structure import _locator_source


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


def _objects(song):
    raw, attribute, reason = _locator_source(song)
    if attribute is None:
        raise ScriptError(
            "UNSUPPORTED",
            "this Live build exposes no readable locators: %s"
            % (reason or "the read returned nothing"),
        )
    return list(raw)


def _rows(song):
    return [
        {
            "index": index,
            "name": str(_attr(locator, "name", "") or ""),
            "time": float(_attr(locator, "time", 0.0) or 0.0),
        }
        for index, locator in enumerate(_objects(song))
    ]


def _bar_of(time, beats_per_bar):
    return round(float(time) / beats_per_bar + 1.0, 4)


def _toggle(song):
    toggle = getattr(song, "set_or_delete_cue", None)
    if not callable(toggle):
        raise ScriptError(
            "UNSUPPORTED", "this Live build cannot create or delete a cue point"
        )
    toggle()


def _seek(song, beat):
    try:
        song.current_song_time = float(beat)
    except Exception as exc:  # noqa: BLE001 - Live's own reason is the answer
        raise ScriptError(
            "UNSUPPORTED", "this Live build cannot move the playhead to write a cue: %s" % (exc,)
        )


def _playhead(song):
    value = _attr(song, "current_song_time", None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _locator_at(song, beat):
    for locator in _objects(song):
        if abs(float(_attr(locator, "time", 0.0) or 0.0) - float(beat)) <= 1e-6:
            return locator
    return None


def _section_entries(value):
    if not isinstance(value, list) or not value:
        raise ScriptError("BAD_ARGS", "sections must be a non-empty list")
    if len(value) > 64:
        raise ScriptError("BAD_ARGS", "sections may hold at most 64 entries")
    out = []
    for position, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "section %d must be an object" % position)
        unknown = sorted(set(entry) - {"name", "bar"})
        if unknown:
            raise ScriptError(
                "BAD_ARGS",
                "section %d has unknown field(s): %s" % (position, ", ".join(unknown)),
            )
        name = entry.get("name")
        bar = entry.get("bar")
        if not isinstance(name, str) or not name.strip():
            raise ScriptError("BAD_ARGS", "section %d needs a non-empty name" % position)
        if isinstance(bar, bool) or not isinstance(bar, (int, float)):
            raise ScriptError("BAD_ARGS", "section %d needs a numeric bar" % position)
        if float(bar) < 1:
            raise ScriptError("BAD_ARGS", "section %d bar must be >= 1" % position)
        out.append({"name": name.strip(), "bar": float(bar)})
    return out


@command("sections.create_locators")
def create_locators(args, song):
    check_args(args, allowed=("sections", "dry_run", "restore"))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if "sections" in args:
            raise ScriptError("BAD_ARGS", "restore cannot be combined with sections")
        return _restore_created(args, song, dry_run)

    requested = _section_entries(args.get("sections"))
    beats_per_bar = _beats_per_bar(song)
    existing = _objects(song)

    planned, seen = [], set()
    for entry in requested:
        beat = round((entry["bar"] - 1.0) * beats_per_bar, 6)
        if beat in seen:
            raise ScriptError("BAD_ARGS", "two sections asked for bar %s" % (entry["bar"],))
        seen.add(beat)
        for locator in existing:
            other = float(_attr(locator, "time", 0.0) or 0.0)
            if abs(other - beat) <= 1e-6:
                raise ScriptError(
                    "PRECONDITION_FAILED",
                    "a locator already exists at bar %s (%r); delete it first"
                    % (entry["bar"], str(_attr(locator, "name", "") or "")),
                )
        planned.append({"name": entry["name"], "bar": entry["bar"], "time": beat})

    if dry_run:
        return {
            "dry_run": True,
            "created": planned,
            "skipped": [],
            "undo": [],
            "playhead_restored": True,
        }

    original = _playhead(song)
    created, undo = [], []
    try:
        for item in planned:
            _seek(song, item["time"])
            _toggle(song)
            locator = _locator_at(song, item["time"])
            if locator is None:
                raise ScriptError(
                    "LIVE_ERROR", "Live did not create a cue at bar %s" % (item["bar"],)
                )
            try:
                locator.name = item["name"]
            except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
                raise ScriptError(
                    "UNSUPPORTED", "this Live build cannot name a locator: %s" % (exc,)
                )
            created.append(dict(item))
            undo.append({"time": item["time"], "bar": item["bar"], "name": item["name"]})
    finally:
        if original is not None:
            try:
                song.current_song_time = original
            except Exception:
                pass

    return {
        "dry_run": False,
        "created": created,
        "skipped": [],
        "undo": undo,
        "playhead_restored": True,
    }


def _restore_created(args, song, dry_run):
    entries = args.get("restore")
    if not isinstance(entries, list) or not entries:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    beats_per_bar = _beats_per_bar(song)
    deleted, missing = [], []
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        try:
            time = float(entry["time"])
        except (KeyError, TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "restore entries need a time")
        locator = _locator_at(song, time)
        if locator is None:
            missing.append({"time": time, "bar": entry.get("bar")})
            continue
        name = str(_attr(locator, "name", "") or "")
        if not dry_run:
            _seek(song, time)
            _toggle(song)
        deleted.append({"time": time, "bar": _bar_of(time, beats_per_bar), "name": name})
    return {
        "dry_run": dry_run,
        "restored": len(deleted),
        "changes": deleted,
        "missing": missing,
    }


@command("sections.delete")
def delete(args, song):
    check_args(args, allowed=("names", "bars", "all", "dry_run", "restore"))
    dry_run = bool(args.get("dry_run", True))
    if args.get("restore") is not None:
        if any(key in args for key in ("names", "bars", "all")):
            raise ScriptError("BAD_ARGS", "restore cannot be combined with a selection")
        return _restore_deleted(args, song, dry_run)

    selectors = [key for key in ("names", "bars", "all") if key in args]
    if len(selectors) != 1:
        raise ScriptError("BAD_ARGS", "give exactly one of names, bars or all")

    beats_per_bar = _beats_per_bar(song)
    rows = _rows(song)
    if not rows:
        raise ScriptError("NOT_FOUND", "this Set has no locators")

    if "all" in args:
        if args.get("all") is not True:
            raise ScriptError("BAD_ARGS", "all must be true when given")
        selected = list(rows)
    elif "names" in args:
        wanted = args.get("names")
        if not isinstance(wanted, list) or not wanted:
            raise ScriptError("BAD_ARGS", "names must be a non-empty list")
        if not all(isinstance(name, str) and name for name in wanted):
            raise ScriptError("BAD_ARGS", "names must be non-empty strings")
        selected = []
        for name in wanted:
            matches = [row for row in rows if row["name"] == name]
            if not matches:
                raise ScriptError("NOT_FOUND", "no locator named %r" % (name,))
            if len(matches) > 1:
                raise ScriptError(
                    "AMBIGUOUS_REF",
                    "%d locators are named %r; select by bar instead" % (len(matches), name),
                )
            selected.extend(matches)
    else:
        bars = args.get("bars")
        if not isinstance(bars, list) or not bars:
            raise ScriptError("BAD_ARGS", "bars must be a non-empty list")
        selected = []
        for bar in bars:
            if isinstance(bar, bool) or not isinstance(bar, (int, float)):
                raise ScriptError("BAD_ARGS", "bars must be numbers")
            beat = (float(bar) - 1.0) * beats_per_bar
            matches = [row for row in rows if abs(row["time"] - beat) <= 1e-6]
            if not matches:
                raise ScriptError("NOT_FOUND", "no locator at bar %s" % (bar,))
            selected.extend(matches)

    seen, changes, undo = set(), [], []
    original = _playhead(song)
    try:
        for row in sorted(selected, key=lambda item: item["time"], reverse=True):
            key = round(row["time"], 6)
            if key in seen:
                continue
            seen.add(key)
            change = {
                "name": row["name"],
                "bar": _bar_of(row["time"], beats_per_bar),
                "time": key,
            }
            changes.append(change)
            undo.append(dict(change))
            if dry_run:
                continue
            _seek(song, row["time"])
            _toggle(song)
            if _locator_at(song, row["time"]) is not None:
                raise ScriptError(
                    "LIVE_ERROR", "Live did not delete the locator at bar %s" % (change["bar"],)
                )
    finally:
        if not dry_run and original is not None:
            try:
                song.current_song_time = original
            except Exception:
                pass

    return {
        "dry_run": dry_run,
        "changes": changes,
        "undo": undo,
        "deleted": 0 if dry_run else len(changes),
    }


def _restore_deleted(args, song, dry_run):
    entries = args.get("restore")
    if not isinstance(entries, list) or not entries:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    beats_per_bar = _beats_per_bar(song)
    changes, missing = [], []
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        try:
            time = float(entry["time"])
        except (KeyError, TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "restore entries need a time")
        name = entry.get("name", "")
        if not isinstance(name, str):
            raise ScriptError("BAD_ARGS", "restore name must be a string")
        if _locator_at(song, time) is not None:
            missing.append({"time": time, "reason": "another locator occupies that beat"})
            continue
        changes.append({"time": time, "bar": _bar_of(time, beats_per_bar), "name": name})
        if dry_run:
            continue
        _seek(song, time)
        _toggle(song)
        locator = _locator_at(song, time)
        if locator is None:
            raise ScriptError(
                "LIVE_ERROR", "Live did not recreate the cue at beat %s" % (time,)
            )
        if name:
            try:
                locator.name = name
            except Exception as exc:  # noqa: BLE001 - Live's reason is the answer
                raise ScriptError(
                    "UNSUPPORTED", "this Live build cannot name a locator: %s" % (exc,)
                )

    return {
        "dry_run": dry_run,
        "restored": len(changes),
        "changes": changes,
        "missing": missing,
    }


@command("sections.scenes_from_sections")
def scenes_from_sections(args, song):
    check_args(args, allowed=("prefix", "dry_run", "restore"))
    dry_run = bool(args.get("dry_run", True))
    prefix = args.get("prefix", "")
    if not isinstance(prefix, str):
        raise ScriptError("BAD_ARGS", "prefix must be a string")

    if args.get("restore") is not None:
        if "prefix" in args:
            raise ScriptError("BAD_ARGS", "restore cannot be combined with prefix")
        return _restore_scenes(args, song, dry_run)

    rows = sorted(_rows(song), key=lambda row: row["time"])
    if not rows:
        raise ScriptError(
            "PRECONDITION_FAILED", "this Set has no locators to turn into scenes"
        )

    beats_per_bar = _beats_per_bar(song)
    existing = {
        str(_attr(scene, "name", "") or "") for scene in (_attr(song, "scenes", []) or [])
    }
    planned, skipped = [], []
    for row in rows:
        name = prefix + row["name"]
        if not name:
            skipped.append({"bar": _bar_of(row["time"], beats_per_bar), "reason": "unnamed locator"})
            continue
        if name in existing:
            skipped.append(
                {"bar": _bar_of(row["time"], beats_per_bar), "name": name,
                 "reason": "a scene with that name already exists"}
            )
            continue
        existing.add(name)
        planned.append({"name": name, "bar": _bar_of(row["time"], beats_per_bar)})

    if dry_run:
        return {"dry_run": True, "created": planned, "skipped": skipped, "undo": []}

    create = getattr(song, "create_scene", None)
    if not callable(create):
        raise ScriptError("UNSUPPORTED", "this Live build cannot create a scene")

    created, undo = [], []
    for item in planned:
        index = len(list(_attr(song, "scenes", []) or []))
        try:
            create(-1)
        except TypeError:
            create(index)
        scenes = list(_attr(song, "scenes", []) or [])
        if len(scenes) <= index:
            raise ScriptError(
                "LIVE_ERROR", "Live did not create a scene for %r" % (item["name"],)
            )
        scene = scenes[-1]
        try:
            scene.name = item["name"]
        except Exception as exc:  # noqa: BLE001 - Live's reason is the answer
            raise ScriptError("UNSUPPORTED", "this Live build cannot name a scene: %s" % (exc,))
        created.append({"name": item["name"], "index": len(scenes) - 1})
        undo.append({"index": len(scenes) - 1, "name": item["name"]})

    return {"dry_run": False, "created": created, "skipped": skipped, "undo": undo}


def _restore_scenes(args, song, dry_run):
    entries = args.get("restore")
    if not isinstance(entries, list) or not entries:
        raise ScriptError("BAD_ARGS", "restore must be a non-empty list")
    checked = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ScriptError("BAD_ARGS", "restore entries must be objects")
        try:
            index = int(entry["index"])
        except (KeyError, TypeError, ValueError):
            raise ScriptError("BAD_ARGS", "restore entries need an index")
        checked.append((index, entry.get("name")))

    delete = getattr(song, "delete_scene", None)
    if not callable(delete):
        raise ScriptError("UNSUPPORTED", "this Live build cannot delete a scene")

    changes, missing = [], []
    for index, wanted in sorted(checked, key=lambda pair: pair[0], reverse=True):
        scenes = list(_attr(song, "scenes", []) or [])
        if index < 0 or index >= len(scenes):
            missing.append({"index": index, "reason": "no scene at that index"})
            continue
        name = str(_attr(scenes[index], "name", "") or "")
        if wanted is not None and name != str(wanted):
            missing.append(
                {"index": index, "reason": "the scene at that index has a different name"}
            )
            continue
        if not dry_run:
            delete(index)
        changes.append({"index": index, "name": name})

    return {
        "dry_run": dry_run,
        "restored": len(changes),
        "changes": changes,
        "missing": missing,
    }

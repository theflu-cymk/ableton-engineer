"""Tool-facing access to the recipe store.

Recipes are JSON data, not Live state. These handlers never open the Live socket; the existing
``RecipeStore`` owns validation and atomic writes. A recipe compiles only into an escalation plan,
so every executable step still passes the same validation, preflight and transactional apply path.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .escalation import EscalationError, escalate, validate_steps
from .plans import PlanStore, PlanStoreError
from .protocol.codes import LiveError
from .recipe_fingerprint import compare_fingerprint, measure_snapshot
from .recipe_rhythm import RhythmCompileError, render_rhythm
from .recipe_store import RecipeStore, RecipeStoreError
from .recipe_validation import (
    MAX_MANUAL,
    MAX_STEPS,
    RecipeValidationError,
    validate_recipe,
)

MAX_COMPILE_DEPTH = 4


class RecipeCompileError(ValueError):
    """A recipe cannot become an executable plan without inventing capability."""


def default_store() -> RecipeStore:
    """The shipped package directory and the user's platform data directory."""
    shipped = Path(__file__).with_name("recipes")
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) / "Enableton" if appdata else Path.home() / ".enableton"
    return RecipeStore(shipped, root / "recipes")


def _only(args: Dict[str, Any], allowed: tuple[str, ...]) -> None:
    unknown = sorted(set(args) - set(allowed))
    if unknown:
        raise LiveError("BAD_ARGS", "unknown argument(s): %s" % ", ".join(unknown))


def _recipe_id(args: Dict[str, Any]) -> str:
    value = args.get("id")
    if not isinstance(value, str) or not value:
        raise LiveError("BAD_ARGS", "id must be a non-empty string")
    return value


def _store_recipe(store: RecipeStore, recipe_id: str) -> Dict[str, Any]:
    try:
        return store.show(recipe_id)
    except RecipeStoreError as exc:
        code = "NOT_FOUND" if str(exc).startswith("no recipe with id") else "BAD_ARGS"
        raise LiveError(code, str(exc)) from exc


def _ingredients_of(recipe: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = recipe.get("ingredients")
    if raw is None:
        raw = recipe.get("parts") or []
    return [dict(item) for item in raw]


def _ingredient_kind(ingredient: Dict[str, Any]) -> Optional[str]:
    kind = ingredient.get("kind")
    if kind is not None:
        return kind
    return "recipe" if ingredient.get("recipe") else None


def _manual_entries(recipe: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries = []
    for value in recipe.get("manual") or []:
        entry = dict(value)
        entry["when"] = entry.get("when", "before_verify")
        entry["status"] = "pending"
        entries.append(entry)
    return entries


RECIPE_KINDS = ("style", "rhythm", "workflow", "combination")


def _catalog_filter(args: Dict[str, Any], key: str) -> Optional[str]:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LiveError("BAD_ARGS", "%s must be a non-empty string" % key)
    return value.strip()


def list_recipes(
    args: Optional[Dict[str, Any]] = None,
    store: Optional[RecipeStore] = None,
) -> Dict[str, Any]:
    args = dict(args or {})
    _only(args, ("kind", "tag", "search", "runnable"))
    kind = _catalog_filter(args, "kind")
    if kind is not None and kind not in RECIPE_KINDS:
        raise LiveError(
            "BAD_ARGS", "kind must be one of: %s" % ", ".join(RECIPE_KINDS)
        )
    tag = _catalog_filter(args, "tag")
    search = _catalog_filter(args, "search")
    runnable = args.get("runnable", False)
    if not isinstance(runnable, bool):
        raise LiveError("BAD_ARGS", "runnable must be a boolean")

    store = store or default_store()
    try:
        rows = store.list()
    except RecipeStoreError as exc:
        raise LiveError("BAD_ARGS", str(exc)) from exc

    # A chooser has to know what it can actually run before the user picks a row. The catalog
    # computes that and tolerates one broken file, so a bad user recipe cannot hide the rest.
    try:
        details = {row["id"]: row for row in store.catalog()}
    except RecipeStoreError:
        details = {}
    for row in rows:
        extra = details.get(row["id"]) or {}
        row["compilable"] = bool(extra.get("compilable"))
        row["needs_target"] = bool(extra.get("needs_target"))
        row["bpm"] = extra.get("bpm")
        row["feel"] = extra.get("feel")
        row["tags"] = list(extra.get("tags") or [])
        row["track_refs"] = list(extra.get("track_refs") or [])

    needle = search.lower() if search is not None else None
    rows = [
        row for row in rows
        if (kind is None or row["kind"] == kind)
        and (tag is None or tag in row["tags"])
        and (
            needle is None
            or needle in row["id"].lower()
            or needle in row["name"].lower()
        )
        and (not runnable or row["compilable"])
    ]
    return {"recipes": rows, "count": len(rows)}


def show_recipe(
    args: Optional[Dict[str, Any]] = None,
    store: Optional[RecipeStore] = None,
) -> Dict[str, Any]:
    args = dict(args or {})
    _only(args, ("id",))
    recipe_id = _recipe_id(args)
    store = store or default_store()
    recipe = _store_recipe(store, recipe_id)
    source = "user" if (store.user_dir / f"{recipe_id}.json").is_file() else "shipped"
    result: Dict[str, Any] = {"recipe": recipe, "source": source}

    resolved: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    for ingredient in _ingredients_of(recipe):
        kind = _ingredient_kind(ingredient)
        if kind == "recipe":
            try:
                child = store.show(ingredient["recipe"])
            except RecipeStoreError as exc:
                missing.append(
                    {
                        "recipe": ingredient["recipe"],
                        "role": ingredient["role"],
                        "reason": str(exc),
                    }
                )
                continue
            row = dict(ingredient)
            row.update(
                {
                    "kind": "recipe",
                    "resolved": True,
                    "name": child["name"],
                    "child_kind": child["kind"],
                    "status": child["status"],
                    "flavor": child.get("flavor"),
                }
            )
            resolved.append(row)
            continue

        row = dict(ingredient)
        row.update(
            {
                "kind": kind,
                "resolved": False,
                "reason": (
                    "sample and instrument bindings are declarations; this build does not "
                    "resolve library sources in the offline recipe store"
                ),
            }
        )
        unresolved.append(row)

    result["ingredients"] = resolved + unresolved
    result["missing"] = missing
    result["unresolved"] = unresolved
    result["contract"] = {
        "flavor": recipe.get("flavor"),
        "expected": recipe.get("expected") or {},
        "manual": recipe.get("manual") or [],
        "steps": len(recipe.get("steps") or []),
    }
    return result


def save_recipe(
    args: Optional[Dict[str, Any]] = None,
    store: Optional[RecipeStore] = None,
) -> Dict[str, Any]:
    args = dict(args or {})
    _only(args, ("recipe", "overwrite"))
    recipe = args.get("recipe")
    if not isinstance(recipe, dict):
        raise LiveError("BAD_ARGS", "recipe must be an object")
    overwrite = args.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise LiveError("BAD_ARGS", "overwrite must be a boolean")

    try:
        validate_recipe(recipe)
    except RecipeValidationError as exc:
        raise LiveError("BAD_ARGS", "invalid recipe: %s" % exc) from exc
    if recipe["status"] == "shipped":
        raise LiveError(
            "BAD_ARGS",
            "user recipes must not use status 'shipped'; use 'draft' or 'user'",
        )
    recipe_id = recipe["id"]
    if (
        not isinstance(recipe_id, str)
        or not recipe_id
        or Path(recipe_id).name != recipe_id
        or recipe_id in (".", "..")
    ):
        raise LiveError("BAD_ARGS", "recipe id must be a filename-safe identifier")

    store = store or default_store()
    if recipe["kind"] in ("combination", "style", "workflow"):
        for ingredient in _ingredients_of(recipe):
            if _ingredient_kind(ingredient) != "recipe":
                continue
            if ingredient["recipe"] == recipe_id:
                raise LiveError("BAD_ARGS", "a recipe cannot reference itself")
            try:
                store.show(ingredient["recipe"])
            except RecipeStoreError as exc:
                raise LiveError(
                    "BAD_ARGS",
                    "recipe references missing ingredient %r: %s"
                    % (ingredient["recipe"], exc),
                ) from exc
        if recipe.get("steps"):
            try:
                validate_steps(recipe["steps"])
            except EscalationError as exc:
                raise LiveError("BAD_ARGS", "invalid workflow steps: %s" % exc) from exc

    target = store.user_dir / f"{recipe_id}.json"
    replaced = target.is_file()
    if replaced and not overwrite:
        raise LiveError(
            "PRECONDITION_FAILED",
            "recipe %r already exists; pass overwrite: true to replace the user copy" % recipe_id,
        )
    try:
        path = store.save_user(recipe)
    except RecipeStoreError as exc:
        raise LiveError("BAD_ARGS", str(exc)) from exc
    return {
        "id": recipe_id,
        "name": recipe["name"],
        "status": recipe["status"],
        "path": str(path),
        "replaced": replaced,
    }


def _target(args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw = args.get("target")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise LiveError("BAD_ARGS", "target must be an object")
    unknown = sorted(set(raw) - {"track", "clip", "location", "slot"})
    if unknown:
        raise LiveError("BAD_ARGS", "target has unknown key(s): %s" % ", ".join(unknown))
    track = raw.get("track")
    clip = raw.get("clip")
    if track is None and clip is None:
        raise LiveError("BAD_ARGS", "target needs a track, a clip, or both")
    if track is not None and (not isinstance(track, str) or not track):
        raise LiveError("BAD_ARGS", "target.track must be a non-empty string when given")
    if clip is not None and (not isinstance(clip, str) or not clip):
        raise LiveError("BAD_ARGS", "target.clip must be a non-empty string when given")
    location = raw.get("location")
    if location is not None and location not in ("arrangement", "session"):
        raise LiveError("BAD_ARGS", "target.location must be 'arrangement' or 'session'")
    slot = raw.get("slot")
    if slot is not None:
        if clip is None:
            raise LiveError("BAD_ARGS", "target.slot needs target.clip")
        if location == "arrangement":
            raise LiveError("BAD_ARGS", "target.slot only applies to a Session clip")
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0:
            raise LiveError("BAD_ARGS", "target.slot must be a non-negative integer")
    target: Dict[str, Any] = {}
    if track is not None:
        target["track"] = track
    if clip is not None:
        target["clip"] = clip
    if location is not None:
        target["location"] = location
    if slot is not None:
        target["slot"] = slot
    return target


def _pitch_map(args: Dict[str, Any]) -> Dict[str, int]:
    raw = args.get("pitch_map")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise LiveError("BAD_ARGS", "pitch_map must be an object")
    out = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise LiveError("BAD_ARGS", "pitch_map keys must be non-empty strings")
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 127:
            raise LiveError(
                "BAD_ARGS", "pitch_map.%s must be an integer from 0 to 127" % key
            )
        out[key] = value
    return out


def _track_bindings(args: Dict[str, Any]) -> Dict[str, str]:
    raw = args.get("track_bindings")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise LiveError("BAD_ARGS", "track_bindings must be an object")
    out = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise LiveError("BAD_ARGS", "track_bindings keys must be non-empty strings")
        if not isinstance(value, str) or not value:
            raise LiveError("BAD_ARGS", "track_bindings.%s must be a non-empty string" % key)
        out[key] = value
    return out


def _beats_per_bar(data: Dict[str, Any]) -> float:
    signature = (data.get("song") or {}).get("signature") or [4, 4]
    try:
        numerator, denominator = int(signature[0]), int(signature[1])
    except (IndexError, TypeError, ValueError):
        return 4.0
    if numerator <= 0 or denominator <= 0:
        return 4.0
    return numerator * 4.0 / denominator


def _target_length(data: Dict[str, Any], target: Dict[str, Any]) -> Optional[float]:
    """Read an Arrangement target length when the name identifies exactly one clip."""
    if not data or target.get("location") == "session" or not target.get("track"):
        return None
    for track in data.get("tracks") or []:
        if track.get("name") != target["track"]:
            continue
        arrangement = [
            clip for clip in track.get("arrangement") or []
            if clip.get("name") == target["clip"]
        ]
        session = [
            clip for clip in (track.get("session") or {}).get("clips") or []
            if clip.get("name") == target["clip"]
        ]
        if target.get("location") is None and session:
            return None
        if len(arrangement) != 1:
            return None
        clip = arrangement[0]
        try:
            length = clip.get("length")
            if length is None:
                length = float(clip.get("end", 0.0)) - float(clip.get("start", 0.0))
            length = float(length)
        except (TypeError, ValueError):
            return None
        return length if length >= 0 else None
    return None


def _rewrite_track_args(
    steps: Sequence[Dict[str, Any]],
    bindings: Dict[str, str],
) -> List[Dict[str, Any]]:
    if not bindings:
        return [dict(step) for step in steps]
    rewritten = []
    for step in steps:
        row = dict(step)
        args = dict(row.get("args") or {})
        if isinstance(args.get("tracks"), list):
            args["tracks"] = [bindings.get(name, name) for name in args["tracks"]]
        for key in ("track", "to_track", "reference_track"):
            if isinstance(args.get(key), str):
                args[key] = bindings.get(args[key], args[key])
        row["args"] = args
        rewritten.append(row)
    return rewritten


def _source_alternatives(source: Any) -> List[str]:
    """The device names an ingredient's free-text ``source`` can mean.

    ``"Ableton Wavetable or Operator"`` is two candidates; a parenthesised qualifier such as
    ``"(sine)"`` is dropped. Only names long enough to be meaningful survive.
    """
    text = re.sub(r"\([^)]*\)", " ", str(source or ""))
    parts = re.split(r"\bor\b|/|,|\band\b", text, flags=re.IGNORECASE)
    out: List[str] = []
    for part in parts:
        cleaned = re.sub(r"\bableton\b|\bpresets?\b", " ", part, flags=re.IGNORECASE)
        name = " ".join(cleaned.casefold().split())
        if len(name) >= 3 and name not in out:
            out.append(name)
    return out


def _track_device_names(track: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for device in track.get("devices") or []:
        if not isinstance(device, dict):
            continue
        for key in ("name", "class"):
            value = device.get(key)
            if isinstance(value, str) and value.strip():
                names.append(value.strip().casefold())
    return names


def _ingredient_label(ingredient: Dict[str, Any]) -> str:
    return "ingredient %r (%s, %r)" % (
        ingredient.get("role"), ingredient.get("kind"), ingredient.get("source")
    )


def _resolve_role_track(
    recipe: Dict[str, Any],
    role: str,
    ingredients: Sequence[Dict[str, Any]],
    target: Optional[Dict[str, Any]],
    bindings: Dict[str, str],
    data: Optional[Dict[str, Any]],
    purpose: str,
    hints: Sequence[str] = (),
) -> Tuple[str, str]:
    """Find the existing track an ingredient role lives on: target, binding, then devices."""
    ingredient = next((i for i in ingredients if i.get("role") == role), None)
    if ingredient is None:
        raise RecipeCompileError(
            "recipe %r %s role %r does not name one of its ingredients (%s)"
            % (
                recipe["id"],
                purpose,
                role,
                ", ".join(str(i.get("role")) for i in ingredients) or "none",
            )
        )
    if _ingredient_kind(ingredient) not in ("instrument", "sample"):
        raise RecipeCompileError(
            "recipe %r %s role %r names a recipe ingredient; it needs an instrument or "
            "sample role" % (recipe["id"], purpose, role)
        )
    if target and target.get("track"):
        return str(target["track"]), "target"
    if role in bindings:
        return bindings[role], "binding"

    alternatives = _source_alternatives(ingredient.get("source"))
    for hint in hints:
        alternatives.extend(_source_alternatives(hint))
    tracks = data.get("tracks") if isinstance(data, dict) else None
    matches: List[str] = []
    for track in tracks or []:
        if not isinstance(track, dict):
            continue
        if str(track.get("kind") or "").casefold() != "midi":
            continue
        names = _track_device_names(track)
        if any(
            name == alternative or (len(name) >= 4 and name in alternative)
            for name in names
            for alternative in alternatives
        ):
            name = str(track.get("name") or "")
            if name and name not in matches:
                matches.append(name)

    label = _ingredient_label(ingredient)
    if len(matches) == 1:
        return matches[0], "device"
    if len(matches) > 1:
        raise RecipeCompileError(
            "recipe %r %s cannot choose a track for %s: several MIDI tracks carry it "
            "(%s); choose one with `--binding %s=<track>` or `--target-track`"
            % (
                recipe["id"], purpose, label,
                ", ".join("'%s'" % m for m in sorted(matches)), role,
            )
        )
    if not tracks:
        raise RecipeCompileError(
            "recipe %r %s needs a connected Set to resolve %s; run it with Live "
            "connected, or bind the track with `--binding %s=<track>`"
            % (recipe["id"], purpose, label, role)
        )
    raise RecipeCompileError(
        "recipe %r %s found no MIDI track carrying %s; bind it with "
        "`--binding %s=<track>` or pass `--target-track`"
        % (recipe["id"], purpose, label, role)
    )


def _find_device(
    data: Optional[Dict[str, Any]], track_name: str, wanted: str
) -> Optional[str]:
    """The real device name on that track, matched by name or class."""
    for track in (data or {}).get("tracks") or []:
        if track.get("name") != track_name:
            continue
        for device in track.get("devices") or []:
            names = [
                str(device.get(key)) for key in ("name", "class")
                if isinstance(device.get(key), str) and device.get(key)
            ]
            if any(name.casefold() == wanted.casefold() for name in names):
                return str(device.get("name") or names[0])
    return None


def _blocked_reason(recipe_id: str, ingredients: Sequence[Dict[str, Any]]) -> str:
    """Name the step this recipe would need and the entity this build cannot add."""
    blocker = next(
        (item for item in ingredients if _ingredient_kind(item) in ("instrument", "sample")),
        None,
    )
    if blocker is None:
        return (
            "recipe %r has 0 executable steps and declares no audition phrase or device_moves, "
            "so it contains no write this build can perform" % recipe_id
        )
    label = _ingredient_label(blocker)
    role = str(blocker.get("role"))
    if _ingredient_kind(blocker) == "sample":
        return (
            "recipe %r cannot run any step: step 1 would need a sample-loading operation "
            "(`clips_create_session_audio` needs a file path this recipe does not carry, and "
            "`recipe_build` is unimplemented) for %s, and this build cannot load a library "
            "sample inside a reversible plan; remedy: place the sample on a track yourself and "
            "bind the role with `--binding %s=<track>`, add an audition or device_moves entry, "
            "or perform the manual checkpoints by hand"
            % (recipe_id, label, role)
        )
    return (
        "recipe %r cannot run any step: step 1 would need `devices_load` to add %s, and that "
        "tool is not reversible or dry-run, so it cannot appear in a plan; this build cannot "
        "insert devices; remedy: load %r yourself and bind the role to that track with "
        "`--binding %s=<track>`, add a device_moves entry, or perform the manual checkpoints by "
        "hand"
        % (recipe_id, label, blocker.get("source"), role)
    )


def _render_device_moves(
    recipe: Dict[str, Any],
    moves: Sequence[Dict[str, Any]],
    ingredients: Sequence[Dict[str, Any]],
    target: Optional[Dict[str, Any]],
    bindings: Dict[str, str],
    data: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Turn declared device moves into reversible parameter writes on existing devices."""
    if not isinstance(data, dict) or not data.get("tracks"):
        raise RecipeCompileError(
            "recipe %r writes device parameters, so it needs a connected Set; run it with "
            "Live connected" % recipe["id"]
        )
    steps: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    for index, move in enumerate(moves, start=1):
        role = str(move["role"])
        wanted = str(move["device"])
        ingredient = next(i for i in ingredients if i.get("role") == role)
        try:
            track, resolved_by = _resolve_role_track(
                recipe, role, ingredients, target, bindings, data, "device move",
                hints=(wanted,),
            )
        except RecipeCompileError as exc:
            raise RecipeCompileError(
                "recipe %r step %d (devices_set_parameter) cannot run: %s; the step needs "
                "device %r on an existing track, and this build cannot insert devices "
                "(`devices_load` is not reversible or dry-run, so it cannot be a step); remedy: "
                "load %r yourself and bind %s to that track with `--binding %s=<track>`, or "
                "pass `--target-track`"
                % (
                    recipe["id"], index, exc, wanted, wanted, role, role,
                )
            ) from exc
        device = _find_device(data, track, wanted)
        if device is None:
            raise RecipeCompileError(
                "recipe %r step %d (devices_set_parameter) cannot run: it needs device %r on "
                "track %r for %s, and this build cannot insert devices inside a reversible plan "
                "(`devices_load` is not reversible or dry-run, so it cannot be a step); remedy: "
                "load %r on %r yourself, bind the role to a track that has it with "
                "`--binding %s=<track>`, or set the parameter by hand"
                % (
                    recipe["id"], index, wanted, track,
                    _ingredient_label(ingredient),
                    wanted, track, role,
                )
            )
        parameter = str(move["parameter"])
        value = float(move["value"])
        steps.append(
            {
                "tool": "devices_set_parameter",
                "args": {"track": track, "device": device, "parameter": parameter, "value": value},
                "why": move.get("why")
                or "Set %s on %s for %s" % (parameter, device, role),
            }
        )
        rows.append(
            {
                "role": role,
                "track": track,
                "device": device,
                "parameter": parameter,
                "value": value,
                "resolved_by": resolved_by,
            }
        )

    moved_roles = {str(move["role"]) for move in moves}
    unresolved = [
        {
            "role": str(item.get("role")),
            "kind": _ingredient_kind(item),
            "source": item.get("source"),
            "reason": (
                "no device move is declared for this ingredient; this build cannot insert or "
                "load it, so set it up by hand"
            ),
        }
        for item in ingredients
        if _ingredient_kind(item) in ("instrument", "sample")
        and str(item.get("role")) not in moved_roles
    ]
    return steps, {
        "strategy": "device_parameters",
        "recipe_id": recipe["id"],
        "moves": rows,
        "move_count": len(rows),
        "unresolved_ingredients": unresolved,
        "warnings": [
            "device parameters are written by name; a name this Live build does not expose "
            "fails in preflight rather than silently doing nothing"
        ],
    }


def _render_audition(
    recipe: Dict[str, Any],
    audition: Dict[str, Any],
    track: str,
    resolved_by: str,
    target: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Build the ``notes_replace`` step that writes the recipe's audition phrase."""
    if not target or not target.get("clip"):
        raise RecipeCompileError(
            "recipe %r is a style checklist with an audition phrase, but it needs an existing "
            "MIDI clip to write into; pass --target-clip (and --target-track or --binding)"
            % recipe["id"]
        )
    notes = []
    for source in audition.get("notes") or []:
        note = {
            "pitch": int(source["pitch"]),
            "start": round(float(source["start"]), 6),
            "duration": round(float(source["duration"]), 6),
            "velocity": int(source.get("velocity", 110)),
        }
        notes.append(note)
    notes.sort(key=lambda note: (note["start"], note["pitch"], note["velocity"]))

    args: Dict[str, Any] = {"track": track, "clip": str(target["clip"])}
    if target.get("location"):
        args["location"] = str(target["location"])
    if target.get("slot") is not None:
        args["slot"] = int(target["slot"])

    step = {
        "tool": "notes_replace",
        "args": {**args, "notes": notes},
        "why": "Write the %s audition phrase (%d notes) for %s into %s / %s"
        % (recipe["id"], len(notes), audition["role"], track, args["clip"]),
    }
    render = {
        "strategy": "audition",
        "recipe_id": recipe["id"],
        "role": audition["role"],
        "track": track,
        "target": dict(args),
        "clip": args["clip"],
        "location": args.get("location"),
        "slot": args.get("slot"),
        "resolved_by": resolved_by,
        "note_count": len(notes),
        "pitches": sorted({note["pitch"] for note in notes}),
        "length_beats": float(audition.get("length_beats") or 4.0),
        "notes": notes,
        "warnings": [
            "notes_replace replaces the clip's whole note vector; the stored plan restores the "
            "previous notes on undo"
        ],
    }
    return [step], render


def _compile_recipe(
    recipe: Dict[str, Any],
    store: RecipeStore,
    target: Optional[Dict[str, Any]] = None,
    pitch_map: Optional[Dict[str, int]] = None,
    data: Optional[Dict[str, Any]] = None,
    trail: Tuple[str, ...] = (),
    depth: int = 0,
    bindings: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Expand recipe ingredients into executable steps, refusing what cannot be built."""
    bindings = bindings or {}
    recipe_id = recipe["id"]
    if recipe_id in trail:
        raise RecipeCompileError(
            "recipe cycle: %s" % " -> ".join(trail + (recipe_id,))
        )
    if depth > MAX_COMPILE_DEPTH:
        raise RecipeCompileError(
            "recipe composition is deeper than %d levels" % MAX_COMPILE_DEPTH
        )

    steps = [dict(step) for step in recipe.get("steps") or []]
    manual = _manual_entries(recipe)
    render = None

    if recipe["kind"] == "rhythm":
        if target is None or not target.get("clip"):
            raise RecipeCompileError(
                "recipe %r is a rhythm and needs an explicit MIDI target; pass "
                "target={track, clip} (and pitch_map for slots without a pitch)"
                % recipe_id
            )
        if not target.get("track"):
            raise RecipeCompileError(
                "recipe %r is a rhythm and needs an explicit target track; pass "
                "target.track or --target-track" % recipe_id
            )
        data = data or {}
        try:
            render = render_rhythm(
                recipe,
                target,
                pitch_map,
                beats_per_bar=_beats_per_bar(data),
                set_tempo=(data.get("song") or {}).get("tempo"),
                target_length=_target_length(data, target),
            )
        except RhythmCompileError as exc:
            raise RecipeCompileError(str(exc)) from exc
        return [render["step"]], manual, render

    ingredients = _ingredients_of(recipe)
    for ingredient in ingredients:
        kind = _ingredient_kind(ingredient)
        role = ingredient.get("role")
        if kind != "recipe":
            # A declaration, not a step: the recipe may still have executable steps or an
            # audition phrase that only needs the track this ingredient describes.
            continue
        child_id = ingredient.get("recipe")
        try:
            child = store.show(child_id)
        except RecipeStoreError as exc:
            raise RecipeCompileError(
                "ingredient %r references %r: %s" % (role, child_id, exc)
            ) from exc
        child_steps, child_manual, child_render = _compile_recipe(
            child,
            store,
            target=target if render is None else None,
            pitch_map=pitch_map,
            data=data,
            trail=trail + (recipe_id,),
            depth=depth + 1,
            bindings=bindings,
        )
        steps = child_steps + steps
        manual = child_manual + manual
        if child_render is not None:
            render = child_render

    audition = recipe.get("audition")
    if isinstance(audition, dict):
        if render is not None:
            raise RecipeCompileError(
                "recipe %r declares both an audition phrase and a rhythm ingredient; a plan "
                "can only render one of them" % recipe_id
            )
        if not target or not target.get("clip"):
            raise RecipeCompileError(
                "recipe %r is a style checklist with an audition phrase, but it needs an "
                "existing MIDI clip to write into; pass --target-clip (and --target-track or "
                "--binding <role>=<track>)" % recipe_id
            )
        track, resolved_by = _resolve_role_track(
            recipe, audition["role"], ingredients, target, bindings, data, "audition"
        )
        audition_steps, render = _render_audition(
            recipe, audition, track, resolved_by, target
        )
        steps = steps + audition_steps

    moves = recipe.get("device_moves")
    if isinstance(moves, list) and moves:
        if render is not None:
            raise RecipeCompileError(
                "recipe %r declares both device_moves and an audition phrase or rhythm "
                "ingredient; a plan can only do one of them" % recipe_id
            )
        move_steps, render = _render_device_moves(
            recipe, moves, ingredients, target, bindings, data
        )
        steps = steps + move_steps

    # A step that names an instrument role is only executable when the caller says which track
    # that role lives on; otherwise report the step and the ingredient it is missing.
    role_ingredients = {
        str(item.get("role")): item
        for item in ingredients
        if _ingredient_kind(item) in ("instrument", "sample")
    }
    for index, step in enumerate(steps, start=1):
        step_args = step.get("args") or {}
        names: List[str] = []
        for key in ("track", "to_track", "reference_track"):
            if isinstance(step_args.get(key), str):
                names.append(step_args[key])
        if isinstance(step_args.get("tracks"), list):
            names.extend(name for name in step_args["tracks"] if isinstance(name, str))
        missing = next(
            (
                name for name in names
                if name in role_ingredients
                and name not in bindings
                and not (target and target.get("track") == name)
            ),
            None,
        )
        if missing is not None:
            raise RecipeCompileError(
                "recipe %r step %d (%s) needs %s, which this build cannot load or create; "
                "bind it with `--binding %s=<track>`"
                % (
                    recipe_id,
                    index,
                    step.get("tool"),
                    _ingredient_label(role_ingredients[missing]),
                    missing,
                )
            )

    if not steps:
        raise RecipeCompileError(_blocked_reason(recipe_id, ingredients))
    if len(steps) > MAX_STEPS:
        raise RecipeCompileError(
            "compiled recipe has %d steps; the plan limit is %d"
            % (len(steps), MAX_STEPS)
        )
    if len(manual) > MAX_MANUAL:
        raise RecipeCompileError(
            "compiled recipe has %d manual checkpoints; the limit is %d"
            % (len(manual), MAX_MANUAL)
        )
    return steps, manual, render


def _manual_rows(
    entries: Sequence[Dict[str, Any]],
    *,
    confirmed: bool,
    gate: str = "before_apply",
) -> List[Dict[str, Any]]:
    rows = [dict(entry) for entry in entries]
    for row in rows:
        if row["when"] == gate:
            row["status"] = "confirmed" if confirmed else "pending"
        else:
            row["status"] = "pending"
    return rows


def apply_recipe(
    args: Optional[Dict[str, Any]] = None,
    store: Optional[RecipeStore] = None,
    adapter: Any = None,
    cache: Any = None,
    plan_root: Optional[str] = None,
    catalogue: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compile a recipe into the existing stored-plan path without writing Live."""
    args = dict(args or {})
    _only(args, (
        "id", "manual_confirmed", "target", "pitch_map", "track_bindings",
    ))
    recipe_id = _recipe_id(args)
    confirmed = args.get("manual_confirmed", False)
    if not isinstance(confirmed, bool):
        raise LiveError("BAD_ARGS", "manual_confirmed must be a boolean")
    target = _target(args)
    pitch_map = _pitch_map(args)
    bindings = _track_bindings(args)

    store = store or default_store()
    recipe = _store_recipe(store, recipe_id)
    if target is not None and not target.get("clip") and recipe["kind"] == "rhythm":
        raise LiveError(
            "BAD_ARGS",
            "a rhythm recipe needs target.clip: it writes into an existing MIDI clip",
        )
    data: Dict[str, Any] = {}
    if cache is not None and adapter is not None:
        data = cache.get()
    try:
        steps, manual, render = _compile_recipe(
            recipe,
            store,
            target=target,
            pitch_map=pitch_map,
            data=data,
            bindings=bindings,
        )
    except RecipeCompileError as exc:
        return {
            "recipe_id": recipe_id,
            "recipe_name": recipe["name"],
            "status": "unavailable",
            "plan_id": None,
            "reason": str(exc),
            "manual": _manual_entries(recipe),
            "expected": recipe.get("expected") or {},
        }
    if bindings:
        steps = _rewrite_track_args(steps, bindings)

    render_summary = None
    if render is not None:
        render_summary = {key: value for key, value in render.items() if key != "step"}

    before = [entry for entry in manual if entry["when"] == "before_apply"]
    if before and not confirmed:
        return {
            "recipe_id": recipe_id,
            "recipe_name": recipe["name"],
            "status": "manual_required",
            "plan_id": None,
            "reason": (
                "this recipe has manual checkpoints before apply; perform them, then call "
                "recipe_apply again with manual_confirmed: true"
            ),
            "manual": _manual_rows(before, confirmed=False),
            "expected": recipe.get("expected") or {},
            "render": render_summary,
            "track_bindings": bindings or None,
        }

    try:
        result = escalate(
            data,
            {
                "intent": "Recipe %s: %s" % (recipe_id, recipe["name"]),
                "steps": steps,
            },
            catalogue,
            PlanStore(root=plan_root),
            adapter=adapter,
        )
    except (EscalationError, PlanStoreError) as exc:
        raise LiveError("BAD_ARGS", str(exc)) from exc

    result["recipe_id"] = recipe_id
    result["recipe_name"] = recipe["name"]
    result["status"] = "plan_ready"
    result["manual"] = _manual_rows(manual, confirmed=confirmed)
    result["expected"] = recipe.get("expected") or {}
    result["render"] = render_summary
    result["track_bindings"] = bindings or None
    result["apply_with"] = "ableton_plan_apply"
    result["verify_with"] = "recipe_verify"
    return result


def verify_recipe(
    args: Optional[Dict[str, Any]] = None,
    store: Optional[RecipeStore] = None,
    cache: Any = None,
) -> Dict[str, Any]:
    """Compare the current snapshot to a recipe's expected structural fingerprint."""
    args = dict(args or {})
    _only(args, ("id", "refresh", "manual_confirmed"))
    recipe_id = _recipe_id(args)
    refresh = args.get("refresh", False)
    if not isinstance(refresh, bool):
        raise LiveError("BAD_ARGS", "refresh must be a boolean")
    confirmed = args.get("manual_confirmed", False)
    if not isinstance(confirmed, bool):
        raise LiveError("BAD_ARGS", "manual_confirmed must be a boolean")

    store = store or default_store()
    recipe = _store_recipe(store, recipe_id)
    expected = recipe.get("expected")
    manual = _manual_entries(recipe)
    base = {
        "recipe_id": recipe_id,
        "recipe_name": recipe["name"],
        "expected": expected or {},
        "manual": _manual_rows(manual, confirmed=confirmed, gate="before_verify"),
    }
    if not expected:
        base.update(
            {
                "status": "unavailable",
                "reason": "this recipe has no expected fingerprint to verify",
                "metrics": [],
            }
        )
        return base

    before = [entry for entry in manual if entry["when"] == "before_verify"]
    if before and not confirmed:
        base.update(
            {
                "status": "manual_required",
                "reason": (
                    "this recipe has manual checkpoints before verify; perform them, then "
                    "call recipe_verify again with manual_confirmed: true"
                ),
            }
        )
        return base
    if cache is None:
        base.update(
            {
                "status": "unavailable",
                "reason": "no snapshot cache is available; connect to Live and retry",
                "metrics": [],
            }
        )
        return base

    measured = measure_snapshot(cache.get(refresh=refresh))
    comparison = compare_fingerprint(expected, measured)
    base.update(comparison)
    base["measured"] = measured.get("metrics") or {}
    base["measurement_unavailable"] = measured.get("unavailable") or {}
    base["snapshot_epoch"] = getattr(cache, "epoch", None)
    return base

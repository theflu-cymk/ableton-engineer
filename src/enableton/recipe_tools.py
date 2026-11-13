"""Tool-facing access to the recipe store.

Recipes are JSON data, not Live state. These handlers never open the Live socket; the existing
``RecipeStore`` owns validation and atomic writes. A recipe compiles only into an escalation plan,
so every executable step still passes the same validation, preflight and transactional apply path.
"""

from __future__ import annotations

import os
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


def list_recipes(
    args: Optional[Dict[str, Any]] = None,
    store: Optional[RecipeStore] = None,
) -> Dict[str, Any]:
    args = dict(args or {})
    _only(args, ())
    store = store or default_store()
    try:
        rows = store.list()
    except RecipeStoreError as exc:
        raise LiveError("BAD_ARGS", str(exc)) from exc
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
    if not isinstance(track, str) or not track:
        raise LiveError("BAD_ARGS", "target.track must be a non-empty string")
    if not isinstance(clip, str) or not clip:
        raise LiveError("BAD_ARGS", "target.clip must be a non-empty string")
    location = raw.get("location")
    if location is not None and location not in ("arrangement", "session"):
        raise LiveError("BAD_ARGS", "target.location must be 'arrangement' or 'session'")
    slot = raw.get("slot")
    if slot is not None:
        if location == "arrangement":
            raise LiveError("BAD_ARGS", "target.slot only applies to a Session clip")
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0:
            raise LiveError("BAD_ARGS", "target.slot must be a non-negative integer")
    target = {"track": track, "clip": clip}
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
    if not data or target.get("location") == "session":
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


def _compile_recipe(
    recipe: Dict[str, Any],
    store: RecipeStore,
    target: Optional[Dict[str, Any]] = None,
    pitch_map: Optional[Dict[str, int]] = None,
    data: Optional[Dict[str, Any]] = None,
    trail: Tuple[str, ...] = (),
    depth: int = 0,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Expand recipe ingredients into executable steps, refusing what cannot be built."""
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
        if target is None:
            raise RecipeCompileError(
                "recipe %r is a rhythm and needs an explicit MIDI target; pass "
                "target={track, clip} (and pitch_map for slots without a pitch)"
                % recipe_id
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

    for ingredient in _ingredients_of(recipe):
        kind = _ingredient_kind(ingredient)
        role = ingredient.get("role")
        if kind != "recipe":
            raise RecipeCompileError(
                "ingredient %r is a %s binding; this build cannot load library sources "
                "inside a plan" % (role, kind)
            )
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
        )
        steps = child_steps + steps
        manual = child_manual + manual
        if child_render is not None:
            render = child_render

    if target is not None and render is None:
        raise RecipeCompileError(
            "a target was supplied, but recipe %r contains no rhythm ingredient" % recipe_id
        )
    if not steps:
        raise RecipeCompileError(
            "recipe %r has no executable steps; a reference-only recipe cannot be compiled"
            % recipe_id
        )
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

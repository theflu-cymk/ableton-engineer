"""Pure validation of the documented version-1 recipe data shape."""

from __future__ import annotations

import math
from collections.abc import Mapping

from .recipe_patterns import RecipePatternError, parse_step_pattern


class RecipeValidationError(ValueError):
    """A recipe is missing required data or contradicts the documented schema."""


def _object(value: object, path: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise RecipeValidationError(f"{path} must be an object")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecipeValidationError(f"{path} must be a non-empty string")
    return value


def _positive_integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RecipeValidationError(f"{path} must be a positive integer")
    return value


def _finite_number(value: object, path: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecipeValidationError(f"{path} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        if minimum is not None:
            raise RecipeValidationError(f"{path} must be a finite number at least {minimum}")
        raise RecipeValidationError(f"{path} must be a finite number")
    return number


def validate_recipe(recipe: object) -> None:
    """Validate required version-1 fields, including unique lane/slot identifiers."""
    data = _object(recipe, "recipe")
    for field in ("id", "name", "kind", "status"):
        _text(data.get(field), f"recipe.{field}")

    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise RecipeValidationError("recipe.version must be an integer")
    if version != 1:
        raise RecipeValidationError(f"unsupported recipe schema version: {version}")

    tempo = _object(data.get("tempo"), "recipe.tempo")
    _finite_number(tempo.get("bpm"), "recipe.tempo.bpm", minimum=0.001)
    _text(tempo.get("feel"), "recipe.tempo.feel")
    _text(tempo.get("grid"), "recipe.tempo.grid")

    length_bars = _positive_integer(data.get("length_bars"), "recipe.length_bars")
    lanes = data.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        raise RecipeValidationError("recipe.lanes must be a non-empty array")
    lane_slots = set()
    for index, value in enumerate(lanes):
        path = f"recipe.lanes[{index}]"
        lane = _object(value, path)
        lane_slot = _text(lane.get("slot"), f"{path}.slot")
        if lane_slot in lane_slots:
            raise RecipeValidationError(
                f"{path}.slot duplicates lane slot {lane_slot!r}"
            )
        lane_slots.add(lane_slot)
        try:
            bars = parse_step_pattern(_text(lane.get("pattern"), f"{path}.pattern"))
        except RecipePatternError as exc:
            raise RecipeValidationError(f"{path}.pattern: {exc}") from exc
        if length_bars % len(bars):
            raise RecipeValidationError(
                f"{path}.pattern has {len(bars)} bars, which does not divide "
                f"recipe.length_bars ({length_bars})"
            )
        for field in ("velocity", "swing", "humanize"):
            if field in lane:
                _finite_number(lane[field], f"{path}.{field}")

    slots = data.get("slots")
    if not isinstance(slots, list) or not slots:
        raise RecipeValidationError("recipe.slots must be a non-empty array")
    defined_slots = set()
    for index, value in enumerate(slots):
        path = f"recipe.slots[{index}]"
        slot = _object(value, path)
        slot_name = _text(slot.get("slot"), f"{path}.slot")
        if slot_name in defined_slots:
            raise RecipeValidationError(
                f"{path}.slot duplicates slot definition {slot_name!r}"
            )
        defined_slots.add(slot_name)
        mode = _text(slot.get("mode"), f"{path}.mode")
        if mode not in ("hit", "layer"):
            raise RecipeValidationError(f"{path}.mode must be 'hit' or 'layer'")
        _text(slot.get("from"), f"{path}.from")
        _text(slot.get("select"), f"{path}.select")
        _positive_integer(slot.get("count"), f"{path}.count")

    missing_slots = sorted(lane_slots - defined_slots)
    if missing_slots:
        raise RecipeValidationError(
            "recipe.lanes reference undefined slot(s): " + ", ".join(missing_slots)
        )

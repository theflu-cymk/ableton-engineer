"""Pure validation of the documented version-1 recipe data shape.

A recipe is one recallable artifact. Its ``kind`` selects the payload:

- ``rhythm``: tempo, bar length, lanes and sample slots (the original shape).
- ``workflow``: a sequence of reversible tool steps.
- ``combination``: a composition of existing recipes plus optional procedure.

The contract is additive: a recipe may also carry a ``flavor`` profile, typed ``ingredients``,
``manual`` checkpoints and an ``expected`` structural fingerprint. Recipe references are checked by
the recipe tool layer, where the store is available.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from .recipe_fingerprint import FingerprintError, parse_fingerprint
from .recipe_patterns import GRID_STEPS, RecipePatternError, parse_step_pattern

PROCEDURAL_KINDS = ("combination", "style", "workflow")
MAX_STEPS = 12
MAX_MANUAL = 12
MANUAL_WHEN = ("before_apply", "after_apply", "before_verify")


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


def _optional_text(value: object, path: str) -> None:
    if value is not None:
        _text(value, path)


def _positive_integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RecipeValidationError(f"{path} must be a positive integer")
    return value


def _integer_in_range(value: object, path: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise RecipeValidationError(
            f"{path} must be an integer from {low} to {high}"
        )
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


def _string_list(value: object, path: str) -> None:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise RecipeValidationError(f"{path} must be an array of non-empty strings")


def _plain_data(value: object, path: str, depth: int = 0) -> None:
    """Keep ingredient constraints JSON-safe without inventing a selector language."""
    if depth > 4:
        raise RecipeValidationError(f"{path} is nested too deeply")
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, (int, float)):
        _finite_number(value, path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _plain_data(item, f"{path}[{index}]", depth + 1)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise RecipeValidationError(f"{path} keys must be non-empty strings")
            _plain_data(item, f"{path}.{key}", depth + 1)
        return
    raise RecipeValidationError(f"{path} must contain only JSON values")


def _source_metadata(source: object) -> None:
    data = _object(source, "recipe.source")
    _text(data.get("kind"), "recipe.source.kind")
    _text(data.get("file"), "recipe.source.file")
    window = data.get("window_s")
    if window is not None:
        if not isinstance(window, (list, tuple)) or len(window) != 2:
            raise RecipeValidationError(
                "recipe.source.window_s must be a [start, end] pair"
            )
        start = _finite_number(window[0], "recipe.source.window_s[0]", minimum=0.0)
        end = _finite_number(window[1], "recipe.source.window_s[1]")
        if end <= start:
            raise RecipeValidationError(
                "recipe.source.window_s must start before it ends"
            )
    if "confidence" in data:
        confidence = _finite_number(data["confidence"], "recipe.source.confidence")
        if not 0.0 <= confidence <= 1.0:
            raise RecipeValidationError(
                "recipe.source.confidence must be between 0 and 1"
            )


def _tags(data: Mapping) -> None:
    tags = data.get("tags")
    if tags is not None:
        _string_list(tags, "recipe.tags")


def _flavor(data: Mapping) -> None:
    value = data.get("flavor")
    if value is None:
        return
    if isinstance(value, str):
        _text(value, "recipe.flavor")
        return

    flavor = _object(value, "recipe.flavor")
    unknown = sorted(set(flavor) - {"name", "bpm", "feel", "reference", "tags", "notes"})
    if unknown:
        raise RecipeValidationError(
            "recipe.flavor has unknown key(s): " + ", ".join(unknown)
        )
    _text(flavor.get("name"), "recipe.flavor.name")

    bpm = flavor.get("bpm")
    if bpm is not None:
        if isinstance(bpm, (list, tuple)):
            if len(bpm) != 2:
                raise RecipeValidationError(
                    "recipe.flavor.bpm must be a number or [low, high] pair"
                )
            low = _finite_number(bpm[0], "recipe.flavor.bpm[0]", minimum=0.001)
            high = _finite_number(bpm[1], "recipe.flavor.bpm[1]", minimum=0.001)
            if high <= low:
                raise RecipeValidationError(
                    "recipe.flavor.bpm must start below its upper bound"
                )
        else:
            _finite_number(bpm, "recipe.flavor.bpm", minimum=0.001)

    _optional_text(flavor.get("feel"), "recipe.flavor.feel")
    _optional_text(flavor.get("reference"), "recipe.flavor.reference")
    _optional_text(flavor.get("notes"), "recipe.flavor.notes")
    tags = flavor.get("tags")
    if tags is not None:
        _string_list(tags, "recipe.flavor.tags")


def _ingredients(ingredients: object, path_prefix: str = "recipe.ingredients") -> None:
    if not isinstance(ingredients, list) or not ingredients:
        raise RecipeValidationError(f"{path_prefix} must be a non-empty array")
    roles = set()
    for index, value in enumerate(ingredients):
        path = f"{path_prefix}[{index}]"
        ingredient = _object(value, path)
        unknown = sorted(
            set(ingredient)
            - {"role", "recipe", "kind", "source", "select", "constraints", "fallback"}
        )
        if unknown:
            raise RecipeValidationError(
                f"{path} has unknown key(s): {', '.join(unknown)}"
            )

        role = _text(ingredient.get("role"), f"{path}.role")
        if role in roles:
            raise RecipeValidationError(f"{path}.role duplicates role {role!r}")
        roles.add(role)

        kind = ingredient.get("kind")
        if kind is not None and kind not in ("recipe", "sample", "instrument"):
            raise RecipeValidationError(
                f"{path}.kind must be 'recipe', 'sample' or 'instrument'"
            )

        if "recipe" in ingredient:
            if kind not in (None, "recipe"):
                raise RecipeValidationError(
                    f"{path}.kind must be 'recipe' when a recipe id is given"
                )
            for field in ("source", "select", "constraints", "fallback"):
                if field in ingredient:
                    raise RecipeValidationError(
                        f"{path}.{field} cannot be combined with a recipe id"
                    )
            _text(ingredient.get("recipe"), f"{path}.recipe")
            continue

        if kind not in ("sample", "instrument"):
            raise RecipeValidationError(
                f"{path} must name a recipe or set kind to 'sample' or 'instrument'"
            )
        _text(ingredient.get("source"), f"{path}.source")
        _optional_text(ingredient.get("select"), f"{path}.select")
        _optional_text(ingredient.get("fallback"), f"{path}.fallback")
        constraints = ingredient.get("constraints")
        if constraints is not None:
            _plain_data(constraints, f"{path}.constraints")


def _steps(steps: object) -> None:
    if not isinstance(steps, list) or not steps:
        raise RecipeValidationError("recipe.steps must be a non-empty array")
    if len(steps) > MAX_STEPS:
        raise RecipeValidationError("recipe.steps is limited to %d" % MAX_STEPS)
    for index, value in enumerate(steps):
        path = f"recipe.steps[{index}]"
        step = _object(value, path)
        unknown = sorted(set(step) - {"tool", "args", "why"})
        if unknown:
            raise RecipeValidationError(
                f"{path} has unknown key(s): {', '.join(unknown)}"
            )
        _text(step.get("tool"), f"{path}.tool")
        args = step.get("args") or {}
        if not isinstance(args, dict):
            raise RecipeValidationError(f"{path}.args must be an object")
        if "dry_run" in args or "restore" in args:
            raise RecipeValidationError(
                f"{path} must not set dry_run or restore"
            )
        _optional_text(step.get("why"), f"{path}.why")


def _manual(manual: object) -> None:
    if manual is None or manual == []:
        return
    if not isinstance(manual, list):
        raise RecipeValidationError("recipe.manual must be an array")
    if len(manual) > MAX_MANUAL:
        raise RecipeValidationError("recipe.manual is limited to %d" % MAX_MANUAL)
    for index, value in enumerate(manual):
        path = f"recipe.manual[{index}]"
        entry = _object(value, path)
        unknown = sorted(set(entry) - {"instruction", "when", "verify", "why"})
        if unknown:
            raise RecipeValidationError(
                f"{path} has unknown key(s): {', '.join(unknown)}"
            )
        _text(entry.get("instruction"), f"{path}.instruction")
        when = entry.get("when", "before_verify")
        if when not in MANUAL_WHEN:
            raise RecipeValidationError(
                f"{path}.when must be one of: {', '.join(MANUAL_WHEN)}"
            )
        _optional_text(entry.get("verify"), f"{path}.verify")
        _optional_text(entry.get("why"), f"{path}.why")


def _expected(expected: object) -> None:
    if expected is None:
        return
    try:
        parse_fingerprint(expected)
    except FingerprintError as exc:
        raise RecipeValidationError(f"recipe.expected: {exc}") from exc


def _composition(data: Mapping) -> None:
    has_ingredients = "ingredients" in data
    has_parts = "parts" in data
    if has_ingredients and has_parts:
        raise RecipeValidationError(
            "recipe must use ingredients or parts, not both"
        )
    ingredients = data.get("ingredients") if has_ingredients else data.get("parts")
    steps = data.get("steps")
    if ingredients is None and steps is None:
        raise RecipeValidationError(
            "recipe must contain ingredients or steps when kind is combination, style or workflow"
        )
    if data["kind"] == "workflow" and steps is None:
        raise RecipeValidationError("workflow recipes must contain steps")
    if ingredients is not None:
        _ingredients(
            ingredients,
            "recipe.ingredients" if has_ingredients else "recipe.parts",
        )
    if steps is not None:
        _steps(steps)


def _rhythm(data: Mapping) -> None:
    tempo = _object(data.get("tempo"), "recipe.tempo")
    _finite_number(tempo.get("bpm"), "recipe.tempo.bpm", minimum=0.001)
    _text(tempo.get("feel"), "recipe.tempo.feel")
    grid = _text(tempo.get("grid"), "recipe.tempo.grid")
    # Unknown grids keep the legacy 16-step reading; the compiler is where a grid is refused.
    steps_per_bar = GRID_STEPS.get(grid, GRID_STEPS["1/16"])

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
        unknown = sorted(set(lane) - {"slot", "pattern", "velocity", "swing", "humanize"})
        if unknown:
            raise RecipeValidationError(
                f"{path} has unknown key(s): {', '.join(unknown)}"
            )
        try:
            bars = parse_step_pattern(
                _text(lane.get("pattern"), f"{path}.pattern"), steps_per_bar
            )
        except RecipePatternError as exc:
            raise RecipeValidationError(f"{path}.pattern: {exc}") from exc
        if length_bars % len(bars):
            raise RecipeValidationError(
                f"{path}.pattern has {len(bars)} bars, which does not divide "
                f"recipe.length_bars ({length_bars})"
            )
        limits = {"velocity": 1.0, "swing": 1.0, "humanize": 0.5}
        for field, high in limits.items():
            if field in lane:
                value = _finite_number(lane[field], f"{path}.{field}", minimum=0.0)
                if value > high:
                    raise RecipeValidationError(
                        f"{path}.{field} must be between 0 and {high:g}"
                    )

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
        unknown = sorted(set(slot) - {"slot", "mode", "from", "select", "count", "pitch"})
        if unknown:
            raise RecipeValidationError(
                f"{path} has unknown key(s): {', '.join(unknown)}"
            )
        _text(slot.get("from"), f"{path}.from")
        _text(slot.get("select"), f"{path}.select")
        _positive_integer(slot.get("count"), f"{path}.count")
        if "pitch" in slot:
            _integer_in_range(slot["pitch"], f"{path}.pitch", 0, 127)

    missing_slots = sorted(lane_slots - defined_slots)
    if missing_slots:
        raise RecipeValidationError(
            "recipe.lanes reference undefined slot(s): " + ", ".join(missing_slots)
        )


def _device_moves(moves: object, ingredients: list[Mapping]) -> None:
    """Machine writes for a processing recipe: an existing device, a parameter and a value."""
    if moves is None:
        return
    if not isinstance(moves, list) or not moves:
        raise RecipeValidationError("recipe.device_moves must be a non-empty array")
    if len(moves) > 8:
        raise RecipeValidationError("recipe.device_moves is limited to 8 entries")
    for index, move in enumerate(moves, start=1):
        path = "recipe.device_moves[%d]" % index
        entry = _object(move, path)
        unknown = sorted(set(entry) - {"role", "device", "parameter", "value", "why"})
        if unknown:
            raise RecipeValidationError(
                "%s has unknown key(s): %s" % (path, ", ".join(unknown))
            )
        role = _text(entry.get("role"), path + ".role")
        matched = [item for item in ingredients if item.get("role") == role]
        if not matched:
            raise RecipeValidationError(
                "%s.role must name one of the recipe's ingredients: %s"
                % (path, ", ".join(str(item.get("role")) for item in ingredients) or "none")
            )
        if matched[0].get("kind") not in ("instrument", "sample"):
            raise RecipeValidationError(
                "%s.role must name an instrument or sample ingredient" % path
            )
        _text(entry.get("device"), path + ".device")
        _text(entry.get("parameter"), path + ".parameter")
        _finite_number(entry.get("value"), path + ".value")
        _optional_text(entry.get("why"), path + ".why")


def _audition(audition: object, ingredients: list[Mapping]) -> None:
    """An audition is a short, playable phrase that a style recipe can write into a clip."""
    if audition is None:
        return
    data = _object(audition, "recipe.audition")
    unknown = sorted(set(data) - {"role", "length_beats", "notes"})
    if unknown:
        raise RecipeValidationError(
            "recipe.audition has unknown key(s): " + ", ".join(unknown)
        )
    role = _text(data.get("role"), "recipe.audition.role")
    matched = [item for item in ingredients if item.get("role") == role]
    if not matched:
        raise RecipeValidationError(
            "recipe.audition.role must name one of the recipe's ingredients: %s"
            % (", ".join(str(item.get("role")) for item in ingredients) or "none")
        )
    if matched[0].get("kind") not in ("instrument", "sample"):
        raise RecipeValidationError(
            "recipe.audition.role must name an instrument or sample ingredient"
        )
    length = _finite_number(
        data.get("length_beats", 4), "recipe.audition.length_beats", minimum=0.25
    )
    notes = data.get("notes")
    if not isinstance(notes, list) or not notes:
        raise RecipeValidationError("recipe.audition.notes must be a non-empty array")
    for index, note in enumerate(notes, start=1):
        path = "recipe.audition.notes[%d]" % index
        entry = _object(note, path)
        extra = sorted(set(entry) - {"pitch", "start", "duration", "velocity"})
        if extra:
            raise RecipeValidationError(
                "%s has unknown key(s): %s" % (path, ", ".join(extra))
            )
        _integer_in_range(entry.get("pitch"), path + ".pitch", 0, 127)
        start = _finite_number(entry.get("start"), path + ".start", minimum=0)
        duration = _finite_number(
            entry.get("duration"), path + ".duration", minimum=0.0001
        )
        if "velocity" in entry:
            _integer_in_range(entry["velocity"], path + ".velocity", 1, 127)
        if start + duration > length + 0.001:
            raise RecipeValidationError(
                "%s ends after recipe.audition.length_beats" % path
            )


def validate_recipe(recipe: object) -> None:
    """Validate common fields, the contract fields, and the payload selected by ``kind``."""
    data = _object(recipe, "recipe")
    for field in ("id", "name", "kind", "status"):
        _text(data.get(field), f"recipe.{field}")

    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise RecipeValidationError("recipe.version must be an integer")
    if version != 1:
        raise RecipeValidationError(f"unsupported recipe schema version: {version}")

    source = data.get("source")
    if source is not None:
        _source_metadata(source)
    _optional_text(data.get("description"), "recipe.description")
    _flavor(data)
    _tags(data)
    _expected(data.get("expected"))
    _manual(data.get("manual"))

    kind = data["kind"]
    if kind not in ("rhythm",) + PROCEDURAL_KINDS:
        raise RecipeValidationError(f"unsupported recipe kind: {kind}")
    if kind in PROCEDURAL_KINDS:
        _composition(data)
        ingredients = data.get("ingredients")
        if ingredients is None:
            ingredients = data.get("parts") or []
        _audition(data.get("audition"), list(ingredients))
        _device_moves(data.get("device_moves"), list(ingredients))
        if data.get("audition") is not None and data.get("device_moves") is not None:
            raise RecipeValidationError(
                "recipe cannot declare both an audition phrase and device_moves"
            )
    else:
        _rhythm(data)
        if "audition" in data or "device_moves" in data:
            raise RecipeValidationError(
                "recipe.audition and recipe.device_moves only apply to a style, workflow or "
                "combination recipe"
            )

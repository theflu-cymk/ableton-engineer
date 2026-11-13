"""Filesystem-backed recipe data storage with shipped/user separation."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .recipe_validation import RecipeValidationError, validate_recipe


class RecipeStoreError(ValueError):
    """A recipe could not be read, validated, or safely stored."""


_RECIPE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _merged_tags(recipe: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    values = list(recipe.get("tags") or [])
    flavor = recipe.get("flavor")
    if isinstance(flavor, dict):
        values.extend(flavor.get("tags") or [])
    for value in values:
        if not isinstance(value, str):
            continue
        key = value.strip().casefold()
        if key and key not in seen:
            seen.add(key)
            tags.append(value.strip())
    return sorted(tags, key=str.casefold)


def _bpm_range(recipe: dict[str, Any]) -> list[float] | None:
    flavor = recipe.get("flavor")
    value = flavor.get("bpm") if isinstance(flavor, dict) else None
    if value is None:
        tempo = recipe.get("tempo")
        value = tempo.get("bpm") if isinstance(tempo, dict) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return [number, number]
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            low, high = float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
        return [low, high]
    return None


def _recipe_children(recipe: dict[str, Any]) -> list[str]:
    raw = recipe.get("ingredients")
    if raw is None:
        raw = recipe.get("parts") or []
    children = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("recipe"), str):
            children.append(item["recipe"])
    return children


def _step_track_refs(recipe: dict[str, Any]) -> list[str]:
    refs: set[str] = set()
    for step in recipe.get("steps") or []:
        if not isinstance(step, dict):
            continue
        args = step.get("args")
        if not isinstance(args, dict):
            continue
        tracks = args.get("tracks")
        if isinstance(tracks, list):
            refs.update(
                value.strip() for value in tracks
                if isinstance(value, str) and value.strip()
            )
        for key in ("track", "to_track", "reference_track"):
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                refs.add(value.strip())
    return sorted(refs, key=str.casefold)


def _recipe_summary(recipe: dict[str, Any]) -> dict[str, Any]:
    raw_flavor = recipe.get("flavor")
    flavor = raw_flavor if isinstance(raw_flavor, dict) else {}
    tempo = recipe.get("tempo")
    tempo = tempo if isinstance(tempo, dict) else {}
    return {
        "name": recipe["name"],
        "kind": recipe["kind"],
        "status": recipe["status"],
        "version": recipe["version"],
        "description": recipe.get("description") or "",
        "notes": recipe.get("notes") or "",
        "tags": _merged_tags(recipe),
        "flavor": raw_flavor if isinstance(raw_flavor, str) else flavor.get("name"),
        "feel": flavor.get("feel") or tempo.get("feel"),
        "bpm": _bpm_range(recipe),
        "grid": tempo.get("grid"),
        "length_bars": recipe.get("length_bars"),
        "steps": len(recipe.get("steps") or []),
        "manual": len(recipe.get("manual") or []),
        "ingredients": _recipe_children(recipe),
        "has_expected": bool(recipe.get("expected")),
    }


def _recipe_compilable(
    recipe: dict[str, Any],
    recipes: dict[str, dict[str, Any]],
    seen: set[str],
) -> bool:
    """Whether this recipe has executable steps, directly or through child recipes."""
    recipe_id = recipe.get("id")
    if isinstance(recipe_id, str):
        if recipe_id in seen:
            return False
        seen.add(recipe_id)
    if recipe.get("kind") == "rhythm":
        return True
    if recipe.get("steps"):
        return True
    for child_id in _recipe_children(recipe):
        child = recipes.get(child_id)
        if child is not None and _recipe_compilable(child, recipes, seen):
            return True
    return False


def _recipe_dependencies(
    recipe: dict[str, Any],
    recipes: dict[str, dict[str, Any]],
    seen: set[str],
) -> tuple[list[str], bool]:
    recipe_id = recipe.get("id")
    if isinstance(recipe_id, str):
        if recipe_id in seen:
            return [], False
        seen.add(recipe_id)
    refs = set(_step_track_refs(recipe))
    needs_target = recipe.get("kind") == "rhythm"
    for child_id in _recipe_children(recipe):
        child = recipes.get(child_id)
        if child is None:
            continue
        child_refs, child_target = _recipe_dependencies(child, recipes, seen)
        refs.update(child_refs)
        needs_target = needs_target or child_target
    return sorted(refs, key=str.casefold), needs_target


def _recipe_id(value: object) -> str:
    if not isinstance(value, str) or not _RECIPE_ID.fullmatch(value):
        raise RecipeStoreError("recipe id must contain only letters, digits, '.', '_' or '-'")
    if value in (".", ".."):
        raise RecipeStoreError("recipe id must not be a path component")
    return value


class RecipeStore:
    """Read shipped recipes and user overrides from explicitly configured directories."""

    def __init__(
        self,
        shipped_dir: str | os.PathLike[str],
        user_dir: str | os.PathLike[str],
    ):
        self.shipped_dir = Path(shipped_dir)
        self.user_dir = Path(user_dir)

    @staticmethod
    def _read(path: Path, expected_id: str) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as source:
                recipe = json.load(source)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RecipeStoreError(f"cannot read recipe {path.name}: {exc}") from exc
        try:
            validate_recipe(recipe)
        except RecipeValidationError as exc:
            raise RecipeStoreError(f"invalid recipe {path.name}: {exc}") from exc
        if recipe["id"] != expected_id:
            raise RecipeStoreError(
                f"recipe id {recipe['id']!r} does not match filename id {expected_id!r}"
            )
        return recipe

    @staticmethod
    def _files(directory: Path) -> dict[str, Path]:
        try:
            paths = directory.glob("*.json")
            return {path.stem: path for path in paths if path.is_file()}
        except OSError as exc:
            raise RecipeStoreError(f"cannot list recipe directory {directory}: {exc}") from exc

    def list(self) -> list[dict[str, str]]:
        """List recipe IDs, names and kinds, with user recipes overriding shipped IDs."""
        files = self._files(self.shipped_dir)
        files.update(self._files(self.user_dir))
        rows = []
        for recipe_id, path in sorted(files.items()):
            _recipe_id(recipe_id)
            recipe = self._read(path, recipe_id)
            rows.append(
                {
                    "id": recipe_id,
                    "name": recipe["name"],
                    "kind": recipe["kind"],
                    "status": recipe["status"],
                    "source": "user" if path.parent == self.user_dir else "shipped",
                }
            )
        return rows

    def catalog(self) -> list[dict[str, Any]]:
        """Return browsable summaries, keeping one broken recipe from hiding the rest.

        ``list`` remains the strict tool-facing read. The panel needs a catalog that survives a
        hand-edited user file, so an invalid recipe becomes a row with ``status: invalid`` and an
        error instead of failing the whole directory.
        """
        files = self._files(self.shipped_dir)
        files.update(self._files(self.user_dir))
        recipes: dict[str, dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []
        for recipe_id, path in sorted(files.items()):
            source = "user" if path.parent == self.user_dir else "shipped"
            modified = None
            try:
                modified = path.stat().st_mtime
            except OSError:
                pass
            row: dict[str, Any] = {
                "id": recipe_id,
                "name": recipe_id,
                "kind": "invalid",
                "status": "invalid",
                "source": source,
                "version": None,
                "description": "",
                "notes": "",
                "tags": [],
                "flavor": None,
                "feel": None,
                "bpm": None,
                "grid": None,
                "length_bars": None,
                "steps": 0,
                "manual": 0,
                "ingredients": [],
                "has_expected": False,
                "compilable": False,
                "needs_target": False,
                "track_refs": [],
                "modified": modified,
                "overrides": source == "user" and (self.shipped_dir / path.name).is_file(),
            }
            try:
                recipe = self._read(path, recipe_id)
            except RecipeStoreError as exc:
                row["error"] = str(exc)
                rows.append(row)
                continue

            recipes[recipe_id] = recipe
            row.update(_recipe_summary(recipe))
            rows.append(row)

        for row in rows:
            recipe = recipes.get(row["id"])
            if recipe is None:
                continue
            refs, needs_target = _recipe_dependencies(recipe, recipes, set())
            row["track_refs"] = refs
            row["needs_target"] = needs_target
            row["compilable"] = _recipe_compilable(recipe, recipes, set())
        return rows

    def show(self, recipe_id: str) -> dict[str, Any]:
        """Return a validated user override or shipped recipe by stable ID."""
        recipe_id = _recipe_id(recipe_id)
        user_path = self.user_dir / f"{recipe_id}.json"
        shipped_path = self.shipped_dir / f"{recipe_id}.json"
        path = user_path if user_path.is_file() else shipped_path
        if not path.is_file():
            raise RecipeStoreError(f"no recipe with id {recipe_id!r}")
        return self._read(path, recipe_id)

    def save_user(self, recipe: object) -> Path:
        """Atomically save a validated user recipe without changing shipped data."""
        try:
            validate_recipe(recipe)
        except RecipeValidationError as exc:
            raise RecipeStoreError(f"invalid user recipe: {exc}") from exc
        data = dict(recipe)
        recipe_id = _recipe_id(data["id"])
        self.user_dir.mkdir(parents=True, exist_ok=True)
        target = self.user_dir / f"{recipe_id}.json"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.user_dir,
                prefix=f".{recipe_id}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temp_path = Path(output.name)
                json.dump(data, output, ensure_ascii=False, indent=2, allow_nan=False)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_path, target)
        except (OSError, TypeError, ValueError) as exc:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    raise RecipeStoreError(
                        f"cannot save user recipe {recipe_id!r}; temporary-file cleanup "
                        f"also failed: {cleanup_error}"
                    ) from exc
            raise RecipeStoreError(f"cannot save user recipe {recipe_id!r}: {exc}") from exc
        return target

    def delete_user(self, recipe_id: str) -> bool:
        """Delete a user recipe only; a same-ID shipped recipe is never removed."""
        recipe_id = _recipe_id(recipe_id)
        path = self.user_dir / f"{recipe_id}.json"
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise RecipeStoreError(f"cannot delete user recipe {recipe_id!r}: {exc}") from exc
        return True

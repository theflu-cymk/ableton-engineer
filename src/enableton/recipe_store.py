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
        """List recipe IDs and names, with user recipes overriding shipped IDs."""
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
                    "status": recipe["status"],
                    "source": "user" if path.parent == self.user_dir else "shipped",
                }
            )
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

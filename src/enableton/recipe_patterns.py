"""Pure parsing for the documented text recipe pattern format."""

from __future__ import annotations

#: Steps per 4/4 bar for every documented grid. Triplet grids use the same one-character-per-step
#: grammar with fewer (1/8T) or more (1/16T) steps in the bar, not a separate notation.
GRID_STEPS = {"1/16": 16, "1/8T": 12, "1/16T": 24}


class RecipePatternError(ValueError):
    """A recipe pattern does not follow the documented step grammar."""


def parse_step_pattern(
    pattern: str, steps_per_bar: int = GRID_STEPS["1/16"]
) -> tuple[tuple[str, ...], ...]:
    """Parse step bars containing hits, accents, ghosts, and rests.

    ``steps_per_bar`` follows the recipe's declared grid (16 for 1/16, 12 for 1/8T, 24 for 1/16T).
    A bar separator is optional, but when present each section must contain exactly that many steps.
    This parser does not infer a recipe's loop count or create Live clips.
    """
    if not isinstance(pattern, str) or not pattern:
        raise RecipePatternError("pattern must be a non-empty string")
    if (
        isinstance(steps_per_bar, bool)
        or not isinstance(steps_per_bar, int)
        or steps_per_bar < 1
    ):
        raise RecipePatternError("steps_per_bar must be a positive integer")

    if any(symbol not in "xXo.|" for symbol in pattern):
        raise RecipePatternError("pattern may contain only x, X, o, ., and |")

    if "|" in pattern:
        bars = pattern.split("|")
    else:
        if len(pattern) % steps_per_bar:
            raise RecipePatternError(
                "each pattern bar must contain exactly %d steps" % steps_per_bar
            )
        bars = [
            pattern[offset : offset + steps_per_bar]
            for offset in range(0, len(pattern), steps_per_bar)
        ]

    if any(len(bar) != steps_per_bar for bar in bars):
        raise RecipePatternError(
            "each pattern bar must contain exactly %d steps" % steps_per_bar
        )

    return tuple(tuple(bar) for bar in bars)

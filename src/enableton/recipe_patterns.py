"""Pure parsing for the documented text recipe pattern format."""

from __future__ import annotations


class RecipePatternError(ValueError):
    """A recipe pattern does not follow the documented step grammar."""


def parse_step_pattern(pattern: str) -> tuple[tuple[str, ...], ...]:
    """Parse 16-step bars containing hits, accents, ghosts, and rests.

    A bar separator is optional, but when present each section must contain exactly 16 steps.
    This parser does not infer a recipe's loop count or create Live clips.
    """
    if not isinstance(pattern, str) or not pattern:
        raise RecipePatternError("pattern must be a non-empty string")

    if any(symbol not in "xXo.|" for symbol in pattern):
        raise RecipePatternError("pattern may contain only x, X, o, ., and |")

    if "|" in pattern:
        bars = pattern.split("|")
    else:
        if len(pattern) % 16:
            raise RecipePatternError("each pattern bar must contain exactly 16 steps")
        bars = [pattern[offset : offset + 16] for offset in range(0, len(pattern), 16)]

    if any(len(bar) != 16 for bar in bars):
        raise RecipePatternError("each pattern bar must contain exactly 16 steps")

    return tuple(tuple(bar) for bar in bars)

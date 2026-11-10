"""Modes are views over the catalogue, never owners of it.

A mode names tools; it never defines behaviour. Two modes naming the same tool share one
implementation, which is what stops duplicated capability creeping in. The invariants below are
the whole reason this file exists as code rather than a dictionary literal:

- every tool in a mode exists in the catalogue
- a mode never exceeds the cap (a long tool list is how a model starts picking the wrong one)
- every catalogue tool appears in at least one mode (an unreachable tool is dead weight)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .manifest import ManifestError, Tool


class ModeError(Exception):
    """A mode is malformed or violates a mode invariant."""


@dataclass(frozen=True)
class Mode:
    name: str
    summary: str
    declared: Tuple[str, ...]
    tools: Tuple[str, ...]
    default_scope: str
    escalate: bool
    examples: Tuple[str, ...] = ()

    def tool_specs(self, catalogue: Dict[str, Tool]):
        from .manifest import to_mcp_tools

        return to_mcp_tools(catalogue, self.tools)


@dataclass(frozen=True)
class ModeSet:
    modes: Dict[str, Mode]
    default: str
    max_tools: int

    def get(self, name: Optional[str] = None) -> Mode:
        if name is None:
            return self.modes[self.default]
        if name not in self.modes:
            raise ModeError(
                "unknown mode %r; available: %s" % (name, ", ".join(sorted(self.modes)))
            )
        return self.modes[name]

    def names(self) -> List[str]:
        return sorted(self.modes)


def load_modes(
    catalogue: Dict[str, Tool],
    path: Optional[Path] = None,
    max_tools: Optional[int] = None,
) -> ModeSet:
    path = path or Path(__file__).with_name("modes.json")
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    cap = max_tools or int(raw.get("validation", {}).get("max_tools_per_mode", 34))
    core: Sequence[str] = tuple(raw.get("core_tools", ()))

    for name in core:
        if name not in catalogue:
            raise ModeError("core tool %r is not in the catalogue" % name)

    entries = raw.get("modes")
    if not isinstance(entries, list) or not entries:
        raise ModeError("%s: 'modes' must be a non-empty list" % path)

    modes: Dict[str, Mode] = {}
    covered = set()

    for entry in entries:
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ModeError("mode without a name in %s" % path)
        if name in modes:
            raise ModeError("duplicate mode %r" % name)

        declared = tuple(entry.get("tools", ()))
        for tool_name in declared:
            if tool_name not in catalogue:
                raise ModeError("mode %r names unknown tool %r" % (name, tool_name))

        # Core tools are always loaded; a mode may name them again without harm.
        resolved: List[str] = []
        for tool_name in tuple(core) + declared:
            if tool_name not in resolved:
                resolved.append(tool_name)

        if len(resolved) > cap:
            raise ModeError(
                "mode %r exposes %d tools, cap is %d" % (name, len(resolved), cap)
            )

        covered.update(resolved)
        modes[name] = Mode(
            name=name,
            summary=entry.get("summary", ""),
            declared=declared,
            tools=tuple(resolved),
            default_scope=entry.get("default_scope", "set"),
            escalate=bool(entry.get("escalate", True)),
            examples=tuple(entry.get("examples", ())),
        )

    unreachable = sorted(set(catalogue) - covered - set(core))
    if unreachable:
        raise ModeError("tools in no mode: %s" % ", ".join(unreachable))

    default = raw.get("default") or ("auto" if "auto" in modes else sorted(modes)[0])
    if default not in modes:
        raise ModeError("default mode %r is not defined" % default)

    return ModeSet(modes=modes, default=default, max_tools=cap)


def guide(catalogue: Dict[str, Tool], mode_name: Optional[str] = None) -> Dict[str, object]:
    """Build the command sheet for one mode, shared by the tool and the CLI."""
    modes = load_modes(catalogue)
    mode = modes.get(mode_name)
    return {
        "mode": mode.name,
        "tools": [
            {
                "tool": name,
                "summary": catalogue[name].summary,
                "examples": catalogue[name].examples,
            }
            for name in mode.tools
        ],
    }


__all__ = ["Mode", "ModeError", "ModeSet", "guide", "load_modes", "ManifestError"]

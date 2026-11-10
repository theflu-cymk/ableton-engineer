"""The tool manifest: one file, one source of truth.

Everything downstream is derived from ``tools.json`` — the MCP tool definitions, the Remote
Script dispatch table (checked by ``tests/test_drift.py``), the guide sheet and the CLI help.
Validation here is deliberately strict: a tool that is half-declared fails at startup, not at
call time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
REQUIRED = (
    "name",
    "domain",
    "summary",
    "description",
    "input",
    "timeout_ms",
    "writes",
    "reversible",
    "needs",
    "min_live",
    "cmd",
)


class ManifestError(Exception):
    """A tool definition is malformed, duplicated or inconsistent."""


@dataclass(frozen=True)
class Tool:
    name: str
    domain: str
    summary: str
    description: str
    input: Dict[str, Any]
    timeout_ms: int
    writes: bool
    reversible: bool
    needs: List[str] = field(default_factory=list)
    min_live: Optional[str] = None
    cmd: Optional[str] = None
    examples: List[str] = field(default_factory=list)

    @property
    def local(self) -> bool:
        """True for tools the server answers without asking Live."""
        return self.cmd is None


def _require(entry: Dict[str, Any], key: str) -> Any:
    if key not in entry:
        raise ManifestError("tool %r is missing %r" % (entry.get("name", "<unnamed>"), key))
    return entry[key]


def _validate(entry: Dict[str, Any]) -> Tool:
    for key in REQUIRED:
        _require(entry, key)

    name = entry["name"]
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ManifestError("bad tool name %r: expected domain_verb" % (name,))

    if not isinstance(entry["input"], dict) or entry["input"].get("type") != "object":
        raise ManifestError("tool %r: input must be a JSON Schema object" % name)

    timeout = entry["timeout_ms"]
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ManifestError("tool %r: timeout_ms must be a positive integer" % name)

    for flag in ("writes", "reversible"):
        if not isinstance(entry[flag], bool):
            raise ManifestError("tool %r: %s must be a boolean" % (name, flag))

    if not isinstance(entry["needs"], list):
        raise ManifestError("tool %r: needs must be a list" % name)

    cmd = entry["cmd"]
    if cmd is not None and (not isinstance(cmd, str) or not cmd):
        raise ManifestError("tool %r: cmd must be a string or null" % name)

    examples = entry.get("examples", [])
    if not isinstance(examples, list) or not all(isinstance(e, str) for e in examples):
        raise ManifestError("tool %r: examples must be a list of strings" % name)

    return Tool(
        name=name,
        domain=entry["domain"],
        summary=entry["summary"],
        description=entry["description"],
        input=entry["input"],
        timeout_ms=timeout,
        writes=entry["writes"],
        reversible=entry["reversible"],
        needs=list(entry["needs"]),
        min_live=entry["min_live"],
        cmd=cmd,
        examples=list(examples),
    )


def load_manifest(path: Optional[Path] = None) -> Dict[str, Tool]:
    """Load and validate ``tools.json``, returning an ordered name -> Tool map."""
    path = path or Path(__file__).with_name("tools.json")
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    entries = raw.get("tools")
    if not isinstance(entries, list) or not entries:
        raise ManifestError("%s: 'tools' must be a non-empty list" % path)

    catalogue: Dict[str, Tool] = {}
    for entry in entries:
        tool = _validate(entry)
        if tool.name in catalogue:
            raise ManifestError("duplicate tool name %r" % tool.name)
        catalogue[tool.name] = tool
    return catalogue


def remote_commands(catalogue: Dict[str, Tool]) -> Iterable[str]:
    """The script commands this manifest requires, sorted for stable assertions."""
    return sorted({t.cmd for t in catalogue.values() if t.cmd})


def to_mcp_tools(catalogue: Dict[str, Tool], names: Iterable[str]) -> List[Dict[str, Any]]:
    """Project the named tools into MCP ``tools/list`` entries."""
    out = []
    for name in names:
        tool = catalogue[name]
        out.append(
            {
                "name": tool.name,
                "description": tool.summary + "\n\n" + tool.description,
                "inputSchema": tool.input,
                "annotations": {
                    "readOnlyHint": not tool.writes,
                    "destructiveHint": tool.writes and not tool.reversible,
                    "idempotentHint": tool.reversible,
                },
            }
        )
    return out

"""The one place a tool name becomes work.

Local tools answer from a cached snapshot; remote tools are one script command. Keeping this in
a single function stops the MCP layer, the CLI and the tests drifting on what a tool call means
— which is the failure that turns a mode list into a lie.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .manifest import load_manifest
from .protocol.codes import LiveError
from .reports import (
    ReportError, levels, mix_headroom, structure, summary_from_snapshot, unused, warp_check,
)
from .state.snapshot import SnapshotCache

LOCAL = {
    "inspect_structure": structure,
    "inspect_unused": unused,
    "mix_levels_report": levels,
    "mix_headroom": mix_headroom,
    "clips_warp_check": warp_check,
}  # type: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]]

#: Tools whose script command returns more than the tool promises. A tool's output must match its
#: description, so projection happens here rather than in every caller.
PROJECT = {"ableton_status": summary_from_snapshot}


def run_tool(
    name: str,
    args: Optional[Dict[str, Any]] = None,
    adapter: Any = None,
    catalogue: Optional[Dict[str, Any]] = None,
    cache: Optional[SnapshotCache] = None,
) -> Dict[str, Any]:
    """Run one tool by name, local or remote, with the manifest's own timeout."""
    catalogue = catalogue or load_manifest()
    tool = catalogue.get(name)
    if tool is None:
        raise LiveError("UNKNOWN_COMMAND", "Enableton has no tool %r" % (name,))

    args = dict(args or {})
    if not isinstance(args, dict):
        raise LiveError("BAD_ARGS", "arguments must be an object")

    cache = cache or SnapshotCache(adapter)

    if tool.local:
        handler = LOCAL.get(name)
        if handler is None:
            raise LiveError(
                "UNSUPPORTED", "tool %r has no server-side implementation yet" % (name,)
            )
        try:
            return handler(cache.get(), args)
        except ReportError as exc:
            raise LiveError("BAD_ARGS", str(exc))

    result = adapter.call(tool.cmd, args, timeout_ms=tool.timeout_ms)
    if tool.writes:
        cache.invalidate()

    project = PROJECT.get(name)
    return project(result) if project is not None else result

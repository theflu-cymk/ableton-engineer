"""The one place a tool name becomes work.

Local tools answer from a cached snapshot; remote tools are one script command. Keeping this in
a single function stops the MCP layer, the CLI and the tests drifting on what a tool call means
— which is the failure that turns a mode list into a lie.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .manifest import load_manifest
from .plans.executor import PlanError, PlanExecutor, Step
from .protocol.codes import LiveError
from .reports import (
    ReportError, levels, mix_headroom, notes_overlaps, structure, summary_from_snapshot, unused,
    warp_check,
)
from .state.snapshot import SnapshotCache

LOCAL = {
    "inspect_structure": structure,
    "inspect_unused": unused,
    "mix_levels_report": levels,
    "mix_headroom": mix_headroom,
    "clips_warp_check": warp_check,
    "notes_overlaps": notes_overlaps,
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
    backup_root: Optional[str] = None,
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

    # Bulk writes with a dry-run switch go through the M2 transaction path: preflight, a scratch
    # copy before the first applied call, and rollback from the tool's own undo tokens.
    if tool.writes and not args.get("dry_run", True) and "dry_run" in (
        tool.input.get("properties") or {}
    ):
        try:
            snapshot = cache.get()
            set_path = (snapshot.get("song") or {}).get("file_path")
            outcome = PlanExecutor(
                adapter, set_path=set_path, backup_root=backup_root
            ).apply([Step(name, args)])
        except PlanError as exc:
            raise LiveError(exc.code, exc.message, exc.detail)

        cache.invalidate()
        if outcome.get("already_applied"):
            return dict(outcome["results"][-1])
        if not outcome.get("applied"):
            error = outcome.get("error") or {}
            restore = outcome.get("restore") or {}
            detail = {
                "error": error,
                "restore": restore,
                "scratch_copy": outcome.get("scratch_copy"),
            }
            message = (
                "write failed and was rolled back"
                if restore.get("ok")
                else "write failed; rollback needs attention"
            )
            raise LiveError("LIVE_ERROR", message, detail)

        result = dict(outcome["results"][-1])
        result["scratch_copy"] = outcome.get("scratch_copy")
        return result

    result = adapter.call(tool.cmd, args, timeout_ms=tool.timeout_ms)
    if tool.writes:
        cache.invalidate()

    project = PROJECT.get(name)
    return project(result) if project is not None else result

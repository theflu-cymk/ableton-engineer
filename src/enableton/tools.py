"""The one place a tool name becomes work.

Local tools answer from a cached snapshot; remote tools are one script command. Keeping this in
a single function stops the MCP layer, the CLI and the tests drifting on what a tool call means
— which is the failure that turns a mode list into a lie.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from . import diagnostics, escalation
from .manifest import load_manifest
from .modes import ModeError, guide as build_guide
from .plans import PlanStore, PlanStoreError, TransactionStore, undo_transaction
from .plans.executor import PlanError, PlanExecutor, Step
from .protocol.codes import LiveError
from .reports import (
    ReportError, devices_read_chain, levels, master_chain_read, mix_headroom, notes_overlaps,
    sections_map, structure, summary_from_snapshot, unused, warp_check,
)
from .state.snapshot import SnapshotCache

LOCAL = {
    "inspect_structure": structure,
    "inspect_unused": unused,
    "mix_levels_report": levels,
    "mix_headroom": mix_headroom,
    "clips_warp_check": warp_check,
    "notes_overlaps": notes_overlaps,
    "devices_read_chain": devices_read_chain,
    "master_chain_read": master_chain_read,
    "sections_map": sections_map,
    "inspect_run": diagnostics.run,
    "inspect_report": diagnostics.report,
    "inspect_export": diagnostics.export,
    "inspect_finding": diagnostics.get,
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
    plan_root: Optional[str] = None,
    transaction_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one tool by name, local or remote, with the manifest's own timeout."""
    catalogue = catalogue or load_manifest()
    tool = catalogue.get(name)
    if tool is None:
        raise LiveError("UNKNOWN_COMMAND", "Enableton has no tool %r" % (name,))

    args = dict(args or {})
    if not isinstance(args, dict):
        raise LiveError("BAD_ARGS", "arguments must be an object")

    if name == "ableton_guide":
        unknown = sorted(set(args) - {"mode"})
        if unknown:
            raise LiveError("BAD_ARGS", "unknown argument(s): %s" % ", ".join(unknown))
        try:
            return build_guide(catalogue, args.get("mode"))
        except ModeError as exc:
            raise LiveError("BAD_ARGS", str(exc))

    cache = cache or SnapshotCache(adapter)

    if name == "ableton_status":
        snapshot = adapter.call(tool.cmd, args, timeout_ms=tool.timeout_ms)
        result = summary_from_snapshot(snapshot)
        # Counts come from this same read, not a second snapshot fetch.
        result["findings"] = diagnostics.counts(
            diagnostics.detect(snapshot, "standard")
        )
        return result

    if tool.local:
        try:
            if name == "inspect_autofix":
                return diagnostics.autofix(
                    adapter, cache, args, catalogue, backup_root=backup_root
                )
            if name == "inspect_plan":
                return diagnostics.plan(cache.get(), args, catalogue)
            if name == "ableton_escalate":
                return escalation.escalate(
                    cache.get(), args, catalogue, PlanStore(root=plan_root)
                )
            if name == "ableton_plan_apply":
                return escalation.apply_plan(
                    adapter, cache, args, PlanStore(root=plan_root), catalogue, backup_root,
                    transaction_root=transaction_root,
                )
            if name == "ableton_plan_discard":
                return escalation.discard_plan(args, PlanStore(root=plan_root))
            if name == "ableton_undo":
                return undo_transaction(
                    adapter, cache, args, catalogue,
                    TransactionStore(root=transaction_root),
                )
            handler = LOCAL.get(name)
            if handler is None:
                raise LiveError(
                    "UNSUPPORTED", "tool %r has no server-side implementation yet" % (name,)
                )
            return handler(cache.get(), args)
        except (
            ReportError, diagnostics.DiagnosticsError, escalation.EscalationError,
            PlanStoreError,
        ) as exc:
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
                adapter, set_path=set_path, backup_root=backup_root,
                transaction_store=TransactionStore(root=transaction_root),
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
            # Surface the tool's own code and message: a delete without confirm is
            # PRECONDITION_FAILED with an instruction, not a generic rollback notice.
            code = error.get("code") or "LIVE_ERROR"
            message = error.get("message") or "write failed"
            message += " (rolled back)" if restore.get("ok") else "; rollback needs attention"
            raise LiveError(code, message, detail)

        result = dict(outcome["results"][-1])
        result["scratch_copy"] = outcome.get("scratch_copy")
        return result

    result = adapter.call(tool.cmd, args, timeout_ms=tool.timeout_ms)
    if tool.writes:
        cache.invalidate()

    project = PROJECT.get(name)
    return project(result) if project is not None else result

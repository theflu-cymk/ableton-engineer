"""The one place a tool name becomes work.

Local tools answer from a cached snapshot; remote tools are one script command. Keeping this in
a single function stops the MCP layer, the CLI and the tests drifting on what a tool call means
— which is the failure that turns a mode list into a lie.
"""

from __future__ import annotations

import threading
import time
import weakref
from typing import Any, Callable, Dict, Optional

from . import diagnostics, escalation
from .audio_analysis import AudioAnalysisError, analyze_wave
from .manifest import load_manifest
from .modes import ModeError, guide as build_guide
from .plans import PlanStore, PlanStoreError, TransactionStore, undo_transaction
from .plans.executor import PlanError, PlanExecutor, Step
from .producer import session_brief
from .protocol.codes import LiveError
from .recipe_store import RecipeStore
from .recipe_tools import (
    apply_recipe, list_recipes, save_recipe, show_recipe, verify_recipe,
)
from .reference import reference_analyze
from .reports import (
    ReportError, devices_read_chain, levels, master_chain_read, mix_headroom, notes_overlaps,
    sections_map, structure, summary_from_snapshot, track_inspect, unused, warp_check,
)
from .state.snapshot import SnapshotCache
from .takes import create_takes, discard_takes, select_takes

LOCAL = {
    "session_brief": session_brief,
    "reference_analyze": lambda _snapshot, args: reference_analyze(args),
    "inspect_structure": structure,
    "tracks_inspect": track_inspect,
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

def _launch_acknowledgement(result: Dict[str, Any]) -> Dict[str, Any]:
    """Drop Live's pre-quantization Clip.is_playing readback.

    Fire and stop are command acknowledgements. On real Live the clip's is_playing flag can still
    describe the state before the launch or stop quantum, so returning it next to ``fired`` or
    ``stopped`` reads as a contradiction. The acknowledgement is what the tool promises.
    """
    projected = dict(result)
    projected.pop("is_playing", None)
    return projected


#: Tools whose script command returns more than the tool promises. A tool's output must match its
#: description, so projection happens here rather than in every caller.
PROJECT = {
    "ableton_status": summary_from_snapshot,
    "clips_fire": _launch_acknowledgement,
    "clips_stop": _launch_acknowledgement,
}

#: One applied outcome per (adapter, Set), used to recognise an immediate retry. A different
#: successful write replaces the slot, and a successful undo clears it, so an intentional repeat
#: after either still writes.
_APPLIED_SLOTS = weakref.WeakKeyDictionary()
_APPLIED_LOCK = threading.Lock()


def _applied_slot(adapter: Any, set_path: Optional[str]) -> Optional[Dict[str, Any]]:
    if adapter is None:
        return None
    with _APPLIED_LOCK:
        by_set = _APPLIED_SLOTS.get(adapter)
        if by_set is None:
            by_set = {}
            _APPLIED_SLOTS[adapter] = by_set
        return by_set.setdefault(set_path or "", {})


def _clear_applied_slots(adapter: Any) -> None:
    if adapter is None:
        return
    with _APPLIED_LOCK:
        _APPLIED_SLOTS.pop(adapter, None)


def _with_analysis(result: Dict[str, Any]) -> Dict[str, Any]:
    """Attach the local PCM analysis to a capture result, or the reason it could not run."""
    path = result.get("file_path")
    if not result.get("recorded") or not path:
        return result
    reason = None
    for attempt in range(5):
        try:
            result["analysis"] = analyze_wave(path)
            return result
        except AudioAnalysisError as exc:
            reason = str(exc)
            # Live can still hold the recorded WAV when the capture returns. Retry the
            # permission failure briefly instead of reporting a good file as unreadable.
            if "Permission denied" in reason and attempt < 4:
                time.sleep(0.5)
                continue
            break
    result["analysis"] = {"measured": False, "reason": reason}
    return result


def run_tool(
    name: str,
    args: Optional[Dict[str, Any]] = None,
    adapter: Any = None,
    catalogue: Optional[Dict[str, Any]] = None,
    cache: Optional[SnapshotCache] = None,
    backup_root: Optional[str] = None,
    plan_root: Optional[str] = None,
    transaction_root: Optional[str] = None,
    recipe_store: Optional[RecipeStore] = None,
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
        unknown = sorted(set(args) - {"mode", "scope", "detail"})
        if unknown:
            raise LiveError("BAD_ARGS", "unknown argument(s): %s" % ", ".join(unknown))
        try:
            return build_guide(
                catalogue,
                args.get("mode"),
                scope=args.get("scope", "mode"),
                detail=args.get("detail", "brief"),
            )
        except ModeError as exc:
            raise LiveError("BAD_ARGS", str(exc))

    if name == "reference_analyze":
        # File measurement must work even when Live is closed.
        return reference_analyze(args)

    cache = cache or SnapshotCache(adapter)

    if name in ("recipe_list", "recipe_show", "recipe_save"):
        return {
            "recipe_list": list_recipes,
            "recipe_show": show_recipe,
            "recipe_save": save_recipe,
        }[name](args, store=recipe_store)

    if name == "recipe_apply":
        return apply_recipe(
            args,
            store=recipe_store,
            adapter=adapter,
            cache=cache,
            plan_root=plan_root,
            catalogue=catalogue,
        )

    if name == "recipe_verify":
        return verify_recipe(
            args,
            store=recipe_store,
            cache=cache if adapter is not None else None,
        )

    if name == "ableton_status":
        snapshot = adapter.call(tool.cmd, args, timeout_ms=tool.timeout_ms)
        result = summary_from_snapshot(snapshot)
        # Counts come from this same read, not a second snapshot fetch.
        result["findings"] = diagnostics.counts(
            diagnostics.detect(snapshot, "standard")
        )
        return result

    if name == "mix_resample_capture":
        # A capture is not a replayable write: the M2 preflight/apply trace comparison cannot
        # apply to a recording that happens once. The handler owns its own restore, so it runs
        # directly and the local analyzer reads the WAV it produced.
        result = adapter.call(tool.cmd, args, timeout_ms=tool.timeout_ms)
        if not args.get("dry_run", True):
            cache.invalidate()
        return _with_analysis(result)

    if name == "takes_create":
        if adapter is None:
            raise LiveError("UNSUPPORTED", "takes_create needs a connected Live adapter")
        try:
            return create_takes(adapter, cache, args)
        except LiveError:
            raise

    if name in ("takes_select", "takes_discard"):
        if adapter is None:
            raise LiveError("UNSUPPORTED", "%s needs a connected Live adapter" % (name,))
        handler = select_takes if name == "takes_select" else discard_takes
        try:
            return handler(adapter, cache, args)
        except LiveError:
            raise

    if tool.local:
        try:
            if name == "mix_headroom":
                # Faders come from the snapshot; peaks need one live meter window. Joining them
                # here keeps the report a pure function of its inputs and out of the script.
                snapshot = cache.get()
                meters = None
                if args.get("measure", True):
                    meters = adapter.call(
                        "mix.meter_poll",
                        {"ms": args.get("ms", 200)},
                        timeout_ms=3000,
                    )
                return mix_headroom(snapshot, args, meters=meters)
            if name == "inspect_autofix":
                return diagnostics.autofix(
                    adapter, cache, args, catalogue, backup_root=backup_root
                )
            if name == "inspect_plan":
                return diagnostics.plan(cache.get(), args, catalogue)
            if name == "ableton_escalate":
                return escalation.escalate(
                    cache.get(), args, catalogue, PlanStore(root=plan_root), adapter=adapter
                )
            if name == "ableton_plan_apply":
                return escalation.apply_plan(
                    adapter, cache, args, PlanStore(root=plan_root), catalogue, backup_root,
                    transaction_root=transaction_root,
                )
            if name == "ableton_plan_discard":
                return escalation.discard_plan(args, PlanStore(root=plan_root))
            if name == "ableton_undo":
                result = undo_transaction(
                    adapter, cache, args, catalogue,
                    TransactionStore(root=transaction_root),
                )
                _clear_applied_slots(adapter)
                return result
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
                applied_slot=_applied_slot(adapter, set_path),
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

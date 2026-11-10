"""Execute write steps with a preflight trace and an exact rollback path.

A plan is data: named tools, closed arguments, no free-form script. The executor runs every step
once as a dry run, then applies the same steps for real. If any applied step fails, or the applied
trace differs from the preflight trace, every step that returned an ``undo`` token is reversed in
reverse order. The scratch copy is made before the first applied call, never for a dry run.

The undo token is deliberately tool-owned. A tool knows which object it touched; the executor only
knows how to replay the token through the same tool's ``restore`` argument. This keeps rollback
exact without teaching the server the Live Object Model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..manifest import Tool, load_manifest
from ..state.scratch import ScratchCopy, ScratchError


class PlanError(Exception):
    """A plan cannot run safely, or its applied result disagreed with its preflight."""

    def __init__(self, code: str, message: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


@dataclass(frozen=True)
class Step:
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)


def _clean(value: Any) -> Any:
    """Remove transport state from a trace without hiding the actual effect."""
    if isinstance(value, dict):
        return {
            key: _clean(item)
            for key, item in value.items()
            if key not in ("dry_run", "undo")
        }
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def _key(steps: Sequence[Step]) -> str:
    payload = [{"tool": step.tool, "args": step.args} for step in steps]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _error_payload(exc: Exception) -> Dict[str, Any]:
    return {"type": type(exc).__name__, "message": str(exc)}


class PlanExecutor:
    """Run a bounded set of write steps against one adapter and one Set."""

    def __init__(
        self,
        adapter: Any,
        set_path: Optional[str] = None,
        backup_root: Optional[str] = None,
        scratch: Optional[ScratchCopy] = None,
        catalogue: Optional[Dict[str, Tool]] = None,
    ):
        self._adapter = adapter
        self._catalogue = catalogue or load_manifest()
        self._scratch = scratch or ScratchCopy(set_path, backup_root)
        self._applied = {}  # type: Dict[str, Dict[str, Any]]

    def _resolve(self, steps: Sequence[Step]) -> List[Tuple[Step, Tool]]:
        resolved = []
        for step in steps:
            tool = self._catalogue.get(step.tool)
            if tool is None:
                raise PlanError("UNKNOWN_COMMAND", "no tool named %r" % (step.tool,))
            if not tool.writes:
                raise PlanError("BAD_ARGS", "tool %r is not a write" % (step.tool,))
            if "dry_run" not in (tool.input.get("properties") or {}):
                raise PlanError(
                    "PRECONDITION_FAILED",
                    "write tool %r has no dry-run mode; it cannot join a transaction" % (step.tool,),
                )
            if len(steps) > 1 and not tool.reversible:
                # A single step runs as a direct write and still takes a scratch copy first; inside a
                # multi-step plan there is nothing to roll it back, so a later failure would leave
                # the Set partly changed.
                raise PlanError(
                    "PRECONDITION_FAILED",
                    "tool %r cannot be undone on this build, so it cannot join a multi-step plan"
                    % (step.tool,),
                )
            resolved.append((step, tool))
        if not resolved:
            raise PlanError("BAD_ARGS", "a plan needs at least one write step")
        return resolved

    def _call(self, step: Step, tool: Tool, dry_run: bool) -> Dict[str, Any]:
        args = dict(step.args)
        args["dry_run"] = dry_run
        result = self._adapter.call(tool.cmd, args, timeout_ms=tool.timeout_ms)
        if not isinstance(result, dict):
            raise PlanError("INTERNAL", "%s returned %r" % (tool.cmd, type(result).__name__))
        return result

    def run(self, steps: Sequence[Step]) -> Dict[str, Any]:
        """Return the no-effect preflight trace."""
        resolved = self._resolve(steps)
        trace = []
        for step, tool in resolved:
            try:
                result = self._call(step, tool, True)
            except PlanError:
                raise
            except Exception as exc:  # noqa: BLE001 - the failing step is the answer
                raise PlanError("LIVE_ERROR", "%s failed: %s" % (step.tool, exc),
                                {"tool": step.tool}) from exc
            trace.append({"tool": step.tool, "args": _clean(step.args), "result": _clean(result)})
        return {"dry_run": True, "applied": False, "trace": trace, "scratch_copy": None}

    def _restore(self, undo: Sequence[Tuple[Step, Tool, List[Any]]]) -> Dict[str, Any]:
        steps = []
        ok = True
        for step, tool, entries in reversed(list(undo)):
            if not entries:
                continue
            try:
                result = self._adapter.call(
                    tool.cmd,
                    {"restore": list(entries), "dry_run": False},
                    timeout_ms=tool.timeout_ms,
                )
                steps.append({"tool": step.tool, "result": _clean(result)})
            except Exception as exc:  # noqa: BLE001 - report the restore failure too
                ok = False
                steps.append({"tool": step.tool, "error": _error_payload(exc)})
        return {"ok": ok, "steps": steps}

    def apply(self, steps: Sequence[Step]) -> Dict[str, Any]:
        """Preflight, copy the Set, apply, verify the trace, and roll back on failure."""
        resolved = self._resolve(steps)
        key = _key(steps)
        if key in self._applied:
            previous = self._applied[key]
            return {
                "dry_run": False,
                "applied": False,
                "already_applied": True,
                "trace": previous["trace"],
                "scratch_copy": previous["scratch_copy"],
                "results": previous["results"],
            }

        preflight = self.run(steps)
        try:
            scratch_path = self._scratch.ensure()
        except ScratchError as exc:
            raise PlanError("PRECONDITION_FAILED", str(exc)) from exc

        undo = []  # type: List[Tuple[Step, Tool, List[Any]]]
        results = []
        trace = []
        try:
            for step, tool in resolved:
                result = self._call(step, tool, False)
                results.append(result)
                trace.append({
                    "tool": step.tool,
                    "args": _clean(step.args),
                    "result": _clean(result),
                })
                entries = result.get("undo") or []
                if entries:
                    undo.append((step, tool, list(entries)))
        except Exception as exc:  # noqa: BLE001 - restore is the contract
            restored = self._restore(undo)
            return {
                "dry_run": False,
                "applied": False,
                "error": _error_payload(exc),
                "restore": restored,
                "trace": trace,
                "scratch_copy": str(scratch_path),
                "results": results,
            }

        if _clean(trace) != _clean(preflight["trace"]):
            restored = self._restore(undo)
            raise PlanError(
                "PRECONDITION_FAILED",
                "applied trace did not match the dry-run trace",
                {"restore": restored, "scratch_copy": str(scratch_path)},
            )

        outcome = {
            "dry_run": False,
            "applied": True,
            "already_applied": False,
            "trace": trace,
            "scratch_copy": str(scratch_path),
            "results": results,
        }
        self._applied[key] = outcome
        return outcome

"""Escalation compiles a bounded plan from findings, then applies it transactionally.

There is no model inside the server. The compiler grounds an intent in the findings it can prove,
uses the same plan builder as ``inspect_plan``, and never invents tool arguments. If an intent has
no matching finding, it returns no plan and a reason instead of guessing. Explicit
``context.finding_ids`` and ``context.phases`` let a caller select precisely.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set

from . import diagnostics
from .manifest import Tool
from .plans import PlanStore, PlanStoreError, TransactionStore
from .plans.executor import PlanError, PlanExecutor, Step


class EscalationError(Exception):
    """An escalation request is malformed or cannot be grounded."""


_WORDS = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "and", "are", "at", "for", "from", "i", "in", "is", "it", "my", "of", "on",
    "or", "the", "this", "to", "with", "please", "can", "could", "would", "you", "me",
}
_SELECT_ALL = {"all", "anything", "clean", "cleanup", "everything", "fix", "repair"}
_MODE_NAMES = {"auto", "inspect"}


def _only(args: Dict[str, Any], allowed: Sequence[str]) -> None:
    unknown = sorted(set(args) - set(allowed))
    if unknown:
        raise EscalationError("unknown argument(s): %s" % ", ".join(unknown))


def _plan_id(args: Dict[str, Any]) -> str:
    value = args.get("plan_id")
    if not isinstance(value, str) or not value:
        raise EscalationError("plan_id must be a non-empty string")
    return value


def _phases(raw: Any) -> List[str]:
    if raw is None:
        return list(diagnostics.PHASES)
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise EscalationError("context.phases must be an array of phase names")
    unknown = [item for item in raw if item not in diagnostics.PHASE_ORDER]
    if unknown:
        raise EscalationError("unknown phase(s): %s" % ", ".join(unknown))
    return [phase for phase in diagnostics.PHASES if phase in set(raw)]


def _tokens(intent: str) -> Set[str]:
    return {
        word for word in _WORDS.findall(intent.lower())
        if len(word) > 1 and word not in _STOPWORDS
    }


def _finding_text(finding: diagnostics.Finding) -> str:
    location = finding.location or {}
    track = (location.get("track") or {}).get("name")
    clip = (location.get("clip") or {}).get("name")
    return " ".join(
        str(part) for part in (
            finding.title, finding.kind, finding.phase, finding.mode, track, clip,
        ) if part
    ).lower()


def _matches(finding: diagnostics.Finding, tokens: Set[str]) -> bool:
    words = set(_WORDS.findall(_finding_text(finding)))
    return bool(words & tokens)


def _select(
    findings: Sequence[diagnostics.Finding],
    intent: str,
    context: Dict[str, Any],
) -> List[diagnostics.Finding]:
    by_id = {finding.id: finding for finding in findings}
    finding_ids = context.get("finding_ids")
    if finding_ids is not None:
        if not isinstance(finding_ids, list) or not all(isinstance(item, str) for item in finding_ids):
            raise EscalationError("context.finding_ids must be an array of finding ids")
        unknown = [item for item in finding_ids if item not in by_id]
        if unknown:
            raise EscalationError("unknown finding id(s): %s" % ", ".join(unknown))
        return [by_id[item] for item in finding_ids]

    selected = list(findings)
    phases = _phases(context.get("phases"))
    if context.get("phases") is not None:
        selected = [finding for finding in selected if finding.phase in phases]
    mode = context.get("mode")
    if mode is not None:
        if not isinstance(mode, str) or mode not in _MODE_NAMES:
            raise EscalationError("context.mode must be 'auto' or 'inspect'")
        selected = [finding for finding in selected if finding.mode == mode]

    # An explicit phase/mode selection is already precise; only free-form intents are lexical.
    if context.get("phases") is None and mode is None:
        tokens = _tokens(intent)
        if not tokens:
            return []
        if not tokens & _SELECT_ALL:
            selected = [finding for finding in selected if _matches(finding, tokens)]
    return selected


def _effects(
    findings: Sequence[diagnostics.Finding],
    steps: Sequence[Dict[str, Any]],
) -> Dict[str, int]:
    by_id = {finding.id: finding for finding in findings}
    tracks = set()
    clips = set()
    notes = 0
    for step in steps:
        finding = by_id.get(step.get("finding_id"))
        if finding is None:
            continue
        location = finding.location or {}
        track = (location.get("track") or {}).get("name")
        clip = (location.get("clip") or {}).get("name")
        if track:
            tracks.add(track)
        if clip:
            clips.add(clip)
        value = (finding.evidence or {}).get("overlaps")
        if isinstance(value, int):
            notes += value
    return {"tracks": len(tracks), "clips": len(clips), "notes": notes}


def _requirements(
    steps: Sequence[Dict[str, Any]],
    catalogue: Dict[str, Tool],
) -> List[str]:
    needed = set()
    for step in steps:
        tool = catalogue.get(step.get("tool"))
        if tool is not None:
            needed.update(tool.needs)
    return sorted(needed)


def _reversible(steps: Sequence[Dict[str, Any]], catalogue: Dict[str, Tool]) -> bool:
    for step in steps:
        tool = catalogue.get(step.get("tool"))
        if tool is None or not tool.writes or not tool.reversible:
            return False
    return True


def _proposed_steps(raw: Any, catalogue: Dict[str, Tool]) -> List[Dict[str, Any]]:
    """Validate an explicit plan before it can become a stored plan.

    The caller may propose any tool in the catalogue, not only the tools in its current mode.
    Only reversible writes with a dry-run mode are allowed: a proposal must be previewable and
    undoable before the executor is asked to apply it.
    """
    if not isinstance(raw, list) or not raw:
        raise EscalationError("steps must be a non-empty array")
    if len(raw) > diagnostics.MAX_PLAN_STEPS:
        raise EscalationError("steps is limited to %d" % diagnostics.MAX_PLAN_STEPS)

    steps = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise EscalationError("step %d must be an object" % index)
        unknown = sorted(set(entry) - {"tool", "args", "why"})
        if unknown:
            raise EscalationError(
                "step %d has unknown key(s): %s" % (index, ", ".join(unknown))
            )
        name = entry.get("tool")
        if not isinstance(name, str) or not name:
            raise EscalationError("step %d needs a tool name" % index)
        args = entry.get("args") or {}
        if not isinstance(args, dict):
            raise EscalationError("step %d args must be an object" % index)
        if "dry_run" in args or "restore" in args:
            raise EscalationError("step %d must not set dry_run or restore" % index)
        why = entry.get("why")
        if why is not None and not isinstance(why, str):
            raise EscalationError("step %d why must be a string" % index)

        tool = catalogue.get(name)
        if tool is None:
            raise EscalationError("step %d names unknown tool %r" % (index, name))
        if not tool.writes:
            raise EscalationError("step %d tool %r is read-only" % (index, name))
        if "dry_run" not in (tool.input.get("properties") or {}):
            raise EscalationError("step %d tool %r has no dry-run mode" % (index, name))
        if not tool.reversible:
            raise EscalationError("step %d tool %r is not reversible" % (index, name))

        step = {"n": index, "tool": name, "args": dict(args)}
        if why:
            step["why"] = why
        steps.append(step)
    return steps


def validate_steps(
    raw: Any,
    catalogue: Optional[Dict[str, Tool]] = None,
) -> List[Dict[str, Any]]:
    """Validate a reusable sequence without storing a plan or touching Live."""
    if catalogue is None:
        from .manifest import load_manifest

        catalogue = load_manifest()
    return _proposed_steps(raw, catalogue)


def escalate(
    data: Dict[str, Any],
    args: Optional[Dict[str, Any]] = None,
    catalogue: Optional[Dict[str, Tool]] = None,
    store: Optional[PlanStore] = None,
    adapter: Any = None,
) -> Dict[str, Any]:
    """Compile a plan from findings, or validate explicit steps proposed by the caller."""
    args = dict(args or {})
    _only(args, ("intent", "context", "steps"))
    context = args.get("context") or {}
    if not isinstance(context, dict):
        raise EscalationError("context must be an object")

    if catalogue is None:
        from .manifest import load_manifest

        catalogue = load_manifest()
    if store is None:
        store = PlanStore()

    if args.get("steps") is not None:
        if context:
            raise EscalationError("context cannot be combined with explicit steps")
        intent = args.get("intent") or "Explicit plan"
        if not isinstance(intent, str) or not intent.strip():
            raise EscalationError("intent must be a non-empty string")
        steps = _proposed_steps(args["steps"], catalogue)
        counts = diagnostics.counts(diagnostics.detect(data, "standard"))
        preflight = {"ran": False, "reason": "no adapter"}
        if adapter is not None:
            try:
                preflight = PlanExecutor(adapter, catalogue=catalogue).run(
                    [Step(step["tool"], dict(step["args"])) for step in steps]
                )
                preflight["ran"] = True
            except PlanError as exc:
                tool = (exc.detail or {}).get("tool") or "the plan"
                raise EscalationError(
                    "preflight failed for %s: %s" % (tool, exc.message)
                ) from exc
        plan = store.create(
            intent=intent,
            steps=steps,
            effects={},
            requires=_requirements(steps, catalogue),
            unavailable=[],
            truncated=[],
            reversible=True,
        )
        return {
            "plan_id": plan["plan_id"],
            "intent": plan["intent"],
            "explicit_steps": True,
            "steps": plan["steps"],
            "phases": [],
            "effects": {},
            "reversible": True,
            "requires": plan["requires"],
            "unavailable": [],
            "truncated": [],
            "needs_listening": [],
            "matched_findings": 0,
            "counts": counts,
            "preflight": preflight,
            "created_at": plan["created_at"],
            "expires_at": plan["expires_at"],
        }

    intent = args.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        raise EscalationError("intent must be a non-empty string")
    unknown = sorted(set(context) - {"phases", "finding_ids", "mode"})
    if unknown:
        raise EscalationError("unknown context key(s): %s" % ", ".join(unknown))

    findings = diagnostics.detect(data, "standard")
    selected = _select(findings, intent, context)
    phases = _phases(context.get("phases")) if context.get("phases") is not None else None
    planned = diagnostics._build_plan(selected, catalogue, phases)
    counts = diagnostics.counts(findings)

    if not planned["steps"]:
        if not selected:
            reason = "no current finding matches the intent; nothing was fabricated"
        elif planned["unavailable"]:
            reason = "the matching findings have no executable fix in this build"
        else:
            reason = "the matching findings contain no auto-applicable step"
        return {
            "plan_id": None,
            "intent": intent,
            "steps": [],
            "phases": [],
            "effects": {"tracks": 0, "clips": 0, "notes": 0},
            "reversible": True,
            "requires": [],
            "unavailable": planned["unavailable"],
            "truncated": planned["truncated"],
            "needs_listening": planned["needs_listening"],
            "matched_findings": len(selected),
            "counts": counts,
            "reason": reason,
        }

    steps = planned["steps"]
    plan = store.create(
        intent=intent,
        steps=steps,
        effects=_effects(selected, steps),
        requires=_requirements(steps, catalogue),
        unavailable=planned["unavailable"],
        truncated=planned["truncated"],
        reversible=_reversible(steps, catalogue),
    )
    return {
        "plan_id": plan["plan_id"],
        "intent": intent,
        "steps": plan["steps"],
        "phases": planned["phases"],
        "effects": plan["effects"],
        "reversible": plan["reversible"],
        "requires": plan["requires"],
        "unavailable": plan["unavailable"],
        "truncated": plan["truncated"],
        "needs_listening": planned["needs_listening"],
        "matched_findings": len(selected),
        "counts": counts,
        "created_at": plan["created_at"],
        "expires_at": plan["expires_at"],
    }


def apply_plan(
    adapter: Any,
    cache: Any,
    args: Optional[Dict[str, Any]] = None,
    store: Optional[PlanStore] = None,
    catalogue: Optional[Dict[str, Tool]] = None,
    backup_root: Optional[str] = None,
    transaction_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a stored plan transactionally and report failure plus restore."""
    args = dict(args or {})
    _only(args, ("plan_id",))
    plan_id = _plan_id(args)
    if store is None:
        store = PlanStore()
    if catalogue is None:
        from .manifest import load_manifest

        catalogue = load_manifest()
    plan = store.get(plan_id)
    steps = []
    for step in plan["steps"]:
        if not isinstance(step, dict) or not isinstance(step.get("tool"), str):
            raise EscalationError("plan %r contains an invalid step" % plan_id)
        steps.append(Step(step["tool"], dict(step.get("args") or {})))
    if not steps:
        raise EscalationError("plan %r has no valid steps" % plan_id)

    data = cache.get()
    set_path = (data.get("song") or {}).get("file_path")
    counts_before = diagnostics.counts(diagnostics.detect(data, "standard"))
    executor = PlanExecutor(
        adapter,
        set_path=set_path,
        backup_root=backup_root,
        catalogue=catalogue,
        transaction_store=TransactionStore(root=transaction_root),
    )
    try:
        outcome = executor.apply(steps)
    except PlanError as exc:
        cache.invalidate()
        current = cache.get()
        return {
            "plan_id": plan_id,
            "applied": False,
            "error": {"code": exc.code, "message": exc.message, "detail": exc.detail},
            "restore": (exc.detail or {}).get("restore"),
            "scratch_copy": (exc.detail or {}).get("scratch_copy"),
            "counts_before": counts_before,
            "counts_after": diagnostics.counts(diagnostics.detect(current, "standard")),
            "discarded": False,
        }

    cache.invalidate()
    current = cache.get()
    applied = bool(outcome.get("applied"))
    if applied:
        store.discard(plan_id)
    return {
        "plan_id": plan_id,
        "applied": applied,
        "already_applied": bool(outcome.get("already_applied")),
        "error": outcome.get("error"),
        "restore": outcome.get("restore"),
        "scratch_copy": outcome.get("scratch_copy"),
        "steps": outcome.get("trace") or [],
        "counts_before": counts_before,
        "counts_after": diagnostics.counts(diagnostics.detect(current, "standard")),
        "discarded": applied,
    }


def discard_plan(
    args: Optional[Dict[str, Any]] = None,
    store: Optional[PlanStore] = None,
) -> Dict[str, Any]:
    """Delete a stored plan; a missing id is an honest false, not an exception."""
    args = dict(args or {})
    _only(args, ("plan_id",))
    plan_id = _plan_id(args)
    if store is None:
        store = PlanStore()
    return {"plan_id": plan_id, "discarded": store.discard(plan_id)}


__all__ = [
    "EscalationError", "apply_plan", "discard_plan", "escalate", "validate_steps",
]

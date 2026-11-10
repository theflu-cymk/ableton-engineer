"""Findings, phases, plans and autofix (spec §8).

A finding is the unit of everything Enableton knows is wrong. Detection is a pure function of a
snapshot, so the same answer comes from Live, a fixture or a saved read. Repairs are ordinary
manifest tools, executed by the same transactional executor as every other write.

The rules encoded here are deliberate:
- a finding carries a fix or declares ``needs_listening``; never neither;
- plans are phase-ordered and bounded;
- autofix never executes a ``needs_listening`` finding;
- after every phase autofix re-reads and stops if the total finding count rose.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .manifest import Tool, load_manifest
from .plans import PlanError, PlanExecutor, Step
from .reports import UNITY_VOLUME, mix_headroom

PHASES = (
    "grid",
    "alignment",
    "notes",
    "hygiene",
    "routing",
    "gain",
    "spectral",
    "master",
)
PHASE_ORDER = {name: index for index, name in enumerate(PHASES)}
SEVERITIES = ("info", "warn", "error")
SEVERITY_ORDER = {name: index for index, name in enumerate(SEVERITIES)}
TIERS = ("fast", "standard", "deep")
DEFAULT_PAGE = 50
MAX_PAGE = 200
MAX_PLAN_STEPS = 12
MAX_PLAN_PHASES = 3


class DiagnosticsError(ValueError):
    """A diagnostics request is malformed."""


@dataclass(frozen=True)
class Finding:
    id: str
    kind: str
    severity: str
    confidence: float
    title: str
    evidence: Dict[str, Any]
    location: Dict[str, Any]
    objective: str
    phase: str
    mode: str
    needs_listening: bool
    fix: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        out = {
            "id": self.id,
            "kind": self.kind,
            "severity": self.severity,
            "confidence": self.confidence,
            "title": self.title,
            "evidence": self.evidence,
            "location": self.location,
            "objective": self.objective,
            "phase": self.phase,
            "mode": self.mode,
            "needs_listening": self.needs_listening,
        }
        if self.fix is not None:
            out["fix"] = self.fix
        return out


def _only(args: Dict[str, Any], allowed: Sequence[str]) -> None:
    unknown = sorted(set(args) - set(allowed))
    if unknown:
        raise DiagnosticsError("unknown argument(s): %s" % ", ".join(unknown))


def _paging(args: Dict[str, Any]) -> Tuple[int, int]:
    offset = args.get("offset", 0)
    limit = args.get("limit", DEFAULT_PAGE)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise DiagnosticsError("offset must be a non-negative integer")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_PAGE:
        raise DiagnosticsError("limit must be an integer from 1 to %d" % MAX_PAGE)
    return offset, limit


def _page(items: Sequence[Any], offset: int, limit: int) -> Dict[str, Any]:
    window = list(items[offset:offset + limit])
    next_offset = offset + len(window)
    return {
        "items": window,
        "total": len(items),
        "next_offset": next_offset if next_offset < len(items) else None,
    }


def _finding_id(kind: str, location: Dict[str, Any]) -> str:
    payload = json.dumps([kind, location], sort_keys=True, separators=(",", ":"))
    return "f_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def _make(
    kind: str,
    severity: str,
    confidence: float,
    title: str,
    evidence: Dict[str, Any],
    location: Dict[str, Any],
    objective: str,
    phase: str,
    mode: str,
    needs_listening: bool,
    fix: Optional[Dict[str, Any]] = None,
) -> Finding:
    if severity not in SEVERITIES:
        raise DiagnosticsError("unknown severity %r" % (severity,))
    if phase not in PHASE_ORDER:
        raise DiagnosticsError("unknown phase %r" % (phase,))
    if fix is None and not needs_listening:
        raise DiagnosticsError("finding %r has neither a fix nor needs_listening" % kind)
    return Finding(
        id=_finding_id(kind, location),
        kind=kind,
        severity=severity,
        confidence=float(confidence),
        title=title,
        evidence=evidence,
        location=location,
        objective=objective,
        phase=phase,
        mode=mode,
        needs_listening=bool(needs_listening),
        fix=fix,
    )


def _empty_track_findings(data: Dict[str, Any]) -> List[Finding]:
    findings = []
    for track in data.get("tracks") or []:
        if track.get("kind") == "return":
            continue
        session = (track.get("session") or {}).get("filled") or 0
        if track.get("arrangement") or session:
            continue
        location = {"track": {"name": track.get("name"), "index": track.get("index")}}
        findings.append(_make(
            "hygiene.empty_track", "info", 1.0,
            "Track %r has no clips in the Arrangement or Session" % (track.get("name"),),
            {"arrangement_clips": 0, "session_clips": 0},
            location, "hygiene", "hygiene", "inspect", False,
            {"tool": "tracks_clean_empty", "args": {"tracks": [track.get("name")]}},
        ))
    return findings


def _duplicate_track_findings(data: Dict[str, Any]) -> List[Finding]:
    names = {}  # type: Dict[str, List[int]]
    for track in data.get("tracks") or []:
        names.setdefault(str(track.get("name")), []).append(track.get("index"))
    findings = []
    for name, indexes in sorted(names.items()):
        if len(indexes) < 2:
            continue
        location = {"track": {"name": name, "index": indexes[0]}, "indexes": indexes}
        findings.append(_make(
            "hygiene.duplicate_track_name", "warn", 1.0,
            "Track name %r is used by %d tracks" % (name, len(indexes)),
            {"indexes": indexes},
            location, "hygiene", "hygiene", "inspect", False,
            {"tool": "tracks_name_and_color", "args": {"tracks": [name]}},
        ))
    return findings


def _fader_findings(data: Dict[str, Any]) -> List[Finding]:
    report = mix_headroom(data, {})
    findings = []
    for row in report["items"]:
        fader_db = row.get("fader_db")
        volume = row.get("volume")
        # Live's display string is the precise read. When a backend omits it, the raw position
        # above 0.85 is still proof of an above-unity trim, just without a dB figure to quote.
        if fader_db is None and (volume is None or float(volume) <= UNITY_VOLUME):
            continue
        if fader_db is not None and fader_db <= 0:
            continue
        name = row.get("name")
        location = {"track": {"name": name, "index": row.get("index")}}
        title = (
            "Track %r sits %.1f dB above unity" % (name, fader_db)
            if fader_db is not None
            else "Track %r sits above unity" % (name,)
        )
        findings.append(_make(
            "mix.fader_above_unity", "info", 1.0 if fader_db is not None else 0.9,
            title,
            {"fader_db": fader_db, "volume": volume,
             "volume_str": row.get("volume_str")},
            location, "headroom", "gain", "auto", False,
            {"tool": "tracks_set_volume",
             "args": {"tracks": [name], "volume": UNITY_VOLUME}},
        ))
    return findings


def _note_findings(data: Dict[str, Any]) -> List[Finding]:
    findings = []
    for track in data.get("tracks") or []:
        clips = [("arrangement", c) for c in (track.get("arrangement") or [])]
        clips += [("session", c) for c in ((track.get("session") or {}).get("clips") or [])]
        for location_name, clip in clips:
            if not clip.get("midi"):
                continue
            pairs = clip.get("note_overlaps") or []
            if not pairs:
                continue
            location = {
                "track": {"name": track.get("name"), "index": track.get("index")},
                "clip": {"name": clip.get("name"), "location": location_name},
            }
            if location_name == "session":
                location["clip"]["slot"] = clip.get("slot")
            findings.append(_make(
                "notes.overlap", "warn", 1.0,
                "%d same-pitch note overlap%s in %r" % (
                    len(pairs), "" if len(pairs) == 1 else "s", clip.get("name"),
                ),
                {"overlaps": len(pairs), "pairs": pairs[:5],
                 "truncated": bool(clip.get("note_overlaps_truncated"))},
                location, "timing", "notes", "inspect", True, None,
            ))
    return findings


_FAST_DETECTORS = (_empty_track_findings, _duplicate_track_findings)
_STANDARD_DETECTORS = _FAST_DETECTORS + (_fader_findings, _note_findings)
_DETECTORS = {
    "fast": _FAST_DETECTORS,
    "standard": _STANDARD_DETECTORS,
    "deep": _STANDARD_DETECTORS,
}


def detect(
    data: Dict[str, Any],
    tier: str = "standard",
    detectors: Optional[Sequence[Callable[[Dict[str, Any]], List[Finding]]]] = None,
) -> List[Finding]:
    """Return findings sorted by phase, severity and stable id."""
    if tier not in TIERS:
        raise DiagnosticsError("tier must be one of %s" % ", ".join(TIERS))
    selected = tuple(detectors) if detectors is not None else _DETECTORS[tier]
    findings = []
    seen = set()
    for detector in selected:
        for finding in detector(data):
            if finding.id in seen:
                continue
            seen.add(finding.id)
            findings.append(finding)
    findings.sort(key=lambda f: (PHASE_ORDER[f.phase], SEVERITY_ORDER[f.severity], f.id))
    return findings


def _has_available_fix(finding: Finding, catalogue: Dict[str, Tool]) -> bool:
    if finding.fix is None or finding.needs_listening:
        return False
    tool = catalogue.get(finding.fix.get("tool"))
    return bool(tool is not None and tool.writes and "dry_run" in (
        tool.input.get("properties") or {}
    ))


def counts(findings: Sequence[Finding], catalogue: Optional[Dict[str, Tool]] = None) -> Dict[str, Any]:
    """Counts per mode, severity, and fixes this build can actually execute."""
    catalogue = catalogue or load_manifest()
    by_mode = {"auto": 0, "inspect": 0}  # type: Dict[str, int]
    by_severity = {name: 0 for name in SEVERITIES}  # type: Dict[str, int]
    for finding in findings:
        by_mode[finding.mode] = by_mode.get(finding.mode, 0) + 1
        by_severity[finding.severity] += 1
    return {
        "total": len(findings),
        "by_mode": dict(sorted(by_mode.items())),
        "by_severity": by_severity,
        "needs_listening": sum(1 for f in findings if f.needs_listening),
        "auto_fixable": sum(1 for f in findings if _has_available_fix(f, catalogue)),
    }


def run(data: Dict[str, Any], args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Detect findings and return the mode counts plus a page."""
    args = dict(args or {})
    _only(args, ("tier", "offset", "limit"))
    tier = args.get("tier", "standard")
    if tier not in TIERS:
        raise DiagnosticsError("tier must be one of %s" % ", ".join(TIERS))
    offset, limit = _paging(args)
    findings = detect(data, tier)
    page = _page([finding.as_dict() for finding in findings], offset, limit)
    unavailable = []
    captured = data.get("captured") or {}
    if not captured.get("notes_available"):
        unavailable.append({
            "capability": "note overlap analysis",
            "reason": captured.get("notes_reason")
            or "This snapshot has no MIDI note data; reinstall the Remote Script and restart Live.",
        })
    if tier == "deep":
        unavailable.append({
            "capability": "deep meter and spectral analysis",
            "reason": "Meter polling and spectral capture arrive with the audio tiers in M6.",
        })
    return {
        "tier": tier,
        "counts": counts(findings),
        "findings": page["items"],
        "total": page["total"],
        "next_offset": page["next_offset"],
        "unavailable": unavailable,
    }


def report(data: Dict[str, Any], args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Page and filter findings without hiding the unfiltered counts."""
    args = dict(args or {})
    _only(args, ("mode", "severity", "phase", "needs_listening", "offset", "limit"))
    offset, limit = _paging(args)
    findings = detect(data, "standard")
    mode = args.get("mode")
    severity = args.get("severity")
    phase = args.get("phase")
    listening = args.get("needs_listening")
    if mode is not None and not isinstance(mode, str):
        raise DiagnosticsError("mode must be a string")
    if severity is not None and severity not in SEVERITIES:
        raise DiagnosticsError("severity must be one of %s" % ", ".join(SEVERITIES))
    if phase is not None and phase not in PHASE_ORDER:
        raise DiagnosticsError("phase must be one of %s" % ", ".join(PHASES))
    if listening is not None and not isinstance(listening, bool):
        raise DiagnosticsError("needs_listening must be a boolean")
    selected = [
        finding for finding in findings
        if (mode is None or finding.mode == mode)
        and (severity is None or finding.severity == severity)
        and (phase is None or finding.phase == phase)
        and (listening is None or finding.needs_listening == listening)
    ]
    page = _page([finding.as_dict() for finding in selected], offset, limit)
    return {
        "counts": counts(findings),
        "filtered_total": len(selected),
        "items": page["items"],
        "total": page["total"],
        "next_offset": page["next_offset"],
    }


def get(data: Dict[str, Any], args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    args = dict(args or {})
    _only(args, ("id",))
    identifier = args.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise DiagnosticsError("id must be a non-empty string")
    findings = detect(data, "standard")
    for finding in findings:
        if finding.id == identifier:
            return {"finding": finding.as_dict(), "counts": counts(findings)}
    raise DiagnosticsError("no finding with id %r" % identifier)


def _phase_list(args: Dict[str, Any]) -> List[str]:
    phases = args.get("phases")
    if phases is None:
        return list(PHASES)
    if not isinstance(phases, list) or not all(isinstance(p, str) for p in phases):
        raise DiagnosticsError("phases must be an array of phase names")
    unknown = [p for p in phases if p not in PHASE_ORDER]
    if unknown:
        raise DiagnosticsError("unknown phase(s): %s" % ", ".join(unknown))
    return [p for p in PHASES if p in set(phases)]


def _build_plan(
    findings: Sequence[Finding],
    catalogue: Dict[str, Tool],
    phases: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    allowed = set(phases) if phases is not None else set(PHASES)
    candidates = [
        finding for finding in findings
        if finding.fix is not None and not finding.needs_listening and finding.phase in allowed
    ]
    unavailable = []
    available = []  # type: List[Finding]
    for finding in candidates:
        fix = finding.fix or {}
        tool_name = fix.get("tool")
        tool = catalogue.get(tool_name)
        reason = None
        if not isinstance(tool_name, str) or tool is None:
            reason = "tool %r is not implemented in this build" % (tool_name,)
        elif not tool.writes:
            reason = "tool %r is read-only" % tool_name
        elif "dry_run" not in (tool.input.get("properties") or {}):
            reason = "tool %r has no dry-run mode" % tool_name
        if reason is not None:
            unavailable.append({"finding_id": finding.id, "tool": tool_name, "reason": reason})
        else:
            available.append(finding)

    grouped = {}  # type: Dict[str, List[Finding]]
    for finding in available:
        grouped.setdefault(finding.phase, []).append(finding)

    steps = []
    phases_out = []
    truncated = []
    for phase in PHASES:
        if phase not in grouped:
            continue
        if len(phases_out) >= MAX_PLAN_PHASES:
            truncated.extend(grouped[phase])
            continue
        phase_steps = []
        for finding in grouped[phase]:
            if len(steps) >= MAX_PLAN_STEPS:
                truncated.append(finding)
                continue
            fix = finding.fix or {}
            step = {
                "n": len(steps) + 1,
                "finding_id": finding.id,
                "tool": fix.get("tool"),
                "args": dict(fix.get("args") or {}),
                "why": finding.title,
                "phase": phase,
                "mode": finding.mode,
            }
            steps.append(step)
            phase_steps.append(step)
        if phase_steps:
            phases_out.append({"phase": phase, "steps": phase_steps})
    return {
        "steps": steps,
        "phases": phases_out,
        "total": len(steps),
        "needs_listening": [
            {"finding_id": f.id, "title": f.title}
            for f in findings if f.needs_listening and f.phase in allowed
        ],
        "unavailable": unavailable,
        "truncated": [{"finding_id": f.id, "title": f.title} for f in truncated],
    }


def plan(data: Dict[str, Any], args: Optional[Dict[str, Any]] = None,
         catalogue: Optional[Dict[str, Tool]] = None) -> Dict[str, Any]:
    args = dict(args or {})
    _only(args, ("phases",))
    if catalogue is None:
        from .manifest import load_manifest

        catalogue = load_manifest()
    phases = _phase_list(args)
    findings = detect(data, "standard")
    result = _build_plan(findings, catalogue, phases)
    result["counts"] = counts(findings)
    return result


def _rollback_phases(
    adapter: Any,
    applied: Sequence[Dict[str, Any]],
    catalogue: Dict[str, Tool],
) -> Dict[str, Any]:
    """Replay the tool-owned undo tokens of every phase already applied."""
    ok = True
    steps = []
    for phase in reversed(list(applied)):
        phase_steps = phase.get("steps") or []
        results = phase.get("results") or []
        for step, result in reversed(list(zip(phase_steps, results))):
            entries = result.get("undo") or []
            if not entries:
                continue
            tool = catalogue.get(step.get("tool"))
            if tool is None or not tool.cmd:
                ok = False
                steps.append({"tool": step.get("tool"), "error": {
                    "message": "the tool needed to restore this step is not available",
                }})
                continue
            try:
                restored = adapter.call(
                    tool.cmd,
                    {"restore": list(entries), "dry_run": False},
                    timeout_ms=tool.timeout_ms,
                )
                steps.append({"tool": step["tool"], "result": restored})
            except Exception as exc:  # noqa: BLE001 - a failed restore is part of the report
                ok = False
                steps.append({"tool": step["tool"], "error": {
                    "type": type(exc).__name__, "message": str(exc),
                }})
    return {"ok": ok, "steps": steps}


def _merge_restore(existing: Optional[Dict[str, Any]], rollback: Dict[str, Any]) -> Dict[str, Any]:
    existing = existing or {}
    return {
        "ok": bool(existing.get("ok", True)) and bool(rollback["ok"]),
        "steps": list(existing.get("steps") or []) + list(rollback["steps"]),
    }


def autofix(
    adapter: Any,
    cache: Any,
    args: Optional[Dict[str, Any]] = None,
    catalogue: Optional[Dict[str, Tool]] = None,
    backup_root: Optional[str] = None,
    detectors: Optional[Sequence[Callable[[Dict[str, Any]], List[Finding]]]] = None,
) -> Dict[str, Any]:
    """Plan or apply available fixes phase by phase, checking the count after each read."""
    args = dict(args or {})
    _only(args, ("phases", "dry_run", "checkpoint"))
    if catalogue is None:
        from .manifest import load_manifest

        catalogue = load_manifest()
    phases = _phase_list(args)
    dry_run = bool(args.get("dry_run", True))
    checkpoint = bool(args.get("checkpoint", True))

    data = cache.get()
    findings = detect(data, "standard", detectors)
    before = counts(findings)
    if dry_run:
        planned = _build_plan(findings, catalogue, phases)
        return {
            "dry_run": True,
            "applied": False,
            "rolled_back": False,
            "checkpoint": checkpoint,
            "counts_before": before,
            "counts_after": before,
            "counts_after_change": None,
            "plan": planned,
            "steps": planned["steps"],
            "phases": planned["phases"],
            "needs_listening": planned["needs_listening"],
            "unavailable": planned["unavailable"],
            "truncated": planned["truncated"],
            "stopped": None,
        }

    applied_phases = []
    all_steps = []
    stopped = None
    error = None
    scratch_copy = None
    restore = None
    rolled_back = False
    counts_after_change = None
    current = data

    def rollback_applied(existing=None):
        nonlocal applied_phases, all_steps, rolled_back, restore, current, findings
        if not applied_phases:
            return
        rollback = _rollback_phases(adapter, applied_phases, catalogue)
        restore = _merge_restore(existing, rollback)
        rolled_back = True
        applied_phases = []
        all_steps = []
        cache.invalidate()
        current = cache.get()
        findings = detect(current, "standard", detectors)

    for phase in phases:
        phase_findings = detect(current, "standard", detectors)
        if any(f.severity == "error" and f.phase == phase for f in phase_findings):
            stopped = "error_finding_blocks_phase"
            findings = phase_findings
            rollback_applied(restore)
            break
        planned = _build_plan(phase_findings, catalogue, [phase])
        steps = planned["steps"]
        if not steps:
            findings = phase_findings
            continue
        set_path = (current.get("song") or {}).get("file_path")
        executor = PlanExecutor(adapter, set_path=set_path, backup_root=backup_root)
        try:
            outcome = executor.apply([
                Step(step["tool"], dict(step["args"])) for step in steps
            ])
        except PlanError as exc:
            stopped = "plan_error"
            error = {"code": exc.code, "message": exc.message, "detail": exc.detail}
            findings = phase_findings
            rollback_applied((exc.detail or {}).get("restore"))
            break
        if not outcome.get("applied"):
            stopped = "apply_failed"
            error = outcome.get("error") or {"message": "write failed"}
            failed_restore = outcome.get("restore")
            restore = failed_restore
            scratch_copy = outcome.get("scratch_copy")
            findings = phase_findings
            rollback_applied(failed_restore)
            break
        scratch_copy = outcome.get("scratch_copy") or scratch_copy
        restore = outcome.get("restore") or restore
        applied_phases.append({
            "phase": phase,
            "steps": steps,
            "results": list(outcome.get("results") or []),
            "scratch_copy": scratch_copy,
        })
        all_steps.extend(steps)
        cache.invalidate()
        current = cache.get()
        findings = detect(current, "standard", detectors)
        if counts(findings)["total"] > before["total"]:
            stopped = "finding_count_rose"
            counts_after_change = counts(findings)
            rollback_applied(restore)
            break

    after = counts(findings)
    return {
        "dry_run": False,
        "applied": bool(applied_phases),
        "rolled_back": rolled_back,
        "checkpoint": checkpoint,
        "counts_before": before,
        "counts_after": after,
        "counts_after_change": counts_after_change,
        "phases": applied_phases,
        "steps": all_steps,
        "stopped": stopped,
        "error": error,
        "restore": restore,
        "scratch_copy": scratch_copy,
    }


__all__ = [
    "DiagnosticsError", "Finding", "PHASES", "TIERS", "autofix", "counts", "detect", "get",
    "plan", "report", "run",
]

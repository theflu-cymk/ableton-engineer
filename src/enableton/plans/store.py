"""Plans produced by escalation, kept as data between tool calls.

The store is deliberately outside the Set and outside the process: ``enableton call`` starts a new
process for every request, so an in-memory registry would make ``ableton_escalate`` followed by
``ableton_plan_apply`` fail from the CLI. A plan is a small JSON file, expires after ten minutes,
and contains only tool names and arguments the manifest already validates.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

PLAN_ID_RE = re.compile(r"^p_[0-9a-f]{8}$")
DEFAULT_TTL_S = 600


class PlanStoreError(Exception):
    """A plan is unknown, expired, malformed, or cannot be stored."""


def default_plans_root() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "Enableton" / "plans"
    return Path.home() / ".enableton" / "plans"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PlanStore:
    """Read and write one JSON plan per id under a private directory."""

    def __init__(
        self,
        root: Optional[str] = None,
        clock: Optional[Callable[[], datetime]] = None,
        ttl_s: int = DEFAULT_TTL_S,
    ):
        self.root = Path(root) if root else default_plans_root()
        self._clock = clock or _utc_now
        self.ttl_s = ttl_s

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _validate_id(plan_id: Any) -> str:
        if not isinstance(plan_id, str) or not PLAN_ID_RE.match(plan_id):
            raise PlanStoreError("plan_id must look like 'p_0123abcd'")
        return plan_id

    def _path(self, plan_id: str) -> Path:
        return self.root / ("%s.json" % plan_id)

    def create(
        self,
        intent: str,
        steps: Sequence[Dict[str, Any]],
        effects: Optional[Dict[str, int]] = None,
        requires: Optional[Sequence[str]] = None,
        unavailable: Optional[Sequence[Dict[str, Any]]] = None,
        truncated: Optional[Sequence[Dict[str, Any]]] = None,
        reversible: bool = True,
    ) -> Dict[str, Any]:
        if not steps:
            raise PlanStoreError("a plan needs at least one step")
        self.root.mkdir(parents=True, exist_ok=True)
        plan_id = None
        for _ in range(20):
            candidate = "p_" + secrets.token_hex(4)
            if not self._path(candidate).exists():
                plan_id = candidate
                break
        if plan_id is None:
            raise PlanStoreError("could not allocate a plan id")

        now = self._now()
        expires = now + timedelta(seconds=self.ttl_s)
        plan = {
            "plan_id": plan_id,
            "intent": intent,
            "steps": list(steps),
            "effects": dict(effects or {}),
            "requires": list(requires or []),
            "unavailable": list(unavailable or []),
            "truncated": list(truncated or []),
            "reversible": bool(reversible),
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
        }
        path = self._path(plan_id)
        temporary = path.with_name(path.name + ".tmp")
        try:
            temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(str(temporary), str(path))
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise PlanStoreError("could not store the plan: %s" % (exc,)) from exc
        return plan

    def get(self, plan_id: str) -> Dict[str, Any]:
        plan_id = self._validate_id(plan_id)
        path = self._path(plan_id)
        if not path.is_file():
            raise PlanStoreError("no plan with id %r" % plan_id)
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PlanStoreError("could not read plan %r: %s" % (plan_id, exc)) from exc
        if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
            raise PlanStoreError("plan %r is malformed" % plan_id)
        if not isinstance(plan.get("steps"), list) or not plan["steps"]:
            raise PlanStoreError("plan %r has no steps" % plan_id)

        expires_raw = plan.get("expires_at")
        try:
            expires = datetime.fromisoformat(expires_raw)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError) as exc:
            raise PlanStoreError("plan %r has an invalid expiry" % plan_id) from exc
        if self._now() >= expires:
            try:
                path.unlink()
            except OSError:
                pass
            raise PlanStoreError("plan %r expired" % plan_id)
        return plan

    def discard(self, plan_id: str) -> bool:
        plan_id = self._validate_id(plan_id)
        path = self._path(plan_id)
        if not path.is_file():
            return False
        try:
            path.unlink()
        except OSError as exc:
            raise PlanStoreError("could not discard plan %r: %s" % (plan_id, exc)) from exc
        return True


__all__ = ["DEFAULT_TTL_S", "PlanStore", "PlanStoreError", "default_plans_root"]

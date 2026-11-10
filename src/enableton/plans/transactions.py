"""The last transaction Enableton applied, kept as data between tool calls.

``ableton_undo`` cannot use Live's undo stack: Live's undo is linear and cannot unwind a plan.
Instead the executor writes the tool-owned restore tokens here after every applied write, and the
undo tool replays them. The record is one JSON file, expires after ten minutes, and is deliberately
outside the Set and outside the process, because the CLI starts a new process per request.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

DEFAULT_TTL_S = 600


class TransactionStoreError(Exception):
    """There is no transaction to undo, it expired, or the record cannot be read."""


def default_transactions_root() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "Enableton" / "transactions"
    return Path.home() / ".enableton" / "transactions"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TransactionStore:
    """Write and read the single ``last.json`` transaction record."""

    def __init__(
        self,
        root: Optional[str] = None,
        clock: Optional[Callable[[], datetime]] = None,
        ttl_s: int = DEFAULT_TTL_S,
    ):
        self.root = Path(root) if root else default_transactions_root()
        self._clock = clock or _utc_now
        self.ttl_s = ttl_s

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def _path(self) -> Path:
        return self.root / "last.json"

    def record(
        self,
        set_path: Optional[str],
        entries: Sequence[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Store the last applied transaction; an empty transaction records nothing."""
        if not entries:
            return None
        self.root.mkdir(parents=True, exist_ok=True)
        now = self._now()
        payload = {
            "set_path": str(set_path) if set_path else None,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=self.ttl_s)).isoformat(),
            "entries": [
                {
                    "tool": str(entry.get("tool")),
                    "cmd": entry.get("cmd"),
                    "undo": list(entry.get("undo") or []),
                }
                for entry in entries
            ],
        }
        path = self._path()
        temporary = path.with_name(path.name + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(str(temporary), str(path))
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise TransactionStoreError(
                "could not store the transaction: %s" % (exc,)
            ) from exc
        return payload

    def get(self) -> Dict[str, Any]:
        path = self._path()
        if not path.is_file():
            raise TransactionStoreError("no applied transaction to undo")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TransactionStoreError(
                "could not read the transaction record: %s" % (exc,)
            ) from exc
        if not isinstance(payload, dict):
            raise TransactionStoreError("the transaction record is malformed")

        entries = payload.get("entries")
        if not isinstance(entries, list) or not entries:
            raise TransactionStoreError("the transaction record has no entries")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("tool"), str):
                raise TransactionStoreError("the transaction record has an invalid entry")
            if not isinstance(entry.get("undo"), list) or not entry["undo"]:
                raise TransactionStoreError("the transaction record has an empty undo token")

        expires_raw = payload.get("expires_at")
        try:
            expires = datetime.fromisoformat(expires_raw)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError) as exc:
            raise TransactionStoreError(
                "the transaction record has an invalid expiry"
            ) from exc
        if self._now() >= expires:
            self.clear()
            raise TransactionStoreError("the last transaction expired after 10 minutes")
        return payload

    def clear(self) -> bool:
        path = self._path()
        if not path.is_file():
            return False
        try:
            path.unlink()
        except OSError as exc:
            raise TransactionStoreError(
                "could not clear the transaction record: %s" % (exc,)
            ) from exc
        return True


__all__ = [
    "DEFAULT_TTL_S", "TransactionStore", "TransactionStoreError",
    "default_transactions_root",
]

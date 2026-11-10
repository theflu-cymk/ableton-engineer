"""A copy of the Set made before the first write of a transaction.

The copy is deliberately outside the Set's folder: a write must never be able to damage the only
copy, and a user's ``.als`` is never written in place. The default is the configurable
``%APPDATA%\\Enableton\\backups`` location from the spec; tests inject a temporary root.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


class ScratchError(Exception):
    """The safety copy could not be made, so the write must not start."""


def default_backups_root() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "Enableton" / "backups"
    return Path.home() / ".enableton" / "backups"


def _safe_stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return stem or "set"


class ScratchCopy:
    """Create one timestamped copy of a Set, once per transaction."""

    def __init__(
        self,
        source: Optional[str] = None,
        root: Optional[str] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.source = Path(source) if source else None
        self.root = Path(root) if root else default_backups_root()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.path = None  # type: Optional[Path]

    def ensure(self) -> Path:
        """Return the existing copy, or make one. Never writes to ``source``."""
        if self.path is not None:
            return self.path
        if self.source is None or not str(self.source).strip():
            raise ScratchError(
                "this Set has no file path; save a copy before the first write so there is "
                "something to recover"
            )
        if not self.source.is_file():
            raise ScratchError("Set file does not exist: %s" % self.source)

        self.root.mkdir(parents=True, exist_ok=True)
        stamp = self._clock().strftime("%Y%m%dT%H%M%SZ")
        stem = _safe_stem(self.source.stem)
        destination = self.root / ("%s-%s.als" % (stem, stamp))
        serial = 1
        while destination.exists():
            destination = self.root / ("%s-%s-%d.als" % (stem, stamp, serial))
            serial += 1
        try:
            shutil.copy2(str(self.source), str(destination))
        except OSError as exc:
            raise ScratchError("could not make the safety copy: %s" % (exc,)) from exc
        self.path = destination
        return destination

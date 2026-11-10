"""One interface, several backends.

Deliberately tiny: a command call and a feature set. Everything richer is a command. That is
what makes a second backend cheap — an Extensions adapter has to provide these two things, not
reimplement the domain.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Optional, Protocol, runtime_checkable


class AdapterError(Exception):
    """A backend failure that is not a protocol error."""


@runtime_checkable
class LiveAdapter(Protocol):
    #: Capabilities this backend actually provides, e.g. {"levels", "warp_markers_read"}.
    features: FrozenSet[str]

    def call(self, cmd: str, args: Optional[Dict[str, Any]] = None,
             timeout_ms: Optional[int] = None) -> Dict[str, Any]:
        """Run one script command and return its result."""
        ...

    def describe(self) -> Dict[str, Any]:
        """Backend name, version and features, for diagnostics."""
        ...

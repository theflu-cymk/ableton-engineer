"""The closed set of error codes.

A closed set is deliberate: every failure a caller can see is one of these, so a client can
branch on the code instead of parsing prose. Adding one is a protocol change.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

ERROR_CODES = frozenset(
    {
        "BAD_REQUEST",         # envelope malformed
        "UNKNOWN_COMMAND",     # no handler for cmd
        "BAD_ARGS",            # argument missing, wrong type, or an unknown key
        "NOT_FOUND",           # a referenced object doesn't exist
        "AMBIGUOUS_REF",       # a name reference matched more than one object
        "LIVE_BUSY",           # another request is in flight, or Live didn't answer in time
        "LIVE_ERROR",          # Live raised
        "UNSUPPORTED",         # capability not available on this build
        "PRECONDITION_FAILED", # the operation doesn't make sense for this object
        "TIMEOUT",             # no reply within the command's timeout
        "DISCONNECTED",        # socket is not open
        "INTERNAL",            # a bug on our side
    }
)


class LiveError(Exception):
    """An error carrying one of ``ERROR_CODES``.

    ``message`` is one sentence a producer can act on; ``detail`` is for the log.
    """

    def __init__(self, code: str, message: str, detail: Optional[Dict[str, Any]] = None):
        if code not in ERROR_CODES:
            raise ValueError("unknown error code %r" % (code,))
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}

    def to_payload(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": self.detail}

    def __str__(self) -> str:
        return "%s: %s" % (self.code, self.message)

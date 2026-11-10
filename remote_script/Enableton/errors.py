"""Errors for the script side.

Deliberately a separate copy of the code set rather than an import from the server package:
Live only has this folder, and a shared import would make the script depend on the server being
installed in the same place.
"""

from __future__ import annotations

CODES = frozenset(
    {
        "BAD_REQUEST",
        "UNKNOWN_COMMAND",
        "BAD_ARGS",
        "NOT_FOUND",
        "AMBIGUOUS_REF",
        "LIVE_BUSY",
        "LIVE_ERROR",
        "UNSUPPORTED",
        "PRECONDITION_FAILED",
        "TIMEOUT",
        "DISCONNECTED",
        "INTERNAL",
    }
)


class ScriptError(Exception):
    def __init__(self, code, message, detail=None):
        if code not in CODES:
            raise ValueError("unknown error code %r" % (code,))
        super(ScriptError, self).__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}

    def to_payload(self):
        return {"code": self.code, "message": self.message, "detail": self.detail}


def unsupported(feature, reason):
    return ScriptError("UNSUPPORTED", reason, {"feature": feature})

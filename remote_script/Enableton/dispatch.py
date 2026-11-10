"""Self-registering command table.

Handlers declare themselves with ``@command("domain.verb")``; there is no central switch. The
server's manifest and this table are asserted equal by ``tests/test_drift.py``, so a tool can't
exist without a handler and a handler can't exist without a declared tool.
"""

from __future__ import annotations

from .errors import ScriptError

HANDLERS = {}


def command(name):
    """Register a handler for ``name``. Duplicate registration is an error, not a shadow."""

    def register(fn):
        if name in HANDLERS:
            raise RuntimeError("duplicate command %r" % name)
        HANDLERS[name] = fn
        return fn

    return register


def check_args(args, allowed=(), required=()):
    """Closed-argument validation: an unknown key is an error, never ignored."""
    if not isinstance(args, dict):
        raise ScriptError("BAD_REQUEST", "args must be an object")

    unknown = sorted(set(args) - set(allowed))
    if unknown:
        raise ScriptError("BAD_ARGS", "unknown argument(s): %s" % ", ".join(unknown))

    missing = [key for key in required if key not in args]
    if missing:
        raise ScriptError("BAD_ARGS", "missing argument(s): %s" % ", ".join(missing))


def call(cmd, args, song):
    """Run one command against a song-like object."""
    handler = HANDLERS.get(cmd)
    if handler is None:
        raise ScriptError("UNKNOWN_COMMAND", "Enableton has no command %r" % (cmd,))
    try:
        return handler(args or {}, song)
    except ScriptError:
        raise
    except Exception as exc:  # a handler bug must not take down the socket thread
        raise ScriptError("INTERNAL", "%s failed: %s" % (cmd, exc))

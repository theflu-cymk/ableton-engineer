"""Enableton — an Ableton Live MCP server.

The package is split into a few deliberate seams:

- ``manifest``   tool definitions, loaded from ``tools.json`` (the single source of truth)
- ``modes``      which tools a session exposes, loaded from ``modes.json``
- ``protocol``   framing, error codes and the blocking transport client
- ``live``       the ``LiveAdapter`` seam and the fake backend used in tests

Nothing in ``manifest``, ``modes`` or ``protocol`` imports ``live``, and nothing outside
``live`` opens a socket.
"""

PROTOCOL_VERSION = 1

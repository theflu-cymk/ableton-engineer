"""Enableton — the Remote Script that runs inside Live.

Live loads a package named after the folder and calls ``create_instance(c_instance)``. Nothing
here imports Live at module scope, so the dispatch table and the framing can be imported by the
test suite and by the fake server without Live present.

Threading contract (spec §3):

- the socket thread parses and replies only; it never touches ``song``
- work is marshalled to the main thread through a queue drained in ``update_display()``
- ``update_display`` calls ``super()`` first, because the framework pumps its own work there
"""

from __future__ import annotations

from . import handlers  # noqa: F401  (importing this package registers every command)
from .server import make_surface


def create_instance(c_instance):
    return make_surface(c_instance)

"""The LiveAdapter seam.

Domain code imports this interface, never a concrete backend. M0 ships the fake backend; M1 adds
the Remote Script one. A new backend means implementing this and passing
``tests/test_adapter_conformance.py``.
"""

from .adapter import AdapterError, LiveAdapter
from .fake import FakeAdapter, FakeServer, FakeSong, build_song

__all__ = [
    "AdapterError",
    "FakeAdapter",
    "FakeServer",
    "FakeSong",
    "LiveAdapter",
    "build_song",
]

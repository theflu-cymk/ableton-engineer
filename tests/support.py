"""Test support: make ``src`` and ``remote_script`` importable without packaging."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

for _rel in ("src", "remote_script", "tests"):
    _path = os.path.join(ROOT, _rel)
    if _path not in sys.path:
        sys.path.insert(0, _path)


def fake_server(**kwargs):
    """Start a FakeServer on an ephemeral port. Caller stops it."""
    from enableton.live.fake import FakeServer

    return FakeServer(port=0, **kwargs).start()

"""4-byte big-endian length + UTF-8 JSON.

The reference implementation parsed the whole receive buffer with ``json.loads`` on every read,
which works until a frame is split across TCP segments or two frames arrive together. This
module accumulates bytes and only ever decodes a complete frame.
"""

from __future__ import annotations

import json
import struct
from typing import Any, Dict, List

HEADER_SIZE = 4
MAX_FRAME = 8 * 1024 * 1024


class FramingError(Exception):
    """The byte stream is not a valid sequence of frames."""


def encode_frame(obj: Dict[str, Any]) -> bytes:
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_FRAME:
        raise FramingError("frame of %d bytes exceeds the %d-byte limit" % (len(body), MAX_FRAME))
    return struct.pack(">I", len(body)) + body


class FrameReader:
    """Incremental decoder. Feed arbitrary chunks, get whole messages back."""

    def __init__(self, max_frame: int = MAX_FRAME):
        self._buf = bytearray()
        self._max = max_frame

    def feed(self, chunk: bytes) -> List[Dict[str, Any]]:
        if chunk:
            self._buf.extend(chunk)

        out: List[Dict[str, Any]] = []
        while True:
            if len(self._buf) < HEADER_SIZE:
                break
            (size,) = struct.unpack(">I", bytes(self._buf[:HEADER_SIZE]))
            if size > self._max:
                raise FramingError("frame of %d bytes exceeds the %d-byte limit" % (size, self._max))
            if len(self._buf) < HEADER_SIZE + size:
                break
            body = bytes(self._buf[HEADER_SIZE:HEADER_SIZE + size])
            del self._buf[:HEADER_SIZE + size]
            try:
                message = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise FramingError("frame is not UTF-8 JSON: %s" % exc)
            if not isinstance(message, dict):
                raise FramingError("frame must be a JSON object")
            out.append(message)
        return out

    def pending(self) -> int:
        """Bytes buffered and not yet decoded — useful in diagnostics."""
        return len(self._buf)

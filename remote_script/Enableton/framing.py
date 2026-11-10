"""Framing, duplicated at the boundary on purpose.

Live only has this folder, so the script cannot import the server's node of the protocol. The
duplication is guarded rather than trusted: ``tests/test_framing.py`` round-trips both
implementations against each other.
"""

from __future__ import annotations

import json
import struct

HEADER_SIZE = 4
MAX_FRAME = 8 * 1024 * 1024


class FramingError(Exception):
    pass


def encode_frame(obj):
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_FRAME:
        raise FramingError("frame too large")
    return struct.pack(">I", len(body)) + body


class FrameReader(object):
    def __init__(self, max_frame=MAX_FRAME):
        self._buf = bytearray()
        self._max = max_frame

    def feed(self, chunk):
        if chunk:
            self._buf.extend(chunk)
        out = []
        while True:
            if len(self._buf) < HEADER_SIZE:
                break
            (size,) = struct.unpack(">I", bytes(self._buf[:HEADER_SIZE]))
            if size > self._max:
                raise FramingError("frame too large")
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

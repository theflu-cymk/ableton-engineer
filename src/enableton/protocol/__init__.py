"""Wire protocol: framing, error codes, and the single blocking client."""

from .client import LiveClient
from .codes import ERROR_CODES, LiveError
from .framing import MAX_FRAME, FrameReader, FramingError, encode_frame

__all__ = [
    "ERROR_CODES",
    "FramingError",
    "FrameReader",
    "LiveClient",
    "LiveError",
    "MAX_FRAME",
    "encode_frame",
]

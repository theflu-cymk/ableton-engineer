"""The one connection to Live.

Owned by the server entrypoint and injected; no other module may open a socket. Requests carry
a monotonic id, and only one may be in flight at a time — a second call gets ``LIVE_BUSY``
immediately rather than queueing behind something that may never answer.
"""

from __future__ import annotations

import socket
import struct
import threading
from typing import Any, Dict, Optional

from .codes import LiveError
from .framing import HEADER_SIZE, FrameReader, FramingError, encode_frame

DEFAULT_PORT = 9878

#: The script's watchdog answers LIVE_BUSY at timeout + 0.5 s, so the client must outlast it —
#: otherwise every slow command looks like a timeout and the typed LIVE_BUSY never arrives.
WATCHDOG_MARGIN_S = 0.75


class LiveClient:
    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 default_timeout_ms: int = 5000):
        self.host = host
        self.port = port
        self.default_timeout_ms = default_timeout_ms
        self._sock: Optional[socket.socket] = None
        self._reader = FrameReader()
        self._next_id = 1
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self, timeout: float = 2.0) -> None:
        if self._sock is not None:
            return
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
        except OSError as exc:
            # A refused connection and a Windows-filtered one both arrive here, and callers
            # only understand LiveError. Never let a raw socket error escape the transport.
            raise LiveError(
                "DISCONNECTED",
                "could not reach Live on %s:%s: %s" % (self.host, self.port, exc),
            )
        sock.settimeout(None)
        self._sock = sock
        self._reader = FrameReader()

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def __enter__(self) -> "LiveClient":
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- calls -------------------------------------------------------------
    def call(self, cmd: str, args: Optional[Dict[str, Any]] = None,
             timeout_ms: Optional[int] = None) -> Dict[str, Any]:
        timeout = (timeout_ms or self.default_timeout_ms) / 1000.0

        if not self._lock.acquire(blocking=False):
            raise LiveError("LIVE_BUSY", "another request is still in flight")
        try:
            if self._sock is None:
                raise LiveError("DISCONNECTED", "not connected to Live")

            self._next_id += 1
            request_id = self._next_id
            payload = {
                "id": request_id,
                "cmd": cmd,
                "args": args or {},
                "timeout_ms": int(timeout * 1000),
            }

            try:
                self._sock.sendall(encode_frame(payload))
            except OSError as exc:
                self.close()
                raise LiveError("DISCONNECTED", "lost the connection to Live: %s" % exc)

            message = self._read_message(timeout, cmd)
            if message.get("id") != request_id:
                raise LiveError(
                    "INTERNAL",
                    "reply id %r did not match request %r" % (message.get("id"), request_id),
                )

            if message.get("ok"):
                return message.get("result") or {}
            error = message.get("error") or {}
            raise LiveError(
                error.get("code", "INTERNAL"),
                error.get("message", "Live returned an error"),
                error.get("detail") or {},
            )
        finally:
            self._lock.release()

    def handshake(self, timeout_ms: Optional[int] = None) -> Dict[str, Any]:
        """Ask the script who it is: protocol version, versions, features."""
        return self.call("hello", {}, timeout_ms=timeout_ms or 2000)

    # -- reading -----------------------------------------------------------
    def _read_message(self, timeout: float, cmd: str) -> Dict[str, Any]:
        assert self._sock is not None
        self._sock.settimeout(timeout + WATCHDOG_MARGIN_S)
        try:
            while True:
                messages = self._reader.feed(b"")
                if messages:
                    return messages[0]
                header = self._recv_exact(HEADER_SIZE)
                (size,) = struct.unpack(">I", header)
                body = self._recv_exact(size) if size else b""
                messages = self._reader.feed(header + body)
                if messages:
                    return messages[0]
        except socket.timeout:
            raise LiveError("TIMEOUT", "%s did not answer within %.0f ms" % (cmd, timeout * 1000))
        except FramingError as exc:
            self.close()
            raise LiveError("INTERNAL", "bad reply from Live: %s" % exc)
        except OSError as exc:
            self.close()
            raise LiveError("DISCONNECTED", "lost the connection to Live: %s" % exc)

    def _recv_exact(self, size: int) -> bytes:
        assert self._sock is not None
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self._sock.recv(size - len(chunks))
            if not chunk:
                raise OSError("peer closed the connection")
            chunks.extend(chunk)
        return bytes(chunks)

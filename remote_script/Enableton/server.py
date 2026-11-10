"""The socket server and the main-thread bridge.

The important part is *what isn't here*: no ``schedule_message``. The framework copies its
scheduled-task list and replaces it on the main thread, so a task appended from the socket thread
between those two steps is silently dropped and the request times out. A queue drained by
``update_display()`` has no such window.

``update_display`` must call ``super().update_display()`` first — the framework pumps its own
scheduled work and components there, and an override without it leaves every real command timing
out while ping still answers.
"""

from __future__ import annotations

import hashlib
import os
import queue
import socket
import threading
import types

from . import dispatch
from .errors import ScriptError
from .framing import FrameReader, FramingError, encode_frame

DEFAULT_PORT = 9878
PROTOCOL_VERSION = 1
SCRIPT_VERSION = "0.1.9"
MAX_QUEUED = 8


def build_digest(root=None):
    """A content hash of the loaded script, so a stale build names itself.

    ``SCRIPT_VERSION`` is hand-bumped and therefore forgettable — which is exactly how three rounds
    of debugging happened against a build nobody had actually loaded. ``doctor`` compares this
    digest with the repo's and says so outright instead of trusting a string someone must remember.
    """
    here = root or os.path.dirname(os.path.abspath(__file__))
    entries = []
    for base, dirs, files in os.walk(here):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            try:
                with open(path, "rb") as handle:
                    body = handle.read()
            except OSError:
                continue
            relative = os.path.relpath(path, here).replace(os.sep, "/")
            entries.append("%s:%s" % (relative, hashlib.sha256(body).hexdigest()))
    return hashlib.sha256("\n".join(sorted(entries)).encode("utf-8")).hexdigest()[:12]


BUILD = build_digest()


def _safe_log(target, text):
    """Best-effort diagnostics: a log call must never be able to abort the surface.

    ``ControlSurface`` does not reliably expose ``log_message`` — Live 12.2.5 raises
    ``'EnabletonSurface' object has no attribute 'log_message'`` — and an exception during
    construction kills the surface while leaving the daemon socket thread alive. The result is the
    worst failure shape available: ``hello`` answers forever, ``display`` stays at 0, and every real
    command stalls, looking exactly like a dead main thread.
    """
    for name in ("log_message", "show_message"):
        log = getattr(target, name, None)
        if callable(log):
            try:
                log(text)
                return
            except Exception:
                pass
    instance = getattr(target, "_c_instance", None)
    log = getattr(instance, "log_message", None) if instance is not None else None
    if callable(log):
        try:
            log(text)
        except Exception:
            pass


def resolve_song(holder):
    """Return the Song object from a ControlSurface, whichever shape it exposes.

    ``callable(song)`` is *not* a safe test: Live's LOM objects answer it truthily and then raise
    ``TypeError: 'Song' object is not callable`` when invoked, so a callable-based guard picks the
    wrong branch on exactly the shape it was written to handle. A bound method is the only thing
    that should be called.
    """
    song = getattr(holder, "song", None)
    if isinstance(song, types.MethodType):
        return song()
    return song


def live_version_string():
    """The Live build, read once on the main thread.

    Two reasons this is a function and not a property of the socket thread: LOM calls from a
    worker thread are unsafe, and ``get_major_version`` alone answers "12" where the useful answer
    is "12.2.5".
    """
    try:
        import Live

        app = Live.Application.get_application()
        getter = getattr(app, "get_version_string", None)
        if callable(getter):
            text = str(getter() or "")
            if text:
                return text
        parts = []
        for name in ("get_major_version", "get_minor_version", "get_bugfix_version"):
            getter = getattr(app, name, None)
            if callable(getter):
                parts.append(str(getter()))
        return ".".join(parts) or "unknown"
    except Exception:
        return "unknown"


class Bridge(object):
    """Owns the socket and the work queue. No Live objects, so it is testable."""

    def __init__(self, song_provider, host="127.0.0.1", port=None,
                 features=("levels", "snapshot"), live_version="unknown"):
        self._song_provider = song_provider
        self._host = host
        # ``port or DEFAULT_PORT`` would turn an explicit 0 ("pick an ephemeral port") into the
        # real port, which silently made the test suite fight Live for 9878.
        self._port = int(DEFAULT_PORT if port is None else port)
        if not self._port:
            self._port = 0
        self._features = tuple(features)
        self.live_version = str(live_version)
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._sock = None
        self._thread = None
        # ``drains`` separates "Live never ticked the surface" from "the queue ran the work but
        # the reply was lost". Without it both look identical: a timeout.
        self.stats = {"requests": 0, "busy": 0, "errors": 0, "drains": 0, "ran": 0,
                      "display": 0, "super_errors": 0}

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self._host, self._port))
        sock.listen(4)
        self._sock = sock
        self._thread = threading.Thread(target=self._accept_loop, name="enableton-socket")
        self._thread.daemon = True
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    @property
    def port(self):
        return self._sock.getsockname()[1] if self._sock is not None else self._port

    @property
    def host(self):
        return self._host

    @property
    def features(self):
        return self._features

    # -- main thread -------------------------------------------------------
    def drain(self, max_tasks=8):
        """Run queued work. Called from ``update_display`` on Live's main thread."""
        self.stats["drains"] += 1
        for _ in range(max_tasks):
            try:
                cmd, args, box, done = self._queue.get_nowait()
            except queue.Empty:
                return
            self.stats["ran"] += 1
            try:
                box["result"] = dispatch.call(cmd, args, self._song_provider())
            except ScriptError as exc:
                self.stats["errors"] += 1
                box["error"] = exc.to_payload()
            except Exception as exc:
                self.stats["errors"] += 1
                box["error"] = {"code": "INTERNAL", "message": str(exc), "detail": {}}
            finally:
                done.set()

    # -- socket thread -----------------------------------------------------
    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            worker = threading.Thread(target=self._serve, args=(conn,), name="enableton-conn")
            worker.daemon = True
            worker.start()

    def _serve(self, conn):
        reader = FrameReader()
        try:
            while not self._stop.is_set():
                chunk = conn.recv(65536)
                if not chunk:
                    return
                for request in reader.feed(chunk):
                    conn.sendall(encode_frame(self._handle(request)))
        except (FramingError, OSError):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _handle(self, request):
        request_id = request.get("id")
        cmd = request.get("cmd")

        if not isinstance(cmd, str):
            return self._error(request_id, "BAD_REQUEST", "cmd must be a string")

        if cmd == "hello":
            return self._ok(request_id, {
                "protocol": PROTOCOL_VERSION,
                "script": SCRIPT_VERSION,
                "live": self.live_version,
                "features": list(self._features),
                # Depth and counters: a timeout is otherwise indistinguishable from a surface
                # that Live never ticked, which is the one failure this design can't see.
                "queued": self._queue.qsize(),
                "stats": dict(self.stats),
                "build": BUILD,
            })

        if self._queue.qsize() >= MAX_QUEUED:
            self.stats["busy"] += 1
            return self._error(request_id, "LIVE_BUSY", "Enableton is behind; try again")

        timeout_ms = request.get("timeout_ms")
        timeout_s = (timeout_ms / 1000.0) if isinstance(timeout_ms, (int, float)) else 5.0
        box = {}
        done = threading.Event()
        self.stats["requests"] += 1

        self._queue.put((cmd, request.get("args") or {}, box, done))
        # Answer *before* the client's watchdog fires. Waiting ``timeout_s + 0.5`` inverts that
        # margin: the bridge's own LIVE_BUSY then arrives after the client has given up and
        # discarded it, so every undrained command surfaces as an unexplained TIMEOUT.
        if not done.wait(max(0.05, timeout_s * 0.9)):
            self.stats["busy"] += 1
            return self._error(request_id, "LIVE_BUSY",
                               "%s did not run; Live may be busy" % cmd)

        if "error" in box:
            return {"id": request_id, "ok": False, "error": box["error"]}
        return self._ok(request_id, box.get("result") or {})

    @staticmethod
    def _ok(request_id, result):
        return {"id": request_id, "ok": True, "result": result}

    @staticmethod
    def _error(request_id, code, message):
        return {"id": request_id, "ok": False,
                "error": {"code": code, "message": message, "detail": {}}}


def make_surface(c_instance):
    """Build the ControlSurface Live loads. Live is imported here, not at module scope."""
    from ableton.v2.control_surface import ControlSurface

    class EnabletonSurface(ControlSurface):
        def __init__(self, c_instance):
            super(EnabletonSurface, self).__init__(c_instance)
            self._bridge = Bridge(self._current_song,
                                  features=("levels", "snapshot"),
                                  live_version=live_version_string())
            try:
                self._bridge.start()
            except OSError as exc:
                _safe_log(self, "Enableton: could not listen on %s:%s: %s"
                          % (self._bridge.host, self._bridge.port, exc))
                self.show_message("Enableton could not start: %s" % exc)
            else:
                # Silence here made "did the script load?" unanswerable from Live's log, which
                # is the only diagnostic a user can reach without a terminal.
                _safe_log(self, "Enableton: listening on %s:%s"
                          % (self._bridge.host, self._bridge.port))

        def _current_song(self):
            """Live 12 exposes ``ControlSurface.song`` as a property.

            Calling it hands back a Song object, which then fails with "'Song' object is not
            callable"; older frameworks made it a method. Accept both shapes.
            """
            return resolve_song(self)

        def update_display(self):
            # ``display`` proves Live ticked us at all; ``super_errors`` proves the framework's own
            # plumbing ran. Two counters because a frozen ``drains`` has two different causes and
            # only one of them is our code.
            self._bridge.stats["display"] += 1
            if self._bridge.stats["display"] == 1:
                _safe_log(self, "Enableton: first update_display tick")
            try:
                super(EnabletonSurface, self).update_display()
            except Exception as exc:
                self._bridge.stats["super_errors"] += 1
                self._bridge.stats["last_super_error"] = "%s: %s" % (type(exc).__name__, exc)
            self._bridge.drain()

        def disconnect(self):
            self._bridge.stop()
            super(EnabletonSurface, self).disconnect()

    return EnabletonSurface(c_instance)

"""A fake Live that is honest about being one.

Two uses, both in tests: ``FakeAdapter`` calls the Remote Script's handlers in-process (so
domain tests need no sockets), and ``FakeServer`` exposes the same handlers over the real wire
protocol (so the framing, client and timeouts are exercised for real).

The handlers are imported from ``remote_script/Enableton``, not reimplemented — if the two sides
drift, the tests fail. The fake objects mimic the LOM shape the handlers read (``clip_slots``,
``arrangement_clips``, ``devices``), so a handler that only works on the fake also fails here.
"""

from __future__ import annotations

import copy
import socket
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..protocol.framing import FrameReader, FramingError, encode_frame

from Enableton import dispatch as _dispatch  # type: ignore  # remote_script is on sys.path
from Enableton.errors import ScriptError

FEATURES = frozenset({"levels", "snapshot"})


@dataclass
class FakeDevice:
    name: str
    class_name: str = "Eq8"
    is_active: bool = True


@dataclass
class FakeNote:
    pitch: int
    start_time: float
    duration: float
    velocity: int = 100
    mute: bool = False


@dataclass
class FakeClip:
    name: str
    start_time: float = 0.0
    end_time: float = 4.0
    is_midi_clip: bool = False
    warping: bool = False
    warp_mode: int = 0
    warp_markers: List[Any] = field(default_factory=list)
    notes: List[FakeNote] = field(default_factory=list)

    @property
    def length(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    def set_notes(self, notes) -> None:
        """Mirror Live's whole-vector write so notes handlers take the real path here."""
        self.notes = [
            FakeNote(int(pitch), float(start), float(duration), int(velocity), bool(mute))
            for pitch, start, duration, velocity, mute in notes
        ]


@dataclass
class FakeClipSlot:
    clip: Optional[FakeClip] = None

    @property
    def has_clip(self) -> bool:
        return self.clip is not None


@dataclass
class FakeScene:
    name: str = ""


@dataclass
class FakeLocator:
    name: str = ""
    time: float = 0.0


@dataclass
class FakeTrack:
    name: str
    volume: float = 0.7
    pan: float = 0.0
    peak_db: Optional[float] = None
    is_midi: bool = False
    mute: bool = False
    solo: bool = False
    arm: bool = False
    is_foldable: bool = False
    group_index: Optional[int] = None
    devices: List[FakeDevice] = field(default_factory=list)
    clip_slots: List[FakeClipSlot] = field(default_factory=list)
    arrangement_clips: List[FakeClip] = field(default_factory=list)

    @property
    def has_midi_input(self) -> bool:
        return self.is_midi

    def duplicate_clip_to_arrangement(self, clip: "FakeClip", destination_time: float):
        duplicate = copy.deepcopy(clip)
        duplicate.start_time = float(destination_time)
        duplicate.end_time = duplicate.start_time + clip.length
        self.arrangement_clips.append(duplicate)
        self.arrangement_clips.sort(key=lambda item: item.start_time)
        return duplicate

    def delete_clip(self, clip: "FakeClip") -> None:
        self.arrangement_clips.remove(clip)
        # Live's proxy no longer reports a name once the clip is deleted; keep the fake honest so a
        # handler cannot read state after deleting and still pass here.
        clip.name = ""


@dataclass
class FakeSong:
    name: str = "M0 Fake Set"
    file_path: str = ""
    tempo: float = 140.0
    signature_numerator: int = 4
    signature_denominator: int = 4
    is_playing: bool = False
    current_song_time: float = 0.0
    loop_start: float = 0.0
    loop_length: float = 16.0
    loop: bool = True
    tracks: List[FakeTrack] = field(default_factory=list)
    return_tracks: List[FakeTrack] = field(default_factory=list)
    scenes: List[FakeScene] = field(default_factory=list)
    locators: List[FakeLocator] = field(default_factory=list)

    def start_playing(self) -> None:
        self.is_playing = True

    def stop_playing(self) -> None:
        self.is_playing = False


def build_song() -> FakeSong:
    """A small arrangement-first Set: 2 sections, one empty track, one empty scene.

    Modelled on the shape the user's real Sets have (spec §2): most material is in the
    arrangement, Session holds a couple of clips, and there are no named locators.
    """
    return FakeSong(
        tracks=[
            FakeTrack(
                "Drums",
                volume=0.82,
                peak_db=-1.5,
                is_midi=True,
                devices=[FakeDevice("EQ Eight", "Eq8"), FakeDevice("Glue", "GlueCompressor")],
                clip_slots=[
                    FakeClipSlot(FakeClip(
                        "drums A", 0.0, 8.0, True,
                        notes=[
                            FakeNote(36, 0.0, 1.0, 110),
                            FakeNote(36, 0.5, 1.0, 96),
                            FakeNote(38, 0.0, 0.5, 100),
                        ],
                    )),
                    FakeClipSlot(),
                    FakeClipSlot(),
                ],
                arrangement_clips=[
                    FakeClip("drums 1", 0.0, 16.0, True),
                    FakeClip("drums 2", 32.0, 48.0, True),
                ],
            ),
            FakeTrack(
                "Bass layer",
                volume=0.65,
                peak_db=-7.0,
                devices=[FakeDevice("EQ Eight", "Eq8")],
                clip_slots=[
                    FakeClipSlot(),
                    FakeClipSlot(FakeClip("bass drop", 0.0, 8.0)),
                    FakeClipSlot(),
                ],
                arrangement_clips=[FakeClip("bass", 32.0, 64.0)],
            ),
            FakeTrack(
                "Vocal chop",
                volume=0.5,
                peak_db=None,
                clip_slots=[FakeClipSlot(), FakeClipSlot(), FakeClipSlot()],
            ),
        ],
        scenes=[FakeScene("intro"), FakeScene("drop"), FakeScene("outro")],
        locators=[],
    )


class FakeAdapter:
    """In-process adapter: same handlers as the script, no socket."""

    features = FEATURES

    def __init__(self, song: Optional[FakeSong] = None):
        self.song = song or build_song()

    def call(self, cmd: str, args: Optional[Dict[str, Any]] = None,
             timeout_ms: Optional[int] = None) -> Dict[str, Any]:
        return _dispatch.call(cmd, args or {}, self.song)

    def describe(self) -> Dict[str, Any]:
        return {"backend": "fake", "features": sorted(self.features)}


class FakeServer:
    """Serves the dispatch table over TCP, honouring the real wire protocol."""

    def __init__(self, song: Optional[FakeSong] = None, host: str = "127.0.0.1", port: int = 0):
        self.song = song or build_song()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(4)
        self.host, self.port = self._sock.getsockname()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> "FakeServer":
        self._thread = threading.Thread(target=self._accept_loop, name="fake-live", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def __enter__(self) -> "FakeServer":
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.stop()

    # -- serving -----------------------------------------------------------
    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
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

    def _handle(self, request: Dict[str, Any]) -> Dict[str, Any]:
        request_id = request.get("id")
        cmd = request.get("cmd")
        if not isinstance(cmd, str):
            return {"id": request_id, "ok": False,
                    "error": {"code": "BAD_REQUEST", "message": "cmd must be a string", "detail": {}}}

        if cmd == "hello":
            return {"id": request_id, "ok": True, "result": {
                "protocol": 1, "script": "0.1.0", "live": "12.2.5 (fake)",
                "features": sorted(FEATURES)}}

        try:
            result = _dispatch.call(cmd, request.get("args") or {}, self.song)
            return {"id": request_id, "ok": True, "result": result}
        except ScriptError as exc:
            return {"id": request_id, "ok": False, "error": exc.to_payload()}
        except Exception as exc:  # keep the server alive; the client sees INTERNAL
            return {"id": request_id, "ok": False,
                    "error": {"code": "INTERNAL", "message": str(exc), "detail": {}}}

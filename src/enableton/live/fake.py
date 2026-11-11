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
from Enableton.errors import Deferred, ScriptError

FEATURES = frozenset({"levels", "snapshot"})


@dataclass
class FakeDeviceParameter:
    name: str
    value: float = 0.0
    min: float = 0.0
    max: float = 1.0
    is_enabled: bool = True
    is_quantized: bool = False
    value_items: List[str] = field(default_factory=list)


@dataclass
class FakeDevice:
    name: str
    class_name: str = "Eq8"
    is_active: bool = True
    parameters: List["FakeDeviceParameter"] = field(default_factory=list)


@dataclass
class FakeSend:
    value: float = 0.0
    name: str = ""


@dataclass
class FakeNote:
    pitch: int
    start_time: float
    duration: float
    velocity: int = 100
    mute: bool = False
    note_id: int = 0


@dataclass
class FakeClip:
    name: str
    start_time: float = 0.0
    end_time: float = 4.0
    is_midi_clip: bool = False
    warping: bool = False
    warp_mode: int = 0
    warp_markers: List[Any] = field(default_factory=list)
    loop_start: float = 0.0
    loop_end: float = 4.0
    looping: bool = True
    notes: List[FakeNote] = field(default_factory=list)
    _next_note_id: int = field(default=1, init=False, repr=False)

    def __post_init__(self) -> None:
        for note in self.notes:
            if not note.note_id:
                note.note_id = self._next_note_id
                self._next_note_id += 1
        if self.notes:
            self._next_note_id = max(
                self._next_note_id, max(note.note_id for note in self.notes) + 1
            )

    @property
    def length(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    def set_notes(self, notes) -> None:
        """Live's ``set_notes`` adds notes; it does not replace the vector.

        The handlers must clear with ``remove_notes_extended`` (or ``remove_notes_by_id``)
        first. Modelling the real append here is what keeps a replacing fake from hiding
        that defect again.
        """
        for pitch, start, duration, velocity, mute in notes:
            self.notes.append(FakeNote(
                int(pitch), float(start), float(duration), int(velocity), bool(mute),
                note_id=self._next_note_id,
            ))
            self._next_note_id += 1

    def get_all_notes_extended(self):
        return list(self.notes)

    def remove_notes_by_id(self, ids) -> None:
        doomed = {int(note_id) for note_id in ids}
        self.notes = [note for note in self.notes if note.note_id not in doomed]

    def remove_notes_extended(self, from_pitch, pitch_span, from_time, time_span) -> None:
        """Live deletes notes whose start lies in the given pitch/time window."""
        self.notes = [
            note for note in self.notes
            if not (
                from_pitch <= note.pitch < from_pitch + pitch_span
                and from_time <= note.start_time < from_time + time_span
            )
        ]


@dataclass
class FakeClipSlot:
    clip: Optional[FakeClip] = None

    @property
    def has_clip(self) -> bool:
        return self.clip is not None

    def duplicate_clip_to(self, destination: "FakeClipSlot") -> None:
        if self.clip is None:
            raise RuntimeError("no clip to duplicate")
        destination.clip = copy.deepcopy(self.clip)

    def delete_clip(self) -> None:
        self.clip = None


@dataclass
class FakeRouting:
    """A routing type or channel, with the fields Live uses to distinguish duplicates."""

    display_name: str
    identifier: str = ""
    category: Any = None
    attached_object: Any = None
    layout: Any = None


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
    color: int = 0
    peak_db: Optional[float] = None
    is_midi: bool = False
    mute: bool = False
    solo: bool = False
    arm: bool = False
    is_foldable: bool = False
    group_index: Optional[int] = None
    devices: List[FakeDevice] = field(default_factory=list)
    sends: List[FakeSend] = field(default_factory=list)
    clip_slots: List[FakeClipSlot] = field(default_factory=list)
    arrangement_clips: List[FakeClip] = field(default_factory=list)
    input_routing_type: FakeRouting = field(
        default_factory=lambda: FakeRouting("All Ins", "AllIns"))
    input_routing_channel: FakeRouting = field(
        default_factory=lambda: FakeRouting("All Channels", "AllChannels"))
    output_routing_type: FakeRouting = field(
        default_factory=lambda: FakeRouting("Master", "Master"))
    output_routing_channel: FakeRouting = field(
        default_factory=lambda: FakeRouting("Track In", "TrackIn"))
    available_input_routing_types: List[FakeRouting] = field(
        default_factory=lambda: [
            FakeRouting("All Ins", "AllIns"), FakeRouting("Ext. In", "ExtIn")
        ]
    )
    available_input_routing_channels: List[FakeRouting] = field(
        default_factory=lambda: [
            FakeRouting("All Channels", "AllChannels"),
            FakeRouting("1", "Input1"),
            FakeRouting("2", "Input2"),
        ]
    )
    available_output_routing_types: List[FakeRouting] = field(
        default_factory=lambda: [
            FakeRouting("Master", "Master"), FakeRouting("Sends Only", "SendsOnly")
        ]
    )
    available_output_routing_channels: List[FakeRouting] = field(
        default_factory=lambda: [
            FakeRouting("Track In", "TrackIn"), FakeRouting("1", "Output1")
        ]
    )

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

    def move_device(self, device: "FakeDevice", new_index: int) -> None:
        """Live's move_device takes a device object and its final index."""
        self.devices.insert(new_index, self.devices.pop(self.devices.index(device)))

    def delete_device(self, index: int) -> None:
        del self.devices[index]


@dataclass
class FakeBrowserItem:
    name: str
    is_folder: bool = False
    is_loadable: bool = False
    uri: str = ""
    children: List["FakeBrowserItem"] = field(default_factory=list)


@dataclass
class FakeBrowser:
    """Just enough of Live's browser to exercise the read path."""

    sounds: FakeBrowserItem = field(default_factory=lambda: FakeBrowserItem(
        "Sounds", True, False, "query:Sounds",
        [
            FakeBrowserItem("Bass", True, False, "query:Sounds#Bass", [
                FakeBrowserItem("Sub Bass.adv", False, True, "file:Sub Bass.adv"),
            ]),
            FakeBrowserItem("Pads", True, False, "query:Sounds#Pads", []),
        ],
    ))
    user_library: FakeBrowserItem = field(default_factory=lambda: FakeBrowserItem(
        "User Library", True, False, "query:UserLibrary",
        [FakeBrowserItem("Presets", True, False, "query:UserLibrary#Presets", [])],
    ))
    instruments: FakeBrowserItem = field(default_factory=lambda: FakeBrowserItem(
        "Instruments", True, False, "query:Instruments",
        [
            FakeBrowserItem("Analog", True, False, "query:Instruments#Analog", [
                FakeBrowserItem("Bass Analog.adv", False, True, "file:Bass Analog.adv"),
            ]),
            FakeBrowserItem("Operator", True, False, "query:Instruments#Operator", [
                FakeBrowserItem("Pad Operator.adv", False, True, "file:Pad Operator.adv"),
            ]),
        ],
    ))
    audio_effects: FakeBrowserItem = field(default_factory=lambda: FakeBrowserItem(
        "Audio Effects", True, False, "query:AudioEffects",
        [
            FakeBrowserItem("EQ Eight", False, False, "query:AudioEffects#EQ Eight", [
                FakeBrowserItem("Vocal EQ.adv", False, True, "file:Vocal EQ.adv"),
            ]),
        ],
    ))
    midi_effects: FakeBrowserItem = field(default_factory=lambda: FakeBrowserItem(
        "MIDI Effects", True, False, "query:MidiEffects", []
    ))


@dataclass
class FakeSong:
    name: str = "M0 Fake Set"
    file_path: str = ""
    tempo: float = 140.0
    signature_numerator: int = 4
    signature_denominator: int = 4
    is_playing: bool = False
    current_song_time: float = 0.0
    #: Live applies ``current_song_time`` between display ticks; cue writes use this value.
    rendered_song_time: float = 0.0
    ticks: int = 0
    loop_start: float = 0.0
    loop_length: float = 16.0
    loop: bool = True
    tracks: List[FakeTrack] = field(default_factory=list)
    return_tracks: List[FakeTrack] = field(default_factory=list)
    scenes: List[FakeScene] = field(default_factory=list)
    locators: List[FakeLocator] = field(default_factory=list)
    browser: FakeBrowser = field(default_factory=FakeBrowser)

    def start_playing(self) -> None:
        self.is_playing = True

    def stop_playing(self) -> None:
        self.is_playing = False

    def tick(self) -> None:
        """A display tick: the pending playhead becomes the one cue writes use."""
        self.rendered_song_time = float(self.current_song_time)
        self.ticks += 1

    def set_or_delete_cue(self) -> None:
        """Live toggles one cue at the *ticked* playhead, not at an unapplied seek."""
        time = float(self.rendered_song_time)
        for index, locator in enumerate(self.locators):
            if abs(float(locator.time) - time) <= 1e-6:
                del self.locators[index]
                return
        self.locators.append(FakeLocator("", time))
        self.locators.sort(key=lambda item: item.time)

    def duplicate_track(self, index: int) -> FakeTrack:
        duplicate = copy.deepcopy(self.tracks[index])
        self.tracks.insert(index + 1, duplicate)
        return duplicate

    def delete_track(self, index: int) -> None:
        """Live's signature is delete_track(ASong, int): a Track object raises a type error."""
        del self.tracks[index]

    def create_scene(self, index: int = -1) -> FakeScene:
        scene = FakeScene("")
        if index < 0 or index >= len(self.scenes):
            self.scenes.append(scene)
        else:
            self.scenes.insert(index, scene)
        return scene

    def delete_scene(self, index: int) -> None:
        del self.scenes[index]

    def move_device(self, device: "FakeDevice", track: "FakeTrack", position: int) -> int:
        """Live 12.2.5's mover lives on Song, not Track; the position it used is returned.

        It indexes the chain *before* the device is taken out, so a forward move lands one index
        short unless the caller raises the position by one. The real gate caught this: ``2 -> 3``
        did nothing and ``2 -> 4`` landed at 3. Mirroring that here is what keeps a handler that
        forgets the correction from passing.
        """
        try:
            start = track.devices.index(device)
        except ValueError:
            # Live hands back a fresh proxy on every access, so the caller's object is not the one
            # in the list. Resolve it by name, the way Live resolves the underlying device.
            start = next(
                index for index, item in enumerate(track.devices) if item.name == device.name
            )
            device = track.devices[start]
        track.devices.pop(start)
        if position > start:
            position -= 1
        position = max(0, min(position, len(track.devices)))
        track.devices.insert(position, device)
        return position


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
                devices=[
                    FakeDevice(
                        "EQ Eight", "Eq8",
                        parameters=[FakeDeviceParameter("Gain", 0.0, -12.0, 12.0)],
                    ),
                    FakeDevice("Glue", "GlueCompressor"),
                ],
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


def _run_with_ticks(cmd: str, args: Dict[str, Any], song: FakeSong) -> Dict[str, Any]:
    """Run a command the way the bridge does: a Deferred step resumes after one tick."""
    result = _dispatch.call(cmd, args, song)
    for _ in range(1000):
        if not isinstance(result, Deferred):
            return result
        song.tick()
        result = result.run(song)
    raise RuntimeError("%s deferred more than 1000 times" % (cmd,))


class FakeAdapter:
    """In-process adapter: same handlers as the script, no socket."""

    features = FEATURES

    def __init__(self, song: Optional[FakeSong] = None):
        self.song = song or build_song()

    def call(self, cmd: str, args: Optional[Dict[str, Any]] = None,
             timeout_ms: Optional[int] = None) -> Dict[str, Any]:
        return _run_with_ticks(cmd, args or {}, self.song)

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
            result = _run_with_ticks(cmd, request.get("args") or {}, self.song)
            return {"id": request_id, "ok": True, "result": result}
        except ScriptError as exc:
            return {"id": request_id, "ok": False, "error": exc.to_payload()}
        except Exception as exc:  # keep the server alive; the client sees INTERNAL
            return {"id": request_id, "ok": False,
                    "error": {"code": "INTERNAL", "message": str(exc), "detail": {}}}

"""Resample capture of the master output.

Master -> a scratch audio track whose input is set to ``Resampling`` -> an empty Session slot ->
a WAV in ``Samples/Recorded``. **Real time and audible.**

Two failures make this worth a handler instead of three loose calls. An invalid input routing arm
is a *silent no-op* on Live 12.2.5, so the setter is verified by reading the routing back before the
track is armed. And a recording left running, or a track left armed on Resampling, changes the Set
after the request has already returned; every failure path restores the routing, the arm state and
stops the transport before raising.

The handler samples time on display ticks through ``Deferred``, the same way ``mix.meter_poll``
does, so Live's main thread never blocks. It deletes the temporary clip it created but keeps the
WAV: the file is the point of the capture.
"""

from __future__ import annotations

import os
import time

from ..dispatch import check_args, command
from ..errors import Deferred, ScriptError
from ..routing import (
    attr as _attr,
    identifier as _identifier,
    index_of as _index_of,
    label as _label,
    pick as _pick,
    ref as _ref,
)

_DEFAULT_MS = 2000
_MIN_MS = 250
_MAX_MS = 10000
_MAX_TICKS = 4096
_MAX_CLIP_TICKS = 40
_MIN_WAV_BYTES = 44


def _clock():
    """Monotonic seconds. Separate so a test can advance the window without sleeping."""
    return time.monotonic()


def _same_route(left, right):
    if left is None or right is None:
        return left is right
    return (_label(left), _identifier(left)) == (_label(right), _identifier(right))


def _track(song, wanted):
    tracks = list(_attr(song, "tracks", []) or [])
    if isinstance(wanted, bool) or not isinstance(wanted, (int, str)):
        raise ScriptError("BAD_ARGS", "track must be a name or an integer index")
    if isinstance(wanted, int):
        if wanted < 0 or wanted >= len(tracks):
            message = "no track at index %d" % (wanted,)
            if tracks:
                message += "; indexes run 0..%d" % (len(tracks) - 1,)
            raise ScriptError("NOT_FOUND", message)
        index, track = wanted, tracks[wanted]
    else:
        if not wanted:
            raise ScriptError("BAD_ARGS", "track names must be non-empty")
        matches = [
            (index, track) for index, track in enumerate(tracks)
            if str(_attr(track, "name", "") or "") == wanted
        ]
        if not matches:
            matches = [
                (index, track) for index, track in enumerate(tracks)
                if str(_attr(track, "name", "") or "").casefold() == wanted.casefold()
            ]
        if not matches:
            available = ", ".join(
                "%d: %s" % (index, _attr(track, "name", "") or "<unnamed>")
                for index, track in enumerate(tracks)
            ) or "none"
            raise ScriptError(
                "NOT_FOUND", "no track named %r; available: %s" % (wanted, available)
            )
        if len(matches) > 1:
            raise ScriptError(
                "AMBIGUOUS_REF",
                "%d tracks are named %r; use a track index instead" % (len(matches), wanted),
            )
        index, track = matches[0]

    name = str(_attr(track, "name", "") or "")
    if _attr(track, "is_foldable", False):
        raise ScriptError(
            "PRECONDITION_FAILED",
            "%r is a group track; resampling needs an audio track" % (name,),
        )
    if _attr(track, "has_midi_input", False) or _attr(track, "is_midi", False):
        raise ScriptError(
            "PRECONDITION_FAILED",
            "%r is a MIDI track; resampling needs an audio track" % (name,),
        )
    return index, track, name


def _slot(track, wanted):
    slots = list(_attr(track, "clip_slots", []) or [])
    if not slots:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "track %r has no Session clip slots to record into"
            % (str(_attr(track, "name", "")),),
        )
    if wanted is None:
        for index, slot in enumerate(slots):
            if not _attr(slot, "has_clip", False):
                return index, slot
        raise ScriptError(
            "PRECONDITION_FAILED",
            "every Session slot on %r holds a clip; pass an empty slot"
            % (str(_attr(track, "name", "")),),
        )
    if isinstance(wanted, bool) or not isinstance(wanted, int) or wanted < 0:
        raise ScriptError("BAD_ARGS", "slot must be a non-negative integer")
    if wanted >= len(slots):
        raise ScriptError(
            "NOT_FOUND",
            "no slot at index %d; %r has slots 0..%d"
            % (wanted, str(_attr(track, "name", "")), len(slots) - 1),
        )
    slot = slots[wanted]
    if _attr(slot, "has_clip", False):
        free = [
            index for index, candidate in enumerate(slots)
            if not _attr(candidate, "has_clip", False)
        ]
        hint = ", ".join(str(index) for index in free) if free else "none"
        raise ScriptError(
            "PRECONDITION_FAILED",
            "slot %d on %r already holds a clip; empty slots: %s"
            % (wanted, str(_attr(track, "name", "")), hint),
        )
    return wanted, slot


def _resampling(track):
    options = list(_attr(track, "available_input_routing_types", []) or [])
    if not options:
        raise ScriptError(
            "UNSUPPORTED",
            "%r exposes no input routing types" % (str(_attr(track, "name", "")),),
        )
    choice = _pick(options, "Resampling", "input type")
    return choice, _index_of(options, choice)


def _arm(track, value):
    try:
        track.arm = bool(value)
    except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
        raise ScriptError(
            "UNSUPPORTED", "this Live build refused the track arm: %s" % (exc,)
        )
    readback = _attr(track, "arm", None)
    if readback is None:
        raise ScriptError("UNSUPPORTED", "the track arm cannot be read back on this build")
    if bool(readback) != bool(value):
        raise ScriptError(
            "PRECONDITION_FAILED",
            "the track arm did not take: asked for %s, Live reports %s"
            % (bool(value), bool(readback)),
        )


def _set_resampling(track, choice):
    try:
        track.input_routing_type = choice
    except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
        raise ScriptError(
            "UNSUPPORTED", "this Live build refused the input routing: %s" % (exc,)
        )
    readback = _attr(track, "input_routing_type", None)
    if not _same_route(readback, choice):
        raise ScriptError(
            "PRECONDITION_FAILED",
            "the input routing did not take: Live reports %r instead of %r"
            % (_label(readback) or "nothing", _label(choice)),
        )
    return readback


def _plan(song, index, track, name, slot_index, slot, ms, scene=None, scene_index=None):
    before_type = _attr(track, "input_routing_type", None)
    before_channel = _attr(track, "input_routing_channel", None)
    choice, choice_index = _resampling(track)
    playing = bool(_attr(song, "is_playing", False))
    before_arm = bool(_attr(track, "arm", False))

    undo = {"track_index": index}
    if _label(before_type) is not None:
        undo["input_type"] = _label(before_type)
    if _identifier(before_type) is not None:
        undo["input_type_identifier"] = _identifier(before_type)
    before_type_index = _index_of(
        list(_attr(track, "available_input_routing_types", []) or []), before_type
    )
    if before_type_index is not None:
        undo["input_type_index"] = before_type_index
    if _label(before_channel) is not None:
        undo["input_channel"] = _label(before_channel)
    if _identifier(before_channel) is not None:
        undo["input_channel_identifier"] = _identifier(before_channel)
    before_channel_index = _index_of(
        list(_attr(track, "available_input_routing_channels", []) or []), before_channel
    )
    if before_channel_index is not None:
        undo["input_channel_index"] = before_channel_index

    return {
        "dry_run": True,
        "audible": True,
        "ready": not playing,
        "playing": playing,
        "will_record": {
            "track": name,
            "track_index": index,
            "slot": slot_index,
            "scene": (
                None if scene is None
                else {
                    "index": scene_index,
                    "name": str(_attr(scene, "name", "") or ""),
                }
            ),
            "ms": ms,
        },
        "routing": {
            "before": _ref(before_type),
            "before_index": before_type_index,
            "target": _ref(choice),
            "target_index": choice_index,
            "channel": _ref(_attr(track, "input_routing_channel", None)),
            "channel_index": before_channel_index,
        },
        "arm": {"before": before_arm},
        "undo": [undo],
        "notes": [
            "This capture plays the Set in real time through the master output and is audible.",
            "Apply with dry_run: false. The WAV stays in Samples/Recorded; the temporary clip "
            "is removed and the routing and arm are put back.",
        ],
    }


def _report(state, song, clip, path, size, file_ready):
    track = state["track"]
    readback = _attr(track, "input_routing_type", None)
    return {
        "dry_run": False,
        "audible": True,
        "recorded": True,
        "track": state["name"],
        "track_index": state["track_index"],
        "slot": state["slot_index"],
        "scene": state["scene_index"],
        "ms": state["ms"],
        "ticks": state["ticks"],
        "routing": {
            "before": _ref(state["before_type"]),
            "requested": _ref(state["choice"]),
            "requested_index": state["choice_index"],
            "readback": _ref(readback),
            "restored": None,
        },
        "arm": {
            "before": state["before_arm"],
            "readback": bool(_attr(track, "arm", False)),
            "restored": None,
        },
        "file_path": path,
        "file_bytes": size,
        "file_ready": file_ready,
        "clip_removed": None,
        "undo": [state["undo"]],
        "notes": [
            "The capture ran in real time and was audible.",
            "file_ready false means Live created the clip but the WAV could not be read yet.",
            "WAV headroom is a file sample peak, not master headroom.",
        ],
    }


def _restore_route(track, attribute, options_attribute, stored, stored_index, label, problems):
    """Put one routing field back, resolving it from the current option vector first.

    A Live proxy captured before the change can be stale afterwards; the value is the same, the
    object may not be. Resolve by name, then by the old index only when that entry still carries
    the same signature.
    """
    if stored is None:
        return True
    options = list(_attr(track, options_attribute, []) or [])
    wanted_label = _label(stored)
    wanted_identifier = _identifier(stored)
    candidates = []
    if wanted_label is not None:
        candidates = [option for option in options if _label(option) == wanted_label]
        if wanted_identifier is not None:
            exact = [
                option for option in candidates
                if _identifier(option) == wanted_identifier
            ]
            if exact:
                candidates = exact
    if not candidates and isinstance(stored_index, int) and 0 <= stored_index < len(options):
        candidate = options[stored_index]
        if _same_route(candidate, stored):
            candidates = [candidate]
    if not candidates:
        # Live 12.2.5 can report a routing value that is absent from its own option vector
        # (Ext. In after Resampling). Assigning the stored value directly is the only exact
        # restore left; if the build refuses it, report that rather than leaving Resampling on.
        try:
            setattr(track, attribute, stored)
        except Exception as exc:  # noqa: BLE001 - restore must keep going
            problems.append("%s: %s" % (label, exc))
            return False
        if not _same_route(_attr(track, attribute, None), stored):
            problems.append(
                "%s: the value before the capture is no longer offered" % (label,)
            )
            return False
        return True
    # Duplicate labels are real (two Ext. In entries). Any member of that set restores the
    # behaviour the track had; restoring the exact duplicate is not observable here.
    choice = candidates[0]
    try:
        setattr(track, attribute, choice)
    except Exception as exc:  # noqa: BLE001 - restore must keep going
        problems.append("%s: %s" % (label, exc))
        return False
    if not _same_route(_attr(track, attribute, None), stored):
        problems.append("%s readback does not match the value before the capture" % (label,))
        return False
    return True


def _restore(state, song):
    """Put back everything this capture changed. Never raises: the result is the report."""
    problems = []
    if state.get("recording"):
        try:
            song.stop_playing()
        except Exception as exc:  # noqa: BLE001 - restore must keep going
            problems.append("stop: %s" % (exc,))
        state["recording"] = False

    track = state["track"]
    type_ok = _restore_route(
        track, "input_routing_type", "available_input_routing_types",
        state["before_type"], state["before_type_index"], "input type", problems,
    )
    if type_ok:
        # The channel list belongs to the selected type, so restore it only after the type.
        _restore_route(
            track, "input_routing_channel", "available_input_routing_channels",
            state["before_channel"], state["before_channel_index"], "input channel", problems,
        )

    try:
        _arm(track, state["before_arm"])
    except ScriptError as exc:
        problems.append("arm: %s" % (exc,))

    removed = False
    try:
        slot = state["slot"]
        if _attr(slot, "has_clip", False):
            delete = _attr(slot, "delete_clip", None)
            if not callable(delete):
                problems.append("clip: this Live build cannot delete the temporary clip")
            else:
                delete()
                removed = not _attr(slot, "has_clip", False)
    except Exception as exc:  # noqa: BLE001 - restore must keep going
        problems.append("clip: %s" % (exc,))

    return {"ok": not problems, "problems": problems, "clip_removed": removed}


def _fire(target, label, quantization=False):
    fire = _attr(target, "fire", None)
    if not callable(fire):
        raise ScriptError("UNSUPPORTED", "this Live build cannot fire a %s" % (label,))
    try:
        if quantization:
            # A quantized launch can wait for the next bar, which made the first real capture
            # check immediately and report that nothing had started. 0 is Live's "None".
            try:
                fire(launch_quantization=0)
                return
            except TypeError:
                pass
        fire()
    except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
        raise ScriptError("LIVE_ERROR", "Live refused to fire the %s: %s" % (label, exc))


def _verify_recording(song, slot):
    recording = _attr(slot, "is_recording", None)
    if recording is True:
        return
    if recording is False:
        raise ScriptError(
            "LIVE_ERROR", "the slot reports it is not recording after it was fired"
        )
    if not bool(_attr(song, "is_playing", False)):
        raise ScriptError(
            "LIVE_ERROR",
            "Live reports neither recording nor playback after the slot was fired",
        )


def _step(state, song):
    """One display tick of the capture; defers until the recording is long enough."""
    try:
        if state["phase"] == "arm":
            state["setup_ticks"] += 1
            if state["setup_ticks"] > _MAX_CLIP_TICKS:
                raise ScriptError(
                    "TIMEOUT",
                    "capture could not arm within %d display ticks" % (_MAX_CLIP_TICKS,),
                )
            _set_resampling(state["track"], state["choice"])
            _arm(state["track"], True)
            if state["scene"] is not None:
                _fire(state["scene"], "scene")
            else:
                _fire(state["slot"], "clip slot")
            state["recording"] = True
            state["phase"] = "confirm"
            return Deferred(lambda next_song: _step(state, next_song))

        if state["phase"] == "confirm":
            state["setup_ticks"] += 1
            if state["setup_ticks"] > _MAX_CLIP_TICKS:
                raise ScriptError(
                    "TIMEOUT",
                    "capture could not confirm recording within %d display ticks"
                    % (_MAX_CLIP_TICKS,),
                )
            recording = _attr(state["slot"], "is_recording", None)
            playing = bool(_attr(song, "is_playing", False))
            if recording is False and state["scene"] is not None and not state["slot_fired"]:
                # A scene launch can start the mix without arming the empty slot for recording
                # (Live's "Start Recording on Scene Launch" is off by default). Firing the slot
                # now captures the mix that is already playing.
                state["slot_fired"] = True
                _fire(state["slot"], "clip slot", quantization=True)
                return Deferred(lambda next_song: _step(state, next_song))
            if recording is False and not playing:
                # A quantized launch lands on the next bar, not on this display tick.
                if state["setup_ticks"] < _MAX_CLIP_TICKS:
                    return Deferred(lambda next_song: _step(state, next_song))
                raise ScriptError(
                    "LIVE_ERROR",
                    "the slot was fired but Live reports neither recording nor playback",
                )
            _verify_recording(song, state["slot"])
            state["started"] = _clock()
            state["phase"] = "record"
            return Deferred(lambda next_song: _step(state, next_song))

        if state["phase"] == "record":
            state["ticks"] += 1
            elapsed_ms = (_clock() - state["started"]) * 1000.0
            if elapsed_ms < state["ms"]:
                if state["ticks"] >= _MAX_TICKS:
                    raise ScriptError(
                        "TIMEOUT",
                        "capture did not reach %d ms within %d display ticks"
                        % (state["ms"], _MAX_TICKS),
                    )
                return Deferred(lambda next_song: _step(state, next_song))

            try:
                song.stop_playing()
            except Exception as exc:  # noqa: BLE001 - the Live reason is the answer
                raise ScriptError(
                    "LIVE_ERROR", "Live refused to stop the capture: %s" % (exc,)
                )
            state["recording"] = False
            state["phase"] = "finalize"
            return Deferred(lambda next_song: _step(state, next_song))

        state["clip_ticks"] += 1
        slot = state["slot"]
        clip = _attr(slot, "clip", None)
        path = _attr(clip, "file_path", None) if clip is not None else None
        path = path if isinstance(path, str) and path else None
        size = None
        file_ready = False
        if path is not None:
            try:
                size = os.path.getsize(path)
                file_ready = size >= _MIN_WAV_BYTES
            except OSError:
                size = None

        if not file_ready and state["clip_ticks"] < _MAX_CLIP_TICKS:
            if clip is None or path is None or not os.path.exists(path):
                return Deferred(lambda next_song: _step(state, next_song))

        if clip is None:
            raise ScriptError(
                "LIVE_ERROR",
                "the recording stopped but no clip appeared in slot %d" % (state["slot_index"],),
            )

        result = _report(state, song, clip, path, size, file_ready)
        if path is None:
            result["file_reason"] = "the recorded clip reports no file_path"
        elif not file_ready:
            result["file_reason"] = (
                "the WAV at %s is missing or shorter than a WAV header" % (path,)
            )
        restore = _restore(state, song)
        result["routing"]["restored"] = restore["ok"]
        result["arm"]["restored"] = restore["ok"]
        result["clip_removed"] = restore["clip_removed"]
        result["restore"] = restore
        if not restore["ok"]:
            result["notes"].append(
                "Restore reported problems: %s" % "; ".join(restore["problems"])
            )
        return result
    except Exception as exc:  # noqa: BLE001 - restore every failure path
        restore = _restore(state, song)
        if isinstance(exc, ScriptError):
            if not restore["ok"]:
                raise ScriptError(
                    exc.code,
                    "%s; restore also reported: %s"
                    % (exc.message, "; ".join(restore["problems"])),
                )
            raise
        raise ScriptError(
            "LIVE_ERROR",
            "capture failed: %s; restore: %s"
            % (exc, "ok" if restore["ok"] else "; ".join(restore["problems"])),
        )


@command("mix.resample_capture")
def resample_capture(args, song):
    check_args(args, allowed=("track", "slot", "ms", "scene", "dry_run"))
    dry_run = bool(args.get("dry_run", True))
    if "track" not in args:
        raise ScriptError("BAD_ARGS", "missing argument(s): track")

    ms = args.get("ms", _DEFAULT_MS)
    if isinstance(ms, bool) or not isinstance(ms, int) or ms < _MIN_MS or ms > _MAX_MS:
        raise ScriptError(
            "BAD_ARGS", "ms must be an integer from %d to %d" % (_MIN_MS, _MAX_MS)
        )

    scene = None
    scene_index = args.get("scene")
    if scene_index is not None:
        if isinstance(scene_index, bool) or not isinstance(scene_index, int) or scene_index < 0:
            raise ScriptError("BAD_ARGS", "scene must be a non-negative integer")
        scenes = list(_attr(song, "scenes", []) or [])
        if scene_index >= len(scenes):
            raise ScriptError(
                "NOT_FOUND",
                "no scene at index %d; the Set has %d scene(s)"
                % (scene_index, len(scenes)),
            )
        scene = scenes[scene_index]

    index, track, name = _track(song, args["track"])
    slot_index, slot = _slot(track, args.get("slot"))
    plan = _plan(song, index, track, name, slot_index, slot, ms, scene, scene_index)

    if dry_run:
        return plan
    if plan["playing"]:
        raise ScriptError(
            "PRECONDITION_FAILED",
            "the Set is playing; stop it before a capture so the recording has a clean start",
        )
    if not plan["ready"]:
        raise ScriptError("PRECONDITION_FAILED", "Live is not ready to record")

    state = {
        "phase": "arm",
        "started": None,
        "ticks": 0,
        "setup_ticks": 0,
        "clip_ticks": 0,
        "slot_fired": False,
        "scene": scene,
        "scene_index": scene_index,
        "ms": ms,
        "track": track,
        "track_index": index,
        "name": name,
        "slot": slot,
        "slot_index": slot_index,
        "before_type": _attr(track, "input_routing_type", None),
        "before_type_index": plan["routing"]["before_index"],
        "before_channel": _attr(track, "input_routing_channel", None),
        "before_channel_index": plan["routing"]["channel_index"],
        "before_arm": bool(_attr(track, "arm", False)),
        "choice": _resampling(track)[0],
        "choice_index": plan["routing"]["target_index"],
        "recording": False,
        "undo": plan["undo"][0],
    }
    return _step(state, song)

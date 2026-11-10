from __future__ import annotations

from ..dispatch import check_args, command
from ..errors import ScriptError


def _bar_to_beats(song, bar):
    return (float(bar) - 1.0) * float(song.signature_numerator)


def _number(value, label):
    if isinstance(value, bool):
        raise ScriptError("BAD_ARGS", "%s must be a number" % (label,))
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ScriptError("BAD_ARGS", "%s must be a number" % (label,))


@command("transport.play")
def play(args, song):
    check_args(args, allowed=("from_bar",))
    from_bar = args.get("from_bar")
    if from_bar is not None:
        from_bar = _number(from_bar, "from_bar")
        if from_bar < 1:
            raise ScriptError("BAD_ARGS", "from_bar must be >= 1")
        song.current_song_time = _bar_to_beats(song, from_bar)
    song.start_playing()
    return {"is_playing": True, "from_bar": from_bar}


@command("transport.stop")
def stop(args, song):
    check_args(args)
    stop_playing = getattr(song, "stop_playing", None)
    if not callable(stop_playing):
        raise ScriptError("UNSUPPORTED", "this Live build cannot stop the transport")
    stop_playing()
    return {
        "is_playing": False,
        "current_song_time": round(float(getattr(song, "current_song_time", 0.0) or 0.0), 4),
    }


@command("transport.locate")
def locate(args, song):
    check_args(args, allowed=("bar",), required=("bar",))
    bar = _number(args["bar"], "bar")
    if bar < 1:
        raise ScriptError("BAD_ARGS", "bar must be >= 1")
    song.current_song_time = _bar_to_beats(song, bar)
    return {
        "bar": bar,
        "position_beats": round(float(song.current_song_time), 4),
        "is_playing": bool(getattr(song, "is_playing", False)),
    }


@command("transport.set_loop")
def set_loop(args, song):
    check_args(args, allowed=("enabled", "start_bar", "end_bar"), required=("enabled",))
    enabled = args["enabled"]
    if not isinstance(enabled, bool):
        raise ScriptError("BAD_ARGS", "enabled must be true or false")

    start = args.get("start_bar")
    end = args.get("end_bar")
    if (start is None) != (end is None):
        raise ScriptError("BAD_ARGS", "start_bar and end_bar must be supplied together")
    if start is not None:
        start = _number(start, "start_bar")
        end = _number(end, "end_bar")
        if start < 1:
            raise ScriptError("BAD_ARGS", "start_bar must be >= 1")
        if end <= start:
            raise ScriptError("BAD_ARGS", "end_bar must be greater than start_bar")
        song.loop_start = _bar_to_beats(song, start)
        song.loop_length = (end - start) * float(song.signature_numerator)

    song.loop = enabled
    return {
        "enabled": enabled,
        "start_bar": start,
        "end_bar": end,
        "loop_start": round(float(song.loop_start), 4),
        "loop_length": round(float(song.loop_length), 4),
    }

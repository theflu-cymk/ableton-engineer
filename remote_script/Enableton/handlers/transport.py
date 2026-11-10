from __future__ import annotations

from ..dispatch import check_args, command
from ..errors import ScriptError


@command("transport.play")
def play(args, song):
    check_args(args, allowed=("from_bar",))
    from_bar = args.get("from_bar")
    if from_bar is not None:
        from_bar = float(from_bar)
        if from_bar < 1:
            raise ScriptError("BAD_ARGS", "from_bar must be >= 1")
        song.current_song_time = (from_bar - 1.0) * float(song.signature_numerator)
    song.start_playing()
    return {"is_playing": True, "from_bar": from_bar}

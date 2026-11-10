"""Read-only reports computed from one snapshot (spec §7, §8).

A report is a pure function of the snapshot, never of Live. That is what makes a 77-track Set
cost one round trip instead of one per question, and what lets the same code answer from a
cached snapshot, a test fixture, or a saved file later.

Nothing here invents data. These Sets have no named locators, so sections come from arrangement
clip density and the report says how many sections are *named* rather than pretending a locator
list exists.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_PAGE = 50
MAX_PAGE = 200


class ReportError(ValueError):
    """Bad arguments to a report."""


def _only(args: Dict[str, Any], allowed: Sequence[str]) -> None:
    unknown = sorted(set(args) - set(allowed))
    if unknown:
        raise ReportError("unknown argument(s): %s" % ", ".join(unknown))


def _paging(args: Dict[str, Any], prefix: str = "") -> Tuple[int, int]:
    offset = args.get(prefix + "offset", 0)
    limit = args.get(prefix + "limit", DEFAULT_PAGE)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ReportError("%soffset must be a non-negative integer" % prefix)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_PAGE:
        raise ReportError("%slimit must be an integer from 1 to %d" % (prefix, MAX_PAGE))
    return offset, limit


def _page(items: Sequence[Any], offset: int, limit: int) -> Dict[str, Any]:
    window = list(items[offset:offset + limit])
    next_offset = offset + len(window)
    return {
        "items": window,
        "total": len(items),
        "next_offset": next_offset if next_offset < len(items) else None,
    }


def summary_from_snapshot(data: Dict[str, Any]) -> Dict[str, Any]:
    """The compact answer for ``ableton_status``, so the tool never dumps a whole Set."""
    song = data.get("song") or {}
    counts = data.get("counts") or {}
    return {
        "name": song.get("name"),
        "tempo": song.get("tempo"),
        "time_signature": song.get("signature"),
        "tracks": counts.get("tracks"),
        "returns": counts.get("returns"),
        "scenes": counts.get("scenes"),
        "locators": counts.get("locators"),
        "arrangement_clips": counts.get("arrangement_clips"),
        "session_clips": counts.get("session_clips"),
        "devices": counts.get("devices"),
        "is_playing": song.get("is_playing"),
        "current_song_time": song.get("current_song_time"),
    }


def beats_per_bar(song: Dict[str, Any]) -> float:
    signature = song.get("signature") or [4, 4]
    try:
        numerator, denominator = int(signature[0]), int(signature[1])
    except (IndexError, TypeError, ValueError):
        return 4.0
    if numerator <= 0 or denominator <= 0:
        return 4.0
    return numerator * 4.0 / denominator


def _arrangement(track: Dict[str, Any]) -> List[Dict[str, Any]]:
    return track.get("arrangement") or []


def _session_count(track: Dict[str, Any]) -> int:
    return int((track.get("session") or {}).get("filled") or 0)


def _sections(tracks: Sequence[Dict[str, Any]], per_bar: float) -> List[Dict[str, Any]]:
    """Merge contiguous occupied bars into sections.

    This is the honest read of an arrangement-first Set: there are no locators to trust, so a
    section is a run of bars that actually holds clips, and a gap is a real gap.
    """
    occupancy = {}  # type: Dict[int, Dict[str, Any]]
    for track in tracks:
        for clip in _arrangement(track):
            start = float(clip.get("start") or 0.0)
            end = float(clip.get("end") or start)
            if end <= start:
                continue
            first = int(start // per_bar) + 1
            last = int((end - 1e-6) // per_bar) + 1
            for bar in range(first, last + 1):
                slot = occupancy.setdefault(bar, {"clips": 0, "tracks": set()})
                slot["clips"] += 1
                slot["tracks"].add(track.get("index"))

    if not occupancy:
        return []

    ordered = sorted(occupancy)
    runs, current = [], [ordered[0]]  # type: List[List[int]], List[int]
    for bar in ordered[1:]:
        if bar == current[-1] + 1:
            current.append(bar)
        else:
            runs.append(current)
            current = [bar]
    runs.append(current)

    sections = []
    for run in runs:
        sections.append(
            {
                "start_bar": run[0],
                "end_bar": run[-1],
                "bars": len(run),
                "clips": sum(occupancy[bar]["clips"] for bar in run),
                "tracks": len(set().union(*(occupancy[bar]["tracks"] for bar in run))),
            }
        )
    return sections


def _total_bars(tracks: Sequence[Dict[str, Any]], per_bar: float) -> int:
    end = 0.0
    for track in tracks:
        for clip in _arrangement(track):
            end = max(end, float(clip.get("end") or 0.0))
    return int((end + 1e-6) // per_bar) if end else 0


def _duplicate_names(tracks: Sequence[Dict[str, Any]]) -> Dict[str, List[Any]]:
    seen = {}  # type: Dict[str, List[Any]]
    for track in tracks:
        seen.setdefault(str(track.get("name")), []).append(track.get("index"))
    return {name: indexes for name, indexes in seen.items() if len(indexes) > 1}


def structure(data: Dict[str, Any], args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Shape of the Set: sections, tracks, and the signals worth knowing before editing."""
    args = dict(args or {})
    _only(args, ("offset", "limit", "section_offset", "section_limit"))
    offset, limit = _paging(args)
    section_offset, section_limit = _paging(args, "section_")

    song = data.get("song") or {}
    tracks = data.get("tracks") or []
    per_bar = beats_per_bar(song)
    sections = _sections(tracks, per_bar)

    rows = []
    for track in tracks:
        rows.append(
            {
                "index": track.get("index"),
                "name": track.get("name"),
                "kind": track.get("kind"),
                "group": track.get("group"),
                "clips": len(_arrangement(track)),
                "session_clips": _session_count(track),
                "devices": len(track.get("devices") or []),
                "empty": not _arrangement(track) and not _session_count(track),
            }
        )

    locators = data.get("locators") or []
    return {
        "set": {
            "name": song.get("name"),
            "tempo": song.get("tempo"),
            "signature": song.get("signature"),
            "is_playing": song.get("is_playing"),
            "current_song_time": song.get("current_song_time"),
        },
        "bars": _total_bars(tracks, per_bar),
        "beats_per_bar": per_bar,
        "sections": _page(sections, section_offset, section_limit),
        "tracks": _page(rows, offset, limit),
        "signals": {
            "arrangement_clips": sum(len(_arrangement(t)) for t in tracks),
            "session_clips": sum(_session_count(t) for t in tracks),
            "named_sections": len([loc for loc in locators if loc.get("name")]),
            "locators_available": bool((data.get("captured") or {}).get("locators_available")),
            "duplicate_track_names": _duplicate_names(tracks),
        },
    }


def unused(data: Dict[str, Any], args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Material that is doing nothing: empty tracks, empty scenes, duplicate names.

    Deliberately not "clips that were never launched": that is not observable through the LOM,
    and a report that guesses it would be worse than no report.
    """
    args = dict(args or {})
    _only(args, ())

    tracks = data.get("tracks") or []
    scenes = data.get("scenes") or []

    without_clips = [
        t.get("name")
        for t in tracks
        if not _arrangement(t) and not _session_count(t)
    ]
    without_devices = [
        t.get("name")
        for t in tracks
        if not (t.get("devices") or []) and not _arrangement(t) and not _session_count(t)
    ]
    empty_scenes = [s.get("index") for s in scenes if not s.get("filled")]
    duplicates = _duplicate_names(tracks)
    counts = data.get("counts") or {}

    return {
        "tracks_without_clips": without_clips,
        "tracks_without_devices": without_devices,
        "scenes_without_clips": empty_scenes,
        "duplicate_track_names": duplicates,
        "empty_session_slots": counts.get("empty_session_slots"),
        "named_sections": len([loc for loc in (data.get("locators") or []) if loc.get("name")]),
        "total": len(without_clips) + len(empty_scenes) + len(duplicates),
    }


def levels(data: Dict[str, Any], args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fader positions and the flags worth seeing before touching gain.

    Peaks are reported as *not measured* rather than guessed. They come from meter polling,
    which is a separate, audible operation (mix_meter_poll).
    """
    args = dict(args or {})
    _only(args, ("offset", "limit"))
    offset, limit = _paging(args)

    tracks = data.get("tracks") or []
    rows = []
    for track in tracks:
        rows.append(
            {
                "index": track.get("index"),
                "name": track.get("name"),
                "kind": track.get("kind"),
                "volume": track.get("volume"),
                "volume_str": track.get("volume_str"),
                "pan": track.get("pan"),
                "mute": track.get("mute"),
                "solo": track.get("solo"),
            }
        )

    def named(predicate):
        return [row["name"] for row in rows if predicate(row)]

    return {
        "items": _page(rows, offset, limit)["items"],
        "total": len(rows),
        "next_offset": _page(rows, offset, limit)["next_offset"],
        "flags": {
            "muted": named(lambda row: row["mute"]),
            "soloed": named(lambda row: row["solo"]),
            "at_unity": named(lambda row: row["volume"] is not None and row["volume"] >= 0.999),
            "silent": named(lambda row: row["volume"] is not None and row["volume"] <= 0.001),
            "duplicate_names": _duplicate_names(tracks),
        },
        "peaks": {
            "measured": False,
            "note": "Peak levels need mix_meter_poll; this report never estimates them.",
        },
    }

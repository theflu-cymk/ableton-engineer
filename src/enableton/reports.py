"""Read-only reports computed from one snapshot (spec §7, §8).

A report is a pure function of the snapshot, never of Live. That is what makes a 77-track Set
cost one round trip instead of one per question, and what lets the same code answer from a
cached snapshot, a test fixture, or a saved file later.

Nothing here invents data. These Sets have no named locators, so sections come from arrangement
clip density and the report says how many sections are *named* rather than pretending a locator
list exists.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_PAGE = 50
MAX_PAGE = 200

# Live's fader position for 0.0 dB. Verified against Crust Wumble, where every track reports
# volume 0.85 next to the display string "0.0 dB". A >= 1.0 test for "unity" can never fire.
UNITY_VOLUME = 0.85


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
    captured = data.get("captured") or {}
    return {
        "name": song.get("name"),
        "tempo": song.get("tempo"),
        "time_signature": song.get("signature"),
        "tracks": counts.get("tracks"),
        "returns": counts.get("returns"),
        "scenes": counts.get("scenes"),
        "locators": counts.get("locators"),
        # Additive, not a rewrite: the count stands, but a reader can see whether the build
        # could read locators at all. Crust Wumble genuinely has none (its .als holds
        # <Locators><Locators /></Locators>); 0.1.5 made `cue_points` the fallback, so the
        # zero is a read result rather than the old false negative.
        "locators_available": bool(captured.get("locators_available")),
        "arrangement_clips": counts.get("arrangement_clips"),
        "session_clips": counts.get("session_clips"),
        "devices": counts.get("devices"),
        "devices_total": counts.get("devices_total"),
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

    ``clips`` counts distinct clips overlapping the section; ``clip_spans`` counts bar
    incidences, so a four-bar clip contributes 4. These were one field until Crust Wumble
    printed 520 clips against a Set holding 315.
    """
    occupancy = {}  # type: Dict[int, Dict[str, Any]]
    spans = []  # type: List[Tuple[int, int]]
    for track in tracks:
        for clip in _arrangement(track):
            start = float(clip.get("start") or 0.0)
            end = float(clip.get("end") or start)
            if end <= start:
                continue
            first = int(start // per_bar) + 1
            last = int((end - 1e-6) // per_bar) + 1
            spans.append((first, last))
            for bar in range(first, last + 1):
                slot = occupancy.setdefault(bar, {"spans": 0, "tracks": set()})
                slot["spans"] += 1
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
                "clips": sum(
                    1 for first, last in spans if first <= run[-1] and last >= run[0]
                ),
                "clip_spans": sum(occupancy[bar]["spans"] for bar in run),
                "tracks": len(set().union(*(occupancy[bar]["tracks"] for bar in run))),
            }
        )
    return sections


def _total_bars(tracks: Sequence[Dict[str, Any]], per_bar: float) -> int:
    """Bars the arrangement reaches, rounded up.

    A clip ending at beat 383.99 is still inside bar 96, so this is a ceiling. Flooring it made
    Crust Wumble report ``bars: 95`` in the same object as a section ending at bar 96.
    """
    end = 0.0
    for track in tracks:
        for clip in _arrangement(track):
            end = max(end, float(clip.get("end") or 0.0))
    if end <= 0:
        return 0
    return int(math.ceil(end / per_bar))


def _duplicate_names(tracks: Sequence[Dict[str, Any]]) -> Dict[str, List[Any]]:
    seen = {}  # type: Dict[str, List[Any]]
    for track in tracks:
        seen.setdefault(str(track.get("name")), []).append(track.get("index"))
    return {name: indexes for name, indexes in seen.items() if len(indexes) > 1}


def _device_total(track: Dict[str, Any]) -> int:
    """Devices at every depth the snapshot captured, including those inside rack chains."""
    def walk(rows: Sequence[Dict[str, Any]]) -> int:
        total = 0
        for row in rows:
            total += 1
            for chain in row.get("chains") or []:
                total += walk(chain)
        return total

    return walk(track.get("devices") or [])


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
                "devices_total": _device_total(track),
                "empty": not _arrangement(track) and not _session_count(track),
            }
        )

    locators = data.get("locators") or []
    # The master chain is outside ``tracks``, so it needs adding explicitly or the Set's device
    # population reads 102 where the file holds 108.
    master_devices = int((data.get("master_track") or {}).get("device_count") or 0)
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
            "devices_total": sum(_device_total(t) for t in tracks) + master_devices,
            "devices_master": master_devices,
            "named_sections": len([loc for loc in locators if loc.get("name")]),
            "locators_available": bool((data.get("captured") or {}).get("locators_available")),
            "duplicate_track_names": _duplicate_names(tracks),
        },
    }


def unused(data: Dict[str, Any], args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Material that is doing nothing: empty tracks, empty scenes, duplicate names.

    Deliberately not "clips that were never launched": that is not observable through the LOM,
    and a report that guesses it would be worse than no report.

    Return tracks are buses: they hold no clips and no session slots by design, so they are not
    waste. Crust Wumble's A-Reverb and B-Delay were reported as unused tracks on the first real
    read of a Set with 17 audio and MIDI tracks.
    """
    args = dict(args or {})
    _only(args, ())

    tracks = [t for t in (data.get("tracks") or []) if t.get("kind") != "return"]
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


def _at_unity(row: Dict[str, Any]) -> bool:
    """Whether a fader sits at 0.0 dB.

    Prefer the display string Live computes (``str_for_value``), because the raw 0..1 position
    depends on the fader curve; fall back to the curve position only when a backend omits it.
    """
    text = row.get("volume_str")
    if isinstance(text, str) and text.strip():
        return re.match(r"^[+-]?0\.0+ dB$", text.strip()) is not None
    value = row.get("volume")
    return value is not None and abs(float(value) - UNITY_VOLUME) <= 0.005


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
            "at_unity": named(_at_unity),
            "silent": named(lambda row: row["volume"] is not None and row["volume"] <= 0.001),
            "duplicate_names": _duplicate_names(tracks),
        },
        "peaks": {
            "measured": False,
            "note": "Peak levels need mix_meter_poll; this report never estimates them.",
        },
    }


WARP_FLAGS = ("markers_unreadable", "no_markers", "mode_unknown")


def _warp_row(track: Dict[str, Any], clip: Dict[str, Any], location: str) -> Dict[str, Any]:
    markers = clip.get("warp_markers")
    mode_name = clip.get("warp_mode_name")
    flags = []
    if markers is None:
        flags.append("markers_unreadable")
    elif markers == 0:
        flags.append("no_markers")
    if mode_name is None:
        flags.append("mode_unknown")

    row = {
        "track": track.get("name"),
        "track_index": track.get("index"),
        "location": location,
        "clip": clip.get("name"),
        "warping": bool(clip.get("warping")),
        "warp_mode": clip.get("warp_mode"),
        "warp_mode_name": mode_name,
        "warp_markers": markers,
        "flags": flags,
    }
    if location == "session":
        row["slot"] = clip.get("slot")
    if markers is None:
        row["warp_markers_reason"] = clip.get("warp_markers_reason")
    return row


def warp_check(data: Dict[str, Any], args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Warp state for every audio clip, with only defects the snapshot can prove.

    Warping off is a legitimate choice, so it is counted rather than flagged. The flags are
    deliberately narrow: a marker vector that could not be read, a vector with no markers at
    all, and a mode whose name the build does not know. Marker positions and grid alignment are
    not in the snapshot, so this report makes no claim about either.
    """
    args = dict(args or {})
    _only(args, ("offset", "limit"))
    offset, limit = _paging(args)

    rows = []  # type: List[Dict[str, Any]]
    for track in data.get("tracks") or []:
        for clip in _arrangement(track):
            if not clip.get("midi"):
                rows.append(_warp_row(track, clip, "arrangement"))
        for clip in (track.get("session") or {}).get("clips") or []:
            if not clip.get("midi"):
                rows.append(_warp_row(track, clip, "session"))

    by_flag = {flag: 0 for flag in WARP_FLAGS}
    for row in rows:
        for flag in row["flags"]:
            by_flag[flag] += 1

    modes = {}  # type: Dict[str, int]
    for row in rows:
        name = row["warp_mode_name"] or "unknown"
        modes[name] = modes.get(name, 0) + 1

    page = _page(rows, offset, limit)
    return {
        "items": page["items"],
        "total": page["total"],
        "next_offset": page["next_offset"],
        "summary": {
            "audio_clips": len(rows),
            "warping_on": sum(1 for row in rows if row["warping"]),
            "warping_off": sum(1 for row in rows if not row["warping"]),
            "flagged": sum(1 for row in rows if row["flags"]),
            "by_flag": by_flag,
            "modes": dict(sorted(modes.items())),
            "warp_markers": sum(
                row["warp_markers"] for row in rows if row["warp_markers"] is not None
            ),
            "unreadable": sum(1 for row in rows if row["warp_markers"] is None),
        },
    }


def notes_overlaps(data: Dict[str, Any], args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Same-pitch MIDI notes whose time ranges intersect.

    Chords are not overlaps: different pitches sounding together are normal. The snapshot carries
    only collision pairs, so this is bounded and does not pretend a truncated capture is complete.
    An older snapshot without note fields is unavailable rather than an empty result.
    """
    args = dict(args or {})
    _only(args, ("offset", "limit"))
    offset, limit = _paging(args)

    clips = []  # type: List[Tuple[Dict[str, Any], Dict[str, Any], str]]
    for track in data.get("tracks") or []:
        for clip in _arrangement(track):
            if clip.get("midi"):
                clips.append((track, clip, "arrangement"))
        for clip in (track.get("session") or {}).get("clips") or []:
            if clip.get("midi"):
                clips.append((track, clip, "session"))

    selected = data.get("captured") or {}
    if not selected.get("notes_available"):
        return {
            "items": [],
            "total": 0,
            "next_offset": None,
            "summary": {
                "midi_clips": len(clips),
                "note_data_available": False,
                "notes_read": 0,
                "overlaps": 0,
                "complete": False,
            },
            "unavailable": {
                # The snapshot's own reason wins: "reinstall the script" is the wrong advice for a
                # clip whose notes could not be read, and a version number here goes stale.
                "reason": selected.get("notes_reason")
                or "This snapshot has no MIDI note data; reinstall the Remote Script and restart "
                   "Live so note capture runs.",
                "requires": "note capture in the Remote Script",
            },
        }

    rows = []  # type: List[Dict[str, Any]]
    warnings = []  # type: List[Dict[str, Any]]
    notes_read = 0
    clips_with_overlaps = 0
    truncated_clips = 0
    unreadable_clips = 0
    for track, clip, location in clips:
        count = clip.get("note_count")
        if count is None:
            unreadable_clips += 1
            warnings.append({
                "kind": "notes_unreadable",
                "track": track.get("name"),
                "clip": clip.get("name"),
                "reason": clip.get("note_overlaps_reason"),
            })
            continue
        notes_read += int(count)
        pairs = clip.get("note_overlaps") or []
        if pairs:
            clips_with_overlaps += 1
        if clip.get("note_overlaps_truncated"):
            truncated_clips += 1
            warnings.append({
                "kind": "overlaps_truncated",
                "track": track.get("name"),
                "clip": clip.get("name"),
            })
        for pair in pairs:
            row = {
                "track": track.get("name"),
                "track_index": track.get("index"),
                "location": location,
                "clip": clip.get("name"),
                "pitch": pair.get("pitch"),
                "first": pair.get("first"),
                "second": pair.get("second"),
                "overlap": pair.get("overlap"),
            }
            if location == "session":
                row["slot"] = clip.get("slot")
            rows.append(row)

    by_pitch = {}  # type: Dict[str, int]
    for row in rows:
        pitch = str(row.get("pitch"))
        by_pitch[pitch] = by_pitch.get(pitch, 0) + 1

    page = _page(rows, offset, limit)
    complete = unreadable_clips == 0 and truncated_clips == 0
    return {
        "items": page["items"],
        "total": page["total"],
        "next_offset": page["next_offset"],
        "summary": {
            "midi_clips": len(clips),
            "note_data_available": True,
            "notes_read": notes_read,
            "overlaps": len(rows),
            "clips_with_overlaps": clips_with_overlaps,
            "by_pitch": dict(sorted(by_pitch.items())),
            "truncated_clips": truncated_clips,
            "unreadable_clips": unreadable_clips,
            "complete": complete,
        },
        "warnings": warnings,
    }


_FADER_DB_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*dB\s*$", re.IGNORECASE)


def _fader_db(row: Dict[str, Any]) -> Optional[float]:
    text = row.get("volume_str")
    if not isinstance(text, str):
        return None
    match = _FADER_DB_RE.match(text)
    return float(match.group(1)) if match else None


def mix_headroom(data: Dict[str, Any], args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fader trim, and the headroom that cannot be measured from this snapshot.

    A fader's dB value is a trim, not a signal level: two tracks at the same position can peak
    12 dB apart. True headroom needs peaks, which the snapshot does not contain, so this report
    never derives a headroom number from faders. It reports what is observable and names what
    is missing rather than estimating it.
    """
    args = dict(args or {})
    _only(args, ("offset", "limit"))
    offset, limit = _paging(args)

    tracks = data.get("tracks") or []
    rows = []  # type: List[Dict[str, Any]]
    for track in tracks:
        rows.append(
            {
                "index": track.get("index"),
                "name": track.get("name"),
                "kind": track.get("kind"),
                "volume": track.get("volume"),
                "volume_str": track.get("volume_str"),
                "fader_db": _fader_db(track),
                "mute": bool(track.get("mute")),
                "solo": bool(track.get("solo")),
            }
        )

    dbs = [row["fader_db"] for row in rows if row["fader_db"] is not None]

    def named(predicate) -> List[Any]:
        return [row["name"] for row in rows if predicate(row)]

    page = _page(rows, offset, limit)
    return {
        "items": page["items"],
        "total": page["total"],
        "next_offset": page["next_offset"],
        "summary": {
            "tracks": len(rows),
            "faders_measured": len(dbs),
            "faders_unmeasured": len(rows) - len(dbs),
            "at_unity": named(_at_unity),
            "above_unity": named(
                lambda row: row["fader_db"] is not None and row["fader_db"] > 0
            ),
            "below_unity": named(
                lambda row: row["fader_db"] is not None and row["fader_db"] < 0
            ),
            "silent": named(
                lambda row: row["volume"] is not None and row["volume"] <= 0.001
            ),
            "muted": named(lambda row: row["mute"]),
            "soloed": named(lambda row: row["solo"]),
            "fader_span_db": {"min": min(dbs), "max": max(dbs)} if dbs else None,
        },
        "headroom": {
            "measured": False,
            "reason": "The snapshot has fader positions but no signal peaks, so headroom cannot be measured.",
            "requires": "mix_meter_poll",
            "note": "Fader dB is trim, not level; do not read it as peak headroom.",
        },
        "master": {
            "available": False,
            "reason": "The snapshot carries the master device chain, not its fader.",
        },
    }

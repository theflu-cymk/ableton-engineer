"""Producer-facing session context.

This is deliberately not another low-level Live tool. It turns one snapshot into the brief a
producer needs before asking for an edit: sections, roles, density, gaps and a short set of next
actions. It is a read-only report, so it can never change a Set.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from .reports import ReportError, beats_per_bar, structure

_ROLE_RULES = (
    ("texture", re.compile(r"top|texture|loop|noise|foley", re.I)),
    ("fx", re.compile(r"fx|riser|impact|downlift|sweep|transition|crash", re.I)),
    ("vocal", re.compile(r"vocal|vox|voice|acapella|choir", re.I)),
    ("drums", re.compile(r"drum|kick|snare|clap|hat|perc|909|break", re.I)),
    ("bass", re.compile(r"bass|sub|growl|808", re.I)),
    ("pad", re.compile(r"pad|atmos|ambient|string|drone", re.I)),
    ("synth", re.compile(r"synth|lead|bell|melody|arp|keys|piano", re.I)),
)


def _role(name: Any) -> str:
    text = str(name or "")
    for role, pattern in _ROLE_RULES:
        if pattern.search(text):
            return role
    return "other"


def _clips(track: Dict[str, Any]) -> List[Dict[str, Any]]:
    return track.get("arrangement") or []


def _session_filled(track: Dict[str, Any]) -> int:
    return int((track.get("session") or {}).get("filled") or 0)


def _device_total(track: Dict[str, Any]) -> int:
    def walk(rows: Sequence[Dict[str, Any]]) -> int:
        total = 0
        for row in rows:
            total += 1
            for chain in row.get("chains") or []:
                total += walk(chain)
        return total

    return walk(track.get("devices") or [])


def _locator_bar(locator: Dict[str, Any], per_bar: float) -> Optional[float]:
    value = locator.get("bar")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    time = locator.get("time")
    if isinstance(time, (int, float)) and not isinstance(time, bool):
        return float(time) / per_bar + 1.0
    return None


def _section_locator(
    start_bar: float,
    locators: Sequence[Dict[str, Any]],
    per_bar: float,
) -> Optional[Dict[str, Any]]:
    exact = None
    preceding = None
    for locator in locators:
        bar = _locator_bar(locator, per_bar)
        if bar is None:
            continue
        if abs(bar - start_bar) < 0.01:
            exact = locator
        if bar <= start_bar + 0.01:
            preceding = locator
    return exact or preceding


def _section_roles(
    tracks: Sequence[Dict[str, Any]],
    start_bar: float,
    end_bar: float,
    per_bar: float,
) -> tuple[List[str], List[str]]:
    roles = set()
    names = []
    for track in tracks:
        hit = False
        for clip in _clips(track):
            start = float(clip.get("start") or 0.0) / per_bar + 1.0
            end = float(clip.get("end") or 0.0) / per_bar + 1.0
            if end <= start:
                continue
            if end > start_bar and start <= end_bar + 0.01:
                hit = True
                break
        if hit:
            roles.add(_role(track.get("name")))
            names.append(str(track.get("name")))
    return sorted(roles), names


def _next_actions(
    sections: Sequence[Dict[str, Any]],
    tracks: Sequence[Dict[str, Any]],
    locators: Sequence[Dict[str, Any]],
) -> List[Dict[str, str]]:
    actions = []
    if sections and not [item for item in locators if item.get("name")]:
        actions.append({
            "title": "Name the sections before giving structural notes",
            "why": "'Make the second drop bigger' is ambiguous until the drop has a name.",
        })
    busiest = max(sections, key=lambda item: (item.get("clip_spans", 0), item.get("tracks", 0)), default=None)
    if busiest:
        actions.append({
            "title": "Capture the busiest section for reference analysis",
            "why": "A measured reference report is more useful than guessing about the drop.",
        })
    non_empty = [track for track in tracks if _clips(track) or _session_filled(track)]
    if non_empty:
        actions.append({
            "title": "Create two A/B takes of one musical decision",
            "why": "Alternatives are easier to judge than one permanent edit.",
        })
    empty = [track for track in tracks if not _clips(track) and not _session_filled(track)]
    if empty:
        actions.append({
            "title": "Review tracks with no clips",
            "why": "Empty tracks make the Set harder to read and are easy to remove.",
        })
    return actions


def session_brief(data: Dict[str, Any], args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A producer-readable map of the Set, computed from one snapshot."""
    args = dict(args or {})
    unknown = sorted(set(args) - {"focus", "include_tracks"})
    if unknown:
        raise ReportError("unknown argument(s): %s" % ", ".join(unknown))
    focus = args.get("focus")
    if focus is not None and (not isinstance(focus, str) or not focus.strip()):
        raise ReportError("focus must be a non-empty string")
    include_tracks = args.get("include_tracks", True)
    if not isinstance(include_tracks, bool):
        raise ReportError("include_tracks must be true or false")

    shape = structure(data, {"limit": 200, "section_limit": 200})
    song = data.get("song") or {}
    # ``Song.tracks`` includes the return buses; a producer brief is about the working tracks.
    raw_tracks = [
        track for track in (data.get("tracks") or []) if track.get("kind") != "return"
    ]
    per_bar = beats_per_bar(song)
    locators = list(data.get("locators") or [])
    sections = []
    for index, row in enumerate(shape.get("sections", {}).get("items", []), start=1):
        start_bar = float(row.get("start_bar") or 1)
        end_bar = float(row.get("end_bar") or start_bar)
        roles, names = _section_roles(raw_tracks, start_bar, end_bar, per_bar)
        locator = _section_locator(start_bar, locators, per_bar)
        label = (locator or {}).get("name") or "Section %d" % index
        span = max(1, int(end_bar - start_bar + 1))
        sections.append({
            "label": str(label),
            "start_bar": start_bar,
            "end_bar": end_bar,
            "bars": span,
            "clips": int(row.get("clips") or 0),
            "clip_spans": int(row.get("clip_spans") or 0),
            "tracks": int(row.get("tracks") or 0),
            "density": round(int(row.get("clip_spans") or 0) / max(1, span), 2),
            "roles": roles,
            "track_names": names,
        })

    role_counts: Dict[str, int] = {}
    track_rows = []
    for track in raw_tracks:
        role = _role(track.get("name"))
        role_counts[role] = role_counts.get(role, 0) + 1
        track_rows.append({
            "index": track.get("index"),
            "name": track.get("name"),
            "role": role,
            "kind": track.get("kind"),
            "clips": len(_clips(track)),
            "session_clips": _session_filled(track),
            "devices_total": _device_total(track),
            "empty": not _clips(track) and not _session_filled(track),
        })

    issues = []
    named = [locator for locator in locators if locator.get("name")]
    if not named:
        issues.append({
            "kind": "unnamed_sections",
            "severity": "info",
            "title": "No named sections",
            "detail": "The Set is arrangement-first but has no locator names for the AI to anchor on.",
        })
    duplicates = (shape.get("signals") or {}).get("duplicate_track_names") or {}
    if duplicates:
        issues.append({
            "kind": "duplicate_track_names",
            "severity": "warn",
            "title": "Duplicate track names",
            "detail": duplicates,
        })
    empty_tracks = [track for track in track_rows if track["empty"] and track["kind"] != "return"]
    if empty_tracks:
        issues.append({
            "kind": "empty_tracks",
            "severity": "info",
            "title": "Tracks with no clips",
            "detail": [track["name"] for track in empty_tracks],
        })
    for section in sections:
        if section["bars"] >= 8 and section["tracks"] <= 2:
            issues.append({
                "kind": "thin_section",
                "severity": "info",
                "title": "%s is sparse" % section["label"],
                "detail": "%d bars, %d tracks; audition it before deciding whether the space is intentional."
                % (section["bars"], section["tracks"]),
            })

    actions = _next_actions(sections, raw_tracks, locators)
    title = "%s | %s BPM | %d bars | %d tracks" % (
        song.get("name") or "Untitled Set",
        song.get("tempo"),
        shape.get("bars") or 0,
        len(raw_tracks),
    )
    lines = [
        title,
        "Sections: " + (
            ", ".join("%s (%d-%d, %d tracks)" % (s["label"], s["start_bar"], s["end_bar"], s["tracks"])
                      for s in sections)
            or "none found"
        ),
        "Roles: " + (", ".join("%s %d" % (role, count) for role, count in sorted(role_counts.items()))),
    ]
    if issues:
        lines.append("Watch: " + "; ".join(item["title"] for item in issues))
    if focus:
        lines.append("Focus: " + focus)

    return {
        "status": "available",
        "title": title,
        "set": {
            "name": song.get("name"),
            "tempo": song.get("tempo"),
            "signature": song.get("signature"),
            "bars": shape.get("bars"),
            "tracks": len(raw_tracks),
        },
        "sections": sections,
        "roles": dict(sorted(role_counts.items())),
        "issues": issues,
        "next_actions": actions,
        "tracks": track_rows if include_tracks else [],
        "focus": focus,
        "text": "\n".join(lines),
        "limitations": [
            "Roles are inferred from track names, not from audio.",
            "This brief does not measure loudness, spectrum or stereo width.",
            "A thin section may be an intentional intro, break or outro.",
        ],
    }


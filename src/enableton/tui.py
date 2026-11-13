"""The interactive menu: a front-end over the same argv the CLI already takes.

Individual actions are argument lists handed to ``enableton.cli.main``. The one-click cleanup
composes the same manifest tools through ``run_tool`` on one connection so it can rename, colour
and align in a single pass; it invents no new Live capability and never talks to the LOM.

The screen is rebuilt from scratch on every key press, which keeps the rendering code free of
cursor arithmetic. The menu is viewport-ed, so it stays usable in a 24-line terminal as well as a
tall one.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import textwrap
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
ORANGE = "\x1b[38;5;209m"
GREEN = "\x1b[38;5;114m"
RED = "\x1b[38;5;203m"
GREY = "\x1b[38;5;245m"
WHITE = "\x1b[38;5;252m"

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

#: A 5x5 block font. Only the letters used by the wordmarks are defined; anything else keeps
#: the width, so a missing glyph cannot break the header.
_FONT = {
    "A": (".###.", "#...#", "#####", "#...#", "#...#"),
    "B": ("####.", "#...#", "####.", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "####.", "#....", "#####"),
    "G": (".###.", "#....", "#.###", "#...#", ".###."),
    "I": ("#####", "..#..", "..#..", "..#..", "#####"),
    "L": ("#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "#.#.#", "#..##", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", ".###."),
    "R": ("####.", "#...#", "####.", "#.#..", "#..#."),
    "S": (".####", "#....", ".###.", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", ".###."),
    "X": ("#...#", ".#.#.", "..#..", ".#.#.", "#...#"),
}


def visible_width(text: str) -> int:
    """Length of a rendered line, ignoring ANSI escapes."""
    return len(_ANSI.sub("", text))


def logo(text: str = "ENABLETON", colour: str = ORANGE) -> List[str]:
    """The title in block letters: five rows, 53 columns for ``ENABLETON``."""
    rows = [""] * 5
    for index, char in enumerate(text.upper()):
        glyph = _FONT.get(char, ("#####",) * 5)
        for row in range(5):
            cells = glyph[row].replace("#", "\u2588").replace(".", " ")
            rows[row] += (" " if index else "") + cells
    return [colour + row + RESET for row in rows]


@dataclass(frozen=True)
class Item:
    kind: str  # "section" or "action"
    label: str
    action: str = ""


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    default: str = ""
    kind: str = "str"  # str, float, int, bool, list, colour
    optional: bool = False


@dataclass(frozen=True)
class ModeAction:
    label: str
    detail: str
    tool: str = ""
    fields: Tuple[Field, ...] = ()
    special: str = ""  # inspect, autofix, report, guide, cleanup, align, colour, warp, back
    phases: Tuple[str, ...] = ()
    writes: bool = False
    available: bool = True
    reason: str = ""
    guide: str = ""


@dataclass(frozen=True)
class ModePage:
    title: str
    summary: str
    options: Tuple[ModeAction, ...]


#: Live snaps an RGB request to its nearest track colour; these are the palette names shown.
COLOURS: Dict[str, int] = {
    "red": 0xE5514B,
    "orange": 0xF5A623,
    "yellow": 0xF8E71C,
    "green": 0x7ED321,
    "blue": 0x4A90E2,
    "purple": 0x9013FE,
    "grey": 0x9B9B9B,
}

_CLIP_FIELDS: Tuple[Field, ...] = (
    Field("track", "Track (exact name)"),
    Field("clip", "Clip name (duplicate Arrangement names are refused by the tool)"),
    Field("location", "Location (arrangement/session, blank for either)", optional=True),
    Field("slot", "Session slot (session clips only)", kind="int", optional=True),
)

GUIDES: Dict[str, str] = {
    "audio": """1. Warp the clip, then run Bad warp markers.
2. If the Arrangement start is wrong, duplicate the clip to a new audio track at the intended bar; Live does not expose a writable Clip.start_time.
3. Trim the head with the clip start marker, then fix loop points.
4. Keep one layer as the timing reference and A/B the others against it.""",
    "warp_mode": """Drums and percussive loops: Beats. Tonal vocals, pads and full mixes: Complex or Complex Pro. Re-pitch: turntablism. Use Edit > Set a clip's warp mode; preview first and A/B the transients.""",
    "tempo": """1. Check the Set tempo against the source before changing it.
2. Warp the audio clip and run Bad warp markers to snap interior markers to 1/16.
3. If the clip still drifts, set its warp mode and move the remaining marker by ear.
4. Set the project tempo in Live's transport; Enableton deliberately does not guess it.""",
    "phase": """1. Solo the two layered tracks and loop the same bar.
2. Insert Utility on one layer, map Phase Invert, and A/B the low end.
3. Open an analyser, click Configure, add Phase/Correlation, then Sound > Read plugin parameters and devices_set_parameter by exact name.
4. Fix the one layer that cancels; do not flip polarity on the whole group.""",
    "boundaries": """Use Edit > Fix loop points for a looped clip, or set the clip start/end markers in Live. Warped audio uses beats; unwarped audio uses seconds. Re-run the report after the edit.""",
    "takes": """1. Rename the track first so the take has context.
2. Rename a uniquely named clip with clips_rename.
3. For duplicate Arrangement names, rename in Live or target by location/slot; Enableton refuses to guess which take you meant.""",
    "clutter": """Delete empty tracks only after the preview: tracks_clean_empty is destructive. For muted or obsolete clips, decide in Live; the snapshot cannot know whether a muted part is a deliberate alternative.""",
    "routing": """1. Note the track and its current output from the report.
2. Use Mix > Route a track and choose the exact output type Live lists.
3. For sends, use tracks_set_sends with the exact return name and value; returns are buses, not tracks to route into themselves.
4. Re-run the report; a blank or unreadable output is flagged.""",
    "deps": """1. Run inspect_structure; plug-in devices carry plugin: true and active.
2. Use Sound > Disable or enable a device (devices_set_active) to bypass a missing or placeholder device. This keeps its chain position and settings.
3. Install the plug-in on the target machine, reopen the Set, and enable the device.
4. Freeze and flatten critical tracks for a portable copy.""",
    "media": """1. File > Collect All and Save, with All files selected.
2. If Live reports missing files, File > Manage Files > Locate Missing Files.
3. Re-run inspect_structure and check the Set path before copying the Set.""",
}

MODE_PAGES: Dict[str, ModePage] = {
    "triage": ModePage(
        "TRIAGE",
        "One safe pass fixes what it can; every other row runs its own check.",
        (
            ModeAction(
                "Clean up everything",
                "Rename duplicates, colour tracks, align MIDI, snap warp markers and fix safe gain. Audible timing and faders; no prompts.",
                special="cleanup",
                writes=True,
            ),
            ModeAction(
                "Duplicate or unclear names",
                "Rename duplicate track names uniquely; safe hygiene fixes only.",
                special="autofix",
                phases=("hygiene",),
                writes=True,
            ),
            ModeAction(
                "Misaligned layers",
                "Snap every MIDI clip on every MIDI track to the sixteenth grid. No clip-name prompts.",
                special="align",
                writes=True,
            ),
            ModeAction(
                "Audio layer alignment",
                "Warp first, then place or duplicate the audio layer at the intended bar.",
                special="guide",
                guide=GUIDES["audio"],
            ),
            ModeAction(
                "Bad warp markers",
                "Snap interior markers on every warped audio clip to 1/16. Audible timing; no prompts.",
                special="warp",
                writes=True,
            ),
            ModeAction(
                "Match layers to drum transients",
                "Move every other audio layer's markers onto the drum track's transients. Audible timing; no prompts.",
                special="warp_match",
                writes=True,
            ),
            ModeAction(
                "Incorrect warp mode",
                "Report the mode in use and apply the right one from Edit.",
                special="report",
                tool="clips_warp_check",
                guide=GUIDES["warp_mode"],
            ),
            ModeAction(
                "Wrong clip or project tempo",
                "Read the Set tempo and timing, then make clip timing follow it.",
                special="report",
                tool="ableton_status",
                guide=GUIDES["tempo"],
            ),
            ModeAction(
                "Phase problems",
                "Find cancellation with Utility or an analyser, then fix the one offending layer.",
                special="guide",
                guide=GUIDES["phase"],
            ),
            ModeAction(
                "Inconsistent clip boundaries",
                "Read the loop and warp state, then set the exact boundaries.",
                special="report",
                tool="clips_warp_check",
                guide=GUIDES["boundaries"],
            ),
            ModeAction(
                "Unlabeled takes and versions",
                "Rename the track context first, then the clip; duplicate names are never guessed.",
                special="guide",
                guide=GUIDES["takes"],
            ),
            ModeAction(
                "Unused or hidden clutter",
                "List empty tracks, scenes and unused material; deletion is explicit.",
                special="report",
                tool="inspect_unused",
                guide=GUIDES["clutter"],
            ),
            ModeAction(
                "Unclear track structure",
                "Colour MIDI, audio and group tracks by role. Returns and grouping stay manual.",
                special="colour",
                writes=True,
            ),
            ModeAction(
                "Routing and send confusion",
                "Read every track's routing, then apply the exact route in Mix.",
                special="report",
                tool="mix_routing_report",
                guide=GUIDES["routing"],
            ),
            ModeAction(
                "Unbalanced levels",
                "Apply safe gain-stage fader fixes; audible, with rollback on any regression.",
                special="autofix",
                phases=("gain",),
                writes=True,
            ),
            ModeAction(
                "Plugin or device dependencies",
                "Disable a missing plug-in without deleting its slot, then install and restore it.",
                special="guide",
                guide=GUIDES["deps"],
            ),
            ModeAction(
                "Missing or uncollected media",
                "Collect files in Live; if a file is missing, locate it before moving the Set.",
                special="guide",
                guide=GUIDES["media"],
            ),
            ModeAction("Back to modes", "", special="back"),
        ),
    ),
    "organise": ModePage(
        "ORGANISE",
        "Names, colours and levels: the file-hygiene pass.",
        (
            ModeAction(
                "Clean up and align everything",
                "Rename duplicates, colour tracks, align MIDI, snap warp markers and fix safe gain. Audible timing and faders; no prompts.",
                special="cleanup",
                writes=True,
            ),
            ModeAction(
                "Align all MIDI tracks",
                "Snap every MIDI clip on every track; no clip-name prompts.",
                special="align",
                writes=True,
            ),
            ModeAction(
                "Rename a track",
                "Give one track a clearer name; preview before writing.",
                tool="tracks_name_and_color",
                fields=(Field("track", "Track (exact name)"), Field("name", "New name")),
                writes=True,
            ),
            ModeAction(
                "Colour a track",
                "Assign a colour from Live's palette; preview before writing.",
                tool="tracks_name_and_color",
                fields=(
                    Field("track", "Track (exact name)"),
                    Field("colour", "Colour (red/orange/yellow/green/blue/purple/grey)", "orange", "colour"),
                ),
                writes=True,
            ),
            ModeAction(
                "Gain stage tracks",
                "Normalise faders toward a headroom target; omit tracks for all.",
                tool="tracks_gain_stage",
                fields=(
                    Field("tracks", "Tracks (comma separated, blank for all)", kind="list", optional=True),
                    Field("headroom_db", "Headroom in dB", "-6", "float"),
                ),
                writes=True,
            ),
            ModeAction(
                "Pan tracks",
                "Set pan on one or more tracks; omit tracks for all.",
                tool="tracks_set_pan",
                fields=(
                    Field("tracks", "Tracks (comma separated, blank for all)", kind="list", optional=True),
                    Field("pan", "Pan -1.0 (left) to 1.0 (right)", "0", "float"),
                ),
                writes=True,
            ),
            ModeAction(
                "Align MIDI notes",
                "Snap note starts to a grid on one clip; preview before writing.",
                tool="notes_quantize",
                fields=_CLIP_FIELDS + (
                    Field("grid", "Grid in beats (0.25 = sixteenth)", "0.25", "float"),
                    Field("strength", "Strength 0-1", "1", "float"),
                ),
                writes=True,
            ),
            ModeAction("Back to modes", "", special="back"),
        ),
    ),
    "mix": ModePage(
        "MIX",
        "Measure the balance, then change it with intent.",
        (
            ModeAction(
                "Levels and pan report",
                "Every fader, pan and mute, with the outliers flagged. No writes.",
                special="report",
                tool="mix_levels_report",
            ),
            ModeAction(
                "Measured headroom",
                "Read the master and track peaks; unmeasured when Live is stopped.",
                special="report",
                tool="mix_headroom",
            ),
            ModeAction(
                "Gain stage tracks",
                "Normalise faders toward a headroom target; preview before writing.",
                tool="tracks_gain_stage",
                fields=(
                    Field("tracks", "Tracks (comma separated, blank for all)", kind="list", optional=True),
                    Field("headroom_db", "Headroom in dB", "-6", "float"),
                ),
                writes=True,
            ),
            ModeAction(
                "Routing report",
                "Input and output routing for every track. No writes.",
                special="report",
                tool="mix_routing_report",
            ),
            ModeAction(
                "Route a track",
                "Set one output type by Live's exact name; preview before writing.",
                tool="tracks_set_routing",
                fields=(
                    Field("track", "Track (exact name)"),
                    Field("output_type", "Output type (exact Live name)"),
                ),
                writes=True,
            ),
            ModeAction("Back to modes", "", special="back"),
        ),
    ),
    "edit": ModePage(
        "EDIT",
        "Work on MIDI timing and note shape.",
        (
            ModeAction(
                "Quantize a clip",
                "Snap note starts to a grid; preview before writing.",
                tool="notes_quantize",
                fields=_CLIP_FIELDS + (
                    Field("grid", "Grid in beats (0.25 = sixteenth)", "0.25", "float"),
                    Field("strength", "Strength 0-1", "1", "float"),
                ),
                writes=True,
            ),
            ModeAction(
                "Humanize a clip",
                "Add seeded timing and velocity variation; preview before writing.",
                tool="notes_humanize",
                fields=_CLIP_FIELDS + (
                    Field("timing", "Timing spread in beats", "0.01", "float"),
                    Field("velocity", "Velocity spread", "8", "int"),
                    Field("seed", "Seed", "0", "int"),
                ),
                writes=True,
            ),
            ModeAction(
                "Review note overlaps",
                "List same-pitch collisions; these need listening.",
                special="report",
                tool="notes_overlaps",
            ),
            ModeAction(
                "Set a clip's warp mode",
                "Choose Beats for drums, Complex Pro for tonal material; preview first.",
                tool="clips_set_warp_mode",
                fields=_CLIP_FIELDS + (
                    Field("mode", "Warp mode (beats/tones/texture/re-pitch/complex/rex/complex_pro)", "beats"),
                ),
                writes=True,
            ),
            ModeAction(
                "Fix loop points",
                "Set exact clip-relative loop boundaries; preview before writing.",
                tool="clips_fix_loop_points",
                fields=_CLIP_FIELDS + (
                    Field("loop_start", "Loop start in beats", kind="float"),
                    Field("loop_end", "Loop end in beats", kind="float"),
                ),
                writes=True,
            ),
            ModeAction("Back to modes", "", special="back"),
        ),
    ),
    "arrange": ModePage(
        "ARRANGE",
        "Map the timeline and duplicate a bar range.",
        (
            ModeAction(
                "Map sections",
                "Sections derived from arrangement clip density. No writes.",
                special="report",
                tool="sections_map",
            ),
            ModeAction(
                "Duplicate a bar range",
                "Copy arrangement clips to a new bar; preview before writing.",
                tool="clips_duplicate_range",
                fields=(
                    Field("tracks", "Tracks (comma separated, blank for all)", kind="list", optional=True),
                    Field("from_bar", "From bar", kind="float"),
                    Field("to_bar", "To bar (exclusive)", kind="float"),
                    Field("destination_bar", "Destination bar", kind="float"),
                ),
                writes=True,
            ),
            ModeAction("Back to modes", "", special="back"),
        ),
    ),
    "sound": ModePage(
        "SOUND",
        "Read a track's devices, then change one parameter.",
        (
            ModeAction(
                "Read a track's devices",
                "List the device chain, including nested rack chains. No writes.",
                special="report",
                tool="devices_read_chain",
                fields=(Field("track", "Track (exact name)"),),
            ),
            ModeAction(
                "Read plugin parameters",
                "List a plugin's exposed parameters after you add them with Configure.",
                tool="devices_read_parameters",
                fields=(
                    Field("track", "Track (exact name)"),
                    Field("device", "Device (exact name)"),
                ),
            ),
            ModeAction(
                "Set a device parameter",
                "Change one parameter by exact name; preview before writing.",
                tool="devices_set_parameter",
                fields=(
                    Field("track", "Track (exact name)"),
                    Field("device", "Device (exact name)"),
                    Field("parameter", "Parameter (exact name)"),
                    Field("value", "New value", kind="float"),
                ),
                writes=True,
            ),
            ModeAction(
                "Disable or enable a device",
                "Bypass a missing plugin without deleting its slot; preview before writing.",
                tool="devices_set_active",
                fields=(
                    Field("track", "Track (exact name)"),
                    Field("device", "Device (exact name)"),
                    Field("active", "Enable (true) or disable (false)", "false", "bool"),
                ),
                writes=True,
            ),
            ModeAction("Back to modes", "", special="back"),
        ),
    ),
}


MENU: Tuple[Item, ...] = (
    Item("section", "Start here"),
    Item("action", "\U0001f9f9  Clean up this Set \u2014 names, colour, align, warp, gain", "cleanup"),
    Item("section", "Modes"),
    Item("action", "\U0001fa7a  Triage \u2014 diagnose and fix this Set", "mode:triage"),
    Item("action", "\U0001f5c2   Organise \u2014 names, colours and levels", "mode:organise"),
    Item("action", "\U0001f39a   Mix \u2014 balance, gain and routing", "mode:mix"),
    Item("action", "\u270f   Edit \u2014 notes and clip timing", "mode:edit"),
    Item("action", "\U0001f3d7   Arrange \u2014 sections and bar ranges", "mode:arrange"),
    Item("action", "\U0001f50a   Sound \u2014 devices and parameters", "mode:sound"),
    Item("section", "Live"),
    Item("action", "\U0001f50c  Doctor \u2014 connection, version, queue", "doctor"),
    Item("action", "\U0001f4ca  Set summary", "status"),
    Item("action", "\U0001f50d  Inspect findings", "inspect"),
    Item("section", "Catalogue"),
    Item("action", "\U0001f9f0  Browse tools", "browse"),
    Item("action", "\U0001f4d6  Describe a tool", "describe"),
    Item("action", "\u25b6   Run a tool with JSON arguments", "call"),
    Item("section", "Plans"),
    Item("action", "\U0001f9e0  Compile a plan", "plan"),
    Item("action", "\u2705  Apply a stored plan", "apply"),
    Item("section", "Setup"),
    Item("action", "\U0001f4e6  Install the Remote Script", "setup"),
    Item("section", "Help"),
    Item("action", "\u2753  Usage", "help"),
    Item("action", "\U0001f6aa  Exit", "exit"),
)

_VERSION_PREFIX = "  "


def _version() -> str:
    """The Remote Script version this repo ships, not the packaging version.

    ``pyproject.toml`` is still at 0.1.0 and has never tracked the script, so showing it here
    would put two different versions on the same screen.
    """
    from .setup import script_version

    return script_version() or ""


def _clear() -> None:
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()


def _stale_notice(running: str, repo: str) -> str:
    """Empty unless Live is running a different script build than this repo ships.

    This is the state where every tool answers from the old build and nothing else on screen
    says so, so it gets its own line rather than being appended to a line that can overflow.
    """
    if not repo or not running or running == repo:
        return ""
    return (
        ORANGE
        + "\u26a0  Live loaded %s, this repo ships %s \u2014 setup then restart Live"
        % (running, repo)
        + RESET
    )


def _status_lines() -> Tuple[str, str]:
    """The Live line, plus a warning line when the loaded build differs from this repo."""
    from .cli import doctor
    from .setup import script_version

    repo = script_version()
    try:
        report = doctor()
    except Exception:  # noqa: BLE001 - the menu must open even when Live is absent
        report = {}
    if not report.get("connected"):
        return (
            RED
            + "\u25cb"
            + RESET
            + " Live not reachable \u2014 select Enableton in Preferences > Link, Tempo & MIDI",
            "",
        )
    running = str(report.get("script") or "?")
    line = GREEN + "\u25cf" + RESET + " Live %s \u00b7 script %s" % (report.get("live"), running)
    if report.get("build"):
        line += " \u00b7 build %s" % report["build"]
    return line, _stale_notice(running, repo or "")


def _first_action() -> int:
    for index, item in enumerate(MENU):
        if item.kind == "action":
            return index
    return 0


def step(selected: int, direction: int) -> int:
    """Move the highlight by one actionable row, wrapping at both ends."""
    index = selected
    for _ in range(len(MENU)):
        index = (index + direction) % len(MENU)
        if MENU[index].kind == "action":
            return index
    return selected


def _ask(label: str, default: str = "") -> str:
    _clear()
    hint = " [%s]" % default if default else ""
    try:
        answer = input("%s%s: " % (label, hint)).strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    return answer or default


def _collect(action: str) -> Optional[List[str]]:
    """Turn a menu action into the argv the CLI already understands."""
    plain = {
        "doctor": ["doctor"],
        "status": ["status"],
        "inspect": ["inspect"],
        "modes": ["modes", "--findings"],
        "tools": ["tools"],
        "setup": ["setup", "--force"],
    }
    if action in plain:
        return plain[action]

    if action == "describe":
        name = _ask("Tool name")
        return ["describe", name] if name else None
    if action == "call":
        name = _ask("Tool name")
        if not name:
            return None
        return ["call", name, "--args", _ask("Arguments (JSON)", "{}") or "{}"]
    if action == "plan":
        intent = _ask("What should the plan fix?", "fix all safe findings")
        return ["plan", "--intent", intent or "fix all safe findings"]
    if action == "apply":
        plan_id = _ask("Plan id")
        return ["run", plan_id] if plan_id else None
    return None


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if limit <= 1 or len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"


def filter_tools(query: str, catalogue: Optional[Dict[str, Any]] = None) -> List[str]:
    """Names matching every word of the query, best first.

    A hit in the name outranks a hit in the description, and a word that starts a name segment
    (``meter`` in ``mix_meter_poll``) outranks one buried mid-word, so typing "meter" puts the
    meter tools above anything that merely mentions meters. Terms are ANDed, so "mix met" works.
    """
    if catalogue is None:
        from .manifest import load_manifest

        catalogue = load_manifest()
    terms = [term for term in query.lower().split() if term]
    if not terms:
        return list(catalogue)

    scored = []
    for name, tool in catalogue.items():
        lowered = name.lower()
        segments = lowered.split("_")
        haystack = ("%s %s %s" % (tool.summary, tool.description, tool.domain)).lower()
        score = 0
        for term in terms:
            if lowered == term:
                score += 100
            elif any(segment.startswith(term) for segment in segments):
                score += 40
            elif term in lowered:
                score += 20
            elif term in haystack:
                score += 5
            else:
                score = -1
                break
        if score >= 0:
            scored.append((-score, name))
    return [name for _, name in sorted(scored)]


def _browser_lines(
    query: str,
    matches: Sequence[str],
    selected: int,
    catalogue: Dict[str, Any],
    size: Optional[Tuple[int, int]] = None,
) -> List[str]:
    """The catalogue as a main-menu-style screen: wordmark, question, arrow-selected rows."""
    columns, rows = size if size is not None else shutil.get_terminal_size((80, 24))
    lines: List[str] = []
    if columns >= 60:
        lines.extend(logo("CATALOGUE"))
    else:
        lines.append(ORANGE + BOLD + "CATALOGUE" + RESET)
    lines.append("")
    lines.append(
        _VERSION_PREFIX
        + GREY
        + "Enableton"
        + RESET
        + " "
        + WHITE
        + _version()
        + RESET
        + DIM
        + "  catalogue / browse tools"
        + RESET
    )
    lines.append(
        _VERSION_PREFIX
        + BOLD
        + "? Which tool?"
        + RESET
        + DIM
        + "  (arrow keys, enter to select)"
        + RESET
    )

    cursor = WHITE + "\u258c" + RESET if query else ""
    prompt = (
        "  " + ORANGE + "/ " + RESET + query + cursor
        if query
        else "  " + DIM + "/  type to filter \u2014 try meter, routing, fader, notes" + RESET
    )
    lines.append(prompt)
    lines.append(
        "  "
        + DIM
        + "%d of %d tools" % (len(matches), len(catalogue))
        + ("  \u00b7 no match: backspace to widen" if not matches else "")
        + RESET
    )
    lines.append("")

    visible = max(3, rows - len(lines) - 2)
    start = max(0, min(selected - visible // 2, len(matches) - visible))
    for index in range(start, min(len(matches), start + visible)):
        name = matches[index]
        tool = catalogue[name]
        summary = _clip(tool.summary, max(10, columns - len(name) - 14))
        flag = ORANGE + "  write" + RESET if tool.writes else ""
        if index == selected:
            lines.append(
                " " + ORANGE + "\u276f" + RESET + " " + BOLD + name + RESET
                + "  " + DIM + summary + RESET + flag
            )
        else:
            lines.append("   " + name + "  " + DIM + summary + RESET + flag)

    lines.append(
        "  "
        + DIM
        + "type to filter \u00b7 \u2191\u2193 move \u00b7 enter describe \u00b7 esc back"
        + RESET
    )
    return lines


def _render_browser(
    query: str, matches: Sequence[str], selected: int, catalogue: Dict[str, Any]
) -> None:
    lines = _browser_lines(query, matches, selected, catalogue)
    sys.stdout.write("\x1b[H\x1b[2J" + "\n".join(lines) + "\n")
    sys.stdout.flush()


def browse_tools(cli_main: Callable[[Optional[Sequence[str]]], int]) -> None:
    """A filterable catalogue: Enter hands the highlighted tool to ``describe``."""
    from .manifest import load_manifest

    catalogue = load_manifest()
    query = ""
    selected = 0
    while True:
        matches = filter_tools(query, catalogue)
        if matches:
            selected = max(0, min(selected, len(matches) - 1))
        else:
            selected = 0
        _render_browser(query, matches, selected, catalogue)

        key = _read_key()
        if key in ("escape", "ctrl-c"):
            return
        if key == "up" and matches:
            selected = (selected - 1) % len(matches)
        elif key == "down" and matches:
            selected = (selected + 1) % len(matches)
        elif key == "backspace":
            query = query[:-1]
            selected = 0
        elif key == "enter" and matches:
            _clear()
            try:
                cli_main(["describe", matches[selected]])
            except SystemExit:
                pass
            _pause()
        elif len(key) == 1 and key.isprintable():
            query += key
            selected = 0


def _draw(lines: Sequence[str]) -> None:
    sys.stdout.write("\x1b[H\x1b[2J" + "\n".join(lines) + "\n")
    sys.stdout.flush()


def _message(text: str) -> None:
    _clear()
    print("\n  " + text)
    _pause()


def _capture_cli(
    cli_main: Callable[[Optional[Sequence[str]]], int], argv: Sequence[str]
) -> Tuple[int, str, str]:
    """Run the CLI with its output captured, so a screen can format it instead of dumping it."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(list(argv))
    except SystemExit as exc:
        code = int(exc.code or 0)
    except Exception as exc:  # noqa: BLE001 - the screen reports the reason, it does not crash
        return 1, "", str(exc)
    return code, out.getvalue(), err.getvalue()


def _json_payload(text: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _call_tool(
    cli_main: Callable[[Optional[Sequence[str]]], int],
    tool: str,
    args: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], str]:
    code, out, err = _capture_cli(
        cli_main, ["call", tool, "--args", json.dumps(args, ensure_ascii=False)]
    )
    payload = _json_payload(out)
    if payload is None:
        return None, (err.strip() or out.strip() or "tool exited %d" % code)
    return payload, ""


def _mode_lines(
    page: ModePage, selected: int, size: Optional[Tuple[int, int]] = None
) -> List[str]:
    """A mode screen with the same wordmark, question and selected-row language as the main menu."""
    columns, rows = size if size is not None else shutil.get_terminal_size((80, 24))
    lines: List[str] = []
    if columns >= 60:
        lines.extend(logo(page.title))
    else:
        lines.append(ORANGE + BOLD + page.title + RESET)
    lines.append("")
    lines.append(
        _VERSION_PREFIX
        + GREY
        + "Enableton"
        + RESET
        + " "
        + WHITE
        + _version()
        + RESET
        + DIM
        + "  "
        + _clip(page.summary, max(20, columns - 24))
        + RESET
    )
    lines.append(
        _VERSION_PREFIX
        + BOLD
        + "? What should I do?"
        + RESET
        + DIM
        + "  (arrow keys, enter to select)"
        + RESET
    )
    lines.append("")

    visible = max(1, (rows - len(lines) - 2) // 2)
    start = max(0, min(selected - visible // 2, len(page.options) - visible))
    for index in range(start, min(len(page.options), start + visible)):
        option = page.options[index]
        label_colour = BOLD if option.available else GREY
        suffix = "" if option.available else "  " + DIM + "unavailable" + RESET
        if index == selected:
            lines.append(
                " " + ORANGE + "\u276f" + RESET + " " + label_colour + option.label + RESET + suffix
            )
        else:
            lines.append("   " + label_colour + option.label + RESET + suffix)
        detail = option.detail if option.available else (option.reason or option.detail)
        lines.append(
            "     " + DIM + _clip(detail, max(20, columns - 8)) + RESET
        )
    lines.append("  " + DIM + "\u2191\u2193 move \u00b7 enter select \u00b7 esc back" + RESET)
    return lines


def _diagnosis_lines(
    payload: Dict[str, Any], focus: str = "", size: Optional[Tuple[int, int]] = None
) -> List[str]:
    columns, rows = size if size is not None else shutil.get_terminal_size((80, 24))
    counts = payload.get("counts") or {}
    findings = list(payload.get("findings") or [])
    if focus:
        findings = [row for row in findings if row.get("kind") == focus]
        total = len(findings)
        listening = sum(1 for row in findings if row.get("needs_listening"))
        fixable = sum(1 for row in findings if row.get("fix") and not row.get("needs_listening"))
        title = "Note overlaps" if focus == "notes.overlap" else focus
    else:
        total = int(counts.get("total", len(findings)))
        listening = int(counts.get("needs_listening", 0))
        fixable = int(counts.get("auto_fixable", 0))
        title = "Full diagnosis"

    lines: List[str] = []
    if columns >= 60:
        lines.extend(logo("TRIAGE"))
    else:
        lines.append(ORANGE + BOLD + "TRIAGE" + RESET)
    lines.append("")
    lines.append(
        _VERSION_PREFIX
        + BOLD
        + title
        + RESET
        + DIM
        + "  tier %s" % payload.get("tier", "standard")
        + RESET
    )
    lines.append(
        "  "
        + GREY
        + "%d finding%s" % (total, "" if total == 1 else "s")
        + RESET
        + "  \u00b7  "
        + ORANGE
        + "%d need listening" % listening
        + RESET
        + "  \u00b7  "
        + GREEN
        + "%d auto-fixable" % fixable
        + RESET
    )
    lines.append("")

    if not findings:
        lines.append("  " + GREEN + "No findings in this view." + RESET)
    else:
        lines.append("  " + GREY + "\u2500\u2500 Findings " + "\u2500" * 3 + RESET)
        room = max(3, rows - len(lines) - 2)
        for index, finding in enumerate(findings[:room], start=1):
            lines.append(
                "  %d  %s%s%s"
                % (
                    index,
                    BOLD,
                    _clip(finding.get("title", "?"), max(20, columns - 8)),
                    RESET,
                )
            )
            meta = "     " + DIM + "%s \u00b7 %s \u00b7 %s" % (
                finding.get("severity", "?"),
                finding.get("phase", "?"),
                finding.get("mode", "?"),
            )
            if finding.get("needs_listening"):
                meta += " \u00b7 listen"
            lines.append(meta + RESET)
        if len(findings) > room:
            lines.append("  " + DIM + "\u2026 %d more" % (len(findings) - room) + RESET)

    unavailable = payload.get("unavailable") or []
    for row in unavailable:
        lines.append(
            "  " + ORANGE + "unavailable" + RESET + "  " + _clip(str(row.get("reason", row)), 60)
        )
    lines.append("  " + DIM + "press any key to return" + RESET)
    return lines


def _show_inspect(
    cli_main: Callable[[Optional[Sequence[str]]], int], focus: str = ""
) -> None:
    code, out, err = _capture_cli(cli_main, ["inspect"])
    payload = _json_payload(out)
    if payload is None:
        _message(err.strip() or out.strip() or "diagnosis exited %d" % code)
        return
    _draw(_diagnosis_lines(payload, focus))
    _pause()


def _plan_lines(payload: Dict[str, Any], size: Optional[Tuple[int, int]] = None) -> List[str]:
    columns, rows = size if size is not None else shutil.get_terminal_size((80, 24))
    lines: List[str] = []
    if columns >= 60:
        lines.extend(logo("TRIAGE"))
    else:
        lines.append(ORANGE + BOLD + "TRIAGE" + RESET)
    lines.append("")
    plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else payload
    steps = list(plan.get("steps") or [])
    lines.append(
        _VERSION_PREFIX
        + BOLD
        + "Safe repair plan"
        + RESET
        + DIM
        + "  %d step%s" % (len(steps), "" if len(steps) == 1 else "s")
        + RESET
    )
    before = payload.get("counts_before") or {}
    if before:
        lines.append(
            "  " + GREY + "Current findings: %s" % before.get("total", "?") + RESET
        )
    lines.append("")
    if not steps:
        lines.append("  " + GREEN + "No safe fixes match this phase." + RESET)
    else:
        lines.append("  " + GREY + "\u2500\u2500 Steps " + "\u2500" * 3 + RESET)
        room = max(3, rows - len(lines) - 2)
        for step in steps[:room]:
            lines.append(
                "  %s  %s%s%s"
                % (step.get("n", "?"), BOLD, step.get("tool", "?"), RESET)
            )
            lines.append("     " + DIM + _clip(step.get("why", ""), max(20, columns - 8)) + RESET)
        if len(steps) > room:
            lines.append("  " + DIM + "\u2026 %d more" % (len(steps) - room) + RESET)
    lines.append("  " + DIM + "press any key to return" + RESET)
    return lines


def _autofix_result_lines(
    payload: Dict[str, Any], size: Optional[Tuple[int, int]] = None
) -> List[str]:
    columns, _ = size if size is not None else shutil.get_terminal_size((80, 24))
    lines: List[str] = []
    if columns >= 60:
        lines.extend(logo("TRIAGE"))
    else:
        lines.append(ORANGE + BOLD + "TRIAGE" + RESET)
    lines.append("")
    before = payload.get("counts_before") or {}
    after = payload.get("counts_after") or {}
    applied = bool(payload.get("applied"))
    lines.append(
        _VERSION_PREFIX
        + (GREEN if applied else GREY)
        + ("Applied" if applied else "Nothing applied")
        + RESET
        + DIM
        + "  findings %s \u2192 %s" % (before.get("total", "?"), after.get("total", "?"))
        + RESET
    )
    if payload.get("rolled_back"):
        lines.append("  " + ORANGE + "Rolled back to the pre-repair state." + RESET)
    if payload.get("stopped"):
        lines.append("  " + ORANGE + "Stopped: %s" % payload["stopped"] + RESET)
    error = payload.get("error") or {}
    if error:
        lines.append("  " + RED + _clip(str(error.get("message", error)), 70) + RESET)
    lines.append("")
    lines.append("  " + GREY + "\u2500\u2500 Steps " + "\u2500" * 3 + RESET)
    steps = list(payload.get("steps") or [])
    if not steps:
        lines.append("  " + DIM + "No step was executed." + RESET)
    for step in steps[:8]:
        lines.append("  %s  %s" % (step.get("n", "?"), step.get("tool", "?")))
    lines.append("  " + DIM + "press any key to return" + RESET)
    return lines


def _show_autofix(
    cli_main: Callable[[Optional[Sequence[str]]], int], phases: Tuple[str, ...] = ()
) -> None:
    args: Dict[str, Any] = {"dry_run": True, "checkpoint": True}
    if phases:
        args["phases"] = list(phases)
    preview, error = _call_tool(cli_main, "inspect_autofix", args)
    if preview is None:
        _message(error)
        return
    _draw(_plan_lines(preview))
    plan = preview.get("plan") if isinstance(preview.get("plan"), dict) else preview
    if not (plan.get("steps") or []):
        _pause()
        return
    try:
        answer = input("\n  Apply these fixes? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if answer != "y":
        return
    applied, error = _call_tool(cli_main, "inspect_autofix", dict(args, dry_run=False))
    if applied is None:
        _message(error)
        return
    _draw(_autofix_result_lines(applied))
    _pause()


def _report_lines(
    payload: Dict[str, Any], title: str, size: Optional[Tuple[int, int]] = None
) -> List[str]:
    columns, rows = size if size is not None else shutil.get_terminal_size((80, 24))
    lines: List[str] = []
    if columns >= 60:
        lines.extend(logo(title))
    else:
        lines.append(ORANGE + BOLD + title + RESET)
    lines.append("")
    for key, value in payload.items():
        if key == "items" or key in ("findings", "steps"):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            lines.append("  " + GREY + key.replace("_", " ") + RESET + "  " + str(value))
        elif isinstance(value, dict):
            lines.append(
                "  " + GREY + key.replace("_", " ") + RESET
                + "  " + _clip(json.dumps(value, ensure_ascii=False), max(20, columns - 20))
            )
        elif isinstance(value, list):
            lines.append("  " + GREY + key.replace("_", " ") + RESET + "  %d item(s)" % len(value))
    lines.append("")
    items = payload.get("items")
    if isinstance(items, list) and items:
        lines.append("  " + GREY + "\u2500\u2500 Items " + "\u2500" * 3 + RESET)
        room = max(3, rows - len(lines) - 2)
        for row in items[:room]:
            lines.append("  " + _clip(json.dumps(row, ensure_ascii=False), max(20, columns - 4)))
        if len(items) > room:
            lines.append("  " + DIM + "\u2026 %d more" % (len(items) - room) + RESET)
    lines.append("  " + DIM + "press any key to return" + RESET)
    return lines


def _guide_text(text: str, columns: int) -> List[str]:
    lines: List[str] = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        for wrapped in textwrap.wrap(paragraph, width=max(20, columns - 6)):
            lines.append("  " + wrapped)
    return lines


def _show_guide(action: ModeAction, title: str) -> None:
    columns, _ = shutil.get_terminal_size((80, 24))
    lines: List[str] = []
    if columns >= 60:
        lines.extend(logo("TRIAGE"))
    else:
        lines.append(ORANGE + BOLD + "TRIAGE" + RESET)
    lines.append("")
    lines.append(_VERSION_PREFIX + BOLD + action.label + RESET)
    lines.extend(_guide_text(action.guide or action.detail, columns))
    lines.append("  " + DIM + "press any key to return" + RESET)
    _draw(lines)
    _pause()


def _show_report(
    cli_main: Callable[[Optional[Sequence[str]]], int],
    tool: str,
    title: str,
    fields: Tuple[Field, ...] = (),
    guide: str = "",
) -> None:
    args: Dict[str, Any] = {}
    if fields:
        collected = _action_args(ModeAction(label="", detail="", fields=fields))
        if collected is None:
            return
        args = collected
    payload, error = _call_tool(cli_main, tool, args)
    if payload is None:
        _message(error)
        return
    lines = _report_lines(payload, title)
    if guide:
        columns, _ = shutil.get_terminal_size((80, 24))
        lines = lines[:-1] + ["", "  " + BOLD + "How to fix" + RESET]
        lines.extend(_guide_text(guide, columns))
        lines.append("  " + DIM + "press any key to return" + RESET)
    _draw(lines)
    _pause()


def _action_args(action: ModeAction) -> Optional[Dict[str, Any]]:
    args: Dict[str, Any] = {}
    for field in action.fields:
        answer = _ask(field.label, field.default)
        if not answer:
            if field.optional:
                continue
            _message("%s is required." % field.label)
            return None
        try:
            if field.kind == "list":
                args[field.key] = [part.strip() for part in answer.split(",") if part.strip()]
            elif field.kind == "int":
                args[field.key] = int(answer)
            elif field.kind == "float":
                args[field.key] = float(answer)
            elif field.kind == "bool":
                lowered = answer.strip().lower()
                if lowered in ("1", "true", "yes", "on"):
                    args[field.key] = True
                elif lowered in ("0", "false", "no", "off"):
                    args[field.key] = False
                else:
                    _message("%s needs true or false." % field.label)
                    return None
            elif field.kind == "colour":
                colour = answer.strip().lower()
                if colour not in COLOURS:
                    _message("Unknown colour %r. Use one of: %s" % (answer, ", ".join(COLOURS)))
                    return None
                args["color"] = COLOURS[colour]
            else:
                args[field.key] = answer
        except ValueError:
            _message("%s needs a number." % field.label)
            return None
    return args


def _action_result_lines(
    payload: Dict[str, Any], title: str, size: Optional[Tuple[int, int]] = None
) -> List[str]:
    columns, rows = size if size is not None else shutil.get_terminal_size((80, 24))
    lines: List[str] = []
    if columns >= 60:
        lines.extend(logo(title))
    else:
        lines.append(ORANGE + BOLD + title + RESET)
    lines.append("")
    changes = payload.get("changes")
    if isinstance(changes, list):
        lines.append(
            _VERSION_PREFIX
            + BOLD
            + ("Preview" if payload.get("dry_run") else "Applied")
            + RESET
            + DIM
            + "  %d change%s" % (len(changes), "" if len(changes) == 1 else "s")
            + RESET
        )
        lines.append("")
        room = max(3, rows - len(lines) - 2)
        for change in changes[:room]:
            lines.append("  " + _clip(json.dumps(change, ensure_ascii=False), max(20, columns - 4)))
        if len(changes) > room:
            lines.append("  " + DIM + "\u2026 %d more" % (len(changes) - room) + RESET)
    else:
        fallback = _report_lines(payload, title, size)
        start = 6 if columns >= 60 else 2
        lines.extend(fallback[start:-1])
    lines.append("  " + DIM + "press any key to return" + RESET)
    return lines


def _run_tool_action(
    cli_main: Callable[[Optional[Sequence[str]]], int], action: ModeAction, title: str
) -> None:
    args = _action_args(action)
    if args is None:
        return
    if action.writes:
        preview, error = _call_tool(cli_main, action.tool, dict(args, dry_run=True))
        if preview is None:
            _message(error)
            return
        _draw(_action_result_lines(preview, title))
        try:
            answer = input("\n  Apply this change? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if answer != "y":
            return
        applied, error = _call_tool(cli_main, action.tool, dict(args, dry_run=False))
        if applied is None:
            _message(error)
            return
        _draw(_action_result_lines(applied, title))
        _pause()
        return
    payload, error = _call_tool(cli_main, action.tool, args)
    if payload is None:
        _message(error)
        return
    _draw(_report_lines(payload, title))
    _pause()


def _track_colour(kind: str, is_midi: bool) -> int:
    """One colour per musical role, so a glance at the Set shows its structure."""
    if kind == "return":
        return COLOURS["purple"]
    if kind == "group":
        return COLOURS["grey"]
    if kind == "midi" or is_midi:
        return COLOURS["green"]
    return COLOURS["blue"]


def _bulk_result_lines(
    title: str,
    renamed: int,
    coloured: int,
    aligned: int,
    failures: Sequence[str],
    audible: bool = False,
    warped: int = 0,
    markers: int = 0,
    size: Optional[Tuple[int, int]] = None,
) -> List[str]:
    columns, rows = size if size is not None else shutil.get_terminal_size((80, 24))
    lines: List[str] = []
    if columns >= 60:
        lines.extend(logo(title))
    else:
        lines.append(ORANGE + BOLD + title + RESET)
    lines.append("")
    lines.append("  " + GREEN + "Safe pass complete." + RESET)
    if not (renamed or coloured or aligned) and not failures:
        lines.append("  " + GREY + "Nothing needed changing." + RESET)
    lines.append("  Renamed duplicate tracks   %d" % renamed)
    lines.append("  Coloured tracks            %d" % coloured)
    lines.append("  MIDI clips aligned         %d" % aligned)
    lines.append("  Warped clips               %d" % warped)
    lines.append("  Warp markers moved         %d" % markers)
    if audible:
        lines.append("  " + ORANGE + "Audible: gain faders or clip timing may have changed." + RESET)
    if failures:
        lines.append("")
        lines.append("  " + RED + BOLD + "Needs attention" + RESET)
        room = max(1, rows - len(lines) - 2)
        for failure in failures[:room]:
            lines.append("  " + RED + _clip(str(failure), max(20, columns - 4)) + RESET)
        if len(failures) > room:
            lines.append("  " + DIM + "\u2026 %d more" % (len(failures) - room) + RESET)
    lines.append("  " + DIM + "press any key to return" + RESET)
    return lines


def _warp_result_lines(
    payload: Dict[str, Any], failures: Sequence[str], size: Optional[Tuple[int, int]] = None
) -> List[str]:
    columns, rows = size if size is not None else shutil.get_terminal_size((80, 24))
    lines: List[str] = []
    if columns >= 60:
        lines.extend(logo("TRIAGE"))
    else:
        lines.append(ORANGE + BOLD + "TRIAGE" + RESET)
    lines.append("")
    reference = payload.get("reference") or {}
    lines.append("  " + BOLD + "Warp markers" + RESET)
    if reference:
        lines.append(
            "  Reference track            %s (%s)"
            % (reference.get("track", "?"), reference.get("source", "auto"))
        )
    lines.append("  Clips changed              %s" % payload.get("clips", 0))
    lines.append(
        "  Markers %-18s %s"
        % ("matched" if reference else "snapped", payload.get("moved", 0))
    )
    lines.append("  Clips/markers skipped      %s" % len(payload.get("skipped") or []))
    skipped = payload.get("skipped") or []
    for row in skipped[:6]:
        lines.append(
            "    "
            + DIM
            + _clip(
                "%s / %s: %s"
                % (row.get("track", "?"), row.get("clip", "?"), row.get("reason", "?")),
                max(20, columns - 6),
            )
            + RESET
        )
    if failures:
        lines.append("")
        lines.append("  " + RED + BOLD + "Needs attention" + RESET)
        for failure in failures[:max(1, rows - len(lines) - 2)]:
            lines.append("  " + RED + _clip(str(failure), max(20, columns - 4)) + RESET)
    lines.append("  " + ORANGE + "Audible: clip timing has changed." + RESET)
    lines.append("  " + DIM + "press any key to return" + RESET)
    return lines


def _run_warp() -> None:
    """Snap every warped audio clip's interior markers in one connection."""
    from .cli import doctor
    from .protocol.client import LiveClient
    from .protocol.codes import LiveError
    from .setup import script_version
    from .tools import run_tool

    report = doctor()
    if not report.get("connected"):
        _message("Live is not reachable: %s" % (report.get("error") or "connection failed"))
        return
    repo = script_version() or ""
    running = str(report.get("script") or "")
    if repo and running and running != repo:
        _message(
            "Live loaded %s; this build ships %s. Restart Live, then run this again."
            % (running, repo)
        )
        return

    _draw(["  " + BOLD + "Working\u2026" + RESET, "", "  " + DIM + "Scanning warped audio clips." + RESET])
    payload: Dict[str, Any] = {}
    failures: List[str] = []
    client = LiveClient()
    try:
        client.connect(timeout=2.0)
        payload = run_tool(
            "clips_align_warp_markers",
            {"grid": 0.25, "max_shift": 0.25, "dry_run": False},
            client,
        )
    except LiveError as exc:
        failures.append(exc.message)
    except Exception as exc:  # noqa: BLE001 - the result screen reports it instead of crashing
        failures.append(str(exc))
    finally:
        client.close()
    _draw(_warp_result_lines(payload, failures))
    _pause()


def _run_warp_match() -> None:
    """Move each audio layer's markers onto the drum track's transients."""
    from .cli import doctor
    from .protocol.client import LiveClient
    from .protocol.codes import LiveError
    from .setup import script_version
    from .tools import run_tool

    report = doctor()
    if not report.get("connected"):
        _message("Live is not reachable: %s" % (report.get("error") or "connection failed"))
        return
    repo = script_version() or ""
    running = str(report.get("script") or "")
    if repo and running and running != repo:
        _message(
            "Live loaded %s; this build ships %s. Restart Live, then run this again."
            % (running, repo)
        )
        return

    _draw([
        "  " + BOLD + "Working\u2026" + RESET,
        "",
        "  " + DIM + "Reading the drum transients, then matching the layers." + RESET,
    ])
    payload: Dict[str, Any] = {}
    failures: List[str] = []
    client = LiveClient()
    try:
        client.connect(timeout=2.0)
        payload = run_tool(
            "clips_warp_match",
            {"max_shift": 0.25, "dry_run": False},
            client,
        )
    except LiveError as exc:
        failures.append(exc.message)
    except Exception as exc:  # noqa: BLE001 - the result screen reports it instead of crashing
        failures.append(str(exc))
    finally:
        client.close()
    _draw(_warp_result_lines(payload, failures))
    _pause()


def _run_bulk(
    title: str,
    autofix: bool = False,
    colour: bool = False,
    align: bool = False,
    warp: bool = False,
) -> None:
    """One connection, no prompts, and every step is an existing manifest tool."""
    from .cli import doctor
    from .protocol.client import LiveClient
    from .protocol.codes import LiveError
    from .setup import script_version
    from .state.snapshot import SnapshotCache
    from .tools import run_tool

    report = doctor()
    if not report.get("connected"):
        _message("Live is not reachable: %s" % (report.get("error") or "connection failed"))
        return
    repo = script_version() or ""
    running = str(report.get("script") or "")
    if repo and running and running != repo:
        _message(
            "Live loaded %s; this build ships %s. Restart Live, then run this again."
            % (running, repo)
        )
        return

    renamed, coloured, aligned, warped, markers = 0, 0, 0, 0, 0
    failures: List[str] = []
    progress = ["  " + BOLD + "Working\u2026" + RESET, "", "  " + DIM + "No prompts; safe tools only." + RESET]
    if autofix or warp:
        progress.append("  " + ORANGE + "Audible: gain and clip timing may move." + RESET)
    _draw(progress)
    client = LiveClient()
    try:
        client.connect(timeout=2.0)
        cache = SnapshotCache(client)
        if autofix:
            result = run_tool(
                "inspect_autofix",
                {"dry_run": False, "checkpoint": True},
                client,
                cache=cache,
            )
            for step in result.get("steps") or []:
                if step.get("tool") in ("tracks_name_and_color", "tracks.name_and_color"):
                    renamed += 1
            if result.get("rolled_back"):
                failures.append("Autofix rolled back to its checkpoint.")
            if result.get("stopped"):
                failures.append("Autofix stopped: %s" % result["stopped"])
            cache.invalidate()

        tracks = run_tool("tracks_list", {"limit": 200}, client).get("items") or []
        if colour:
            structure = run_tool(
                "inspect_structure", {"limit": 200}, client, cache=cache
            )
            rows = (structure.get("tracks") or {}).get("items") or []
            kinds = {
                row.get("index"): str(row.get("kind") or "")
                for row in rows if isinstance(row.get("index"), int)
            }
            for row in tracks:
                index = row.get("index")
                if not isinstance(index, int):
                    continue
                desired = _track_colour(kinds.get(index, ""), bool(row.get("is_midi")))
                if int(row.get("color") or 0) == desired:
                    continue
                try:
                    run_tool(
                        "tracks_name_and_color",
                        {"track_index": index, "color": desired, "dry_run": False},
                        client,
                        cache=cache,
                    )
                    coloured += 1
                except LiveError as exc:
                    failures.append("Colour %s: %s" % (row.get("name", "?"), exc.message))

        if align:
            for row in tracks:
                if not row.get("is_midi"):
                    continue
                index = row.get("index")
                if not isinstance(index, int):
                    continue
                try:
                    result = run_tool(
                        "notes_align_track",
                        {
                            "track_index": index,
                            "grid": 0.25,
                            "strength": 1.0,
                            "dry_run": False,
                        },
                        client,
                    )
                    aligned += int(result.get("clips") or 0)
                except LiveError as exc:
                    failures.append("Align %s: %s" % (row.get("name", "?"), exc.message))

        if warp:
            try:
                result = run_tool(
                    "clips_align_warp_markers",
                    {"grid": 0.25, "max_shift": 0.25, "dry_run": False},
                    client,
                )
                warped = int(result.get("clips") or 0)
                markers = int(result.get("moved") or 0)
            except LiveError as exc:
                failures.append("Warp markers: %s" % exc.message)
        cache.invalidate()
    except LiveError as exc:
        failures.append(exc.message)
    except Exception as exc:  # noqa: BLE001 - the result screen reports it instead of crashing
        failures.append(str(exc))
    finally:
        client.close()

    _draw(
        _bulk_result_lines(
            title, renamed, coloured, aligned, failures,
            audible=autofix or warp, warped=warped, markers=markers,
        )
    )
    _pause()


def open_mode(cli_main: Callable[[Optional[Sequence[str]]], int], key: str) -> None:
    page = MODE_PAGES.get(key)
    if page is None:
        return
    selected = 0
    while True:
        _draw(_mode_lines(page, selected))
        pressed = _read_key()
        if pressed in ("escape", "q", "ctrl-c"):
            return
        if pressed == "up":
            selected = (selected - 1) % len(page.options)
            continue
        if pressed == "down":
            selected = (selected + 1) % len(page.options)
            continue
        if pressed != "enter":
            continue
        action = page.options[selected]
        if not action.available:
            _message(action.reason or "This action is not available in this build.")
            continue
        if action.special == "back":
            return
        if action.special == "guide":
            _show_guide(action, page.title)
            continue
        if action.special == "warp":
            _run_warp()
            continue
        if action.special == "warp_match":
            _run_warp_match()
            continue
        if action.special == "cleanup":
            _run_bulk("CLEAN", autofix=True, colour=True, align=True, warp=True)
            continue
        if action.special == "align":
            _run_bulk("ALIGN", align=True)
            continue
        if action.special == "colour":
            _run_bulk("COLOUR", colour=True)
            continue
        if action.special == "inspect":
            _show_inspect(cli_main)
            continue
        if action.special == "autofix":
            _show_autofix(cli_main, action.phases)
            continue
        if action.special == "report":
            _show_report(cli_main, action.tool, page.title, action.fields, action.guide)
            continue
        _run_tool_action(cli_main, action, page.title)


def _render(selected: int, status: str, stale: str = "") -> None:
    columns, rows = shutil.get_terminal_size((80, 24))
    lines: List[str] = []

    if columns >= 60:
        lines.extend(logo())
        lines.append("")
    else:
        lines.append(ORANGE + BOLD + "ENABLETON" + RESET)
    version = _version()
    lines.append(
        _VERSION_PREFIX
        + GREY
        + "Enableton"
        + RESET
        + " "
        + WHITE
        + version
        + RESET
        + DIM
        + "  Ableton Live, for your LLM"
        + RESET
    )
    lines.append(_VERSION_PREFIX + status)
    if stale:
        lines.append(_VERSION_PREFIX + stale)
    lines.append("")
    lines.append(
        _VERSION_PREFIX
        + BOLD
        + "? What would you like to do?"
        + RESET
        + DIM
        + "  (arrow keys, enter to select)"
        + RESET
    )

    chrome = len(lines) + 1  # + the footer
    visible = max(4, rows - chrome)
    start = max(0, min(selected - visible // 2, len(MENU) - visible))
    for index in range(start, min(len(MENU), start + visible)):
        item = MENU[index]
        if item.kind == "section":
            lines.append("  " + GREY + "\u2500\u2500 " + item.label + " " + "\u2500" * 3 + RESET)
        elif index == selected:
            lines.append(" " + ORANGE + "\u276f" + RESET + " " + BOLD + item.label + RESET)
        else:
            lines.append("   " + item.label)

    lines.append(
        "  " + DIM + "\u2191\u2193 move \u00b7 enter select \u00b7 q quit" + RESET
    )
    sys.stdout.write("\x1b[H\x1b[2J" + "\n".join(lines) + "\n")
    sys.stdout.flush()


def _read_key() -> str:
    """One key press as a name: up, down, enter, escape, or the character itself."""
    if os.name == "nt":
        import msvcrt

        char = msvcrt.getwch()
        if char in ("\x00", "\xe0"):
            return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(
                msvcrt.getwch(), ""
            )
        if char == "\r":
            return "enter"
        if char == "\x1b":
            return "escape"
        if char == "\x03":
            return "ctrl-c"
        if char in ("\x08", "\x7f"):
            return "backspace"
        return char.lower()

    import select
    import termios
    import tty

    descriptor = sys.stdin.fileno()
    original = termios.tcgetattr(descriptor)
    try:
        tty.setraw(descriptor)
        char = sys.stdin.read(1)
        if char == "\x1b":
            ready, _, _ = select.select([descriptor], [], [], 0.05)
            if ready:
                return {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}.get(
                    sys.stdin.read(2), ""
                )
            return "escape"
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, original)
    if char in ("\r", "\n"):
        return "enter"
    if char == "\x03":
        return "ctrl-c"
    if char in ("\x08", "\x7f"):
        return "backspace"
    return char.lower()


def _pause() -> None:
    sys.stdout.write("\n  " + DIM + "press any key to return to the menu" + RESET)
    sys.stdout.flush()
    _read_key()


def run(cli_main: Callable[[Optional[Sequence[str]]], int]) -> int:
    """Draw the menu until the user quits. Returns the CLI's own exit code for actions."""
    os.system("")  # enable ANSI escapes on consoles that still need telling
    selected = _first_action()
    status, stale = _status_lines()
    sys.stdout.write("\x1b[?25l")  # hide the cursor while the menu owns the screen
    try:
        while True:
            _render(selected, status, stale)
            key = _read_key()
            if key in ("q", "escape", "ctrl-c"):
                _clear()
                return 0
            if key == "up":
                selected = step(selected, -1)
                continue
            if key == "down":
                selected = step(selected, 1)
                continue
            if key == "r":
                status, stale = _status_lines()
                continue
            if key != "enter":
                continue

            action = MENU[selected].action
            if action.startswith("mode:"):
                open_mode(cli_main, action.split(":", 1)[1])
                continue
            if action == "exit":
                _clear()
                return 0
            if action == "help":
                _clear()
                cli_main(["--help"])
                _pause()
                continue
            if action == "cleanup":
                _run_bulk("CLEAN", autofix=True, colour=True, align=True, warp=True)
                status, stale = _status_lines()
                continue

            if action == "browse":
                browse_tools(cli_main)
                continue

            argv = _collect(action)
            if argv is None:
                continue
            _clear()
            try:
                code = cli_main(argv)
            except SystemExit as exc:  # argparse exits this way on bad arguments
                code = int(exc.code or 0)
            except KeyboardInterrupt:
                code = 130
            sys.stdout.write(
                "\n  " + (GREEN if code == 0 else GREY) + "exit %d" % code + RESET
            )
            _pause()
    finally:
        sys.stdout.write("\x1b[?25h")  # always give the cursor back
        _clear()


__all__ = ["Item", "MENU", "logo", "run", "step", "visible_width"]

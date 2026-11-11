"""The interactive menu: a front-end over the same argv the CLI already takes.

Every action here is an argument list handed to ``enableton.cli.main``. The menu cannot do
anything the CLI cannot, and it inherits the CLI's exit codes; nothing in this module talks to
Live directly, so the menu can never drift into being a second API.

The screen is rebuilt from scratch on every key press, which keeps the rendering code free of
cursor arithmetic. The menu is viewport-ed, so it stays usable in a 24-line terminal as well as a
tall one.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
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

#: A 5x5 block font. Only the letters in the title are defined; anything else keeps the width.
_FONT = {
    "A": (".###.", "#...#", "#####", "#...#", "#...#"),
    "B": ("####.", "#...#", "####.", "#...#", "####."),
    "E": ("#####", "#....", "####.", "#....", "#####"),
    "L": ("#....", "#....", "#....", "#....", "#####"),
    "N": ("#...#", "##..#", "#.#.#", "#..##", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", ".###."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#.."),
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


MENU: Tuple[Item, ...] = (
    Item("section", "Live"),
    Item("action", "\U0001f50c  Doctor \u2014 connection, version, queue", "doctor"),
    Item("action", "\U0001f4ca  Set summary", "status"),
    Item("action", "\U0001fa7a  Inspect findings", "inspect"),
    Item("action", "\U0001f39b   Modes and per-mode findings", "modes"),
    Item("section", "Catalogue"),
    Item("action", "\U0001f9f0  Browse tools", "browse"),
    Item("action", "\U0001f4d6  Describe a tool", "describe"),
    Item("action", "\u25b6   Run a tool", "call"),
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


def _render_browser(
    query: str, matches: Sequence[str], selected: int, catalogue: Dict[str, Any]
) -> None:
    columns, rows = shutil.get_terminal_size((80, 24))
    lines = [
        "  " + ORANGE + BOLD + "ENABLETON" + RESET + GREY + "  tool browser" + RESET,
        "",
    ]
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
            if action == "exit":
                _clear()
                return 0
            if action == "help":
                _clear()
                cli_main(["--help"])
                _pause()
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

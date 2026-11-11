"""Text screens and stable choice routing for one MCP session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..manifest import Tool
from ..modes import ModeSet, guide


class ScreenError(ValueError):
    """A requested screen or choice is not available in the current state."""


@dataclass(frozen=True)
class Choice:
    id: str
    label: str
    target: str


class Session:
    """In-memory screen state; the loaded mode and its tool scope stay fixed."""

    def __init__(
        self,
        mode: str,
        catalogue: dict[str, Tool],
        modes: ModeSet,
    ) -> None:
        self.mode = modes.get(mode).name
        self.catalogue = catalogue
        self.modes = modes
        self.screen = "main"
        self.selection: dict[str, Any] | None = None
        self.report: dict[str, Any] | None = None
        self.live_status: dict[str, Any] | None = None
        self.plan: str | None = None
        self._view_mode = self.mode
        self._choices: list[Choice] = []

    def render(self, screen: str | None = None) -> dict[str, Any]:
        if screen is not None:
            self._set_screen(screen)

        mode = self.modes.get(self.mode)
        choices = self._screen_choices()
        self._choices = choices
        labels = [choice.label for choice in choices]
        scope = {"mode": self.mode, "tools": len(mode.tools)}
        lines = [
            "ENABLETON",
            f"Scope: {self.mode} ({len(mode.tools)} tools)",
        ]
        structured: dict[str, Any] = {
            "scope": scope,
            "selection": self.selection,
            "report": self.report,
            "live_status": self.live_status,
            "plan": self.plan,
            "choices": [{"id": choice.id, "label": choice.label} for choice in choices],
        }

        if self.screen == "main":
            if self.live_status is None:
                structured["set"] = {
                    "status": "unavailable",
                    "reason": "Live has not been queried in this screen session; call ableton_status for current Set details.",
                }
                lines.append(
                    "Set status: unavailable — call ableton_status to read the current Set."
                )
            else:
                structured["set"] = {"status": "available", **self.live_status}
                lines.append(
                    "Set status: " + str(self.live_status.get("name", "read from Live"))
                )
                lines.append("Live details: " + str(self.live_status))
            if self.report is not None:
                counts = self.report.get("counts")
                if counts is not None:
                    structured["findings"] = counts
                    lines.append("Last diagnostic counts: " + str(counts))
            lines.append("Open a mode, review the current scope, or inspect settings.")
        elif self.screen == "modes":
            lines.append("Modes")
            rows = []
            for name in self.modes.names():
                item = self.modes.get(name)
                rows.append(
                    {
                        "mode": name,
                        "tools": len(item.tools),
                        "summary": item.summary,
                        "loaded": name == self.mode,
                    }
                )
                marker = " [loaded]" if name == self.mode else ""
                lines.append(
                    f"{name} — {len(item.tools)} tools — {item.summary}{marker}"
                )
            structured["modes"] = rows
        elif self.screen.startswith("mode:"):
            viewed = self.modes.get(self._view_mode)
            lines.append(f"Mode: {viewed.name} — {viewed.summary}")
            if viewed.name != self.mode:
                lines.append(
                    f"This is a read-only mode preview; the loaded scope remains {self.mode}. "
                    f"Start a new server with --mode {viewed.name} to load it."
                )
            lines.append("Tools: " + ", ".join(viewed.tools))
            structured["view_mode"] = viewed.name
            structured["tools"] = list(viewed.tools)
        elif self.screen == "prompt":
            sheet = guide(self.catalogue, self.mode)
            lines.append(f"Custom prompt — scope: {self.mode}")
            lines.append("Available commands:")
            structured["tools"] = sheet["tools"]
            for item in sheet["tools"]:
                example = "; ".join(item["examples"])
                suffix = f" — try: {example}" if example else ""
                lines.append(f"{item['tool']} — {item['summary']}{suffix}")
        elif self.screen == "apply":
            status = (
                f"active plan: {self.plan}"
                if self.plan
                else "unavailable — no active plan is loaded."
            )
            lines.append(f"Apply screen: {status}")
            lines.append(
                "Plan execution is available only through the listed plan tools and their safety checks."
            )
            structured["availability"] = {
                "status": "available" if self.plan else "unavailable",
                "reason": None if self.plan else "no active plan is loaded",
            }
        elif self.screen == "recipe":
            lines.append(
                "Recipe screen: unavailable — no recipe session is loaded in this M5 server."
            )
            structured["availability"] = {
                "status": "unavailable",
                "reason": "no recipe session is loaded",
            }
        elif self.screen == "settings":
            lines.append(
                "Settings screen: unavailable — persistent user configuration is not part of this server session."
            )
            structured["availability"] = {
                "status": "unavailable",
                "reason": "persistent user configuration is not part of this server session",
            }

        if labels:
            lines.append("Choices:")
            lines.extend(
                f"{index}. {choice.label} (id: {choice.id})"
                for index, choice in enumerate(choices, start=1)
            )
        return {
            "screen": self.screen,
            "text": "\n".join(lines),
            "structured": structured,
        }

    def choose(self, choice_id: Any) -> dict[str, Any]:
        token = str(choice_id).strip()
        if not self._choices:
            self.render()

        choice = None
        if token.isdigit():
            index = int(token) - 1
            if 0 <= index < len(self._choices):
                choice = self._choices[index]
        if choice is None:
            for candidate in self._choices:
                aliases = {candidate.id.casefold(), candidate.label.casefold()}
                if candidate.target.startswith("mode:"):
                    aliases.add(candidate.target.split(":", 1)[1].casefold())
                if token.casefold() in aliases:
                    choice = candidate
                    break
        if choice is None:
            raise ScreenError(
                f"choice {token!r} is not available on screen {self.screen!r}"
            )
        self._set_screen(choice.target)
        return self.render()

    def _set_screen(self, screen: str) -> None:
        if screen.startswith("mode:"):
            name = screen.split(":", 1)[1]
            self.modes.get(name)
            self._view_mode = name
        elif screen not in {"main", "modes", "prompt", "apply", "recipe", "settings"}:
            raise ScreenError(f"unknown screen {screen!r}")
        self.screen = screen

    def _screen_choices(self) -> list[Choice]:
        if self.screen == "main":
            return [
                Choice("open:modes", "Browse modes", "modes"),
                Choice("open:prompt", "Custom prompt", "prompt"),
                Choice("open:settings", "Settings", "settings"),
            ]
        if self.screen == "modes":
            return [
                Choice(f"mode:{name}", name, f"mode:{name}")
                for name in self.modes.names()
            ] + [Choice("back:main", "Back", "main")]
        if self.screen.startswith("mode:"):
            return [
                Choice("open:prompt", "Open custom prompt", "prompt"),
                Choice("back:modes", "Back to modes", "modes"),
            ]
        if self.screen == "prompt":
            return [
                Choice("open:modes", "Show all modes", "modes"),
                Choice("back:main", "Back", "main"),
            ]
        return [Choice("back:main", "Back", "main")]

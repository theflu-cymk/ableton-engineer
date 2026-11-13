"""MCP server construction and stdio transport."""

from __future__ import annotations

import json
from typing import Any

from mcp import types as mcp_types
from mcp.server import MCPServer

from ..manifest import load_manifest, to_mcp_tools
from ..modes import ModeError, ModeSet, load_modes
from ..protocol.client import DEFAULT_PORT, LiveClient
from ..protocol.codes import LiveError
from ..state.snapshot import SnapshotCache
from ..tools import run_tool
from .session import ScreenError, Session

_SCREEN_TOOLS = {"ableton_start", "ableton_screen", "ableton_choose"}
_SERVER_INSTRUCTIONS = (
    "Enableton serves one static, mode-scoped catalogue per session. "
    "Screen controls are ableton_start with no arguments, ableton_screen with a screen "
    "name, and ableton_choose with a displayed choice id; they return text and structured "
    "screen data. They are session controls, separate from the mode catalogue. "
    "Use ableton_guide with scope='all' and detail='full' to discover the whole catalogue. "
    "Use ableton_inspect to run any read-only, non-core tool outside the loaded mode; it "
    "never writes Live. Use ableton_escalate with explicit steps for any reversible write "
    "outside the mode, then ableton_plan_apply. If no tool can perform a step, tell the user "
    "the exact manual action and how to verify it; never claim it happened."
)


class LiveTransport:
    """Own one lazy connection to Live for the lifetime of the MCP server."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        client: LiveClient | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.client = client or LiveClient(host=host, port=port)
        self.features = frozenset()

    def call(
        self,
        cmd: str,
        args: dict[str, Any] | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        if not self.client.connected:
            self.client.connect(timeout=1.5)
        return self.client.call(cmd, args, timeout_ms=timeout_ms)

    def describe(self) -> dict[str, Any]:
        return {
            "backend": "remote",
            "host": self.host,
            "port": self.port,
            "features": sorted(self.features),
        }

    def close(self) -> None:
        self.client.close()


class EnabletonServer(MCPServer):
    """An MCP server whose exposed tools and calls share the selected mode."""

    def __init__(
        self,
        catalogue: dict[str, Any],
        modes: ModeSet,
        mode: str,
        adapter: Any,
    ) -> None:
        super().__init__(
            name="enableton",
            title="Enableton",
            instructions=_SERVER_INSTRUCTIONS,
        )
        self.catalogue = catalogue
        self.modes = modes
        self.mode = modes.get(mode)
        self.adapter = adapter
        self.cache = SnapshotCache(adapter)
        self.session = Session(self.mode.name, catalogue, modes)
        self._tool_names = frozenset(self.mode.tools)

    async def list_tools(self) -> list[mcp_types.Tool]:
        projected = to_mcp_tools(self.catalogue, self.mode.tools)
        catalogue_tools = [
            mcp_types.Tool(
                name=item["name"],
                description=item["description"],
                inputSchema=item["inputSchema"],
                annotations=mcp_types.ToolAnnotations(**item["annotations"]),
            )
            for item in projected
        ]
        return catalogue_tools + self._screen_tools() + [self._inspect_tool()]

    @staticmethod
    def _inspect_tool() -> mcp_types.Tool:
        annotations = mcp_types.ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
        return mcp_types.Tool(
            name="ableton_inspect",
            description=(
                "Run any read-only, non-core catalogue tool outside the loaded mode. Use "
                "ableton_guide with scope='all' to discover names and schemas. This never "
                "writes Live; use ableton_escalate for writes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "description": "Read-only catalogue tool name.",
                    },
                    "args": {
                        "type": "object",
                        "default": {},
                        "description": "Arguments for that tool.",
                    },
                },
                "required": ["tool"],
                "additionalProperties": False,
            },
            annotations=annotations,
            _meta={"enableton": {"scope": "session_control"}},
        )

    @staticmethod
    def _screen_tools() -> list[mcp_types.Tool]:
        annotations = mcp_types.ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
        meta = {"enableton": {"scope": "session_control"}}
        return [
            mcp_types.Tool(
                name="ableton_start",
                description="Open the current Enableton text screen.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                annotations=annotations,
                _meta=meta,
            ),
            mcp_types.Tool(
                name="ableton_screen",
                description="Render a text screen: main, modes, mode:<name>, prompt, apply, recipe, or settings.",
                inputSchema={
                    "type": "object",
                    "properties": {"screen": {"type": "string"}},
                    "required": ["screen"],
                    "additionalProperties": False,
                },
                annotations=annotations,
                _meta=meta,
            ),
            mcp_types.Tool(
                name="ableton_choose",
                description="Follow a displayed numbered choice, label, or stable choice id.",
                inputSchema={
                    "type": "object",
                    "properties": {"id": {"type": ["string", "integer"]}},
                    "required": ["id"],
                    "additionalProperties": False,
                },
                annotations=annotations,
                _meta=meta,
            ),
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Any = None,
    ) -> mcp_types.CallToolResult:
        if not isinstance(arguments, dict):
            return self._error("BAD_ARGS", "arguments must be an object")

        if name in _SCREEN_TOOLS:
            return self._screen_call(name, arguments)
        if name == "ableton_inspect":
            return self._inspect_call(arguments)
        if name not in self._tool_names:
            if name in self.catalogue:
                message = f"tool {name!r} is not available in mode {self.mode.name!r}"
            else:
                message = f"Enableton has no tool {name!r}"
            return self._error("UNKNOWN_COMMAND", message)

        try:
            result = run_tool(
                name,
                arguments,
                self.adapter,
                catalogue=self.catalogue,
                cache=self.cache,
            )
        except LiveError as exc:
            return self._error(exc.code, exc.message, exc.detail)
        if name == "ableton_status":
            self.session.live_status = result
        elif name == "inspect_run":
            self.session.report = result
        elif name == "ableton_escalate":
            self.session.plan = result.get("plan_id") or self.session.plan
        elif (
            name == "ableton_plan_apply"
            and result.get("applied")
            or name == "ableton_plan_discard"
            and result.get("discarded")
        ):
            self.session.plan = None
        return self._success(result)

    def _inspect_call(
        self,
        arguments: dict[str, Any],
    ) -> mcp_types.CallToolResult:
        unknown = sorted(set(arguments) - {"tool", "args"})
        if unknown:
            return self._error(
                "BAD_ARGS",
                "ableton_inspect has unknown argument(s): %s" % ", ".join(unknown),
            )
        tool_name = arguments.get("tool")
        if not isinstance(tool_name, str) or not tool_name:
            return self._error("BAD_ARGS", "tool must be a non-empty string")
        target_args = arguments.get("args", {})
        if not isinstance(target_args, dict):
            return self._error("BAD_ARGS", "args must be an object")
        target = self.catalogue.get(tool_name)
        if target is None:
            return self._error("UNKNOWN_COMMAND", "Enableton has no tool %r" % (tool_name,))
        if target.writes:
            return self._error(
                "BAD_ARGS",
                "tool %r writes; use ableton_escalate with explicit steps instead" % (tool_name,),
            )
        if target.domain == "core":
            return self._error(
                "BAD_ARGS",
                "core control tools are not available through ableton_inspect",
            )
        try:
            result = run_tool(
                tool_name,
                target_args,
                self.adapter,
                catalogue=self.catalogue,
                cache=self.cache,
            )
        except LiveError as exc:
            return self._error(exc.code, exc.message, exc.detail)
        return self._success({"tool": tool_name, "args": target_args, "result": result})

    def _screen_call(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> mcp_types.CallToolResult:
        required: dict[str, set[str]] = {
            "ableton_start": set(),
            "ableton_screen": {"screen"},
            "ableton_choose": {"id"},
        }
        if set(arguments) != required[name]:
            expected = ", ".join(sorted(required[name])) or "no arguments"
            return self._error(
                "BAD_ARGS",
                f"{name} expects {expected}",
            )
        try:
            if name == "ableton_start":
                result = self.session.render()
            elif name == "ableton_screen":
                screen = arguments["screen"]
                if not isinstance(screen, str):
                    raise ScreenError("screen must be a string")
                result = self.session.render(screen)
            else:
                choice_id = arguments["id"]
                if not isinstance(choice_id, (str, int)) or isinstance(choice_id, bool):
                    raise ScreenError("choice id must be a string or integer")
                result = self.session.choose(choice_id)
        except (ScreenError, ModeError) as exc:
            return self._error("BAD_ARGS", str(exc))
        return self._success(result)

    @staticmethod
    def _success(result: dict[str, Any]) -> mcp_types.CallToolResult:
        text = json.dumps(result, ensure_ascii=False, allow_nan=False)
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(text=text)],
            structuredContent=result,
        )

    @staticmethod
    def _error(
        code: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> mcp_types.CallToolResult:
        payload = {
            "error": {
                "code": code,
                "message": message,
                "detail": detail or {},
            }
        }
        return mcp_types.CallToolResult(
            content=[
                mcp_types.TextContent(
                    text=json.dumps(payload, ensure_ascii=False, allow_nan=False)
                )
            ],
            structuredContent=payload,
            isError=True,
        )


def create_server(
    mode: str | None = None,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    adapter: Any = None,
) -> EnabletonServer:
    catalogue = load_manifest()
    modes = load_modes(catalogue)
    selected = modes.get(mode)
    transport = adapter if adapter is not None else LiveTransport(host=host, port=port)
    return EnabletonServer(catalogue, modes, selected.name, transport)


def run_stdio(
    mode: str | None = None,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
) -> None:
    server = create_server(mode=mode, host=host, port=port)
    try:
        server.run("stdio")
    finally:
        close = getattr(server.adapter, "close", None)
        if close is not None:
            close()

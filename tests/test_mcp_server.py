import asyncio
import io
import json
import unittest
from contextlib import redirect_stdout

import support

from enableton.cli import EXIT_OK, main
from enableton.live.fake import FakeAdapter
from enableton.manifest import load_manifest
from enableton.mcp.transport import create_server
from enableton.modes import load_modes


class McpServerTests(unittest.TestCase):
    def test_tools_list_is_the_selected_mode(self):
        server = create_server(mode="sound", adapter=FakeAdapter())
        listed = asyncio.run(server.list_tools())
        listed_names = [tool.name for tool in listed]
        mode_names = list(server.modes.get("sound").tools)
        self.assertEqual(
            [name for name in listed_names if name in mode_names], mode_names
        )
        self.assertEqual(
            len(mode_names),
            len(load_modes(server.catalogue).get("sound").tools),
        )
        self.assertEqual(
            set(listed_names) - set(mode_names),
            {"ableton_start", "ableton_screen", "ableton_choose", "ableton_inspect"},
        )

    def test_read_only_call_matches_cli_json(self):
        fake = support.fake_server()
        self.addCleanup(fake.stop)

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                main(
                    [
                        "--port",
                        str(fake.port),
                        "call",
                        "ableton_guide",
                        "--args",
                        '{"mode":"sound"}',
                    ]
                ),
                EXIT_OK,
            )
        cli_result = json.loads(output.getvalue())

        server = create_server(mode="sound", adapter=FakeAdapter())
        mcp_result = asyncio.run(server.call_tool("ableton_guide", {"mode": "sound"}))
        self.assertFalse(mcp_result.is_error)
        self.assertEqual(mcp_result.structured_content, cli_result)

    def test_inspect_reaches_a_read_only_tool_outside_the_mode(self):
        server = create_server(mode="sound", adapter=FakeAdapter())
        self.assertNotIn("tracks_list", server.mode.tools)

        result = asyncio.run(
            server.call_tool("ableton_inspect", {"tool": "tracks_list", "args": {}})
        )

        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["tool"], "tracks_list")
        self.assertIn("items", result.structured_content["result"])

    def test_inspect_refuses_writes_control_tools_and_unknown_tools(self):
        server = create_server(mode="sound", adapter=FakeAdapter())

        for target, code, text in (
            ("tracks_set_volume", "BAD_ARGS", "writes"),
            ("ableton_escalate", "BAD_ARGS", "core control"),
            ("not_a_tool", "UNKNOWN_COMMAND", "not_a_tool"),
        ):
            with self.subTest(target=target):
                result = asyncio.run(
                    server.call_tool("ableton_inspect", {"tool": target, "args": {}})
                )
                self.assertTrue(result.is_error)
                self.assertEqual(result.structured_content["error"]["code"], code)
                self.assertIn(text, result.structured_content["error"]["message"])

    def test_inspect_rejects_bad_arguments(self):
        server = create_server(mode="sound", adapter=FakeAdapter())
        result = asyncio.run(
            server.call_tool("ableton_inspect", {"tool": "tracks_list", "args": []})
        )
        self.assertTrue(result.is_error)
        self.assertEqual(result.structured_content["error"]["code"], "BAD_ARGS")

    def test_unknown_tool_returns_structured_error(self):
        server = create_server(mode="sound", adapter=FakeAdapter())
        result = asyncio.run(server.call_tool("not_a_tool", {}))
        self.assertTrue(result.is_error)
        self.assertEqual(
            result.structured_content["error"]["code"],
            "UNKNOWN_COMMAND",
        )
        self.assertIn("not_a_tool", result.structured_content["error"]["message"])

    def test_serve_mode_list_reports_catalogue_counts(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["serve", "--mode", "list"]), EXIT_OK)
        payload = json.loads(output.getvalue())
        # Counts come from modes.json, so read the same source rather than quoting a number
        # that every catalogue change invalidates.
        expected = {
            name: len(mode.tools)
            for name, mode in load_modes(load_manifest()).modes.items()
        }
        reported = {row["mode"]: row["tools"] for row in payload["modes"]}
        self.assertEqual(reported, expected)


if __name__ == "__main__":
    unittest.main()

import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from enableton.manifest import load_manifest
from enableton.modes import load_modes


class McpStdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_lists_mode_and_completes_text_navigation(self):
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "enableton", "serve", "--mode", "sound"],
        )
        catalogue = load_manifest()
        mode_names = set(load_modes(catalogue).get("sound").tools)

        async with (
            stdio_client(parameters) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()
            listed = await session.list_tools()
            listed_names = {tool.name for tool in listed.tools}
            self.assertEqual(listed_names.intersection(mode_names), mode_names)
            self.assertEqual(
                listed_names - mode_names,
                {"ableton_start", "ableton_screen", "ableton_choose"},
            )

            start = await session.call_tool("ableton_start", {})
            self.assertEqual(start.structured_content["screen"], "main")
            modes = await session.call_tool("ableton_choose", {"id": "open:modes"})
            self.assertEqual(modes.structured_content["screen"], "modes")
            sound = await session.call_tool("ableton_choose", {"id": "sound"})
            self.assertEqual(sound.structured_content["screen"], "mode:sound")
            self.assertEqual(
                sound.structured_content["structured"]["scope"]["tools"],
                len(mode_names),
            )

            unknown = await session.call_tool("unknown_tool", {})
            self.assertTrue(unknown.is_error)
            self.assertEqual(
                unknown.structured_content["error"]["code"],
                "UNKNOWN_COMMAND",
            )


if __name__ == "__main__":
    unittest.main()

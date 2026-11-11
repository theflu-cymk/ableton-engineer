import asyncio
import unittest

from enableton.live.fake import FakeAdapter
from enableton.mcp.transport import create_server


class McpSessionTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(mode="sound", adapter=FakeAdapter())

    def call_tool(self, name, arguments=None):
        return asyncio.run(self.server.call_tool(name, arguments or {}))

    def test_text_screens_and_loaded_scope(self):
        start = self.call_tool("ableton_start")
        self.assertFalse(start.is_error)
        self.assertEqual(start.structured_content["screen"], "main")
        self.assertIn("Set status: unavailable", start.structured_content["text"])

        # The scope line counts the loaded mode's catalogue tools; derive it instead of
        # quoting a number that every catalogue change invalidates.
        expected_tools = len(self.server.modes.get("sound").tools)
        screens = ("modes", "mode:sound", "prompt", "apply", "recipe", "settings")
        for screen in screens:
            result = self.call_tool("ableton_screen", {"screen": screen})
            self.assertFalse(result.is_error, screen)
            payload = result.structured_content
            self.assertEqual(payload["screen"], screen)
            self.assertIn(f"Scope: sound ({expected_tools} tools)", payload["text"])
            self.assertEqual(
                payload["structured"]["scope"],
                {"mode": "sound", "tools": expected_tools},
            )

    def test_choice_ids_and_aliases_navigate_and_keep_state(self):
        self.server.session.selection = {"track": 2}
        self.server.session.report = {"count": 3}

        modes = self.call_tool("ableton_choose", {"id": "open:modes"})
        self.assertEqual(modes.structured_content["screen"], "modes")
        sound = self.call_tool("ableton_choose", {"id": "sound"})
        self.assertEqual(sound.structured_content["screen"], "mode:sound")
        self.assertEqual(
            sound.structured_content["structured"]["selection"], {"track": 2}
        )
        self.assertEqual(sound.structured_content["structured"]["report"], {"count": 3})

        back = self.call_tool("ableton_choose", {"id": "back:modes"})
        self.assertEqual(back.structured_content["screen"], "modes")
        selected = self.call_tool("ableton_choose", {"id": "7"})
        self.assertEqual(selected.structured_content["screen"], "mode:sound")

    def test_unavailable_screens_explain_why(self):
        for screen, expected in (
            ("apply", "no active plan is loaded"),
            ("recipe", "no recipe session is loaded"),
            ("settings", "persistent user configuration"),
        ):
            payload = self.call_tool(
                "ableton_screen", {"screen": screen}
            ).structured_content
            self.assertEqual(
                payload["structured"]["availability"]["status"], "unavailable"
            )
            self.assertIn(expected, payload["text"])

    def test_read_only_results_feed_the_main_screen(self):
        self.server = create_server(mode="auto", adapter=FakeAdapter())
        report = self.call_tool("inspect_run", {"tier": "fast"})
        self.assertFalse(report.is_error)
        self.assertEqual(self.server.session.report, report.structured_content)

        status = self.call_tool("ableton_status")
        self.assertFalse(status.is_error)
        self.assertEqual(self.server.session.live_status, status.structured_content)

        main = self.call_tool("ableton_start")
        self.assertEqual(
            main.structured_content["structured"]["findings"],
            report.structured_content["counts"],
        )
        self.assertEqual(
            main.structured_content["structured"]["set"]["status"], "available"
        )
        self.assertIn("Last diagnostic counts", main.structured_content["text"])

    def test_stale_choice_and_unknown_screen_return_errors(self):
        stale = self.call_tool("ableton_choose", {"id": "mode:edit"})
        self.assertTrue(stale.is_error)
        self.assertEqual(stale.structured_content["error"]["code"], "BAD_ARGS")

        unknown = self.call_tool("ableton_screen", {"screen": "not-a-screen"})
        self.assertTrue(unknown.is_error)
        self.assertEqual(unknown.structured_content["error"]["code"], "BAD_ARGS")


if __name__ == "__main__":
    unittest.main()

import json
import unittest

import support  # noqa: F401
from enableton.protocol.codes import LiveError
from enableton.tools import run_tool


class GuideTests(unittest.TestCase):
    def test_guide_is_local_and_lists_the_default_mode(self):
        result = run_tool("ableton_guide", {}, None)
        self.assertEqual(result["mode"], "auto")
        names = [row["tool"] for row in result["tools"]]
        self.assertIn("ableton_status", names)
        self.assertIn("ableton_escalate", names)
        self.assertIn("ableton_plan_apply", names)
        json.dumps(result)

    def test_guide_can_describe_another_mode(self):
        result = run_tool("ableton_guide", {"mode": "inspect"}, None)
        self.assertEqual(result["mode"], "inspect")
        self.assertNotIn("inspect_autofix", [row["tool"] for row in result["tools"]])

    def test_unknown_guide_mode_is_a_typed_error(self):
        with self.assertRaises(LiveError) as ctx:
            run_tool("ableton_guide", {"mode": "mastering"}, None)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")
        self.assertIn("available:", ctx.exception.message)

    def test_unknown_guide_argument_is_rejected(self):
        with self.assertRaises(LiveError) as ctx:
            run_tool("ableton_guide", {"bogus": True}, None)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")


if __name__ == "__main__":
    unittest.main()

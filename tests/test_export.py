import json
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from enableton.live.fake import FakeAdapter
from enableton.protocol.codes import LiveError
from enableton.tools import run_tool


class ExportTests(unittest.TestCase):
    def test_export_writes_a_complete_json_audit(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "audit.json"
            result = run_tool(
                "inspect_export", {"tier": "standard", "path": str(path)}, FakeAdapter()
            )
            self.assertEqual(result["path"], str(path))
            self.assertEqual(result["tier"], "standard")
            self.assertEqual(result["findings"], 2)
            self.assertEqual(result["counts"]["total"], 2)
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["version"], 1)
            self.assertEqual(document["tier"], "standard")
            self.assertEqual(document["counts"]["by_mode"], {"auto": 0, "inspect": 2})
            self.assertEqual(len(document["findings"]), 2)
            self.assertFalse(path.with_name("audit.json.tmp").exists())

    def test_export_rejects_a_non_json_path(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(LiveError) as ctx:
                run_tool(
                    "inspect_export",
                    {"path": str(Path(root) / "audit.txt")},
                    FakeAdapter(),
                )
            self.assertEqual(ctx.exception.code, "BAD_ARGS")
            self.assertIn(".json", ctx.exception.message)

    def test_export_rejects_an_unknown_tier(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(LiveError) as ctx:
                run_tool(
                    "inspect_export",
                    {"tier": "slow", "path": str(Path(root) / "audit.json")},
                    FakeAdapter(),
                )
            self.assertEqual(ctx.exception.code, "BAD_ARGS")


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest

import support  # noqa: F401
from enableton.manifest import load_manifest
from enableton.modes import ModeError, load_modes


def write_modes(text):
    handle, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        json.dump(text, fh)
    return path


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = load_manifest()

    def test_shipped_modes(self):
        modes = load_modes(self.catalogue)
        self.assertEqual(modes.default, "auto")
        self.assertEqual(modes.names(), ["auto", "edit", "inspect"])
        self.assertIn("ableton_status", modes.get("auto").tools)  # core injected
        self.assertIn("tracks_gain_stage", modes.get("auto").tools)
        self.assertIn("notes_quantize", modes.get("edit").tools)
        self.assertIn("notes_read", modes.get("edit").tools)

    def test_unknown_mode_is_a_clear_error(self):
        modes = load_modes(self.catalogue)
        with self.assertRaises(ModeError) as ctx:
            modes.get("mastering")
        self.assertIn("available:", str(ctx.exception))

    def test_cap_is_enforced(self):
        path = write_modes({
            "validation": {"max_tools_per_mode": 3},
            "core_tools": ["ableton_status"],
            "modes": [{"name": "auto", "tools": ["ableton_guide", "tracks_list", "transport_play"]}],
        })
        try:
            with self.assertRaises(ModeError) as ctx:
                load_modes(self.catalogue, path)
            self.assertIn("cap is 3", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_unknown_tool_is_rejected(self):
        path = write_modes({
            "validation": {"max_tools_per_mode": 34},
            "core_tools": ["ableton_status"],
            "modes": [{"name": "auto", "tools": ["tracks_teleport"]}],
        })
        try:
            with self.assertRaises(ModeError):
                load_modes(self.catalogue, path)
        finally:
            os.unlink(path)

    def test_unreachable_tool_is_rejected(self):
        path = write_modes({
            "validation": {"max_tools_per_mode": 34},
            "core_tools": ["ableton_status"],
            "modes": [{"name": "auto", "tools": ["ableton_guide"]}],
        })
        try:
            with self.assertRaises(ModeError) as ctx:
                load_modes(self.catalogue, path)
            self.assertIn("tools in no mode", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_duplicate_mode_is_rejected(self):
        path = write_modes({
            "validation": {"max_tools_per_mode": 34},
            "core_tools": ["ableton_status", "ableton_guide"],
            "modes": [
                {"name": "auto", "tools": ["tracks_list"]},
                {"name": "auto", "tools": ["tracks_list"]},
            ],
        })
        try:
            with self.assertRaises(ModeError):
                load_modes(self.catalogue, path)
        finally:
            os.unlink(path)

    def test_every_shipped_mode_fits_the_cap(self):
        modes = load_modes(self.catalogue)
        for name in modes.names():
            self.assertLessEqual(len(modes.get(name).tools), modes.max_tools)


if __name__ == "__main__":
    unittest.main()

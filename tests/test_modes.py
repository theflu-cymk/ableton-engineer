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
        self.assertEqual(
            sorted(modes.names()),
            [
                "arrange", "auto", "edit", "inspect", "mix", "prep", "produce",
                "recipe", "session", "sound",
            ],
        )
        self.assertIn("ableton_status", modes.get("auto").tools)  # core injected
        self.assertIn("tracks_gain_stage", modes.get("auto").tools)
        self.assertIn("tracks_set_sends", modes.get("auto").tools)
        self.assertIn("tracks_name_and_color", modes.get("auto").tools)
        self.assertIn("clips_set_warp_mode", modes.get("auto").tools)
        self.assertIn("clips_set_warp_mode", modes.get("edit").tools)
        self.assertIn("clips_set_warping", modes.get("prep").tools)
        self.assertIn("clips_set_warping", modes.get("edit").tools)
        self.assertIn("clips_warp_map", modes.get("prep").tools)
        self.assertIn("clips_apply_warp_map", modes.get("prep").tools)
        self.assertIn("clips_apply_warp_map", modes.get("edit").tools)
        self.assertIn("clips_warp_match", modes.get("prep").tools)
        self.assertIn("clips_warp_match", modes.get("edit").tools)
        self.assertIn("clips_fix_loop_points", modes.get("auto").tools)
        self.assertIn("clips_fix_loop_points", modes.get("edit").tools)
        self.assertIn("notes_quantize", modes.get("edit").tools)
        self.assertIn("notes_read", modes.get("edit").tools)
        self.assertIn("tracks_duplicate", modes.get("prep").tools)
        self.assertIn("tracks_set_routing", modes.get("mix").tools)
        self.assertIn("sections_create_locators", modes.get("arrange").tools)
        self.assertIn("sections_move", modes.get("arrange").tools)
        self.assertIn("ableton_undo", modes.get("prep").tools)
        self.assertIn("clips_copy", modes.get("edit").tools)
        self.assertIn("clips_create_audio", modes.get("edit").tools)
        self.assertIn("clips_create_audio", modes.get("prep").tools)
        self.assertIn("tracks_create", modes.get("edit").tools)
        self.assertIn("tracks_create", modes.get("prep").tools)
        self.assertIn("library_browse", modes.get("sound").tools)
        self.assertIn("recipe_list", modes.get("recipe").tools)
        self.assertIn("recipe_save", modes.get("recipe").tools)
        self.assertIn("session_brief", modes.get("produce").tools)
        self.assertIn("reference_analyze", modes.get("produce").tools)
        self.assertIn("takes_create", modes.get("produce").tools)
        self.assertIn("takes_select", modes.get("produce").tools)
        self.assertIn("takes_discard", modes.get("produce").tools)
        self.assertIn("clips_fire", modes.get("session").tools)
        self.assertIn("clips_stop", modes.get("session").tools)
        self.assertIn("clips_delete", modes.get("session").tools)
        self.assertIn("clips_create_session_midi", modes.get("session").tools)
        self.assertIn("clips_create_session_audio", modes.get("session").tools)
        self.assertIn("clips_duplicate_to_arrangement", modes.get("session").tools)
        self.assertIn("transport_switch_view", modes.get("session").tools)
        self.assertIn("tracks_inspect", modes.get("session").tools)

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

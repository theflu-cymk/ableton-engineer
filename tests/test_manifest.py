import json
import os
import tempfile
import unittest

import support  # noqa: F401
from enableton.manifest import (
    ManifestError,
    load_manifest,
    remote_commands,
    to_mcp_tools,
)


def write_manifest(entries):
    handle, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "tools": entries}, fh)
    return path


def tool(**overrides):
    base = {
        "name": "tracks_list",
        "domain": "tracks",
        "summary": "List tracks.",
        "description": "Lists tracks.",
        "input": {"type": "object", "properties": {}},
        "timeout_ms": 1000,
        "writes": False,
        "reversible": True,
        "needs": [],
        "min_live": None,
        "cmd": "track.list",
    }
    base.update(overrides)
    return base


class ManifestTests(unittest.TestCase):
    def test_loads_shipped_manifest(self):
        catalogue = load_manifest()
        self.assertIn("ableton_status", catalogue)
        self.assertEqual(catalogue["ableton_guide"].cmd, None)
        self.assertTrue(catalogue["ableton_guide"].local)
        self.assertEqual(catalogue["ableton_status"].examples, ["what's in my set", "are you connected to Live"])

    def test_remote_commands_are_sorted_and_complete(self):
        catalogue = load_manifest()
        self.assertEqual(
            remote_commands(catalogue),
            ["clips.duplicate_range", "clips.fix_loop_points", "clips.rename",
             "clips.set_warp_mode",
             "notes.humanize", "notes.quantize",
             "notes.read", "notes.replace", "notes.scale_lock", "notes.strum", "notes.transform",
             "snapshot.get", "track.list", "tracks.gain_stage", "tracks.name_and_color",
             "tracks.set_pan", "tracks.set_sends", "tracks.set_volume", "transport.locate",
             "transport.play", "transport.set_loop", "transport.stop"],
        )

    def test_rejects_duplicate_names(self):
        path = write_manifest([tool(), tool()])
        try:
            with self.assertRaises(ManifestError):
                load_manifest(path)
        finally:
            os.unlink(path)

    def test_rejects_bad_name(self):
        path = write_manifest([tool(name="tracks")])
        try:
            with self.assertRaises(ManifestError):
                load_manifest(path)
        finally:
            os.unlink(path)

    def test_rejects_non_snake_names(self):
        for bad in ("Tracks_List", "tracks-list", "tracks_list!"):
            path = write_manifest([tool(name=bad)])
            try:
                with self.assertRaises(ManifestError, msg=bad):
                    load_manifest(path)
            finally:
                os.unlink(path)

    def test_rejects_non_object_input(self):
        path = write_manifest([tool(input={"type": "array"})])
        try:
            with self.assertRaises(ManifestError):
                load_manifest(path)
        finally:
            os.unlink(path)

    def test_rejects_bad_timeout(self):
        for bad in (0, -5, "fast", True):
            path = write_manifest([tool(timeout_ms=bad)])
            try:
                with self.assertRaises(ManifestError, msg=repr(bad)):
                    load_manifest(path)
            finally:
                os.unlink(path)

    def test_rejects_missing_field(self):
        entry = tool()
        del entry["reversible"]
        path = write_manifest([entry])
        try:
            with self.assertRaises(ManifestError):
                load_manifest(path)
        finally:
            os.unlink(path)

    def test_mcp_projection(self):
        catalogue = load_manifest()
        specs = to_mcp_tools(catalogue, ["tracks_list", "tracks_gain_stage"])
        by_name = {spec["name"]: spec for spec in specs}
        self.assertTrue(by_name["tracks_list"]["annotations"]["readOnlyHint"])
        self.assertFalse(by_name["tracks_gain_stage"]["annotations"]["readOnlyHint"])
        self.assertEqual(by_name["tracks_list"]["inputSchema"]["type"], "object")
        self.assertIn("List tracks with name, colour, volume, pan and sends.",
                      by_name["tracks_list"]["description"])


if __name__ == "__main__":
    unittest.main()

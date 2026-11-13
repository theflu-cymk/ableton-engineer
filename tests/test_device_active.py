"""Device bypass writes: dry run, apply, exact restore and type validation."""

import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, build_song
from enableton.manifest import load_manifest
from enableton.modes import load_modes

from Enableton.errors import ScriptError


class DeviceActiveTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.adapter = FakeAdapter(self.song)
        self.device = self.song.tracks[0].devices[0]

    def args(self, **overrides):
        base = {
            "track": "Drums",
            "device": self.device.name,
            "active": False,
        }
        base.update(overrides)
        return base

    def test_dry_run_and_apply_are_reversible(self):
        before = self.device.is_active
        preview = self.adapter.call("devices.set_active", self.args(dry_run=True))
        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["changes"][0]["from"], before)
        self.assertEqual(self.device.is_active, before)

        applied = self.adapter.call("devices.set_active", self.args(dry_run=False))
        self.assertFalse(self.device.is_active)
        self.assertFalse(applied["changes"][0]["to"])

        restored = self.adapter.call("devices.set_active", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertEqual(self.device.is_active, before)

    def test_active_must_be_a_boolean(self):
        for value in (0, 1, "false", None):
            with self.assertRaises(ScriptError, msg=repr(value)) as ctx:
                self.adapter.call("devices.set_active", self.args(active=value))
            self.assertEqual(ctx.exception.code, "BAD_ARGS", value)

    def test_tool_and_sound_mode_are_declared(self):
        catalogue = load_manifest()
        self.assertEqual(catalogue["devices_set_active"].cmd, "devices.set_active")
        self.assertTrue(catalogue["devices_set_active"].writes)
        self.assertTrue(catalogue["devices_set_active"].reversible)
        self.assertIn("devices_set_active", load_modes(catalogue).get("sound").tools)


if __name__ == "__main__":
    unittest.main()

import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeDevice, build_song

from Enableton.errors import ScriptError


class DeviceBypassTests(unittest.TestCase):
    def setUp(self):
        self.song = build_song()
        self.adapter = FakeAdapter(self.song)
        self.device = self.song.tracks[0].devices[0]

    def test_dry_run_leaves_the_device_active(self):
        result = self.adapter.call("devices.bypass", {
            "track": "Drums", "device_index": 0, "bypass": True, "dry_run": True,
        })
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["from"])
        self.assertFalse(result["to"])
        self.assertTrue(self.device.is_active)

    def test_apply_and_restore_are_exact(self):
        applied = self.adapter.call("devices.bypass", {
            "track": "Drums", "device_index": 0, "bypass": True, "dry_run": False,
        })
        self.assertFalse(self.device.is_active)
        self.assertFalse(applied["active"])
        self.assertEqual(len(applied["undo"]), 1)

        restored = self.adapter.call("devices.bypass", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertTrue(self.device.is_active)

    def test_device_name_and_track_index_are_supported(self):
        applied = self.adapter.call("devices.bypass", {
            "track_index": 0, "device": "Glue", "bypass": True, "dry_run": False,
        })
        self.assertFalse(self.song.tracks[0].devices[1].is_active)
        self.assertEqual(applied["device"], "Glue")
        restored = self.adapter.call("devices.bypass", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertTrue(self.song.tracks[0].devices[1].is_active)

    def test_duplicate_device_names_are_refused(self):
        self.song.tracks[0].devices.append(FakeDevice("EQ Eight"))
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.bypass", {
                "track": "Drums", "device": "EQ Eight", "bypass": True,
            })
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")

    def test_invalid_selections_and_boolean_are_typed(self):
        cases = (
            ({"track": "Drums", "track_index": 0, "device_index": 0, "bypass": True}, "BAD_ARGS"),
            ({"track": "Drums", "device": "EQ Eight", "device_index": 0, "bypass": True}, "BAD_ARGS"),
            ({"track": "Drums"}, "BAD_ARGS"),
            ({"track": "Drums", "device_index": 0, "bypass": "yes"}, "BAD_ARGS"),
            ({"track": "Missing", "device_index": 0, "bypass": True}, "NOT_FOUND"),
            ({"track": "Drums", "device": "Missing", "bypass": True}, "NOT_FOUND"),
            ({"track": "Drums", "device_index": 99, "bypass": True}, "NOT_FOUND"),
        )
        for args, code in cases:
            with self.assertRaises(ScriptError, msg=repr(args)) as ctx:
                self.adapter.call("devices.bypass", args)
            self.assertEqual(ctx.exception.code, code, args)

    def test_a_device_without_an_active_state_is_unavailable(self):
        self.song.tracks[0].devices.append(FakeDevice("Mystery", is_active=None))
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.bypass", {
                "track": "Drums", "device": "Mystery", "bypass": True,
            })
        self.assertEqual(ctx.exception.code, "UNSUPPORTED")
        self.assertIn("is_active", ctx.exception.message)

    def test_restore_rejects_a_selection(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.bypass", {
                "restore": [{"track_index": 0, "device_index": 0, "active": True}],
                "track": "Drums",
            })
        self.assertEqual(ctx.exception.code, "BAD_ARGS")


if __name__ == "__main__":
    unittest.main()

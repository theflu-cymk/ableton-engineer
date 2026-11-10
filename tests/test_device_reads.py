"""Reading a device's parameters: the names a write needs, without guessing indexes."""

import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeDevice, FakeDeviceParameter
from enableton.manifest import load_manifest
from enableton.modes import load_modes

from Enableton.errors import ScriptError


class ParameterReadTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()

    def test_lists_a_parameter_with_its_name_range_and_state(self):
        result = self.adapter.call(
            "devices.read_parameters", {"track": "Drums", "device": "EQ Eight"}
        )
        self.assertEqual(result["total"], 1)
        row = result["items"][0]
        self.assertEqual(row["index"], 0)
        self.assertEqual(row["name"], "Gain")
        self.assertEqual(row["min"], -12.0)
        self.assertEqual(row["max"], 12.0)
        self.assertTrue(row["enabled"])
        self.assertFalse(row["quantised"])

    def test_paging_keeps_each_parameter_index(self):
        device = self.adapter.song.tracks[0].devices[0]
        for number in range(5):
            device.parameters.append(
                FakeDeviceParameter("Band %d" % number, 0.0, 0.0, 1.0)
            )
        result = self.adapter.call("devices.read_parameters", {
            "track": "Drums", "device": "EQ Eight", "offset": 2, "limit": 2,
        })
        self.assertEqual(result["total"], 6)
        self.assertEqual([row["index"] for row in result["items"]], [2, 3])
        self.assertEqual(result["next_offset"], 4)

    def test_an_ambiguous_device_name_is_refused(self):
        self.adapter.song.tracks[0].devices.append(FakeDevice(
            "EQ Eight", "Eq8", parameters=[FakeDeviceParameter("Gain", 0.0, -12.0, 12.0)],
        ))
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "devices.read_parameters", {"track": "Drums", "device": "EQ Eight"}
            )
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")

    def test_unknown_track_and_device_report_not_found(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "devices.read_parameters", {"track": "Missing", "device": "EQ Eight"}
            )
        self.assertEqual(ctx.exception.code, "NOT_FOUND")
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call(
                "devices.read_parameters", {"track": "Drums", "device": "Nope"}
            )
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

    def test_a_read_changes_no_value(self):
        before = self.adapter.song.tracks[0].devices[0].parameters[0].value
        self.adapter.call("devices.read_parameters", {"track": "Drums", "device": "EQ Eight"})
        self.assertEqual(self.adapter.song.tracks[0].devices[0].parameters[0].value, before)


class ParameterReadCatalogueTests(unittest.TestCase):
    def test_declared_read_only_with_its_command(self):
        tool = load_manifest()["devices_read_parameters"]
        self.assertEqual(tool.cmd, "devices.read_parameters")
        self.assertFalse(tool.writes)

    def test_loaded_by_sound_and_inspect(self):
        modes = load_modes(load_manifest())
        self.assertIn("devices_read_parameters", modes.get("sound").tools)
        self.assertIn("devices_read_parameters", modes.get("inspect").tools)
        self.assertLessEqual(len(modes.get("sound").tools), 34)


if __name__ == "__main__":
    unittest.main()

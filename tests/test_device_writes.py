"""Device-chain writes: parameters, macros, order, delete and preset browse.

These run against the fake LOM. Green here means the handlers agree with each other, not that Live
accepts the write; the real gate for each tool is a call on `SCRATCH fortnight` against the build
`doctor` reports.
"""

import unittest

import support  # noqa: F401
from enableton.live.fake import (
    FakeAdapter,
    FakeBrowserItem,
    FakeDevice,
    FakeDeviceParameter,
    build_song,
)
from enableton.manifest import load_manifest
from enableton.modes import load_modes
from enableton.plans.executor import PlanError, PlanExecutor, Step, _clean

from Enableton.errors import ScriptError


NEW_TOOLS = (
    "devices_set_parameter",
    "devices_set_macro",
    "devices_move",
    "devices_delete",
    "devices_browse_presets",
)


class DeviceCatalogueTests(unittest.TestCase):
    def test_every_new_tool_is_declared_with_its_command(self):
        catalogue = load_manifest()
        expected = {
            "devices_set_parameter": "devices.set_parameter",
            "devices_set_macro": "devices.set_macro",
            "devices_move": "devices.move",
            "devices_delete": "devices.delete",
            "devices_browse_presets": "devices.browse_presets",
        }
        for name, cmd in expected.items():
            self.assertIn(name, catalogue)
            self.assertEqual(catalogue[name].cmd, cmd)

    def test_delete_is_irreversible_and_the_others_are_not(self):
        catalogue = load_manifest()
        self.assertTrue(catalogue["devices_delete"].writes)
        self.assertFalse(catalogue["devices_delete"].reversible)
        for name in ("devices_set_parameter", "devices_set_macro", "devices_move"):
            self.assertTrue(catalogue[name].writes)
            self.assertTrue(catalogue[name].reversible)
        self.assertFalse(catalogue["devices_browse_presets"].writes)

    def test_sound_mode_loads_them_and_mix_can_set_a_parameter(self):
        modes = load_modes(load_manifest())
        sound = modes.get("sound").tools
        for name in NEW_TOOLS:
            self.assertIn(name, sound)
        self.assertIn("devices_set_parameter", modes.get("mix").tools)
        self.assertLessEqual(len(sound), 34)


class ParameterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.song = self.adapter.song
        self.gain = self.song.tracks[0].devices[0].parameters[0]

    def test_dry_run_reports_the_change_without_writing(self):
        result = self.adapter.call("devices.set_parameter", {
            "track": "Drums", "device": "EQ Eight", "parameter": "Gain", "value": -6.0,
        })
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["changes"][0]["from"], 0.0)
        self.assertEqual(result["changes"][0]["to"], -6.0)
        self.assertEqual(result["undo"][0]["value"], 0.0)
        self.assertEqual(self.gain.value, 0.0)

    def test_apply_and_restore_round_trip(self):
        result = self.adapter.call("devices.set_parameter", {
            "track": "Drums", "device": "EQ Eight", "parameter": "Gain",
            "value": -6.0, "dry_run": False,
        })
        self.assertAlmostEqual(self.gain.value, -6.0)
        self.assertAlmostEqual(result["changes"][0]["to"], -6.0)

        self.adapter.call("devices.set_parameter", {
            "restore": result["undo"], "dry_run": False,
        })
        self.assertAlmostEqual(self.gain.value, 0.0)

    def test_value_outside_the_parameter_range_is_refused(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.set_parameter", {
                "track": "Drums", "device": "EQ Eight", "parameter": "Gain", "value": 30.0,
            })
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertEqual(self.gain.value, 0.0)

    def test_a_disabled_parameter_is_refused(self):
        self.gain.is_enabled = False
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.set_parameter", {
                "track": "Drums", "device": "EQ Eight", "parameter": "Gain", "value": 1.0,
            })
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")

    def test_an_ambiguous_device_name_is_refused_not_guessed(self):
        self.song.tracks[0].devices.append(FakeDevice(
            "EQ Eight", "Eq8",
            parameters=[FakeDeviceParameter("Gain", 0.0, -12.0, 12.0)],
        ))
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.set_parameter", {
                "track": "Drums", "device": "EQ Eight", "parameter": "Gain", "value": 1.0,
            })
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")

    def test_unknown_parameter_and_track_report_not_found(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.set_parameter", {
                "track": "Drums", "device": "EQ Eight", "parameter": "Nope", "value": 1.0,
            })
        self.assertEqual(ctx.exception.code, "NOT_FOUND")
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.set_parameter", {
                "track": "Missing", "device": "EQ Eight", "parameter": "Gain", "value": 1.0,
            })
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

    def test_a_quantised_parameter_snaps_before_the_write(self):
        # Live stores a quantised parameter as an index, so 1.6 on a three-way switch is step 2.
        self.song.tracks[0].devices[0].parameters.append(FakeDeviceParameter(
            "Mode", 0.0, 0.0, 2.0, is_quantized=True, value_items=["Off", "A", "B"],
        ))
        result = self.adapter.call("devices.set_parameter", {
            "track": "Drums", "device": "EQ Eight", "parameter": "Mode", "value": 1.6,
        })
        self.assertEqual(result["changes"][0]["to"], 2.0)

    def test_both_track_and_track_index_is_an_argument_error(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.set_parameter", {
                "track": "Drums", "track_index": 0,
                "device": "EQ Eight", "parameter": "Gain", "value": 1.0,
            })
        self.assertEqual(ctx.exception.code, "BAD_ARGS")


class MacroTests(unittest.TestCase):
    def make_rack(self, *parameters):
        song = build_song()
        song.tracks[0].devices.append(FakeDevice(
            "Instrument Rack", "InstrumentGroupDevice", parameters=list(parameters)
        ))
        return FakeAdapter(song)

    def test_macro_write_and_restore(self):
        adapter = self.make_rack(
            FakeDeviceParameter("Device On", 1.0, 0.0, 1.0),
            FakeDeviceParameter("Low Gain", 0.0, 0.0, 1.0),
        )
        result = adapter.call("devices.set_macro", {
            "track": "Drums", "device": "Instrument Rack", "macro": 1,
            "value": 0.5, "dry_run": False,
        })
        parameter = adapter.song.tracks[0].devices[-1].parameters[1]
        self.assertAlmostEqual(parameter.value, 0.5)
        adapter.call("devices.set_macro", {"restore": result["undo"], "dry_run": False})
        self.assertAlmostEqual(parameter.value, 0.0)

    def test_a_renamed_macro_resolves_by_position(self):
        # Live reports the user's macro name, not "Macro 1"; the real rack exposed Low Gain at the
        # index Macro 1 occupies.
        adapter = self.make_rack(
            FakeDeviceParameter("Device On", 1.0, 0.0, 1.0),
            FakeDeviceParameter("Low Gain", 0.0, 0.0, 1.0),
        )
        result = adapter.call("devices.set_macro", {
            "track": "Drums", "device": "Instrument Rack", "macro": 1, "value": 0.25,
        })
        self.assertEqual(result["changes"][0]["parameter"], "Low Gain")
        self.assertEqual(result["changes"][0]["parameter_index"], 1)

    def test_a_device_without_macros_reports_why(self):
        adapter = FakeAdapter()
        with self.assertRaises(ScriptError) as ctx:
            adapter.call("devices.set_macro", {
                "track": "Drums", "device": "EQ Eight", "macro": 1, "value": 0.5,
            })
        self.assertEqual(ctx.exception.code, "UNSUPPORTED")
        self.assertIn("racks only", str(ctx.exception))

    def test_macro_number_is_bounded(self):
        adapter = self.make_rack(
            FakeDeviceParameter("Device On", 1.0, 0.0, 1.0),
            FakeDeviceParameter("Low Gain", 0.0, 0.0, 1.0),
        )
        with self.assertRaises(ScriptError) as ctx:
            adapter.call("devices.set_macro", {
                "track": "Drums", "device": "Instrument Rack", "macro": 17, "value": 0.5,
            })
        self.assertEqual(ctx.exception.code, "BAD_ARGS")


class _NoMoveTrack:
    """A track proxy without Track.move_device, like Live 12.2.5."""

    def __init__(self, track):
        object.__setattr__(self, "_track", track)

    def __getattr__(self, name):
        if name == "move_device":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_track"), name)


class MoveTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.track = self.adapter.song.tracks[0]

    def test_move_reorders_and_restores(self):
        self.assertEqual([device.name for device in self.track.devices], ["EQ Eight", "Glue"])
        result = self.adapter.call("devices.move", {
            "track": "Drums", "device": "EQ Eight", "to_index": 1, "dry_run": False,
        })
        self.assertEqual(result["changes"][0]["from_index"], 0)
        self.assertEqual(result["changes"][0]["to_index"], 1)
        self.assertEqual([device.name for device in self.track.devices], ["Glue", "EQ Eight"])

        self.adapter.call("devices.move", {"restore": result["undo"], "dry_run": False})
        self.assertEqual([device.name for device in self.track.devices], ["EQ Eight", "Glue"])

    def test_dry_run_does_not_reorder(self):
        self.adapter.call("devices.move", {"track": "Drums", "device": "Glue", "to_index": 0})
        self.assertEqual([device.name for device in self.track.devices], ["EQ Eight", "Glue"])

    def test_out_of_range_index_is_refused(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.move", {
                "track": "Drums", "device": "Glue", "to_index": 2,
            })
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_moving_to_the_same_index_is_a_no_op(self):
        result = self.adapter.call("devices.move", {
            "track": "Drums", "device": "Glue", "to_index": 1,
        })
        self.assertEqual(result["changes"][0]["from_index"], 1)
        self.assertEqual(result["changes"][0]["to_index"], 1)
        self.assertEqual(result["undo"], [])

    def test_the_song_level_mover_is_used_when_the_track_has_none(self):
        adapter = FakeAdapter()
        adapter.song.tracks[0] = _NoMoveTrack(adapter.song.tracks[0])
        adapter.call("devices.move", {
            "track": "Drums", "device": "EQ Eight", "to_index": 1, "dry_run": False,
        })
        self.assertEqual(
            [device.name for device in adapter.song.tracks[0].devices], ["Glue", "EQ Eight"]
        )


class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.track = self.adapter.song.tracks[0]

    def test_dry_run_previews_and_requires_confirmation(self):
        result = self.adapter.call("devices.delete", {"track": "Drums", "device": "Glue"})
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["requires_confirm"])
        self.assertFalse(result["reversible"])
        self.assertEqual(len(self.track.devices), 2)

    def test_apply_without_confirm_is_refused(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.delete", {
                "track": "Drums", "device": "Glue", "dry_run": False,
            })
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertEqual(len(self.track.devices), 2)

    def test_a_refused_delete_reports_its_own_code(self):
        outcome = PlanExecutor(FakeAdapter(), scratch=_StubScratch()).apply([
            Step("devices_delete", {"track": "Drums", "device": "Glue"}),
        ])
        self.assertFalse(outcome["applied"])
        self.assertEqual(outcome["error"]["code"], "PRECONDITION_FAILED")

    def test_apply_with_confirm_removes_one_device(self):
        result = self.adapter.call("devices.delete", {
            "track": "Drums", "device": "Glue", "confirm": True, "dry_run": False,
        })
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["count"], 1)
        self.assertEqual([device.name for device in self.track.devices], ["EQ Eight"])

    def test_an_irreversible_delete_cannot_join_a_multi_step_plan(self):
        executor = PlanExecutor(self.adapter)
        with self.assertRaises(PlanError) as ctx:
            executor.run([
                Step("devices_delete", {"track": "Drums", "device": "Glue", "confirm": True}),
                Step("tracks_set_volume", {"tracks": ["Drums"], "volume": 0.5}),
            ])
        self.assertIn("cannot be undone", str(ctx.exception))

    def test_a_single_step_delete_still_resolves(self):
        executor = PlanExecutor(self.adapter)
        trace = executor.run([
            Step("devices_delete", {"track": "Drums", "device": "Glue", "confirm": True}),
        ])
        self.assertTrue(trace["dry_run"])
        self.assertEqual(len(self.track.devices), 2)


class BrowsePresetTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()

    def test_lists_device_folders_across_categories(self):
        result = self.adapter.call("devices.browse_presets", {})
        names = [row["name"] for row in result["items"]]
        self.assertIn("Analog", names)
        self.assertIn("EQ Eight", names)
        eq_eight = next(row for row in result["items"] if row["name"] == "EQ Eight")
        self.assertEqual(eq_eight["category"], "audio_effects")
        self.assertEqual(eq_eight["child_count"], 1)

    def test_one_device_lists_its_presets(self):
        result = self.adapter.call("devices.browse_presets", {"device": "EQ Eight"})
        self.assertEqual([row["name"] for row in result["items"]], ["Vocal EQ.adv"])
        self.assertEqual(result["items"][0]["uri"], "file:Vocal EQ.adv")

    def test_an_unknown_device_is_not_found(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.browse_presets", {"device": "Nebula"})
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

    def test_an_unknown_category_is_refused(self):
        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("devices.browse_presets", {"category": "samples"})
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_a_device_past_the_old_eight_folder_cap_is_found(self):
        # The real browser puts EQ Eight well past the eighth audio-effect folder.
        song = build_song()
        song.browser.audio_effects.children = [
            FakeBrowserItem("Filler %02d" % index, True, False, "query:x")
            for index in range(12)
        ] + [FakeBrowserItem("EQ Eight", False, False, "query:AudioEffects#EQ Eight", [
            FakeBrowserItem("Vocal EQ.adv", False, True, "file:Vocal EQ.adv"),
        ])]
        result = FakeAdapter(song).call("devices.browse_presets", {"device": "EQ Eight"})
        self.assertEqual([row["name"] for row in result["items"]], ["Vocal EQ.adv"])

    def test_a_device_folder_live_marks_as_not_a_folder_is_still_found(self):
        # Live's browser reports is_folder False for a device's preset folder, because the folder
        # holds presets rather than more folders; the default fake now matches that.
        result = self.adapter.call("devices.browse_presets", {"device": "EQ Eight"})
        self.assertEqual(result["total"], 1)

    def test_the_same_device_folder_in_two_categories_is_ambiguous(self):
        song = build_song()
        song.browser.midi_effects.children = [FakeBrowserItem(
            "EQ Eight", False, False, "query:MidiEffects#EQ Eight",
            [FakeBrowserItem("MIDI EQ.adv", False, True, "file:MIDI EQ.adv")],
        )]
        with self.assertRaises(ScriptError) as ctx:
            FakeAdapter(song).call("devices.browse_presets", {"device": "EQ Eight"})
        self.assertEqual(ctx.exception.code, "AMBIGUOUS_REF")

    def test_the_folder_list_pages_past_the_old_cap(self):
        song = build_song()
        song.browser.audio_effects.children = [
            FakeBrowserItem("FX %02d" % index, True, False, "query:x") for index in range(20)
        ]
        adapter = FakeAdapter(song)
        first = adapter.call(
            "devices.browse_presets", {"category": "audio_effects", "limit": 5}
        )
        self.assertEqual(first["total"], 20)
        self.assertEqual(first["next_offset"], 5)

        last = adapter.call("devices.browse_presets", {
            "category": "audio_effects", "offset": 15, "limit": 5,
        })
        self.assertEqual(len(last["items"]), 5)
        self.assertIsNone(last["next_offset"])


class TraceShapeTests(unittest.TestCase):
    """The transactional path compares an applied result to its own preflight, field for field."""

    def test_parameter_write_payload_is_the_same_in_both_modes(self):
        adapter = FakeAdapter()
        args = {"track": "Drums", "device": "EQ Eight", "parameter": "Gain", "value": -4.0}
        self.assertEqual(
            _clean(adapter.call("devices.set_parameter", args)),
            _clean(adapter.call("devices.set_parameter", dict(args, dry_run=False))),
        )

    def test_macro_write_payload_is_the_same_in_both_modes(self):
        song = build_song()
        song.tracks[0].devices.append(FakeDevice(
            "Instrument Rack", "InstrumentGroupDevice",
            parameters=[
                FakeDeviceParameter("Device On", 1.0, 0.0, 1.0),
                FakeDeviceParameter("Drive", 0.0, 0.0, 1.0),
            ],
        ))
        adapter = FakeAdapter(song)
        args = {"track": "Drums", "device": "Instrument Rack", "macro": 1, "value": 0.5}
        self.assertEqual(
            _clean(adapter.call("devices.set_macro", args)),
            _clean(adapter.call("devices.set_macro", dict(args, dry_run=False))),
        )

    def test_move_payload_is_the_same_in_both_modes(self):
        adapter = FakeAdapter()
        args = {"track": "Drums", "device": "EQ Eight", "to_index": 1}
        self.assertEqual(
            _clean(adapter.call("devices.move", args)),
            _clean(adapter.call("devices.move", dict(args, dry_run=False))),
        )

    def test_delete_payload_is_the_same_in_both_modes(self):
        adapter = FakeAdapter()
        args = {"track": "Drums", "device": "Glue", "confirm": True}
        self.assertEqual(
            _clean(adapter.call("devices.delete", args)),
            _clean(adapter.call("devices.delete", dict(args, dry_run=False))),
        )


class _StubScratch:
    def ensure(self):
        return "scratch.als"


class TransactionTests(unittest.TestCase):
    """A single write must survive the executor's preflight-versus-applied comparison."""

    def test_a_parameter_write_applies_through_the_executor(self):
        adapter = FakeAdapter()
        outcome = PlanExecutor(adapter, scratch=_StubScratch()).apply([
            Step("devices_set_parameter", {
                "track": "Drums", "device": "EQ Eight", "parameter": "Gain", "value": -6.0,
            }),
        ])
        self.assertTrue(outcome["applied"])
        self.assertAlmostEqual(adapter.song.tracks[0].devices[0].parameters[0].value, -6.0)

    def test_a_move_applies_through_the_executor(self):
        adapter = FakeAdapter()
        outcome = PlanExecutor(adapter, scratch=_StubScratch()).apply([
            Step("devices_move", {"track": "Drums", "device": "EQ Eight", "to_index": 1}),
        ])
        self.assertTrue(outcome["applied"])
        self.assertEqual(
            [device.name for device in adapter.song.tracks[0].devices], ["Glue", "EQ Eight"]
        )

    def test_a_confirmed_delete_applies_through_the_executor(self):
        adapter = FakeAdapter()
        outcome = PlanExecutor(adapter, scratch=_StubScratch()).apply([
            Step("devices_delete", {"track": "Drums", "device": "Glue", "confirm": True}),
        ])
        self.assertTrue(outcome["applied"])
        self.assertEqual([device.name for device in adapter.song.tracks[0].devices], ["EQ Eight"])


if __name__ == "__main__":
    unittest.main()

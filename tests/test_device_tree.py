"""Device trees and locator readability, exercised against the handler itself.

The fake backend gives every track one flat device, which is why a Set holding 22 group devices
read as 18 top-level devices for a whole session without a single failure. These tests put a rack
in front of the handler so nesting is exercised even while the fake stays flat.
"""

import unittest

import support  # noqa: F401
from Enableton.handlers import structure as handler


class Obj:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def make_song(tracks=(), **extra):
    fields = dict(
        name="set",
        tempo=120.0,
        signature_numerator=4,
        signature_denominator=4,
        is_playing=False,
        current_song_time=0.0,
        loop_start=0.0,
        loop_length=0.0,
        loop=False,
        tracks=list(tracks),
        return_tracks=[],
        scenes=[],
        locators=[],
    )
    fields.update(extra)
    return Obj(**fields)


def make_track(name="Track", devices=(), **extra):
    fields = dict(
        name=name,
        is_foldable=False,
        has_midi_input=True,
        devices=list(devices),
        clip_slots=[],
        arrangement_clips=[],
    )
    fields.update(extra)
    return Obj(**fields)


def make_device(class_name, name=None, chains=None, **extra):
    fields = dict(class_name=class_name, name=name or class_name, is_active=True)
    if chains is not None:
        fields["chains"] = [Obj(devices=list(chain)) for chain in chains]
    fields.update(extra)
    return Obj(**fields)


class DeviceTreeTests(unittest.TestCase):
    def test_a_rack_reports_the_devices_inside_it(self):
        rack = make_device("InstrumentGroupDevice", "Rack", chains=[[make_device("Eq8", "EQ")]])
        data = handler.snapshot(
            {}, make_song([make_track(devices=[rack, make_device("Compressor2", "Glue")])])
        )
        row = data["tracks"][0]
        self.assertEqual(row["devices"][0]["chains"][0][0]["name"], "EQ")
        self.assertEqual(row["devices"][0]["chains"][0][0]["depth"], 1)
        self.assertEqual(row["device_count"], 3)
        self.assertEqual(data["counts"]["devices"], 2, "the top-level count keeps its meaning")
        self.assertEqual(data["counts"]["devices_total"], 3)

    def test_nesting_stops_at_the_cap_and_says_so(self):
        level = make_device("Eq8", "deep")
        for _ in range(handler.MAX_DEVICE_DEPTH + 2):
            level = make_device("InstrumentGroupDevice", "Rack", chains=[[level]])
        row = handler.snapshot({}, make_song([make_track(devices=[level])]))["tracks"][0]["devices"][0]

        def truncated(node):
            if node.get("truncated"):
                return True
            return any(truncated(child) for chain in node.get("chains") or [] for child in chain)

        self.assertTrue(truncated(row), "a capped tree must never look complete")

    def test_plugins_are_flagged_at_any_depth(self):
        rack = make_device(
            "AudioEffectGroupDevice", "Chain", chains=[[make_device("VstPluginDevice", "Serum")]]
        )
        row = handler.snapshot({}, make_song([make_track(devices=[rack])]))["tracks"][0]
        self.assertTrue(row["devices"][0]["chains"][0][0]["plugin"])

    def test_a_flat_track_is_unchanged(self):
        data = handler.snapshot({}, make_song([make_track(devices=[make_device("Eq8", "EQ")])]))
        row = data["tracks"][0]
        self.assertNotIn("chains", row["devices"][0])
        self.assertEqual(row["device_count"], 1)
        self.assertEqual(data["counts"]["devices"], data["counts"]["devices_total"])


class MasterChainTests(unittest.TestCase):
    def test_master_devices_are_part_of_the_set(self):
        rack = make_device("AudioEffectGroupDevice", "Master rack", chains=[[make_device("Limiter", "Lim")]])
        data = handler.snapshot({}, make_song(master_track=Obj(devices=[rack, make_device("Eq8", "EQ")])))
        self.assertEqual(data["master_track"]["device_count"], 3)
        self.assertEqual(data["counts"]["devices_master"], 3)
        self.assertEqual(data["counts"]["devices_total"], 3, "this Set has no track devices")
        self.assertTrue(data["captured"]["master_available"])

    def test_a_missing_master_is_reported_with_a_reason(self):
        class _NoMaster:
            def __init__(self, fields):
                self.__dict__.update(fields)

            @property
            def master_track(self):
                raise RuntimeError("not exposed")

        song = _NoMaster(make_song().__dict__)
        data = handler.snapshot({}, song)
        self.assertEqual(data["counts"]["devices_master"], 0)
        self.assertFalse(data["captured"]["master_available"])
        self.assertIn("master_track: RuntimeError: not exposed", data["captured"]["master_reason"])


class _NoLocators:
    """A Song whose locator attributes raise, as an unsupported build would."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    @property
    def locators(self):
        raise RuntimeError("attribute not readable")

    @property
    def cue_points(self):
        raise RuntimeError("attribute not readable")


class LocatorReadabilityTests(unittest.TestCase):
    def test_the_attribute_that_answered_is_recorded(self):
        captured = handler.snapshot({}, make_song())["captured"]
        self.assertTrue(captured["locators_available"])
        self.assertEqual(captured["locators_attribute"], "locators")
        self.assertIsNone(captured["locators_reason"])

    def test_cue_points_answers_when_locators_is_absent(self):
        song = make_song()
        del song.locators
        song.cue_points = []
        captured = handler.snapshot({}, song)["captured"]
        self.assertTrue(captured["locators_available"])
        self.assertEqual(captured["locators_attribute"], "cue_points")

    def test_an_unreadable_list_carries_the_reason(self):
        fields = {k: v for k, v in make_song().__dict__.items() if k != "locators"}
        captured = handler.snapshot({}, _NoLocators(**fields))["captured"]
        self.assertFalse(captured["locators_available"])
        self.assertIsNone(captured["locators_attribute"])
        self.assertIn("locators: RuntimeError: attribute not readable", captured["locators_reason"])
        self.assertIn("cue_points: RuntimeError", captured["locators_reason"])

    def test_a_present_but_empty_list_is_not_unavailable(self):
        captured = handler.snapshot({}, make_song(locators=[]))["captured"]
        self.assertTrue(captured["locators_available"], "an empty list is an answer, not a failure")


if __name__ == "__main__":
    unittest.main()

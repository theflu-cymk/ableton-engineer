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


def make_clip(**extra):
    fields = dict(
        name="clip",
        start_time=0.0,
        end_time=4.0,
        is_midi_clip=False,
        warping=True,
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


class WarpFieldTests(unittest.TestCase):
    def test_an_audio_clip_carries_its_warp_state(self):
        clip = make_clip(warp_mode=4, warp_markers=[Obj(), Obj(), Obj()])
        data = handler.snapshot({}, make_song([make_track(arrangement_clips=[clip])]))
        row = data["tracks"][0]["arrangement"][0]

        self.assertTrue(row["warping"])
        self.assertEqual(row["warp_mode"], 4)
        self.assertEqual(row["warp_mode_name"], "complex")
        self.assertEqual(row["warp_markers"], 3)
        self.assertEqual(data["counts"]["warp_markers"], 3)
        self.assertEqual(data["counts"]["warp_markers_unreadable"], 0)

    def test_a_session_audio_clip_carries_the_same_fields(self):
        clip = make_clip(name="loop", warp_mode=0, warp_markers=[Obj(), Obj()])
        track = make_track(clip_slots=[Obj(clip=clip)])
        data = handler.snapshot({}, make_song([track]))
        row = data["tracks"][0]["session"]["clips"][0]

        self.assertEqual(row["warp_mode"], 0)
        self.assertEqual(row["warp_mode_name"], "beats")
        self.assertEqual(row["warp_markers"], 2)
        self.assertEqual(data["counts"]["warp_markers"], 2)

    def test_midi_clips_have_no_warp_fields(self):
        clip = make_clip(is_midi_clip=True, warping=True)
        data = handler.snapshot({}, make_song([make_track(arrangement_clips=[clip])]))
        row = data["tracks"][0]["arrangement"][0]

        self.assertNotIn("warp_mode", row)
        self.assertNotIn("warp_markers", row)
        self.assertNotIn("warping", row)
        self.assertEqual(data["counts"]["warp_markers"], 0)

    def test_every_documented_warp_mode_has_a_name(self):
        expected = {
            0: "beats", 1: "tones", 2: "texture", 3: "re-pitch",
            4: "complex", 5: "rex", 6: "complex_pro",
        }
        for mode, name in expected.items():
            with self.subTest(mode=mode):
                clip = make_clip(warp_mode=mode, warp_markers=[Obj(), Obj()])
                data = handler.snapshot({}, make_song([make_track(arrangement_clips=[clip])]))
                row = data["tracks"][0]["arrangement"][0]
                self.assertEqual(row["warp_mode"], mode)
                self.assertEqual(row["warp_mode_name"], name)

    def test_an_unreadable_marker_vector_is_not_zero(self):
        class _UnreadableClip(Obj):
            @property
            def warp_markers(self):
                raise RuntimeError("no marker vector")

        clip = _UnreadableClip(
            name="broken", start_time=0.0, end_time=4.0,
            is_midi_clip=False, warping=True, warp_mode=2,
        )
        data = handler.snapshot({}, make_song([make_track(arrangement_clips=[clip])]))
        row = data["tracks"][0]["arrangement"][0]

        self.assertIsNone(row["warp_markers"])
        self.assertIn("no marker vector", row["warp_markers_reason"])
        self.assertEqual(data["counts"]["warp_markers"], 0)
        self.assertEqual(data["counts"]["warp_markers_unreadable"], 1)


class NoteOverlapTests(unittest.TestCase):
    def test_same_pitch_overlap_is_captured_but_a_chord_is_not(self):
        clip = make_clip(
            is_midi_clip=True,
            notes=[
                Obj(pitch=60, start_time=0.0, duration=1.0, velocity=100),
                Obj(pitch=60, start_time=0.5, duration=1.0, velocity=90),
                Obj(pitch=64, start_time=0.0, duration=1.0, velocity=80),
            ],
        )
        data = handler.snapshot({}, make_song([make_track(arrangement_clips=[clip])]))
        row = data["tracks"][0]["arrangement"][0]

        self.assertTrue(data["captured"]["notes_available"])
        self.assertEqual(row["note_count"], 3)
        self.assertEqual(len(row["note_overlaps"]), 1)
        pair = row["note_overlaps"][0]
        self.assertEqual(pair["pitch"], 60)
        self.assertEqual(pair["overlap"], 0.5)
        self.assertEqual(data["counts"]["notes_read"], 3)
        self.assertEqual(data["counts"]["note_overlaps"], 1)

    def test_adjacent_notes_do_not_overlap(self):
        clip = make_clip(
            is_midi_clip=True,
            notes=[
                Obj(pitch=60, start_time=0.0, duration=1.0),
                Obj(pitch=60, start_time=1.0, duration=1.0),
            ],
        )
        row = handler.snapshot({}, make_song([make_track(arrangement_clips=[clip])]))["tracks"][0]["arrangement"][0]

        self.assertEqual(row["note_count"], 2)
        self.assertEqual(row["note_overlaps"], [])

    def test_a_session_midi_clip_carries_the_same_data(self):
        clip = make_clip(
            name="session notes",
            is_midi_clip=True,
            notes=[Obj(pitch=36, start_time=0.0, duration=2.0),
                   Obj(pitch=36, start_time=1.0, duration=2.0)],
        )
        data = handler.snapshot({}, make_song([make_track(clip_slots=[Obj(clip=clip)])]))
        row = data["tracks"][0]["session"]["clips"][0]

        self.assertEqual(row["note_count"], 2)
        self.assertEqual(len(row["note_overlaps"]), 1)

    def test_an_unreadable_note_vector_is_not_zero(self):
        class _UnreadableNotes(Obj):
            @property
            def notes(self):
                raise RuntimeError("no note vector")

        clip = _UnreadableNotes(
            name="broken notes", start_time=0.0, end_time=4.0, is_midi_clip=True,
        )
        data = handler.snapshot({}, make_song([make_track(arrangement_clips=[clip])]))
        row = data["tracks"][0]["arrangement"][0]

        self.assertIsNone(row["note_count"])
        self.assertIn("no note vector", row["note_overlaps_reason"])
        self.assertEqual(data["counts"]["notes_unreadable"], 1)

    def test_the_capture_budget_marks_truncation(self):
        from unittest import mock

        clip = make_clip(
            is_midi_clip=True,
            notes=[Obj(pitch=60, start_time=0.0, duration=1.0),
                   Obj(pitch=60, start_time=0.5, duration=1.0)],
        )
        with mock.patch.object(handler, "MAX_NOTE_OVERLAPS_TOTAL", 0):
            data = handler.snapshot({}, make_song([make_track(arrangement_clips=[clip])]))
        row = data["tracks"][0]["arrangement"][0]

        self.assertTrue(row["note_overlaps_truncated"])
        self.assertEqual(row["note_overlaps"], [])
        self.assertEqual(data["counts"]["note_overlaps_truncated"], 1)


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

"""Style recipes write their audition phrase into a real track, or name the exact blocker.

A style recipe has no MIDI lanes. Its ``audition`` block is the short phrase that makes the patch
audible; the compiler must resolve the ingredient's role to an existing MIDI track (explicit
target, ``track_bindings`` or a device match in the snapshot) and write it through the normal plan.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from enableton.escalation import apply_plan
from enableton.live.fake import FakeAdapter, FakeDevice, FakeDeviceParameter
from enableton.manifest import load_manifest
from enableton.plans import PlanStore
from enableton.recipe_store import RecipeStore
from enableton.recipe_tools import apply_recipe, default_store, save_recipe
from enableton.state.snapshot import SnapshotCache

FLAGSHIPS = {
    "dubstep.wobble_operator": 4,
    "riddim.triplet_operator": 6,
    "deathstep.growl_operator": 6,
    "tearout.siren_lead": 4,
}

CLIP_TARGET = {"track": "Drums", "clip": "drums A", "location": "session"}


class StyleAuditionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(os.environ.pop, "APPDATA", None)
        os.environ["APPDATA"] = os.path.join(self.temp.name, "appdata")
        self.store = default_store()
        self.adapter = FakeAdapter()
        path = os.path.join(self.temp.name, "scratch.als")
        Path(path).write_bytes(b"scratch")
        self.adapter.song.file_path = path
        self.cache = SnapshotCache(self.adapter)
        self.catalogue = load_manifest()
        self.plan_root = os.path.join(self.temp.name, "plans")

    def _compile(self, recipe_id, **args):
        return apply_recipe(
            {"id": recipe_id, "manual_confirmed": True, **args},
            store=self.store,
            adapter=self.adapter,
            cache=self.cache,
            plan_root=self.plan_root,
            catalogue=self.catalogue,
        )

    def _apply(self, plan):
        return apply_plan(
            self.adapter,
            self.cache,
            {"plan_id": plan["plan_id"]},
            PlanStore(root=self.plan_root),
            self.catalogue,
            os.path.join(self.temp.name, "backups"),
        )

    def _drum_clip(self):
        return self.adapter.song.tracks[0].clip_slots[0].clip

    def test_each_style_flaghsip_writes_its_audition_phrase(self):
        for recipe_id, expected in FLAGSHIPS.items():
            with self.subTest(recipe=recipe_id):
                plan = self._compile(recipe_id, target=dict(CLIP_TARGET))
                self.assertEqual(plan["status"], "plan_ready", plan.get("reason"))
                render = plan["render"]
                self.assertEqual(render["strategy"], "audition")
                self.assertEqual(render["resolved_by"], "target")
                self.assertEqual(render["track"], "Drums")
                self.assertEqual(render["note_count"], expected)
                self.assertEqual(len(render["notes"]), expected)
                self.assertEqual(
                    [step["tool"] for step in plan["steps"]], ["notes_replace"]
                )
                self.assertEqual(
                    plan["steps"][0]["args"]["notes"], render["notes"]
                )

                applied = self._apply(plan)
                self.assertTrue(applied.get("applied"), applied)

                notes = sorted(
                    self._drum_clip().notes, key=lambda note: (note.start_time, note.pitch)
                )
                self.assertEqual(len(notes), expected)
                self.assertEqual(
                    [round(note.start_time, 6) for note in notes],
                    [note["start"] for note in render["notes"]],
                )
                self.assertEqual(
                    [note.pitch for note in notes],
                    [note["pitch"] for note in render["notes"]],
                )

    def test_a_binding_names_the_track_for_the_audition_role(self):
        plan = self._compile(
            "dubstep.wobble_operator",
            target={"clip": "drums A", "location": "session"},
            track_bindings={"synth": "Drums"},
        )
        self.assertEqual(plan["status"], "plan_ready", plan.get("reason"))
        self.assertEqual(plan["render"]["resolved_by"], "binding")
        self.assertEqual(plan["render"]["track"], "Drums")
        self.assertTrue(self._apply(plan).get("applied"))
        self.assertEqual(len(self._drum_clip().notes), 4)

    def test_a_device_in_the_set_resolves_the_role(self):
        self.adapter.song.tracks[0].devices.append(FakeDevice("Operator", "Operator"))
        plan = self._compile(
            "dubstep.wobble_operator",
            target={"clip": "drums A", "location": "session"},
        )
        self.assertEqual(plan["status"], "plan_ready", plan.get("reason"))
        self.assertEqual(plan["render"]["resolved_by"], "device")
        self.assertEqual(plan["render"]["track"], "Drums")

    def test_ambiguous_device_matches_name_the_candidates(self):
        self.adapter.song.tracks[0].devices.append(FakeDevice("Operator", "Operator"))
        self.adapter.song.tracks[1].is_midi = True
        self.adapter.song.tracks[1].devices.append(FakeDevice("Operator", "Operator"))
        plan = self._compile(
            "dubstep.wobble_operator",
            target={"clip": "drums A", "location": "session"},
        )
        self.assertEqual(plan["status"], "unavailable")
        reason = plan["reason"]
        self.assertIn("Drums", reason)
        self.assertIn("Bass layer", reason)
        self.assertIn("--binding synth=<track>", reason)

    def test_an_unresolvable_role_names_the_ingredient_and_the_binding(self):
        plan = self._compile(
            "deathstep.growl_operator",
            target={"clip": "drums A", "location": "session"},
        )
        self.assertEqual(plan["status"], "unavailable")
        self.assertIn("ingredient 'synth'", plan["reason"])
        self.assertIn("'Ableton Operator'", plan["reason"])
        self.assertIn("--binding synth=<track>", plan["reason"])

    def test_a_step_that_needs_an_unbound_role_names_step_and_ingredient(self):
        recipe = {
            "id": "test.role_step",
            "name": "Role step probe",
            "version": 1,
            "kind": "style",
            "status": "draft",
            "ingredients": [
                {"role": "synth", "kind": "instrument", "source": "Ableton Operator"}
            ],
            "steps": [
                {
                    "tool": "devices_set_parameter",
                    "args": {
                        "track": "synth",
                        "device": "Operator",
                        "parameter": "Coarse",
                        "value": 0,
                    },
                }
            ],
        }
        save_recipe({"recipe": recipe}, store=self.store)

        plan = self._compile("test.role_step")
        self.assertEqual(plan["status"], "unavailable")
        self.assertIn("step 1 (devices_set_parameter)", plan["reason"])
        self.assertIn("ingredient 'synth' (instrument, 'Ableton Operator')", plan["reason"])
        self.assertIn("--binding synth=<track>", plan["reason"])

        # With the role bound to a track that really carries the device, the same recipe compiles.
        self.adapter.song.tracks[0].devices.append(
            FakeDevice(
                "Operator",
                "Operator",
                parameters=[FakeDeviceParameter("Coarse", 0.0, -48.0, 48.0)],
            )
        )
        bound = self._compile("test.role_step", track_bindings={"synth": "Drums"})
        self.assertEqual(bound["status"], "plan_ready", bound.get("reason"))
        self.assertEqual(bound["steps"][0]["args"]["track"], "Drums")

    def test_a_recipe_with_no_write_path_names_the_step_op_and_entity(self):
        plan = self._compile("bass_music.mix_chain")
        self.assertEqual(plan["status"], "unavailable")
        reason = plan["reason"]
        self.assertIn("cannot run any step", reason)
        self.assertIn("step 1", reason)
        self.assertIn("devices_load", reason)
        self.assertIn("ingredient 'mono' (instrument, 'Utility')", reason)
        self.assertIn("--binding mono=<track>", reason)

    def test_a_sample_recipe_names_the_missing_sample_operation(self):
        plan = self._compile("tearout.gun_click")
        self.assertEqual(plan["status"], "unavailable")
        reason = plan["reason"]
        self.assertIn("step 1", reason)
        self.assertIn("sample-loading operation", reason)
        self.assertIn("ingredient 'click' (sample, 'Short percussion or noise')", reason)
        self.assertIn("--binding click=<track>", reason)

    def _seed_processing_devices(self):
        self.adapter.song.tracks[1].devices = [
            FakeDevice(
                "Multiband Dynamics", "Multiband Dynamics",
                parameters=[FakeDeviceParameter("Amount", 0.2, 0.0, 1.0)],
            ),
            FakeDevice(
                "Saturator", "Saturator",
                parameters=[
                    FakeDeviceParameter("Drive", 0.0, 0.0, 36.0),
                    FakeDeviceParameter("Dry/Wet", 0.5, 0.0, 1.0),
                ],
            ),
            FakeDevice(
                "EQ Eight", "Eq8",
                parameters=[
                    FakeDeviceParameter("Frequency", 20000.0, 20.0, 22000.0),
                    FakeDeviceParameter("Gain", 0.0, -18.0, 18.0),
                ],
            ),
        ]
        self.cache.invalidate()

    def _processing_parameters(self):
        found = {}
        for device in self.adapter.song.tracks[1].devices:
            for parameter in device.parameters:
                found[(device.name, parameter.name)] = parameter.value
        return found

    def test_bass_loud_rack_writes_device_parameters(self):
        self._seed_processing_devices()
        plan = self._compile("bass.loud_rack", target={"track": "Bass layer"})
        self.assertEqual(plan["status"], "plan_ready", plan.get("reason"))
        render = plan["render"]
        self.assertEqual(render["strategy"], "device_parameters")
        self.assertEqual(render["move_count"], 5)
        self.assertEqual(render["moves"][0]["resolved_by"], "target")
        self.assertEqual(
            [row["role"] for row in render["unresolved_ingredients"]], ["clipper"]
        )
        self.assertEqual(
            [step["tool"] for step in plan["steps"]], ["devices_set_parameter"] * 5
        )

        applied = self._apply(plan)
        self.assertTrue(applied.get("applied"), applied)
        written = self._processing_parameters()
        for move in render["moves"]:
            self.assertAlmostEqual(
                written[(move["device"], move["parameter"])], move["value"]
            )

    def test_bass_loud_rack_resolves_each_role_by_binding(self):
        self._seed_processing_devices()
        plan = self._compile(
            "bass.loud_rack",
            track_bindings={
                "ott": "Bass layer",
                "saturation": "Bass layer",
                "eq": "Bass layer",
            },
        )
        self.assertEqual(plan["status"], "plan_ready", plan.get("reason"))
        self.assertEqual(
            {row["resolved_by"] for row in plan["render"]["moves"]}, {"binding"}
        )

    def test_bass_loud_rack_without_its_devices_names_the_step_and_device(self):
        plan = self._compile("bass.loud_rack", target={"track": "Vocal chop"})
        self.assertEqual(plan["status"], "unavailable")
        reason = plan["reason"]
        self.assertIn("step 1 (devices_set_parameter)", reason)
        self.assertIn("ingredient 'ott' (instrument, 'OTT')", reason)
        self.assertIn("'Multiband Dynamics'", reason)
        self.assertIn("devices_load", reason)
        self.assertIn("--binding ott=<track>", reason)

    def test_audition_needs_an_existing_clip(self):
        plan = self._compile("tearout.siren_lead")
        self.assertEqual(plan["status"], "unavailable")
        self.assertIn("--target-clip", plan["reason"])

    def test_user_recipe_can_declare_an_audition(self):
        recipe = {
            "id": "test.audition",
            "name": "Audition probe",
            "version": 1,
            "kind": "style",
            "status": "draft",
            "ingredients": [
                {"role": "synth", "kind": "instrument", "source": "Ableton Drift"}
            ],
            "audition": {
                "role": "synth",
                "length_beats": 2,
                "notes": [
                    {"pitch": 33, "start": 0.0, "duration": 0.5},
                    {"pitch": 33, "start": 1.0, "duration": 0.5, "velocity": 90},
                ],
            },
        }
        save_recipe({"recipe": recipe}, store=self.store)
        plan = self._compile("test.audition", target=dict(CLIP_TARGET))
        self.assertEqual(plan["status"], "plan_ready", plan.get("reason"))
        self.assertEqual(plan["render"]["note_count"], 2)
        self.assertEqual(plan["render"]["notes"][1]["velocity"], 90)


if __name__ == "__main__":
    unittest.main()

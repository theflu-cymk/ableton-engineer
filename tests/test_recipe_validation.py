import copy
import unittest

import support  # noqa: F401
from enableton.recipe_validation import RecipeValidationError, validate_recipe


def example_recipe():
    return {
        "id": "dubstep.half_time",
        "name": "Dubstep half-time step",
        "version": 1,
        "kind": "rhythm",
        "status": "shipped",
        "tempo": {"bpm": 140, "feel": "half_time", "grid": "1/16"},
        "length_bars": 2,
        "lanes": [
            {"slot": "kick", "pattern": "x.......x.......", "velocity": 1.0, "swing": 0.0},
            {"slot": "snare", "pattern": "....x.......x...", "humanize": 0.04},
        ],
        "source": {
            "kind": "learned",
            "file": "riddim/refs/dubstep_140.wav",
            "window_s": [0, 8],
            "confidence": 0.81,
        },
        "slots": [
            {
                "slot": "kick",
                "mode": "hit",
                "from": "riddim/drums/one shots",
                "select": "lowest_centroid",
                "count": 1,
            },
            {
                "slot": "snare",
                "mode": "layer",
                "from": "riddim/drums/loops",
                "select": "high_transient",
                "count": 1,
            },
        ],
    }


def style_recipe():
    return {
        "id": "dubstep.wobble_operator",
        "name": "Operator wobble",
        "version": 1,
        "kind": "style",
        "status": "shipped",
        "ingredients": [
            {"role": "synth", "kind": "instrument", "source": "Ableton Operator"}
        ],
        "audition": {
            "role": "synth",
            "length_beats": 2,
            "notes": [{"pitch": 36, "start": 0.0, "duration": 0.5}],
        },
    }


class RecipeValidationTests(unittest.TestCase):
    def test_accepts_an_audition_phrase(self):
        recipe = style_recipe()
        self.assertIsNone(validate_recipe(recipe))

    def test_rejects_an_audition_role_that_is_not_an_ingredient(self):
        recipe = style_recipe()
        recipe["audition"]["role"] = "sub"
        with self.assertRaisesRegex(
            RecipeValidationError, "must name one of the recipe's ingredients"
        ):
            validate_recipe(recipe)

    def test_rejects_an_audition_note_past_its_length(self):
        recipe = style_recipe()
        recipe["audition"]["notes"][0].update({"start": 1.8, "duration": 0.5})
        with self.assertRaisesRegex(RecipeValidationError, "ends after"):
            validate_recipe(recipe)

    def test_rejects_unknown_audition_note_keys(self):
        recipe = style_recipe()
        recipe["audition"]["notes"][0]["length"] = 0.5
        with self.assertRaisesRegex(RecipeValidationError, "unknown key"):
            validate_recipe(recipe)

    def test_rejects_an_audition_on_a_rhythm_recipe(self):
        recipe = example_recipe()
        recipe["audition"] = style_recipe()["audition"]
        with self.assertRaisesRegex(RecipeValidationError, "only apply"):
            validate_recipe(recipe)
    def test_accepts_the_documented_recipe_shape_without_mutation(self):
        recipe = example_recipe()
        original = copy.deepcopy(recipe)

        self.assertIsNone(validate_recipe(recipe))
        self.assertEqual(recipe, original)

    def test_rejects_unknown_schema_version(self):
        recipe = example_recipe()
        recipe["version"] = 2

        with self.assertRaisesRegex(RecipeValidationError, "unsupported recipe schema version"):
            validate_recipe(recipe)

    def test_rejects_pattern_bar_count_that_does_not_divide_recipe_length(self):
        recipe = example_recipe()
        recipe["lanes"][0]["pattern"] = "x.......x.......|" * 2 + "x.......x......."

        with self.assertRaisesRegex(RecipeValidationError, "does not divide"):
            validate_recipe(recipe)

    def test_rejects_bad_pattern_with_field_path(self):
        recipe = example_recipe()
        recipe["lanes"][1]["pattern"] = "x.......x......?"

        with self.assertRaisesRegex(RecipeValidationError, r"recipe\.lanes\[1\]\.pattern"):
            validate_recipe(recipe)

    def test_rejects_boolean_and_non_finite_tempo(self):
        for bpm in (True, float("nan"), float("inf"), 0):
            with self.subTest(bpm=bpm):
                recipe = example_recipe()
                recipe["tempo"]["bpm"] = bpm
                with self.assertRaisesRegex(RecipeValidationError, "tempo.bpm"):
                    validate_recipe(recipe)

    def test_rejects_invalid_slot_mode(self):
        recipe = example_recipe()
        recipe["slots"][0]["mode"] = "rack"

        with self.assertRaisesRegex(RecipeValidationError, "mode must be"):
            validate_recipe(recipe)

    def test_rejects_non_positive_slot_count(self):
        recipe = example_recipe()
        recipe["slots"][0]["count"] = 0

        with self.assertRaisesRegex(RecipeValidationError, "count must be a positive integer"):
            validate_recipe(recipe)

    def test_rejects_lane_without_a_slot_definition(self):
        recipe = example_recipe()
        recipe["lanes"][0]["slot"] = "missing"

        with self.assertRaisesRegex(RecipeValidationError, "undefined slot"):
            validate_recipe(recipe)


    def test_rejects_duplicate_lane_slots(self):
        recipe = example_recipe()
        recipe["lanes"].append(copy.deepcopy(recipe["lanes"][0]))

        with self.assertRaisesRegex(RecipeValidationError, "duplicates lane slot"):
            validate_recipe(recipe)

    def test_rejects_duplicate_slot_definitions(self):
        recipe = example_recipe()
        recipe["slots"].append(copy.deepcopy(recipe["slots"][0]))

        with self.assertRaisesRegex(RecipeValidationError, "duplicates slot definition"):
            validate_recipe(recipe)

    def test_accepts_a_slot_pitch_and_rejects_an_out_of_range_pitch(self):
        recipe = example_recipe()
        recipe["slots"][0]["pitch"] = 36
        self.assertIsNone(validate_recipe(recipe))

        recipe["slots"][0]["pitch"] = 128
        with self.assertRaisesRegex(RecipeValidationError, "pitch"):
            validate_recipe(recipe)

    def test_source_metadata_is_optional_and_accepts_the_documented_shape(self):
        without_source = example_recipe()
        del without_source["source"]
        self.assertIsNone(validate_recipe(without_source))

        without_window = example_recipe()
        del without_window["source"]["window_s"]
        del without_window["source"]["confidence"]
        self.assertIsNone(validate_recipe(without_window))

    def test_rejects_invalid_source_shape_and_required_fields(self):
        for source in ([], {}, {"kind": "learned"}, {"file": "refs/x.wav"}):
            with self.subTest(source=source):
                recipe = example_recipe()
                recipe["source"] = source
                with self.assertRaisesRegex(RecipeValidationError, "source"):
                    validate_recipe(recipe)

    def test_rejects_invalid_source_window(self):
        for window in ([0], [0, 0], [-0.1, 8], [8, 0], [0, float("nan")], [0, "8"]):
            with self.subTest(window=window):
                recipe = example_recipe()
                recipe["source"]["window_s"] = window
                with self.assertRaisesRegex(RecipeValidationError, "source.window_s"):
                    validate_recipe(recipe)

    def test_rejects_invalid_source_confidence(self):
        for confidence in (-0.01, 1.01, True, "0.5", float("nan")):
            with self.subTest(confidence=confidence):
                recipe = example_recipe()
                recipe["source"]["confidence"] = confidence
                with self.assertRaisesRegex(RecipeValidationError, "source.confidence"):
                    validate_recipe(recipe)

    def test_accepts_a_combination_without_rhythm_fields(self):
        recipe = {
            "id": "user.roller",
            "name": "Roller",
            "version": 1,
            "kind": "combination",
            "status": "draft",
            "flavor": "dubstep",
            "description": "A composed style",
            "tags": ["dubstep", "140"],
            "ingredients": [{"recipe": "dubstep.half_time", "role": "drums"}],
            "steps": [
                {
                    "tool": "tracks_set_volume",
                    "args": {"tracks": ["Drums"], "volume": 0.82},
                    "why": "leave headroom",
                }
            ],
        }

        self.assertIsNone(validate_recipe(recipe))

    def test_combination_needs_ingredients_or_steps(self):
        recipe = {
            "id": "user.empty",
            "name": "Empty",
            "version": 1,
            "kind": "combination",
            "status": "draft",
        }

        with self.assertRaisesRegex(RecipeValidationError, "ingredients or steps"):
            validate_recipe(recipe)

    def test_workflow_steps_are_bounded_and_cannot_set_transport_flags(self):
        recipe = {
            "id": "user.workflow",
            "name": "Workflow",
            "version": 1,
            "kind": "workflow",
            "status": "draft",
            "steps": [
                {
                    "tool": "tracks_set_volume",
                    "args": {"tracks": ["Drums"], "volume": 0.8, "dry_run": True},
                }
            ],
        }

        with self.assertRaisesRegex(RecipeValidationError, "dry_run or restore"):
            validate_recipe(recipe)


class TripletGridValidationTests(unittest.TestCase):
    def test_twelve_step_bars_validate_on_the_eighth_triplet_grid(self):
        recipe = example_recipe()
        recipe["tempo"]["grid"] = "1/8T"
        recipe["lanes"] = [
            {"slot": "kick", "pattern": "x.......x...", "velocity": 1.0},
            {"slot": "snare", "pattern": "....x......."},
        ]

        validate_recipe(recipe)

    def test_sixteen_step_bars_are_refused_on_a_twelve_step_grid(self):
        recipe = example_recipe()
        recipe["tempo"]["grid"] = "1/8T"

        with self.assertRaisesRegex(RecipeValidationError, "exactly 12 steps"):
            validate_recipe(recipe)


if __name__ == "__main__":
    unittest.main()

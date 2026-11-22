import copy
import os
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from enableton.live.fake import FakeAdapter
from enableton.manifest import load_manifest
from enableton.recipe_fingerprint import (
    FingerprintError,
    compare_fingerprint,
    measure_snapshot,
    parse_fingerprint,
)
from enableton.recipe_store import RecipeStore
from enableton.recipe_tools import (
    apply_recipe,
    save_recipe,
    show_recipe,
    verify_recipe,
)
from enableton.recipe_validation import RecipeValidationError, validate_recipe
from enableton.state.snapshot import SnapshotCache
from enableton.tools import run_tool


def workflow_recipe(recipe_id="test.level", **overrides):
    recipe = {
        "id": recipe_id,
        "name": "Test level",
        "version": 1,
        "kind": "workflow",
        "status": "draft",
        "steps": [
            {
                "tool": "tracks_set_volume",
                "args": {"tracks": ["Drums"], "volume": 0.82},
                "why": "leave headroom",
            }
        ],
        "expected": {"tempo_bpm": {"value": 140, "tolerance": 1}},
    }
    recipe.update(overrides)
    return recipe


class RecipeContractValidationTests(unittest.TestCase):
    def test_accepts_typed_ingredients_manual_and_expected_fingerprint(self):
        recipe = workflow_recipe()
        recipe["flavor"] = {
            "name": "dubstep",
            "bpm": [138, 142],
            "feel": "half_time",
            "tags": ["140"],
        }
        recipe["ingredients"] = [
            {"role": "drums", "recipe": "other.workflow"},
            {
                "role": "kick",
                "kind": "sample",
                "source": "riddim/drums/one shots",
                "select": "lowest_centroid",
                "constraints": {"tags": ["punchy"]},
                "fallback": "riddim/drums",
            },
            {
                "role": "bass",
                "kind": "instrument",
                "source": "Serum",
                "fallback": "Operator",
            },
        ]
        recipe["manual"] = [
            {
                "instruction": "Load the Serum preset.",
                "when": "before_apply",
                "verify": "The preset name is visible in Live.",
            }
        ]
        recipe["expected"] = {
            "tempo_bpm": {"value": 140, "tolerance": 1},
            "track_count": 3,
        }

        self.assertIsNone(validate_recipe(recipe))

    def test_rejects_invalid_contract_fields_with_field_paths(self):
        cases = [
            (
                {"expected": {"tempo_bpm": {"value": 140, "tolerance": -1}}},
                "tolerance",
            ),
            (
                {"expected": {"wat": 1}},
                "unknown metric",
            ),
            (
                {"manual": [{"instruction": "Do it", "when": "later"}]},
                "when",
            ),
            (
                {"flavor": {"name": "dubstep", "bpm": [142, 138]}},
                "start below",
            ),
            (
                {"flavor": {"name": "dubstep", "tags": "140"}},
                "flavor.tags",
            ),
            (
                {"ingredients": [{"role": "kick", "kind": "sample"}]},
                "source",
            ),
            (
                {
                    "ingredients": [
                        {"role": "kick", "recipe": "x", "source": "y"}
                    ]
                },
                "cannot be combined",
            ),
        ]
        for overrides, text in cases:
            with self.subTest(text=text):
                recipe = workflow_recipe(**overrides)
                with self.assertRaisesRegex(RecipeValidationError, text):
                    validate_recipe(recipe)

    def test_rejects_unknown_recipe_kind(self):
        recipe = workflow_recipe(kind="bogus")
        with self.assertRaisesRegex(RecipeValidationError, "unsupported recipe kind"):
            validate_recipe(recipe)


class FingerprintTests(unittest.TestCase):
    def data(self, *, note_count=8):
        return {
            "song": {"tempo": 140.0, "signature": [4, 4]},
            "counts": {
                "tracks": 1,
                "arrangement_clips": 1,
                "session_clips": 1,
                "devices_total": 2,
            },
            "tracks": [
                {
                    "index": 0,
                    "name": "Drums",
                    "device_count": 2,
                    "arrangement": [
                        {"start": 0.0, "end": 16.0, "midi": True, "note_count": note_count}
                    ],
                    "session": {
                        "filled": 1,
                        "clips": [{"midi": True, "note_count": 4}],
                    },
                }
            ],
        }

    def test_measures_snapshot_only_metrics(self):
        measured = measure_snapshot(self.data())
        self.assertEqual(
            measured["metrics"],
            {
                "tempo_bpm": 140.0,
                "arrangement_clip_count": 1,
                "session_clip_count": 1,
                "clip_count": 2,
                "track_count": 1,
                "device_count": 2,
                "note_count": 12,
                "bars": 4,
            },
        )
        self.assertEqual(measured["unavailable"], {})

    def test_compares_match_mismatch_partial_and_unavailable(self):
        measured = measure_snapshot(self.data())

        matched = compare_fingerprint(
            {"tempo_bpm": {"value": 140, "tolerance": 1}, "track_count": 1}, measured
        )
        self.assertEqual(matched["status"], "match")
        self.assertEqual(matched["matched"], 2)

        mismatch = compare_fingerprint({"tempo_bpm": 150}, measured)
        self.assertEqual(mismatch["status"], "mismatch")
        self.assertEqual(mismatch["metrics"][0]["actual"], 140.0)
        self.assertEqual(mismatch["metrics"][0]["delta"], -10.0)

        missing_notes = measure_snapshot(self.data(note_count=None))
        partial = compare_fingerprint({"tempo_bpm": 140, "note_count": 12}, missing_notes)
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["unavailable"], 1)

        unavailable = compare_fingerprint({"note_count": 12}, missing_notes)
        self.assertEqual(unavailable["status"], "unavailable")

    def test_fingerprint_rejects_non_integer_counts_and_bad_tolerance(self):
        for raw in (
            {"track_count": 1.5},
            {"tempo_bpm": 0},
            {"tempo_bpm": {"value": 140, "tolerance": True}},
            {"track_count": {"value": 1, "extra": 2}},
            {},
        ):
            with self.subTest(raw=raw), self.assertRaises(FingerprintError):
                parse_fingerprint(raw)


class RecipeCompileTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.shipped = root / "shipped"
        self.user = root / "user"
        self.store = RecipeStore(self.shipped, self.user)
        self.adapter = FakeAdapter()
        self.set_path = root / "scratch.als"
        self.set_path.write_bytes(b"scratch set bytes")
        self.adapter.song.file_path = str(self.set_path)
        self.cache = SnapshotCache(self.adapter)
        self.plan_root = str(root / "plans")
        self.backup_root = str(root / "backups")
        self.transaction_root = str(root / "transactions")
        self.catalogue = load_manifest()

    def save(self, recipe):
        save_recipe({"recipe": recipe}, store=self.store)

    def parent(self, **overrides):
        recipe = {
            "id": "test.parent",
            "name": "Test parent",
            "version": 1,
            "kind": "combination",
            "status": "draft",
            "flavor": {"name": "dubstep", "bpm": [138, 142]},
            "ingredients": [{"role": "level", "recipe": "test.level"}],
            "steps": [
                {
                    "tool": "tracks_set_pan",
                    "args": {"tracks": ["Drums"], "pan": -0.1},
                }
            ],
            "manual": [
                {
                    "instruction": "Confirm the drum track is the one you want.",
                    "when": "before_apply",
                    "verify": "Track Drums is selected.",
                }
            ],
            "expected": {"tempo_bpm": {"value": 140, "tolerance": 1}},
        }
        recipe.update(overrides)
        return recipe

    def compile_parent(self, **args):
        return apply_recipe(
            {"id": "test.parent", **args},
            store=self.store,
            adapter=self.adapter,
            cache=self.cache,
            plan_root=self.plan_root,
            catalogue=self.catalogue,
        )

    def test_manual_gate_then_compiles_child_and_parent_steps(self):
        self.save(workflow_recipe())
        self.save(self.parent())

        blocked = self.compile_parent()
        self.assertEqual(blocked["status"], "manual_required")
        self.assertIsNone(blocked["plan_id"])
        self.assertEqual(blocked["manual"][0]["when"], "before_apply")

        ready = self.compile_parent(manual_confirmed=True)
        self.assertEqual(ready["status"], "plan_ready")
        self.assertTrue(ready["plan_id"].startswith("p_"))
        self.assertEqual(
            [step["tool"] for step in ready["steps"]],
            ["tracks_set_volume", "tracks_set_pan"],
        )
        self.assertEqual(ready["manual"][0]["status"], "confirmed")

        applied = run_tool(
            "ableton_plan_apply",
            {"plan_id": ready["plan_id"]},
            self.adapter,
            catalogue=self.catalogue,
            cache=self.cache,
            plan_root=self.plan_root,
            backup_root=self.backup_root,
            transaction_root=self.transaction_root,
        )
        self.assertTrue(applied["applied"])

        verified = verify_recipe(
            {"id": "test.parent"}, store=self.store, cache=SnapshotCache(self.adapter)
        )
        self.assertEqual(verified["status"], "match")
        self.assertEqual(verified["metrics"][0]["actual"], 140.0)

    def test_verify_reports_mismatch_and_manual_gate_before_verify(self):
        self.save(workflow_recipe(expected={"tempo_bpm": {"value": 150, "tolerance": 1}}))
        mismatch = verify_recipe(
            {"id": "test.level"}, store=self.store, cache=self.cache
        )
        self.assertEqual(mismatch["status"], "mismatch")

        self.save(
            workflow_recipe(
                "test.manual",
                manual=[
                    {
                        "instruction": "Confirm the mix is audible.",
                        "when": "before_verify",
                    }
                ],
            )
        )
        blocked = verify_recipe(
            {"id": "test.manual"}, store=self.store, cache=self.cache
        )
        self.assertEqual(blocked["status"], "manual_required")
        confirmed = verify_recipe(
            {"id": "test.manual", "manual_confirmed": True},
            store=self.store,
            cache=self.cache,
        )
        self.assertEqual(confirmed["status"], "match")
        self.assertEqual(confirmed["manual"][0]["status"], "confirmed")

    def test_recipe_without_expected_fingerprint_is_unavailable(self):
        self.save(workflow_recipe(expected=None))
        result = verify_recipe({"id": "test.level"}, store=self.store, cache=self.cache)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("no expected fingerprint", result["reason"])

    def test_sample_binding_is_reported_unresolved_and_never_loaded(self):
        recipe = workflow_recipe(
            "test.sample",
            ingredients=[
                {
                    "role": "kick",
                    "kind": "sample",
                    "source": "riddim/drums/one shots",
                }
            ],
        )
        self.save(recipe)
        shown = show_recipe({"id": "test.sample"}, store=self.store)
        self.assertFalse(shown["ingredients"][0]["resolved"])
        self.assertIn("does not resolve library sources", shown["unresolved"][0]["reason"])

        # A declaration no longer blocks a workflow that has its own executable steps: the plan
        # carries exactly those steps and never pretends to have loaded the sample.
        result = apply_recipe(
            {"id": "test.sample"},
            store=self.store,
            adapter=self.adapter,
            cache=self.cache,
            plan_root=self.plan_root,
            catalogue=self.catalogue,
        )
        self.assertEqual(result["status"], "plan_ready", result.get("reason"))
        self.assertEqual(
            [step["args"] for step in result["steps"]],
            [step["args"] for step in recipe["steps"]],
        )
        self.assertNotIn("kick", str(result["steps"]))

    def test_rhythm_ingredient_needs_a_target_and_then_compiles(self):
        rhythm = {
            "id": "test.rhythm",
            "name": "Test rhythm",
            "version": 1,
            "kind": "rhythm",
            "status": "draft",
            "tempo": {"bpm": 140, "feel": "half_time", "grid": "1/16"},
            "length_bars": 1,
            "lanes": [{"slot": "kick", "pattern": "x.......x......."}],
            "slots": [
                {
                    "slot": "kick",
                    "mode": "hit",
                    "from": "drums",
                    "select": "lowest_centroid",
                    "count": 1,
                    "pitch": 36,
                }
            ],
        }
        self.save(rhythm)
        self.save(
            self.parent(
                ingredients=[{"role": "drums", "recipe": "test.rhythm"}],
                manual=[],
            )
        )

        missing_target = self.compile_parent(manual_confirmed=True)
        self.assertEqual(missing_target["status"], "unavailable")
        self.assertIn("explicit MIDI target", missing_target["reason"])

        ready = self.compile_parent(
            manual_confirmed=True,
            target={
                "track": "Drums",
                "clip": "drums 1",
                "location": "arrangement",
            },
        )
        self.assertEqual(ready["status"], "plan_ready")
        self.assertEqual(
            [step["tool"] for step in ready["steps"]],
            ["notes_replace", "tracks_set_pan"],
        )
        self.assertEqual(ready["render"]["note_count"], 2)
        self.assertEqual(ready["render"]["samples"][0]["status"], "unresolved")
        self.assertTrue(ready["render"]["length_checked"])

        applied = run_tool(
            "ableton_plan_apply",
            {"plan_id": ready["plan_id"]},
            self.adapter,
            catalogue=self.catalogue,
            cache=self.cache,
            plan_root=self.plan_root,
            backup_root=self.backup_root,
            transaction_root=self.transaction_root,
        )
        self.assertTrue(applied["applied"])
        self.assertEqual(len(self.adapter.song.tracks[0].arrangement_clips[0].notes), 2)
        self.assertAlmostEqual(self.adapter.song.tracks[0].pan, -0.1)

    def test_run_tool_dispatches_recipe_contract_tools(self):
        self.save(workflow_recipe())
        shown = run_tool(
            "recipe_show", {"id": "test.level"}, None, recipe_store=self.store
        )
        self.assertEqual(shown["recipe"]["kind"], "workflow")
        verified = run_tool(
            "recipe_verify",
            {"id": "test.level"},
            self.adapter,
            cache=self.cache,
            recipe_store=self.store,
        )
        self.assertEqual(verified["status"], "match")


if __name__ == "__main__":
    unittest.main()

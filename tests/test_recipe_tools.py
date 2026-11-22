import json
import os
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from enableton.protocol.codes import LiveError
from enableton.recipe_store import RecipeStore
from enableton.recipe_tools import list_recipes, save_recipe, show_recipe


def example_recipe(*, name="Dubstep half-time step", status="draft"):
    return {
        "id": "dubstep.half_time",
        "name": name,
        "version": 1,
        "kind": "rhythm",
        "status": status,
        "tempo": {"bpm": 140, "feel": "half_time", "grid": "1/16"},
        "length_bars": 2,
        "lanes": [
            {"slot": "kick", "pattern": "x.......x.......", "velocity": 1.0, "swing": 0.0},
            {"slot": "snare", "pattern": "....x.......x...", "humanize": 0.04},
        ],
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


class RecipeToolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.shipped = os.path.join(self.temp_dir.name, "shipped")
        self.user = os.path.join(self.temp_dir.name, "user")
        self.store = RecipeStore(self.shipped, self.user)

    def _write(self, directory, recipe):
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, recipe["id"] + ".json")
        with open(path, "w", encoding="utf-8") as output:
            json.dump(recipe, output)
        return path

    def test_save_list_and_show_a_user_recipe(self):
        recipe = example_recipe()
        saved = save_recipe({"recipe": recipe}, store=self.store)

        self.assertFalse(saved["replaced"])
        self.assertTrue(os.path.isfile(saved["path"]))
        rows = list_recipes({}, store=self.store)
        self.assertEqual(rows["count"], 1)
        self.assertEqual(rows["recipes"][0]["source"], "user")
        self.assertEqual(show_recipe({"id": recipe["id"]}, store=self.store)["recipe"], recipe)

    def test_list_filters_by_kind_tag_search_and_runnable(self):
        rhythm = example_recipe()
        rhythm["tags"] = ["riddim", "executable"]
        self._write(self.shipped, rhythm)
        self._write(
            self.shipped,
            {
                "id": "riddim.checklist",
                "name": "Riddim checklist",
                "version": 1,
                "kind": "style",
                "status": "shipped",
                "tags": ["riddim"],
                "ingredients": [
                    {"role": "synth", "kind": "instrument", "source": "Operator"}
                ],
            },
        )

        rows = list_recipes({}, store=self.store)
        self.assertEqual(rows["count"], 2)
        self.assertTrue(all("tags" in row for row in rows["recipes"]))

        by_kind = list_recipes({"kind": "style"}, store=self.store)
        self.assertEqual([row["id"] for row in by_kind["recipes"]], ["riddim.checklist"])
        self.assertEqual(by_kind["count"], 1)

        by_tag = list_recipes({"tag": "riddim"}, store=self.store)
        self.assertEqual(
            [row["id"] for row in by_tag["recipes"]],
            ["dubstep.half_time", "riddim.checklist"],
        )

        by_search = list_recipes({"search": "CHECK"}, store=self.store)
        self.assertEqual([row["id"] for row in by_search["recipes"]], ["riddim.checklist"])

        runnable = list_recipes({"runnable": True}, store=self.store)
        self.assertEqual([row["id"] for row in runnable["recipes"]], ["dubstep.half_time"])

        combined = list_recipes(
            {"kind": "style", "tag": "riddim", "runnable": True}, store=self.store
        )
        self.assertEqual(combined["count"], 0)

    def test_list_rejects_unknown_kind_and_bad_filter_values(self):
        with self.assertRaises(LiveError) as ctx:
            list_recipes({"kind": "loop"}, store=self.store)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")
        self.assertIn("style, rhythm, workflow, combination", ctx.exception.message)

        for args in ({"tag": ""}, {"search": 3}, {"runnable": "yes"}):
            with self.assertRaises(LiveError) as ctx:
                list_recipes(args, store=self.store)
            self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_existing_user_recipe_requires_explicit_overwrite(self):
        save_recipe({"recipe": example_recipe()}, store=self.store)

        with self.assertRaises(LiveError) as ctx:
            save_recipe({"recipe": example_recipe(name="Changed")}, store=self.store)
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")

        saved = save_recipe(
            {"recipe": example_recipe(name="Changed"), "overwrite": True},
            store=self.store,
        )
        self.assertTrue(saved["replaced"])
        self.assertEqual(
            show_recipe({"id": "dubstep.half_time"}, store=self.store)["recipe"]["name"],
            "Changed",
        )

    def test_save_rejects_shipped_status_and_bad_schema(self):
        with self.assertRaises(LiveError) as ctx:
            save_recipe({"recipe": example_recipe(status="shipped")}, store=self.store)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

        broken = example_recipe()
        broken["version"] = 2
        with self.assertRaises(LiveError) as ctx:
            save_recipe({"recipe": broken}, store=self.store)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")
        self.assertFalse(os.path.exists(self.user))

    def test_show_missing_recipe_is_not_found(self):
        with self.assertRaises(LiveError) as ctx:
            show_recipe({"id": "not.here"}, store=self.store)
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

    def test_path_like_ids_and_unknown_args_are_rejected(self):
        with self.assertRaises(LiveError) as ctx:
            show_recipe({"id": "../escape"}, store=self.store)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

        recipe = example_recipe()
        recipe["id"] = "../escape"
        with self.assertRaises(LiveError) as ctx:
            save_recipe({"recipe": recipe}, store=self.store)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

        with self.assertRaises(LiveError) as ctx:
            list_recipes({"bogus": True}, store=self.store)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_list_reports_what_can_be_compiled(self):
        self._write(self.shipped, example_recipe())
        self._write(
            self.shipped,
            {
                "id": "tearout.checklist",
                "name": "Tearout checklist",
                "version": 1,
                "kind": "style",
                "status": "shipped",
                "ingredients": [
                    {"role": "synth", "kind": "instrument", "source": "Serum 2"}
                ],
            },
        )

        rows = {row["id"]: row for row in list_recipes({}, store=self.store)["recipes"]}
        self.assertTrue(rows["dubstep.half_time"]["compilable"])
        self.assertTrue(rows["dubstep.half_time"]["needs_target"])
        self.assertEqual(rows["dubstep.half_time"]["bpm"], [140.0, 140.0])
        self.assertFalse(rows["tearout.checklist"]["compilable"])
        self.assertFalse(rows["tearout.checklist"]["needs_target"])

    def test_combination_saves_and_shows_resolved_ingredients(self):
        save_recipe({"recipe": example_recipe()}, store=self.store)
        style = {
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

        saved = save_recipe({"recipe": style}, store=self.store)
        self.assertFalse(saved["replaced"])
        rows = list_recipes({}, store=self.store)
        kinds = {row["id"]: row["kind"] for row in rows["recipes"]}
        self.assertEqual(kinds["user.roller"], "combination")

        shown = show_recipe({"id": "user.roller"}, store=self.store)
        self.assertEqual(shown["ingredients"][0]["role"], "drums")
        self.assertEqual(shown["ingredients"][0]["name"], "Dubstep half-time step")
        self.assertEqual(shown["missing"], [])

    def test_combination_rejects_missing_ingredients_and_invalid_steps(self):
        style = {
            "id": "user.roller",
            "name": "Roller",
            "version": 1,
            "kind": "combination",
            "status": "draft",
            "ingredients": [{"recipe": "not.here", "role": "drums"}],
        }
        with self.assertRaises(LiveError) as ctx:
            save_recipe({"recipe": style}, store=self.store)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

        save_recipe({"recipe": example_recipe()}, store=self.store)
        style["ingredients"] = [{"recipe": "dubstep.half_time", "role": "drums"}]
        style["steps"] = [{"tool": "not_a_tool", "args": {}}]
        with self.assertRaises(LiveError) as ctx:
            save_recipe({"recipe": style}, store=self.store)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_shipped_recipe_pack_is_valid_and_listable(self):
        shipped = Path(__file__).resolve().parents[1] / "src" / "enableton" / "recipes"
        store = RecipeStore(shipped, self.user)

        rows = list_recipes({}, store=store)
        ids = [row["id"] for row in rows["recipes"]]
        self.assertIn("dubstep.half_time", ids)
        self.assertIn("dubstep.roller", ids)
        shown = show_recipe({"id": "dubstep.half_time"}, store=store)
        self.assertEqual(shown["source"], "shipped")
        self.assertEqual(shown["recipe"]["status"], "shipped")

        style = show_recipe({"id": "dubstep.roller"}, store=store)
        self.assertEqual(style["recipe"]["kind"], "combination")
        self.assertEqual(style["recipe"]["flavor"]["name"], "dubstep")
        self.assertEqual(style["recipe"]["flavor"]["bpm"], [138, 142])
        self.assertEqual(style["ingredients"][0]["name"], "Dubstep - half-time step")
        self.assertEqual(style["missing"], [])


if __name__ == "__main__":
    unittest.main()

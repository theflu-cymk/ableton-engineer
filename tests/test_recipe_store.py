import json
import os
import tempfile
import unittest

import support  # noqa: F401
from enableton.recipe_store import RecipeStore, RecipeStoreError


def example_recipe(*, name="Dubstep half-time step", status="shipped"):
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


class RecipeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.shipped = os.path.join(self.temp_dir.name, "shipped")
        self.user = os.path.join(self.temp_dir.name, "user")
        os.makedirs(self.shipped)
        self.store = RecipeStore(self.shipped, self.user)

    def _write(self, directory, recipe):
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, recipe["id"] + ".json")
        with open(path, "w", encoding="utf-8") as output:
            json.dump(recipe, output)
        return path

    def test_list_and_show_shipped_recipes(self):
        self._write(self.shipped, example_recipe())

        self.assertEqual(
            self.store.list(),
            [
                {
                    "id": "dubstep.half_time",
                    "name": "Dubstep half-time step",
                    "kind": "rhythm",
                    "status": "shipped",
                    "source": "shipped",
                }
            ],
        )
        self.assertEqual(self.store.show("dubstep.half_time"), example_recipe())

    def test_user_recipe_overrides_shipped_by_id_without_mutating_shipped(self):
        shipped_path = self._write(self.shipped, example_recipe())
        user_recipe = example_recipe(name="My edited beat", status="draft")
        saved_path = self.store.save_user(user_recipe)

        self.assertEqual(self.store.show(user_recipe["id"])["name"], "My edited beat")
        self.assertEqual(self.store.list()[0]["source"], "user")
        with open(shipped_path, encoding="utf-8") as source:
            self.assertEqual(json.load(source)["name"], "Dubstep half-time step")
        with open(saved_path, encoding="utf-8") as source:
            self.assertEqual(json.load(source), user_recipe)
        self.assertEqual(os.path.abspath(saved_path.parent), os.path.abspath(self.user))

    def test_delete_removes_only_user_override_and_reveals_shipped(self):
        self._write(self.shipped, example_recipe())
        self.store.save_user(example_recipe(name="My edited beat", status="draft"))

        self.assertTrue(self.store.delete_user("dubstep.half_time"))
        self.assertEqual(self.store.show("dubstep.half_time")["name"], "Dubstep half-time step")
        self.assertFalse(self.store.delete_user("dubstep.half_time"))

    def test_show_missing_recipe_fails_explicitly(self):
        with self.assertRaisesRegex(RecipeStoreError, "no recipe with id"):
            self.store.show("not.here")

    def test_invalid_recipe_json_fails_explicitly(self):
        path = os.path.join(self.shipped, "dubstep.half_time.json")
        with open(path, "w", encoding="utf-8") as output:
            output.write("{")

        with self.assertRaisesRegex(RecipeStoreError, "cannot read recipe"):
            self.store.show("dubstep.half_time")

    def test_filename_and_recipe_ids_must_match(self):
        recipe = example_recipe()
        recipe["id"] = "different.id"
        path = os.path.join(self.shipped, "dubstep.half_time.json")
        with open(path, "w", encoding="utf-8") as output:
            json.dump(recipe, output)

        with self.assertRaisesRegex(RecipeStoreError, "does not match filename"):
            self.store.show("dubstep.half_time")

    def test_refuses_path_like_ids(self):
        for recipe_id in ("../escape", "", "."):
            with self.subTest(recipe_id=recipe_id), self.assertRaises(RecipeStoreError):
                self.store.show(recipe_id)

    def test_save_rejects_an_invalid_recipe_without_creating_user_files(self):
        recipe = example_recipe()
        recipe["version"] = 2

        with self.assertRaisesRegex(RecipeStoreError, "unsupported recipe schema version"):
            self.store.save_user(recipe)
        self.assertFalse(os.path.exists(self.user))


if __name__ == "__main__":
    unittest.main()

"""Every shipped style recipe, exercised through the CLI, lands in exactly one of two buckets.

Bucket 1: it applies and what the payload reported is what the fake Set now holds (notes or device
parameter values). Bucket 2: it refuses at compile time naming the step, the blocking ingredient
and the operation this build cannot perform. There is no silent third outcome.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import enableton
import support  # noqa: F401
from enableton.cli import main
from enableton.live.fake import FakeDevice, FakeDeviceParameter

RECIPE_DIR = Path(enableton.__file__).parent / "recipes"


class StyleSweepTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(os.environ.pop, "APPDATA", None)
        os.environ["APPDATA"] = os.path.join(self.temp.name, "appdata")
        self.server = support.fake_server()
        self.addCleanup(self.server.stop)
        source = Path(self.temp.name) / "scratch.als"
        source.write_bytes(b"scratch")
        self.server.song.file_path = str(source)
        # A realistic processing track: the loud-rack recipe's devices already exist here.
        self.server.song.tracks[1].devices = [
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

    def _style_recipes(self):
        recipes = []
        for path in sorted(RECIPE_DIR.glob("*.json")):
            recipe = json.loads(path.read_text(encoding="utf-8"))
            if recipe.get("kind") == "style":
                recipes.append(recipe)
        return recipes

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--port", str(self.server.port), *argv])
        text = out.getvalue()
        return code, (json.loads(text) if text.strip() else {}), err.getvalue()

    def _device_value(self, track_name, device_name, parameter_name):
        for track in self.server.song.tracks:
            if track.name != track_name:
                continue
            for device in track.devices:
                if device.name != device_name:
                    continue
                for parameter in device.parameters:
                    if parameter.name == parameter_name:
                        return parameter.value
        raise AssertionError("no %s / %s / %s" % (track_name, device_name, parameter_name))

    def test_every_style_recipe_applies_or_names_its_blocker(self):
        recipes = self._style_recipes()
        self.assertEqual(len(recipes), 26)

        applied, blocked = [], []
        for recipe in recipes:
            recipe_id = recipe["id"]
            argv = ["recipe", recipe_id, "--manual-confirmed", "--apply"]
            if recipe.get("device_moves"):
                argv += ["--target-track", "Bass layer"]
            else:
                argv += [
                    "--target-track", "Drums", "--target-clip", "drums A",
                    "--location", "session",
                ]
            code, payload, stderr_text = self._run(argv)

            if code == 0:
                self.assertTrue(payload["apply"]["applied"], recipe_id)
                render = payload["recipe"]["render"]
                if render["strategy"] == "audition":
                    clip = [
                        slot.clip for slot in self.server.song.tracks[0].clip_slots
                        if slot.clip is not None
                    ][0]
                    self.assertEqual(len(clip.notes), render["note_count"], recipe_id)
                    self.assertEqual(
                        sorted(round(note.start_time, 6) for note in clip.notes),
                        [note["start"] for note in render["notes"]],
                        recipe_id,
                    )
                elif render["strategy"] == "device_parameters":
                    self.assertGreater(render["move_count"], 0, recipe_id)
                    for move in render["moves"]:
                        self.assertAlmostEqual(
                            self._device_value(
                                move["track"], move["device"], move["parameter"]
                            ),
                            move["value"],
                            msg="%s %s" % (recipe_id, move),
                        )
                else:  # pragma: no cover - the two strategies are the only ones that write
                    self.fail("%s reported strategy %r" % (recipe_id, render["strategy"]))
                applied.append(recipe_id)
                continue

            self.assertEqual(code, 1, (recipe_id, code, stderr_text))
            self.assertEqual(payload.get("status"), "unavailable", recipe_id)
            reason = payload.get("reason") or stderr_text
            self.assertIn("step 1", reason, recipe_id)
            self.assertIn("ingredient", reason, recipe_id)
            self.assertTrue(
                "--binding" in reason or "by hand" in reason, (recipe_id, reason)
            )
            blocked.append(recipe_id)

        self.assertEqual(len(applied) + len(blocked), 26)
        self.assertEqual(len(blocked), 5)
        self.assertGreaterEqual(len(applied), 21)
        for recipe_id in (
            "dubstep.wobble_operator",
            "riddim.triplet_operator",
            "deathstep.growl_operator",
            "tearout.siren_lead",
            "bass.loud_rack",
        ):
            self.assertIn(recipe_id, applied)
        self.assertEqual(
            sorted(blocked),
            [
                "bass_music.mix_chain",
                "tearout.filtered_fill",
                "tearout.growl_fatten",
                "tearout.gun_click",
                "tearout.gun_glue",
            ],
        )


if __name__ == "__main__":
    unittest.main()

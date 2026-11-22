"""Rhythm recipes compile to reversible MIDI writes, with honest source limits."""

import json
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeClip, FakeTrack
from enableton.manifest import load_manifest
from enableton.recipe_rhythm import RhythmCompileError, render_rhythm
from enableton.recipe_store import RecipeStore
from enableton.recipe_tools import apply_recipe
from enableton.state.snapshot import SnapshotCache
from enableton.tools import run_tool


def rhythm_recipe(**overrides):
    recipe = {
        "id": "test.rhythm",
        "name": "Test rhythm",
        "version": 1,
        "kind": "rhythm",
        "status": "draft",
        "tempo": {"bpm": 140, "feel": "half_time", "grid": "1/16"},
        "length_bars": 2,
        "lanes": [
            {
                "slot": "kick",
                "pattern": "x......x........",
                "velocity": 0.8,
                "swing": 0.5,
            },
            {
                "slot": "snare",
                "pattern": "....x.......x...",
                "velocity": 0.6,
                "humanize": 0.1,
            },
        ],
        "slots": [
            {
                "slot": "kick",
                "mode": "hit",
                "from": "drums",
                "select": "lowest_centroid",
                "count": 1,
                "pitch": 36,
            },
            {
                "slot": "snare",
                "mode": "hit",
                "from": "drums",
                "select": "high_transient",
                "count": 1,
                "pitch": 38,
            },
        ],
    }
    recipe.update(overrides)
    return recipe


class RhythmRenderTests(unittest.TestCase):
    def target(self, **overrides):
        target = {"track": "Drums", "clip": "drums 1", "location": "arrangement"}
        target.update(overrides)
        return target

    def test_renders_lanes_to_midi_with_velocities_and_swing(self):
        result = render_rhythm(
            rhythm_recipe(), self.target(), target_length=8.0, beats_per_bar=4.0
        )

        notes = result["step"]["args"]["notes"]
        self.assertEqual(result["strategy"], "midi_notes")
        self.assertEqual(result["note_count"], 8)
        self.assertTrue(result["length_checked"])
        self.assertEqual([row["slot"] for row in result["lanes"]], ["kick", "snare"])
        self.assertEqual([row["hits"] for row in result["lanes"]], [4, 4])
        self.assertEqual([row["status"] for row in result["samples"]], ["unresolved", "unresolved"])
        self.assertEqual(
            sorted({note["pitch"] for note in notes}),
            [36, 38],
        )
        self.assertEqual(
            [note["velocity"] for note in notes if note["pitch"] == 36],
            [102, 102, 102, 102],
        )
        snare_velocities = [note["velocity"] for note in notes if note["pitch"] == 38]
        self.assertEqual(len(snare_velocities), 4)
        self.assertTrue(all(73 <= value <= 79 for value in snare_velocities))
        # Swing moves the odd-step kick from beat 1.75 to 1.8125 in each bar.
        kick_starts = [note["start"] for note in notes if note["pitch"] == 36]
        self.assertEqual(kick_starts, [0.0, 1.8125, 4.0, 5.8125])

    def test_pitch_map_can_supply_a_missing_slot_pitch(self):
        recipe = rhythm_recipe()
        del recipe["slots"][0]["pitch"]

        with self.assertRaisesRegex(RhythmCompileError, "no pitch"):
            render_rhythm(recipe, self.target(), target_length=8.0)

        result = render_rhythm(
            recipe, self.target(), pitch_map={"kick": 40}, target_length=8.0
        )
        self.assertEqual(result["lanes"][0]["pitch"], 40)

    def test_short_target_is_refused_instead_of_writing_a_partial_pattern(self):
        with self.assertRaisesRegex(RhythmCompileError, "needs 8 beats"):
            render_rhythm(rhythm_recipe(), self.target(), target_length=4.0)

    def test_layer_slots_are_not_silently_treated_as_hits(self):
        recipe = rhythm_recipe()
        recipe["slots"][0]["mode"] = "layer"
        with self.assertRaisesRegex(RhythmCompileError, "only 'hit'"):
            render_rhythm(recipe, self.target(), target_length=8.0)

    def test_session_target_reports_that_length_was_not_checked(self):
        result = render_rhythm(
            rhythm_recipe(),
            self.target(location="session", slot=0),
            target_length=None,
        )
        self.assertFalse(result["length_checked"])
        self.assertTrue(any("length was not readable" in item for item in result["warnings"]))


def triplet_recipe(grid="1/8T", pattern=None, **lane_overrides):
    """A one-lane recipe whose pattern length follows its declared grid."""
    steps = 12 if grid == "1/8T" else 24
    lane = {"slot": "kick", "pattern": pattern or "X" + "." * (steps - 1), "velocity": 1.0}
    lane.update(lane_overrides)
    return rhythm_recipe(
        tempo={"bpm": 140, "feel": "half_time", "grid": grid},
        lanes=[lane],
        slots=[rhythm_recipe()["slots"][0]],
    )


class TripletRhythmTests(unittest.TestCase):
    target = {"track": "Drums", "clip": "drums 1", "location": "arrangement"}

    def test_eighth_triplets_land_on_third_beat_offsets(self):
        result = render_rhythm(
            triplet_recipe(pattern="Xxx......x.."), self.target, target_length=8.0
        )

        self.assertEqual(result["grid"], "1/8T")
        self.assertEqual(result["steps_per_bar"], 12)
        self.assertEqual(result["note_count"], 8)
        starts = [note["start"] for note in result["step"]["args"]["notes"]]
        # Three hits inside beat one, then the answer on beat three, in both bars.
        self.assertEqual(starts[:4], [0.0, 0.333333, 0.666667, 3.0])
        for start in starts:
            self.assertAlmostEqual(start * 3, round(start * 3), places=4)
        # A 1/16 position is a whole quarter-beat; triplet starts must miss that grid.
        self.assertTrue(any(abs(start * 4 - round(start * 4)) > 0.01 for start in starts))

    def test_sixteenth_triplets_land_on_sixth_beat_offsets(self):
        result = render_rhythm(
            triplet_recipe(grid="1/16T", pattern="Xx...." * 4),
            self.target,
            target_length=8.0,
        )

        self.assertEqual(result["grid"], "1/16T")
        self.assertEqual(result["steps_per_bar"], 24)
        starts = [note["start"] for note in result["step"]["args"]["notes"]]
        self.assertEqual(len(starts), 16)
        self.assertAlmostEqual(starts[1], 1.0 / 6.0, places=4)
        for start in starts:
            self.assertAlmostEqual(start * 6, round(start * 6), places=4)
        self.assertTrue(any(abs(start * 4 - round(start * 4)) > 0.01 for start in starts))

    def test_pattern_bars_must_match_the_declared_grid(self):
        recipe = triplet_recipe(pattern="x.......x.......")
        with self.assertRaisesRegex(RhythmCompileError, "exactly 12 steps"):
            render_rhythm(recipe, self.target, target_length=8.0)

    def test_swing_is_refused_on_a_triplet_grid(self):
        recipe = triplet_recipe(pattern="x..x..x..x..", swing=0.3)
        with self.assertRaisesRegex(RhythmCompileError, "straight 1/16 grid"):
            render_rhythm(recipe, self.target, target_length=8.0)

    def test_an_unsupported_grid_names_the_supported_grids(self):
        recipe = rhythm_recipe(tempo={"bpm": 140, "feel": "half_time", "grid": "1/8"})
        with self.assertRaisesRegex(RhythmCompileError, "'1/8T'"):
            render_rhythm(recipe, self.target, target_length=8.0)


class RhythmApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.store = RecipeStore(root / "shipped", root / "user")
        self.store.user_dir.mkdir(parents=True)
        (self.store.user_dir / "test.rhythm.json").write_text(
            json.dumps(rhythm_recipe()), encoding="utf-8"
        )
        self.adapter = FakeAdapter()
        self.set_path = root / "scratch.als"
        self.set_path.write_bytes(b"scratch set")
        self.adapter.song.file_path = str(self.set_path)
        self.cache = SnapshotCache(self.adapter)
        self.plan_root = str(root / "plans")
        self.backup_root = str(root / "backups")
        self.transaction_root = str(root / "transactions")
        self.catalogue = load_manifest()

    def compile(self, recipe_id="test.rhythm", **args):
        return apply_recipe(
            {"id": recipe_id, **args},
            store=self.store,
            adapter=self.adapter,
            cache=self.cache,
            plan_root=self.plan_root,
            catalogue=self.catalogue,
        )

    def test_target_plan_applies_to_the_existing_clip_and_undoes_exactly(self):
        result = self.compile(
            target={
                "track": "Drums",
                "clip": "drums 1",
                "location": "arrangement",
            }
        )
        self.assertEqual(result["status"], "plan_ready")
        self.assertEqual([step["tool"] for step in result["steps"]], ["notes_replace"])
        clip = self.adapter.song.tracks[0].arrangement_clips[0]
        self.assertEqual(clip.notes, [])

        applied = run_tool(
            "ableton_plan_apply",
            {"plan_id": result["plan_id"]},
            self.adapter,
            catalogue=self.catalogue,
            cache=self.cache,
            plan_root=self.plan_root,
            backup_root=self.backup_root,
            transaction_root=self.transaction_root,
        )
        self.assertTrue(applied["applied"])
        self.assertEqual(len(clip.notes), 8)
        self.assertEqual({note.pitch for note in clip.notes}, {36, 38})

        undone = run_tool(
            "ableton_undo",
            {},
            self.adapter,
            catalogue=self.catalogue,
            cache=self.cache,
            transaction_root=self.transaction_root,
        )
        self.assertTrue(undone["restored"])
        self.assertEqual(clip.notes, [])

    def test_track_binding_redirects_the_target_and_procedure_step(self):
        self.adapter.song.tracks.append(
            FakeTrack(
                "Synth",
                is_midi=True,
                arrangement_clips=[FakeClip("synth", 0.0, 8.0, True)],
            )
        )
        parent = {
            "id": "test.parent",
            "name": "Test parent",
            "version": 1,
            "kind": "combination",
            "status": "draft",
            "ingredients": [{"role": "drums", "recipe": "test.rhythm"}],
            "steps": [
                {
                    "tool": "tracks_set_pan",
                    "args": {"tracks": ["Drums"], "pan": -0.1},
                }
            ],
        }
        (self.store.user_dir / "test.parent.json").write_text(
            json.dumps(parent), encoding="utf-8"
        )

        result = self.compile(
            "test.parent",
            target={
                "track": "Synth",
                "clip": "synth",
                "location": "arrangement",
            },
            track_bindings={"Drums": "Synth"},
        )
        self.assertEqual(result["status"], "plan_ready")
        self.assertEqual(
            [step["tool"] for step in result["steps"]],
            ["notes_replace", "tracks_set_pan"],
        )
        self.assertEqual(result["steps"][0]["args"]["track"], "Synth")
        self.assertEqual(result["steps"][1]["args"]["tracks"], ["Synth"])

    def test_shipped_riddim_bounce_writes_triplet_note_starts(self):
        from enableton.recipe_tools import default_store

        user_dir = Path(self.temp_dir.name) / "shipped_user"
        user_dir.mkdir()
        store = RecipeStore(default_store().shipped_dir, user_dir)
        result = apply_recipe(
            {
                "id": "riddim.bounce_140",
                "target": {
                    "track": "Drums",
                    "clip": "drums A",
                    "location": "session",
                    "slot": 0,
                },
            },
            store=store,
            adapter=self.adapter,
            cache=self.cache,
            plan_root=self.plan_root,
            catalogue=self.catalogue,
        )
        self.assertEqual(result["status"], "plan_ready")

        applied = run_tool(
            "ableton_plan_apply",
            {"plan_id": result["plan_id"]},
            self.adapter,
            catalogue=self.catalogue,
            cache=self.cache,
            plan_root=self.plan_root,
            backup_root=self.backup_root,
            transaction_root=self.transaction_root,
        )
        self.assertTrue(applied["applied"])
        clip = self.adapter.song.tracks[0].clip_slots[0].clip
        starts = sorted(note.start_time for note in clip.notes)
        self.assertEqual(len(starts), 14)
        # Grid 1/8T: twelve steps per bar, so a step is one third of a beat.
        for start in starts:
            self.assertAlmostEqual(start * 3, round(start * 3), places=4)
        # Several lanes share beat one, so probe for a third-beat hit rather than an index.
        self.assertTrue(any(abs(start - 1.0 / 3.0) < 1e-4 for start in starts))
        self.assertTrue(any(abs(start * 4 - round(start * 4)) > 0.01 for start in starts))

    def test_invalid_target_shape_is_a_bad_argument_not_a_plan(self):
        from enableton.protocol.codes import LiveError

        with self.assertRaises(LiveError) as ctx:
            self.compile(target={"track": "Drums"})
        self.assertEqual(ctx.exception.code, "BAD_ARGS")


if __name__ == "__main__":
    unittest.main()

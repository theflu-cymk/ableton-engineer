import math
import os
import tempfile
import unittest
import wave

import support  # noqa: F401
from enableton.live.fake import FakeAdapter
from enableton.producer import session_brief
from enableton.reference import reference_analyze
from enableton.state.snapshot import SnapshotCache
from enableton.takes import create_takes
from enableton.tools import run_tool
from enableton.protocol.codes import LiveError


class SessionBriefTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.snapshot = self.adapter.call("snapshot.get", {})

    def test_brief_maps_sections_roles_and_next_actions(self):
        brief = session_brief(self.snapshot)

        self.assertEqual(brief["status"], "available")
        self.assertEqual(brief["set"]["name"], "M0 Fake Set")
        self.assertEqual(brief["roles"], {"bass": 1, "drums": 1, "vocal": 1})
        self.assertEqual(brief["sections"][0]["label"], "Section 1")
        self.assertEqual(brief["sections"][1]["roles"], ["bass", "drums"])
        self.assertTrue(brief["next_actions"])
        self.assertIn("Roles:", brief["text"])

    def test_brief_can_omit_track_rows_and_echo_focus(self):
        brief = session_brief(self.snapshot, {"include_tracks": False, "focus": "second drop"})

        self.assertEqual(brief["tracks"], [])
        self.assertEqual(brief["focus"], "second drop")
        self.assertIn("Focus: second drop", brief["text"])

    def test_brief_excludes_return_buses_from_the_working_track_count(self):
        snapshot = {
            **self.snapshot,
            "tracks": list(self.snapshot["tracks"])
            + [{"index": 99, "name": "A-Reverb", "kind": "return", "arrangement": [], "session": {}}],
        }
        brief = session_brief(snapshot)

        self.assertEqual(brief["set"]["tracks"], 3)
        self.assertNotIn("A-Reverb", [track["name"] for track in brief["tracks"]])

    def test_brief_is_available_through_run_tool(self):
        result = run_tool("session_brief", {}, adapter=self.adapter)
        self.assertEqual(result["set"]["tempo"], 140.0)

    def test_unknown_argument_is_rejected(self):
        with self.assertRaises(Exception):
            session_brief(self.snapshot, {"nope": 1})


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = os.path.join(self.temp_dir.name, "ref.wav")
        self.other = os.path.join(self.temp_dir.name, "other.wav")

    def _write(self, path, values):
        with wave.open(path, "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"".join(
                value.to_bytes(2, "little", signed=True)
                for frame in values
                for value in frame
            ))

    def test_basic_measurements_and_flags(self):
        self._write(self.path, [(-32768, 32767), (0, 0)])
        result = reference_analyze({"path": self.path})

        profile = result["profile"]
        self.assertTrue(profile["measured"])
        self.assertEqual(profile["channels"], 2)
        self.assertAlmostEqual(profile["peak_dbfs"], 0.0)
        self.assertIsNotNone(profile["crest_db"])
        self.assertIn("near_clipping", profile["flags"])
        self.assertIn("advanced", profile)

    def test_reference_is_available_through_run_tool(self):
        self._write(self.path, [(-16384, 16384), (0, 0)])
        result = run_tool("reference_analyze", {"path": self.path}, adapter=None)
        self.assertTrue(result["profile"]["measured"])

    def test_comparison_reports_deltas_not_targets(self):
        self._write(self.path, [(-16384, 16384), (0, 0)])
        self._write(self.other, [(-8192, 8192), (0, 0)])
        result = reference_analyze({"path": self.path, "compare_to": self.other})

        comparison = result["comparison"]
        self.assertEqual(comparison["path"], self.other)
        self.assertIn("peak_dbfs", comparison["deltas"])
        self.assertGreater(comparison["deltas"]["peak_dbfs"], 0)

    def test_missing_file_is_a_clear_error(self):
        with self.assertRaisesRegex(Exception, "does not exist"):
            reference_analyze({"path": os.path.join(self.temp_dir.name, "missing.wav")})


class TakeTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.cache = SnapshotCache(self.adapter)

    def test_dry_run_plans_without_writing(self):
        before = len(self.adapter.song.tracks)
        result = create_takes(self.adapter, self.cache, {"track": "Drums", "count": 2})

        self.assertTrue(result["dry_run"])
        self.assertEqual(len(result["planned"]), 2)
        self.assertEqual(len(self.adapter.song.tracks), before)

    def test_apply_duplicates_names_and_isolates_take_one(self):
        result = create_takes(
            self.adapter, self.cache, {"track": "Drums", "count": 2, "dry_run": False}
        )

        self.assertFalse(result["dry_run"])
        self.assertEqual(result["active"], "Drums take 1")
        self.assertEqual(result["takes"][0]["volume"], 0.82)
        self.assertEqual(result["takes"][1]["volume"], 0.0)
        self.assertEqual(self.adapter.song.tracks[0].name, "Drums")
        self.assertEqual(self.adapter.song.tracks[0].volume, 0.0)
        self.assertEqual(self.adapter.song.tracks[1].name, "Drums take 1")
        self.assertEqual(self.adapter.song.tracks[1].volume, 0.82)

    def test_unknown_argument_is_rejected(self):
        with self.assertRaises(LiveError):
            create_takes(self.adapter, self.cache, {"track": "Drums", "bogus": 1})


if __name__ == "__main__":
    unittest.main()
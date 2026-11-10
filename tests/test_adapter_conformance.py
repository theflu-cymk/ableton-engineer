"""A single interface behind several backends (spec §18.6).

Every backend must pass this. The fake passes in M0; the Remote Script passes in M1; an
Extensions backend later, with no domain changes.
"""

import unittest

import support
from enableton.live.adapter import LiveAdapter
from enableton.live.fake import FakeAdapter, build_song


class ConformanceTests(unittest.TestCase):
    def test_fake_satisfies_the_interface(self):
        adapter = FakeAdapter()
        self.assertIsInstance(adapter, LiveAdapter)
        self.assertTrue(adapter.features)
        self.assertEqual(adapter.describe()["backend"], "fake")

    def test_reads_are_reads(self):
        adapter = FakeAdapter()
        snapshot = adapter.call("snapshot.get", {})
        for key in ("song", "tracks", "scenes", "locators", "counts", "captured"):
            self.assertIn(key, snapshot)
        tracks = adapter.call("track.list", {})
        self.assertEqual(tracks["total"], len(build_song().tracks))

    def test_writes_are_visible_after_apply(self):
        adapter = FakeAdapter()
        adapter.call("tracks.gain_stage", {"dry_run": False})
        after = adapter.call("track.list", {})
        drums = [t for t in after["items"] if t["name"] == "Drums"][0]
        self.assertLess(drums["volume"], 0.82)

    def test_preconditions_and_arguments_are_typed(self):
        from Enableton.errors import ScriptError

        adapter = FakeAdapter()
        with self.assertRaises(ScriptError) as ctx:
            adapter.call("tracks.gain_stage", {"tracks": ["Ghost"], "dry_run": True})
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

        with self.assertRaises(ScriptError) as ctx:
            adapter.call("snapshot.get", {"bogus": 1})
        self.assertEqual(ctx.exception.code, "BAD_ARGS")


if __name__ == "__main__":
    unittest.main()

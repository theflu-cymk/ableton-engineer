"""M1 read-path acceptance over a captured real Live snapshot.

The fixture is the snapshot returned by the running 12.2.5 bridge for ``fortnight*`` on
2026-11-10, not a FakeSong. The bridge itself was verified separately; this test guards the
report answers and the cache rule that four questions share one read.
"""

import json
import unittest
from pathlib import Path

import support  # noqa: F401
from enableton.state.snapshot import SnapshotCache
from enableton.tools import run_tool

FIXTURE = Path(__file__).with_name("fixtures") / "fortnight_snapshot.json"


class FixtureAdapter:
    """Serve the captured snapshot and count how often it is read."""

    features = frozenset({"levels", "snapshot"})

    def __init__(self, data):
        self.data = data
        self.calls = 0

    def call(self, cmd, args=None, timeout_ms=None):
        self.calls += 1
        if cmd != "snapshot.get":
            raise AssertionError("acceptance fixture only serves snapshot.get, not %r" % (cmd,))
        return self.data


class AcceptanceReadPathTests(unittest.TestCase):
    def test_four_questions_share_one_snapshot_and_match_the_real_set(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        adapter = FixtureAdapter(data)
        cache = SnapshotCache(adapter)

        structure = run_tool("inspect_structure", {}, adapter, cache=cache)
        unused = run_tool("inspect_unused", {}, adapter, cache=cache)
        headroom = run_tool("mix_headroom", {}, adapter, cache=cache)
        warp = run_tool("clips_warp_check", {}, adapter, cache=cache)

        # Structure: one section, 122 bars, the same 114 devices the live status reported.
        self.assertEqual(structure["bars"], 122)
        self.assertEqual(structure["sections"]["total"], 1)
        self.assertEqual(structure["signals"]["arrangement_clips"], 137)
        self.assertEqual(structure["signals"]["devices_total"], 114)

        # Unused material: six clip-less tracks, no empty scenes, 239 empty Session slots.
        self.assertEqual(len(unused["tracks_without_clips"]), 6)
        self.assertEqual(unused["scenes_without_clips"], [])
        self.assertEqual(unused["empty_session_slots"], 239)
        self.assertEqual(unused["total"], 8)

        # Mix: every fader readable, but peak headroom remains explicitly unmeasured.
        self.assertEqual(headroom["summary"]["tracks"], 34)
        self.assertEqual(headroom["summary"]["faders_measured"], 34)
        self.assertEqual(headroom["summary"]["fader_span_db"], {"min": -16.8, "max": 4.0})
        self.assertEqual(len(headroom["summary"]["muted"]), 20)
        self.assertEqual(headroom["summary"]["soloed"], [])
        self.assertFalse(headroom["headroom"]["measured"])
        self.assertEqual(headroom["headroom"]["requires"], "mix_meter_poll")

        # Warp: 58 audio clips and 487 markers, no flags.
        self.assertEqual(warp["summary"]["audio_clips"], 58)
        self.assertEqual(warp["summary"]["warp_markers"], 487)
        self.assertEqual(warp["summary"]["warping_on"], 15)
        self.assertEqual(warp["summary"]["warping_off"], 43)
        self.assertEqual(warp["summary"]["modes"], {"beats": 56, "complex": 1, "complex_pro": 1})
        self.assertEqual(warp["summary"]["flagged"], 0)

        # The whole point of the cache: one read for four answers.
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(len(cache.trace), 1)
        self.assertEqual(cache.trace[0]["tracks"], 32)
        self.assertEqual(cache.trace[0]["clips"], 250)


if __name__ == "__main__":
    unittest.main()

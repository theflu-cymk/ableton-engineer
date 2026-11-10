"""M3 diagnostics: stable findings, mode counts, ordering and autofix guards."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from enableton import diagnostics
from enableton.diagnostics import Finding
from enableton.live.fake import FakeAdapter, build_song
from enableton.manifest import load_manifest
from enableton.state.snapshot import SnapshotCache
from enableton.tools import run_tool


def track(index, name, volume=0.7, volume_str=None, clips=(), session=0, kind="audio"):
    return {
        "index": index,
        "name": name,
        "kind": kind,
        "volume": volume,
        "volume_str": volume_str,
        "mute": False,
        "solo": False,
        "devices": [],
        "session": {"filled": session, "clips": []},
        "arrangement": list(clips),
    }


def clip(name, midi=False, overlaps=(), truncated=False):
    return {
        "name": name,
        "start": 0.0,
        "end": 4.0,
        "length": 4.0,
        "midi": midi,
        "note_count": 2 if midi else None,
        "note_overlaps": list(overlaps),
        "note_overlaps_truncated": truncated,
    }


def snapshot(tracks, notes_available=False):
    return {
        "song": {"name": "test", "tempo": 120.0, "signature": [4, 4]},
        "tracks": list(tracks),
        "counts": {"tracks": len(tracks)},
        "captured": {"notes_available": notes_available},
    }


PAIR = {
    "pitch": 60,
    "first": {"start": 0.0, "duration": 1.0, "velocity": 100, "mute": False},
    "second": {"start": 0.5, "duration": 1.0, "velocity": 90, "mute": False},
    "overlap": 0.5,
}


class DiagnosticsReportTests(unittest.TestCase):
    def data(self):
        return snapshot([
            track(0, "A", volume=1.0, volume_str=None,
                  clips=[clip("midi", midi=True, overlaps=[PAIR])]),
            track(1, "B", volume=0.7),
            track(2, "A", volume=0.7, clips=[clip("audio")]),
        ], notes_available=True)

    def test_detects_each_supported_finding_and_counts_modes(self):
        findings = diagnostics.detect(self.data(), "standard")
        kinds = {finding.kind for finding in findings}

        self.assertEqual(kinds, {
            "hygiene.empty_track",
            "hygiene.duplicate_track_name",
            "mix.fader_above_unity",
            "notes.overlap",
        })
        counts = diagnostics.counts(findings)
        self.assertEqual(counts["total"], 4)
        self.assertEqual(counts["by_mode"], {"auto": 1, "inspect": 3})
        self.assertEqual(counts["needs_listening"], 1)
        self.assertEqual(counts["auto_fixable"], 1)

    def test_ids_are_stable_and_findings_are_phase_ordered(self):
        first = diagnostics.detect(self.data(), "standard")
        second = diagnostics.detect(self.data(), "standard")
        self.assertEqual([f.id for f in first], [f.id for f in second])
        self.assertEqual([diagnostics.PHASE_ORDER[f.phase] for f in first],
                         sorted(diagnostics.PHASE_ORDER[f.phase] for f in first))

    def test_tiers_are_honest_about_what_they_read(self):
        data = self.data()
        fast = diagnostics.run(data, {"tier": "fast"})
        standard = diagnostics.run(data, {"tier": "standard"})

        self.assertEqual(fast["counts"]["total"], 2)
        self.assertEqual(standard["counts"]["total"], 4)
        self.assertEqual(standard["unavailable"], [])
        json.dumps(standard)  # the CLI and MCP layer must be able to encode this
        self.assertIsInstance(standard["findings"][0], dict)

    def test_missing_note_data_is_unavailable_with_a_reason(self):
        result = diagnostics.run(snapshot([track(0, "A", clips=[clip("midi", midi=True)])]),
                                 {"tier": "standard"})
        self.assertEqual(result["counts"]["total"], 0)
        self.assertEqual(len(result["unavailable"]), 1)
        self.assertIn("note", result["unavailable"][0]["capability"])
        self.assertTrue(result["unavailable"][0]["reason"])

    def test_report_filters_without_hiding_the_unfiltered_count(self):
        result = diagnostics.report(self.data(), {"needs_listening": True})
        self.assertEqual(result["counts"]["total"], 4)
        self.assertEqual(result["filtered_total"], 1)
        self.assertEqual(result["items"][0]["kind"], "notes.overlap")

    def test_get_rejects_an_unknown_id(self):
        with self.assertRaises(diagnostics.DiagnosticsError):
            diagnostics.get(self.data(), {"id": "f_missing"})

    def test_bad_arguments_are_rejected(self):
        data = self.data()
        for args in ({"tier": "warp"}, {"limit": 0}, {"offset": -1}, {"bogus": 1}):
            with self.assertRaises(diagnostics.DiagnosticsError, msg=repr(args)):
                diagnostics.run(data, args)


class DiagnosticsPlanTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = load_manifest()
        self.hygiene = Finding(
            id="f_hygiene", kind="test.hygiene", severity="info", confidence=1.0,
            title="hygiene", evidence={}, location={}, objective="", phase="hygiene",
            mode="auto", needs_listening=False,
            fix={"tool": "clips_duplicate_range", "args": {
                "tracks": ["A"], "from_bar": 1, "to_bar": 2, "destination_bar": 3,
            }},
        )
        self.gain = Finding(
            id="f_gain", kind="test.gain", severity="info", confidence=1.0,
            title="gain", evidence={}, location={}, objective="", phase="gain",
            mode="auto", needs_listening=False,
            fix={"tool": "tracks_set_volume", "args": {"tracks": ["A"], "volume": 0.85}},
        )

    def test_plan_is_phase_ordered_and_bounded(self):
        plan = diagnostics._build_plan([self.gain, self.hygiene], self.catalogue)
        self.assertEqual([step["phase"] for step in plan["steps"]], ["hygiene", "gain"])
        self.assertEqual([step["n"] for step in plan["steps"]], [1, 2])

    def test_needs_listening_is_listed_but_never_a_step(self):
        listening = Finding(
            id="f_ear", kind="test.ear", severity="warn", confidence=1.0,
            title="ear", evidence={}, location={}, objective="", phase="notes",
            mode="inspect", needs_listening=True,
            fix={"tool": "tracks_set_volume", "args": {"tracks": ["A"], "volume": 0.85}},
        )
        plan = diagnostics._build_plan([listening], self.catalogue)
        self.assertEqual(plan["steps"], [])
        self.assertEqual(plan["needs_listening"][0]["finding_id"], "f_ear")

    def test_missing_fix_tool_is_unavailable_not_silently_dropped(self):
        data = snapshot([track(0, "empty")])
        result = diagnostics.plan(data, {}, self.catalogue)
        self.assertEqual(result["steps"], [])
        self.assertEqual(result["unavailable"][0]["tool"], "tracks_clean_empty")
        self.assertIn("not implemented", result["unavailable"][0]["reason"])


class AutofixTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.root), True)
        self.source = self.root / "scratch.als"
        self.source.write_bytes(b"original set bytes")
        self.adapter = FakeAdapter()
        self.adapter.song.file_path = str(self.source)
        self.adapter.song.tracks[0].volume = 1.0
        self.cache = SnapshotCache(self.adapter)
        self.catalogue = load_manifest()

    def test_dry_run_writes_nothing_and_matches_the_apply_plan(self):
        before = self.adapter.song.tracks[0].volume
        preview = diagnostics.autofix(
            self.adapter, self.cache, {"dry_run": True}, self.catalogue,
            backup_root=str(self.root / "backups"),
        )
        self.assertTrue(preview["dry_run"])
        self.assertFalse(preview["applied"])
        self.assertEqual(preview["plan"]["steps"][0]["tool"], "tracks_set_volume")
        self.assertEqual(self.adapter.song.tracks[0].volume, before)
        self.assertFalse(self.backups_exists())

        applied = diagnostics.autofix(
            self.adapter, self.cache, {"dry_run": False}, self.catalogue,
            backup_root=str(self.root / "backups"),
        )
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["counts_after"]["total"] < applied["counts_before"]["total"],
                         True)
        self.assertAlmostEqual(self.adapter.song.tracks[0].volume, 0.85)
        self.assertTrue(Path(applied["scratch_copy"]).is_file())

    def backups_exists(self):
        return any(self.root.rglob("backups"))

    def test_autofix_stops_when_the_finding_count_rises(self):
        def detector(data):
            if data["tracks"][0]["volume"] > 0.85:
                return [self.fix_finding()]
            return [self.fix_finding(), self.regression_finding()]

        result = diagnostics.autofix(
            self.adapter, self.cache, {"dry_run": False}, self.catalogue,
            backup_root=str(self.root / "backups"),
            detectors=[detector],
        )

        self.assertEqual(result["stopped"], "finding_count_rose")
        self.assertEqual(result["counts_before"]["total"], 1)
        self.assertEqual(result["counts_after_change"]["total"], 2)
        self.assertEqual(result["counts_after"]["total"], 1)
        self.assertTrue(result["rolled_back"])
        self.assertAlmostEqual(self.adapter.song.tracks[0].volume, 1.0)

    def fix_finding(self):
        return Finding(
            id="f_fix", kind="test.fix", severity="info", confidence=1.0,
            title="fix me", evidence={}, location={}, objective="", phase="gain",
            mode="auto", needs_listening=False,
            fix={"tool": "tracks_set_volume", "args": {"tracks": ["Drums"], "volume": 0.85}},
        )

    def regression_finding(self):
        return Finding(
            id="f_regression", kind="test.regression", severity="warn", confidence=1.0,
            title="do not auto-apply", evidence={}, location={}, objective="", phase="gain",
            mode="inspect", needs_listening=True,
        )

    def test_a_later_phase_failure_rolls_back_earlier_phases(self):
        class FailVolumeApply(FakeAdapter):
            def call(self, cmd, args=None, timeout_ms=None):
                args = args or {}
                if cmd == "tracks.set_volume" and not args.get("dry_run", True):
                    raise RuntimeError("synthetic volume failure")
                return super().call(cmd, args, timeout_ms=timeout_ms)

        adapter = FailVolumeApply(self.adapter.song)
        before = len(adapter.song.tracks[0].arrangement_clips)
        hygiene = Finding(
            id="f_dup", kind="test.dup", severity="info", confidence=1.0,
            title="duplicate", evidence={}, location={}, objective="", phase="hygiene",
            mode="auto", needs_listening=False,
            fix={"tool": "clips_duplicate_range", "args": {
                "tracks": ["Drums"], "from_bar": 1, "to_bar": 2, "destination_bar": 5,
            }},
        )
        result = diagnostics.autofix(
            adapter, SnapshotCache(adapter), {"dry_run": False}, self.catalogue,
            backup_root=str(self.root / "backups"),
            detectors=[lambda data: [hygiene, self.fix_finding()]],
        )

        self.assertEqual(result["stopped"], "apply_failed")
        self.assertTrue(result["rolled_back"])
        self.assertFalse(result["applied"])
        self.assertEqual(len(adapter.song.tracks[0].arrangement_clips), before)
        self.assertAlmostEqual(adapter.song.tracks[0].volume, 1.0)

    def test_an_error_finding_rolls_back_the_phases_already_applied(self):
        before = len(self.adapter.song.tracks[0].arrangement_clips)
        hygiene = Finding(
            id="f_dup", kind="test.dup", severity="info", confidence=1.0,
            title="duplicate", evidence={}, location={}, objective="", phase="hygiene",
            mode="auto", needs_listening=False,
            fix={"tool": "clips_duplicate_range", "args": {
                "tracks": ["Drums"], "from_bar": 1, "to_bar": 2, "destination_bar": 5,
            }},
        )
        blocker = Finding(
            id="f_error", kind="test.blocker", severity="error", confidence=1.0,
            title="blocks gain", evidence={}, location={}, objective="", phase="gain",
            mode="inspect", needs_listening=True,
        )
        result = diagnostics.autofix(
            self.adapter, SnapshotCache(self.adapter), {"dry_run": False}, self.catalogue,
            backup_root=str(self.root / "backups"),
            detectors=[lambda data: [hygiene, blocker]],
        )

        self.assertEqual(result["stopped"], "error_finding_blocks_phase")
        self.assertTrue(result["rolled_back"])
        self.assertFalse(result["applied"])
        self.assertEqual(len(self.adapter.song.tracks[0].arrangement_clips), before)

    def test_needs_listening_is_never_applied_even_if_it_has_a_fix(self):
        listening = Finding(
            id="f_ear", kind="test.ear", severity="warn", confidence=1.0,
            title="listen", evidence={}, location={}, objective="", phase="gain",
            mode="inspect", needs_listening=True,
            fix={"tool": "tracks_set_volume", "args": {"tracks": ["Drums"], "volume": 0.85}},
        )
        result = diagnostics.autofix(
            self.adapter, self.cache, {"dry_run": False}, self.catalogue,
            detectors=[lambda data: [listening]],
        )

        self.assertFalse(result["applied"])
        self.assertEqual(result["steps"], [])
        self.assertEqual(self.adapter.song.tracks[0].volume, 1.0)


class VolumeToolTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.adapter.song.tracks[0].volume = 1.0

    def test_dry_run_apply_and_restore_are_exact(self):
        preview = self.adapter.call("tracks.set_volume", {
            "tracks": ["Drums"], "volume": 0.85,
        })
        self.assertTrue(preview["dry_run"])
        self.assertEqual(self.adapter.song.tracks[0].volume, 1.0)
        self.assertEqual(preview["changes"][0]["to"], 0.85)

        applied = self.adapter.call("tracks.set_volume", {
            "tracks": ["Drums"], "volume": 0.85, "dry_run": False,
        })
        self.assertAlmostEqual(self.adapter.song.tracks[0].volume, 0.85)
        self.assertEqual(len(applied["undo"]), 1)

        restored = self.adapter.call("tracks.set_volume", {
            "restore": applied["undo"], "dry_run": False,
        })
        self.assertEqual(restored["restored"], 1)
        self.assertAlmostEqual(self.adapter.song.tracks[0].volume, 1.0)

    def test_unknown_track_is_rejected_without_a_partial_write(self):
        from Enableton.errors import ScriptError

        with self.assertRaises(ScriptError) as ctx:
            self.adapter.call("tracks.set_volume", {
                "tracks": ["Drums", "Missing"], "volume": 0.5, "dry_run": False,
            })
        self.assertEqual(ctx.exception.code, "NOT_FOUND")
        self.assertEqual(self.adapter.song.tracks[0].volume, 1.0)


class ToolRouterDiagnosticsTests(unittest.TestCase):
    def test_status_carries_counts_from_the_same_snapshot(self):
        adapter = FakeAdapter()
        result = run_tool("ableton_status", {}, adapter)
        self.assertEqual(result["findings"]["by_mode"]["inspect"], 2)
        self.assertEqual(result["findings"]["total"], 2)

    def test_inspect_tools_are_routed_locally(self):
        adapter = FakeAdapter()
        run = run_tool("inspect_run", {}, adapter)
        self.assertEqual(run["counts"]["total"], 2)
        json.dumps(run)
        plan = run_tool("inspect_plan", {}, adapter)
        self.assertEqual(plan["total"], 0)
        self.assertTrue(plan["unavailable"])


if __name__ == "__main__":
    unittest.main()

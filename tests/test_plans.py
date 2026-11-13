import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import support  # noqa: F401
from enableton.escalation import apply_plan, escalate
from enableton.live.fake import FakeAdapter
from enableton.manifest import load_manifest
from enableton.plans import PlanStore, PlanStoreError
from enableton.protocol.codes import LiveError
from enableton.state.snapshot import SnapshotCache
from enableton.tools import run_tool


class PlanStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.root), True)
        self.steps = [{"n": 1, "tool": "tracks_set_volume", "args": {"volume": 0.85}}]

    def test_create_get_discard_and_expiry(self):
        now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        store = PlanStore(root=str(self.root), clock=lambda: now, ttl_s=600)
        plan = store.create("test", self.steps)
        self.assertEqual(store.get(plan["plan_id"])["intent"], "test")
        self.assertTrue(store.discard(plan["plan_id"]))
        with self.assertRaises(PlanStoreError):
            store.get(plan["plan_id"])

        later = now + timedelta(seconds=601)
        expired = PlanStore(root=str(self.root), clock=lambda: later, ttl_s=600)
        plan = store.create("expire me", self.steps)
        with self.assertRaises(PlanStoreError) as ctx:
            expired.get(plan["plan_id"])
        self.assertIn("expired", str(ctx.exception))

    def test_bad_plan_ids_are_rejected(self):
        store = PlanStore(root=str(self.root))
        for bad in ("../x", "p_xyz", "p_0123abcd\n", ""):
            with self.assertRaises(PlanStoreError, msg=repr(bad)):
                store.get(bad)


class EscalationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.root), True)
        self.adapter = FakeAdapter()
        self.source = self.root / "scratch.als"
        self.source.write_bytes(b"scratch")
        self.adapter.song.file_path = str(self.source)
        self.adapter.song.tracks[0].volume = 1.0
        self.plan_root = str(self.root / "plans")
        self.catalogue = load_manifest()

    def test_escalate_then_apply_uses_a_stored_plan(self):
        plan = run_tool("ableton_escalate", {"intent": "gain"}, self.adapter,
                        plan_root=self.plan_root)
        self.assertTrue(plan["plan_id"].startswith("p_"))
        self.assertEqual([step["tool"] for step in plan["steps"]], ["tracks_set_volume"])
        self.assertEqual(plan["effects"]["tracks"], 1)
        self.assertEqual(plan["needs_listening"], [])
        self.assertEqual(plan["counts"]["by_mode"]["auto"], 1)

        applied = run_tool(
            "ableton_plan_apply", {"plan_id": plan["plan_id"]}, self.adapter,
            plan_root=self.plan_root, backup_root=str(self.root / "backups"),
            transaction_root=str(self.root / "transactions"),
        )
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["counts_before"]["total"], 3)
        self.assertEqual(applied["counts_after"]["total"], 2)
        self.assertAlmostEqual(self.adapter.song.tracks[0].volume, 0.85)
        self.assertTrue(applied["discarded"])

        store = PlanStore(root=self.plan_root)
        with self.assertRaises(PlanStoreError):
            store.get(plan["plan_id"])

    def test_unmatched_intent_is_not_fabricated(self):
        result = run_tool("ableton_escalate", {"intent": "warp markers"},
                          self.adapter, plan_root=self.plan_root)
        self.assertIsNone(result["plan_id"])
        self.assertEqual(result["steps"], [])
        self.assertIn("nothing was fabricated", result["reason"])

    def test_explicit_steps_are_preflighted_and_stored(self):
        plan = run_tool(
            "ableton_escalate",
            {
                "intent": "widen the drums",
                "steps": [
                    {"tool": "tracks_set_volume",
                     "args": {"tracks": ["Drums"], "volume": 0.8},
                     "why": "balance"},
                    {"tool": "tracks_set_pan",
                     "args": {"tracks": ["Drums"], "pan": -0.2},
                     "why": "width"},
                ],
            },
            self.adapter,
            plan_root=self.plan_root,
        )
        self.assertTrue(plan["plan_id"].startswith("p_"))
        self.assertTrue(plan["explicit_steps"])
        self.assertEqual(
            [step["tool"] for step in plan["steps"]],
            ["tracks_set_volume", "tracks_set_pan"],
        )
        self.assertEqual(plan["steps"][0]["why"], "balance")
        self.assertTrue(plan["preflight"]["ran"])
        self.assertEqual(len(plan["preflight"]["trace"]), 2)
        self.assertEqual(self.adapter.song.tracks[0].volume, 1.0)
        self.assertEqual(self.adapter.song.tracks[0].pan, 0.0)

        applied = run_tool(
            "ableton_plan_apply", {"plan_id": plan["plan_id"]}, self.adapter,
            plan_root=self.plan_root, backup_root=str(self.root / "backups"),
            transaction_root=str(self.root / "transactions"),
        )
        self.assertTrue(applied["applied"])
        self.assertAlmostEqual(self.adapter.song.tracks[0].volume, 0.8)
        self.assertAlmostEqual(self.adapter.song.tracks[0].pan, -0.2)

    def test_explicit_steps_reject_unsafe_or_unknown_tools(self):
        cases = [
            ([{"tool": "tracks_list", "args": {}}], "read-only"),
            ([{"tool": "devices_delete", "args": {
                "track": "Drums", "device": "EQ Eight", "confirm": True,
            }}], "not reversible"),
            ([{"tool": "not_a_tool", "args": {}}], "unknown tool"),
            ([{"tool": "tracks_set_volume", "args": {
                "volume": 0.8, "dry_run": True,
            }}], "must not set dry_run"),
        ]
        for steps, text in cases:
            with self.subTest(text=text):
                with self.assertRaises(LiveError) as ctx:
                    run_tool("ableton_escalate", {"steps": steps}, self.adapter,
                             plan_root=self.plan_root)
                self.assertEqual(ctx.exception.code, "BAD_ARGS")
                self.assertIn(text, ctx.exception.message)

    def test_explicit_steps_are_bounded_and_preflighted(self):
        too_many = [
            {"tool": "tracks_set_volume", "args": {"volume": 0.9}}
            for _ in range(13)
        ]
        with self.assertRaises(LiveError) as ctx:
            run_tool("ableton_escalate", {"steps": too_many}, self.adapter,
                     plan_root=self.plan_root)
        self.assertIn("limited to 12", ctx.exception.message)

        with self.assertRaises(LiveError) as ctx:
            run_tool(
                "ableton_escalate",
                {"steps": [{"tool": "tracks_set_volume",
                            "args": {"volume": 1.5}}]},
                self.adapter,
                plan_root=self.plan_root,
            )
        self.assertIn("preflight failed", ctx.exception.message)

    def test_discard_removes_the_plan(self):
        plan = run_tool("ableton_escalate", {"intent": "gain"}, self.adapter,
                        plan_root=self.plan_root)
        result = run_tool("ableton_plan_discard", {"plan_id": plan["plan_id"]},
                          self.adapter, plan_root=self.plan_root)
        self.assertTrue(result["discarded"])
        with self.assertRaises(LiveError):
            run_tool("ableton_plan_apply", {"plan_id": plan["plan_id"]},
                     self.adapter, plan_root=self.plan_root)

    def test_apply_failure_restores_and_keeps_the_plan(self):
        class FailVolumeApply(FakeAdapter):
            def call(self, cmd, args=None, timeout_ms=None):
                args = args or {}
                if cmd == "tracks.set_volume" and not args.get("dry_run", True):
                    raise RuntimeError("synthetic volume failure")
                return super().call(cmd, args, timeout_ms=timeout_ms)

        adapter = FailVolumeApply(self.adapter.song)
        before = len(adapter.song.tracks[0].arrangement_clips)
        store = PlanStore(root=self.plan_root)
        plan = store.create("failure probe", [
            {"n": 1, "tool": "clips_duplicate_range", "args": {
                "tracks": ["Drums"], "from_bar": 1, "to_bar": 2, "destination_bar": 5,
            }},
            {"n": 2, "tool": "tracks_set_volume", "args": {
                "tracks": ["Drums"], "volume": 0.85,
            }},
        ])
        result = apply_plan(
            adapter, SnapshotCache(adapter), {"plan_id": plan["plan_id"]}, store,
            self.catalogue, backup_root=str(self.root / "backups"),
            transaction_root=str(self.root / "transactions"),
        )
        self.assertFalse(result["applied"])
        self.assertIn("error", result)
        self.assertTrue(result["restore"]["ok"])
        self.assertEqual(len(adapter.song.tracks[0].arrangement_clips), before)
        self.assertEqual(store.get(plan["plan_id"])["plan_id"], plan["plan_id"])


if __name__ == "__main__":
    unittest.main()

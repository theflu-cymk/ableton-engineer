import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import support  # noqa: F401
from enableton.live.fake import FakeAdapter, FakeLocator
from enableton.plans.transactions import TransactionStore, TransactionStoreError
from enableton.protocol.codes import LiveError
from enableton.tools import run_tool


class TransactionStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.root), True)
        self.now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)

    def test_record_get_clear_and_empty(self):
        store = TransactionStore(root=str(self.root), clock=lambda: self.now)
        self.assertIsNone(store.record("/tmp/a.als", []))
        record = store.record("/tmp/a.als", [
            {"tool": "tracks_set_volume", "cmd": "tracks.set_volume",
             "undo": [{"track": "Drums", "volume": 0.82}]},
        ])
        self.assertEqual(store.get()["entries"], record["entries"])
        self.assertTrue(store.clear())
        with self.assertRaises(TransactionStoreError) as ctx:
            store.get()
        self.assertIn("no applied transaction", str(ctx.exception))

    def test_the_record_expires_after_ten_minutes(self):
        store = TransactionStore(root=str(self.root), clock=lambda: self.now)
        store.record("/tmp/a.als", [
            {"tool": "tracks_set_volume", "cmd": "tracks.set_volume",
             "undo": [{"track": "Drums", "volume": 0.82}]},
        ])
        later = TransactionStore(
            root=str(self.root), clock=lambda: self.now + timedelta(seconds=601)
        )
        with self.assertRaises(TransactionStoreError) as ctx:
            later.get()
        self.assertIn("expired", str(ctx.exception))


class UndoToolTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.root), True)
        self.adapter = FakeAdapter()
        source = self.root / "scratch.als"
        source.write_bytes(b"scratch")
        self.adapter.song.file_path = str(source)
        self.backups = str(self.root / "backups")
        self.transactions = str(self.root / "transactions")

    def _apply(self):
        return run_tool(
            "tracks_set_volume",
            {"tracks": ["Drums"], "volume": 0.5, "dry_run": False},
            self.adapter,
            backup_root=self.backups,
            transaction_root=self.transactions,
        )

    def test_undo_restores_the_last_write(self):
        before = self.adapter.song.tracks[0].volume
        self._apply()
        self.assertAlmostEqual(self.adapter.song.tracks[0].volume, 0.5)

        undone = run_tool(
            "ableton_undo", {}, self.adapter, transaction_root=self.transactions
        )
        self.assertTrue(undone["ok"], undone)
        self.assertEqual(undone["restored"], 1)
        self.assertAlmostEqual(self.adapter.song.tracks[0].volume, before)

    def test_undo_moves_a_section_back(self):
        self.adapter.song.locators = [FakeLocator("intro", 0.0), FakeLocator("drop", 16.0)]
        applied = run_tool(
            "sections_move",
            {"bar": 1, "to_bar": 9, "dry_run": False},
            self.adapter,
            backup_root=self.backups,
            transaction_root=self.transactions,
        )
        self.assertEqual(applied["moved"]["to_bar"], 9.0)
        self.assertEqual(
            [(locator.name, locator.time) for locator in self.adapter.song.locators],
            [("drop", 16.0), ("intro", 32.0)],
        )

        undone = run_tool(
            "ableton_undo", {}, self.adapter, transaction_root=self.transactions
        )
        self.assertTrue(undone["ok"], undone)
        self.assertEqual(
            [(locator.name, locator.time) for locator in self.adapter.song.locators],
            [("intro", 0.0), ("drop", 16.0)],
        )

    def test_create_and_delete_survive_the_executor_trace_check(self):
        created = run_tool(
            "sections_create_locators",
            {"sections": [{"name": "gate", "bar": 2}], "dry_run": False},
            self.adapter,
            backup_root=self.backups,
            transaction_root=self.transactions,
        )
        self.assertEqual(created["created"][0]["time"], 4.0)
        self.assertEqual(
            [(locator.name, locator.time) for locator in self.adapter.song.locators],
            [("gate", 4.0)],
        )

        deleted = run_tool(
            "sections_delete",
            {"names": ["gate"], "dry_run": False},
            self.adapter,
            backup_root=self.backups,
            transaction_root=self.transactions,
        )
        self.assertEqual(deleted["deleted"], 1)
        self.assertEqual(self.adapter.song.locators, [])

    def test_nothing_to_undo_is_a_precondition(self):
        with self.assertRaises(LiveError) as ctx:
            run_tool(
                "ableton_undo", {}, self.adapter, transaction_root=self.transactions
            )
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")

    def test_a_transaction_from_another_set_is_refused(self):
        self._apply()
        self.adapter.song.file_path = str(self.root / "other.als")
        with self.assertRaises(LiveError) as ctx:
            run_tool(
                "ableton_undo", {}, self.adapter, transaction_root=self.transactions
            )
        self.assertEqual(ctx.exception.code, "PRECONDITION_FAILED")
        self.assertIn("not undone", str(ctx.exception))
        self.assertAlmostEqual(self.adapter.song.tracks[0].volume, 0.5)


if __name__ == "__main__":
    unittest.main()

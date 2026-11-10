"""The snapshot cache, and the one-round-trip promise.

The reports are pure functions of the payload, so these tests care about two things only: how
many times Live is asked, and whether the answer survives an invalidation correctly.
"""

import unittest

import support  # noqa: F401
from enableton.live.fake import FakeAdapter
from enableton.state.snapshot import SnapshotCache


class CountingAdapter(FakeAdapter):
    def __init__(self, song=None):
        super().__init__(song)
        self.calls = 0

    def call(self, cmd, args=None, timeout_ms=None):
        self.calls += 1
        return super().call(cmd, args, timeout_ms)


class SnapshotCacheTests(unittest.TestCase):
    def test_two_reads_cost_one_round_trip(self):
        adapter = CountingAdapter()
        cache = SnapshotCache(adapter)

        first = cache.get()
        second = cache.get()

        self.assertIs(first, second)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(cache.trace[-1]["cmd"], "snapshot.get")
        self.assertEqual(cache.trace[-1]["tracks"], 3)

    def test_invalidate_forces_a_refetch(self):
        adapter = CountingAdapter()
        cache = SnapshotCache(adapter)

        cache.get()
        cache.invalidate()
        cache.get()

        self.assertEqual(adapter.calls, 2)
        self.assertEqual(cache.epoch, 1)

    def test_age_is_a_backstop_not_the_mechanism(self):
        now = [0.0]
        adapter = CountingAdapter()
        cache = SnapshotCache(adapter, max_age_s=10.0, clock=lambda: now[0])

        cache.get()
        now[0] = 5.0
        cache.get()
        self.assertEqual(adapter.calls, 1, "a fresh snapshot must be reused")

        now[0] = 11.0
        cache.get()
        self.assertEqual(adapter.calls, 2, "past the age limit it must be re-read")

    def test_refresh_bypasses_a_fresh_snapshot(self):
        adapter = CountingAdapter()
        cache = SnapshotCache(adapter)

        cache.get()
        cache.get(refresh=True)

        self.assertEqual(adapter.calls, 2)

    def test_trace_records_cost_and_size(self):
        adapter = CountingAdapter()
        cache = SnapshotCache(adapter)
        cache.get()

        entry = cache.trace[0]
        self.assertIn("ms", entry)
        self.assertEqual(entry["clips"], 5)  # 3 arrangement, 2 session
        self.assertEqual(entry["epoch"], 0)


if __name__ == "__main__":
    unittest.main()

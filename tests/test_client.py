import socket
import threading
import time
import unittest

import support
from enableton.live.fake import FakeAdapter
from enableton.protocol.client import LiveClient
from enableton.protocol.codes import LiveError


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.server = support.fake_server()
        self.addCleanup(self.server.stop)
        self.client = LiveClient(port=self.server.port, default_timeout_ms=2000)
        self.client.connect()
        self.addCleanup(self.client.close)

    def test_handshake(self):
        info = self.client.handshake()
        self.assertEqual(info["protocol"], 1)
        self.assertIn("levels", info["features"])

    def test_status_over_the_wire(self):
        result = self.client.call("snapshot.get", {}, timeout_ms=2000)
        self.assertEqual(result["song"]["name"], "M0 Fake Set")
        self.assertEqual(result["counts"]["tracks"], 3)
        self.assertEqual(result["song"]["signature"], [4, 4])
        self.assertFalse(result["song"]["is_playing"])

    def test_paging(self):
        page = self.client.call("track.list", {"offset": 1, "limit": 1})
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["items"][0]["name"], "Bass layer")
        self.assertEqual(page["next_offset"], 2)
        self.assertEqual(page["total"], 3)

    def test_last_page_has_no_next_offset(self):
        page = self.client.call("track.list", {"offset": 2, "limit": 10})
        self.assertIsNone(page["next_offset"])

    def test_gain_stage_is_dry_by_default(self):
        result = self.client.call("tracks.gain_stage", {})
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["skipped"], ["Vocal chop"])  # no measured peak
        self.assertEqual([c["track"] for c in result["changes"]], ["Drums", "Bass layer"])
        # Dry run must not have changed anything.
        after = self.client.call("track.list", {})
        drums = [t for t in after["items"] if t["name"] == "Drums"][0]
        self.assertAlmostEqual(drums["volume"], 0.82, places=4)

    def test_gain_stage_apply_changes_levels(self):
        result = self.client.call("tracks.gain_stage", {"dry_run": False, "headroom_db": -6})
        self.assertFalse(result["dry_run"])
        after = self.client.call("track.list", {})
        drums = [t for t in after["items"] if t["name"] == "Drums"][0]
        self.assertLess(drums["volume"], 0.82)

    def test_unknown_command_is_typed(self):
        with self.assertRaises(LiveError) as ctx:
            self.client.call("song.teleport", {})
        self.assertEqual(ctx.exception.code, "UNKNOWN_COMMAND")

    def test_bad_args_are_typed(self):
        with self.assertRaises(LiveError) as ctx:
            self.client.call("track.list", {"limit": 0})
        self.assertEqual(ctx.exception.code, "BAD_ARGS")

    def test_not_found_is_typed(self):
        with self.assertRaises(LiveError) as ctx:
            self.client.call("tracks.gain_stage", {"tracks": ["Nope"]})
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

    def test_timeout_is_typed(self):
        silent = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)
        port = silent.getsockname()[1]
        self.addCleanup(silent.close)

        def accept_and_hang():
            conn, _ = silent.accept()
            time.sleep(3.0)
            conn.close()

        threading.Thread(target=accept_and_hang, daemon=True).start()

        client = LiveClient(port=port)
        client.connect()
        self.addCleanup(client.close)
        with self.assertRaises(LiveError) as ctx:
            client.call("snapshot.get", {}, timeout_ms=100)
        self.assertEqual(ctx.exception.code, "TIMEOUT")

    def test_connect_failure_is_typed(self):
        client = LiveClient(port=1)  # nothing listens here
        with self.assertRaises(LiveError) as ctx:
            client.connect(timeout=0.5)
        self.assertEqual(ctx.exception.code, "DISCONNECTED")

    def test_disconnected_is_typed(self):
        self.client.close()
        with self.assertRaises(LiveError) as ctx:
            self.client.call("snapshot.get", {})
        self.assertEqual(ctx.exception.code, "DISCONNECTED")


class FakeAdapterTests(unittest.TestCase):
    def test_adapter_runs_handlers_in_process(self):
        adapter = FakeAdapter()
        self.assertEqual(adapter.call("snapshot.get", {})["song"]["name"], "M0 Fake Set")
        self.assertIn("levels", adapter.features)
        self.assertEqual(adapter.describe()["backend"], "fake")


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import threading
import unittest
from http.client import HTTPConnection

import support  # noqa: F401 - puts src and remote_script on sys.path
from enableton.live.fake import FakeAdapter
from enableton.panel import PANEL_HOST, PanelHTTPServer, PanelService, run_panel
from enableton.protocol.codes import LiveError


def healthy_status():
    return {
        "connected": True,
        "host": "127.0.0.1",
        "port": 9878,
        "protocol": 1,
        "live": "12.2.5",
        "script": "0.4.26",
        "build": "fake-build",
        "queued": 0,
        "stats": {"drains": 4, "ran": 4, "errors": 0, "display": 4, "super_errors": 0},
    }


def offline_status():
    return {
        "connected": False,
        "host": "127.0.0.1",
        "port": 9878,
        "code": "DISCONNECTED",
        "error": "could not reach Live: connection refused",
    }


class BrokenAdapter:
    features = frozenset()

    def call(self, cmd, args=None, timeout_ms=None):
        raise LiveError("DISCONNECTED", "not connected to Live")

    def describe(self):
        return {"backend": "broken", "features": []}


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.service = PanelService(adapter=self.adapter, status_provider=healthy_status)
        self.server, self.thread, self.port = self._start(self.service)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)
        self.service.close()

    def _start(self, service):
        server = PanelHTTPServer((PANEL_HOST, 0), service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, server.server_address[1]

    def _request(self, method, path, payload=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3.0)
        body = None if payload is None else json.dumps(payload)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw.decode("utf-8"))

    def test_status_is_doctor_as_json(self):
        status, payload = self._request("GET", "/api/status")

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["status"]["connected"])
        self.assertEqual(payload["status"]["live"], "12.2.5")
        self.assertEqual(payload["status"]["script"], "0.4.26")
        self.assertEqual(payload["status"]["build"], "fake-build")
        self.assertTrue(payload["status"]["panel"]["loopback"])

    def test_session_and_snapshot_endpoints_use_the_fake_bridge(self):
        status, session = self._request("GET", "/api/session")
        self.assertEqual(status, 200)
        self.assertIn("title", session["session"])
        self.assertTrue(session["session"]["sections"])

        status, tracks = self._request("GET", "/api/tracks")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(tracks["tracks"]), 3)
        self.assertIn("mute", tracks["tracks"][0])
        self.assertIn("solo", tracks["tracks"][0])
        self.assertIn("arm", tracks["tracks"][0])
        self.assertEqual(tracks["tracks"][0]["restore_kind"], "track")

        status, takes = self._request("GET", "/api/takes")
        self.assertEqual(status, 200)
        self.assertEqual(takes["groups"], [])
        self.assertTrue(takes["read_only"])

    def test_static_assets_are_served_without_a_build_step(self):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3.0)
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        self.assertIn("text/html", response.getheader("Content-Type"))
        self.assertIn("Enableton", body)
        connection.close()

        connection = HTTPConnection("127.0.0.1", self.port, timeout=3.0)
        connection.request("GET", "/panel.js")
        response = connection.getresponse()
        self.assertIn("javascript", response.getheader("Content-Type"))
        self.assertIn("previewTool", response.read().decode("utf-8"))
        connection.close()

    def test_plan_then_apply_and_token_is_single_use(self):
        status, planned = self._request(
            "POST", "/api/plan",
            {"tool": "takes_create", "args": {"track": "Drums", "count": 1}},
        )
        self.assertEqual(status, 200)
        self.assertTrue(planned["ok"])
        self.assertTrue(planned["can_apply"])
        self.assertTrue(planned["token"])
        self.assertTrue(planned["preview"]["dry_run"])
        self.assertEqual(planned["preview"]["source"], "Drums")

        status, applied = self._request("POST", "/api/apply", {"token": planned["token"]})
        self.assertEqual(status, 200)
        self.assertTrue(applied["applied"])
        self.assertFalse(applied["result"]["dry_run"])
        self.assertTrue(any(track.name.startswith("Drums take") for track in self.adapter.song.tracks))

        status, reused = self._request("POST", "/api/apply", {"token": planned["token"]})
        self.assertEqual(status, 409)
        self.assertEqual(reused["error"]["code"], "PREVIEW_NOT_FOUND")

    def test_mute_preview_uses_the_existing_snapshot_restore_tool(self):
        status, planned = self._request(
            "POST", "/api/plan",
            {
                "tool": "mix_snapshot_restore",
                "args": {
                    "restore": [
                        {"kind": "track", "index": 0, "name": "Drums", "field": "mute", "value": True},
                    ],
                },
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(planned["can_apply"])
        self.assertTrue(planned["preview"]["dry_run"])
        self.assertEqual(planned["preview"]["changes"][0]["field"], "mute")
        self.assertFalse(planned["preview"]["changes"][0]["from"])
        self.assertTrue(planned["preview"]["changes"][0]["to"])

    def test_mute_apply_writes_one_field_through_the_executor(self):
        with tempfile.TemporaryDirectory() as temporary:
            set_path = os.path.join(temporary, "panel-test.als")
            with open(set_path, "wb") as output:
                output.write(b"fake Set")

            adapter = FakeAdapter()
            adapter.song.file_path = set_path
            service = PanelService(
                adapter=adapter,
                status_provider=healthy_status,
                backup_root=temporary,
            )
            server, thread, port = self._start(service)
            self.addCleanup(service.close)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            self.addCleanup(thread.join, 2.0)

            connection = HTTPConnection("127.0.0.1", port, timeout=3.0)
            body = json.dumps({
                "tool": "mix_snapshot_restore",
                "args": {
                    "restore": [
                        {"kind": "track", "index": 0, "name": "Drums", "field": "mute", "value": True},
                    ],
                },
            })
            connection.request(
                "POST", "/api/plan", body=body, headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            planned = json.loads(response.read().decode("utf-8"))
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertTrue(planned["can_apply"])

            connection = HTTPConnection("127.0.0.1", port, timeout=3.0)
            connection.request(
                "POST", "/api/apply",
                body=json.dumps({"token": planned["token"]}),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            applied = json.loads(response.read().decode("utf-8"))
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertTrue(applied["applied"])
            self.assertTrue(adapter.song.tracks[0].mute)
            self.assertEqual(applied["undo"][0]["field"], "mute")

    def test_read_only_plan_has_no_apply_token(self):
        status, planned = self._request(
            "POST", "/api/plan",
            {"tool": "session_brief", "args": {"include_tracks": False}},
        )
        self.assertEqual(status, 200)
        self.assertFalse(planned["writes"])
        self.assertFalse(planned["can_apply"])
        self.assertIsNone(planned["token"])

    def test_discard_is_preview_only_because_deletion_is_irreversible(self):
        status, create = self._request(
            "POST", "/api/plan",
            {"tool": "takes_create", "args": {"track": "Drums", "count": 2}},
        )
        self.assertEqual(status, 200)
        status, applied = self._request("POST", "/api/apply", {"token": create["token"]})
        self.assertEqual(status, 200)
        names = [item["name"] for item in applied["result"]["takes"]]

        status, planned = self._request(
            "POST", "/api/plan", {"tool": "takes_discard", "args": {"takes": [names[1]]}}
        )
        self.assertEqual(status, 200)
        self.assertFalse(planned["can_apply"])
        self.assertIsNone(planned["token"])
        self.assertTrue(planned["preview"]["dry_run"])
        self.assertEqual(planned["preview"]["count"], 1)
        self.assertIn(names[1], [track.name for track in self.adapter.song.tracks])

    def test_rejected_write_returns_an_error_envelope_and_no_token(self):
        status, payload = self._request(
            "POST", "/api/plan",
            {"tool": "takes_create", "args": {"track": "Missing track", "count": 1}},
        )
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")
        self.assertNotIn("token", payload)

    def test_unknown_route_is_a_json_envelope(self):
        status, payload = self._request("GET", "/api/nope")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")

        status, payload = self._request("PUT", "/api/status")
        self.assertEqual(status, 405)
        self.assertEqual(payload["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_bridge_unreachable_is_503_and_keeps_the_page_usable(self):
        service = PanelService(adapter=BrokenAdapter(), status_provider=offline_status)
        server, thread, port = self._start(service)
        self.addCleanup(service.close)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(thread.join, 2.0)

        connection = HTTPConnection("127.0.0.1", port, timeout=3.0)
        connection.request("GET", "/api/status")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        self.assertEqual(response.status, 503)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "DISCONNECTED")
        self.assertFalse(payload["error"]["detail"]["status"]["connected"])
        self.assertTrue(payload["error"]["detail"]["hints"])

        connection = HTTPConnection("127.0.0.1", port, timeout=3.0)
        connection.request("GET", "/api/session")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        self.assertEqual(response.status, 503)
        self.assertEqual(payload["error"]["code"], "DISCONNECTED")

    def test_panel_binds_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        with self.assertRaises(ValueError):
            run_panel(host="0.0.0.0", no_browser=True)


if __name__ == "__main__":
    unittest.main()

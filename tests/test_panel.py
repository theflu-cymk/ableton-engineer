import json
import os
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

import support  # noqa: F401 - puts src and remote_script on sys.path
from enableton.live.fake import FakeAdapter
from enableton.panel import PANEL_HOST, PanelHTTPServer, PanelService, run_panel
from enableton.protocol.codes import LiveError
from enableton.recipe_store import RecipeStore


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
        self.assertFalse(takes["read_only"])
        self.assertTrue(takes["controls"]["select"])
        self.assertFalse(takes["controls"]["discard_apply"])

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
        script = response.read().decode("utf-8")
        self.assertIn("stageTool", script)
        self.assertIn("stageRecipe", script)
        self.assertIn("takes_select", script)
        self.assertIn("takes_discard", script)
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

    def test_select_take_group_previews_and_applies(self):
        status, create = self._request(
            "POST", "/api/plan",
            {"tool": "takes_create", "args": {"track": "Drums", "count": 2}},
        )
        self.assertEqual(status, 200)
        status, applied = self._request("POST", "/api/apply", {"token": create["token"]})
        self.assertEqual(status, 200)
        names = [item["name"] for item in applied["result"]["takes"]]
        active_volume = applied["result"]["source_volume"]

        status, takes = self._request("GET", "/api/takes")
        self.assertEqual(status, 200)
        group = next(item for item in takes["groups"] if item["source"] == "Drums")
        self.assertEqual([item["name"] for item in group["takes"]], names)

        status, planned = self._request(
            "POST", "/api/plan",
            {"tool": "takes_select", "args": {"takes": names, "active": 2}},
        )
        self.assertEqual(status, 200)
        self.assertTrue(planned["can_apply"])
        self.assertTrue(planned["token"])
        self.assertTrue(planned["preview"]["dry_run"])
        self.assertEqual(planned["preview"]["changes"][1]["to"], active_volume)

        status, selected = self._request("POST", "/api/apply", {"token": planned["token"]})
        self.assertEqual(status, 200)
        self.assertTrue(selected["applied"])
        volumes = {track.name: track.volume for track in self.adapter.song.tracks}
        self.assertEqual(volumes[names[0]], 0.0)
        self.assertEqual(volumes[names[1]], active_volume)

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


class RecipePanelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.shipped = root / "shipped"
        self.user = root / "user"
        self.plans = root / "plans"
        self.transactions = root / "transactions"
        self.store = RecipeStore(self.shipped, self.user)

        self._write(self.shipped, {
            "id": "mix.trim",
            "name": "Trim the drums",
            "version": 1,
            "kind": "workflow",
            "status": "shipped",
            "tags": ["mix", "drums"],
            "flavor": {"name": "utility", "bpm": [120, 130], "feel": "straight"},
            "description": "Pull the drum bus back.",
            "steps": [
                {
                    "tool": "tracks_set_volume",
                    "args": {"tracks": ["Drums"], "volume": 0.4},
                    "why": "leave headroom",
                }
            ],
        })
        self._write(self.user, {
            "id": "mix.trim",
            "name": "Trim the drums (custom)",
            "version": 1,
            "kind": "workflow",
            "status": "user",
            "tags": ["mix"],
            "flavor": {"name": "utility", "bpm": [120, 130], "feel": "straight"},
            "description": "My shorter trim.",
            "steps": [
                {
                    "tool": "tracks_set_volume",
                    "args": {"tracks": ["Drums"], "volume": 0.4},
                    "why": "leave headroom",
                }
            ],
        })
        self._write(self.user, {
            "id": "mix.manual",
            "name": "Manual trim",
            "version": 1,
            "kind": "workflow",
            "status": "user",
            "tags": ["manual"],
            "description": "Needs a hand first.",
            "steps": [
                {
                    "tool": "tracks_set_volume",
                    "args": {"tracks": ["Bass layer"], "volume": 0.3},
                }
            ],
            "manual": [
                {
                    "instruction": "Lower the bass fader in Live.",
                    "when": "before_apply",
                    "verify": "The bass is out of the way.",
                }
            ],
        })
        self._write(self.user, {
            "id": "mix.role",
            "name": "Role trim",
            "version": 1,
            "kind": "workflow",
            "status": "draft",
            "steps": [
                {
                    "tool": "tracks_set_volume",
                    "args": {"tracks": ["Bass"], "volume": 0.35},
                }
            ],
        })
        self._write(self.user, {
            "id": "mix.reference",
            "name": "Reference palette",
            "version": 1,
            "kind": "style",
            "status": "user",
            "tags": ["reference"],
            "ingredients": [
                {"role": "bass", "kind": "sample", "source": "packs/bass"},
            ],
            "manual": [
                {"instruction": "Choose a bass in your own sampler.", "when": "after_apply"},
            ],
        })
        (self.user / "broken.recipe.json").write_text("{", encoding="utf-8")

        self.adapter = FakeAdapter()
        self.set_path = root / "recipe-panel.als"
        self.set_path.write_bytes(b"fake Set")
        self.adapter.song.file_path = str(self.set_path)
        self.service = PanelService(
            adapter=self.adapter,
            status_provider=healthy_status,
            recipe_store=self.store,
            plan_root=str(self.plans),
            transaction_root=str(self.transactions),
            backup_root=str(root / "backups"),
        )
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

    def _write(self, directory, recipe):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (recipe["id"] + ".json")
        path.write_text(json.dumps(recipe), encoding="utf-8")

    def _request(self, method, path, payload=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3.0)
        body = None if payload is None else json.dumps(payload)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw.decode("utf-8"))

    def test_catalog_enriches_and_survives_a_broken_user_file(self):
        status, payload = self._request("GET", "/api/recipes")

        self.assertEqual(status, 200)
        rows = {row["id"]: row for row in payload["recipes"]}
        self.assertEqual(rows["mix.trim"]["source"], "user")
        self.assertTrue(rows["mix.trim"]["overrides"])
        self.assertEqual(rows["mix.trim"]["bpm"], [120.0, 130.0])
        self.assertIn("mix", rows["mix.trim"]["tags"])
        self.assertTrue(rows["mix.trim"]["compilable"])
        self.assertEqual(rows["mix.role"]["track_refs"], ["Bass"])
        self.assertFalse(rows["mix.reference"]["compilable"])
        self.assertEqual(rows["broken.recipe"]["status"], "invalid")
        self.assertIn("cannot read", rows["broken.recipe"]["error"])

    def test_recipe_detail_and_invalid_recipe_error(self):
        status, payload = self._request("GET", "/api/recipes/mix.trim")
        self.assertEqual(status, 200)
        self.assertEqual(payload["recipe"]["name"], "Trim the drums (custom)")
        self.assertEqual(payload["summary"]["source"], "user")

        status, payload = self._request("GET", "/api/recipes/broken.recipe")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "BAD_ARGS")

    def test_recipe_targets_lists_midi_clips(self):
        status, payload = self._request("GET", "/api/recipe-targets")

        self.assertEqual(status, 200)
        drums = next(track for track in payload["tracks"] if track["name"] == "Drums")
        names = {clip["name"] for clip in drums["clips"]}
        self.assertIn("drums A", names)
        self.assertIn("drums 1", names)
        self.assertIn("drums 2", names)

    def test_cue_runs_the_exact_plan_and_undo_restores(self):
        status, cue = self._request("POST", "/api/cue", {"id": "mix.trim"})
        self.assertEqual(status, 200)
        self.assertEqual(cue["status"], "ready")
        self.assertTrue(cue["token"])
        self.assertEqual([step["tool"] for step in cue["steps"]], ["tracks_set_volume"])

        status, applied = self._request("POST", "/api/cue/run", {"token": cue["token"]})
        self.assertEqual(status, 200)
        self.assertTrue(applied["applied"])
        self.assertTrue(applied["undo_available"])
        self.assertAlmostEqual(self.adapter.song.tracks[0].volume, 0.4)

        status, reused = self._request("POST", "/api/cue/run", {"token": cue["token"]})
        self.assertEqual(status, 409)
        self.assertEqual(reused["error"]["code"], "PREVIEW_NOT_FOUND")

        status, undone = self._request("POST", "/api/undo", {})
        self.assertEqual(status, 200)
        self.assertTrue(undone["ok"])
        self.assertAlmostEqual(self.adapter.song.tracks[0].volume, 0.82)

    def test_manual_checkpoint_blocks_cue_until_confirmed(self):
        status, cue = self._request("POST", "/api/cue", {"id": "mix.manual"})
        self.assertEqual(status, 200)
        self.assertEqual(cue["status"], "manual_required")
        self.assertIsNone(cue["token"])
        self.assertTrue(cue["can_confirm"])
        self.assertEqual(cue["manual"][0]["when"], "before_apply")

        status, ready = self._request(
            "POST", "/api/cue", {"id": "mix.manual", "manual_confirmed": True}
        )
        self.assertEqual(status, 200)
        self.assertEqual(ready["status"], "ready")

        status, discarded = self._request("POST", "/api/cue/discard", {"token": ready["token"]})
        self.assertEqual(status, 200)
        self.assertTrue(discarded["discarded"])
        self.assertEqual(list(self.plans.glob("p_*.json")), [])

    def test_track_binding_rewrites_a_recipe_role(self):
        status, cue = self._request(
            "POST",
            "/api/cue",
            {"id": "mix.role", "track_bindings": {"Bass": "Bass layer"}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(cue["status"], "ready")
        self.assertEqual(cue["steps"][0]["args"]["tracks"], ["Bass layer"])


if __name__ == "__main__":
    unittest.main()

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import support
from enableton.cli import EXIT_CONNECTION, EXIT_FINDINGS, EXIT_OK, doctor, main
from enableton.protocol.client import LiveClient


class CliTests(unittest.TestCase):
    def test_doctor_reports_a_fake_live(self):
        server = support.fake_server()
        self.addCleanup(server.stop)

        report = doctor(port=server.port)
        self.assertTrue(report["connected"])
        self.assertEqual(report["protocol"], 1)
        self.assertIn("levels", report["features"])

    def test_doctor_reports_a_closed_port_with_a_fix(self):
        report = doctor(port=1)  # nothing listens here
        self.assertFalse(report["connected"])
        self.assertEqual(report["code"], "DISCONNECTED")
        self.assertIn("error", report)

    def test_doctor_exit_codes(self):
        server = support.fake_server()
        self.addCleanup(server.stop)

        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--port", str(server.port), "doctor"]), EXIT_OK)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--port", "1", "doctor"]), EXIT_CONNECTION)

    def test_status_prints_json(self):
        server = support.fake_server()
        self.addCleanup(server.stop)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["--port", str(server.port), "status"])
        self.assertEqual(code, EXIT_OK)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["tracks"], 3)

    def test_modes_lists_the_catalogue(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(main(["modes"]), EXIT_OK)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["default"], "auto")
        self.assertEqual(
            [row["mode"] for row in payload["modes"]],
            ["arrange", "auto", "edit", "inspect", "mix", "prep", "produce", "recipe", "sound"],
        )

    def test_modes_findings_reads_per_mode_counts_from_live(self):
        server = support.fake_server()
        self.addCleanup(server.stop)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(
                main(["--port", str(server.port), "modes", "--findings"]), EXIT_OK
            )
        payload = json.loads(buffer.getvalue())
        rows = {row["mode"]: row for row in payload["modes"]}
        self.assertEqual(payload["findings"]["total"], 2)
        self.assertEqual(rows["auto"]["findings"]["total"], 0)
        self.assertEqual(rows["inspect"]["findings"]["total"], 2)

    def test_modes_findings_without_live_still_lists_modes(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(main(["--port", "1", "modes", "--findings"]), EXIT_OK)
        payload = json.loads(buffer.getvalue())
        self.assertFalse(payload["live"]["connected"])
        self.assertEqual(
            [row["mode"] for row in payload["modes"]],
            ["arrange", "auto", "edit", "inspect", "mix", "prep", "produce", "recipe", "sound"],
        )

    def test_inspect_prints_findings_and_returns_the_findings_exit_code(self):
        server = support.fake_server()
        self.addCleanup(server.stop)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["--port", str(server.port), "inspect"])
        self.assertEqual(code, EXIT_FINDINGS)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["tier"], "standard")
        self.assertEqual(payload["counts"]["total"], 2)

    def test_plan_and_run_round_trip(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)
        source = root / "scratch.als"
        source.write_bytes(b"scratch")

        server = support.fake_server()
        self.addCleanup(server.stop)
        server.song.file_path = str(source)
        server.song.tracks[0].volume = 1.0

        appdata = str(root / "appdata")
        with mock.patch.dict(os.environ, {"APPDATA": appdata}):
            plan_buffer = io.StringIO()
            with redirect_stdout(plan_buffer):
                code = main(["--port", str(server.port), "plan", "--intent", "gain"])
            self.assertEqual(code, EXIT_OK)
            plan = json.loads(plan_buffer.getvalue())
            self.assertTrue(plan["plan_id"].startswith("p_"))
            self.assertEqual([step["tool"] for step in plan["steps"]], ["tracks_set_volume"])

            run_buffer = io.StringIO()
            with redirect_stdout(run_buffer):
                code = main(["--port", str(server.port), "run", plan["plan_id"]])
            self.assertEqual(code, EXIT_OK)
            applied = json.loads(run_buffer.getvalue())
            self.assertTrue(applied["applied"])
            self.assertEqual(applied["counts_before"]["total"], 3)
            self.assertEqual(applied["counts_after"]["total"], 2)
            self.assertAlmostEqual(server.song.tracks[0].volume, 0.85)

    def test_tools_lists_a_domain(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(main(["tools", "--domain", "mix"]), EXIT_OK)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["tools"])
        self.assertEqual(payload["count"], len(payload["tools"]))
        self.assertTrue(all(row["domain"] == "mix" for row in payload["tools"]))
        self.assertIn("mix_meter_poll", {row["name"] for row in payload["tools"]})

    def test_tools_writes_filter_only_lists_mutating_tools(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(main(["tools", "--writes"]), EXIT_OK)
        rows = json.loads(buffer.getvalue())["tools"]
        self.assertTrue(rows)
        self.assertTrue(all(row["writes"] for row in rows))

    def test_describe_prints_the_schema_and_examples(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(main(["describe", "mix_resample_capture"]), EXIT_OK)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["cmd"], "mix.resample_capture")
        self.assertEqual(
            set(payload["input"]["properties"]),
            {"track", "slot", "scene", "ms", "dry_run"},
        )
        self.assertEqual(payload["input"]["required"], ["track"])
        self.assertTrue(payload["examples"])
        self.assertTrue(payload["writes"])

    def test_describe_suggests_a_near_miss(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["describe", "mix_meter_pol"]), EXIT_FINDINGS)
        self.assertIn("mix_meter_poll", err.getvalue())

    def test_call_refuses_an_unknown_tool_without_connecting(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--port", "1", "call", "nope_tool"]), EXIT_FINDINGS)
        self.assertIn("enableton tools", err.getvalue())

    def test_call_arguments_must_be_a_json_object(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["call", "ableton_status", "--args", "[1]"]) , EXIT_FINDINGS)
        self.assertIn("JSON object", err.getvalue())

    def test_a_refused_request_is_not_a_connection_failure(self):
        server = support.fake_server()
        self.addCleanup(server.stop)

        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = main(
                ["--port", str(server.port), "call", "mix_resample_capture", "--args", "{}"]
            )
        self.assertEqual(code, EXIT_FINDINGS)
        self.assertIn("BAD_ARGS", err.getvalue())

    def test_a_closed_port_is_a_connection_failure(self):
        for argv in (["call", "ableton_status"], ["status"]):
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                code = main(["--port", "1"] + argv)
            self.assertEqual(code, EXIT_CONNECTION, argv)
            self.assertIn("could not reach Live", err.getvalue(), argv)

    def test_a_refused_socket_is_also_a_connection_failure(self):
        # The client normally turns a dead port into a LiveError; this covers the raw OSError
        # escaping connect(), which used to traceback out of `status` and `call`.
        with mock.patch.object(
            LiveClient, "connect", side_effect=ConnectionRefusedError("refused")
        ):
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                self.assertEqual(main(["status"]), EXIT_CONNECTION)
        self.assertIn("cannot reach Live", err.getvalue())

    def test_flags_after_the_subcommand_are_accepted(self):
        server = support.fake_server()
        self.addCleanup(server.stop)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(main(["status", "--port", str(server.port), "--json"]), EXIT_OK)
        self.assertEqual(json.loads(buffer.getvalue())["tracks"], 3)


if __name__ == "__main__":
    unittest.main()

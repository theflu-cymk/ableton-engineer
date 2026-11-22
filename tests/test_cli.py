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
            [
                "arrange", "auto", "edit", "inspect", "mix", "prep", "produce",
                "recipe", "session", "sound",
            ],
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
            [
                "arrange", "auto", "edit", "inspect", "mix", "prep", "produce",
                "recipe", "session", "sound",
            ],
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

    def test_recipes_lists_the_catalog_with_compile_flags(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)

        with mock.patch.dict(os.environ, {"APPDATA": str(root / "appdata")}):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                self.assertEqual(main(["recipes"]), EXIT_OK)

        payload = json.loads(buffer.getvalue())
        rows = {row["id"]: row for row in payload["recipes"]}
        self.assertEqual(payload["count"], len(rows))
        self.assertTrue(rows["dubstep.half_time"]["compilable"])
        self.assertTrue(rows["dubstep.half_time"]["needs_target"])
        self.assertTrue(rows["tearout.growl"]["compilable"])
        self.assertTrue(rows["tearout.growl"]["needs_target"])
        self.assertTrue(rows["bass.loud_rack"]["compilable"])
        self.assertTrue(rows["bass.loud_rack"]["needs_target"])
        self.assertFalse(rows["bass_music.mix_chain"]["compilable"])

    def test_recipes_filters_narrow_the_catalog(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)

        def run(*flags):
            buffer = io.StringIO()
            with mock.patch.dict(os.environ, {"APPDATA": str(root / "appdata")}), \
                    redirect_stdout(buffer):
                self.assertEqual(main(["recipes", *flags]), EXIT_OK)
            return json.loads(buffer.getvalue())

        tagged = run("--tag", "riddim")
        self.assertEqual(tagged["count"], len(tagged["recipes"]))
        self.assertGreater(tagged["count"], 0)
        self.assertTrue(all("riddim" in row["tags"] for row in tagged["recipes"]))

        rhythms = run("--kind", "rhythm")
        self.assertEqual(rhythms["count"], 4)
        self.assertTrue(all(row["kind"] == "rhythm" for row in rhythms["recipes"]))

        everything = run()
        expected = sorted(row["id"] for row in everything["recipes"] if row["compilable"])
        runnable = run("--runnable")
        self.assertTrue(all(row["compilable"] for row in runnable["recipes"]))
        self.assertEqual(
            sorted(row["id"] for row in runnable["recipes"]), expected
        )
        self.assertIn("riddim.bounce_140", expected)

        found = run("--search", "BOUNCE")
        self.assertEqual([row["id"] for row in found["recipes"]], ["riddim.bounce_140"])

    def test_recipe_reads_and_previews_without_live(self):
        """Compiling a recipe that writes nothing is a local read, not a connection."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)

        with mock.patch.dict(os.environ, {"APPDATA": str(root / "appdata")}):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["--port", "9", "recipe", "tearout.growl"])
            self.assertEqual(code, EXIT_FINDINGS)
            plan = json.loads(buffer.getvalue())
            self.assertEqual(plan["status"], "unavailable")
            self.assertIn("--target-clip", plan["reason"])
            self.assertTrue(plan["manual"])
            self.assertEqual(plan["manual"][0]["status"], "pending")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                self.assertEqual(
                    main(["--port", "9", "recipe", "tearout.growl", "--show"]), EXIT_OK
                )
            shown = json.loads(buffer.getvalue())
            self.assertEqual(shown["recipe"]["id"], "tearout.growl")
            self.assertEqual(shown["recipe"]["kind"], "style")
            self.assertTrue(shown["recipe"]["manual"])
            self.assertTrue(shown["ingredients"])

    def test_recipe_show_refuses_apply_and_target_flags(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"APPDATA": tempfile.mkdtemp()}), \
                redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = main(["recipe", "tearout.growl", "--show", "--apply"])
        self.assertEqual(code, EXIT_FINDINGS)
        self.assertIn("cannot be combined", err.getvalue())

    def test_recipe_compiles_a_rhythm_into_a_stored_plan(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)
        server = support.fake_server()
        self.addCleanup(server.stop)
        source = root / "scratch.als"
        source.write_bytes(b"scratch")
        server.song.file_path = str(source)

        with mock.patch.dict(os.environ, {"APPDATA": str(root / "appdata")}):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(
                    ["--port", str(server.port), "recipe", "dubstep.half_time"]
                )
            self.assertEqual(code, EXIT_FINDINGS)
            missing = json.loads(buffer.getvalue())
            self.assertEqual(missing["status"], "unavailable")
            self.assertIn("MIDI target", missing["reason"])

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(
                    [
                        "--port", str(server.port), "recipe", "dubstep.half_time",
                        "--target-track", "Drums", "--target-clip", "drums A",
                        "--location", "session",
                    ]
                )
            self.assertEqual(code, EXIT_OK)
            plan = json.loads(buffer.getvalue())
            self.assertEqual(plan["status"], "plan_ready")
            self.assertTrue(plan["plan_id"].startswith("p_"))
            self.assertEqual([step["tool"] for step in plan["steps"]], ["notes_replace"])
            self.assertEqual(plan["render"]["note_count"], 26)

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["--port", str(server.port), "run", plan["plan_id"]])
            self.assertEqual(code, EXIT_OK)
            self.assertTrue(json.loads(buffer.getvalue())["applied"])
            self.assertEqual(len(server.song.tracks[0].clip_slots[0].clip.notes), 26)

    def test_recipe_apply_writes_the_current_set(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)
        server = support.fake_server()
        self.addCleanup(server.stop)
        source = root / "scratch.als"
        source.write_bytes(b"scratch")
        server.song.file_path = str(source)
        server.song.tracks[0].volume = 0.5

        with mock.patch.dict(os.environ, {"APPDATA": str(root / "appdata")}):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(
                    [
                        "--port", str(server.port), "recipe", "dubstep.roller",
                        "--target-track", "Drums", "--target-clip", "drums A",
                        "--location", "session", "--apply",
                    ]
                )

        self.assertEqual(code, EXIT_OK)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["recipe"]["status"], "plan_ready")
        self.assertTrue(payload["apply"]["applied"])
        self.assertAlmostEqual(server.song.tracks[0].volume, 0.82)
        self.assertEqual(len(server.song.tracks[0].clip_slots[0].clip.notes), 26)

    def test_recipe_location_and_slot_need_a_clip(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = main(["recipe", "dubstep.half_time", "--slot", "1"])
        self.assertEqual(code, EXIT_FINDINGS)
        self.assertIn("--target-clip", err.getvalue())

    def test_a_rhythm_still_needs_a_clip(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)
        server = support.fake_server()
        self.addCleanup(server.stop)
        source = root / "scratch.als"
        source.write_bytes(b"scratch")
        server.song.file_path = str(source)

        with mock.patch.dict(os.environ, {"APPDATA": str(root / "appdata")}):
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                code = main([
                    "--port", str(server.port), "recipe", "dubstep.half_time",
                    "--target-track", "Drums",
                ])
        self.assertEqual(code, EXIT_FINDINGS)
        self.assertIn("needs target.clip", err.getvalue())

    def test_style_recipes_apply_an_audition_through_the_cli(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)
        server = support.fake_server()
        self.addCleanup(server.stop)
        source = root / "scratch.als"
        source.write_bytes(b"scratch")
        server.song.file_path = str(source)

        flagships = {
            "dubstep.wobble_operator": 4,
            "riddim.triplet_operator": 6,
            "deathstep.growl_operator": 6,
            "tearout.siren_lead": 4,
        }
        with mock.patch.dict(os.environ, {"APPDATA": str(root / "appdata")}):
            for recipe_id, expected in flagships.items():
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    code = main([
                        "--port", str(server.port), "recipe", recipe_id,
                        "--target-track", "Drums", "--target-clip", "drums A",
                        "--location", "session", "--manual-confirmed", "--apply",
                    ])
                self.assertEqual(code, EXIT_OK, buffer.getvalue()[:400])
                payload = json.loads(buffer.getvalue())
                self.assertTrue(payload["apply"]["applied"])
                render = payload["recipe"]["render"]
                self.assertEqual(render["strategy"], "audition")
                self.assertEqual(render["note_count"], expected)
                self.assertEqual(len(render["notes"]), expected)

                clip = [
                    slot.clip for slot in server.song.tracks[0].clip_slots
                    if slot.clip is not None
                ][0]
                self.assertEqual(len(clip.notes), expected)
                self.assertEqual(
                    sorted(round(note.start_time, 6) for note in clip.notes),
                    [note["start"] for note in render["notes"]],
                )
                self.assertEqual(
                    sorted(note.pitch for note in clip.notes),
                    sorted(note["pitch"] for note in render["notes"]),
                )

    def test_style_recipe_binding_names_the_audition_track(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(root), True)
        server = support.fake_server()
        self.addCleanup(server.stop)
        source = root / "scratch.als"
        source.write_bytes(b"scratch")
        server.song.file_path = str(source)

        with mock.patch.dict(os.environ, {"APPDATA": str(root / "appdata")}):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main([
                    "--port", str(server.port), "recipe", "dubstep.sub_operator",
                    "--binding", "synth=Drums",
                    "--target-clip", "drums A", "--location", "session",
                    "--manual-confirmed", "--apply",
                ])
        self.assertEqual(code, EXIT_OK, buffer.getvalue()[:400])
        render = json.loads(buffer.getvalue())["recipe"]["render"]
        self.assertEqual(render["resolved_by"], "binding")
        self.assertEqual(render["track"], "Drums")
        self.assertTrue(render["note_count"])


if __name__ == "__main__":
    unittest.main()

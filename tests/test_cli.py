import io
import json
import unittest
from contextlib import redirect_stdout

import support
from enableton.cli import EXIT_CONNECTION, EXIT_OK, doctor, main


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
        self.assertEqual([row["mode"] for row in payload["modes"]], ["auto", "inspect"])


if __name__ == "__main__":
    unittest.main()

import os
import shutil
import tempfile
import unittest

import support
from enableton.setup import install, instructions


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.source = os.path.join(self.tmp, "src", "Enableton")
        os.makedirs(os.path.join(self.source, "handlers"))
        for rel in ("__init__.py", "server.py", "handlers/__init__.py", "handlers/song.py"):
            with open(os.path.join(self.source, rel), "w", encoding="utf-8") as fh:
                fh.write("# %s\n" % rel)
        # A __pycache__ must never be installed.
        os.makedirs(os.path.join(self.source, "__pycache__"))
        with open(os.path.join(self.source, "__pycache__", "x.pyc"), "w") as fh:
            fh.write("junk")
        self.target = os.path.join(self.tmp, "User Library", "Remote Scripts", "Enableton")

    def test_installs_the_package_tree(self):
        result = install(target=self.target, source=self.source)
        self.assertTrue(result.changed)
        self.assertTrue(result.created)
        self.assertIn("handlers/song.py", result.files)
        self.assertTrue(os.path.isfile(os.path.join(self.target, "handlers", "song.py")))

    def test_skips_bytecode(self):
        result = install(target=self.target, source=self.source)
        self.assertFalse(any("__pycache__" in name for name in result.files))

    def test_second_run_is_a_no_op(self):
        install(target=self.target, source=self.source)
        again = install(target=self.target, source=self.source)
        self.assertTrue(again.already_present)
        self.assertFalse(again.changed)

    def test_dry_run_writes_nothing(self):
        result = install(target=self.target, source=self.source, dry_run=True)
        self.assertTrue(result.changed)
        self.assertIn("server.py", result.files)
        self.assertFalse(os.path.exists(self.target))

    def test_force_reinstalls(self):
        install(target=self.target, source=self.source)
        forced = install(target=self.target, source=self.source, force=True)
        self.assertFalse(forced.already_present)
        self.assertTrue(forced.changed)
        self.assertFalse(forced.created)

    def test_user_library_override_wins(self):
        import os as _os
        from pathlib import Path as _Path
        from enableton.setup import USER_LIBRARY_ENV, default_target

        _os.environ[USER_LIBRARY_ENV] = self.tmp
        try:
            self.assertEqual(default_target(),
                             _Path(self.tmp) / "Remote Scripts" / "Enableton")
        finally:
            del _os.environ[USER_LIBRARY_ENV]

    def test_instructions_name_the_menu_path(self):
        text = " ".join(instructions())
        self.assertIn("Control Surface", text)
        self.assertIn("Enableton", text)


if __name__ == "__main__":
    unittest.main()

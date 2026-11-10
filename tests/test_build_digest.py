"""The build digest exists twice: once server-side, once inside Live's interpreter.

They cannot share code — the server cannot reach Live's Python, and the script cannot import
``enableton``. A divergence would make ``doctor`` cry "stale" on every run, and the first thing a
user does with an alarm that always fires is ignore it.
"""

import os
import shutil
import tempfile
import unittest

import support
from enableton.setup import digest

from Enableton.server import build_digest


class BuildDigestTests(unittest.TestCase):
    def _tree(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "handlers"))
        for relative, body in (("__init__.py", "a\n"), ("handlers/song.py", "b\n")):
            with open(os.path.join(root, relative), "w", encoding="utf-8") as fh:
                fh.write(body)
        os.makedirs(os.path.join(root, "__pycache__"), exist_ok=True)
        with open(os.path.join(root, "__pycache__", "junk.pyc"), "wb") as fh:
            fh.write(b"bytecode")
        return root

    def test_both_implementations_agree(self):
        root = self._tree()
        self.assertEqual(digest(root), build_digest(root))

    def test_bytecode_does_not_change_the_digest(self):
        root = self._tree()
        before = digest(root)
        with open(os.path.join(root, "__pycache__", "junk.pyc"), "wb") as fh:
            fh.write(b"different bytecode")
        self.assertEqual(digest(root), before)
        self.assertEqual(build_digest(root), before)

    def test_editing_a_module_changes_the_digest(self):
        root = self._tree()
        before = digest(root)
        with open(os.path.join(root, "handlers", "song.py"), "a", encoding="utf-8") as fh:
            fh.write("# edit\n")
        self.assertNotEqual(digest(root), before)
        self.assertNotEqual(build_digest(root), before)


if __name__ == "__main__":
    unittest.main()

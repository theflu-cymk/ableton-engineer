"""The invariant that keeps the two sides honest.

The manifest declares commands; the Remote Script registers handlers. If those sets ever differ,
a tool exists that cannot run, or a handler exists that no tool can reach.
"""

import unittest

import support  # noqa: F401
from enableton.manifest import load_manifest, remote_commands

from Enableton import dispatch


class DriftTests(unittest.TestCase):
    def test_manifest_and_handlers_agree(self):
        declared = set(remote_commands(load_manifest()))
        registered = set(dispatch.HANDLERS)
        self.assertEqual(declared - registered, set(), "declared but not implemented")
        self.assertEqual(registered - declared, set(), "implemented but not declared")

    def test_local_tools_declare_no_command(self):
        for tool in load_manifest().values():
            if tool.local:
                self.assertIsNone(tool.cmd)
            else:
                self.assertIn(tool.cmd, dispatch.HANDLERS)

    def test_duplicate_registration_raises(self):
        with self.assertRaises(RuntimeError):
            dispatch.command("snapshot.get")(lambda args, song: {})

    def test_unknown_command_is_typed(self):
        from Enableton.errors import ScriptError

        with self.assertRaises(ScriptError) as ctx:
            dispatch.call("song.teleport", {}, None)
        self.assertEqual(ctx.exception.code, "UNKNOWN_COMMAND")

    def test_closed_arguments(self):
        from Enableton.errors import ScriptError

        with self.assertRaises(ScriptError) as ctx:
            dispatch.call("snapshot.get", {"tempo": 120}, None)
        self.assertEqual(ctx.exception.code, "BAD_ARGS")


if __name__ == "__main__":
    unittest.main()

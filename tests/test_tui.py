"""The menu is presentation only, so its tests stay on the parts that can be wrong without a
terminal: the logo geometry, the highlight stepping, and the argv each action produces."""

import io
import unittest
from contextlib import redirect_stdout

from enableton import tui
from enableton.cli import EXIT_OK, main
from enableton.setup import default_source, script_version

BLOCK = "\u2588"


class MenuShapeTests(unittest.TestCase):
    def test_logo_is_five_rows_of_one_width(self):
        rows = tui.logo()
        self.assertEqual(len(rows), 5)
        widths = {tui.visible_width(row) for row in rows}
        self.assertEqual(len(widths), 1, rows)
        self.assertGreaterEqual(widths.pop(), 50)
        self.assertTrue(all(BLOCK in row for row in rows))

    def test_logo_falls_back_to_the_same_width_for_an_unknown_letter(self):
        narrow = tui.logo("ENA")
        wide = tui.logo("ENAZ")
        self.assertEqual(
            tui.visible_width(wide[0]) - tui.visible_width(narrow[0]),
            tui.visible_width(tui.logo("A")[0]) + 1,
        )

    def test_visible_width_ignores_colour(self):
        self.assertEqual(tui.visible_width(tui.ORANGE + "abc" + tui.RESET), 3)

    def test_the_menu_is_sections_and_actions(self):
        self.assertTrue(all(item.kind in ("section", "action") for item in tui.MENU))
        self.assertEqual(tui.MENU[0].kind, "section")
        self.assertEqual(tui.MENU[-1].action, "exit")
        actions = [item.action for item in tui.MENU if item.kind == "action"]
        for expected in ("doctor", "status", "inspect", "browse", "describe", "call"):
            self.assertIn(expected, actions)

    def test_step_skips_sections_and_wraps(self):
        first = tui._first_action()
        self.assertEqual(tui.MENU[first].kind, "action")

        index = first
        for _ in range(len([item for item in tui.MENU if item.kind == "action"])):
            index = tui.step(index, 1)
            self.assertEqual(tui.MENU[index].kind, "action")
        self.assertEqual(index, first)

        self.assertEqual(tui.MENU[tui.step(first, -1)].kind, "action")

    def test_actions_map_to_the_cli_argv_they_would_type(self):
        self.assertEqual(tui._collect("doctor"), ["doctor"])
        self.assertEqual(tui._collect("status"), ["status"])
        self.assertEqual(tui._collect("modes"), ["modes", "--findings"])
        self.assertEqual(tui._collect("setup"), ["setup", "--force"])
        self.assertIsNone(tui._collect("nonsense"))


class ToolSearchTests(unittest.TestCase):
    def test_an_empty_query_lists_the_whole_catalogue(self):
        from enableton.manifest import load_manifest

        catalogue = load_manifest()
        self.assertEqual(tui.filter_tools("", catalogue), list(catalogue))

    def test_a_name_hit_outranks_a_description_hit(self):
        names = tui.filter_tools("meter")
        self.assertIn("mix_meter_poll", names)
        self.assertEqual(names[0], "mix_meter_poll")

    def test_terms_are_anded(self):
        names = tui.filter_tools("mix met")
        self.assertIn("mix_meter_poll", names)
        self.assertNotIn("tracks_set_volume", names)

    def test_a_domain_word_finds_its_tools(self):
        names = tui.filter_tools("routing")
        self.assertIn("mix_routing_report", names)
        self.assertIn("tracks_set_routing", names)

    def test_no_match_returns_nothing_rather_than_everything(self):
        self.assertEqual(tui.filter_tools("zzzznope"), [])

    def test_browsing_is_a_menu_action(self):
        actions = [item.action for item in tui.MENU if item.kind == "action"]
        self.assertIn("browse", actions)

    def test_clip_keeps_rows_inside_the_terminal(self):
        self.assertEqual(tui._clip("a  b\n c", 40), "a b c")
        clipped = tui._clip("x" * 50, 20)
        self.assertEqual(len(clipped), 20)
        self.assertTrue(clipped.endswith("\u2026"))


class MenuVersionTests(unittest.TestCase):
    def test_the_banner_uses_the_shipped_script_version(self):
        shipped = script_version()
        self.assertRegex(shipped or "", r"^\d+\.\d+\.\d+$")
        self.assertEqual(tui._version(), shipped)

    def test_stale_notice_only_when_the_builds_differ(self):
        self.assertEqual(tui._stale_notice("0.4.17", "0.4.17"), "")
        self.assertEqual(tui._stale_notice("0.4.17", ""), "")
        self.assertEqual(tui._stale_notice("", "0.4.17"), "")

        notice = tui._stale_notice("0.4.16", "0.4.17")
        self.assertIn("0.4.16", notice)
        self.assertIn("0.4.17", notice)
        self.assertIn("restart Live", notice)

    def test_script_version_reads_the_value_from_server_py(self):
        text = (default_source() / "server.py").read_text(encoding="utf-8")
        self.assertIn('SCRIPT_VERSION = "%s"' % script_version(), text)


class MenuFallbackTests(unittest.TestCase):
    """Without a terminal the menu must degrade to the old behaviour, not block on input()."""

    def test_bare_invocation_prints_usage(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(main([]), EXIT_OK)
        self.assertIn("usage: enableton", buffer.getvalue())

    def test_menu_command_explains_why_it_cannot_draw(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(main(["menu"]), EXIT_OK)
        text = buffer.getvalue()
        self.assertIn("needs an interactive terminal", text)
        self.assertIn("usage: enableton", text)


if __name__ == "__main__":
    unittest.main()

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


class ModeScreenTests(unittest.TestCase):
    def test_the_first_action_is_one_click_cleanup(self):
        first = tui._first_action()
        self.assertEqual(tui.MENU[first].action, "cleanup")
        actions = [item.action for item in tui.MENU if item.kind == "action"]
        for expected in (
            "mode:triage",
            "mode:organise",
            "mode:mix",
            "mode:edit",
            "mode:arrange",
            "mode:sound",
        ):
            self.assertIn(expected, actions)

    def test_every_mode_page_ends_with_back(self):
        for key, page in tui.MODE_PAGES.items():
            self.assertTrue(page.options, key)
            self.assertEqual(page.options[-1].special, "back", key)
            self.assertTrue(all(option.label for option in page.options), key)
            self.assertTrue(all(option.detail for option in page.options[:-1]), key)

    def test_triage_offers_real_repair_paths(self):
        actions = {option.label: option for option in tui.MODE_PAGES["triage"].options}
        self.assertEqual(actions["Clean up everything"].special, "cleanup")
        self.assertTrue(actions["Clean up everything"].writes)
        self.assertEqual(actions["Duplicate or unclear names"].special, "autofix")
        self.assertEqual(actions["Duplicate or unclear names"].phases, ("hygiene",))
        self.assertEqual(actions["Misaligned layers"].special, "align")
        self.assertEqual(actions["Unclear track structure"].special, "colour")
        self.assertEqual(actions["Unbalanced levels"].phases, ("gain",))
        self.assertEqual(actions["Bad warp markers"].special, "warp")
        self.assertEqual(actions["Match layers to drum transients"].special, "warp_match")
        self.assertEqual(actions["Audio layer alignment"].special, "guide")
        self.assertEqual(actions["Routing and send confusion"].tool, "mix_routing_report")
        self.assertEqual(actions["Phase problems"].special, "guide")
        self.assertIn("Configure", actions["Phase problems"].guide)
        self.assertIn("devices_set_active", actions["Plugin or device dependencies"].guide)
        self.assertIn("Collect All", actions["Missing or uncollected media"].guide)

    def test_mode_screen_uses_the_wordmark_and_main_menu_rows(self):
        page = tui.MODE_PAGES["triage"]
        lines = tui._mode_lines(page, 0, (100, 30))
        self.assertEqual(lines[:5], tui.logo("TRIAGE"))
        self.assertTrue(any("? What should I do?" in line for line in lines))
        selected = next(line for line in lines if "Clean up everything" in line)
        self.assertTrue(
            selected.startswith(" " + tui.ORANGE + "\u276f" + tui.RESET + " " + tui.BOLD)
        )
        self.assertTrue(any("Rename duplicates, colour tracks" in line for line in lines))

    def test_guide_rows_contain_exact_steps(self):
        page = tui.MODE_PAGES["triage"]
        phase = next(option for option in page.options if option.label == "Phase problems")
        self.assertEqual(phase.special, "guide")
        steps = tui._guide_text(phase.guide, 100)
        self.assertTrue(any("Configure" in line for line in steps))
        self.assertTrue(any("Utility" in line for line in steps))

    def test_sound_exposes_plugin_surfaces_and_bypass(self):
        actions = {option.label: option for option in tui.MODE_PAGES["sound"].options}
        self.assertEqual(actions["Read plugin parameters"].tool, "devices_read_parameters")
        self.assertEqual(actions["Disable or enable a device"].tool, "devices_set_active")
        self.assertTrue(actions["Disable or enable a device"].writes)
        self.assertEqual(
            next(field for field in actions["Disable or enable a device"].fields
                 if field.key == "active").kind,
            "bool",
        )

    def test_track_colours_follow_role(self):
        self.assertEqual(tui._track_colour("midi", False), tui.COLOURS["green"])
        self.assertEqual(tui._track_colour("audio", False), tui.COLOURS["blue"])
        self.assertEqual(tui._track_colour("group", False), tui.COLOURS["grey"])
        self.assertEqual(tui._track_colour("return", False), tui.COLOURS["purple"])

    def test_bulk_result_names_every_count(self):
        lines = tui._bulk_result_lines(
            "CLEAN", 2, 20, 5, [], audible=True, warped=3, markers=8, size=(100, 30)
        )
        self.assertEqual(lines[:5], tui.logo("CLEAN"))
        joined = "\n".join(lines)
        self.assertIn("Renamed duplicate tracks   2", joined)
        self.assertIn("Coloured tracks            20", joined)
        self.assertIn("MIDI clips aligned         5", joined)
        self.assertIn("Warped clips               3", joined)
        self.assertIn("Warp markers moved         8", joined)
        self.assertIn("Audible: gain faders or clip timing", joined)

    def test_warp_match_result_names_the_reference(self):
        lines = tui._warp_result_lines(
            {"reference": {"track": "Drum bus", "source": "auto"}, "clips": 1,
             "moved": 2, "skipped": []},
            [],
            (100, 30),
        )
        joined = "\n".join(lines)
        self.assertIn("Reference track            Drum bus (auto)", joined)
        self.assertIn("Markers matched", joined)

    def test_mode_wordmarks_are_five_rows_of_one_width(self):
        for title in ("TRIAGE", "ORGANISE", "MIX", "EDIT", "ARRANGE", "SOUND"):
            rows = tui.logo(title)
            self.assertEqual(len(rows), 5, title)
            self.assertEqual(len({tui.visible_width(row) for row in rows}), 1, title)
            self.assertTrue(all(BLOCK in row for row in rows), title)

    def test_colour_palette_is_valid_rgb(self):
        self.assertTrue(tui.COLOURS)
        for name, value in tui.COLOURS.items():
            self.assertIsInstance(value, int, name)
            self.assertGreaterEqual(value, 0, name)
            self.assertLessEqual(value, 0xFFFFFF, name)


class CatalogueScreenTests(unittest.TestCase):
    def test_catalogue_wordmark_is_the_same_width_as_the_logo(self):
        rows = tui.logo("CATALOGUE")
        self.assertEqual(len(rows), 5)
        self.assertEqual(
            {tui.visible_width(row) for row in rows},
            {tui.visible_width(tui.logo()[0])},
        )
        self.assertTrue(all(BLOCK in row for row in rows))

    def test_browser_header_is_the_catalogue_wordmark(self):
        from enableton.manifest import load_manifest

        catalogue = load_manifest()
        matches = tui.filter_tools("meter", catalogue)
        lines = tui._browser_lines("meter", matches, 0, catalogue, (100, 30))
        self.assertEqual(lines[:5], tui.logo("CATALOGUE"))
        self.assertTrue(any("? Which tool?" in line for line in lines))

    def test_selected_tool_uses_the_main_menu_marker(self):
        from enableton.manifest import load_manifest

        catalogue = load_manifest()
        matches = tui.filter_tools("meter", catalogue)
        lines = tui._browser_lines("meter", matches, 0, catalogue, (100, 30))
        row = next(line for line in lines if "mix_meter_poll" in line)
        self.assertTrue(
            row.startswith(" " + tui.ORANGE + "\u276f" + tui.RESET + " " + tui.BOLD)
        )

    def test_narrow_terminal_uses_a_plain_catalogue_header(self):
        from enableton.manifest import load_manifest

        catalogue = load_manifest()
        matches = tui.filter_tools("meter", catalogue)
        lines = tui._browser_lines("meter", matches, 0, catalogue, (59, 24))
        self.assertEqual(lines[0], tui.ORANGE + tui.BOLD + "CATALOGUE" + tui.RESET)
        self.assertFalse(any(BLOCK in line for line in lines))


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

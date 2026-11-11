import unittest

import support  # noqa: F401
from enableton.recipe_patterns import RecipePatternError, parse_step_pattern


class RecipePatternTests(unittest.TestCase):
    def test_parses_a_single_sixteen_step_bar(self):
        self.assertEqual(
            parse_step_pattern("x.......x......."),
            (tuple("x.......x......."),),
        )

    def test_parses_multiple_bars_with_and_without_separators(self):
        bar = "x.......x......."
        self.assertEqual(parse_step_pattern(bar * 2), (tuple(bar), tuple(bar)))
        self.assertEqual(parse_step_pattern(bar + "|" + bar), (tuple(bar), tuple(bar)))

    def test_rejects_invalid_symbols(self):
        with self.assertRaisesRegex(RecipePatternError, "only x, X, o, ., and \\|"):
            parse_step_pattern("x.......x......?")

    def test_rejects_incomplete_or_empty_bars(self):
        for pattern in ("", "x.......", "x.......x.......|", "|x.......x......."):
            with self.subTest(pattern=pattern), self.assertRaises(RecipePatternError):
                parse_step_pattern(pattern)

    def test_rejects_whitespace_instead_of_silently_normalizing(self):
        with self.assertRaises(RecipePatternError):
            parse_step_pattern("x.......x...... .")


if __name__ == "__main__":
    unittest.main()

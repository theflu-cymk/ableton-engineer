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

    def test_triplet_grids_use_their_own_bar_length(self):
        self.assertEqual(
            parse_step_pattern("x..x..x..x..", steps_per_bar=12),
            (tuple("x..x..x..x.."),),
        )
        bar24 = "x....." * 4
        self.assertEqual(len(parse_step_pattern(bar24, steps_per_bar=24)), 1)
        self.assertEqual(len(parse_step_pattern(bar24 * 2, steps_per_bar=24)), 2)
        self.assertEqual(
            parse_step_pattern("x..x..x..x..|" + "x..x..x..x..", steps_per_bar=12),
            (tuple("x..x..x..x.."), tuple("x..x..x..x..")),
        )

    def test_a_bar_of_the_wrong_grid_length_is_refused(self):
        with self.assertRaisesRegex(RecipePatternError, "exactly 12 steps"):
            parse_step_pattern("x.......x.......", steps_per_bar=12)
        with self.assertRaisesRegex(RecipePatternError, "exactly 24 steps"):
            parse_step_pattern("x..x..x..x..", steps_per_bar=24)

    def test_steps_per_bar_must_be_a_positive_integer(self):
        for value in (0, -12, 12.0, True, "12"):
            with self.subTest(value=value), self.assertRaisesRegex(
                RecipePatternError, "positive integer"
            ):
                parse_step_pattern("xxxxxxxxxxxx", steps_per_bar=value)


if __name__ == "__main__":
    unittest.main()

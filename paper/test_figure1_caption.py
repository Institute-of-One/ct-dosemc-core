"""Plant a wrong number in Figure 1's caption, and require the gate to refuse it.

    python -m unittest paper.test_figure1_caption -v

A caption gate that passes everything and a caption gate that works look exactly
alike from a green run. Each case here changes one printed quantity to a value
the frozen results do not hold, and the last runs the gate over the caption the
paper actually ships, which must pass: a suite where every case expects a failure
cannot tell a working checker from one that fails on everything.

The damage is always a *different number*, never a rewording. A caption rewritten
around the same value is still true, and a gate that fell over it would be
refusing correct work.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import check_figure1_caption as gate  # noqa: E402
import collect_figures  # noqa: E402


def shipped() -> str:
    numbers = [
        number for number, (name, _) in collect_figures.FIGURE_SOURCES.items()
        if name == gate.FIGURE_NAME
    ]
    return collect_figures.captions()[numbers[0]]


def damage(old: str, new: str, caption: str | None = None) -> str:
    """``caption`` with ``old`` replaced, refusing a replacement that did nothing."""
    caption = shipped() if caption is None else caption
    if old not in caption:
        raise AssertionError(f"the injection matched nothing: {old!r}")
    damaged = caption.replace(old, new, 1)
    if damaged == caption:
        raise AssertionError(f"the injection changed nothing: {old!r} -> {new!r}")
    return damaged


class TheShippedCaptionPasses(unittest.TestCase):
    """Without this, every refusal below would be meaningless."""

    def setUp(self):
        if not gate.LADDER.is_file():
            self.skipTest("the figure 1 results have not been frozen")

    def test_it_passes(self):
        self.assertEqual(gate.check(shipped()), 0)

    def test_every_quantity_is_read_back_out_of_it(self):
        have = gate.printed(shipped())
        missing = sorted(name for name, value in have.items() if value is None)
        self.assertEqual(missing, [])

    def test_a_rewording_that_keeps_the_values_still_passes(self):
        reworded = damage(
            "no conversion of (b) reaches (c) closer than a median of 13 %",
            "no conversion of (b) comes within a median of 13 % of (c)",
        )
        self.assertEqual(gate.check(reworded), 0)


class RefusesAWrongNumber(unittest.TestCase):
    def setUp(self):
        if not gate.LADDER.is_file():
            self.skipTest("the figure 1 results have not been frozen")

    def test_a_stale_ctdivol(self):
        self.assertEqual(gate.check(damage("examination: 17.9 mGy",
                                           "examination: 16.1 mGy")), 1)

    def test_a_wrong_index_range(self):
        self.assertEqual(gate.check(damage("study: 18–20 mGy",
                                           "study: 18–24 mGy")), 1)

    def test_a_wrong_dose_range(self):
        self.assertEqual(gate.check(damage("anatomy: 33–49 mGy",
                                           "anatomy: 31–49 mGy")), 1)

    def test_a_wrong_held_out_error(self):
        self.assertEqual(gate.check(damage("a median of 13 %", "a median of 11 %")), 1)

    def test_a_wrong_count_of_eligible_series(self):
        self.assertEqual(gate.check(damage("one of the 23 carrying",
                                           "one of the 30 carrying")), 1)

    def test_a_wrong_selection_ratio(self):
        self.assertEqual(gate.check(damage("(2.194 against 2.188)",
                                           "(2.170 against 2.188)")), 1)

    def test_a_wrong_organ_count_on_the_section(self):
        self.assertEqual(gate.check(damage("organs scored, ten of twelve",
                                           "organs scored, eleven of twelve")), 1)

    def test_a_wrong_slice_number(self):
        self.assertEqual(gate.check(damage("slice 239 of 309", "slice 241 of 309")), 1)

    def test_a_quantity_dropped_from_the_caption(self):
        self.assertEqual(gate.check(damage(", slice 239 of 309", "")), 1)


class RefusesAMisconfiguredFigure(unittest.TestCase):
    def setUp(self):
        if not gate.LADDER.is_file():
            self.skipTest("the figure 1 results have not been frozen")
        self._sources = dict(collect_figures.FIGURE_SOURCES)

    def tearDown(self):
        collect_figures.FIGURE_SOURCES = self._sources

    def test_the_figure_is_not_registered(self):
        collect_figures.FIGURE_SOURCES = {
            number: value for number, value in self._sources.items()
            if value[0] != gate.FIGURE_NAME
        }
        self.assertEqual(gate.check(), 1)

    def test_the_figure_is_registered_twice(self):
        collect_figures.FIGURE_SOURCES = dict(self._sources)
        collect_figures.FIGURE_SOURCES[99] = (gate.FIGURE_NAME, None)
        self.assertEqual(gate.check(), 1)

    def test_the_figure_moves_and_the_gate_follows_it(self):
        """Renumbering must not leave the gate reading another figure's caption.

        Both tables move together, which is what a renumbering is. The gate finds
        the figure by its file name and must read the caption at its new number,
        not at number one.
        """
        original = collect_figures.captions
        caption = shipped()
        collect_figures.FIGURE_SOURCES = {
            (number + 10): value for number, value in self._sources.items()
        }
        collect_figures.captions = lambda: {11: caption, 12: "another figure"}
        try:
            self.assertEqual(gate.check(), 0)
        finally:
            collect_figures.captions = original


if __name__ == "__main__":
    unittest.main(verbosity=2)

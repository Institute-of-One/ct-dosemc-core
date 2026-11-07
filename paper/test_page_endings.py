"""Require the page-ending check to catch a stranded heading, and only that.

    python -m unittest paper.test_page_endings -v

The first version of this check matched a *pattern* for a heading and reported
two defects that were not defects: a numbered list item ("2. one factor per
organ...") at the foot of page 10, and a reference entry ending
"220. https://doi.org/10.37206/146." at the foot of page 26. A check that cries
wolf is worse than no check, because the next real finding is read as noise.

So both halves are required here: the real heading is caught, and neither of
those two false positives comes back.

No Word, no PDF. The page text is given directly, with the line numbers Word
prints in the margin, which is how it arrives from pypdf.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import render_pdf  # noqa: E402

HEADINGS = {
    "3. results",
    "4. discussion",
    "2.9 index-based conversions, and how they are scored",
    "4.6 limitations",
    "references",
    "declarations",
}


class CatchesAStrandedHeading(unittest.TestCase):
    def test_a_numbered_section_alone_at_the_foot(self):
        page = "412 some last paragraph of the section.\n413 \n414 3. Results"
        self.assertEqual(render_pdf.stranded_pages([page], HEADINGS), [(1, "3. results")])

    def test_a_subsection_alone_at_the_foot(self):
        page = "500 text\n501 4.6 Limitations"
        self.assertEqual(render_pdf.stranded_pages([page], HEADINGS), [(1, "4.6 limitations")])

    def test_a_named_back_matter_heading_alone_at_the_foot(self):
        page = "600 the last of the conclusions.\n601 References"
        self.assertEqual(render_pdf.stranded_pages([page], HEADINGS), [(1, "references")])

    def test_several_pages_are_all_reported(self):
        pages = ["1 a\n2 3. Results", "3 b\n4 body text", "5 c\n6 Declarations"]
        self.assertEqual([n for n, _ in render_pdf.stranded_pages(pages, HEADINGS)], [1, 3])


class DoesNotCryWolf(unittest.TestCase):
    """The two findings the pattern-matching version reported, which were wrong."""

    def test_a_numbered_list_item_is_not_a_heading(self):
        page = (
            "320 Five conversions are compared:\n"
            "321 1. a single factor for the whole cohort;\n"
            "322 2. one factor per organ, which is what a per-organ coefficient "
            "table offers;"
        )
        self.assertEqual(render_pdf.stranded_pages([page], HEADINGS), [])

    def test_a_reference_entry_is_not_a_heading(self):
        page = (
            "474 McCollough C, Bakalyar D, Bostani M. Use of Water Equivalent "
            "Diameter. AAPM; 2014. AAPM Report\n"
            "475 220. https://doi.org/10.37206/146. 475"
        )
        self.assertEqual(render_pdf.stranded_pages([page], HEADINGS), [])

    def test_ordinary_prose_is_not_a_heading(self):
        page = "100 the residual is physical, not statistical, and it is the transport."
        self.assertEqual(render_pdf.stranded_pages([page], HEADINGS), [])

    def test_a_heading_followed_by_its_text_is_not_stranded(self):
        page = "200 3. Results\n201 Across 342 organ-series pairs the median dose is"
        self.assertEqual(render_pdf.stranded_pages([page], HEADINGS), [])


class ReadsTheMarginLineNumbers(unittest.TestCase):
    def test_a_leading_line_number_is_removed(self):
        self.assertEqual(render_pdf._normalise("414 3. Results"), "3. results")

    def test_a_trailing_line_number_is_offered_as_an_alternative(self):
        self.assertIn("3. results", render_pdf._candidates("3. Results 414"))

    def test_a_heading_ending_in_a_number_is_offered_unchanged(self):
        # Stripping the trailing number unconditionally truncated this heading
        # to "... Case", so its stranding could never have been reported.
        self.assertIn(
            "2.3 verification against tg-195 case 4",
            render_pdf._candidates("138 2.3 Verification against TG-195 Case 4"),
        )

    def test_a_heading_with_a_number_in_it_survives(self):
        self.assertEqual(
            render_pdf._normalise("138 2.3 Verification against TG-195 Case 4"),
            "2.3 verification against tg-195 case 4",
        )

    def test_a_heading_ending_in_a_number_is_caught_when_stranded(self):
        headings = HEADINGS | {"2.3 verification against tg-195 case 4"}
        page = "\n".join(["137 text above", "138 2.3 Verification against TG-195 Case 4"])
        self.assertEqual(
            render_pdf.stranded_pages([page], headings),
            [(1, "2.3 verification against tg-195 case 4")],
        )


class TheRealManuscriptsHeadingsAreFound(unittest.TestCase):
    def test_the_headings_come_from_the_built_manuscript(self):
        built = PAPER / "build" / "manuscript.md"
        if not built.exists():
            self.skipTest(f"{built} has not been built")
        headings = render_pdf._headings()
        self.assertGreater(len(headings), 20)
        for wanted in ("3. results", "4. discussion", "declarations", "references"):
            self.assertIn(wanted, headings)


if __name__ == "__main__":
    unittest.main(verbosity=2)

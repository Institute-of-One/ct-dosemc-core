"""Plant each defect check_rpt_limits exists to catch, and require a failure.

    python -m unittest paper.test_rpt_limits -v

The limits checker is the thing standing between a Research Article and a
reclassification, so it is not trusted until it has refused a known defect.

Each case damages a minimal well-formed manuscript in one way. The damage is a
*contradicted or missing claim*, never a rewording: a check that looks for one
word passes a sentence rewritten around that word, and no file comparison can
see that, because the file did change.

The last case runs the checker over the real built manuscript, which must pass.
A suite where every case expects a failure cannot tell a working checker from
one that fails on everything.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import check_rpt_limits as limits  # noqa: E402

WELL_FORMED = """\
# Between-patient variation sets the limit on index-based organ dose

## Abstract

A short abstract that says what was done and what came of it, with no citation and
no figure named, and comfortably under the limit.

**Keywords:** computed tomography, organ dose, Monte Carlo, dose index

## 1. Introduction

Some introduction.

## 2. Materials and methods

### 2.1 First

Some method.

### 2.2 Second

Some more method.

## 3. Results

Some results. Table 1 and Fig. 1 are named here.

## 4. Discussion

### 4.1 One

Some discussion.

### 4.2 Limitations

Some limitations.

## 5. Conclusions

Some conclusions.

## Acknowledgments

Thanks.

## Declarations

**Funding.** None.

**Conflict of interest.** None.

**Ethics approval.** Waived.

**Data availability.** At a DOI.

**Code availability.** At a DOI.

**Use of generative artificial intelligence.** Used as a tool, not to produce values.

## References

1. Someone A. A title. A Journal. 2020;1(1):1-2. https://doi.org/10.0000/x.

<!-- scope-of-claim -->
The bound is over the conversions scored here.
"""


def check(text):
    """``(measured, notes, problems)`` for a manuscript given as a string."""
    return limits.measure(text)


def problems(text):
    return check(text)[2]


def damage(old, new, text=WELL_FORMED):
    """``text`` with ``old`` replaced, refusing a replacement that did nothing.

    An injection that does not match plants nothing and the test passes or fails
    for the wrong reason. One case here did exactly that: the string spanned a
    line break in the fixture, ``str.replace`` found nothing, and the "damaged"
    manuscript was the clean one.
    """
    if old not in text:
        raise AssertionError(f"the injection matched nothing: {old!r}")
    damaged = text.replace(old, new, 1)
    if damaged == text:
        raise AssertionError(f"the injection changed nothing: {old!r} -> {new!r}")
    return damaged


class TheWellFormedCasePasses(unittest.TestCase):
    """Without this, every failure below would be meaningless."""

    def test_no_problems(self):
        self.assertEqual(problems(WELL_FORMED), [])

    def test_the_measurements_are_sane(self):
        measured, notes, _ = check(WELL_FORMED)
        self.assertEqual(measured["references"], 1)
        self.assertEqual(measured["figures and tables"], 2)
        self.assertGreater(measured["abstract words"], 10)
        self.assertGreater(measured["text words"], 10)
        self.assertTrue(any("keywords: 4" in note for note in notes))


class CatchesAnAbstractThatBreaksTheRules(unittest.TestCase):
    def test_a_citation_in_the_abstract(self):
        damaged = damage("with no citation", "with a citation [3]")
        self.assertTrue(any("cites a reference" in p for p in problems(damaged)))

    def test_a_figure_named_in_the_abstract(self):
        damaged = damage("no figure named", "Fig. 2 named")
        self.assertTrue(any("names a figure" in p for p in problems(damaged)))

    def test_too_few_keywords(self):
        damaged = damage(
            "computed tomography, organ dose, Monte Carlo, dose index",
            "computed tomography, organ dose",
        )
        self.assertTrue(any("keywords" in p for p in problems(damaged)))

    def test_too_many_keywords(self):
        damaged = damage(
            "computed tomography, organ dose, Monte Carlo, dose index", "a, b, c, d, e, f, g"
        )
        self.assertTrue(any("keywords" in p for p in problems(damaged)))

    def test_no_keyword_line_at_all(self):
        damaged = damage(
            "**Keywords:** computed tomography, organ dose, Monte Carlo, dose index\n\n", ""
        )
        self.assertTrue(any("Keywords" in p for p in problems(damaged)))


class CatchesAStructureTheJournalDoesNotAskFor(unittest.TestCase):
    def test_a_section_renamed(self):
        damaged = damage("## 2. Materials and methods", "## 2. Methods")
        self.assertTrue(any("not the ones the journal expects" in p for p in problems(damaged)))

    def test_a_section_missing(self):
        damaged = damage("## 5. Conclusions\n\nSome conclusions.\n\n", "")
        self.assertTrue(any("not the ones the journal expects" in p for p in problems(damaged)))

    def test_a_gap_in_the_subsection_numbers(self):
        # "4.5 Limitations" under a Discussion whose other subsection is 4.1
        # tells the reader that 4.2 to 4.4 have gone missing. This was the real
        # state of the manuscript after the mechanical conversion.
        damaged = damage("### 4.2 Limitations", "### 4.5 Limitations")
        self.assertTrue(any("not 1..n" in p for p in problems(damaged)))

    def test_no_declarations_section(self):
        damaged = damage("## Declarations", "## Statements")
        self.assertTrue(any("'Declarations'" in p for p in problems(damaged)))

    def test_a_declaration_left_out(self):
        damaged = damage("**Ethics approval.** Waived.\n\n", "")
        self.assertTrue(any("Ethics approval" in p for p in problems(damaged)))

    def test_the_generative_ai_declaration_left_out(self):
        damaged = damage("**Use of generative artificial intelligence.**", "**Note.**")
        self.assertTrue(any("generative artificial intelligence" in p for p in problems(damaged)))

    def test_no_references_section(self):
        damaged = damage("## References", "## Bibliography")
        self.assertTrue(any("'References'" in p for p in problems(damaged)))


class CatchesABoldSentenceInTheBody(unittest.TestCase):
    """The author has objected to this every time and removed it by hand."""

    def test_bold_prose(self):
        damaged = damage("Some results.", "**One factor per organ does not improve on it.**")
        self.assertTrue(any("bold text" in p for p in problems(damaged)))

    def test_a_figure_label_in_bold_is_allowed(self):
        allowed = damage("Some results.", "Some results.\n\n**Figure 1.** A caption.")
        self.assertEqual([p for p in problems(allowed) if "bold" in p], [])


class CatchesABoundWithNoStatedScope(unittest.TestCase):
    """A referee rejected this manuscript once on exactly this."""

    def test_a_bound_in_the_title_without_a_scope_paragraph(self):
        damaged = damage("<!-- scope-of-claim -->\n", "")
        self.assertTrue(any("scope-of-claim" in p for p in problems(damaged)))

    def test_no_scope_paragraph_is_needed_when_nothing_is_bounded(self):
        unbounded = (
            damage(
                "# Between-patient variation sets the limit on index-based organ dose",
                "# Organ dose in abdominal CT from routine metadata",
            )
            .replace("<!-- scope-of-claim -->\n", "")
            .replace("The bound is over the conversions scored here.", "Nothing is bounded here.")
        )
        self.assertEqual([p for p in problems(unbounded) if "scope" in p], [])


class CountsAgainstTheLimits(unittest.TestCase):
    def test_a_body_over_the_limit(self):
        damaged = damage("Some introduction.", "word " * (limits.LIMITS["text words"] + 10))
        measured, _, _ = check(damaged)
        self.assertGreater(measured["text words"], limits.LIMITS["text words"])

    def test_an_abstract_over_the_limit(self):
        damaged = damage(
            "A short abstract that says what was done and what came of it, with no citation and\n"
            "no figure named, and comfortably under the limit.",
            "word " * (limits.LIMITS["abstract words"] + 10),
        )
        measured, _, _ = check(damaged)
        self.assertGreater(measured["abstract words"], limits.LIMITS["abstract words"])

    def test_a_title_over_the_limit(self):
        damaged = damage(
            "# Between-patient variation sets the limit on index-based organ dose",
            "# " + "word " * (limits.LIMITS["title words"] + 5),
        )
        measured, _, _ = check(damaged)
        self.assertGreater(measured["title words"], limits.LIMITS["title words"])

    def test_the_word_count_includes_a_lone_per_cent_sign(self):
        # SI style puts a space before the sign. Counting only tokens that hold
        # a letter or digit put this manuscript 70 words under what the
        # editorial office would measure.
        self.assertEqual(limits.words("the median was 24 % and the span 1.8 %"), 10)

    def test_headings_and_table_rows_are_not_prose(self):
        self.assertEqual(limits.words("## 3. Results\n\n| a | b |\n| - | - |\n\none two"), 2)

    def test_a_whole_caption_paragraph_is_excluded_not_just_its_first_line(self):
        # Figures and tables are outside the journal's count, and a caption is
        # part of its figure or table. Stripping only the line the label sits on
        # left a hundred and ten words of Table 1's caption in the total.
        text = (
            "one two three\n\n"
            "**Table 1.** A caption that runs\n"
            "onto a second line and then\n"
            "a third.\n\n"
            "four five\n"
        )
        self.assertEqual(limits.words(text), 5)

    def test_a_figure_caption_paragraph_is_excluded(self):
        text = "one\n\n**Figure 5.** A caption\nover two lines.\n\ntwo three\n"
        self.assertEqual(limits.words(text), 3)

    def test_the_count_is_the_journals_own_definition(self):
        # "Text words (main text, acknowledgments, declarations, and
        # appendices)", from the checklist the journal distributes. Counting the
        # numbered sections alone read 3996 of 4000 on a manuscript the journal
        # would have measured at 4313.
        text = (
            "# T\n\n## Abstract\n\nabstract words here\n\n"
            "**Keywords:** a, b, c, d\n\n"
            "## 1. Introduction\n\nintro words\n\n"
            "## 5. Conclusions\n\nconclusion words\n\n"
            "## Acknowledgments\n\nacknowledgment words\n\n"
            "## Declarations\n\n**Funding.** declaration words\n\n"
            "## References\n\n1. A reference that is not counted at all.\n"
        )
        counted = limits.counted_text(text)
        for inside in (
            "intro words",
            "conclusion words",
            "acknowledgment words",
            "declaration words",
        ):
            self.assertIn(inside, counted)
        for outside in ("abstract words here", "A reference that is not counted"):
            self.assertNotIn(outside, counted)


class TheRealManuscriptPasses(unittest.TestCase):
    """The built document, as the submission system will receive it."""

    def setUp(self):
        if not limits.BUILT.exists():
            self.skipTest(f"{limits.BUILT} has not been built")
        self.text = limits.BUILT.read_text(encoding="utf-8")

    def test_within_every_limit_and_correctly_structured(self):
        measured, _, found = check(self.text)
        over = [
            f"{name}: {measured[name]} > {limit}"
            for name, limit in limits.LIMITS.items()
            if measured[name] > limit
        ]
        self.assertEqual(over, [])
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

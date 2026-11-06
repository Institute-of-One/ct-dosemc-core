"""Plant each defect the retargeted journal checks exist to catch.

    python -m unittest paper.test_journal_checks -v

Three checks in presubmission_check.py were written for a different publisher
and have been pointed at this one: the data availability statement moved from a
section of its own into a labelled declaration, the generative-AI disclosure
moved with it, and the reference list went from Harvard alphabetical in the
source to Vancouver numbered in the built document.

A retargeted check is an unproved check. These plant the defects each one is
supposed to refuse, and require it to refuse them. The clean document is
required to pass as well, because a suite of expected failures cannot tell a
working check from one that fails on everything.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import presubmission_check as gate  # noqa: E402

BUILT = PAPER / "build" / "manuscript.md"

WELL_FORMED = """\
# A title

## 1. Introduction

Some text citing [1] and then [2, 3].

## 5. Conclusions

A conclusion.

## Acknowledgments

Thanks.

## Declarations

**Funding.** None.

**Conflict of interest.** None to declare.

**Ethics approval.** Waived; only public de-identified data were used.

**Data availability.** Openly available at https://doi.org/10.5281/zenodo.23537665.

**Code availability.** The same archive, under the MIT licence.

**Use of generative artificial intelligence.** An assistant (Claude Opus 5,
Anthropic) was used as a tool in developing the software.

## References

1. Someone A. A title. A Journal. 2020;1(1):1-2. https://doi.org/10.0000/a.

2. Another B. Another title. B Journal. 2021;2(2):3-4. https://doi.org/10.0000/b.

3. Third C. A third title. C Journal. 2022;3(3):5-6. https://doi.org/10.0000/c.
"""


def run(check, *args):
    """Run one check in isolation and return (failures, warnings)."""
    gate.errors.clear()
    gate.warnings.clear()
    check(*args)
    return list(gate.errors), list(gate.warnings)


def damage(old, new, text=WELL_FORMED):
    """``text`` with ``old`` replaced, refusing a replacement that did nothing."""
    if old not in text:
        raise AssertionError(f"the injection matched nothing: {old!r}")
    damaged = text.replace(old, new, 1)
    if damaged == text:
        raise AssertionError(f"the injection changed nothing: {old!r}")
    return damaged


class TheWellFormedCasePasses(unittest.TestCase):
    def test_data_availability(self):
        self.assertEqual(run(gate.check_code_is_reachable, WELL_FORMED)[0], [])

    def test_generative_ai(self):
        self.assertEqual(run(gate.check_generative_ai_is_declared, WELL_FORMED)[0], [])

    def test_references(self):
        self.assertEqual(run(gate.check_references, WELL_FORMED)[0], [])


class CatchesAMissingDeclaration(unittest.TestCase):
    def test_no_declarations_section_at_all(self):
        damaged = damage("## Declarations", "## Statements")
        failures, _ = run(gate.check_code_is_reachable, damaged)
        self.assertTrue(any("no Declarations section" in f for f in failures))

    def test_no_data_availability_statement(self):
        damaged = damage(
            "**Data availability.** Openly available at "
            "https://doi.org/10.5281/zenodo.23537665.\n\n", "")
        failures, _ = run(gate.check_code_is_reachable, damaged)
        self.assertTrue(any("Data availability" in f for f in failures))

    def test_a_data_statement_with_no_locator(self):
        damaged = damage(
            "Openly available at https://doi.org/10.5281/zenodo.23537665.",
            "Available in this repository.")
        failures, _ = run(gate.check_code_is_reachable, damaged)
        self.assertTrue(any("names no URL or DOI" in f for f in failures))

    def test_a_data_statement_with_a_url_but_no_doi(self):
        damaged = damage(
            "https://doi.org/10.5281/zenodo.23537665",
            "https://github.com/Institute-of-One/ct-dosemc-core")
        failures, _ = run(gate.check_code_is_reachable, damaged)
        self.assertTrue(any("not an archive" in f for f in failures))

    def test_each_required_declaration_in_turn(self):
        for label, line in (
            ("Funding", "**Funding.** None.\n\n"),
            ("Conflict of interest", "**Conflict of interest.** None to declare.\n\n"),
            ("Ethics approval",
             "**Ethics approval.** Waived; only public de-identified data were used.\n\n"),
            ("Code availability",
             "**Code availability.** The same archive, under the MIT licence.\n\n"),
        ):
            with self.subTest(label=label):
                failures, _ = run(gate.check_code_is_reachable, damage(line, ""))
                self.assertTrue(any(label in f for f in failures))


class CatchesAMissingGenerativeAiDisclosure(unittest.TestCase):
    def test_no_disclosure_anywhere(self):
        damaged = damage(
            "**Use of generative artificial intelligence.** An assistant (Claude Opus 5,\n"
            "Anthropic) was used as a tool in developing the software.\n", "")
        failures, _ = run(gate.check_generative_ai_is_declared, damaged)
        self.assertTrue(any("no generative-AI declaration" in f for f in failures))

    def test_a_disclosure_outside_the_declarations(self):
        # It was in the Acknowledgments while the paper was going to IOP. Left
        # there, it is not where this journal takes declarations.
        damaged = damage(
            "**Use of generative artificial intelligence.** An assistant (Claude Opus 5,\n"
            "Anthropic) was used as a tool in developing the software.\n", "")
        damaged = damage(
            "Thanks.",
            "Thanks. A generative artificial intelligence assistant (Claude Opus 5, "
            "Anthropic) was used as a tool.",
            damaged)
        failures, _ = run(gate.check_generative_ai_is_declared, damaged)
        self.assertTrue(any("not a labelled statement" in f for f in failures))

    def test_a_disclosure_naming_no_model(self):
        damaged = damage("(Claude Opus 5,\nAnthropic)", "a large language model")
        _, warned = run(gate.check_generative_ai_is_declared, damaged)
        self.assertTrue(any("names no model and vendor" in w for w in warned))


class CatchesABrokenReferenceList(unittest.TestCase):
    def test_a_citation_with_no_entry(self):
        damaged = damage("citing [1] and then [2, 3]", "citing [1] and then [2, 9]")
        failures, _ = run(gate.check_references, damaged)
        self.assertTrue(any("cited but not listed" in f for f in failures))

    def test_an_entry_nobody_cites(self):
        damaged = damage("citing [1] and then [2, 3]", "citing [1] and then [2]")
        failures, _ = run(gate.check_references, damaged)
        self.assertTrue(any("listed but never cited" in f for f in failures))

    def test_a_gap_in_the_numbering(self):
        damaged = damage("3. Third C.", "4. Third C.")
        damaged = damage("[2, 3]", "[2, 4]", damaged)
        failures, _ = run(gate.check_references, damaged)
        self.assertTrue(any("not 1..3" in f or "[1, 2, 4]" in f for f in failures))

    def test_references_numbered_out_of_citation_order(self):
        damaged = damage("citing [1] and then [2, 3]", "citing [3] and then [2, 1]")
        failures, _ = run(gate.check_references, damaged)
        self.assertTrue(any("not numbered in order of first citation" in f
                            for f in failures))

    def test_an_unnumbered_entry(self):
        damaged = damage("1. Someone A.", "Someone A.")
        failures, _ = run(gate.check_references, damaged)
        self.assertTrue(any("not numbered" in f for f in failures))

    def test_no_references_section(self):
        damaged = damage("## References", "## Bibliography")
        failures, _ = run(gate.check_references, damaged)
        self.assertTrue(any("no '## References' section" in f for f in failures))

    def test_an_untraceable_entry_is_warned_about(self):
        damaged = damage(
            "1. Someone A. A title. A Journal. 2020;1(1):1-2. https://doi.org/10.0000/a.",
            "1. Someone A. A title.")
        _, warned = run(gate.check_references, damaged)
        self.assertTrue(any("cannot follow them" in w for w in warned))


class TheRealBuiltManuscriptPasses(unittest.TestCase):
    def setUp(self):
        if not BUILT.exists():
            self.skipTest(f"{BUILT} has not been built")
        self.built = BUILT.read_text(encoding="utf-8")

    def test_all_three_retargeted_checks(self):
        for check in (gate.check_code_is_reachable,
                      gate.check_generative_ai_is_declared,
                      gate.check_references):
            with self.subTest(check=check.__name__):
                failures, _ = run(check, self.built)
                self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

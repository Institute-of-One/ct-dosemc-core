"""Standard-unittest tests for the four figure and claim gates.

    python -m unittest discover -s paper -v

These live beside ``presubmission_check.py`` rather than in ``tests/`` for one reason: the
rest of the suite uses pytest fixtures, and the cross-check framework this repository is
registered with runs standard ``unittest`` only, discovering from the manifest's root. A test
it cannot run is a test it will report as absent, and an absent test is not a pass.

Every case is a defect that reached a submitted manuscript, or the corrected form of one.
Nothing here touches ``paper/figures/`` or the real ledger: the image cases build their own
files in a temporary directory and the module globals are swapped back in ``tearDown``.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import collect_figures                                       # noqa: E402
import presubmission_check as gate                           # noqa: E402


class GateCase(unittest.TestCase):
    """Give every test its own error list and put the module back as it was."""

    def setUp(self) -> None:
        self._errors, self._warnings = gate.errors, gate.warnings
        self._sources = collect_figures.FIGURE_SOURCES
        self._figures, self._paper = gate.FIGURES, gate.PAPER
        gate.errors, gate.warnings = [], []

    def tearDown(self) -> None:
        gate.errors, gate.warnings = self._errors, self._warnings
        collect_figures.FIGURE_SOURCES = self._sources
        gate.FIGURES, gate.PAPER = self._figures, self._paper

    def assertCaught(self, why: str) -> None:
        self.assertTrue(gate.errors, f"the check passed {why}")

    def assertClean(self, why: str) -> None:
        self.assertFalse(gate.errors, f"the check reported {why}: {gate.errors}")


class FigureCitationOrder(GateCase):
    def setUp(self) -> None:
        super().setUp()
        # The gate only orders this manuscript's own figures, so a case about ordering has
        # to declare which figures exist. Twelve is more than any case below uses.
        collect_figures.FIGURE_SOURCES = {n: (f"figure{n}.png", None) for n in range(1, 13)}

    def test_a_later_figure_named_first_is_caught(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "Per-organ values are in figure 6; plotted against the index (figure 4)."
        )
        self.assertCaught("a manuscript that names figure 6 before figure 4")

    def test_the_message_names_both_figures(self) -> None:
        gate.check_figures_are_first_cited_in_order("see figure 3, and earlier figure 1")
        self.assertCaught("figure 3 before figure 1")
        self.assertIn("figure 3", gate.errors[0])
        self.assertIn("figure 1", gate.errors[0])

    def test_figures_named_in_order_pass(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "text citing figure 1, then figure 2, then figure 3 at the end."
        )
        self.assertClean("a manuscript whose figures are named in order")

    def test_a_repeated_mention_does_not_count_as_a_first_one(self) -> None:
        # figure 1 is named again after figure 2; only the first mention of each matters.
        gate.check_figures_are_first_cited_in_order("figure 1 ... figure 2 ... figure 1 again")
        self.assertClean("a second mention of figure 1 after figure 2")

    def test_abbreviated_forms_are_recognised(self) -> None:
        gate.check_figures_are_first_cited_in_order("as fig. 6 shows, and later fig. 4")
        self.assertCaught("the abbreviated form 'fig. 6' before 'fig. 4'")

    def test_two_digit_numbers_are_not_confused_with_one(self) -> None:
        gate.check_figures_are_first_cited_in_order("figure 1 then figure 10 then figure 11")
        self.assertClean("figures 1, 10 and 11 named in order")

    def test_a_two_digit_figure_named_too_early_is_caught(self) -> None:
        # The clean case above passes under an implementation that reads only the first
        # digit, because 1, 10 and 11 all look like figure 1 to it. This one does not.
        gate.check_figures_are_first_cited_in_order("as figure 10 shows, and later figure 2")
        self.assertCaught("figure 10 named before figure 2")

    def test_a_plural_citation_is_read(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "Values are in figures 6 and 7. Later, figure 4 and figure 5."
        )
        self.assertCaught("a first citation written as 'figures 6 and 7'")

    def test_a_plural_citation_in_order_passes(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "Values are in figures 1 and 2. Later, figure 3."
        )
        self.assertClean("plural citations that are in order")

    def test_every_number_in_a_list_citation_counts_as_a_first_mention(self) -> None:
        # Only the second number of the first citation is out of place, so the message has
        # to name it. Reading one number per citation makes figure 7 invisible and clean.
        gate.check_figures_are_first_cited_in_order(
            "Values are in figures 1 and 7. Then figure 2, figure 3, figure 4, figure 5, "
            "figure 6."
        )
        self.assertCaught("figure 7 first named inside a list, before figure 6")
        self.assertTrue(
            any("figure 7" in message for message in gate.errors),
            f"figure 7 was not among the figures reported: {gate.errors}",
        )

    def test_a_range_names_the_figures_between_its_ends(self) -> None:
        # Figure 2 is named only by the range. If a range did not expand, its first mention
        # would be the later one and the gate would report 2 as cited after 3.
        gate.check_figures_are_first_cited_in_order(
            "figures 1-3 are the design; figure 2 is the gate; figure 4 follows."
        )
        self.assertClean("a range that already named figure 2")

    def test_a_range_cited_out_of_order_is_caught(self) -> None:
        gate.check_figures_are_first_cited_in_order("see figures 4-6, then figure 1")
        self.assertCaught("a range citing figures 4 to 6 before figure 1")

    def test_a_plural_citation_continued_by_a_comma_is_refused(self) -> None:
        # The form is narrowed because it cannot be parsed; narrowing it has to be enforced
        # or it is only a comment. Write "figures 1 and 2 and 3".
        gate.check_figures_are_first_cited_in_order(
            "figures 1, 2 and 3 are the design; figure 4 follows."
        )
        self.assertCaught("a plural citation continued by a comma")
        self.assertIn("write 'and' instead", gate.errors[0])

    def test_a_comma_after_a_parsed_list_is_also_refused(self) -> None:
        # "figures 1 and 2, 6" parses cleanly up to the comma and then drops figure 6 in
        # silence, which is the same hole one step further along.
        gate.check_figures_are_first_cited_in_order(
            "See figures 1 and 2, 6. Then figure 3, figure 4, figure 5, figure 6."
        )
        self.assertCaught("a comma following a citation that had already parsed")

    def test_a_panel_letter_does_not_end_a_citation(self) -> None:
        # The manuscript writes "figure 1b" and "figure 5a", so a list can carry one.
        gate.check_figures_are_first_cited_in_order(
            "See figures 1(a) and 6. Then figure 2, figure 3, figure 4, figure 5."
        )
        self.assertCaught("figure 6 named after a panel letter, before figures 2 to 5")

    def test_every_joiner_the_pattern_accepts_can_be_parsed(self) -> None:
        # The citation pattern and the number parser listed their separators separately, so
        # a joiner added to one and not the other left "1 or 2" unsplit and int() raised on
        # a correct manuscript. They are built from one fragment now; this holds them to it.
        for text in (
            "figures 1 or 2, then figure 3",
            "figures 1 through 3, then figure 4",
            "figures 1 to 3, then figure 4",
            "figures 1 and 2, then figure 3",
            "figures 1 & 2, then figure 3",
            "figures 1/2, then figure 3",
            "figures 1 vs. 2, then figure 3",
            "figures 1-3, then figure 4",
        ):
            with self.subTest(text=text):
                gate.errors.clear()
                gate.check_figures_are_first_cited_in_order(text)
                self.assertClean(f"{text!r}, which is in order")

    def test_an_emphasised_citation_is_still_a_citation(self) -> None:
        # "_" is a word character, so a citation touching Markdown emphasis was invisible.
        gate.check_figures_are_first_cited_in_order(
            "_Figure 6_ gives the vendors. Then figure 1, figure 2, figure 3."
        )
        self.assertCaught("figure 6 cited first, inside underscore emphasis")

    def test_a_filename_is_not_a_citation(self) -> None:
        # The data-availability prose names files like figure4_stats.json and figure6.png.
        gate.check_figures_are_first_cited_in_order(
            "Statistics are frozen in figure4_stats.json. Figure 1, then figure 2."
        )
        self.assertClean("a filename that begins with 'figure4'")

    def test_a_filename_with_an_extension_is_not_a_citation(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "The image file is figure6.png. Figure 1; figure 2; figure 3; figure 4; "
            "figure 5; figure 6."
        )
        self.assertClean("the filename 'figure6.png'")

    def test_a_citation_at_the_end_of_a_sentence_is_still_a_citation(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "The vendors are in figure 6. The funnel is figure 1."
        )
        self.assertCaught("figure 6 cited first, with a full stop after the number")

    def test_a_panel_letter_does_not_slip_past_the_comma_rule(self) -> None:
        # The two patterns are built from one number definition because they drifted apart:
        # panel letters went into the citation pattern and not into the comma rule, and
        # "figures 1a, 6" walked through.
        gate.check_figures_are_first_cited_in_order(
            "See figures 1a, 6. Then figure 2, figure 3, figure 4, figure 5."
        )
        self.assertCaught("a comma list whose first number carries a panel letter")

    def test_a_panel_range_does_not_end_a_citation(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "See figures 1a-c and 6. Then figure 2, figure 3, figure 4, figure 5."
        )
        self.assertCaught("figure 6 named after a panel range, before figures 2 to 5")

    def test_a_panel_range_is_still_one_figure(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "See figures 1a-c. Then figure 2, figure 3."
        )
        self.assertClean("'figures 1a-c', which is three panels of figure 1")

    def test_a_panel_letter_is_not_a_different_figure(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "figure 1 shows the funnel, figure 1b the reasons, then figure 2."
        )
        self.assertClean("figure 1b, which is a panel of figure 1")

    def test_a_repeat_cannot_hide_an_earlier_first_mention(self) -> None:
        # Keeping the last mention instead of the first would make this clean.
        gate.check_figures_are_first_cited_in_order(
            "figure 2 opens it, then figure 1, and figure 2 again at the end."
        )
        self.assertCaught("figure 2 named before figure 1 and repeated afterwards")

    def test_a_singular_comma_list_of_our_figures_is_refused(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "See fig. 1, 6. Then figure 2, figure 3, figure 4, figure 5, figure 6."
        )
        self.assertCaught("'fig. 1, 6', a comma list in the singular form")

    def test_a_singular_citation_followed_by_a_count_is_not_refused(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "In figure 1, 38 of 40 series pass the gate. Figure 2 shows the density gate."
        )
        self.assertClean("a singular citation followed by a comma and a count")

    def test_a_reversed_pair_inside_one_citation_is_caught(self) -> None:
        # A reader meets figure 2 before figure 1 even though both are in one citation.
        gate.check_figures_are_first_cited_in_order("See figures 2 and 1.")
        self.assertCaught("'figures 2 and 1', which puts figure 2 in front")

    def test_a_count_after_a_comma_is_not_a_figure(self) -> None:
        # "In figure 1, 38 of 40 series pass" is a citation and a count. Reading the 38 as
        # a figure number failed a correct manuscript.
        gate.check_figures_are_first_cited_in_order(
            "In figure 1, 38 of 40 series pass the gate. Figure 2 shows the density gate."
        )
        self.assertClean("a count that happens to follow a figure citation and a comma")

    def test_a_count_that_is_also_a_figure_number_is_refused(self) -> None:
        # Twelve figures are registered here, so "figure 1, 12 and 28 series" could be a
        # count or a citation of figure 12 and nothing in the text says which. It is
        # refused, which is the documented trade-off: rewrite the sentence.
        gate.check_figures_are_first_cited_in_order(
            "In figure 1, 12 and 28 series were excluded. Figure 2 shows the gate."
        )
        self.assertCaught("a count whose first number is also one of our figures")

    def test_a_comma_list_that_would_hide_a_first_mention_is_refused(self) -> None:
        # The defect the narrowing exists for: read as its first number only, this text
        # passes although a reader meets figure 6 before figures 2 to 5. It is refused
        # instead of parsed.
        gate.check_figures_are_first_cited_in_order(
            "Dose is in figs. 1, 6. Then figure 2, figure 3, figure 4, figure 5, figure 6."
        )
        self.assertCaught("a comma list that hides figure 6's real first mention")

    def test_a_figure_of_another_work_is_not_ours(self) -> None:
        collect_figures.FIGURE_SOURCES = {n: (f"figure{n}.png", None) for n in (1, 2, 3)}
        gate.check_figures_are_first_cited_in_order(
            "The geometry is figure 7 of Sechopoulos et al (2015). Figure 1 shows the "
            "funnel; figure 2 the gate; figure 3 the verification."
        )
        self.assertClean("a citation of figure 7 of another paper, in a paper with three")

    def test_another_work_s_figure_whose_number_is_also_ours(self) -> None:
        # The number collides with one of ours, so "of Sechopoulos" is the only signal.
        gate.check_figures_are_first_cited_in_order(
            "The geometry is figure 3 of Sechopoulos et al (2015). Figure 1 shows the "
            "funnel; figure 2 the gate; figure 3 the verification."
        )
        self.assertClean("a foreign figure 3 in a manuscript that also has a figure 3")

    def test_our_own_figure_followed_by_of_is_still_ours(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "figure 3 of this study comes last; figure 1 is the funnel."
        )
        self.assertCaught("'figure 3 of this study', which is ours and cited first")

    def test_a_section_name_after_in_does_not_make_a_figure_foreign(self) -> None:
        # Requiring only a capital letter after "of" or "in" let these be read as other
        # papers' figures, which is a way to pass a manuscript that is out of order.
        for text in (
            "figure 3 in Section 4 comes last; figure 1 is the funnel.",
            "figure 3 in Results comes last; figure 1 is the funnel.",
            "figure 3 from the Appendix comes last; figure 1 is the funnel.",
        ):
            with self.subTest(text=text):
                gate.errors.clear()
                gate.check_figures_are_first_cited_in_order(text)
                self.assertCaught(f"{text!r}, which cites our own figure 3 first")

    def test_an_acronym_reference_is_foreign(self) -> None:
        gate.check_figures_are_first_cited_in_order(
            "The geometry is figure 3 of TG-195. Figure 1 is the funnel; figure 2 the gate; "
            "figure 3 the verification."
        )
        self.assertClean("'figure 3 of TG-195', which is a standard's figure")

    def test_a_figure_named_in_a_comment_is_not_a_citation(self) -> None:
        # Comments survive into the built manuscript -- that is how the scope marker gets
        # there -- so an editorial note must not be read as a citation.
        gate.check_figures_are_first_cited_in_order(
            "<!-- check figure 9 before submitting -->\nfigure 1 then figure 2"
        )
        self.assertClean("a figure named only inside an HTML comment")


class FigureRenumberedOnTheWayIn(GateCase):
    def test_a_source_drawn_under_a_different_number_is_caught(self) -> None:
        collect_figures.FIGURE_SOURCES = {
            6: ("figure6_vendor.png", "phase2_cohort/figure5_vendor.png")
        }
        gate.check_no_figure_is_renumbered_on_the_way_in("")
        self.assertCaught("a figure 6 copied from a file drawn as figure 5")
        self.assertIn("figure 5", gate.errors[0])

    def test_a_source_drawn_under_the_same_number_passes(self) -> None:
        collect_figures.FIGURE_SOURCES = {
            6: ("figure6_vendor.png", "phase2_cohort/figure6_vendor.png")
        }
        gate.check_no_figure_is_renumbered_on_the_way_in("")
        self.assertClean("a figure copied from a file drawn under the same number")

    def test_a_source_with_no_number_in_its_name_passes(self) -> None:
        collect_figures.FIGURE_SOURCES = {
            6: ("figure6_vendor.png", "phase2_cohort/vendor_organ_dose.png")
        }
        gate.check_no_figure_is_renumbered_on_the_way_in("")
        self.assertClean("a source file that carries no figure number at all")

    def test_fig_inside_another_word_is_not_a_drawn_number(self) -> None:
        collect_figures.FIGURE_SOURCES = {
            6: ("figure6_vendor.png", "phase2_cohort/config2_figure6_vendor.png")
        }
        gate.check_no_figure_is_renumbered_on_the_way_in("")
        self.assertClean("'config2' being read as the number the figure was drawn under")

    def test_a_figure_drawn_in_place_has_no_source_to_disagree_with(self) -> None:
        collect_figures.FIGURE_SOURCES = {5: ("figure5_conversion_ceiling.png", None)}
        gate.check_no_figure_is_renumbered_on_the_way_in("")
        self.assertClean("a figure drawn directly into paper/figures/")


class FigureImageWasLookedAt(GateCase):
    def _temporary_figure(self, directory: str, content: bytes) -> str:
        image = Path(directory) / "figure4_scatter.png"
        image.write_bytes(content)
        collect_figures.FIGURE_SOURCES = {4: ("figure4_scatter.png", None)}
        gate.FIGURES = Path(directory)
        gate.PAPER = Path(directory)
        return hashlib.sha256(content).hexdigest()

    def _ledger(self, directory: str, entries: dict) -> None:
        (Path(directory) / "figures_reviewed.json").write_text(
            json.dumps({"figures": entries}), encoding="utf-8"
        )

    def test_an_unrecorded_image_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._temporary_figure(directory, b"\x89PNG\r\n\x1a\n first drawing")
            self._ledger(directory, {})
            gate.check_every_figure_image_has_been_looked_at()
            self.assertCaught("an image nobody has recorded as looked at")

    def test_an_image_recorded_at_its_current_hash_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            digest = self._temporary_figure(directory, b"\x89PNG\r\n\x1a\n first drawing")
            self._ledger(directory, {"figure4_scatter.png": {"sha256": digest}})
            gate.check_every_figure_image_has_been_looked_at()
            self.assertClean("an image recorded at the hash it still has")

    def test_an_image_redrawn_after_recording_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            digest = self._temporary_figure(directory, b"\x89PNG\r\n\x1a\n first drawing")
            self._ledger(
                directory, {"figure4_scatter.png": {"sha256": digest, "reviewed": "2026-10-21"}}
            )
            (Path(directory) / "figure4_scatter.png").write_bytes(b"\x89PNG\r\n\x1a\n redrawn")
            gate.check_every_figure_image_has_been_looked_at()
            self.assertCaught("an image redrawn since it was last looked at")

    def test_a_registered_image_that_is_not_on_disk_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            collect_figures.FIGURE_SOURCES = {4: ("figure4_scatter.png", None)}
            gate.FIGURES = Path(directory)
            gate.PAPER = Path(directory)
            gate.check_every_figure_image_has_been_looked_at()
            self.assertCaught("a registered figure with no file behind it")

    def test_a_missing_ledger_is_not_a_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._temporary_figure(directory, b"\x89PNG\r\n\x1a\n drawing")
            gate.check_every_figure_image_has_been_looked_at()
            self.assertCaught("every image, when the ledger file does not exist at all")


class BoundingClaimDeclaresItsScope(GateCase):
    TITLED = "# A measured floor on index-based organ dose estimation\n\nAbstract.\n\n## 1\n"
    PLAIN = "# Organ dose recovered from an index in forty abdominal series\n\nAbstract.\n\n## 1\n"
    DECLARED = (
        "The bound is over the five conversions evaluated here, cross-validated on this "
        "cohort of forty series, and not over index-based conversion in general."
    )

    def test_a_bounding_title_with_no_declared_scope_is_caught(self) -> None:
        gate.check_a_bounding_claim_declares_its_scope("body text", self.TITLED)
        self.assertCaught("a title claiming a floor with no scope paragraph")

    def test_a_declared_scope_that_reaches_the_build_passes(self) -> None:
        source = f"{gate._SCOPE_MARKER}\n{self.DECLARED}\n\n"
        gate.check_a_bounding_claim_declares_its_scope(source, self.TITLED + self.DECLARED)
        self.assertClean("a title whose scope is declared and carried into the build")

    def test_a_scope_lost_before_the_build_is_caught(self) -> None:
        source = f"{gate._SCOPE_MARKER}\n{self.DECLARED}\n\n"
        gate.check_a_bounding_claim_declares_its_scope(source, self.TITLED)
        self.assertCaught("a scope paragraph that never reaches the built manuscript")

    def test_the_length_rule_is_what_rejects_a_short_paragraph(self) -> None:
        # Isolated from the survival rule: this paragraph does reach the build word for
        # word, so only the minimum length can be what reports it.
        short = "Over the five conversions."
        gate.check_a_bounding_claim_declares_its_scope(
            f"{gate._SCOPE_MARKER}\n{short}\n\n", self.TITLED + short
        )
        self.assertCaught("a scope paragraph that survives intact but says too little")
        self.assertIn("words of prose", gate.errors[0])

    def test_one_long_token_is_not_a_paragraph(self) -> None:
        token = "x" * 80
        gate.check_a_bounding_claim_declares_its_scope(
            f"{gate._SCOPE_MARKER}\n{token}\n\n", self.TITLED + token
        )
        self.assertCaught("eighty characters that are all one word")

    def test_a_token_scope_paragraph_is_caught(self) -> None:
        gate.check_a_bounding_claim_declares_its_scope(
            f"{gate._SCOPE_MARKER}\nOver five conversions.\n\n", self.TITLED
        )
        self.assertCaught("a marked paragraph too short to delimit anything")

    def test_a_title_claiming_no_bound_requires_nothing(self) -> None:
        gate.check_a_bounding_claim_declares_its_scope("body text", self.PLAIN)
        self.assertClean("a title that claims no bound")

    def test_a_bound_claimed_in_the_abstract_is_seen(self) -> None:
        # The first '## ' heading is '## Abstract', so a check that stops at the first
        # heading reads the title alone and never sees the abstract at all.
        gate.check_a_bounding_claim_declares_its_scope(
            "body",
            "# Organ dose recovered from an index\n\n## Abstract\n\n"
            "Main results. The error is an irreducible limit on conversion.\n\n"
            "## 1. Introduction\n",
        )
        self.assertCaught("a bound claimed in the abstract body")

    def test_a_scope_paragraph_containing_markers_passes(self) -> None:
        # check_no_typed_numbers requires numbers to be markers, and a scope paragraph
        # states cohort sizes, so markers inside it are the normal case, not an edge one.
        source = (
            f"{gate._SCOPE_MARKER}\nThe bound is over [[results:n]] series and the five "
            "conversions evaluated here, not over index-based conversion in general.\n\n"
        )
        built = (
            "# A measured floor on index-based organ dose estimation\n\nAbstract.\n\n"
            "The bound is over 40 series and the five conversions evaluated here, not "
            "over index-based conversion in general.\n"
        )
        gate.check_a_bounding_claim_declares_its_scope(source, built)
        self.assertClean("a scope paragraph whose numbers are interpolated")

    def test_a_blank_line_carrying_a_space_still_ends_the_paragraph(self) -> None:
        source = f"{gate._SCOPE_MARKER}\n{self.DECLARED}\n \nAn unrelated paragraph.\n\n"
        built = self.TITLED + self.DECLARED + "\n\nAn unrelated paragraph.\n"
        gate.check_a_bounding_claim_declares_its_scope(source, built)
        self.assertClean("a blank line that happens to carry a space")

    def test_a_marker_wrapped_across_a_source_line_is_still_a_marker(self) -> None:
        source = (
            f"{gate._SCOPE_MARKER}\nThe bound is over [[results:\nn]] series and the five "
            "conversions evaluated here, not over index-based conversion in general.\n\n"
        )
        built = (
            self.TITLED + "The bound is over 40 series and the five conversions evaluated "
            "here, not over index-based conversion in general.\n"
        )
        gate.check_a_bounding_claim_declares_its_scope(source, built)
        self.assertClean("a marker the source wrapped across a line")

    def test_a_scope_paragraph_wrapped_differently_in_the_build_passes(self) -> None:
        source = (
            f"{gate._SCOPE_MARKER}\nThe bound is over the five conversions\nevaluated "
            "here, and not over index-based conversion in general.\n\n"
        )
        built = (
            "# A measured floor on index-based organ dose estimation\n\nAbstract.\n\n"
            "The bound is over the five conversions evaluated here, and not over\n"
            "index-based conversion in general.\n"
        )
        gate.check_a_bounding_claim_declares_its_scope(source, built)
        self.assertClean("a scope paragraph the build re-wrapped")

    def test_a_word_inside_a_longer_word_does_not_trigger_it(self) -> None:
        gate.check_a_bounding_claim_declares_its_scope(
            "body", "# An overall index of abdominal dose\n\nAbstract.\n\n## 1\n"
        )
        self.assertClean("'overall index', which merely contains 'all index'")

    def test_a_bounding_phrase_broken_across_a_line_is_still_seen(self) -> None:
        gate.check_a_bounding_claim_declares_its_scope(
            "body", "# A conversion no better\nthan a single factor\n\nAbstract.\n\n## 1\n"
        )
        self.assertCaught("'no better than' wrapped across a line")

    def test_a_bounding_word_below_the_abstract_does_not_trigger_it(self) -> None:
        # The check reads the title and abstract, which is where a claim is made; the word
        # appearing in a Discussion that is busy qualifying it is not the same thing. The
        # manuscript has a real '## Abstract' heading, so the case has one: without it this
        # text stops at '## 1' and an implementation that never reads past the title passes
        # for the wrong reason.
        gate.check_a_bounding_claim_declares_its_scope(
            "body",
            "# Organ dose recovered from an index\n\n## Abstract\n\n"
            "Main results. Twelve coefficients did not beat one number.\n\n"
            "## 1. Introduction\n\nbackground\n\n"
            "## 4. Discussion\n\nwhether this floor generalises is another question\n",
        )
        self.assertClean("the word 'floor' appearing only in the Discussion")

    def test_a_section_before_the_abstract_is_not_part_of_the_claim(self) -> None:
        # A keyword list is not where a claim is made. Reading everything up to the abstract
        # made a keyword of "floor" demand a scope paragraph.
        gate.check_a_bounding_claim_declares_its_scope(
            "body",
            "# Organ dose estimation\n\n## Keywords\n\nfloor, dose, CT\n\n"
            "## Abstract\n\nWe measured conversion error on forty series.\n\n## 1\n",
        )
        self.assertClean("the word 'floor' appearing only in a keyword list")

    def test_an_emphasised_bounding_word_is_caught(self) -> None:
        # "_" is a word character, so \b never matches between "_" and "f".
        gate.check_a_bounding_claim_declares_its_scope(
            "body", "# A measured _floor_ on index-based organ dose\n\nAbstract.\n\n## 1\n"
        )
        self.assertCaught("a bounding word in Markdown emphasis")

    def test_an_emphasised_abstract_heading_is_still_the_abstract(self) -> None:
        gate.check_a_bounding_claim_declares_its_scope(
            "body",
            "# Organ dose recovered from an index\n\n## **Abstract**\n\n"
            "Main results. The error is an irreducible limit.\n\n## 1\n",
        )
        self.assertCaught("a bound in an abstract whose heading is bold")

    def test_a_heading_inside_a_comment_does_not_end_the_scan(self) -> None:
        gate.check_a_bounding_claim_declares_its_scope(
            "body",
            "# Organ dose recovered from an index\n\n<!-- ## Notes to self -->\n\n"
            "## Abstract\n\nMain results. The error is an irreducible limit.\n\n## 1\n",
        )
        self.assertCaught("a bound in the abstract, behind a heading inside a comment")

    def test_a_section_before_the_abstract_does_not_hide_it(self) -> None:
        gate.check_a_bounding_claim_declares_its_scope(
            "body",
            "# Organ dose recovered from an index\n\n## Keywords\n\ndose, CT\n\n"
            "## Abstract\n\nMain results. The error is an irreducible limit.\n\n## 1\n",
        )
        self.assertCaught("a bound in an abstract that follows another section")

    def test_a_plural_bounding_phrase_is_caught(self) -> None:
        # The optional trailing s pluralises the last word, which gives "any indexs" for
        # "any index"; the irregular plurals have to be listed.
        gate.check_a_bounding_claim_declares_its_scope(
            "body", "# A bound over any indices of dose\n\nAbstract.\n\n## 1\n"
        )
        self.assertCaught("'any indices', the plural of a listed phrase")

    def test_an_inflected_bounding_word_is_caught(self) -> None:
        gate.check_a_bounding_claim_declares_its_scope(
            "body", "# Two floors on index-based organ dose estimation\n\nAbstract.\n\n## 1\n"
        )
        self.assertCaught("a title saying 'floors' rather than 'floor'")

    def test_a_scope_paragraph_made_of_markers_is_not_long_enough(self) -> None:
        # The 80-character minimum used to count the raw marker text, so a paragraph that
        # says nothing itself could clear it.
        source = (
            f"{gate._SCOPE_MARKER}\nOver [[a:a]] and [[b:b]] and [[c:c]] and [[d:d]] and "
            "[[e:e]] and [[f:f]] and [[g:g]] runs.\n\n"
        )
        gate.check_a_bounding_claim_declares_its_scope(source, self.TITLED)
        self.assertCaught("a scope paragraph that is mostly interpolation markers")

    def test_passages_present_but_scattered_do_not_count_as_survival(self) -> None:
        # Every passage of the paragraph exists in the build, in different sections and in
        # the wrong order. That is not the paragraph reaching the manuscript.
        source = (
            f"{gate._SCOPE_MARKER}\nThe bound is over the five conversions evaluated here "
            "in [[r:n]] series, and is not a claim about index-based conversion in "
            "general.\n\n"
        )
        built = (
            "# A measured floor\n\n## Abstract\n\nx\n\n## 1\n\n"
            "series, and is not a claim about index-based conversion in general.\n\n"
            "Elsewhere entirely: The bound is over the five conversions evaluated here in\n"
        )
        gate.check_a_bounding_claim_declares_its_scope(source, built)
        self.assertCaught("passages that are all present but not together and in order")

    def test_a_scope_paragraph_that_survives_only_in_part_is_caught(self) -> None:
        # A surviving fragment is not a surviving paragraph.
        source = (
            f"{gate._SCOPE_MARKER}\nThe bound is over the five conversions evaluated here. "
            "It is not a claim about index-based conversion in general.\n\n"
        )
        built = (
            self.TITLED + "The bound is over the five conversions evaluated here.\n"
        )
        gate.check_a_bounding_claim_declares_its_scope(source, built)
        self.assertCaught("a scope paragraph whose second sentence never reached the build")

    def test_every_bounding_word_is_detected(self) -> None:
        for word in gate._BOUNDING_WORDS:
            with self.subTest(word=word):
                gate.errors.clear()
                gate.check_a_bounding_claim_declares_its_scope(
                    "body", f"# A result that is {word} here\n\nAbstract.\n\n## 1\n"
                )
                self.assertCaught(f"a title containing {word!r}")


if __name__ == "__main__":
    unittest.main()

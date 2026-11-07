"""Each check must fire on the defect it was written for.

A check that has never been seen to fail is a check that might not work. Every
case below is the shape of a defect that actually reached a built manuscript or an
editorial office in this programme.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PAPER = Path(__file__).resolve().parents[1] / "paper"
sys.path.insert(0, str(PAPER))

import presubmission_check as check  # noqa: E402


@pytest.fixture(autouse=True)
def clean() -> None:
    check.errors.clear()
    check.warnings.clear()


def test_a_control_character_is_caught() -> None:
    check.check_control_characters("an abstract with a stray \x0b in it")
    assert check.errors


def test_clean_text_passes() -> None:
    check.check_control_characters("an abstract\nwith\ttabs and newlines only")
    assert not check.errors


def test_an_unresolved_marker_is_caught() -> None:
    check.check_markers_resolved("Pearson r was [[results:manifest.json:metrics.x]].")
    assert check.errors


def test_bold_mid_sentence_is_caught() -> None:
    check.check_emphasis("The index and the dose are **not the same quantity** here.")
    assert check.warnings or check.errors


def test_a_run_in_heading_is_allowed() -> None:
    check.check_emphasis("**Verification.** The engine agrees with PENELOPE.")
    assert not check.errors and not check.warnings


def test_a_typed_metric_is_caught() -> None:
    """The Pearson r, typed as digits instead of resolved from the freeze."""
    source = "The correlation was 0.6601 across all series."
    check.check_no_typed_numbers(source, "")
    assert check.errors, "a frozen metric typed into the source was not caught"


def test_the_marker_form_of_the_same_number_passes() -> None:
    source = "The correlation was [[results:manifest.json:metrics.pearson_r_all|.2f]]."
    check.check_no_typed_numbers(source, "")
    assert not check.errors


def test_the_mid_scan_defect_file_cannot_be_cited() -> None:
    check.check_the_defective_file_is_not_cited("Doses are in `figure4_y_axis.json`.", "")
    assert check.errors


def test_a_data_and_code_section_without_a_locator_is_caught() -> None:
    built = "## Data and code\n\nSoftware under the MIT licence, in this repository.\n\n## Next\n"
    check.check_code_is_reachable(built)
    assert check.errors


def test_a_data_availability_declaration_with_a_doi_passes() -> None:
    """Springer puts the statement inside Declarations, under its own bold label.

    IOP wanted it as a section heading of its own, and this test kept that shape
    for a day after the checker moved to the Springer one -- long enough to fail
    on every run and be read as noise.
    """
    built = (
        "## Acknowledgments\n\nThanks.\n\n"
        "## Declarations\n\n"
        "**Funding.** None.\n\n"
        "**Conflict of interest.** None.\n\n"
        "**Ethics approval.** Waived.\n\n"
        "**Data availability.** The frozen result tables are openly available at "
        "https://doi.org/10.5281/zenodo.22233153 under the MIT licence.\n\n"
        "**Code availability.** The same archive.\n"
    )
    check.check_code_is_reachable(built)
    assert not check.errors


def test_a_missing_data_and_code_section_is_caught() -> None:
    check.check_code_is_reachable("## Results\n\nNothing about code.\n")
    assert check.errors


#: A minimal built manuscript in the journal's style: numbered citations in the
#: body, a numbered list under "## References". check_references reads the built
#: document, never the source, because the source carries one [[references]]
#: marker and no numbers at all.
def _built(body: str, *entries: str) -> str:
    listed = "\n\n".join(entries)
    return f"{body}\n\n## References\n\n{listed}\n"


def test_references_out_of_citation_order_are_caught() -> None:
    """Vancouver numbers by first appearance in the prose, not by surname.

    These five tests injected author-year defects into a checker that had been
    rewritten for numbered references, and failed on every run from the day the
    submission moved from IOP to Springer. That is worse than having no tests: a
    permanently red suite stops being read, and nothing then established that the
    numbered checks caught anything at all.
    """
    check.check_references(
        _built(
            "Body cites [2] and then [1].",
            "1. Alpha A. An earlier work. J. 2019;1:1. https://doi.org/10.0000/a.",
            "2. Zeta B. A later work. J. 2020;2:2. https://doi.org/10.0000/b.",
        )
    )
    assert any("not numbered in order of first citation" in message for message in check.errors)


def test_an_uncited_reference_is_caught() -> None:
    check.check_references(
        _built(
            "Body cites [1].",
            "1. Alpha A. A cited work. J. 2019;1:1. https://doi.org/10.0000/a.",
            "2. Orphan O. Never mentioned. J. 2021;3:3. https://doi.org/10.0000/b.",
        )
    )
    assert any("listed but never cited" in message for message in check.errors)


def test_a_citation_with_no_entry_is_caught() -> None:
    check.check_references(
        _built(
            "Body cites [1] and [2].",
            "1. Alpha A. A cited work. J. 2019;1:1. https://doi.org/10.0000/a.",
        )
    )
    assert any("cited but not listed" in message for message in check.errors)


def test_a_gap_in_the_numbering_is_caught() -> None:
    check.check_references(
        _built(
            "Body cites [1] and [3].",
            "1. Alpha A. A cited work. J. 2019;1:1. https://doi.org/10.0000/a.",
            "3. Gamma C. A third work. J. 2021;3:3. https://doi.org/10.0000/c.",
        )
    )
    assert any("the reference numbers are" in message for message in check.errors)


def test_a_reference_a_reader_cannot_follow_warns() -> None:
    """Neither a DOI nor a publisher and year is the shape of a fabrication."""
    check.check_references(
        _built(
            "Body cites [1].",
            "1. Alpha A. A book with no identifier at all",
        )
    )
    assert any("cannot follow" in message for message in check.warnings)


def test_a_report_with_a_publisher_and_year_is_traceable() -> None:
    """PENELOPE has no registered DOI and is not thereby suspect."""
    check.check_references(
        _built(
            "Body cites [1].",
            "1. Salvat F, Fernandez-Varea JM, Sempau J. PENELOPE - a code system for "
            "Monte Carlo simulation of electron and photon transport. "
            "Issy-les-Moulineaux: NEA-OECD; 2006.",
        )
    )
    assert not any("cannot follow" in message for message in check.warnings)


def test_the_series_accounting_holds_on_the_real_freeze() -> None:
    """32 = 30 + 2 and 30 = 23 + 7, on the frozen production run."""
    check.check_series_account_for_one_another()
    assert not check.errors


def test_the_freeze_is_current() -> None:
    check.check_frozen_is_current()
    assert not check.errors


def test_the_inquiry_check_catches_a_stale_title(tmp_path, monkeypatch) -> None:
    """The defect this exists for: the paper was reframed, the inquiry was not."""
    stale = tmp_path / "inquiry.txt"
    stale.write_text(
        "Title. How far an organ-weighted CTDIvol index is from absorbed organ "
        "dose.\nPearson r = 0.66 over all series.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check, "INQUIRY", stale)
    check.check_inquiry("# A measured floor on index-based organ dose estimation\n")
    assert any("current title" in message for message in check.errors)
    assert any("withdrawn wording" in message for message in check.errors)


def test_the_inquiry_check_catches_a_number_the_paper_no_longer_reports(
    tmp_path, monkeypatch
) -> None:
    built = "# A measured floor on index-based organ dose estimation\n"
    letter = tmp_path / "inquiry.txt"
    letter.write_text(
        "Title. A measured floor on index-based organ dose estimation.\n"
        "The floor is reached at a median of 99%.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check, "INQUIRY", letter)
    check.check_inquiry(built)
    assert any("does not carry" in message for message in check.errors)


def test_the_real_inquiry_agrees_with_the_real_manuscript() -> None:
    built_path = check.BUILT
    if not built_path.is_file():
        pytest.skip("no built manuscript; run paper/build_all.py")
    if not check.INQUIRY.is_file():
        # Two different reasons were reported as one, and the message named the wrong fix.
        pytest.skip(f"no inquiry drafted at {check.INQUIRY.name}; nothing to compare")
    check.check_inquiry(built_path.read_text(encoding="utf-8"))
    assert not check.errors, check.errors

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
    check.check_the_defective_file_is_not_cited(
        "Doses are in `figure4_y_axis.json`.", ""
    )
    assert check.errors


def test_a_data_and_code_section_without_a_locator_is_caught() -> None:
    built = (
        "## Data and code\n\nSoftware under the MIT licence, in this repository.\n\n"
        "## Next\n"
    )
    check.check_code_is_reachable(built)
    assert check.errors


def test_a_data_and_code_section_with_a_url_passes() -> None:
    built = (
        "## Data and code\n\nSoftware is at "
        "https://github.com/Institute-of-One/ct-dosemc-core.\n\n## Next\n"
    )
    check.check_code_is_reachable(built)
    assert not check.errors


def test_a_missing_data_and_code_section_is_caught() -> None:
    check.check_code_is_reachable("## Results\n\nNothing about code.\n")
    assert check.errors


def test_references_out_of_citation_order_are_caught() -> None:
    source = (
        "Body cites [2] and then [1].\n\n"
        "## References\n1. First, doi:10/a\n2. Second, doi:10/b\n"
    )
    check.check_references(source)
    assert any("order of first citation" in message for message in check.errors)


def test_an_uncited_reference_is_caught() -> None:
    source = (
        "Body cites [1].\n\n## References\n1. First, doi:10/a\n2. Orphan, doi:10/b\n"
    )
    check.check_references(source)
    assert any("never cited" in message for message in check.errors)


def test_a_cited_but_unlisted_reference_is_caught() -> None:
    source = "Body cites [1] and [2].\n\n## References\n1. Only one, doi:10/a\n"
    check.check_references(source)
    assert any("cited but not listed" in message for message in check.errors)


def test_a_reference_without_a_doi_warns() -> None:
    source = "Body cites [1].\n\n## References\n1. A book with no identifier\n"
    check.check_references(source)
    assert any("no DOI" in message for message in check.warnings)


def test_the_series_accounting_holds_on_the_real_freeze() -> None:
    """32 = 30 + 2 and 30 = 23 + 7, on the frozen production run."""
    check.check_series_account_for_one_another()
    assert not check.errors


def test_the_freeze_is_current() -> None:
    check.check_frozen_is_current()
    assert not check.errors

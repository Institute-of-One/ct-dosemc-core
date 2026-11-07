"""A resolved number must be printable, not merely correct.

Every number in the manuscript arrives through the marker resolver, so a defect
there is a defect in all of them at once and no gate that reads the markdown can
see it -- what goes wrong is what Word does with the characters afterwards.

The case that prompted this: on page 18 of the manuscript rendered 2026-11-07,
"r = -0.30" was printed as "r = -" at the end of one line and "0.30" at the start
of the next, because the formatter emitted an ASCII hyphen and Word treats a
hyphen as a place it may break. Found by looking at the page, not by any check.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "paper"))

import build_manuscript  # noqa: E402

MINUS = "−"


@pytest.fixture()
def frozen(tmp_path: Path) -> Path:
    (tmp_path / "x.json").write_text(
        json.dumps({"r": -0.2973, "pp": -1.43, "n": 10000, "share": 0.8789}),
        encoding="utf-8",
    )
    return tmp_path


def render(frozen: Path, text: str) -> str:
    return build_manuscript.render(text, frozen, cite=False)


def test_a_negative_number_carries_a_minus_sign_not_a_hyphen(frozen: Path) -> None:
    out = render(frozen, "r = [[results:x.json:r|.2f]]")
    assert out == f"r = {MINUS}0.30"
    assert "-" not in out, "an ASCII hyphen is a line-break opportunity in Word"


def test_an_explicit_sign_is_a_minus_too(frozen: Path) -> None:
    assert render(frozen, "[[results:x.json:pp|+.1f]]") == f"{MINUS}1.4"


def test_a_positive_number_is_untouched(frozen: Path) -> None:
    assert render(frozen, "[[results:x.json:n]]") == "10000"
    # The space before the per-cent sign is a non-breaking one, by the rule in
    # build_manuscript: a per-cent sign alone at the start of a line is worse
    # than either form.
    assert render(frozen, "[[results:x.json:share|.0%]]") == "88 %"


def test_the_check_bites_on_the_defect_it_was_written_for(frozen: Path) -> None:
    """Put the hyphen back and the first test must fail.

    A formatter that quietly stopped substituting would pass every assertion
    above that does not name the character, so this names it.
    """
    rendered = render(frozen, "r = [[results:x.json:r|.2f]]")
    reverted = rendered.replace(MINUS, "-")
    assert reverted == "r = -0.30"
    assert reverted != rendered

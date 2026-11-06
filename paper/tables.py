"""Render the manuscript's tables from ``paper/frozen/``, so no cell is typed.

A table is the easiest place for a number to drift: it is the part of a manuscript
most often rebuilt by hand, and a stale cell in a grid of sixty looks exactly like a
current one. ``build_manuscript`` resolves ``[[table:<name>]]`` through the registry
at the bottom of this file.

Width is a design constraint, not an afterthought. Seven columns of
``value [low, high]`` do not fit a 6.5 inch text block; Word then breaks a line
inside a number, and a companion paper printed an interval whose lower bound read
as positive because the minus sign ended a line. The per-vendor columns here carry
a median and a count only, and the interquartile range is given once, in the column
that pools every series. Nothing is lost: the paper makes no vendor claim.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

FROZEN = Path(__file__).resolve().parent / "frozen"

#: The order organs appear in, largest and most central first, so that a reader
#: scanning the first rows sees the organs the scan is usually planned around.
ORGAN_ORDER = (
    "liver",
    "spleen",
    "stomach",
    "pancreas",
    "gallbladder",
    "kidney_left",
    "kidney_right",
    "adrenal_gland_left",
    "adrenal_gland_right",
    "small_bowel",
    "colon",
    "urinary_bladder",
)

ORGAN_LABEL = {
    "adrenal_gland_left": "Adrenal, left",
    "adrenal_gland_right": "Adrenal, right",
    "kidney_left": "Kidney, left",
    "kidney_right": "Kidney, right",
    "small_bowel": "Small bowel",
    "urinary_bladder": "Bladder",
}

VENDOR_ORDER = ("GE", "Siemens", "Canon/Toshiba", "Philips")

#: What the column heading says, where the key is longer than the column.
#: "Canon/Toshiba" printed as "Canon/Tos" on one line and "hiba" on the next,
#: with the first half floating above the header rule. The caption names the
#: manufacturer in full, so nothing is lost by shortening the heading.
VENDOR_HEADING = {"Canon/Toshiba": "Canon"}

#: Relative column widths, as the number of dashes pandoc reads from the
#: separator row of a pipe table. Equal dashes give equal columns, and seven
#: equal columns in this text block are about ten characters wide: "Gallbladder"
#: printed as "Gallbladde" and "r". The organ names and the pooled column with
#: its interquartile range need the room; a median and a count do not.
#: Derived from what each column has to hold, not guessed: the organ names need
#: "Gallbladder", the vendor columns need the heading "Siemens" (their data is
#: shorter), and the pooled column needs "27.5 [16.2, 33.9] (29)" to stay on one
#: line. check_column_widths below refuses the build if any of that stops being
#: true.
COLUMN_WEIGHTS = {"Organ": 19, "All series": 28}
DEFAULT_COLUMN_WEIGHT = 13

#: The text block the table has to fit, in inches: the page less the margins
#: build_docx.py sets. Kept here because the width check below is meaningless
#: without it, and a check against the wrong page is worse than no check.
TEXT_BLOCK_INCHES = (11906 - 2 * 1800) / 1440

#: A generous upper bound on the width of one character at the table's 10 pt,
#: in inches. Calibri averages about 0.065 in at that size and its widest
#: lower-case letters reach 0.085; the bound is deliberately the wide end,
#: because the cost of a column half a character too wide is nothing and the
#: cost of one half a character too narrow is a word broken in two.
CHARACTER_INCHES = 0.085

#: Word's default cell padding, both sides, in inches.
CELL_PADDING_INCHES = 0.16


def check_column_widths(header: list[str], rows: list[list[str]]) -> list[str]:
    """Columns too narrow for their longest unbreakable word.

    Word breaks a word in half rather than overflow a cell: "Canon/Toshiba"
    printed as "Canon/Tos" and "hiba", "Gallbladder" as "Gallbladde" and "r",
    "Siemens" as "Siemen" and "s". None of that is visible in the markdown, in
    the .docx paragraph text, or in the extracted PDF text -- only in the
    rendered page. This is the arithmetic that predicts it, so that the build
    refuses before anyone has to notice it by eye.
    """
    weights = [COLUMN_WEIGHTS.get(name, DEFAULT_COLUMN_WEIGHT) for name in header]
    total = sum(weights)
    problems = []
    for index, name in enumerate(header):
        inches = weights[index] / total * TEXT_BLOCK_INCHES - CELL_PADDING_INCHES
        cells = [name, *(row[index] for row in rows if index < len(row))]
        longest = max((max(cell.split(), key=len, default="") for cell in cells),
                      key=len, default="")
        needed = len(longest) * CHARACTER_INCHES
        if needed > inches:
            problems.append(
                f"column {name!r} is {inches:.2f} in wide but must hold {longest!r}, "
                f"which needs about {needed:.2f} in: Word will break it in two"
            )
    return problems

#: U+2212. An ASCII hyphen lets Word break a line directly after it, and a bound
#: that begins the next line loses its sign.
MINUS = "−"


def _label(organ: str) -> str:
    return ORGAN_LABEL.get(organ, organ.replace("_", " ").capitalize())


def _number(value: float) -> str:
    return f"{value:.1f}".replace("-", MINUS)


def organ_doses() -> str:
    """Absorbed organ dose by vendor: median (n), and the pooled interquartile range."""
    payload = json.loads((FROZEN / "table4_organ_doses.json").read_text(encoding="utf-8"))
    by_organ = {entry["organ"]: entry for entry in payload["organs"]}

    header = ["Organ", *(VENDOR_HEADING.get(v, v) for v in VENDOR_ORDER), "All series"]
    separator = "|" + "".join(
        "-" * COLUMN_WEIGHTS.get(name, DEFAULT_COLUMN_WEIGHT) + "|" for name in header
    )
    rows = [
        "| " + " | ".join(header) + " |",
        separator,
    ]

    body: list[list[str]] = []
    for organ in ORGAN_ORDER:
        entry = by_organ.get(organ)
        if entry is None:
            continue
        cells = [_label(organ)]
        for vendor in VENDOR_ORDER:
            stats = entry["by_vendor"].get(vendor)
            cells.append(f"{_number(stats['median_mgy'])} ({stats['n']})" if stats else "—")
        pooled = entry["all"]
        cells.append(
            f"{_number(pooled['median_mgy'])} "
            f"[{_number(pooled['q1_mgy'])}, {_number(pooled['q3_mgy'])}] "
            f"({pooled['n']})"
        )
        rows.append("| " + " | ".join(cells) + " |")
        body.append(cells)

    problems = check_column_widths(header, body)
    if problems:
        raise SystemExit(
            "Table 1 cannot be laid out without breaking a word:\n  - "
            + "\n  - ".join(problems)
            + "\nWiden the column in COLUMN_WEIGHTS, or shorten what it holds."
        )

    counts = ", ".join(
        f"{vendor} {payload['n_series_by_vendor'][vendor]}" for vendor in VENDOR_ORDER
    )

    # The uncertainty on each entry, from the frozen record rather than asserted. A table of
    # doses with no uncertainty beside them was the second thing a referee asked about, and
    # the two contributions are both measured: how well the Monte Carlo converged, and what
    # the dose grid costs the organ's mass.
    metrics = json.loads((FROZEN / "manifest.json").read_text(encoding="utf-8"))["metrics"]
    resample = json.loads((FROZEN / "resample_cost.json").read_text(encoding="utf-8"))
    worst_organ = max(
        resample["by_organ"].items(), key=lambda item: item[1]["median_abs_pct"]
    )
    stem, _, side = worst_organ[0].rpartition("_")
    worst_name = (
        f"{side} {stem.replace('_', ' ')}" if side in {"left", "right"}
        else worst_organ[0].replace("_", " ")
    )

    rows.append("")
    rows.append(
        f"**Table 1.** Absorbed organ dose in mGy over the "
        f"{payload['n_scaled_series']} series carrying a CTDIvol. Vendor columns give "
        f"the median and, in parentheses, the number of series in which that organ is "
        f"present; the final column pools every series and adds the interquartile "
        f"range. Series per vendor: {counts}. The cohort is not powered for a vendor "
        f"comparison and none is claimed. The spread shown is between patients, which is "
        f"the quantity of interest here and is far larger than the uncertainty on any one "
        f"entry: the Monte-Carlo statistical uncertainty is "
        f"{metrics['mc_sigma_median_pct']:.3f} % of the organ dose at the median and "
        f"{metrics['mc_sigma_max_pct']:.2f} % at worst, and resampling the organ mask to "
        f"the {resample['dose_grid_mm']:.1f} mm dose grid changes the organ's mass by "
        f"{resample['by_organ']['liver']['median_abs_pct']:.1f} % at the median for the "
        f"liver, rising to {worst_organ[1]['median_abs_pct']:.1f} % for the "
        f"{worst_name}, the smallest organ scored."
    )
    return "\n".join(rows)


TABLES: dict[str, Callable[[], str]] = {
    "organ_doses": organ_doses,
}

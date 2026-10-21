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

    header = ["Organ", *VENDOR_ORDER, "All series"]
    rows = [
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]

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

"""Table 4, Fig. 4 stats, and Fig. 5 from scan-covering Fig. 4 doses.

    python tools/collect_phase2_results.py
    python tools/figure4_scatter.py --doses results/phase2_cohort/figure4_doses.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from extract_iorn006_index import FIGURE4_RECORDED_ONLY  # noqa: E402
from figure4_scatter import points_from_index, recorded_only  # noqa: E402

DOSES = REPO / "results" / "phase2_cohort" / "figure4_doses.json"
INDEX = REPO / "results" / "phase2_cohort" / "iorn006_organ_index.json"
TABLE4 = REPO / "results" / "phase2_cohort" / "table4_organ_doses.json"
STATS = REPO / "results" / "phase2_cohort" / "figure4_stats.json"
#: The vendor figure, named for what it shows and not for where it lands in a manuscript.
#: It used to be figure5_vendor.png, which is this pipeline's own numbering; the paper places
#: it as figure 6, so the copy into paper/figures/ renamed it and the title drawn inside the
#: image went on saying Figure 5. A figure number belongs to a manuscript, and a manuscript
#: renumbers; results files outlive that and must not carry one.
VENDOR_FIGURE = REPO / "results" / "phase2_cohort" / "vendor_organ_dose.png"

VENDORS = ("GE", "Siemens", "Canon/Toshiba", "Philips")
ORGAN_ORDER = (
    "liver",
    "spleen",
    "stomach",
    "kidney_left",
    "kidney_right",
    "pancreas",
    "gallbladder",
    "colon",
    "small_bowel",
    "adrenal_gland_left",
    "adrenal_gland_right",
    "urinary_bladder",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def pearson_r(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    a = np.asarray(xs, dtype=float)
    b = np.asarray(ys, dtype=float)
    if a.std() == 0.0 or b.std() == 0.0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def _median_iqr(values: list[float]) -> dict[str, float | int]:
    arr = np.asarray(values, dtype=float)
    return {
        "n": int(arr.size),
        "median_mgy": float(np.median(arr)),
        "q1_mgy": float(np.percentile(arr, 25)),
        "q3_mgy": float(np.percentile(arr, 75)),
    }


def table4_from_doses(doses_payload: dict[str, Any]) -> dict[str, Any]:
    by_vendor_organ: dict[str, dict[str, list[float]]] = {v: defaultdict(list) for v in VENDORS}
    n_series = {v: 0 for v in VENDORS}
    for row in doses_payload.get("series") or []:
        if row.get("status") != "scaled":
            continue
        vendor = str(row["vendor"])
        if vendor not in by_vendor_organ:
            continue
        n_series[vendor] += 1
        uid = row["series_instance_uid"]
        organs = (doses_payload.get("doses") or {}).get(uid) or {}
        for name, value in organs.items():
            by_vendor_organ[vendor][name].append(float(value))

    organs = [o for o in ORGAN_ORDER if any(o in by_vendor_organ[v] for v in VENDORS)]
    extra = sorted(
        {
            name
            for vendor_map in by_vendor_organ.values()
            for name in vendor_map
            if name not in organs
        }
    )
    organs.extend(extra)

    rows: list[dict[str, Any]] = []
    for organ in organs:
        rec: dict[str, Any] = {"organ": organ, "by_vendor": {}}
        pooled: list[float] = []
        for vendor in VENDORS:
            vals = by_vendor_organ[vendor].get(organ) or []
            rec["by_vendor"][vendor] = _median_iqr(vals) if vals else {"n": 0}
            pooled.extend(vals)
        rec["all"] = _median_iqr(pooled) if pooled else {"n": 0}
        rows.append(rec)

    return {
        "what": "Table 4: scan-covering absorbed organ dose (mGy), median [Q1, Q3], per vendor",
        "formula": doses_payload.get("formula"),
        "n_scaled_series": int(doses_payload.get("n_scaled") or 0),
        "n_series_by_vendor": n_series,
        "organs": rows,
    }


def figure4_stats(index: dict[str, Any], doses_payload: dict[str, Any]) -> dict[str, Any]:
    points = [p for p in points_from_index(index, doses_payload.get("doses")) if "y" in p]
    rec = recorded_only(points)
    organs = sorted({p["organ"] for p in points})
    xs = [p["x"] for p in points]
    ys = [p["y"] for p in points]
    ratios = [p["y"] / p["x"] for p in points if p["x"] != 0.0]
    rec_xs = [p["x"] for p in rec]
    rec_ys = [p["y"] for p in rec]
    rec_ratios = [p["y"] / p["x"] for p in rec if p["x"] != 0.0]
    return {
        "what": "Fig. 4 y-axis from scan-covering production (not the mid-scan defect file)",
        "usable_for_figure4": bool(doses_payload.get("usable_for_figure4")),
        "n_eligible": int(doses_payload.get("n_eligible") or 0),
        "n_scaled": int(doses_payload.get("n_scaled") or 0),
        "n_omitted_no_ctdivol": int(doses_payload.get("n_eligible") or 0)
        - int(doses_payload.get("n_scaled") or 0),
        "n_organs": len(organs),
        "organs": organs,
        "n_points": len(points),
        "n_series": len({p["series_instance_uid"] for p in points}),
        "n_points_recorded_only": len(rec),
        "n_series_recorded_only": len({p["series_instance_uid"] for p in rec}),
        "pearson_r_all": pearson_r(xs, ys),
        "pearson_r_recorded": pearson_r(rec_xs, rec_ys),
        "y_over_x_median": float(np.median(ratios)) if ratios else None,
        "y_over_x_median_recorded": float(np.median(rec_ratios)) if rec_ratios else None,
        "y_median_mgy": float(np.median(ys)) if ys else None,
        "y_min_mgy": float(min(ys)) if ys else None,
        "y_max_mgy": float(max(ys)) if ys else None,
        "recorded_only_sentence": FIGURE4_RECORDED_ONLY["sentence"],
        "not": "Not results/phase2_cohort/figure4_y_axis.json (mid-scan defect).",
    }


def draw_vendor_figure(table: dict[str, Any], path: Path) -> Path:
    import matplotlib.pyplot as plt

    organs = [row["organ"] for row in table["organs"] if int(row["all"].get("n") or 0) > 0]
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    x = np.arange(len(organs))
    width = 0.18
    colors = {
        "GE": "#1b9e77",
        "Siemens": "#d95f02",
        "Canon/Toshiba": "#7570b3",
        "Philips": "#e7298a",
    }
    for i, vendor in enumerate(VENDORS):
        med = []
        for organ in organs:
            rec = next(r for r in table["organs"] if r["organ"] == organ)
            cell = rec["by_vendor"].get(vendor) or {}
            med.append(float(cell["median_mgy"]) if cell.get("n") else math.nan)
        n = int(table["n_series_by_vendor"].get(vendor) or 0)
        ax.bar(
            x + (i - 1.5) * width,
            med,
            width,
            color=colors[vendor],
            label=f"{vendor} (N={n})",
        )
    ax.set_xticks(x)
    ax.set_xticklabels([o.replace("_", " ") for o in organs], rotation=35, ha="right")
    ax.set_ylabel("Absorbed organ dose (mGy), median")
    # Below the axes in one row. Inside them the four entries sat in the top right, where the
    # tallest bar of the last organ group rises into the same band -- close enough that
    # deciding whether they touch needs a magnified crop, which is not a thing a figure should
    # require. Outside the axes the question cannot arise.
    ax.legend(
        frameon=False,
        fontsize=8,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.28),
        ncol=4,
        borderaxespad=0.0,
    )
    # No title drawn into the image. This file is copied into paper/figures/ as figure 6, and
    # the title said "Figure 5" because that is what this pipeline calls it -- so the
    # manuscript printed Figure 5 above the image and Figure 6 in the caption below, which is
    # what a reader has no way to resolve. Renaming a file does not repaint it. The
    # caption belongs to the manuscript; the image carries no number at all.
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    # bbox_inches="tight" so the legend below the axes is inside the canvas rather than
    # hanging off it, which is how figure 4's legend went out cut mid-word.
    fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    return path


def collect(
    *,
    doses_payload: dict[str, Any],
    index: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not doses_payload.get("usable_for_figure4"):
        raise SystemExit(
            "figure4_doses.json is not usable_for_figure4; "
            "do not fill Table 4 / Fig. 5 from a mid-scan or incomplete set"
        )
    table = table4_from_doses(doses_payload)
    stats = figure4_stats(index, doses_payload)
    return table, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--doses", type=Path, default=DOSES)
    ap.add_argument("--index", type=Path, default=INDEX)
    ap.add_argument("--table4", type=Path, default=TABLE4)
    ap.add_argument("--stats", type=Path, default=STATS)
    ap.add_argument("--vendor-figure", type=Path, default=VENDOR_FIGURE)
    args = ap.parse_args(argv)
    doses_payload = _load(args.doses)
    index = _load(args.index)
    table, stats = collect(doses_payload=doses_payload, index=index)
    args.table4.write_text(json.dumps(table, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.stats.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    draw_vendor_figure(table, args.vendor_figure)
    print(
        f"[phase2] table4={args.table4}  stats={args.stats}  "
        f"n_organs={stats['n_organs']}  r_all={stats['pearson_r_all']:.3f}  "
        f"r_rec={stats['pearson_r_recorded']:.3f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

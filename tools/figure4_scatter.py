"""Figure 4: IORN-006 organ index (x) vs IORN-007 absorbed dose (y).

The y-axis is gated until G0–G5 close. The marker mapping is not: it is fixed
here so a low-confidence reconstruction cannot land on the same symbol as a
recorded CTDIvol. Open squares are IORN-004's own low-confidence warning
(Revolution CT → Revolution CT ES, score 0.50), not a second policy invented
for the plot.

    python tools/figure4_scatter.py            # needs 007 organ doses
    python tools/figure4_scatter.py --legend-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from extract_iorn006_index import FIGURE4_MARKERS, figure4_marker  # noqa: E402

DEFAULT_INDEX = REPO / "results" / "phase2_cohort" / "iorn006_organ_index.json"
DEFAULT_OUT = REPO / "results" / "phase2_cohort" / "figure4_scatter.png"
DEFAULT_LEGEND = REPO / "results" / "phase2_cohort" / "figure4_legend.png"

# Same colour for both reconstructed classes so hollow vs filled is the signal.
_EDGE = {
    "recorded": "#2166ac",
    "reconstructed": "#b2182b",
    "reconstructed_low_confidence": "#b2182b",
}


def matplotlib_style(kind: str) -> dict[str, Any]:
    """kwargs for ax.scatter. Hollow = facecolors 'none'."""
    spec = FIGURE4_MARKERS[kind]
    if spec.get("omit"):
        raise ValueError(f"{kind} is omitted from Figure 4")
    filled = spec["facecolor"] == "filled"
    color = _EDGE[kind]
    return {
        "marker": spec["marker"],
        "facecolors": color if filled else "none",
        "edgecolors": color,
        "linewidths": 1.2,
        "label": spec["label"],
    }


def points_from_index(
    index: dict[str, Any],
    doses: dict[str, dict[str, float]] | None,
) -> list[dict[str, Any]]:
    """One point per organ with a defined x (and y, when doses are supplied)."""
    out: list[dict[str, Any]] = []
    for series in index["series"]:
        kind = series.get("figure4_marker") or figure4_marker(
            series["ctdivol_origin"], series.get("ctdivol_reconstruction")
        )
        if FIGURE4_MARKERS[kind].get("omit"):
            continue
        uid = series["series_instance_uid"]
        by_organ = (doses or {}).get(uid) or {}
        for organ in series["organs"]:
            x = organ.get("organ_weighted_ctdivol_mgy")
            if x is None:
                continue
            rec = {
                "series_instance_uid": uid,
                "organ": organ["organ"],
                "x": float(x),
                "figure4_marker": kind,
            }
            if organ["organ"] in by_organ:
                rec["y"] = float(by_organ[organ["organ"]])
            out.append(rec)
    return out


def _draw_legend(ax) -> None:
    import matplotlib.pyplot as plt  # noqa: F401 — ax.scatter

    for kind in ("recorded", "reconstructed", "reconstructed_low_confidence"):
        style = matplotlib_style(kind)
        ax.scatter([], [], s=48, **style)
    ax.legend(frameon=False, loc="best", fontsize=8)


def draw_legend_only(path: Path) -> Path:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.2, 1.6))
    _draw_legend(ax)
    ax.set_axis_off()
    ax.set_title("Figure 4 markers", fontsize=10, loc="left")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def draw_scatter(points: list[dict[str, Any]], path: Path, *, caption: str) -> Path:
    import matplotlib.pyplot as plt

    if any("y" not in p for p in points):
        raise SystemExit(
            "Figure 4 y-axis is gated: 007 organ doses are not in the point list. "
            "Pass doses once G0–G5 close, or use --legend-only."
        )
    fig, ax = plt.subplots(figsize=(5.2, 5.2))
    for kind in ("recorded", "reconstructed", "reconstructed_low_confidence"):
        xs = [p["x"] for p in points if p["figure4_marker"] == kind]
        ys = [p["y"] for p in points if p["figure4_marker"] == kind]
        if not xs:
            continue
        ax.scatter(xs, ys, s=28, **matplotlib_style(kind))
    ax.set_xlabel("IORN-006 organ-weighted CTDIvol (mGy)")
    ax.set_ylabel("IORN-007 absorbed organ dose (mGy)")
    ax.legend(frameon=False, fontsize=7)
    fig.text(0.02, 0.01, caption, fontsize=7, wrap=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    ap.add_argument("--doses", type=Path, default=None, help="007 organ-dose JSON (gated)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--legend-only", action="store_true")
    args = ap.parse_args(argv)

    if args.legend_only:
        draw_legend_only(DEFAULT_LEGEND if args.out == DEFAULT_OUT else args.out)
        print(f"wrote legend {args.out if args.out != DEFAULT_OUT else DEFAULT_LEGEND}")
        return 0

    index = json.loads(args.index.read_text(encoding="utf-8"))
    caption = index.get("scatter", {}).get("caption_line") or FIGURE4_MARKERS[
        "reconstructed_low_confidence"
    ]["label"]
    doses = None
    if args.doses is not None:
        doses = json.loads(args.doses.read_text(encoding="utf-8"))
    points = points_from_index(index, doses)
    draw_scatter(points, args.out, caption=caption)
    print(f"wrote {args.out}  n={len(points)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

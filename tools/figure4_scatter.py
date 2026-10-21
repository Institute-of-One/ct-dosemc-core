"""Figure 4: IORN-006 organ index (x) vs IORN-007 absorbed dose (y).

The y-axis is gated until G0–G5 close. The marker mapping is not: it is fixed
here so a low-confidence reconstruction cannot land on the same symbol as a
recorded CTDIvol. Open squares are IORN-004's own low-confidence warning
(Revolution CT → Revolution CT ES, score 0.50), not a second policy invented
for the plot.

    python tools/figure4_scatter.py            # needs 007 organ doses; also writes
                                              # the recorded-only robustness line
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

from extract_iorn006_index import (  # noqa: E402
    FIGURE4_MARKERS,
    FIGURE4_RECORDED_ONLY,
    figure4_marker,
)

DEFAULT_INDEX = REPO / "results" / "phase2_cohort" / "iorn006_organ_index.json"
DEFAULT_OUT = REPO / "results" / "phase2_cohort" / "figure4_scatter.png"
DEFAULT_LEGEND = REPO / "results" / "phase2_cohort" / "figure4_legend.png"

# Same colour for both reconstructed classes so hollow vs filled is the signal.
_EDGE = {
    "recorded": "#2166ac",
    "reconstructed": "#b2182b",
    "reconstructed_low_confidence": "#b2182b",
}

#: What the legend says, as against what ``FIGURE4_MARKERS[kind]["label"]`` says.
#:
#: The long labels are prose and belong in the caption, where PMB-122419's referee 2 found
#: them anyway -- printed a second time inside the image. Drawn into a legend they ran off
#: the left edge of the canvas and were cut mid-word, because matplotlib places a legend
#: inside the axes and will not shrink the text to fit. They also name IORN-004, which is
#: this programme's own numbering and means nothing to a reader of the journal.
_LEGEND_LABEL = {
    "recorded": "recorded CTDIvol",
    "reconstructed": "reconstructed, exact or high-confidence match",
    "reconstructed_low_confidence": "reconstructed, low-confidence match",
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
        "label": _LEGEND_LABEL.get(kind, spec["label"]),
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


def recorded_only(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fig. 4 robustness subset: recorded CTDIvol, no extra Monte Carlo."""
    return [p for p in points if p.get("figure4_marker") == "recorded"]


def robustness_recorded_only_line(
    points: list[dict[str, Any]],
) -> dict[str, Any]:
    """One reserved sentence. Filled when every point has y; otherwise gated."""
    rec = recorded_only(points)
    n_all = len({p["series_instance_uid"] for p in points})
    n_rec = len({p["series_instance_uid"] for p in rec})
    ready = bool(points) and all("y" in p for p in points)
    out = {
        **FIGURE4_RECORDED_ONLY,
        "n_series_plotted": n_all,
        "n_series_recorded_only": n_rec,
        "n_points_plotted": len(points),
        "n_points_recorded_only": len(rec),
        "status": "ready" if ready else "gated",
    }
    if ready:
        out["sentence_to_report"] = FIGURE4_RECORDED_ONLY["sentence"]
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
    # The caption is the journal's to print under the figure. It used to be drawn into the
    # image as well, where referee 2 of PMB-122419 found it and asked for its removal; it is
    # still accepted as an argument so the caller's contract does not change, and it is still
    # what the manuscript places, but it is no longer painted on top of the data.
    del caption

    fig, ax = plt.subplots(figsize=(5.2, 5.2))
    for kind in ("recorded", "reconstructed", "reconstructed_low_confidence"):
        xs = [p["x"] for p in points if p["figure4_marker"] == kind]
        ys = [p["y"] for p in points if p["figure4_marker"] == kind]
        if not xs:
            continue
        ax.scatter(xs, ys, s=28, **matplotlib_style(kind))
    # No IORN numbers on the axes: they are this programme's filing system, not a quantity.
    ax.set_xlabel("Organ-weighted CTDIvol (mGy)")
    ax.set_ylabel("Absorbed organ dose (mGy)")
    # Under the axes, not inside them: three entries of this length have nowhere to sit in a
    # square panel, and matplotlib's "best" placement put them over the edge of the canvas.
    ax.legend(
        frameon=False,
        fontsize=7,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.11),
        ncol=1,
        handletextpad=0.6,
        borderaxespad=0.0,
    )
    ax.spines[["top", "right"]].set_visible(False)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight", pad_inches=0.04)
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
        raw = json.loads(args.doses.read_text(encoding="utf-8"))
        if "doses" in raw:
            if raw.get("usable_for_figure4") is False:
                raise SystemExit(
                    "Figure 4 y-axis is not ready: "
                    f"scaled={raw.get('n_scaled')} "
                    f"awaiting_scale={raw.get('n_awaiting_scale')} "
                    f"incomplete={raw.get('n_production_incomplete')}. "
                    "Finish production and the bowtie-aware CTDI scale first."
                )
            doses = raw["doses"]
        else:
            doses = raw
    points = points_from_index(index, doses)
    line = robustness_recorded_only_line(points)
    draw_scatter(points, args.out, caption=caption)
    side = args.out.with_name(args.out.stem + "_recorded_only.json")
    side.write_text(json.dumps(line, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}  n={len(points)}")
    rob = f"recorded-only robustness [{line['status']}]: {line['sentence']}"
    encoding = sys.stdout.encoding or "utf-8"
    print(rob.encode(encoding, errors="replace").decode(encoding, errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

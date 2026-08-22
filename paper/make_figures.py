"""Draw Figures 1-3 from ``paper/frozen/``, at the size they print.

    python paper/make_figures.py

Figures 4 and 5 are drawn by ``tools/figure4_scatter.py`` and
``tools/collect_phase2_results.py`` from the production runs; this module covers
the three the manuscript declares and that had no drawing code at all.

Nothing here is decorative. Each choice below answers a defect that reached a
built manuscript in a companion paper:

* every text size is set explicitly, because a figure drawn wide and shrunk into a
  column takes its labels down to five points;
* the printed height is checked as well as the width, because a figure taller than
  the text block is cut in half and its caption stranded overleaf;
* no legend is placed with ``loc="best"``, which chooses the emptiest corner of the
  axes and has covered plotted points;
* zero-valued observations are drawn, not dropped. Fourteen of the forty series in
  Figure 2 have no out-of-calibration voxel at all, and a logarithmic axis would
  silently discard more than a third of the cohort;
* captions are not painted into the image. A caption that exists both as pixels and
  as a numbered paragraph prints twice, in two wordings.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

PAPER = Path(__file__).resolve().parent
FROZEN = PAPER / "frozen"
FIGURES = PAPER / "figures"

#: PMB's text block. A figure wider than this is scaled down on the page, taking
#: its type with it; a figure taller than this is broken across two pages.
TEXT_WIDTH_IN = 6.5
TEXT_HEIGHT_IN = 8.7

#: One size per role, so a figure cannot drift into eight-point axis labels.
TICK = 8
LABEL = 9
ANNOT = 7.5
PANEL = 10

#: Colour-blind-safe (Okabe-Ito), and distinguishable in greyscale by marker too.
VENDOR_STYLE = {
    "GE": ("#0072B2", "o"),
    "Siemens": ("#D55E00", "s"),
    "Canon/Toshiba": ("#009E73", "^"),
    "Philips": ("#CC79A7", "D"),
}


def _load(name: str) -> dict:
    return json.loads((FROZEN / name).read_text(encoding="utf-8"))


def _save(fig: plt.Figure, name: str) -> Path:
    """Write the figure, after checking it fits the page it prints on."""
    width, height = fig.get_size_inches()
    if width > TEXT_WIDTH_IN + 1e-9:
        raise ValueError(f"{name}: {width:.2f} in wide, wider than the text block")
    scale = min(1.0, TEXT_WIDTH_IN / width)
    if height * scale > TEXT_HEIGHT_IN + 1e-9:
        raise ValueError(
            f"{name}: prints {height * scale:.2f} in tall, taller than the text block; "
            "it would be cut across two pages"
        )
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / name
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  {name}  {width:.2f} x {height:.2f} in")
    return path


def figure1_selection_funnel() -> Path:
    """How 47 181 index rows became the 40 series that were probed and kept."""
    funnel = _load("cohort_overlap.json")["selection_funnel"]

    stages = [
        ("Index rows", funnel["index_rows"]),
        ("Vendor recognised", funnel["vendor_recognised"]),
        ("Passed metadata screen", funnel["passed_metadata_screen"]),
        ("One series per patient", funnel["after_one_series_per_patient"]),
        ("Probe queue", funnel["probe_queue"]),
        ("Probed", funnel["probed"]),
        ("Kept", funnel["kept"]),
    ]
    labels = [name for name, _ in stages]
    counts = [count for _, count in stages]

    reasons = funnel["probe_rejections_by_reason"]
    ordered = sorted(reasons.items(), key=lambda item: item[1])

    fig, (left, right) = plt.subplots(
        1, 2, figsize=(6.5, 3.0), gridspec_kw={"width_ratios": [1.35, 1.0]}
    )

    # Dots, not bars. A bar on a logarithmic axis encodes its length as a ratio to
    # wherever the axis happens to start, so 40 drawn against 47 181 came out about
    # a quarter as long instead of a thousandth. Position carries the value here and
    # there is no length to misread; the stem is a guide to the label only.
    positions = range(len(stages))
    left.set_xscale("log")
    left.set_xlim(10, counts[0] * 4.5)
    for position, count in zip(positions, counts):
        left.plot(
            [10, count], [position, position],
            color="#C8D3E0", linewidth=0.9, zorder=1,
        )
        left.plot(
            count, position, marker="o", color="#4C72B0", markersize=6, zorder=2
        )
        left.text(count * 1.35, position, f"{count:,}", va="center", fontsize=ANNOT)
    left.set_yticks(list(positions))
    left.set_yticklabels(labels, fontsize=TICK)
    left.set_ylim(len(stages) - 0.5, -0.5)
    left.set_xlabel("Series remaining (log scale)", fontsize=LABEL)
    left.set_title("(a) Selection", fontsize=PANEL, loc="left")
    left.tick_params(labelsize=TICK)

    reason_positions = range(len(ordered))
    right.barh(
        list(reason_positions),
        [count for _, count in ordered],
        color="#B0B0B0",
        height=0.62,
    )
    right.set_yticks(list(reason_positions))
    right.set_yticklabels(
        [name.replace("-", "‑") for name, _ in ordered], fontsize=TICK
    )
    right.set_xlabel("Series rejected at probe", fontsize=LABEL)
    right.set_xlim(0, max(count for _, count in ordered) * 1.28)
    for position, (_, count) in zip(reason_positions, ordered):
        right.text(count + 0.25, position, str(count), va="center", fontsize=ANNOT)
    right.set_title(
        f"(b) Why {funnel['n_probe_rejected']} of {funnel['probed']} were rejected",
        fontsize=PANEL,
        loc="left",
    )
    right.tick_params(labelsize=TICK)

    for axis in (left, right):
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)

    fig.tight_layout()
    return _save(fig, "figure1_selection_funnel.png")


def figure2_density_gate() -> Path:
    """The pre-declared density gate, with every assessed series shown."""
    eligibility = _load("density_eligibility.json")
    threshold = eligibility["threshold_cm3"]
    series = sorted(
        eligibility["series"], key=lambda row: row["largest_component_cm3"]
    )
    values = [row["largest_component_cm3"] for row in series]
    n_zero = sum(1 for value in values if value == 0.0)

    fig, ax = plt.subplots(figsize=(6.5, 3.2))

    for index, row in enumerate(series):
        colour, marker = VENDOR_STYLE[row["vendor"]]
        # `color` would set face and edge together and silently win over
        # `facecolors`, which left excluded series drawn filled -- the one thing
        # this panel exists to distinguish. Set the two properties and never both.
        ax.scatter(
            index,
            row["largest_component_cm3"],
            marker=marker,
            # Large enough, with a thin enough edge, that an unfilled triangle
            # reads as unfilled at print size. At s=26 with a 1.1 pt edge the
            # edge nearly closed the triangle and excluded series looked eligible.
            s=44,
            facecolors=colour if row["eligible"] else "none",
            edgecolors=colour,
            linewidths=0.9,
            zorder=3,
        )

    # Symmetric-log below the threshold, so the fourteen zeros are visible instead
    # of being dropped off the bottom of a logarithmic axis.
    ax.set_yscale("symlog", linthresh=0.01, linscale=0.4)
    ax.set_ylim(-0.002, max(values) * 2.2)
    ax.axhline(threshold, color="#333333", linestyle="--", linewidth=1.0, zorder=2)
    ax.text(
        len(series) - 0.5,
        threshold * 1.25,
        f"pre-declared gate, {threshold:g} cm³",
        ha="right",
        fontsize=ANNOT,
    )
    ax.axhline(0.0, color="#CCCCCC", linewidth=0.8, zorder=1)

    ax.set_xlabel(
        f"Series, ordered by largest out-of-calibration component "
        f"(n = {eligibility['n_assessed']})",
        fontsize=LABEL,
    )
    ax.set_ylabel("Largest component (cm³)", fontsize=LABEL)
    ax.set_xlim(-1, len(series))
    ax.tick_params(labelsize=TICK)
    ax.annotate(
        f"{n_zero} series have no out-of-calibration voxel\n"
        f"inside the body contour, and are plotted at zero",
        xy=(0.6, 0.0),
        xytext=(1.5, 0.055),
        fontsize=ANNOT,
        arrowprops={"arrowstyle": "-", "linewidth": 0.7, "color": "#666666"},
    )

    handles = [
        Line2D(
            [], [], color=colour, marker=marker, linestyle="none", markersize=5,
            label=vendor,
        )
        for vendor, (colour, marker) in VENDOR_STYLE.items()
    ]
    handles += [
        Line2D(
            [], [], color="#333333", marker="o", linestyle="none", markersize=5,
            label=f"eligible (n = {eligibility['n_eligible']})",
        ),
        Line2D(
            [], [], color="#333333", marker="o", linestyle="none", markersize=5,
            markerfacecolor="none",
            label=f"excluded (n = {eligibility['n_excluded']})",
        ),
    ]
    # Outside the axes: the emptiest corner of this plot holds the fourteen zeros.
    ax.legend(
        handles=handles,
        frameon=False,
        fontsize=ANNOT,
        loc="upper left",
        bbox_to_anchor=(0.015, 0.99),
        ncol=2,
        handletextpad=0.4,
        columnspacing=1.2,
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    return _save(fig, "figure2_density_gate.png")


def figure3_tg195() -> Path:
    """Case 4 against all four published codes, not only the chosen yardstick."""
    criterion_b = _load("phase1a_close.json")["criterion_b"]
    vois = criterion_b["vois"]

    fig, axes = plt.subplots(1, 2, figsize=(6.5, 3.0), sharey=True)

    for axis, (voi_name, voi) in zip(axes, vois.items()):
        per_code = voi["per_code_ours_minus_reference"]
        # PENELOPE last, so the yardstick reads as the reference point, and the
        # order is otherwise fixed rather than sorted by how well each agrees.
        codes = [name for name in ("EGSnrc", "Geant4", "MCNP") if name in per_code]
        codes += [name for name in per_code if name.lower().startswith("pen")]
        values = [per_code[name] * 100.0 for name in codes]
        sigma = voi["sigma_comb_relative"] * 100.0

        positions = range(len(codes))
        axis.axhspan(-sigma, sigma, color="#DDE7F0", zorder=1)
        axis.axhline(0.0, color="#333333", linewidth=0.9, zorder=2)
        for position, (code, value) in zip(positions, zip(codes, values)):
            is_yardstick = code.lower().startswith("pen")
            axis.errorbar(
                position,
                value,
                yerr=sigma,
                fmt="D" if is_yardstick else "o",
                color="#0072B2" if is_yardstick else "#666666",
                markersize=6 if is_yardstick else 5,
                capsize=3,
                linewidth=1.1,
                zorder=3,
            )
        axis.set_xticks(list(positions))
        axis.set_xticklabels(
            ["PENELOPE" if c.lower().startswith("pen") else c for c in codes],
            fontsize=TICK,
        )
        axis.set_xlim(-0.6, len(codes) - 0.4)
        axis.set_title(
            f"{voi_name.replace('center', 'centre').capitalize()} VOI",
            fontsize=PANEL,
            loc="left",
        )
        axis.tick_params(labelsize=TICK)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)

    axes[0].set_ylabel("(ours − reference) / reference  (%)", fontsize=LABEL)
    axes[0].text(
        -0.5,
        0.0,
        " ±σ$_{comb}$",
        va="bottom",
        ha="left",
        fontsize=ANNOT,
        color="#31597A",
    )
    fig.tight_layout()
    return _save(fig, "figure3_tg195_case4.png")


def main() -> int:
    print("drawing figures 1-3 into paper/figures/")
    figure1_selection_funnel()
    figure2_density_gate()
    figure3_tg195()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

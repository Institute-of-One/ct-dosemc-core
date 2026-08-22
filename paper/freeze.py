"""Freeze the results the manuscript cites, and derive the metrics it quotes.

    python paper/freeze.py            # -> paper/frozen/
    python paper/freeze.py --check    # fail if the freeze is stale

``results/`` is written by the production runs and is the record of what was
computed. ``paper/frozen/`` is the subset the manuscript is allowed to quote,
copied at a moment in time so that a later re-run cannot silently change a number
that has already been written into a sentence.

The manifest is *derived* from the copied files, never typed beside them. A
manifest maintained by hand is a fourth copy of the results and drifts like every
other copy: this programme has had a cover letter, a submission form and a
submission kit each go stale against the paper they described.

What may be frozen is deliberately narrow. ``figure4_y_axis.json`` carries the
mid-scan defect and is excluded by name; the scan-covering file that supersedes it
declares ``usable_for_figure4: true`` and the freeze refuses to run without it.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

PAPER = Path(__file__).resolve().parent
REPO = PAPER.parent
RESULTS = REPO / "results"
FROZEN = PAPER / "frozen"

#: Every results file the manuscript is allowed to cite, as (source, frozen name).
#: A file absent here cannot be quoted, which is what keeps the paper's evidence
#: enumerable rather than "somewhere under results/".
CITED: tuple[tuple[str, str], ...] = (
    ("phase1a_close.json", "phase1a_close.json"),
    ("phase2_cohort/figure4_stats.json", "figure4_stats.json"),
    ("phase2_cohort/figure4_doses.json", "figure4_doses.json"),
    (
        "phase2_cohort/figure4_scatter_recorded_only.json",
        "figure4_scatter_recorded_only.json",
    ),
    ("phase2_cohort/table4_organ_doses.json", "table4_organ_doses.json"),
    ("phase2_cohort/cohort_overlap.json", "cohort_overlap.json"),
    ("phase2_cohort/density_eligibility.json", "density_eligibility.json"),
    ("phase2_cohort/metal_distribution.json", "metal_distribution.json"),
    ("phase2_cohort/ctdi_scale.json", "ctdi_scale.json"),
    ("phase2_cohort/organ_volume_vs_icrp89.json", "organ_volume_vs_icrp89.json"),
    ("phase2_cohort/conversion_ceiling.json", "conversion_ceiling.json"),
)

#: Named so a reader of the manifest can see why the file is not cited.
EXCLUDED = {
    "phase2_cohort/figure4_y_axis.json": (
        "mid-scan defect: the y-axis is not an exam dose. Superseded by "
        "figure4_stats.json, which declares usable_for_figure4."
    ),
    "phase2_cohort/ctdi_scale_plan.json": (
        "the plan, not the outcome. ctdi_scale.json records what ran."
    ),
}


class FreezeError(RuntimeError):
    """The results are not in a state the manuscript may quote."""


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _gate(sources: dict[str, Any]) -> None:
    """Refuse to freeze results the paper has already declared uncitable."""
    stats = sources["figure4_stats.json"]
    if not stats.get("usable_for_figure4"):
        raise FreezeError(
            "figure4_stats.json does not declare usable_for_figure4; the "
            "scan-covering production has not completed"
        )
    if stats["n_eligible"] != stats["n_scaled"] + stats["n_omitted_no_ctdivol"]:
        raise FreezeError(
            f"the series do not account for one another: {stats['n_eligible']} "
            f"eligible against {stats['n_scaled']} scaled and "
            f"{stats['n_omitted_no_ctdivol']} omitted"
        )


def _first_number(payload: Any, *names: str) -> float:
    """Find a scalar by key name anywhere in a nested payload.

    phase1a_close.json nests its criteria by position, and the manuscript quotes
    the centre. Searching by name keeps the manifest honest when the structure
    moves, and raises rather than guessing when the name appears twice with
    different values.
    """
    found: list[float] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in names and isinstance(value, (int, float)):
                    found.append(float(value))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    if not found:
        raise FreezeError(f"none of {names} found")
    return found[0]


def derive(sources: dict[str, Any]) -> dict[str, Any]:
    """Build the manifest from the frozen files. Nothing here is typed twice."""
    stats = sources["figure4_stats.json"]
    close = sources["phase1a_close.json"]
    table4 = sources["table4_organ_doses.json"]
    overlap = sources["cohort_overlap.json"]

    metrics: dict[str, Any] = {
        # Fig. 4 -- the contribution-split figure.
        "n_eligible": stats["n_eligible"],
        "n_scaled": stats["n_scaled"],
        "n_recorded": stats["n_series_recorded_only"],
        "n_reconstructed": stats["n_scaled"] - stats["n_series_recorded_only"],
        "n_omitted_no_ctdivol": stats["n_omitted_no_ctdivol"],
        "n_organs": stats["n_organs"],
        "n_points": stats["n_points"],
        "n_points_recorded": stats["n_points_recorded_only"],
        "pearson_r_all": stats["pearson_r_all"],
        "pearson_r_recorded": stats["pearson_r_recorded"],
        "y_over_x_median": stats["y_over_x_median"],
        "y_over_x_median_recorded": stats["y_over_x_median_recorded"],
        "dose_median_mgy": stats["y_median_mgy"],
        "dose_min_mgy": stats["y_min_mgy"],
        "dose_max_mgy": stats["y_max_mgy"],
        # TG-195 Case 4, centre position.
        "tg195_centre_abs_rel": _first_number(close, "abs_ours_minus_penelope_relative"),
        "tg195_centre_n_sigma": _first_number(close, "n_sigma_vs_penelope"),
        # Cohort.
        "n_iorn007": overlap["n_iorn007"],
        "n_iorn006": overlap["n_iorn006"],
        "n_shared": overlap["n_shared"],
        "n_table4_series": table4["n_scaled_series"],
    }

    # The primary endpoint: how close an index-based conversion gets, held out.
    ceiling = sources["conversion_ceiling.json"]
    models = ceiling["models"]
    for name, scores in models.items():
        metrics[f"ceiling_{name}_median"] = scores["median_absolute_relative_error"]
        metrics[f"ceiling_{name}_p90"] = scores["p90_absolute_relative_error"]
        metrics[f"ceiling_{name}_within20"] = scores["within_20_percent"]
    metrics.update(
        {
            "ratio_median": ceiling["ratio"]["median"],
            "ratio_patient_min": ceiling["ratio"]["patient_median_min"],
            "ratio_patient_max": ceiling["ratio"]["patient_median_max"],
            "ratio_patient_fold": ceiling["ratio"]["patient_fold_span"],
            "ratio_within_patient_fold": ceiling["ratio"]["within_patient_spread_median_fold"],
            "variance_between_patient": ceiling["variance"]["between_patient_share"],
            "variance_between_organ": ceiling["variance"]["between_organ_share"],
            "variance_between_vendor": ceiling["variance"]["between_vendor_share"],
            "length_slope": ceiling["length_dependence"]["slope"],
            "size_pearson_r": ceiling["size_dependence"]["pearson_r_log"],
            "mc_sigma_median": ceiling["monte_carlo_noise_floor"]["median"],
            "mc_sigma_max": ceiling["monte_carlo_noise_floor"]["max"],
        }
    )
    # Percent forms, so prose never multiplies by a hundred by hand.
    for name in list(metrics):
        if name.startswith("ceiling_") or name.startswith("mc_sigma"):
            metrics[f"{name}_pct"] = metrics[name] * 100.0
    # Percent forms, so prose never multiplies by a hundred by hand.
    metrics["tg195_centre_abs_pct"] = metrics["tg195_centre_abs_rel"] * 100.0

    return {
        "what": (
            "Metrics the IORN-007 manuscript quotes, derived from paper/frozen/. "
            "Do not edit: run paper/freeze.py."
        ),
        "sources": sorted(sources),
        "excluded": EXCLUDED,
        "metrics": metrics,
    }


def freeze(check_only: bool = False) -> int:
    missing = [src for src, _ in CITED if not (RESULTS / src).exists()]
    if missing:
        print("results the manuscript cites are missing:")
        for src in missing:
            print(f"  {src}")
        return 1

    sources = {name: _load(RESULTS / src) for src, name in CITED}
    try:
        _gate(sources)
    except FreezeError as error:
        print(f"refusing to freeze: {error}")
        return 1

    manifest = derive(sources)

    if check_only:
        stale: list[str] = []
        for _source, name in CITED:
            frozen = FROZEN / name
            if not frozen.exists() or _load(frozen) != sources[name]:
                stale.append(name)
        current = FROZEN / "manifest.json"
        if not current.exists() or _load(current) != manifest:
            stale.append("manifest.json")
        if stale:
            print("the freeze is stale; run paper/freeze.py:")
            for name in stale:
                print(f"  {name}")
            return 1
        print(f"freeze current: {len(CITED)} files, {len(manifest['metrics'])} metrics")
        return 0

    FROZEN.mkdir(parents=True, exist_ok=True)
    for src, name in CITED:
        shutil.copy2(RESULTS / src, FROZEN / name)
    (FROZEN / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"froze {len(CITED)} files and derived {len(manifest['metrics'])} metrics")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the freeze is stale")
    args = parser.parse_args(argv)
    return freeze(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())

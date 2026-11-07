"""How close to absorbed organ dose can any index-based conversion get?

The organ-weighted CTDIvol index of IORN-006 and the absorbed organ dose of this
work are different quantities; that much is not in question and is not a finding.
The question this answers is quantitative: given everything an index can carry --
the tube-current organ weighting, a scan-length term, a per-organ coefficient --
how far from mGy does the best such conversion still sit, and what is left over?

The models are fitted and scored under leave-one-patient-out cross-validation.
Fitting a length coefficient and twelve organ offsets on thirty patients and then
reporting the error on those same thirty is optimistic by construction, and thirty
is small enough for that to matter. Every error quoted here is on a patient the
model never saw.

Nothing here runs the engine. It reads what the production run already recorded:

    results/phase2_cohort/figure4_doses.json       absorbed dose, scaled, per organ
    results/phase2_cohort/iorn006_organ_index.json the index, per organ
    results/phase2_patient/prod_*/organ_doses.json geometry and Monte-Carlo sigma

and writes results/phase2_cohort/conversion_ceiling.json.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
COHORT = REPO / "results" / "phase2_cohort"
PATIENT = REPO / "results" / "phase2_patient"
DEFAULT_OUT = COHORT / "conversion_ceiling.json"

#: Resampling for the model comparisons. Fixed, because a confidence interval that
#: moves between runs cannot be quoted in a manuscript.
BOOTSTRAP_DRAWS = 10000
BOOTSTRAP_SEED = 20261107


class Point(dict):
    """One organ in one series: the index, the dose, and what an index could know."""


def _collect() -> list[Point]:
    doses = json.loads((COHORT / "figure4_doses.json").read_text(encoding="utf-8"))
    index = json.loads((COHORT / "iorn006_organ_index.json").read_text(encoding="utf-8"))
    by_uid = {row["series_instance_uid"]: row for row in index["series"]}

    geometry: dict[str, dict[str, Any]] = {}
    for path in sorted(PATIENT.glob("prod_*/organ_doses.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        plan = record["plan"]
        phantom = plan["phantom"]
        voxel_cm = phantom["iso_grid_mm"] / 10.0
        body_cm3 = phantom["n_body_voxels"] * voxel_cm**3
        length_cm = float(plan["bbox_cm"][2])
        area_cm2 = body_cm3 / length_cm
        geometry[record["series_instance_uid"]] = {
            "n_z_stations": plan["n_z_stations"],
            "scan_length_cm": length_cm,
            "effective_diameter_cm": 2.0 * math.sqrt(area_cm2 / math.pi),
            "kvp": plan["kvp"],
            "sigma": {
                organ: values["sigma_mgy"] / values["dose_mgy"]
                for organ, values in record["organs"].items()
                if values.get("dose_mgy")
            },
        }

    points: list[Point] = []
    for uid, organ_doses in doses["doses"].items():
        meta, geom = by_uid.get(uid), geometry.get(uid)
        if meta is None or geom is None:
            continue
        by_organ = {entry["organ"]: entry for entry in meta["organs"]}
        for organ, dose in organ_doses.items():
            entry = by_organ.get(organ)
            if entry is None:
                continue
            index_mgy = entry.get("organ_weighted_ctdivol_mgy")
            if not index_mgy or not dose:
                continue
            points.append(
                Point(
                    uid=uid,
                    vendor=meta["vendor"],
                    organ=organ,
                    index_mgy=float(index_mgy),
                    dose_mgy=float(dose),
                    ratio=float(dose) / float(index_mgy),
                    mass_g=entry.get("mass_g"),
                    n_z_stations=geom["n_z_stations"],
                    scan_length_cm=geom["scan_length_cm"],
                    effective_diameter_cm=geom["effective_diameter_cm"],
                    relative_sigma=geom["sigma"].get(organ),
                )
            )
    return points


# --------------------------------------------------------------------- models
#
# Each model is fitted on a set of points and returns a function predicting the
# index-to-dose ratio for an unseen point. All work in log ratio, because the
# quantity is a multiplicative factor spanning several fold and its errors are
# naturally relative.

Model = Callable[[Sequence[Point]], Callable[[Point], float]]


def _fit_line(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    n = len(xs)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return my, 0.0
    slope = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / sxx
    return my - slope * mx, slope


def model_global(train: Sequence[Point]) -> Callable[[Point], float]:
    """One number for the whole cohort."""
    k = math.exp(statistics.fmean([math.log(p["ratio"]) for p in train]))
    return lambda point: k


def model_per_organ(train: Sequence[Point]) -> Callable[[Point], float]:
    """One number per organ: what a published coefficient table offers."""
    overall = statistics.fmean([math.log(p["ratio"]) for p in train])
    by_organ: dict[str, float] = {}
    for organ in {p["organ"] for p in train}:
        by_organ[organ] = statistics.fmean(
            [math.log(p["ratio"]) for p in train if p["organ"] == organ]
        )
    return lambda point: math.exp(by_organ.get(point["organ"], overall))


def model_length(train: Sequence[Point]) -> Callable[[Point], float]:
    """A scan-length term. CTDIvol is per rotation and carries no length."""
    intercept, slope = _fit_line(
        [math.log(p["n_z_stations"]) for p in train],
        [math.log(p["ratio"]) for p in train],
    )
    return lambda point: math.exp(intercept + slope * math.log(point["n_z_stations"]))


def model_length_and_organ(train: Sequence[Point]) -> Callable[[Point], float]:
    """Everything an index can carry: length, then a per-organ offset on top."""
    intercept, slope = _fit_line(
        [math.log(p["n_z_stations"]) for p in train],
        [math.log(p["ratio"]) for p in train],
    )
    offsets: dict[str, float] = {}
    for organ in {p["organ"] for p in train}:
        residuals = [
            math.log(p["ratio"]) - (intercept + slope * math.log(p["n_z_stations"]))
            for p in train
            if p["organ"] == organ
        ]
        offsets[organ] = statistics.fmean(residuals)
    return lambda point: math.exp(
        intercept + slope * math.log(point["n_z_stations"]) + offsets.get(point["organ"], 0.0)
    )


def model_length_and_size(train: Sequence[Point]) -> Callable[[Point], float]:
    """Length, then patient size -- the correction the field reaches for first."""
    intercept, slope = _fit_line(
        [math.log(p["n_z_stations"]) for p in train],
        [math.log(p["ratio"]) for p in train],
    )
    residuals = [
        math.log(p["ratio"]) - (intercept + slope * math.log(p["n_z_stations"])) for p in train
    ]
    size_intercept, size_slope = _fit_line(
        [math.log(p["effective_diameter_cm"]) for p in train], residuals
    )
    return lambda point: math.exp(
        intercept
        + slope * math.log(point["n_z_stations"])
        + size_intercept
        + size_slope * math.log(point["effective_diameter_cm"])
    )


MODELS: dict[str, tuple[str, Model]] = {
    "global_factor": ("a single conversion factor for the cohort", model_global),
    "per_organ_factor": (
        "one factor per organ, as a coefficient table offers",
        model_per_organ,
    ),
    "scan_length": ("a scan-length term alone", model_length),
    "scan_length_and_organ": (
        "a scan-length term and a per-organ offset: everything an index carries",
        model_length_and_organ,
    ),
    "scan_length_and_size": (
        "a scan-length term and patient effective diameter",
        model_length_and_size,
    ),
}


# ---------------------------------------------------------------- the error
#
# The quantity every number in this section reports: how far the conversion's
# estimate of absorbed organ dose falls from the Monte-Carlo dose, as a fraction
# of the Monte-Carlo dose. The reference goes in the denominator.
#
# This was the other way round until 2026-11-07, dividing by the model's own
# prediction, and it is not a cosmetic difference. For a ratio x the two measures
# are |x - 1| and |1/x - 1|, so a conversion that errs low and one that errs high
# are weighted differently, and the ranking of two models can and here does move:
# the per-organ table was reported as slightly worse than one factor and is
# slightly better when the reference is in the denominator. The manuscript's own
# verification figure already used the reference as the denominator, so the paper
# was carrying two conventions at once. This is the one it says it uses -- "recovers
# absorbed organ dose to within x %" is a statement about the reference -- and the
# one TG-195 comparisons and dose-estimation papers use.
#
# Because the index-to-dose ratio is the dose divided by a quantity both sides
# share, the relative error on the ratio is the relative error on the dose.


def _relative_error(measured: float, predicted: float) -> float:
    """|estimate - reference| / reference."""
    return abs(predicted / measured - 1.0)


def _inverted_relative_error(measured: float, predicted: float) -> float:
    """The superseded measure, kept so the change above can be audited."""
    return abs(measured / predicted - 1.0)


def _held_out(points: Sequence[Point], model: Model) -> tuple[dict[str, list[float]], list[float]]:
    """Leave-one-patient-out errors, both ways, from one pass of folds.

    Returns the errors grouped by the patient they were scored on, and the pooled
    errors under the superseded measure. Grouped rather than pooled because the
    comparisons below resample patients: the organs of one patient share that
    patient's conversion factor, which is the finding of section 3.5, so they are
    not independent draws.

    One pass, not two. Fitting every fold a second time to compute the second
    measure would double the work and -- the reason it is written this way -- would
    make ``_score`` fit each patient twice, which is indistinguishable from a
    cross-validation defect to any test that counts folds.
    """
    grouped: dict[str, list[float]] = {}
    inverted: list[float] = []
    for uid in sorted({p["uid"] for p in points}):
        train = [p for p in points if p["uid"] != uid]
        test = [p for p in points if p["uid"] == uid]
        predict = model(train)
        errors: list[float] = []
        for point in test:
            predicted = predict(point)
            errors.append(_relative_error(point["ratio"], predicted))
            inverted.append(_inverted_relative_error(point["ratio"], predicted))
        grouped[uid] = errors
    return grouped, inverted


def _distribution(errors: Iterable[float]) -> dict[str, Any]:
    ordered = sorted(errors)

    def quantile(fraction: float) -> float:
        return ordered[min(int(fraction * len(ordered)), len(ordered) - 1)]

    return {
        "n_points": len(ordered),
        "median_absolute_relative_error": quantile(0.5),
        "p90_absolute_relative_error": quantile(0.9),
        "max_absolute_relative_error": ordered[-1],
        "within_20_percent": sum(1 for e in ordered if e <= 0.20) / len(ordered),
        "quantiles": {
            "p10": quantile(0.10),
            "p25": quantile(0.25),
            "p50": quantile(0.50),
            "p75": quantile(0.75),
            "p90": quantile(0.90),
        },
    }


def _score(points: Sequence[Point], model: Model) -> dict[str, Any]:
    """Leave-one-patient-out. Every error is on a patient the fit never saw."""
    by_patient, inverted = _held_out(points, model)
    scored = _distribution(e for errors in by_patient.values() for e in errors)
    scored["error_definition"] = (
        "|estimated organ dose - Monte-Carlo organ dose| / Monte-Carlo organ dose"
    )

    # The superseded measure, on the same held-out predictions, so that a reader
    # can see what the choice of denominator is worth here.
    scored["prediction_in_denominator"] = {
        "what": "the superseded measure, |reference / estimate - 1|, for audit only",
        **{key: value for key, value in _distribution(inverted).items() if key != "n_points"},
    }
    return scored


def _compare(points: Sequence[Point], baseline: str, other: str) -> dict[str, Any]:
    """Is the difference between two models resolved by thirty patients?

    Two medians a percentage point or two apart are not a result on their own, and
    the paper's practical recommendation turns on one such pair. Resampling is over
    patients for the reason given in ``_held_out_errors``; the paired sign test asks
    the same question without assuming anything about the shape.
    """
    base, _ = _held_out(points, MODELS[baseline][1])
    test, _ = _held_out(points, MODELS[other][1])
    uids = sorted(base)

    def median_over(groups: dict[str, list[float]], draw: Sequence[str]) -> float:
        return statistics.median([e for uid in draw for e in groups[uid]])

    observed = median_over(test, uids) - median_over(base, uids)

    rng = random.Random(BOOTSTRAP_SEED)
    differences = sorted(
        median_over(test, draw) - median_over(base, draw)
        for draw in ([rng.choice(uids) for _ in uids] for _ in range(BOOTSTRAP_DRAWS))
    )
    low = differences[int(0.025 * len(differences))]
    high = differences[int(0.975 * len(differences))]

    wins = sum(1 for uid in uids if statistics.median(test[uid]) < statistics.median(base[uid]))
    n = len(uids)
    tail = min(wins, n - wins)
    p_value = sum(math.comb(n, k) for k in range(tail + 1)) * 2 / 2**n

    return {
        "baseline": baseline,
        "model": other,
        "median_difference": observed,
        "ci95_patient_bootstrap": [low, high],
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "patients_where_model_is_better": wins,
        "n_patients": n,
        "sign_test_p": min(p_value, 1.0),
        "resolved": not (low < 0.0 < high),
    }


def _additive_fit(points: Sequence[Point], keys: Sequence[str]) -> float:
    """Residual sum of squares of an additive model in the named factors.

    The layout is one observation per patient-organ cell with cells missing, so the
    patient and organ sums of squares are not orthogonal and cannot simply be added.
    Alternating least squares fits the additive model itself; what it leaves is the
    part neither factor explains.
    """
    ys = [math.log(p["ratio"]) for p in points]
    grand = statistics.fmean(ys)
    effects: list[dict[str, float]] = [{} for _ in keys]

    for _ in range(500):
        moved = 0.0
        for axis, key in enumerate(keys):
            groups: dict[str, list[float]] = {}
            for index, point in enumerate(points):
                other = sum(
                    effects[a].get(point[keys[a]], 0.0) for a in range(len(keys)) if a != axis
                )
                groups.setdefault(point[key], []).append(ys[index] - grand - other)
            for level, residuals in groups.items():
                new = statistics.fmean(residuals)
                moved = max(moved, abs(new - effects[axis].get(level, 0.0)))
                effects[axis][level] = new
        if moved < 1e-12:
            break

    return sum(
        (ys[index] - grand - sum(effects[a].get(point[keys[a]], 0.0) for a in range(len(keys))))
        ** 2
        for index, point in enumerate(points)
    )


def _variance_decomposition(points: Sequence[Point]) -> dict[str, Any]:
    """Where the index-to-dose factor varies: between patients and between organs.

    This used to measure patient, organ and vendor each against the grand mean and
    report the three shares side by side, which reads as a partition and is not one.
    Two things were wrong with that. Vendor is a property of the series and every
    patient here contributed one series, so vendor is nested inside patient and its
    share is a part of the patient share, not an addition to it. And the patient and
    organ shares overlap, because eighteen of the three hundred and sixty cells are
    empty; they summed to within a few per cent of one only by coincidence.

    What is reported instead: each factor's own share, the share the additive model
    in both explains, the overlap between them as a number, and the residual. Those
    last three do partition the total.
    """
    ys = [math.log(p["ratio"]) for p in points]
    grand = statistics.fmean(ys)
    total_ss = sum((y - grand) ** 2 for y in ys)

    def marginal_ss(key: str) -> tuple[float, int]:
        groups: dict[str, list[float]] = {}
        for index, point in enumerate(points):
            groups.setdefault(point[key], []).append(ys[index])
        between = sum(
            len(values) * (statistics.fmean(values) - grand) ** 2 for values in groups.values()
        )
        return between, len(groups)

    patient_ss, n_patients = marginal_ss("uid")
    organ_ss, n_organs = marginal_ss("organ")
    vendor_ss, n_vendors = marginal_ss("vendor")

    additive_ss = total_ss - _additive_fit(points, ("uid", "organ"))

    vendors_per_patient = {}
    for point in points:
        vendors_per_patient.setdefault(point["uid"], set()).add(point["vendor"])
    n_mixed = sum(1 for vendors in vendors_per_patient.values() if len(vendors) > 1)

    return {
        "what": (
            "variance of the log dose-to-index ratio, by factor. The patient and "
            "organ shares overlap; the additive, overlap and residual shares below "
            "are the ones that sum to one."
        ),
        "total_variance_of_log_ratio": total_ss / len(points),
        "between_patient_share": patient_ss / total_ss,
        "between_organ_share": organ_ss / total_ss,
        "n_patients": n_patients,
        "n_organ": n_organs,
        "additive_patient_and_organ_share": additive_ss / total_ss,
        "patient_organ_overlap_share": (patient_ss + organ_ss - additive_ss) / total_ss,
        "residual_share": 1.0 - additive_ss / total_ss,
        "vendor": {
            "nested_in_patient": n_mixed == 0,
            "n_patients_with_more_than_one_vendor": n_mixed,
            "n_vendor": n_vendors,
            "share_of_total": vendor_ss / total_ss,
            "share_of_between_patient": vendor_ss / patient_ss,
            "note": (
                "every patient contributed one series and therefore one vendor, so "
                "this is a contrast within the between-patient variation and is "
                "contained in it, not additional to it"
            ),
        },
    }


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return float("nan")
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / (sx * sy)


def analyse() -> dict[str, Any]:
    points = _collect()
    if not points:
        raise SystemExit("no paired index/dose points; has the production run completed?")

    patients = sorted({p["uid"] for p in points})
    patient_ratio = {
        uid: statistics.median([p["ratio"] for p in points if p["uid"] == uid]) for uid in patients
    }

    # Is the length dependence physics or arithmetic? A slope of one on
    # log n_z means dose simply accumulates once per station, which is what a
    # per-rotation index failing to carry length would look like, and nothing more.
    intercept, slope = _fit_line(
        [math.log(p["n_z_stations"]) for p in points],
        [math.log(p["ratio"]) for p in points],
    )

    # Two different quantities, and the manuscript printed the first while
    # describing the second. A geometric standard deviation is a spread; it does
    # not bound anything. The widest separation inside a patient is what a sentence
    # of the form "every one of that patient's organs to within x" is claiming, so
    # measure that too -- it is larger, and it holds for no patient at the value
    # the geometric standard deviation suggests.
    within_patient_gsd = []
    within_patient_fold = []
    for uid in patients:
        ratios = [p["ratio"] for p in points if p["uid"] == uid]
        if len(ratios) >= 4:
            within_patient_gsd.append(math.exp(statistics.stdev([math.log(r) for r in ratios])))
            within_patient_fold.append(max(ratios) / min(ratios))
    within_patient_fold.sort()

    sigmas = [p["relative_sigma"] for p in points if p["relative_sigma"] is not None]

    return {
        "what": (
            "How close an index-based conversion can get to absorbed organ dose, "
            "scored under leave-one-patient-out cross-validation."
        ),
        "not": (
            "Not a claim that a scan-length term is a discovery. CTDIvol is a "
            "per-rotation index and carries no length by construction; DLP is the "
            "standard quantity that does. The length term is included because a "
            "conversion that omitted it would be a straw man, and the fitted slope "
            "is reported so a reader can see how close to proportional it is. Not a "
            "statement about index-based conversion in general either: five models "
            "were fitted and cross-validated here, and the numbers bound those five "
            "on this cohort."
        ),
        "n_points": len(points),
        "n_patients": len(patients),
        "n_organs": len({p["organ"] for p in points}),
        "ratio": {
            "definition": "absorbed organ dose (mGy) / organ-weighted CTDIvol (mGy)",
            "median": statistics.median([p["ratio"] for p in points]),
            "min": min(p["ratio"] for p in points),
            "max": max(p["ratio"] for p in points),
            "patient_median_min": min(patient_ratio.values()),
            "patient_median_max": max(patient_ratio.values()),
            "patient_fold_span": max(patient_ratio.values()) / min(patient_ratio.values()),
            "within_patient_geometric_sd_median": statistics.median(within_patient_gsd),
            "within_patient_fold_median": statistics.median(within_patient_fold),
            "within_patient_fold_p90": within_patient_fold[
                min(int(0.9 * len(within_patient_fold)), len(within_patient_fold) - 1)
            ],
            "within_patient_fold_max": within_patient_fold[-1],
            "n_patients_scored_for_fold": len(within_patient_fold),
        },
        "variance": _variance_decomposition(points),
        "length_dependence": {
            "fit": "log(ratio) = intercept + slope * log(n_z_stations)",
            "intercept": intercept,
            "slope": slope,
            "interpretation": (
                "a slope of 1 is simple accumulation per z station; this is "
                "reported, not claimed as a result"
            ),
        },
        "size_dependence": {
            "what": "patient effective diameter against the patient-level factor",
            "pearson_r_log": _pearson(
                [
                    math.log(next(p["effective_diameter_cm"] for p in points if p["uid"] == uid))
                    for uid in patients
                ],
                [math.log(patient_ratio[uid]) for uid in patients],
            ),
            "effective_diameter_cm_range": [
                min(p["effective_diameter_cm"] for p in points),
                max(p["effective_diameter_cm"] for p in points),
            ],
        },
        "monte_carlo_noise_floor": {
            "what": "per-organ Monte-Carlo statistical uncertainty, relative",
            "n": len(sigmas),
            "median": statistics.median(sigmas),
            "max": max(sigmas),
            "what_it_bounds": (
                "the sampling uncertainty of this engine's own estimate, and nothing "
                "else. It does not bound the source model, the CTDIvol normalisation, "
                "the HU-to-material conversion, the segmentation, or the choice of "
                "conversion model, so a residual far above it is not thereby shown "
                "to be a property of the transport"
            ),
        },
        "models": {
            name: {"description": description, **_score(points, model)}
            for name, (description, model) in MODELS.items()
        },
        # Both baselines a claim in the paper rests on: whether a richer model beats
        # one number at all, and whether anything beats a scan-length term once that
        # term is in. Section 3.6's statement about patient size is the second kind.
        "model_comparisons": {
            f"{name}_vs_{baseline}": _compare(points, baseline, name)
            for baseline in ("global_factor", "scan_length")
            for name in MODELS
            if name != baseline and not (baseline == "scan_length" and name == "global_factor")
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    payload = analyse()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    for name, scores in payload["models"].items():
        print(
            f"  {name:24} median {scores['median_absolute_relative_error']:5.1%}"
            f"   p90 {scores['p90_absolute_relative_error']:5.1%}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

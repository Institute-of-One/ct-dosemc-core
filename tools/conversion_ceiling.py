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
import statistics
from pathlib import Path
from typing import Any, Callable, Sequence

REPO = Path(__file__).resolve().parents[1]
COHORT = REPO / "results" / "phase2_cohort"
PATIENT = REPO / "results" / "phase2_patient"
DEFAULT_OUT = COHORT / "conversion_ceiling.json"


class Point(dict):
    """One organ in one series: the index, the dose, and what an index could know."""


def _collect() -> list[Point]:
    doses = json.loads((COHORT / "figure4_doses.json").read_text(encoding="utf-8"))
    index = json.loads(
        (COHORT / "iorn006_organ_index.json").read_text(encoding="utf-8")
    )
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
    return lambda point: math.exp(
        intercept + slope * math.log(point["n_z_stations"])
    )


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
        intercept
        + slope * math.log(point["n_z_stations"])
        + offsets.get(point["organ"], 0.0)
    )


def model_length_and_size(train: Sequence[Point]) -> Callable[[Point], float]:
    """Length, then patient size -- the correction the field reaches for first."""
    intercept, slope = _fit_line(
        [math.log(p["n_z_stations"]) for p in train],
        [math.log(p["ratio"]) for p in train],
    )
    residuals = [
        math.log(p["ratio"]) - (intercept + slope * math.log(p["n_z_stations"]))
        for p in train
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


def _score(points: Sequence[Point], model: Model) -> dict[str, Any]:
    """Leave-one-patient-out. Every error is on a patient the fit never saw."""
    errors: list[float] = []
    for uid in sorted({p["uid"] for p in points}):
        train = [p for p in points if p["uid"] != uid]
        test = [p for p in points if p["uid"] == uid]
        predict = model(train)
        for point in test:
            errors.append(abs(point["ratio"] / predict(point) - 1.0))
    errors.sort()

    def quantile(fraction: float) -> float:
        return errors[min(int(fraction * len(errors)), len(errors) - 1)]

    return {
        "n_points": len(errors),
        "median_absolute_relative_error": quantile(0.5),
        "p90_absolute_relative_error": quantile(0.9),
        "max_absolute_relative_error": errors[-1],
        "within_20_percent": sum(1 for e in errors if e <= 0.20) / len(errors),
        "quantiles": {
            "p10": quantile(0.10),
            "p25": quantile(0.25),
            "p50": quantile(0.50),
            "p75": quantile(0.75),
            "p90": quantile(0.90),
        },
    }


def _variance_decomposition(points: Sequence[Point]) -> dict[str, Any]:
    """Where the index-to-dose factor varies: between patients, organs, vendors."""
    log_ratio = [math.log(p["ratio"]) for p in points]
    grand = statistics.fmean(log_ratio)
    total = statistics.pvariance(log_ratio)

    shares: dict[str, Any] = {"total_variance_of_log_ratio": total}
    for key in ("uid", "organ", "vendor"):
        groups: dict[str, list[float]] = {}
        for point in points:
            groups.setdefault(point[key], []).append(math.log(point["ratio"]))
        between = sum(
            len(values) * (statistics.fmean(values) - grand) ** 2
            for values in groups.values()
        ) / len(points)
        shares[f"between_{key}_share"] = between / total
        shares[f"n_{key}"] = len(groups)
    shares["between_patient_share"] = shares.pop("between_uid_share")
    shares["n_patients"] = shares.pop("n_uid")
    return shares


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
        uid: statistics.median([p["ratio"] for p in points if p["uid"] == uid])
        for uid in patients
    }

    # Is the length dependence physics or arithmetic? A slope of one on
    # log n_z means dose simply accumulates once per station, which is what a
    # per-rotation index failing to carry length would look like, and nothing more.
    intercept, slope = _fit_line(
        [math.log(p["n_z_stations"]) for p in points],
        [math.log(p["ratio"]) for p in points],
    )

    within_patient = []
    for uid in patients:
        logs = [math.log(p["ratio"]) for p in points if p["uid"] == uid]
        if len(logs) >= 4:
            within_patient.append(math.exp(statistics.stdev(logs)))

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
            "is reported so a reader can see how close to proportional it is."
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
            "patient_fold_span": max(patient_ratio.values())
            / min(patient_ratio.values()),
            "within_patient_spread_median_fold": statistics.median(within_patient),
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
                    math.log(
                        next(
                            p["effective_diameter_cm"] for p in points if p["uid"] == uid
                        )
                    )
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
        },
        "models": {
            name: {"description": description, **_score(points, model)}
            for name, (description, model) in MODELS.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    payload = analyse()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.out}")
    for name, scores in payload["models"].items():
        print(
            f"  {name:24} median {scores['median_absolute_relative_error']:5.1%}"
            f"   p90 {scores['p90_absolute_relative_error']:5.1%}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

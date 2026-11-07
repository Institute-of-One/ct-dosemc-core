"""The ceiling analysis must be honest about what it fitted and what it scored."""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import conversion_ceiling as ceiling  # noqa: E402

RESULT = REPO / "results" / "phase2_cohort" / "conversion_ceiling.json"

pytestmark = pytest.mark.skipif(
    not (REPO / "results" / "phase2_cohort" / "figure4_doses.json").is_file(),
    reason="the production run has not been collected",
)


@pytest.fixture(scope="module")
def points():
    return ceiling._collect()


@pytest.fixture(scope="module")
def recorded():
    if not RESULT.is_file():
        pytest.skip("run tools/conversion_ceiling.py")
    return json.loads(RESULT.read_text(encoding="utf-8"))


def test_the_pairing_matches_the_figure_it_shares_a_cohort_with(points) -> None:
    """342 points over 30 series is what Figure 4 plots; this must be the same set."""
    stats = json.loads(
        (REPO / "results" / "phase2_cohort" / "figure4_stats.json").read_text(encoding="utf-8")
    )
    assert len(points) == stats["n_points"]
    assert len({p["uid"] for p in points}) == stats["n_series"]
    assert len({p["organ"] for p in points}) == stats["n_organs"]


def test_every_point_carries_what_the_models_need(points) -> None:
    for point in points:
        assert point["index_mgy"] > 0
        assert point["dose_mgy"] > 0
        assert point["n_z_stations"] >= 1
        assert point["effective_diameter_cm"] > 0


def test_the_scoring_never_fits_on_the_patient_it_scores() -> None:
    """The whole claim rests on this. A model that saw the patient is optimistic.

    A model that memorises its training patients and falls back to a constant for
    anyone else must score no better than that constant.
    """
    seen: list[set[str]] = []

    def memorising(train):
        seen.append({p["uid"] for p in train})
        lookup = {p["uid"]: p["ratio"] for p in train}
        return lambda point: lookup.get(point["uid"], 1.0)

    points = ceiling._collect()
    patients = {p["uid"] for p in points}
    ceiling._score(points, memorising)

    assert len(seen) == len(patients), "one fold per patient"
    for train_uids in seen:
        assert len(train_uids) == len(patients) - 1
    # Every patient was held out exactly once.
    held_out = [patients - train_uids for train_uids in seen]
    assert sorted(len(h) for h in held_out) == [1] * len(patients)
    assert {next(iter(h)) for h in held_out} == patients


def test_a_per_organ_table_is_not_separated_from_a_single_factor(recorded) -> None:
    """The paper's sharpest claim, asserted against the recorded numbers.

    This asserted the per-organ median was the larger of the two until 2026-11-07,
    which was an artefact of dividing by the prediction rather than the reference:
    under the measure the paper says it uses, the per-organ median is the smaller.
    Neither direction is the claim. The claim is that thirty patients do not
    separate them, and the interval is what says so.
    """
    comparison = recorded["model_comparisons"]["per_organ_factor_vs_global_factor"]
    low, high = comparison["ci95_patient_bootstrap"]
    assert low < 0.0 < high, "the interval must contain zero for the claim to hold"
    assert comparison["resolved"] is False
    assert comparison["sign_test_p"] > 0.05


def test_the_error_is_measured_against_the_reference(recorded, points) -> None:
    """The reference goes in the denominator, and the two measures differ here.

    A paper reporting that a conversion "recovers dose to within x %" is making a
    statement about the reference. Until 2026-11-07 the scoring divided by the
    model's own prediction instead, which reversed the ranking of the first two
    conversions.

    This recomputes the single-factor median from the points with the division
    written out here, rather than asking the module whether it agrees with itself,
    and requires the recorded number to match. Checking the definition string
    instead would not bite: a rescoring that leaves the words "Monte-Carlo organ
    dose" in the sentence passes it, and the first version of this test did.
    """
    errors: list[float] = []
    for uid in sorted({p["uid"] for p in points}):
        train = [p for p in points if p["uid"] != uid]
        predict = ceiling.model_global(train)
        for point in (p for p in points if p["uid"] == uid):
            measured = point["ratio"]
            errors.append(abs(predict(point) - measured) / measured)
    errors.sort()

    assert recorded["models"]["global_factor"]["median_absolute_relative_error"] == pytest.approx(
        errors[len(errors) // 2]
    )

    # And the two measures must actually differ, or the test above is vacuous.
    assert recorded["models"]["global_factor"]["median_absolute_relative_error"] != pytest.approx(
        recorded["models"]["global_factor"]["prediction_in_denominator"][
            "median_absolute_relative_error"
        ]
    )


def test_sampling_noise_cannot_account_for_the_residual(recorded) -> None:
    """If Monte-Carlo noise were the same size as the residual, there is no result.

    Named for what it shows. It was named "the residual is physical", which is not
    what a comparison against the sampling uncertainty establishes: the sampling
    uncertainty bounds this engine's own estimate and nothing else, so the result
    carries that limit in the payload where the prose can be checked against it.
    """
    floor = recorded["monte_carlo_noise_floor"]["median"]
    best = min(model["median_absolute_relative_error"] for model in recorded["models"].values())
    assert best > 100 * floor, (
        f"the best model's error {best:.3f} is not far above the Monte-Carlo "
        f"noise floor {floor:.5f}"
    )
    bounds = recorded["monte_carlo_noise_floor"]["what_it_bounds"]
    assert "and nothing else" in bounds


def test_the_variance_shares_that_are_a_partition_sum_to_one(recorded) -> None:
    """Three shares against the grand mean are not a decomposition.

    Patient, organ and vendor were reported side by side and summed to 0.98, which
    reads as a partition. It was not one: vendor is nested in patient here, so its
    share lies inside the patient share. What does partition the total is the
    additive model in patient and organ against what it leaves.
    """
    variance = recorded["variance"]
    for key in ("between_patient_share", "between_organ_share"):
        assert 0.0 <= variance[key] <= 1.0
    assert variance["additive_patient_and_organ_share"] + variance[
        "residual_share"
    ] == pytest.approx(1.0)
    assert variance["vendor"]["nested_in_patient"] is True
    assert variance["vendor"]["n_patients_with_more_than_one_vendor"] == 0
    # Nested means contained: the vendor contrast cannot exceed what it sits inside.
    assert variance["vendor"]["share_of_total"] <= variance["between_patient_share"]


def test_the_length_slope_is_reported_not_hidden(recorded) -> None:
    """Near-proportional means largely arithmetic, and the paper has to say so."""
    slope = recorded["length_dependence"]["slope"]
    assert 0.5 < slope < 2.0
    assert "not claimed as a result" in recorded["length_dependence"]["interpretation"]
    assert "straw man" in recorded["not"]


def test_the_recorded_numbers_are_reproducible(points, recorded) -> None:
    """Recompute one score from the points and match what was written."""
    fresh = ceiling._score(points, ceiling.model_global)
    assert fresh["median_absolute_relative_error"] == pytest.approx(
        recorded["models"]["global_factor"]["median_absolute_relative_error"]
    )


def test_within_patient_spread_is_tighter_than_between(recorded) -> None:
    ratio = recorded["ratio"]
    assert ratio["within_patient_fold_median"] < ratio["patient_fold_span"]
    assert recorded["variance"]["between_patient_share"] > 0.5


def test_the_within_patient_fold_is_wider_than_the_geometric_spread(recorded, points) -> None:
    """A geometric standard deviation is not a bound, and was printed as one.

    The manuscript said every one of a patient's organs lay within the geometric
    standard deviation of that patient's factor. It is a spread: the widest
    separation actually present is larger, and the two are reported separately so
    that a sentence about "all of that patient's organs" quotes the second.
    """
    ratio = recorded["ratio"]
    assert ratio["within_patient_fold_median"] > ratio["within_patient_geometric_sd_median"]
    assert ratio["within_patient_fold_max"] >= ratio["within_patient_fold_median"]

    # No patient is actually within the geometric standard deviation, so a claim
    # using it as a bound is false for every patient, not merely imprecise.
    gsd = ratio["within_patient_geometric_sd_median"]
    folds = []
    for uid in sorted({p["uid"] for p in points}):
        ratios = [p["ratio"] for p in points if p["uid"] == uid]
        folds.append(max(ratios) / min(ratios))
    assert sum(1 for fold in folds if fold <= gsd) == 0


# --------------------------------------------------------------------------
# The checks above are only worth what they catch. Each defect below was in the
# shipped analysis on 2026-11-07; each is put back as it actually was, because a
# paraphrase that leaves the words a test reads will pass it -- the first version
# of test_the_error_is_measured_against_the_reference checked the definition
# string, and a rescoring that kept the phrase "Monte-Carlo organ dose" in that
# string walked straight through it.


def _doctored(recorded: dict, **patch) -> dict:
    copied = json.loads(json.dumps(recorded))
    for path, value in patch.items():
        node = copied
        *parents, leaf = path.split("__")
        for step in parents:
            node = node[step]
        node[leaf] = value
    return copied


def test_the_denominator_check_catches_the_prediction_in_the_denominator(recorded, points) -> None:
    bad = json.loads(json.dumps(recorded))
    original = ceiling._relative_error
    ceiling._relative_error = ceiling._inverted_relative_error
    try:
        for name, (description, model) in ceiling.MODELS.items():
            bad["models"][name] = {"description": description, **ceiling._score(points, model)}
    finally:
        ceiling._relative_error = original
    with pytest.raises(AssertionError):
        test_the_error_is_measured_against_the_reference(bad, points)


def test_the_partition_check_catches_three_shares_of_one_whole(recorded) -> None:
    bad = json.loads(json.dumps(recorded))
    bad["variance"] = {
        "between_patient_share": recorded["variance"]["between_patient_share"],
        "between_organ_share": recorded["variance"]["between_organ_share"],
        "between_vendor_share": recorded["variance"]["vendor"]["share_of_total"],
    }
    with pytest.raises((AssertionError, KeyError)):
        test_the_variance_shares_that_are_a_partition_sum_to_one(bad)


def test_the_fold_check_catches_a_geometric_spread_wearing_its_name(recorded, points) -> None:
    gsd = recorded["ratio"]["within_patient_geometric_sd_median"]
    bad = _doctored(
        recorded,
        ratio__within_patient_fold_median=gsd,
        ratio__within_patient_fold_max=gsd,
    )
    with pytest.raises(AssertionError):
        test_the_within_patient_fold_is_wider_than_the_geometric_spread(bad, points)


def test_the_separation_check_catches_a_difference_declared_resolved(recorded) -> None:
    bad = json.loads(json.dumps(recorded))
    bad["model_comparisons"]["per_organ_factor_vs_global_factor"].update(
        {"ci95_patient_bootstrap": [-0.049, -0.004], "resolved": True, "sign_test_p": 0.01}
    )
    with pytest.raises(AssertionError):
        test_a_per_organ_table_is_not_separated_from_a_single_factor(bad)


def test_ratios_agree_with_the_raw_dose_and_index(points) -> None:
    for point in points[:20]:
        assert point["ratio"] == pytest.approx(point["dose_mgy"] / point["index_mgy"])


def test_log_fit_recovers_a_known_line() -> None:
    xs = [math.log(v) for v in (2, 4, 8, 16)]
    ys = [0.5 + 1.5 * x for x in xs]
    intercept, slope = ceiling._fit_line(xs, ys)
    assert intercept == pytest.approx(0.5)
    assert slope == pytest.approx(1.5)


def test_variance_decomposition_is_exact_on_a_constructed_case() -> None:
    """All variation between patients, none within: the patient share must be 1."""
    points = [
        ceiling.Point(uid=f"p{i}", organ=organ, vendor="V", ratio=math.exp(i))
        for i in range(4)
        for organ in ("liver", "spleen", "colon")
    ]
    shares = ceiling._variance_decomposition(points)
    assert shares["between_patient_share"] == pytest.approx(1.0)
    assert shares["between_organ_share"] == pytest.approx(0.0, abs=1e-12)
    assert statistics.fmean([1.0]) == 1.0

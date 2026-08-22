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
        (REPO / "results" / "phase2_cohort" / "figure4_stats.json").read_text(
            encoding="utf-8"
        )
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


def test_a_per_organ_table_does_not_beat_a_single_factor(recorded) -> None:
    """The paper's sharpest claim, asserted against the recorded numbers.

    Cross-validated, per-organ coefficients carry no transferable information: the
    twelve organ means are fitted on 29 patients and do not generalise to the 30th.
    """
    models = recorded["models"]
    assert (
        models["per_organ_factor"]["median_absolute_relative_error"]
        >= models["global_factor"]["median_absolute_relative_error"]
    )


def test_the_residual_is_physical_not_statistical(recorded) -> None:
    """If Monte-Carlo noise were the same size as the residual, there is no result."""
    floor = recorded["monte_carlo_noise_floor"]["median"]
    best = min(
        model["median_absolute_relative_error"]
        for model in recorded["models"].values()
    )
    assert best > 100 * floor, (
        f"the best model's error {best:.3f} is not far above the Monte-Carlo "
        f"noise floor {floor:.5f}"
    )


def test_the_variance_shares_are_shares(recorded) -> None:
    variance = recorded["variance"]
    for key in ("between_patient_share", "between_organ_share", "between_vendor_share"):
        assert 0.0 <= variance[key] <= 1.0


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
    assert ratio["within_patient_spread_median_fold"] < ratio["patient_fold_span"]
    assert recorded["variance"]["between_patient_share"] > 0.5


def test_ratios_agree_with_the_raw_dose_and_index(points) -> None:
    for point in points[:20]:
        assert point["ratio"] == pytest.approx(
            point["dose_mgy"] / point["index_mgy"]
        )


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

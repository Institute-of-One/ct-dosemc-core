"""Anti-fabrication: every number in ``results/`` must be re-derivable.

The rule inherited from ctdose-core and ctsegdose-core is that a figure quoted in
the paper is not a figure someone typed -- it is the output of a recorded
computation over recorded inputs.  These tests take the results files as they
sit on disk and recompute the reported values from the components stored beside
them.  If a value were edited by hand, or a stale file left behind, the
arithmetic stops closing and the test fails.

They are skipped, not failed, when no results file exists yet: an absent
Phase-1 run is a state of the project, not a defect.  A results file that exists
and does not reconcile is a defect.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ct_dosemc_core.ctdi import CHAMBER_POSITIONS
from ct_dosemc_core.source_model import EV_PER_G_TO_GY

RESULTS = Path(__file__).resolve().parent.parent / "results"
PERIPHERAL = tuple(n for n in CHAMBER_POSITIONS if n != "centre")


def _anchor_files() -> list[Path]:
    return sorted(RESULTS.glob("phase1_ctdi_anchor_*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


pytestmark = pytest.mark.skipif(
    not _anchor_files(), reason="no Phase-1 anchor results yet (tools/run_validation.py)"
)


@pytest.fixture(params=_anchor_files() or [None], ids=lambda p: p.name if p else "none")
def anchor(request):
    return _load(request.param)


def test_ctdiw_is_the_weighted_sum_of_the_reported_ctdi100(anchor):
    res = anchor["results"]
    centre = res["ctdi100_pmma_mgy"]["centre"]["value"]
    peripheral = res["ctdi100_peripheral_mean_mgy"]["value"]
    assert res["ctdiw_pmma_mgy"]["value"] == pytest.approx(centre / 3 + 2 * peripheral / 3, rel=1e-9)


def test_peripheral_mean_is_the_mean_of_the_four_positions(anchor):
    res = anchor["results"]
    four = [res["ctdi100_pmma_mgy"][n]["value"] for n in PERIPHERAL]
    assert res["ctdi100_peripheral_mean_mgy"]["value"] == pytest.approx(
        sum(four) / 4.0, rel=1e-9
    )


def test_ctdivol_is_ctdiw_over_pitch(anchor):
    res = anchor["results"]
    pitch = anchor["geometry"]["beam"]["pitch"]
    assert res["ctdivol_pmma_mgy"]["value"] == pytest.approx(
        res["ctdiw_pmma_mgy"]["value"] / pitch, rel=1e-9
    )


def test_ctdi100_follows_from_the_stored_region_dose_and_collimation(anchor):
    res = anchor["results"]
    collimation = anchor["geometry"]["beam"]["collimation_cm"]
    chamber_length = anchor["geometry"]["phantom"]["chamber_length_cm"]
    for name in CHAMBER_POSITIONS:
        detail = res["region_dose_detail"][name]
        expected = detail["dose_mgy"] * chamber_length / collimation
        assert res["ctdi100_pmma_mgy"][name]["value"] == pytest.approx(expected, rel=1e-9), name


def test_region_dose_follows_from_the_per_history_tally_and_the_photon_count(anchor):
    """The eV/g -> mGy conversion, recomputed from first principles."""
    n_hist = anchor["normalisation"]["histories_for_reported_mas"]["value"]
    for name, detail in anchor["results"]["region_dose_detail"].items():
        expected = detail["dose_ev_per_g_per_history"] * n_hist * EV_PER_G_TO_GY * 1.0e3
        assert detail["dose_mgy"] == pytest.approx(expected, rel=1e-9), name


def test_photon_count_follows_from_the_spectrum_and_the_solid_angle(anchor):
    norm = anchor["normalisation"]
    n_omega = norm["photons_per_sr_per_mas"]["value"]
    omega = anchor["geometry"]["beam"]["solid_angle_sr"]["value"]
    mas = norm["reported_mas"]
    assert norm["histories_for_reported_mas"]["value"] == pytest.approx(
        n_omega * omega * mas, rel=1e-9
    )


def test_solid_angle_follows_from_the_two_apertures(anchor):
    beam = anchor["geometry"]["beam"]
    theta = math.radians(beam["polar_aperture_deg"])
    phi = math.radians(beam["fan_aperture_deg"])
    assert beam["solid_angle_sr"]["value"] == pytest.approx(
        2.0 * math.sin(0.5 * theta) * phi, rel=1e-9
    )


def test_polar_aperture_reproduces_the_stated_collimation(anchor):
    beam = anchor["geometry"]["beam"]
    width = 2.0 * beam["sad_cm"] * math.tan(0.5 * math.radians(beam["polar_aperture_deg"]))
    assert width == pytest.approx(beam["collimation_cm"], rel=1e-6)


def test_the_engine_used_the_apertures_we_asked_for(anchor):
    """Not arithmetic -- provenance.  The engine echoes what it parsed."""
    checks = anchor["results"].get("beam_geometry_checks")
    if checks is None:
        pytest.skip("results file predates the beam-geometry diagnostics")
    beam = anchor["geometry"]["beam"]
    assert checks["engine_apertures_deg"]["azimuthal"] == pytest.approx(
        beam["fan_aperture_deg"], rel=1e-4
    )
    assert checks["engine_apertures_deg"]["polar"] == pytest.approx(
        beam["polar_aperture_deg"], rel=1e-4
    )


def test_symmetry_spread_matches_the_four_reported_positions(anchor):
    res = anchor["results"]
    four = [res["ctdi100_pmma_mgy"][n]["value"] for n in PERIPHERAL]
    expected = (max(four) - min(four)) / res["ctdi100_peripheral_mean_mgy"]["value"]
    assert res["peripheral_symmetry_spread_fraction"] == pytest.approx(expected, rel=1e-9)


# -- positive controls: these must FAIL if a value is tampered with ---------


def test_the_reconciliation_is_actually_sensitive(anchor):
    """A guard against a test that passes because it checks nothing.

    Perturb CTDIw by 1% and confirm the weighted-sum identity breaks.  If this
    ever passes, the reconciliation above is vacuous.
    """
    res = anchor["results"]
    centre = res["ctdi100_pmma_mgy"]["centre"]["value"]
    peripheral = res["ctdi100_peripheral_mean_mgy"]["value"]
    tampered = res["ctdiw_pmma_mgy"]["value"] * 1.01
    assert tampered != pytest.approx(centre / 3 + 2 * peripheral / 3, rel=1e-9)


def test_physics_shape_checks_are_recorded_and_pass(anchor):
    """The CTDI values alone cannot detect a mis-parsed beam; the profile can."""
    checks = anchor["results"].get("beam_geometry_checks")
    if checks is None:
        pytest.skip("results file predates the beam-geometry diagnostics")
    # Surface dose must exceed central dose in a body phantom.
    assert checks["radial_surface_over_centre"] > 1.0
    # The measured longitudinal beam width must match the geometric prediction.
    measured = checks["peripheral_z_profile_fwhm_cm"]
    geometric = checks["geometric_beam_width_at_peripheral_chamber_cm"]
    voxel = anchor["geometry"]["phantom"]["voxel_size_cm"]
    assert measured == pytest.approx(geometric, abs=2 * voxel + 0.2 * geometric)

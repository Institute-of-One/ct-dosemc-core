"""The beam geometry and the absolute normalisation.

The whole chain from ``eV/g per history`` to mGy hangs on the solid angle and the
unit conversion, and neither is visible in the output, so both are checked
against closed form here.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ct_dosemc_core.source_model import (
    EV_PER_G_TO_GY,
    BeamGeometry,
    eV_per_g_to_mGy,
    fan_segments,
    focal_spot_cm,
    histories_for_mas,
    load_bowtie_profile,
    mas_for_histories,
    tube_current_profile,
)


def _beam(**kw) -> BeamGeometry:
    base = dict(sad_cm=60.0, sdd_cm=100.0, collimation_cm=2.0, fan_aperture_deg=34.0)
    base.update(kw)
    return BeamGeometry(**base)


def test_polar_aperture_reproduces_the_nominal_collimation_at_isocentre():
    b = _beam(sad_cm=60.0, collimation_cm=2.0)
    assert b.beam_width_at(60.0) == pytest.approx(2.0)


def test_beam_width_grows_linearly_with_distance():
    b = _beam(sad_cm=60.0, collimation_cm=4.0)
    assert b.beam_width_at(120.0) == pytest.approx(8.0)
    assert b.beam_width_at(30.0) == pytest.approx(2.0)


def test_solid_angle_matches_the_mcgpu_sampling_formula():
    b = _beam()
    theta = math.radians(b.polar_aperture_deg)
    phi = math.radians(b.fan_aperture_deg)
    assert b.solid_angle_sr == pytest.approx(2.0 * math.sin(0.5 * theta) * phi)


def test_solid_angle_matches_the_small_angle_product_of_the_two_apertures():
    # For a narrow beam, Omega -> theta_ap * phi_ap in radians.
    b = _beam(collimation_cm=0.5, fan_aperture_deg=2.0)
    naive = math.radians(b.polar_aperture_deg) * math.radians(b.fan_aperture_deg)
    assert b.solid_angle_sr == pytest.approx(naive, rel=1e-4)


def test_solid_angle_is_linear_in_the_fan_aperture():
    a = _beam(fan_aperture_deg=10.0).solid_angle_sr
    b = _beam(fan_aperture_deg=20.0).solid_angle_sr
    assert b == pytest.approx(2.0 * a)


def test_fan_coverage_is_decided_by_the_geometry_not_by_hope():
    b = _beam(sad_cm=60.0, fan_aperture_deg=32.0)
    # asin(16/60) = 15.47 deg half-angle, so 32 deg covers a 32 cm phantom...
    assert b.covers_radius(16.0)
    # ...but not a 40 cm one.
    assert not b.covers_radius(20.0)
    # and nothing at or beyond the isocentre distance is coverable
    assert not b.covers_radius(60.0)


def test_histories_scale_linearly_with_mas_and_solid_angle():
    b = _beam()
    n1 = histories_for_mas(1.0e9, b, 100.0).value
    n2 = histories_for_mas(1.0e9, b, 200.0).value
    assert n2 == pytest.approx(2.0 * n1)
    wide = _beam(fan_aperture_deg=68.0)
    assert histories_for_mas(1.0e9, wide, 100.0).value == pytest.approx(2.0 * n1, rel=1e-9)


def test_mas_for_histories_inverts_histories_for_mas():
    b = _beam()
    n = histories_for_mas(3.7e9, b, 250.0).value
    assert mas_for_histories(3.7e9, b, n) == pytest.approx(250.0)


def test_ev_per_g_to_gy_is_the_si_definition():
    # 1 eV = 1.602176634e-19 J exactly (SI, 2019); 1/g -> 1000/kg.
    assert pytest.approx(1.602176634e-16, rel=1e-12) == EV_PER_G_TO_GY


def test_ev_per_g_to_mgy_against_a_hand_calculation():
    # 1e-9 eV/g/history over 1e13 histories = 1e4 eV/g
    #   = 1e4 * 1.602176634e-16 Gy = 1.602176634e-12 Gy = 1.602176634e-9 mGy
    got = eV_per_g_to_mGy(1.0e-9, 1.0e13)
    assert got == pytest.approx(1.602176634e-9, rel=1e-9)


def test_tcm_from_pairs_interpolates_and_does_not_invent_beyond_the_range():
    profile = tube_current_profile([(0.0, 100.0), (10.0, 200.0)])
    assert float(profile.current_at_mm(5.0)) == pytest.approx(150.0)
    # clamp, don't extrapolate
    assert float(profile.current_at_mm(-5.0)) == pytest.approx(100.0)
    assert float(profile.current_at_mm(99.0)) == pytest.approx(200.0)
    assert profile.modulated
    w = profile.relative_weight([0.0, 10.0])
    assert float(w[0]) == pytest.approx(100.0 / 150.0)
    assert float(w[1]) == pytest.approx(200.0 / 150.0)


def test_flat_tcm_is_recorded_as_unmodulated_not_missing():
    profile = tube_current_profile([(0.0, 250.0), (10.0, 250.0), (20.0, 250.0)])
    assert not profile.modulated
    assert float(profile.relative_weight(10.0)) == pytest.approx(1.0)


def test_missing_tube_current_is_an_error_not_a_flat_profile():
    with pytest.raises(ValueError, match="I\\(z\\)|tube current"):
        tube_current_profile(object())


def test_focal_spot_sits_inside_a_130cm_box_and_points_at_isocentre():
    pos, direction = focal_spot_cm((130.0, 130.0, 50.0), sad_cm=60.0, gantry_deg=0.0)
    assert pos[0] == pytest.approx(65.0)
    assert pos[1] == pytest.approx(5.0)  # 65 - 60
    assert pos[2] == pytest.approx(25.0)
    # direction toward +y (isocentre)
    assert direction[1] == pytest.approx(1.0, abs=1e-12)
    with pytest.raises(ValueError, match="outside the voxel box"):
        focal_spot_cm((40.0, 40.0, 40.0), sad_cm=60.0)


def test_bowtie_thickness_rises_with_fan_angle_and_siemens_carries_spread():
    ge = load_bowtie_profile("GE", kvp=120)
    assert ge.provenance.startswith("measured")
    assert ge.thickness_mm(0.0) < ge.thickness_mm(10.0)
    assert ge.thickness_mm(-10.0) == pytest.approx(ge.thickness_mm(10.0))  # symmetry
    assert ge.spread_at_mm(0.0) is None
    siemens = load_bowtie_profile("Siemens", kvp=120)
    assert "cross-vendor average" in siemens.provenance
    assert siemens.spread_mm is not None
    assert siemens.spread_at_mm(0.0) is not None


def test_fan_segments_cover_the_fan_and_narrow_polar_aperture_off_axis():
    segs = fan_segments(4, half_fan_deg=25.0, collimation_cm=2.0, sad_cm=60.0)
    assert len(segs) == 4
    assert sum(s.azimuthal_aperture_deg for s in segs) == pytest.approx(50.0)
    centre = [s for s in segs if abs(s.centre_psi_deg) < 10]
    edge = [s for s in segs if abs(s.centre_psi_deg) > 15]
    assert centre[0].polar_aperture_deg > edge[0].polar_aperture_deg

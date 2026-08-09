"""TG-195 Case 4: geometry, the fan decomposition, and the reference reader.

The Monte-Carlo gate itself lives in ``tools/run_tg195.py``; what is checked here
is everything around it that could be wrong without the simulation complaining --
the specification values, the solid angle of the field, and the parsing of the
reference workbook.

The tests that need the AAPM electronic resources skip when they are absent:
those files are copyrighted and are fetched, not committed.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from ct_dosemc_core.phantom import Material
from ct_dosemc_core.tg195 import (
    CASE4,
    CASE4_DISCRETE_PROJECTION_ANGLES_DEG,
    CASE4_FAN_THICKNESSES_CM,
    Case4Spec,
    build_case4_phantom,
    first_test_voi_masks,
    first_test_voi_weights,
    read_case4_reference,
    second_test_voi_masks,
    second_test_voi_weights,
    specified_solid_angle_sr,
    sub_fans,
    write_monoenergetic_spectrum,
)

AIR = Material(1, "air", "air.mcgpu.gz", 1.20479e-3)
PMMA = Material(2, "PMMA", "PMMA.mcgpu.gz", 1.19)

CASE4_RESULTS = Path(__file__).resolve().parent.parent / "data" / "tg195" / "09-Case 4 Results.xlsx"
needs_reference = pytest.mark.skipif(
    not CASE4_RESULTS.is_file(), reason="AAPM TG-195 electronic resources not fetched"
)


# -- the specification ------------------------------------------------------


def test_case4_matches_the_published_specification():
    """Report section 3.4, verbatim: radius 160 mm, 3,000 mm long, SAD 600 mm."""
    assert CASE4.phantom_radius_cm == 16.0
    assert CASE4.phantom_length_cm == 300.0
    assert CASE4.sad_cm == 60.0
    assert CASE4.fan_width_at_isocentre_cm == 32.0
    assert CASE4.second_test_voi_diameter_cm == 1.0
    assert CASE4.second_test_voi_length_cm == 10.0
    assert CASE4.second_test_perimeter_radius_cm == 15.0
    assert CASE4.monoenergetic_kev == 56.4
    assert CASE4_FAN_THICKNESSES_CM == (1.0, 8.0)
    assert len(CASE4_DISCRETE_PROJECTION_ANGLES_DEG) == 36
    assert CASE4_DISCRETE_PROJECTION_ANGLES_DEG[1] == 10.0


def test_the_fan_is_defined_by_a_width_not_by_a_tangent():
    """"width ... equal to the body diameter (320 mm)" measured at the isocentre.

    The field is a rectangle on the isocentre plane, so the half-angle is
    ``atan(160/600)``.  Using ``asin`` -- the angle that would just graze the
    cylinder -- would open the beam by 3.6% in solid angle and dilute every
    per-photon figure.  The specified field genuinely clips the cylinder.
    """
    assert CASE4.half_fan_deg == pytest.approx(math.degrees(math.atan(16.0 / 60.0)))
    grazing = math.degrees(math.asin(16.0 / 60.0))
    assert CASE4.half_fan_deg < grazing


# -- the fan decomposition --------------------------------------------------


def test_a_single_aperture_overshoots_the_specified_solid_angle():
    """The reason sub-fans exist, quantified.

    MC-GPU samples a rectangle in (cos theta, phi), whose z extent at the
    isocentre plane grows as 1/cos(psi) towards the fan edges.  Emitting into
    that larger window dilutes eV-per-photon by the solid-angle ratio -- 1.1%
    here, which is the entire error budget of the test.
    """
    one = sum(f.solid_angle_sr for f in sub_fans(CASE4, 1))
    assert one / specified_solid_angle_sr(CASE4) - 1.0 == pytest.approx(0.0114, abs=5e-4)


@pytest.mark.parametrize("k,tolerance", [(2, 3e-3), (4, 1e-3), (8, 2e-4), (16, 5e-5)])
def test_sub_fans_converge_on_the_specified_solid_angle(k, tolerance):
    total = sum(f.solid_angle_sr for f in sub_fans(CASE4, k))
    assert abs(total / specified_solid_angle_sr(CASE4) - 1.0) < tolerance


def test_sub_fans_tile_the_whole_fan_without_gaps_or_overlap():
    fans = sub_fans(CASE4, 8)
    edges = [f.centre_psi_deg - 0.5 * f.azimuthal_aperture_deg for f in fans]
    edges.append(fans[-1].centre_psi_deg + 0.5 * fans[-1].azimuthal_aperture_deg)
    assert edges[0] == pytest.approx(-CASE4.half_fan_deg)
    assert edges[-1] == pytest.approx(+CASE4.half_fan_deg)
    assert np.allclose(np.diff(edges), fans[0].azimuthal_aperture_deg)


def test_the_polar_aperture_narrows_towards_the_fan_edges():
    """A ray to the fan edge travels SAD/cos(psi), so it needs a smaller angle to
    reach the same physical thickness at the isocentre plane."""
    fans = sub_fans(CASE4, 8)
    centre = min(fans, key=lambda f: abs(f.centre_psi_deg))
    edge = max(fans, key=lambda f: abs(f.centre_psi_deg))
    assert edge.polar_aperture_deg < centre.polar_aperture_deg
    expected = 2.0 * math.degrees(
        math.atan(0.5 * 1.0 * math.cos(math.radians(edge.centre_psi_deg)) / 60.0)
    )
    assert edge.polar_aperture_deg == pytest.approx(expected)


def test_the_specified_field_reproduces_its_own_dimensions_at_the_isocentre():
    """Closed form: Omega = 2 (t/SAD) sin(psi_max)."""
    got = specified_solid_angle_sr(CASE4, thickness_cm=1.0)
    assert got == pytest.approx(
        2.0 * (1.0 / 60.0) * math.sin(math.radians(CASE4.half_fan_deg))
    )


def test_sub_fan_directions_are_unit_vectors_in_the_scan_plane():
    for fan in sub_fans(CASE4, 8):
        ux, uy, uz = fan.direction()
        assert uz == 0.0
        assert math.hypot(ux, uy) == pytest.approx(1.0)


def test_zero_sub_fans_is_an_error():
    with pytest.raises(ValueError, match="at least one"):
        sub_fans(CASE4, 0)


# -- geometry ---------------------------------------------------------------


def test_case4_phantom_mass_matches_the_analytic_cylinder():
    spec = Case4Spec()
    ph = build_case4_phantom(spec, air=AIR, pmma=PMMA, voxel_size_cm=0.25, length_cm=20.0)
    analytic = math.pi * 16.0**2 * 20.0 * spec.pmma_density_g_cm3
    assert ph.mass_g(ph.material == PMMA.index) == pytest.approx(analytic, rel=0.01)


def test_first_test_segments_are_contiguous_10_mm_sections_of_the_whole_disc():
    spec = Case4Spec()
    ph = build_case4_phantom(spec, air=AIR, pmma=PMMA, voxel_size_cm=0.25, length_cm=20.0)
    masks = first_test_voi_masks(ph, spec)
    assert list(masks) == [f"segment_{i}" for i in range(1, 5)]

    stacked = np.stack(list(masks.values()))
    assert stacked.sum(axis=0).max() == 1, "segments overlap"

    for name, mask in masks.items():
        # each is a full disc, 10 mm thick, entirely inside the PMMA
        assert np.all(ph.material[mask] == PMMA.index)
        volume = mask.sum() * ph.voxel_volume_cm3
        assert volume == pytest.approx(math.pi * 16.0**2 * 1.0, rel=0.01), name
        z_extent = (mask.any(axis=(1, 2))).sum() * ph.voxel_size_cm[2]
        assert z_extent == pytest.approx(1.0), name


def test_first_test_segments_start_at_the_scan_plane_and_step_by_10_mm():
    spec = Case4Spec()
    ph = build_case4_phantom(spec, air=AIR, pmma=PMMA, voxel_size_cm=0.25, length_cm=20.0)
    masks = first_test_voi_masks(ph, spec)
    _x, _y, z = ph.axis_coordinates_cm()
    _cx, _cy, cz = ph.centre_cm()
    centres = [float(z[m.any(axis=(1, 2))].mean() - cz) for m in masks.values()]
    assert centres == pytest.approx([0.0, 1.0, 2.0, 3.0], abs=1e-6)


def test_second_test_vois_are_10_mm_cylinders_at_the_axis_and_at_150_mm():
    spec = Case4Spec()
    ph = build_case4_phantom(spec, air=AIR, pmma=PMMA, voxel_size_cm=0.125, length_cm=20.0)
    masks = second_test_voi_masks(ph, spec)
    assert set(masks) == {"center", "perimeter"}

    x, y, _z = ph.axis_coordinates_cm()
    cx, cy, _cz = ph.centre_cm()
    for name, mask in masks.items():
        assert np.all(ph.material[mask] == PMMA.index)
        assert (mask.any(axis=(1, 2))).sum() * ph.voxel_size_cm[2] == pytest.approx(10.0)
        ys, xs = np.nonzero(mask.any(axis=0))
        radius = float(np.hypot(x[xs].mean() - cx, y[ys].mean() - cy))
        assert radius == pytest.approx(0.0 if name == "center" else 15.0, abs=0.1)


def test_second_test_voi_occupancy_reproduces_the_analytic_volume():
    """The mask is every voxel the cylinder touches; the *weights* are the volume.

    This is the fix for the -3.2% G2 result: scoring energy deposited is
    proportional to the selected volume, and a voxel-centre test resolves a 10 mm
    circle on a 2.5 mm grid as 12 voxels against a true 12.57 -- 4.51% short.
    """
    spec = Case4Spec()
    analytic = math.pi * 0.5**2 * 10.0
    for voxel in (0.25, 0.125):
        ph = build_case4_phantom(spec, air=AIR, pmma=PMMA, voxel_size_cm=voxel, length_cm=20.0)
        weights = second_test_voi_weights(ph, spec)
        for name, w in weights.items():
            assert np.all((w >= 0.0) & (w <= 1.0)), name
            volume = float(w.sum()) * ph.voxel_volume_cm3
            assert volume == pytest.approx(analytic, rel=1e-3), (name, voxel)


def test_the_boolean_mask_is_the_set_of_voxels_the_weights_touch():
    spec = Case4Spec()
    ph = build_case4_phantom(spec, air=AIR, pmma=PMMA, voxel_size_cm=0.25, length_cm=20.0)
    weights = second_test_voi_weights(ph, spec)
    masks = second_test_voi_masks(ph, spec)
    for name, w in weights.items():
        np.testing.assert_array_equal(masks[name], w > 0.0)
        # Boundary voxels are only partly inside, so the touched volume exceeds
        # the true one -- which is precisely why the weights exist.
        assert float((w > 0).sum()) > float(w.sum())


def test_first_test_segments_are_not_radially_weighted():
    """The first test's VOI edge IS the phantom edge.

    The phantom was voxelised by a voxel-centre test, so a voxel whose centre is
    inside the cylinder is entirely PMMA and its whole mass really did absorb
    dose. Weighting it down would discard deposited energy at the entrance
    surface, where the dose is highest -- measured at -2.2% on the segment holding
    the primary beam. Only the z boundaries, which sit in bulk PMMA, are weighted.
    """
    spec = Case4Spec()
    ph = build_case4_phantom(spec, air=AIR, pmma=PMMA, voxel_size_cm=0.25, length_cm=20.0)
    weights = first_test_voi_weights(ph, spec)
    pmma_index = max(m.index for m in ph.materials)
    for name, w in weights.items():
        interior = w > 0
        # every weight is either 0 or the z-fraction; no partial radial values
        assert set(np.unique(w[interior]).round(9).tolist()) == {1.0}, name
        assert np.all(ph.material[interior] == pmma_index), name


def test_a_voi_outside_the_tally_roi_is_an_error_not_a_silent_zero():
    spec = Case4Spec()
    ph = build_case4_phantom(spec, air=AIR, pmma=PMMA, voxel_size_cm=0.5, length_cm=20.0)
    with pytest.raises(ValueError, match="outside the dose tally ROI"):
        first_test_voi_masks(ph, spec, roi_origin_zyx=(0, 0, 0), roi_shape_zyx=(2, 2, 2))


def test_the_transverse_air_margin_is_separate_from_the_longitudinal_one():
    """The beam travels in the xy-plane, so only the transverse margin has to be
    large; coupling them turns a 9-million-voxel geometry into a 130-million one."""
    spec = Case4Spec()
    ph = build_case4_phantom(
        spec, air=AIR, pmma=PMMA, voxel_size_cm=0.5, length_cm=20.0,
        air_margin_cm=30.0, air_margin_z_cm=2.0,
    )
    bx, _by, bz = ph.bbox_cm
    assert bx == pytest.approx(2 * 16.0 + 2 * 30.0, abs=0.5)
    assert bz == pytest.approx(20.0 + 2 * 2.0, abs=0.5)


# -- spectra ----------------------------------------------------------------


def test_monoenergetic_spectrum_is_a_single_narrow_terminated_bin(tmp_path):
    path = tmp_path / "mono.spc"
    summary = write_monoenergetic_spectrum(path, 56.4)
    rows = [
        [float(v) for v in line.split()]
        for line in path.read_text(encoding="ascii").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert len(rows) == 2
    assert rows[0][0] == pytest.approx(56400.0)
    assert rows[0][1] == 1.0
    assert rows[1][1] < 0, "MC-GPU needs a negative probability to end the spectrum"
    assert rows[1][0] - rows[0][0] == pytest.approx(summary["bin_width_ev"])
    assert rows[1][0] > rows[0][0], "MC-GPU rejects non-increasing bin energies"


# -- the reference workbook -------------------------------------------------


@needs_reference
def test_reference_reader_returns_all_six_case4_vois():
    ref = read_case4_reference(CASE4_RESULTS, beam="56.4 keV", thickness_cm=1.0)
    assert set(ref) == {f"segment_{i}" for i in range(1, 5)} | {"center", "perimeter"}


@needs_reference
def test_reference_mean_lies_inside_its_own_published_range():
    for beam in ("56.4 keV", "120 kVp"):
        for voi, r in read_case4_reference(CASE4_RESULTS, beam=beam, thickness_cm=1.0).items():
            assert r["min"] <= r["mean"] <= r["max"], (beam, voi)
            assert r["inter_code_spread_fraction"] >= 0.0


@needs_reference
def test_the_first_test_segments_fall_off_with_distance_from_the_beam():
    """Physics sanity on the reference itself: for a 10 mm beam at z=0, energy in
    successive 10 mm sections must decrease.  If this ever fails, the columns of
    the workbook have been read in the wrong order."""
    ref = read_case4_reference(CASE4_RESULTS, beam="56.4 keV", thickness_cm=1.0)
    values = [ref[f"segment_{i}"]["mean"] for i in range(1, 5)]
    assert values == sorted(values, reverse=True)
    assert values[0] > 4 * values[1], "segment 1 holds the primary beam"


@needs_reference
def test_a_thick_fan_flattens_the_longitudinal_falloff():
    """With an 80 mm beam the four 10 mm sections are all inside the primary, so
    the profile is nearly flat -- unlike the 10 mm case."""
    thin = read_case4_reference(CASE4_RESULTS, beam="56.4 keV", thickness_cm=1.0)
    thick = read_case4_reference(CASE4_RESULTS, beam="56.4 keV", thickness_cm=8.0)
    thin_ratio = thin["segment_2"]["mean"] / thin["segment_1"]["mean"]
    thick_ratio = thick["segment_2"]["mean"] / thick["segment_1"]["mean"]
    assert thin_ratio < 0.3 < 0.9 < thick_ratio


@needs_reference
def test_the_perimeter_voi_receives_more_than_the_central_one():
    """A rotating source deposits more at 150 mm radius than on the axis."""
    for beam in ("56.4 keV", "120 kVp"):
        ref = read_case4_reference(CASE4_RESULTS, beam=beam, thickness_cm=1.0)
        assert ref["perimeter"]["mean"] > 2.0 * ref["center"]["mean"]


@needs_reference
def test_an_unknown_beam_or_thickness_is_refused():
    with pytest.raises(KeyError, match="no Case 4 column"):
        read_case4_reference(CASE4_RESULTS, beam="80 kVp", thickness_cm=1.0)
    with pytest.raises(KeyError, match="no Case 4 column"):
        read_case4_reference(CASE4_RESULTS, beam="120 kVp", thickness_cm=4.0)

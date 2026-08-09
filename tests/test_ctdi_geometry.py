"""The CTDI phantom must be the phantom the standard describes.

Geometry errors are the quietest way to get a plausible-looking wrong dose, so
the analytic properties of the voxelised phantom are checked against closed form
rather than against a stored expectation.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ct_dosemc_core.ctdi import (
    CHAMBER_POSITIONS,
    CtdiPhantomSpec,
    build_ctdi_phantom,
    chamber_masks,
    chamber_weights,
)
from ct_dosemc_core.phantom import Material

AIR = Material(1, "air", "air.mcgpu.gz", 1.20479e-3)
PMMA = Material(2, "PMMA", "PMMA.mcgpu.gz", 1.19)


def _phantom(**kw):
    spec = CtdiPhantomSpec(**kw)
    return spec, build_ctdi_phantom(spec, air=AIR, pmma=PMMA)


@pytest.mark.parametrize("diameter", [16.0, 32.0])
def test_pmma_mass_matches_the_analytic_cylinder(diameter):
    spec, ph = _phantom(diameter_cm=diameter, voxel_size_cm=0.2)
    analytic = math.pi * spec.radius_cm**2 * spec.length_cm * spec.pmma_density_g_cm3
    voxelised = ph.mass_g(ph.material == PMMA.index)
    # A centre-in-voxel test stair-steps the curved surface; at 2 mm voxels on a
    # 16-32 cm cylinder the error is well under a percent in either direction.
    assert voxelised == pytest.approx(analytic, rel=0.01)


def test_phantom_is_air_outside_and_pmma_inside():
    spec, ph = _phantom(diameter_cm=32.0, voxel_size_cm=0.5)
    nz, ny, nx = ph.shape_zyx
    # corner of the bounding box: air, at air density
    assert ph.material[0, 0, 0] == AIR.index
    assert ph.density[0, 0, 0] == pytest.approx(spec.air_density_g_cm3)
    # dead centre: PMMA
    assert ph.material[nz // 2, ny // 2, nx // 2] == PMMA.index
    assert ph.density[nz // 2, ny // 2, nx // 2] == pytest.approx(spec.pmma_density_g_cm3)
    # only the two declared materials appear
    assert set(np.unique(ph.material)) == {AIR.index, PMMA.index}


def test_phantom_extends_only_over_its_stated_length():
    spec, ph = _phantom(diameter_cm=32.0, voxel_size_cm=0.25, air_margin_cm=2.0)
    per_slice = (ph.material == PMMA.index).sum(axis=(1, 2))
    occupied = float((per_slice > 0).sum()) * ph.voxel_size_cm[2]
    assert occupied == pytest.approx(spec.length_cm, abs=2 * ph.voxel_size_cm[2])


def test_chambers_sit_at_the_standard_positions():
    spec, ph = _phantom(diameter_cm=32.0, voxel_size_cm=0.25)
    masks = chamber_masks(ph, spec)
    assert set(masks) == set(CHAMBER_POSITIONS)

    x, y, _z = ph.axis_coordinates_cm()
    cx, cy, _cz = ph.centre_cm()
    for name, mask in masks.items():
        ys, xs = np.nonzero(mask.any(axis=0))
        radius = float(np.hypot(x[xs].mean() - cx, y[ys].mean() - cy))
        expected = 0.0 if name == "centre" else spec.peripheral_radius_cm
        assert radius == pytest.approx(expected, abs=0.5 * ph.voxel_size_cm[0])
        # every chamber must lie inside the PMMA
        assert np.all(ph.material[mask] == PMMA.index)


def test_chambers_do_not_overlap():
    spec, ph = _phantom(diameter_cm=32.0, voxel_size_cm=0.2)
    masks = chamber_masks(ph, spec)
    stacked = np.stack(list(masks.values()))
    assert stacked.sum(axis=0).max() == 1, "chamber regions overlap"


def test_chamber_occupancy_reproduces_the_analytic_volume():
    """A voxel-centre test overstates a 13.1 mm chamber on a 2.5 mm grid by 11.3%.

    CTDI100 uses a *mean* dose, so a volume error does not scale the result the
    way it does for energy scoring, but it inflates the effective chamber radius
    and moves the mean inside the steep radial gradient at the peripheral
    positions. The occupancy weights are the volume; the boolean mask is only the
    set of voxels the chamber touches.
    """
    analytic = math.pi * (0.5 * 1.31) ** 2 * 10.0
    for voxel in (0.25, 0.125):
        spec, ph = _phantom(diameter_cm=32.0, voxel_size_cm=voxel)
        weights = chamber_weights(ph, spec)
        for name, w in weights.items():
            assert np.all((w >= 0.0) & (w <= 1.0)), name
            volume = float(w.sum()) * ph.voxel_volume_cm3
            assert volume == pytest.approx(analytic, rel=1e-3), (name, voxel)
            assert float((w > 0).sum()) > float(w.sum()), name


def test_chamber_masks_crop_to_the_tally_roi():
    spec, ph = _phantom(diameter_cm=32.0, voxel_size_cm=0.5)
    nz, ny, nx = ph.shape_zyx
    origin = (2, 3, 4)
    shape = (nz - 4, ny - 6, nx - 8)
    masks = chamber_masks(ph, spec, roi_origin_zyx=origin, roi_shape_zyx=shape)
    for mask in masks.values():
        assert mask.shape == shape


def test_a_chamber_outside_the_roi_is_an_error_not_a_silent_zero():
    spec, ph = _phantom(diameter_cm=32.0, voxel_size_cm=0.5)
    with pytest.raises(ValueError, match="outside the dose tally ROI"):
        chamber_masks(ph, spec, roi_origin_zyx=(0, 0, 0), roi_shape_zyx=(4, 4, 4))


def test_peripheral_chamber_must_fit_inside_the_phantom():
    with pytest.raises(ValueError, match="inside the phantom"):
        CtdiPhantomSpec(diameter_cm=16.0, chamber_depth_cm=9.0)


def test_chamber_longer_than_the_phantom_is_rejected():
    with pytest.raises(ValueError, match="does not fit"):
        CtdiPhantomSpec(length_cm=5.0, chamber_length_cm=10.0)

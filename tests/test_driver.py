"""Patient-driver wiring: bbox ROI dose reduction, no MC-GPU run."""

from __future__ import annotations

import numpy as np
import pytest

from ct_dosemc_core.driver import crop_to_roi, organ_doses_from_roi, roi_to_slices
from ct_dosemc_core.mcgpu_io import DoseMap
from ct_dosemc_core.patient import union_organ_roi


def _tally(shape, origin, value=1.0):
    dose = np.full(shape, value, dtype=float)
    sigma = np.full(shape, 0.01 * value, dtype=float)
    return DoseMap(
        dose_ev_per_g=dose,
        sigma_ev_per_g=sigma,
        roi_origin_zyx=origin,
        voxel_size_cm=(0.25, 0.25, 0.25),
    )


def test_organ_doses_crop_masks_to_the_bbox_roi():
    density = np.ones((10, 10, 10), dtype=float)
    liver = np.zeros((10, 10, 10), dtype=bool)
    spleen = np.zeros((10, 10, 10), dtype=bool)
    liver[2:5, 2:5, 2:5] = True
    spleen[6:8, 6:8, 6:8] = True
    roi = union_organ_roi({"liver": liver, "spleen": spleen}, pad_voxels=0)
    zs, ys, xs = roi_to_slices(roi)
    origin = (zs.start, ys.start, xs.start)
    shape = (zs.stop - zs.start, ys.stop - ys.start, xs.stop - xs.start)
    tally = _tally(shape, origin, value=2.0)
    doses = organ_doses_from_roi(tally, density, {"liver": liver, "spleen": spleen}, n_histories=1.0, roi=roi)
    assert set(doses) == {"liver", "spleen"}
    assert doses["liver"].n_voxels == 27
    assert doses["spleen"].n_voxels == 8
    # same per-voxel dose → same organ dose (mass-weighted mean)
    assert doses["liver"].dose_mgy == pytest.approx(doses["spleen"].dose_mgy)


def test_organ_doses_refuse_a_mismatched_roi_origin():
    density = np.ones((6, 6, 6))
    mask = np.zeros((6, 6, 6), dtype=bool)
    mask[1:3, 1:3, 1:3] = True
    roi = union_organ_roi({"o": mask}, pad_voxels=0)
    tally = _tally((2, 2, 2), origin=(0, 0, 0), value=1.0)
    with pytest.raises(ValueError, match="does not match"):
        organ_doses_from_roi(tally, density, {"o": mask}, n_histories=1.0, roi=roi)


def test_crop_to_roi_is_1based_inclusive():
    vol = np.arange(27).reshape(3, 3, 3)
    cropped = crop_to_roi(vol, ((2, 3), (1, 2), (1, 1)))  # x[1:3], y[0:2], z[0:1]
    assert cropped.shape == (1, 2, 2)
    assert cropped[0, 0, 0] == vol[0, 0, 1]

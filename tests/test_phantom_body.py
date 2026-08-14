"""The body-contour mask and the patient density map (IORN-007 D4 structural fix).

A CT reconstruction fills everything outside the field of view with a padding value --
-2048 HU on the Canon/Toshiba series in this cohort, with no DICOM padding tag to
declare it. That region is not a material; it is nothing. These tests pin the fix that
turns it into air explicitly (rather than trusting a density clamp to land near air by
luck) and that reports, rather than silently clamps, an in-body voxel above the tissue
calibration -- the metal case that would otherwise be mapped to cortical-bone density
and shield the organ behind it.
"""

from __future__ import annotations

import numpy as np

from ct_dosemc_core.phantom import (
    _SCHNEIDER_DENSITY_G_CM3,
    body_contour,
    hu_to_density,
    patient_density_map,
)

AIR = float(min(_SCHNEIDER_DENSITY_G_CM3))


def _phantom() -> np.ndarray:
    """A (z,y,x) volume: -2048 background, a central soft-tissue block with an internal
    air pocket and one metal voxel, plus a detached couch speckle to be dropped."""
    vol = np.full((6, 40, 40), -2048.0, dtype=float)
    vol[:, 10:30, 10:30] = 0.0        # patient: soft tissue at 0 HU
    vol[:, 18:22, 18:22] = -1000.0    # internal air/lung pocket, fully enclosed
    vol[2:4, 15, 15] = 5000.0         # metal implant, above the Schneider calibration
    vol[:, 0:3, 0:3] = 100.0          # detached couch/speckle, a smaller component
    return vol


def test_body_contour_excludes_background_and_couch() -> None:
    vol = _phantom()
    body = body_contour(vol)
    assert body[:, 20, 20].all()      # inside the patient block
    assert not body[:, 5, 5].any()    # -2048 background
    assert not body[:, 1, 1].any()    # detached couch speckle dropped (smaller component)


def test_body_contour_fills_internal_air_pocket() -> None:
    vol = _phantom()
    body = body_contour(vol)
    # The -1000 HU pocket is below threshold but enclosed, so hole-fill keeps it inside.
    assert body[:, 19, 19].all()


def test_patient_density_map_air_outside_tissue_inside() -> None:
    vol = _phantom()
    density, body, report = patient_density_map(vol)
    assert density.shape == vol.shape
    assert np.all(density > 0.0)
    # background is air, exactly the calibration air density, not a lucky clamp
    assert density[0, 5, 5] == AIR
    assert not body[0, 5, 5]
    # soft tissue at 0 HU maps to ~1.03 g/cm^3 inside the body
    assert density[0, 25, 25] == float(hu_to_density(np.array([0.0]))[0])
    assert body[0, 25, 25]


def test_patient_density_map_reports_metal_not_clamps_silently() -> None:
    vol = _phantom()
    density, body, report = patient_density_map(vol)
    assert report["n_above_calibration_in_body"] == 2  # two metal voxels, both in-body
    assert report["max_hu_in_body"] == 5000.0
    # it is held at the top calibration density (reported), never dropped
    assert density[2, 15, 15] == float(max(_SCHNEIDER_DENSITY_G_CM3))
    assert 0.0 < report["body_fraction"] < 1.0

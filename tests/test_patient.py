"""Unit tests for the Phase-2 patient driver front end (geometry + materials).

These exercise the two things settled in ``ct_dosemc_core.patient``: the Schneider
composition-group assignment (bone must not fall in with soft tissue) and the 2.5 mm
isotropic geometry. No MC-GPU run happens here.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ct_dosemc_core.patient import (
    DOSE_GRID_MM,
    assign_material_index,
    axial_station_z_cm,
    bone_bin_volume_fraction,
    bone_discretization_error,
    bone_volume_fraction,
    build_patient_phantom,
    default_tissue_groups,
    material_energy_tag,
    embed_in_focal_box,
    mix_by_volume_fraction,
    organ_bounding_box,
    pad_mask,
    resample_isotropic,
    tissue_group_materials,
    union_organ_roi,
)
from ct_dosemc_core.phantom import MCGPU_MAX_MATERIALS


def test_default_group_table_fits_max_materials():
    groups = default_tissue_groups()
    assert groups[0].name == "air"
    assert len(groups) == 15  # 4 soft + 11 bone fills MAX_MATERIALS
    assert len(groups) <= MCGPU_MAX_MATERIALS
    lows = [g.hu_low for g in groups]
    assert lows == sorted(lows)
    assert sum(g.is_bone for g in groups) == 11
    # low-f bins are narrower than equal-HU would be
    bone_lows = [g.hu_low for g in groups if g.is_bone] + [3000.0]
    first = bone_lows[1] - bone_lows[0]
    last = bone_lows[-1] - bone_lows[-2]
    assert first < last
    equal = (3000.0 - 100.0) / 11
    assert first < equal < last


def test_group_table_refuses_to_exceed_max_materials():
    with pytest.raises(ValueError, match="MAX_MATERIALS"):
        default_tissue_groups(n_bone_bins=MCGPU_MAX_MATERIALS)  # 4 + 15 > 15


def test_materials_are_one_based_and_ordered():
    mats = tissue_group_materials(default_tissue_groups())
    assert [m.index for m in mats] == list(range(1, len(mats) + 1))
    assert mats[0].name == "air"


def test_bone_is_not_merged_with_soft_tissue():
    groups = default_tissue_groups()
    hu = np.array([-1000.0, -500.0, -100.0, 40.0, 400.0, 1500.0, 5000.0])
    body = np.ones_like(hu, dtype=bool)
    idx = assign_material_index(hu, body, groups)
    names = [groups[i - 1].name for i in idx]
    assert names[0] == "air"  # in-body gas
    assert names[1] == "lung"
    assert names[2] == "adipose"
    assert names[3] == "soft_tissue"
    # the bone HU values land in *bone* groups, never in soft
    assert groups[idx[4] - 1].is_bone
    assert groups[idx[5] - 1].is_bone
    # above the top calibration edge is clamped into the top (cortical) group
    assert idx[6] == len(groups)


def test_outside_body_is_air():
    groups = default_tissue_groups()
    hu = np.array([40.0, 1500.0])  # soft and bone HU...
    body = np.array([False, False])  # ...but both outside the contour
    idx = assign_material_index(hu, body, groups)
    assert list(idx) == [1, 1]  # forced to air


def test_resample_isotropic_lands_on_the_dose_grid():
    # anisotropic native voxel: 3 mm slices, 0.5 mm in-plane
    vol = np.zeros((10, 40, 40), dtype=np.float32)
    out = resample_isotropic(vol, (3.0, 0.5, 0.5), iso_mm=2.5, order=1)
    # z upsamples (3/2.5=1.2 -> 12), x/y downsample (0.5/2.5=0.2 -> 8)
    assert out.shape == (12, 8, 8)


def _synthetic_patient() -> tuple[np.ndarray, tuple[float, float, float]]:
    # air background, a soft-tissue block, a bony core inside it
    hu = np.full((16, 60, 60), -1000.0, dtype=np.float32)
    hu[3:13, 10:50, 10:50] = 40.0  # soft tissue body
    hu[6:10, 25:35, 25:35] = 1200.0  # bone
    return hu, (3.0, 0.7, 0.7)


def test_build_patient_phantom_geometry_and_materials():
    hu, spacing = _synthetic_patient()
    phantom, report = build_patient_phantom(hu, spacing, iso_mm=2.5, focal_box_xy_cm=None)
    assert phantom.voxel_size_cm == (0.25, 0.25, 0.25)
    assert len(phantom.materials) == 15
    assert phantom.material.min() >= 1
    assert phantom.material.max() <= 15
    assert np.all(phantom.density > 0.0)  # MC-GPU rejects zero density
    assert report["iso_grid_mm"] == DOSE_GRID_MM
    assert report["n_body_voxels"] > 0
    # a bone material is actually present somewhere in the resampled body
    bone_indices = {i + 1 for i, g in enumerate(phantom.materials) if g.name.startswith("bone")}
    assert bone_indices & set(np.unique(phantom.material).tolist())


def test_build_patient_phantom_air_outside_body():
    hu, spacing = _synthetic_patient()
    phantom, _ = build_patient_phantom(hu, spacing, iso_mm=2.5, focal_box_xy_cm=None)
    # corner voxel is outside the body -> air material and near-air density
    assert phantom.material[0, 0, 0] == 1
    assert phantom.density[0, 0, 0] < 0.01


def test_organ_bounding_box_is_one_based_inclusive_and_clamped():
    mask = np.zeros((10, 10, 10), dtype=bool)
    mask[2:5, 3:6, 4:7] = True
    (x0, x1), (y0, y1), (z0, z1) = organ_bounding_box(mask, pad_voxels=1)
    # 0-based extent x[4,6] -> +1 pad -> [3,7]; 1-based inclusive -> [4,8]
    assert (x0, x1) == (4, 8)
    assert (y0, y1) == (3, 7)
    assert (z0, z1) == (2, 6)
    # a mask touching the edge is clamped, not pushed past the volume
    edge = np.zeros((5, 5, 5), dtype=bool)
    edge[0, 0, 0] = True
    (bx0, bx1), _, _ = organ_bounding_box(edge, pad_voxels=2)
    assert bx0 == 1


def test_organ_bounding_box_rejects_empty_mask():
    with pytest.raises(ValueError, match="empty mask"):
        organ_bounding_box(np.zeros((4, 4, 4), dtype=bool))


def test_material_energy_tag_follows_the_spectrum_max():
    assert material_energy_tag(100) == "5-120keV"
    assert material_energy_tag(120) == "5-120keV"
    assert material_energy_tag(140) == "5-150keV"


def test_default_groups_reference_generated_material_files():
    """Every group's material file must be pinned in materials/PROVENANCE.json.

    Skipped where the material set has not been generated (a machine without the
    generator), so the check catches a group/table drift without demanding the
    ~MB of binary material files on every checkout.
    """
    prov = Path(__file__).resolve().parents[1] / "materials" / "PROVENANCE.json"
    if not prov.is_file():
        pytest.skip("materials not generated on this machine")
    pinned = {m["file"] for m in json.loads(prov.read_text(encoding="utf-8"))["materials"]}
    missing = [g.material_file for g in default_tissue_groups() if g.material_file not in pinned]
    assert not missing, f"group table references unpinned material files: {missing}"


def test_volume_fraction_not_weight_fraction_at_the_midpoint():
    # The numbers in the correction: f=0.5, ρ_soft=1.03, ρ_bone=1.92 → w=0.651
    dummy = [(1, 1.0)]
    _frac, rho_mix, w_bone = mix_by_volume_fraction(dummy, dummy, 0.5, 1.03, 1.92)
    assert rho_mix == pytest.approx(0.5 * 1.03 + 0.5 * 1.92)
    assert w_bone == pytest.approx(0.5 * 1.92 / rho_mix)
    assert w_bone == pytest.approx(0.651, abs=5e-4)
    assert w_bone != pytest.approx(0.5)  # the bug this test exists to forbid


def test_volume_fraction_is_linear_in_hu():
    f = bone_volume_fraction(np.array([100.0, 1550.0, 3000.0]))
    assert list(np.round(f, 5)) == [0.0, 0.5, 1.0]


def test_binned_volume_fraction_is_the_bin_midpoint():
    # √f spacing, 11 bins: first bin f in [0, 1/121], midpoint f = 1/(2*121)
    f = float(bone_bin_volume_fraction(110.0, n_bins=11))
    assert f == pytest.approx(0.5 / 11**2)


def test_sqrt_f_spacing_beats_equal_hu_at_the_soft_boundary():
    soft = [(1, 0.10), (6, 0.20), (8, 0.70)]
    bone = [(1, 0.04), (8, 0.43), (20, 0.53)]
    err_eq = bone_discretization_error(soft, bone, 1.03, 1.92, n_bins=11, power=1.0, n_samples=291)
    err_sq = bone_discretization_error(soft, bone, 1.03, 1.92, n_bins=11, power=2.0, n_samples=291)
    assert err_sq["max_relative_error"] < err_eq["max_relative_error"]
    assert np.isfinite(err_sq["max_relative_error"])


def test_mix_elemental_weights_follow_the_mass_fraction():
    soft = [(1, 0.1), (8, 0.9)]
    bone = [(1, 0.04), (20, 0.96)]
    frac, _rho, w = mix_by_volume_fraction(soft, bone, 0.5, 1.03, 1.92)
    by_z = dict(frac)
    assert by_z[1] == pytest.approx((1 - w) * 0.1 + w * 0.04)
    assert by_z[8] == pytest.approx((1 - w) * 0.9)
    assert by_z[20] == pytest.approx(w * 0.96)


def test_more_bins_beat_one_bin():
    # Magnitude is reported, not gated -- this only insists the measurement runs
    # and that 11 √f bins beat a single bin.
    soft = [(1, 0.10), (6, 0.20), (8, 0.70)]
    bone = [(1, 0.04), (8, 0.43), (20, 0.53)]
    err11 = bone_discretization_error(soft, bone, 1.03, 1.92, n_bins=11, n_samples=291)
    err1 = bone_discretization_error(soft, bone, 1.03, 1.92, n_bins=1, n_samples=291)
    assert err11["max_relative_error"] < err1["max_relative_error"]
    assert err11["max_relative_error"] > 0.0
    assert np.isfinite(err11["max_relative_error"])


def test_embed_in_focal_box_pads_xy_with_air_and_keeps_z():
    hu, spacing = _synthetic_patient()
    inner, _ = build_patient_phantom(hu, spacing, iso_mm=2.5, focal_box_xy_cm=None)
    padded, pad = embed_in_focal_box(inner, xy_cm=20.0)  # 80 voxels at 0.25 cm
    assert padded.shape_zyx[0] == inner.shape_zyx[0]  # z unchanged
    assert padded.n_voxels[0] == 80  # nx
    assert padded.n_voxels[1] == 80  # ny
    assert padded.material[0, 0, 0] == 1  # air in the pad
    # a mask on the inner grid lands on the body after pad_mask
    mask = np.zeros(inner.shape_zyx, dtype=bool)
    mask[inner.shape_zyx[0] // 2, inner.shape_zyx[1] // 2, inner.shape_zyx[2] // 2] = True
    shifted = pad_mask(mask, pad, padded.shape_zyx)
    assert int(shifted.sum()) == 1
    nz, ny, nx = inner.shape_zyx
    z0, y0, x0 = pad
    assert shifted[z0 + nz // 2, y0 + ny // 2, x0 + nx // 2]


def test_union_organ_roi_covers_every_organ():
    a = np.zeros((8, 8, 8), dtype=bool)
    b = np.zeros((8, 8, 8), dtype=bool)
    a[2:4, 2:4, 2:4] = True
    b[5:7, 5:7, 5:7] = True
    (x0, x1), (y0, y1), (z0, z1) = union_organ_roi({"a": a, "b": b}, pad_voxels=0)
    # 0-based x[2,6] → 1-based [3,7]
    assert (x0, x1) == (3, 7)
    assert (y0, y1) == (3, 7)
    assert (z0, z1) == (3, 7)


def test_axial_stations_cover_a_27cm_series_at_2cm_collimation():
    z = axial_station_z_cm(27.75, 2.0)
    assert z.size == 14
    assert z[0] > 0.0
    assert z[-1] < 27.75
    np.testing.assert_allclose(np.diff(z), 27.75 / 14)


def test_a_short_phantom_is_one_station():
    z = axial_station_z_cm(1.5, 2.0)
    assert z.size == 1
    assert z[0] == pytest.approx(0.75)

"""D3 tests: the mask-on-native-grid invariant, and the geometry it rests on.

The dangerous D3 failure is a mask that comes back on a *different* grid than the CT it
was run on -- the segmenter resampled to its own 1.5 mm isotropic lattice, say -- so
mask voxel no longer equals image voxel. For a Monte-Carlo organ dose that silently
pairs each organ with the density and deposited energy of the wrong voxels. IORN-006
turned this into an assertion; these tests turn it into a check that runs in CI, plus
the affine and grid it depends on. None of this needs TotalSegmentator, torch or
nibabel: the invariant is a pure shape comparison and the geometry is pure DICOM.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from ct_dosemc_core.ct_series import load_series, series_geometry
from ct_dosemc_core.grid import NonUniformGrid, resolve_grid
from ct_dosemc_core.segment import SegmentationUnavailable, assert_voxel_correspondence, dicom_affine
from ct_dosemc_core.volume import load_volume_hu


# --- the invariant: masks must sit on the native DICOM grid ---------------------------


def test_voxel_correspondence_holds_for_identical_shape() -> None:
    assert_voxel_correspondence((160, 512, 512), (160, 512, 512)) is None  # no raise


def test_voxel_correspondence_fails_on_resample() -> None:
    with pytest.raises(SegmentationUnavailable) as exc:
        assert_voxel_correspondence((341, 341, 160), (160, 512, 512), name="liver.nii.gz")
    msg = str(exc.value)
    assert "liver.nii.gz" in msg
    assert "voxel correspondence cannot be assumed" in msg


def test_voxel_correspondence_fails_on_transposed_axes() -> None:
    # A (z,y,x) volume whose mask returns (x,y,z) has the same voxel count but is not
    # the same grid; a shape check catches it, a voxel-count check would not.
    with pytest.raises(SegmentationUnavailable):
        assert_voxel_correspondence((512, 512, 160), (160, 512, 512))


# --- the affine the invariant rests on ------------------------------------------------


def test_dicom_affine_lps_to_ras_and_spacing() -> None:
    affine = dicom_affine(
        orientation=(1, 0, 0, 0, 1, 0),
        origin=(10.0, 20.0, 30.0),
        pixel_spacing_mm=(0.7, 0.8),  # (row dy, col dx)
        slice_direction=(0, 0, 1),
        slice_spacing_mm=2.5,
    )
    assert affine[0, 0] == pytest.approx(-0.8)  # column spacing, x sign-flipped LPS->RAS
    assert affine[1, 1] == pytest.approx(-0.7)  # row spacing, y sign-flipped
    assert affine[2, 2] == pytest.approx(2.5)   # slice spacing along +z
    assert affine[0, 3] == pytest.approx(-10.0)
    assert affine[1, 3] == pytest.approx(-20.0)
    assert affine[2, 3] == pytest.approx(30.0)


# --- the grid it is built on ----------------------------------------------------------


def test_resolve_grid_drops_duplicate_positions() -> None:
    grid = resolve_grid([0.0, 2.0, 2.0, 4.0, 6.0])
    assert len(grid.keep) == 4
    assert grid.spacing_mm == pytest.approx(2.0)
    assert grid.n_duplicates == 1
    assert any("repeat" in w for w in grid.warnings)


def test_resolve_grid_rejects_flattened_z() -> None:
    # De-identification that flattens Image Position (Patient) to one value leaves no
    # longitudinal axis at all: the volume, extents and I(z) weighting are unrecoverable.
    with pytest.raises(NonUniformGrid):
        resolve_grid([5.0, 5.0, 5.0])


# --- the whole D3 load chain on a synthesised series ----------------------------------


def _write_ct_slice(
    path: Path, *, series_uid: str, z: float, rows: int = 8, cols: int = 8,
    row_spacing: float = 0.7, col_spacing: float = 0.8, thickness: float = 2.0, fill: int = 0,
) -> None:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = series_uid
    ds.Modality = "CT"
    ds.Manufacturer = "TEST"
    ds.KVP = 120.0
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [0.0, 0.0, float(z)]
    ds.PixelSpacing = [row_spacing, col_spacing]
    ds.SliceThickness = thickness
    ds.Rows = rows
    ds.Columns = cols
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.RescaleSlope = 1
    ds.RescaleIntercept = 0
    ds.PixelData = np.full((rows, cols), fill, dtype=np.int16).tobytes()
    try:
        ds.save_as(str(path), enforce_file_format=True)  # pydicom >= 3.0
    except TypeError:
        ds.save_as(str(path), write_like_original=False)  # pydicom < 3.0


def _make_series(directory: Path, z_positions: list[float], series_uid: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for i, z in enumerate(z_positions):
        # no ".dcm" extension, exactly as TCIA delivers
        _write_ct_slice(directory / f"instance_{i:03d}", series_uid=series_uid, z=z, fill=50)


def test_load_series_orders_and_resolves_grid(tmp_path: Path) -> None:
    uid = "1.2.3.999"
    _make_series(tmp_path / "series", [0.0, 2.0, 4.0, 6.0], uid)
    series = load_series(tmp_path / "series", series_uid=uid)
    assert series.n_slices == 4
    assert series.grid.spacing_mm == pytest.approx(2.0)
    assert series.pixel_spacing_mm == (0.7, 0.8)
    assert series.kvp == pytest.approx(120.0)


def test_load_chain_produces_matching_volume_and_affine(tmp_path: Path) -> None:
    """The full D3 chain: the HU volume shape and the affine agree, so a mask on that
    affine's grid satisfies :func:`assert_voxel_correspondence` by construction."""
    uid = "1.2.3.1000"
    _make_series(tmp_path / "series", [0.0, 2.0, 4.0, 6.0, 8.0], uid)
    series = load_series(tmp_path / "series", series_uid=uid)
    volume, notes = load_volume_hu(series)
    affine, spacing = series_geometry(series)

    assert volume.shape == (5, 8, 8)            # (z, y, x)
    assert spacing == pytest.approx((2.0, 0.7, 0.8))
    assert affine[2, 2] == pytest.approx(2.0)   # +z slice direction, resolved spacing
    # A mask returned on this same grid must pass; anything resampled must not.
    assert_voxel_correspondence(volume.shape, volume.shape)
    with pytest.raises(SegmentationUnavailable):
        assert_voxel_correspondence((volume.shape[0] + 1, *volume.shape[1:]), volume.shape)

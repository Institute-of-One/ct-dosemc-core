"""Load a downloaded DICOM series onto the grid the Monte Carlo will run on.

This is the self-contained loader IORN-007 uses instead of ``ctdose_core.io``: it
reads a series directory, resolves the true slice grid (:mod:`ct_dosemc_core.grid`),
canonicalises the slice order so index 0 is the most inferior slice, and builds the
NIfTI affine from the DICOM patient coordinates. The Hounsfield volume comes from
:func:`ct_dosemc_core.volume.load_volume_hu`, which applies the pixel-padding rule.

Nothing here assumes a file extension: TCIA series arrive as bare DICOM files with no
``.dcm`` suffix, so every entry is probed and the non-DICOM ones are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pydicom

from .grid import SliceGrid, resolve_grid
from .segment import dicom_affine

#: CT image SOP classes; a series directory can also hold a dose report or a secondary
#: capture, which carry no ``ImagePositionPatient`` and must not enter the stack.
_CT_IMAGE_SOP = {
    "1.2.840.10008.5.1.4.1.1.2",  # CT Image Storage
    "1.2.840.10008.5.1.4.1.1.2.1",  # Enhanced CT Image Storage
}


@dataclass
class LoadedSeries:
    """One series on a single resolved grid, ordered inferior -> superior."""

    series_uid: str
    files: list[Path]
    pixel_spacing_mm: tuple[float, float]  # (row spacing dy, column spacing dx)
    slice_thickness_mm: float | None
    manufacturer: str
    model_name: str
    kvp: float | None
    grid: SliceGrid

    @property
    def n_slices(self) -> int:
        return len(self.files)


def _z_of(ds: pydicom.Dataset) -> float | None:
    ipp = getattr(ds, "ImagePositionPatient", None)
    if ipp is None or len(ipp) < 3:
        return None
    try:
        return float(ipp[2])
    except (TypeError, ValueError):
        return None


def _candidate_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.iterdir() if p.is_file())


def load_series(directory: Path | str, series_uid: str | None = None) -> LoadedSeries:
    """Load the series in ``directory`` onto one regular, feet-first slice grid.

    Args:
        directory: a folder of DICOM instances (bare files, no extension assumed).
        series_uid: if given, only instances with this Series Instance UID are used;
            a directory holding one series can leave it ``None``.

    Raises:
        ValueError: if the directory holds no readable CT image with a slice position.
        ct_dosemc_core.grid.NonUniformGrid: if the surviving slices are not on one grid.
    """
    directory = Path(directory)
    headers: list[tuple[Path, float]] = []
    first_ds: pydicom.Dataset | None = None
    for path in _candidate_files(directory):
        try:
            ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        except Exception:
            continue
        sop = str(getattr(ds, "SOPClassUID", "") or "")
        if sop and sop not in _CT_IMAGE_SOP:
            continue
        if series_uid and str(getattr(ds, "SeriesInstanceUID", "")) != series_uid:
            continue
        z = _z_of(ds)
        if z is None:
            continue
        headers.append((path, z))
        if first_ds is None:
            first_ds = ds

    if not headers or first_ds is None:
        raise ValueError(
            f"{directory}: no readable CT image with an ImagePositionPatient was found"
        )

    files_in_z_file_order = [p for p, _ in headers]
    z_positions = np.asarray([z for _, z in headers], dtype=float)
    thickness = None
    if getattr(first_ds, "SliceThickness", None) not in (None, ""):
        try:
            thickness = float(first_ds.SliceThickness)
        except (TypeError, ValueError):
            thickness = None

    grid = resolve_grid(z_positions, fallback_spacing_mm=thickness)
    ordered = [files_in_z_file_order[i] for i in grid.keep]

    ps = getattr(first_ds, "PixelSpacing", None)
    pixel_spacing = (float(ps[0]), float(ps[1])) if ps is not None else (1.0, 1.0)
    kvp = None
    if getattr(first_ds, "KVP", None) not in (None, ""):
        try:
            kvp = float(first_ds.KVP)
        except (TypeError, ValueError):
            kvp = None

    return LoadedSeries(
        series_uid=series_uid or str(getattr(first_ds, "SeriesInstanceUID", "")),
        files=ordered,
        pixel_spacing_mm=pixel_spacing,
        slice_thickness_mm=thickness,
        manufacturer=str(getattr(first_ds, "Manufacturer", "") or ""),
        model_name=str(getattr(first_ds, "ManufacturerModelName", "") or ""),
        kvp=kvp,
        grid=grid,
    )


def series_geometry(series: LoadedSeries) -> tuple[np.ndarray, tuple[float, float, float]]:
    """The NIfTI affine for a loaded series, and its voxel spacing in ``(z, y, x)`` mm.

    The slice *direction* is measured from the first and last Image Position (Patient)
    rather than assumed from the cross product, so a series reconstructed in descending
    order keeps its true handedness. The slice *spacing* is the resolved grid spacing,
    not the extent divided by the file count.
    """
    first = pydicom.dcmread(str(series.files[0]), stop_before_pixels=True, force=True)
    last = pydicom.dcmread(str(series.files[-1]), stop_before_pixels=True, force=True)
    orientation = tuple(float(v) for v in first.ImageOrientationPatient)
    origin = tuple(float(v) for v in first.ImagePositionPatient)
    step = np.asarray([float(v) for v in last.ImagePositionPatient]) - np.asarray(origin)
    norm = float(np.linalg.norm(step))
    direction = tuple(step / norm) if norm > 0 else (0.0, 0.0, 1.0)
    py, px = series.pixel_spacing_mm
    affine = dicom_affine(orientation, origin, (py, px), direction, series.grid.spacing_mm)
    return affine, (series.grid.spacing_mm, float(py), float(px))

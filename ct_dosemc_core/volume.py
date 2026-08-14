"""Reading a series as Hounsfield units, including the padding rule that eats images.

Outside the reconstruction circle a CT image carries a padding value rather than a
measurement, and that value must be replaced with air before anything measures the
patient. The DICOM attribute that names it, Pixel Padding Value (0028,0120), has a value
representation that *depends on another attribute*: US when Pixel Representation is 0,
SS when it is 1. Implementations do not reliably honour that, and GE writes ``63536``
with VR US on signed data -- 63536 unsigned is -2000 signed, the padding value it meant.

Taken at face value, that gives a padding threshold of 62512 HU. Every voxel in the
volume is below it. The image becomes a uniform block of air, the segmenter finds no
organs in it, and nothing anywhere reports an error: four of the ten GE series in this
sample were destroyed exactly this way, and the only visible symptom was empty masks.

So two things happen here. The padding value is reinterpreted against Pixel
Representation, which fixes the cause. And a padding rule that would blank essentially
the whole image is refused, which fixes the class -- because the next encoding quirk will
not be this one.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pydicom

PIXEL_PADDING_VALUE = (0x0028, 0x0120)
PIXEL_PADDING_RANGE_LIMIT = (0x0028, 0x0121)
RESCALE_INTERCEPT = (0x0028, 0x1052)
RESCALE_SLOPE = (0x0028, 0x1053)

#: Air, in Hounsfield units. Padded voxels are set to this so they carry no mass and no
#: attenuation, rather than an out-of-range value that would distort a mean or a contour.
AIR_HU = -1000.0

#: A padding rule that would blank at least this fraction of a slice is not describing
#: padding. No reconstruction pads away the entire image, so the rule is rejected and
#: the slice kept.
MAX_PADDED_FRACTION = 0.98


def signed_padding_value(raw: Any, pixel_representation: int) -> float | None:
    """Pixel Padding Value as the encoder meant it.

    When the pixel data is signed, a padding value above 32767 is an unsigned encoding
    of a negative number and is reinterpreted as two's complement. This is the whole
    defect: 63536 read literally is nonsense, read correctly it is -2000.
    """
    if raw is None:
        return None
    try:
        value = float(raw[0] if isinstance(raw, (list, tuple)) else raw)
    except (TypeError, ValueError):
        return None
    if pixel_representation == 1 and value > 32767:
        value -= 65536.0
    return value


def slice_hu(ds: pydicom.Dataset, dtype: type = np.float32) -> tuple[np.ndarray, str]:
    """One slice in Hounsfield units, with padding replaced by air.

    Returns the slice and a note describing anything unusual, empty when nothing was.
    """
    slope = float(ds.get(RESCALE_SLOPE, 1.0).value if RESCALE_SLOPE in ds else 1.0)
    intercept = float(ds.get(RESCALE_INTERCEPT, 0.0).value if RESCALE_INTERCEPT in ds else 0.0)
    hu = ds.pixel_array.astype(dtype) * slope + intercept

    raw = ds[PIXEL_PADDING_VALUE].value if PIXEL_PADDING_VALUE in ds else None
    pad = signed_padding_value(raw, int(getattr(ds, "PixelRepresentation", 0)))
    if pad is None:
        return hu, ""

    limit_raw = ds[PIXEL_PADDING_RANGE_LIMIT].value if PIXEL_PADDING_RANGE_LIMIT in ds else None
    limit = signed_padding_value(limit_raw, int(getattr(ds, "PixelRepresentation", 0)))

    lo_raw, hi_raw = (pad, pad) if limit is None else (min(pad, limit), max(pad, limit))
    lo = lo_raw * slope + intercept
    hi = hi_raw * slope + intercept
    # Padding sits at or below the air floor, so everything down to it is padding too.
    padded = hu <= hi
    fraction = float(padded.mean())
    if fraction > MAX_PADDED_FRACTION:
        return hu, (
            f"pixel padding ({lo_raw:g}..{hi_raw:g} raw -> {lo:g}..{hi:g} HU) would blank "
            f"{fraction:.1%} of the slice; the rule is not describing padding and was "
            "not applied"
        )
    hu[padded] = AIR_HU
    return hu, ""


def load_volume_hu(series, dtype: type = np.float32) -> tuple[np.ndarray, list[str]]:
    """The whole series as a ``(z, y, x)`` Hounsfield volume, in the series' slice order.

    Raises:
        ValueError: if the slices do not all share one matrix size. Public archives do
            contain series reconstructed at two matrices; cropping or padding them
            silently would corrupt every area and volume measured afterwards.
    """
    volume: np.ndarray | None = None
    expected: tuple[int, ...] | None = None
    notes: list[str] = []
    for i, path in enumerate(series.files):
        ds = pydicom.dcmread(str(path))
        arr, note = slice_hu(ds, dtype)
        if note and note not in notes:
            notes.append(note)
        if volume is None:
            expected = arr.shape
            volume = np.empty((len(series.files), *arr.shape), dtype=dtype)
        elif arr.shape != expected:
            raise ValueError(
                f"series has inconsistent image dimensions: {path.name} is {arr.shape} "
                f"but the series starts at {expected}. Split it by matrix size, or "
                "select one Series Instance UID."
            )
        volume[i] = arr
    if volume is None:
        raise ValueError("series contains no readable images")

    if float(volume.max()) <= AIR_HU:
        raise ValueError(
            "the whole volume is at or below air after decoding; there is no patient in "
            "it. This is what a mis-decoded pixel padding value produces."
        )
    return volume, notes

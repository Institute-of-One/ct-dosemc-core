"""Patient-scan execution plan: bowtie sub-fans, focal spot, TCM, organ-dose ROI.

This is the (a) patient driver's *wiring*. It does not run MC-GPU -- that stays
gated by G0–G5 -- but it produces everything the run will need, with provenance
on every vendor profile, and it reduces a finished tally over the organ
bounding-box ROI. The six pieces:

1. Voxel phantom -- :func:`ct_dosemc_core.patient.build_patient_phantom`
2. Schneider tissue groups -- ``materials/PROVENANCE.json``
3. Bowtie as per-sub-fan spectra -- :func:`bowtie_subfan_plan`
4. Focal spot inside the 130 cm box -- :func:`ct_dosemc_core.source_model.focal_spot_cm`
5. TCM I(z) as a per-station history weight -- :class:`TubeCurrentProfile`
6. Organ-dose reduction over the bbox ROI -- :func:`organ_doses_from_roi`
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from .dosimetry import RegionDose, region_dose
from .mcgpu_io import DoseMap
from .patient import union_organ_roi
from .source_model import (
    BowtieProfile,
    FanSegment,
    fan_segments,
    load_bowtie_profile,
)
from .spectra import Filter, Spectrum, generate_spectrum

__all__ = [
    "SubFanPlan",
    "bowtie_filtered_spectrum",
    "bowtie_subfan_plan",
    "crop_to_roi",
    "organ_doses_from_roi",
    "roi_to_slices",
]


@dataclass(frozen=True)
class SubFanPlan:
    """One azimuthal sub-fan with its bowtie-attenuated spectrum and provenance."""

    segment: FanSegment
    extra_al_mm: float
    spectrum: Spectrum
    provenance: str
    vendor: str
    spread_mm: float | None


def bowtie_filtered_spectrum(
    kvp: float,
    extra_al_mm: float,
    *,
    inherent: Sequence[Filter] = (),
    anode_angle_deg: float = 7.0,
) -> Spectrum:
    """SpekPy spectrum with the bowtie's equivalent-Al thickness added as a filter."""
    filters = list(inherent) + [Filter("Al", float(extra_al_mm))]
    return generate_spectrum(kvp, filters, anode_angle_deg=anode_angle_deg)


def bowtie_subfan_plan(
    vendor: str,
    *,
    n_sub_fans: int,
    half_fan_deg: float,
    collimation_cm: float,
    sad_cm: float,
    kvp: float = 120.0,
    filter_name: str = "Large",
    inherent: Sequence[Filter] = (),
    profile: BowtieProfile | None = None,
) -> list[SubFanPlan]:
    """K sub-fans, each with t(ψ_k) mm Al baked into its own spectrum.

    The profile's provenance (measured vs cross-vendor average) is copied onto
    every segment so a Siemens run cannot silently look like a measured one.
    """
    prof = profile or load_bowtie_profile(vendor, kvp=kvp, filter_name=filter_name)
    segments = fan_segments(
        n_sub_fans,
        half_fan_deg=half_fan_deg,
        collimation_cm=collimation_cm,
        sad_cm=sad_cm,
    )
    plans: list[SubFanPlan] = []
    for seg in segments:
        t = prof.thickness_mm(seg.centre_psi_deg)
        spec = bowtie_filtered_spectrum(kvp, t, inherent=inherent)
        plans.append(
            SubFanPlan(
                segment=seg,
                extra_al_mm=t,
                spectrum=spec,
                provenance=prof.provenance,
                vendor=prof.vendor,
                spread_mm=prof.spread_at_mm(seg.centre_psi_deg),
            )
        )
    return plans


def roi_to_slices(
    roi: tuple[tuple[int, int], tuple[int, int], tuple[int, int]],
) -> tuple[slice, slice, slice]:
    """1-based inclusive ``((x0,x1),(y0,y1),(z0,z1))`` -> ``(z, y, x)`` slices."""
    (x0, x1), (y0, y1), (z0, z1) = roi
    return slice(z0 - 1, z1), slice(y0 - 1, y1), slice(x0 - 1, x1)


def crop_to_roi(array: np.ndarray, roi: tuple[tuple[int, int], tuple[int, int], tuple[int, int]]) -> np.ndarray:
    """Crop a ``(z, y, x)`` array to a 1-based inclusive MC-GPU dose ROI."""
    zs, ys, xs = roi_to_slices(roi)
    return np.asarray(array)[zs, ys, xs]


def organ_doses_from_roi(
    dose_map: DoseMap,
    density_full: np.ndarray,
    masks_full: Mapping[str, np.ndarray],
    *,
    n_histories: float,
    roi: tuple[tuple[int, int], tuple[int, int], tuple[int, int]] | None = None,
    pad_voxels: int = 1,
) -> dict[str, RegionDose]:
    """Mass-weighted organ doses from a bbox-cropped tally.

    ``masks_full`` and ``density_full`` live on the whole phantom grid; the tally
    lives on ``dose_map``'s ROI. The ROI is either given or taken as the union of
    the organ boxes. An organ that misses the ROI is skipped rather than scored
    as zero -- a silent zero would look like a finding.
    """
    if roi is None:
        roi = union_organ_roi(dict(masks_full), pad_voxels=pad_voxels)
    origin = dose_map.roi_origin_zyx
    zs, ys, xs = roi_to_slices(roi)
    expected = (zs.start, ys.start, xs.start)
    if origin != expected:
        raise ValueError(
            f"tally ROI origin {origin} does not match the organ box {expected}; "
            "the mask crop would be on the wrong voxels"
        )
    density_roi = crop_to_roi(density_full, roi)
    if density_roi.shape != dose_map.shape_zyx:
        raise ValueError(
            f"cropped density {density_roi.shape} does not match tally {dose_map.shape_zyx}"
        )
    out: dict[str, RegionDose] = {}
    for name, mask in masks_full.items():
        m = crop_to_roi(np.asarray(mask, dtype=bool), roi)
        if not m.any():
            continue
        out[name] = region_dose(name, dose_map, m, density_roi, n_histories)
    if not out:
        raise ValueError("no organ overlapped the dose ROI")
    return out

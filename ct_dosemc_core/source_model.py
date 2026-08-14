"""The CT source model: beam geometry, absolute normalisation, tube-current modulation.

This is where the openness thesis is most exposed, so every approximation is
stated rather than buried.  MC-GPU v1.3 gives us a point source emitting into a
rectangular solid angle, a circular (optionally helical) trajectory about Z, and
no bowtie filter and no anti-scatter grid at all.  Everything a real scanner does
beyond that is either modelled here explicitly or declared as an assumption.

Absolute normalisation
----------------------
MC-GPU reports dose as ``eV/g per history``.  Turning that into mGy needs the
number of photons the tube actually emitted into the simulated solid angle:

    N_hist = N_Omega * Omega * mAs

with ``N_Omega`` from SpekPy (:meth:`ct_dosemc_core.spectra.Spectrum.photons_per_sr_per_mas`)
and ``Omega`` the solid angle MC-GPU samples.  MC-GPU samples ``w = cos(theta)``
uniformly on a symmetric interval and the azimuth ``phi`` uniformly
(vendor/MCGPU/MC-GPU_kernel_v1.3.cu:652), so the sampling is uniform in solid
angle and

    Omega = delta(cos theta) * delta(phi) = 2 sin(theta_ap/2) * phi_ap[rad]

See vendor/MCGPU/MC-GPU_v1.3.cu:1378-1381 for the aperture convention.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .provenance import Provenance, Value

__all__ = [
    "BOWTIE_PROFILES",
    "BeamGeometry",
    "BowtieProfile",
    "FanSegment",
    "TubeCurrentProfile",
    "canonical_vendor",
    "eV_per_g_to_mGy",
    "fan_segments",
    "focal_spot_cm",
    "histories_for_mas",
    "load_bowtie_profile",
    "mas_for_histories",
    "tube_current_profile",
]

# eV/g -> Gy:  1 eV = 1.602176634e-19 J, and 1/g = 1000/kg.
EV_PER_G_TO_GY = 1.602176634e-19 * 1.0e3
"""CODATA 2018 elementary charge; exact by SI definition since 2019."""


def eV_per_g_to_mGy(dose_ev_per_g: float, n_histories: float) -> float:
    """Convert MC-GPU's per-history ``eV/g`` tally to mGy for ``n_histories`` photons."""
    return dose_ev_per_g * n_histories * EV_PER_G_TO_GY * 1.0e3


@dataclass(frozen=True)
class BeamGeometry:
    """The simulated beam, in the terms MC-GPU understands.

    Attributes
    ----------
    sad_cm:
        Source-to-axis (isocentre) distance.
    sdd_cm:
        Source-to-detector distance.  Only the image tally uses it; it does not
        affect the dose, but MC-GPU requires it.
    collimation_cm:
        Nominal total beam width N*T **at the isocentre**, along Z.
    fan_aperture_deg:
        Full in-plane (azimuthal) aperture.  Must cover the object; making it
        wider only costs histories, because the solid angle is accounted for.
    """

    sad_cm: float
    sdd_cm: float
    collimation_cm: float
    fan_aperture_deg: float

    @property
    def polar_aperture_deg(self) -> float:
        """Full aperture along Z that yields ``collimation_cm`` at the isocentre.

        MC-GPU's polar aperture is symmetric about the central plane, so the
        half-angle alpha satisfies ``tan(alpha) = (N*T/2) / SAD``.
        """
        return 2.0 * math.degrees(math.atan(0.5 * self.collimation_cm / self.sad_cm))

    @property
    def solid_angle_sr(self) -> float:
        """Solid angle MC-GPU samples, in steradians."""
        theta_ap = math.radians(self.polar_aperture_deg)
        phi_ap = math.radians(self.fan_aperture_deg)
        return 2.0 * math.sin(0.5 * theta_ap) * phi_ap

    def beam_width_at(self, distance_cm: float) -> float:
        """Beam width along Z at ``distance_cm`` from the focal spot."""
        return 2.0 * distance_cm * math.tan(0.5 * math.radians(self.polar_aperture_deg))

    def covers_radius(self, radius_cm: float) -> bool:
        """Does the fan aperture cover a cylinder of ``radius_cm`` on the axis?"""
        if radius_cm >= self.sad_cm:
            return False
        needed_deg = 2.0 * math.degrees(math.asin(radius_cm / self.sad_cm))
        return self.fan_aperture_deg >= needed_deg

    def solid_angle_value(self) -> Value:
        return Value(
            value=self.solid_angle_sr,
            unit="sr",
            uncertainty=None,
            provenance=Provenance(
                formula="Omega = 2*sin(theta_ap/2) * phi_ap[rad]",
                inputs={
                    "theta_ap_deg": self.polar_aperture_deg,
                    "phi_ap_deg": self.fan_aperture_deg,
                    "sad_cm": self.sad_cm,
                    "collimation_cm": self.collimation_cm,
                },
                assumptions=(
                    "MC-GPU samples cos(theta) and phi uniformly, i.e. uniformly in "
                    "solid angle over a rectangular (cos theta, phi) window",
                    "no bowtie filter: the fluence is flat across the fan",
                    "point focal spot",
                ),
                source="vendor/MCGPU/MC-GPU_v1.3.cu:1378-1381 and "
                "MC-GPU_kernel_v1.3.cu:652-653",
            ),
        )


def histories_for_mas(
    photons_per_sr_per_mas: float,
    geometry: BeamGeometry,
    mas: float,
) -> Value:
    """Number of MC histories equivalent to ``mas`` of tube output."""
    n = photons_per_sr_per_mas * geometry.solid_angle_sr * mas
    return Value(
        value=float(n),
        unit="photons",
        uncertainty=None,
        provenance=Provenance(
            formula="N_hist = N_Omega * Omega * mAs",
            inputs={
                "N_Omega_photons_per_sr_per_mAs": float(photons_per_sr_per_mas),
                "Omega_sr": geometry.solid_angle_sr,
                "mAs": float(mas),
            },
            assumptions=(
                "tube output is linear in mAs",
                "the whole emitted solid angle is the simulated one (no extra-focal "
                "radiation, no off-focus leakage)",
            ),
            source="ct_dosemc_core.source_model.histories_for_mas",
        ),
    )


def mas_for_histories(
    photons_per_sr_per_mas: float,
    geometry: BeamGeometry,
    n_histories: float,
) -> float:
    """Inverse of :func:`histories_for_mas` -- the mAs a finished run corresponds to."""
    denom = photons_per_sr_per_mas * geometry.solid_angle_sr
    if denom <= 0.0:
        raise ValueError("non-positive photons/sr/mAs or solid angle")
    return float(n_histories) / denom


BOWTIE_PROFILES = Path(__file__).resolve().parents[1] / "data" / "bowtie" / "bowtie_profiles.json"

_VENDOR_ALIASES = {
    "ge": "GE",
    "ge medical systems": "GE",
    "ge healthcare": "GE",
    "siemens": "Siemens",
    "siemens healthineers": "Siemens",
    "philips": "Philips",
    "philips medical systems": "Philips",
    "toshiba": "Canon/Toshiba",
    "canon": "Canon/Toshiba",
    "canon medical systems": "Canon/Toshiba",
    "canon/toshiba": "Canon/Toshiba",
}


def canonical_vendor(manufacturer: str) -> str:
    """Map a DICOM Manufacturer string onto the four cohort vendor labels."""
    key = " ".join(str(manufacturer).strip().lower().split())
    if key not in _VENDOR_ALIASES:
        raise ValueError(
            f"unrecognised manufacturer {manufacturer!r}; expected one of "
            f"{sorted(set(_VENDOR_ALIASES.values()))}"
        )
    return _VENDOR_ALIASES[key]


@dataclass(frozen=True)
class BowtieProfile:
    """One vendor's equivalent-Al thickness vs fan angle, with its provenance."""

    vendor: str
    provenance: str
    kvp: float
    filter_name: str
    angle_deg: np.ndarray
    al_mm: np.ndarray
    spread_mm: np.ndarray | None = None

    def thickness_mm(self, psi_deg: float) -> float:
        """t(|ψ|) mm Al; the bowtie is symmetric (``bowtie_profiles.json``)."""
        a = np.asarray(self.angle_deg, dtype=float)
        t = np.asarray(self.al_mm, dtype=float)
        x = abs(float(psi_deg))
        if x > float(a.max()) + 1e-9:
            raise ValueError(
                f"fan angle {psi_deg} deg is outside the measured profile "
                f"(0–{float(a.max()):.1f} deg) for {self.vendor}"
            )
        return float(np.interp(x, a, t))

    def spread_at_mm(self, psi_deg: float) -> float | None:
        if self.spread_mm is None:
            return None
        a = np.asarray(self.angle_deg, dtype=float)
        s = np.asarray(self.spread_mm, dtype=float)
        return float(np.interp(abs(float(psi_deg)), a, s))


def load_bowtie_profile(
    vendor: str,
    *,
    kvp: float = 120.0,
    filter_name: str = "Large",
    path: Path | str | None = None,
) -> BowtieProfile:
    """Load a provenanced t(ψ) curve. Siemens is the cross-vendor average."""
    label = canonical_vendor(vendor) if vendor not in ("GE", "Siemens", "Philips", "Canon/Toshiba") else vendor
    data = json.loads(Path(path or BOWTIE_PROFILES).read_text(encoding="utf-8"))
    block = data["vendors"][label]
    kv = str(int(kvp))
    fam = block["filters"][filter_name]
    entry = fam.get(kv) or (fam.get("135") if kv in {"135", "140"} else None)
    if entry is None:
        raise ValueError(f"no {label} {filter_name} bowtie at {kvp} kVp")
    spread = entry.get("cross_vendor_spread_mm")
    return BowtieProfile(
        vendor=label,
        provenance=str(block["provenance"]),
        kvp=float(kvp),
        filter_name=filter_name,
        angle_deg=np.asarray(entry["angle_deg"], dtype=float),
        al_mm=np.asarray(entry["al_mm"], dtype=float),
        spread_mm=None if spread is None else np.asarray(spread, dtype=float),
    )


@dataclass(frozen=True)
class FanSegment:
    """One azimuthal sub-fan: aperture pair plus the central-ray angle."""

    index: int
    centre_psi_deg: float
    azimuthal_aperture_deg: float
    polar_aperture_deg: float

    @property
    def solid_angle_sr(self) -> float:
        return (
            2.0
            * math.sin(0.5 * math.radians(self.polar_aperture_deg))
            * math.radians(self.azimuthal_aperture_deg)
        )

    def direction(self) -> tuple[float, float, float]:
        """Central direction for a source whose fan centre points along +y."""
        psi = math.radians(self.centre_psi_deg)
        return (-math.sin(psi), math.cos(psi), 0.0)


def fan_segments(
    n: int,
    *,
    half_fan_deg: float,
    collimation_cm: float,
    sad_cm: float,
) -> list[FanSegment]:
    """Split a rectangular fan into ``n`` azimuthal segments (the bowtie's K).

    Polar aperture at each centre azimuth reproduces ``collimation_cm`` at the
    isocentre plane, the same 1/cos(ψ) correction as TG-195 Case 4.
    """
    if n < 1:
        raise ValueError("need at least one sub-fan")
    edges = np.linspace(-float(half_fan_deg), float(half_fan_deg), n + 1)
    out: list[FanSegment] = []
    for k in range(n):
        centre = 0.5 * float(edges[k] + edges[k + 1])
        polar = 2.0 * math.degrees(
            math.atan(0.5 * collimation_cm * math.cos(math.radians(centre)) / sad_cm)
        )
        out.append(
            FanSegment(
                index=k,
                centre_psi_deg=centre,
                azimuthal_aperture_deg=float(edges[k + 1] - edges[k]),
                polar_aperture_deg=polar,
            )
        )
    return out


def focal_spot_cm(
    bbox_cm: tuple[float, float, float],
    sad_cm: float,
    *,
    gantry_deg: float = 0.0,
    isocentre_cm: tuple[float, float, float] | None = None,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Focal-spot position and beam direction in MC-GPU corner-origin coordinates.

    Gantry 0 matches TG-195: source at (cx, cy − SAD, cz), beam toward +y. Raises
    if the spot would sit outside the voxel box -- that is G3 failing, not a
    warning.
    """
    bx, by, bz = bbox_cm
    if isocentre_cm is None:
        isocentre_cm = (0.5 * bx, 0.5 * by, 0.5 * bz)
    cx, cy, cz = isocentre_cm
    beta = math.radians(gantry_deg)
    pos = (
        cx + sad_cm * math.sin(beta),
        cy - sad_cm * math.cos(beta),
        cz,
    )
    if not (0.0 < pos[0] < bx and 0.0 < pos[1] < by and 0.0 < pos[2] < bz):
        raise ValueError(
            f"focal spot {pos} is outside the voxel box {(bx, by, bz)} cm; "
            "the in-plane box must reach the focus (G3, typically 130 cm at SAD 60 cm)"
        )
    dx, dy, dz = cx - pos[0], cy - pos[1], cz - pos[2]
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    return pos, (dx / n, dy / n, dz / n)


@dataclass(frozen=True)
class TubeCurrentProfile:
    """Longitudinal tube-current modulation I(z)."""

    z_mm: np.ndarray
    current_ma: np.ndarray
    exposure_time_ms: np.ndarray | None = None

    @property
    def modulated(self) -> bool:
        mean = float(self.current_ma.mean())
        if mean <= 0.0:
            return False
        return float((np.max(self.current_ma) - np.min(self.current_ma)) / mean) >= 0.05

    def current_at_mm(self, z_mm: float | np.ndarray) -> np.ndarray:
        """Linear interpolation in z; clamped to the recorded range (no invented TCM)."""
        z = np.asarray(self.z_mm, dtype=float)
        i = np.asarray(self.current_ma, dtype=float)
        order = np.argsort(z)
        z, i = z[order], i[order]
        x = np.clip(np.asarray(z_mm, dtype=float), z[0], z[-1])
        return np.interp(x, z, i)

    def relative_weight(self, z_mm: float | np.ndarray) -> np.ndarray:
        """I(z) / mean(I). A flat TCM is identically 1."""
        mean = float(self.current_ma.mean())
        if mean <= 0.0:
            raise ValueError("non-positive mean tube current")
        return self.current_at_mm(z_mm) / mean


def tube_current_profile(series) -> TubeCurrentProfile:
    """Build I(z) from a loaded DICOM series, or from ``(z_mm, mA)`` pairs.

    Missing per-slice (0018,1151) is an error, not a silent flat current: a CTDI
    acquisition is fixed-mA by definition, but a patient scan without I(z) cannot
    support a modulation weighting. A *recorded* constant current is returned
    with ``modulated is False``.
    """
    if isinstance(series, TubeCurrentProfile):
        return series
    if isinstance(series, (list, tuple)) and series and isinstance(series[0], (tuple, list)):
        z = np.asarray([float(p[0]) for p in series], dtype=float)
        ma = np.asarray([float(p[1]) for p in series], dtype=float)
        if (ma <= 0.0).any():
            raise ValueError("tube current must be positive on every sample")
        return TubeCurrentProfile(z_mm=z, current_ma=ma)

    # LoadedSeries: one (0018,1151) per file, z from ImagePositionPatient.
    import pydicom

    files = getattr(series, "files", None)
    if not files:
        raise ValueError(
            "tube_current_profile needs a LoadedSeries or a list of (z_mm, mA) pairs; "
            "a missing I(z) is not replaced by a flat current"
        )
    z_vals: list[float] = []
    ma_vals: list[float] = []
    t_vals: list[float] = []
    for path in files:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        ipp = getattr(ds, "ImagePositionPatient", None)
        ma = getattr(ds, "XRayTubeCurrent", None)
        if ipp is None or ma is None:
            continue
        z_vals.append(float(ipp[2]))
        ma_vals.append(float(ma))
        t = getattr(ds, "ExposureTime", None)
        t_vals.append(float(t) if t not in (None, "") else float("nan"))
    if not ma_vals:
        raise ValueError(
            "no per-slice X-Ray Tube Current (0018,1151) on the series; "
            "I(z) cannot be invented"
        )
    if len(ma_vals) != len(files):
        raise ValueError(
            f"tube current recorded on {len(ma_vals)}/{len(files)} slices; "
            "a partial I(z) is not a TCM profile"
        )
    exp = None if not np.isfinite(t_vals).all() else np.asarray(t_vals, dtype=float)
    return TubeCurrentProfile(
        z_mm=np.asarray(z_vals, dtype=float),
        current_ma=np.asarray(ma_vals, dtype=float),
        exposure_time_ms=exp,
    )

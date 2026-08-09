"""The CTDI phantom and the CTDI anchor -- Phase 1 of IORN-007.

Nothing patient-specific happens here.  This module builds the IEC 60601-2-44
CTDI phantoms as voxel geometry, defines the five ionisation-chamber positions,
and turns a Monte-Carlo dose tally into CTDI100, CTDIw and CTDIvol.  It is the
one place in the project where the answer is fixed by a published standard rather
than by an image, which is exactly why the validation is anchored here and not to
IORN-006's organ index.

What is reported
----------------
MC-GPU tallies energy deposited in the phantom material, so what comes out of
here is **absorbed dose to PMMA** at the chamber positions, written
``CTDI100_PMMA``.  The conventional CTDI is air kerma measured in the bore; the
two differ by the ratio of mass energy-absorption coefficients
``(mu_en/rho)_air / (mu_en/rho)_PMMA`` averaged over the local spectrum.  That
conversion is **not applied here** -- see ``docs/MC_SOURCE_MODEL.md``.  The
dimensionless ratios this module also reports (peripheral/central, and phantom
relative to free-in-air scored in the same medium) are insensitive to it to first
order, and are the quantities compared against the literature.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .dosimetry import RegionDose
from .phantom import Material, VoxelPhantom, cylinder_occupancy
from .provenance import Provenance, Value

__all__ = [
    "CHAMBER_POSITIONS",
    "CtdiPhantomSpec",
    "build_ctdi_phantom",
    "chamber_masks",
    "chamber_weights",
    "ctdi_100",
    "ctdi_vol",
    "ctdi_w",
]

CHAMBER_POSITIONS = ("centre", "12_o_clock", "3_o_clock", "6_o_clock", "9_o_clock")
"""The five standard measurement positions: one central, four peripheral."""


@dataclass(frozen=True)
class CtdiPhantomSpec:
    """A standard CTDI dosimetry phantom.

    Defaults follow IEC 60601-2-44: a homogeneous PMMA cylinder 15 cm long, 32 cm
    diameter for the body phantom and 16 cm for the head phantom, with bores of
    about 13 mm diameter on the axis and at 1 cm depth at the four cardinal
    positions.

    The bores are **not** cut out of the geometry.  Real CTDI measurements are
    made with the four unused bores filled by PMMA rods and the chamber in the
    fifth, so a homogeneous cylinder is the closer model; the chamber regions are
    simply the volumes over which dose is scored.
    """

    diameter_cm: float = 32.0
    length_cm: float = 15.0
    voxel_size_cm: float = 0.25
    air_margin_cm: float = 2.0
    chamber_depth_cm: float = 1.0
    chamber_diameter_cm: float = 1.31
    chamber_length_cm: float = 10.0
    pmma_density_g_cm3: float = 1.19
    air_density_g_cm3: float = 1.20479e-3

    def __post_init__(self) -> None:
        if self.chamber_depth_cm >= 0.5 * self.diameter_cm:
            raise ValueError("peripheral chambers must lie inside the phantom")
        if self.chamber_length_cm > self.length_cm:
            raise ValueError(
                f"the {self.chamber_length_cm:g} cm chamber does not fit in a "
                f"{self.length_cm:g} cm phantom"
            )

    @property
    def radius_cm(self) -> float:
        return 0.5 * self.diameter_cm

    @property
    def peripheral_radius_cm(self) -> float:
        """Distance from the axis to the centre of a peripheral chamber."""
        return self.radius_cm - self.chamber_depth_cm

    def chamber_offsets_cm(self) -> dict[str, tuple[float, float]]:
        """(dx, dy) of each chamber centre relative to the phantom axis."""
        r = self.peripheral_radius_cm
        return {
            "centre": (0.0, 0.0),
            "12_o_clock": (0.0, +r),
            "3_o_clock": (+r, 0.0),
            "6_o_clock": (0.0, -r),
            "9_o_clock": (-r, 0.0),
        }


def build_ctdi_phantom(
    spec: CtdiPhantomSpec,
    *,
    air: Material,
    pmma: Material,
) -> VoxelPhantom:
    """Voxelise ``spec`` as a PMMA cylinder surrounded by air.

    The cylinder axis runs along Z through the centre of the bounding box, which
    is where ``tools/run_validation.py`` places MC-GPU's rotation axis.  A voxel
    belongs to the phantom if its centre lies inside the cylinder -- a hard edge,
    whose stair-step is one of the documented approximations.
    """
    v = spec.voxel_size_cm
    span_xy = spec.diameter_cm + 2.0 * spec.air_margin_cm
    span_z = spec.length_cm + 2.0 * spec.air_margin_cm
    nx = ny = int(math.ceil(span_xy / v))
    nz = int(math.ceil(span_z / v))

    x = (np.arange(nx) + 0.5) * v
    y = (np.arange(ny) + 0.5) * v
    z = (np.arange(nz) + 0.5) * v
    cx, cy, cz = 0.5 * nx * v, 0.5 * ny * v, 0.5 * nz * v

    rr = (x[None, :] - cx) ** 2 + (y[:, None] - cy) ** 2  # [y, x]
    in_disc = rr <= spec.radius_cm**2
    in_z = np.abs(z - cz) <= 0.5 * spec.length_cm

    inside = in_z[:, None, None] & in_disc[None, :, :]  # [z, y, x]

    material = np.where(inside, pmma.index, air.index).astype(np.int16)
    density = np.where(inside, spec.pmma_density_g_cm3, spec.air_density_g_cm3)

    return VoxelPhantom(
        material=material,
        density=density,
        voxel_size_cm=(v, v, v),
        materials=(air, pmma),
    )


def chamber_weights(
    phantom: VoxelPhantom,
    spec: CtdiPhantomSpec,
    *,
    roi_origin_zyx: tuple[int, int, int] = (0, 0, 0),
    roi_shape_zyx: tuple[int, int, int] | None = None,
    subdivisions: int = 64,
) -> dict[str, np.ndarray]:
    """Per-voxel volume occupancy of the five chamber regions, in ``[0, 1]``.

    Each chamber is a cylinder of ``spec.chamber_diameter_cm`` diameter and
    ``spec.chamber_length_cm`` length centred on the scan plane -- the volume a
    100 mm pencil chamber occupies.

    A voxel-centre-inside test is badly wrong at this scale: a 13.1 mm circle on a
    2.5 mm grid resolves as 24 voxels = 1.500 cm^2 against a true 1.348 cm^2,
    **+11.3%**.  CTDI100 is built from a *mean* dose, so a volume error does not
    scale the answer the way it does for TG-195's energy scoring -- but it inflates
    the effective chamber radius from 6.55 mm to about 6.9 mm, which shifts where
    the mean sits inside the steep radial gradient at the peripheral positions.

    The chambers lie wholly inside bulk PMMA, so unlike the TG-195 first test
    there is no material boundary here that the weighting would falsely erase.
    """
    if roi_shape_zyx is None:
        roi_shape_zyx = phantom.shape_zyx
    z0, y0, x0 = roi_origin_zyx
    dz, dy, dx = roi_shape_zyx
    cx, cy, cz = phantom.centre_cm()
    half = 0.5 * spec.chamber_length_cm

    out: dict[str, np.ndarray] = {}
    for name, (ox, oy) in spec.chamber_offsets_cm().items():
        full = cylinder_occupancy(
            phantom.n_voxels,
            phantom.voxel_size_cm,
            centre_xy_cm=(cx + ox, cy + oy),
            radius_cm=0.5 * spec.chamber_diameter_cm,
            z_min_cm=cz - half,
            z_max_cm=cz + half,
            subdivisions=subdivisions,
        )
        w = full[z0 : z0 + dz, y0 : y0 + dy, x0 : x0 + dx]
        if not w.any():
            raise ValueError(f"chamber {name!r} falls outside the dose tally ROI")
        out[name] = w
    return out


def chamber_masks(
    phantom: VoxelPhantom,
    spec: CtdiPhantomSpec,
    *,
    roi_origin_zyx: tuple[int, int, int] = (0, 0, 0),
    roi_shape_zyx: tuple[int, int, int] | None = None,
) -> dict[str, np.ndarray]:
    """Boolean form of :func:`chamber_weights` -- every voxel the chamber touches."""
    return {
        k: w > 0.0
        for k, w in chamber_weights(
            phantom, spec, roi_origin_zyx=roi_origin_zyx, roi_shape_zyx=roi_shape_zyx
        ).items()
    }


def ctdi_100(
    region: RegionDose,
    *,
    collimation_cm: float,
    chamber_length_cm: float = 10.0,
    medium: str = "PMMA",
) -> Value:
    """CTDI100 from the mean dose over a 100 mm chamber volume.

    ``CTDI100 = (1/(N*T)) * integral_{-50mm}^{+50mm} D(z) dz``.  The mean dose the
    Monte Carlo reports over the chamber volume already is that integral divided
    by the chamber length, so ``CTDI100 = D_mean * L / (N*T)``, exactly as an
    ionisation chamber of that length integrates the profile.
    """
    if collimation_cm <= 0:
        raise ValueError("collimation must be positive")
    scale = chamber_length_cm / collimation_cm
    return Value(
        value=region.dose_mgy * scale,
        unit="mGy",
        uncertainty=region.sigma_mgy * scale,
        provenance=Provenance(
            formula="CTDI100 = D_mean_over_chamber * L_chamber / (N*T)",
            inputs={
                "position": region.name,
                "D_mean_mGy": region.dose_mgy,
                "L_chamber_cm": chamber_length_cm,
                "collimation_NT_cm": collimation_cm,
                "n_voxels": region.n_voxels,
                "chamber_mass_g": region.mass_g,
            },
            assumptions=(
                f"dose is absorbed dose to {medium}, not air kerma in a bore; the "
                "conversion by (mu_en/rho)_air/(mu_en/rho)_" + medium + " is not applied",
                "the chamber responds uniformly over its 100 mm length",
                "the phantom is homogeneous: bores are not cut out, matching a "
                "measurement with the unused bores plugged",
            ),
            source="IEC 60601-2-44; AAPM Report 96",
        ),
    )


def ctdi_w(central: Value, peripheral: Value) -> Value:
    """``CTDIw = CTDI100_centre/3 + 2*CTDI100_peripheral/3``."""
    value = central.value / 3.0 + 2.0 * peripheral.value / 3.0
    sigma = None
    if central.uncertainty is not None and peripheral.uncertainty is not None:
        sigma = math.sqrt(
            (central.uncertainty / 3.0) ** 2 + (2.0 * peripheral.uncertainty / 3.0) ** 2
        )
    return Value(
        value=value,
        unit=central.unit,
        uncertainty=sigma,
        provenance=Provenance(
            formula="CTDIw = (1/3)*CTDI100_centre + (2/3)*CTDI100_peripheral",
            inputs={
                "CTDI100_centre": central.value,
                "CTDI100_peripheral": peripheral.value,
            },
            assumptions=(
                "the four peripheral positions are averaged before weighting",
                "central and peripheral uncertainties are combined in quadrature; "
                "they share Monte-Carlo histories, so this slightly understates the "
                "correlated component",
            ),
            source="IEC 60601-2-44; AAPM Report 96",
        ),
    )


def ctdi_vol(ctdiw: Value, pitch: float) -> Value:
    """``CTDIvol = CTDIw / pitch``."""
    if pitch <= 0:
        raise ValueError("pitch must be positive")
    return Value(
        value=ctdiw.value / pitch,
        unit=ctdiw.unit,
        uncertainty=None if ctdiw.uncertainty is None else ctdiw.uncertainty / pitch,
        provenance=Provenance(
            formula="CTDIvol = CTDIw / pitch",
            inputs={"CTDIw": ctdiw.value, "pitch": float(pitch)},
            assumptions=("pitch = table travel per rotation / (N*T)",),
            source="IEC 60601-2-44",
        ),
    )


def average_peripheral(values: dict[str, Value]) -> Value:
    """Mean of the four peripheral CTDI100 values."""
    names = [n for n in CHAMBER_POSITIONS if n != "centre"]
    missing = [n for n in names if n not in values]
    if missing:
        raise KeyError(f"missing peripheral positions: {missing}")
    vals = [values[n].value for n in names]
    sigmas = [values[n].uncertainty for n in names]
    mean = float(np.mean(vals))
    sigma = (
        float(np.sqrt(sum(s**2 for s in sigmas)) / len(sigmas))
        if all(s is not None for s in sigmas)
        else None
    )
    return Value(
        value=mean,
        unit=values[names[0]].unit,
        uncertainty=sigma,
        provenance=Provenance(
            formula="CTDI100_peripheral = mean of the four cardinal positions",
            inputs={n: values[n].value for n in names},
            assumptions=(
                "a full 360 degree rotation makes the four positions equivalent; the "
                "spread between them is reported as a symmetry check",
            ),
            source="IEC 60601-2-44",
        ),
    )

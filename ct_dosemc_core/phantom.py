"""Voxel phantoms: the material/density universe the photons are tracked through.

Two producers feed this container:

* :mod:`ct_dosemc_core.ctdi` builds the IEC CTDI phantoms analytically -- the
  Phase-1 validation geometry, where the answer is defined by a standard rather
  than by an image.
* Phase 2 builds patient phantoms from TotalSegmentator masks plus a Schneider
  stoichiometric HU->density calibration, reusing the ctsegdose-core pipeline.

Both end up as the same thing: a material index per voxel and a mass density per
voxel, which is exactly what MC-GPU's penEasy-format voxel file carries.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

__all__ = [
    "BODY_THRESHOLD_HU",
    "CALIBRATION_MAX_HU",
    "Material",
    "VoxelPhantom",
    "body_contour",
    "cylinder_occupancy",
    "hu_to_density",
    "patient_density_map",
]

# MC-GPU v1.3 compiles with MAX_MATERIALS=15 (vendor/MCGPU/MC-GPU_v1.3.h:62).
MCGPU_MAX_MATERIALS = 15


@dataclass(frozen=True)
class Material:
    """One entry of MC-GPU's material list.

    ``index`` is 1-based, matching the order of the material files in the input
    file -- MC-GPU rejects a voxel material of 0 or less.
    """

    index: int
    name: str
    file: str
    nominal_density_g_cm3: float


@dataclass
class VoxelPhantom:
    """A voxelised material/density universe.

    Arrays are indexed ``[z, y, x]``; MC-GPU's file format wants X running
    fastest, which :func:`ct_dosemc_core.mcgpu_io.write_voxel_file` handles.

    The origin of MC-GPU's coordinate system is the lower-back corner of the
    volume, so every coordinate in the input file is positive and measured from
    that corner (vendor/MCGPU/README.md).
    """

    material: np.ndarray  # int, 1-based material index
    density: np.ndarray  # float, g/cm^3
    voxel_size_cm: tuple[float, float, float]
    materials: tuple[Material, ...]

    def __post_init__(self) -> None:
        if self.material.shape != self.density.shape:
            raise ValueError(
                f"material {self.material.shape} and density {self.density.shape} disagree"
            )
        if self.material.min() < 1:
            raise ValueError("material indices are 1-based; found a value < 1")
        if len(self.materials) > MCGPU_MAX_MATERIALS:
            raise ValueError(
                f"{len(self.materials)} materials exceeds MC-GPU's MAX_MATERIALS="
                f"{MCGPU_MAX_MATERIALS}; rebuild the engine or merge materials"
            )
        if self.material.max() > len(self.materials):
            raise ValueError(
                f"voxel references material {self.material.max()} but only "
                f"{len(self.materials)} are declared"
            )
        if not np.all(self.density > 0.0):
            raise ValueError("MC-GPU rejects zero or negative voxel density")

    @property
    def shape_zyx(self) -> tuple[int, int, int]:
        return tuple(int(n) for n in self.material.shape)  # type: ignore[return-value]

    @property
    def n_voxels(self) -> tuple[int, int, int]:
        """(nx, ny, nz), the order MC-GPU's header wants."""
        nz, ny, nx = self.shape_zyx
        return nx, ny, nz

    @property
    def bbox_cm(self) -> tuple[float, float, float]:
        nx, ny, nz = self.n_voxels
        dx, dy, dz = self.voxel_size_cm
        return nx * dx, ny * dy, nz * dz

    @property
    def voxel_volume_cm3(self) -> float:
        dx, dy, dz = self.voxel_size_cm
        return dx * dy * dz

    def centre_cm(self) -> tuple[float, float, float]:
        """Geometric centre in MC-GPU coordinates (corner-origin)."""
        bx, by, bz = self.bbox_cm
        return 0.5 * bx, 0.5 * by, 0.5 * bz

    def axis_coordinates_cm(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Voxel-centre coordinates along X, Y, Z in MC-GPU coordinates."""
        nx, ny, nz = self.n_voxels
        dx, dy, dz = self.voxel_size_cm
        return (
            (np.arange(nx) + 0.5) * dx,
            (np.arange(ny) + 0.5) * dy,
            (np.arange(nz) + 0.5) * dz,
        )

    def mass_g(self, mask: np.ndarray | None = None) -> float:
        """Mass of the whole phantom, or of ``mask`` if given."""
        d = self.density if mask is None else self.density[mask]
        return float(d.sum() * self.voxel_volume_cm3)


# -- partial-volume occupancy for analytically-defined regions --------------


def cylinder_occupancy(
    n_voxels_xyz: tuple[int, int, int],
    voxel_size_cm: tuple[float, float, float],
    *,
    centre_xy_cm: tuple[float, float],
    radius_cm: float,
    z_min_cm: float,
    z_max_cm: float,
    subdivisions: int = 64,
) -> np.ndarray:
    """Fraction of each voxel lying inside a z-aligned cylinder, in ``[0, 1]``.

    A voxel-centre-inside test is a *boolean* approximation whose error scales
    with the surface-to-volume ratio of the region.  For a region the size of the
    phantom that is negligible (+0.19% for a 320 mm disc at 2.5 mm voxels); for a
    10 mm diameter scoring cylinder it is **-4.51%**, because a 2.5 mm grid
    resolves such a circle as exactly 12 voxels against a true area of 12.57.
    Any quantity proportional to the selected volume -- energy deposited, mass --
    inherits that error directly.

    The occupancy is separable for a z-aligned cylinder: the xy-fraction of a
    voxel inside the disc times the z-fraction inside ``[z_min, z_max]``.  The
    z factor is computed exactly, and only voxels the disc boundary actually
    crosses are subdivided, so this costs almost nothing.

    Returns an array indexed ``[z, y, x]``, matching :class:`VoxelPhantom`.
    """
    if radius_cm <= 0.0:
        raise ValueError("radius must be positive")
    if z_max_cm <= z_min_cm:
        raise ValueError("z_max must exceed z_min")
    if subdivisions < 2:
        raise ValueError("need at least 2 subdivisions per axis")

    nx, ny, nz = n_voxels_xyz
    vx, vy, vz = voxel_size_cm
    cx, cy = centre_xy_cm

    x = (np.arange(nx) + 0.5) * vx
    y = (np.arange(ny) + 0.5) * vy
    z = (np.arange(nz) + 0.5) * vz

    # -- xy: exact for interior and exterior voxels, subdivided on the boundary
    dx = np.abs(x[None, :] - cx)
    dy = np.abs(y[:, None] - cy)
    near = np.hypot(np.maximum(dx - 0.5 * vx, 0.0), np.maximum(dy - 0.5 * vy, 0.0))
    far = np.hypot(dx + 0.5 * vx, dy + 0.5 * vy)

    f_xy = np.zeros((ny, nx), dtype=float)
    f_xy[far <= radius_cm] = 1.0
    straddling = (near < radius_cm) & (far > radius_cm)

    if straddling.any():
        offsets = (np.arange(subdivisions) + 0.5) / subdivisions - 0.5
        sub_x = offsets * vx
        sub_y = offsets * vy
        js, is_ = np.nonzero(straddling)
        # Sub-cell centres for every straddling voxel at once: (n, sub, sub)
        px = (x[is_][:, None, None] + sub_x[None, None, :]) - cx
        py = (y[js][:, None, None] + sub_y[None, :, None]) - cy
        inside = (px * px + py * py) <= radius_cm * radius_cm
        f_xy[js, is_] = inside.mean(axis=(1, 2))

    # -- z: exact overlap of the voxel extent with [z_min, z_max]
    lo = np.maximum(z - 0.5 * vz, z_min_cm)
    hi = np.minimum(z + 0.5 * vz, z_max_cm)
    f_z = np.clip(hi - lo, 0.0, None) / vz

    return f_z[:, None, None] * f_xy[None, :, :]


# -- Schneider stoichiometric HU -> density ---------------------------------
# Piecewise-linear calibration reused from ctsegdose-core.  The breakpoints are
# the standard three-segment form of Schneider et al. (1996): air/lung below
# -1000..-98 HU, soft tissue -98..14 HU, and bone above.  A scanner-specific
# calibration replaces this for the cohort run; the values below are the
# published generic ones and are carried as provenance, never as a silent default.
_SCHNEIDER_BREAKPOINTS_HU = (-1000.0, -98.0, 14.0, 23.0, 100.0, 1600.0, 3000.0)
_SCHNEIDER_DENSITY_G_CM3 = (0.00121, 0.93, 1.03, 1.031, 1.076, 1.964, 2.8)


def hu_to_density(
    hu: np.ndarray,
    breakpoints_hu: Sequence[float] = _SCHNEIDER_BREAKPOINTS_HU,
    density_g_cm3: Sequence[float] = _SCHNEIDER_DENSITY_G_CM3,
    *,
    floor_g_cm3: float = 1.0e-4,
) -> np.ndarray:
    """Piecewise-linear HU -> mass density (Schneider stoichiometric calibration).

    Clamped at both ends and floored at ``floor_g_cm3`` because MC-GPU refuses a
    voxel of zero density.

    Reference: Schneider, Pedroni and Lomax, "The calibration of CT Hounsfield
    units for radiotherapy treatment planning", Phys. Med. Biol. 41 (1996) 111.
    """
    bp = np.asarray(breakpoints_hu, dtype=float)
    dn = np.asarray(density_g_cm3, dtype=float)
    if bp.shape != dn.shape:
        raise ValueError("breakpoints and densities must have the same length")
    if np.any(np.diff(bp) <= 0):
        raise ValueError("breakpoints must be strictly increasing")
    rho = np.interp(np.asarray(hu, dtype=float), bp, dn)
    return np.maximum(rho, floor_g_cm3)


# -- patient body contour and density map -----------------------------------
# The reconstruction fills everything outside the field of view with a padding
# value -- -2048 HU on the Canon/Toshiba series in this cohort, with no DICOM Pixel
# Padding attribute to declare it.  That region is not a material the photons travel
# through; it is nothing.  A density clamp maps an undeclared -2048 to air roughly by
# luck; masking to the body contour makes "outside the patient is air" explicit.

#: Above this HU is patient, below is air.  AAPM TG-220 uses -300 HU for the
#: water-equivalent-diameter contour, and the same threshold separates tissue from a
#: reconstruction's out-of-field fill (which vendors set anywhere from -1000 to
#: -3000 HU).
BODY_THRESHOLD_HU = -300.0

#: HU above the top Schneider breakpoint is outside the tissue calibration -- a metal
#: implant, dense contrast, or a beam-hardening artefact.  Reported rather than
#: silently clamped: clamping an in-body high value to cortical-bone density can
#: shield an organ and bias its dose downward, which no error message would reveal.
CALIBRATION_MAX_HU = 3000.0


def body_contour(volume_hu: np.ndarray, *, threshold_hu: float = BODY_THRESHOLD_HU) -> np.ndarray:
    """Patient outline for a ``(z, y, x)`` HU volume: threshold, largest component, fill.

    Threshold at ``threshold_hu``, keep the largest 3-D connected component (which
    drops the couch and any detached out-of-field speckle), then fill holes slice by
    slice so gas pockets and low-density lung *inside* the patient stay inside the
    contour. Slice-wise rather than 3-D because a 3-D fill bridges the trachea to the
    outside air through the top and bottom faces of the stack.
    """
    from scipy import ndimage

    vol = np.asarray(volume_hu)
    solid = vol > threshold_hu
    if not solid.any():
        return np.zeros(vol.shape, dtype=bool)
    labels, n = ndimage.label(solid)
    if n > 1:
        counts = np.bincount(labels.ravel())
        counts[0] = 0  # background label is not a component
        solid = labels == int(counts.argmax())
    filled = np.empty_like(solid)
    for i in range(solid.shape[0]):
        filled[i] = ndimage.binary_fill_holes(solid[i])
    return filled


def patient_density_map(
    volume_hu: np.ndarray,
    *,
    threshold_hu: float = BODY_THRESHOLD_HU,
    breakpoints_hu: Sequence[float] = _SCHNEIDER_BREAKPOINTS_HU,
    density_g_cm3: Sequence[float] = _SCHNEIDER_DENSITY_G_CM3,
    body: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """HU volume -> mass density, air outside the body contour, with a defect report.

    Returns ``(density, body, report)``. Everything outside the body contour is set
    to the calibration's air density; inside, the Schneider mapping applies. This is
    the density universe the Monte Carlo tracks through, so the out-of-field fill can
    no longer masquerade as material and cannot be silently clamped into it.

    ``report`` counts what the calibration cannot describe -- voxels above
    :data:`CALIBRATION_MAX_HU` *inside* the body (metal, dense contrast, artefact) --
    so those are visible for review rather than absorbed into cortical-bone density.
    """
    vol = np.asarray(volume_hu, dtype=float)
    if body is None:
        body = body_contour(vol, threshold_hu=threshold_hu)
    air = float(min(density_g_cm3))
    density = hu_to_density(vol, breakpoints_hu, density_g_cm3)
    density = np.where(body, density, air)

    top_hu = float(max(breakpoints_hu))
    over = (vol > CALIBRATION_MAX_HU) & body
    report = {
        "threshold_hu": threshold_hu,
        "air_density_g_cm3": air,
        "n_voxels": int(vol.size),
        "n_body_voxels": int(body.sum()),
        "body_fraction": round(float(body.mean()), 4),
        "hu_range": [round(float(vol.min()), 1), round(float(vol.max()), 1)],
        "calibration_max_hu": CALIBRATION_MAX_HU,
        "schneider_top_hu": top_hu,
        "n_above_calibration_in_body": int(over.sum()),
        "max_hu_in_body": round(float(vol[body].max()), 1) if body.any() else None,
        "note_above_calibration": (
            "voxels above the Schneider top breakpoint are held at its density "
            f"({max(density_g_cm3):g} g/cm^3); they are metal/contrast/artefact, not "
            "tissue, and are reported here rather than clamped silently"
        ),
    }
    return density, body, report

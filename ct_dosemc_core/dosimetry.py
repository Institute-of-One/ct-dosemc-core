"""Absorbed dose in a region, in mGy, with its Monte-Carlo uncertainty.

One function does the real work: take a voxel dose tally and a mask, return the
mass-weighted mean absorbed dose over that mask.  In Phase 1 the mask is a CTDI
ionisation-chamber position; in Phase 2 it is a TotalSegmentator organ.  The
arithmetic is identical, which is the point -- the organ doses of the flagship
paper come out of the same estimator the CTDI anchor validates.

Caveat carried in every provenance record: MC-GPU does not transport electrons,
so its tally is a *collision kerma* estimate.  At CT energies in soft tissue the
secondary-electron range is far below a voxel and charged-particle equilibrium
holds, so kerma and absorbed dose agree closely; at low-density interfaces and in
air-filled cavities they do not.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .mcgpu_io import DoseMap
from .provenance import Provenance, Value
from .source_model import EV_PER_G_TO_GY

__all__ = ["RegionDose", "region_dose"]


@dataclass(frozen=True)
class RegionDose:
    """Mass-weighted mean absorbed dose over a set of voxels."""

    name: str
    dose_mgy: float
    sigma_mgy: float
    mass_g: float
    n_voxels: int
    dose_ev_per_g_per_history: float
    n_histories: float
    partial_volume_weighted: bool = False
    """True when the region's mass used analytic occupancy rather than a
    voxel-centre-inside test.  Recorded because it changes the reported number."""

    @property
    def relative_sigma(self) -> float:
        return self.sigma_mgy / self.dose_mgy if self.dose_mgy else float("nan")

    def as_value(self, extra_assumptions: tuple[str, ...] = ()) -> Value:
        return Value(
            value=self.dose_mgy,
            unit="mGy",
            uncertainty=self.sigma_mgy,
            provenance=Provenance(
                formula=(
                    "D = sum_i(d_i * m_i)/sum_i(m_i) * N_hist * 1.602176634e-16 [Gy] * 1e3; "
                    "sigma_D = sqrt(sum_i (sigma_i * m_i)^2) / sum_i(m_i) * (same factors)"
                ),
                inputs={
                    "region": self.name,
                    "n_voxels": self.n_voxels,
                    "mass_g": self.mass_g,
                    "dose_eV_per_g_per_history": self.dose_ev_per_g_per_history,
                    "n_histories": self.n_histories,
                    "partial_volume_weighted": self.partial_volume_weighted,
                },
                assumptions=(
                    "MC-GPU tallies collision kerma (electrons are not transported); "
                    "charged-particle equilibrium is assumed",
                    "per-voxel Monte-Carlo uncertainties are combined as if independent, "
                    "which slightly understates the region uncertainty because voxel "
                    "tallies share histories",
                    (
                        "voxel masses use analytic volume occupancy, so a boundary "
                        "voxel contributes only the fraction of it inside the region; "
                        "the dose it contributes is still the whole-voxel average, "
                        "which leaves a second-order residual where the dose gradient "
                        "is steep"
                        if self.partial_volume_weighted
                        else "region volume is a voxel-centre-inside test, which "
                        "misstates the volume of a region comparable in size to the "
                        "voxel grid"
                    ),
                    *extra_assumptions,
                ),
                source="ct_dosemc_core.dosimetry.region_dose",
            ),
        )


def region_dose(
    name: str,
    dose_map: DoseMap,
    mask: np.ndarray,
    density_g_cm3: np.ndarray,
    n_histories: float,
    *,
    weights: np.ndarray | None = None,
) -> RegionDose:
    """Mass-weighted mean absorbed dose over ``mask``, in mGy.

    Parameters
    ----------
    dose_map:
        The MC-GPU tally, per history, already 1-sigma.
    mask:
        Boolean array over the *tally ROI*, same shape as ``dose_map``.
    density_g_cm3:
        Voxel densities over the same ROI.
    n_histories:
        Total photons the scan corresponds to -- from
        :func:`ct_dosemc_core.source_model.histories_for_mas`.
    weights:
        Optional per-voxel volume occupancy ``f_i`` in ``[0, 1]``, same shape as
        ``mask``, so that ``m_i = f_i * rho_i * v^3``.  ``None`` means every
        selected voxel counts whole, which is the historical behaviour.

        This is for regions with an **analytic** definition -- a scoring cylinder,
        an ionisation-chamber volume, a standard phantom -- where a
        voxel-centre-inside test misstates the volume and therefore the deposited
        energy.  It is **not** for segmentation masks: a TotalSegmentator organ
        mask *is* the definition of the organ, with no underlying analytic shape
        to be partially inside of, so weighting it would be meaningless.
    """
    if mask.shape != dose_map.shape_zyx:
        raise ValueError(f"mask {mask.shape} does not match the tally ROI {dose_map.shape_zyx}")
    if density_g_cm3.shape != mask.shape:
        raise ValueError("density array does not match the mask")
    n_vox = int(mask.sum())
    if n_vox == 0:
        raise ValueError(f"region {name!r} selects no voxels")

    dx, dy, dz = dose_map.voxel_size_cm
    voxel_volume = dx * dy * dz
    if weights is None:
        f = 1.0
    else:
        if weights.shape != mask.shape:
            raise ValueError("weights array does not match the mask")
        f = weights[mask]
        if np.any(f < 0.0) or np.any(f > 1.0):
            raise ValueError("occupancy weights must lie in [0, 1]")
    m = f * density_g_cm3[mask] * voxel_volume
    total_mass = float(np.sum(m))
    if total_mass <= 0.0:
        raise ValueError(f"region {name!r} has non-positive mass")

    d = dose_map.dose_ev_per_g[mask]
    s = dose_map.sigma_ev_per_g[mask]

    mean_ev_per_g = float(np.sum(d * m) / total_mass)
    sigma_ev_per_g = float(np.sqrt(np.sum((s * m) ** 2)) / total_mass)

    to_mgy = n_histories * EV_PER_G_TO_GY * 1.0e3
    return RegionDose(
        name=name,
        dose_mgy=mean_ev_per_g * to_mgy,
        sigma_mgy=sigma_ev_per_g * to_mgy,
        mass_g=total_mass,
        n_voxels=n_vox,
        dose_ev_per_g_per_history=mean_ev_per_g,
        n_histories=float(n_histories),
        partial_volume_weighted=weights is not None,
    )

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

import math
from dataclasses import dataclass

from .provenance import Provenance, Value

__all__ = ["BeamGeometry", "eV_per_g_to_mGy", "histories_for_mas", "mas_for_histories"]

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


def tube_current_profile(dataset) -> dict[str, object]:
    """Longitudinal tube-current modulation I(z) from a DICOM series.

    Reads X-Ray Tube Current (0018,1151) against Table Position / slice location,
    which is the same source IORN-004/006 used.  Phase 2 feeds this into the
    per-rotation mAs so that the simulated output tracks the real TCM.

    Not exercised by the Phase-1 CTDI anchor: the CTDI phantom is scanned at
    fixed mA by definition, so this is only reached once patient series are
    processed.
    """
    raise NotImplementedError(
        "TCM extraction lands with the Phase-2 cohort run; the Phase-1 CTDI "
        "anchor is a fixed-mA acquisition by definition (IEC 60601-2-44)."
    )

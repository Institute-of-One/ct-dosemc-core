"""X-ray tube spectra, via SpekPy.

SpekPy (BSD-3, Bujila/Poludniowski/Omar) is the only spectrum source used in this
project.  No proprietary spectrum table is shipped or transcribed.  Two things
come out of here:

* the **shape** of the spectrum, resampled onto MC-GPU's sampling grid, and
* its **absolute** normalisation -- photons per steradian per mAs -- which is the
  only thing that turns MC-GPU's ``eV/g per history`` into mGy.

SpekPy reports fluence at a reference distance ``z`` from the focal spot.  For a
point source the number of photons emitted per unit solid angle is

    N_Omega = Phi(z) * z^2          [photons / sr / mAs]

which is distance-independent, and that is the quantity :func:`Spectrum.photons_per_sr_per_mas`
hands to :mod:`ct_dosemc_core.source_model`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .provenance import Provenance, Value

__all__ = ["Filter", "Spectrum", "generate_spectrum", "write_mcgpu_spectrum"]

# MC-GPU v1.3 hard-codes MAX_ENERGY_BINS=256 for the source spectrum
# (vendor/MCGPU/MC-GPU_v1.3.h:68).  One slot is consumed by the terminating
# negative-probability line, so at most 255 bin edges may be written.
MCGPU_MAX_ENERGY_BINS = 256


@dataclass(frozen=True)
class Filter:
    """An added filter: element symbol and thickness in mm."""

    material: str
    thickness_mm: float

    def __str__(self) -> str:
        return f"{self.thickness_mm:g} mm {self.material}"


@dataclass(frozen=True)
class Spectrum:
    """A polyenergetic spectrum with its absolute normalisation."""

    kvp: float
    anode_angle_deg: float
    filters: tuple[Filter, ...]
    reference_distance_cm: float

    energy_kev: np.ndarray
    """Bin-centre energies [keV]."""

    differential_fluence: np.ndarray
    """Photons / cm^2 / keV / mAs at ``reference_distance_cm``."""

    hvl1_al_mm: float
    hvl2_al_mm: float
    mean_energy_kev: float
    total_fluence_per_mas: float
    """Photons / cm^2 / mAs at ``reference_distance_cm``."""

    air_kerma_ugy_per_mas: float
    """Air kerma at ``reference_distance_cm`` [uGy/mAs], from SpekPy."""

    spekpy_version: str

    @property
    def homogeneity_coefficient(self) -> float:
        """HVL1/HVL2 -- how polyenergetic the beam still is after filtration."""
        return self.hvl1_al_mm / self.hvl2_al_mm

    def photons_per_sr_per_mas(self) -> Value:
        """Photons emitted per steradian per mAs -- the absolute normalisation.

        Distance-independent for a point source, so this is what couples SpekPy
        to the Monte-Carlo history count.
        """
        z = self.reference_distance_cm
        n = self.total_fluence_per_mas * z * z
        return Value(
            value=float(n),
            unit="photons/sr/mAs",
            uncertainty=None,
            provenance=Provenance(
                formula="N_Omega = Phi(z) * z^2",
                inputs={
                    "Phi(z)_photons_per_cm2_per_mAs": float(self.total_fluence_per_mas),
                    "z_cm": z,
                },
                assumptions=(
                    "point focal spot (focal-spot size is not modelled)",
                    "inverse-square law with no air attenuation between focus and z",
                    "SpekPy fluence is reported per mAs at distance z",
                ),
                source=f"SpekPy {self.spekpy_version}; Poludniowski et al., "
                "Phys. Med. Biol. 54 (2009) 5293 and Bujila et al., Phys. Med. 75 (2020) 44",
            ),
        )

    def describe(self) -> dict[str, object]:
        return {
            "kvp": self.kvp,
            "anode_angle_deg": self.anode_angle_deg,
            "filtration": [str(f) for f in self.filters],
            "reference_distance_cm": self.reference_distance_cm,
            "hvl1_al_mm": self.hvl1_al_mm,
            "hvl2_al_mm": self.hvl2_al_mm,
            "homogeneity_coefficient": self.homogeneity_coefficient,
            "mean_energy_kev": self.mean_energy_kev,
            "total_fluence_photons_per_cm2_per_mas": self.total_fluence_per_mas,
            "air_kerma_ugy_per_mas": self.air_kerma_ugy_per_mas,
            "spekpy_version": self.spekpy_version,
        }


def generate_spectrum(
    kvp: float,
    filters: Sequence[Filter],
    *,
    anode_angle_deg: float = 7.0,
    bin_width_kev: float = 0.5,
    reference_distance_cm: float = 100.0,
    target: str = "W",
) -> Spectrum:
    """Generate a tube spectrum and its HVLs.

    ``filters`` is the *added* filtration; SpekPy's physics model supplies the
    inherent filtration of the tube itself.  The bowtie filter is deliberately
    NOT included here -- see :mod:`ct_dosemc_core.source_model` and
    ``docs/MC_SOURCE_MODEL.md``, because its geometry is vendor-proprietary and
    is handled separately as a documented approximation.
    """
    import spekpy as sp

    spek = sp.Spek(
        kvp=float(kvp),
        th=float(anode_angle_deg),
        dk=float(bin_width_kev),
        z=float(reference_distance_cm),
        targ=target,
        mas=1.0,
    )
    for f in filters:
        spek.filter(f.material, float(f.thickness_mm))

    energy_kev, diff_fluence = spek.get_spectrum(edges=False)
    return Spectrum(
        kvp=float(kvp),
        anode_angle_deg=float(anode_angle_deg),
        filters=tuple(filters),
        reference_distance_cm=float(reference_distance_cm),
        energy_kev=np.asarray(energy_kev, dtype=float),
        differential_fluence=np.asarray(diff_fluence, dtype=float),
        hvl1_al_mm=float(spek.get_hvl1()),
        hvl2_al_mm=float(spek.get_hvl2()),
        mean_energy_kev=float(spek.get_emean()),
        total_fluence_per_mas=float(spek.get_flu()),
        air_kerma_ugy_per_mas=float(spek.get_kerma()),
        spekpy_version=str(getattr(sp, "__version__", "unknown")),
    )


def write_mcgpu_spectrum(
    path: str | Path,
    spectrum: Spectrum,
    *,
    e_min_kev: float = 5.0,
    e_max_kev: float | None = None,
    n_bins: int | None = None,
) -> dict[str, object]:
    """Write ``spectrum`` in MC-GPU's ``.spc`` format.

    MC-GPU wants one line per bin holding the **lower** edge in eV and the
    emission probability of that bin, followed by a final line giving the top
    edge of the last bin with a negative probability as the terminator
    (vendor/MCGPU/MC-GPU_v1.3.cu:3442, ``init_energy_spectrum``).  Within a bin
    the sampled energy is uniform between consecutive edges, so the resampling
    below conserves the photon count per bin rather than the differential
    fluence at the bin centre.

    Returns a summary dict (bin count, energy range, conserved photon fraction)
    for the provenance record.
    """
    out = Path(path)
    e_max = float(spectrum.kvp if e_max_kev is None else e_max_kev)

    if n_bins is None:
        n_bins = MCGPU_MAX_ENERGY_BINS - 1
    n_bins = int(min(n_bins, MCGPU_MAX_ENERGY_BINS - 1))
    if n_bins < 2:
        raise ValueError("need at least 2 spectrum bins")

    edges_kev = np.linspace(float(e_min_kev), e_max, n_bins + 1)

    # SpekPy hands back bin centres; rebin by integrating the differential
    # fluence over each target bin.  Work on the SpekPy grid's own bin edges so
    # no photons are created or destroyed by the resampling.
    src_e = spectrum.energy_kev
    src_dk = float(np.median(np.diff(src_e))) if src_e.size > 1 else 1.0
    src_counts = spectrum.differential_fluence * src_dk  # photons/cm^2/mAs per SpekPy bin

    idx = np.digitize(src_e, edges_kev) - 1
    counts = np.zeros(n_bins, dtype=float)
    inside = (idx >= 0) & (idx < n_bins)
    np.add.at(counts, idx[inside], src_counts[inside])

    total = float(src_counts.sum())
    kept = float(counts.sum())
    if kept <= 0.0:
        raise ValueError(f"no photons fall in [{e_min_kev}, {e_max}] keV")
    prob = counts / kept

    lines = [
        "# MC-GPU v1.3 energy spectrum, written by ct_dosemc_core",
        f"# tube: {spectrum.kvp:g} kVp, {spectrum.anode_angle_deg:g} deg anode, "
        f"filtration {', '.join(str(f) for f in spectrum.filters) or 'none added'}",
        f"# SpekPy {spectrum.spekpy_version}; HVL1 = {spectrum.hvl1_al_mm:.4f} mm Al",
        "# columns: lower bin energy [eV]   relative probability",
        "#          (a negative probability terminates the spectrum)",
    ]
    for i in range(n_bins):
        lines.append(f"{edges_kev[i] * 1e3:.4f}   {prob[i]:.8e}")
    lines.append(f"{edges_kev[-1] * 1e3:.4f}   -1")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="ascii")

    return {
        "path": str(out),
        "n_bins": n_bins,
        "e_min_kev": float(edges_kev[0]),
        "e_max_kev": float(edges_kev[-1]),
        "photon_fraction_retained": kept / total if total > 0 else 0.0,
        "mean_energy_kev_after_rebinning": float(
            np.sum(prob * 0.5 * (edges_kev[:-1] + edges_kev[1:]))
        ),
    }

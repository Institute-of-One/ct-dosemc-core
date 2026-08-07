"""Spectra, and the MC-GPU spectrum file they are written into.

The file format is unforgiving -- a wrong terminator or one bin too many and the
engine either exits or, worse, silently samples the wrong energies -- so the
written file is parsed back and checked against MC-GPU's parser
(``MC-GPU_v1.3.cu:3442``).
"""

from __future__ import annotations

import numpy as np
import pytest

from ct_dosemc_core.spectra import (
    MCGPU_MAX_ENERGY_BINS,
    Filter,
    generate_spectrum,
    write_mcgpu_spectrum,
)

spekpy = pytest.importorskip("spekpy", reason="SpekPy supplies every spectrum")


@pytest.fixture(scope="module")
def spectrum_120kv():
    return generate_spectrum(120.0, (Filter("Al", 5.0),))


def _read_back(path):
    """Parse a .spc the way MC-GPU does: lines of (lower edge eV, probability),
    terminated by a negative probability."""
    edges, probs = [], []
    for line in path.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        e, p = (float(v) for v in line.split()[:2])
        edges.append(e)
        probs.append(p)
        if p < 0:
            break
    return np.array(edges), np.array(probs)


def test_filtration_hardens_the_beam(spectrum_120kv):
    soft = generate_spectrum(120.0, (Filter("Al", 2.0),))
    hard = generate_spectrum(120.0, (Filter("Al", 10.0),))
    assert soft.hvl1_al_mm < spectrum_120kv.hvl1_al_mm < hard.hvl1_al_mm
    assert soft.mean_energy_kev < hard.mean_energy_kev
    # ...and costs fluence
    assert hard.total_fluence_per_mas < soft.total_fluence_per_mas


def test_hvl2_exceeds_hvl1_for_a_polyenergetic_beam(spectrum_120kv):
    assert spectrum_120kv.hvl2_al_mm > spectrum_120kv.hvl1_al_mm
    assert 0.5 < spectrum_120kv.homogeneity_coefficient < 1.0


def test_a_120kv_beam_has_a_plausible_hvl(spectrum_120kv):
    # Diagnostic CT at 120 kVp sits in the 5-10 mm Al band; outside it, either the
    # filtration or the tube model is wrong.
    assert 5.0 < spectrum_120kv.hvl1_al_mm < 10.0
    assert 40.0 < spectrum_120kv.mean_energy_kev < 80.0


def test_no_photon_exceeds_the_tube_potential(spectrum_120kv):
    assert spectrum_120kv.energy_kev.max() <= 120.0


def test_photons_per_sr_is_distance_independent():
    near = generate_spectrum(120.0, (Filter("Al", 5.0),), reference_distance_cm=50.0)
    far = generate_spectrum(120.0, (Filter("Al", 5.0),), reference_distance_cm=150.0)
    assert near.photons_per_sr_per_mas().value == pytest.approx(
        far.photons_per_sr_per_mas().value, rel=1e-6
    )


def test_written_spectrum_obeys_the_mcgpu_format(tmp_path, spectrum_120kv):
    path = tmp_path / "spectrum.spc"
    summary = write_mcgpu_spectrum(path, spectrum_120kv, e_min_kev=5.0)
    edges, probs = _read_back(path)

    assert probs[-1] < 0, "the spectrum must end with a negative probability"
    assert np.all(probs[:-1] >= 0)
    assert np.all(np.diff(edges) > 0), "MC-GPU rejects non-increasing bin energies"
    assert len(edges) <= MCGPU_MAX_ENERGY_BINS, "MC-GPU compiles with MAX_ENERGY_BINS=256"
    assert probs[:-1].sum() == pytest.approx(1.0)
    assert edges[0] == pytest.approx(5000.0)
    assert edges[-1] == pytest.approx(120000.0)
    assert len(edges) == summary["n_bins"] + 1


def test_rebinning_conserves_the_photon_count(tmp_path, spectrum_120kv):
    summary = write_mcgpu_spectrum(tmp_path / "s.spc", spectrum_120kv, e_min_kev=5.0)
    # Only photons below 5 keV are discarded, and a 120 kVp beam with 5 mm Al has
    # essentially none.
    assert summary["photon_fraction_retained"] > 0.999


def test_rebinning_preserves_the_mean_energy(tmp_path, spectrum_120kv):
    summary = write_mcgpu_spectrum(tmp_path / "s.spc", spectrum_120kv, e_min_kev=5.0)
    assert summary["mean_energy_kev_after_rebinning"] == pytest.approx(
        spectrum_120kv.mean_energy_kev, rel=0.01
    )


def test_bin_count_is_capped_at_the_engine_limit(tmp_path, spectrum_120kv):
    summary = write_mcgpu_spectrum(tmp_path / "s.spc", spectrum_120kv, n_bins=10_000)
    assert summary["n_bins"] == MCGPU_MAX_ENERGY_BINS - 1


def test_an_empty_energy_window_is_an_error(tmp_path, spectrum_120kv):
    with pytest.raises(ValueError, match="no photons"):
        write_mcgpu_spectrum(
            tmp_path / "s.spc", spectrum_120kv, e_min_kev=200.0, e_max_kev=300.0
        )

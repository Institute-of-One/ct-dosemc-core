"""Engine array bounds are checked before MC-GPU, not discovered in its log."""

from __future__ import annotations

from pathlib import Path

import pytest

from ct_dosemc_core.engine_limits import (
    EngineCapacityError,
    assert_engine_can_run,
    engine_limits,
)
from ct_dosemc_core.patient import default_tissue_groups

REPO = Path(__file__).resolve().parent.parent
MATERIALS = REPO / "materials"
HEADER = REPO / "vendor" / "build" / "MC-GPU_v1.3.h"


@pytest.mark.skipif(not HEADER.is_file(), reason="engine header not copied")
def test_patched_header_covers_150kev_tables():
    limits = engine_limits()
    assert limits["MAX_SHELLS"] >= 40
    assert limits["MAX_ENERGYBINS_RAYLEIGH"] >= 29002
    assert limits["MAX_MATERIALS"] == 15


@pytest.mark.skipif(not (MATERIALS / "air_5-150keV.mcgpu.gz").is_file(), reason="150 keV tables missing")
def test_140kvp_patient_set_fits_the_patched_engine():
    files = [MATERIALS / g.material_file for g in default_tissue_groups(energy_tag="5-150keV")]
    limits = assert_engine_can_run(files, spectrum_emax_kev=140.0)
    assert limits["MAX_ENERGYBINS_RAYLEIGH"] >= 29002


@pytest.mark.skipif(not (MATERIALS / "air_5-120keV.mcgpu.gz").is_file(), reason="120 keV tables missing")
def test_140kvp_is_rejected_on_120kev_tables_before_the_gpu():
    files = [MATERIALS / g.material_file for g in default_tissue_groups(energy_tag="5-120keV")]
    with pytest.raises(EngineCapacityError, match="140 kVp"):
        assert_engine_can_run(files, spectrum_emax_kev=140.0)

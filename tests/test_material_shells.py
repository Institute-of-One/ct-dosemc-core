"""Schneider bone mixes must fit in the patched MC-GPU Compton-shell table.

Upstream MAX_SHELLS is 30. ICRP soft tissue uses all 30; the volume-fraction
mixes with cortical bone emit up to 32. The build copies the header and raises
the bound to 40 (array size only). This test fails if a newly generated material
exceeds that bound, rather than waiting for MC-GPU to exit(-2) mid-patient.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

import pytest

MATERIALS = Path(__file__).resolve().parent.parent / "materials"
PATCHED_HEADER = Path(__file__).resolve().parent.parent / "vendor" / "build" / "MC-GPU_v1.3.h"
SHELL_RE = re.compile(r"\[NUMBER OF SHELLS\][^\n]*\n#\s*(\d+)")
DEFINE_RE = re.compile(r"#define\s+MAX_SHELLS\s+(\d+)")


def _shell_count(path: Path) -> int:
    text = gzip.open(path, "rt", encoding="latin-1").read()
    match = SHELL_RE.search(text)
    if match is None:
        raise AssertionError(f"no [NUMBER OF SHELLS] in {path.name}")
    return int(match.group(1))


@pytest.mark.skipif(not any(MATERIALS.glob("*.mcgpu.gz")), reason="materials/ not generated")
def test_every_material_fits_in_max_shells():
    files = sorted(MATERIALS.glob("*.mcgpu.gz"))
    cap = 40
    if PATCHED_HEADER.is_file():
        match = DEFINE_RE.search(PATCHED_HEADER.read_text(encoding="latin-1"))
        if match:
            cap = int(match.group(1))
    counts = {p.name: _shell_count(p) for p in files}
    over = {n: c for n, c in counts.items() if c > cap}
    assert not over, f"Compton shells exceed MAX_SHELLS={cap}: {over}"
    # the mixes that forced the bump: keep the fact on record
    bone = {n: c for n, c in counts.items() if n.startswith("bone_")}
    if bone:
        assert max(bone.values()) > 30


@pytest.mark.skipif(not (MATERIALS / "PROVENANCE.json").is_file(), reason="materials/ not generated")
def test_every_material_fits_in_max_energy_bins():
    """5-150 keV at 5 eV step is 29002 bins; upstream Rayleigh table is 25005."""
    import json

    cap = 32000
    if PATCHED_HEADER.is_file():
        match = re.search(
            r"#define\s+MAX_ENERGYBINS_RAYLEIGH\s+(\d+)",
            PATCHED_HEADER.read_text(encoding="latin-1"),
        )
        if match:
            cap = int(match.group(1))
    prov = json.loads((MATERIALS / "PROVENANCE.json").read_text(encoding="utf-8"))
    over = {}
    for rec in prov["materials"]:
        lo, hi = rec["energy_range_ev"]
        step = int(rec["energy_step_ev"])
        n = (int(hi) - int(lo)) // step + 1
        if n > cap:
            over[rec["file"]] = n
    assert not over, f"Rayleigh bins exceed MAX_ENERGYBINS_RAYLEIGH={cap}: {over}"
    wide = [r for r in prov["materials"] if r["energy_range_ev"][1] >= 150000]
    if wide:
        n = (int(wide[0]["energy_range_ev"][1]) - int(wide[0]["energy_range_ev"][0])) // int(wide[0]["energy_step_ev"]) + 1
        assert n > 25005

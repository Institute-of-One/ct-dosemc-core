"""Refuse the GPU if this job will not fit in the engine arrays.

The patient path already died three times on capacity, each time after writing
inputs: Compton shells (MAX_SHELLS), spectrum vs table emax, Rayleigh bins
(MAX_ENERGYBINS_RAYLEIGH). Those bounds live in the copied header
``vendor/build/MC-GPU_v1.3.h``. Read them here and fail before ``run_mcgpu``.
This is not a physics change.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PATCHED_HEADER = REPO / "vendor" / "build" / "MC-GPU_v1.3.h"
UPSTREAM_HEADER = REPO / "vendor" / "MCGPU" / "MC-GPU_v1.3.h"
MATERIALS_DIR = REPO / "materials"
PROVENANCE = MATERIALS_DIR / "PROVENANCE.json"

_SHELL_RE = re.compile(r"\[NUMBER OF SHELLS\][^\n]*\n#\s*(\d+)")
_DEFINE_RE = re.compile(r"#define\s+(MAX_SHELLS|MAX_ENERGYBINS_RAYLEIGH|MAX_MATERIALS)\s+(\d+)")


class EngineCapacityError(SystemExit):
    """This job will not fit in the compiled MC-GPU arrays."""


def engine_limits(header: Path | None = None) -> dict[str, int]:
    path = header or (PATCHED_HEADER if PATCHED_HEADER.is_file() else UPSTREAM_HEADER)
    text = path.read_text(encoding="latin-1")
    found = {name: int(val) for name, val in _DEFINE_RE.findall(text)}
    for key in ("MAX_SHELLS", "MAX_ENERGYBINS_RAYLEIGH", "MAX_MATERIALS"):
        if key not in found:
            raise EngineCapacityError(f"{key} not found in {path}")
    return found


def compton_shells(path: Path) -> int:
    text = gzip.open(path, "rt", encoding="latin-1").read()
    match = _SHELL_RE.search(text)
    if match is None:
        raise EngineCapacityError(f"no [NUMBER OF SHELLS] in {path.name}")
    return int(match.group(1))


def _provenance_by_file() -> dict[str, dict]:
    if not PROVENANCE.is_file():
        return {}
    payload = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    return {str(row["file"]): row for row in payload.get("materials", [])}


def energy_bins(path: Path, records: dict[str, dict] | None = None) -> tuple[int, int, int]:
    """Return (n_bins, e_min_ev, e_max_ev) for one material file."""
    rec = (records or _provenance_by_file()).get(path.name)
    if rec is None:
        raise EngineCapacityError(f"{path.name} is not in {PROVENANCE}")
    lo, hi = (int(x) for x in rec["energy_range_ev"])
    step = int(rec["energy_step_ev"])
    n = (hi - lo) // step + 1
    return n, lo, hi


def assert_engine_can_run(
    material_files: list[Path],
    *,
    spectrum_emax_kev: float,
    header: Path | None = None,
) -> dict[str, int]:
    """Raise :class:`EngineCapacityError` if MC-GPU would exit on this job."""
    limits = engine_limits(header)
    if len(material_files) > limits["MAX_MATERIALS"]:
        raise EngineCapacityError(
            f"{len(material_files)} materials > MAX_MATERIALS={limits['MAX_MATERIALS']}"
        )
    records = _provenance_by_file()
    spectrum_ev = int(round(float(spectrum_emax_kev) * 1000.0))
    for path in material_files:
        if not path.is_file():
            raise EngineCapacityError(f"material file missing: {path}")
        shells = compton_shells(path)
        if shells > limits["MAX_SHELLS"]:
            raise EngineCapacityError(
                f"{path.name} has {shells} Compton shells; "
                f"MAX_SHELLS={limits['MAX_SHELLS']}. Capacity bump, not a spectrum cut."
            )
        n_bins, e_min, e_max = energy_bins(path, records)
        if n_bins > limits["MAX_ENERGYBINS_RAYLEIGH"]:
            raise EngineCapacityError(
                f"{path.name} has {n_bins} energy bins; "
                f"MAX_ENERGYBINS_RAYLEIGH={limits['MAX_ENERGYBINS_RAYLEIGH']}. "
                "Bump the header array; do not coarsen the 5 eV grid."
            )
        if spectrum_ev < e_min or spectrum_ev > e_max:
            raise EngineCapacityError(
                f"{spectrum_emax_kev:.0f} kVp spectrum ({spectrum_ev} eV) is outside "
                f"{path.name} tabulated range {e_min}-{e_max} eV. "
                "Generate wider tables; do not truncate the spectrum."
            )
    return limits

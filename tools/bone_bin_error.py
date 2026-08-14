"""Measure the bone table's discretization error in μ(60 keV). No Monte Carlo.

For each HU on a 1-HU grid from 100 to 3000, compare
    (a) the continuous volume-fraction mix at that HU
    (b) the binned mix (bin-midpoint volume fraction; default 11 bins, √f spacing)
and report max |μ_b − μ_a| / μ_a at 60 keV. NIST mass-attenuation coefficients
via SpekPy; endpoint compositions from PENDBASE (ICRP soft tissue and cortical bone).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ct_dosemc_core.patient import N_BONE_BINS, bone_discretization_error  # noqa: E402
from ct_dosemc_core.provenance import environment  # noqa: E402

SOFT_ENDPOINT_ID = 262
BONE_ENDPOINT_ID = 120
PDCOMPOS = REPO / "vendor" / "MCGPU_materials" / "PENDBASE_photons" / "pdcompos.p06"


def _pendbase_composition(pendbase_id: int) -> tuple[str, float, list[tuple[int, float]]]:
    lines = PDCOMPOS.read_text(encoding="latin-1").splitlines()
    i = 15
    while i < len(lines):
        header = lines[i]
        try:
            iord = int(header[:3])
        except ValueError:
            i += 1
            continue
        nelem_tok = lines[i + 1].split()
        nelem = int(nelem_tok[0])
        density = float(nelem_tok[3])
        elems = []
        for j in range(nelem):
            z_tok = lines[i + 2 + j].split()
            elems.append((int(z_tok[0]), float(z_tok[1])))
        if iord == pendbase_id:
            return header[5:].strip(), density, elems
        i += 2 + nelem
    raise SystemExit(f"PENDBASE id {pendbase_id} not found in {PDCOMPOS}")


def main() -> int:
    _, rho_soft, soft = _pendbase_composition(SOFT_ENDPOINT_ID)
    _, rho_bone, bone = _pendbase_composition(BONE_ENDPOINT_ID)
    report = bone_discretization_error(
        soft, bone, rho_soft, rho_bone, n_bins=N_BONE_BINS, energy_kev=60.0, n_samples=2901
    )
    report["endpoints"] = {
        "soft_tissue_pendbase_id": SOFT_ENDPOINT_ID,
        "cortical_bone_pendbase_id": BONE_ENDPOINT_ID,
        "rho_soft_g_cm3": rho_soft,
        "rho_cortical_g_cm3": rho_bone,
    }
    report["environment"] = environment(REPO)
    out = REPO / "results" / "phase2_cohort" / "bone_bin_error.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"{report['n_bins']} bins ({report.get('spacing', '?')}), μ(60 keV): "
        f"max |Δμ/μ| = {report['max_relative_error_pct']}% at HU {report['at_hu']:.0f}"
    )
    print(f"  median {report['median_relative_error_pct']}%")
    print(f"  at soft boundary (HU {report['hu_range'][0]:.0f}): {report['soft_boundary_relative_error_pct']}%")
    print(f"  f_cont={report['f_continuous']:.4f}  f_bin={report['f_binned']:.4f}")
    print(f"  w_cont={report['w_bone_continuous']:.4f}  w_bin={report['w_bone_binned']:.4f}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

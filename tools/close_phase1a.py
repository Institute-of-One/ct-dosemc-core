"""Phase-1a close: re-derive (a), (b), Δ_length and the uncertainty budget.

Every number in results/phase1a_close.json is computed here from the replica
JSON and the TG-195 per-code values already stored beside G2. A hand-edited
close file fails tests/test_phase1a_close.py.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RESULTS = REPO / "results"
L40 = RESULTS / "phase1a_G4_replica_uncertainty_120kvp_second_K4_L40.json"
L160 = RESULTS / "phase1a_G4_replica_uncertainty_120kvp_second_K4_L160.json"
G2_REF = RESULTS / "phase1a_G2_G2_anchor_air50.json"
OUT = RESULTS / "phase1a_close.json"

# TG-195 §3.4: reference values carry up to 1% statistical uncertainty per VOI.
# 36 discrete angles → 1%/√36.
PENELOPE_36ANGLE_REL = 0.01 / math.sqrt(36)
N_REPLICAS = 10
SD_OF_SD_REL = 1.0 / math.sqrt(2.0 * (N_REPLICAS - 1))  # ±23.57% ≈ ±24%
ANCHOR_SEM_LIMIT = 0.0015  # 0.15%


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _rel(sd: float, mean: float) -> float:
    return sd / mean


def _sem_rel(sd: float, mean: float, n: int = N_REPLICAS) -> float:
    return _rel(sd, mean) / math.sqrt(n)


def _pct(x: float) -> float:
    return 100.0 * x


def close() -> dict:
    l40 = _load(L40)
    l160 = _load(L160)
    g2 = _load(G2_REF)
    codes = g2["comparison_with_tg195"]

    assert l40["n_replicas"] == N_REPLICAS and l160["n_replicas"] == N_REPLICAS
    assert l40["source_route"] == "B" and l160["source_route"] == "A"

    criterion_a = {}
    for voi in ("center", "perimeter"):
        c = l40["comparison"][voi]
        mean, sd = c["mean_ev_per_photon"], c["replica_sample_sd"]
        rel_sd = _rel(sd, mean)
        sem = _sem_rel(sd, mean)
        criterion_a[voi] = {
            "mean_ev_per_photon": mean,
            "replica_sample_sd": sd,
            "replica_relative_sd": rel_sd,
            "anchor_sem_relative": sem,
            "sd_of_the_sd_relative": SD_OF_SD_REL,
            "meets_0p15pct": sem <= ANCHOR_SEM_LIMIT,
            "source_route": "B",
            "n_replicas": N_REPLICAS,
            "engine_invocations_per_replica": int(l40["engine_invocations_per_replica"][0]),
        }

    criterion_b = {}
    for voi in ("center", "perimeter"):
        ours = l40["comparison"][voi]["mean_ev_per_photon"]
        per = codes[voi]["per_code"]
        pen = per["Penelope"]["reference"]
        mean4 = codes[voi]["reference_mean"]
        d_pen_vs_mean = pen / mean4 - 1.0
        d_ours_vs_pen = ours / pen - 1.0
        d_ours_vs_mean = ours / mean4 - 1.0
        product = (1.0 + d_pen_vs_mean) * (1.0 + d_ours_vs_pen) - 1.0
        sem = criterion_a[voi]["anchor_sem_relative"]
        sigma_comb = math.sqrt(sem**2 + PENELOPE_36ANGLE_REL**2)
        abs_vs_pen = abs(d_ours_vs_pen)
        criterion_b[voi] = {
            "ours_ev_per_photon": ours,
            "penelope_ev_per_photon": pen,
            "four_code_mean_ev_per_photon": mean4,
            "ours_minus_penelope_relative": d_ours_vs_pen,
            "abs_ours_minus_penelope_relative": abs_vs_pen,
            "sigma_comb_relative": sigma_comb,
            "n_sigma_vs_penelope": abs_vs_pen / sigma_comb,
            "reported_not_gated": True,
            "decomposition": {
                "penelope_vs_four_code_mean": d_pen_vs_mean,
                "ours_vs_penelope": d_ours_vs_pen,
                "product_equals_ours_vs_mean": product,
                "ours_vs_four_code_mean": d_ours_vs_mean,
                "identity_residual": product - d_ours_vs_mean,
            },
            "per_code_ours_minus_reference": {
                name: ours / rec["reference"] - 1.0 for name, rec in per.items()
            },
        }

    delta_length = {}
    for voi in ("center", "perimeter"):
        m40 = l40["comparison"][voi]["mean_ev_per_photon"]
        m160 = l160["comparison"][voi]["mean_ev_per_photon"]
        sd40 = l40["comparison"][voi]["replica_sample_sd"]
        sd160 = l160["comparison"][voi]["replica_sample_sd"]
        diff = m160 - m40
        sigma_abs = math.sqrt(sd40**2 / N_REPLICAS + sd160**2 / N_REPLICAS)
        rel = diff / m40
        sigma_rel = sigma_abs / m40
        n_sigma = abs(diff) / sigma_abs if sigma_abs else float("nan")
        delta_length[voi] = {
            "L40_mean": m40,
            "L160_mean": m160,
            "L160_minus_L40": diff,
            "relative_to_L40": rel,
            "sigma_abs": sigma_abs,
            "sigma_relative": sigma_rel,
            "n_sigma": n_sigma,
            "distinguishable": n_sigma >= 2.0,
            "L40_source_route": "B",
            "L160_source_route": "A",
        }

    omega_excess = g2["geometry"]["omega_excess_fraction"]
    voxel_first_test = 0.0002  # 2.5 mm → 1.25 mm moved first-test segment 1 by 0.02%
    n_bins = int(g2["spectrum"]["n_bins"])
    spectrum_255 = 0.0  # cap not exercised when n_bins < 256

    budget = {}
    for voi in ("center", "perimeter"):
        terms = {
            "anchor_sem": {
                "kind": "measured",
                "relative": criterion_a[voi]["anchor_sem_relative"],
                "note": "L40 K=4 replica SD / √10 (Route B)",
            },
            "penelope_36angle": {
                "kind": "declared",
                "relative": PENELOPE_36ANGLE_REL,
                "note": "TG-195 ≤1% per VOI over √36 discrete angles",
            },
            "delta_length": {
                "kind": "measured",
                "relative": abs(delta_length[voi]["relative_to_L40"]),
                "sigma_of_the_delta": delta_length[voi]["sigma_relative"],
                "note": "L160 − L40; 40 cm is the production phantom length",
            },
            "subfan_omega_k4": {
                "kind": "analytic",
                "relative": omega_excess,
                "note": "solid-angle excess of K=4 rectangular sub-fans vs the specified fan",
            },
            "voxel_2p5mm": {
                "kind": "declared_upper_bound",
                "relative": voxel_first_test,
                "measured_on": "first test, 2.5 mm → 1.25 mm, segment 1",
                "second_test": "unmeasured",
            },
            "spectrum_255bin": {
                "kind": "declared",
                "relative": spectrum_255,
                "note": (
                    f"TG-195 120 kVp table has {n_bins} bins "
                    "(G2_anchor_air50); MAX_ENERGY_BINS=256 is not exercised"
                ),
            },
        }
        sigma_total = math.sqrt(sum(t["relative"] ** 2 for t in terms.values()))
        abs_vs_pen = criterion_b[voi]["abs_ours_minus_penelope_relative"]
        budget[voi] = {
            "terms": terms,
            "sigma_total": sigma_total,
            "abs_ours_minus_penelope": abs_vs_pen,
            "abs_ours_minus_penelope_over_sigma_total": abs_vs_pen / sigma_total,
        }

    a_pass = all(criterion_a[v]["meets_0p15pct"] for v in ("center", "perimeter"))
    length_indistinguishable = all(
        not delta_length[v]["distinguishable"] for v in ("center", "perimeter")
    )
    return {
        "gate": "Phase 1a close — TG-195 Case 4, production configuration",
        "configuration": {
            "beam": "120kvp",
            "test": "second",
            "n_projections": 36,
            "n_sub_fans": 4,
            "histories": 2.0e8,
            "voxel_size_cm": 0.25,
            "air_margin_cm": 50.0,
            "L40_source_route": "B",
            "L160_source_route": "A",
            "bit_identity": "results/phase1a_source_routes.json",
        },
        "criterion_a": {
            "requirement": "anchor uncertainty = replica SD/√10 ≤ 0.15%",
            "sd_of_the_sd_relative": SD_OF_SD_REL,
            "sd_precision_note": "sample SD from N=10 is known to ±1/√(2(N-1)) ≈ ±24%",
            "vois": criterion_a,
            "met": a_pass,
        },
        "criterion_b": {
            "requirement": "|ours − PENELOPE| reported with σ_comb; not a gate",
            "yardstick": "PENELOPE (shared PENDBASE photon cross-sections), chosen before looking at which code agrees best",
            "sigma_comb": "sqrt(anchor_SEM^2 + (1%/√36)^2)",
            "vois": criterion_b,
        },
        "delta_length": {
            "replaces": "noise-buried 0.4% upper bound from the first-test length scan",
            "vois": delta_length,
            "conclusion": (
                "40 cm is indistinguishable from 160 cm at the second-test VOIs "
                "(both |Δ| < 2σ of the two ten-replica means)"
                if length_indistinguishable
                else "40 cm differs from 160 cm at ≥2σ on at least one VOI"
            ),
            "indistinguishable": length_indistinguishable,
        },
        "uncertainty_budget": budget,
        "verdict": {
            "phase1a_closed": a_pass,
            "criterion_a": "PASS" if a_pass else "OPEN",
            "criterion_b": "reported, not gated",
            "delta_length": (
                "measured; 40 cm indistinguishable from 160 cm"
                if length_indistinguishable
                else "measured; see n_sigma"
            ),
            "patient_dose_unlocked": a_pass,
            "usable_as_anchor": a_pass,
            "note": (
                "The deliverable is how far the numbers agree and what was assumed, "
                "not whether a self-defined threshold was crossed. (b) is a finding."
            ),
        },
        "evidence": {
            "L40": str(L40.relative_to(REPO)).replace("\\", "/"),
            "L160": str(L160.relative_to(REPO)).replace("\\", "/"),
            "tg195_per_code": str(G2_REF.relative_to(REPO)).replace("\\", "/"),
        },
    }


def main() -> int:
    payload = close()
    from ct_dosemc_core.provenance import write_results

    write_results(OUT, payload)
    a = payload["criterion_a"]
    print(
        f"(a) centre SEM {_pct(a['vois']['center']['anchor_sem_relative']):.4f}%  "
        f"perim {_pct(a['vois']['perimeter']['anchor_sem_relative']):.4f}%  "
        f"{'PASS' if a['met'] else 'OPEN'}"
    )
    for voi in ("center", "perimeter"):
        b = payload["criterion_b"]["vois"][voi]
        print(
            f"(b) {voi}: |ours−PENELOPE|={_pct(b['abs_ours_minus_penelope_relative']):.3f}%  "
            f"σ_comb={_pct(b['sigma_comb_relative']):.3f}%  "
            f"{b['n_sigma_vs_penelope']:.2f}σ"
        )
        d = b["decomposition"]
        print(
            f"    decomp: PENELOPE vs mean {_pct(d['penelope_vs_four_code_mean']):+.3f}%  "
            f"× ours vs PENELOPE {_pct(d['ours_vs_penelope']):+.3f}%  "
            f"→ ours vs mean {_pct(d['ours_vs_four_code_mean']):+.3f}%"
        )
    for voi in ("center", "perimeter"):
        dl = payload["delta_length"]["vois"][voi]
        print(
            f"ΔL {voi}: {_pct(dl['relative_to_L40']):+.4f}%  "
            f"σ={_pct(dl['sigma_relative']):.4f}%  {dl['n_sigma']:.2f}σ"
        )
    for voi in ("center", "perimeter"):
        u = payload["uncertainty_budget"][voi]
        print(
            f"budget {voi}: σ_total={_pct(u['sigma_total']):.3f}%  "
            f"|ours−PENELOPE|/σ_total={u['abs_ours_minus_penelope_over_sigma_total']:.2f}"
        )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

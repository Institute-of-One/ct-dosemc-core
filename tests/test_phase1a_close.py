"""Anti-fabrication for the Phase-1a close: re-derive (a), (b), Δ_length, RSS.

The close file is not a typed-in verdict. Every figure is recomputed here from
the L40/L160 replica JSON and the TG-195 per-code values stored beside G2.
A hand-edited close file fails this module.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

RESULTS = Path(__file__).resolve().parent.parent / "results"
CLOSE = RESULTS / "phase1a_close.json"
L40 = RESULTS / "phase1a_G4_replica_uncertainty_120kvp_second_K4_L40.json"
L160 = RESULTS / "phase1a_G4_replica_uncertainty_120kvp_second_K4_L160.json"
G2 = RESULTS / "phase1a_G2_G2_anchor_air50.json"

N = 10
PENELOPE_36 = 0.01 / math.sqrt(36)
SD_OF_SD = 1.0 / math.sqrt(2.0 * (N - 1))
VOXEL_FIRST_TEST = 0.0002


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


pytestmark = pytest.mark.skipif(
    not (CLOSE.is_file() and L40.is_file() and L160.is_file() and G2.is_file()),
    reason="Phase-1a close inputs not on disk yet",
)


@pytest.fixture(scope="module")
def close() -> dict:
    return _load(CLOSE)


@pytest.fixture(scope="module")
def l40() -> dict:
    return _load(L40)


@pytest.fixture(scope="module")
def l160() -> dict:
    return _load(L160)


@pytest.fixture(scope="module")
def g2() -> dict:
    return _load(G2)


def test_criterion_a_is_replica_sd_over_sqrt_n(close, l40):
    for voi in ("center", "perimeter"):
        mean = l40["comparison"][voi]["mean_ev_per_photon"]
        sd = l40["comparison"][voi]["replica_sample_sd"]
        sem = (sd / mean) / math.sqrt(N)
        got = close["criterion_a"]["vois"][voi]
        assert got["mean_ev_per_photon"] == pytest.approx(mean, rel=1e-15)
        assert got["replica_sample_sd"] == pytest.approx(sd, rel=1e-15)
        assert got["anchor_sem_relative"] == pytest.approx(sem, rel=1e-15)
        assert got["sd_of_the_sd_relative"] == pytest.approx(SD_OF_SD, rel=1e-15)
        assert got["meets_0p15pct"] is (sem <= 0.0015)
    assert close["criterion_a"]["met"] is True
    assert close["criterion_a"]["vois"]["center"]["source_route"] == "B"


def test_criterion_b_uses_the_n10_mean_not_the_single_g2_run(close, l40, g2):
    for voi in ("center", "perimeter"):
        ours = l40["comparison"][voi]["mean_ev_per_photon"]
        per = g2["comparison_with_tg195"][voi]["per_code"]
        pen = per["Penelope"]["reference"]
        mean4 = g2["comparison_with_tg195"][voi]["reference_mean"]
        d_ours_pen = ours / pen - 1.0
        d_pen_mean = pen / mean4 - 1.0
        d_ours_mean = ours / mean4 - 1.0
        product = (1.0 + d_pen_mean) * (1.0 + d_ours_pen) - 1.0
        sem = close["criterion_a"]["vois"][voi]["anchor_sem_relative"]
        sigma_comb = math.sqrt(sem**2 + PENELOPE_36**2)
        b = close["criterion_b"]["vois"][voi]
        assert b["ours_ev_per_photon"] == pytest.approx(ours, rel=1e-15)
        assert b["ours_ev_per_photon"] != pytest.approx(
            g2["comparison_with_tg195"][voi]["ours_ev_per_photon"], rel=1e-12
        )
        assert b["ours_minus_penelope_relative"] == pytest.approx(d_ours_pen, rel=1e-15)
        assert b["sigma_comb_relative"] == pytest.approx(sigma_comb, rel=1e-15)
        assert b["n_sigma_vs_penelope"] == pytest.approx(abs(d_ours_pen) / sigma_comb, rel=1e-15)
        d = b["decomposition"]
        assert d["penelope_vs_four_code_mean"] == pytest.approx(d_pen_mean, rel=1e-15)
        assert d["ours_vs_penelope"] == pytest.approx(d_ours_pen, rel=1e-15)
        assert d["ours_vs_four_code_mean"] == pytest.approx(d_ours_mean, rel=1e-15)
        assert d["product_equals_ours_vs_mean"] == pytest.approx(product, rel=1e-15)
        assert abs(d["identity_residual"]) < 1e-15
        for name, rec in per.items():
            assert b["per_code_ours_minus_reference"][name] == pytest.approx(
                ours / rec["reference"] - 1.0, rel=1e-15
            )
        assert b["reported_not_gated"] is True


def test_delta_length_is_the_difference_of_the_two_ten_replica_means(close, l40, l160):
    for voi in ("center", "perimeter"):
        m40 = l40["comparison"][voi]["mean_ev_per_photon"]
        m160 = l160["comparison"][voi]["mean_ev_per_photon"]
        sd40 = l40["comparison"][voi]["replica_sample_sd"]
        sd160 = l160["comparison"][voi]["replica_sample_sd"]
        diff = m160 - m40
        sigma_abs = math.sqrt(sd40**2 / N + sd160**2 / N)
        dl = close["delta_length"]["vois"][voi]
        assert dl["L160_minus_L40"] == pytest.approx(diff, rel=1e-15)
        assert dl["relative_to_L40"] == pytest.approx(diff / m40, rel=1e-15)
        assert dl["sigma_abs"] == pytest.approx(sigma_abs, rel=1e-15)
        assert dl["n_sigma"] == pytest.approx(abs(diff) / sigma_abs, rel=1e-15)
        assert dl["distinguishable"] is (abs(diff) / sigma_abs >= 2.0)
        assert dl["L40_source_route"] == "B"
        assert dl["L160_source_route"] == "A"
    assert close["delta_length"]["indistinguishable"] is True


def test_uncertainty_budget_rss_and_kinds(close, g2):
    omega = g2["geometry"]["omega_excess_fraction"]
    n_bins = g2["spectrum"]["n_bins"]
    assert n_bins == 207
    for voi in ("center", "perimeter"):
        terms = close["uncertainty_budget"][voi]["terms"]
        assert terms["anchor_sem"]["kind"] == "measured"
        assert terms["penelope_36angle"]["kind"] == "declared"
        assert terms["penelope_36angle"]["relative"] == pytest.approx(PENELOPE_36, rel=1e-15)
        assert terms["delta_length"]["kind"] == "measured"
        assert terms["subfan_omega_k4"]["kind"] == "analytic"
        assert terms["subfan_omega_k4"]["relative"] == pytest.approx(omega, rel=1e-15)
        assert terms["voxel_2p5mm"]["kind"] == "declared_upper_bound"
        assert terms["voxel_2p5mm"]["relative"] == pytest.approx(VOXEL_FIRST_TEST, rel=1e-15)
        assert terms["voxel_2p5mm"]["second_test"] == "unmeasured"
        assert terms["spectrum_255bin"]["kind"] == "declared"
        assert terms["spectrum_255bin"]["relative"] == 0.0
        rss = math.sqrt(sum(t["relative"] ** 2 for t in terms.values()))
        u = close["uncertainty_budget"][voi]
        assert u["sigma_total"] == pytest.approx(rss, rel=1e-15)
        abs_pen = close["criterion_b"]["vois"][voi]["abs_ours_minus_penelope_relative"]
        assert u["abs_ours_minus_penelope_over_sigma_total"] == pytest.approx(
            abs_pen / rss, rel=1e-15
        )


def test_verdict_records_the_gate_not_a_homemade_pass_on_b(close):
    assert close["verdict"]["criterion_a"] == "PASS"
    assert close["verdict"]["criterion_b"] == "reported, not gated"
    assert close["verdict"]["phase1a_closed"] is True
    assert close["verdict"]["usable_as_anchor"] is True
    assert close["configuration"]["L40_source_route"] == "B"
    assert close["configuration"]["L160_source_route"] == "A"


def test_the_reconciliation_is_sensitive_to_a_hand_edit(close, l40):
    """Guard against a vacuous check: perturb the centre mean and the SEM identity breaks."""
    mean = l40["comparison"]["center"]["mean_ev_per_photon"]
    sd = l40["comparison"]["center"]["replica_sample_sd"]
    tampered_sem = (sd / (mean * 1.01)) / math.sqrt(N)
    recorded = close["criterion_a"]["vois"]["center"]["anchor_sem_relative"]
    assert tampered_sem != pytest.approx(recorded, rel=1e-9)

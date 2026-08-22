"""The 32-series production list is the eligibility file, not a hand-picked set."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _cohort():
    spec = importlib.util.spec_from_file_location("run_cohort", REPO / "tools" / "run_cohort.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_one_resilient_retries_on_failure(monkeypatch):
    cohort = _cohort()
    calls: list[str] = []

    def fake_run(_py: str, uid: str, _timeout: float) -> int:
        calls.append(uid)
        return 1

    monkeypatch.setattr(cohort, "_run_one", fake_run)
    monkeypatch.setattr(cohort, "is_complete", lambda _uid: False)
    assert cohort._run_one_resilient("python", "uid-x", 12.0) == 1
    assert calls == ["uid-x", "uid-x"]


def test_run_one_resilient_skips_retry_when_complete(monkeypatch):
    cohort = _cohort()
    calls: list[str] = []

    def fake_run(_py: str, uid: str, _timeout: float) -> int:
        calls.append(uid)
        return 0

    monkeypatch.setattr(cohort, "_run_one", fake_run)
    monkeypatch.setattr(cohort, "is_complete", lambda _uid: True)
    assert cohort._run_one_resilient("python", "uid-x", 12.0) == 0
    assert calls == ["uid-x"]


def test_eligible_count_is_thirty_two():
    cohort = _cohort()
    uids = cohort.eligible_uids(REPO / "results" / "phase2_cohort" / "density_eligibility.json")
    assert len(uids) == 32
    assert len(set(uids)) == 32


def test_prod_tag_is_stable_and_unique():
    cohort = _cohort()
    uids = cohort.eligible_uids(REPO / "results" / "phase2_cohort" / "density_eligibility.json")
    tags = [cohort.prod_tag(u) for u in uids]
    assert len(set(tags)) == 32
    assert all(t.startswith("prod_") for t in tags)


def test_140kvp_waits_only_until_150kev_tables_exist():
    cohort = _cohort()
    uid = "1.3.6.1.4.1.14519.5.2.1.1.12144631656438139661502631773455627610"
    assert cohort.series_kvp(uid) == 140.0
    have = cohort._tables_on_disk("5-150keV")
    assert cohort.needs_extended_tables(uid) is (not have)
    others = [
        u
        for u in cohort.eligible_uids(REPO / "results" / "phase2_cohort" / "density_eligibility.json")
        if u != uid
    ]
    assert not any(cohort.needs_extended_tables(u) for u in others)

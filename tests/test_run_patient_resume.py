"""Interrupted z-station runs must keep finished beams and drop only truncated ones."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _mod():
    spec = importlib.util.spec_from_file_location("run_patient", REPO / "tools" / "run_patient.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_tally(rundir: Path, stem: str, raw_n: int) -> None:
    ascii_path = rundir / f"dose_{stem}.dat"
    ascii_path.write_text("header\n", encoding="ascii")
    Path(str(ascii_path) + ".raw").write_bytes(b"\x00" * raw_n)
    Path(str(ascii_path) + "_PercentRelError2sigma.raw").write_bytes(b"\x00" * raw_n)


def test_same_scan_coverage_rejects_mid_scan_plan():
    rp = _mod()
    zcover = {
        "n_z_stations": 30,
        "n_projections": 36,
        "n_sub_fans": 4,
        "collimation_cm": 2.0,
    }
    assert rp.same_scan_coverage(zcover, n_z_stations=30, n_projections=36, n_sub_fans=4, collimation_cm=2.0)
    assert not rp.same_scan_coverage(None, n_z_stations=30, n_projections=36, n_sub_fans=4, collimation_cm=2.0)
    mid = dict(zcover)
    mid["n_z_stations"] = 1
    assert not rp.same_scan_coverage(mid, n_z_stations=30, n_projections=36, n_sub_fans=4, collimation_cm=2.0)


def test_unfinished_jobs_keeps_complete_and_drops_truncated(tmp_path: Path):
    rp = _mod()
    jobs = [{"stem": "s00_p000_fan00"}, {"stem": "s00_p001_fan00"}, {"stem": "s01_p000_fan00"}]
    _write_tally(tmp_path, "s00_p000_fan00", 40)
    _write_tally(tmp_path, "s00_p001_fan00", 40)
    _write_tally(tmp_path, "s01_p000_fan00", 16)
    todo = rp.unfinished_jobs(jobs, tmp_path)
    assert [j["stem"] for j in todo] == ["s01_p000_fan00"]
    assert rp.tally_complete(tmp_path, "s00_p000_fan00", 40)
    assert not (tmp_path / "dose_s01_p000_fan00.dat").is_file()


def test_unfinished_jobs_all_missing(tmp_path: Path):
    rp = _mod()
    jobs = [{"stem": "s00_p000_fan00"}]
    todo = rp.unfinished_jobs(jobs, tmp_path)
    assert len(todo) == 1

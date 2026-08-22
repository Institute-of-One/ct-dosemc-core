"""build_info.json keeps defect fixes out of the Route A performance record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

INFO = Path(__file__).resolve().parent.parent / "vendor" / "build" / "build_info.json"


pytestmark = pytest.mark.skipif(not INFO.is_file(), reason="engine not built yet")


def _info():
    return json.loads(INFO.read_text(encoding="utf-8-sig"))


def test_route_a_is_not_listed_among_defect_fixes():
    info = _info()
    kinds = {p["kind"] for p in info["patches"]}
    assert "performance" not in kinds
    assert all("Route A" not in (p.get("name") or "") for p in info["patches"])
    assert all(p["kind"] in {"defect_fix", "portability"} for p in info["patches"])


def test_route_a_sits_in_performance_modifications():
    info = _info()
    perf = info["performance_modifications"]
    assert len(perf) == 1
    a = perf[0]
    assert a["kind"] == "performance"
    assert a["not_a_defect_fix"] is True
    assert a["physics_unchanged"] is True
    assert a["identical_definition_both_targets"] is True
    applied = " ".join(a["applied_to"])
    assert "win_cpu.cu" in applied and "win_gpu.cu" in applied


def test_both_targets_are_recorded():
    info = _info()
    assert "cpu" in info["targets"] and "gpu" in info["targets"]
    assert info["targets"]["cpu"]["executable_sha256"]
    assert info["targets"]["gpu"]["executable_sha256"]
    assert info["targets"]["cpu"]["executable_sha256"] != info["targets"]["gpu"]["executable_sha256"]

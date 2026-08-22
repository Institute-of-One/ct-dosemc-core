"""build_info.json keeps defect fixes out of the Route A performance record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

INFO = Path(__file__).resolve().parent.parent / "vendor" / "build" / "build_info.json"


pytestmark = pytest.mark.skipif(not INFO.is_file(), reason="engine not built yet")


def _info():
    return json.loads(INFO.read_text(encoding="utf-8-sig"))


#: What a source patch to the engine may be. `capacity` raises a compile-time array
#: bound to admit a larger input -- it changes neither the physics nor the speed --
#: and was added when the Schneider tables at 140 kVp overran MAX_SHELLS and
#: MAX_ENERGYBINS_RAYLEIGH. `performance` is deliberately absent: Route A belongs in
#: performance_modifications, which is what this file exists to keep separate.
PATCH_KINDS = {"defect_fix", "portability", "capacity"}


def test_route_a_is_not_listed_among_defect_fixes():
    info = _info()
    kinds = {p["kind"] for p in info["patches"]}
    assert "performance" not in kinds
    assert all("Route A" not in (p.get("name") or "") for p in info["patches"])
    unknown = kinds - PATCH_KINDS
    assert not unknown, f"patch kinds outside {sorted(PATCH_KINDS)}: {sorted(unknown)}"


def test_every_capacity_patch_says_why_it_was_raised():
    """A bound raised without a reason is indistinguishable from one raised to
    make a failure go away. The manuscript cites this file as build provenance."""
    for patch in _info()["patches"]:
        if patch["kind"] != "capacity":
            continue
        reason = (patch.get("reason") or "").strip()
        assert len(reason) > 40, f"capacity patch with no stated reason: {patch}"
        assert patch.get("from") and patch.get("to"), patch


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
    assert (
        info["targets"]["cpu"]["executable_sha256"] != info["targets"]["gpu"]["executable_sha256"]
    )

"""Fig. 4 collector does not treat raw MC mGy as the paper number."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _mod():
    spec = importlib.util.spec_from_file_location(
        "collect_figure4_doses", REPO / "tools" / "collect_figure4_doses.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_figure4_is_not_usable_until_ctdi_scale_exists():
    collect = _mod()
    index = collect._load(REPO / "results" / "phase2_cohort" / "iorn006_organ_index.json")
    payload = collect.collect(index=index, scale=None)
    assert payload["usable_for_figure4"] is False
    assert payload["n_scaled"] == 0
    assert payload["doses"] == {}


def test_scale_key_is_vendor_and_kvp():
    collect = _mod()
    assert collect.scale_key("Siemens", 140.0) == "Siemens|140"
    assert collect.scale_key("GE", 120) == "GE|120"


def test_collect_computes_factor_from_ctdiw_mc():
    collect = _mod()
    index = collect._load(REPO / "results" / "phase2_cohort" / "iorn006_organ_index.json")
    scale = {"ctdiw_pmma_mgy_by_vendor_kvp": {"Siemens|140": 10.0}}
    payload = collect.collect(index=index, scale=scale)
    rows = [
        r
        for r in payload["series"]
        if r.get("scale_key") == "Siemens|140" and r.get("on_figure4")
    ]
    assert rows
    assert rows[0]["status"] == "scaled"
    assert rows[0]["scale_factor"] == pytest.approx(float(rows[0]["ctdivol_mgy"]) / 10.0)


def test_midscan_only_production_is_not_figure4():
    """A single 2 cm rotation is not the exam organ dose; Fig. 4 must wait."""
    collect = _mod()
    index = collect._load(REPO / "results" / "phase2_cohort" / "iorn006_organ_index.json")
    payload = collect.collect(index=index, scale=None)
    assert payload["usable_for_figure4"] is False
    assert payload["n_scaled"] == 0

"""Table 4 / Fig. 4 stats refuse an unusable (mid-scan or unscaled) y-axis."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _mod():
    spec = importlib.util.spec_from_file_location(
        "collect_phase2_results", REPO / "tools" / "collect_phase2_results.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_refuses_unusable_figure4_payload():
    mod = _mod()
    with pytest.raises(SystemExit, match="usable_for_figure4"):
        mod.collect(
            doses_payload={"usable_for_figure4": False, "doses": {}, "series": []},
            index={"series": []},
        )


def test_table4_counts_only_scaled_series():
    mod = _mod()
    payload = {
        "usable_for_figure4": True,
        "n_eligible": 2,
        "n_scaled": 1,
        "formula": "test",
        "doses": {
            "a": {"liver": 10.0, "spleen": 12.0},
            "b": {"liver": 99.0},
        },
        "series": [
            {"series_instance_uid": "a", "vendor": "GE", "status": "scaled"},
            {"series_instance_uid": "b", "vendor": "GE", "status": "omitted_no_ctdivol"},
        ],
    }
    table, _stats = mod.collect(doses_payload=payload, index={"series": []})
    assert table["n_scaled_series"] == 1
    assert table["n_series_by_vendor"]["GE"] == 1
    liver = next(r for r in table["organs"] if r["organ"] == "liver")
    assert liver["by_vendor"]["GE"]["n"] == 1
    assert liver["by_vendor"]["GE"]["median_mgy"] == 10.0

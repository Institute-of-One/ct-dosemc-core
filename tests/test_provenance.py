"""Provenance is a hard requirement, not documentation.

A ``Value`` that cannot say how it was produced does not get reported, so the
structure is checked here and the results files are checked for completeness.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ct_dosemc_core.dosimetry import RegionDose
from ct_dosemc_core.phantom import hu_to_density
from ct_dosemc_core.provenance import (
    Provenance,
    Value,
    environment,
    file_digest,
    write_results,
)

RESULTS = Path(__file__).resolve().parent.parent / "results"


def test_value_carries_formula_inputs_and_uncertainty():
    v = Value(
        value=5.25,
        unit="mGy",
        uncertainty=0.02,
        provenance=Provenance(
            formula="CTDIw = CTDIc/3 + 2*CTDIp/3",
            inputs={"CTDIc": 6.2, "CTDIp": 4.8},
            assumptions=("no bowtie",),
            source="IEC 60601-2-44",
        ),
    )
    d = v.to_dict()
    assert d["provenance"]["formula"]
    assert d["provenance"]["inputs"] == {"CTDIc": 6.2, "CTDIp": 4.8}
    assert d["provenance"]["assumptions"] == ["no bowtie"]
    assert v.relative_uncertainty == pytest.approx(0.02 / 5.25)


def test_a_value_without_uncertainty_says_so_rather_than_implying_zero():
    v = Value(1.0, "sr", Provenance(formula="geometry"))
    assert v.to_dict()["uncertainty"] is None
    assert v.to_dict()["uncertainty_kind"] is None
    assert v.relative_uncertainty is None


def test_region_dose_provenance_names_the_kerma_approximation():
    r = RegionDose("liver", 12.0, 0.1, 1500.0, 4000, 1.0e-9, 1.0e13)
    assumptions = " ".join(r.as_value().provenance.assumptions)
    assert "collision kerma" in assumptions
    assert "independent" in assumptions


def test_write_results_stamps_the_environment_and_expands_values(tmp_path):
    out = write_results(
        tmp_path / "r.json",
        {"results": {"ctdiw": Value(5.25, "mGy", Provenance(formula="f"), uncertainty=0.01)}},
    )
    body = json.loads(out.read_text(encoding="utf-8"))
    assert set(body["environment"]) >= {"generated_utc", "python", "platform", "numpy"}
    assert body["results"]["ctdiw"]["value"] == 5.25
    assert body["results"]["ctdiw"]["provenance"]["formula"] == "f"


def test_write_results_serialises_numpy_scalars(tmp_path):
    out = write_results(tmp_path / "r.json", {"n": np.int64(7), "x": np.float64(1.5)})
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["n"] == 7
    assert body["x"] == pytest.approx(1.5)


def test_file_digest_pins_content_and_returns_none_for_a_missing_file(tmp_path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"abc")
    first = file_digest(p)
    assert first and len(first) == 64
    p.write_bytes(b"abd")
    assert file_digest(p) != first
    assert file_digest(tmp_path / "nope.bin") is None


def test_environment_records_what_can_change_an_answer():
    env = environment()
    assert env["python"]
    assert env["platform"]
    assert "spekpy" in env  # None is a fact too


# -- HU -> density ----------------------------------------------------------


def test_hu_to_density_hits_the_published_anchor_points():
    rho = hu_to_density(np.array([-1000.0, -98.0, 14.0, 1600.0]))
    np.testing.assert_allclose(rho, [0.00121, 0.93, 1.03, 1.964], rtol=1e-6)


def test_hu_to_density_is_monotonic_and_clamped():
    hu = np.linspace(-2000, 5000, 500)
    rho = hu_to_density(hu)
    assert np.all(np.diff(rho) >= 0)
    assert rho[0] == pytest.approx(0.00121)  # clamped below the first breakpoint
    assert rho[-1] == pytest.approx(2.8)  # clamped above the last


def test_hu_to_density_never_returns_a_density_mcgpu_would_reject():
    assert np.all(hu_to_density(np.array([-100000.0, 0.0])) > 0.0)


def test_hu_to_density_rejects_an_inconsistent_calibration():
    with pytest.raises(ValueError, match="same length"):
        hu_to_density(np.array([0.0]), breakpoints_hu=(0.0, 1.0), density_g_cm3=(1.0,))
    with pytest.raises(ValueError, match="strictly increasing"):
        hu_to_density(np.array([0.0]), breakpoints_hu=(1.0, 0.0), density_g_cm3=(1.0, 2.0))


# -- the results files ------------------------------------------------------


@pytest.mark.parametrize(
    "path", sorted(RESULTS.glob("phase1_ctdi_anchor_*.json")), ids=lambda p: p.name
)
def test_every_reported_value_in_a_results_file_has_provenance(path):
    body = json.loads(path.read_text(encoding="utf-8"))

    def walk(node, where=""):
        if isinstance(node, dict):
            if "value" in node and "unit" in node:
                assert node.get("provenance", {}).get("formula"), f"{where}: no formula"
            for k, v in node.items():
                walk(v, f"{where}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{where}[{i}]")

    walk(body["results"], "results")
    assert body["environment"]["generated_utc"]
    assert body["engine"]["executable_sha256"], "the engine binary must be pinned"
    assert body["known_gaps"], "a run that claims no known gaps is not being honest"

"""source_route classification: K=4 P=36 invocations, not a flag."""

from __future__ import annotations

import importlib.util
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "tools" / "run_tg195.py"


def _mod():
    spec = importlib.util.spec_from_file_location("run_tg195", RUN)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_k4_144_invocations_is_route_b():
    f = _mod().source_route_fields(
        n_sub_fans=4, n_projections=36, engine_invocations=144
    )
    assert f["source_route"] == "B"


def test_k4_one_invocation_is_route_a():
    f = _mod().source_route_fields(
        n_sub_fans=4, n_projections=36, engine_invocations=1
    )
    assert f["source_route"] == "A"
    assert "bit-identical" in f["bit_identity_note"]


def test_k1_is_not_labelled_route_a():
    f = _mod().source_route_fields(
        n_sub_fans=1, n_projections=36, engine_invocations=1
    )
    assert f["source_route"] == "native_ct_trajectory"

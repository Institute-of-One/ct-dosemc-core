"""Route A engine patch applies to a Windows-patched copy of upstream."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
UPSTREAM = REPO / "vendor" / "MCGPU" / "MC-GPU_v1.3.cu"
APPLY = REPO / "tools" / "apply_route_a.py"


@pytest.mark.skipif(not UPSTREAM.is_file(), reason="vendored MC-GPU source missing")
def test_apply_route_a_is_idempotent_on_windows_patched_upstream():
    import importlib.util

    spec = importlib.util.spec_from_file_location("apply_route_a", APPLY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    text = UPSTREAM.read_text(encoding="latin-1")
    for src, dst in (
        ('fopen(file_binary, "w")', 'fopen(file_binary, "wb")'),
        ('fopen(file_binary_mean, "w")', 'fopen(file_binary_mean, "wb")'),
        ('fopen(file_binary_sigma, "w")', 'fopen(file_binary_sigma, "wb")'),
        ("if (abs(theta_aperture) < 1.0e-7)", "if (fabs(theta_aperture) < 1.0e-7)"),
        ("if (abs(phi_aperture) < 1.0e-7)", "if (fabs(phi_aperture) < 1.0e-7)"),
        ("cudaThreadSynchronize", "cudaDeviceSynchronize"),
    ):
        text = text.replace(src, dst)

    patched, status = mod.apply_route_a(text)
    assert status == "applied"
    assert "=== Route A: expand an optional manifest" in patched
    assert "reusing cached voxel geometry" in patched
    assert "end of the per-beam loop" in patched
    assert "=== Route A: per-beam tally reset ===" in patched
    assert "Route A: fclose input and spectrum per beam" in patched
    assert patched.count("fclose(file_ptr);  // Route A: fclose input and spectrum per beam") == 2
    assert "cudaDeviceSynchronize" in patched
    assert "cudaThreadSynchronize" not in patched

    again, status2 = mod.apply_route_a(patched)
    assert status2 == "already"
    assert again == patched

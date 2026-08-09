"""The Phase-2 admission criterion.

These tests exist mostly to pin the *difference* from IORN-006, because that
difference is a judgement call that a reviewer will want to see stated and
enforced rather than described.
"""

from __future__ import annotations

import pytest

from ct_dosemc_core.eligibility import (
    GEOMETRY_REQUIRED,
    REQUIRED_FOR_TRANSPORT,
    assess_series,
    summarise,
)


def _header(**overrides):
    h = {
        "series_instance_uid": "1.2.3.4",
        "manufacturer": "VendorA",
        "tube_voltage_kvp": 120.0,
        "total_collimation_width_mm": 40.0,
        "spiral_pitch_factor": 0.984,
        "exposure_time_ms": 500.0,
        "recorded_ctdivol_mgy": 7.4,
        "slice_spacing_regular": True,
        "single_acquisition": True,
        "reconstruction_kernel": "B30f",
        "reconstruction_diameter_mm": 500.0,
    }
    h.update(overrides)
    return h


_DEFAULT = object()  # so that currents=None can mean "the tag was never written"


def _assess(header=None, *, n_slices=100, currents=_DEFAULT, **kw):
    if currents is _DEFAULT:
        currents = [200.0] * n_slices
    return assess_series(
        header or _header(), n_slices=n_slices, tube_current_values=currents, **kw
    )


def test_a_complete_series_is_eligible():
    e = _assess()
    assert e.eligible
    assert e.reasons == ()
    assert e.tube_current_coverage == pytest.approx(1.0)


@pytest.mark.parametrize("attribute", sorted(REQUIRED_FOR_TRANSPORT))
def test_every_transport_attribute_is_individually_required(attribute):
    """Absence disqualifies -- the deliberate departure from IORN-006.

    An index can be computed without kVp; a photon transport calculation cannot,
    and substituting a default would be inventing the input.
    """
    e = _assess(_header(**{attribute: None}))
    assert not e.eligible
    assert any(r.startswith(attribute) for r in e.reasons)


@pytest.mark.parametrize("attribute", sorted(GEOMETRY_REQUIRED))
def test_every_geometry_attribute_is_individually_required(attribute):
    e = _assess(_header(**{attribute: None}))
    assert not e.eligible
    assert any(r.startswith(attribute) for r in e.reasons)


def test_irregular_geometry_is_distinguished_from_absent_geometry():
    absent = _assess(_header(slice_spacing_regular=None))
    irregular = _assess(_header(slice_spacing_regular=False))
    assert not absent.eligible and not irregular.eligible
    assert absent.by_attribute["slice_spacing_regular"] == "absent"
    assert irregular.by_attribute["slice_spacing_regular"] == "irregular"


def test_tube_current_must_cover_every_slice_not_merely_exist():
    """IORN-006 needed the current over an organ's extent; a Monte Carlo driving a
    per-rotation mAs needs I(z) over the whole irradiated length, because photons
    from outside any organ of interest still reach it."""
    partial = [200.0] * 90 + [None] * 10
    e = _assess(n_slices=100, currents=partial)
    assert not e.eligible
    assert e.tube_current_coverage == pytest.approx(0.9)
    assert any("incomplete" in r for r in e.reasons)


def test_a_completely_absent_tube_current_is_not_the_same_as_a_partial_one():
    e = _assess(currents=None)
    assert not e.eligible
    assert e.tube_current_coverage is None
    assert e.by_attribute["tube_current_per_slice"] == "absent"


def test_full_tcm_requirement_can_be_relaxed_explicitly():
    partial = [200.0] * 90 + [None] * 10
    e = _assess(n_slices=100, currents=partial, require_full_tcm=False)
    assert e.eligible
    assert e.tube_current_coverage == pytest.approx(0.9)


def test_all_reasons_are_reported_not_just_the_first():
    e = _assess(_header(tube_voltage_kvp=None, reconstruction_kernel=None))
    assert len(e.reasons) == 2


# -- cohort summary ---------------------------------------------------------


def test_summary_reports_attrition_by_vendor():
    """The multi-vendor claim has to survive the criterion, and this is where it
    would fail if requiring attributes fell unevenly across manufacturers."""
    assessed = {
        "a": _assess(_header(series_instance_uid="a", manufacturer="VendorA")),
        "b": _assess(_header(series_instance_uid="b", manufacturer="VendorB")),
        "c": _assess(
            _header(series_instance_uid="c", manufacturer="VendorB", tube_voltage_kvp=None)
        ),
    }
    s = summarise(assessed)
    assert s["n_assessed"] == 3
    assert s["n_eligible"] == 2
    assert s["by_vendor"]["VendorA"] == {"assessed": 1, "eligible": 1}
    assert s["by_vendor"]["VendorB"] == {"assessed": 2, "eligible": 1}
    assert s["vendors_surviving"] == ["VendorA", "VendorB"]


def test_summary_shows_a_vendor_wiped_out_by_the_criterion():
    assessed = {
        "a": _assess(_header(series_instance_uid="a", manufacturer="VendorA")),
        "b": _assess(
            _header(series_instance_uid="b", manufacturer="VendorB", recorded_ctdivol_mgy=None)
        ),
    }
    s = summarise(assessed)
    assert s["vendors_surviving"] == ["VendorA"]
    assert s["by_vendor"]["VendorB"]["eligible"] == 0
    assert "recorded_ctdivol_mgy: absent" in s["exclusions_by_reason"]


def test_summary_states_how_it_differs_from_the_index_study():
    s = summarise({"a": _assess()})
    assert "IORN-006" in s["differs_from_iorn006"]
    assert s["criterion"]


def test_every_required_attribute_names_what_consumes_it():
    """A gate on an attribute nothing reads is a gate that cannot be defended."""
    for name, why in {**REQUIRED_FOR_TRANSPORT, **GEOMETRY_REQUIRED}.items():
        assert why and len(why) > 20, name

"""CTDI arithmetic, against the closed forms in IEC 60601-2-44."""

from __future__ import annotations

import math

import pytest

from ct_dosemc_core.ctdi import average_peripheral, ctdi_100, ctdi_vol, ctdi_w
from ct_dosemc_core.dosimetry import RegionDose
from ct_dosemc_core.provenance import Provenance, Value


def _region(dose_mgy: float, sigma_mgy: float = 0.0, name: str = "centre") -> RegionDose:
    return RegionDose(
        name=name,
        dose_mgy=dose_mgy,
        sigma_mgy=sigma_mgy,
        mass_g=13.5,
        n_voxels=1000,
        dose_ev_per_g_per_history=1.0e-9,
        n_histories=1.0e12,
    )


def _value(v: float, s: float | None = None) -> Value:
    return Value(v, "mGy", Provenance(formula="test"), uncertainty=s)


def test_ctdi100_rescales_the_chamber_average_by_length_over_collimation():
    # A 100 mm chamber irradiated over a 20 mm slice reads 5x the mean dose.
    r = _region(2.0)
    assert ctdi_100(r, collimation_cm=2.0, chamber_length_cm=10.0).value == pytest.approx(10.0)
    # Doubling the collimation halves CTDI100 for the same chamber reading.
    assert ctdi_100(r, collimation_cm=4.0, chamber_length_cm=10.0).value == pytest.approx(5.0)


def test_ctdi100_scales_the_uncertainty_by_the_same_factor():
    r = _region(2.0, sigma_mgy=0.02)
    v = ctdi_100(r, collimation_cm=2.0, chamber_length_cm=10.0)
    assert v.relative_uncertainty == pytest.approx(0.01)


def test_ctdi100_rejects_a_non_positive_collimation():
    with pytest.raises(ValueError, match="positive"):
        ctdi_100(_region(1.0), collimation_cm=0.0)


def test_ctdiw_is_one_third_centre_plus_two_thirds_peripheral():
    cw = ctdi_w(_value(6.0), _value(24.0))
    assert cw.value == pytest.approx(6.0 / 3 + 2 * 24.0 / 3)
    assert cw.value == pytest.approx(18.0)


def test_ctdiw_of_a_uniform_phantom_is_that_uniform_value():
    cw = ctdi_w(_value(7.5), _value(7.5))
    assert cw.value == pytest.approx(7.5)


def test_ctdiw_combines_uncertainties_in_quadrature_with_their_weights():
    cw = ctdi_w(_value(6.0, 0.3), _value(24.0, 0.6))
    assert cw.uncertainty == pytest.approx(math.hypot(0.3 / 3, 2 * 0.6 / 3))


def test_ctdivol_divides_by_pitch():
    cw = _value(18.0, 0.2)
    assert ctdi_vol(cw, 1.0).value == pytest.approx(18.0)
    assert ctdi_vol(cw, 1.5).value == pytest.approx(12.0)
    assert ctdi_vol(cw, 0.5).value == pytest.approx(36.0)
    assert ctdi_vol(cw, 2.0).uncertainty == pytest.approx(0.1)


def test_ctdivol_rejects_a_non_positive_pitch():
    with pytest.raises(ValueError, match="positive"):
        ctdi_vol(_value(18.0), 0.0)


def test_average_peripheral_uses_all_four_cardinal_positions():
    vals = {
        "12_o_clock": _value(20.0, 0.2),
        "3_o_clock": _value(22.0, 0.2),
        "6_o_clock": _value(24.0, 0.2),
        "9_o_clock": _value(26.0, 0.2),
    }
    p = average_peripheral(vals)
    assert p.value == pytest.approx(23.0)
    assert p.uncertainty == pytest.approx(0.2 / 2)  # sqrt(4*0.04)/4


def test_average_peripheral_refuses_to_guess_a_missing_position():
    with pytest.raises(KeyError, match="missing peripheral positions"):
        average_peripheral({"12_o_clock": _value(20.0)})

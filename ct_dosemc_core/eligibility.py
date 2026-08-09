"""Which series may enter a Monte-Carlo absorbed-dose calculation, and why.

This is **not** the IORN-006 criterion with a different name.  That study computed
an *index* -- a dimensionless weight scaling a recorded CTDIvol -- and could
tolerate a missing attribute, because the index describes the recorded tube
current and nothing else.  A Monte-Carlo absorbed dose is a different object: it
needs an actual beam, an actual spectrum and an actual trajectory, and there is no
value the model can proceed without.

The criterion, stated once in advance and applied mechanically:

    A series may enter a Monte-Carlo absorbed-dose calculation only when every
    quantity the source model consumes is present and internally consistent in the
    archived headers, and the reconstruction is geometrically regular enough to be
    voxelised without interpolation across a discontinuity.

Two consequences follow, and both must be reported rather than absorbed:

* **Absence disqualifies here, where it did not before.** IORN-006 deliberately
  did not exclude on absence, because doing so removes series for a property of
  the de-identified export rather than of the acquisition, and falls unevenly
  across manufacturers.  That reasoning is sound for an index and unavailable for
  a transport calculation: without kVp there is no spectrum, and a default would
  be an invention.  The cost is a cohort that may be skewed by vendor, so
  :func:`summarise` reports attrition **by vendor and by reason**, and the
  manuscript must carry that table.
* **The tube-current record must be complete, not merely present.** IORN-006 used
  the recorded current over an organ's longitudinal extent; a Monte Carlo driving
  a per-rotation mAs needs I(z) across the whole irradiated length, including the
  parts outside any organ of interest, because photons from there reach it.

Nothing in this module reads pixels or computes a dose.  It decides what is
admissible, so that the decision is made once, in the open, before any number
exists to be influenced by it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "GEOMETRY_REQUIRED",
    "REQUIRED_FOR_TRANSPORT",
    "Eligibility",
    "assess_series",
    "summarise",
]

#: Attributes the source model consumes directly.  Each maps to a documented
#: consumer; an attribute nothing consumes has no business being a gate.
REQUIRED_FOR_TRANSPORT: dict[str, str] = {
    "tube_voltage_kvp": "spectra.generate_spectrum -- selects the spectrum",
    "total_collimation_width_mm": "source_model.BeamGeometry -- the polar aperture",
    "spiral_pitch_factor": "the helical trajectory and the CTDIvol relation",
    "exposure_time_ms": "converts tube current to mAs per rotation",
    "recorded_ctdivol_mgy": (
        "the normalisation anchor: patient dose is scaled so the simulated CTDIvol "
        "reproduces the recorded one, which removes most of the dependence on the "
        "bowtie's absolute transmission (docs/MC_SOURCE_MODEL.md section 4.5)"
    ),
}

#: Reconstruction geometry that must be regular for the voxel phantom to be built
#: without interpolating across a discontinuity.
GEOMETRY_REQUIRED: dict[str, str] = {
    "slice_spacing_regular": "uniform z sampling -- the voxel grid is uniform",
    "single_acquisition": "one continuous helix; a restart breaks I(z) and the trajectory",
    "reconstruction_kernel": "the HU->density calibration is kernel dependent",
    "reconstruction_diameter_mm": "FOV; needed to place the patient in the beam correctly",
}

PRESENT = "present"
ABSENT = "absent"
INCOMPLETE = "incomplete"
IRREGULAR = "irregular"


@dataclass(frozen=True)
class Eligibility:
    """Whether one series may enter a Monte-Carlo absorbed-dose calculation."""

    series_uid: str
    vendor: str
    eligible: bool
    reasons: tuple[str, ...] = ()
    by_attribute: Mapping[str, str] = field(default_factory=dict)
    tube_current_coverage: float | None = None
    """Fraction of slices carrying (0018,1151).  ``None`` when the tag is absent
    entirely, which is a different failure from a partially-written one."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_instance_uid": self.series_uid,
            "vendor": self.vendor,
            "eligible": self.eligible,
            "disqualifying_reasons": list(self.reasons),
            "by_attribute": dict(self.by_attribute),
            "tube_current_coverage": self.tube_current_coverage,
        }


def assess_series(
    header: Mapping[str, Any],
    *,
    n_slices: int,
    tube_current_values: Sequence[float] | None,
    require_full_tcm: bool = True,
) -> Eligibility:
    """Apply the criterion to one series.

    ``header`` carries the series-level attributes named in
    :data:`REQUIRED_FOR_TRANSPORT` and :data:`GEOMETRY_REQUIRED`.
    ``tube_current_values`` is the per-slice (0018,1151) record, or ``None`` when
    the tag was never written.
    """
    by_attribute: dict[str, str] = {}
    reasons: list[str] = []

    for name in REQUIRED_FOR_TRANSPORT:
        value = header.get(name)
        ok = value is not None and value != ""
        by_attribute[name] = PRESENT if ok else ABSENT
        if not ok:
            reasons.append(f"{name}: {ABSENT}")

    for name in GEOMETRY_REQUIRED:
        value = header.get(name)
        if value is None or value == "":
            by_attribute[name] = ABSENT
            reasons.append(f"{name}: {ABSENT}")
        elif value is False:
            by_attribute[name] = IRREGULAR
            reasons.append(f"{name}: {IRREGULAR}")
        else:
            by_attribute[name] = PRESENT

    coverage: float | None = None
    if tube_current_values is None:
        by_attribute["tube_current_per_slice"] = ABSENT
        reasons.append(f"tube_current_per_slice: {ABSENT}")
    else:
        recorded = sum(1 for v in tube_current_values if v is not None and v > 0)
        coverage = recorded / n_slices if n_slices else 0.0
        if require_full_tcm and coverage < 1.0:
            by_attribute["tube_current_per_slice"] = INCOMPLETE
            reasons.append(
                f"tube_current_per_slice: {INCOMPLETE} ({recorded}/{n_slices} slices)"
            )
        else:
            by_attribute["tube_current_per_slice"] = PRESENT

    return Eligibility(
        series_uid=str(header.get("series_instance_uid", "")),
        vendor=str(header.get("manufacturer", "")),
        eligible=not reasons,
        reasons=tuple(reasons),
        by_attribute=by_attribute,
        tube_current_coverage=coverage,
    )


def summarise(assessed: Mapping[str, Eligibility]) -> dict[str, Any]:
    """Cohort attrition, broken down the two ways a reviewer will ask for.

    By reason, because the criterion has to be shown to be mechanical; and **by
    vendor**, because requiring attributes to be present is known to fall
    unevenly across manufacturers' de-identified exports.  If the surviving
    cohort is not multi-vendor, the multi-vendor claim fails here rather than in
    the discussion, and this table is where that becomes visible.
    """
    values = list(assessed.values())
    eligible = [e for e in values if e.eligible]

    by_vendor: dict[str, dict[str, int]] = {}
    for e in values:
        v = by_vendor.setdefault(e.vendor or "(unrecorded)", {"assessed": 0, "eligible": 0})
        v["assessed"] += 1
        v["eligible"] += int(e.eligible)

    by_reason: dict[str, int] = {}
    for e in values:
        for r in e.reasons:
            key = r.split(" (")[0]
            by_reason[key] = by_reason.get(key, 0) + 1

    return {
        "criterion": (
            "A series may enter a Monte-Carlo absorbed-dose calculation only when "
            "every quantity the source model consumes is present and internally "
            "consistent in the archived headers, and the reconstruction is "
            "geometrically regular enough to be voxelised without interpolation "
            "across a discontinuity."
        ),
        "differs_from_iorn006": (
            "IORN-006 computed an index and deliberately did not exclude on a "
            "missing attribute, since absence is a property of the de-identified "
            "export rather than of the acquisition. A transport calculation has no "
            "such option: without kVp there is no spectrum, and a default would be "
            "an invention. The attrition this causes is reported by vendor below "
            "rather than absorbed."
        ),
        "required_for_transport": dict(REQUIRED_FOR_TRANSPORT),
        "geometry_required": dict(GEOMETRY_REQUIRED),
        "n_assessed": len(values),
        "n_eligible": len(eligible),
        "n_excluded": len(values) - len(eligible),
        "exclusions_by_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
        "by_vendor": by_vendor,
        "vendors_surviving": sorted(
            v for v, c in by_vendor.items() if c["eligible"] > 0
        ),
        "excluded_series": [e.to_dict() for e in values if not e.eligible],
    }

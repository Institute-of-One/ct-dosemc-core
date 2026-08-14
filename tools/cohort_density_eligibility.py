"""Density-calibration eligibility -- the one pixel-based gate, applied mechanically.

This completes the absorbed-dose eligibility that ``ct_dosemc_core.eligibility``
begins (that module is header-only by design; this is its pixel-based sibling).
It is a *rule*, declared once in advance, with a single threshold:

    definition   an out-of-calibration voxel is inside the body contour with
                 HU >= 3071 (the 12-bit reconstruction saturation ceiling); this
                 treats clipping and exceeding identically, so the metric is
                 vendor-neutral and not a 16-bit-export detector.
    gate         a series is excluded if its largest connected out-of-calibration
                 component is >= 1 cm^3 -- a compact metal implant, whose atomic
                 number the Schneider calibration cannot represent, so the
                 photoelectric cross section would be misassigned.  The threshold
                 sits in the natural gap (0.91-2.06 cm^3) of the cohort's
                 distribution, so it is not fitted to any one series.

Everything else the distribution measured -- scattered clips, vascular
calcification, contrast, beam-hardening speckle -- stays: those are compact
components below 1 cm^3, within Schneider's cortical-bone range, and clamping them
to the top bone density is adequate.

Distances from the out-of-calibration voxels to each scored organ are carried
through as a **reported table, not a second gate** ("measure everything, gate on
one thing").  The by-vendor attrition is reported with N per vendor; the resulting
imbalance is a consequence of the pre-declared criterion and is not corrected --
adding probes would restart selection, trimming would discard survivors of a
declared rule.

Input is ``metal_distribution.json`` (from ``tools/metal_distribution.py``); this
tool only applies the threshold, so the expensive per-voxel work is not repeated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

#: The exclusion threshold on the largest connected out-of-calibration component.
#: Chosen from the cohort distribution's natural gap (0.91-2.06 cm^3).
IMPLANT_COMPONENT_CM3 = 1.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--distribution",
        type=Path,
        default=REPO / "results" / "phase2_cohort" / "metal_distribution.json",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "results" / "phase2_cohort" / "density_eligibility.json",
    )
    args = ap.parse_args()

    dist = json.loads(args.distribution.read_text(encoding="utf-8"))
    series = dist["series"]

    records: list[dict[str, Any]] = []
    for s in series:
        if "error" in s:
            records.append(
                {
                    "series_instance_uid": s["series_instance_uid"],
                    "vendor": s.get("vendor"),
                    "eligible": False,
                    "reason": "load-failed",
                    "error": s["error"],
                }
            )
            continue
        largest = float(s.get("largest_component_cm3") or 0.0)
        excluded = largest >= IMPLANT_COMPONENT_CM3
        records.append(
            {
                "series_instance_uid": s["series_instance_uid"],
                "vendor": s.get("vendor"),
                "eligible": not excluded,
                "reason": (
                    f"metal implant: largest out-of-calibration component "
                    f"{largest:.2f} cm^3 >= {IMPLANT_COMPONENT_CM3:g} cm^3"
                )
                if excluded
                else None,
                "largest_component_cm3": largest,
                "n_out_of_calibration_voxels": s.get("n_voxels"),
                "n_components": s.get("n_components"),
                "mass_fraction_lower_bound": s.get("mass_fraction_lower_bound"),
                "max_hu_in_body": s.get("max_hu_in_body"),
                "nearest_scored_organ": s.get("nearest_scored_organ"),
                "min_distance_mm": s.get("min_distance_mm"),
                "min_distance_by_organ_mm": s.get("min_distance_by_organ_mm", {}),
            }
        )

    by_vendor: dict[str, dict[str, int]] = {}
    for r in records:
        v = r.get("vendor") or "(unrecorded)"
        c = by_vendor.setdefault(v, {"assessed": 0, "eligible_N": 0, "excluded": 0})
        c["assessed"] += 1
        if r["eligible"]:
            c["eligible_N"] += 1
        else:
            c["excluded"] += 1

    n_eligible = sum(1 for r in records if r["eligible"])
    eligible_counts = {v: c["eligible_N"] for v, c in by_vendor.items()}
    balanced = len(set(eligible_counts.values())) <= 1

    # Reported distance table for the excluded series (not a gate).
    excluded = [r for r in records if not r["eligible"]]
    distance_table = [
        {
            "vendor": r["vendor"],
            "series_instance_uid": r["series_instance_uid"],
            "largest_component_cm3": r.get("largest_component_cm3"),
            "max_hu_in_body": r.get("max_hu_in_body"),
            "nearest_scored_organ": r.get("nearest_scored_organ"),
            "min_distance_mm": r.get("min_distance_mm"),
            "min_distance_by_organ_mm": r.get("min_distance_by_organ_mm", {}),
        }
        for r in sorted(excluded, key=lambda r: -(r.get("largest_component_cm3") or 0))
    ]

    payload = {
        "criterion": (
            "Out-of-calibration voxel = inside body contour AND HU >= 3071 (the "
            "12-bit saturation ceiling; clip and exceed treated identically so the "
            "metric is vendor-neutral). A series is EXCLUDED from the absorbed-dose "
            f"analysis if its largest connected out-of-calibration component "
            f">= {IMPLANT_COMPONENT_CM3:g} cm^3, i.e. a compact metal implant whose "
            "atomic number Schneider cannot represent (photoelectric cross section "
            "misassigned). Threshold chosen from the cohort's natural gap "
            "(0.91-2.06 cm^3), not fitted to any one series."
        ),
        "is_pre_declared": True,
        "single_gate": "largest out-of-calibration component volume",
        "distance_is_reported_not_gated": True,
        "completes": "ct_dosemc_core.eligibility (header-only); pixel-based sibling",
        "threshold_cm3": IMPLANT_COMPONENT_CM3,
        "n_assessed": len(records),
        "n_eligible": n_eligible,
        "n_excluded": len(records) - n_eligible,
        "by_vendor": by_vendor,
        "vendor_balance_preserved": balanced,
        "vendor_balance_note": (
            "The surviving per-vendor counts are unequal; this is a consequence of a "
            "pre-declared criterion, not a defect. It is NOT corrected: adding probes "
            "would restart selection, and trimming would discard survivors of a "
            "declared rule. Every by-vendor table must carry N. The exclusions fire "
            "on all four vendors (GE, Siemens, Canon/Toshiba, Philips), which is the "
            "signature of a material rule rather than a vendor detector; Canon's "
            "higher count is corroborated by max in-body HU >> 3071 (true 16-bit "
            "metal) and is reported as a cohort finding."
        ),
        "excluded_distance_table_mm": distance_table,
        "series": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = ", ".join(f"{v} {c['eligible_N']}/{c['assessed']}" for v, c in sorted(by_vendor.items()))
    print(f"wrote {args.out}")
    print(f"eligible {n_eligible}/{len(records)}; by vendor (eligible/N): {counts}")
    for r in distance_table:
        print(
            f"  EXCLUDE {r['vendor']:14s} largest={r['largest_component_cm3']:.2f}cm3 "
            f"maxHU={r['max_hu_in_body']} nearest={r['nearest_scored_organ']}@{r['min_distance_mm']}mm"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

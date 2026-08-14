"""Out-of-calibration voxel distribution, before any exclusion threshold is set.

The eligibility criterion must be a *rule*, and the rule must not secretly be a
vendor detector.  ``HU > 3071`` is a vendor detector: 3071 HU is the saturation
ceiling of a 12-bit reconstruction, so the same implant clips *at* 3071 on
GE/Siemens/Philips and only *exceeds* it on a 16-bit Canon export.  The
vendor-neutral definition of an out-of-calibration voxel therefore treats clipping
and exceeding identically:

    out-of-calibration voxel  ==  inside the body contour AND HU >= 3071

This tool reports the *distribution* of those voxels per series so the exclusion
threshold can be chosen on physics, not on one series.  For each series it records:

* ``n_voxels`` and ``volume_cm3`` -- how much out-of-calibration material there is;
* connected components (``n_components``, ``largest_component_voxels/_cm3``) -- a
  scattered handful (surgical clip, calcification, beam-hardening speckle, all of
  which Schneider's cortical-bone range already covers) versus one compact blob
  (a port or a prosthesis);
* ``mass_fraction_lower_bound`` -- clamped-density mass of the out-of-calibration
  voxels over the body mass (a lower bound, since a clamp *under*-weighs metal);
* ``min_distance_mm`` from the out-of-calibration voxels to each scored organ, and
  to the nearest scored organ -- material far from every scored organ perturbs no
  scored dose.

No keep/exclude verdict is emitted here.  The threshold is set after reading this,
and its by-vendor breakdown is then checked so a residual vendor skew is reported
as either a rule defect or a genuine cohort finding.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DICOM_ROOT = REPO.parent / "ctsegdose_core"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ct_dosemc_core.ct_series import load_series, series_geometry  # noqa: E402
from ct_dosemc_core.phantom import body_contour, patient_density_map  # noqa: E402
from ct_dosemc_core.segment import load_mask  # noqa: E402
from ct_dosemc_core.volume import load_volume_hu  # noqa: E402

#: The 12-bit reconstruction saturation ceiling.  A voxel at or above this is
#: out-of-calibration whether it clipped here (12-bit) or exceeds it (16-bit);
#: defining it this way removes the vendor confound of ``> 3071``.
OUT_OF_CALIBRATION_HU = 3071.0


def _seg_json(uid: str, segdir: Path) -> dict[str, Any] | None:
    p = segdir / f"{uid}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def analyse_one(directory: Path, uid: str, segdir: Path) -> dict[str, Any]:
    from scipy import ndimage
    from scipy.spatial import cKDTree

    rec: dict[str, Any] = {"series_instance_uid": uid}
    try:
        series = load_series(directory, series_uid=uid or None)
        volume, _notes = load_volume_hu(series)
        _affine, spacing = series_geometry(series)  # (sz, sy, sx) mm
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
        return rec

    sz, sy, sx = (float(s) for s in spacing)
    voxel_cm3 = (sz * sy * sx) / 1000.0

    body = body_contour(volume)
    density, _body, report = patient_density_map(volume, body=body)
    body_mass_g = float(density[body].sum() * voxel_cm3)

    over = body & (volume >= OUT_OF_CALIBRATION_HU)
    n_over = int(over.sum())
    rec.update(
        {
            "definition_hu": OUT_OF_CALIBRATION_HU,
            "max_hu_in_body": report["max_hu_in_body"],
            "n_voxels": n_over,
            "volume_cm3": round(n_over * voxel_cm3, 4),
            "body_mass_g": round(body_mass_g, 1),
            "voxel_spacing_mm_zyx": [round(sz, 4), round(sy, 4), round(sx, 4)],
        }
    )
    if n_over == 0:
        rec.update(
            {
                "n_components": 0,
                "largest_component_voxels": 0,
                "largest_component_cm3": 0.0,
                "mass_fraction_lower_bound": 0.0,
                "nearest_scored_organ": None,
                "min_distance_mm": None,
                "min_distance_by_organ_mm": {},
            }
        )
        return rec

    labels, n_comp = ndimage.label(over)
    comp_sizes = np.bincount(labels.ravel())[1:] if n_comp else np.array([], dtype=int)
    largest = int(comp_sizes.max()) if comp_sizes.size else 0
    mass_lb_g = float(density[over].sum() * voxel_cm3)
    rec.update(
        {
            "n_components": int(n_comp),
            "largest_component_voxels": largest,
            "largest_component_cm3": round(largest * voxel_cm3, 4),
            "mass_fraction_lower_bound": round(mass_lb_g / body_mass_g, 6) if body_mass_g else None,
        }
    )

    # Distance from out-of-calibration voxels to each scored organ, in mm.
    scale = np.array([sz, sy, sx], dtype=np.float64)
    metal_mm = np.argwhere(over).astype(np.float64) * scale

    seg = _seg_json(uid, segdir)
    per_organ: dict[str, float] = {}
    if seg and seg.get("status") == "ok":
        mask_dir = Path(seg["segmentation"]["mask_dir"])
        organs = seg.get("organs") or seg["segmentation"].get("structures", [])
        for organ in organs:
            mp = mask_dir / f"{organ}.nii.gz"
            if not mp.exists():
                continue
            try:
                m = load_mask(mp, volume.shape)
            except Exception:  # noqa: BLE001
                continue
            org_idx = np.argwhere(m)
            if org_idx.size == 0:
                continue
            tree = cKDTree(org_idx.astype(np.float64) * scale)
            d, _ = tree.query(metal_mm, k=1)
            per_organ[organ] = round(float(d.min()), 2)
    if per_organ:
        nearest = min(per_organ, key=per_organ.get)
        rec["nearest_scored_organ"] = nearest
        rec["min_distance_mm"] = per_organ[nearest]
    else:
        rec["nearest_scored_organ"] = None
        rec["min_distance_mm"] = None
    rec["min_distance_by_organ_mm"] = dict(sorted(per_organ.items(), key=lambda kv: kv[1]))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provenance", type=Path, default=REPO / "data" / "PROVENANCE.json")
    ap.add_argument("--dicom-root", type=Path, default=DEFAULT_DICOM_ROOT)
    ap.add_argument("--segdir", type=Path, default=REPO / "results" / "phase2_cohort" / "segmentation")
    ap.add_argument("--out", type=Path, default=REPO / "results" / "phase2_cohort" / "metal_distribution.json")
    args = ap.parse_args()

    rows = json.loads(args.provenance.read_text(encoding="utf-8")).get("series", [])
    records: list[dict[str, Any]] = []
    for r in rows:
        uid = str(r.get("series_instance_uid", ""))
        local_path = str(r.get("local_path", ""))
        p = Path(local_path)
        directory = p if p.is_absolute() else (args.dicom_root / local_path)
        print(f"metal-dist: {str(r.get('vendor','')):14s} {uid[:20]}...", flush=True)
        rec = analyse_one(directory, uid, args.segdir)
        rec["vendor"] = str(r.get("vendor", ""))
        records.append(rec)
        if "error" in rec:
            print(f"  ERROR {rec['error']}", flush=True)
        else:
            print(
                f"  n={rec['n_voxels']:>6}  vol={rec['volume_cm3']:>8.3f}cm3  "
                f"comps={rec['n_components']:>4} largest={rec['largest_component_voxels']:>6}"
                f"  massfrac>={rec['mass_fraction_lower_bound']}  "
                f"nearest={rec['nearest_scored_organ']}@{rec['min_distance_mm']}mm "
                f"(maxHU {rec['max_hu_in_body']})",
                flush=True,
            )

    # Sort a compact view by largest compact blob so the order-of-magnitude gap shows.
    ranked = sorted(
        (r for r in records if "error" not in r),
        key=lambda r: r.get("largest_component_voxels", 0),
        reverse=True,
    )
    by_vendor: dict[str, dict[str, Any]] = {}
    for r in records:
        v = r.get("vendor") or "(unrecorded)"
        c = by_vendor.setdefault(v, {"series": 0, "with_out_of_calib": 0})
        c["series"] += 1
        if r.get("n_voxels", 0) > 0:
            c["with_out_of_calib"] += 1

    payload = {
        "definition": (
            "out-of-calibration voxel = inside body contour AND HU >= 3071 "
            "(the 12-bit saturation ceiling; treats clip and exceed identically so "
            "the metric is vendor-neutral, not a 16-bit-export detector)"
        ),
        "no_threshold_applied": True,
        "scored_organs": 12,
        "by_vendor_presence": by_vendor,
        "ranked_by_largest_component": [
            {
                "vendor": r["vendor"],
                "series_instance_uid": r["series_instance_uid"],
                "n_voxels": r["n_voxels"],
                "largest_component_voxels": r["largest_component_voxels"],
                "largest_component_cm3": r["largest_component_cm3"],
                "n_components": r["n_components"],
                "mass_fraction_lower_bound": r["mass_fraction_lower_bound"],
                "nearest_scored_organ": r["nearest_scored_organ"],
                "min_distance_mm": r["min_distance_mm"],
                "max_hu_in_body": r["max_hu_in_body"],
            }
            for r in ranked
        ],
        "series": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

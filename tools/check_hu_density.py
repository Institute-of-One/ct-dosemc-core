"""D4 (early) -- verify the HU -> density write-out on real cohort series.

Running this on the first few series *before* the full segmentation finishes is
deliberate: the failure it catches is the one that destroyed four GE series in IORN-006,
where a mis-decoded Pixel Padding Value turned the whole image into a block of air with
no error anywhere downstream. The Monte Carlo would then track photons through a patient
made entirely of air. Better to see it on three series now than on forty later.

For each sampled series this loads the HU volume through the same padding-aware path the
dose calculation uses (:func:`ct_dosemc_core.volume.load_volume_hu`), maps it to mass
density (:func:`ct_dosemc_core.phantom.hu_to_density`), and checks:

* the density grid is exactly the CT grid -- the dose grid voxel is the CT voxel;
* every density is strictly positive and within the Schneider calibration range;
* the volume is not, in fact, a block of air (a decoded-padding failure), judged from
  the fraction of soft-tissue and higher-density voxels a real abdomen must contain.

No segmentation is needed, so this is independent of D3 and can run in parallel.
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
from ct_dosemc_core.phantom import (  # noqa: E402
    _SCHNEIDER_DENSITY_G_CM3,
    patient_density_map,
)
from ct_dosemc_core.volume import load_volume_hu  # noqa: E402

#: Inside the body contour a real patient is mostly tissue. If almost nothing there is
#: above the air/lung band, the volume decoded to air (the padding failure) and must be
#: flagged rather than passed to the Monte Carlo.
MIN_SOFT_TISSUE_FRACTION_IN_BODY = 0.20
SOFT_TISSUE_HU = -200.0


def check_one(directory: Path, uid: str) -> dict[str, Any]:
    rec: dict[str, Any] = {"series_instance_uid": uid, "dicom_dir": str(directory), "passed": False}
    try:
        series = load_series(directory, series_uid=uid or None)
        volume, notes = load_volume_hu(series)
        affine, spacing = series_geometry(series)
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
        return rec

    # The density universe the Monte Carlo will actually track through: air outside the
    # body contour, Schneider inside, with out-of-calibration voxels reported.
    density, body, report = patient_density_map(volume)
    lo, hi = float(min(_SCHNEIDER_DENSITY_G_CM3)), float(max(_SCHNEIDER_DENSITY_G_CM3))

    grid_ok = density.shape == volume.shape
    positive = bool(np.all(density > 0.0))
    in_range = bool(density.min() >= lo - 1e-9 and density.max() <= hi + 1e-9)

    in_body = volume[body] if body.any() else volume[:0]
    soft_in_body = float((in_body > SOFT_TISSUE_HU).mean()) if in_body.size else 0.0
    not_air_block = soft_in_body >= MIN_SOFT_TISSUE_FRACTION_IN_BODY

    # Calibration read (item 1a): in-body air/lung near -1000 and soft tissue near 0 are
    # what a correctly scaled series shows; a swapped slope/intercept would not land here.
    air_band = in_body[(in_body > -1100) & (in_body < -600)] if in_body.size else np.array([])
    soft_band = in_body[(in_body > -100) & (in_body < 150)] if in_body.size else np.array([])
    calib = {
        "in_body_p1_hu": round(float(np.percentile(in_body, 1)), 1) if in_body.size else None,
        "in_body_median_hu": round(float(np.median(in_body)), 1) if in_body.size else None,
        "in_body_air_lung_mode_hu": _mode(air_band),
        "in_body_soft_tissue_mode_hu": _mode(soft_band),
    }

    rec.update(
        {
            "passed": grid_ok and positive and in_range and not_air_block,
            "warnings": notes,
            "volume_shape_zyx": [int(n) for n in volume.shape],
            "voxel_spacing_mm_zyx": [round(float(v), 4) for v in spacing],
            "grid_matches_ct": grid_ok,
            "density_positive": positive,
            "density_in_schneider_range": in_range,
            "hu_range": report["hu_range"],
            "body_fraction": report["body_fraction"],
            "n_above_calibration_in_body": report["n_above_calibration_in_body"],
            "max_hu_in_body": report["max_hu_in_body"],
            "in_body_calibration": calib,
            "density_g_cm3": {
                "min": round(float(density.min()), 5),
                "median": round(float(np.median(density)), 5),
                "max": round(float(density.max()), 5),
            },
            "fraction_soft_tissue_or_denser_in_body": round(soft_in_body, 4),
            "not_an_air_block": not_air_block,
            "affine_slice_spacing_mm": round(float(affine[2, 2]), 4),
        }
    )
    if not rec["passed"]:
        reasons = []
        if not grid_ok:
            reasons.append("density grid != CT grid")
        if not positive:
            reasons.append("non-positive density present")
        if not in_range:
            reasons.append("density outside Schneider range")
        if not not_air_block:
            reasons.append(
                f"only {soft_in_body:.1%} of in-body voxels are above {SOFT_TISSUE_HU:g} HU; "
                "the volume looks like decoded-padding air, not a patient"
            )
        rec["failure_reasons"] = reasons
    return rec


def _mode(band: np.ndarray) -> float | None:
    if band.size == 0:
        return None
    hist, edges = np.histogram(band, bins=50)
    return round(float(edges[int(np.argmax(hist))]), 1)


def _sample(rows: list[dict[str, Any]], per_vendor: int, limit: int) -> list[dict[str, Any]]:
    if limit:
        return rows[:limit]
    taken: dict[str, int] = {}
    out = []
    for r in rows:
        v = str(r.get("vendor", ""))
        if taken.get(v, 0) < per_vendor:
            out.append(r)
            taken[v] = taken.get(v, 0) + 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provenance", type=Path, default=REPO / "data" / "PROVENANCE.json")
    ap.add_argument("--dicom-root", type=Path, default=DEFAULT_DICOM_ROOT)
    ap.add_argument("--out", type=Path, default=REPO / "results" / "phase2_cohort" / "hu_density_check.json")
    ap.add_argument("--per-vendor", type=int, default=1, help="sample N series per vendor")
    ap.add_argument("--limit", type=int, default=0, help="instead, check the first N series")
    args = ap.parse_args()

    payload = json.loads(args.provenance.read_text(encoding="utf-8"))
    rows = _sample(payload.get("series", []), args.per_vendor, args.limit)

    records = []
    for r in rows:
        uid = str(r.get("series_instance_uid", ""))
        local_path = str(r.get("local_path", ""))
        p = Path(local_path)
        directory = p if p.is_absolute() else (args.dicom_root / local_path)
        print(f"D4 HU->density: {r.get('vendor',''):14s} {uid[:24]}...", flush=True)
        rec = check_one(directory, uid)
        rec["vendor"] = str(r.get("vendor", ""))
        records.append(rec)
        detail = rec.get("error") or (
            f"HU {rec['hu_range']} body {rec['body_fraction']:.0%} "
            f"in-body air/soft mode {rec['in_body_calibration']['in_body_air_lung_mode_hu']}/"
            f"{rec['in_body_calibration']['in_body_soft_tissue_mode_hu']} HU "
            f"metal(>3000)in-body {rec['n_above_calibration_in_body']}"
        )
        print(f"  {'PASS' if rec['passed'] else 'FAIL'}: {detail}", flush=True)

    n_pass = sum(1 for r in records if r["passed"])
    out_payload = {
        "calibration": "Schneider et al. (1996) generic piecewise-linear (ct_dosemc_core.phantom)",
        "n_checked": len(records),
        "n_passed": n_pass,
        "n_failed": len(records) - n_pass,
        "series": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {n_pass}/{len(records)} passed")
    return 0 if n_pass == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())

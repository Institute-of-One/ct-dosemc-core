"""Measure, not assume, the cost of the 2.5 mm dose grid.

The patient dose grid cannot be the native 0.7 mm image: the air box must reach the
focal spot (G3), which needs a ~130 cm box, and at 0.7 mm that is ~2.4e9 voxels.
At 2.5 mm the same box is ~520x520x200 = 5.4e7 voxels -- about twice the G2 phantom
and the *same* 0.25 cm at which G2/G3 convergence was measured, so the voxel-size
systematic term carries over. The price of resampling to 2.5 mm is a partial-volume
change in each organ; this tool measures it rather than assuming it is small.

For every eligible series and every scored organ it reports:
    mass_native   = sum(density * mask) * voxel_volume        on the native grid
    mass_2p5mm    = sum(density_2p5 * occupancy_2p5) * vox2p5  on an isotropic 2.5 mm grid
where the 2.5 mm density and organ occupancy are volume-conserving (order-1) zooms of
the native density and binary mask. The ratio mass_2p5mm / mass_native is the
resampling cost, reported per organ and aggregated per vendor.
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
from ct_dosemc_core.phantom import patient_density_map  # noqa: E402
from ct_dosemc_core.segment import load_mask  # noqa: E402
from ct_dosemc_core.volume import load_volume_hu  # noqa: E402

DOSE_GRID_MM = 2.5


def _seg(uid: str, segdir: Path) -> dict | None:
    p = segdir / f"{uid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def analyse_one(directory: Path, uid: str, segdir: Path) -> dict[str, Any]:
    from scipy import ndimage

    rec: dict[str, Any] = {"series_instance_uid": uid}
    try:
        series = load_series(directory, series_uid=uid or None)
        volume, _n = load_volume_hu(series)
        _affine, spacing = series_geometry(series)  # (sz, sy, sx) mm
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
        return rec

    sz, sy, sx = (float(s) for s in spacing)
    vox_native_cm3 = (sz * sy * sx) / 1000.0
    vox_25_cm3 = (DOSE_GRID_MM**3) / 1000.0
    factors = (sz / DOSE_GRID_MM, sy / DOSE_GRID_MM, sx / DOSE_GRID_MM)

    density, body, _report = patient_density_map(volume)
    density = density.astype(np.float32)
    density_25 = ndimage.zoom(density, factors, order=1, mode="nearest")

    seg = _seg(uid, segdir)
    if not seg or seg.get("status") != "ok":
        rec["error"] = "no segmentation"
        return rec
    mask_dir = Path(seg["segmentation"]["mask_dir"])
    organs = seg.get("organs") or seg["segmentation"].get("structures", [])

    rec["voxel_spacing_mm_zyx"] = [round(sz, 4), round(sy, 4), round(sx, 4)]
    rec["native_shape_zyx"] = [int(n) for n in volume.shape]
    rec["resampled_shape_zyx"] = [int(n) for n in density_25.shape]
    per_organ: dict[str, dict[str, float]] = {}
    for organ in organs:
        mp = mask_dir / f"{organ}.nii.gz"
        if not mp.exists():
            continue
        try:
            m = load_mask(mp, volume.shape)
        except Exception:  # noqa: BLE001
            continue
        if not m.any():
            continue
        mass_native = float((density[m]).sum() * vox_native_cm3)
        occ_25 = ndimage.zoom(m.astype(np.float32), factors, order=1, mode="nearest")
        np.clip(occ_25, 0.0, 1.0, out=occ_25)
        mass_25 = float((density_25 * occ_25).sum() * vox_25_cm3)
        per_organ[organ] = {
            "mass_native_g": round(mass_native, 2),
            "mass_2p5mm_g": round(mass_25, 2),
            "ratio_2p5_over_native": round(mass_25 / mass_native, 4) if mass_native else None,
            "native_voxels": int(m.sum()),
        }
    rec["organs"] = per_organ
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provenance", type=Path, default=REPO / "data" / "PROVENANCE.json")
    ap.add_argument("--eligibility", type=Path, default=REPO / "results" / "phase2_cohort" / "density_eligibility.json")
    ap.add_argument("--dicom-root", type=Path, default=DEFAULT_DICOM_ROOT)
    ap.add_argument("--segdir", type=Path, default=REPO / "results" / "phase2_cohort" / "segmentation")
    ap.add_argument("--out", type=Path, default=REPO / "results" / "phase2_cohort" / "resample_cost.json")
    args = ap.parse_args()

    prov = {s["series_instance_uid"]: s for s in json.loads(args.provenance.read_text(encoding="utf-8")).get("series", [])}
    elig = json.loads(args.eligibility.read_text(encoding="utf-8"))
    eligible_uids = [r["series_instance_uid"] for r in elig["series"] if r.get("eligible")]

    records: list[dict[str, Any]] = []
    for uid in eligible_uids:
        row = prov.get(uid, {})
        vendor = str(row.get("vendor", ""))
        local_path = str(row.get("local_path", ""))
        p = Path(local_path)
        directory = p if p.is_absolute() else (args.dicom_root / local_path)
        print(f"resample-cost: {vendor:14s} {uid[:20]}...", flush=True)
        rec = analyse_one(directory, uid, args.segdir)
        rec["vendor"] = vendor
        records.append(rec)
        if "error" in rec:
            print(f"  ERROR {rec['error']}", flush=True)
        else:
            ratios = [o["ratio_2p5_over_native"] for o in rec["organs"].values() if o["ratio_2p5_over_native"]]
            if ratios:
                print(f"  organs={len(ratios)} ratio min/median/max = "
                      f"{min(ratios):.3f}/{float(np.median(ratios)):.3f}/{max(ratios):.3f}", flush=True)

    # Aggregate per organ and per vendor.
    per_organ_all: dict[str, list[float]] = {}
    per_vendor_all: dict[str, list[float]] = {}
    for rec in records:
        if "error" in rec:
            continue
        v = rec["vendor"] or "(unrecorded)"
        for organ, o in rec["organs"].items():
            r = o["ratio_2p5_over_native"]
            if r is None:
                continue
            per_organ_all.setdefault(organ, []).append(r)
            per_vendor_all.setdefault(v, []).append(r)

    def _stats(xs: list[float]) -> dict[str, float]:
        a = np.asarray(xs, float)
        return {
            "n": int(a.size),
            "median_ratio": round(float(np.median(a)), 4),
            "mean_ratio": round(float(a.mean()), 4),
            "min_ratio": round(float(a.min()), 4),
            "max_ratio": round(float(a.max()), 4),
            "median_abs_pct": round(float(np.median(np.abs(a - 1.0)) * 100), 2),
            "max_abs_pct": round(float(np.max(np.abs(a - 1.0)) * 100), 2),
        }

    payload = {
        "dose_grid_mm": DOSE_GRID_MM,
        "definition": (
            "mass_2p5mm / mass_native per organ; mass = sum(density * occupancy) * "
            "voxel_volume; 2.5 mm density and occupancy are order-1 (volume-conserving) "
            "zooms of the native density and binary mask. Cost of the dose grid, measured."
        ),
        "n_series": sum(1 for r in records if "error" not in r),
        "by_organ": {k: _stats(v) for k, v in sorted(per_organ_all.items())},
        "by_vendor": {k: _stats(v) for k, v in sorted(per_vendor_all.items())},
        "series": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out}")
    print("by organ (median abs % mass change at 2.5 mm):")
    for k, s in payload["by_organ"].items():
        print(f"  {k:22s} n={s['n']:>2} median {s['median_ratio']:.3f}  |Δ| med {s['median_abs_pct']:.2f}%  max {s['max_abs_pct']:.2f}%")
    print("by vendor:")
    for k, s in payload["by_vendor"].items():
        print(f"  {k:14s} n={s['n']:>3} median {s['median_ratio']:.3f}  |Δ| med {s['median_abs_pct']:.2f}%  max {s['max_abs_pct']:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

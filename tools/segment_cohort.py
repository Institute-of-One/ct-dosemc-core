"""D3 -- organ masks for the Phase-2 cohort, one series at a time, resumably.

Forty series segmented unattended will lose a few: a missing slice, two acquisitions
concatenated under one UID, a padding value that decodes to a block of air. The worst
outcome is a series that fails silently and is averaged into the results as if it had
succeeded. So this runner takes the same discipline the replica study did:

* **one series is finalised before the next begins** -- its masks and its per-series
  JSON are on disk, and its verdict is in the manifest, before the loop moves on;
* **every series has a recorded status** -- ``ok``, ``downgraded`` (the 1.5 mm model
  ran out of memory and the 3 mm model was used, which is coarser and is flagged), or
  ``failed`` with the exception text. Nothing is dropped without a reason;
* **the run resumes** -- a series already ``ok`` in the manifest, at the same
  resolution and organ set, is skipped, and ``segment_volume`` reuses cached masks.

Inference runs in a separate CPU process (``--device cpu`` by default) so it does not
contend with a GPU Monte-Carlo job (Route B) for device memory.

Resolution: full 1.5 mm by default (``--fast`` selects the 3 mm model). Absorbed
organ dose is sensitive to the partial-volume error at an organ boundary, so the finer
grid is the right default here; the choice, and how it relates to IORN-006, is recorded
in ``segmentation_config.json`` beside the results.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ct_dosemc_core import __version__  # noqa: E402
from ct_dosemc_core.ct_series import load_series, series_geometry  # noqa: E402
from ct_dosemc_core.provenance import environment  # noqa: E402
from ct_dosemc_core.segment import (  # noqa: E402
    ABDOMINAL_ORGANS,
    SegmentationUnavailable,
    load_masks,
    segment_volume,
)
from ct_dosemc_core.volume import load_volume_hu  # noqa: E402

#: Where the DICOM actually sits. ``local_path`` in data/PROVENANCE.json is relative to
#: the repository that downloaded it (the IORN-006 sibling holds the shared cache); a
#: reader who re-fetches into this repo's data/ points ``--dicom-root`` at the repo.
DEFAULT_DICOM_ROOT = REPO.parent / "ctsegdose_core"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _config(args: argparse.Namespace, organs: list[str]) -> dict[str, Any]:
    """The segmentation settings, and how they relate to IORN-006. Recorded once."""
    return {
        "task": "total",
        "roi_subset": organs,
        "resolution": "3mm (fast model)" if args.fast else "1.5mm (full-resolution model)",
        "fast": args.fast,
        "device": args.device,
        "inference_python": args.python or sys.executable,
        "totalsegmentator_requirement": ">=2.0 (Apache-2.0, inference only; weights fetched on first use)",
        "totalsegmentator_version": "recorded per series once inference has run",
        "torch_version": "recorded per series once inference has run",
        "alignment_with_iorn006": (
            "Same TotalSegmentator 'total' task and the same abdominal roi_subset as "
            "IORN-006 (ctsegdose-core). IORN-006 defaults to the 3 mm fast model and "
            "offers 1.5 mm via --full-resolution; IORN-007 defaults to full 1.5 mm "
            "because absorbed organ dose is sensitive to partial-volume error at organ "
            "boundaries. This is an intentional difference, recorded here rather than "
            "left implicit. TotalSegmentator and torch versions are pinned only as >=2.0 "
            "in pyproject and captured exactly, per series, in each series' JSON."
        ),
        "ct_dosemc_core_version": __version__,
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"series": {}}


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    entries = manifest.get("series", {})
    statuses = [e.get("status") for e in entries.values()]
    manifest["updated_utc"] = _now()
    manifest["n_total"] = len(entries)
    manifest["n_ok"] = sum(1 for s in statuses if s == "ok")
    manifest["n_downgraded"] = sum(1 for s in statuses if s == "downgraded")
    manifest["n_failed"] = sum(1 for s in statuses if s == "failed")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _mask_summary(run, expected_shape: tuple[int, int, int]) -> dict[str, Any]:
    """Per-organ voxel counts, and which organs touch the z boundary (truncated)."""
    masks = load_masks(run)  # raises SegmentationUnavailable on any grid mismatch
    nz = expected_shape[0]
    organs: dict[str, Any] = {}
    for name, m in masks.items():
        count = int(m.sum())
        if count == 0:
            organs[name] = {"voxels": 0, "present": False}
            continue
        zc = np.argwhere(m.any(axis=(1, 2))).ravel()
        organs[name] = {
            "voxels": count,
            "present": True,
            "z_extent": [int(zc.min()), int(zc.max())],
            "truncated": bool(zc.min() == 0 or zc.max() == nz - 1),
        }
    return {
        "n_structures_returned": len(run.structures),
        "structures": list(run.structures),
        "organs_with_voxels": sorted(k for k, v in organs.items() if v["present"]),
        "organs": organs,
    }


def process_series(row: dict[str, Any], args: argparse.Namespace, organs: tuple[str, ...]) -> dict[str, Any]:
    """Segment one series into a per-series record. Never raises; failure is a record."""
    uid = str(row.get("series_instance_uid", ""))
    vendor = str(row.get("vendor", ""))
    local_path = str(row.get("local_path", ""))
    p = Path(local_path)
    directory = p if p.is_absolute() else (args.dicom_root / local_path)
    work_dir = args.work_dir / uid / ("3mm" if args.fast else "1.5mm")

    record: dict[str, Any] = {
        "series_instance_uid": uid,
        "vendor": vendor,
        "collection": row.get("collection", ""),
        "dicom_dir": str(directory),
        "status": "failed",
        "stage_reached": "",
        "error": "",
        "warnings": [],
        "resolution": "3mm" if args.fast else "1.5mm",
    }
    started = time.monotonic()

    if not directory.is_dir():
        record["error"] = f"DICOM directory not found: {directory}"
        record["elapsed_s"] = 0.0
        return record

    try:
        series = load_series(directory, series_uid=uid or None)
        record["stage_reached"] = "loaded"
        record["n_slices"] = series.n_slices
        record["grid"] = series.grid.to_dict()
        record["warnings"].extend(series.grid.warnings)
    except Exception as exc:  # noqa: BLE001 - a load failure is a recorded verdict
        record["error"] = f"load failed: {type(exc).__name__}: {exc}"
        record["elapsed_s"] = round(time.monotonic() - started, 1)
        return record

    try:
        volume, notes = load_volume_hu(series)
        affine, spacing = series_geometry(series)
        record["warnings"].extend(notes)
        record["volume_shape_zyx"] = list(int(n) for n in volume.shape)
        record["voxel_spacing_mm_zyx"] = [round(float(v), 4) for v in spacing]
        record["stage_reached"] = "volume"
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"volume/geometry failed: {type(exc).__name__}: {exc}"
        record["elapsed_s"] = round(time.monotonic() - started, 1)
        return record

    downgraded = False
    try:
        run = segment_volume(
            volume, affine, work_dir,
            voxel_spacing_mm=spacing, organs=organs, fast=args.fast,
            device=args.device, python_executable=args.python,
        )
    except SegmentationUnavailable as exc:
        if args.fast or args.no_fallback:
            record["error"] = f"segmentation failed: {exc}"
            record["elapsed_s"] = round(time.monotonic() - started, 1)
            return record
        record["warnings"].append(
            f"the 1.5 mm model failed on this series ({exc}); retried with the 3 mm "
            "model, whose masks are coarser than the rest of the cohort"
        )
        downgraded = True
        try:
            run = segment_volume(
                volume, affine, args.work_dir / uid / "3mm-fallback",
                voxel_spacing_mm=spacing, organs=organs, fast=True,
                device=args.device, python_executable=args.python,
            )
        except Exception as exc2:  # noqa: BLE001
            record["error"] = f"segmentation failed at both resolutions: {exc2}"
            record["elapsed_s"] = round(time.monotonic() - started, 1)
            return record
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"segmentation failed: {type(exc).__name__}: {exc}"
        record["elapsed_s"] = round(time.monotonic() - started, 1)
        return record

    try:
        record["segmentation"] = run.to_dict()
        record["masks"] = _mask_summary(run, tuple(int(n) for n in volume.shape))
        record["stage_reached"] = "segmented"
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"masks unreadable / grid mismatch: {type(exc).__name__}: {exc}"
        record["elapsed_s"] = round(time.monotonic() - started, 1)
        return record

    if not record["masks"]["organs_with_voxels"]:
        record["error"] = "no organ mask contains any voxel in this series"
        record["elapsed_s"] = round(time.monotonic() - started, 1)
        return record

    record["status"] = "downgraded" if downgraded else "ok"
    record["totalsegmentator_version"] = run.totalsegmentator_version
    record["torch_version"] = run.torch_version
    record["cached"] = run.cached
    record["elapsed_s"] = round(time.monotonic() - started, 1)
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provenance", type=Path, default=REPO / "data" / "PROVENANCE.json")
    ap.add_argument("--dicom-root", type=Path, default=DEFAULT_DICOM_ROOT,
                    help="base for series local_path (default: IORN-006 sibling cache)")
    ap.add_argument("--out-dir", type=Path, default=REPO / "results" / "phase2_cohort" / "segmentation")
    ap.add_argument("--work-dir", type=Path, default=REPO / "segmentations",
                    help="where per-series masks are written")
    ap.add_argument("--manifest", type=Path,
                    default=REPO / "results" / "phase2_cohort" / "segmentation_manifest.json")
    ap.add_argument("--config-out", type=Path,
                    default=REPO / "results" / "phase2_cohort" / "segmentation_config.json")
    ap.add_argument("--organs", default="", help="comma-separated; default is the abdominal set")
    ap.add_argument("--fast", action="store_true", help="3 mm model instead of full 1.5 mm")
    ap.add_argument("--no-fallback", action="store_true",
                    help="do not retry a failed 1.5 mm series at 3 mm")
    ap.add_argument("--device", default="cpu", help="cpu | gpu | mps (default cpu to spare the GPU)")
    ap.add_argument("--python", default="", help="interpreter that runs inference (default: this one)")
    ap.add_argument("--limit", type=int, default=0, help="segment at most N series (smoke test)")
    ap.add_argument("--vendor", default="", help="only this vendor")
    ap.add_argument("--series", default="", help="only this Series Instance UID")
    ap.add_argument("--redo", action="store_true", help="re-run series already ok in the manifest")
    args = ap.parse_args()

    organs = tuple(s for s in args.organs.split(",") if s) or ABDOMINAL_ORGANS
    config = _config(args, list(organs))

    payload = json.loads(args.provenance.read_text(encoding="utf-8"))
    rows = payload.get("series", [])
    if args.vendor:
        rows = [r for r in rows if str(r.get("vendor", "")) == args.vendor]
    if args.series:
        rows = [r for r in rows if str(r.get("series_instance_uid", "")) == args.series]
    if args.limit:
        rows = rows[: args.limit]

    args.config_out.parent.mkdir(parents=True, exist_ok=True)
    args.config_out.write_text(
        json.dumps({"environment": environment(REPO), "segmentation_config": config}, indent=2,
                   ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    manifest = _load_manifest(args.manifest)
    manifest.setdefault("series", {})
    manifest["config"] = config
    manifest.setdefault("started_utc", _now())
    args.out_dir.mkdir(parents=True, exist_ok=True)

    resolution = "3mm" if args.fast else "1.5mm"
    print(f"D3 segmentation: {len(rows)} series, {resolution}, device={args.device}")
    for i, row in enumerate(rows, 1):
        uid = str(row.get("series_instance_uid", ""))
        prior = manifest["series"].get(uid, {})
        per_series_json = args.out_dir / f"{uid}.json"
        already = (
            not args.redo
            and prior.get("status") in ("ok", "downgraded")
            and prior.get("resolution") == resolution
            and prior.get("organs") == list(organs)
            and per_series_json.exists()
        )
        if already:
            print(f"[{i}/{len(rows)}] {uid[:24]}... skip ({prior['status']}, cached)")
            continue

        print(f"[{i}/{len(rows)}] {uid[:24]}... {row.get('vendor','')}", flush=True)
        record = process_series(row, args, organs)
        record["organs"] = list(organs)
        per_series_json.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        manifest["series"][uid] = {
            "status": record["status"],
            "vendor": record["vendor"],
            "resolution": resolution,
            "organs": list(organs),
            "stage_reached": record["stage_reached"],
            "error": record["error"],
            "elapsed_s": record["elapsed_s"],
            "totalsegmentator_version": record.get("totalsegmentator_version", ""),
            "n_organs_with_voxels": len(record.get("masks", {}).get("organs_with_voxels", [])),
            "per_series_json": str(per_series_json),
            "mask_dir": record.get("segmentation", {}).get("mask_dir", ""),
            "updated_utc": _now(),
        }
        _write_manifest(args.manifest, manifest)
        status = record["status"]
        detail = record["error"] or f"{manifest['series'][uid]['n_organs_with_voxels']} organs"
        print(f"          -> {status}: {detail} ({record['elapsed_s']}s)", flush=True)

    _write_manifest(args.manifest, manifest)
    print(f"done. ok={manifest['n_ok']} downgraded={manifest['n_downgraded']} "
          f"failed={manifest['n_failed']} / {manifest['n_total']}")
    print(f"manifest: {args.manifest}")
    return 0 if manifest["n_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

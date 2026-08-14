"""End-to-end patient absorbed-dose driver: one CT series through MC-GPU.

Wires the pieces that already exist (phantom, Schneider groups, bowtie sub-fans,
focal spot inside the 130 cm box, TCM I(z), bbox ROI, organ-dose reduction) and
invokes MC-GPU. ``--plan-only`` walks the chain and writes inputs without taking
the GPU; ``--run`` is the Monte Carlo. Production (40 series) is a later call;
this tool is the one-series path-through.

Do not start ``--run`` while Route B (or any other GPU job) owns the device.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ct_dosemc_core.ct_series import load_series, series_geometry  # noqa: E402
from ct_dosemc_core.driver import (  # noqa: E402
    bowtie_subfan_plan,
    organ_doses_from_roi,
)
from ct_dosemc_core.mcgpu_io import (  # noqa: E402
    read_dose_map,
    run_mcgpu,
    stage_material_files,
    write_input_file,
    write_voxel_file,
)
from ct_dosemc_core.patient import (  # noqa: E402
    DEFAULT_SAD_CM,
    DOSE_GRID_MM,
    FOCAL_BOX_XY_CM,
    build_patient_phantom,
    pad_mask,
    resample_isotropic,
    union_organ_roi,
)
from ct_dosemc_core.provenance import write_results  # noqa: E402
from ct_dosemc_core.segment import SegmentationRun, load_masks  # noqa: E402
from ct_dosemc_core.source_model import (  # noqa: E402
    canonical_vendor,
    focal_spot_cm,
    tube_current_profile,
)
from ct_dosemc_core.spectra import write_mcgpu_spectrum  # noqa: E402
from ct_dosemc_core.volume import load_volume_hu  # noqa: E402

MATERIALS_DIR = REPO / "materials"
ELIGIBILITY = REPO / "results" / "phase2_cohort" / "density_eligibility.json"
DATA_PROVENANCE = REPO / "data" / "PROVENANCE.json"
DEFAULT_DICOM_ROOT = REPO.parent / "ctsegdose_core"
MCGPU_TIME_THRESHOLD = 100_000.0


def _first_eligible(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for row in payload["series"]:
        if row.get("eligible"):
            return row
    raise SystemExit(f"no eligible series in {path}")


def _series_row(uid: str) -> dict[str, Any]:
    data = json.loads(DATA_PROVENANCE.read_text(encoding="utf-8"))
    for row in data.get("series", []):
        if row.get("series_instance_uid") == uid:
            return row
    raise SystemExit(f"{uid} not in {DATA_PROVENANCE}")


def _seg_record(uid: str) -> dict[str, Any]:
    path = REPO / "results" / "phase2_cohort" / "segmentation" / f"{uid}.json"
    if not path.is_file():
        raise SystemExit(f"no segmentation record at {path}")
    rec = json.loads(path.read_text(encoding="utf-8"))
    if rec.get("status") not in {"ok", "downgraded"}:
        raise SystemExit(f"segmentation status {rec.get('status')!r} for {uid}")
    return rec


def _dicom_dir(row: dict[str, Any], dicom_root: Path) -> Path:
    local = str(row.get("local_path", ""))
    p = Path(local)
    directory = p if p.is_absolute() else (dicom_root / local)
    if not directory.is_dir():
        raise SystemExit(f"DICOM directory not found: {directory}")
    return directory


def _resample_masks(
    native: dict[str, np.ndarray],
    spacing_zyx_mm: tuple[float, float, float],
    pad_before: tuple[int, int, int],
    shape_zyx: tuple[int, int, int],
    iso_mm: float,
) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for name, mask in native.items():
        iso = resample_isotropic(mask.astype(np.uint8), spacing_zyx_mm, iso_mm=iso_mm, order=0)
        out[name] = pad_mask(iso.astype(bool), pad_before, shape_zyx)
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--series", default=None, help="Series Instance UID (default: first eligible)")
    ap.add_argument("--dicom-root", type=Path, default=DEFAULT_DICOM_ROOT)
    ap.add_argument("--executable", default=str(REPO / "vendor" / "build" / "MC-GPU_v1.3_GPU.exe"))
    ap.add_argument("--run", action="store_true", help="invoke MC-GPU (default is plan-only)")
    ap.add_argument("--plan-only", action="store_true", help="write inputs, do not take the GPU")
    ap.add_argument("--histories", type=float, default=3.2e6, help="total histories across all beamlets")
    ap.add_argument("--projections", type=int, default=8)
    ap.add_argument("--sub-fans", type=int, default=4)
    ap.add_argument("--sad-cm", type=float, default=DEFAULT_SAD_CM)
    ap.add_argument("--collimation-cm", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=1234567890)
    ap.add_argument("--timeout-hours", type=float, default=12.0)
    ap.add_argument("--tag", default=None)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    do_run = bool(args.run) and not bool(args.plan_only)

    elig = _first_eligible(ELIGIBILITY) if not args.series else None
    uid = args.series or str(elig["series_instance_uid"])
    row = _series_row(uid)
    seg = _seg_record(uid)
    vendor = canonical_vendor(str(row.get("manufacturer") or row.get("vendor")))
    tag = args.tag or f"patient_{uid.split('.')[-1][:16]}"
    rundir = REPO / "results" / "phase2_patient" / tag
    rundir.mkdir(parents=True, exist_ok=True)

    print(f"[patient] series {uid}", flush=True)
    print(f"[patient] vendor={vendor}  rundir={rundir}", flush=True)

    directory = _dicom_dir(row, args.dicom_root)
    series = load_series(directory, series_uid=uid)
    volume_hu, notes = load_volume_hu(series)
    _affine, spacing = series_geometry(series)
    tcm = tube_current_profile(series)
    print(
        f"[tcm   ] {len(tcm.current_ma)} slices, "
        f"I={float(tcm.current_ma.min()):.0f}-{float(tcm.current_ma.max()):.0f} mA, "
        f"modulated={tcm.modulated}",
        flush=True,
    )
    if notes:
        for n in notes:
            print(f"[volume] {n}", flush=True)

    run = SegmentationRun(
        mask_dir=Path(seg["segmentation"]["mask_dir"]),
        structures=list(seg["segmentation"]["structures"]),
        volume_shape=tuple(int(x) for x in seg["volume_shape_zyx"]),
        voxel_spacing_mm=tuple(float(x) for x in seg["voxel_spacing_mm_zyx"]),
    )
    native_masks = load_masks(run)
    if not native_masks:
        raise SystemExit(f"no organ masks in {run.mask_dir}")

    phantom, report = build_patient_phantom(volume_hu, spacing, iso_mm=DOSE_GRID_MM)
    pad = tuple(int(x) for x in report["pad_before_zyx"])
    masks = _resample_masks(native_masks, spacing, pad, phantom.shape_zyx, DOSE_GRID_MM)
    present = {k: v for k, v in masks.items() if v.any()}
    if not present:
        raise SystemExit("every organ mask is empty after resample+pad")
    roi = union_organ_roi(present, pad_voxels=1)
    bbox = phantom.bbox_cm
    iso = phantom.centre_cm()
    pos0, dir0 = focal_spot_cm(bbox, args.sad_cm, gantry_deg=0.0, isocentre_cm=iso)
    print(
        f"[phant] {phantom.n_voxels[0]}x{phantom.n_voxels[1]}x{phantom.n_voxels[2]} "
        f"@ {phantom.voxel_size_cm[0]:g} cm, bbox={bbox[0]:.1f}x{bbox[1]:.1f}x{bbox[2]:.1f} cm, "
        f"{len(phantom.materials)} materials",
        flush=True,
    )
    print(f"[focus] gantry 0: {pos0} -> {dir0} (inside box)", flush=True)

    # Fan must cover the reconstructed FOV, not just a 16 cm PMMA cylinder.
    half_fan = math.degrees(math.asin(min(0.999, 25.0 / args.sad_cm))) + 2.0
    kvp = float(series.kvp or 120.0)
    plans = bowtie_subfan_plan(
        vendor,
        n_sub_fans=int(args.sub_fans),
        half_fan_deg=half_fan,
        collimation_cm=float(args.collimation_cm),
        sad_cm=float(args.sad_cm),
        kvp=kvp,
    )
    omega_total = sum(p.segment.solid_angle_sr for p in plans)
    print(
        f"[bowtie] {vendor} {kvp:.0f} kVp, K={len(plans)}, "
        f"half-fan={half_fan:.2f} deg, provenance={plans[0].provenance}",
        flush=True,
    )

    nz = phantom.shape_zyx[0]
    dz_cm = phantom.voxel_size_cm[2]
    z_mid_mm = 10.0 * (0.5 * nz * dz_cm)
    tcm_w = float(tcm.relative_weight(z_mid_mm))
    print(f"[tcm   ] mid-scan weight I(z)/mean(I) = {tcm_w:.3f}", flush=True)

    materials = stage_material_files(phantom.materials, MATERIALS_DIR, rundir)
    vox = write_voxel_file(rundir / "patient.vox.gz", phantom)
    print(f"[vox   ] {vox.name}  {vox.stat().st_size / 1e6:.1f} MB gz", flush=True)

    spec_names: list[str] = []
    for plan in plans:
        name = f"bowtie_fan{plan.segment.index:02d}.spc"
        write_mcgpu_spectrum(rundir / name, plan.spectrum)
        spec_names.append(name)

    n_proj = int(args.projections)
    n_runs = n_proj * len(plans)
    per_hist = float(args.histories) / n_runs
    if per_hist < MCGPU_TIME_THRESHOLD:
        raise SystemExit(
            f"histories per beamlet = {per_hist:.0f} is below MC-GPU's "
            f"{MCGPU_TIME_THRESHOLD:.0f} line (read as seconds, not a count). "
            f"--histories must be at least {MCGPU_TIME_THRESHOLD * n_runs:.3g}."
        )

    nx, ny, _nz = phantom.n_voxels
    (x0, x1), (y0, y1), (z0, z1) = roi
    sample_in = write_input_file(
        rundir / "patient_p000_fan00.in",
        histories_per_projection=per_hist,
        random_seed=int(args.seed),
        spectrum_file=spec_names[0],
        source_position_cm=pos0,
        source_direction=dir0,
        polar_aperture_deg=plans[0].segment.polar_aperture_deg,
        azimuthal_aperture_deg=plans[0].segment.azimuthal_aperture_deg,
        image_file="image_p000_fan00.dat",
        image_pixels=(4, 4),
        image_size_cm=(40.0, 4.0),
        sdd_cm=100.0,
        n_projections=1,
        angle_between_projections_deg=0.0,
        sad_cm=float(args.sad_cm),
        translation_per_projection_cm=0.0,
        dose_file="dose_p000_fan00.dat",
        voxel_file=vox.name,
        materials=materials,
        dose_roi=roi,
    )
    print(f"[input ] sample {sample_in.name}  ROI X[{x0},{x1}] Y[{y0},{y1}] Z[{z0},{z1}]", flush=True)

    plan_payload = {
        "series_instance_uid": uid,
        "vendor": vendor,
        "manufacturer": series.manufacturer,
        "model_name": series.model_name,
        "kvp": kvp,
        "n_slices": series.n_slices,
        "phantom": report,
        "n_materials": len(phantom.materials),
        "material_names": [m.name for m in phantom.materials],
        "focal_spot_gantry0_cm": list(pos0),
        "beam_direction_gantry0": list(dir0),
        "bbox_cm": list(bbox),
        "sad_cm": float(args.sad_cm),
        "collimation_cm": float(args.collimation_cm),
        "half_fan_deg": half_fan,
        "n_sub_fans": len(plans),
        "n_projections": n_proj,
        "omega_total_sr": omega_total,
        "bowtie_provenance": plans[0].provenance,
        "tcm": {
            "n_samples": int(tcm.current_ma.size),
            "modulated": bool(tcm.modulated),
            "min_ma": float(tcm.current_ma.min()),
            "max_ma": float(tcm.current_ma.max()),
            "mean_ma": float(tcm.current_ma.mean()),
            "midscan_relative_weight": tcm_w,
        },
        "organs_present": sorted(present),
        "dose_roi_1based": {"x": [x0, x1], "y": [y0, y1], "z": [z0, z1]},
        "histories_total": float(args.histories),
        "histories_per_beamlet": per_hist,
        "engine_invocations": n_runs,
        "notes": notes,
        "dicom_dir": str(directory),
        "mask_dir": str(run.mask_dir),
    }
    write_results(rundir / "plan.json", plan_payload)

    if not do_run:
        print("[plan  ] wrote plan.json; GPU not taken (--run to invoke MC-GPU)", flush=True)
        return 0

    # Accumulate per-history eV/g, weighted by solid angle and TCM, then scale
    # by histories_per_beamlet so organ_doses_from_roi sees a combined tally.
    acc = None
    sigma2 = None
    origin = None
    vox_size = None
    for p_index in range(n_proj):
        beta_deg = 360.0 * p_index / n_proj
        pos, aim0 = focal_spot_cm(bbox, args.sad_cm, gantry_deg=beta_deg, isocentre_cm=iso)
        d0x, d0y, d0z = aim0
        for plan in plans:
            psi = math.radians(plan.segment.centre_psi_deg)
            ux = d0x * math.cos(psi) - d0y * math.sin(psi)
            uy = d0x * math.sin(psi) + d0y * math.cos(psi)
            stem = f"p{p_index:03d}_fan{plan.segment.index:02d}"
            w = (plan.segment.solid_angle_sr / omega_total) * tcm_w / n_proj
            inp = write_input_file(
                rundir / f"patient_{stem}.in",
                histories_per_projection=per_hist,
                random_seed=int(args.seed) + 1000 * plan.segment.index + 7 * p_index,
                spectrum_file=spec_names[plan.segment.index],
                source_position_cm=pos,
                source_direction=(ux, uy, d0z),
                polar_aperture_deg=plan.segment.polar_aperture_deg,
                azimuthal_aperture_deg=plan.segment.azimuthal_aperture_deg,
                image_file=f"image_{stem}.dat",
                image_pixels=(4, 4),
                image_size_cm=(40.0, 4.0),
                sdd_cm=100.0,
                n_projections=1,
                angle_between_projections_deg=0.0,
                sad_cm=float(args.sad_cm),
                translation_per_projection_cm=0.0,
                dose_file=f"dose_{stem}.dat",
                voxel_file=vox.name,
                materials=materials,
                dose_roi=roi,
            )
            print(f"[run   ] {stem}  beta={beta_deg:6.1f} deg  w={w:.4f}", flush=True)
            mc = run_mcgpu(
                args.executable,
                inp,
                workdir=rundir,
                log_file=rundir / f"mcgpu_{stem}.log",
                total_histories=per_hist,
                timeout_s=args.timeout_hours * 3600.0,
            )
            mc.check()
            tally = read_dose_map(rundir / f"dose_{stem}.dat")
            if acc is None:
                acc = np.zeros_like(tally.dose_ev_per_g)
                sigma2 = np.zeros_like(tally.sigma_ev_per_g)
                origin = tally.roi_origin_zyx
                vox_size = tally.voxel_size_cm
            acc += w * tally.dose_ev_per_g
            sigma2 += (w * tally.sigma_ev_per_g) ** 2
            print(f"[run   ] {stem}  {mc.wall_seconds:.1f} s", flush=True)

    from ct_dosemc_core.mcgpu_io import DoseMap  # noqa: E402

    combined = DoseMap(
        dose_ev_per_g=acc,
        sigma_ev_per_g=np.sqrt(sigma2),
        roi_origin_zyx=origin,
        voxel_size_cm=vox_size,
    )
    doses = organ_doses_from_roi(
        combined, phantom.density, present, n_histories=float(args.histories), roi=roi
    )
    organ_out = {
        name: {
            "dose_mgy": d.dose_mgy,
            "sigma_mgy": d.sigma_mgy,
            "n_voxels": d.n_voxels,
            "mass_g": d.mass_g,
        }
        for name, d in doses.items()
    }
    for name, rec in sorted(organ_out.items()):
        print(
            f"[organ ] {name:<22} {rec['dose_mgy']:.4g} mGy  "
            f"n={rec['n_voxels']}  mass={rec['mass_g']:.1f} g",
            flush=True,
        )
    write_results(
        rundir / "organ_doses.json",
        {
            "series_instance_uid": uid,
            "vendor": vendor,
            "histories": float(args.histories),
            "n_projections": n_proj,
            "n_sub_fans": len(plans),
            "smoke": True,
            "note": (
                "First-patient path-through. Histories and projection count are a "
                "pipeline smoke, not the 40-series production configuration. "
                "Absolute mGy still needs CTDIvol/RDSR normalisation (Phase 1b)."
            ),
            "organs": organ_out,
            "plan": plan_payload,
        },
    )
    print(f"[done  ] {rundir / 'organ_doses.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

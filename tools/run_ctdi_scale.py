"""Bowtie-aware 32 cm CTDI at the patient source model — Fig. 4 scale.

Same 36 projections, K=4, 2e8 histories, Route A, 130 cm focal box, and
per-vendor bowtie as the 32-series production. The Phase-1 no-bowtie CTDI
anchor is not this factor.

    python tools/run_ctdi_scale.py --campaign
    python tools/run_ctdi_scale.py --vendor Siemens --kvp 140 --run

D_scaled = D_raw * CTDIvol_series / CTDIw_MC(vendor, kVp). Both MC legs are
axial; the recorded CTDIvol already carries the series pitch.
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

from ct_dosemc_core.ctdi import (  # noqa: E402
    CHAMBER_POSITIONS,
    CtdiPhantomSpec,
    average_peripheral,
    build_ctdi_phantom,
    chamber_weights,
    ctdi_100,
    ctdi_w,
)
from ct_dosemc_core.dosimetry import region_dose  # noqa: E402
from ct_dosemc_core.driver import bowtie_subfan_plan  # noqa: E402
from ct_dosemc_core.engine_limits import assert_engine_can_run  # noqa: E402
from ct_dosemc_core.mcgpu_io import (  # noqa: E402
    DoseMap,
    read_dose_map,
    run_mcgpu,
    split_route_a_logs,
    stage_material_files,
    write_input_file,
    write_manifest,
    write_voxel_file,
)
from ct_dosemc_core.patient import (  # noqa: E402
    DEFAULT_SAD_CM,
    FOCAL_BOX_XY_CM,
    embed_in_focal_box,
    material_energy_tag,
    organ_bounding_box,
)
from ct_dosemc_core.phantom import Material  # noqa: E402
from ct_dosemc_core.provenance import write_results  # noqa: E402
from ct_dosemc_core.source_model import canonical_vendor, focal_spot_cm  # noqa: E402
from ct_dosemc_core.spectra import write_mcgpu_spectrum  # noqa: E402

MATERIALS_DIR = REPO / "materials"
PLAN = REPO / "results" / "phase2_cohort" / "ctdi_scale_plan.json"
OUT_ROOT = REPO / "results" / "phase2_ctdi"
SCALE_JSON = REPO / "results" / "phase2_cohort" / "ctdi_scale.json"
EXE = REPO / "vendor" / "build" / "MC-GPU_v1.3_GPU.exe"
MCGPU_TIME_THRESHOLD = 100_000.0
PROD_PROJECTIONS = 36
PROD_SUB_FANS = 4
PROD_HISTORIES = 2.0e8
COLLIMATION_CM = 2.0


def _vendor(label: str) -> str:
    if label in ("GE", "Siemens", "Philips", "Canon/Toshiba"):
        return label
    return canonical_vendor(label)


def _tag(vendor: str, kvp: float) -> str:
    safe = vendor.replace("/", "-").replace(" ", "")
    return f"scale_{safe}_{float(kvp):.0f}kVp"


def _materials(kvp: float) -> tuple[Material, Material]:
    tag = material_energy_tag(kvp)
    air = Material(1, "air", f"air_{tag}.mcgpu.gz", 1.20479e-3)
    pmma = Material(2, "PMMA", f"PMMA_{tag}.mcgpu.gz", 1.19)
    return air, pmma


def rundir_for(vendor: str, kvp: float) -> Path:
    return OUT_ROOT / _tag(vendor, kvp)


def is_complete(vendor: str, kvp: float) -> bool:
    path = rundir_for(vendor, kvp) / "ctdi_result.json"
    if not path.is_file():
        return False
    rec = json.loads(path.read_text(encoding="utf-8-sig"))
    return (
        abs(float(rec.get("histories") or 0.0) - PROD_HISTORIES) < 1.0
        and int(rec.get("n_projections") or 0) == PROD_PROJECTIONS
        and int(rec.get("n_sub_fans") or 0) == PROD_SUB_FANS
        and rec.get("ctdiw_pmma_mgy") is not None
    )


def plan_runs() -> list[dict[str, Any]]:
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    return list(payload["runs"])


def write_scale_json() -> Path:
    rows = []
    by_key: dict[str, float] = {}
    for run in plan_runs():
        vendor, kvp = _vendor(str(run["vendor"])), float(run["kvp"])
        rec: dict[str, Any] = {"vendor": vendor, "kvp": kvp, "complete": is_complete(vendor, kvp)}
        if rec["complete"]:
            data = json.loads((rundir_for(vendor, kvp) / "ctdi_result.json").read_text(encoding="utf-8-sig"))
            rec["ctdiw_pmma_mgy"] = data["ctdiw_pmma_mgy"]
            rec["tag"] = _tag(vendor, kvp)
            by_key[f"{vendor}|{kvp:.0f}"] = float(data["ctdiw_pmma_mgy"])
        rows.append(rec)
    payload = {
        "what": "Bowtie-aware CTDIw_MC at the patient source model, for Fig. 4",
        "formula": "D_scaled = D_raw * CTDIvol_series / CTDIw_MC(vendor, kVp)",
        "not": "Not the Phase-1 no-bowtie CTDI anchor. Both MC legs are axial; recorded CTDIvol carries pitch.",
        "source_model": {
            "projections": PROD_PROJECTIONS,
            "sub_fans": PROD_SUB_FANS,
            "histories": PROD_HISTORIES,
            "route": "A",
            "phantom_cm": 32,
            "sad_cm": DEFAULT_SAD_CM,
            "collimation_cm": COLLIMATION_CM,
        },
        "n_complete": sum(1 for r in rows if r["complete"]),
        "n_planned": len(rows),
        "ctdiw_pmma_mgy_by_vendor_kvp": by_key,
        "runs": rows,
    }
    SCALE_JSON.parent.mkdir(parents=True, exist_ok=True)
    SCALE_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return SCALE_JSON


def run_one(vendor: str, kvp: float, *, timeout_hours: float) -> int:
    vendor = _vendor(vendor)
    rundir = rundir_for(vendor, kvp)
    rundir.mkdir(parents=True, exist_ok=True)
    print(f"[ctdi] {vendor} {kvp:.0f} kVp  {rundir}", flush=True)

    air, pmma = _materials(kvp)
    assert_engine_can_run(
        [MATERIALS_DIR / air.file, MATERIALS_DIR / pmma.file],
        spectrum_emax_kev=kvp,
    )

    spec = CtdiPhantomSpec(diameter_cm=32.0, voxel_size_cm=0.25)
    phantom = build_ctdi_phantom(spec, air=air, pmma=pmma)
    phantom, _pad = embed_in_focal_box(phantom, xy_cm=FOCAL_BOX_XY_CM)
    pmma_mask = phantom.material == pmma.index
    roi = organ_bounding_box(pmma_mask, pad_voxels=2)
    bbox = phantom.bbox_cm
    iso = phantom.centre_cm()
    pos0, dir0 = focal_spot_cm(bbox, DEFAULT_SAD_CM, gantry_deg=0.0, isocentre_cm=iso)
    print(
        f"[phant] {phantom.n_voxels} @ {phantom.voxel_size_cm[0]:g} cm  "
        f"focus0={pos0}",
        flush=True,
    )

    half_fan = math.degrees(math.asin(min(0.999, 25.0 / DEFAULT_SAD_CM))) + 2.0
    plans = bowtie_subfan_plan(
        vendor,
        n_sub_fans=PROD_SUB_FANS,
        half_fan_deg=half_fan,
        collimation_cm=COLLIMATION_CM,
        sad_cm=DEFAULT_SAD_CM,
        kvp=kvp,
    )
    omega_total = sum(p.segment.solid_angle_sr for p in plans)
    print(
        f"[bowtie] {vendor} {kvp:.0f} kVp K={len(plans)} provenance={plans[0].provenance}",
        flush=True,
    )

    materials = stage_material_files((air, pmma), MATERIALS_DIR, rundir)
    vox = write_voxel_file(rundir / "ctdi.vox.gz", phantom)
    spec_names: list[str] = []
    for plan in plans:
        name = f"bowtie_fan{plan.segment.index:02d}.spc"
        write_mcgpu_spectrum(rundir / name, plan.spectrum)
        spec_names.append(name)

    n_runs = PROD_PROJECTIONS * len(plans)
    per_hist = PROD_HISTORIES / n_runs
    if per_hist < MCGPU_TIME_THRESHOLD:
        raise SystemExit(f"histories per beam {per_hist:.0f} below {MCGPU_TIME_THRESHOLD:.0f}")

    jobs: list[dict[str, Any]] = []
    for p_index in range(PROD_PROJECTIONS):
        beta_deg = 360.0 * p_index / PROD_PROJECTIONS
        pos, aim0 = focal_spot_cm(bbox, DEFAULT_SAD_CM, gantry_deg=beta_deg, isocentre_cm=iso)
        d0x, d0y, d0z = aim0
        for plan in plans:
            psi = math.radians(plan.segment.centre_psi_deg)
            ux = d0x * math.cos(psi) - d0y * math.sin(psi)
            uy = d0x * math.sin(psi) + d0y * math.cos(psi)
            stem = f"p{p_index:03d}_fan{plan.segment.index:02d}"
            w = (plan.segment.solid_angle_sr / omega_total) / PROD_PROJECTIONS
            write_input_file(
                rundir / f"ctdi_{stem}.in",
                histories_per_projection=per_hist,
                random_seed=1234567890 + 1000 * plan.segment.index + 7 * p_index,
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
                sad_cm=DEFAULT_SAD_CM,
                translation_per_projection_cm=0.0,
                dose_file=f"dose_{stem}.dat",
                voxel_file=vox.name,
                materials=materials,
                dose_roi=roi,
            )
            jobs.append({"stem": stem, "w": w, "inp": rundir / f"ctdi_{stem}.in"})

    names = [j["inp"].name for j in jobs]
    manifest = write_manifest(rundir / "manifest.txt", names)
    print(f"[batch] Route A {len(names)} beams @{manifest.name}", flush=True)
    mc = run_mcgpu(
        EXE,
        jobs[0]["inp"],
        workdir=rundir,
        log_file=rundir / "mcgpu_batch.log",
        total_histories=PROD_HISTORIES,
        timeout_s=timeout_hours * 3600.0,
        argv1=f"@{manifest.name}",
    )
    try:
        mc.check()
    except RuntimeError as exc:
        print(f"[batch] MC-GPU failed: {exc}", flush=True)
        raise
    split_route_a_logs(mc.log_file, rundir)
    print(f"[batch] wall={mc.wall_seconds:.1f} s", flush=True)

    acc = None
    sigma2 = None
    origin = None
    vox_size = None
    for job in jobs:
        tally = read_dose_map(rundir / f"dose_{job['stem']}.dat")
        if acc is None:
            acc = np.zeros_like(tally.dose_ev_per_g)
            sigma2 = np.zeros_like(tally.sigma_ev_per_g)
            origin = tally.roi_origin_zyx
            vox_size = tally.voxel_size_cm
        acc += job["w"] * tally.dose_ev_per_g
        sigma2 += (job["w"] * tally.sigma_ev_per_g) ** 2
    combined = DoseMap(
        dose_ev_per_g=acc,
        sigma_ev_per_g=np.sqrt(sigma2),
        roi_origin_zyx=origin,
        voxel_size_cm=vox_size,
    )
    weights = chamber_weights(
        phantom, spec, roi_origin_zyx=combined.roi_origin_zyx, roi_shape_zyx=combined.shape_zyx
    )
    z0, y0, x0 = combined.roi_origin_zyx
    dz, dy, dx = combined.shape_zyx
    density_roi = phantom.density[z0 : z0 + dz, y0 : y0 + dy, x0 : x0 + dx]
    ctdi100 = {}
    for name in CHAMBER_POSITIONS:
        r = region_dose(
            name, combined, weights[name] > 0.0, density_roi, PROD_HISTORIES, weights=weights[name]
        )
        ctdi100[name] = ctdi_100(r, collimation_cm=COLLIMATION_CM, chamber_length_cm=spec.chamber_length_cm)
        print(
            f"[score] {name:12s} {ctdi100[name].value:.6g} mGy",
            flush=True,
        )
    peri = average_peripheral(ctdi100)
    cw = ctdi_w(ctdi100["centre"], peri)
    print(f"[score] CTDIw_PMMA = {cw.value:.6g} mGy", flush=True)
    write_results(
        rundir / "ctdi_result.json",
        {
            "vendor": vendor,
            "kvp": kvp,
            "histories": PROD_HISTORIES,
            "n_projections": PROD_PROJECTIONS,
            "n_sub_fans": len(plans),
            "source_route": "A",
            "bowtie_provenance": plans[0].provenance,
            "material_energy_tag": material_energy_tag(kvp),
            "ctdi100_pmma_mgy": {k: v.value for k, v in ctdi100.items()},
            "ctdiw_pmma_mgy": cw.value,
            "ctdiw_sigma_mgy": cw.uncertainty,
            "wall_seconds": mc.wall_seconds,
        },
    )
    print(f"[done] {rundir / 'ctdi_result.json'}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", action="store_true")
    ap.add_argument("--vendor", default=None)
    ap.add_argument("--kvp", type=float, default=None)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--timeout-hours", type=float, default=6.0)
    args = ap.parse_args(argv)

    if args.campaign:
        failed: list[str] = []
        for i, run in enumerate(plan_runs(), 1):
            vendor, kvp = _vendor(str(run["vendor"])), float(run["kvp"])
            print(f"[campaign] {i}/{len(plan_runs())} {vendor} {kvp:.0f} kVp", flush=True)
            if is_complete(vendor, kvp):
                print("[campaign] skip complete", flush=True)
                continue
            try:
                run_one(vendor, kvp, timeout_hours=args.timeout_hours)
            except BaseException as exc:
                if isinstance(exc, KeyboardInterrupt):
                    raise
                print(f"[campaign] FAILED {vendor} {kvp:.0f}: {exc}", flush=True)
                failed.append(f"{vendor}|{kvp:.0f}")
                continue
        write_scale_json()
        if failed:
            print(f"[campaign] finished with failures: {failed}", flush=True)
            print("CTDI_SCALE_FAILED", flush=True)
            return 1
        print("[campaign] session finished", flush=True)
        print("CTDI_SCALE_DONE", flush=True)
        return 0

    if not args.run or not args.vendor or args.kvp is None:
        raise SystemExit("use --campaign, or --run --vendor X --kvp N")
    code = run_one(_vendor(args.vendor), float(args.kvp), timeout_hours=args.timeout_hours)
    write_scale_json()
    return code


if __name__ == "__main__":
    raise SystemExit(main())

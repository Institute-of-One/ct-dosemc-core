"""Phase 1a -- code verification against AAPM TG-195 Case 4.

This is the Phase-1 gate.  A measured scanner CTDIvol cannot verify this code
(no bowtie, flat fan, homogeneous cylinder), but TG-195 Case 4 specifies exactly
that configuration and publishes results from four independent Monte Carlo
packages.  Passing it means the transport, the geometry and the source model are
right; it says nothing yet about whether the scanner model is.

Gates, in the order they must be run::

    python tools/run_tg195.py --gate G1     # 56.4 keV, one projection  <- FIRST
    python tools/run_tg195.py --gate G0     # spectrum: HVL and mean energy
    python tools/run_tg195.py --gate G2     # 120 kVp, 36 projections

G1 is first because it removes the spectrum and the rotation from the problem.
If the monoenergetic single-projection case disagrees, nothing downstream of it
means anything.

Requires ``python tools/fetch_tg195.py`` (copyrighted reference data, fetched
locally, never committed).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ct_dosemc_core.mcgpu_io import (  # noqa: E402
    McgpuRun,
    read_dose_map,
    run_mcgpu,
    split_route_a_logs,
    stage_material_files,
    write_input_file,
    write_manifest,
    write_voxel_file,
)
from ct_dosemc_core.phantom import Material  # noqa: E402
from ct_dosemc_core.provenance import Provenance, Value, file_digest, write_results  # noqa: E402
from ct_dosemc_core.tg195 import (  # noqa: E402
    Case4Spec,
    build_case4_phantom,
    first_test_voi_weights,
    perimeter_replica_weights,
    read_case4_reference,
    read_tg195_spectrum,
    second_test_voi_weights,
    specified_solid_angle_sr,
    sub_fans,
    write_monoenergetic_spectrum,
    write_tg195_spectrum_file,
)

DEFAULT_EXE = REPO / "vendor" / "build" / "MC-GPU_v1.3_CPU.exe"
MATERIALS_DIR = REPO / "materials"
TG195_DIR = REPO / "data" / "tg195"
CASE4_RESULTS = TG195_DIR / "09-Case 4 Results.xlsx"
SPECTRA_XLSX = TG195_DIR / "03-X-Ray Spectra Definition.xlsx"

def _materials(e_min_kev: int) -> tuple[Material, Material]:
    """Material tables for a given lower energy bound.

    The bound is not cosmetic. MC-GPU discards a photon whose energy falls below
    the table's first entry, and -- unlike a photoelectric absorption, where the
    whole energy is deposited (MC-GPU_kernel_v1.3.cu:351) -- the residual energy
    of a Compton-degraded photon is **dropped, not deposited**
    (MC-GPU_kernel_v1.3.cu:311, :372). Lowering the bound shrinks that leak.
    It biases scatter-fed regions preferentially, because those are reached by
    the multiply-scattered photons that degrade furthest in energy.
    """
    return (
        Material(1, "air, dry (PENELOPE #104)", f"air_{e_min_kev}-120keV.mcgpu.gz", 1.20479e-3),
        Material(2, "PMMA (PENELOPE #224)", f"PMMA_{e_min_kev}-120keV.mcgpu.gz", 1.19),
    )


AIR, PMMA = _materials(5)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--gate", choices=["G0", "G1", "G2"], default="G1")
    # G1 and G2 differ in three ways at once -- beam, scored VOIs and rotation.
    # When they disagree, the only way to find out which one is responsible is to
    # change them one at a time, so each is separately addressable.
    p.add_argument(
        "--beam",
        choices=["mono", "120kvp"],
        default=None,
        help="override the gate's beam (default: mono for G1, 120kvp for G2)",
    )
    p.add_argument(
        "--test",
        choices=["first", "second"],
        default=None,
        help="override the gate's scored VOIs: 'first' = four axial sections, "
        "'second' = the two 10 mm cylinders (default: first for G1, second for G2)",
    )
    p.add_argument("--fan-thickness", type=float, default=1.0, help="t in cm; TG-195 gives 1 or 8")
    p.add_argument("--voxel-size", type=float, default=0.25, help="cm")
    p.add_argument(
        "--phantom-length",
        type=float,
        default=60.0,
        help="cm. TG-195 specifies 300 cm to approximate an infinite cylinder; the "
        "default is the converged length measured by --length-scan, and the full "
        "300 cm is reproducible by passing it explicitly.",
    )
    p.add_argument("--sub-fans", type=int, default=8, help="azimuthal fan subdivisions")
    p.add_argument(
        "--air-margin",
        type=float,
        default=50.0,
        help="cm of air modelled around the cylinder. MC-GPU carries photons from "
        "the focal spot to the voxel box WITHOUT interaction, so air outside the box "
        "does not exist. The default covers the whole 44 cm from the cylinder surface "
        "to the source, because anything less silently deletes part of the geometry "
        "TG-195 specifies (measured: +0.8% at 1 cm). NOT 44 cm, which places the "
        "source exactly on the box face -- a branch ambiguity in MC-GPU's "
        "move_to_bbox. The rule is: contain the whole air path AND keep the source "
        "strictly inside, so margin > SAD - phantom_radius, never equal to it.",
    )
    p.add_argument(
        "--air-margin-z",
        type=float,
        default=4.0,
        help="cm of air above and below the cylinder. Separate from --air-margin "
        "because the beam travels in the xy-plane, so only the transverse margin "
        "needs to be large.",
    )
    p.add_argument("--histories", type=float, default=2.0e7, help="total, across all sub-fans")
    p.add_argument("--projections", type=int, default=1)
    p.add_argument(
        "--replicas",
        type=int,
        default=0,
        help="G4: repeat the gate K times with independent seeds and report the "
        "sample standard deviation alongside the two in-run estimators. The "
        "replica SD makes no independence assumption at all, so it is the one to "
        "trust where they disagree.",
    )
    p.add_argument(
        "--material-emin-kev",
        type=int,
        default=5,
        help="lower energy bound of the material tables. MC-GPU drops the residual "
        "energy of a photon that degrades below it, so this sets the size of a "
        "systematic leak that falls on scatter-fed regions. Generate the tables "
        "first: tools/make_materials.py --e-min-ev 1000",
    )
    p.add_argument(
        "--perimeter-replicas",
        type=int,
        default=0,
        help="also score the perimeter VOI at N non-overlapping azimuths on its "
        "150 mm circle. The dose field of a cylindrically symmetric phantom under "
        "a full rotation depends only on (r, z), so every azimuth has the same "
        "expectation: averaging them costs no Monte Carlo and divides the SD by "
        "sqrt(N). Their scatter is also an independent check that nothing breaks "
        "the symmetry. 94 fit without overlapping.",
    )
    p.add_argument("--seed", type=int, default=1234567890)
    p.add_argument("--executable", type=Path, default=DEFAULT_EXE)
    p.add_argument("--tag", type=str, default=None)
    p.add_argument(
        "--batch",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Route A: one MC-GPU process over @manifest so the geometry is parsed "
        "once. Each sub-fan still writes its own dose tally (an equal-weight "
        "single-tally sum would bias the estimator by -0.53%%). --no-batch is "
        "Route B, one process per beam.",
    )
    p.add_argument("--timeout-hours", type=float, default=48.0)
    p.add_argument(
        "--rescore",
        action="store_true",
        help="re-score the tallies already in the run directory instead of running "
        "the engine. Only valid when every geometry argument is unchanged; the "
        "engine's own echoed apertures are re-read and asserted, which catches "
        "the case where they are not.",
    )
    p.add_argument(
        "--scan",
        type=str,
        default=None,
        metavar="PARAM=v1,v2,...",
        help="convergence sweep instead of a single gate run: repeats G1 varying one "
        "parameter and reports how much the answer moves. PARAM is one of "
        "phantom_length, air_margin, voxel_size, sub_fans. Example: "
        "--scan air_margin=1,10,20,30,40",
    )
    return p


SCANNABLE = {
    "phantom_length": "cm of PMMA cylinder (TG-195 specifies 300)",
    "air_margin": "cm of air modelled transversely, out of the 44 cm to the source",
    "voxel_size": "cm",
    "sub_fans": "azimuthal fan subdivisions",
}


# ---------------------------------------------------------------------------


def _score_beamlet(
    *,
    run,
    rundir: Path,
    stem: str,
    fan,
    phantom,
    spec: Case4Spec,
    voi_builder,
    weight: float,
    totals: dict,
    variances: dict,
    fan_records: list,
    p_index: int,
    beta: float,
    histories: float,
) -> None:
    """Score one (projection, sub-fan) tally into the running totals.

    The energy in a VOI is ``sum_i f_i * d_i * m_i`` with ``f_i`` the fraction of
    voxel ``i`` inside the analytic VOI.  Using a voxel-centre-inside test instead
    -- ``f_i in {0, 1}`` -- costs 4.5% on a 10 mm cylinder at 2.5 mm voxels, which
    is what the first G2 run was missing.
    """
    # The engine echoes the apertures it parsed. Under --rescore this also
    # catches a geometry argument that no longer matches the stored tally.
    run.assert_apertures(
        azimuthal_deg=fan.azimuthal_aperture_deg, polar_deg=fan.polar_aperture_deg
    )
    dose = read_dose_map(rundir / f"dose_{stem}.dat")
    weights = voi_builder(
        phantom, spec, roi_origin_zyx=dose.roi_origin_zyx, roi_shape_zyx=dose.shape_zyx
    )
    z0, y0, x0 = dose.roi_origin_zyx
    dz, dy, dx = dose.shape_zyx
    density_roi = phantom.density[z0 : z0 + dz, y0 : y0 + dy, x0 : x0 + dx]
    voxel_volume = dose.voxel_size_cm[0] * dose.voxel_size_cm[1] * dose.voxel_size_cm[2]

    per_voi = {}
    for name, f in weights.items():
        mass = f * density_roi * voxel_volume  # g, partial-volume weighted
        energy = float(np.sum(dose.dose_ev_per_g * mass))
        sigma = float(np.sqrt(np.sum((dose.sigma_ev_per_g * mass) ** 2)))
        totals[name] = totals.get(name, 0.0) + weight * energy
        variances[name] = variances.get(name, 0.0) + (weight * sigma) ** 2
        per_voi[name] = {
            "ev_per_photon_in_beamlet": energy,
            "sigma": sigma,
            "voi_volume_cm3": float(f.sum() * voxel_volume),
            "n_voxels_touched": int((f > 0).sum()),
        }

    fan_records.append(
        {
            "projection_index": p_index,
            "gantry_angle_deg": math.degrees(beta),
            "sub_fan_index": fan.index,
            "centre_psi_deg": fan.centre_psi_deg,
            "azimuthal_aperture_deg": fan.azimuthal_aperture_deg,
            "polar_aperture_deg": fan.polar_aperture_deg,
            "solid_angle_sr": fan.solid_angle_sr,
            "weight": weight,
            "histories": histories,
            "wall_seconds": run.wall_seconds,
            "voi": per_voi,
        }
    )


def run_sub_fan_set(
    *,
    spec: Case4Spec,
    args,
    rundir: Path,
    spectrum_file: str,
    voi_builder,
    phantom_length_cm: float,
    n_projections: int,
    label: str,
) -> tuple[dict[str, Value], dict]:
    """Simulate every sub-fan and combine into eV per emitted photon.

    Each sub-fan is an independent MC-GPU run, so combining their uncertainties
    in quadrature is *correct* here -- unlike the per-voxel combination inside a
    single run, which shares histories.
    """
    phantom = build_case4_phantom(
        spec,
        air=AIR,
        pmma=PMMA,
        voxel_size_cm=args.voxel_size,
        air_margin_cm=args.air_margin,
        air_margin_z_cm=args.air_margin_z,
        length_cm=phantom_length_cm,
    )
    nx, ny, nz = phantom.n_voxels
    cx, cy, cz = phantom.centre_cm()
    v = args.voxel_size

    # Tally only what is scored. MC-GPU writes the mean and the uncertainty map
    # for the whole ROI on every invocation, so with 144 invocations per replica a
    # full-phantom ROI costs tens of GB of write-then-read for tallies that are
    # discarded. The VOIs occupy a thin slab, and transversely no more than the
    # perimeter annulus.
    half_slab_cm = 6.0
    z_lo = max(1, int((cz - half_slab_cm) / v) + 1)
    z_hi = min(nz, int((cz + half_slab_cm) / v) + 1)

    if voi_builder is second_test_voi_weights or args.perimeter_replicas:
        # Must still contain the FULL perimeter annulus, not just one azimuth,
        # or the azimuthal replication of section 5.1.3b has nothing to score.
        reach = (
            spec.second_test_perimeter_radius_cm
            + 0.5 * spec.second_test_voi_diameter_cm
            + 2.0 * v
        )
        xy_lo = max(1, int((cx - reach) / v) + 1)
        xy_hi = min(nx, int((cx + reach) / v) + 1)
    else:
        # The first test scores whole discs of the phantom; nothing to crop.
        xy_lo, xy_hi = 1, nx
    roi_voxels = (xy_hi - xy_lo + 1) * (xy_hi - xy_lo + 1) * (z_hi - z_lo + 1)
    print(
        f"[roi  ] {xy_hi - xy_lo + 1} x {xy_hi - xy_lo + 1} x {z_hi - z_lo + 1} "
        f"= {roi_voxels / 1e6:.2f}M voxels tallied of {nx * ny * nz / 1e6:.1f}M "
        f"({nx * ny * nz / max(roi_voxels, 1):.0f}x less dose I/O per invocation)"
    )

    fans = sub_fans(spec, args.sub_fans, thickness_cm=args.fan_thickness)
    omega_total = sum(f.solid_angle_sr for f in fans)
    omega_spec = specified_solid_angle_sr(spec, thickness_cm=args.fan_thickness)

    # MC-GPU's own CT trajectory re-aims the source at the rotation centre for
    # every projection after the first (MC-GPU_v1.3.cu:3292), which silently
    # undoes an off-axis sub-fan. So a rotation with K > 1 has to be driven one
    # projection at a time: P*K invocations rather than K.
    drive_projections_here = n_projections > 1 and len(fans) > 1
    engine_projections = 1 if drive_projections_here else n_projections
    gantry_angles = (
        [2.0 * math.pi * p / n_projections for p in range(n_projections)]
        if drive_projections_here
        else [0.0]
    )
    n_runs = len(fans) * len(gantry_angles)
    per_fan_histories = float(args.histories) / (n_runs * engine_projections)
    # MC-GPU reads the "TOTAL NUMBER OF HISTORIES (PER PROJECTION)" field as a
    # simulation TIME in seconds when it is below 95000 (MC-GPU_v1.3.cu:654),
    # not as a count -- a silent switch of the whole experiment from "N
    # histories" to "run for N seconds". A smoke test at 2e6/36 = 55556 tried to
    # run ~15 h per projection this way. Refuse it loudly rather than run the
    # wrong thing; the documented contract is "> 1e5 histories" (line 141).
    mcgpu_time_threshold = 100000.0
    if per_fan_histories < mcgpu_time_threshold:
        raise SystemExit(
            f"histories per projection = {per_fan_histories:.0f} is below MC-GPU's "
            f"{mcgpu_time_threshold:.0f} line: it would be read as a simulation TIME "
            f"in seconds, not a count (MC-GPU_v1.3.cu:654). With {n_runs} sub-fan(s) "
            f"x {engine_projections} engine projection(s), --histories must be at "
            f"least {mcgpu_time_threshold * n_runs * engine_projections:.3g} total."
        )
    if drive_projections_here:
        print(
            f"[traj ] {n_projections} projections x {len(fans)} sub-fans = {n_runs} "
            "beams (MC-GPU re-aims at the rotation centre, so its "
            "built-in trajectory cannot carry an off-axis sub-fan)"
        )

    materials = stage_material_files((AIR, PMMA), MATERIALS_DIR, rundir)
    vox = rundir / f"case4_{label}.vox.gz"
    if not (args.rescore and vox.is_file()):
        vox = write_voxel_file(vox, phantom)
    print(
        f"[phant] r={spec.phantom_radius_cm:g} cm, L={phantom_length_cm:g} cm, "
        f"{nx}x{ny}x{nz} voxels of {v:g} cm "
        f"({phantom.mass_g(phantom.material == PMMA.index) / 1000:.1f} kg PMMA), "
        f"{vox.stat().st_size / 1e6:.1f} MB gz"
    )
    print(
        f"[fan  ] K={len(fans)}, Omega={omega_total:.6e} sr "
        f"({100 * (omega_total / omega_spec - 1):+.4f} % vs the specified rectangle)"
    )

    totals: dict[str, float] = {}
    variances: dict[str, float] = {}
    fan_records = []
    jobs: list[dict] = []

    for p_index, beta in enumerate(gantry_angles):
        for fan in fans:
            # ONE focal spot per projection.  The sub-fans are angular slices of a
            # single source's emission, so only the aim rotates -- moving the focal
            # spot with them would irradiate the phantom from K different
            # positions, which is a different experiment entirely.
            sx = cx + spec.sad_cm * math.sin(beta)
            sy = cy - spec.sad_cm * math.cos(beta)
            # Aim at the axis, then swing by the sub-fan's azimuth.
            d0x, d0y = -math.sin(beta), math.cos(beta)
            psi = math.radians(fan.centre_psi_deg)
            ux = d0x * math.cos(psi) - d0y * math.sin(psi)
            uy = d0x * math.sin(psi) + d0y * math.cos(psi)

            stem = f"{label}_p{p_index:03d}_fan{fan.index:02d}"
            jobs.append(
                {
                    "p_index": p_index,
                    "beta": beta,
                    "fan": fan,
                    "stem": stem,
                    "sx": sx,
                    "sy": sy,
                    "ux": ux,
                    "uy": uy,
                    "weight": (fan.solid_angle_sr / omega_total) / len(gantry_angles),
                    "histories": per_fan_histories * engine_projections,
                    "seed": args.seed + 1000 * fan.index + 7 * p_index,
                }
            )

    use_batch = bool(getattr(args, "batch", True)) and (not args.rescore) and len(jobs) > 1

    if args.rescore:
        for job in jobs:
            existing = rundir / f"dose_{job['stem']}.dat"
            if not (existing.parent / (existing.name + ".raw")).is_file():
                raise SystemExit(f"--rescore: no tally at {existing}.raw")
            run = McgpuRun(
                executable=Path(args.executable).resolve(),
                input_file=rundir / f"case4_{job['stem']}.in",
                log_file=rundir / f"mcgpu_{job['stem']}.log",
                returncode=0,
                wall_seconds=float("nan"),
                total_histories=job["histories"],
            )
            _score_beamlet(
                run=run,
                rundir=rundir,
                stem=job["stem"],
                fan=job["fan"],
                phantom=phantom,
                spec=spec,
                voi_builder=voi_builder,
                weight=job["weight"],
                totals=totals,
                variances=variances,
                fan_records=fan_records,
                p_index=job["p_index"],
                beta=job["beta"],
                histories=job["histories"],
            )
    else:
        input_names: list[str] = []
        for job in jobs:
            inp = write_input_file(
                rundir / f"case4_{job['stem']}.in",
                histories_per_projection=per_fan_histories,
                random_seed=job["seed"],
                spectrum_file=spectrum_file,
                source_position_cm=(job["sx"], job["sy"], cz),
                source_direction=(job["ux"], job["uy"], 0.0),
                polar_aperture_deg=job["fan"].polar_aperture_deg,
                azimuthal_aperture_deg=job["fan"].azimuthal_aperture_deg,
                image_file=f"image_{job['stem']}.dat",
                image_pixels=(4, 4),
                image_size_cm=(40.0, 4.0),
                sdd_cm=100.0,
                n_projections=engine_projections,
                angle_between_projections_deg=(
                    360.0 / engine_projections if engine_projections > 1 else 0.0
                ),
                sad_cm=spec.sad_cm,
                translation_per_projection_cm=0.0,
                dose_file=f"dose_{job['stem']}.dat",
                voxel_file=vox.name,
                materials=materials,
                dose_roi=((xy_lo, xy_hi), (xy_lo, xy_hi), (z_lo, z_hi)),
            )
            input_names.append(inp.name)
            job["input_file"] = inp

        if use_batch:
            manifest = write_manifest(rundir / "manifest.txt", input_names)
            print(
                f"[batch] Route A: {len(input_names)} beams in one process "
                f"(@{manifest.name}); geometry parsed once, per-beam tallies"
            )
            batch_run = run_mcgpu(
                args.executable,
                manifest,
                workdir=rundir,
                log_file=rundir / "mcgpu_batch.log",
                total_histories=sum(j["histories"] for j in jobs),
                timeout_s=args.timeout_hours * 3600.0,
                argv1=f"@{manifest.name}",
            )
            batch_run.check()
            per_log = split_route_a_logs(batch_run.log_file, rundir)
            missing = [name for name in input_names if name not in per_log]
            if missing:
                raise RuntimeError(
                    f"Route A log split missed {len(missing)} beam(s); first={missing[0]}"
                )
            parsed_once = batch_run.log_file.read_text(
                encoding="latin-1", errors="replace"
            )
            n_parsed = parsed_once.count("Reading voxel file")
            n_cache = parsed_once.count("ASCII parse skipped")
            print(
                f"[batch] wall={batch_run.wall_seconds:.1f} s  "
                f"voxel-file reads={n_parsed}  cache-hits={n_cache}"
            )
            per_beam_wall = batch_run.wall_seconds / len(jobs)
            for job in jobs:
                run = McgpuRun(
                    executable=batch_run.executable,
                    input_file=job["input_file"],
                    log_file=per_log[job["input_file"].name],
                    returncode=0,
                    wall_seconds=per_beam_wall,
                    total_histories=job["histories"],
                )
                _score_beamlet(
                    run=run,
                    rundir=rundir,
                    stem=job["stem"],
                    fan=job["fan"],
                    phantom=phantom,
                    spec=spec,
                    voi_builder=voi_builder,
                    weight=job["weight"],
                    totals=totals,
                    variances=variances,
                    fan_records=fan_records,
                    p_index=job["p_index"],
                    beta=job["beta"],
                    histories=job["histories"],
                )
        else:
            for job in jobs:
                run = run_mcgpu(
                    args.executable,
                    job["input_file"],
                    workdir=rundir,
                    log_file=rundir / f"mcgpu_{job['stem']}.log",
                    total_histories=job["histories"],
                    timeout_s=args.timeout_hours * 3600.0,
                )
                run.check()
                _score_beamlet(
                    run=run,
                    rundir=rundir,
                    stem=job["stem"],
                    fan=job["fan"],
                    phantom=phantom,
                    spec=spec,
                    voi_builder=voi_builder,
                    weight=job["weight"],
                    totals=totals,
                    variances=variances,
                    fan_records=fan_records,
                    p_index=job["p_index"],
                    beta=job["beta"],
                    histories=job["histories"],
                )
                if len(gantry_angles) == 1:
                    print(
                        f"[fan {job['fan'].index:02d}] psi={job['fan'].centre_psi_deg:+7.3f} deg  "
                        f"w={fan_records[-1]['weight']:.4f}  "
                        f"{fan_records[-1]['wall_seconds']:6.1f} s"
                    )
                elif job["fan"].index == fans[-1].index:
                    print(
                        f"[proj {job['p_index'] + 1:3d}/{len(gantry_angles)}] "
                        f"beta={math.degrees(job['beta']):6.1f} deg  "
                        f"{sum(r['wall_seconds'] for r in fan_records[-len(fans):]):6.1f} s"
                    )

    values = {
        name: Value(
            value=totals[name],
            unit="eV per emitted photon",
            uncertainty=math.sqrt(variances[name]),
            provenance=Provenance(
                formula="E = sum_k (Omega_k/Omega_total) * sum_voxels(d_i * m_i); "
                "sigma = sqrt(sum_k (Omega_k/Omega_total)^2 * sigma_k^2)",
                inputs={
                    "voi": name,
                    "n_sub_fans": len(fans),
                    "histories_total": float(args.histories),
                    "omega_total_sr": omega_total,
                },
                assumptions=(
                    "MC-GPU tallies collision kerma; electrons are not transported",
                    "sub-fan runs are statistically independent, so their "
                    "uncertainties combine in quadrature -- unlike per-voxel "
                    "uncertainties within one run",
                    "the source emits uniformly in solid angle over the specified "
                    "rectangular field",
                ),
                source="AAPM TG-195 Case 4, scoring in eV per emitted photon",
            ),
        )
        for name in totals
    }
    meta = {
        "phantom_length_cm": phantom_length_cm,
        "voxel_size_cm": v,
        "n_voxels_xyz": [nx, ny, nz],
        "dose_roi_z_index": [z_lo, z_hi],
        "dose_roi_xy_index": [xy_lo, xy_hi],
        "n_sub_fans": len(fans),
        "omega_total_sr": omega_total,
        "omega_specified_sr": omega_spec,
        "omega_excess_fraction": omega_total / omega_spec - 1.0,
        "histories_total": float(args.histories),
        "n_projections": n_projections,
        "projections_driven_externally": drive_projections_here,
        "engine_invocations": 1 if use_batch else n_runs,
        "route_a_batch": use_batch,
        "air_margin_cm": args.air_margin,
        "air_margin_z_cm": args.air_margin_z,
        "beamlets": fan_records,
    }
    return values, meta


# TG-195 asks users to report "the relative percentage difference found between
# the results obtained and the corresponding mean of the results in this report"
# (report p.56), and states that the reference values themselves carry up to 1%
# statistical uncertainty at each VOI (section 3.4). So 1% against the four-code
# mean is the criterion the report itself sets up. Whether we also land inside
# the much tighter inter-code range is reported separately: for some VOIs the
# four codes agree to 0.1%, which is a stricter bar than the report asks for and
# than its own stated statistics support.
TG195_TOLERANCE = 0.01

# The package whose cross-section library this engine shares. Comparing against
# it makes the test one of transport implementation rather than of cross-section
# datasets; comparing against the four-code mean asks one library to reproduce
# the average of four. See docs/MC_SOURCE_MODEL.md section 5.1.4. The choice is
# made on that physical ground and is stated before the numbers, and every other
# code is reported next to it so the choice stays arguable.
REFERENCE_CODE = "Penelope"
AGREEMENT_SIGMAS = 2.0
REPLICA_SD_REQUIREMENT = 0.0025

SOURCE_ROUTE_BIT_IDENTITY = (
    "One further modification hoists the geometry parse out of the sub-fan loop. "
    "It changes no physics: on a full 10-replica reference set computed with the "
    "unmodified engine, all 144 dose arrays are SHA-256 identical and the scored "
    "VOI values are bit-identical "
    "(results/phase1a/replica_120kvp_second_K4_L40_00 vs "
    "results/phase1a/replica_120kvp_second_K4_L40_00_routeA)."
)


def source_route_fields(
    *,
    n_sub_fans: int,
    n_projections: int,
    engine_invocations: int,
) -> dict:
    """Which engine path produced a Phase-1a number. Does not change the values.

    Route B = one process per beam (P*K invocations). Route A = one process over
    ``@manifest``. K=1 keeps the projection loop inside MC-GPU (neither A nor B).
    """
    if int(n_sub_fans) > 1 and int(n_projections) > 1:
        route = "A" if int(engine_invocations) == 1 else "B"
        detail = (
            "Route A: one MC-GPU process over @manifest; geometry parsed once; "
            "each sub-fan still writes its own dose tally"
            if route == "A"
            else "Route B: one MC-GPU process per (projection, sub-fan) beam"
        )
    else:
        route = "native_ct_trajectory"
        detail = (
            "single centred fan; MC-GPU's built-in projection loop; not the "
            "sub-fan @manifest path"
        )
    return {
        "source_route": route,
        "source_route_detail": detail,
        "physics_unchanged_across_A_and_B": route in ("A", "B"),
        "bit_identity_note": SOURCE_ROUTE_BIT_IDENTITY if route in ("A", "B") else None,
    }


def compare(values: dict[str, Value], reference: dict[str, dict[str, float]]) -> dict:
    """Our numbers against the published ones."""
    rows = {}
    for name, v in values.items():
        if name not in reference:
            continue
        ref = reference[name]
        ratio = v.value / ref["mean"]
        per_code = ref.get("per_code") or {}
        rows[name] = {
            "ours_ev_per_photon": v.value,
            "ours_sigma": v.uncertainty,
            "ours_relative_sigma": (v.uncertainty / v.value) if v.uncertainty else None,
            # Against each package individually, not only their average. The
            # packages disagree with each other by up to 1% here, so a single
            # deviation-from-the-mean presents a spread as if it were a value.
            "per_code": {
                code: {"reference": val, "deviation_fraction": v.value / val - 1.0}
                for code, val in per_code.items()
            },
            "closest_code": (
                min(per_code, key=lambda c: abs(v.value / per_code[c] - 1.0))
                if per_code
                else None
            ),
            "reference_mean": ref["mean"],
            "reference_min": ref["min"],
            "reference_max": ref["max"],
            "inter_code_spread_fraction": ref["inter_code_spread_fraction"],
            "ratio_to_reference_mean": ratio,
            "deviation_fraction": ratio - 1.0,
            "passes_tg195_tolerance": bool(abs(ratio - 1.0) <= TG195_TOLERANCE),
            "within_inter_code_range": bool(ref["min"] <= v.value <= ref["max"]),
            "angular_case": ref.get("angular_case"),
            "n_codes_in_reference": ref.get("n_codes_discrete") or ref.get("n_codes_continuous"),
        }
    return rows


def _print_comparison(rows: dict) -> None:
    print()
    print(
        f"  {'VOI':<12} {'ours':>13} {'ref mean':>13} {'dev':>9} "
        f"{'MC sigma':>9} {'code spread':>12}  {'vs 1%':>6}  in-range"
    )
    _pending_per_code = []
    for name, r in rows.items():
        sig = r["ours_relative_sigma"]
        print(
            f"  {name:<12} {r['ours_ev_per_photon']:13.4f} {r['reference_mean']:13.4f} "
            f"{100 * r['deviation_fraction']:+8.3f}% "
            f"{(100 * sig if sig else float('nan')):8.3f}% "
            f"{100 * r['inter_code_spread_fraction']:11.3f}%  "
            f"{'PASS' if r['passes_tg195_tolerance'] else 'FAIL':>6}  "
            f"{'yes' if r['within_inter_code_range'] else 'no'}"
        )
        if r.get("per_code"):
            _pending_per_code.append((name, r))
    for name, r in _pending_per_code:
        parts = " ".join(
            f"{code} {100 * d['deviation_fraction']:+.2f}%"
            for code, d in sorted(r["per_code"].items())
        )
        print(f"    {name:<10} vs each code: {parts}   closest: {r['closest_code']}")
    print()


# ---------------------------------------------------------------------------


def gate_g0(args) -> int:
    """The distributed TG-195 spectrum vs SpekPy: HVL and mean energy.

    No Monte Carlo. The report states the 120 kVp W/Al beam has a mean energy of
    56.4 keV and an HVL of 5.010 mm Al; SpekPy asked for the same tube should say
    the same thing. This checks the spectrum generator against a published
    reference before it is ever used for a dose.
    """
    if not SPECTRA_XLSX.is_file():
        raise SystemExit(f"{SPECTRA_XLSX} missing; run tools/fetch_tg195.py")
    from ct_dosemc_core.spectra import Filter, generate_spectrum, half_value_layer_mm_al

    # TG-195 states, per beam: the tube settings, the mean energy and the HVL.
    beams = {
        "120 kVp": {"kvp": 120.0, "al_mm": 2.861, "anode_deg": 11.0, "mean": 56.4, "hvl": 5.010},
        "100 kVp": {"kvp": 100.0, "al_mm": 2.708, "anode_deg": 11.0, "mean": 50.6, "hvl": 3.950},
    }

    rows = {}
    for column, b in beams.items():
        energy, fluence, meta = read_tg195_spectrum(SPECTRA_XLSX, column=column)
        tg_mean = float(np.sum(fluence * energy) / fluence.sum())
        tg_hvl = half_value_layer_mm_al(energy, fluence)

        ours = generate_spectrum(
            b["kvp"], (Filter("Al", b["al_mm"]),), anode_angle_deg=b["anode_deg"]
        )
        our_hvl = half_value_layer_mm_al(ours.energy_kev, ours.differential_fluence)

        rows[column] = {
            "tg195_header": meta,
            # Does OUR estimator reproduce TG-195's stated values from TG-195's own
            # table? This validates the estimator, independently of SpekPy.
            "estimator_check": {
                "hvl_stated": b["hvl"],
                "hvl_from_tg195_table_our_estimator": tg_hvl,
                "deviation_fraction": tg_hvl / b["hvl"] - 1.0,
                "mean_energy_stated": b["mean"],
                "mean_energy_from_tg195_table": tg_mean,
                "mean_energy_deviation_fraction": tg_mean / b["mean"] - 1.0,
            },
            # Same estimator applied to both spectra: any difference left is a
            # difference between the two tube MODELS, not between definitions.
            "model_comparison_same_estimator": {
                "hvl_tg195": tg_hvl,
                "hvl_spekpy": our_hvl,
                "hvl_deviation_fraction": our_hvl / tg_hvl - 1.0,
                "mean_energy_tg195": tg_mean,
                "mean_energy_spekpy": ours.mean_energy_kev,
                "mean_energy_deviation_fraction": ours.mean_energy_kev / tg_mean - 1.0,
            },
            "spekpy_reported_hvl1": ours.hvl1_al_mm,
        }
        est = rows[column]["estimator_check"]
        cmp_ = rows[column]["model_comparison_same_estimator"]
        print(f"[G0] {column}: {meta.get('filtration', '')}, {meta.get('anode_angle', '')}")
        print(
            f"     estimator vs stated HVL : {est['hvl_from_tg195_table_our_estimator']:.4f} "
            f"vs {est['hvl_stated']:.4f} mm Al  ({100 * est['deviation_fraction']:+.2f} %)"
        )
        print(
            f"     SpekPy vs TG-195 HVL    : {cmp_['hvl_spekpy']:.4f} vs "
            f"{cmp_['hvl_tg195']:.4f} mm Al  ({100 * cmp_['hvl_deviation_fraction']:+.2f} %)"
        )
        print(
            f"     SpekPy vs TG-195 Emean  : {cmp_['mean_energy_spekpy']:.3f} vs "
            f"{cmp_['mean_energy_tg195']:.3f} keV  "
            f"({100 * cmp_['mean_energy_deviation_fraction']:+.2f} %)"
        )

    out = write_results(
        REPO / "results" / "phase1a_G0_spectrum.json",
        {
            "gate": "G0 -- spectrum beam quality against TG-195",
            "comparison": rows,
            "interpretation": (
                "Two separate questions, deliberately not conflated. (1) Applying our "
                "HVL estimator to TG-195's own distributed spectrum reproduces the HVL "
                "the report states, which validates the estimator. (2) Applying the "
                "same estimator to a SpekPy spectrum of the same nominal tube gives a "
                "harder/softer beam -- that residual is a difference between tube "
                "MODELS. TG-195 generated its spectra with the IPEM Report 78 software "
                "(report section 2.3, p.9); SpekPy implements a different model. The "
                "difference is not a defect in either, but it must not be absorbed "
                "silently: TG-195 gates use TG-195's distributed spectrum, and Phase-1b "
                "tunes filtration to a measured HVL, which makes the model choice "
                "second-order."
            ),
            "note": "No Monte Carlo is involved. This checks the spectrum layer alone, "
            "before it is used for any dose.",
        },
    )
    print(f"[G0] wrote {out}")
    return 0


def gate_g1_or_g2(args, *, gate: str) -> int:
    if not CASE4_RESULTS.is_file():
        raise SystemExit(f"{CASE4_RESULTS} missing; run tools/fetch_tg195.py")

    spec = Case4Spec(fan_thickness_at_isocentre_cm=args.fan_thickness)
    tag = args.tag or (
        f"{gate}_t{args.fan_thickness:g}cm_v{args.voxel_size:g}_L{args.phantom_length:g}"
        f"_K{args.sub_fans}_{args.histories:.0e}"
    )
    rundir = REPO / "results" / "phase1a" / tag
    rundir.mkdir(parents=True, exist_ok=True)
    print(f"[{gate}] {tag}\n[{gate}] run directory: {rundir}")

    beam_choice = args.beam or ("mono" if gate == "G1" else "120kvp")
    test_choice = args.test or ("first" if gate == "G1" else "second")

    if beam_choice == "mono":
        beam = "56.4 keV"
        spc = write_monoenergetic_spectrum(rundir / "mono.spc", spec.monoenergetic_kev)
        spectrum_file = "mono.spc"
    else:
        beam = "120 kVp"
        energy, fluence, header = read_tg195_spectrum(SPECTRA_XLSX, column="120 kVp")
        spc = write_tg195_spectrum_file(rundir / "tg195_120kvp.spc", energy, fluence)
        spectrum_file = "tg195_120kvp.spc"
        spc["tg195_header"] = header

    if test_choice == "first":
        # The first test is defined at a single projection: "This simulation is
        # only performed with the x-ray source at the 0 degree position" (§3.4).
        voi_builder = first_test_voi_weights
        n_projections = 1
    else:
        n_projections = int(args.projections)
        if args.perimeter_replicas:
            n_rep = int(args.perimeter_replicas)

            def voi_builder(phantom, spec, **kw):
                out = second_test_voi_weights(phantom, spec, **kw)
                out.update(
                    perimeter_replica_weights(phantom, spec, n_positions=n_rep, **kw)
                )
                return out
        else:
            voi_builder = second_test_voi_weights
    print(f"[{gate}] beam={beam}, {test_choice} test, {n_projections} projection(s)")

    values, meta = run_sub_fan_set(
        spec=spec,
        args=args,
        rundir=rundir,
        spectrum_file=spectrum_file,
        voi_builder=voi_builder,
        phantom_length_cm=args.phantom_length,
        n_projections=n_projections,
        label=gate.lower(),
    )

    # A 36-projection run is the DISCRETE sub-case, not the continuous one:
    # TG-195 publishes both and they differ by 1-2%. Comparing a discrete run
    # against the continuous column was worth -2.1% on the centre VOI.
    angular = "discrete" if (test_choice == "second" and n_projections == 36) else "continuous"
    replica_summary = None
    rep_names = sorted(n for n in values if n.startswith("perimeter_"))
    if rep_names:
        # Symmetry-averaged perimeter, plus the scatter across azimuths as a
        # second, independent uncertainty estimate. If it disagrees with the
        # replica SD from independent seeds, something breaks the rotational
        # symmetry that should not -- the same structure as the four-chamber CTDI
        # check that caught the PRNG defect.
        vals = np.array([values[n].value for n in rep_names])
        mean = float(vals.mean())
        sd_of_mean = float(vals.std(ddof=1) / math.sqrt(vals.size))
        replica_summary = {
            "n_positions": int(vals.size),
            "mean_ev_per_photon": mean,
            "sample_sd_across_azimuths": float(vals.std(ddof=1)),
            "sd_of_the_mean": sd_of_mean,
            "relative_sd_of_the_mean": sd_of_mean / mean,
            "single_position_relative_sd": float(vals.std(ddof=1) / mean),
            "min": float(vals.min()),
            "max": float(vals.max()),
            "note": "Azimuthal replication: no extra Monte Carlo, the expectation "
            "is identical at every azimuth by symmetry, and the scatter is an "
            "independent uncertainty estimate that must agree with the "
            "independent-seed replica SD.",
        }
        values = {k: v for k, v in values.items() if not k.startswith("perimeter_")}
        values["perimeter"] = Value(
            value=mean,
            unit="eV per emitted photon",
            uncertainty=sd_of_mean,
            provenance=Provenance(
                formula=f"mean of the perimeter VOI over {vals.size} azimuths",
                inputs={"n_positions": int(vals.size)},
                assumptions=(
                    "a full 360 degree rotation of a cylindrically symmetric "
                    "phantom makes the dose field independent of azimuth, so every "
                    "position has the same expectation",
                ),
                source="ct_dosemc_core.tg195.perimeter_replica_weights",
            ),
        )
        print(
            f"[{gate}] perimeter replicated over {vals.size} azimuths: "
            f"SD/position {100 * replica_summary['single_position_relative_sd']:.4f}% "
            f"-> SD of mean {100 * replica_summary['relative_sd_of_the_mean']:.4f}%"
        )

    reference = read_case4_reference(
        CASE4_RESULTS, beam=beam, thickness_cm=args.fan_thickness, angular=angular
    )
    print(f"[{gate}] comparing against the {angular} angular reference")
    rows = compare(values, reference)
    _print_comparison(rows)

    passed = all(r["passes_tg195_tolerance"] for r in rows.values())
    strict = all(r["within_inter_code_range"] for r in rows.values())
    payload = {
        "gate": f"{gate} -- TG-195 Case 4 ({beam}, {test_choice} test, "
        f"{n_projections} projection(s))",
        "tag": tag,
        "passed": passed,
        "angular_reference_case": angular,
        "perimeter_azimuthal_replication": replica_summary,
        "anchor_quality": {
            "usable_as_anchor": int(args.sub_fans) >= 4,
            "n_sub_fans": int(args.sub_fans),
            "solid_angle_excess_fraction": meta["omega_excess_fraction"],
            "note": (
                "K < 4 oversamples the specified solid angle (1.14% at K=1) and "
                "happens to agree better with the reference. That is not a reason "
                "to use it. These values demonstrate self-consistency between the "
                "angular sub-cases, where the bias is common to the pair and "
                "cancels; they are not anchor values. See "
                "docs/MC_SOURCE_MODEL.md section 5.3.3."
                if int(args.sub_fans) < 4
                else "Sub-fan count is fixed by solid-angle convergence, not by "
                "agreement with the reference."
            ),
        },
        "tolerance": {
            "criterion": "relative difference from the four-code mean within 1%",
            "source": "AAPM Report 195: users are asked to report the relative "
            "percentage difference against the mean (p.56), and the reference "
            "values themselves carry up to 1% statistical uncertainty per VOI "
            "(section 3.4).",
            "also_within_inter_code_range": strict,
            "note": "The inter-code range is reported separately and is a stricter "
            "bar than the report asks for -- for some VOIs the four packages agree "
            "to 0.1%, tighter than their own stated statistics.",
        },
        "engine": {
            "executable": str(Path(args.executable).resolve()),
            "executable_sha256": file_digest(args.executable),
            "build_info": json.loads(
                (REPO / "vendor" / "build" / "build_info.json").read_text(encoding="utf-8-sig")
            )
            if (REPO / "vendor" / "build" / "build_info.json").is_file()
            else None,
            "random_seed": int(args.seed),
        },
        "spectrum": spc,
        "geometry": {
            "spec": {
                "phantom_radius_cm": spec.phantom_radius_cm,
                "phantom_length_specified_cm": spec.phantom_length_cm,
                "sad_cm": spec.sad_cm,
                "fan_width_at_isocentre_cm": spec.fan_width_at_isocentre_cm,
                "fan_thickness_at_isocentre_cm": args.fan_thickness,
                "half_fan_deg": spec.half_fan_deg,
                "standard": "AAPM Report 195 (TG-195) Case 4, section 3.4",
            },
            **meta,
        },
        "results": {name: v for name, v in values.items()},
        "comparison_with_tg195": rows,
        "reference_note": "Reference values are read at run time from the AAPM "
        "electronic resources in data/tg195/, which are copyrighted and are not "
        "redistributed by this repository. Only the comparison is recorded here.",
        "known_gaps": [
            "MC-GPU tallies collision kerma; electrons are not transported.",
            f"Phantom modelled at {args.phantom_length:g} cm rather than the "
            "specified 300 cm; run --length-scan to show this is converged.",
            "Voxelised cylinder: the curved surface is stair-stepped at the "
            f"{args.voxel_size:g} cm voxel scale.",
            "The fan is approximated by "
            f"{args.sub_fans} azimuthal sub-fans; the residual solid-angle error "
            f"is {100 * meta['omega_excess_fraction']:+.4f} %.",
            f"Only {args.air_margin:g} cm of the 44 cm source-to-phantom air path "
            "is inside the voxel box; MC-GPU crosses the remainder without "
            "interaction. Measure the sensitivity with "
            "--scan air_margin=1,10,20,30,40.",
        ],
    }
    out = write_results(rundir / f"{gate.lower()}.json", payload)
    (REPO / "results" / f"phase1a_{gate}_{tag}.json").write_bytes(out.read_bytes())
    worst = max(abs(r["deviation_fraction"]) for r in rows.values()) if rows else float("nan")
    print(
        f"[{gate}] {'PASSED' if passed else 'DID NOT PASS'} "
        f"(worst deviation {100 * worst:+.3f} %, tolerance +/-{100 * TG195_TOLERANCE:g} %; "
        f"inside the inter-code range: {'yes' if strict else 'no'}) -- wrote {out}"
    )
    return 0 if passed else 2


def convergence_scan(args) -> int:
    """Repeat G1 varying one parameter, and report how far the answer moves.

    Every "we modelled it this way instead" in the gaps list is a claim about a
    number.  This turns each of them into a measurement, against the reference,
    so a reviewer can see the size of the approximation rather than take the word
    for it.
    """
    param, _, raw = args.scan.partition("=")
    param = param.strip()
    if param not in SCANNABLE:
        raise SystemExit(f"--scan parameter must be one of {sorted(SCANNABLE)}; got {param!r}")
    cast = int if param == "sub_fans" else float
    values_to_try = [cast(v) for v in raw.split(",") if v.strip()]
    if len(values_to_try) < 2:
        raise SystemExit("--scan needs at least two values to compare")

    spec = Case4Spec(fan_thickness_at_isocentre_cm=args.fan_thickness)
    # The scan must be able to follow the gate it is diagnosing. A residual seen
    # on the second test's centre VOI at 120 kVp cannot be chased with a
    # monoenergetic first-test scan: the VOIs differ, and so does how far the
    # scatter that feeds them travels.
    beam_choice = args.beam or "mono"
    test_choice = args.test or "first"
    beam = "56.4 keV" if beam_choice == "mono" else "120 kVp"
    n_projections = 1 if test_choice == "first" else int(args.projections)
    voi_builder = first_test_voi_weights if test_choice == "first" else second_test_voi_weights
    angular = "discrete" if (test_choice == "second" and n_projections == 36) else "continuous"
    reference = read_case4_reference(
        CASE4_RESULTS, beam=beam, thickness_cm=args.fan_thickness, angular=angular
    )
    print(f"[scan] {beam}, {test_choice} test, {n_projections} projection(s), {angular} reference")
    rundir = REPO / "results" / "phase1a" / f"scan_{param}_{beam_choice}_{test_choice}"
    rundir.mkdir(parents=True, exist_ok=True)

    scan: dict[str, dict[str, float]] = {}
    deviations: dict[str, dict[str, float]] = {}
    for value in values_to_try:
        print(f"\n[scan] {param} = {value:g}")
        setattr(args, param, value)
        if beam_choice == "mono":
            write_monoenergetic_spectrum(rundir / "mono.spc", spec.monoenergetic_kev)
            spectrum_file = "mono.spc"
        else:
            energy, fluence, _hdr = read_tg195_spectrum(SPECTRA_XLSX, column="120 kVp")
            write_tg195_spectrum_file(rundir / "tg195_120kvp.spc", energy, fluence)
            spectrum_file = "tg195_120kvp.spc"
        got, _meta = run_sub_fan_set(
            spec=spec,
            args=args,
            rundir=rundir,
            spectrum_file=spectrum_file,
            voi_builder=voi_builder,
            phantom_length_cm=args.phantom_length,
            n_projections=n_projections,
            label=f"{param}{value:g}",
        )
        key = f"{value:g}"
        scan[key] = {k: v.value for k, v in got.items()}
        deviations[key] = {
            k: v.value / reference[k]["mean"] - 1.0 for k, v in got.items() if k in reference
        }
        worst = max(abs(x) for x in deviations[key].values())
        print(f"    worst deviation from the TG-195 mean: {100 * worst:+.3f} %")

    out = write_results(
        REPO / "results" / f"phase1a_{param}_convergence_{beam_choice}_{test_choice}.json",
        {
            "gate": f"TG-195 Case 4 first test: convergence in {param}",
            "parameter": param,
            "parameter_meaning": SCANNABLE[param],
            "beam": beam,
            "test": test_choice,
            "n_projections": n_projections,
            "angular_reference_case": angular,
            "values": values_to_try,
            "fixed": {
                k: getattr(args, k)
                for k in ("phantom_length", "air_margin", "voxel_size", "sub_fans", "histories")
                if k != param
            },
            "results_ev_per_photon": scan,
            "deviation_from_tg195_mean": deviations,
            "note": "Each entry is a full G1 run; the deviation column is against "
            "the same four-code TG-195 mean the gate is judged on, so the size of "
            "the approximation is read directly rather than argued.",
        },
    )
    print(f"\n[scan] wrote {out}")
    return 0


def replica_study(args) -> int:
    """G4 -- the Monte-Carlo uncertainty, estimated three ways.

    Three estimators of the same quantity, in increasing order of trustworthiness:

    1. **per-voxel quadrature within one run.** Treats voxel tallies as
       independent; they are not, since one photon deposits in many voxels, so it
       understates sigma.
    2. **sub-fan quadrature.** The sub-fans are separate engine invocations with
       disjoint stretches of the random sequence, so combining *those* in
       quadrature is legitimate. Still blind to any correlation inside a sub-fan.
    3. **replica sample SD.** K runs differing only in seed. Assumes nothing.

    Reporting all three, rather than the most convenient one, is the point: where
    they disagree the disagreement is the finding.
    """
    k = int(args.replicas)
    if k < 1:
        raise SystemExit("--replicas needs at least 1 run")
    base_seed = int(args.seed)
    # The inflation factor is a property of the estimator and the VOI, not of the
    # beam, so it has to be measured on the VOIs it will be applied to. Measuring
    # it on the first test's axial sections and then using it to judge the second
    # test's small cylinders would be assuming the very thing in question.
    beam_choice = args.beam or "mono"
    test_choice = args.test or "first"
    voi_builder = first_test_voi_weights if test_choice == "first" else second_test_voi_weights
    n_projections = 1 if test_choice == "first" else int(args.projections)

    # What a saved replica must match to be reused. A multi-hour run that dies at
    # replica 7 must not lose replicas 0-6, and must never silently reuse a
    # replica computed at a different history count, geometry or beam.
    config = {
        "histories": float(args.histories),
        "voxel_size_cm": float(args.voxel_size),
        "air_margin_cm": float(args.air_margin),
        "air_margin_z_cm": float(args.air_margin_z),
        "phantom_length_cm": float(args.phantom_length),
        "sub_fans": int(args.sub_fans),
        "n_projections": int(n_projections),
        "beam": beam_choice,
        "test": test_choice,
        "fan_thickness_cm": float(args.fan_thickness),
        "material_emin_kev": int(args.material_emin_kev),
        "executable": str(Path(args.executable).resolve()),
    }

    def _config_matches(stored: dict) -> bool:
        for key, want in config.items():
            got = stored.get(key)
            if isinstance(want, float):
                if got is None or not math.isclose(float(got), want, rel_tol=1e-9):
                    return False
            elif got != want:
                return False
        return True

    def _comparison(per_run, quoted):
        out = {}
        n = len(per_run)
        for name in sorted(per_run[0]):
            samples = np.array([r[name] for r in per_run])
            mean = float(samples.mean())
            replica_sd = float(samples.std(ddof=1)) if n >= 2 else float("nan")
            subfan_sd = float(np.mean([q[name] for q in quoted]))
            out[name] = {
                "mean_ev_per_photon": mean,
                "replica_sample_sd": replica_sd,
                "replica_relative_sd": replica_sd / mean if mean else float("nan"),
                "sub_fan_quadrature_sd": subfan_sd,
                "replica_over_sub_fan": replica_sd / subfan_sd if subfan_sd else float("nan"),
                "n_replicas": n,
                "sd_of_the_sd_relative": (
                    float(1.0 / math.sqrt(2.0 * (n - 1))) if n >= 2 else float("nan")
                ),
            }
        return out

    # Sub-fan count and phantom length are both part of the configuration, so they
    # must be part of the filename too: a K=1 SD run, a K=4 40 cm anchor, and a
    # K=4 160 cm length arm are different measurements and must not clobber each
    # other on disk.
    k_sub_fans = int(args.sub_fans)
    length_cm = int(round(float(args.phantom_length)))
    tag_suffix = f"_{args.tag}" if args.tag else ""
    final_path = (
        REPO
        / "results"
        / f"phase1a_G4_replica_uncertainty_{beam_choice}_{test_choice}_K{k_sub_fans}_L{length_cm}{tag_suffix}.json"
    )
    progress_path = final_path.with_suffix(".progress.json")
    per_run: list[dict[str, float]] = []
    quoted: list[dict[str, float]] = []
    replica_records: list[dict] = []
    engine_invocations_each: list[int] = []
    driven_externally_each: list[bool] = []
    user_tag = args.tag

    for i in range(k):
        seed_i = base_seed + 7919 * (i + 1)  # disjoint PRNG starts
        tag = f"replica_{beam_choice}_{test_choice}_K{k_sub_fans}_L{length_cm}_{i:02d}"
        if user_tag:
            tag = f"{tag}_{user_tag}"
        args.seed = seed_i
        rundir = REPO / "results" / "phase1a" / tag
        rundir.mkdir(parents=True, exist_ok=True)
        result_path = rundir / "replica_result.json"

        reused = False
        if result_path.is_file():
            try:
                stored = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                stored = None
            if stored and stored.get("seed") == seed_i and _config_matches(stored.get("config", {})):
                per_run.append({n: float(v) for n, v in stored["values_ev_per_photon"].items()})
                quoted.append({n: float(v) for n, v in stored["quoted_uncertainty"].items()})
                engine_invocations_each.append(int(stored.get("engine_invocations", 0)))
                driven_externally_each.append(bool(stored.get("projections_driven_externally", False)))
                replica_records.append(stored)
                reused = True
                print(f"\n[G4] replica {i + 1}/{k}: reusing {result_path.name} (seed {seed_i})", flush=True)
                for n, v in per_run[-1].items():
                    print(f"    {n}: {v:.4f} (from disk)", flush=True)

        if not reused:
            print(f"\n[G4] replica {i + 1}/{k}, seed {seed_i}", flush=True)
            spec = Case4Spec(fan_thickness_at_isocentre_cm=args.fan_thickness)
            if beam_choice == "mono":
                write_monoenergetic_spectrum(rundir / "mono.spc", spec.monoenergetic_kev)
                spectrum_file = "mono.spc"
            else:
                energy, fluence, _hdr = read_tg195_spectrum(SPECTRA_XLSX, column="120 kVp")
                write_tg195_spectrum_file(rundir / "tg195_120kvp.spc", energy, fluence)
                spectrum_file = "tg195_120kvp.spc"
            values, meta = run_sub_fan_set(
                spec=spec,
                args=args,
                rundir=rundir,
                spectrum_file=spectrum_file,
                voi_builder=voi_builder,
                phantom_length_cm=args.phantom_length,
                n_projections=n_projections,
                label="g4",
            )
            per_run.append({name: v.value for name, v in values.items()})
            quoted.append({name: float(v.uncertainty or 0.0) for name, v in values.items()})
            engine_invocations_each.append(int(meta.get("engine_invocations", 0)))
            driven_externally_each.append(bool(meta.get("projections_driven_externally", False)))
            record = {
                "replica_index": i,
                "seed": seed_i,
                "config": config,
                "values_ev_per_photon": per_run[-1],
                "quoted_uncertainty": quoted[-1],
                "engine_invocations": int(meta.get("engine_invocations", 0)),
                "projections_driven_externally": bool(
                    meta.get("projections_driven_externally", False)
                ),
                "wall_seconds": float(
                    sum(b.get("wall_seconds", 0.0) or 0.0 for b in meta.get("beamlets", []))
                ),
                **source_route_fields(
                    n_sub_fans=int(args.sub_fans),
                    n_projections=n_projections,
                    engine_invocations=int(meta.get("engine_invocations", 0)),
                ),
            }
            replica_records.append(record)
            # Persist this replica before starting the next one, so a crash in a
            # multi-hour run keeps every replica already paid for.
            write_results(result_path, record)
            for name, v in values.items():
                print(f"    {name}: {v.value:.4f} +/- {v.uncertainty:.4f}")

        # Rewrite the running summary after every replica. A job interrupted at
        # replica i still leaves a valid file describing replicas 0..i.
        write_results(
            progress_path,
            {
                "gate": "G4 -- MC uncertainty by independent-seed replicas (in progress)",
                "beam": beam_choice,
                "test": test_choice,
                "n_projections": n_projections,
                "n_sub_fans": int(args.sub_fans),
                "n_replicas_target": k,
                "n_replicas_done": len(per_run),
                "base_seed": base_seed,
                "engine_invocations_per_replica": engine_invocations_each,
                "projections_driven_externally": driven_externally_each,
                **source_route_fields(
                    n_sub_fans=int(args.sub_fans),
                    n_projections=n_projections,
                    engine_invocations=(
                        engine_invocations_each[-1] if engine_invocations_each else 0
                    ),
                ),
                "comparison": _comparison(per_run, quoted) if len(per_run) >= 2 else None,
                "per_replica": replica_records,
            },
        )

    comparison = _comparison(per_run, quoted)
    for name, c in comparison.items():
        print(
            f"  {name:<12} replica SD {c['replica_sample_sd']:.4f} "
            f"({100 * c['replica_relative_sd']:.4f} %)"
            f"   sub-fan quadrature {c['sub_fan_quadrature_sd']:.4f}"
            f"   ratio {c['replica_over_sub_fan']:.2f}x"
        )

    # One engine invocation per replica is the evidence that the projection loop
    # stayed inside MC-GPU (native CT trajectory): with --sub-fans 1 there is a
    # single centred fan aimed at the axis, so run_sub_fan_set does not drive the
    # rotation externally. Recorded, not asserted, so a regression that
    # reintroduces P-per-replica invocations is visible in the results file.
    out = write_results(
        final_path,
        {
            "gate": "G4 -- Monte-Carlo uncertainty by independent-seed replicas",
            "beam": beam_choice,
            "test": test_choice,
            "n_projections": n_projections,
            "n_sub_fans": int(args.sub_fans),
            "estimator_inflated": (
                "sub-fan quadrature over independent engine invocations"
                if int(args.sub_fans) > 1
                else "per-voxel quadrature within one invocation"
            ),
            "n_replicas": k,
            "base_seed": base_seed,
            "engine_invocations_per_replica": engine_invocations_each,
            "projections_driven_externally": driven_externally_each,
            **source_route_fields(
                n_sub_fans=int(args.sub_fans),
                n_projections=n_projections,
                engine_invocations=(
                    engine_invocations_each[0] if engine_invocations_each else 0
                ),
            ),
            "comparison": comparison,
            "per_replica": replica_records,
            "note": "The sub-fan quadrature combines genuinely independent engine "
            "invocations, so unlike the per-voxel quadrature inside a single run it "
            "is not obviously biased. The replica SD assumes nothing at all. "
            "'sd_of_the_sd_relative' is 1/sqrt(2(K-1)): with K replicas the SD "
            "itself is only known to that precision, so ratios should be quoted as "
            "intervals rather than point estimates. Each replica is written to its "
            "own results/phase1a/replica_*/replica_result.json as it completes and "
            "reused on a re-run, so an interrupted multi-hour job resumes without "
            "recomputing finished replicas.",
        },
    )
    # The in-progress file is now superseded by the final one.
    if progress_path.is_file():
        progress_path.unlink()
    print(f"\n[G4] wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    global AIR, PMMA
    AIR, PMMA = _materials(args.material_emin_kev)
    if args.replicas:
        return replica_study(args)
    if args.scan:
        return convergence_scan(args)
    if args.gate == "G0":
        return gate_g0(args)
    return gate_g1_or_g2(args, gate=args.gate)


if __name__ == "__main__":
    raise SystemExit(main())

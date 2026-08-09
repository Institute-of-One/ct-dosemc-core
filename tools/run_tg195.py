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
    stage_material_files,
    write_input_file,
    write_voxel_file,
)
from ct_dosemc_core.phantom import Material  # noqa: E402
from ct_dosemc_core.provenance import Provenance, Value, file_digest, write_results  # noqa: E402
from ct_dosemc_core.tg195 import (  # noqa: E402
    Case4Spec,
    build_case4_phantom,
    first_test_voi_weights,
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

AIR = Material(1, "air, dry (PENELOPE #104)", "air_5-120keV.mcgpu.gz", 1.20479e-3)
PMMA = Material(2, "PMMA (PENELOPE #224)", "PMMA_5-120keV.mcgpu.gz", 1.19)


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
        default=1.0,
        help="cm of air modelled around the cylinder. TG-195 fills the rest of the "
        "geometry with air, but MC-GPU's voxel box cannot reach the source: photons "
        "cross the gap unattenuated, so this controls how much of the 44 cm "
        "source-to-phantom air path is actually simulated.",
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
    p.add_argument("--seed", type=int, default=1234567890)
    p.add_argument("--executable", type=Path, default=DEFAULT_EXE)
    p.add_argument("--tag", type=str, default=None)
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

    # Tally only the scored slab. The geometry is 3 m long; the VOIs span at most
    # z = -50..+35 mm, and a full-length tally would cost 350 MB for nothing.
    half_slab_cm = 6.0
    z_lo = max(1, int((cz - half_slab_cm) / v) + 1)
    z_hi = min(nz, int((cz + half_slab_cm) / v) + 1)

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
    if drive_projections_here:
        print(
            f"[traj ] {n_projections} projections x {len(fans)} sub-fans = {n_runs} "
            "engine invocations (MC-GPU re-aims at the rotation centre, so its "
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
            if args.rescore:
                # Re-score an existing tally. The scoring geometry is rebuilt from
                # the same arguments, so this is only valid when they are
                # unchanged; assert_apertures below re-reads the engine's own log
                # and catches the case where they are not.
                existing = rundir / f"dose_{stem}.dat"
                if not (existing.parent / (existing.name + ".raw")).is_file():
                    raise SystemExit(f"--rescore: no tally at {existing}.raw")
                run = McgpuRun(
                    executable=Path(args.executable).resolve(),
                    input_file=rundir / f"case4_{stem}.in",
                    log_file=rundir / f"mcgpu_{stem}.log",
                    returncode=0,
                    wall_seconds=float("nan"),
                    total_histories=per_fan_histories * engine_projections,
                )
                _score_beamlet(
                    run=run,
                    rundir=rundir,
                    stem=stem,
                    fan=fan,
                    phantom=phantom,
                    spec=spec,
                    voi_builder=voi_builder,
                    weight=(fan.solid_angle_sr / omega_total) / len(gantry_angles),
                    totals=totals,
                    variances=variances,
                    fan_records=fan_records,
                    p_index=p_index,
                    beta=beta,
                    histories=per_fan_histories * engine_projections,
                )
                continue

            inp = write_input_file(
                rundir / f"case4_{stem}.in",
                histories_per_projection=per_fan_histories,
                random_seed=args.seed + 1000 * fan.index + 7 * p_index,
                spectrum_file=spectrum_file,
                source_position_cm=(sx, sy, cz),
                source_direction=(ux, uy, 0.0),
                polar_aperture_deg=fan.polar_aperture_deg,
                azimuthal_aperture_deg=fan.azimuthal_aperture_deg,
                image_file=f"image_{stem}.dat",
                image_pixels=(4, 4),
                image_size_cm=(40.0, 4.0),
                sdd_cm=100.0,
                n_projections=engine_projections,
                angle_between_projections_deg=(
                    360.0 / engine_projections if engine_projections > 1 else 0.0
                ),
                sad_cm=spec.sad_cm,
                translation_per_projection_cm=0.0,
                dose_file=f"dose_{stem}.dat",
                voxel_file=vox.name,
                materials=materials,
                dose_roi=((1, nx), (1, ny), (z_lo, z_hi)),
            )
            run = run_mcgpu(
                args.executable,
                inp,
                workdir=rundir,
                log_file=rundir / f"mcgpu_{stem}.log",
                total_histories=per_fan_histories * engine_projections,
                timeout_s=args.timeout_hours * 3600.0,
            )
            run.check()
            _score_beamlet(
                run=run,
                rundir=rundir,
                stem=stem,
                fan=fan,
                phantom=phantom,
                spec=spec,
                voi_builder=voi_builder,
                weight=(fan.solid_angle_sr / omega_total) / len(gantry_angles),
                totals=totals,
                variances=variances,
                fan_records=fan_records,
                p_index=p_index,
                beta=beta,
                histories=per_fan_histories * engine_projections,
            )
            if len(gantry_angles) == 1:
                print(
                    f"[fan {fan.index:02d}] psi={fan.centre_psi_deg:+7.3f} deg  "
                    f"w={fan_records[-1]['weight']:.4f}  "
                    f"{fan_records[-1]['wall_seconds']:6.1f} s"
                )
        if len(gantry_angles) > 1:
            print(
                f"[proj {p_index + 1:3d}/{len(gantry_angles)}] "
                f"beta={math.degrees(beta):6.1f} deg  "
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
        "n_sub_fans": len(fans),
        "omega_total_sr": omega_total,
        "omega_specified_sr": omega_spec,
        "omega_excess_fraction": omega_total / omega_spec - 1.0,
        "histories_total": float(args.histories),
        "n_projections": n_projections,
        "projections_driven_externally": drive_projections_here,
        "engine_invocations": n_runs,
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


def compare(values: dict[str, Value], reference: dict[str, dict[str, float]]) -> dict:
    """Our numbers against the published ones."""
    rows = {}
    for name, v in values.items():
        if name not in reference:
            continue
        ref = reference[name]
        ratio = v.value / ref["mean"]
        rows[name] = {
            "ours_ev_per_photon": v.value,
            "ours_sigma": v.uncertainty,
            "ours_relative_sigma": (v.uncertainty / v.value) if v.uncertainty else None,
            "reference_mean": ref["mean"],
            "reference_min": ref["min"],
            "reference_max": ref["max"],
            "inter_code_spread_fraction": ref["inter_code_spread_fraction"],
            "ratio_to_reference_mean": ratio,
            "deviation_fraction": ratio - 1.0,
            "passes_tg195_tolerance": bool(abs(ratio - 1.0) <= TG195_TOLERANCE),
            "within_inter_code_range": bool(ref["min"] <= v.value <= ref["max"]),
        }
    return rows


def _print_comparison(rows: dict) -> None:
    print()
    print(
        f"  {'VOI':<12} {'ours':>13} {'ref mean':>13} {'dev':>9} "
        f"{'MC sigma':>9} {'code spread':>12}  {'vs 1%':>6}  in-range"
    )
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
        voi_builder = second_test_voi_weights
        n_projections = int(args.projections)
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
    reference = read_case4_reference(CASE4_RESULTS, beam="56.4 keV", thickness_cm=args.fan_thickness)
    rundir = REPO / "results" / "phase1a" / f"scan_{param}"
    rundir.mkdir(parents=True, exist_ok=True)

    scan: dict[str, dict[str, float]] = {}
    deviations: dict[str, dict[str, float]] = {}
    for value in values_to_try:
        print(f"\n[scan] {param} = {value:g}")
        setattr(args, param, value)
        write_monoenergetic_spectrum(rundir / "mono.spc", spec.monoenergetic_kev)
        got, _meta = run_sub_fan_set(
            spec=spec,
            args=args,
            rundir=rundir,
            spectrum_file="mono.spc",
            voi_builder=first_test_voi_weights,
            phantom_length_cm=args.phantom_length,
            n_projections=1,
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
        REPO / "results" / f"phase1a_G1_{param}_convergence.json",
        {
            "gate": f"TG-195 Case 4 first test: convergence in {param}",
            "parameter": param,
            "parameter_meaning": SCANNABLE[param],
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.scan:
        return convergence_scan(args)
    if args.gate == "G0":
        return gate_g0(args)
    return gate_g1_or_g2(args, gate=args.gate)


if __name__ == "__main__":
    raise SystemExit(main())

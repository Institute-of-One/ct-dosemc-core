"""Phase 1 -- the CTDI validation anchor.

Simulate one axial rotation of a collimated beam about a standard CTDI phantom,
score the dose at the five chamber positions, and report CTDI100, CTDIw and
CTDIvol with their Monte-Carlo statistical uncertainties.

This is the gate.  Patient doses are not computed until the numbers this script
produces have been reviewed, because the CTDI phantom is the one geometry where a
published standard, rather than an image, fixes the answer.

Usage::

    python tools/run_validation.py --kvp 120 --phantom-diameter 32 --histories 2e7

Everything it writes -- the spectrum, the voxel geometry, the engine input, the
log, the raw tallies and the results JSON -- lands under ``results/phase1/<tag>/``
so a run can be re-read long after the fact.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ct_dosemc_core import ctdi as ctdi_mod  # noqa: E402
from ct_dosemc_core.ctdi import (  # noqa: E402
    CHAMBER_POSITIONS,
    CtdiPhantomSpec,
    build_ctdi_phantom,
    chamber_masks,
    ctdi_100,
    ctdi_vol,
    ctdi_w,
)
from ct_dosemc_core.dosimetry import region_dose  # noqa: E402
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
from ct_dosemc_core.source_model import BeamGeometry, histories_for_mas  # noqa: E402
from ct_dosemc_core.spectra import Filter, generate_spectrum, write_mcgpu_spectrum  # noqa: E402

DEFAULT_EXE = REPO / "vendor" / "build" / "MC-GPU_v1.3_CPU.exe"
MATERIALS_DIR = REPO / "materials"

AIR = Material(1, "air, dry (PENELOPE #104)", "air_5-120keV.mcgpu.gz", 1.20479e-3)
PMMA = Material(2, "PMMA (PENELOPE #224)", "PMMA_5-120keV.mcgpu.gz", 1.19)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--kvp", type=float, default=120.0)
    p.add_argument(
        "--added-filtration-mm-al",
        type=float,
        default=5.0,
        help="added Al filtration; the bowtie is NOT included (see docs/MC_SOURCE_MODEL.md)",
    )
    p.add_argument("--anode-angle-deg", type=float, default=7.0)
    p.add_argument("--phantom-diameter", type=float, default=32.0, help="32 = body, 16 = head")
    p.add_argument("--voxel-size", type=float, default=0.25, help="cm")
    p.add_argument("--collimation", type=float, default=2.0, help="nominal N*T at isocentre, cm")
    p.add_argument("--sad", type=float, default=60.0, help="source-to-axis distance, cm")
    p.add_argument("--sdd", type=float, default=100.0, help="source-to-detector distance, cm")
    p.add_argument("--mas", type=float, default=100.0, help="mAs per rotation to report for")
    p.add_argument("--pitch", type=float, default=1.0)
    p.add_argument("--histories", type=float, default=2.0e6, help="histories PER PROJECTION")
    p.add_argument("--projections", type=int, default=90, help="angular samples over 360 degrees")
    p.add_argument("--seed", type=int, default=1234567890)
    p.add_argument("--fan-margin-deg", type=float, default=2.0)
    p.add_argument("--executable", type=Path, default=DEFAULT_EXE)
    p.add_argument("--tag", type=str, default=None)
    p.add_argument("--timeout-hours", type=float, default=48.0)
    p.add_argument(
        "--keep-raw",
        action="store_true",
        help="keep the per-projection image files (they are deleted by default)",
    )
    p.add_argument(
        "--reuse-tally",
        action="store_true",
        help="re-score an existing dose tally in the run directory instead of "
        "re-running the engine. Only valid when the geometry arguments are "
        "unchanged; the tally's own voxel size is checked against them.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    tag = args.tag or (
        f"{args.kvp:g}kV_{args.phantom_diameter:g}cm_NT{args.collimation:g}cm_"
        f"{args.histories:.0e}x{args.projections}"
    )
    rundir = REPO / "results" / "phase1" / tag
    rundir.mkdir(parents=True, exist_ok=True)
    print(f"[phase1] {tag}\n[phase1] run directory: {rundir}")

    # -- 1. spectrum -------------------------------------------------------
    filters = (Filter("Al", args.added_filtration_mm_al),)
    spectrum = generate_spectrum(
        args.kvp,
        filters,
        anode_angle_deg=args.anode_angle_deg,
        reference_distance_cm=100.0,
    )
    spc_summary = write_mcgpu_spectrum(rundir / "spectrum.spc", spectrum, e_min_kev=5.0)
    print(
        f"[phase1] {args.kvp:g} kVp, +{args.added_filtration_mm_al:g} mm Al: "
        f"HVL1 = {spectrum.hvl1_al_mm:.3f} mm Al, HVL2 = {spectrum.hvl2_al_mm:.3f} mm Al, "
        f"Emean = {spectrum.mean_energy_kev:.2f} keV"
    )

    # -- 2. geometry -------------------------------------------------------
    spec = CtdiPhantomSpec(
        diameter_cm=args.phantom_diameter,
        voxel_size_cm=args.voxel_size,
    )
    phantom = build_ctdi_phantom(spec, air=AIR, pmma=PMMA)
    nx, ny, nz = phantom.n_voxels
    print(
        f"[phant] {spec.diameter_cm:g} cm PMMA cylinder, {nx} x {ny} x {nz} voxels of "
        f"{args.voxel_size:g} cm ({phantom.mass_g(phantom.material == PMMA.index) / 1000:.2f} kg PMMA)"
    )

    half_fan_deg = math.degrees(math.asin(min(0.999, spec.radius_cm / args.sad)))
    fan_deg = 2.0 * half_fan_deg + args.fan_margin_deg
    beam = BeamGeometry(
        sad_cm=args.sad,
        sdd_cm=args.sdd,
        collimation_cm=args.collimation,
        fan_aperture_deg=fan_deg,
    )
    if not beam.covers_radius(spec.radius_cm):
        raise SystemExit("fan aperture does not cover the phantom")

    n_omega = spectrum.photons_per_sr_per_mas()
    n_required = histories_for_mas(n_omega.value, beam, args.mas)
    n_simulated = float(args.histories) * int(args.projections)
    print(
        f"[beam ] fan {fan_deg:.3f} deg, polar {beam.polar_aperture_deg:.4f} deg, "
        f"Omega = {beam.solid_angle_sr:.6e} sr"
    )
    print(
        f"[norm ] {args.mas:g} mAs -> {n_required.value:.4e} photons; "
        f"simulating {n_simulated:.3e} for statistics "
        f"({n_simulated / n_required.value:.4f} x)"
    )

    # -- 3. write engine inputs -------------------------------------------
    materials = stage_material_files((AIR, PMMA), MATERIALS_DIR, rundir)
    vox = write_voxel_file(rundir / "ctdi_phantom.vox.gz", phantom)
    print(f"[phant] wrote {vox.name} ({vox.stat().st_size / 1e6:.1f} MB gz)")

    cx, cy, cz = phantom.centre_cm()
    inp = write_input_file(
        rundir / "ctdi.in",
        histories_per_projection=float(args.histories),
        random_seed=args.seed,
        spectrum_file="spectrum.spc",
        source_position_cm=(cx, cy - args.sad, cz),
        source_direction=(0.0, 1.0, 0.0),
        polar_aperture_deg=beam.polar_aperture_deg,
        azimuthal_aperture_deg=fan_deg,
        image_file="image.dat",
        image_pixels=(8, 8),
        image_size_cm=(2.0 * args.sdd * math.tan(math.radians(0.5 * fan_deg)),
                       beam.beam_width_at(args.sdd)),
        sdd_cm=args.sdd,
        n_projections=int(args.projections),
        angle_between_projections_deg=360.0 / int(args.projections),
        sad_cm=args.sad,
        translation_per_projection_cm=0.0,
        dose_file="dose.dat",
        voxel_file=vox.name,
        materials=materials,
        dose_roi=((1, nx), (1, ny), (1, nz)),
    )

    # -- 4. run ------------------------------------------------------------
    if args.reuse_tally:
        if not (rundir / "dose.dat.raw").is_file():
            raise SystemExit(f"--reuse-tally: no tally in {rundir}")
        print("[mcgpu] --reuse-tally: re-scoring the existing tally, engine not run")
        run = McgpuRun(
            executable=Path(args.executable).resolve(),
            input_file=inp,
            log_file=rundir / "mcgpu.log",
            returncode=0,
            wall_seconds=float("nan"),
            total_histories=n_simulated,
        )
    else:
        print(f"[mcgpu] running {Path(args.executable).name} ...")
        run = run_mcgpu(
            args.executable,
            inp,
            workdir=rundir,
            log_file=rundir / "mcgpu.log",
            total_histories=n_simulated,
            timeout_s=args.timeout_hours * 3600.0,
        )
        run.check()
    # The engine echoes the apertures it actually parsed; confirm they are the
    # ones we meant before a single dose value is believed.  Under --reuse-tally
    # this also catches a geometry argument that no longer matches the tally.
    run.assert_apertures(azimuthal_deg=fan_deg, polar_deg=beam.polar_aperture_deg)
    if not args.reuse_tally:
        print(
            f"[mcgpu] done in {run.wall_seconds / 60:.1f} min "
            f"({n_simulated / max(run.wall_seconds, 1e-9):.3e} histories/s)"
        )

    # -- 5. score ----------------------------------------------------------
    dose = read_dose_map(rundir / "dose.dat")
    if not math.isclose(dose.voxel_size_cm[0], args.voxel_size, rel_tol=1e-6):
        raise SystemExit(
            f"the stored tally has {dose.voxel_size_cm[0]} cm voxels but "
            f"--voxel-size {args.voxel_size} was given"
        )
    masks = chamber_masks(
        phantom,
        spec,
        roi_origin_zyx=dose.roi_origin_zyx,
        roi_shape_zyx=dose.shape_zyx,
    )
    z0, y0, x0 = dose.roi_origin_zyx
    dz, dy, dx = dose.shape_zyx
    density_roi = phantom.density[z0 : z0 + dz, y0 : y0 + dy, x0 : x0 + dx]

    ctdi100: dict[str, Value] = {}
    regions = {}
    for name in CHAMBER_POSITIONS:
        r = region_dose(name, dose, masks[name], density_roi, n_required.value)
        regions[name] = r
        ctdi100[name] = ctdi_100(
            r,
            collimation_cm=args.collimation,
            chamber_length_cm=spec.chamber_length_cm,
        )
        print(
            f"[score] {name:12s} CTDI100_PMMA = {ctdi100[name].value:8.4f} mGy "
            f"+/- {ctdi100[name].uncertainty:.4f} "
            f"({100 * ctdi100[name].uncertainty / ctdi100[name].value:.2f} %, "
            f"{r.n_voxels} voxels)"
        )

    # -- 5b. beam-geometry diagnostics ------------------------------------
    # The aperture-order defect that produced a wide-open Z beam still gave
    # plausible-looking CTDI numbers.  What it could not fake is the shape of the
    # longitudinal profile and the sign of the radial gradient, so both are
    # measured and reported rather than assumed.
    zc = (np.arange(dz) + 0.5) * dose.voxel_size_cm[2]
    z_axis = zc - zc.mean()
    # Use whichever peripheral chamber received the most dose. Over a full
    # rotation the four are equivalent, so this is any of them; for a single
    # projection it picks the one facing the source, which is the only one with a
    # collimated primary peak to measure a width from.
    peripheral_names = [n for n in CHAMBER_POSITIONS if n != "centre"]
    hottest = max(peripheral_names, key=lambda n: float(dose.dose_ev_per_g[masks[n]].sum()))
    peri_mask = masks[hottest].any(axis=0)
    z_profile = (dose.dose_ev_per_g * peri_mask[None, :, :]).sum(axis=(1, 2)) / peri_mask.sum()
    half = 0.5 * float(z_profile.max())
    above = np.flatnonzero(z_profile >= half)
    fwhm_cm = (
        float(z_axis[above[-1]] - z_axis[above[0]] + dose.voxel_size_cm[2])
        if above.size
        else float("nan")
    )
    geometric_fwhm_cm = beam.beam_width_at(args.sad - spec.peripheral_radius_cm)

    # Surface dose must exceed central dose in a 32 cm phantom; if it does not,
    # the beam is not entering the phantom the way we think it is.
    xs, ys, _zs = phantom.axis_coordinates_cm()
    pcx, pcy, _pcz = phantom.centre_cm()
    radius_map = np.hypot(
        xs[None, x0 : x0 + dx] - pcx, ys[y0 : y0 + dy, None] - pcy
    )
    z_window = np.abs(z_axis) <= 0.5 * spec.chamber_length_cm
    integrated = dose.dose_ev_per_g[z_window].sum(axis=0) * dose.voxel_size_cm[2]
    # Take the material map from a slice inside the phantom, not from the first
    # ROI slice -- the ROI starts in the air margin, where nothing is PMMA.
    mid_z = z0 + dz // 2
    in_pmma = phantom.material[mid_z, y0 : y0 + dy, x0 : x0 + dx] == PMMA.index

    def shell(lo: float, hi: float) -> float:
        sel = (radius_map >= lo) & (radius_map < hi) & in_pmma
        if not sel.any():
            raise ValueError(f"no PMMA voxels between r={lo} and r={hi} cm")
        return float(integrated[sel].mean())

    radial_surface_over_centre = shell(spec.radius_cm - 1.0, spec.radius_cm) / shell(0.0, 1.0)

    print(
        f"[check] peripheral beam FWHM      = {fwhm_cm:.3f} cm "
        f"(geometric {geometric_fwhm_cm:.3f} cm)"
    )
    print(f"[check] surface/centre radial dose = {radial_surface_over_centre:.3f} (must be > 1)")

    # -- single-projection geometry check ---------------------------------
    # The FWHM above is only sensitive to gantry angles near the chamber: the
    # peripheral peak is dominated by the ~30 degrees where the source faces it,
    # and a rotation average can hide a wrong beam definition. With one
    # projection there is no averaging to hide behind, and both the longitudinal
    # and the in-plane extent can be read against plain geometry.
    #
    # This is the cheap in-repo version. The decisive test of the beam definition
    # is tools/run_tg195.py --gate G1, which puts the same single-projection
    # geometry against four independent Monte Carlo codes; a wrong fan width
    # would show up there directly as a normalisation error.
    fan_check = None
    if int(args.projections) == 1:
        entry_slab = np.abs(z_axis) <= 0.5 * args.collimation
        entry = dose.dose_ev_per_g[entry_slab].sum(axis=0)
        # Restrict to PMMA so the measured width is directly comparable with the
        # phantom diameter; the beam also lights up the air margin either side.
        entry = np.where(in_pmma, entry, 0.0)
        in_beam = entry > 0.5 * entry[entry > 0].max()
        xs = np.nonzero(in_beam.any(axis=0))[0]
        measured_width = (xs[-1] - xs[0] + 1) * dose.voxel_size_cm[0]
        geometric_width = 2.0 * args.sad * math.tan(math.radians(0.5 * fan_deg))
        covered = min(geometric_width, 2.0 * spec.radius_cm)
        fan_check = {
            "measured_irradiated_width_cm": float(measured_width),
            "geometric_fan_width_at_isocentre_cm": geometric_width,
            "expected_width_clipped_by_phantom_cm": covered,
            "note": "Single projection, so no rotation average can mask a wrong "
            "beam definition. The measured width is clipped by the phantom "
            "whenever the fan is wider than it.",
        }
        print(
            f"[check] in-plane irradiated width = {measured_width:.2f} cm "
            f"(geometric fan {geometric_width:.2f} cm, phantom {2 * spec.radius_cm:.2f} cm)"
        )

    peripheral = ctdi_mod.average_peripheral(ctdi100)
    cw = ctdi_w(ctdi100["centre"], peripheral)
    cvol = ctdi_vol(cw, args.pitch)

    per_vals = [ctdi100[n].value for n in CHAMBER_POSITIONS if n != "centre"]
    symmetry_spread = (max(per_vals) - min(per_vals)) / peripheral.value
    # The four peripheral positions are physically equivalent under a full
    # rotation, so their scatter IS a Monte-Carlo uncertainty -- and unlike the
    # quadrature sum of per-voxel sigmas it does not assume the voxel tallies are
    # independent.  The expected range of four standard normals is 2.059 sigma.
    sigma_from_symmetry = float(np.std(per_vals, ddof=1) / math.sqrt(len(per_vals)))
    quoted_sigma = peripheral.uncertainty or float("nan")
    understatement = sigma_from_symmetry / quoted_sigma if quoted_sigma else float("nan")
    ratio_c_p = Value(
        value=ctdi100["centre"].value / peripheral.value,
        unit="dimensionless",
        uncertainty=None,
        provenance=Provenance(
            formula="CTDI100_centre / CTDI100_peripheral",
            inputs={
                "centre_mGy": ctdi100["centre"].value,
                "peripheral_mGy": peripheral.value,
            },
            assumptions=(
                "medium-independent to first order, so it is comparable with the "
                "published air-kerma ratio without the PMMA-to-air conversion",
            ),
            source="compared against published 32 cm body-phantom values at 120 kVp",
        ),
    )

    # Air kerma free in air at the isocentre, straight from SpekPy -- an
    # independent open number that does not pass through the Monte Carlo at all.
    kerma_iso = Value(
        value=spectrum.air_kerma_ugy_per_mas
        * (spectrum.reference_distance_cm / args.sad) ** 2
        * args.mas
        / 1000.0,
        unit="mGy",
        uncertainty=None,
        provenance=Provenance(
            formula="K_air(SAD) = K_air(z_ref) * (z_ref/SAD)^2 * mAs",
            inputs={
                "K_air_uGy_per_mAs_at_z_ref": spectrum.air_kerma_ugy_per_mas,
                "z_ref_cm": spectrum.reference_distance_cm,
                "SAD_cm": args.sad,
                "mAs": args.mas,
            },
            assumptions=(
                "inverse-square law, no air attenuation",
                "no bowtie filter, so this is the unattenuated central-ray value",
            ),
            source=f"SpekPy {spectrum.spekpy_version}",
        ),
    )

    print(
        f"[score] CTDIw_PMMA   = {cw.value:.4f} +/- {cw.uncertainty:.4f} mGy "
        f"per {args.mas:g} mAs"
    )
    print(f"[score] CTDIvol_PMMA = {cvol.value:.4f} +/- {cvol.uncertainty:.4f} mGy")
    print(f"[check] centre/peripheral        = {ratio_c_p.value:.4f}")
    print(f"[check] peripheral 4-point spread = {100 * symmetry_spread:.2f} %")
    print(f"[check] free-in-air kerma at iso  = {kerma_iso.value:.4f} mGy (SpekPy, no MC)")

    # -- 6. report ---------------------------------------------------------
    payload = {
        "phase": "1 -- CTDI validation anchor",
        "tag": tag,
        "engine": {
            "name": "MC-GPU v1.3 (DIDSR/FDA, public domain)",
            "executable": str(run.executable),
            "executable_sha256": file_digest(run.executable),
            # PowerShell writes this with a UTF-8 BOM; utf-8-sig eats it so the read
            # does not depend on the machine's ANSI code page.
            "build_info": json.loads(
                (REPO / "vendor" / "build" / "build_info.json").read_text(encoding="utf-8-sig")
            )
            if (REPO / "vendor" / "build" / "build_info.json").is_file()
            else None,
            # NaN is not valid JSON; --reuse-tally did not time anything.
            "wall_seconds": run.wall_seconds if math.isfinite(run.wall_seconds) else None,
            "rescored_from_existing_tally": bool(args.reuse_tally),
            "histories_simulated": n_simulated,
            "histories_per_projection": float(args.histories),
            "projections": int(args.projections),
            "random_seed": int(args.seed),
        },
        "spectrum": {**spectrum.describe(), "mcgpu_file": spc_summary},
        "geometry": {
            "phantom": {
                "diameter_cm": spec.diameter_cm,
                "length_cm": spec.length_cm,
                "voxel_size_cm": spec.voxel_size_cm,
                "n_voxels_xyz": [nx, ny, nz],
                "pmma_density_g_cm3": spec.pmma_density_g_cm3,
                "pmma_mass_kg": phantom.mass_g(phantom.material == PMMA.index) / 1000.0,
                "chamber_diameter_cm": spec.chamber_diameter_cm,
                "chamber_length_cm": spec.chamber_length_cm,
                "chamber_depth_cm": spec.chamber_depth_cm,
                "standard": "IEC 60601-2-44",
            },
            "beam": {
                "sad_cm": beam.sad_cm,
                "sdd_cm": beam.sdd_cm,
                "collimation_cm": beam.collimation_cm,
                "fan_aperture_deg": beam.fan_aperture_deg,
                "polar_aperture_deg": beam.polar_aperture_deg,
                "solid_angle_sr": beam.solid_angle_value(),
                "pitch": args.pitch,
            },
        },
        "normalisation": {
            "photons_per_sr_per_mas": n_omega,
            "histories_for_reported_mas": n_required,
            "reported_mas": args.mas,
            "note": "The Monte Carlo ran a different number of histories than the "
            "reported mAs implies; dose per history is scaled to the reported mAs, "
            "which leaves the relative statistical uncertainty unchanged.",
        },
        "materials": [
            {
                "index": m.index,
                "name": m.name,
                "file": m.file,
                "sha256": file_digest(rundir / m.file),
                "nominal_density_g_cm3": m.nominal_density_g_cm3,
            }
            for m in materials
        ],
        "results": {
            "ctdi100_pmma_mgy": {k: v for k, v in ctdi100.items()},
            "ctdi100_peripheral_mean_mgy": peripheral,
            "ctdiw_pmma_mgy": cw,
            "ctdivol_pmma_mgy": cvol,
            "ratio_centre_over_peripheral": ratio_c_p,
            "peripheral_symmetry_spread_fraction": symmetry_spread,
            "uncertainty_cross_check": {
                "quoted_sigma_peripheral_mean_mgy": quoted_sigma,
                "sigma_from_four_position_scatter_mgy": sigma_from_symmetry,
                "understatement_factor": understatement,
                "note": "The four peripheral positions are physically equivalent "
                "under a full rotation, so their scatter is an independent estimate "
                "of the same uncertainty -- one that does not assume voxel tallies "
                "are uncorrelated, which they are not. Where the two disagree the "
                "larger should be quoted. Replacing the quadrature estimate with "
                "independent-seed replicas is an open item "
                "(docs/MC_SOURCE_MODEL.md section 6).",
            },
            "beam_geometry_checks": {
                "engine_apertures_deg": dict(
                    zip(("azimuthal", "polar"), run.echoed_apertures_deg(), strict=True)
                ),
                "peripheral_z_profile_fwhm_cm": fwhm_cm,
                "geometric_beam_width_at_peripheral_chamber_cm": geometric_fwhm_cm,
                "radial_surface_over_centre": radial_surface_over_centre,
                "single_projection_fan_check": fan_check,
                "note": "FWHM should match the geometric beam width to within the "
                "voxel size plus scatter broadening; the radial ratio must exceed 1 "
                "for a 32 cm phantom. Both are shape checks that a mis-parsed beam "
                "aperture cannot pass, unlike the CTDI values themselves.",
            },
            "air_kerma_free_in_air_at_isocentre_mgy": kerma_iso,
            "region_dose_detail": {
                k: {
                    "dose_mgy": r.dose_mgy,
                    "sigma_mgy": r.sigma_mgy,
                    "relative_sigma": r.relative_sigma,
                    "n_voxels": r.n_voxels,
                    "mass_g": r.mass_g,
                    "dose_ev_per_g_per_history": r.dose_ev_per_g_per_history,
                }
                for k, r in regions.items()
            },
        },
        "known_gaps": [
            "Absorbed dose to PMMA is reported, not air kerma in the bore: the "
            "(mu_en/rho)_air/(mu_en/rho)_PMMA conversion is not yet implemented.",
            "No bowtie filter. The beam is flat across the fan, so the peripheral "
            "dose is overestimated relative to a real scanner and the "
            "centre/peripheral ratio is biased low.",
            "MC-GPU tallies collision kerma; electrons are not transported.",
            "Point focal spot, no anti-scatter grid, no gantry or table attenuation.",
        ],
    }
    out = write_results(rundir / "ctdi_anchor.json", payload)
    shutil.copy2(out, REPO / "results" / f"phase1_ctdi_anchor_{tag}.json")
    print(f"[phase1] wrote {out}")

    if not args.keep_raw:
        removed = 0
        for f in rundir.glob("image.dat*"):
            f.unlink()
            removed += 1
        if removed:
            print(f"[phase1] removed {removed} per-projection image files (--keep-raw to keep)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

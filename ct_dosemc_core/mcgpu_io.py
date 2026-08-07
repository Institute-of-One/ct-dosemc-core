"""Write MC-GPU inputs, run the engine, read its outputs back.

Nothing in here does physics; it is the boundary between our Python model and the
public-domain MC-GPU v1.3 executable.  The file formats are pinned to the vendored
source, and the line references in the docstrings point at it so a reviewer can
check the convention without guessing.

MC-GPU reports voxel dose as **eV/g per history**, and separately the *percent*
relative error at **two** standard deviations.  Both are read here and converted
to a 1-sigma absolute uncertainty as early as possible, so that nothing
downstream has to remember the factor of two.
"""

from __future__ import annotations

import gzip
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .phantom import Material, VoxelPhantom

__all__ = [
    "DoseMap",
    "McgpuRun",
    "read_dose_map",
    "run_mcgpu",
    "write_input_file",
    "write_voxel_file",
]


def write_voxel_file(path: str | Path, phantom: VoxelPhantom, *, compress: bool = True) -> Path:
    """Write ``phantom`` in the penEasy 2008 voxel format MC-GPU reads.

    Two columns per voxel -- material index and mass density -- with X running
    fastest, then Y, then Z (vendor/MCGPU/MC-GPU_v1.3.cu:1908-1923).  Gzip is
    accepted directly by the engine and cuts the file by roughly 50x, so it is
    the default.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    nx, ny, nz = phantom.n_voxels
    dx, dy, dz = phantom.voxel_size_cm

    header = (
        "# Voxel geometry written by ct_dosemc_core\n"
        "# Voxel order: X runs first, then Y, then Z.\n"
        "[SECTION VOXELS HEADER v.2008-04-13]\n"
        f"{nx} {ny} {nz}   No. OF VOXELS IN X,Y,Z\n"
        f"{dx:.6e} {dy:.6e} {dz:.6e}   VOXEL SIZE (cm) ALONG X,Y,Z\n"
        "1   COLUMN NUMBER WHERE MATERIAL ID IS LOCATED\n"
        "2   COLUMN NUMBER WHERE THE MASS DENSITY IS LOCATED\n"
        "0   BLANK LINES AT END OF X,Y-CYCLES (1=YES,0=NO)\n"
        "[END OF VXH SECTION]\n"
    )

    mat = np.ascontiguousarray(phantom.material.reshape(-1)).astype(np.int32)
    dens = np.ascontiguousarray(phantom.density.reshape(-1)).astype(np.float64)

    # Analytic phantoms use a handful of distinct (material, density) pairs, so
    # rendering each unique pair once and indexing into that table is ~100x
    # faster than formatting several million lines individually.  Patient
    # phantoms have a continuous density spectrum and fall back to np.savetxt.
    pairs, inverse = np.unique(np.stack([mat.astype(np.float64), dens], axis=1), axis=0,
                               return_inverse=True)
    opener = gzip.open if compress else open
    if pairs.shape[0] <= 4096:
        table = np.array([f"{int(m)} {d:.6g}" for m, d in pairs], dtype=object)
        body = "\n".join(table[inverse].tolist()) + "\n"
        with opener(out, "wt", encoding="ascii") as fh:  # type: ignore[operator]
            fh.write(header)
            fh.write(body)
    else:  # pragma: no cover - exercised by the Phase-2 patient phantoms
        with opener(out, "wt", encoding="ascii") as fh:  # type: ignore[operator]
            fh.write(header)
            np.savetxt(fh, np.stack([mat, dens], axis=1), fmt=["%d", "%.6g"])
    return out


def write_input_file(
    path: str | Path,
    *,
    histories_per_projection: float,
    random_seed: int,
    spectrum_file: str,
    source_position_cm: tuple[float, float, float],
    source_direction: tuple[float, float, float],
    polar_aperture_deg: float,
    azimuthal_aperture_deg: float,
    image_file: str,
    image_pixels: tuple[int, int],
    image_size_cm: tuple[float, float],
    sdd_cm: float,
    n_projections: int,
    angle_between_projections_deg: float,
    sad_cm: float,
    translation_per_projection_cm: float,
    dose_file: str,
    voxel_file: str,
    materials: tuple[Material, ...],
    dose_roi: tuple[tuple[int, int], tuple[int, int], tuple[int, int]],
    gpu_threads_per_block: int = 128,
    histories_per_thread: int = 1000,
    tally_material_dose: bool = True,
    tally_voxel_dose: bool = True,
) -> Path:
    """Write an MC-GPU v1.3 ``.in`` file.

    The section header strings are matched literally by the engine's parser
    (vendor/MCGPU/MC-GPU_v1.3.cu:1286-1657) and must not be reworded.

    ``histories_per_projection`` is per projection, not per scan: MC-GPU divides
    the tally by ``total_histories * num_projections``
    (vendor/MCGPU/MC-GPU_v1.3.cu:2993).

    ``dose_roi`` indices are 1-based, as in the sample input files.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    (xr, yr, zr) = dose_roi
    sx, sy, sz = source_position_cm
    ux, uy, uz = source_direction

    lines = [
        "# >>>> INPUT FILE FOR MC-GPU v1.3 >>>>",
        "#   Written by ct_dosemc_core -- do not edit by hand.",
        "",
        "#[SECTION SIMULATION CONFIG v.2009-05-12]",
        f"{histories_per_projection:.6e}   # TOTAL NUMBER OF HISTORIES (PER PROJECTION)",
        f"{int(random_seed)}   # RANDOM SEED (ranecu PRNG)",
        "0   # GPU NUMBER TO USE WHEN MPI IS NOT USED",
        f"{int(gpu_threads_per_block)}   # GPU THREADS PER CUDA BLOCK (multiple of 32)",
        f"{int(histories_per_thread)}   # SIMULATED HISTORIES PER GPU THREAD",
        "",
        "#[SECTION SOURCE v.2011-07-12]",
        f"{spectrum_file}   # X-RAY ENERGY SPECTRUM FILE",
        f"{sx:.6f} {sy:.6f} {sz:.6f}   # SOURCE POSITION: X Y Z [cm]",
        f"{ux:.6f} {uy:.6f} {uz:.6f}   # SOURCE DIRECTION COSINES: U V W",
        # ORDER MATTERS AND IS NOT WHAT THE UPSTREAM SAMPLE FILES SAY.  Their
        # comment reads "POLAR AND AZIMUTHAL APERTURES", but the parser is
        #     sscanf(new_line, "%lf %lf", &phi_aperture, &theta_aperture)
        # (MC-GPU_v1.3.cu:1353), i.e. AZIMUTHAL first, POLAR second.  Getting this
        # backwards produces a beam collimated across the fan and wide open along
        # Z -- which still runs, still looks like a CT scan, and is wrong.
        f"{azimuthal_aperture_deg:.6f} {polar_aperture_deg:.6f}   "
        "# AZIMUTHAL (fan) AND POLAR (Z collimation) APERTURES [degrees]",
        "",
        "#[SECTION IMAGE DETECTOR v.2009-12-02]",
        f"{image_file}   # OUTPUT IMAGE FILE NAME",
        f"{int(image_pixels[0])} {int(image_pixels[1])}   # NUMBER OF PIXELS IN THE IMAGE: Nx Nz",
        f"{image_size_cm[0]:.6f} {image_size_cm[1]:.6f}   # IMAGE SIZE (width, height): Dx Dz [cm]",
        f"{sdd_cm:.6f}   # SOURCE-TO-DETECTOR DISTANCE",
        "",
        "#[SECTION CT SCAN TRAJECTORY v.2011-10-25]",
        f"{int(n_projections)}   # NUMBER OF PROJECTIONS",
        f"{angle_between_projections_deg:.8f}   # ANGLE BETWEEN PROJECTIONS [degrees]",
        "0.0 5000.0   # ANGLES OF INTEREST",
        f"{sad_cm:.6f}   # SOURCE-TO-ROTATION AXIS DISTANCE",
        f"{translation_per_projection_cm:.8f}   # VERTICAL TRANSLATION BETWEEN PROJECTIONS",
        "",
        "#[SECTION DOSE DEPOSITION v.2012-12-12]",
        f"{'YES' if tally_material_dose else 'NO'}   # TALLY MATERIAL DOSE?",
        f"{'YES' if tally_voxel_dose else 'NO'}   # TALLY 3D VOXEL DOSE?",
        f"{dose_file}   # OUTPUT VOXEL DOSE FILE NAME",
        f"{xr[0]} {xr[1]}   # VOXEL DOSE ROI: X-index min max (first voxel has index 1)",
        f"{yr[0]} {yr[1]}   # VOXEL DOSE ROI: Y-index min max",
        f"{zr[0]} {zr[1]}   # VOXEL DOSE ROI: Z-index min max",
        "",
        "#[SECTION VOXELIZED GEOMETRY FILE v.2009-11-30]",
        f"{voxel_file}   # VOXEL GEOMETRY FILE (penEasy 2008 format; .gz accepted)",
        "",
        "#[SECTION MATERIAL FILE LIST v.2009-11-30]",
    ]
    for m in sorted(materials, key=lambda m: m.index):
        lines.append(f"{m.file}   # {m.index}: {m.name}")
    lines += ["", "# >>>> END INPUT FILE >>>>", ""]
    out.write_text("\n".join(lines), encoding="ascii")
    return out


@dataclass
class DoseMap:
    """A 3D dose tally read back from MC-GPU.

    ``dose_ev_per_g`` and ``sigma_ev_per_g`` are per history, indexed ``[z, y, x]``.
    ``sigma`` is one standard deviation: MC-GPU writes the percent relative error
    at 2 sigma, and the conversion happens in :func:`read_dose_map`.
    """

    dose_ev_per_g: np.ndarray
    sigma_ev_per_g: np.ndarray
    roi_origin_zyx: tuple[int, int, int]
    """0-based index of the ROI's first voxel within the full phantom."""

    voxel_size_cm: tuple[float, float, float]

    @property
    def shape_zyx(self) -> tuple[int, int, int]:
        return tuple(int(n) for n in self.dose_ev_per_g.shape)  # type: ignore[return-value]


_ROI_RE = re.compile(
    r"Coordinates of the ROI inside the voxel volume\s*=\s*"
    r"X\[(\d+),(\d+)\],\s*Y\[(\d+),(\d+)\],\s*Z\[(\d+),(\d+)\]"
)
_NVOX_RE = re.compile(r"Number of voxels in the reported region of interest.*?\n#\s+(\d+)\s+(\d+)\s+(\d+)", re.S)
_VOXSIZE_RE = re.compile(r"Voxel size:\s*([0-9.eE+-]+)\s*x\s*([0-9.eE+-]+)\s*x\s*([0-9.eE+-]+)")


def read_dose_map(dose_file: str | Path) -> DoseMap:
    """Read MC-GPU's dose tally.

    The ASCII file named in the input is only a header plus one Z plane; the full
    3D tally lives in ``<dose_file>.raw`` (mean, eV/g per history) and
    ``<dose_file>_PercentRelError2sigma.raw`` (percent relative error at 2 sigma),
    both 32-bit floats with X fastest (vendor/MCGPU/MC-GPU_v1.3.cu:2901-3060).
    The ASCII header carries the ROI extent needed to shape them.
    """
    ascii_path = Path(dose_file)
    raw_path = Path(str(ascii_path) + ".raw")
    err_path = Path(str(ascii_path) + "_PercentRelError2sigma.raw")
    for p in (ascii_path, raw_path, err_path):
        if not p.is_file():
            raise FileNotFoundError(f"MC-GPU dose output missing: {p}")

    head = ascii_path.read_text(encoding="latin-1", errors="replace")[:8000]

    m = _NVOX_RE.search(head)
    if not m:
        raise ValueError(f"could not read the ROI voxel counts from {ascii_path}")
    dx_n, dy_n, dz_n = (int(v) for v in m.groups())

    m = _ROI_RE.search(head)
    if not m:
        raise ValueError(f"could not read the ROI coordinates from {ascii_path}")
    x0, _x1, y0, _y1, z0, _z1 = (int(v) for v in m.groups())

    m = _VOXSIZE_RE.search(head)
    if not m:
        raise ValueError(f"could not read the voxel size from {ascii_path}")
    voxel_size = tuple(float(v) for v in m.groups())

    n = dx_n * dy_n * dz_n
    mean = np.fromfile(raw_path, dtype=np.float32, count=n)
    rel2 = np.fromfile(err_path, dtype=np.float32, count=n)
    if mean.size != n or rel2.size != n:
        raise ValueError(
            f"expected {n} voxels but read {mean.size} / {rel2.size} from the .raw files"
        )

    dose = mean.reshape(dz_n, dy_n, dx_n).astype(np.float64)
    # percent, at 2 sigma -> absolute, at 1 sigma
    sigma = dose * (rel2.reshape(dz_n, dy_n, dx_n).astype(np.float64) / 100.0) / 2.0

    return DoseMap(
        dose_ev_per_g=dose,
        sigma_ev_per_g=sigma,
        roi_origin_zyx=(z0 - 1, y0 - 1, x0 - 1),  # header is 1-based
        voxel_size_cm=voxel_size,  # type: ignore[arg-type]
    )


@dataclass
class McgpuRun:
    """The record of one engine invocation."""

    executable: Path
    input_file: Path
    log_file: Path
    returncode: int
    wall_seconds: float
    total_histories: float
    """Histories per projection x projections -- the divisor MC-GPU used."""

    def check(self) -> None:
        if self.returncode != 0:
            tail = self.log_file.read_text(encoding="latin-1", errors="replace")[-3000:]
            raise RuntimeError(
                f"MC-GPU exited with {self.returncode}. Last output:\n{tail}"
            )

    def echoed_apertures_deg(self) -> tuple[float, float]:
        """(azimuthal, polar) as the engine itself understood them, from its log.

        MC-GPU echoes what it parsed (``MC-GPU_v1.3.cu:509``).  Reading it back is
        the only way to be sure the input file was interpreted the way the caller
        meant -- the aperture line's documented order and its actual order differ.
        """
        text = self.log_file.read_text(encoding="latin-1", errors="replace")
        m = re.search(
            r"azimuthal \(phi\), polar apertures\s*=\s*([0-9.eE+-]+)\s*,\s*([0-9.eE+-]+)", text
        )
        if not m:
            raise ValueError(f"no aperture line in {self.log_file}")
        return float(m.group(1)), float(m.group(2))

    def assert_apertures(
        self, azimuthal_deg: float, polar_deg: float, *, rtol: float = 1e-4
    ) -> None:
        """Fail loudly if the engine did not use the beam we asked for."""
        got_phi, got_theta = self.echoed_apertures_deg()
        for want, got, what in (
            (azimuthal_deg, got_phi, "azimuthal (fan)"),
            (polar_deg, got_theta, "polar (Z collimation)"),
        ):
            if abs(got - want) > rtol * max(abs(want), 1e-12):
                raise RuntimeError(
                    f"MC-GPU used a {what} aperture of {got:.6f} deg but "
                    f"{want:.6f} deg was requested -- check the aperture line order "
                    f"in the input file ({self.input_file})."
                )


def run_mcgpu(
    executable: str | Path,
    input_file: str | Path,
    *,
    workdir: str | Path | None = None,
    log_file: str | Path | None = None,
    total_histories: float = 0.0,
    timeout_s: float | None = None,
) -> McgpuRun:
    """Run MC-GPU on ``input_file``, capturing stdout to ``log_file``.

    The engine resolves every path in the input file relative to its working
    directory, so ``workdir`` defaults to the directory holding the input file.
    """
    exe = Path(executable).resolve()
    if not exe.is_file():
        raise FileNotFoundError(
            f"MC-GPU executable not found: {exe}. Build it with tools/build_mcgpu.ps1."
        )
    inp = Path(input_file).resolve()
    cwd = Path(workdir).resolve() if workdir else inp.parent
    log = Path(log_file) if log_file else inp.with_suffix(".out")
    log.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    with log.open("w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.run(
            [str(exe), inp.name if inp.parent == cwd else str(inp)],
            cwd=str(cwd),
            stdout=fh,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
            check=False,
        )
    elapsed = time.perf_counter() - started

    return McgpuRun(
        executable=exe,
        input_file=inp,
        log_file=log,
        returncode=proc.returncode,
        wall_seconds=elapsed,
        total_histories=float(total_histories),
    )


def stage_material_files(
    materials: tuple[Material, ...], source_dir: str | Path, dest_dir: str | Path
) -> tuple[Material, ...]:
    """Copy the material files next to the simulation and return rebased entries.

    MC-GPU opens material files relative to its working directory; keeping a copy
    in the run directory makes each simulation self-describing and lets the
    provenance record hash exactly the file that was used.
    """
    src = Path(source_dir)
    dst = Path(dest_dir)
    dst.mkdir(parents=True, exist_ok=True)
    staged = []
    for m in materials:
        name = Path(m.file).name
        target = dst / name
        if not target.exists():
            origin = src / name
            if not origin.is_file():
                raise FileNotFoundError(
                    f"material file {origin} not found; run tools/make_materials.py"
                )
            shutil.copy2(origin, target)
        staged.append(Material(m.index, m.name, name, m.nominal_density_g_cm3))
    return tuple(staged)

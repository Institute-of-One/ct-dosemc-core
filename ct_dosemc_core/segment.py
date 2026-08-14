"""Organ segmentation, in a separate process, in a geometry we control.

Two decisions are worth stating, because both are about not guessing.

**The process boundary.** TotalSegmentator is launched as a child process
(:mod:`ct_dosemc_core._ts_worker`) and never imported here. nnU-Net spawns its own
workers, and spawning those from a long-lived parent leaks runaway processes on Windows.
A child that exits when it is done cannot.

Ported from ctsegdose-core (IORN-006) so IORN-007 stands on its own. The masks it
produces are the anatomy input to the Monte-Carlo dose calculation, so the one thing
that must not slip -- that a mask comes back on the same voxel grid as the CT it was
run on -- is factored into :func:`assert_voxel_correspondence` and pinned by a test.

**The geometry.** The series is written to NIfTI *by this module*, with an affine built
from the DICOM patient coordinates, and the masks come back on that same grid. So the
mapping from mask voxel to image voxel is the identity by construction, and it is
asserted rather than assumed — a mask that came back on a different grid is an error,
not something to be fixed with a transpose and a flip. Getting this wrong would silently
mirror left and right kidney, or reverse z and weight each organ by the tube current of
the opposite end of the patient.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

#: The dose-relevant abdominal organs this work reports. Restricting inference to a
#: subset is much faster than segmenting all 100+ structures, and these are the organs
#: for which CTDIvol-normalised dose coefficients are published.
ABDOMINAL_ORGANS: tuple[str, ...] = (
    "liver",
    "spleen",
    "kidney_left",
    "kidney_right",
    "pancreas",
    "stomach",
    "gallbladder",
    "adrenal_gland_left",
    "adrenal_gland_right",
    "small_bowel",
    "colon",
    "urinary_bladder",
)

#: The patient outline, which the water-equivalent diameter -- and therefore the size
#: correction -- is measured from. It is *not* part of TotalSegmentator's ``total`` task;
#: it belongs to a separate ``body`` task. Rather than pay for a second inference pass,
#: the outline is taken from ctdose-core's deterministic threshold contour
#: (:mod:`ctdose_core.segmentation`), which is the AAPM TG-220 construction, is
#: reproducible across platforms, and needs no model weights. Set ``include_body`` to
#: request it from the segmenter instead, where a ``body`` run is available.
BODY_STRUCTURE = "body"


class SegmentationUnavailable(RuntimeError):
    """TotalSegmentator could not be run."""


@dataclass
class SegmentationRun:
    """What one segmentation produced, and under what conditions."""

    mask_dir: Path
    structures: list[str] = field(default_factory=list)
    task: str = "total"
    fast: bool = True
    roi_subset: list[str] = field(default_factory=list)
    device: str = ""
    python_executable: str = ""
    totalsegmentator_version: str = ""
    torch_version: str = ""
    elapsed_s: float = 0.0
    volume_shape: tuple[int, int, int] = (0, 0, 0)
    voxel_spacing_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    input_fingerprint: str = ""
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mask_dir": str(self.mask_dir),
            "structures": list(self.structures),
            "task": self.task,
            "fast": self.fast,
            "roi_subset": list(self.roi_subset),
            "device": self.device,
            "python_executable": self.python_executable,
            "totalsegmentator_version": self.totalsegmentator_version,
            "torch_version": self.torch_version,
            "elapsed_s": round(self.elapsed_s, 1),
            "volume_shape_zyx": list(self.volume_shape),
            "voxel_spacing_mm_zyx": [round(v, 4) for v in self.voxel_spacing_mm],
            "input_fingerprint": self.input_fingerprint,
            "cached": self.cached,
            "licence": "TotalSegmentator, Apache-2.0, inference only; no weights redistributed",
            "process": "separate child process (python -m ct_dosemc_core._ts_worker)",
        }


# --- geometry ---------------------------------------------------------------------------


def dicom_affine(
    orientation: tuple[float, ...],
    origin: tuple[float, float, float],
    pixel_spacing_mm: tuple[float, float],
    slice_direction: tuple[float, float, float],
    slice_spacing_mm: float,
) -> np.ndarray:
    """NIfTI (RAS) affine for a volume indexed ``[column, row, slice]``.

    DICOM patient coordinates are LPS and NIfTI's are RAS, so the first two axes change
    sign. ``orientation`` is Image Orientation (Patient) (0020,0037): the first three
    cosines point along increasing column index, the second three along increasing row
    index. ``slice_direction`` comes from the measured step between consecutive Image
    Position (Patient) values rather than from the cross product, so a series acquired
    feet-first or reconstructed in descending order keeps its true handedness.
    """
    col_dir = np.asarray(orientation[:3], dtype=float)
    row_dir = np.asarray(orientation[3:6], dtype=float)
    slc_dir = np.asarray(slice_direction, dtype=float)
    di, dj = float(pixel_spacing_mm[1]), float(pixel_spacing_mm[0])

    affine = np.eye(4)
    affine[:3, 0] = col_dir * di
    affine[:3, 1] = row_dir * dj
    affine[:3, 2] = slc_dir * float(slice_spacing_mm)
    affine[:3, 3] = np.asarray(origin, dtype=float)
    lps_to_ras = np.diag([-1.0, -1.0, 1.0, 1.0])
    return lps_to_ras @ affine


def write_nifti(
    volume_hu: np.ndarray, affine: np.ndarray, path: Path | str
) -> Path:
    """Write a ``(z, y, x)`` Hounsfield volume as NIfTI indexed ``(x, y, z)``."""
    import nibabel as nib

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.transpose(np.asarray(volume_hu, dtype=np.float32), (2, 1, 0))
    img = nib.Nifti1Image(data, affine)
    img.header.set_xyzt_units("mm")
    nib.save(img, str(path))
    return path


def assert_voxel_correspondence(
    mask_shape: tuple[int, ...],
    expected_shape: tuple[int, ...],
    *,
    name: str = "",
) -> None:
    """Fail unless a mask sits on exactly the CT's ``(z, y, x)`` voxel grid.

    This is the identity the whole geometry relies on: the series is written to NIfTI
    with an affine built from its DICOM patient coordinates, TotalSegmentator returns
    masks on that same grid, and so mask voxel *is* image voxel with no transform. If
    the segmenter resampled -- to its own 1.5 mm isotropic grid, say -- the shapes
    differ and the correspondence is gone. For a Monte-Carlo organ dose that would
    assign every organ the density and the deposited energy of the wrong voxels, so it
    must stop the series rather than be reconciled with a transpose or a resample.

    Pure and dependency-free (no nibabel), so the invariant is tested directly.
    """
    if tuple(mask_shape) != tuple(expected_shape):
        prefix = f"{name}: " if name else ""
        raise SegmentationUnavailable(
            f"{prefix}mask grid {tuple(mask_shape)} does not match the image grid "
            f"{tuple(expected_shape)}; voxel correspondence cannot be assumed"
        )


def load_mask(path: Path | str, expected_shape: tuple[int, int, int]) -> np.ndarray:
    """Load one mask back onto the image grid, shaped ``(z, y, x)``.

    Raises if the grid differs. The masks were produced from a volume this module wrote,
    so a shape mismatch means the segmenter resampled and the voxel correspondence is
    no longer the identity — which must stop the run rather than be papered over.
    """
    import nibabel as nib

    data = np.asarray(nib.load(str(path)).dataobj)
    mask = np.transpose(data > 0, (2, 1, 0))
    assert_voxel_correspondence(mask.shape, expected_shape, name=Path(path).name)
    return mask


# --- running it -------------------------------------------------------------------------


def _versions(python_executable: str) -> tuple[str, str]:
    """Ask the interpreter that will run inference what it has.

    The parent process may be a different interpreter entirely -- CPU-only torch in the
    analysis environment, CUDA torch in the inference one -- so asking the parent would
    record the wrong thing in the provenance of every mask.
    """
    probe = (
        "import json\n"
        "d={}\n"
        "try:\n"
        " from importlib.metadata import version; d['ts']=version('TotalSegmentator')\n"
        "except Exception: pass\n"
        "try:\n"
        " import torch\n"
        " d['torch']=f\"{torch.__version__} (cuda={torch.cuda.is_available()})\"\n"
        " d['gpu']=torch.cuda.get_device_name(0) if torch.cuda.is_available() else ''\n"
        "except Exception: pass\n"
        "print(json.dumps(d))"
    )
    try:  # pragma: no cover - depends on the optional extra
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [python_executable, "-c", probe], capture_output=True, text=True, timeout=300
        )
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        torch_version = payload.get("torch", "")
        if payload.get("gpu"):
            torch_version += f" on {payload['gpu']}"
        return payload.get("ts", ""), torch_version
    except Exception:
        return "", ""


def segment_volume(
    volume_hu: np.ndarray,
    affine: np.ndarray,
    work_dir: Path | str,
    *,
    voxel_spacing_mm: tuple[float, float, float] = (0.0, 0.0, 0.0),
    organs: tuple[str, ...] = ABDOMINAL_ORGANS,
    include_body: bool = False,
    fast: bool = True,
    task: str = "total",
    device: str = "",
    python_executable: str = "",
    timeout_s: float = 7200.0,
    reuse: bool = True,
) -> SegmentationRun:
    """Segment one volume, reusing a previous run when its masks are already present.

    The volume is written to NIfTI, a child process runs inference, and the masks are
    read back on the same grid. ``reuse`` makes a repeated run free, which matters when
    a forty-series batch is interrupted.
    """
    work_dir = Path(work_dir)
    mask_dir = work_dir / "masks"
    wanted = list(organs) + ([BODY_STRUCTURE] if include_body else [])
    shape = tuple(int(n) for n in volume_hu.shape)
    interpreter = python_executable or sys.executable
    stamp = fingerprint(volume_hu, affine)

    if reuse and mask_dir.is_dir():
        present = sorted(p.name.removesuffix(".nii.gz") for p in mask_dir.glob("*.nii.gz"))
        meta = _read_meta(work_dir)
        stale = meta.get("input_fingerprint", "") != stamp
        if present and all(name in present for name in wanted) and not stale:
            return SegmentationRun(
                mask_dir=mask_dir,
                structures=present,
                task=task,
                fast=fast,
                roi_subset=wanted,
                device=device,
                python_executable=meta.get("python_executable", interpreter),
                totalsegmentator_version=meta.get("totalsegmentator_version", ""),
                torch_version=meta.get("torch_version", ""),
                elapsed_s=float(meta.get("elapsed_s", 0.0)),
                volume_shape=shape,
                voxel_spacing_mm=voxel_spacing_mm,
                input_fingerprint=stamp,
                cached=True,
            )

    work_dir.mkdir(parents=True, exist_ok=True)
    nifti = write_nifti(volume_hu, affine, work_dir / "image.nii.gz")

    cmd = [
        interpreter, "-m", "ct_dosemc_core._ts_worker",
        str(nifti), str(mask_dir),
        "--task", task,
        "--roi-subset", ",".join(wanted),
    ]
    if fast:
        cmd.append("--fast")
    if device:
        cmd += ["--device", device]

    started = time.monotonic()
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        cmd, capture_output=True, text=True, timeout=timeout_s,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    elapsed = time.monotonic() - started
    (work_dir / "segmentation.log").write_text(
        f"$ {' '.join(cmd)}\n\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}\n",
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise SegmentationUnavailable(
            f"TotalSegmentator exited {proc.returncode}; see {work_dir / 'segmentation.log'}"
        )

    structures = sorted(p.name.removesuffix(".nii.gz") for p in mask_dir.glob("*.nii.gz"))
    if not structures:
        raise SegmentationUnavailable(f"no masks written to {mask_dir}")

    version, torch_version = _versions(interpreter)
    run = SegmentationRun(
        mask_dir=mask_dir,
        structures=structures,
        task=task,
        fast=fast,
        roi_subset=wanted,
        device=device,
        python_executable=interpreter,
        totalsegmentator_version=version,
        torch_version=torch_version,
        elapsed_s=elapsed,
        volume_shape=shape,
        voxel_spacing_mm=voxel_spacing_mm,
        input_fingerprint=stamp,
    )
    (work_dir / "segmentation.json").write_text(
        json.dumps(run.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    # The image copy is only an input to inference; the masks are the product.
    nifti.unlink(missing_ok=True)
    return run


def fingerprint(volume_hu: np.ndarray, affine: np.ndarray) -> str:
    """A cheap identity for the volume inference was run on.

    Masks are cached so an interrupted batch resumes for free, but "the mask files
    exist" is not the same as "they belong to *this* volume". If the slice order or the
    geometry changes -- as it did when the head-first series were canonicalised -- the
    cached masks are still valid files describing a volume that no longer exists, and
    reusing them mirrors every organ along z without any error. Comparing a fingerprint
    turns that from a silent corruption into a cache miss.
    """
    digest = hashlib.sha256()
    digest.update(np.asarray(volume_hu.shape, dtype=np.int64).tobytes())
    digest.update(np.round(np.asarray(affine, dtype=float), 4).tobytes())
    arr = np.asarray(volume_hu, dtype=np.float64)
    stats = np.array(
        [arr[0].mean(), arr[-1].mean(), arr.mean(), arr.std()], dtype=np.float64
    )
    digest.update(np.round(stats, 4).tobytes())
    return digest.hexdigest()[:32]


def _read_meta(work_dir: Path) -> dict[str, Any]:
    path = work_dir / "segmentation.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_masks(run: SegmentationRun, names: list[str] | None = None) -> dict[str, np.ndarray]:
    """Load the requested masks from a completed run, on the image grid."""
    out: dict[str, np.ndarray] = {}
    for name in names or run.structures:
        path = run.mask_dir / f"{name}.nii.gz"
        if path.exists():
            out[name] = load_mask(path, run.volume_shape)
    return out


def totalsegmentator_available(python_executable: str = "") -> bool:
    """Whether the interpreter that would run inference can import TotalSegmentator."""
    interpreter = python_executable or sys.executable
    if shutil.which(interpreter) is None and not Path(interpreter).exists():  # pragma: no cover
        return False
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [interpreter, "-c", "import totalsegmentator"], capture_output=True, timeout=300
        )
    except Exception:
        return False
    return proc.returncode == 0

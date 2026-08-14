"""The slice grid a series actually sits on, which is not always the one it claims.

Organ *mass* is voxel count times voxel volume times density, so the slice spacing is a
direct multiplier on every mass this project reports. Taking it as
``(z_last - z_first) / (n_slices - 1)`` is wrong whenever the file count is not the
position count, and public archives supply that case routinely:

* **duplicate positions** — the same z appearing more than once, which a PET/CT series
  or a re-sent study produces. The naive spacing is then too small *and* the stacked
  volume repeats anatomy, so an organ occupies more slices than it physically does. Both
  errors inflate organ volume, and they do it silently: the masks look right, the
  Hounsfield values look right, and only the numbers are wrong.
* **gaps** — a missing instance, or two acquisitions with different spacing concatenated
  into one series. A single affine cannot describe that volume at all.

So the grid is resolved explicitly: one slice per position, spacing from the median step
between neighbouring positions, and a uniformity check that fails loudly rather than
handing a wrong multiplier to everything downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: A step may differ from the median by this fraction before the grid is called
#: non-uniform. Reconstruction rounds positions to 0.01 mm, so a few tenths of a percent
#: is normal; a missing slice is a 100% deviation and must not pass.
UNIFORMITY_TOLERANCE = 0.02


class NonUniformGrid(ValueError):
    """The slices do not lie on a single regular grid, so one affine cannot describe them."""


@dataclass
class SliceGrid:
    """Which slices to use, and the spacing they sit on."""

    keep: list[int]
    spacing_mm: float
    n_input: int
    n_duplicates: int
    max_step_deviation: float
    warnings: list[str] = field(default_factory=list)

    @property
    def deduplicated(self) -> bool:
        return self.n_duplicates > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_input_slices": self.n_input,
            "n_slices_used": len(self.keep),
            "n_duplicate_positions_dropped": self.n_duplicates,
            "slice_spacing_mm": round(self.spacing_mm, 4),
            "max_step_deviation": round(self.max_step_deviation, 4),
            "uniformity_tolerance": UNIFORMITY_TOLERANCE,
            "warnings": list(self.warnings),
        }


def resolve_grid(
    z_positions: np.ndarray | list[float],
    *,
    tolerance: float = UNIFORMITY_TOLERANCE,
    fallback_spacing_mm: float | None = None,
) -> SliceGrid:
    """Resolve the usable slice grid from the longitudinal positions of a series.

    Args:
        z_positions: one per image, in file order.
        fallback_spacing_mm: used only when a single slice makes the step undefined.

    Returns:
        The indices to keep — one per distinct position, ordered from the most inferior
        to the most superior — with the spacing they sit on.

    Raises:
        NonUniformGrid: when the surviving positions are not evenly spaced, or when
            every slice reports the same position (a de-identification artefact seen in
            public archives, which makes the z axis unrecoverable rather than imprecise).
    """
    z = np.asarray(z_positions, dtype=float)
    if z.size == 0:
        raise NonUniformGrid("the series carries no slice positions")
    warnings: list[str] = []

    # One slice per position, keeping the first occurrence, ordered along +z.
    order = np.argsort(z, kind="stable")
    keep: list[int] = []
    seen: set[float] = set()
    for idx in order:
        key = round(float(z[idx]), 3)
        if key in seen:
            continue
        seen.add(key)
        keep.append(int(idx))

    n_duplicates = int(z.size - len(keep))
    if n_duplicates:
        warnings.append(
            f"{n_duplicates} of {z.size} images repeat a slice position; one image per "
            "position is used, because stacking duplicates repeats anatomy and inflates "
            "every organ volume derived from the stack"
        )

    if len(keep) == 1:
        if n_duplicates:
            # Seen in public archives: de-identification flattens the z coordinate, so
            # every slice reports one position. The images are fine; the axis is gone.
            raise NonUniformGrid(
                f"all {z.size} images report the same longitudinal position "
                f"({z[keep[0]]:g} mm); the axis is unrecoverable rather than imprecise, "
                "so no volume, no organ extent and no I(z) weighting can be built"
            )
        if fallback_spacing_mm and fallback_spacing_mm > 0:
            warnings.append("single slice; spacing taken from Slice Thickness (0018,0050)")
            return SliceGrid([keep[0]], float(fallback_spacing_mm), int(z.size), n_duplicates, 0.0, warnings)
        raise NonUniformGrid("a single slice position gives no spacing and no volume")

    steps = np.diff(z[keep])
    median = float(np.median(steps))
    if median <= 0:
        raise NonUniformGrid(
            f"all {z.size} images report the same or a non-increasing position; the "
            "longitudinal axis is unrecoverable and no volume can be built from it"
        )
    deviation = float(np.max(np.abs(steps - median)) / median)
    if deviation <= tolerance:
        return SliceGrid(keep, median, int(z.size), n_duplicates, deviation, warnings)

    recovered = _largest_uniform_subgrid(z, keep, tolerance=tolerance)
    if recovered is None:
        raise NonUniformGrid(
            f"slice steps vary by {deviation:.1%} around {median:.3f} mm (tolerance "
            f"{tolerance:.0%}) and no regular sub-grid covers enough of the series; it "
            "has a gap, or two acquisitions were concatenated. A single affine cannot "
            "describe it."
        )
    sub_keep, sub_spacing, sub_deviation = recovered
    warnings.append(
        f"slice steps varied by {deviation:.1%} around {median:.3f} mm, which is two "
        f"reconstructions interleaved in one series rather than one volume; the largest "
        f"regular sub-grid was taken instead — {len(sub_keep)} of {len(keep)} positions "
        f"at {sub_spacing:.3f} mm"
    )
    return SliceGrid(sub_keep, sub_spacing, int(z.size), n_duplicates, sub_deviation, warnings)


def _largest_uniform_subgrid(
    z: np.ndarray, keep: list[int], *, tolerance: float, min_span_coverage: float = 0.9
) -> tuple[list[int], float, float] | None:
    """The longest run of positions at a constant step, when the whole is not regular.

    Public archives publish series that are two reconstructions of one acquisition
    interleaved under a single Series Instance UID -- a 2.5 mm set and a second 2.5 mm
    set offset by 0.75 mm, which reads as steps of 0.75, 1.75, 2.5 repeating. That is
    not a corrupt series and it is not one volume; it is two volumes sharing a UID, and
    taking either one of them recovers a usable acquisition.

    Acceptance is by **span**, not by count: the sub-grid must cover at least
    ``min_span_coverage`` of the original longitudinal extent. That is what separates the
    two cases. Taking one of two interleaved reconstructions keeps the full extent and
    halves the count; dropping everything after a gap keeps the count and loses the
    extent. Only the first is a recovery, and only the first is accepted.
    """
    positions = z[keep]
    steps = np.diff(positions)
    if steps.size == 0:
        return None
    full_span = float(positions[-1] - positions[0])
    if full_span <= 0:
        return None

    best: tuple[list[int], float, float] | None = None
    # Candidate steps: the distinct observed steps and their consecutive sums, which is
    # what an interleaved pair produces (0.75 and 1.75 sum to the true 2.5 mm pitch).
    candidates = {round(float(s), 3) for s in steps}
    candidates |= {
        round(float(a + b), 3) for a, b in zip(steps[:-1], steps[1:], strict=False)
    }
    for step in sorted(c for c in candidates if c > 0):
        for start in range(len(positions)):
            run = [start]
            expected = positions[start] + step
            for i in range(start + 1, len(positions)):
                if abs(positions[i] - expected) <= tolerance * step:
                    run.append(i)
                    expected = positions[i] + step
            if len(run) < 2:
                continue
            actual = np.diff(positions[run])
            spacing = float(np.median(actual))
            deviation = float(np.max(np.abs(actual - spacing)) / spacing)
            if deviation > tolerance:
                continue
            span = float(positions[run[-1]] - positions[run[0]])
            if span < min_span_coverage * full_span:
                continue
            if best is None or len(run) > len(best[0]):
                best = ([keep[i] for i in run], spacing, deviation)

    return best

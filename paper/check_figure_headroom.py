"""Every uploaded figure must leave the top band of its page empty.

    python paper/check_figure_headroom.py

Adapted from ctp-core/paper/check_figure_headroom.py, where the defect it exists
for was found: the portal builds the PDF a reviewer reads by taking each
uploaded figure file as a page of its own and stamping its own label across the
top left. It does not move the artwork down, and there is no setting that
changes this. In the first PDF one portal built, the stamp was printed across
the panel titles of figures 1, 2 and 3, and that reached the approval screen.

The band is measured from the file that is actually uploaded, not from the
figure object that drew it and not from the reviewed copy in paper/figures/.
Those are three different files, and only one of them is sent anywhere.

paper/test_figure_headroom.py injects a figure cropped the old way and requires
this to report it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PAPER = Path(__file__).resolve().parent
UPLOADED = PAPER / "build" / "figures"

#: Inches of blank page that must sit above the topmost ink. make_submission_
#: figures.py reserves 0.5 in; this is the smaller number a file has to clear,
#: so that a rounding difference between renderers is not reported as a defect.
REQUIRED_INCHES = 0.40

#: Anything darker than this, on a 0-255 grey scale, counts as ink. Pure white
#: is 255 and antialiasing puts the faintest edge pixels in the low 250s.
INK = 250


def _top_of_ink(image) -> int | None:
    """The first row from the top holding any ink, or None if the page is blank."""
    import numpy as np

    inked = (np.asarray(image) < INK).any(axis=1)
    where = np.flatnonzero(inked)
    return int(where[0]) if where.size else None


def blank_band_inches(path: Path) -> float:
    """Inches of blank page above the topmost ink.

    A page with no ink at all returns its full height: that is a different
    defect, and the person looking at the figures will not miss it.
    """
    from PIL import Image

    opened = Image.open(path)
    dpi = opened.info.get("dpi")
    if not dpi:
        raise ValueError(
            f"{path.name} carries no dpi; its size in inches is unknown and the band "
            f"cannot be measured"
        )
    image = opened.convert("L")
    top = _top_of_ink(image)
    return (image.height if top is None else top) / float(dpi[1])


def check(paths: list[Path]) -> list[str]:
    problems = []
    for path in paths:
        if not path.is_file():
            problems.append(f"{path.name} is missing")
            continue
        band = blank_band_inches(path)
        mark = "ok  " if band >= REQUIRED_INCHES else "FAIL"
        print(f"  {mark} {path.name}: {band:.2f} in blank above the artwork "
              f"({band * 72:.0f} pt)")
        if band < REQUIRED_INCHES:
            problems.append(
                f"{path.name} leaves only {band:.2f} in ({band * 72:.0f} pt) above the "
                f"artwork; the portal stamps its figure label there and needs "
                f"{REQUIRED_INCHES:.2f} in"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path)
    args = parser.parse_args(argv)

    paths = args.files or sorted(UPLOADED.glob("Figure_*.png"))
    if not paths:
        print(f"no uploaded figures in {UPLOADED}; "
              f"run paper/make_submission_figures.py first")
        return 1

    print(f"headroom for the portal's figure label ({REQUIRED_INCHES:.2f} in required):")
    problems = check(paths)
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"\nall {len(paths)} uploaded figures leave the band empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

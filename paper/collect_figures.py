"""Gather every figure the manuscript places, and the caption that goes with it.

    python paper/collect_figures.py
    python paper/collect_figures.py --check

Figures 1-4 and 6 are drawn by ``paper/make_figures.py`` from ``paper/frozen/``.
Figures 5 and 7 fall out of the production pipeline and live under ``results/``;
they are copied here so that every image the manuscript places sits in one
directory and can be shipped as one set.

A source file never carries a figure number: the number belongs to the
manuscript, and this table is the only place it is decided. The frozen result
files are the exception and keep the names they were written under --
``figure4_doses.json`` feeds what is now Figure 5 -- because renaming them
would break the freeze manifest and every number already traced through it.

Captions are read from the table in ``paper/README.md`` and are written there once.
A caption that also exists as image alt text prints twice in the converted
document, in two wordings, which is how a companion paper shipped every figure
described twice.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

PAPER = Path(__file__).resolve().parent
REPO = PAPER.parent
FIGURES = PAPER / "figures"
README = PAPER / "README.md"
RESULTS = REPO / "results"

#: ``number -> (filename in paper/figures/, where it comes from)``. A source of
#: ``None`` means the figure is drawn into paper/figures/ directly by make_figures.
FIGURE_SOURCES: dict[int, tuple[str, str | None]] = {
    1: ("figure1_ladder.png", None),
    2: ("figure2_selection_funnel.png", None),
    3: ("figure3_density_gate.png", None),
    4: ("figure4_tg195_case4.png", None),
    5: ("figure5_scatter.png", "phase2_cohort/index_vs_dose_scatter.png"),
    6: ("figure6_conversion_ceiling.png", None),
    7: ("figure7_vendor.png", "phase2_cohort/vendor_organ_dose.png"),
}

_CAPTION_ROW = re.compile(r"^\|\s*Fig\s*(\d+)\s*\|\s*(.+?)\s*\|\s*$", re.M)


def captions() -> dict[int, str]:
    """The caption table in ``paper/README.md``, as ``number -> text``."""
    if not README.exists():
        return {}
    return {
        int(number): text
        for number, text in _CAPTION_ROW.findall(README.read_text(encoding="utf-8"))
    }


def collect(*, check: bool = False) -> int:
    FIGURES.mkdir(parents=True, exist_ok=True)
    written = captions()
    problems: list[str] = []

    for number, (name, source) in sorted(FIGURE_SOURCES.items()):
        destination = FIGURES / name

        if source is not None:
            origin = RESULTS / source
            if not origin.exists():
                problems.append(
                    f"Figure {number}: {source} has not been produced by the production pipeline"
                )
                continue
            if check:
                if not destination.exists():
                    problems.append(f"Figure {number}: {name} has not been collected")
                elif destination.read_bytes() != origin.read_bytes():
                    problems.append(
                        f"Figure {number}: {name} differs from {source}; "
                        f"run paper/collect_figures.py"
                    )
            else:
                shutil.copy2(origin, destination)
        elif not destination.exists():
            problems.append(
                f"Figure {number}: {name} has not been drawn; run paper/make_figures.py"
            )

        if number not in written:
            problems.append(
                f"Figure {number}: no caption in paper/README.md. A figure without a "
                f"caption cannot be placed, and one written in the manuscript instead "
                f"is a second copy"
            )

    orphaned = sorted(set(written) - set(FIGURE_SOURCES))
    if orphaned:
        problems.append(f"captions in paper/README.md for figures that do not exist: {orphaned}")

    if problems:
        for problem in problems:
            print(f"  {problem}")
        return 1

    verb = "checked" if check else "collected"
    print(f"{verb} {len(FIGURE_SOURCES)} figures, each with a caption")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify rather than copy")
    return collect(check=parser.parse_args(argv).check)


if __name__ == "__main__":
    raise SystemExit(main())

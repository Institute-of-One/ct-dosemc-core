"""Write the figure files the submission system is sent, with room for its stamp.

    python paper/make_submission_figures.py     # -> paper/build/figures/

The submission system takes each uploaded figure as a page of its own and prints
its own label across the top left of that page. It does not move the artwork
down to make room. With a tight crop the artwork starts at the very top, so the
label lands on it: in the first PDF a portal built for a companion manuscript it
was printed across the panel titles of figures 1, 2 and 3, and that reached the
approval screen.

No gate in this repository was looking. The manuscript gates read the .docx, and
the figures are not in the .docx -- they are separate uploads.

The band is added here rather than in ``make_figures.py`` for two reasons. Two
of the six figures are not drawn by that script at all: they are produced by the
production pipeline and copied in, so a change there would not reach them. And
the figures kept in ``paper/figures/`` are the ones the author has looked at and
whose digests are recorded in ``figures_reviewed.json``; padding them in place
would invalidate that record for a change that alters no pixel of the artwork.

So the reviewed figure is the input and the uploaded figure is a derived file,
exactly as the manuscript is derived from its source.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import collect_figures  # noqa: E402

FIGURES = PAPER / "figures"
OUTPUT = PAPER / "build" / "figures"

#: Inches of blank page to leave above the artwork.
#:
#: Measured from a portal's own output: the stamp begins 4 pt below the top of
#: the page and the longest of three wrapped onto a second line and ended 24 pt
#: down, which is 0.33 in. A third line would reach 0.47 in.
STAMP_HEADROOM_INCHES = 0.5

#: What the uploaded file is called. The submission system shows the file name
#: in its list, and "figure5_conversion_ceiling.png" tells an editor nothing that
#: "Figure_5.png" does not.
def uploaded_name(number: int) -> str:
    return f"Figure_{number}.png"


def pad(source: Path, destination: Path, inches: float = STAMP_HEADROOM_INCHES) -> int:
    """Copy ``source`` with white added at the top. Returns the pixels added."""
    from PIL import Image

    image = Image.open(source)
    dpi = image.info.get("dpi")
    if not dpi:
        raise SystemExit(
            f"{source.name} carries no dpi, so the band cannot be sized in inches. "
            f"A figure saved without dpi is a figure whose printed size is unknown."
        )
    added = int(round(float(dpi[1]) * inches))
    padded = Image.new(image.mode, (image.width, image.height + added),
                       "white" if image.mode != "RGBA" else (255, 255, 255, 255))
    padded.paste(image, (0, added))
    destination.parent.mkdir(parents=True, exist_ok=True)
    padded.save(destination, dpi=dpi)
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)

    for old in args.output.glob("Figure_*.png"):
        old.unlink()

    written = []
    for number, (name, _) in sorted(collect_figures.FIGURE_SOURCES.items()):
        source = FIGURES / name
        if not source.is_file():
            print(f"{source} is missing; run paper/collect_figures.py")
            return 1
        destination = args.output / uploaded_name(number)
        added = pad(source, destination)
        print(f"  {destination.name}  <- {name}  (+{added} px of headroom)")
        written.append(destination)

    print(f"\nwrote {len(written)} figure files to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

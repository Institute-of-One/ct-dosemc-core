"""Rebuild every submission artefact in dependency order, then check them.

    python paper/build_all.py

The artefacts depend on each other: the frozen results feed the figures and the
manuscript, the manuscript feeds the Word file, and the checks read all of it.
Rebuilding one and forgetting another is how a copy goes stale, and every copy in
this programme has gone stale at least once -- a cover letter that kept a withdrawn
claim, a submission form three weeks behind the abstract, a kit naming a title the
paper no longer had.

Running the steps by hand in the right order is a thing to get wrong. This is the
order.

The manuscript steps are skipped while ``paper/manuscript.md`` does not exist, and
the check at the end says so rather than reporting success over a gap.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PAPER = Path(__file__).resolve().parent
REPO = PAPER.parent
SOURCE = PAPER / "manuscript.md"

#: (description, command, needs the manuscript prose)
STEPS: tuple[tuple[str, list[str], bool], ...] = (
    ("freeze the results the paper cites", ["paper/freeze.py"], False),
    ("draw figures 1-3", ["paper/make_figures.py"], False),
    ("collect every figure and its caption", ["paper/collect_figures.py"], False),
    # The reference list is an artefact like any other: it is generated from the
    # metadata registered at doi.org, and without a step here it is whatever was
    # resolved by hand last. --check rather than a rewrite, so that a silent
    # change in a registered record stops the build instead of being absorbed
    # into it.
    ("check every reference still resolves", ["paper/references.py", "--check"], True),
    ("resolve the manuscript's numbers and citations", ["paper/build_manuscript.py"], True),
    ("measure against the journal's limits", ["paper/check_rpt_limits.py"], True),
    ("render the manuscript to Word", ["paper/build_docx.py"], True),
    # The PDF is the file the portal receives, so it is an artefact and needs a step. It did
    # not have one, and the PDF sitting in paper/build/ was six weeks older than the .docx
    # beside it when this was noticed.
    ("render the Word file to the submission PDF", ["paper/render_pdf.py"], True),
    # The figures are separate uploads and are in none of the files above, so
    # without these two steps nothing in this repository ever looks at the
    # artwork the reviewer is actually sent.
    ("write the figure files the portal is sent", ["paper/make_submission_figures.py"], False),
    ("check the portal's stamp will not land on a figure",
     ["paper/check_figure_headroom.py"], False),
    ("check everything", ["paper/presubmission_check.py", "--strict"], False),
)


def main(argv: list[str] | None = None) -> int:
    have_prose = SOURCE.exists()
    if not have_prose:
        print(f"note: {SOURCE.name} does not exist yet; its steps are skipped\n")

    for description, command, needs_prose in STEPS:
        if needs_prose and not have_prose:
            print(f"\n=== {description}  [skipped: no manuscript]")
            continue
        print(f"\n=== {description}")
        result = subprocess.run([sys.executable, *command], cwd=REPO, check=False, text=True)
        if result.returncode != 0:
            print(f"\nstopped at: {description}")
            return result.returncode

    if not have_prose:
        print("\nevidence and figures rebuilt; the manuscript is not written")
        return 0
    print("\nevery artefact rebuilt and checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

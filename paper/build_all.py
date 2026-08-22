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
    ("resolve the manuscript's numbers", ["paper/build_manuscript.py"], True),
    ("render the manuscript to Word", ["paper/build_docx.py"], True),
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
        result = subprocess.run(
            [sys.executable, *command], cwd=REPO, check=False, text=True
        )
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

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

import os
import subprocess
import sys
from pathlib import Path

PAPER = Path(__file__).resolve().parent
REPO = PAPER.parent
SOURCE = PAPER / "manuscript.md"

#: (description, command, needs the manuscript prose)
#: Steps that drive Word through COM. They cannot run anywhere but Windows, and
#: a Linux runner must say so rather than either failing (which reports a defect
#: that does not exist) or passing (which reports a check that did not happen).
#: Everything downstream of the PDF is here too: the page images are made from
#: it, and a page ledger with no pages to compare is not a comparison.
WINDOWS_ONLY = frozenset(
    {
        "render the Word file to the submission PDF",
        "check every page is as it was when it was looked at",
    }
)

STEPS: tuple[tuple[str, list[str], bool], ...] = (
    ("freeze the results the paper cites", ["paper/freeze.py"], False),
    ("draw figures 1-4 and 6", ["paper/make_figures.py"], False),
    ("collect every figure and its caption", ["paper/collect_figures.py"], False),
    # Captions are outside both the marker resolver and the typed-number gate, so
    # Figure 1's -- which prints thirteen measured quantities -- is compared with
    # the frozen results here or nowhere.
    ("check Figure 1's caption against the results", ["paper/check_figure1_caption.py"], False),
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
    (
        "check the portal's stamp will not land on a figure",
        ["paper/check_figure_headroom.py"],
        False,
    ),
    ("check the version and both DOIs agree", ["paper/check_release_metadata.py"], True),
    # The journal requires its checklist with every submission and sends an
    # incomplete one back. Every quantity on it is measured by the step above,
    # so it is filled from that rather than typed into a form nobody rechecks.
    ("fill the journal's submission checklist", ["paper/fill_checklist.py"], True),
    ("build the cover letter, the novel points and the kit", ["paper/build_submission.py"], True),
    # The pages are the last thing between a defect and the reviewer, and the
    # only thing that sees a word broken in two or a heading stranded at a
    # page foot. This does not look at them; it notices when a page has
    # changed since somebody did.
    ("check every page is as it was when it was looked at", ["paper/check_visual_review.py"], True),
    ("check everything", ["paper/presubmission_check.py", "--strict"], False),
)


def main(argv: list[str] | None = None) -> int:
    have_prose = SOURCE.exists()
    if not have_prose:
        print(f"note: {SOURCE.name} does not exist yet; its steps are skipped\n")

    skipped: list[str] = []
    for description, command, needs_prose in STEPS:
        if needs_prose and not have_prose:
            print(f"\n=== {description}  [skipped: no manuscript]")
            continue
        if description in WINDOWS_ONLY and os.name != "nt":
            print(f"\n=== {description}  [skipped: drives Word, which needs Windows]")
            skipped.append(description)
            continue
        print(f"\n=== {description}")
        result = subprocess.run([sys.executable, *command], cwd=REPO, check=False, text=True)
        if result.returncode != 0:
            print(f"\nstopped at: {description}")
            return result.returncode

    if not have_prose:
        print("\nevidence and figures rebuilt; the manuscript is not written")
        return 0
    if skipped:
        # Never "every artefact": the submission is prepared on Windows, and a
        # run that could not open the PDF has not seen the pages a reader sees.
        print(f"\nrebuilt and checked, except for {len(skipped)} step(s) this platform cannot run:")
        for description in skipped:
            print(f"  - {description}")
        print("run paper/build_all.py on Windows before submitting.")
        return 0
    print("\nevery artefact rebuilt and checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

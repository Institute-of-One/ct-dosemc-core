"""Record that the submission runbook was read, and pin the version that was read.

    python paper/record_runbook_read.py --by "..." --note "..."

The runbook's own section 11 opens by saying to read it before starting on a
manuscript, and AGENTS.md says the same. Both are instructions to a reader, and a
reader who skips them finds out by rediscovering what is already written there.
That happened twice in one day on 2026-11-07: a negative number breaking across a
line was reported as a new defect when section 3.4 already gives it and its fix,
and the line-number switch was set the wrong way without reading the journal's
guidelines, which section 2.4.1 now records.

So the instruction becomes a gate. This writes a ledger pinning the sha256 of the
runbook as it was when it was read; presubmission_check fails while the file on
disk has a different digest, which is both "never read" and "changed since read".
The runbook is not in this repository -- it is not public -- so nothing of its
content is stored here, only its digest and the date it was read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PAPER = Path(__file__).resolve().parent
REPO = PAPER.parent
LEDGER = PAPER / "runbook_read.json"

#: Where the runbook lives, relative to the parent of this repository. It is kept
#: outside any public repository on purpose, so a clone will not have it and the
#: gate reports that rather than failing.
RUNBOOK = REPO.parent / "IoO" / "docs" / "IoO_Submission_Runbook.md"

#: The sections the runbook itself says to read before starting on a manuscript.
REQUIRED_SECTIONS = ("2", "11")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(by: str, note: str) -> int:
    if not RUNBOOK.is_file():
        print(f"{RUNBOOK} is not here; nothing to record")
        return 1
    LEDGER.write_text(
        json.dumps(
            {
                "_why": (
                    "The submission runbook was read before this manuscript was "
                    "worked on. paper/presubmission_check.py fails while the runbook "
                    "on disk has a different sha256 from the one recorded here, which "
                    "covers both never having read it and its having changed since. "
                    "The runbook is not public and none of its content is stored here."
                ),
                "runbook": RUNBOOK.name,
                "sha256": digest(RUNBOOK),
                "sections": list(REQUIRED_SECTIONS),
                "read_on": date.today().isoformat(),
                "by": by,
                "note": note,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"recorded {RUNBOOK.name} as read in {LEDGER}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--by", required=True, help="who read it; recorded as given")
    parser.add_argument("--note", default="", help="what reading it changed, for the record")
    args = parser.parse_args(argv)
    return record(args.by, args.note)


if __name__ == "__main__":
    raise SystemExit(main())

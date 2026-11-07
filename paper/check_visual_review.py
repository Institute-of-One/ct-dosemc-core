"""Every page of the submitted document must have been looked at as it prints.

    python paper/check_visual_review.py          # verify
    python paper/check_visual_review.py --record # after looking at every page

A script's pass is not a look. The defects that matter in a rendered document
are invisible to everything upstream of it, and this manuscript supplied five of
them in one sitting: a table heading printed as "Canon/Tos" and "hiba", an organ
name as "Gallbladde" and "r", a vendor as "Siemen" and "s", a page left
two-thirds empty by a binding chain, and two lines of the last reference stranded
alone on a page. None of them is a property of the markdown, of the .docx
paragraphs, or of the text pypdf extracts. They are properties of the page.

So the ledger pins the **page images**, not the .docx and not the PDF.

That is not a stylistic preference. Measured on this repository: a rebuild that
changes not one character of content produces a .docx and a PDF with different
digests every time -- python-docx writes a fresh zip timestamp and Word stamps a
creation date -- while all 26 page images come back byte-identical. A ledger
pinning the first two is permanently red and therefore says nothing about what
the reader sees. A companion paper's did exactly that.

``--record`` is the author's assertion that they have opened every page listed.
It is not something the build may do for itself, and nothing here can verify it;
what this file can do is notice when a page has changed since that assertion was
made, and name the page.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PAPER = Path(__file__).resolve().parent
PAGES = PAPER / "build" / "pages"
LEDGER = PAPER / "visual_review.json"


def digests() -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(PAGES.glob("manuscript_p*.png"))
    }


def check() -> int:
    if not LEDGER.exists():
        print(f"{LEDGER} does not exist. Open every page in {PAGES}, then run this with --record.")
        return 1
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    reviewed = ledger["pages"]
    current = digests()

    if not current:
        print(f"no page images in {PAGES}; run paper/render_pdf.py")
        return 1

    changed = sorted(
        name for name in current if name in reviewed and current[name] != reviewed[name]
    )
    added = sorted(set(current) - set(reviewed))
    gone = sorted(set(reviewed) - set(current))

    print(f"{len(reviewed)} pages opened on {ledger['reviewed_on']} by {ledger['looked_at_by']}")
    approved = ledger.get("author_approved_on")
    print(f"  author's own approval: {approved or 'NOT GIVEN'}")
    for name in changed:
        print(f"  CHANGED  {name}")
    for name in added:
        print(f"  NEW      {name}  (never looked at)")
    for name in gone:
        print(f"  GONE     {name}  (the document is shorter than the review)")

    if changed or added or gone:
        print(
            f"\n{len(changed) + len(added) + len(gone)} page(s) differ from the "
            f"review. Open them, then run this with --record."
        )
        return 1
    print(f"all {len(current)} pages are as they were when they were looked at")
    return 0


def record(note: str, args_reviewer: str) -> int:
    current = digests()
    if not current:
        print(f"no page images in {PAGES}; run paper/render_pdf.py")
        return 1
    ledger = {
        "_what_this_is": [
            "The author's record of having opened every page of the rendered",
            "manuscript. The digests are of the page images, because a rebuild that",
            "changes nothing produces a different .docx and a different PDF every",
            "time while the page images come back byte-identical: a ledger pinning",
            "the documents would be permanently red and would say nothing about what",
            "the reader sees.",
        ],
        "reviewed_on": datetime.date.today().isoformat(),
        # Who actually opened the pages. Recording the author's name for a look
        # somebody else took would make the ledger a false record, which is
        # worse than no ledger: it is the one thing in this repository that
        # cannot be re-derived from the files.
        "looked_at_by": args_reviewer,
        # The author's own sign-off, which no script can give on his behalf.
        "author_approved_on": None,
        "note": note,
        "pages": current,
    }
    LEDGER.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"recorded {len(current)} pages in {LEDGER}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--record", action="store_true", help="assert that every page has been opened and looked at"
    )
    parser.add_argument("--note", default="", help="what the review found, for the record")
    parser.add_argument("--by", default="", help="who opened the pages; recorded as given")
    args = parser.parse_args(argv)
    if not args.record:
        return check()
    if not args.by:
        print(
            "--by is required: the ledger records who opened the pages, "
            "and a look recorded under the wrong name is a false record"
        )
        return 2
    return record(args.note, args.by)


if __name__ == "__main__":
    raise SystemExit(main())

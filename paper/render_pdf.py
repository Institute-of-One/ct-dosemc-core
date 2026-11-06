"""Render paper/build/manuscript.docx to the single PDF the portal wants.

    python paper/render_pdf.py

IOP takes one PDF at first submission, with the figures embedded. The .docx is the
generated artefact and this is the step that turns it into that PDF; without this step in
build_all.py the PDF in paper/build/ is whatever was rendered by hand last, and on
2026-10-21 that was six weeks older than the manuscript beside it.

Two things about driving Word here, both learned the hard way in this programme:

* ``Options.Pagination = False``. With background pagination on, exporting a manuscript
  carrying several figures ran for twenty minutes and produced nothing. A page-number
  footer causes the same hang, and IOP wants neither page numbers nor line numbers because
  the submission system adds its own.
* ``DispatchEx``, not ``Dispatch``. That starts a separate Word instance and only that
  instance is closed, so the author's own open documents are not touched.

Also writes a PNG of every page to paper/build/pages/, because a script's pass is not a
look and the defects that matter in a rendered document -- a blank page, a figure split
from its caption, a table broken across a boundary -- are invisible in the source.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PAPER = Path(__file__).resolve().parent
BUILD = PAPER / "build"
DOCX = BUILD / "manuscript.docx"
PDF = BUILD / "manuscript.pdf"
PAGES = BUILD / "pages"


def render() -> int:
    import win32com.client

    if not DOCX.is_file():
        print(f"{DOCX} is missing; run paper/build_docx.py")
        return 1
    if PDF.exists() and PDF.stat().st_mtime > DOCX.stat().st_mtime:
        print(f"{PDF.name} is newer than the .docx; re-rendering anyway")

    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = False
    try:
        try:
            word.Options.Pagination = False
        except Exception:                                     # noqa: BLE001
            pass
        document = word.Documents.Open(str(DOCX), ReadOnly=True)
        try:
            document.SaveAs(str(PDF), FileFormat=17)
        finally:
            document.Close(SaveChanges=False)
    finally:
        word.Quit()
    print(f"rendered {PDF} ({PDF.stat().st_size / 1024:.0f} KB)")
    return 0


def page_images() -> int:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        print("pypdfium2 is not installed, so no page images were written. The visual "
              "review is a required step, not an optional one: install pypdfium2.")
        return 1
    PAGES.mkdir(parents=True, exist_ok=True)
    for old in PAGES.glob("manuscript_p*.png"):
        old.unlink()
    document = pdfium.PdfDocument(str(PDF))
    for number, page in enumerate(document, start=1):
        page.render(scale=2).to_pil().save(PAGES / f"manuscript_p{number:02d}.png")
    print(f"wrote {len(document)} page images to {PAGES}")
    print("Now look at every one. A script's pass is not a look.")
    return 0


#: A page carrying less than this share of the median page is an orphan: a heading, a
#: stranded reference, a caption cut from its figure. Measured against the median rather than
#: against a fixed character count, because a figure page is legitimately short and a text
#: page is not, and the median tracks whatever the layout is.
THIN_PAGE_SHARE = 0.25


def check_pages() -> int:
    """No page may be almost empty.

    Nothing in this repository looked at the rendered PDF. On 2026-10-21 a paragraph added to
    the Conclusions pushed the last reference onto a page of its own, 182 characters against a
    median of about 2,000, and every check passed because they all read the .docx or the
    markdown. The file the referee opens is this one.
    """
    try:
        import pypdf                                          # noqa: PLC0415
    except ImportError:
        print("pypdf is not installed, so the pages were not checked. A check that "
              "passes when its dependency is absent is a check that cannot fail: "
              "install pypdf.")
        return 1

    lengths = [
        len((page.extract_text() or "").strip())
        for page in pypdf.PdfReader(str(PDF)).pages
    ]
    if not lengths:
        print("the PDF has no pages")
        return 1
    ordered = sorted(lengths)
    median = ordered[len(ordered) // 2]
    floor = median * THIN_PAGE_SHARE
    thin = [(n, length) for n, length in enumerate(lengths, start=1) if length < floor]
    for number, length in thin:
        print(
            f"  FAIL page {number} carries {length} characters against a median of "
            f"{median}; it is an orphan, not a page"
        )
    if thin:
        print(f"{len(thin)} near-empty pages; shorten or re-flow the text above them")
        return 1
    print(f"{len(lengths)} pages, none under {floor:.0f} characters")
    return 0


def _headings() -> set[str]:
    """The manuscript's own heading texts, normalised for comparison.

    Matching a *pattern* for a heading does not work: "2. one factor per organ"
    is a list item and "220. https://doi.org/..." is a reference, and the first
    version of this check reported both as stranded headings. The manuscript
    knows exactly what its headings are, so they are read from it.
    """
    source = (PAPER / "build" / "manuscript.md").read_text(encoding="utf-8")
    return {
        " ".join(heading.split()).lower()
        for heading in re.findall(r"(?m)^#{1,6}\s+(.*)$", source)
    }


def _normalise(line: str) -> str:
    """A rendered line, with the margin line number Word prints at its left removed.

    Only the leading number. Stripping a trailing one as well truncated the
    heading "2.3 Verification against TG-195 Case 4" to "... Case", so that
    heading could never have matched and its stranding could never have been
    reported. The trailing form is handled where the comparison is made, by
    trying both, which cannot lose a heading that ends in a number.
    """
    line = re.sub(r"^\s*\d+\s+", "", line)
    return " ".join(line.split()).lower()


def _candidates(line: str) -> tuple[str, ...]:
    """The forms a rendered heading line can take, for comparison.

    pypdf puts the margin line number sometimes before the text and sometimes
    after it, so both are offered. A heading that genuinely ends in a number is
    matched by the first form; a heading followed by its line number, by the
    second.
    """
    normalised = _normalise(line)
    without_trailing = re.sub(r"\s+\d+$", "", normalised)
    return (normalised,) if without_trailing == normalised else (normalised,
                                                                without_trailing)


def stranded_pages(pages: list[str], headings: set[str]) -> list[tuple[int, str]]:
    """``(page number, heading)`` for every page whose last line is a heading.

    Separated from the PDF so that it can be tested on page text directly.
    """
    found = []
    for number, text in enumerate(pages, start=1):
        lines = [line for line in (line.strip() for line in text.splitlines()) if line]
        if not lines:
            continue
        for candidate in _candidates(lines[-1]):
            if candidate in headings:
                found.append((number, candidate))
                break
    return found


def check_page_endings() -> int:
    """No page may end on a heading.

    Word strands a heading at the foot of a page whenever the paragraph has no
    ``keepNext``, and nothing that reads the .docx or the markdown can see it:
    where the text falls is a property of the rendered page and of nothing else.
    A companion manuscript reached its referees with sections 2.6 and 3.2 alone
    at the bottom of a page. build_docx.py binds the headings; this is the check
    that the binding worked on the file the referee opens.
    """
    try:
        import pypdf                                          # noqa: PLC0415
    except ImportError:
        print("pypdf is not installed, so the page endings were not checked: "
              "install pypdf.")
        return 1

    headings = _headings()
    if not headings:
        print("no headings found in the built manuscript; nothing was checked")
        return 1

    pages = [page.extract_text() or "" for page in pypdf.PdfReader(str(PDF)).pages]
    stranded = stranded_pages(pages, headings)
    for number, line in stranded:
        print(f"  FAIL page {number} ends on the heading {line[:60]!r}")
    if stranded:
        print(f"{len(stranded)} heading(s) stranded at a page foot")
        return 1
    print("no page ends on a heading")
    return 0


def main() -> int:
    if os.name != "nt":
        print("this step drives Word and needs Windows; the .docx is unchanged")
        return 1
    failed = render()
    if failed:
        return failed
    failed = page_images()
    if failed:
        return failed
    failed = check_pages()
    if failed:
        return failed
    return check_page_endings()


if __name__ == "__main__":
    raise SystemExit(main())

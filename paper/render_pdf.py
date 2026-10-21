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
        print("pypdfium2 is not installed; page images were not written")
        return 0
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
        print("pypdf is not installed; the pages were not checked")
        return 0

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
    return check_pages()


if __name__ == "__main__":
    raise SystemExit(main())

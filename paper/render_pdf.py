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


def main() -> int:
    if os.name != "nt":
        print("this step drives Word and needs Windows; the .docx is unchanged")
        return 1
    failed = render()
    if failed:
        return failed
    return page_images()


if __name__ == "__main__":
    raise SystemExit(main())

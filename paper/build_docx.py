"""Render the built manuscript to the ``.docx`` the submission system takes.

    python paper/build_docx.py              # -> paper/build/manuscript.docx
    python paper/build_docx.py --output some/where.docx

A derivative, never a source. It re-renders ``paper/manuscript.md`` and refuses to
continue if the committed build is out of date, so a stale number cannot be baked into a
circulated document. Figures are placed after the paragraph that first names them and
carry the caption from ``paper/README.md``, written once.

Two Word defaults are wrong for a results table and are patched after pandoc writes the
file: a row may break across a page, and a table may break between rows even when the
whole of it would fit overleaf. Neither is reachable from pandoc or from a reference
document, because one is a row property and the other has to be set paragraph by
paragraph. A companion paper shipped both.

Page numbers and continuous line numbering are patched in for the same reason.
Pandoc emits neither and no reference document supplies them. Medical Physics
returned a companion manuscript before peer review for the want of both -- a full
round trip for a requirement stated plainly in its author guidelines. Whether PMB
insists on them or not, a reviewer who cannot write "line 412" is a reviewer who
writes "the third paragraph of section 2.7" instead, and they cost nothing.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import build_manuscript  # noqa: E402
import collect_figures  # noqa: E402

DEFAULT_OUTPUT = PAPER / "build" / "manuscript.docx"

#: Case-insensitive, and accepting the abbreviated form. Journal prose names a
#: figure mid-sentence in lower case, and a mention this pattern misses is a figure
#: that never reaches the page -- the build refuses to continue when that happens,
#: which is how it was caught.
#: The trailing guard is ``(?!\d)`` and not ``\b``: prose names a panel as
#: "figure 5a", and a word boundary does not hold between "5" and "a", so the only
#: figure whose every mention carried a panel letter was never placed.
_FIGURE_MENTION = re.compile(r"\bfigs?(?:ure)?\.?\s*(\d+)(?!\d)", re.I)


def _figure_block(number: int, caption: str) -> str:
    """One figure as a captioned image. The alt text is left empty deliberately.

    Pandoc renders alt text as a caption of its own, so text placed there *and* in a
    numbered paragraph prints twice, in two wordings.
    """
    path = collect_figures.FIGURES / collect_figures.FIGURE_SOURCES[number][0]
    return f"![]({path.as_posix()})\n\n**Figure {number}.** {caption}\n"


def assemble(built: str) -> str:
    """The built prose, each figure placed after the paragraph that first names it."""
    captions = collect_figures.captions()
    placed: set[int] = set()
    out: list[str] = []
    for block in built.split("\n\n"):
        out.append(block)
        wanted = sorted(
            {
                int(number)
                for number in _FIGURE_MENTION.findall(block)
                if int(number) in collect_figures.FIGURE_SOURCES
            }
            - placed
        )
        for number in wanted:
            out.append(_figure_block(number, captions[number]))
            placed.add(number)
    missing = sorted(set(collect_figures.FIGURE_SOURCES) - placed)
    if missing:
        raise SystemExit(f"figures never named in the prose, so never placed: {missing}")
    return "\n\n".join(out)


def _set_property(fragment: str, container: str, element: str, prop: str) -> str:
    """Add ``prop`` to every ``container``'s properties, whatever form they take.

    Three forms occur and all three must be handled: present with children, present and
    self-closing, absent. Missing the middle one appends a *second* properties element,
    which the schema forbids and Word silently ignores, so the setting reads as
    applied and does nothing.
    """
    opened = f"<{element}>"
    fragment = re.sub(re.escape(opened), f"{opened}{prop}", fragment)
    fragment = re.sub(rf"<{re.escape(element)}\s*/>", f"{opened}{prop}</{element}>", fragment)
    return re.sub(
        rf"(<{re.escape(container)}\b[^>]*>)(?<!/>)(?!<{re.escape(element)})",
        rf"\1{opened}{prop}</{element}>",
        fragment,
    )


def keep_tables_whole(path: Path) -> Path:
    """``cantSplit`` on every row; ``keepNext`` on the caption and all but the last."""
    entry = "word/document.xml"
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        contents = {name: archive.read(name) for name in names}

    document = contents[entry].decode("utf-8")
    document = _set_property(document, "w:tr", "w:trPr", "<w:cantSplit/>")

    def bind(match: re.Match) -> str:
        caption, table = match.group(1), match.group(2)
        rows = re.findall(r"<w:tr\b.*?</w:tr>", table, re.S)
        caption = _set_property(caption, "w:p", "w:pPr", "<w:keepNext/>")
        # The last row is left free: binding it drags the paragraph after the table onto
        # the same page, which trades one defect for another.
        for row in rows[:-1]:
            table = table.replace(row, _set_property(row, "w:p", "w:pPr", "<w:keepNext/>"), 1)
        return caption + table

    document = re.sub(
        r"(<w:p\b(?:(?!<w:p\b).)*?</w:p>\s*)(<w:tbl>.*?</w:tbl>)",
        bind,
        document,
        flags=re.S,
    )
    contents[entry] = document.encode("utf-8")

    temporary = path.with_suffix(".docx.tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, contents[name])
    shutil.move(str(temporary), str(path))
    return path


#: The footer part, holding a centred PAGE field. Word evaluates the field on open; the
#: literal "1" is what a reader sees before it does.
_FOOTER_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    "<w:r><w:t>1</w:t></w:r>"
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    "</w:p></w:ftr>"
)

_FOOTER_PART = "word/footer1.xml"
_FOOTER_RELATIONSHIP = "rIdPageFooter"
_FOOTER_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"

#: Continuous line numbering down the left margin, every line, restarting never.
#: ``distance`` is twentieths of a point: 360 is a quarter inch clear of the text.
_LINE_NUMBERING = '<w:lnNumType w:countBy="1" w:restart="continuous" w:distance="360"/>'

#: Whether this paper's .docx carries its own line numbers. False for PMB: ScholarOne
#: numbers the lines of the proof it builds from the upload, and a manuscript that
#: brings its own ends up with two sets that do not agree. Set True for a journal that
#: requires them, Medical Physics among them.
LINE_NUMBERS = False


def number_pages_and_lines(path: Path, line_numbers: bool = LINE_NUMBERS) -> Path:
    """Add page numbers, and line numbering only where the journal wants it.

    Medical Physics returned a companion submission before peer review for the want of
    both. Elsevier recommends line numbering rather than requiring it, but the cost of
    carrying it is nothing and the cost of discovering it at the desk is a round trip.

    PMB is the exception, and it is why this is now a switch. Its ScholarOne site
    numbers the lines of the proof it builds, so a manuscript that already carries its
    own arrives with two columns of numbers down the same page, disagreeing with each
    other. Page numbers are added either way; only the line numbers are conditional.

    Pandoc emits neither and no reference document supplies them. Line numbering is one
    section property; a page number needs a footer part carrying a PAGE field, a
    content-type override, a relationship, and a reference to it from the section. Order
    inside ``sectPr`` is fixed by the schema -- ``footerReference`` before
    ``footnotePr``, ``lnNumType`` after -- and Word rejects the part if they are
    reversed.
    """
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        contents = {name: archive.read(name) for name in names}

    document = contents["word/document.xml"].decode("utf-8")
    # The footer is added in every case, so it, and not the optional line numbering,
    # is what says the furniture is already in place.
    if _FOOTER_PART in names:
        return path

    reference = f'<w:footerReference w:type="default" r:id="{_FOOTER_RELATIONSHIP}"/>'
    document = document.replace("<w:sectPr>", f"<w:sectPr>{reference}", 1)
    if line_numbers:
        document = document.replace(
            "</w:footnotePr>", f"</w:footnotePr>{_LINE_NUMBERING}", 1
        )
    contents["word/document.xml"] = document.encode("utf-8")

    rels = contents["word/_rels/document.xml.rels"].decode("utf-8")
    relationship = (
        f'<Relationship Id="{_FOOTER_RELATIONSHIP}" Type="http://schemas.openxmlformats'
        '.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
    )
    rels = rels.replace("</Relationships>", f"{relationship}</Relationships>", 1)
    contents["word/_rels/document.xml.rels"] = rels.encode("utf-8")

    types = contents["[Content_Types].xml"].decode("utf-8")
    override = f'<Override PartName="/{_FOOTER_PART}" ContentType="{_FOOTER_TYPE}"/>'
    types = types.replace("</Types>", f"{override}</Types>", 1)
    contents["[Content_Types].xml"] = types.encode("utf-8")

    contents[_FOOTER_PART] = _FOOTER_XML.encode("utf-8")

    temporary = path.with_suffix(".docx.tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in [*names, _FOOTER_PART]:
            archive.writestr(name, contents[name])
    shutil.move(str(temporary), str(path))
    return path


def build(output: Path = DEFAULT_OUTPUT, line_numbers: bool = LINE_NUMBERS) -> int:
    import pypandoc  # noqa: PLC0415

    source = build_manuscript.DEFAULT_SOURCE.read_text(encoding="utf-8")
    rendered = build_manuscript.render(source)
    committed = build_manuscript.DEFAULT_OUTPUT
    if not committed.exists() or committed.read_text(encoding="utf-8") != rendered:
        print("paper/build/manuscript.md is out of date; run paper/build_manuscript.py")
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    pypandoc.convert_text(
        assemble(rendered),
        to="docx",
        format="markdown+implicit_figures",
        outputfile=str(output),
        extra_args=["--resource-path", str(PAPER)],
    )
    keep_tables_whole(output)
    number_pages_and_lines(output, line_numbers=line_numbers)
    print(f"wrote {output} ({output.stat().st_size // 1024} KB)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--line-numbers", action="store_true",
        help="carry line numbers in the .docx; PMB's ScholarOne adds its own, so off here",
    )
    args = parser.parse_args(argv)
    return build(args.output, line_numbers=args.line_numbers or LINE_NUMBERS)


if __name__ == "__main__":
    raise SystemExit(main())

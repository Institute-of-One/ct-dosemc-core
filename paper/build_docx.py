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
#: brings its own ends up with two sets that do not agree. True for Radiological
#: Physics and Technology, whose guidelines require "all lines ... numbered
#: consecutively from the title page through the manuscript" and whose Editorial
#: Manager does not add them, and for Medical Physics.
LINE_NUMBERS = True

#: A4, because the author and the journal are both in Japan and the reviewers will
#: print it. Twentieths of a point.
_PAGE_WIDTH, _PAGE_HEIGHT = 11906, 16838

#: Wide margins, which the guidelines ask for: 1 inch top and bottom, 1.25 inches
#: left and right. The line numbers sit 0.25 inches into the left margin, so the
#: wider side margins are what keeps them clear of the text.
_MARGIN_TOP = _MARGIN_BOTTOM = 1440
_MARGIN_LEFT = _MARGIN_RIGHT = 1800

#: Double spacing, which the guidelines ask for. ``line`` is twentieths of a point
#: and 480 is two 12-point lines; ``auto`` keeps it proportional if a run is larger.
_DOUBLE_SPACED = '<w:spacing w:after="200" w:line="480" w:lineRule="auto"/>'


def single_column_double_spaced(path: Path) -> Path:
    """Set the page size, the wide margins and double line spacing.

    Pandoc writes a ``sectPr`` with no page size and no margins at all, leaving
    both to whatever Word defaults to on the machine that opens the file. A
    manuscript whose layout depends on the reader's copy of Word is a manuscript
    whose compliance with "single-column, double-spaced" cannot be checked.

    The order of children inside ``sectPr`` is fixed by the schema --
    ``footerReference``, ``footnotePr``, ``pgSz``, ``pgMar``, ``lnNumType`` -- and
    Word rejects the part outright when they are out of order, so the element is
    rebuilt rather than patched in pieces.
    """
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        contents = {name: archive.read(name) for name in names}

    document = contents["word/document.xml"].decode("utf-8")
    match = re.search(r"<w:sectPr\b[^>]*>(.*?)</w:sectPr>", document, re.S)
    if not match:
        raise SystemExit("no sectPr in the converted document; pandoc changed its output")
    inside = match.group(1)

    def take(element: str) -> str:
        found = re.search(rf"<w:{element}\b(?:[^>]*/>|.*?</w:{element}>)", inside, re.S)
        return found.group(0) if found else ""

    page = (
        f'<w:pgSz w:w="{_PAGE_WIDTH}" w:h="{_PAGE_HEIGHT}"/>'
        f'<w:pgMar w:top="{_MARGIN_TOP}" w:right="{_MARGIN_RIGHT}" '
        f'w:bottom="{_MARGIN_BOTTOM}" w:left="{_MARGIN_LEFT}" '
        'w:header="720" w:footer="720" w:gutter="0"/>'
    )
    rebuilt = (
        "<w:sectPr>"
        + take("footerReference")
        + take("footnotePr")
        + page
        + take("lnNumType")
        + '<w:cols w:space="720"/>'   # one column, stated rather than defaulted
        + "</w:sectPr>"
    )
    document = document[: match.start()] + rebuilt + document[match.end():]
    contents["word/document.xml"] = document.encode("utf-8")

    # The spacing has to be read out of docDefaults, not looked for anywhere in
    # styles.xml: named styles carry w:line of their own, so a test for the
    # string in the whole file is satisfied by a document that is still single
    # spaced. The first version of this patch did exactly that and changed
    # nothing, and the .docx it wrote looked finished.
    styles = contents["word/styles.xml"].decode("utf-8")
    defaults = re.search(r"<w:pPrDefault>.*?</w:pPrDefault>", styles, re.S)
    if not defaults:
        raise SystemExit("pandoc wrote no pPrDefault; double spacing cannot be set here")
    if "w:line=" not in defaults.group(0):
        patched = f"<w:pPrDefault><w:pPr>{_DOUBLE_SPACED}</w:pPr></w:pPrDefault>"
        styles = styles[: defaults.start()] + patched + styles[defaults.end():]
        again = re.search(r"<w:pPrDefault>.*?</w:pPrDefault>", styles, re.S)
        if not again or 'w:line="480"' not in again.group(0):
            raise SystemExit("could not set double spacing in docDefaults")
        contents["word/styles.xml"] = styles.encode("utf-8")

    temporary = path.with_suffix(".docx.tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, contents[name])
    shutil.move(str(temporary), str(path))
    return path


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
        document = document.replace("</w:footnotePr>", f"</w:footnotePr>{_LINE_NUMBERING}", 1)
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


#: Tables are set smaller than the body. At the body size a row of
#: "value [low, high] (n)" does not fit the text block, and Word breaks a line
#: inside a number; a companion paper printed an interval whose lower bound read
#: as positive because the minus sign ended a line. Half-points.
_TABLE_FONT_HALF_POINTS = 20


def shrink_tables(path: Path) -> Path:
    """Set the table text one size down, and single-spaced.

    Double spacing inside a table doubles its height for no gain -- the rows are
    already separated by rules -- and it is what pushed this manuscript's one
    table over a page boundary and left the page before it two-thirds empty.
    """
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        contents = {name: archive.read(name) for name in names}

    document = contents["word/document.xml"].decode("utf-8")
    tables = re.findall(r"<w:tbl>.*?</w:tbl>", document, re.S)
    if not tables:
        print("  note: no tables in the document")
        return path

    size = (f'<w:sz w:val="{_TABLE_FONT_HALF_POINTS}"/>'
            f'<w:szCs w:val="{_TABLE_FONT_HALF_POINTS}"/>')
    single = '<w:spacing w:before="40" w:after="40" w:line="240" w:lineRule="auto"/>'
    for table in tables:
        shrunk = _set_property(table, "w:r", "w:rPr", size)
        shrunk = _set_property(shrunk, "w:p", "w:pPr", single)
        document = document.replace(table, shrunk, 1)
    contents["word/document.xml"] = document.encode("utf-8")

    temporary = path.with_suffix(".docx.tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, contents[name])
    shutil.move(str(temporary), str(path))
    return path


def bind_headings_to_text(path: Path) -> Path:
    """Keep every heading on the page as the text it introduces.

    Word breaks a heading from its body unless the paragraph carries
    ``keepNext``, and pandoc does not set it. A heading alone at the foot of a
    page is invisible to every check that reads the .docx or the markdown,
    because it is not a property of either: it is where the text happened to
    fall. A companion manuscript reached its referees with two.
    """
    import docx                                               # noqa: PLC0415

    document = docx.Document(str(path))
    bound = 0
    for paragraph in document.paragraphs:
        if paragraph.style.name.startswith(("Heading", "Title", "Subtitle")):
            paragraph.paragraph_format.keep_with_next = True
            bound += 1
    if not bound:
        raise SystemExit(
            "no headings were found to bind to their text; pandoc's style names have "
            "changed and every heading would be free to strand at a page foot"
        )
    document.save(str(path))
    return path


def plain_headings(path: Path) -> Path:
    """Make every heading black.

    Pandoc styles headings in its own blue, which is how a converted file looks rather than
    how a manuscript looks. The editorial office sees the upload before a referee does, and a
    document announcing its own toolchain is an avoidable distraction. Nothing else is
    touched: the journal typesets its own, and a manuscript that arrives over-formatted is no
    better than one that arrives blue.
    """
    import docx                                               # noqa: PLC0415
    from docx.shared import RGBColor                          # noqa: PLC0415

    document = docx.Document(str(path))
    black = RGBColor(0, 0, 0)
    for style in document.styles:
        if style.name.startswith(("Heading", "Title", "Subtitle")):
            try:
                style.font.color.rgb = black
            except AttributeError:
                pass
    for paragraph in document.paragraphs:
        if paragraph.style.name.startswith(("Heading", "Title", "Subtitle")):
            for run in paragraph.runs:
                run.font.color.rgb = black
    document.save(str(path))
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
    shrink_tables(output)
    bind_headings_to_text(output)
    plain_headings(output)
    # The furniture first, then the layout: single_column_double_spaced rebuilds
    # the sectPr and has to find the footer reference and line numbering already
    # in it to carry them over in schema order.
    number_pages_and_lines(output, line_numbers=line_numbers)
    single_column_double_spaced(output)
    print(f"wrote {output} ({output.stat().st_size // 1024} KB)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--line-numbers",
        action="store_true",
        help="carry line numbers in the .docx; PMB's ScholarOne adds its own, so off here",
    )
    args = parser.parse_args(argv)
    return build(args.output, line_numbers=args.line_numbers or LINE_NUMBERS)


if __name__ == "__main__":
    raise SystemExit(main())

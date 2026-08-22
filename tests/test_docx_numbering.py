"""The submitted .docx must carry page numbers and continuous line numbering.

Medical Physics returned a companion manuscript before peer review for the want of
both. Every check in that repository read the markdown, and the markdown holds the
numbers and the prose, so it felt sufficient; page furniture exists only in the
artefact that reaches the editor.

These tests run before IORN-007 has prose, which is the point. The numbering was
added to a companion paper after it was written, and it was the editorial office
that found it missing.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

PAPER = Path(__file__).resolve().parents[1] / "paper"
sys.path.insert(0, str(PAPER))

pypandoc = pytest.importorskip("pypandoc")
import build_docx  # noqa: E402

MARKDOWN = """
# A heading

A paragraph, so the document has a section and a body.

| Organ | Dose |
|---|---|
| Liver | 27.5 |
| Spleen | 29.7 |
"""


@pytest.fixture(scope="module")
def numbered(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("docx") / "manuscript.docx"
    pypandoc.convert_text(
        MARKDOWN, to="docx", format="markdown", outputfile=str(output)
    )
    build_docx.keep_tables_whole(output)
    build_docx.number_pages_and_lines(output)
    return output


def _part(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name).decode("utf-8")


def test_pandoc_supplies_neither_on_its_own(tmp_path: Path) -> None:
    """The premise: this is not something the converter would have done."""
    plain = tmp_path / "plain.docx"
    pypandoc.convert_text(
        MARKDOWN, to="docx", format="markdown", outputfile=str(plain)
    )
    document = _part(plain, "word/document.xml")
    assert "lnNumType" not in document
    assert "footerReference" not in document


def test_lines_are_numbered_continuously(numbered: Path) -> None:
    document = _part(numbered, "word/document.xml")
    assert 'w:countBy="1"' in document
    assert 'w:restart="continuous"' in document


def test_the_page_number_is_a_field_not_a_literal(numbered: Path) -> None:
    """A typed "1" would print 1 on every page."""
    footer = _part(numbered, build_docx._FOOTER_PART)
    assert "PAGE" in footer
    assert 'w:fldCharType="begin"' in footer


def test_the_footer_is_declared_and_related(numbered: Path) -> None:
    """A part Word cannot resolve makes the whole file unopenable, not the footer."""
    assert build_docx._FOOTER_TYPE in _part(numbered, "[Content_Types].xml")
    rels = _part(numbered, "word/_rels/document.xml.rels")
    assert build_docx._FOOTER_RELATIONSHIP in rels
    assert 'Target="footer1.xml"' in rels


def test_section_properties_are_in_schema_order(numbered: Path) -> None:
    """footerReference before footnotePr, lnNumType after.

    The order inside sectPr is fixed by the schema and Word rejects the part when
    it is wrong -- silently, by refusing to open the document at all, which reads
    as a corrupt file rather than as a malformed element.
    """
    document = _part(numbered, "word/document.xml")
    start = document.index("<w:sectPr")
    section = document[start : document.index("</w:sectPr>", start)]
    positions = [
        section.find("footerReference"),
        section.find("footnotePr"),
        section.find("lnNumType"),
    ]
    assert all(position >= 0 for position in positions), positions
    assert positions == sorted(positions), (
        f"sectPr children out of schema order: {positions}"
    )


def test_rows_cannot_split_across_a_page(numbered: Path) -> None:
    assert "cantSplit" in _part(numbered, "word/document.xml")


def test_applying_it_twice_changes_nothing(numbered: Path) -> None:
    """build_all reruns every step; a second pass must not duplicate the footer."""
    before = _part(numbered, "word/document.xml")
    build_docx.number_pages_and_lines(numbered)
    assert _part(numbered, "word/document.xml") == before
    assert before.count("lnNumType") == 1
    assert before.count("footerReference") == 1

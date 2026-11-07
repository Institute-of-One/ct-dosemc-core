"""Build the cover letter, the novel scientific points and the submission kit.

    python paper/build_submission.py

Everything the portal is given besides the manuscript itself. All three are
generated, not typed, and every checkable value in them is resolved from the
same frozen results the manuscript resolves from, or read back out of the built
manuscript.

That is not tidiness. A submission kit is a memory of the last submission: on a
companion paper eight of its claims were false by the time it was used, and one
of them was the name of the file to upload. A cover letter is worse, because the
editor reads it first and it survives untouched into the next revision -- one in
this programme carried a retracted number for two revision rounds.

So the rule here is that nothing in these files is written twice. The title
comes from the manuscript. The word counts come from the checker that measures
them. The file names come from the list of files this script itself writes.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import build_manuscript  # noqa: E402
import check_rpt_limits  # noqa: E402

BUILD = PAPER / "build"
BUILT_MANUSCRIPT = BUILD / "manuscript.md"

COVER_SOURCE = PAPER / "cover_letter.md"
POINTS_SOURCE = PAPER / "novel_points.md"

COVER_TEXT = BUILD / "cover_letter.txt"
COVER_DOCX = BUILD / "cover_letter.docx"
POINTS_TEXT = BUILD / "novel_scientific_points.txt"
KIT = BUILD / "SUBMISSION_KIT.md"

#: The submission system's limit on one novel scientific point, in characters
#: including spaces, from the editor-in-chief's preparation guide.
POINT_LIMIT = 100
POINT_COUNT = (3, 5)

#: Editorial Manager's own item types, from the same guide: M for the main
#: document, F for a figure, S for a supporting file.
#: Each entry is the path, relative to paper/, of a file this build writes or
#: this repository keeps. The kit reports whether each one exists, so a file
#: that was never built is named on the list rather than discovered at the
#: portal.
UPLOADS = (
    ("build/manuscript.docx", "M", "Manuscript"),
    ("build/figures/Figure_1.png", "F", "Figure 1"),
    ("build/figures/Figure_2.png", "F", "Figure 2"),
    ("build/figures/Figure_3.png", "F", "Figure 3"),
    ("build/figures/Figure_4.png", "F", "Figure 4"),
    ("build/figures/Figure_5.png", "F", "Figure 5"),
    ("build/figures/Figure_6.png", "F", "Figure 6"),
    ("build/cover_letter.docx", "S", "Cover Letter"),
    # The filled copy in build/, not the blank template in submission/. The
    # template is kept as downloaded and never written to.
    (
        "build/12194_RPT Submission Checklist_2025.xlsx",
        "S",
        "Supplementary Material (only for review)",
    ),
)


def _title() -> str:
    """The manuscript's own title. Never retyped into the letter or the kit."""
    found = re.search(r"(?m)^#\s+(.+)$", BUILT_MANUSCRIPT.read_text(encoding="utf-8"))
    if not found:
        raise SystemExit(f"{BUILT_MANUSCRIPT} has no level-1 title")
    return " ".join(found.group(1).split())


def _resolve(source: Path) -> str:
    """Markers resolved, and the title substituted, exactly as the manuscript is.

    The comments go first. Each of these files documents its own notation in a
    comment at the top, and that example contains a literal marker which render()
    deliberately leaves alone -- so checking for leftovers before stripping the
    comments reports the documentation as a defect.
    """
    text = _strip_comments(source.read_text(encoding="utf-8"))
    text = text.replace("[[title]]", _title())
    rendered = build_manuscript.render(text, cite=False)
    if "[[" in rendered:
        leftover = re.findall(r"\[\[[^\]]*\]\]", rendered)
        raise SystemExit(f"{source.name}: unresolved markers {leftover}")
    return rendered


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->\s*", "", text, flags=re.S)


def build_cover_letter() -> str:
    """The letter, as one paragraph per line with a blank line between.

    The portal's cover-letter box keeps the line breaks it is given. A letter
    wrapped at 90 columns arrives with every line broken in the middle, which is
    what happened to a companion paper's.
    """
    text = _resolve(COVER_SOURCE)
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        if not block.strip():
            continue
        lines = [line for line in block.splitlines() if line.strip()]
        # A block whose lines all begin with "|" keeps its line breaks: an
        # address is not a paragraph, and the first version of this collapsed
        # the whole signature onto one line.
        if all(line.lstrip().startswith("|") for line in lines):
            paragraphs.append("\n".join(line.lstrip()[1:].strip() for line in lines))
        else:
            paragraphs.append(" ".join(block.split()))
    return "\n\n".join(paragraphs) + "\n"


def build_points() -> list[str]:
    text = _resolve(POINTS_SOURCE)
    points = [" ".join(line[2:].split()) for line in text.splitlines() if line.startswith("- ")]

    problems = []
    if not POINT_COUNT[0] <= len(points) <= POINT_COUNT[1]:
        problems.append(
            f"{len(points)} novel scientific points; the guide asks for "
            f"{POINT_COUNT[0]} to {POINT_COUNT[1]}"
        )
    for point in points:
        # The length is measured after the markers resolve. Measuring the source
        # would measure "[[results:manifest.json:metrics...]]", which is not what
        # anyone counts.
        if len(point) > POINT_LIMIT:
            problems.append(f"{len(point)} characters, {POINT_LIMIT} allowed: {point!r}")
    if problems:
        raise SystemExit("the novel scientific points do not fit:\n  - " + "\n  - ".join(problems))
    return points


def build_kit(points: list[str]) -> str:
    """What to upload and what the submission form will ask for.

    Every number here is resolved from the build, so the kit cannot assert
    something the manuscript stopped being true about.
    """
    built = BUILT_MANUSCRIPT.read_text(encoding="utf-8")
    measured, notes, problems = check_rpt_limits.measure(built)
    if problems:
        raise SystemExit(
            "the manuscript does not pass its own limits check, so no kit is written:\n"
            "  - " + "\n  - ".join(problems)
        )

    keywords = next((note for note in notes if note.startswith("keywords:")), "")
    keyword_list = keywords.partition("(")[2].rstrip(")")

    doi = re.search(r"10\.5281/zenodo\.\d+", built)
    present = []
    missing = []
    for relative, kind, label in UPLOADS:
        path = PAPER / relative
        (present if path.is_file() else missing).append((Path(relative).name, kind, label, path))

    lines = [
        "# Submission kit: Radiological Physics and Technology",
        "",
        "Generated by `paper/build_submission.py`. Every value below is resolved from",
        "the build, not typed: a kit is otherwise a memory of the last submission.",
        "",
        "**Portal.** Editorial Manager, https://www.editorialmanager.com/rpte",
        "",
        "## The manuscript",
        "",
        f"- **Title** ({measured['title words']} words): {_title()}",
        "- **Article type:** Research Article",
        "- **Author:** Shuji Yamamoto, Institute of One, LISIT Co., Ltd.,",
        "  Tokyo 150-0044, Japan. yamamoto@lisit.jp, ORCID 0000-0001-9211-1071.",
        "  Sole author, so no co-author confirmation e-mails will be outstanding.",
        f"- **Abstract:** {measured['abstract words']} words "
        f"(limit {check_rpt_limits.LIMITS['abstract words']})",
        f"- **Text:** {measured['text words']} words "
        f"(limit {check_rpt_limits.LIMITS['text words']})",
        f"- **References:** {measured['references']} "
        f"(limit {check_rpt_limits.LIMITS['references']})",
        f"- **Figures and tables:** {measured['figures and tables']} "
        f"(limit {check_rpt_limits.LIMITS['figures and tables']})",
        f"- **Keywords:** {keyword_list}",
        f"- **Data availability DOI:** {doi.group(0) if doi else 'MISSING'}",
        "",
        "## Files to upload",
        "",
        "| File | Item type | Label |",
        "|---|---|---|",
    ]
    for name, kind, label, _ in present:
        lines.append(f"| `{name}` | {kind} | {label} |")
    for name, kind, label, path in missing:
        lines.append(f"| `{name}` | {kind} | {label} — **NOT BUILT YET** ({path}) |")
    lines += [
        "",
        "## Novel scientific points",
        "",
        f"Three to five, at most {POINT_LIMIT} characters each. Paste into the metadata",
        "field during submission; they are not published.",
        "",
    ]
    for point in points:
        lines.append(f"- ({len(point)}) {point}")
    lines += [
        "",
        "## Author comments to the editors",
        "",
        "- The checklist is uploaded as 'Supplementary Material (only for review)',",
        "  as the submission guidelines require.",
        "- No reviewer is suggested. Preferred Associate Editors may be named from the",
        "  published editorial board; no name is invented here.",
        "",
        "## Before pressing submit",
        "",
        "- `python paper/build_all.py` is green, including the limits, the reference",
        "  resolution, the figure headroom and the release metadata.",
        "- The rendered pages in `paper/build/pages/` have been looked at. A script's",
        "  pass is not a look.",
        "- The PDF the portal builds has been read before approving it: the portal",
        "  stamps its own figure labels, and that is the first place they are visible.",
        "",
    ]
    if missing:
        lines.insert(
            0,
            f"> **{len(missing)} file(s) in the upload list have not been built yet.**\n",
        )
    return "\n".join(lines)


def _to_docx(text: str, destination: Path) -> None:
    import pypandoc  # noqa: PLC0415

    pypandoc.convert_text(text, to="docx", format="markdown", outputfile=str(destination))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-docx", action="store_true", help="skip the Word versions (pandoc not available)"
    )
    args = parser.parse_args(argv)

    if not BUILT_MANUSCRIPT.exists():
        print(f"{BUILT_MANUSCRIPT} is missing; run paper/build_manuscript.py")
        return 1

    BUILD.mkdir(parents=True, exist_ok=True)

    letter = build_cover_letter()
    COVER_TEXT.write_text(letter, encoding="utf-8", newline="\n")
    print(
        f"wrote {COVER_TEXT} ({len(letter.split())} words, "
        f"{len(letter.strip().split(chr(10) * 2))} paragraphs)"
    )

    points = build_points()
    POINTS_TEXT.write_text("\n".join(points) + "\n", encoding="utf-8", newline="\n")
    print(
        f"wrote {POINTS_TEXT} ({len(points)} points, "
        f"longest {max(len(p) for p in points)} characters)"
    )

    # The Word letter before the kit: the kit reports which upload files exist,
    # and a kit written first reports the letter it is about as missing.
    if not args.no_docx:
        try:
            _to_docx(letter, COVER_DOCX)
            print(f"wrote {COVER_DOCX}")
        except Exception as error:  # noqa: BLE001
            print(f"the Word cover letter was not written: {error}")
            return 1

    kit = build_kit(points)
    KIT.write_text(kit, encoding="utf-8", newline="\n")
    print(f"wrote {KIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

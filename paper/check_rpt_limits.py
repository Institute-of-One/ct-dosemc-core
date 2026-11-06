"""Measure the built manuscript against the journal's Research Article limits.

    python paper/check_rpt_limits.py

Radiological Physics and Technology states, for a Research Article: 250 words of
abstract, 14 figures and tables, 50 references, 4000 words of text, and a title
of about 20 words. The guidelines add that lengths "may be negotiable if
necessary", which is not a budget to spend: the journal carries Technical Note
and Clinical Technique categories, and a Research Article that arrives over
length is a Research Article that can be reclassified rather than reviewed.

What counts as text is decided here and stated, because every tool counts
differently and a limit measured two ways is not a limit. The body is the
numbered sections: title, abstract, keywords, the reference list, the tables,
the figure captions, the acknowledgments and the declarations are all outside
it, which is the convention the journal's own guide follows when it excludes
"abstract, figures/tables, and references" for a Review Article.

Run against ``paper/build/manuscript.md``, never the source: the source says
``[[results:...]]`` where the document says a number, and a marker is one word
where "13.4" is one word but "6 to 9" is three.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PAPER = Path(__file__).resolve().parent
BUILT = PAPER / "build" / "manuscript.md"

#: Research Article, from the submission guidelines read on 2026-11-07.
LIMITS = {
    # "Text words (main text, acknowledgments, declarations, and appendices)",
    # as the journal's own submission checklist names and bounds it.
    "text words": 4000,
    "abstract words": 250,
    "references": 50,
    "figures and tables": 14,
    "title words": 20,
}

#: Four to six, from the preparation guide (arXiv:2403.02888).
KEYWORDS = (4, 6)

#: The numbered sections the journal expects, in order.
EXPECTED_SECTIONS = (
    "1. Introduction",
    "2. Materials and methods",
    "3. Results",
    "4. Discussion",
    "5. Conclusions",
)

#: Back matter, unnumbered, after the body and before the references.
EXPECTED_BACK_MATTER = ("Acknowledgments", "Declarations", "References")

#: Every declaration the guide names, plus the ones this work must make.
EXPECTED_DECLARATIONS = (
    "Funding",
    "Conflict of interest",
    "Ethics approval",
    "Data availability",
    "Code availability",
    "Use of generative artificial intelligence",
)


def sections(text: str) -> list[tuple[int, str, str]]:
    """``(level, heading, body)`` for every ``#``-headed section, in order."""
    parts = re.split(r"(?m)^(#{1,6})\s+(.*)$", text)
    out: list[tuple[int, str, str]] = []
    for index in range(1, len(parts), 3):
        out.append((len(parts[index]), parts[index + 1].strip(), parts[index + 2]))
    return out


def prose(text: str) -> str:
    """The text with everything that is not prose removed."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"(?m)^\s*\|.*$", " ", text)            # table rows
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)     # placed images
    # A caption is a paragraph, not a line. Stripping only the line the label
    # sits on left most of every caption in the count, and left the whole of
    # Table 1's -- a hundred and ten words. Figures and tables are outside the
    # journal's text count, and a caption is part of its figure or table.
    text = re.sub(r"(?ms)^\*\*(?:Figure|Table) \d+\.\*\*.*?(?=\n\s*\n|\Z)", " ", text)
    text = re.sub(r"(?m)^#{1,6}\s+.*$", " ", text)        # headings
    text = re.sub(r"(?m)^\s*-{3,}\s*$", " ", text)        # horizontal rules
    return text


def words(text: str) -> int:
    """Words, counted the way a word processor counts them.

    Every whitespace-separated token, including a lone ``%`` or em dash. That is
    deliberately the stricter of the two defensible counts: SI style puts a space
    before the per-cent sign, this manuscript has 31 of them and 30 em dashes,
    and counting only tokens containing a letter or digit put it 70 words under
    what the editorial office will see. A limit measured two ways is not a limit,
    so it is measured the way the person checking it will measure it.
    """
    return len(prose(text).split())


def counted_text(text: str) -> str:
    """What the journal counts as "text", in its own words.

    The submission checklist the journal distributes defines the quantity it
    limits to 4000 words as "Text words (main text, acknowledgments,
    declarations, and appendices)". Only the abstract, the figures and tables
    and the references are outside it.

    That is not what this check measured first. It counted the numbered sections
    alone and reported 3996 of 4000, while the journal's own definition made the
    same manuscript 4313. A limit measured two ways is not a limit, and when the
    two readings differ the journal's is the one that counts.

    (Counting each numbered section's own body is wrong in a third way, and was
    the first version of this: it misses every subsection, because a
    ``## 2. Materials and methods`` whose next line is ``### 2.1`` has almost no
    body of its own. That reading made the manuscript 712 words.)
    """
    start = re.search(r"(?m)^##\s+1\.\s", text)
    if not start:
        return ""
    end = re.search(r"(?m)^##\s+References\b", text[start.start():])
    stop = start.start() + end.start() if end else len(text)
    return text[start.start():stop]


def measure(text: str) -> tuple[dict[str, int], list[str], list[str]]:
    found = sections(text)
    notes: list[str] = []
    problems: list[str] = []

    title = next((heading for level, heading, _ in found if level == 1), "")
    if not title:
        problems.append("the manuscript has no level-1 title")

    abstract = next((body for level, heading, body in found
                     if heading.lower().startswith("abstract")), "")
    if not abstract:
        problems.append("no Abstract section")
    # The keyword line sits inside the abstract section and is not abstract prose.
    keyword_line = re.search(r"(?m)^\*\*Keywords?:?\*\*\s*(.+(?:\n(?!\n).+)*)", abstract)
    abstract_prose = abstract
    if keyword_line:
        abstract_prose = abstract.replace(keyword_line.group(0), " ")
        keywords = [k.strip() for k in re.split(r",", keyword_line.group(1)) if k.strip()]
        if not KEYWORDS[0] <= len(keywords) <= KEYWORDS[1]:
            problems.append(
                f"{len(keywords)} keywords; the guide asks for {KEYWORDS[0]} to {KEYWORDS[1]}"
            )
        notes.append(f"keywords: {len(keywords)} ({', '.join(keywords)})")
    else:
        problems.append("no **Keywords:** line inside the Abstract")

    # The abstract must stand alone: no citation, no table, no display equation.
    if re.search(r"\[\d+(?:,\s*\d+)*\]", abstract_prose):
        problems.append("the abstract cites a reference; the guide forbids it")
    if re.search(r"(?i)\b(?:Fig\.|Figure|Table)\s+\d", abstract_prose):
        problems.append("the abstract names a figure or table; the guide forbids it")

    numbered = [(heading, body) for level, heading, body in found
                if re.match(r"^\d+\.\s", heading)]
    names = [heading for heading, _ in numbered]
    if names != list(EXPECTED_SECTIONS):
        problems.append(
            "the numbered sections are not the ones the journal expects.\n"
            f"       expected: {list(EXPECTED_SECTIONS)}\n"
            f"       found:    {names}"
        )

    # Subsection numbers must continue their section and leave no gap: a "4.5"
    # under a section whose first subsection is 4.5 tells the reader four
    # subsections are missing.
    subsections: dict[str, list[int]] = {}
    for level, heading, _ in found:
        match = re.match(r"^(\d+)\.(\d+)\s", heading)
        if match:
            subsections.setdefault(match.group(1), []).append(int(match.group(2)))
    for parent, got in sorted(subsections.items()):
        if got != list(range(1, len(got) + 1)):
            problems.append(f"section {parent} has subsections {got}, which is not 1..n")

    headings = [heading for _, heading, _ in found]
    for wanted in EXPECTED_BACK_MATTER:
        if wanted not in headings:
            problems.append(f"no {wanted!r} section")

    declarations = next((body for level, heading, body in found
                         if heading == "Declarations"), "")
    for wanted in EXPECTED_DECLARATIONS:
        if f"**{wanted}.**" not in declarations:
            problems.append(f"the Declarations section makes no {wanted!r} declaration")

    body_words = words(counted_text(text))
    if not body_words:
        problems.append("no numbered text was found to count")

    reference_section = next((body for level, heading, body in found
                              if heading == "References"), "")
    references = len(re.findall(r"(?m)^\s*\d+\.\s+\S", reference_section))

    figures = {int(n) for n in re.findall(r"(?m)^\*\*Figure (\d+)\.\*\*", text)}
    if not figures:
        figures = {int(n) for n in re.findall(r"(?i)\b(?:Fig\.|Figure)\s+(\d+)", text)}
    tables = set(re.findall(r"(?i)\bTable\s+(\d+)", text))

    measured = {
        "text words": body_words,
        "abstract words": words(abstract_prose),
        "references": references,
        "figures and tables": len(figures) + len(tables),
        "title words": len(title.split()),
    }

    # A bold run in body prose. The journal sets declaration labels and the
    # Figure N label in bold; a bold sentence in the text is the author's
    # standing objection and has had to be removed by hand every time.
    for heading, body in numbered:
        for match in re.finditer(r"\*\*(.+?)\*\*", body, re.S):
            run = " ".join(match.group(1).split())
            if not run.startswith("Figure "):
                problems.append(f"bold text in section {heading!r}: {run[:60]!r}")

    if "<!-- scope-of-claim -->" not in text and re.search(
            r"(?i)\b(floor|ceiling|irreducible|fundamental limit|sets the limit)\b",
            title + abstract_prose):
        problems.append(
            "the title or abstract states a bound but there is no scope-of-claim "
            "paragraph; a referee rejected this manuscript once on exactly that"
        )

    return measured, notes, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--built", type=Path, default=BUILT)
    args = parser.parse_args(argv)

    if not args.built.exists():
        print(f"{args.built} does not exist; run paper/build_manuscript.py first")
        return 2

    measured, notes, problems = measure(args.built.read_text(encoding="utf-8"))

    print(f"{args.built}\n")
    over = []
    for name, limit in LIMITS.items():
        value = measured[name]
        status = "ok" if value <= limit else "OVER by %d" % (value - limit)
        if value > limit:
            over.append(f"{name}: {value} against a limit of {limit}")
        print(f"  {name:<22} {value:>6}   limit {limit:<6} {status}")
    for note in notes:
        print(f"  {note}")

    if over:
        problems = [f"over the journal's limit -- {item}" for item in over] + problems
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print("  - " + problem)
        return 1
    print("\nwithin every stated limit, and structured as the journal asks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

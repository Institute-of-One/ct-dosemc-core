"""Everything a person had to find by hand in a companion paper, checked instead.

    python paper/presubmission_check.py
    python paper/presubmission_check.py --strict     # warnings fail too

Every check below corresponds to a defect that reached a built manuscript, an
uploaded file or an editorial office in IORN-002 to IORN-008. None of them are
hypothetical, and none were caught by reading carefully -- careful reading is what
missed them.

The checks run against ``paper/build/manuscript.md`` and the written ``.docx``,
never against the source alone. A source-line scan misses every span that straddles
a line break, and page furniture exists only in the artefact that reaches the
editor: that is the root cause of the one pre-review return this programme has had
on format.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

PAPER = Path(__file__).resolve().parent
REPO = PAPER.parent
FROZEN = PAPER / "frozen"
FIGURES = PAPER / "figures"
SOURCE = PAPER / "manuscript.md"
BUILT = PAPER / "build" / "manuscript.md"
DOCX = PAPER / "build" / "manuscript.docx"

sys.path.insert(0, str(PAPER))
import collect_figures  # noqa: E402

#: The pre-submission inquiry: a copy of the paper's claims that lives outside the
#: build and therefore drifts. It already did once -- rewritten around a floor, the
#: paper left an inquiry still quoting the correlation and the median ratio that had
#: been the headline the week before.
INQUIRY = REPO / "docs" / "pmb_inquiry_send.txt"

#: PMB's text block, in inches.
TEXT_WIDTH_IN = 6.5
TEXT_HEIGHT_IN = 8.7
#: Below this, a figure drawn wide and scaled down takes its type under 6 pt.
MIN_SCALE = 0.70

errors: list[str] = []
warnings: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def warn(message: str) -> None:
    warnings.append(message)


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def _manifest() -> dict:
    return json.loads((FROZEN / "manifest.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- text


def check_control_characters(built: str) -> None:
    """A scripted edit once turned ``\\times`` into a literal tab inside an abstract."""
    stray = {
        hex(ord(character))
        for character in built
        if ord(character) < 32 and character not in "\n\t"
    }
    if stray:
        fail(f"control characters in the built manuscript: {sorted(stray)}")


def check_emphasis(built: str) -> None:
    """Bold does one job: run-in headings. It had accumulated on ordinary terms.

    The reference list is excluded. A bold volume number is bibliographic style,
    not emphasis, and flagging twenty of them buries the one that matters.
    """
    body = built.split("## References")[0]
    for match in re.finditer(r"\*\*(.+?)\*\*", body, flags=re.S):
        span = match.group(1)
        line_start = body.rfind("\n", 0, match.start()) + 1
        prefix = body[line_start : match.start()].strip()
        # A numbered list item opening with a bold term is a run-in heading too:
        # "1. **a single factor** for the whole cohort" labels the item, it does
        # not shout inside a sentence.
        is_run_in = (
            prefix in {"", "-", "*", ">"}
            or prefix.endswith("|")
            or re.fullmatch(r"\d+\.", prefix) is not None
        )
        if is_run_in:
            continue
        if len(span) > 60:
            fail(f"a bold span of {len(span)} characters mid-sentence: {span[:50]!r}")
        else:
            warn(f"bold mid-sentence, not a run-in heading: {span!r}")


def check_markers_resolved(built: str) -> None:
    """An unresolved marker means the build did not run, or ran and was ignored.

    Comments are stripped first: the source carries a comment explaining the marker
    convention, and the example inside it is not an unresolved number.
    """
    opened = len(re.findall(r"\[\[results:", _strip_comments(built)))
    if opened:
        fail(f"{opened} unresolved [[results:...]] marker(s) in the built manuscript")


def check_no_typed_numbers(source: str, built: str) -> None:
    """A metric typed as digits is a number that can drift from the run.

    Checked against the source, where a literal means someone typed it; the built
    file legitimately contains every one of these as resolved text.
    """
    metrics = _manifest()["metrics"]
    prose = _strip_comments(source)
    for name, value in metrics.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        for digits in (2, 3, 4):
            literal = f"{value:.{digits}f}".rstrip("0").rstrip(".")
            if len(literal) < 4:
                continue
            if re.search(rf"(?<![\d.]){re.escape(literal)}(?![\d])", prose):
                fail(
                    f"{name} appears in paper/manuscript.md as the literal {literal!r}; "
                    f"use a [[results:...]] marker"
                )
                break


# ---------------------------------------------------------------------- evidence


def check_frozen_is_current() -> None:
    """The paper must quote the freeze, and the freeze must match results/."""
    sys.path.insert(0, str(PAPER))
    import freeze  # noqa: PLC0415

    if freeze.freeze(check_only=True) != 0:
        fail("paper/frozen/ is stale; run paper/freeze.py")


def check_the_defective_file_is_not_cited(source: str, built: str) -> None:
    """figure4_y_axis.json is the one number here that must never reach the paper.

    Its y-axis is not an exam dose. It is superseded by figure4_stats.json, which
    declares usable_for_figure4, and the freeze names it excluded -- but a marker
    or a sentence could still reach around the freeze and name it.
    """
    for label, text in (("source", source), ("built", built)):
        if "figure4_y_axis" in text:
            fail(
                f"the {label} manuscript names figure4_y_axis.json, which carries the "
                f"mid-scan defect and is not citable"
            )
    stats = json.loads((FROZEN / "figure4_stats.json").read_text(encoding="utf-8"))
    if not stats.get("usable_for_figure4"):
        fail("the frozen figure4_stats.json does not declare usable_for_figure4")


def check_series_account_for_one_another() -> None:
    """Eligible = scaled + omitted, and recorded + reconstructed = scaled."""
    metrics = _manifest()["metrics"]
    if metrics["n_scaled"] + metrics["n_omitted_no_ctdivol"] != metrics["n_eligible"]:
        fail(
            f"{metrics['n_eligible']} eligible series do not decompose into "
            f"{metrics['n_scaled']} scaled and {metrics['n_omitted_no_ctdivol']} omitted"
        )
    if metrics["n_recorded"] + metrics["n_reconstructed"] != metrics["n_scaled"]:
        fail(
            f"{metrics['n_scaled']} scaled series do not decompose into "
            f"{metrics['n_recorded']} recorded and {metrics['n_reconstructed']} "
            f"reconstructed"
        )


def check_author_block(built: str) -> None:
    """Title, author, the canonical affiliation, e-mail and ORCID -- all present.

    The manuscript went from title straight to abstract and carried no author block at
    all, which was found only by extracting the text of the built PDF and looking for the
    affiliation. PMB is submitted under single-anonymous review here, so the identity
    belongs on the manuscript.

    The affiliation is asserted character for character. Crossref carries
    "Institute of One, LISIT Co., Ltd., Tokyo 150-0044, Japan" for the author's published
    work, and a second ordering of the same address reads to an affiliation-matching
    system as a second affiliation.
    """
    head = built.split("## Abstract")[0]
    flat = " ".join(head.split())
    for what, value in (
        ("the author's name", "Shuji Yamamoto"),
        ("the canonical affiliation", "Institute of One, LISIT Co., Ltd., Tokyo 150-0044, Japan"),
        ("a corresponding e-mail", "yamamoto@lisit.jp"),
        ("an ORCID", "0000-0001-9211-1071"),
    ):
        if value not in flat:
            fail(f"the manuscript's title block is missing {what}: {value!r}")
    if "150-0044 Tokyo" in flat:
        fail(
            "the affiliation gives the postcode before the city; Crossref carries "
            "'Tokyo 150-0044', and two orderings read as two affiliations"
        )


def check_code_is_reachable(built: str) -> None:
    """IOP's data availability statement: the heading, the placement, the wording, a DOI.

    IOP Publishing has required a data availability statement in every article since 2022.
    It must sit under the heading 'Data availability', after the acknowledgements, and use
    one of the publisher's template forms. The locator matters as much as the wording: a
    companion paper was submitted saying the software was "in this repository" and naming
    no repository, and nothing else in the package carried a URL either. "this repository"
    is neither a URL nor a DOI.
    """
    section = re.search(
        r"^##\s*Data availability[^\n]*$(.*?)(?=^##\s|\Z)", built, flags=re.M | re.S
    )
    if section is None:
        fail(
            "the manuscript has no 'Data availability' section; IOP requires one, under "
            "that heading, in every article"
        )
        return
    text = " ".join(section.group(1).split())

    headings = re.findall(r"^##\s*(.+?)\s*$", built, flags=re.M)
    names = [h.lower() for h in headings]
    if (
        "acknowledgements" in names
        and "data availability" in names
        and names.index("data availability") < names.index("acknowledgements")
    ):
        fail("'Data availability' must come after 'Acknowledgements', as IOP asks")

    # One of IOP's template openings, quoted from the publisher's data policy.
    templates = (
        "The data that support the findings of this study are openly available",
        "The data that support the findings of this study will be openly available",
        "The data that support the findings of this study are available upon reasonable",
        "All data that support the findings of this study are included within the article",
        "No new data were created or analysed in this study",
    )
    if not any(t.lower() in text.lower() for t in templates):
        fail(
            "the data availability statement does not open with one of IOP's template "
            "forms, which the publisher's data policy requires"
        )

    if not re.search(r"https?://|doi\.org|doi:", text):
        fail(
            "the data availability statement names no URL or DOI: a reviewer cannot reach "
            "the software from the manuscript"
        )
    elif not re.search(r"10\.\d{4,9}/\S+", text):
        fail(
            "the data availability statement carries a URL but no DOI. A repository URL "
            "is not an archive: it moves, and the version a reviewer fetches is not the "
            "version the results came from"
        )


# ----------------------------------------------------------------------- figures


def check_figures(built: str) -> None:
    """Registered, named in the prose, captioned once, and fitting the page."""
    if collect_figures.collect(check=True) != 0:
        fail("the collected figures are out of date; run paper/collect_figures.py")

    captions = collect_figures.captions()
    for number, (name, _) in sorted(collect_figures.FIGURE_SOURCES.items()):
        if not re.search(rf"\bfigs?(?:ure)?\.?\s*{number}(?!\d)", built, re.I):
            fail(f"Figure {number} is never named in the prose, so it is never placed")

        caption = captions.get(number, "")
        if caption and built.count(caption[:60]) > 1:
            fail(f"Figure {number}'s caption appears more than once in the manuscript")

        path = FIGURES / name
        if not path.exists():
            continue
        try:
            from PIL import Image  # noqa: PLC0415
        except ImportError:
            warn("Pillow is not installed; figure dimensions were not checked")
            return
        with Image.open(path) as image:
            width_px, height_px = image.size
            dpi = (image.info.get("dpi") or (300, 300))[0] or 300
        width_in, height_in = width_px / dpi, height_px / dpi
        scale = min(1.0, TEXT_WIDTH_IN / width_in)
        if scale < MIN_SCALE:
            warn(
                f"Figure {number} is {width_in:.2f} in wide and prints at "
                f"{scale:.0%}, taking its type down with it"
            )
        if height_in * scale > TEXT_HEIGHT_IN:
            fail(
                f"Figure {number} prints {height_in * scale:.2f} in tall, taller than "
                f"the text block; it will be cut across two pages"
            )


#: Words that turn a measurement into a statement about everything of its kind. The list is
#: short on purpose: these are the words that appeared in the title and abstract of
#: this manuscript's title and abstract, not every word that could ever overreach.
_BOUNDING_WORDS = (
    "floor", "ceiling", "irreducible", "fundamental limit", "cannot be improved",
    "no better than", "any index", "all index",
)

#: The marker that points at the sentence delimiting the claim. An HTML comment, so it
#: survives into paper/build/manuscript.md and vanishes from the .docx.
_SCOPE_MARKER = "<!-- scope-of-claim -->"


def check_a_bounding_claim_declares_its_scope(source: str, built: str) -> None:
    """A paper that claims a limit must say, in the text, what the limit is over.

    The question this exists for is: a limit on what? This study cross-validates five
    conversions that it chose, which bounds those five. A title of the form "a measured
    floor on index-based organ dose estimation" is a statement about every index-based
    conversion there is or could be, and the distance between the two is not something a
    reader should have to work out for themselves. Peer review will ask, and it is a much
    cheaper question to answer before submission than after.

    Whether a given sentence justifies a given claim is not computable and this check does
    not pretend otherwise. What it does is refuse to let the question go unasked: if a
    bounding word reaches the title or the abstract, the source must carry a paragraph
    marked ``<!-- scope-of-claim -->`` that says what the bound was measured over, and that
    paragraph must survive into the built manuscript. Writing it is the work; the gate only
    makes its absence impossible to miss.
    """
    head = built[: built.find("\n## ") if "\n## " in built else len(built)]
    found = [word for word in _BOUNDING_WORDS if word in head.lower()]
    if not found:
        return

    if _SCOPE_MARKER not in source:
        fail(
            f"the title or abstract claims a bound ({', '.join(found)}) and no paragraph "
            f"is marked {_SCOPE_MARKER}. Say in the text what the bound was measured over "
            f"-- which conversions, which cohort -- or narrow the claim to it. A bound is "
            f"over the things that were varied, and a title that speaks for more than that "
            f"is a claim the measurement does not carry"
        )
        return

    paragraph = source.split(_SCOPE_MARKER, 1)[1].lstrip().split("\n\n", 1)[0]
    carried = _strip_comments(paragraph).strip()
    if len(carried) < 80:
        fail(
            f"the paragraph marked {_SCOPE_MARKER} is {len(carried)} characters; it is "
            f"meant to delimit the claim, not to satisfy the check"
        )
        return

    opening = re.sub(r"\[\[.*?\]\]", "", carried)[:60].strip()
    if opening and opening not in _strip_comments(built):
        fail(
            f"the paragraph marked {_SCOPE_MARKER} does not reach the built manuscript, so "
            f"the claim is bounded only in the source a reader never sees"
        )


def check_figures_are_first_cited_in_order(built: str) -> None:
    """Figure n must be first named before figure n+1.

    This manuscript did it: the Results cited "table 1 and figure 6" before figure 4 and
    figure 5 were mentioned at all, so a reader met figure 6 first and the numbering served
    the order the figures were made rather than the order they are read.
    ``check_figures`` above requires every figure to be named somewhere and captioned once,
    which this manuscript satisfied, and says nothing about the order -- a check can be
    green and a reader still lost.
    """
    first: dict[int, int] = {}
    for match in re.finditer(r"\bfigs?(?:ure)?\.?\s*(\d+)(?!\d)", built, re.I):
        number = int(match.group(1))
        first.setdefault(number, match.start())

    cited = sorted(first)
    out_of_order = [
        (a, b) for a, b in zip(cited, cited[1:]) if first[a] > first[b]
    ]
    for earlier, later in out_of_order:
        fail(
            f"figure {later} is first named before figure {earlier}; figures must be "
            f"first cited in numerical order, or they are numbered for the author and "
            f"not for the reader"
        )


def check_no_figure_is_renumbered_on_the_way_in(built: str) -> None:
    """A figure copied from the pipeline keeps the number drawn into its pixels.

    ``collect_figures`` renames the file; it cannot repaint the image. This manuscript
    went out with figure 6 carrying "Figure 5  Scan-covering organ dose by vendor" drawn
    across the top of it, because the pipeline that produced it called it figure 5 and the
    copy into paper/figures/ changed only the filename. A reader sees one number above the
    image and a different one in the caption below, and has no way to tell which is right.

    There is no OCR here, and installing one to read a number we already know would be the
    wrong fix. The source filename carries the number the drawing code used, and a
    disagreement between that and the number the manuscript gives it is the defect itself.
    """
    for number, (_name, source) in sorted(collect_figures.FIGURE_SOURCES.items()):
        if not source:
            continue
        drawn = re.search(r"fig(?:ure)?[_\- ]?(\d+)", Path(source).name, re.I)
        if drawn and int(drawn.group(1)) != number:
            fail(
                f"figure {number} is copied from {source}, which was drawn as figure "
                f"{drawn.group(1)}: the file is renamed but the title inside the image is "
                f"not, so the manuscript prints two different numbers for one figure. "
                f"Redraw it with the number it has here, or with no number at all"
            )


def check_every_figure_image_has_been_looked_at() -> None:
    """Each image must be recorded as seen, by its hash, since it last changed.

    This is the one check here that does not describe a defect; it describes how three of
    them escaped. Figure 4 went out with its legend running off the left edge of the
    canvas, a paragraph of the caption repeated inside the image, and "IORN-006" and
    "IORN-007" -- this programme's own internal identifiers -- printed on its axes.
    No check in this file could have seen any of that, and no check ever will:
    they are visible, not computable. What is computable is whether anybody opened the
    file after it last changed.

    So the ledger records a hash per figure. Change the image and the hash stops matching,
    the gate fails, and the only way through it is to open the image and record what was
    seen. ``--strict`` is not needed: an unreviewed figure is a failure, because the
    looking is the check.
    """
    import hashlib

    ledger_path = PAPER / "figures_reviewed.json"
    ledger = {}
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")).get("figures", {})

    for number, (name, _source) in sorted(collect_figures.FIGURE_SOURCES.items()):
        path = FIGURES / name
        if not path.exists():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entry = ledger.get(name)
        if entry is None:
            fail(
                f"figure {number} ({name}) has never been recorded as looked at; open it, "
                f"then add it to paper/figures_reviewed.json with sha256 {digest[:16]}..."
            )
        elif entry.get("sha256") != digest:
            fail(
                f"figure {number} ({name}) has changed since it was last looked at on "
                f"{entry.get('reviewed')}; open it again and update "
                f"paper/figures_reviewed.json to sha256 {digest[:16]}..."
            )


# -------------------------------------------------------------------- references


def check_references(source: str) -> None:
    """Harvard: every citation resolves, every entry is cited, alphabetical, traceable.

    Physics in Medicine & Biology requires the Harvard alphabetical style exclusively, so
    this checks author-year rather than the numbering it used to check. Markers are
    stripped before citations are counted: a marker path may index a list --
    ``...range[0]`` -- which a numbered-citation scan read as a citation of reference
    zero, and which an author-year scan would ignore anyway.
    """
    prose = re.sub(r"\[\[results:.+?\]\]", "", _strip_comments(source), flags=re.S)
    body, _, tail = prose.rpartition("## References")
    if not body:
        fail("the manuscript has no '## References' section")
        return

    if re.search(r"(?<![\w.])\[\d+(?:\s*,\s*\d+)*\]", body):
        fail(
            "a numbered citation is still in the body; PMB requires Harvard "
            "(alphabetical) references exclusively"
        )

    # An entry begins at the left margin with a surname and initials, and carries a year.
    entries = [entry.strip() for entry in re.split(r"\n\s*\n", tail.strip()) if entry.strip()]
    listed: list[tuple[str, str]] = []
    for entry in entries:
        match = re.match(
            r"([A-Z][A-Za-z\u00C0-\u024F'\-]+)\b.*?\b((?:19|20)\d{2}[ab]?)\b",
            " ".join(entry.split()),
        )
        if match is None:
            fail(f"a reference entry has no leading surname and year: {entry[:70]!r}")
            continue
        listed.append((match.group(1), match.group(2)))
    if not listed:
        fail("the reference list is empty")
        return

    surnames = [surname for surname, _ in listed]
    if surnames != sorted(surnames, key=str.casefold):
        out_of_order = [
            f"{b} after {a}"
            # strict=False on purpose: the tail is one shorter, which is the point
            for a, b in zip(surnames, surnames[1:], strict=False)
            if b.casefold() < a.casefold()
        ]
        fail(f"the reference list is not in alphabetical order: {out_of_order}")

    # Every (surname, year) in the list must be cited, and every citation must resolve.
    flat = " ".join(body.split())
    uncited = [
        f"{surname} {year}"
        for surname, year in listed
        # The year may sit in its own brackets, as in "Turner *et al* (2009)", so the
        # span between the surname and the year has to be allowed to contain them.
        if not re.search(rf"\b{re.escape(surname)}\b.{{0,40}}?{re.escape(year)}", flat)
    ]
    if uncited:
        fail(f"listed but never cited: {uncited}")

    years = {year for _, year in listed}
    cited_years = set(re.findall(r"\b((?:19|20)\d{2}[ab]?)\b", flat))
    dangling = sorted(
        y for y in cited_years - years if re.search(rf"\({{0,1}}[A-Z][^()]*{y}\)", flat)
    )
    if dangling:
        warn(f"a year appears in a citation but in no reference entry: {dangling}")

    # A reference must be traceable. A DOI is the usual way; a report or a
    # standard often has none, and for those the issuing body and place stand in.
    # What is not acceptable is an entry a reader cannot follow to anything, which
    # is the shape a fabricated reference takes.
    untraceable = [
        entry.split(" 20")[0][:48]
        for entry in entries
        if "doi" not in entry.lower() and "(" not in entry
    ]
    if untraceable:
        warn(
            f"reference(s) with neither a DOI nor a publisher and place, so a "
            f"reader cannot follow them: {untraceable}"
        )

    words = len(re.findall(r"\b\w+\b", body))
    density = len(listed) / max(words, 1) * 1000
    if density < 2.0:
        warn(
            f"{len(listed)} references over {words} words is {density:.1f} per 1000; "
            f"a thin bibliography reads as a Note whatever the work behind it"
        )


# ------------------------------------------------------------------------- .docx


def check_inquiry(built: str) -> None:
    """The pre-submission inquiry must quote the paper it is inquiring about.

    It is the one copy of the argument that the build does not generate, so it is
    the one that goes stale. When the paper was rebuilt around a measured floor,
    the inquiry still argued the correlation and the median ratio, and still
    carried the title from two framings earlier. An editor reading it would have
    been told about a different manuscript.
    """
    if not INQUIRY.exists():
        warn("no pre-submission inquiry at docs/pmb_inquiry_send.txt")
        return
    letter = INQUIRY.read_text(encoding="utf-8")

    title = next((line[2:].strip() for line in built.splitlines() if line.startswith("# ")), "")
    if title:
        # Compare on normalised whitespace: the letter wraps, the heading does not.
        flat_letter = " ".join(letter.split()).lower()
        if " ".join(title.split()).lower().rstrip(".") not in flat_letter:
            fail("the inquiry does not quote the manuscript's current title")

    metrics = _manifest()["metrics"]
    # The figures the inquiry leads with must be the ones the paper reports.
    for name, spec in (
        ("ceiling_global_factor_median_pct", "{:.0f}%"),
        ("ceiling_per_organ_factor_median_pct", "{:.0f}%"),
        ("ceiling_scan_length_and_size_median_pct", "{:.0f}%"),
        ("variance_between_patient", "{:.0%}"),
        ("tg195_centre_abs_pct", "{:.3f}%"),
    ):
        rendered = spec.format(metrics[name])
        if rendered not in letter:
            fail(f"the inquiry does not carry {name} as {rendered}")

    # And must not still carry the framing the paper withdrew.
    for stale in ("How far an organ-weighted", "Pearson r = 0.66"):
        if stale in letter:
            fail(f"the inquiry still carries withdrawn wording: {stale!r}")


def check_docx_furniture() -> None:
    """The file the editor opens, not the markdown that produced it."""
    if not DOCX.exists():
        fail("paper/build/manuscript.docx has not been built")
        return
    with zipfile.ZipFile(DOCX) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
        parts = archive.namelist()
    # Line numbering is per journal, not universal. Medical Physics returns a
    # submission that lacks it; PMB's ScholarOne adds its own to the proof it builds,
    # so a file that brings its own arrives with two disagreeing columns of numbers.
    # build_docx.LINE_NUMBERS is the single place that decides, and this asserts the
    # .docx agrees with it rather than asserting one journal's rule for all of them.
    sys.path.insert(0, str(PAPER))
    import build_docx  # noqa: PLC0415

    carries = "lnNumType" in document
    if carries and not build_docx.LINE_NUMBERS:
        fail(
            "the .docx carries line numbering while build_docx.LINE_NUMBERS is False; "
            "PMB's submission system numbers the proof itself and the two sets disagree"
        )
    if build_docx.LINE_NUMBERS and not carries:
        fail("the .docx carries no line numbering, and this journal requires it")
    if not any(name.startswith("word/footer") for name in parts):
        fail("the .docx carries no footer, so no page numbers")
    if "cantSplit" not in document:
        warn("no table row is marked cantSplit; a row may break across a page")
    if "$" in re.sub(r"<[^>]+>", "", document):
        fail("a dollar sign survives in the .docx: an equation printed as LaTeX source")


# -------------------------------------------------------------------------- main


def check_generative_ai_is_declared(built: str) -> None:
    """IOP requires the use of generative AI to be disclosed in the Acknowledgements.

    The policy asks for the model and version and how it was used, and it names the
    Acknowledgements as the place. This manuscript went to PMB on 2026-09-01 with no
    such declaration anywhere in it, while every other paper in this programme carried
    one -- so it was an omission, not a decision. A missing disclosure is not a
    formatting slip: found after publication it is what a correction notice is for.
    """
    if not re.search(r"generative artificial intelligence|generative AI", built, re.I):
        fail(
            "no generative-AI declaration; IOP requires the model, its version and how "
            "it was used, disclosed in the Acknowledgements"
        )
        return
    section = re.search(
        r"^##\s*Acknowledge?ments[^\n]*$(.*?)(?=^##\s|\Z)", built, flags=re.M | re.S
    )
    if section is None or not re.search(
        r"generative artificial intelligence|generative AI", section.group(1), re.I
    ):
        fail(
            "the generative-AI declaration is not in the Acknowledgements, which is "
            "where IOP's policy puts it"
        )
        return
    if not re.search(r"\(([^)]*,\s*[^)]*)\)", section.group(1)):
        warn(
            "the generative-AI declaration names no model and vendor in brackets; "
            "IOP asks for the model and version"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true", help="warnings fail too")
    args = parser.parse_args(argv)

    check_frozen_is_current()
    check_series_account_for_one_another()

    if not SOURCE.exists():
        print("paper/manuscript.md has not been written yet.")
        print("Checks that need prose are pending; the evidence checks above ran.")
    else:
        source = SOURCE.read_text(encoding="utf-8")
        if not BUILT.exists():
            fail("paper/build/manuscript.md is missing; run paper/build_manuscript.py")
            built = ""
        else:
            built = BUILT.read_text(encoding="utf-8")
            check_control_characters(built)
            check_emphasis(built)
            check_markers_resolved(built)
            check_no_typed_numbers(source, built)
            check_the_defective_file_is_not_cited(source, built)
            check_author_block(built)
            check_generative_ai_is_declared(built)
            check_code_is_reachable(built)
            check_a_bounding_claim_declares_its_scope(source, built)
            check_figures(built)
            check_figures_are_first_cited_in_order(built)
            check_no_figure_is_renumbered_on_the_way_in(built)
            check_every_figure_image_has_been_looked_at()
            check_docx_furniture()
            check_inquiry(built)
        check_references(source)

    for message in warnings:
        print(f"  warn  {message}")
    for message in errors:
        print(f"  FAIL  {message}")
    print(f"\n{len(errors)} failures, {len(warnings)} warnings")
    if errors or (args.strict and warnings):
        return 1
    print("ready to submit" if SOURCE.exists() else "evidence checks pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

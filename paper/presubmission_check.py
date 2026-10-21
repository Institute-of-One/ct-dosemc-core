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
#: Named for the next venue, not for PMB: the letter sent on 2026-08-23 is parked beside it
#: as pmb_inquiry_sent_2026-08-23.txt and is a record, not a draft.
INQUIRY = REPO / "docs" / "inquiry_send.txt"

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


def _plain_prose(text: str) -> str:
    """Comments gone and emphasis markers turned into spaces.

    Both gates that read the built manuscript need this, and they needed it separately: "_"
    is a word character, so ``\\b`` never matches between "_" and the letter after it. A
    title reading "a measured _floor_" matched no bounding word, and "_figure 6_" was not a
    citation. Fixing one and not the other is how the two citation patterns drifted apart
    earlier, so there is one function.

    Only emphasis is removed, by Markdown's own rule that an underscore inside a word does
    not emphasise anything: removing every underscore turned ``figure4_stats.json``, a file
    this manuscript names, into ``figure4 stats.json`` and back into a citation of figure 4.
    """
    return re.sub(
        r"(?<![0-9A-Za-z])[_*]+|[_*]+(?![0-9A-Za-z])", " ", _strip_comments(text)
    )


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
#: short on purpose: these are the words that appeared in this manuscript's title and
#: abstract, not every word that could ever overreach.
#:
#: Matched on word boundaries against whitespace-normalised text. As plain substrings,
#: "all index" fired on "overall index" and "no better than" went unseen when the source
#: wrapped it across a line.
#: The optional trailing s below pluralises the last word, which is right for "floors" and
#: "fundamental limits" and wrong for "any index", so the irregular plurals are listed.
#: "bound" is on the list because the title was narrowed to use it. A word that this
#: manuscript's own claim rests on and the gate does not know is a gate renamed around.
_BOUNDING_WORDS = (
    "floor", "ceiling", "bound", "irreducible", "fundamental limit", "cannot be improved",
    "no better than", "any index", "all index", "any indices", "all indices",
    "any indexes", "all indexes",
)


def _title_and_abstract(built: str) -> str:
    """The title and the abstract: where a claim is made, rather than qualified.

    This was ``built[: built.find("\\n## ")]``, which stops at the first ``##`` heading --
    and the first ``##`` heading is ``## Abstract``. The result was the title alone, so a
    bound claimed in the abstract body was never seen. Stopping at the first heading that is
    *not* the abstract gives the two places the claim is actually made.
    """
    # Comments first: a heading inside one -- "<!-- ## Notes -->" -- would otherwise end the
    # scan before the abstract and let a claim in it through.
    built = _strip_comments(built)
    headings = list(re.finditer(r"^##\s+(.*)$", built, flags=re.M))
    title = built[: headings[0].start()] if headings else built

    # The title, plus the abstract section wherever it sits -- not everything up to it. Taking
    # the whole run meant a "## Keywords" section before the abstract was read as part of the
    # claim, and a keyword list that happens to contain "floor" demanded a scope paragraph.
    for index, heading in enumerate(headings):
        # Emphasis stripped from the heading too: "## **Abstract**" is an abstract.
        name = re.sub(r"[_*]+", "", heading.group(1)).strip().lower()
        if not name.startswith("abstract"):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(built)
        return title + built[heading.end(): end]
    return title

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

    Known limits, left here deliberately rather than papered over. The survival search
    traces the paragraph's *prose* into the build; what a ``[[...]]`` marker rendered to is
    not traced, because this file cannot know what the value should be --
    ``check_markers_resolved`` and ``check_no_typed_numbers`` are what cover the values. And
    the bounding-word list is a list: a claim made in words that are not on it goes unasked.
    Both are reasons to read the paragraph, which is the point of making you write one.
    """
    # Whitespace flattened so a phrase wrapped across a line is still one phrase, word
    # boundaries so "all index" does not fire on "overall index", and a trailing s so a title
    # that says "two floors" is not a way past the gate.
    head = " ".join(_plain_prose(_title_and_abstract(built)).lower().split())
    found = [
        word for word in _BOUNDING_WORDS
        if re.search(rf"\b{re.escape(word)}s?\b", head)
    ]
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

    # Split on the same blank-line rule the build is split on below. Cutting the source at a
    # literal "\n\n" while splitting the build at "\n\s*\n" meant a blank line carrying a
    # stray space swallowed the next paragraph into the scope text, and a correct manuscript
    # failed for a character nobody can see.
    paragraph = re.split(r"\n\s*\n", source.split(_SCOPE_MARKER, 1)[1].lstrip(), maxsplit=1)[0]
    carried = _strip_comments(paragraph).strip()
    # Measure the words, not the markers. Counting raw text let a paragraph made of
    # [[results:...]] markers clear an 80-character minimum while saying nothing itself.
    # re.S because a marker wrapped across a source line is still one marker.
    segments = [" ".join(part.split()) for part in re.split(r"\[\[.*?\]\]", carried, flags=re.S)]
    written = " ".join(segment for segment in segments if segment)
    # Characters and words both: eighty characters of one token is not a sentence, and the
    # paragraph is meant to say what the bound is over.
    if len(written) < 80 or len(written.split()) < 12:
        fail(
            f"the paragraph marked {_SCOPE_MARKER} has {len(written)} characters and "
            f"{len(written.split())} words of prose outside its interpolated values; it is "
            f"meant to delimit the claim, not to satisfy the check"
        )
        return

    # Require every substantial run of plain words to reach the build, not just the longest
    # one: a surviving fragment is not a surviving paragraph. The first sixty raw characters
    # were used before, which broke twice over -- a [[...]] marker is replaced by its value in
    # the build and left a double space behind in the needle, and the source's wrapping need
    # not match the build's -- so a correct manuscript was reported as a failure.
    # Paragraph by paragraph, not one flattened document: with the boundaries gone, two
    # halves of the paragraph sitting in different sections counted as a surviving paragraph.
    paragraphs = [
        " ".join(block.split())
        for block in re.split(r"\n\s*\n", _strip_comments(built))
        if block.strip()
    ]
    checkable = [segment for segment in segments if segment]
    if not [segment for segment in checkable if len(segment) >= 12]:
        # Not "could not be checked, carry on". An unverifiable claim-scope paragraph is a
        # failure, or the gate becomes a warning that nothing acts on.
        fail(
            f"the paragraph marked {_SCOPE_MARKER} is broken into fragments too short to "
            f"trace into the built manuscript; write it as prose so that its survival can "
            f"be checked"
        )
        return
    # One run, in order, with only a short interpolated value allowed between the passages.
    # Testing each passage on its own passed a build where both halves of the paragraph
    # existed in different sections, in the wrong order -- which is every passage present
    # and no paragraph at all.
    # The gap has to allow spaces: a marker can render as "38 to 40" or "5.2 mGy", and a
    # gap of "no whitespace" failed a correct manuscript for it.
    pattern = r".{0,80}?".join(re.escape(segment) for segment in checkable)
    if not any(re.search(pattern, paragraph) for paragraph in paragraphs):
        flat = " ".join(paragraphs)
        missing = next((s for s in checkable if s not in flat), None)
        detail = (
            f"the passage {missing[:40]!r} is not there"
            if missing
            else "its passages are there but not together and in order"
        )
        fail(
            f"the paragraph marked {_SCOPE_MARKER} does not reach the built manuscript "
            f"intact: {detail}. The claim is bounded only in the source a reader never sees"
        )


#: One figure citation, with every number it names: "figure 4", "figs. 4 and 5",
#: "figures 4-6".
#:
#: Commas are deliberately not a continuation. Three rounds of cross-review turned the comma
#: into an arms race: honour it and "In figure 1, 38 of 40 series pass" cites a figure 38
#: that does not exist; guard it with "requires an and" and "In figure 1, 12 and 28 series
#: were excluded" cites figures 12 and 28; drop the guard and a real "figures 1, 6" list
#: hides an out-of-order mention. Prose cannot be parsed reliably for this, so the citation
#: form this manuscript may use is narrowed instead: write "figures 1 and 6", not
#: "figures 1, 6". Narrowing it in a comment would only be a wish, so _COMMA_LIST enforces it.
#: Panel letters are allowed on every number -- this manuscript writes "figure 1b" and
#: "figure 5a" -- and a citation that carries one must still be read to its end: "figures
#: 1(a) and 6" stopped at the bracket and dropped figure 6's first mention.
#: One figure number with an optional panel letter: "4", "4b", "4(b)". The trailing lookahead
#: keeps the "a" of "and" from being taken for a panel.
_NUMBER = r"\d+\s*(?:\(\s*[a-z]\s*\)|[a-z](?![a-z]))?"
#: What continues a citation. A comma is not here: see _COMMA_LIST.
_JOIN = r"(?:&|and|or|to|through|vs\.?|/|-|–|—)"
#: The number list a citation can carry, built once so the two patterns below cannot drift
#: apart -- which they did the moment panel letters were added to one of them and not the
#: other, letting "figures 1a, 6" past the comma rule.
#: A joiner may be followed by a bare panel letter rather than a number -- "figures 1a-c and
#: 6" -- and stopping at the "c" dropped figure 6's first mention.
_PANEL_ONLY = r"(?:\(\s*[a-z]\s*\)|[a-z](?![a-z]))"
_NUMBER_LIST = rf"(?:{_NUMBER})(?:\s*{_JOIN}\s*(?:{_NUMBER}|{_PANEL_ONLY}))*"

#: The trailing boundary keeps a filename out of it: "figure4_stats.json" and "figure6.png"
#: are files this manuscript names in prose, not citations. A full stop followed by a letter
#: is an extension; a full stop followed by a space is the end of a sentence, and "figure 6."
#: is still a citation.
_FIGURE_CITATION = re.compile(
    rf"\b(?:figs?|figures?)\.?\s*({_NUMBER_LIST})(?!\w|\.\w)", re.I
)


#: A plural citation continued by a comma -- "figures 1, 6" -- which this file refuses to
#: parse and therefore refuses to accept. The plural keeps "In figure 1, 38 of 40 series
#: pass" out of it, where the comma introduces a count and the manuscript is correct. It is
#: not a complete separation: "In figures 1 and 2, 38 of 40 series pass" is refused too, and
#: that is deliberate, because nothing in the text says which of the two it is. Rewrite it.
#: The comma may also come after a list that parsed cleanly -- "figures 1 and 2, 6" -- where
#: the citation regex stops at the comma and figure 6's first mention is dropped in silence.
#: Singular too -- "fig. 1, 6" is as unparseable as "figs 1, 6" -- so the plural is no longer
#: what keeps "In figure 1, 38 of 40 series pass" out of it. What does is the number after the
#: comma: 38 is not one of this manuscript's figures and 6 is. A paper with 38 figures would
#: have that sentence flagged, and should rewrite it, because nothing in the text says which
#: of the two it is.
_COMMA_LIST = re.compile(rf"\b(?:figs?|figures?)\.?\s*{_NUMBER_LIST}\s*,\s*(\d+)", re.I)


def _numbers_cited(citation: str) -> list[int]:
    """Every figure a citation names, expanding ``4-6`` to 4, 5, 6.

    Panel letters are dropped: "1(a)" and "1b" are both figure 1.

    The split is built from :data:`_JOIN`, the same fragment the citation pattern is built
    from. Listing the separators again here is what broke it: a joiner added to one list and
    not the other left "1 or 2" unsplit and ``int()`` raised on a correct manuscript.
    """
    citation = re.sub(r"\(\s*[a-z]\s*\)|(?<=\d)\s*[a-z]\b", "", citation, flags=re.I)
    parts = re.split(rf"\s*({_JOIN})\s*", citation, flags=re.I)
    numbers = [int(parts[0])]
    for separator, value in zip((p.lower() for p in parts[1::2]), parts[2::2]):
        if not value.strip().isdigit():
            continue        # a bare panel letter: "1a-c" is still figure 1
        number = int(value)
        if separator in {"to", "through", "-", "–", "—"} and number > numbers[-1]:
            numbers.extend(range(numbers[-1] + 1, number + 1))
        else:
            numbers.append(number)
    return numbers


def check_figures_are_first_cited_in_order(built: str) -> None:
    """Figure n must be first named before figure n+1.

    This manuscript did it: the Results cited "table 1 and figure 6" before figure 4 and
    figure 5 were mentioned at all, so a reader met figure 6 first and the numbering served
    the order the figures were made rather than the order they are read.

    Known limits, after eighteen rounds of adversarial review and left here on purpose. A
    multi-letter panel group -- "figures 1(a-c)" written with the letters inside one bracket,
    or "1a,b" -- ends the citation at the group, so a number after it is not read. A figure of
    another work is excluded only when the reference that follows looks bibliographic
    ("of Sechopoulos et al", "of TG-195"); "figure 3 of the manual" is read as ours. Neither
    is a form this manuscript uses, and both are reasons the proof PDF still gets looked at.
    ``check_figures`` above requires every figure to be named somewhere and captioned once,
    which this manuscript satisfied, and says nothing about the order -- a check can be
    green and a reader still lost.
    """
    # Two things this got wrong before. "figs?(?:ure)?" cannot match "figures" at all, because
    # the optional s sits before "ure". And matching one number per citation reads "figures 6
    # and 7" as a citation of figure 6 only, so figure 7's first mention is invisible and a
    # manuscript that names it out of order passes. A citation names every number in its list,
    # and a range names the figures between its ends.
    #
    # Comments are stripped first: they survive into the built manuscript -- that is how the
    # scope marker gets there -- so an editorial note reading "check figure 9 before
    # submitting" would otherwise be read as a citation and fail a correct manuscript.
    # Numbers inside one citation are ordered by where they sit in it, not treated as
    # simultaneous: "see figures 2 and 1" puts figure 2 in front of figure 1 for a reader,
    # and giving both the same position made that invisible.
    # Only this manuscript's own figures. "figure 7 of Sechopoulos et al (2015)" is somebody
    # else's figure and ordering it against ours is meaningless; a number past the end of
    # FIGURE_SOURCES cannot be ours. A foreign figure whose number happens to fall inside our
    # range is still read as ours -- that one is not decidable from the text, and the manual
    # look at the proof is where it would be caught.
    ours = set(collect_figures.FIGURE_SOURCES)
    prose = _plain_prose(built)
    # "figure 7 of Sechopoulos et al (2015)" is somebody else's figure. Numbers past the end
    # of our own set are already ignored below; this catches the ones that collide with ours,
    # which was the remaining way to fail a correctly ordered manuscript.
    #
    # It has to be the shape of a bibliographic citation, not merely a capital letter after
    # "of" or "in": any capitalised word let "figure 3 in Section 4" and "figure 2 in Results"
    # be read as another paper's, which is a way to pass a manuscript that is out of order.
    foreign = re.compile(
        r"\s*(?:of|in|from)\s+(?:"
        r"[A-Z][\w.'-]*(?:\s+et\s+al\b|\s*\(\s*\d{4}|\s+\d{4}\b)"   # Sechopoulos et al (2015)
        r"|[A-Z]{2,}[-\s]?\d"                                        # TG-195
        r")"
    )
    for comma in _COMMA_LIST.finditer(prose):
        if int(comma.group(1)) not in ours:
            continue
        fail(
            f"a figure citation continued by a comma, {comma.group(0).strip()!r}: write "
            f"'and' instead. This file cannot tell a comma list from a citation followed by "
            f"a count, so the form is narrowed rather than guessed at"
        )
    first: dict[int, int] = {}
    for match in _FIGURE_CITATION.finditer(prose):
        if foreign.match(prose, match.end()):
            continue
        for offset, number in enumerate(_numbers_cited(match.group(1))):
            if number in ours:
                first.setdefault(number, match.start() * 1000 + offset)

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

    What this cannot do: once a source file carries no number -- which is the fix, and what
    ``vendor_organ_dose.png`` now is -- this check has nothing to compare and says nothing
    about whether a number is still painted inside the image. Only
    :func:`check_every_figure_image_has_been_looked_at`, and the person it obliges, covers
    that. The two are not alternatives.
    """
    for number, (_name, source) in sorted(collect_figures.FIGURE_SOURCES.items()):
        if not source:
            continue
        # Anchored to a token boundary: unanchored, the "fig" in "config2_figure6" matched
        # and the file was reported as drawn under figure 2.
        drawn = re.search(
            r"(?:^|[._\- ])fig(?:ure)?[._\- ]?(\d+)", Path(source).name, re.I
        )
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
            # Skipping it meant an empty paper/figures/ produced no findings at all, and
            # nothing to look at is not a figure that has been looked at.
            fail(
                f"figure {number} ({name}) is registered and not on disk; run "
                f"paper/collect_figures.py"
            )
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

    A letter that has been sent is a record and is not rewritten to match a manuscript that
    moved afterwards: the one sent to PMB on 2026-08-23 is kept at
    ``docs/pmb_inquiry_sent_<date>.txt`` and is not read here. This path is the inquiry for
    the venue the paper is going to next, and its absence is a warning rather than a failure
    because not every venue is asked first.
    """
    if not INQUIRY.exists():
        warn(f"no pre-submission inquiry drafted at {INQUIRY.relative_to(REPO)}")
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

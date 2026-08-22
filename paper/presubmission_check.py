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
    """Bold does one job: run-in headings. It had accumulated on ordinary terms."""
    for match in re.finditer(r"\*\*(.+?)\*\*", built, flags=re.S):
        span = match.group(1)
        line_start = built.rfind("\n", 0, match.start()) + 1
        prefix = built[line_start : match.start()].strip()
        is_run_in = prefix in {"", "-", "*", ">"} or prefix.endswith("|")
        if is_run_in:
            continue
        if len(span) > 60:
            fail(f"a bold span of {len(span)} characters mid-sentence: {span[:50]!r}")
        else:
            warn(f"bold mid-sentence, not a run-in heading: {span!r}")


def check_markers_resolved(built: str) -> None:
    """An unresolved marker means the build did not run, or ran and was ignored."""
    opened = len(re.findall(r"\[\[results:", built))
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


def check_code_is_reachable(built: str) -> None:
    """The data and code statement must name somewhere a reader can go.

    A companion paper was submitted saying the software was "in this repository"
    and naming no repository; nothing else in the package carried a URL either. A
    locator is a URL or a DOI. "this repository" is neither.
    """
    section = re.search(
        r"^##\s*Data and code[^\n]*$(.*?)(?=^##\s|\Z)", built, flags=re.M | re.S
    )
    if section is None:
        fail("the manuscript has no 'Data and code' section")
        return
    if not re.search(r"https?://|doi\.org|doi:", section.group(1)):
        fail(
            "the data and code statement names no URL or DOI: a reviewer cannot reach "
            "the software from the manuscript"
        )


# ----------------------------------------------------------------------- figures


def check_figures(built: str) -> None:
    """Registered, named in the prose, captioned once, and fitting the page."""
    if collect_figures.collect(check=True) != 0:
        fail("the collected figures are out of date; run paper/collect_figures.py")

    captions = collect_figures.captions()
    for number, (name, _) in sorted(collect_figures.FIGURE_SOURCES.items()):
        if not re.search(rf"\bFig(?:ure)?\.?\s*{number}\b", built):
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


# -------------------------------------------------------------------- references


def check_references(source: str) -> None:
    """Contiguous, all cited, none uncited, in order of first citation, with DOIs."""
    prose = _strip_comments(source)
    body, _, tail = prose.rpartition("## References")
    if not body:
        fail("the manuscript has no '## References' section")
        return

    listed = [int(number) for number in re.findall(r"^\s*(\d+)\.\s", tail, flags=re.M)]
    if listed != list(range(1, len(listed) + 1)):
        fail(f"the reference list is not numbered 1..n: {listed}")

    cited: list[int] = []
    for group in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", body):
        for number in group.split(","):
            value = int(number)
            if value not in cited:
                cited.append(value)

    if not cited:
        fail("no reference is cited in the body")
        return
    missing = sorted(set(cited) - set(listed))
    if missing:
        fail(f"cited but not listed: {missing}")
    uncited = sorted(set(listed) - set(cited))
    if uncited:
        fail(f"listed but never cited: {uncited}")
    if cited != sorted(cited):
        fail(f"references are not numbered in order of first citation: {cited}")

    without_doi = [
        number
        for number, entry in enumerate(
            re.findall(r"^\s*\d+\.\s+(.+?)(?=^\s*\d+\.\s|\Z)", tail, flags=re.M | re.S),
            start=1,
        )
        if "doi" not in entry.lower()
    ]
    if without_doi:
        warn(f"reference(s) with no DOI, so unverifiable as written: {without_doi}")

    words = len(re.findall(r"\b\w+\b", body))
    density = len(listed) / max(words, 1) * 1000
    if density < 2.0:
        warn(
            f"{len(listed)} references over {words} words is {density:.1f} per 1000; "
            f"a thin bibliography reads as a Note whatever the work behind it"
        )


# ------------------------------------------------------------------------- .docx


def check_docx_furniture() -> None:
    """The file the editor opens, not the markdown that produced it."""
    if not DOCX.exists():
        fail("paper/build/manuscript.docx has not been built")
        return
    with zipfile.ZipFile(DOCX) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
        parts = archive.namelist()
    if "lnNumType" not in document:
        fail("the .docx carries no line numbering")
    if not any(name.startswith("word/footer") for name in parts):
        fail("the .docx carries no footer, so no page numbers")
    if "cantSplit" not in document:
        warn("no table row is marked cantSplit; a row may break across a page")
    if "$" in re.sub(r"<[^>]+>", "", document):
        fail("a dollar sign survives in the .docx: an equation printed as LaTeX source")


# -------------------------------------------------------------------------- main


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
            check_code_is_reachable(built)
            check_figures(built)
            check_docx_furniture()
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

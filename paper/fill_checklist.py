"""Fill the journal's mandatory submission checklist from the build.

    python paper/fill_checklist.py

The submission guidelines require the RPT Submission Checklist to be completed
and uploaded as "Supplementary Material (only for review)"; an incomplete
submission is sent back to the author.

Every quantity on it -- title words, abstract words, text words, keywords,
references, figures and tables -- is a number the build already measures, and
the checklist is where a stale one would be least visible: it is a form, read
once, by someone who cannot check it. So none of them is typed here. They come
from check_rpt_limits.measure() on the built manuscript, which is the same
function the limits gate uses, so the form and the gate cannot disagree.

The template is kept as downloaded in paper/submission/ and never written to.
The filled copy is a derived artefact in paper/build/, like everything else.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import check_rpt_limits  # noqa: E402

TEMPLATE = PAPER / "submission" / "12194_RPT Submission Checklist_2025.xlsx"
OUTPUT = PAPER / "build" / "12194_RPT Submission Checklist_2025.xlsx"
BUILT = PAPER / "build" / "manuscript.md"

AUTHOR = "Shuji Yamamoto"

#: Row -> the measurement that answers it, from check_rpt_limits.measure().
QUANTITIES = {
    12: "title words",
    13: "abstract words",
    15: "text words",
    16: "references",
    17: "figures and tables",
}

#: Row -> (answer, comment). The comment is for an exceptional value, which is
#: what the sheet itself asks for.
PROPOSITIONS = {
    20: (True, ""),
    21: (True, ""),
    22: (
        True,
        "A4, 1.25 in side margins, double line spacing, continuous line "
        "numbers from the title page.",
    ),
    23: (True, "Original work. The submission history is given in the cover letter."),
    24: (True, ""),
    25: (
        True,
        "No published figure is reproduced. Figure 3 plots published numerical "
        "results from the cited task-group report, and the bowtie profiles used "
        "as model input are published measurements (CC BY 4.0), cited in the "
        "text.",
    ),
    26: (True, "Sole author; there are no coauthors to confirm."),
    27: (False, "Not applicable: this is a new submission to this journal."),
}


def fill(template: Path = TEMPLATE, output: Path = OUTPUT) -> int:
    import openpyxl  # noqa: PLC0415

    if not template.is_file():
        print(f"{template} is missing; download it from the journal's submission guidelines page")
        return 1
    if not BUILT.is_file():
        print(f"{BUILT} is missing; run paper/build_manuscript.py")
        return 1

    measured, notes, problems = check_rpt_limits.measure(BUILT.read_text(encoding="utf-8"))
    if problems:
        print("the manuscript does not pass its own limits check, so no checklist is written:")
        for problem in problems:
            print("  - " + problem)
        return 1

    keywords = next((note for note in notes if note.startswith("keywords:")), "")
    keyword_count = int(keywords.split()[1]) if keywords else 0

    workbook = openpyxl.load_workbook(template)
    sheet = workbook["Checklist"]

    sheet["C4"] = datetime.date.today().isoformat()
    sheet["C5"] = AUTHOR
    sheet["C8"] = "New"
    sheet["D8"] = (
        "New to this journal. The manuscript was previously submitted "
        "elsewhere; the history is given in the cover letter."
    )
    sheet["C9"] = "Research Article"

    for row, key in QUANTITIES.items():
        sheet.cell(row=row, column=3, value=measured[key])
    sheet["C14"] = keyword_count

    for row, (answer, comment) in PROPOSITIONS.items():
        sheet.cell(row=row, column=3, value=answer)
        if comment:
            sheet.cell(row=row, column=4, value=comment)

    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)

    print(f"wrote {output}")
    print(f"  date {sheet['C4'].value}, {AUTHOR}, New, Research Article")
    for row, key in QUANTITIES.items():
        minimum = sheet.cell(row=row, column=5).value
        print(f"  {key:<20} {measured[key]:>5}   (sheet row {row}, min {minimum})")
    print(f"  {'keywords':<20} {keyword_count:>5}")
    answered = sum(1 for answer, _ in PROPOSITIONS.values() if answer)
    print(
        f"  {answered} of {len(PROPOSITIONS)} propositions confirmed; "
        f"{len(PROPOSITIONS) - answered} marked not applicable with a comment"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template", type=Path, default=TEMPLATE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    return fill(args.template, args.output)


if __name__ == "__main__":
    raise SystemExit(main())

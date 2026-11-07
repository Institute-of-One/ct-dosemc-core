"""Every number Figure 1's caption prints must come back from the frozen file.

    python paper/check_figure1_caption.py

The manuscript's numbers are markers resolved at build time, and
``check_no_typed_numbers`` refuses a frozen metric typed into the prose as digits.
Captions are outside both: they are written once in ``paper/README.md`` and copied
into the document verbatim, so a caption is the one place in this paper where a
number can be typed and then drift from the run it describes.

Figure 1's caption prints thirteen of them -- the recorded CTDIvol, the range each
panel spans, the error no conversion beats, the two medians the selection rule
compares, how many series were eligible for that rule, how many organs the section
carries, and which slice of how many it is. The figure is redrawn by a rule that
can select a different series, which would leave every one of those false while
the figure itself looks fine.

So the caption is read, and each quantity is resolved from
``paper/frozen/figure1_ladder.json`` and ``manifest.json`` and compared with what
is printed, at the precision it is printed to. Nothing here is a spelling check:
a caption that has simply been reworded passes, and a caption carrying last run's
CTDIvol does not.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import collect_figures  # noqa: E402

FROZEN = PAPER / "frozen"
LADDER = FROZEN / "figure1_ladder.json"
MANIFEST = FROZEN / "manifest.json"

#: The figure the caption belongs to. Resolved from the sources table rather than
#: assumed, so that a later renumbering moves this with it.
FIGURE_NAME = "figure1_ladder.png"

#: A range may be set with a hyphen or an en dash, and which one it is says
#: nothing about whether the number is right. Reading only one of them made
#: this gate refuse a caption whose dashes had just been corrected.
DASH = r"[-‐–]"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _number(caption: str, pattern: str) -> float | None:
    found = re.search(pattern, caption)
    return float(found.group(1)) if found else None


def _integer(caption: str, pattern: str) -> int | None:
    found = re.search(pattern, caption)
    return int(found.group(1)) if found else None


WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def _word(caption: str, pattern: str) -> int | None:
    found = re.search(pattern, caption)
    return WORD_NUMBERS.get(found.group(1).lower()) if found else None


def expected() -> dict[str, float]:
    """What the caption should print, resolved from the frozen results."""
    ladder = _load(LADDER)
    manifest = _load(MANIFEST)
    organs = ladder["organs"]
    index = [o["organ_weighted_ctdivol_mgy"] for o in organs.values()]
    dose = [o["absorbed_dose_mgy"] for o in organs.values()]
    selection, section = ladder["selection"], ladder["slice"]
    best = min(
        manifest["metrics"][key]
        for key in manifest["metrics"]
        if key.startswith("ceiling_") and key.endswith("_median")
    )
    return {
        "ctdivol": ladder["series"]["ctdivol_mgy"],
        "index_low": min(index),
        "index_high": max(index),
        "dose_low": min(dose),
        "dose_high": max(dose),
        "best_median_error_percent": best * 100.0,
        "n_recorded": selection["n_with_recorded_ctdivol"],
        "chosen_median_ratio": selection["chosen_median_ratio"],
        "cohort_median_ratio": selection["cohort_median_of_series_medians"],
        "n_organs_on_section": section["n_organs_on_slice"],
        "n_organs_scored": ladder["series"]["n_organs_scored"],
        "z_index": section["z_index"],
        "n_slices": section["n_slices"],
    }


def printed(caption: str) -> dict[str, float | None]:
    """What the caption actually prints, read back out of it."""
    return {
        "ctdivol": _number(caption, r"recorded for the examination:\s*([\d.]+)\s*mGy"),
        "index_low": _number(caption, r"tube current[^:]*:\s*([\d.]+)" + DASH + r"[\d.]+\s*mGy"),
        "index_high": _number(caption, r"tube current[^:]*:\s*[\d.]+" + DASH + r"([\d.]+)\s*mGy"),
        "dose_low": _number(caption, r"same anatomy:\s*([\d.]+)" + DASH + r"[\d.]+\s*mGy"),
        "dose_high": _number(caption, r"same anatomy:\s*[\d.]+" + DASH + r"([\d.]+)\s*mGy"),
        "best_median_error_percent": _number(caption, r"median of\s*([\d.]+)\s*%"),
        "n_recorded": _integer(caption, r"one of the (\d+) carrying a CTDIvol recorded"),
        "chosen_median_ratio": _number(caption, r"\(([\d.]+)\s*against\s*[\d.]+\)"),
        "cohort_median_ratio": _number(caption, r"\([\d.]+\s*against\s*([\d.]+)\)"),
        "n_organs_on_section": _word(caption, r"organs scored,\s*(\w+)\s+of\s+\w+"),
        "n_organs_scored": _word(caption, r"organs scored,\s*\w+\s+of\s+(\w+)"),
        "z_index": _integer(caption, r"slice\s*(\d+)\s*of\s*\d+"),
        "n_slices": _integer(caption, r"slice\s*\d+\s*of\s*(\d+)"),
    }


#: How many decimals the caption prints each quantity to. The comparison is made
#: at that precision: 17.94 printed as 17.9 is correct, 17.8 is not.
DECIMALS = {
    "ctdivol": 1,
    "index_low": 0,
    "index_high": 0,
    "dose_low": 0,
    "dose_high": 0,
    "best_median_error_percent": 0,
    "chosen_median_ratio": 3,
    "cohort_median_ratio": 3,
}


def check(caption: str | None = None) -> int:
    if not LADDER.is_file() or not MANIFEST.is_file():
        print(f"{LADDER.name} or {MANIFEST.name} is missing; run paper/freeze.py")
        return 1
    if caption is None:
        numbers = {
            number
            for number, (name, _) in collect_figures.FIGURE_SOURCES.items()
            if name == FIGURE_NAME
        }
        if len(numbers) != 1:
            print(f"{FIGURE_NAME} is registered {len(numbers)} times in FIGURE_SOURCES")
            return 1
        captions = collect_figures.captions()
        number = numbers.pop()
        if number not in captions:
            print(f"figure {number} has no caption in paper/README.md")
            return 1
        caption = captions[number]

    want, have = expected(), printed(caption)
    problems: list[str] = []
    for name, value in want.items():
        found = have[name]
        if found is None:
            problems.append(f"{name}: the caption does not state it")
            continue
        decimals = DECIMALS.get(name)
        if decimals is None:
            if int(found) != int(value):
                problems.append(f"{name}: caption says {int(found)}, results say {int(value)}")
        elif round(found, decimals) != round(value, decimals):
            problems.append(
                f"{name}: caption says {found:.{decimals}f}, results say {value:.{decimals}f}"
            )

    if problems:
        print("Figure 1's caption disagrees with the frozen results:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"Figure 1's caption: {len(want)} quantities, all resolved from the results")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    return check()


if __name__ == "__main__":
    raise SystemExit(main())

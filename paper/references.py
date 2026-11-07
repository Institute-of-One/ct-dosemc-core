"""Resolve every reference and render the list in the journal's style.

    python paper/references.py              # refresh paper/frozen/references.json
    python paper/references.py --check      # resolve and compare, write nothing

Radiological Physics and Technology follows the National Library of Medicine
(Vancouver) style: citations are numbered in order of first appearance and the
list is in that order. The numbers are not written anywhere by hand --
``build_manuscript.py`` assigns them from the prose, so moving a paragraph
cannot leave a citation pointing at the wrong entry.

Nothing in the rendered entry is typed. Each one is built from the metadata
registered at doi.org, because a reference list typed by hand is a list nobody
resolved: a companion paper shipped a reference whose DOI pointed at a
different article, and another printed a journal name as
``Physics in Medicine &amp; Biology``.

That second defect is the reason this module does not print the registered
record as it stands. Registered metadata arrives with HTML entities, with
``<i>`` and ``<sub>`` left in titles, and sometimes with a whole name in the
family field. Markup and entities are decoded mechanically. Anything that looks
like a *wrong* registration -- an author with no given name, a title beginning
mid-word -- is refused, and may only be printed through
``reference_overrides.json``, where the correction is recorded together with the
registered value it corrects. If the publisher fixes the record, the override
stops matching and this script fails, rather than printing a correction that is
no longer true.

Two style decisions, recorded so that they are decisions and not oversights:

* The month is omitted. The guide's own example prints one, and NLM allows it,
  but the registered date is frequently the online-first date while the volume
  and issue belong to a later print issue: the engine reference here is
  registered 2009-10-02 and appeared in the November issue. Year, volume, issue
  and pages identify the article without that contradiction.
* Author lists follow NLM: all authors up to six, otherwise the first six and
  ``et al``. Several references here carry twelve or more.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Every entry point in this repository writes UTF-8 explicitly. Without it the
# first em dash in a reference title raises UnicodeEncodeError under the cp932
# console this work is done on -- and never on a GitHub runner, which is UTF-8,
# so the public CI would stay green over a script that cannot run for the author.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PAPER = Path(__file__).resolve().parent
SEED = PAPER / "reference_seed.json"
OVERRIDES = PAPER / "reference_overrides.json"
FROZEN = PAPER / "frozen" / "references.json"

CSL_ACCEPT = "application/vnd.citationstyles.csl+json"
USER_AGENT = "IORN-007 manuscript reference verification (mailto:yamamoto@lisit.jp)"

#: NLM lists every author up to this many, then the first this many and "et al".
MAX_AUTHORS = 6


class ReferenceError(RuntimeError):
    """A reference could not be resolved, or resolved to something unexpected."""


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def clean(text: str) -> str:
    """Decode the markup registered metadata arrives wrapped in.

    Entities and inline tags are an encoding, not an error, and are removed
    without comment. A defect in the registration itself is not handled here;
    it is refused in :func:`inspect` and corrected only through an override.
    """
    text = re.sub(r"</?(?:i|b|em|strong|sub|sup|scp|span)\b[^>]*>", "", text)
    text = html.unescape(text)
    # Registered titles arrive with typographic hyphens that are not hyphens:
    # one reference here carries U+2010 in "x-ray". They render as a slightly
    # wrong dash in Word and as mojibake in a plain-text export, so they are
    # folded to the ASCII hyphen. The en and em dashes are left alone: those are
    # deliberate punctuation in two of these titles.
    text = re.sub(r"[‐‑⁃−]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def issue_number(record: dict[str, Any]) -> str:
    """The issue, with the part marker some publishers register inside it removed.

    Medical Physics volume 36 issue 6 is registered as ``6Part1``, which prints
    as ``36(6Part1)``. The part is not part of the issue number, and dropping it
    cannot become wrong if the publisher corrects the record -- the pattern
    simply stops matching.
    """
    issue = clean(str(record.get("issue") or ""))
    return re.sub(r"\s*Part\s*\d+\s*$", "", issue, flags=re.I)


def initials(given: str) -> str:
    """``"D. W. O."`` -> ``"DWO"``; ``"Hans-Christian"`` -> ``"HC"``.

    Splitting on whitespace alone collapses ``F.R.`` to ``F``, which a companion
    paper printed.
    """
    return "".join(part[0].upper() for part in re.split(r"[\s.\-‐-―]+", given) if part)


def author_list(authors: list[dict[str, Any]], doi: str) -> str:
    names: list[str] = []
    for person in authors:
        family = clean(person.get("family") or "")
        given = clean(person.get("given") or "")
        if not family:
            literal = clean(person.get("literal") or person.get("name") or "")
            raise ReferenceError(
                f"{doi}: an author is registered without a family name "
                f"({literal!r}); correct it in reference_overrides.json"
            )
        if not given:
            raise ReferenceError(
                f"{doi}: author {family!r} is registered without a given name, so an "
                f"initial cannot be formed; correct it in reference_overrides.json"
            )
        names.append(f"{family} {initials(given)}")
    if not names:
        raise ReferenceError(f"{doi}: no authors registered")
    if len(names) > MAX_AUTHORS:
        names = names[:MAX_AUTHORS] + ["et al"]
    return ", ".join(names)


def inspect(title: str, doi: str) -> None:
    """Refuse a title that looks mis-registered rather than printing it."""
    if not title:
        raise ReferenceError(f"{doi}: no title registered")
    # "aLow-dose ..." -- a stray leading character, seen in a companion paper's
    # reference list. A single lower-case letter followed by a capital is not a
    # word in any of these titles.
    if re.match(r"^[a-z][A-Z]", title):
        raise ReferenceError(
            f"{doi}: the registered title begins {title[:12]!r}, which looks like a "
            f"stray leading character; correct it in reference_overrides.json"
        )
    if ("<" in title or ("&" in title and ";" in title)) and re.search(
        r"<[a-zA-Z/]|&[a-zA-Z#][a-zA-Z0-9]*;", title
    ):
        raise ReferenceError(f"{doi}: markup survived cleaning in {title!r}")


def fetch(doi: str) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://doi.org/" + doi,
        headers={"Accept": CSL_ACCEPT, "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise ReferenceError(f"{doi}: doi.org returned HTTP {error.code}") from error
    except Exception as error:  # noqa: BLE001 - network, JSON, anything
        raise ReferenceError(f"{doi}: {error}") from error


def page_range(record: dict[str, Any]) -> str:
    pages = clean(str(record.get("page") or "")) or clean(str(record.get("article-number") or ""))
    return pages.replace("-", "–")


def render(
    record: dict[str, Any], overrides: dict[str, Any], doi: str, item: dict[str, Any] | None = None
) -> tuple[str, int, str]:
    """One reference as the journal prints it, its year, and the title printed.

    The printed title is returned so that the caller can compare it with the
    title the author admitted. Comparing the *registered* title instead would
    make an override and a silent publisher edit indistinguishable: the override
    pins the registered value itself, here, and fails on its own if that moves.
    """
    fix = overrides.get(doi, {})

    title = record.get("title")
    if isinstance(title, list):
        title = title[0] if title else ""
    title = clean(title or "")
    if "title" in fix:
        if normalise(fix["title"]["registered"]) != normalise(title):
            raise ReferenceError(
                f"{doi}: the title override no longer matches the registered title "
                f"{title!r}; the publisher may have corrected it, so check and remove "
                f"the override"
            )
        title = fix["title"]["display"]
    else:
        inspect(title, doi)
    title = title.rstrip(".")

    authors = fix.get("authors") or author_list(record.get("author") or [], doi)

    issued = (record.get("issued") or {}).get("date-parts") or [[None]]
    year = issued[0][0]
    if not isinstance(year, int):
        raise ReferenceError(f"{doi}: no publication year registered")

    container = record.get("container-title")
    if isinstance(container, list):
        container = container[0] if container else ""
    container = clean(container or "")
    if "container" in fix:
        if normalise(fix["container"]["registered"]) != normalise(container):
            raise ReferenceError(
                f"{doi}: the journal-name override no longer matches the registered "
                f"{container!r}; check and remove the override"
            )
        container = fix["container"]["display"]

    kind = record.get("type") or ""
    url = "https://doi.org/" + doi.lower()

    if kind == "journal-article" and container:
        volume = clean(str(record.get("volume") or ""))
        issue = issue_number(record)
        pages = page_range(record)
        locator = f"{year}"
        if volume:
            locator += f";{volume}"
            if issue:
                locator += f"({issue})"
            if pages:
                locator += f":{pages}"
        elif pages:
            locator += f":{pages}"
        entry = f"{authors}. {title}. {container}. {locator}. {url}."
    elif kind == "software":
        version = clean(str(record.get("version") or ""))
        publisher = clean(str(record.get("publisher") or "")) or "Zenodo"
        version_part = f" Version {version}." if version else ""
        entry = f"{authors}. {title} [software].{version_part} {publisher}; {year}. {url}."
    else:
        publisher = clean(str(record.get("publisher") or ""))
        place = clean(str(record.get("publisher-place") or ""))
        where = f"{place}: {publisher}" if place and publisher else publisher
        tail = f" {where};" if where else ""
        # The report number is how a reader finds an AAPM report, and no part of
        # the registered record carries it. It comes from the seed, where it is
        # the author's own information rather than a correction to anyone's
        # metadata.
        series = clean(str((item or {}).get("series") or ""))
        # NLM places a report number after the date, not between the title and
        # the publisher, where it reads as "AAPM Report 96. AAPM; 2008."
        series_part = f" {series}." if series else ""
        entry = f"{authors}. {title}.{tail} {year}.{series_part} {url}."

    return re.sub(r"\s+", " ", entry).strip(), year, title


def resolve() -> list[dict[str, Any]]:
    seed = json.loads(SEED.read_text(encoding="utf-8"))["references"]
    overrides = {
        key: value
        for key, value in json.loads(OVERRIDES.read_text(encoding="utf-8")).items()
        if not key.startswith("_")
    }

    seen_keys: set[str] = set()
    out: list[dict[str, Any]] = []
    failures: list[str] = []

    for item in seed:
        key = item["key"]
        if key in seen_keys:
            failures.append(f"{key}: duplicate key in reference_seed.json")
            continue
        seen_keys.add(key)

        if "literal" in item:
            if not item.get("reason"):
                failures.append(f"{key}: a literal reference must record why it has no DOI")
                continue
            out.append(
                {
                    "key": key,
                    "doi": None,
                    "entry": clean(item["literal"]),
                    "year": None,
                    "literal": True,
                }
            )
            print(f"LITERAL  {key}  (no registered DOI: {item['reason'][:60]}...)")
            continue

        doi = item["doi"]
        try:
            record = fetch(doi)
            entry, year, printed_title = render(record, overrides, doi, item)
            if not item.get("title"):
                raise ReferenceError(
                    f"{doi}: reference_seed.json carries no admitted title, so the "
                    f"registered one would reach the page uncompared"
                )
            if normalise(item["title"]) != normalise(printed_title):
                raise ReferenceError(
                    f"{doi}: the title about to be printed is not the one admitted.\n"
                    f"    admitted: {item['title']}\n    to print: {printed_title}"
                )
            if item.get("year") and item["year"] != year:
                raise ReferenceError(
                    f"{doi}: registered year {year} does not match the admitted {item['year']}"
                )
        except ReferenceError as error:
            failures.append(str(error))
            print(f"FAILED   {key}  {error}")
            continue

        out.append({"key": key, "doi": doi, "entry": entry, "year": year, "literal": False})
        print(f"RESOLVED {key}  {entry[:96]}")

    if failures:
        joined = "\n  - ".join(failures)
        raise SystemExit(f"\n{len(failures)} reference(s) could not be used:\n  - {joined}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="resolve and compare with the frozen list; write nothing",
    )
    args = parser.parse_args(argv)

    resolved = resolve()
    payload = {"references": resolved}

    if args.check:
        if not FROZEN.exists():
            print(f"\n{FROZEN} does not exist; run without --check first")
            return 1
        current = json.loads(FROZEN.read_text(encoding="utf-8"))
        if current == payload:
            print(f"\n{len(resolved)} references resolved and identical to {FROZEN.name}")
            return 0
        print(f"\n{FROZEN.name} is out of date; run without --check")
        return 1

    FROZEN.parent.mkdir(parents=True, exist_ok=True)
    FROZEN.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"\n{len(resolved)} references written to {FROZEN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

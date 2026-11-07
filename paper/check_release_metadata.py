"""The version and the DOIs must agree everywhere they are written.

    python paper/check_release_metadata.py

The version, the release date and the two DOIs are written in several files, and
a gate that only looks at one of them is satisfied by a repository that
contradicts itself. This one found the first thing it looked at: pyproject.toml
carried version 0.1.0 while __init__.py, CITATION.cff and .zenodo.json all said
0.2.1, so the release the paper's DOI points at installs as 0.1.0.

It checks, it does not fix. Making the files agree is a release step; noticing
that they do not is this.

Two DOIs, and they are not interchangeable:

* the **version** DOI identifies one release, and is what the manuscript cites,
  because a result belongs to the release it was computed with;
* the **concept** DOI resolves to the latest release, and is what CITATION.cff
  and the README badge carry.

Putting the concept DOI in the manuscript is the accident no other check stops:
it resolves, it is a real DOI for this software, and it is not the release the
numbers came from. So the two are compared against each other here, and the
manuscript's is resolved against the public record at Zenodo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PAPER = Path(__file__).resolve().parent
REPO = PAPER.parent

INIT = REPO / "ct_dosemc_core" / "__init__.py"
PYPROJECT = REPO / "pyproject.toml"
ZENODO = REPO / ".zenodo.json"
CITATION = REPO / "CITATION.cff"
BUILT = PAPER / "build" / "manuscript.md"

_DOI = re.compile(r"10\.5281/zenodo\.(\d+)")


def _version_from_init() -> str:
    found = re.search(r'^__version__\s*=\s*"([^"]+)"', INIT.read_text(encoding="utf-8"), re.M)
    if not found:
        raise SystemExit(f"{INIT} declares no __version__")
    return found.group(1)


def _zenodo_record(doi: str) -> dict | None:
    """The public record for a Zenodo DOI, or None if it cannot be fetched.

    The public records API, not the webhook's last response: a 409 from the hook
    means the record already exists, and reading it as a failure once led to two
    days of reporting that no DOI had been minted when both releases were
    archived all along.
    """
    match = _DOI.search(doi)
    if not match:
        return None
    try:
        request = urllib.request.Request(
            f"https://zenodo.org/api/records/{match.group(1)}",
            headers={"User-Agent": "IORN-007 release metadata check"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def check(offline: bool = False) -> list[str]:
    problems: list[str] = []
    version = _version_from_init()
    print(f"version in {INIT.name}: {version}")

    pyproject = PYPROJECT.read_text(encoding="utf-8")
    literal = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
    if literal:
        if literal.group(1) != version:
            problems.append(
                f"pyproject.toml declares version {literal.group(1)!r} and "
                f"__init__.py declares {version!r}"
            )
    elif 'dynamic = ["version"]' not in pyproject:
        problems.append("pyproject.toml neither declares a version nor reads one from the package")
    else:
        print("  pyproject.toml reads the version from the package")

    zenodo = json.loads(ZENODO.read_text(encoding="utf-8"))
    if zenodo.get("version") != version:
        problems.append(f".zenodo.json declares version {zenodo.get('version')!r}, not {version!r}")
    if "doi" in zenodo:
        problems.append(
            "a top-level 'doi' in .zenodo.json tells Zenodo the DOI was assigned "
            "elsewhere and stops it minting a version DOI for the release"
        )

    citation = CITATION.read_text(encoding="utf-8")
    cff_version = re.search(r"(?m)^version:\s*(\S+)", citation)
    if not cff_version:
        problems.append("CITATION.cff declares no version")
    elif cff_version.group(1).strip('"') != version:
        problems.append(f"CITATION.cff declares version {cff_version.group(1)!r}, not {version!r}")

    concept = re.search(r"(?m)^doi:\s*(\S+)", citation)
    if not concept:
        problems.append(
            "CITATION.cff carries no doi; it should carry the concept DOI, which "
            "resolves to the latest release"
        )
        concept_doi = None
    else:
        concept_doi = concept.group(1).strip('"')
        print(f"  concept DOI in CITATION.cff: {concept_doi}")

    if not BUILT.exists():
        problems.append(f"{BUILT} has not been built, so its DOI cannot be checked")
        return problems

    built = BUILT.read_text(encoding="utf-8")
    section = re.search(r"\*\*Data availability\.\*\*(.*?)(?=\n\s*\n\*\*|\Z)", built, re.S)
    if not section:
        problems.append("the built manuscript has no data availability statement")
        return problems
    cited = _DOI.search(section.group(1))
    if not cited:
        problems.append("the data availability statement cites no Zenodo DOI")
        return problems
    cited_doi = f"10.5281/zenodo.{cited.group(1)}"
    print(f"  version DOI cited by the manuscript: {cited_doi}")

    if concept_doi and cited_doi == concept_doi:
        problems.append(
            f"the manuscript cites {cited_doi}, which CITATION.cff carries as the "
            f"concept DOI. A concept DOI resolves to whatever the latest release is, "
            f"not to the release these numbers came from"
        )

    if offline:
        print("  (offline: the DOI was not resolved against Zenodo)")
        return problems

    record = _zenodo_record(cited_doi)
    if record is None:
        problems.append(
            f"{cited_doi} could not be read from the Zenodo records API, so nothing "
            f"here shows it resolves to a real release"
        )
        return problems

    recorded = (record.get("metadata") or {}).get("version")
    print(
        f"  Zenodo says that DOI is version {recorded!r}, "
        f"published {(record.get('metadata') or {}).get('publication_date')}"
    )
    if recorded != version:
        problems.append(
            f"the manuscript cites the archive of version {recorded!r} while this "
            f"working tree is version {version!r}. Either the release the paper "
            f"describes has moved on, or the citation has"
        )
    if concept_doi and record.get("conceptdoi") != concept_doi:
        problems.append(
            f"Zenodo records the concept DOI of that release as "
            f"{record.get('conceptdoi')!r}, and CITATION.cff carries {concept_doi!r}"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--offline", action="store_true", help="skip resolving the DOI against Zenodo"
    )
    args = parser.parse_args(argv)

    problems = check(offline=args.offline)
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print("  - " + problem)
        return 1
    print("\nthe version and both DOIs agree everywhere they are written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

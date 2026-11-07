"""Plant each disagreement the release-metadata check exists to catch.

    python -m unittest paper.test_release_metadata -v

The check found a real one the first time it ran: pyproject.toml said 0.1.0
while everything else said 0.2.1, so the release the paper's DOI points at
installed as 0.1.0.

Each case here writes a small repository into a temporary directory, damages one
file, and requires the check to report it. The undamaged copy must pass, and the
real repository is checked offline at the end, because the point of the network
call is to resolve the DOI and a test that needs Zenodo to be up is a test that
fails for reasons of its own.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import check_release_metadata as release  # noqa: E402

VERSION = "0.2.1"
CONCEPT = "10.5281/zenodo.22233152"
VERSIONED = "10.5281/zenodo.23537665"

INIT = f'__version__ = "{VERSION}"\n'
PYPROJECT = '[project]\nname = "x"\ndynamic = ["version"]\n'
ZENODO = json.dumps({"title": "x", "version": VERSION}, indent=2)
CITATION = (
    "cff-version: 1.2.0\n"
    "title: x\n"
    f"version: {VERSION}\n"
    'date-released: "2026-10-22"\n'
    f"doi: {CONCEPT}\n"
)
BUILT = (
    "# A title\n\n## Declarations\n\n"
    f"**Data availability.** Openly available at https://doi.org/{VERSIONED}.\n\n"
    "**Code availability.** The same archive.\n"
)

RECORD = {
    "doi": VERSIONED,
    "conceptdoi": CONCEPT,
    "metadata": {"version": VERSION, "publication_date": "2026-10-21"},
}


class Repository(unittest.TestCase):
    """A small repository of the shape check() reads, in a temporary directory."""

    files = {
        "init": INIT,
        "pyproject": PYPROJECT,
        "zenodo": ZENODO,
        "citation": CITATION,
        "built": BUILT,
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, **overrides):
        """Write the repository, with any named file replaced."""
        contents = dict(self.files, **overrides)
        paths = {
            "INIT": self.dir / "ct_dosemc_core" / "__init__.py",
            "PYPROJECT": self.dir / "pyproject.toml",
            "ZENODO": self.dir / ".zenodo.json",
            "CITATION": self.dir / "CITATION.cff",
            "BUILT": self.dir / "paper" / "build" / "manuscript.md",
        }
        for key, path in paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            text = contents[key.lower()]
            if text is None:
                continue
            path.write_text(text, encoding="utf-8")
        return paths

    def run_check(self, record=RECORD, **overrides):
        paths = self.write(**overrides)
        patches = {name: paths[name] for name in paths}
        with (
            mock.patch.multiple(release, **patches),
            mock.patch.object(release, "_zenodo_record", return_value=record),
        ):
            return release.check()


class TheConsistentCasePasses(Repository):
    def test_nothing_is_reported(self):
        self.assertEqual(self.run_check(), [])


class CatchesAVersionThatDisagrees(Repository):
    def test_pyproject_pins_a_different_version(self):
        problems = self.run_check(pyproject='[project]\nname = "x"\nversion = "0.1.0"\n')
        self.assertTrue(any("pyproject.toml declares version '0.1.0'" in p for p in problems))

    def test_pyproject_pinning_the_same_version_is_allowed(self):
        self.assertEqual(
            self.run_check(pyproject=f'[project]\nname = "x"\nversion = "{VERSION}"\n'), []
        )

    def test_pyproject_with_no_version_at_all(self):
        problems = self.run_check(pyproject='[project]\nname = "x"\n')
        self.assertTrue(any("neither declares a version" in p for p in problems))

    def test_zenodo_json_disagrees(self):
        problems = self.run_check(zenodo=json.dumps({"title": "x", "version": "0.2.0"}))
        self.assertTrue(any(".zenodo.json declares version" in p for p in problems))

    def test_citation_disagrees(self):
        problems = self.run_check(citation=CITATION.replace(VERSION, "0.2.0", 1))
        self.assertTrue(any("CITATION.cff declares version" in p for p in problems))

    def test_the_cited_archive_is_a_different_version(self):
        record = json.loads(json.dumps(RECORD))
        record["metadata"]["version"] = "0.2.0"
        problems = self.run_check(record=record)
        self.assertTrue(any("has moved on" in p for p in problems))


class CatchesADoiThatIsTheWrongKind(Repository):
    def test_the_manuscript_citing_the_concept_doi(self):
        # It resolves, it is a real DOI for this software, and it is not the
        # release the numbers came from. No other check stops this.
        problems = self.run_check(built=BUILT.replace(VERSIONED, CONCEPT))
        self.assertTrue(any("concept DOI" in p for p in problems))

    def test_citation_carrying_no_doi(self):
        problems = self.run_check(citation=CITATION.replace(f"doi: {CONCEPT}\n", ""))
        self.assertTrue(any("carries no doi" in p for p in problems))

    def test_zenodo_recording_a_different_concept_doi(self):
        record = json.loads(json.dumps(RECORD))
        record["conceptdoi"] = "10.5281/zenodo.99999999"
        problems = self.run_check(record=record)
        self.assertTrue(any("records the concept DOI" in p for p in problems))

    def test_a_top_level_doi_in_zenodo_json(self):
        # It tells Zenodo the DOI was assigned elsewhere, and Zenodo then stops
        # minting a version DOI for the release.
        problems = self.run_check(
            zenodo=json.dumps({"title": "x", "version": VERSION, "doi": CONCEPT})
        )
        self.assertTrue(any("stops it minting" in p for p in problems))

    def test_a_doi_that_does_not_resolve(self):
        problems = self.run_check(record=None)
        self.assertTrue(any("could not be read from the Zenodo records API" in p for p in problems))

    def test_a_manuscript_with_no_data_statement(self):
        problems = self.run_check(built="# A title\n\nNothing here.\n")
        self.assertTrue(any("no data availability statement" in p for p in problems))


class TheRealRepositoryAgrees(unittest.TestCase):
    def test_offline(self):
        self.assertEqual(release.check(offline=True), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

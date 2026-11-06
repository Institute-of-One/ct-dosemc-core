"""Plant each defect the reference checker exists to catch, and require a failure.

    python -m unittest paper.test_reference_checks -v

A clean run and a broken checker look identical, so the checker is not trusted
until it has refused a known defect. Two checkers in this programme were trusted
without this and let a planted defect through twice.

Every case here plants a *missing or contradicted claim*, not a rewording: a
checker that reads one word will pass a sentence rewritten around that word, and
a file-comparison cannot see it, because the file did change.

No network. The records are the shapes that actually arrive from doi.org,
including the two defective registrations found on 2026-11-07.
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

import references  # noqa: E402

GOOD_RECORD = {
    "type": "journal-article",
    "title": "Prospective estimation of organ dose in CT under tube current modulation",
    "container-title": "Medical Physics",
    "volume": "42",
    "issue": "4",
    "page": "1575-1585",
    "issued": {"date-parts": [[2015, 3, 30]]},
    "author": [
        {"family": "Tian", "given": "Xiaoyu"},
        {"family": "Li", "given": "Xiang"},
        {"family": "Segars", "given": "W. Paul"},
        {"family": "Frush", "given": "Donald P."},
        {"family": "Samei", "given": "Ehsan"},
    ],
    "DOI": "10.1118/1.4907955",
}

SEED_ENTRY = {
    "key": "tian2015",
    "doi": "10.1118/1.4907955",
    "title": "Prospective estimation of organ dose in CT under tube current modulation",
    "year": 2015,
}


def render(record, overrides=None, doi="10.1118/1.4907955", item=None):
    return references.render(record, overrides or {}, doi, item or SEED_ENTRY)


class RendersTheGoodCase(unittest.TestCase):
    """If the clean case did not pass, every failure below would be meaningless."""

    def test_the_undamaged_record_renders(self):
        entry, year, title = render(GOOD_RECORD)
        self.assertEqual(year, 2015)
        self.assertEqual(
            entry,
            "Tian X, Li X, Segars WP, Frush DP, Samei E. Prospective estimation of organ "
            "dose in CT under tube current modulation. Medical Physics. "
            "2015;42(4):1575–1585. https://doi.org/10.1118/1.4907955.",
        )

    def test_initials_do_not_collapse(self):
        # "D. W. O. Rogers" must not print as "Rogers D". A companion paper's
        # reference list did exactly that.
        self.assertEqual(references.initials("D. W. O."), "DWO")
        self.assertEqual(references.initials("Hans-Christian"), "HC")
        self.assertEqual(references.initials("W. Paul"), "WP")


class RefusesABrokenRegistration(unittest.TestCase):
    def test_an_author_without_a_given_name(self):
        record = json.loads(json.dumps(GOOD_RECORD))
        record["author"][2] = {"family": "Zhou Wang", "given": ""}
        with self.assertRaises(references.ReferenceError) as caught:
            render(record)
        self.assertIn("without a given name", str(caught.exception))

    def test_an_author_without_a_family_name(self):
        record = json.loads(json.dumps(GOOD_RECORD))
        record["author"][0] = {"literal": "Xiaoyu Tian"}
        with self.assertRaises(references.ReferenceError):
            render(record)

    def test_a_title_beginning_mid_word(self):
        record = json.loads(json.dumps(GOOD_RECORD))
        record["title"] = "aProspective estimation of organ dose in CT"
        with self.assertRaises(references.ReferenceError) as caught:
            render(record)
        self.assertIn("stray leading character", str(caught.exception))

    def test_a_record_with_no_year(self):
        record = json.loads(json.dumps(GOOD_RECORD))
        record["issued"] = {"date-parts": [[None]]}
        with self.assertRaises(references.ReferenceError):
            render(record)

    def test_a_record_with_no_title(self):
        record = json.loads(json.dumps(GOOD_RECORD))
        record["title"] = ""
        with self.assertRaises(references.ReferenceError):
            render(record)


class CleansWhatIsOnlyEncoding(unittest.TestCase):
    def test_an_entity_in_the_journal_name(self):
        record = json.loads(json.dumps(GOOD_RECORD))
        record["container-title"] = "Physics in Medicine &amp; Biology"
        entry, _, _ = render(record)
        self.assertIn("Physics in Medicine & Biology", entry)
        self.assertNotIn("&amp;", entry)

    def test_italics_left_in_a_title(self):
        record = json.loads(json.dumps(GOOD_RECORD))
        record["title"] = "Prospective estimation of <i>organ dose</i> in CT under tube current modulation"
        entry, _, printed = render(record)
        self.assertNotIn("<i>", entry)
        self.assertEqual(
            printed, "Prospective estimation of organ dose in CT under tube current modulation"
        )

    def test_a_typographic_hyphen_becomes_a_hyphen(self):
        record = json.loads(json.dumps(GOOD_RECORD))
        record["title"] = "Modeling x‐ray tube spectra"
        item = dict(SEED_ENTRY, title="Modeling x-ray tube spectra")
        entry, _, _ = render(record, item=item)
        self.assertIn("x-ray", entry)
        self.assertNotIn("‐", entry)

    def test_the_part_marker_leaves_the_issue(self):
        # Medical Physics 36(6) is registered as "6Part1" and printed as
        # "36(6Part1)" by anything that trusts the field.
        record = json.loads(json.dumps(GOOD_RECORD))
        record["issue"] = "6Part1"
        entry, _, _ = render(record)
        self.assertIn("42(6):", entry)
        self.assertNotIn("Part1", entry)


class HonoursAndPolicesOverrides(unittest.TestCase):
    """An override is a claim about the registered record, and expires with it."""

    REGISTERED = "CT Dose Index and Patient Dose: They AreNotthe Same Thing"
    CORRECT = "CT dose index and patient dose: they are not the same thing"

    def record(self, title):
        return {
            "type": "journal-article", "title": title, "container-title": "Radiology",
            "volume": "259", "issue": "2", "page": "311-316",
            "issued": {"date-parts": [[2011, 4, 18]]},
            "author": [{"family": "McCollough", "given": "Cynthia H."}],
            "DOI": "10.1148/radiol.11101800",
        }

    def override(self):
        return {"10.1148/radiol.11101800":
                {"title": {"registered": self.REGISTERED, "display": self.CORRECT}}}

    def test_the_override_applies_while_the_record_is_still_wrong(self):
        entry, _, printed = references.render(
            self.record(self.REGISTERED), self.override(), "10.1148/radiol.11101800")
        self.assertEqual(printed, self.CORRECT)
        self.assertIn(self.CORRECT, entry)

    def test_the_override_expires_when_the_publisher_fixes_the_record(self):
        # The defect this guards against is printing a correction nobody checked
        # again. If Radiology repairs the spaces, this must stop, not continue.
        with self.assertRaises(references.ReferenceError) as caught:
            references.render(self.record(self.CORRECT), self.override(),
                              "10.1148/radiol.11101800")
        self.assertIn("no longer matches", str(caught.exception))


class PolicesTheSeed(unittest.TestCase):
    """resolve() reads the seed; these plant defects in it, with fetch stubbed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, references_list, overrides=None):
        """The seed and overrides as real files; Path.read_text cannot be patched."""
        seed = self.dir / "reference_seed.json"
        over = self.dir / "reference_overrides.json"
        seed.write_text(json.dumps({"references": references_list}), encoding="utf-8")
        over.write_text(json.dumps(overrides or {}), encoding="utf-8")
        return seed, over

    def run_resolve(self, references_list, overrides=None, record=None, fetch=None):
        seed, over = self.write(references_list, overrides)
        stub = {"side_effect": fetch} if fetch else {
            "return_value": record or json.loads(json.dumps(GOOD_RECORD))}
        with mock.patch.object(references, "SEED", seed), \
             mock.patch.object(references, "OVERRIDES", over), \
             mock.patch.object(references, "fetch", **stub):
            return references.resolve()

    def test_the_good_seed_resolves(self):
        out = self.run_resolve([dict(SEED_ENTRY)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["key"], "tian2015")

    def test_a_reference_with_no_admitted_title_is_refused(self):
        entry = dict(SEED_ENTRY)
        entry.pop("title")
        with self.assertRaises(SystemExit) as caught:
            self.run_resolve([entry])
        self.assertIn("no admitted title", str(caught.exception))

    def test_a_title_the_publisher_has_since_changed_is_refused(self):
        entry = dict(SEED_ENTRY, title="Retrospective estimation of organ dose in CT")
        with self.assertRaises(SystemExit) as caught:
            self.run_resolve([entry])
        self.assertIn("not the one admitted", str(caught.exception))

    def test_a_year_that_disagrees_is_refused(self):
        with self.assertRaises(SystemExit):
            self.run_resolve([dict(SEED_ENTRY, year=2014)])

    def test_a_duplicate_key_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_resolve([dict(SEED_ENTRY), dict(SEED_ENTRY)])
        self.assertIn("duplicate key", str(caught.exception))

    def test_a_literal_reference_must_say_why_it_has_no_doi(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_resolve([{"key": "salvat2006", "literal": "Salvat F. PENELOPE. 2006."}])
        self.assertIn("why it has no DOI", str(caught.exception))

    def test_a_literal_reference_with_a_reason_is_allowed(self):
        out = self.run_resolve([{"key": "salvat2006",
                                 "literal": "Salvat F. PENELOPE. NEA-OECD; 2006.",
                                 "reason": "No DOI is registered; checked at doi.org."}])
        self.assertEqual(out[0]["doi"], None)
        self.assertTrue(out[0]["literal"])

    def test_an_unresolvable_doi_is_refused(self):
        with self.assertRaises(SystemExit):
            self.run_resolve([dict(SEED_ENTRY)],
                             fetch=references.ReferenceError("doi.org returned HTTP 404"))


class TheRealSeedIsIntact(unittest.TestCase):
    """The shipped files, read as data. No network."""

    def setUp(self):
        self.seed = json.loads(references.SEED.read_text(encoding="utf-8"))["references"]
        self.overrides = {
            k: v for k, v in
            json.loads(references.OVERRIDES.read_text(encoding="utf-8")).items()
            if not k.startswith("_")
        }

    def test_every_reference_carries_an_admitted_title_or_a_reason(self):
        for item in self.seed:
            with self.subTest(key=item["key"]):
                if "literal" in item:
                    self.assertTrue(item.get("reason"))
                else:
                    self.assertTrue(item.get("title"))

    def test_keys_are_unique(self):
        keys = [item["key"] for item in self.seed]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_override_records_its_source_and_reason(self):
        for doi, fix in self.overrides.items():
            with self.subTest(doi=doi):
                self.assertTrue(fix.get("source"), "an override must say where the "
                                                   "correct value was read")
                self.assertTrue(fix.get("reason"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

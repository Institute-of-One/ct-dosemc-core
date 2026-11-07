"""The kit must follow the manuscript, including when the manuscript moves.

    python -m unittest paper.test_submission_kit -v

paper/build_submission.py opens by saying that a submission kit is a memory of
the last submission and that nothing in it is written twice. It then wrote the
figure rows twice: once in paper/collect_figures.py, where the manuscript's
figures are actually decided, and once as six typed rows here. A seventh figure
was added, and the kit went on listing six -- the author would have attached one
file fewer than the manuscript places, and nothing anywhere would have said so.

The module had no test of any kind. These are the tests that would have caught
it, so each one plants the defect rather than describing it.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import build_submission as kit  # noqa: E402
import collect_figures  # noqa: E402

#: A row of the kit's upload table: | `name` | kind | label |
ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(\w)\s*\|\s*(.+?)\s*\|$", re.M)

POINTS = ["A point about the result", "A second point", "A third point"]


def rows(text: str) -> list[tuple[str, str, str]]:
    return ROW.findall(text)


class TheUploadList(unittest.TestCase):
    def test_one_row_per_figure_the_manuscript_places(self):
        named = [name for name, kind, _ in kit.uploads() if kind == "F"]
        self.assertEqual(len(named), len(collect_figures.FIGURE_SOURCES))

    def test_the_figures_are_numbered_from_one_without_a_gap(self):
        numbers = [
            int(re.search(r"Figure_(\d+)\.png", name).group(1))
            for name, kind, _ in kit.uploads()
            if kind == "F"
        ]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_the_manuscript_is_first_and_the_supporting_files_last(self):
        kinds = [kind for _, kind, _ in kit.uploads()]
        self.assertEqual(kinds[0], "M")
        self.assertEqual(kinds[-2:], ["S", "S"])

    def test_an_added_figure_reaches_the_upload_list(self):
        """The defect itself: a figure added to the manuscript, not to the kit."""
        moved = dict(collect_figures.FIGURE_SOURCES)
        moved[max(moved) + 1] = ("figure_new.png", None)
        with mock.patch.object(collect_figures, "FIGURE_SOURCES", moved):
            named = [name for name, kind, _ in kit.uploads() if kind == "F"]
        self.assertEqual(len(named), len(moved))
        self.assertIn(f"build/figures/Figure_{max(moved)}.png", [n for n in named])

    def test_a_removed_figure_leaves_the_upload_list(self):
        """And the other way: a kit that still names a file nobody draws.

        It drops the *first* figure, not the last. Dropping the last is no
        evidence at all against a typed list, because a typed list that is
        already short does not name it either.
        """
        fewer = dict(collect_figures.FIGURE_SOURCES)
        gone = min(fewer)
        del fewer[gone]
        with mock.patch.object(collect_figures, "FIGURE_SOURCES", fewer):
            named = [name for name, kind, _ in kit.uploads() if kind == "F"]
        self.assertNotIn(f"build/figures/Figure_{gone}.png", named)
        self.assertEqual(len(named), len(fewer))


class TheWrittenKit(unittest.TestCase):
    """Against the real built manuscript, which is what the author uploads."""

    @classmethod
    def setUpClass(cls):
        if not kit.BUILT_MANUSCRIPT.is_file():
            raise unittest.SkipTest("no built manuscript; run paper/build_all.py")
        cls.text = kit.build_kit(POINTS)

    def test_the_table_names_every_upload(self):
        self.assertEqual(len(rows(self.text)), len(kit.uploads()))

    def test_the_table_names_a_figure_for_each_one_the_manuscript_places(self):
        """Counted against the figure table, not against the kit's own list.

        Comparing the printed kit with the list the kit was printed from is a
        comparison of something with itself: it was green while the kit named
        six of the seven figures. The manuscript's figure table is the only
        independent source, so the count comes from there.
        """
        printed = [name for name, kind, _ in rows(self.text) if kind == "F"]
        self.assertEqual(len(printed), len(collect_figures.FIGURE_SOURCES))
        for number in collect_figures.FIGURE_SOURCES:
            self.assertIn(f"Figure_{number}.png", printed)

    def test_every_named_figure_is_a_file_that_exists(self):
        for relative, kind, _ in kit.uploads():
            if kind == "F":
                self.assertTrue(
                    (kit.PAPER / relative).is_file(),
                    f"{relative} is named in the kit and has not been written",
                )

    def test_a_file_that_was_never_built_is_marked_rather_than_listed(self):
        """A kit that quietly lists an absent file is how one gets discovered at
        the portal instead of here."""
        real = kit.uploads()
        invented = (*real, ("build/figures/Figure_99.png", "F", "Figure 99"))
        with mock.patch.object(kit, "uploads", lambda: invented):
            text = kit.build_kit(POINTS)
        self.assertIn("NOT BUILT YET", text)
        self.assertIn("Figure_99.png", text)

    def test_the_doi_is_the_one_the_manuscript_carries(self):
        built = kit.BUILT_MANUSCRIPT.read_text(encoding="utf-8")
        in_manuscript = re.search(r"10\.5281/zenodo\.\d+", built)
        self.assertIsNotNone(in_manuscript, "the manuscript carries no Zenodo DOI")
        self.assertIn(in_manuscript.group(0), self.text)

    def test_the_doi_is_not_reported_missing(self):
        self.assertNotIn("MISSING", self.text)

    def test_the_title_is_the_manuscript_s_own(self):
        built = kit.BUILT_MANUSCRIPT.read_text(encoding="utf-8")
        title = re.search(r"(?m)^#\s+(.+)$", built).group(1)
        self.assertIn(title, self.text)


class TheStagingFolder(unittest.TestCase):
    """The folder the portal is given must be exactly the upload list.

    It was made by hand on 2026-11-07 and was stale by the end of the same day:
    the checklist in it said 3998 words against a manuscript of 3987, and the
    manuscript in it still carried its own line numbers. Nothing wrote it and no
    gate read it. These plant that defect rather than describing it.
    """

    def setUp(self):
        self.tmp = Path(__import__("tempfile").mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.source = self.tmp / "src"
        self.source.mkdir()
        for name in ("manuscript.docx", "cover_letter.docx"):
            (self.source / name).write_bytes(b"current")
        self.listing = (
            ("src/manuscript.docx", "M", "Manuscript"),
            ("src/cover_letter.docx", "S", "Cover Letter"),
        )

    def stage(self):
        with (
            mock.patch.object(kit, "PAPER", self.tmp),
            mock.patch.object(kit, "UPLOAD", self.tmp / "upload"),
            mock.patch.object(kit, "uploads", lambda: self.listing),
        ):
            return kit.stage_uploads(), sorted(p.name for p in (self.tmp / "upload").iterdir())

    def test_it_copies_every_file_on_the_list(self):
        changes, names = self.stage()
        self.assertEqual(names, ["cover_letter.docx", "manuscript.docx"])
        self.assertTrue(all(c.startswith("refreshed") for c in changes), changes)

    def test_a_stale_copy_is_replaced(self):
        self.stage()
        (self.source / "manuscript.docx").write_bytes(b"rebuilt")
        changes, _ = self.stage()
        self.assertIn("refreshed manuscript.docx", changes)
        self.assertEqual((self.tmp / "upload" / "manuscript.docx").read_bytes(), b"rebuilt")

    def test_a_file_not_on_the_list_is_removed(self):
        self.stage()
        (self.tmp / "upload" / "old_figure.png").write_bytes(b"left over")
        changes, names = self.stage()
        self.assertIn("removed old_figure.png", changes)
        self.assertNotIn("old_figure.png", names)

    def test_an_unbuilt_file_is_named_rather_than_skipped(self):
        self.listing = (*self.listing, ("src/missing.docx", "S", "Nothing"))
        changes, names = self.stage()
        self.assertIn("NOT BUILT src/missing.docx", changes)
        self.assertNotIn("missing.docx", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)

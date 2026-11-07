"""Require the headroom check to catch a figure cropped the old way.

    python -m unittest paper.test_figure_headroom -v

The defect this guards against reached a portal's approval screen on a companion
manuscript: the submission system stamps its own figure label across the top
left of each uploaded figure's page without moving the artwork down, so a
tightly cropped figure has the label printed across its panel titles.

Nothing downstream looks at a figure file. The manuscript gates read the .docx
and the figures are not in the .docx. So the check is the only thing between
that defect and the reviewer, and an unproved check is no check.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import check_figure_headroom as headroom  # noqa: E402
import make_submission_figures as submission  # noqa: E402

DPI = 300


def figure(path: Path, blank_rows: int, dpi: int = DPI) -> Path:
    """A 'figure': white, with a black bar starting ``blank_rows`` from the top."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1200, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([100, blank_rows, 1100, blank_rows + 200], fill="black")
    image.save(path, dpi=(dpi, dpi))
    return path


class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)


class MeasuresTheBand(Setup):
    def test_a_tight_crop_measures_near_zero(self):
        path = figure(self.dir / "tight.png", blank_rows=2)
        self.assertLess(headroom.blank_band_inches(path), 0.05)

    def test_half_an_inch_measures_half_an_inch(self):
        path = figure(self.dir / "padded.png", blank_rows=int(0.5 * DPI))
        self.assertAlmostEqual(headroom.blank_band_inches(path), 0.5, places=2)

    def test_a_file_without_dpi_is_refused(self):
        from PIL import Image

        path = self.dir / "nodpi.png"
        Image.new("RGB", (100, 100), "white").save(path)
        with self.assertRaises(ValueError) as caught:
            headroom.blank_band_inches(path)
        self.assertIn("no dpi", str(caught.exception))

    def test_a_blank_page_returns_its_whole_height(self):
        from PIL import Image

        path = self.dir / "blank.png"
        Image.new("RGB", (300, 600), "white").save(path, dpi=(DPI, DPI))
        self.assertAlmostEqual(headroom.blank_band_inches(path), 600 / DPI, places=3)


class RefusesATightCrop(Setup):
    def test_the_old_crop_is_reported(self):
        path = figure(self.dir / "Figure_1.png", blank_rows=2)
        problems = headroom.check([path])
        self.assertEqual(len(problems), 1)
        self.assertIn("stamps its figure label there", problems[0])

    def test_a_band_just_under_the_requirement_is_reported(self):
        rows = int((headroom.REQUIRED_INCHES - 0.05) * DPI)
        path = figure(self.dir / "Figure_2.png", blank_rows=rows)
        self.assertEqual(len(headroom.check([path])), 1)

    def test_a_band_at_the_requirement_passes(self):
        rows = int((headroom.REQUIRED_INCHES + 0.01) * DPI)
        path = figure(self.dir / "Figure_3.png", blank_rows=rows)
        self.assertEqual(headroom.check([path]), [])

    def test_a_missing_file_is_reported(self):
        self.assertEqual(len(headroom.check([self.dir / "absent.png"])), 1)


class PaddingTurnsOneIntoTheOther(Setup):
    def test_a_tight_figure_padded_then_passes(self):
        source = figure(self.dir / "tight.png", blank_rows=2)
        self.assertEqual(len(headroom.check([source])), 1)

        padded = self.dir / "Figure_1.png"
        submission.pad(source, padded)
        self.assertEqual(headroom.check([padded]), [])

    def test_padding_keeps_the_artwork_and_the_dpi(self):
        from PIL import Image

        source = figure(self.dir / "tight.png", blank_rows=2)
        padded = self.dir / "Figure_1.png"
        added = submission.pad(source, padded)

        before, after = Image.open(source), Image.open(padded)
        self.assertEqual(after.width, before.width)
        self.assertEqual(after.height, before.height + added)
        self.assertEqual(after.info.get("dpi"), before.info.get("dpi"))
        # The artwork itself must be unchanged, not merely present: a pad that
        # rescaled the figure would still pass a height check.
        self.assertEqual(
            after.crop((0, added, after.width, after.height)).tobytes(),
            before.convert(after.mode).tobytes(),
        )

    def test_padding_a_file_without_dpi_is_refused(self):
        from PIL import Image

        source = self.dir / "nodpi.png"
        Image.new("RGB", (100, 100), "white").save(source)
        with self.assertRaises(SystemExit):
            submission.pad(source, self.dir / "out.png")


class TheRealUploadFilesPass(unittest.TestCase):
    def test_every_uploaded_figure_leaves_the_band_empty(self):
        paths = sorted(headroom.UPLOADED.glob("Figure_*.png"))
        if not paths:
            self.skipTest("run paper/make_submission_figures.py first")
        # Resolved from the figure table, not typed. A typed six went on passing
        # when the manuscript had seven figures, which is the shape of defect this
        # whole file exists to catch: it would have checked six of the seven
        # images the portal receives and called that every one.
        import collect_figures  # noqa: PLC0415

        self.assertEqual(len(paths), len(collect_figures.FIGURE_SOURCES))
        self.assertEqual(headroom.check(paths), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

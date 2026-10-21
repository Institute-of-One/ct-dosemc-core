"""Break the figure checks on purpose and require each one to notice.

    python paper/prove_figure_checks.py

A check that has only ever run on one manuscript cannot be told apart from a check that
returns success. These were written on 2026-10-21, and each injection below is a defect
that actually reached a submitted manuscript:

* figure 6 cited in the Results before figures 4 and 5 are mentioned at all;
* figure 6 copied from the pipeline's ``figure5_vendor.png``, which left "Figure 5" drawn
  across the top of the image while the caption underneath said Figure 6;
* figure 4 shipped with its legend off the canvas, its caption repeated inside the image
  and this programme's internal identifiers on its axes -- none of which any check in
  presubmission_check.py can see, which is why the third gate asks whether a person
  opened the file rather than trying to judge it;
* a title claiming a floor over every index-based conversion while five were evaluated.

Nothing here touches paper/figures/ or the ledger; the sources dictionary and the errors
list are swapped out around each case and put back.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sys
import tempfile
from pathlib import Path

PAPER = Path(__file__).resolve().parent
sys.path.insert(0, str(PAPER))

import collect_figures                                       # noqa: E402
import presubmission_check as gate                           # noqa: E402


@contextlib.contextmanager
def collecting():
    """Run one case with its own error list, and hand back what it reported."""
    kept_errors, kept_warnings = gate.errors, gate.warnings
    gate.errors, gate.warnings = [], []
    try:
        yield gate.errors
    finally:
        gate.errors, gate.warnings = kept_errors, kept_warnings


@contextlib.contextmanager
def sources(mapping):
    kept = collect_figures.FIGURE_SOURCES
    collect_figures.FIGURE_SOURCES = mapping
    try:
        yield
    finally:
        collect_figures.FIGURE_SOURCES = kept


@contextlib.contextmanager
def figures_at(directory, ledger):
    """Point the ledger check at a throwaway directory and a throwaway ledger."""
    kept_figures, kept_paper = gate.FIGURES, gate.PAPER
    gate.FIGURES = Path(directory)
    gate.PAPER = Path(directory)
    (Path(directory) / "figures_reviewed.json").write_text(
        json.dumps({"figures": ledger}), encoding="utf-8"
    )
    try:
        yield
    finally:
        gate.FIGURES, gate.PAPER = kept_figures, kept_paper


IN_ORDER = "text citing figure 1, then figure 2, then figure 3 at the end."
OUT_OF_ORDER = "Per-organ values are in figure 6; plotted against the index (figure 4)."


def main() -> int:
    failures: list[str] = []

    def case(name: str, *, expect_caught: bool, run) -> None:
        with collecting() as reported:
            run()
            caught = bool(reported)
        if caught != expect_caught:
            failures.append(
                f"{name}: expected {'a failure' if expect_caught else 'a pass'}, "
                f"got {reported or 'nothing'}"
            )
        mark = "caught " if caught else "passed "
        print(f"  {mark} {name}")
        for message in reported:
            print(f"          {message}")

    print("citation order")
    case("figure 6 named before figures 4 and 5, as submitted",
         expect_caught=True,
         run=lambda: gate.check_figures_are_first_cited_in_order(OUT_OF_ORDER))
    case("figures 1, 2, 3 named in order",
         expect_caught=False,
         run=lambda: gate.check_figures_are_first_cited_in_order(IN_ORDER))

    print("\nrenumbered on the way in")
    with sources({6: ("figure6_vendor.png", "phase2_cohort/figure5_vendor.png")}):
        case("figure 6 copied from a file the pipeline drew as figure 5",
             expect_caught=True,
             run=lambda: gate.check_no_figure_is_renumbered_on_the_way_in(""))
    with sources({6: ("figure6_vendor.png", "phase2_cohort/figure6_vendor.png")}):
        case("figure 6 copied from a file drawn as figure 6",
             expect_caught=False,
             run=lambda: gate.check_no_figure_is_renumbered_on_the_way_in(""))
    with sources({5: ("figure5_conversion_ceiling.png", None)}):
        case("a figure drawn in place, with no source to disagree with",
             expect_caught=False,
             run=lambda: gate.check_no_figure_is_renumbered_on_the_way_in(""))

    print("\nnobody opened the image")
    with tempfile.TemporaryDirectory() as directory:
        image = Path(directory) / "figure4_scatter.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n first drawing")
        first = hashlib.sha256(image.read_bytes()).hexdigest()
        entry = {"figure4_scatter.png": {"sha256": first, "reviewed": "2026-10-21"}}

        with sources({4: ("figure4_scatter.png", None)}):
            with figures_at(directory, {}):
                case("an image that has never been recorded as looked at",
                     expect_caught=True,
                     run=gate.check_every_figure_image_has_been_looked_at)
            with figures_at(directory, entry):
                case("an image recorded at the hash it still has",
                     expect_caught=False,
                     run=gate.check_every_figure_image_has_been_looked_at)
            image.write_bytes(b"\x89PNG\r\n\x1a\n redrawn, and nobody looked again")
            with figures_at(directory, entry):
                case("an image redrawn after it was recorded",
                     expect_caught=True,
                     run=gate.check_every_figure_image_has_been_looked_at)

    print("\na bounding claim without a declared scope")
    titled = "# A measured floor on index-based organ dose estimation\n\nAbstract.\n\n## 1\n"
    plain = "# Organ dose recovered from an index in forty abdominal series\n\nAbstract.\n\n## 1\n"
    declared = (
        "The bound is over the five conversions evaluated here, cross-validated on this "
        "cohort of forty series, and not over index-based conversion in general."
    )
    scope = f"<!-- scope-of-claim -->\n{declared}\n\n"
    case("a title claiming a floor, with no paragraph declaring the scope",
         expect_caught=True,
         run=lambda: gate.check_a_bounding_claim_declares_its_scope("body text", titled))
    case("the same title, with the scope declared and carried into the build",
         expect_caught=False,
         run=lambda: gate.check_a_bounding_claim_declares_its_scope(
             scope, titled + declared))
    case("the scope declared in the source but lost before the build",
         expect_caught=True,
         run=lambda: gate.check_a_bounding_claim_declares_its_scope(scope, titled))
    case("a marked paragraph too short to delimit anything",
         expect_caught=True,
         run=lambda: gate.check_a_bounding_claim_declares_its_scope(
             "<!-- scope-of-claim -->\nOver five conversions.\n\n", titled))
    case("a title that claims no bound, so nothing is required",
         expect_caught=False,
         run=lambda: gate.check_a_bounding_claim_declares_its_scope("body text", plain))

    print("\nthe manuscript as it stands")
    shipped: list[str] = []
    built = PAPER / "build" / "manuscript.md"
    # Nothing to examine is not a pass. Without this, deleting the built manuscript and
    # emptying paper/figures/ made this section silent and the script exited 0.
    if not built.exists():
        failures.append("paper/build/manuscript.md is missing; nothing was checked")
    present = [
        name for name, _ in collect_figures.FIGURE_SOURCES.values()
        if (gate.FIGURES / name).exists()
    ]
    if not present:
        # Gate 3 now reports a registered image that is not on disk, so an empty
        # paper/figures/ no longer passes in silence. This stays as the belt to that
        # brace: if nothing is registered either, there is still nothing to look at.
        failures.append("no registered figure image is on disk; nothing was checked")
    with collecting() as reported:
        gate.check_figures_are_first_cited_in_order(
            built.read_text(encoding="utf-8") if built.exists() else ""
        )
        gate.check_no_figure_is_renumbered_on_the_way_in("")
        gate.check_every_figure_image_has_been_looked_at()
        shipped = list(reported)
        for message in shipped:
            print(f"  FAIL  {message}")
        if not shipped:
            print("  the submitted figures now pass all three")

    # This section used to print FAIL and return 0, so the script could report that every
    # injected defect was caught while the real figures failed every gate. A script whose
    # exit code disagrees with its own output is worse than no script.
    if failures:
        print(f"\nthe checks are not doing their job ({len(failures)}):")
        for failure in failures:
            print(f"  {failure}")
        return 1
    if shipped:
        print(
            f"\nthe checks work, and the manuscript does not pass them "
            f"({len(shipped)} outstanding). Fix the figures, not the checks."
        )
        return 1
    print("\nevery injected defect was caught and every correct case passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

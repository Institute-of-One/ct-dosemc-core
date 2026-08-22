"""Resolve the manuscript's number markers from ``paper/frozen/``.

    python paper/build_manuscript.py            # -> paper/build/manuscript.md
    python paper/build_manuscript.py --check    # fail if the built file is out of date

Every number in ``paper/manuscript.md`` is written as a marker naming the frozen
file and the path the value comes from::

    [[results:manifest.json:metrics.m3_tcia_closed_form_nrmse_mean|.3f]]
    [[results:m2_summary.json:cells[noise=25.0,stride=4].pinn_param_mre|.2f]]

The build substitutes the value found under ``paper/frozen/``. A marker that cannot be
resolved is an **error, not a warning**, so a stale or hand-edited number cannot
survive a rebuild, and the test suite runs the rebuild on every CI run.

This exists because a manuscript that types its numbers drifts from the run that
produced them. Every companion paper in this programme shipped at least one number
that had drifted, and each was caught by a person reading rather than by anything
mechanical. IORN-007 records its evidence in results/ already; this closes the last
gap, between the recorded value and the sentence that quotes it.

Path syntax
-----------
``a.b``               nested keys
``a["k.with.dots"]``  a key a dotted path cannot express
``a[2]``              list index (negative counts from the end)
``a[k=v,k2=v2]``      the single list element whose fields match (ambiguity is an error)
``|fmt``              trailing Python format spec, e.g. ``.3f``
``|sciN``             scientific notation with N decimals, typeset ``4.0x10^-8`` in the
                      journal's form rather than ``4.0e-08`` -- a number that has to be
                      retyped to look right is a number that can drift
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PAPER_DIR = Path(__file__).resolve().parent
REPO_DIR = PAPER_DIR.parent
DEFAULT_FROZEN = PAPER_DIR / "frozen"
DEFAULT_SOURCE = PAPER_DIR / "manuscript.md"
DEFAULT_OUTPUT = PAPER_DIR / "build" / "manuscript.md"

#: ``[[results:<file>:<path>]]`` or the same with ``|<format>``. The format is
#: separated by a pipe because paths contain brackets and dots but never a pipe. The
#: trailing lookahead lets a path end in a bracket: ``cells[0]]]`` must close the marker
#: after ``[0]``, not after ``[0``.
MARKER = re.compile(r"\[\[results:([^:|\]]+):(.+?)(?:\|([^|\]]+))?\]\](?!\])")
_STEP = re.compile(r"([^.\[\]]+)|\[([^\]]*)\]")
#: Capturing, so ``re.split`` returns the comments too, in place.
_COMMENT = re.compile(r"(<!--.*?-->)", re.S)
#: ``[[table:<name>]]`` -- a whole table built from the frozen results by
#: ``paper/tables.py``, so that no cell in it is ever typed by hand.
TABLE_MARKER = re.compile(r"\[\[table:([A-Za-z0-9_]+)\]\]")

#: Unicode superscripts, for the exponent of ``|sciN``.
_SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


class ResolutionError(LookupError):
    """A marker that does not name anything under ``paper/frozen/``."""


def scientific(value: float, digits: int) -> str:
    """``4.0115e-08`` -> ``4.0x10^-8`` in the form journal prose uses.

    Exact powers of ten keep the mantissa, so a reader never has to wonder whether
    one was rounded away.
    """
    mantissa, exponent = f"{float(value):.{int(digits)}e}".split("e")
    return f"{mantissa}×10{str(int(exponent)).translate(_SUPERSCRIPT)}"


def _match_value(candidate: Any, wanted: str) -> bool:
    """Compare a field to a marker's literal, numerically when both look like numbers.

    Tolerant, because a sweep axis built with ``linspace`` stores
    ``12.500000000000002`` and a manuscript writes ``12.5``. The tolerance identifies
    grid points; it does not merge them.
    """
    if str(candidate) == wanted:
        return True
    try:
        left, right = float(candidate), float(wanted)
    except (TypeError, ValueError):
        return False
    return abs(left - right) <= 1e-9 * max(1.0, abs(right))


def resolve(payload: Any, path: str) -> Any:
    """Follow a marker path into a loaded frozen file."""
    current = payload
    for name, bracket in _STEP.findall(path):
        if name:
            if not isinstance(current, dict) or name not in current:
                raise ResolutionError(f"{path!r}: no key {name!r} at this level")
            current = current[name]
            continue
        if len(bracket) >= 2 and bracket[0] == bracket[-1] and bracket[0] in "\"'":
            key = bracket[1:-1]
            if not isinstance(current, dict) or key not in current:
                raise ResolutionError(f"{path!r}: no key {key!r} at this level")
            current = current[key]
            continue
        if not isinstance(current, list):
            raise ResolutionError(f"{path!r}: {bracket!r} indexes something that is not a list")
        if re.fullmatch(r"-?\d+", bracket):
            index = int(bracket)
            if not -len(current) <= index < len(current):
                raise ResolutionError(f"{path!r}: index {index} is out of range")
            current = current[index]
            continue
        criteria = [part.split("=", 1) for part in bracket.split(",")]
        matches = [
            item
            for item in current
            if isinstance(item, dict)
            and all(key in item and _match_value(item[key], value) for key, value in criteria)
        ]
        if len(matches) != 1:
            raise ResolutionError(
                f"{path!r}: [{bracket}] matched {len(matches)} rows, expected exactly 1"
            )
        current = matches[0]
    return current


def render(source: str, frozen: Path = DEFAULT_FROZEN) -> str:
    """Substitute every marker in ``source`` with its value from ``frozen``."""
    cache: dict[str, Any] = {}
    problems: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        filename, path, spec = match.group(1), match.group(2), match.group(3)
        if filename not in cache:
            file_path = frozen / filename
            if not file_path.exists():
                problems.append(f"{filename} is missing from {frozen}")
                return match.group(0)
            cache[filename] = json.loads(file_path.read_text(encoding="utf-8"))
        try:
            value = resolve(cache[filename], path)
        except ResolutionError as exc:
            problems.append(str(exc))
            return match.group(0)
        try:
            if spec and re.fullmatch(r"sci\d+", spec):
                return scientific(value, int(spec[3:]))
            return format(value, spec) if spec else str(value)
        except (TypeError, ValueError) as exc:
            problems.append(f"{path!r}: cannot format {value!r} as {spec!r} ({exc})")
            return match.group(0)

    def substitute_table(match: re.Match[str]) -> str:
        """``[[table:<name>]]`` -> a whole table, rendered from the frozen results.

        A table is where a stale number hides best: sixty cells rebuilt by hand, and
        the one that drifted looks like the fifty-nine that did not.
        """
        import tables  # noqa: PLC0415

        name = match.group(1)
        builder = tables.TABLES.get(name)
        if builder is None:
            problems.append(f"no table named {name!r}; known: {sorted(tables.TABLES)}")
            return match.group(0)
        return builder()

    # Markers inside HTML comments document the syntax; the file explains its own
    # notation in a comment at the top and that example must not be resolved.
    pieces = _COMMENT.split(source)
    rendered = "".join(
        piece
        if _COMMENT.fullmatch(piece)
        else TABLE_MARKER.sub(substitute_table, MARKER.sub(substitute, piece))
        for piece in pieces
    )
    if problems:
        raise ResolutionError(
            "the manuscript cites values that cannot be resolved:\n  " + "\n  ".join(problems)
        )
    return rendered


def build(
    source: Path = DEFAULT_SOURCE,
    output: Path = DEFAULT_OUTPUT,
    frozen: Path = DEFAULT_FROZEN,
    *,
    check: bool = False,
) -> int:
    if not source.exists():
        print(f"{source} does not exist")
        return 2
    rendered = render(source.read_text(encoding="utf-8"), frozen)
    if check:
        if not output.exists():
            print(f"{output} has never been built; run without --check")
            return 1
        if output.read_text(encoding="utf-8") != rendered:
            print(f"{output} is out of date: rebuild it and commit the result")
            return 1
        print(f"{output} is current")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    markers = len(MARKER.findall(source.read_text(encoding="utf-8")))
    print(f"wrote {output} ({len(rendered.split())} words, {markers} markers resolved)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify without writing")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--frozen", type=Path, default=DEFAULT_FROZEN)
    args = parser.parse_args(argv)
    try:
        return build(args.source, args.output, args.frozen, check=args.check)
    except ResolutionError as exc:
        print(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

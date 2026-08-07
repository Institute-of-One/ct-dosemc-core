"""Per-value provenance records.

Every number this package reports carries a record of how it was produced: the
formula, the inputs it consumed, the assumptions that were made, and the source
of any external constant.  ``results/`` is written from these records, and the
anti-fabrication tests in ``tests/`` re-derive quoted figures from them.

The rule is the same one used in ctdose-core and ctsegdose-core: a value that
cannot state where it came from does not get reported.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = ["Provenance", "Value", "environment", "file_digest", "write_results"]


@dataclass(frozen=True)
class Provenance:
    """How a single value was produced."""

    formula: str
    """Human-readable formula or procedure, e.g. 'CTDIw = CTDIc/3 + 2*CTDIp/3'."""

    inputs: Mapping[str, Any] = field(default_factory=dict)
    """The values fed into ``formula``, by name."""

    assumptions: Sequence[str] = field(default_factory=tuple)
    """Everything taken on faith.  An empty tuple is a claim, so be honest."""

    source: str | None = None
    """Where an external constant or dataset came from (citation, URL, file)."""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["assumptions"] = list(self.assumptions)
        d["inputs"] = dict(self.inputs)
        return d


@dataclass(frozen=True)
class Value:
    """A number, its unit, its uncertainty and its provenance."""

    value: float
    unit: str
    provenance: Provenance
    uncertainty: float | None = None
    """1 standard deviation, in the same unit as ``value``.  ``None`` means the
    quantity is not a Monte-Carlo estimate (a geometric constant, say)."""

    uncertainty_kind: str = "1sigma_mc_statistical"

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "uncertainty": self.uncertainty,
            "uncertainty_kind": None if self.uncertainty is None else self.uncertainty_kind,
            "provenance": self.provenance.to_dict(),
        }

    @property
    def relative_uncertainty(self) -> float | None:
        if self.uncertainty is None or self.value == 0.0:
            return None
        return abs(self.uncertainty / self.value)


def file_digest(path: str | Path) -> str | None:
    """SHA-256 of a file, or ``None`` if it is not there.

    Used to pin the exact engine binary, material file and spectrum that
    produced a result.
    """
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit(repo_root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def environment(repo_root: str | Path | None = None) -> dict[str, Any]:
    """The bits of the machine that can change a Monte-Carlo answer."""
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent.parent
    env: dict[str, Any] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor(),
        "git_commit": _git_commit(root),
    }
    try:
        import numpy

        env["numpy"] = numpy.__version__
    except ImportError:  # pragma: no cover - numpy is a hard dependency in practice
        pass
    try:
        import spekpy

        env["spekpy"] = getattr(spekpy, "__version__", "unknown")
    except ImportError:
        env["spekpy"] = None
    return env


def write_results(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Write a machine-readable results file, stamping the environment on it.

    ``Value`` and ``Provenance`` instances anywhere in ``payload`` are expanded.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    body = {"environment": environment(), **payload}
    out.write_text(json.dumps(body, indent=2, default=_encode, sort_keys=False), encoding="utf-8")
    return out


def _encode(obj: Any) -> Any:
    if isinstance(obj, (Value, Provenance)):
        return obj.to_dict()
    if isinstance(obj, Path):
        return str(obj)
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        raise TypeError(f"not JSON serialisable: {type(obj)!r}") from None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"not JSON serialisable: {type(obj)!r}")

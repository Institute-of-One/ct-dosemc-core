"""Provenance for the patient-image acquisition step (Phase-2 data, IORN-007).

No DICOM is redistributed by this repository, so the provenance record *is* the
dataset as far as a reader is concerned: it names the archive, the collection, the
collection URI, the Series Instance UID, the licence the series was published under
and the date it was retrieved, precisely enough that the same series can be fetched
again and the same numbers reproduced.

This mirrors the record ``ctsegdose-core`` writes for IORN-006, ported here so the
IORN-007 pipeline stands on its own (docs/REPRODUCING_DATA.md). The one behavioural
change from the ported original is :func:`series_local_path`, which fixes a defect
that aborted an otherwise-complete download when the data directory lay outside the
repository (see the regression test in ``tests/test_select_and_download.py``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "ARCHIVE",
    "REDISTRIBUTION_NOTE",
    "SeriesProvenance",
    "document",
    "series_local_path",
]

ARCHIVE = "The Cancer Imaging Archive (TCIA), public NBIA REST API"

REDISTRIBUTION_NOTE = (
    "No DICOM is redistributed by this repository. Each series is identified by its "
    "Series Instance UID, collection and licence so that a reader retrieves it from the "
    "archive directly; see docs/REPRODUCING_DATA.md."
)


def series_local_path(dest: Path | str, *, data_root: Path | str, repo: Path | str) -> str:
    """The path recorded in provenance so a reader can locate a fetched series.

    Prefer a path relative to the repository root, which is stable across checkouts.
    When the download directory is **outside** the repository -- a legitimate case,
    because ``--data`` may point at a shared cache on another drive -- fall back to a
    path relative to the download root, and finally to the absolute POSIX path.

    Crucially this **never raises**. The defect it replaces called
    ``dest.relative_to(REPO)`` unconditionally, so pointing ``--data`` anywhere outside
    the script's own repository threw ``ValueError`` *after* the series had already been
    transferred -- turning a cosmetic provenance field into a hard failure that required
    a manual re-run. A reproducibility claim cannot rest on a downloader that only works
    when its output happens to land inside one particular repository.
    """
    dest_p = Path(dest).resolve()
    for base in (Path(repo).resolve(), Path(data_root).resolve()):
        try:
            return dest_p.relative_to(base).as_posix()
        except ValueError:
            continue
    return dest_p.as_posix()


@dataclass
class SeriesProvenance:
    """Everything needed to re-fetch one series and to cite it correctly."""

    vendor: str
    manufacturer: str
    model_name: str
    collection: str
    collection_uri: str
    patient_id: str
    series_instance_uid: str
    study_instance_uid: str
    series_description: str
    body_part: str
    n_instances: int
    n_files_written: int
    size_bytes: int
    kvp: float | None
    slice_thickness_mm: float | None
    pixel_spacing_mm: list[float] = field(default_factory=list)
    z_coverage_mm: float | None = None
    tube_current_spread: float | None = None
    licence: str = ""
    licence_uri: str = ""
    retrieved_utc: str = ""
    local_path: str = ""
    selection_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def document(
    *,
    series: list[SeriesProvenance],
    parameters: dict[str, Any],
    generated_by: str,
    package_version: str,
    started_utc: str,
    finished_utc: str,
    exclusions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the ``data/PROVENANCE.json`` document for IORN-007.

    ``parameters`` records the query that produced the sample, so the selection is
    reproducible and not merely described.
    """
    by_vendor: dict[str, dict[str, Any]] = {}
    for s in series:
        block = by_vendor.setdefault(
            s.vendor, {"n_series": 0, "n_instances": 0, "size_bytes": 0, "collections": []}
        )
        block["n_series"] += 1
        block["n_instances"] += s.n_instances
        block["size_bytes"] += s.size_bytes
        if s.collection not in block["collections"]:
            block["collections"].append(s.collection)

    return {
        "provenance": {
            "layer": "1 - patient image acquisition for patient-specific absorbed organ dose (IORN-007)",
            "generated_by": generated_by,
            "ct_dosemc_core_version": package_version,
            "archive": ARCHIVE,
            "access_started_utc": started_utc,
            "access_finished_utc": finished_utc,
            "redistribution": REDISTRIBUTION_NOTE,
        },
        "parameters": parameters,
        "summary": {
            "n_series": len(series),
            "n_instances": sum(s.n_instances for s in series),
            "size_bytes": sum(s.size_bytes for s in series),
            "size_gb": round(sum(s.size_bytes for s in series) / 1e9, 3),
            "by_vendor": by_vendor,
            "licences": sorted({s.licence for s in series if s.licence}),
            "collections": sorted({s.collection for s in series if s.collection}),
        },
        "exclusions": exclusions or {},
        "series": [s.to_dict() for s in series],
    }

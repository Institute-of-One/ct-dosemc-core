"""Regression tests for the ported TCIA downloader (IORN-007 Phase-2 data, D2).

The reproducibility claim of this project is that a third party can fetch the same
series from TCIA and re-run every number. That claim fails if the downloader itself
carries a bug that needs a manual work-around. The download stage in the ported
original computed the provenance ``local_path`` with ``dest.relative_to(REPO)``,
which raised ``ValueError`` the moment ``--data`` pointed outside the script's own
repository -- *after* the series had been transferred. These tests pin the fix:
:func:`ct_dosemc_core.acquisition.series_local_path` must never raise, whatever the
relationship between the download directory and the repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ct_dosemc_core.acquisition import SeriesProvenance, document, series_local_path
from ct_dosemc_core.selection import (
    Candidate,
    candidate_from_index_row,
    one_series_per_patient,
    screen,
)


def test_series_local_path_under_repo_is_repo_relative(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data_root = repo / "data"
    dest = data_root / "GE" / "CMB-CRC__patient1" / "1.2.3.4"
    dest.mkdir(parents=True)
    assert series_local_path(dest, data_root=data_root, repo=repo) == "data/GE/CMB-CRC__patient1/1.2.3.4"


def test_series_local_path_outside_repo_does_not_raise(tmp_path: Path) -> None:
    """The exact defect: --data outside the repo used to crash the download stage.

    A cache on another drive (or the sibling repo we actually used) is a legitimate
    ``--data``. The old ``dest.relative_to(repo)`` raised here; the fix falls back to a
    path relative to the download root and returns a usable string.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    data_root = tmp_path / "elsewhere_cache"  # sibling of repo, NOT under it
    dest = data_root / "Philips" / "CPTAC-SAR__p2" / "5.6.7.8"
    dest.mkdir(parents=True)

    # Document that the naive computation is exactly what failed before the fix.
    with pytest.raises(ValueError):
        dest.resolve().relative_to(repo.resolve())

    # The fix must return a stable, download-root-relative path and never raise.
    assert series_local_path(dest, data_root=data_root, repo=repo) == "Philips/CPTAC-SAR__p2/5.6.7.8"


def test_series_local_path_unrelated_falls_back_to_absolute(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data_root = tmp_path / "declared_root"
    dest = tmp_path / "somewhere_else" / "series"
    for p in (repo, data_root, dest):
        p.mkdir(parents=True)
    got = series_local_path(dest, data_root=data_root, repo=repo)
    assert got == dest.resolve().as_posix()  # never raises, always a usable string


def test_document_records_local_path_from_helper(tmp_path: Path) -> None:
    """A completed transfer to an out-of-repo cache still yields a valid provenance doc."""
    repo = tmp_path / "repo"
    repo.mkdir()
    data_root = tmp_path / "cache"
    dest = data_root / "Siemens" / "CMB-OV__p3" / "9.9.9"
    dest.mkdir(parents=True)
    rec = SeriesProvenance(
        vendor="Siemens",
        manufacturer="SIEMENS",
        model_name="SOMATOM",
        collection="CMB-OV",
        collection_uri="",
        patient_id="p3",
        series_instance_uid="9.9.9",
        study_instance_uid="",
        series_description="",
        body_part="ABDOMEN",
        n_instances=164,
        n_files_written=164,
        size_bytes=86_600_000,
        kvp=120.0,
        slice_thickness_mm=1.5,
        local_path=series_local_path(dest, data_root=data_root, repo=repo),
    )
    doc = document(
        series=[rec],
        parameters={"modality": "CT"},
        generated_by="tools/select_and_download.py --stage download",
        package_version="test",
        started_utc="2026-01-01T00:00:00+00:00",
        finished_utc="2026-01-01T00:10:00+00:00",
    )
    assert doc["summary"]["n_series"] == 1
    assert doc["series"][0]["local_path"] == "Siemens/CMB-OV__p3/9.9.9"
    assert doc["provenance"]["ct_dosemc_core_version"] == "test"


def test_ported_selection_screens_offline() -> None:
    """The ported selection module runs without network, so the port is exercised in CI."""
    rows = [
        {
            "Manufacturer": "SIEMENS",
            "ManufacturerModelName": "SOMATOM",
            "Collection": "CMB-CRC",
            "SeriesInstanceUID": "1.1",
            "StudyInstanceUID": "s1",
            "PatientID": "pA",
            "SeriesDescription": "Abdomen portal venous",
            "BodyPartExamined": "ABDOMEN",
            "ImageCount": 300,
            "LicenseName": "CC BY 4.0",
        },
        {  # a localiser must be screened out
            "Manufacturer": "GE MEDICAL SYSTEMS",
            "Collection": "CMB-CRC",
            "SeriesInstanceUID": "2.1",
            "PatientID": "pB",
            "SeriesDescription": "Scout localizer",
            "ImageCount": 3,
        },
        {  # unknown vendor is dropped before screening
            "Manufacturer": "ACME",
            "Collection": "CMB-CRC",
            "SeriesInstanceUID": "3.1",
            "SeriesDescription": "Abdomen",
            "ImageCount": 300,
        },
    ]
    candidates = [c for c in (candidate_from_index_row(r) for r in rows) if c is not None]
    assert len(candidates) == 2  # ACME dropped as an unknown vendor
    kept, excluded = screen(candidates)
    assert [c.series_uid for c in kept] == ["1.1"]  # only the abdominal diagnostic series
    assert excluded  # the localiser is counted under its reason
    assert all(isinstance(c, Candidate) for c in kept)
    assert one_series_per_patient(kept)[0].series_uid == "1.1"

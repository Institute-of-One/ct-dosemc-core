"""IORN-006 organ index is pinned to the published release, not a dirty tree."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import extract_iorn006_index as extract  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "results" / "phase2_cohort" / "iorn006_organ_index.json"
SISTER = Path(__file__).resolve().parent.parent.parent / "ctsegdose_core"


def test_classify_origin_is_prefix_not_guesswork() -> None:
    assert extract.classify_origin("recorded (0018,9345)") == "recorded"
    assert extract.classify_origin(
        "reconstructed (open MIRDct table, GE Optima 660)"
    ) == "reconstructed"
    assert extract.classify_origin("unavailable") == "unavailable"
    assert extract.classify_origin(None) == "unavailable"


def test_apply_ctdivol_uses_006_rounding_and_leaves_w_o_untouched() -> None:
    organs = [
        {"organ": "liver", "relative_weight": 0.9, "organ_weighted_ctdivol_mgy": None},
        {"organ": "spleen", "relative_weight": 1.1, "organ_weighted_ctdivol_mgy": None},
    ]
    out = extract.apply_ctdivol(organs, 10.0, "reconstructed (ctdose-core v0.1.1, GE LightSpeed 16)")
    assert organs[0]["organ_weighted_ctdivol_mgy"] is None  # input not mutated
    assert out[0]["ctdivol_mgy"] == 10.0
    assert out[0]["organ_weighted_ctdivol_mgy"] == 9.0
    assert out[1]["organ_weighted_ctdivol_mgy"] == 11.0
    assert out[0]["relative_weight"] == 0.9


def test_figure4_low_confidence_is_an_open_square() -> None:
    """004's own warning, not a new policy: score < 0.6 → hollow square."""
    assert extract.figure4_marker("recorded") == "recorded"
    assert extract.figure4_marker("unavailable") == "unavailable"
    assert extract.figure4_marker("reconstructed") == "reconstructed"
    assert (
        extract.figure4_marker(
            "reconstructed",
            {
                "match": "fuzzy",
                "match_score": 0.67,
                "resolver_warnings": [],
            },
        )
        == "reconstructed"
    )
    assert (
        extract.figure4_marker(
            "reconstructed",
            {
                "match": "fuzzy",
                "match_score": 0.50,
                "resolver_warnings": [
                    "scanner model 'Revolution CT' matched 'Revolution CT ES' "
                    "with low confidence (0.50); verify the coefficients apply"
                ],
            },
        )
        == "reconstructed_low_confidence"
    )
    from figure4_scatter import matplotlib_style

    hollow = matplotlib_style("reconstructed_low_confidence")
    filled = matplotlib_style("reconstructed")
    recorded = matplotlib_style("recorded")
    assert hollow["facecolors"] == "none"
    assert hollow["marker"] == "s"
    assert filled["facecolors"] != "none"
    assert filled["marker"] == "s"
    assert recorded["marker"] == "o"


def test_release_constants_match_the_zenodo_snapshot() -> None:
    assert extract.IORN006_RELEASE_TAG == "v0.1.1"
    assert extract.IORN006_RELEASE_COMMIT == "46edee6423ddc19b47efae180d8edf527299d066"
    assert extract.IORN006_VERSION_DOI == "10.5281/zenodo.21817307"
    assert extract.IORN004_RELEASE_TAG == "v0.1.1"
    assert extract.IORN004_RELEASE_COMMIT == "5753a109dd245b1f6bbc207b5248ae35faecbe5a"
    assert extract.IORN004_VERSION_DOI == "10.5281/zenodo.21636719"


@pytest.mark.skipif(not (SISTER / ".git").exists(), reason="ctsegdose_core sibling not present")
def test_v0_1_1_tag_is_the_pinned_commit() -> None:
    peeled = extract._peel_commit(SISTER, "v0.1.1")
    assert peeled == extract.IORN006_RELEASE_COMMIT


@pytest.mark.skipif(not RESULTS.is_file(), reason="extract has not been run yet")
def test_extracted_index_is_the_release_blob_and_closes_arithmetically() -> None:
    payload = json.loads(RESULTS.read_text(encoding="utf-8"))
    i6 = payload["iorn006"]
    assert i6["working_tree_dirty"] is False
    assert i6["git_commit"] == extract.IORN006_RELEASE_COMMIT
    assert i6["zenodo_version_doi"] == extract.IORN006_VERSION_DOI
    assert i6["release"] == "v0.1.1"
    assert i6["source_read"].startswith("git show ")
    assert len(i6["source_sha256"]) == 64

    summary = payload["summary"]
    assert summary["n_matched"] == 32
    assert summary["n_missing_from_iorn006"] == 0
    origins = {s["ctdivol_origin"] for s in payload["series"]}
    assert origins <= {"recorded", "reconstructed", "unavailable"}
    assert sum(summary["n_series_by_ctdivol_origin"].values()) == 32

    filled = set(summary.get("reconstructed_here_uids") or [])
    for series in payload["series"]:
        origin = series["ctdivol_origin"]
        assert origin == extract.classify_origin(series["ctdivol_source"])
        if origin == "unavailable":
            assert series["ctdivol_mgy"] is None
            continue
        assert series["ctdivol_mgy"] is not None
        if series["series_instance_uid"] not in filled:
            continue
        # 004-filled rows must close: we form CTDIvol_o from the rounded CTDIvol
        # and 006's w_o. Copied 006 rows keep 006's own rounding and are not
        # re-derived here.
        for organ in series["organs"]:
            expected = round(float(series["ctdivol_mgy"]) * float(organ["relative_weight"]), 3)
            assert organ["organ_weighted_ctdivol_mgy"] == expected
        recon = series["ctdivol_reconstruction"]
        assert recon["via"].startswith("ctdose-core")
        assert recon["release"] == "v0.1.1"
        assert recon["git_commit"] == extract.IORN004_RELEASE_COMMIT
        assert recon["zenodo_version_doi"] == extract.IORN004_VERSION_DOI

    origins = summary["n_series_by_ctdivol_origin"]
    assert origins == {"recorded": 23, "reconstructed": 7, "unavailable": 2}
    assert summary["n_reconstructed_already_in_iorn006"] == 4
    assert summary["n_reconstructed_here_via_iorn004"] == 3
    assert summary["n_series_with_weighted_ctdivol"] == 30
    markers = {s["figure4_marker"] for s in payload["series"]}
    assert "reconstructed_low_confidence" in markers
    low = [
        s
        for s in payload["series"]
        if s["figure4_marker"] == "reconstructed_low_confidence"
    ]
    assert len(low) == 1
    assert low[0]["model_name"] == "Revolution CT"
    assert payload["scatter"]["markers"]["reconstructed_low_confidence"]["facecolor"] == "none"
    assert "Open squares" in payload["scatter"]["caption_line"]
    reserved = payload["scatter"]["robustness_recorded_only"]
    assert reserved["n_series"] == 23
    assert reserved["gated_on"].startswith("007")
    assert "23 series with a recorded CTDIvol" in reserved["sentence"]


@pytest.mark.skipif(not RESULTS.is_file(), reason="extract has not been run yet")
def test_recorded_only_robustness_is_a_subset_not_a_new_calculation() -> None:
    from figure4_scatter import points_from_index, recorded_only, robustness_recorded_only_line

    index = json.loads(RESULTS.read_text(encoding="utf-8"))
    points = points_from_index(index, doses=None)
    rec = recorded_only(points)
    assert rec
    assert all(p["figure4_marker"] == "recorded" for p in rec)
    assert len({p["series_instance_uid"] for p in rec}) == 23
    assert len({p["series_instance_uid"] for p in points}) == 30
    line = robustness_recorded_only_line(points)
    assert line["status"] == "gated"
    assert line["n_series_recorded_only"] == 23
    assert "sentence_to_report" not in line

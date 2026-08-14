"""Extract IORN-006 organ-weighted CTDIvol for this project's eligible 32 series.

The 006 values come from the **published release**, not from a dirty working tree:

    ctsegdose-core v0.1.1
    commit 46edee6423ddc19b47efae180d8edf527299d066
    version DOI 10.5281/zenodo.21817307

``git show <ref>:results/organ_dose_1.5mm.json`` is the default source, so a
reviewer who clones the Zenodo snapshot gets the same bytes as Figure 4's x-axis
for every organ that 006 already defined.

Series that 006 left without CTDIvol are then reconstructed with **ctdose-core
v0.1.1** (IORN-004, version DOI 10.5281/zenodo.21636719): recorded tag/RDSR if
present, otherwise the open MIRDct table via 004's published scanner resolver.
``w_o`` is never recomputed; CTDIvol_o = CTDIvol * w_o. Each series records
whether its CTDIvol is recorded or reconstructed.

No Monte Carlo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ct_dosemc_core.provenance import write_results  # noqa: E402

DEFAULT_SISTER = REPO.parent / "ctsegdose_core"
DEFAULT_CTDOSE = REPO.parent / "ctdose-core"
DEFAULT_DICOM_ROOT = REPO.parent / "ctsegdose_core"
DEFAULT_ELIGIBILITY = REPO / "results" / "phase2_cohort" / "density_eligibility.json"
DEFAULT_OUT = REPO / "results" / "phase2_cohort" / "iorn006_organ_index.json"
DEFAULT_DATA = REPO / "data" / "PROVENANCE.json"

IORN006_RELEASE_TAG = "v0.1.1"
IORN006_RELEASE_COMMIT = "46edee6423ddc19b47efae180d8edf527299d066"
IORN006_VERSION_DOI = "10.5281/zenodo.21817307"
IORN006_CONCEPT_DOI = "10.5281/zenodo.21817234"
IORN006_BLOB = "results/organ_dose_1.5mm.json"

IORN004_RELEASE_TAG = "v0.1.1"
IORN004_RELEASE_COMMIT = "5753a109dd245b1f6bbc207b5248ae35faecbe5a"
IORN004_VERSION_DOI = "10.5281/zenodo.21636719"
IORN004_CONCEPT_DOI = "10.5281/zenodo.21636082"

_ORGAN_KEEP = (
    "organ",
    "relative_weight",
    "organ_weighted_ctdivol_mgy",
    "ctdivol_mgy",
    "ctdivol_source",
    "truncated",
    "volume_cm3",
    "mass_g",
)

# Header-only reconstruction; 004's pipeline uses 32 cm for body examinations.
_BODY_PHANTOM_CM = 32


def _git(repo: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def _git_bytes(repo: Path, spec: str) -> bytes:
    out = subprocess.run(
        ["git", "-C", str(repo), "show", spec],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if out.returncode != 0:
        err = (out.stderr or out.stdout).decode("utf-8", "replace").strip()
        raise SystemExit(f"git show {spec} failed in {repo}: {err}")
    return out.stdout


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def classify_origin(source: str | None) -> str:
    """recorded / reconstructed / unavailable. Never inferred from a missing field."""
    text = (source or "").strip().lower()
    if text.startswith("recorded"):
        return "recorded"
    if text.startswith("reconstructed"):
        return "reconstructed"
    return "unavailable"


# 004's scanners.resolve_model emits a low-confidence warning below this score
# (ctdose_core/scanners.py, v0.1.1). Figure 4 uses the same cut: hollow marker,
# not a second reconstruction policy.
IORN004_LOW_CONFIDENCE_SCORE = 0.6

FIGURE4_MARKERS = {
    "recorded": {
        "marker": "o",
        "facecolor": "filled",
        "label": "recorded CTDIvol (DICOM/RDSR)",
    },
    "reconstructed": {
        "marker": "s",
        "facecolor": "filled",
        "label": "reconstructed CTDIvol (exact or high-confidence table match)",
    },
    "reconstructed_low_confidence": {
        "marker": "s",
        "facecolor": "none",
        "label": (
            "reconstructed CTDIvol, low-confidence scanner match "
            "(IORN-004 warning; Revolution CT → Revolution CT ES, score 0.50)"
        ),
    },
    "unavailable": {
        "omit": True,
        "label": "not plotted (LightSpeed Ultra, Revolution EVO)",
    },
}


def figure4_marker(
    origin: str,
    reconstruction: dict[str, Any] | None = None,
) -> str:
    """Which Fig. 4 symbol a series uses. Hollow = 004's own low-confidence warning."""
    if origin != "reconstructed":
        return origin
    recon = reconstruction or {}
    score = recon.get("match_score")
    warnings = recon.get("resolver_warnings") or []
    low = recon.get("match") == "fuzzy" and (
        (score is not None and float(score) < IORN004_LOW_CONFIDENCE_SCORE)
        or any("low confidence" in str(w) for w in warnings)
    )
    return "reconstructed_low_confidence" if low else "reconstructed"


def apply_ctdivol(
    organs: list[dict[str, Any]],
    ctdivol_mgy: float | None,
    source: str,
) -> list[dict[str, Any]]:
    """CTDIvol_o = CTDIvol * w_o, rounded the way IORN-006 reports (3 d.p.)."""
    value = None if ctdivol_mgy is None else round(float(ctdivol_mgy), 3)
    out = []
    for organ in organs:
        rec = dict(organ)
        rec["ctdivol_mgy"] = value
        rec["ctdivol_source"] = source
        weight = rec.get("relative_weight")
        rec["organ_weighted_ctdivol_mgy"] = (
            None if value is None or weight is None else round(value * float(weight), 3)
        )
        out.append(rec)
    return out


def _peel_commit(repo: Path, ref: str) -> str | None:
    return _git(repo, "rev-parse", f"{ref}^{{commit}}") or _git(repo, "rev-parse", ref)


def load_iorn006_blob(sister: Path, ref: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read organ_dose_1.5mm.json from a git object, never from a dirty work tree."""
    commit = _peel_commit(sister, ref)
    if not commit:
        raise SystemExit(
            f"IORN-006 ref {ref!r} is not in {sister}. Clone "
            "https://github.com/Institute-of-One/ctsegdose-core and check out "
            f"{IORN006_RELEASE_TAG} (Zenodo {IORN006_VERSION_DOI})."
        )
    blob = _git_bytes(sister, f"{ref}:{IORN006_BLOB}")
    payload = json.loads(blob.decode("utf-8"))
    tag_commit = _peel_commit(sister, IORN006_RELEASE_TAG)
    provenance = {
        "project": "ctsegdose-core (IORN-006)",
        "endpoint": "organ-specific weighted CTDIvol index (not absorbed dose)",
        "formula": "CTDIvol_o = CTDIvol * w_o;  w_o = mean_{z in organ} I(z) / mean_z I(z)",
        "release": IORN006_RELEASE_TAG,
        "git_commit": commit,
        "git_commit_short": commit[:7],
        "working_tree_dirty": False,
        "zenodo_version_doi": IORN006_VERSION_DOI,
        "zenodo_concept_doi": IORN006_CONCEPT_DOI,
        "derived_from_iorn004_zenodo_doi": IORN004_CONCEPT_DOI,
        "repository": _git(sister, "remote", "get-url", "origin")
        or "https://github.com/Institute-of-One/ctsegdose-core",
        "source_file": IORN006_BLOB,
        "source_read": f"git show {ref}:{IORN006_BLOB}",
        "source_sha256": sha256_bytes(blob),
        "release_tag_commit": tag_commit,
        "note": (
            "Read from the published v0.1.1 object, not from the sister working "
            "tree. A reviewer who fetches Zenodo 10.5281/zenodo.21817307 and runs "
            "this tool against that checkout gets the same 006 bytes. Imaging is "
            "not copied. Values needed for the 007 scatter (w_o and, where 006 "
            "defined it, CTDIvol_o) are copied; the rest of the sister results "
            "file is not."
        ),
    }
    return payload, provenance


def _ensure_ctdose(ctdose: Path) -> None:
    if str(ctdose) not in sys.path:
        sys.path.insert(0, str(ctdose))


def reconstruct_ctdivol(
    dicom_dir: Path,
    *,
    ctdose: Path,
) -> dict[str, Any]:
    """One series: recorded CTDIvol, else IORN-004's published reconstruction.

    Exact table aliases first (what 006 / 004 ``analyse()`` use). If that refuses
    the scanner, 004's ``scanners.resolve_model`` (fuzzy, min score 0.45). If that
    also refuses, the series is unrecoverable — no silent alias is invented here.
    """
    _ensure_ctdose(ctdose)
    from ctdose_core.ctdi_table import CoefficientNotAvailable
    from ctdose_core.ctdi_table import resolve_model as exact_resolve
    from ctdose_core.ctdi_table import resolve_vendor
    from ctdose_core.io import load_series
    from ctdose_core.metrics import acquisition_from_series, estimate_ctdivol_open
    from ctdose_core.pipeline import collect_recorded_dose
    from ctdose_core.scanners import match_models
    from ctdose_core.scanners import resolve_model as fuzzy_resolve

    series = load_series(dicom_dir)
    recorded = collect_recorded_dose(series)
    if recorded.ctdivol is not None:
        q = recorded.ctdivol
        return {
            "ok": True,
            "origin": "recorded",
            "ctdivol_mgy": float(q),
            "ctdivol_source": q.formula or "recorded",
            "reconstruction": {
                "via": "ctdose-core (IORN-004)",
                "release": IORN004_RELEASE_TAG,
                "git_commit": IORN004_RELEASE_COMMIT,
                "zenodo_version_doi": IORN004_VERSION_DOI,
                "quantity": q.to_dict(),
            },
        }

    acq = acquisition_from_series(series)
    match_kind = "exact"
    match_score: float | None = None
    resolver_warnings: list[str] = []
    try:
        vendor, model = exact_resolve(series.manufacturer, series.model_name)
    except CoefficientNotAvailable:
        try:
            model, resolver_warnings = fuzzy_resolve(
                series.model_name, series.manufacturer
            )
        except LookupError as exc:
            return {
                "ok": False,
                "origin": "unavailable",
                "ctdivol_mgy": None,
                "ctdivol_source": "unavailable",
                "error": str(exc),
                "dicom_model": series.model_name,
                "manufacturer": series.manufacturer,
            }
        vendor = resolve_vendor(series.manufacturer)
        if vendor is None:
            return {
                "ok": False,
                "origin": "unavailable",
                "ctdivol_mgy": None,
                "ctdivol_source": "unavailable",
                "error": f"manufacturer {series.manufacturer!r} is not a tabulated vendor",
                "dicom_model": series.model_name,
                "manufacturer": series.manufacturer,
            }
        match_kind = "fuzzy"
        hits = match_models(series.model_name, series.manufacturer)
        match_score = hits[0].score if hits else None

    try:
        q = estimate_ctdivol_open(
            acq, vendor=vendor, model=model, phantom_cm=_BODY_PHANTOM_CM
        )
    except (CoefficientNotAvailable, ValueError) as exc:
        return {
            "ok": False,
            "origin": "unavailable",
            "ctdivol_mgy": None,
            "ctdivol_source": "unavailable",
            "error": str(exc),
            "dicom_model": series.model_name,
            "manufacturer": series.manufacturer,
            "table_model": f"{vendor} {model}",
        }

    source = (
        f"reconstructed (ctdose-core {IORN004_RELEASE_TAG}, "
        f"{q.inputs.get('table_model') or f'{vendor} {model}'})"
    )
    return {
        "ok": True,
        "origin": "reconstructed",
        "ctdivol_mgy": float(q),
        "ctdivol_source": source,
        "reconstruction": {
            "via": "ctdose-core (IORN-004)",
            "release": IORN004_RELEASE_TAG,
            "git_commit": IORN004_RELEASE_COMMIT,
            "zenodo_version_doi": IORN004_VERSION_DOI,
            "zenodo_concept_doi": IORN004_CONCEPT_DOI,
            "formula": q.formula,
            "dicom_model": series.model_name,
            "manufacturer": series.manufacturer,
            "table_model": q.inputs.get("table_model") or f"{vendor} {model}",
            "match": match_kind,
            "match_score": match_score,
            "resolver_warnings": resolver_warnings,
            "quantity": q.to_dict(),
        },
    }


def _dicom_dir(row: dict[str, Any], dicom_root: Path) -> Path:
    local = str(row.get("local_path") or "")
    p = Path(local)
    return p if p.is_absolute() else (dicom_root / local)


def _ctdose_pin(ctdose: Path) -> dict[str, Any]:
    head = _peel_commit(ctdose, "HEAD")
    tag = _peel_commit(ctdose, IORN004_RELEASE_TAG)
    modules = (
        "ctdose_core/metrics.py",
        "ctdose_core/scanners.py",
        "ctdose_core/ctdi_table.py",
        "ctdose_core/pipeline.py",
    )
    diff = _git(ctdose, "diff", "--stat", f"{IORN004_RELEASE_TAG}..HEAD", "--", *modules)
    return {
        "project": "ctdose-core (IORN-004)",
        "release": IORN004_RELEASE_TAG,
        "cited_commit": IORN004_RELEASE_COMMIT,
        "zenodo_version_doi": IORN004_VERSION_DOI,
        "zenodo_concept_doi": IORN004_CONCEPT_DOI,
        "repository": _git(ctdose, "remote", "get-url", "origin")
        or "https://github.com/Institute-of-One/ctdose-core",
        "local_head": head,
        "local_tag_commit": tag,
        "reconstruction_modules_diff_vs_release": diff or "",
        "note": (
            "Reconstruction uses 004's published APIs (load_series, "
            "collect_recorded_dose, scanners.resolve_model, estimate_ctdivol_open). "
            "The cited version is v0.1.1 / 10.5281/zenodo.21636719. metrics / "
            "scanners / ctdi_table / pipeline are unchanged since that tag; io.py "
            "on HEAD only tightens pixel-padding and is not used for pixels here."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sister", type=Path, default=DEFAULT_SISTER)
    ap.add_argument(
        "--iorn006-ref",
        default=IORN006_RELEASE_COMMIT,
        help="git ref in the sister repo whose organ_dose_1.5mm.json is read "
        f"(default: {IORN006_RELEASE_COMMIT}, the v0.1.1 release)",
    )
    ap.add_argument("--eligibility", type=Path, default=DEFAULT_ELIGIBILITY)
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--dicom-root", type=Path, default=DEFAULT_DICOM_ROOT)
    ap.add_argument("--ctdose", type=Path, default=DEFAULT_CTDOSE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--no-reconstruct",
        action="store_true",
        help="copy 006 values only; do not call ctdose-core on missing CTDIvol",
    )
    args = ap.parse_args(argv)

    payload, iorn006 = load_iorn006_blob(args.sister, args.iorn006_ref)
    if iorn006["git_commit"] != IORN006_RELEASE_COMMIT:
        raise SystemExit(
            f"ref {args.iorn006_ref} peeled to {iorn006['git_commit']}, "
            f"not the published v0.1.1 commit {IORN006_RELEASE_COMMIT}. "
            "Figure 4's x-axis must come from that object."
        )

    elig = json.loads(args.eligibility.read_text(encoding="utf-8"))
    wanted = {
        str(r["series_instance_uid"]): r
        for r in elig["series"]
        if r.get("eligible")
    }
    if len(wanted) != int(elig["n_eligible"]):
        raise SystemExit(
            f"eligibility n_eligible={elig['n_eligible']} but {len(wanted)} eligible rows"
        )
    data_rows = {
        str(s["series_instance_uid"]): s
        for s in json.loads(args.data.read_text(encoding="utf-8"))["series"]
    }
    by_uid = {str(s["series_instance_uid"]): s for s in payload["series"]}

    extracted: list[dict[str, Any]] = []
    missing: list[str] = []
    n_organs = 0
    n_with_index = 0
    n_index_series = 0
    n_weight_only = 0
    by_vendor: dict[str, dict[str, int]] = {}
    origin_counts = {"recorded": 0, "reconstructed": 0, "unavailable": 0}
    marker_counts: dict[str, int] = {}
    reconstructed_here: list[str] = []
    unrecoverable: list[dict[str, Any]] = []
    iorn004_pin = None if args.no_reconstruct else _ctdose_pin(args.ctdose)

    for uid, row in wanted.items():
        vendor = str(row.get("vendor") or "")
        vc = by_vendor.setdefault(
            vendor, {"eligible": 0, "matched": 0, "with_weighted_ctdivol": 0}
        )
        vc["eligible"] += 1
        src = by_uid.get(uid)
        if src is None:
            missing.append(uid)
            continue
        vc["matched"] += 1
        organs = [{k: organ.get(k) for k in _ORGAN_KEEP} for organ in (src.get("organs") or [])]
        ctdivol = src.get("ctdivol_mgy")
        source = str(src.get("ctdivol_source") or "unavailable")
        origin = classify_origin(source)
        reconstruction: dict[str, Any] | None = None

        if ctdivol is None and not args.no_reconstruct:
            data = data_rows.get(uid)
            if data is None:
                raise SystemExit(f"{uid} is eligible but missing from {args.data}")
            directory = _dicom_dir(data, args.dicom_root)
            if not directory.is_dir():
                raise SystemExit(
                    f"DICOM for {uid} not at {directory}. Re-fetch from TCIA "
                    f"(data/PROVENANCE.json) or pass --dicom-root."
                )
            hit = reconstruct_ctdivol(directory, ctdose=args.ctdose)
            origin = hit["origin"]
            ctdivol = hit["ctdivol_mgy"]
            source = hit["ctdivol_source"]
            reconstruction = hit.get("reconstruction")
            if hit["ok"]:
                organs = apply_ctdivol(organs, ctdivol, source)
                reconstructed_here.append(uid)
            else:
                unrecoverable.append(
                    {
                        "series_instance_uid": uid,
                        "vendor": vendor,
                        "model_name": src.get("model_name"),
                        "error": hit.get("error"),
                        "dicom_model": hit.get("dicom_model"),
                    }
                )

        for rec in organs:
            n_organs += 1
            if rec["organ_weighted_ctdivol_mgy"] is not None:
                n_with_index += 1
        has_index = any(o["organ_weighted_ctdivol_mgy"] is not None for o in organs)
        if has_index:
            n_index_series += 1
            vc["with_weighted_ctdivol"] += 1
        else:
            n_weight_only += 1
        origin_counts[origin] = origin_counts.get(origin, 0) + 1
        marker = figure4_marker(origin, reconstruction)
        marker_counts[marker] = marker_counts.get(marker, 0) + 1

        entry: dict[str, Any] = {
            "series_instance_uid": uid,
            "vendor": src.get("vendor") or vendor,
            "model_name": src.get("model_name"),
            "ctdivol_mgy": (
                None if ctdivol is None else round(float(ctdivol), 3)
            )
            if reconstruction is not None
            else src.get("ctdivol_mgy"),
            "ctdivol_source": source,
            "ctdivol_origin": origin,
            "figure4_marker": marker,
            "scan_mean_tube_current_ma": src.get("scan_mean_tube_current_ma"),
            "n_organs": len(organs),
            "organs": organs,
        }
        if reconstruction is not None:
            entry["ctdivol_reconstruction"] = reconstruction
        extracted.append(entry)

    try:
        elig_rel = args.eligibility.resolve().relative_to(REPO).as_posix()
    except ValueError:
        elig_rel = str(args.eligibility)

    write_results(
        args.out,
        {
            "what": (
                "IORN-006 organ-specific weighted CTDIvol index for the IORN-007 "
                "absorbed-dose eligible cohort (N=32), taken from the published "
                f"v0.1.1 object ({IORN006_VERSION_DOI}). Series that 006 left "
                "without CTDIvol are filled by ctdose-core v0.1.1 reconstruction "
                "where that resolver accepts the scanner."
            ),
            "not": (
                "Not absorbed dose. Not a third-party coefficient table. Not a "
                "re-segmentation. w_o is copied from the 006 release; CTDIvol is "
                "either that release's recorded/reconstructed value or an IORN-004 "
                "reconstruction recorded beside it."
            ),
            "eligibility": {
                "file": elig_rel,
                "n_assessed": elig["n_assessed"],
                "n_eligible": elig["n_eligible"],
                "n_excluded": elig["n_excluded"],
                "criterion": elig["single_gate"],
            },
            "iorn006": iorn006,
            "iorn004": iorn004_pin,
            "recipe": {
                "006_blob": (
                    f"git -C <ctsegdose-core> show {IORN006_RELEASE_COMMIT}:{IORN006_BLOB}"
                ),
                "004_reconstruct": (
                    "ctdose_core.io.load_series + collect_recorded_dose; "
                    "if no recorded CTDIvol, ctdi_table.resolve_model then "
                    "scanners.resolve_model (min score 0.45); "
                    "estimate_ctdivol_open(..., phantom_cm=32); "
                    "CTDIvol_o = CTDIvol * w_o with 006's w_o"
                ),
                "command": "python tools/extract_iorn006_index.py",
            },
            "summary": {
                "n_eligible": len(wanted),
                "n_matched": len(extracted),
                "n_missing_from_iorn006": len(missing),
                "missing_uids": missing,
                "n_organ_records": n_organs,
                "n_organ_records_with_weighted_ctdivol": n_with_index,
                "n_series_with_weighted_ctdivol": n_index_series,
                "n_series_weight_only_ctdivol_unavailable": n_weight_only,
                "n_series_by_ctdivol_origin": origin_counts,
                "n_series_by_figure4_marker": marker_counts,
                "n_reconstructed_already_in_iorn006": (
                    origin_counts.get("reconstructed", 0) - len(reconstructed_here)
                ),
                "n_reconstructed_here_via_iorn004": len(reconstructed_here),
                "reconstructed_here_uids": reconstructed_here,
                "n_unrecoverable_after_iorn004": len(unrecoverable),
                "unrecoverable": unrecoverable,
                "arithmetic": (
                    f"{origin_counts.get('recorded', 0)} recorded + "
                    f"{origin_counts.get('reconstructed', 0) - len(reconstructed_here)} "
                    f"already reconstructed in IORN-006 v0.1.1 = "
                    f"{origin_counts.get('recorded', 0) + origin_counts.get('reconstructed', 0) - len(reconstructed_here)} "
                    f"with a defined index before this fill; "
                    f"+ {len(reconstructed_here)} reconstructed here via IORN-004 = "
                    f"{n_index_series}; {n_weight_only} remain unrecoverable. "
                    "Normalisation to a recorded CTDIvol applies to the recorded "
                    "series only."
                ),
                "by_vendor": by_vendor,
            },
            "scatter": {
                "x": "organ_weighted_ctdivol_mgy (IORN-006 index, mGy)",
                "y": "absorbed organ dose (IORN-007, mGy) — GATED, not in this file",
                "markers": FIGURE4_MARKERS,
                "caption_line": (
                    "Open squares: CTDIvol reconstructed under IORN-004's own "
                    "low-confidence warning (Revolution CT matched to Revolution "
                    "CT ES, score 0.50). Filled squares: reconstructed with an "
                    "exact or high-confidence table match. Filled circles: "
                    "recorded in DICOM/RDSR. Two series omitted (LightSpeed Ultra, "
                    "Revolution EVO)."
                ),
                "fallback_when_ctdivol_unavailable": (
                    "relative_weight w_o is present on every organ; the mGy-vs-mGy "
                    "scatter uses only series with a defined CTDIvol_o. A scanner "
                    "004's resolver refuses is unrecoverable, not aliased."
                ),
            },
            "series": extracted,
        },
    )
    print(
        f"wrote {args.out}  matched {len(extracted)}/{len(wanted)}  "
        f"index {n_index_series} series / {n_with_index} organs  "
        f"origin {origin_counts}  "
        f"004-filled {len(reconstructed_here)}  "
        f"unrecoverable {len(unrecoverable)}"
    )
    if missing:
        print(f"missing from IORN-006: {missing}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

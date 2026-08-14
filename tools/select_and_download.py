"""Phase 1: select a small, balanced, multi-vendor abdominal CT sample and fetch only it.

Three stages, each of which writes its result and can be re-run on its own::

    python tools/select_and_download.py --stage plan       # metadata only, no images
    python tools/select_and_download.py --stage verify     # a few header probes per series
    python tools/select_and_download.py --stage download   # only the series that passed

``--stage all`` runs the three in order. ``--dry-run`` stops before any image transfer,
so the download stage prints what it would fetch and how many gigabytes that is.

Why it is built this way: feeding a collection manifest to NBIA Data Retriever pulls the
whole collection -- about 600 GB for the low-dose CT collection, most of it raw
projection data. Instead the catalogue is read as metadata, the candidates are screened
on that metadata, each survivor is probed with a handful of single images to confirm it
records per-slice tube current (0018,1151) and readable Hounsfield units, and only then
is a series transferred. The typical cost is a few gigabytes for the whole sample.

Outputs::

    results/candidates.json     the screened candidate pool and why each rejection went
    results/verification.json   per-series header evidence and the keep/drop verdict
    data/PROVENANCE.json        collection, DOI, UID, licence and retrieval date per series
    data/<vendor>/<collection>__<patient>/<series-uid>/*.dcm   (git-ignored, never published)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ct_dosemc_core import __version__  # noqa: E402
from ct_dosemc_core.acquisition import (  # noqa: E402
    SeriesProvenance,
    document,
    series_local_path,
)
from ct_dosemc_core.nbia import DATA_USE_NOTE, NBIA_BASE, NbiaClient  # noqa: E402
from ct_dosemc_core.selection import (  # noqa: E402
    MIN_IMAGES,
    MIN_Z_COVERAGE_MM,
    MODULATION_TOLERANCE,
    VENDORS,
    Candidate,
    candidate_from_index_row,
    candidate_from_survey_row,
    diversify,
    is_abdominal,
    one_series_per_patient,
    read_probe,
    screen,
)

#: Abdominal CT collections queried in addition to whatever the IORN-004 survey vouches
#: for. They are the collections that survey's abdominal rows fall in, plus the widely
#: used abdominal collections it happened not to sample; all are openly licensed (CC BY)
#: on TCIA. The list only decides *where to look*: every series still has to pass the
#: metadata screen and the header probe.
DEFAULT_COLLECTIONS: tuple[str, ...] = (
    "C4KC-KiTS",
    "TCGA-KIRC",
    "TCGA-KIRP",
    "TCGA-KICH",
    "TCGA-LIHC",
    "TCGA-STAD",
    "TCGA-COAD",
    "CPTAC-CCRCC",
    "CPTAC-PDA",
    "CPTAC-STAD",
    "CPTAC-UCEC",
    "CMB-CRC",
    "CMB-MEL",
    "CMB-PCA",
    "CMB-LCA",
    "CMB-MML",
    "HCC-TACE-Seg",
    "Colorectal-Liver-Metastases",
    "Pancreatic-CT-CBCT-SEG",
    "Pancreas-CT",
    "CTpred-Sunitinib-panNET",
    "Adrenal-ACC-Ki67-Seg",
    "StageII-Colorectal-CT",
    "CT4Harmonization-Multicentric",
    "CC-Tumor-Heterogeneity",
    "VAREPOP-APOLLO",
    "LDCT-and-Projection-data",
)

SURVEY_JSON = REPO.parent / "ctdose-core" / "results" / "survey.json"


def _vendor_slug(vendor: str) -> str:
    return vendor.replace("/", "_").replace(" ", "_")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --- stage 1: plan ---------------------------------------------------------------------


def survey_seed_uids(path: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Series UIDs the IORN-004 survey already screened, and their collections per vendor.

    The survey catalogued 400 series over four manufacturers and 92 collections through
    the same public API and without bulk download. Its abdominal rows are the primary
    candidate source here: reusing them means the multi-vendor list starts from screened
    series rather than from a fresh crawl.
    """
    if not path.exists():
        return set(), {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    uids: set[str] = set()
    collections: dict[str, set[str]] = {}
    for row in payload.get("series", []):
        cand = candidate_from_survey_row(row)
        if cand is None or not is_abdominal(cand):
            continue
        uids.add(cand.series_uid)
        collections.setdefault(cand.vendor, set()).add(cand.collection)
    return uids, collections


def stage_plan(args: argparse.Namespace, client: NbiaClient) -> dict[str, Any]:
    started = _now()
    seed_uids, seed_collections = survey_seed_uids(args.survey)
    queried = sorted({*DEFAULT_COLLECTIONS, *args.collections, *(c for v in seed_collections.values() for c in v)})

    rows: list[dict[str, Any]] = []
    failures: dict[str, str] = {}
    for name in queried:
        try:
            got = client.series(collection=name, modality="CT")
        except Exception as exc:  # a collection may be withdrawn or renamed
            failures[name] = f"{type(exc).__name__}: {exc}"
            continue
        rows.extend(got)
        print(f"  {len(got):5d} CT series  {name}")

    candidates: list[Candidate] = []
    for row in rows:
        cand = candidate_from_index_row(row)
        if cand is None:
            continue
        if cand.series_uid in seed_uids:
            cand.source = "iorn004-survey"
        candidates.append(cand)

    kept, excluded = screen(candidates)
    deduped = one_series_per_patient(kept)
    ordered = diversify(deduped, per_vendor=args.per_vendor)

    payload = {
        "provenance": {
            "stage": "plan - metadata only, no pixel data transferred",
            "generated_by": "tools/select_and_download.py --stage plan",
            "ct_dosemc_core_version": __version__,
            "archive": NBIA_BASE,
            "survey_reused": str(args.survey) if args.survey.exists() else None,
            "access_started_utc": started,
            "access_finished_utc": _now(),
            "data_use_note": DATA_USE_NOTE,
        },
        "parameters": {
            "modality": "CT",
            "collections_queried": queried,
            "collections_unavailable": failures,
            "vendors": list(VENDORS),
            "per_vendor_target": args.per_vendor,
            "min_images": MIN_IMAGES,
            "survey_seed_series": len(seed_uids),
        },
        "counts": {
            "index_rows": len(rows),
            "vendor_recognised": len(candidates),
            "passed_metadata_screen": len(kept),
            "after_one_series_per_patient": len(deduped),
            "probe_queue": len(ordered),
            "probe_queue_by_vendor": _by_vendor(ordered),
            "screen_exclusions": excluded,
        },
        "candidates": [c.to_dict() for c in ordered],
    }
    _write(args.results / "candidates.json", payload)
    print("\n-- plan --")
    print(f"  index rows                {len(rows)}")
    print(f"  vendor recognised         {len(candidates)}")
    print(f"  passed metadata screen    {len(kept)}")
    print(f"  one series per patient    {len(deduped)}")
    print(f"  probe queue               {len(ordered)}  {_by_vendor(ordered)}")
    print(f"  screen exclusions         {excluded}")
    return payload


def _by_vendor(items: list[Candidate]) -> dict[str, int]:
    out: dict[str, int] = {v: 0 for v in VENDORS}
    for c in items:
        out[c.vendor] = out.get(c.vendor, 0) + 1
    return out


# --- stage 2: verify -------------------------------------------------------------------


def _probe_indices(n: int, k: int) -> list[int]:
    """``k`` indices spread over ``n`` instances, ends included."""
    if n <= k:
        return list(range(n))
    return [round(i * (n - 1) / (k - 1)) for i in range(k)]


def probe_candidate(client: NbiaClient, cand: Candidate, *, n_probes: int) -> dict[str, Any]:
    """Fetch a few image headers of one series and judge it.

    A few hundred kilobytes per image, a handful of images: this is what replaces
    downloading hundreds of megabytes to discover that a series records a single fixed
    tube current and cannot support a modulation weighting.
    """
    try:
        uids = client.sop_instance_uids(cand.series_uid)
    except Exception as exc:
        probe = read_probe([], series_uid=cand.series_uid, vendor=cand.vendor, n_instances=0)
        probe.error = f"{type(exc).__name__}"
        return probe.to_dict()

    datasets = []
    error = ""
    for i in _probe_indices(len(uids), n_probes):
        try:
            datasets.append(client.single_image(cand.series_uid, uids[i]))
        except Exception as exc:
            error = f"{type(exc).__name__}"
            break
    probe = read_probe(
        datasets, series_uid=cand.series_uid, vendor=cand.vendor, n_instances=len(uids)
    )
    probe.error = error if not datasets else ""
    return probe.to_dict()


def stage_verify(args: argparse.Namespace, client: NbiaClient) -> dict[str, Any]:
    started = _now()
    plan = json.loads((args.results / "candidates.json").read_text(encoding="utf-8"))
    queue = [Candidate(**c) for c in plan["candidates"]]

    kept_by_vendor: dict[str, list[dict[str, Any]]] = {v: [] for v in VENDORS}
    probes: list[dict[str, Any]] = []
    reasons: dict[str, dict[str, int]] = {v: {} for v in VENDORS}

    for cand in queue:
        if len(kept_by_vendor[cand.vendor]) >= args.per_vendor:
            continue
        result = probe_candidate(client, cand, n_probes=args.probes)
        result["candidate"] = cand.to_dict()
        probes.append(result)
        reason = result["verdict"]
        key = reason.split(":")[0]
        reasons[cand.vendor][key] = reasons[cand.vendor].get(key, 0) + 1
        if reason == "keep":
            kept_by_vendor[cand.vendor].append(result)
        print(
            f"  {cand.vendor:14s} {cand.collection:30.30s} "
            f"n={result['n_instances']:4d} spread={result['tube_current_spread']:.3f} "
            f"-> {reason}"
        )
        if all(len(kept_by_vendor[v]) >= args.per_vendor for v in VENDORS):
            break

    kept = [r for v in VENDORS for r in kept_by_vendor[v]]
    payload = {
        "provenance": {
            "stage": "verify - image headers only (getSingleImage), no series transferred",
            "generated_by": "tools/select_and_download.py --stage verify",
            "ct_dosemc_core_version": __version__,
            "archive": NBIA_BASE,
            "access_started_utc": started,
            "access_finished_utc": _now(),
            "data_use_note": DATA_USE_NOTE,
        },
        "criteria": {
            "per_slice_tube_current_tag": "(0018,1151) present on every probed slice",
            "modulation": f"peak-to-peak / mean tube current >= {MODULATION_TOLERANCE}",
            "hu_readable": "RescaleSlope (0028,1053) and RescaleIntercept (0028,1052) present",
            "min_slices": MIN_IMAGES,
            "min_axial_extent_mm": MIN_Z_COVERAGE_MM,
            "probes_per_series": args.probes,
            "per_vendor_target": args.per_vendor,
        },
        "counts": {
            "probed": len(probes),
            "kept": len(kept),
            "kept_by_vendor": {v: len(kept_by_vendor[v]) for v in VENDORS},
            "verdicts_by_vendor": reasons,
        },
        "probes": probes,
    }
    _write(args.results / "verification.json", payload)
    print("\n-- verify --")
    print(f"  probed {len(probes)}, kept {len(kept)}: {payload['counts']['kept_by_vendor']}")
    for vendor in VENDORS:
        print(f"  {vendor:14s} {reasons[vendor]}")
    return payload


# --- stage 3: download -----------------------------------------------------------------


def stage_download(args: argparse.Namespace, client: NbiaClient) -> dict[str, Any]:
    started = _now()
    verification = json.loads((args.results / "verification.json").read_text(encoding="utf-8"))
    kept = [p for p in verification["probes"] if p["verdict"] == "keep"]

    planned_bytes = sum(int(p["candidate"].get("file_size_bytes") or 0) for p in kept)
    print(f"\n-- download -- {len(kept)} series, index reports {planned_bytes / 1e9:.2f} GB")
    if args.dry_run:
        for p in kept:
            c = p["candidate"]
            print(f"  would fetch {c['vendor']:14s} {c['collection']:28.28s} {c['series_uid']}")
        return {"dry_run": True, "n_series": len(kept), "planned_gb": planned_bytes / 1e9}

    records: list[SeriesProvenance] = []
    for i, p in enumerate(kept, 1):
        c = p["candidate"]
        subject = f"{c['collection']}__{c['patient_id'] or 'unknown'}"
        dest = args.data / _vendor_slug(c["vendor"]) / subject / c["series_uid"]
        t0 = time.monotonic()
        dest, n_files = client.download_series(c["series_uid"], dest)
        size = sum(f.stat().st_size for f in dest.glob("*.dcm"))
        records.append(
            SeriesProvenance(
                vendor=c["vendor"],
                manufacturer=c["manufacturer_raw"],
                model_name=c["model_name"],
                collection=c["collection"],
                collection_uri=c["collection_uri"],
                patient_id=c["patient_id"],
                series_instance_uid=c["series_uid"],
                study_instance_uid=c["study_uid"],
                series_description=c["series_description"],
                body_part=p["body_part"] or c["body_part"],
                n_instances=p["n_instances"],
                n_files_written=n_files,
                size_bytes=size,
                kvp=p["kvp"],
                slice_thickness_mm=p["slice_thickness_mm"],
                pixel_spacing_mm=p["pixel_spacing_mm"],
                z_coverage_mm=p["axial_extent_mm"],
                tube_current_spread=p["tube_current_spread"],
                licence=c["licence"],
                licence_uri=c["licence_uri"],
                retrieved_utc=_now(),
                local_path=series_local_path(dest, data_root=args.data, repo=REPO),
                selection_source=c["source"],
            )
        )
        print(
            f"  [{i:2d}/{len(kept)}] {c['vendor']:14s} {n_files:4d} files "
            f"{size / 1e6:7.1f} MB  {time.monotonic() - t0:5.1f}s  {c['collection']}"
        )

    payload = document(
        series=records,
        parameters={
            **verification["criteria"],
            "collections_queried": json.loads(
                (args.results / "candidates.json").read_text(encoding="utf-8")
            )["parameters"]["collections_queried"],
            "selection_stages": "plan (metadata) -> verify (header probes) -> download (kept only)",
            "data_use_note": DATA_USE_NOTE,
        },
        generated_by="tools/select_and_download.py --stage download",
        package_version=__version__,
        started_utc=started,
        finished_utc=_now(),
        exclusions=verification["counts"]["verdicts_by_vendor"],
    )
    _write(args.data / "PROVENANCE.json", payload)
    s = payload["summary"]
    print("\n-- downloaded --")
    for vendor, block in s["by_vendor"].items():
        print(
            f"  {vendor:14s} {block['n_series']:2d} series  {block['n_instances']:5d} slices  "
            f"{block['size_bytes'] / 1e9:5.2f} GB  from {len(block['collections'])} collections"
        )
    print(f"  {'TOTAL':14s} {s['n_series']:2d} series  {s['n_instances']:5d} slices  {s['size_gb']:5.2f} GB")
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  wrote {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=["plan", "verify", "download", "all"], default="all")
    ap.add_argument("--per-vendor", type=int, default=10, help="series to keep per manufacturer")
    ap.add_argument("--probes", type=int, default=6, help="image headers sampled per series")
    ap.add_argument("--collections", nargs="*", default=[], help="extra collections to query")
    ap.add_argument("--survey", type=Path, default=SURVEY_JSON, help="IORN-004 results/survey.json")
    ap.add_argument("--results", type=Path, default=REPO / "results" / "phase2_cohort")
    ap.add_argument("--data", type=Path, default=REPO / "data")
    ap.add_argument("--work-dir", type=Path, default=REPO / ".tcia_work")
    ap.add_argument("--dry-run", action="store_true", help="never transfer a whole series")
    args = ap.parse_args()

    client = NbiaClient(cache_dir=args.work_dir / "cache")
    if args.stage in ("plan", "all"):
        stage_plan(args, client)
    if args.stage in ("verify", "all"):
        stage_verify(args, client)
    if args.stage in ("download", "all"):
        stage_download(args, client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

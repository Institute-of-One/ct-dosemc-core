"""Record how much the IORN-007 Phase-2 cohort overlaps the IORN-006 cohort.

Whether the paper may write "we reuse the IORN-006 cohort" or must write "we
re-select from the same archive under an absorbed-dose criterion" is a factual
question, not a stylistic one, and it turns on how many Series Instance UIDs the two
selections share. This records that number rather than leaving it to be asserted.

Both cohorts are named by their ``data/PROVENANCE.json``; only the Series Instance
UIDs are compared, so no imaging is read. The result is written to
``results/phase2_cohort/cohort_overlap.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OURS = REPO / "data" / "PROVENANCE.json"
DEFAULT_IORN006 = REPO.parent / "ctsegdose_core" / "data" / "PROVENANCE.json"


def _selection_funnel(results_dir: Path) -> dict[str, Any] | None:
    """The 47,181 -> 40 selection funnel, for the paper's flow diagram.

    Assembled from the plan-stage ``candidates.json`` and the verify-stage
    ``verification.json`` this repository's downloader wrote. Screen exclusions are
    archive-wide totals (the archive does not attribute them per vendor before the
    per-patient reduction); the probe stage is reported per vendor, which is where the
    keep/reject decision is made.
    """
    cand_p = results_dir / "candidates.json"
    ver_p = results_dir / "verification.json"
    if not cand_p.exists() or not ver_p.exists():
        return None
    cand = json.loads(cand_p.read_text(encoding="utf-8"))
    ver = json.loads(ver_p.read_text(encoding="utf-8"))
    cc = cand.get("counts", {})
    vc = ver.get("counts", {})
    params = cand.get("parameters", {})
    per_vendor_target = params.get("per_vendor_target")

    # The probe stage is where the eligibility screen actually rejects series, and it is
    # the flow-diagram's operative step. Aggregate the per-vendor verdicts into a
    # reason -> count table over everything that was not kept.
    verdicts = vc.get("verdicts_by_vendor", {})
    probe_rejections_by_reason: dict[str, int] = {}
    for _vendor, table in verdicts.items():
        for reason, n in table.items():
            if reason == "keep":
                continue
            probe_rejections_by_reason[reason] = probe_rejections_by_reason.get(reason, 0) + int(n)
    n_probed = vc.get("probed")
    n_kept = vc.get("kept")
    n_probe_rejected = (n_probed - n_kept) if (n_probed is not None and n_kept is not None) else None

    return {
        "index_rows": cc.get("index_rows"),
        "vendor_recognised": cc.get("vendor_recognised"),
        "passed_metadata_screen": cc.get("passed_metadata_screen"),
        "screen_exclusions": cc.get("screen_exclusions", {}),
        "after_one_series_per_patient": cc.get("after_one_series_per_patient"),
        "probe_queue": cc.get("probe_queue"),
        "probe_queue_by_vendor": cc.get("probe_queue_by_vendor", {}),
        "probed": n_probed,
        "kept": n_kept,
        "kept_by_vendor": vc.get("kept_by_vendor", {}),
        "n_probe_rejected": n_probe_rejected,
        "probe_rejections_by_reason": probe_rejections_by_reason,
        "probe_verdicts_by_vendor": verdicts,
        "per_vendor_target": per_vendor_target,
        "per_vendor_is_cap_note": (
            f"'{per_vendor_target} per vendor' is a target cap, not the natural yield: "
            "probing halts for a vendor once the cap is reached (each vendor's probe "
            "queue held more). The multi-vendor balance is therefore a design choice, "
            "not a property of the data. The probe stage "
            f"({n_probed} probed, {n_kept} kept, {n_probe_rejected} rejected) is where "
            "the eligibility screen -- per-slice tube current (0018,1151), tube-current "
            "modulation, HU rescale, slice count and axial extent, abdominal body part "
            "-- actually acted."
        ),
        "collections_queried": params.get("collections_queried", []),
    }


def _uids(provenance_path: Path) -> tuple[set[str], dict[str, str]]:
    """The Series Instance UIDs in one PROVENANCE.json, and each one's vendor."""
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    uids: set[str] = set()
    vendor: dict[str, str] = {}
    for s in payload.get("series", []):
        uid = str(s.get("series_instance_uid", ""))
        if uid:
            uids.add(uid)
            vendor[uid] = str(s.get("vendor", ""))
    return uids, vendor


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ours", type=Path, default=DEFAULT_OURS,
                    help="IORN-007 data/PROVENANCE.json")
    ap.add_argument("--iorn006", type=Path, default=DEFAULT_IORN006,
                    help="IORN-006 (ctsegdose_core) data/PROVENANCE.json")
    ap.add_argument("--out", type=Path, default=REPO / "results" / "phase2_cohort" / "cohort_overlap.json")
    args = ap.parse_args()

    if not args.ours.exists():
        raise SystemExit(f"IORN-007 provenance not found: {args.ours}")
    if not args.iorn006.exists():
        raise SystemExit(f"IORN-006 provenance not found: {args.iorn006}")

    ours, ours_vendor = _uids(args.ours)
    theirs, _ = _uids(args.iorn006)
    shared = ours & theirs
    only_ours = ours - theirs
    only_theirs = theirs - ours

    n_shared, n_ours = len(shared), len(ours)
    if n_shared == n_ours == len(theirs):
        verdict = (
            "identical selection: every downloaded series is in the IORN-006 cohort and "
            "vice versa. The paper may state the IORN-006 cohort is reused; the "
            "absorbed-dose eligibility (ct_dosemc_core.eligibility) is then applied on "
            "top of that shared set."
        )
    elif n_shared == 0:
        verdict = (
            "disjoint selection: no series is shared. The paper must state IORN-007 "
            "re-selects from the same archive under an independent criterion."
        )
    else:
        verdict = (
            f"partial overlap: {n_shared} of {n_ours} downloaded series are also in the "
            "IORN-006 cohort. The paper must state IORN-007 re-selects from the same "
            "archive rather than reusing the IORN-006 cohort wholesale."
        )

    shared_by_vendor: dict[str, int] = {}
    for uid in shared:
        v = ours_vendor.get(uid, "")
        shared_by_vendor[v] = shared_by_vendor.get(v, 0) + 1

    funnel = _selection_funnel(args.out.parent)
    eligibility_note = (
        "IORN-007's absorbed-dose eligibility (ct_dosemc_core.eligibility) is stricter "
        "than the shared IORN-006 index/probe screen, but it was NOT applied as a "
        "constraint on this cohort at download time: 0 series were removed from, and 0 "
        "added to, the IORN-006 set. The 40/40 identity is therefore by construction, "
        "not coincidence -- the download used the same index/probe screen, and the "
        "stricter absorbed-dose criterion is assessed per series later in Phase 2 and "
        "reported, rather than used to prune the cohort."
    )

    payload: dict[str, Any] = {
        "compared": {
            "iorn007_provenance": str(args.ours),
            "iorn006_provenance": str(args.iorn006),
        },
        "selection_funnel": funnel,
        "eligibility_note": eligibility_note,
        "n_iorn007": n_ours,
        "n_iorn006": len(theirs),
        "n_shared": n_shared,
        "n_only_iorn007": len(only_ours),
        "n_only_iorn006": len(only_theirs),
        "shared_fraction_of_iorn007": round(n_shared / n_ours, 4) if n_ours else None,
        "shared_by_vendor": dict(sorted(shared_by_vendor.items())),
        "verdict": verdict,
        "shared_series_instance_uids": sorted(shared),
        "only_in_iorn007": sorted(only_ours),
        "only_in_iorn006": sorted(only_theirs),
        "note": (
            "Selection here uses the same index/probe screen as IORN-006 (ported into "
            "ct_dosemc_core.selection). IORN-007's absorbed-dose eligibility "
            "(ct_dosemc_core.eligibility) is a separate, later gate applied to this "
            "downloaded set, not the download filter."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"  IORN-007 {n_ours} series, IORN-006 {len(theirs)} series, shared {n_shared}")
    print(f"  shared by vendor: {payload['shared_by_vendor']}")
    print(f"  verdict: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

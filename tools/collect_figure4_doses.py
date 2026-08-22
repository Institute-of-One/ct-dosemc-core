"""Collect scaled 007 organ doses for Fig. 4.

Raw MC mGy is not the paper number. The y-axis is

    D_scaled = D_raw * CTDIvol_series / CTDIvol_MC(vendor, kVp)

CTDIvol_MC is a bowtie-aware 32 cm CTDI run at the production source model
(36 projections, K=4). The Phase-1 no-bowtie anchor is not this factor.
Series with unavailable CTDIvol stay off the scatter (already omitted on x).

    python tools/collect_figure4_doses.py
    python tools/figure4_scatter.py --doses results/phase2_cohort/figure4_doses.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("run_cohort", REPO / "tools" / "run_cohort.py")
assert _spec is not None and _spec.loader is not None
_cohort = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cohort)
eligible_uids = _cohort.eligible_uids
is_complete = _cohort.is_complete
prod_dir = _cohort.prod_dir

INDEX = REPO / "results" / "phase2_cohort" / "iorn006_organ_index.json"
SCALE = REPO / "results" / "phase2_cohort" / "ctdi_scale.json"
OUT = REPO / "results" / "phase2_cohort" / "figure4_doses.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def scale_key(vendor: str, kvp: float) -> str:
    return f"{vendor}|{float(kvp):.0f}"


def collect(
    *,
    index: dict[str, Any],
    scale: dict[str, Any] | None,
) -> dict[str, Any]:
    by_uid = {s["series_instance_uid"]: s for s in index["series"]}
    factors = (scale or {}).get("factor_by_vendor_kvp") or {}
    doses: dict[str, dict[str, float]] = {}
    rows: list[dict[str, Any]] = []
    for uid in eligible_uids():
        src = by_uid[uid]
        complete = is_complete(uid)
        origin = src.get("ctdivol_origin")
        ctdivol = src.get("ctdivol_mgy")
        vendor = src["vendor"]
        rec: dict[str, Any] = {
            "series_instance_uid": uid,
            "vendor": vendor,
            "ctdivol_origin": origin,
            "ctdivol_mgy": ctdivol,
            "complete": complete,
            "on_figure4": origin not in {None, "unavailable"} and ctdivol is not None,
        }
        if not complete:
            rec["status"] = "production_incomplete"
            rows.append(rec)
            continue
        raw = _load(prod_dir(uid) / "organ_doses.json")
        plan = raw.get("plan") or {}
        bbox = plan.get("bbox_cm") or [0.0, 0.0, 0.0]
        coll = float(plan.get("collimation_cm") or 2.0)
        length = float(bbox[2]) if len(bbox) > 2 else 0.0
        need = max(1, int(round(length / coll))) if length > 0.0 and coll > 0.0 else 0
        n_z = int(raw.get("n_z_stations") or plan.get("n_z_stations") or 0)
        if n_z != need or n_z < 1:
            rec["status"] = "awaiting_scan_coverage"
            rec["n_z_stations"] = n_z
            rec["n_z_stations_needed"] = need
            rows.append(rec)
            continue
        kvp = float(raw.get("plan", {}).get("kvp") or 0.0)
        key = scale_key(vendor, kvp)
        factor = factors.get(key)
        rec["kvp"] = kvp
        rec["scale_key"] = key
        ctdiw = ((scale or {}).get("ctdiw_pmma_mgy_by_vendor_kvp") or {}).get(key)
        rec["ctdiw_mc_mgy"] = ctdiw
        if factor is None and ctdiw not in (None, 0) and ctdivol is not None:
            factor = float(ctdivol) / float(ctdiw)
        rec["scale_factor"] = factor
        if rec["on_figure4"] and factor is None:
            rec["status"] = "awaiting_ctdi_scale"
            rows.append(rec)
            continue
        organs: dict[str, float] = {}
        for name, organ in raw["organs"].items():
            value = float(organ["dose_mgy"])
            if rec["on_figure4"]:
                value *= float(factor)
            organs[name] = value
        if rec["on_figure4"]:
            doses[uid] = organs
            rec["status"] = "scaled"
        else:
            rec["status"] = "omitted_no_ctdivol"
        rec["n_organs"] = len(organs)
        rows.append(rec)

    n_scaled = sum(1 for r in rows if r["status"] == "scaled")
    return {
        "what": "IORN-007 absorbed organ dose for Fig. 4, scaled to the series CTDIvol",
        "formula": "D_scaled = D_raw * CTDIvol_series / CTDIvol_MC(vendor, kVp)",
        "not": "Not the raw MC mGy. Not the Phase-1 no-bowtie CTDI anchor.",
        "n_eligible": len(rows),
        "n_scaled": n_scaled,
        "n_awaiting_scale": sum(1 for r in rows if r["status"] == "awaiting_ctdi_scale"),
        "n_awaiting_scan_coverage": sum(1 for r in rows if r["status"] == "awaiting_scan_coverage"),
        "n_production_incomplete": sum(1 for r in rows if r["status"] == "production_incomplete"),
        "usable_for_figure4": n_scaled > 0
        and all(r["status"] in {"scaled", "omitted_no_ctdivol"} for r in rows),
        "doses": doses,
        "series": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", type=Path, default=INDEX)
    ap.add_argument("--scale", type=Path, default=SCALE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    index = _load(args.index)
    scale = _load(args.scale) if args.scale.is_file() else None
    payload = collect(index=index, scale=scale)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"[figure4] wrote {args.out}  scaled={payload['n_scaled']}  "
        f"awaiting_scale={payload['n_awaiting_scale']}  "
        f"awaiting_scan_coverage={payload.get('n_awaiting_scan_coverage')}  "
        f"incomplete={payload['n_production_incomplete']}  "
        f"usable={payload['usable_for_figure4']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

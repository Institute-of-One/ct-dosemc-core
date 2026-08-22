"""Backfill source_route on Phase-1a replica JSON already on disk.

Re-run after L160 finishes. Classification is from engine_invocations
(P*K → B, 1 with K>1 → A). A K=1 native-trajectory replica is not labelled A.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from run_tg195 import source_route_fields  # noqa: E402

RESULTS = REPO / "results"


def _invocations(obj: dict) -> int | None:
    if obj.get("engine_invocations") is not None:
        return int(obj["engine_invocations"])
    each = obj.get("engine_invocations_per_replica") or []
    if each:
        return int(each[0])
    return None


def _dims(obj: dict, fallback_sub: int, fallback_proj: int) -> tuple[int, int]:
    cfg = obj.get("config") or {}
    sub = int(cfg.get("sub_fans") or obj.get("n_sub_fans") or fallback_sub or 0)
    proj = int(cfg.get("n_projections") or obj.get("n_projections") or fallback_proj or 0)
    return sub, proj


def _apply(obj: dict, n_sub: int, n_proj: int) -> bool:
    inv = _invocations(obj)
    sub, proj = _dims(obj, n_sub, n_proj)
    if inv is None or sub == 0 or proj == 0:
        return False
    fields = source_route_fields(
        n_sub_fans=sub, n_projections=proj, engine_invocations=inv
    )
    if obj.get("source_route") == fields["source_route"] and obj.get("source_route_detail"):
        return False
    obj.update(fields)
    return True


def annotate_file(path: Path) -> str | None:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    n_sub, n_proj = _dims(data, 0, 0)
    changed = _apply(data, n_sub, n_proj)
    for rec in data.get("per_replica") or []:
        changed = _apply(rec, n_sub, n_proj) or changed
    if not changed:
        return None
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(data.get("source_route") or "?")


def main() -> int:
    n = 0
    paths = list((RESULTS / "phase1a").glob("replica_*/replica_result.json"))
    paths += [
        RESULTS / "phase1a_G4_replica_uncertainty_120kvp_second_K4_L40.json",
        RESULTS / "phase1a_G4_replica_uncertainty_120kvp_second_K4_L40_routeA.json",
        RESULTS / "phase1a_G4_replica_uncertainty_120kvp_second_K4_L160.json",
        RESULTS / "phase1a_G4_replica_uncertainty_120kvp_second_K4_L160.progress.json",
        RESULTS / "phase1a_G4_replica_uncertainty_120kvp_second_K1.json",
    ]
    for path in paths:
        if not path.is_file():
            continue
        route = annotate_file(path)
        if route:
            print(f"{path.name}: {route}")
            n += 1
    print(f"annotated {n} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

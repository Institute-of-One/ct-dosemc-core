"""32-series Phase-2 production: one eligible series after another.

Configuration matches the G2 production anchor (36 projections, K=4,
2e8 histories) so the patient numbers sit on the same source model that
Phase 1a closed. Route A is the default (parse once per series). Completed
series with usable_as_result true at this configuration are skipped, so an
interrupted job resumes.

Do not start this while another GPU job owns the device.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ct_dosemc_core.patient import (  # noqa: E402
    axial_station_z_cm,
    default_tissue_groups,
    material_energy_tag,
)

ELIGIBILITY = REPO / "results" / "phase2_cohort" / "density_eligibility.json"
PROVENANCE = REPO / "data" / "PROVENANCE.json"
OUT_ROOT = REPO / "results" / "phase2_patient"
LOCK = OUT_ROOT / "cohort.lock"
MAX_PASSES = 3

# Same source-model configuration as the closed G2 anchor.
PROD_PROJECTIONS = 36
PROD_SUB_FANS = 4
PROD_HISTORIES = 2.0e8
# Patient tissue tables are 5–120 keV (materials/PROVENANCE.json). MC-GPU
# refuses a spectrum whose max exceeds the table. 140 kVp series wait until
# 5–150 keV tables exist; do not take the GPU to rediscover that.
MATERIAL_EMAX_KEV = 120.0


def eligible_uids(path: Path = ELIGIBILITY) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [str(row["series_instance_uid"]) for row in payload["series"] if row.get("eligible")]


def prod_tag(uid: str) -> str:
    return f"prod_{uid}"


def prod_dir(uid: str) -> Path:
    return OUT_ROOT / prod_tag(uid)


def series_kvp(uid: str, path: Path = PROVENANCE) -> float | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data.get("series", []):
        if row.get("series_instance_uid") == uid:
            kv = row.get("kvp")
            return float(kv) if kv is not None else None
    return None


def _tables_on_disk(energy_tag: str) -> bool:
    materials = REPO / "materials"
    return all(
        (materials / g.material_file).is_file()
        for g in default_tissue_groups(energy_tag=energy_tag)
    )


def needs_extended_tables(uid: str) -> bool:
    kv = series_kvp(uid)
    if kv is None or kv <= MATERIAL_EMAX_KEV:
        return False
    return not _tables_on_disk(material_energy_tag(kv))


def is_complete(uid: str) -> bool:
    path = prod_dir(uid) / "organ_doses.json"
    if not path.is_file():
        return False
    rec = json.loads(path.read_text(encoding="utf-8-sig"))
    plan = rec.get("plan") or {}
    bbox = plan.get("bbox_cm") or [0.0, 0.0, 0.0]
    coll = float(plan.get("collimation_cm") or 2.0)
    length = float(bbox[2]) if len(bbox) > 2 else 0.0
    n_z = int(rec.get("n_z_stations") or plan.get("n_z_stations") or 0)
    need = int(axial_station_z_cm(length, coll).size) if length > 0.0 and coll > 0.0 else 0
    return (
        bool(rec.get("usable_as_result"))
        and int(rec.get("n_projections") or 0) == PROD_PROJECTIONS
        and int(rec.get("n_sub_fans") or 0) == PROD_SUB_FANS
        and float(rec.get("histories") or 0.0) >= PROD_HISTORIES - 1.0
        and n_z == need
        and n_z >= 1
    )


def _stdio_replace_errors() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _acquire_lock() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if LOCK.is_file():
        try:
            old = int(LOCK.read_text(encoding="ascii").strip().split()[0])
        except (ValueError, OSError):
            old = 0
        if _pid_alive(old) and old != os.getpid():
            raise SystemExit(
                f"cohort already running (pid {old}, {LOCK}). Not starting a second GPU job."
            )
    LOCK.write_text(f"{os.getpid()}\n", encoding="ascii")


def _release_lock() -> None:
    try:
        if LOCK.is_file() and LOCK.read_text(encoding="ascii").strip().split()[0] == str(os.getpid()):
            LOCK.unlink()
    except OSError:
        pass


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="list series and skip state, do not take the GPU")
    ap.add_argument("--limit", type=int, default=0, help="run at most N remaining series (0 = all)")
    ap.add_argument("--timeout-hours", type=float, default=12.0)
    return ap


def _run_one(py: str, uid: str, timeout_hours: float) -> int:
    cmd = [
        py,
        "-u",
        str(REPO / "tools" / "run_patient.py"),
        "--run",
        "--usable-as-result",
        "--batch",
        "--series",
        uid,
        "--projections",
        str(PROD_PROJECTIONS),
        "--sub-fans",
        str(PROD_SUB_FANS),
        "--histories",
        f"{PROD_HISTORIES:.3e}",
        "--timeout-hours",
        str(timeout_hours),
        "--tag",
        prod_tag(uid),
    ]
    return subprocess.run(cmd, cwd=str(REPO)).returncode


def _run_one_resilient(py: str, uid: str, timeout_hours: float) -> int:
    """Run once; on failure run again immediately so leftover beams resume."""
    code = _run_one(py, uid, timeout_hours)
    if code == 0 and is_complete(uid):
        return 0
    print(f"[cohort] retrying {uid} immediately (resume leftover beams)", flush=True)
    code = _run_one(py, uid, timeout_hours)
    return code


def main(argv: list[str] | None = None) -> int:
    _stdio_replace_errors()
    args = build_parser().parse_args(argv)
    uids = eligible_uids()
    if len(uids) != 32:
        raise SystemExit(f"expected 32 eligible series, found {len(uids)} in {ELIGIBILITY}")

    remaining = [u for u in uids if not is_complete(u)]
    print(f"[cohort] eligible={len(uids)}  done={len(uids) - len(remaining)}  remaining={len(remaining)}", flush=True)
    if args.limit > 0:
        remaining = remaining[: args.limit]
        print(f"[cohort] limit={args.limit}  this session={len(remaining)}", flush=True)
    if args.dry_run:
        for i, uid in enumerate(uids, 1):
            if is_complete(uid):
                mark = "DONE"
            elif needs_extended_tables(uid):
                mark = f"WAIT {series_kvp(uid):.0f}kVp>tables"
            else:
                mark = "TODO"
            print(f"  {i:02d} {mark}  {uid}", flush=True)
        return 0
    if not remaining:
        print("[cohort] nothing to run", flush=True)
        return 0

    _acquire_lock()
    try:
        py = sys.executable
        deferred: list[str] = []
        failed: list[str] = []
        queue = list(remaining)
        for pass_i in range(1, MAX_PASSES + 1):
            if not queue:
                break
            print(f"[cohort] pass {pass_i}/{MAX_PASSES}  n={len(queue)}", flush=True)
            failed = []
            for i, uid in enumerate(queue, 1):
                print(f"[cohort] {i}/{len(queue)}  {uid}", flush=True)
                if needs_extended_tables(uid):
                    kv = series_kvp(uid)
                    print(
                        f"[cohort] DEFER {uid}  {kv:.0f} kVp exceeds "
                        f"{MATERIAL_EMAX_KEV:.0f} keV material tables; "
                        "not taking the GPU",
                        flush=True,
                    )
                    deferred.append(uid)
                    continue
                code = _run_one_resilient(py, uid, float(args.timeout_hours))
                if code != 0:
                    print(f"[cohort] FAILED {uid}  exit={code}", flush=True)
                    failed.append(uid)
                    continue
                if not is_complete(uid):
                    print(f"[cohort] FAILED {uid}  organ_doses.json missing or not production", flush=True)
                    failed.append(uid)
                    continue
                print(f"[cohort] ok  {prod_dir(uid) / 'organ_doses.json'}", flush=True)
            queue = [u for u in failed if not is_complete(u)]
            if queue and pass_i < MAX_PASSES:
                print(f"[cohort] retrying {len(queue)} failure(s) on the next pass", flush=True)
        if deferred:
            print(f"[cohort] deferred {len(deferred)} series pending 5-150 keV tables", flush=True)
            for uid in deferred:
                print(f"  DEFER {uid}", flush=True)
        leftover = [u for u in remaining if not is_complete(u) and u not in deferred]
        if leftover:
            print(f"[cohort] session finished with {len(leftover)} failure(s)", flush=True)
            for uid in leftover:
                print(f"  FAIL  {uid}", flush=True)
            return 1
        print("[cohort] session finished", flush=True)
        return 0
    finally:
        _release_lock()


if __name__ == "__main__":
    raise SystemExit(main())

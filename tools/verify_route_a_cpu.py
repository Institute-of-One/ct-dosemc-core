"""CPU Route A vs Route B bit-identity on two off-axis sub-fans.

Uses the production L40 replica-00 input files (same seeds as the GPU 144/144
check) but only two beams, so the CPU rebuild can be validated without occupying
the GPU. Acceptance is SHA-256 of the dose .raw, not "within statistics".
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REF = REPO / "results" / "phase1a" / "replica_120kvp_second_K4_L40_00"
OUT = REPO / "results" / "phase1a" / "routeA_cpu_bitid"
EXE = REPO / "vendor" / "build" / "MC-GPU_v1.3_CPU.exe"
BEAMS = ("case4_g4_p000_fan00.in", "case4_g4_p000_fan01.in")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(argv1: str, log: Path) -> None:
    with log.open("w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.run(
            [str(EXE), argv1],
            cwd=str(OUT),
            stdout=fh,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if proc.returncode != 0:
        tail = log.read_text(encoding="latin-1", errors="replace")[-2000:]
        raise SystemExit(f"CPU MC-GPU exited {proc.returncode}\n{tail}")


def main() -> int:
    if not EXE.is_file():
        raise SystemExit(f"missing {EXE}")
    if not REF.is_dir():
        raise SystemExit(f"missing reference rundir {REF}")
    OUT.mkdir(parents=True, exist_ok=True)
    for name in (
        "case4_g4.vox.gz",
        "tg195_120kvp.spc",
        "air_5-120keV.mcgpu.gz",
        "PMMA_5-120keV.mcgpu.gz",
        *BEAMS,
    ):
        src = REF / name
        if not src.is_file():
            raise SystemExit(f"missing {src}")
        shutil.copy2(src, OUT / name)

    singles: dict[str, str] = {}
    for beam in BEAMS:
        stem = Path(beam).stem.removeprefix("case4_")
        raw = OUT / f"dose_{stem}.dat.raw"
        if raw.is_file():
            raw.unlink()
        print(f"[cpu] standalone {beam}", flush=True)
        _run(beam, OUT / f"single_{stem}.log")
        if not raw.is_file():
            raise SystemExit(f"no tally {raw}")
        singles[stem] = _sha(raw)
        raw.replace(OUT / f"single_{raw.name}")

    (OUT / "manifest.txt").write_text("\n".join(BEAMS) + "\n", encoding="ascii")
    print("[cpu] @manifest batch", flush=True)
    _run("@manifest.txt", OUT / "batch.log")
    batch_log = (OUT / "batch.log").read_text(encoding="latin-1", errors="replace")
    n_parse = batch_log.count("Reading voxel file")
    n_cache = batch_log.count("ASCII parse skipped")
    print(f"[cpu] voxel-file reads={n_parse} cache-hits={n_cache}", flush=True)

    ok = n_parse == 1 and n_cache >= 1
    for beam in BEAMS:
        stem = Path(beam).stem.removeprefix("case4_")
        raw = OUT / f"dose_{stem}.dat.raw"
        got = _sha(raw)
        match = got == singles[stem]
        print(f"[cpu] {stem}: {'IDENTICAL' if match else 'DIFFER'}  {got}")
        ok = ok and match

    summary = OUT / "cpu_bitid.json"
    summary.write_text(
        __import__("json").dumps(
            {
                "executable": str(EXE),
                "executable_sha256": _sha(EXE),
                "reference_inputs": str(REF),
                "beams": list(BEAMS),
                "voxel_file_reads": n_parse,
                "cache_hits": n_cache,
                "single_sha256": singles,
                "pass": ok,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[cpu] {'PASS' if ok else 'FAIL'} wrote {summary}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

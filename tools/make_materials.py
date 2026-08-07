"""Generate the MC-GPU material files this project needs, from open data.

MC-GPU v1.3's own repository ships only a dozen materials, none of which is PMMA,
air or water -- the three the CTDI anchor needs.  Rather than transcribe a
proprietary table, the files are *generated* from the PENELOPE 2006 photon
cross-section database using Andreu Badal's ``MCGPU_materials`` utility, which
carries the permissive Universitat de Barcelona notice reproduced in
``docs/MC_SOURCE_MODEL.md``.

That keeps the openness claim intact end to end: engine (public domain), material
data (permissive, redistributable), spectra (BSD-3), wrapper (MIT).

Usage::

    python tools/make_materials.py                 # all default materials
    python tools/make_materials.py --only PMMA air

Prerequisites: ``vendor/MCGPU_materials`` cloned and its executable built (the
script builds it if gfortran is on PATH or under ``vendor/mingw64/bin``).
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ct_dosemc_core.provenance import environment, file_digest  # noqa: E402

GENERATOR_REPO = "https://github.com/andreubs/MCGPU_materials"
VENDOR = REPO / "vendor" / "MCGPU_materials"
MATERIALS_DIR = REPO / "materials"


@dataclass(frozen=True)
class MaterialSpec:
    """One material, identified by its PENELOPE ``pdcompos.p06`` entry.

    Using the database entry rather than typing a composition by hand means the
    elemental composition and density are the published ICRU/NIST ones and are
    traceable to a line number in a file that ships with the generator.
    """

    name: str
    pendbase_id: int
    pendbase_label: str
    insulator: bool = True

    def input_deck(self, e_min_ev: int, e_max_ev: int, step_ev: int, out_name: str) -> str:
        return "\n".join(
            [
                "2",  # read composition from PENDBASE_photons/pdcompos.p06
                str(self.pendbase_id),
                "1" if self.insulator else "2",
                f"{e_min_ev} {e_max_ev}",
                str(step_ev),
                out_name,
                "",
            ]
        )


MATERIALS: tuple[MaterialSpec, ...] = (
    MaterialSpec("PMMA", 224, "POLYMETHYL METHACRALATE (LUCITE, PERSPEX, PLEXIGLASS)"),
    MaterialSpec("air", 104, "AIR, DRY (NEAR SEA LEVEL)"),
    MaterialSpec("water", 278, "WATER, LIQUID"),
)


def _gfortran() -> str:
    local = REPO / "vendor" / "mingw64" / "bin" / "gfortran.exe"
    if local.is_file():
        return str(local)
    found = shutil.which("gfortran")
    if found:
        return found
    raise SystemExit(
        "gfortran not found. Either put it on PATH or unpack a MinGW-w64 build "
        f"into {REPO / 'vendor' / 'mingw64'} (see docs/MC_SOURCE_MODEL.md)."
    )


def _executable() -> Path:
    if not VENDOR.is_dir():
        raise SystemExit(
            f"{VENDOR} is missing. Clone it first:\n"
            f"    git clone --depth 1 {GENERATOR_REPO} {VENDOR}"
        )
    exe = VENDOR / ("MCGPU_materials.exe" if os.name == "nt" else "MCGPU_materials.x")
    if exe.is_file():
        return exe
    print(f"[make_materials] building the generator -> {exe.name}")
    subprocess.run(
        [_gfortran(), "MCGPU_materials.f", "penelope_photons.f", "-o", exe.name, "-O2"],
        cwd=str(VENDOR),
        check=True,
    )
    return exe


def generate(
    spec: MaterialSpec,
    exe: Path,
    *,
    e_min_ev: int,
    e_max_ev: int,
    step_ev: int,
    compress: bool,
) -> dict[str, object]:
    stem = f"{spec.name}_{e_min_ev // 1000}-{e_max_ev // 1000}keV"
    raw_name = f"{stem}.mcgpu"
    deck = VENDOR / f"_deck_{spec.name}.txt"
    deck.write_text(spec.input_deck(e_min_ev, e_max_ev, step_ev, raw_name), encoding="ascii")

    env = dict(os.environ)
    mingw_bin = REPO / "vendor" / "mingw64" / "bin"
    if mingw_bin.is_dir():
        env["PATH"] = f"{mingw_bin}{os.pathsep}{env.get('PATH', '')}"

    with deck.open("rb") as fh:
        proc = subprocess.run(
            [str(exe)], cwd=str(VENDOR), stdin=fh, capture_output=True, text=True, env=env
        )
    if "correctly generated" not in proc.stdout:
        raise SystemExit(
            f"generator failed for {spec.name}:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        )
    # The generator echoes the entry it resolved; refuse a silent mismatch, which
    # is how you end up simulating photographic emulsion instead of PMMA.
    if spec.pendbase_label.split()[0] not in proc.stdout:
        raise SystemExit(
            f"PENDBASE id {spec.pendbase_id} did not resolve to {spec.pendbase_label!r}:\n"
            + "\n".join(line for line in proc.stdout.splitlines() if str(spec.pendbase_id) in line)
        )

    density = None
    for line in proc.stdout.splitlines():
        if "Density" in line:
            density = float(line.split("=")[1].split()[0])
            break

    produced = VENDOR / raw_name
    MATERIALS_DIR.mkdir(parents=True, exist_ok=True)
    target = MATERIALS_DIR / (raw_name + ".gz" if compress else raw_name)
    if compress:
        with produced.open("rb") as src, gzip.open(target, "wb", compresslevel=9) as dst:
            shutil.copyfileobj(src, dst)
    else:
        shutil.copy2(produced, target)
    produced.unlink()
    deck.unlink()

    return {
        "material": spec.name,
        "file": target.name,
        "sha256": file_digest(target),
        "pendbase_id": spec.pendbase_id,
        "pendbase_label": spec.pendbase_label,
        "nominal_density_g_cm3": density,
        "insulator": spec.insulator,
        "energy_range_ev": [e_min_ev, e_max_ev],
        "energy_step_ev": step_ev,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", default=None, help="subset of material names")
    ap.add_argument("--e-min-ev", type=int, default=5_000)
    ap.add_argument("--e-max-ev", type=int, default=120_000)
    ap.add_argument("--step-ev", type=int, default=5)
    ap.add_argument("--no-compress", action="store_true")
    args = ap.parse_args(argv)

    wanted = MATERIALS
    if args.only:
        names = {n.lower() for n in args.only}
        wanted = tuple(m for m in MATERIALS if m.name.lower() in names)
        unknown = names - {m.name.lower() for m in MATERIALS}
        if unknown:
            raise SystemExit(f"unknown material(s): {sorted(unknown)}")

    exe = _executable()
    records = []
    for spec in wanted:
        print(f"[make_materials] {spec.name} (PENDBASE #{spec.pendbase_id})")
        records.append(
            generate(
                spec,
                exe,
                e_min_ev=args.e_min_ev,
                e_max_ev=args.e_max_ev,
                step_ev=args.step_ev,
                compress=not args.no_compress,
            )
        )

    manifest = MATERIALS_DIR / "PROVENANCE.json"
    existing = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
    by_name = {r["material"]: r for r in existing.get("materials", [])}
    by_name.update({r["material"]: r for r in records})
    manifest.write_text(
        json.dumps(
            {
                "environment": environment(REPO),
                "generator": {
                    "repository": GENERATOR_REPO,
                    "program": "MCGPU_materials.f + penelope_photons.f",
                    "database": "PENDBASE_photons (photon-only subset of PENELOPE 2006 PENDBASE)",
                    "licence": "Universitat de Barcelona permissive notice; see "
                    "docs/MC_SOURCE_MODEL.md",
                    "reference": "F. Salvat, J. M. Fernandez-Varea, J. Sempau, PENELOPE -- "
                    "A code system for Monte Carlo simulation of electron and photon "
                    "transport, NEA-OECD (2006)",
                },
                "materials": sorted(by_name.values(), key=lambda r: str(r["material"])),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[make_materials] wrote {manifest}")
    for r in records:
        print(f"    {r['material']:6s} rho={r['nominal_density_g_cm3']}  {r['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

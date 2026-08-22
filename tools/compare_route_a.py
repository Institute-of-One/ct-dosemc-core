"""Compare a Route A replica against a Route B reference replica.

Acceptance is byte-equality, not "within statistics": every dose .raw SHA-256
must match, and the combined VOI values must be IEEE-identical.  A mismatch
prints the first differing file and the max |Δ| of the float32 arrays so the
source of the difference can be named before anything else proceeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _stem_key(path: Path) -> str:
    name = path.name
    if name.startswith("dose_") and name.endswith(".dat.raw"):
        return name[len("dose_") : -len(".dat.raw")]
    return name


def compare_dirs(ref: Path, got: Path) -> int:
    ref_raws = { _stem_key(p): p for p in ref.glob("dose_*.dat.raw") }
    got_raws = { _stem_key(p): p for p in got.glob("dose_*.dat.raw") }
    if not ref_raws:
        print(f"no dose_*.dat.raw under {ref}", file=sys.stderr)
        return 2
    missing = sorted(set(ref_raws) - set(got_raws))
    extra = sorted(set(got_raws) - set(ref_raws))
    if missing or extra:
        print(f"file set mismatch: missing={missing[:5]} extra={extra[:5]}")
        return 1

    n_match = 0
    first_diff = None
    for key in sorted(ref_raws):
        a, b = ref_raws[key], got_raws[key]
        sa, sb = _sha256(a), _sha256(b)
        if sa == sb:
            n_match += 1
            continue
        fa = np.fromfile(a, dtype=np.float32)
        fb = np.fromfile(b, dtype=np.float32)
        n = min(fa.size, fb.size)
        delta = np.abs(fa[:n].astype(np.float64) - fb[:n].astype(np.float64))
        info = {
            "stem": key,
            "ref_sha256": sa,
            "got_sha256": sb,
            "nbytes_ref": a.stat().st_size,
            "nbytes_got": b.stat().st_size,
            "max_abs_delta": float(delta.max()) if n else float("nan"),
            "n_differing_voxels": int((delta != 0).sum()) if n else -1,
        }
        if first_diff is None:
            first_diff = info
            print("FIRST RAW MISMATCH:")
            for k, v in info.items():
                print(f"  {k}: {v}")
        else:
            print(f"  also {key}: max|Δ|={info['max_abs_delta']:.6g}  ndiff={info['n_differing_voxels']}")

    print(f"dose .raw SHA256 identical: {n_match}/{len(ref_raws)}")

    voi_ok = True
    ref_json = ref / "replica_result.json"
    got_json = got / "replica_result.json"
    if ref_json.is_file() and got_json.is_file():
        rv = json.loads(ref_json.read_text(encoding="utf-8"))["values_ev_per_photon"]
        gv = json.loads(got_json.read_text(encoding="utf-8"))["values_ev_per_photon"]
        print("VOI values (IEEE == after JSON round-trip of the replica files):")
        for name in sorted(set(rv) | set(gv)):
            a, b = rv.get(name), gv.get(name)
            same = a == b
            voi_ok = voi_ok and same
            print(f"  {name}: ref={a!r}  got={b!r}  {'IDENTICAL' if same else 'DIFFER'}")
    else:
        print("replica_result.json missing on one side; VOI compare skipped")
        voi_ok = False

    if first_diff is not None or not voi_ok:
        print("FAIL: not bit-identical. Do not proceed; name the source of the difference.")
        return 1
    print("PASS: every dose .raw SHA256 matches and VOI values are identical.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ref", type=Path)
    p.add_argument("got", type=Path)
    args = p.parse_args(argv)
    return compare_dirs(args.ref.resolve(), args.got.resolve())


if __name__ == "__main__":
    raise SystemExit(main())

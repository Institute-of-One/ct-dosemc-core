"""Subprocess entry point for TotalSegmentator. Not imported by the package.

TotalSegmentator runs nnU-Net, which spawns worker processes for resampling and saving.
Spawning those from inside a long-lived parent -- a Streamlit app, a notebook kernel, a
batch driver holding open file handles -- deadlocks or leaks runaway processes on
Windows. Running inference in a short-lived child that exits afterwards is the reliable
arrangement, so :mod:`ct_dosemc_core.segment` never imports TotalSegmentator: it
launches this module with ``python -m ct_dosemc_core._ts_worker``.

Inference only. No weights are trained, modified or redistributed here;
TotalSegmentator is Apache-2.0 and fetches its own weights on first use.
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="input NIfTI (or DICOM directory)")
    ap.add_argument("output", help="directory to write per-structure masks into")
    ap.add_argument("--task", default="total")
    ap.add_argument("--roi-subset", default="", help="comma-separated structure names")
    ap.add_argument("--fast", action="store_true", help="3 mm model")
    ap.add_argument("--device", default="")
    args = ap.parse_args()

    from totalsegmentator.python_api import totalsegmentator

    try:
        import totalsegmentator as ts_pkg

        version = getattr(ts_pkg, "__version__", "")
    except Exception:  # pragma: no cover - version attribute is optional
        version = ""

    kwargs = {
        "task": args.task,
        "fast": args.fast,
        "quiet": True,
        "roi_subset": [s for s in args.roi_subset.split(",") if s] or None,
    }
    if args.device:
        kwargs["device"] = args.device

    try:
        totalsegmentator(args.input, args.output, **kwargs)
    except TypeError:
        # Older releases do not accept every keyword; fall back to the stable subset.
        totalsegmentator(
            args.input, args.output, task=args.task, fast=args.fast, quiet=True,
            roi_subset=kwargs["roi_subset"],
        )

    print(json.dumps({"totalsegmentator_version": version, "task": args.task}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

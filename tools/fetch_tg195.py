"""Fetch the AAPM TG-195 reference data sets, and pin what was fetched.

AAPM Report No. 195 and its electronic resources are distributed free of charge
but are **copyrighted**: "(c) 2015 by American Association of Physicists in
Medicine. All rights reserved."  They are therefore treated exactly like the TCIA
DICOM -- downloaded and used locally, never committed to this repository.  What
is committed is `data/tg195/PROVENANCE.json`: the URLs, the retrieval date and
the SHA-256 of every file, so that a reviewer can confirm they obtained the same
bytes.

This is the same pattern already established by ``tools/make_materials.py``.

Usage::

    python tools/fetch_tg195.py
    python tools/fetch_tg195.py --verify      # re-check digests, download nothing
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ct_dosemc_core.provenance import environment, file_digest  # noqa: E402

DEST = REPO / "data" / "tg195"
MANIFEST = DEST / "PROVENANCE.json"

DOWNLOADS = {
    "RPT_195.pdf": "https://www.aapm.org/pubs/reports/RPT_195.pdf",
    "RPT_195ElectronicResources.zip": (
        "https://www.aapm.org/pubs/reports/RPT_195ElectronicResources.zip"
    ),
}

LANDING_PAGE = "https://www.aapm.org/pubs/reports/report195.asp"

CITATION = (
    "Sechopoulos I, Ali ESM, Badal A, Badano A, Boone JM, Kyprianou IS, Mainegra-Hing E, "
    "McMillan KL, McNitt-Gray MF, Rogers DWO, Samei E, Turner AC. "
    "'Monte Carlo reference data sets for imaging research: Executive summary of the "
    "report of AAPM Research Committee Task Group 195', "
    "Med. Phys. 42(10), 5679-5691 (2015). doi:10.1118/1.4928676"
)

LICENCE_NOTE = (
    "(c) 2015 American Association of Physicists in Medicine. All rights reserved. "
    "Distributed free of charge by AAPM. Downloaded for local use only; NOT "
    "redistributed by this repository. See docs/REPRODUCING_DATA.md."
)


def download(name: str, url: str, *, force: bool = False) -> Path:
    target = DEST / name
    if target.is_file() and not force:
        print(f"[fetch_tg195] {name} already present, skipping")
        return target
    DEST.mkdir(parents=True, exist_ok=True)
    print(f"[fetch_tg195] downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "ct_dosemc_core"})
    with urllib.request.urlopen(req, timeout=300) as fh, target.open("wb") as out:
        out.write(fh.read())
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="re-check digests only")
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    args = ap.parse_args(argv)

    if args.verify:
        if not MANIFEST.is_file():
            raise SystemExit(f"no manifest at {MANIFEST}; run without --verify first")
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        bad = []
        for rec in manifest["files"]:
            got = file_digest(DEST / rec["file"])
            if got != rec["sha256"]:
                bad.append((rec["file"], rec["sha256"], got))
        for name, want, got in bad:
            print(f"  MISMATCH {name}\n    expected {want}\n    got      {got}")
        print(f"[fetch_tg195] {len(manifest['files']) - len(bad)}/{len(manifest['files'])} verified")
        return 1 if bad else 0

    records = []
    for name, url in DOWNLOADS.items():
        path = download(name, url, force=args.force)
        records.append(
            {"file": name, "url": url, "sha256": file_digest(path), "bytes": path.stat().st_size}
        )

    zip_path = DEST / "RPT_195ElectronicResources.zip"
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            # The archive was made on macOS and carries a __MACOSX resource-fork
            # shadow of every entry; those are not data.
            if info.is_dir() or info.filename.startswith("__MACOSX"):
                continue
            out = DEST / Path(info.filename).name
            if not out.is_file() or args.force:
                out.write_bytes(zf.read(info))
            records.append(
                {
                    "file": out.name,
                    "url": f"{DOWNLOADS['RPT_195ElectronicResources.zip']}!{info.filename}",
                    "sha256": file_digest(out),
                    "bytes": out.stat().st_size,
                }
            )

    MANIFEST.write_text(
        json.dumps(
            {
                "environment": environment(REPO),
                "source": {
                    "landing_page": LANDING_PAGE,
                    "citation": CITATION,
                    "licence": LICENCE_NOTE,
                },
                "files": sorted(records, key=lambda r: str(r["file"])),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[fetch_tg195] wrote {MANIFEST} ({len(records)} files)")
    print("[fetch_tg195] reminder: none of these files may be committed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

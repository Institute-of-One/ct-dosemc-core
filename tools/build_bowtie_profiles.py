"""Turn the Yang (2019) open bowtie dataset into a machine-readable, provenanced JSON.

Input: ``data/bowtie/yang2019_dib_mmc1.xlsx`` — the supplementary file of

    Yang K, Ruan C, Li X, Liu B. "Data of CT bow tie filter profiles from three
    modern CT scanners." Data in Brief 25:104261 (2019).
    doi:10.1016/j.dib.2019.104261, PMC6706760. **Licence: CC BY 4.0**
    (verified from the article's JATS <license license-type="CC BY">).

Each sheet is one scanner (GE Revolution, Philips iQon, Toshiba/Canon Aquilion ONE
Vision). Column A is the fan angle in degrees; the remaining columns are blocks of
four kVp (80/100/120/135|140) per bowtie filter (Small/Medium/Large), giving the
**absolute equivalent aluminium thickness t(ψ) in mm**. The bowtie is symmetric, so
t(−ψ) = t(ψ).

This turns "we borrowed a profile" into "we used a CC-BY measured dataset, extracted
by a pinned script, with a recorded SHA-256". It also builds the Siemens entry the
open dataset lacks: the **cross-vendor average** of the body (Large) profiles, with
the inter-vendor spread carried as a **declared uncertainty band** — a measured band,
not a borrow. Each vendor entry records its ``provenance`` (measured / cross-vendor
average) so the downstream patient driver can report where every profile came from.

Output: ``data/bowtie/bowtie_profiles.json`` and ``data/bowtie/PROVENANCE.json``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import openpyxl

REPO = Path(__file__).resolve().parents[1]
XLSX = REPO / "data" / "bowtie" / "yang2019_dib_mmc1.xlsx"
OUT = REPO / "data" / "bowtie" / "bowtie_profiles.json"
PROV = REPO / "data" / "bowtie" / "PROVENANCE.json"

#: sheet -> cohort vendor label
SHEET_VENDOR = {
    "GE_Revolution": "GE",
    "Philips iQon": "Philips",
    "Toshiba_Aquilion_ONE_Vision": "Canon/Toshiba",
}
#: the body bowtie used for abdominal CT (Philips reports a single filter, labelled Large)
BODY_FILTER = "Large"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def parse_sheet(ws) -> dict:
    # Row 2 = filter labels at the first column of each 4-kVp block; row 3 = kVp; data from row 4.
    filters: dict[str, dict] = {}
    col = 2
    while col <= ws.max_column:
        label = ws.cell(row=2, column=col).value
        if label is None:
            col += 1
            continue
        kvps = [ws.cell(row=3, column=col + i).value for i in range(4)]
        angles: list[float] = []
        cols_vals: list[list[float]] = [[] for _ in range(4)]
        for r in range(4, ws.max_row + 1):
            a = ws.cell(row=r, column=1).value
            if a is None:
                continue
            angles.append(float(a))
            for i in range(4):
                v = ws.cell(row=r, column=col + i).value
                cols_vals[i].append(None if v is None else float(v))
        per_kvp = {}
        for i, kv in enumerate(kvps):
            if kv is None:
                continue
            per_kvp[str(int(kv))] = {
                "angle_deg": angles,
                "al_mm": cols_vals[i],
            }
        filters[str(label)] = per_kvp
        col += 4
    return filters


def main() -> int:
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    vendors: dict[str, dict] = {}
    for sheet, vendor in SHEET_VENDOR.items():
        filters = parse_sheet(wb[sheet])
        vendors[vendor] = {
            "scanner_model": sheet.replace("_", " "),
            "provenance": "measured (Yang 2019 DiB, CC BY 4.0)",
            "filters": filters,
        }

    # Siemens: the open dataset has no Siemens profile. Build it as the cross-vendor
    # average of the body (Large) profiles, per kVp, on a common angle grid, and carry
    # the inter-vendor spread as a declared uncertainty band.
    kvps_common = ["80", "100", "120", "140"]
    siemens_filters: dict[str, dict] = {"Large": {}}
    for kv in kvps_common:
        curves = []
        grids = []
        for vendor in ("GE", "Philips", "Canon/Toshiba"):
            fam = vendors[vendor]["filters"].get(BODY_FILTER, {})
            # Canon's top kVp is 135, not 140; fall back to the nearest available.
            entry = fam.get(kv) or (fam.get("135") if kv == "140" else None)
            if entry is None:
                continue
            a = np.asarray(entry["angle_deg"], float)
            t = np.asarray([np.nan if x is None else x for x in entry["al_mm"]], float)
            m = ~np.isnan(t)
            grids.append(a[m])
            curves.append((a[m], t[m]))
        if not curves:
            continue
        amax = min(float(g.max()) for g in grids)
        grid = np.round(np.arange(0.0, amax + 1e-9, 0.1), 1)
        stack = np.vstack([np.interp(grid, a, t) for a, t in curves])
        mean = stack.mean(axis=0)
        spread = stack.max(axis=0) - stack.min(axis=0)
        siemens_filters["Large"][kv] = {
            "angle_deg": grid.tolist(),
            "al_mm": np.round(mean, 4).tolist(),
            "cross_vendor_spread_mm": np.round(spread, 4).tolist(),
            "n_vendors_averaged": int(stack.shape[0]),
        }
    vendors["Siemens"] = {
        "scanner_model": "(no open profile) cross-vendor average of GE/Philips/Canan body bowtie",
        "provenance": "cross-vendor average (declared uncertainty band = inter-vendor spread)",
        "filters": siemens_filters,
    }

    payload = {
        "quantity": "equivalent aluminium thickness t(psi) vs fan angle (mm Al)",
        "beam_used_by_iorn007": "120 kVp",
        "body_filter_for_abdominal_ct": BODY_FILTER,
        "symmetry": "bowtie assumed symmetric: t(-psi) = t(psi)",
        "source": {
            "citation": "Yang K, Ruan C, Li X, Liu B. Data in Brief 25:104261 (2019)",
            "doi": "10.1016/j.dib.2019.104261",
            "pmcid": "PMC6706760",
            "licence": "CC BY 4.0",
            "licence_url": "https://creativecommons.org/licenses/by/4.0/",
            "covers_vendors": ["GE", "Philips", "Canon/Toshiba"],
            "missing_vendors": ["Siemens"],
            "kvps_measured": [80, 100, 120, "135/140"],
        },
        "vendors": vendors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    prov = {
        "file": "yang2019_dib_mmc1.xlsx",
        "sha256": _sha256(XLSX),
        "bytes": XLSX.stat().st_size,
        "downloaded_from": "https://ars.els-cdn.com/content/image/1-s2.0-S2352340919306158-mmc1.xlsx",
        "citation": "Yang K, Ruan C, Li X, Liu B. Data of CT bow tie filter profiles from three modern CT scanners. Data in Brief 25:104261 (2019).",
        "doi": "10.1016/j.dib.2019.104261",
        "pmcid": "PMC6706760",
        "licence": "CC BY 4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "licence_verified_from": "PMC JATS <license license-type='CC BY' href='creativecommons.org/licenses/by/4.0/'>; (c) 2019 The Author(s)",
        "extracted_by": "tools/build_bowtie_profiles.py",
        "derived_products": {
            "bowtie_profiles.json": "per-vendor t(psi); Siemens = cross-vendor average with declared spread",
        },
    }
    PROV.write_text(json.dumps(prov, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Report the 120 kVp body-bowtie centre values so the extraction is visible.
    print(f"wrote {OUT}\nwrote {PROV}  (sha256 {prov['sha256'][:16]}...)")
    for vendor in ("GE", "Philips", "Canon/Toshiba", "Siemens"):
        e = vendors[vendor]["filters"].get(BODY_FILTER, {}).get("120")
        if not e:
            print(f"  {vendor:14s} Large 120 kVp: (none)")
            continue
        t = np.asarray(e["al_mm"], float)
        extra = ""
        if "cross_vendor_spread_mm" in e:
            extra = f"  spread<= {max(e['cross_vendor_spread_mm']):.2f} mm"
        print(
            f"  {vendor:14s} Large 120 kVp: centre {t[0]:.2f} mm, edge {t[-1]:.2f} mm "
            f"(delta {t[-1]-t[0]:.2f} mm over {e['angle_deg'][-1]:.1f} deg){extra}  [{vendors[vendor]['provenance']}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

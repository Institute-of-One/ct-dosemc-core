"""Extract the one cross-section Figure 1 is drawn from, and the numbers on it.

    python tools/figure1_ladder.py

Figure 1 shows what each level of the calculation knows about the patient, on one
patient: the index the scanner reports, that index weighted by the patient's own
organs, and absorbed dose transported through them. Every other figure in this
paper is a plot. A reader who treats patients rather than scatter points has
nothing in the paper to look at, and the quantity the paper is about -- dose in
an organ of a particular person -- is never shown in an organ.

This script is the only thing in the repository that opens imaging. It reduces
one series to a single axial slice and the organ labels on it, writes that beside
the three numbers per organ, and stops. ``paper/freeze.py`` copies the result into
``paper/frozen/`` and ``paper/make_figures.py`` draws from the copy, so the
archive can redraw the figure with no imaging and no network.

**What is published.** One axial cross-section of one series from a Creative
Commons Attribution collection, with the collection, the Series Instance UID and
the licence recorded here and printed in the caption. That is a figure, not a
redistribution of the collection: the 3 1/2 thousand other slices, the header and
the pixel data as acquired stay where they are, and ``data/PROVENANCE.json``
records how to fetch them.

Nothing here is chosen by eye. Both choices are rules, they are recomputed on
every run, and they are written into the output so the caption can state them:

* **the patient** -- among the series carrying a CTDIvol *recorded by the
  scanner*, the one whose median dose-to-index ratio is closest to the cohort
  median of those medians. The typical patient by the paper's own endpoint, with
  no reconstruction step standing between the scanner and panel (a).
* **the slice** -- the axial slice carrying the most of the twelve organs; among
  ties, the one where they cover the most area. The purpose of the section is to
  show the organs the dose is reported in, so the rule maximises how many of them
  it shows. The liver's centroid, the first rule tried, sits high in the abdomen
  and carried six.

If the results change, the rule selects whatever it now selects and the image
changes with it. That is the intent: the visual-review ledger then goes red and
the figure has to be looked at again, which is the only check that has ever
caught anything in an image.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DICOM_ROOT = REPO.parent / "ctsegdose_core"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ct_dosemc_core.ct_series import load_series  # noqa: E402
from ct_dosemc_core.segment import load_mask  # noqa: E402
from ct_dosemc_core.volume import load_volume_hu  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

COHORT = REPO / "results" / "phase2_cohort"
RUNS = REPO / "results" / "phase2_patient"
SEGMENTATIONS = REPO / "segmentations"
PROVENANCE = REPO / "data" / "PROVENANCE.json"

OUT_NPZ = COHORT / "figure1_ladder.npz"
OUT_JSON = COHORT / "figure1_ladder.json"

#: Margin in voxels around the body on the published section.
CROP_MARGIN = 6

#: Below this the voxel is outside the patient for cropping purposes. The same
#: threshold the phantom builder uses to find the body.
BODY_HU = -300.0

SERIES_RULE = (
    "Among the series carrying a CTDIvol recorded by the scanner, the one whose "
    "median dose-to-index ratio is closest to the cohort median of those medians."
)
SLICE_RULE = (
    "The axial slice carrying the most of the organs scored; among ties, the one "
    "where they cover the most area."
)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _organ_records(organs: Any) -> dict[str, Any]:
    """``organ_doses.json`` has written organs both ways over the campaign."""
    if isinstance(organs, dict):
        return dict(organs)
    return {o["organ"]: o for o in organs}


def _dose_mgy(record: dict[str, Any]) -> float:
    for key in ("dose_mgy", "absorbed_dose_mgy"):
        if key in record:
            return float(record[key])
    raise KeyError(f"no dose in an organ record with keys {sorted(record)}")


def per_series_ratios() -> dict[str, dict[str, Any]]:
    """Dose-to-index ratio per organ, per series, for every series on Fig. 4."""
    doses = load(REPO / "paper" / "frozen" / "figure4_doses.json")
    index = load(COHORT / "iorn006_organ_index.json")
    by_uid = {s["series_instance_uid"]: s for s in index["series"]}

    out: dict[str, dict[str, Any]] = {}
    for series in doses["series"]:
        uid = series["series_instance_uid"]
        if not (series.get("on_figure4") and series.get("scale_factor")):
            continue
        run = RUNS / f"prod_{uid}" / "organ_doses.json"
        if not run.is_file():
            continue
        raw = _organ_records(load(run)["organs"])
        idx = {o["organ"]: o for o in by_uid[uid]["organs"]}
        organs: dict[str, dict[str, float]] = {}
        for organ, record in raw.items():
            weighted = idx.get(organ, {}).get("organ_weighted_ctdivol_mgy")
            if not weighted:
                continue
            dose = _dose_mgy(record) * series["scale_factor"]
            organs[organ] = {
                "absorbed_dose_mgy": dose,
                "organ_weighted_ctdivol_mgy": float(weighted),
                "ratio": dose / float(weighted),
            }
        if organs:
            out[uid] = {
                "vendor": series["vendor"],
                "ctdivol_mgy": series["ctdivol_mgy"],
                "ctdivol_origin": series["ctdivol_origin"],
                "organs": organs,
                "median_ratio": statistics.median(o["ratio"] for o in organs.values()),
            }
    return out


def choose(ratios: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """The series SERIES_RULE names, and the cohort statistic it is measured against."""
    if not ratios:
        raise SystemExit("no series carry both an absorbed dose and an index")
    cohort_median = statistics.median(s["median_ratio"] for s in ratios.values())
    recorded = {
        uid: s for uid, s in ratios.items() if s["ctdivol_origin"] == "recorded"
    }
    if not recorded:
        raise SystemExit("no series carries a CTDIvol recorded by the scanner")
    # Sorted by distance, then by UID, so a tie cannot depend on dict order.
    uid = min(recorded, key=lambda u: (abs(recorded[u]["median_ratio"] - cohort_median), u))
    return uid, {
        "rule": SERIES_RULE,
        "n_series_considered": len(ratios),
        "n_with_recorded_ctdivol": len(recorded),
        "cohort_median_of_series_medians": cohort_median,
        "chosen_median_ratio": recorded[uid]["median_ratio"],
    }


def section(uid: str, dicom_root: Path) -> dict[str, Any]:
    """The HU section SLICE_RULE names, its organ labels, and where it came from."""
    provenance = {s["series_instance_uid"]: s for s in load(PROVENANCE)["series"]}
    if uid not in provenance:
        raise SystemExit(f"{uid} is not in data/PROVENANCE.json")
    record = provenance[uid]

    directory = Path(record["local_path"])
    if not directory.is_dir():
        # The working copy is deleted after processing. The series was segmented
        # from the companion project's copy, which is where the run recorded it.
        plan = load(RUNS / f"prod_{uid}" / "organ_doses.json")["plan"]
        directory = Path(plan["dicom_dir"])
    if not directory.is_dir():
        candidate = dicom_root / Path(record["local_path"]).relative_to("data")
        directory = candidate
    if not directory.is_dir():
        raise SystemExit(
            f"the imaging for {uid} is not on this machine. data/PROVENANCE.json "
            f"records how to fetch it; see docs/REPRODUCING_DATA.md"
        )

    series = load_series(directory, series_uid=uid)
    volume, _ = load_volume_hu(series)  # (z, y, x), inferior -> superior

    mask_dir = next(
        (p for p in sorted((SEGMENTATIONS / uid).glob("*/masks")) if p.is_dir()), None
    )
    if mask_dir is None:
        raise SystemExit(f"no segmentation masks under {SEGMENTATIONS / uid}")

    masks = {}
    for path in sorted(mask_dir.glob("*.nii.gz")):
        masks[path.name[: -len(".nii.gz")]] = load_mask(path, volume.shape)
    if not masks:
        raise SystemExit(f"no masks loaded for {uid}")

    # Per slice: how many organs appear on it, and how much area they cover.
    present_per_slice = np.zeros(volume.shape[0], dtype=np.int32)
    area_per_slice = np.zeros(volume.shape[0], dtype=np.int64)
    for mask in masks.values():
        per_slice = mask.sum(axis=(1, 2))
        present_per_slice += (per_slice > 0).astype(np.int32)
        area_per_slice += per_slice.astype(np.int64)
    best = int(present_per_slice.max())
    if best == 0:
        raise SystemExit(f"no organ appears on any slice for {uid}")
    candidates = np.flatnonzero(present_per_slice == best)
    z = int(candidates[int(np.argmax(area_per_slice[candidates]))])

    hu = volume[z].astype(np.int16)
    names = sorted(masks)
    labels = np.zeros(hu.shape, dtype=np.uint8)
    present = []
    for number, name in enumerate(names, start=1):
        plane = masks[name][z]
        if plane.any():
            present.append(name)
        # Later organs do not overwrite earlier ones, so a voxel claimed twice
        # keeps the first label rather than depending on iteration order.
        labels = np.where((labels == 0) & plane, np.uint8(number), labels)

    body = hu > BODY_HU
    if not body.any():
        raise SystemExit("no voxel above the body threshold on the chosen slice")
    rows = np.flatnonzero(body.any(axis=1))
    cols = np.flatnonzero(body.any(axis=0))
    r0 = max(int(rows[0]) - CROP_MARGIN, 0)
    r1 = min(int(rows[-1]) + CROP_MARGIN + 1, hu.shape[0])
    c0 = max(int(cols[0]) - CROP_MARGIN, 0)
    c1 = min(int(cols[-1]) + CROP_MARGIN + 1, hu.shape[1])

    dy, dx = series.pixel_spacing_mm
    return {
        "hu": hu[r0:r1, c0:c1],
        "labels": labels[r0:r1, c0:c1],
        "label_names": names,
        "organs_on_section": present,
        "slice": {
            "rule": SLICE_RULE,
            "z_index": z,
            "n_slices": int(volume.shape[0]),
            "n_organs_on_slice": best,
            "n_slices_tied": int(candidates.size),
            "crop_rows": [r0, r1],
            "crop_cols": [c0, c1],
            "pixel_spacing_mm": [float(dy), float(dx)],
            "body_threshold_hu": BODY_HU,
        },
        "acquisition": {
            "manufacturer": series.manufacturer,
            "model_name": series.model_name,
            "kvp": series.kvp,
            "slice_thickness_mm": series.slice_thickness_mm,
        },
        "source": {
            "collection": record["collection"],
            "collection_uri": record.get("collection_uri"),
            "series_instance_uid": uid,
            "licence": record["licence"],
            "licence_uri": record.get("licence_uri"),
            "retrieved_utc": record.get("retrieved_utc"),
            "what_is_published": (
                "one axial cross-section of this series, and the organ labels on it"
            ),
        },
    }


def build(dicom_root: Path = DEFAULT_DICOM_ROOT) -> int:
    ratios = per_series_ratios()
    uid, selection = choose(ratios)
    chosen = ratios[uid]
    extracted = section(uid, dicom_root)

    index = load(COHORT / "iorn006_organ_index.json")
    weights = {
        o["organ"]: o
        for s in index["series"]
        if s["series_instance_uid"] == uid
        for o in s["organs"]
    }

    organs = {}
    for organ in extracted["organs_on_section"]:
        pair = chosen["organs"].get(organ)
        if pair is None:
            continue
        organs[organ] = {
            "organ_weighted_ctdivol_mgy": pair["organ_weighted_ctdivol_mgy"],
            "absorbed_dose_mgy": pair["absorbed_dose_mgy"],
            "ratio": pair["ratio"],
            "relative_weight": weights.get(organ, {}).get("relative_weight"),
        }
    if not organs:
        raise SystemExit("no organ on the chosen section carries both quantities")

    payload = {
        "what": (
            "Figure 1: what each level of the calculation knows about the patient, "
            "on one series. Panel (a) the CTDIvol the scanner recorded; (b) that "
            "index weighted by each segmented organ's share of the tube current; "
            "(c) absorbed dose transported through the same anatomy."
        ),
        "not": (
            "Not a dose distribution: the paper's endpoint is the dose in an organ, "
            "so panels (b) and (c) paint one value per organ and no voxel-level "
            "dose map is shown or implied. Not a redistribution of the collection."
        ),
        "selection": selection,
        "series": {
            "series_instance_uid": uid,
            "vendor": chosen["vendor"],
            "ctdivol_mgy": chosen["ctdivol_mgy"],
            "ctdivol_origin": chosen["ctdivol_origin"],
            "median_ratio": chosen["median_ratio"],
            "n_organs_scored": len(chosen["organs"]),
        },
        "acquisition": extracted["acquisition"],
        "slice": extracted["slice"],
        "source": extracted["source"],
        "label_names": extracted["label_names"],
        "organs": organs,
        "lineage": {
            "panel_a": {
                "quantity": "CTDIvol recorded in the series header, in mGy",
                "knows_about_the_patient": "nothing beyond the acquisition settings",
            },
            "panel_b": {
                "quantity": "organ-weighted CTDIvol, in mGy",
                "knows_about_the_patient": "the geometry of each segmented organ",
                "from": index["iorn006"],
            },
            "panel_c": {
                "quantity": "absorbed organ dose, in mGy",
                "knows_about_the_patient": (
                    "the same geometry, with photons transported through it"
                ),
            },
        },
    }

    COHORT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        OUT_NPZ,
        hu=extracted["hu"],
        labels=extracted["labels"],
        label_names=np.array(extracted["label_names"], dtype=object),
    )
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )

    print(f"wrote {OUT_NPZ.relative_to(REPO)} and {OUT_JSON.relative_to(REPO)}")
    print(f"  series   {uid}")
    print(f"           {chosen['vendor']}, {extracted['acquisition']['model_name']}, "
          f"CTDIvol {chosen['ctdivol_mgy']:.1f} mGy ({chosen['ctdivol_origin']})")
    print(f"           {extracted['source']['collection']}, "
          f"{extracted['source']['licence']}")
    print(f"  rule     median ratio {chosen['median_ratio']:.4f} against cohort "
          f"median {selection['cohort_median_of_series_medians']:.4f}, "
          f"{selection['n_with_recorded_ctdivol']} of "
          f"{selection['n_series_considered']} series eligible")
    print(f"  slice    z={extracted['slice']['z_index']} of "
          f"{extracted['slice']['n_slices']}, section "
          f"{extracted['hu'].shape[0]}x{extracted['hu'].shape[1]} voxels")
    print(f"  organs   {len(organs)} on the section: {', '.join(sorted(organs))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dicom-root", type=Path, default=DEFAULT_DICOM_ROOT,
                        help="where the companion project keeps its working copy")
    args = parser.parse_args(argv)
    return build(args.dicom_root)


if __name__ == "__main__":
    raise SystemExit(main())

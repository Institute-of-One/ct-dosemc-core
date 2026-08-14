# Reproducing the data

**No DICOM is redistributed by this repository, and none ever will be.** The
imaging is public and CC BY, but the openness claim of IORN-007 is about the
*pipeline* being reproducible, not about mirroring archives. What is recorded
here — collection, Series Instance UID, licence, retrieval date, and the exact
query that selected it — is enough for anyone to fetch the identical series from
TCIA and re-run every number.

The same rule applies in the other direction: **no proprietary organ-dose
coefficient table is shipped, transcribed or paraphrased.** IORN-007 computes its
own coefficients; that is its entire reason to exist.

---

## 1. What data the project uses

| Phase | Data | Source | Licence |
|---|---|---|---|
| 1 (anchor) | none — the CTDI phantom is built analytically from IEC 60601-2-44 | — | — |
| 2 (cohort) | the multi-vendor CT series of IORN-006 | TCIA | CC BY |
| 2 | material cross-sections | PENELOPE 2006 PENDBASE photon subset, generated locally | permissive (see `MC_SOURCE_MODEL.md` §1.1) |
| 2 | organ masks | TotalSegmentator, run at inference on the local series | Apache-2.0 |

Phase 1 needs **no patient data at all**. That is deliberate: the validation
anchor must not depend on any acquisition, so that it stands alone if the
IORN-004/006 reviews change anything about the shared pipeline.

## 2. Cohort selection (Phase 2)

The selection targets four vendors with contrast-free or arterial-phase
abdominal/chest series carrying the acquisition attributes the dose model needs —
per-slice **X-Ray Tube Current (0018,1151)**, kVp, collimation, pitch, CTDIvol —
and series that are complete, single-acquisition and geometrically regular.

**"10 per vendor" is an upper limit, not a natural yield.** `--per-vendor 10` is a
target cap: probing halts for a vendor once ten series are kept, and every vendor's
probe queue held more than ten. The multi-vendor balance is therefore a **design
choice, not a property of the data** — the paper should state it that way.

**Ported and exercised (D2, done).** The selective NBIA fetch — which downloads
only the series that pass the filter rather than a whole collection — is now in
this repository as `tools/select_and_download.py`, on top of the ported
`ct_dosemc_core.nbia`, `ct_dosemc_core.selection` and
`ct_dosemc_core.acquisition` modules. It was ported at the start of Phase 2, not
before: Phase 1 needs no patient data, so a downloader that could not be exercised
would be untested code pretending to be a capability.

```powershell
python tools/select_and_download.py --stage all --per-vendor 10
```

*Download-path fix.* The ported original computed each series' provenance
`local_path` with `dest.relative_to(REPO)`, which raised `ValueError` — **after**
the bytes had transferred — whenever `--data` pointed outside the script's own
repository (a shared cache on another drive is a legitimate `--data`). A
reproducibility claim cannot rest on a downloader that only works when its output
lands inside one particular repository, so the copy here uses
`ct_dosemc_core.acquisition.series_local_path`, which never raises, and the fix is
pinned by `tests/test_select_and_download.py`.

*The probe stage is the flow-diagram's operative step.* The full funnel is
recorded in `results/phase2_cohort/cohort_overlap.json` (`selection_funnel`). The
eligibility screen does its real work at the probe: **62 series probed, 40 kept,
22 rejected**, dominated by *tube-current-not-modulated* (15) and
*no-per-slice-tube-current* (5), with *not-a-reconstructed-image* (1) and
*not-abdominal-in-header* (1). By vendor the rejections were GE 8, Canon/Toshiba 6,
Siemens 4, Philips 4 (each vendor still reaching its cap of 10). These are the
per-slice-modulation and reconstruction attributes the absorbed-dose model needs;
the flow diagram should show this stage, not just the final count.

*Cohort identity.* This selection returned the **same 40 series as IORN-006**
(10 per vendor; overlap 40/40, recorded in `cohort_overlap.json`). The paper may
therefore say the IORN-006 cohort is reused; IORN-007's absorbed-dose eligibility
(`ct_dosemc_core.eligibility`) is a separate, later gate applied on top of that
shared set, not the download filter. `data/PROVENANCE.json` is the only thing
under `data/` that is committed.

## 2a. Organ masks (Phase 2, D3)

`tools/segment_cohort.py` runs TotalSegmentator on each downloaded series and
returns organ masks **on the native DICOM voxel grid**. The chain — resolve the
true slice grid (`ct_dosemc_core.grid`), build the NIfTI affine from the DICOM
patient coordinates (`ct_dosemc_core.ct_series`), segment in a separate CPU child
process (`ct_dosemc_core.segment` → `_ts_worker`), read the masks back on the same
grid — is ported from IORN-006 so IORN-007 stands alone.

```powershell
python tools/segment_cohort.py            # full 1.5 mm, device cpu, resumable
```

* **Resolution.** Full 1.5 mm model (`--fast` selects 3 mm but is **not** used).
  This **matches** IORN-006's committed cohort, which was itself segmented at 1.5 mm
  with the same TotalSegmentator 2.17.0 — so §2c's device-independence cross-check is
  a like-for-like comparison. Absorbed organ dose is sensitive to the partial-volume
  error at an organ boundary, which is the reason 1.5 mm (not 3 mm) is used. Task
  (`total`), roi_subset (the abdominal set) and licence (Apache-2.0, inference only)
  match IORN-006. TotalSegmentator and torch are pinned only as `>=2.0` in
  `pyproject`; the exact versions are captured per series.
  The choice is recorded in `results/phase2_cohort/segmentation_config.json`.
* **CPU.** `--device cpu` by default, so segmentation does not contend with a GPU
  Monte-Carlo job for device memory.
* **One series finalised before the next.** Each series' masks and per-series JSON
  are written, and its verdict (`ok` / `downgraded` to 3 mm / `failed` with the
  exception text) recorded in `results/phase2_cohort/segmentation_manifest.json`,
  before the loop moves on. A re-run skips series already `ok` and reuses cached
  masks — nothing is dropped silently, and an interrupted batch resumes for free.
* **Voxel correspondence is a test, not a claim.** That a mask returns on exactly
  the CT's `(z, y, x)` grid — the identity the whole geometry relies on — is
  `ct_dosemc_core.segment.assert_voxel_correspondence`, pinned by
  `tests/test_segmentation.py`.

## 2b. HU → density write-out check (Phase 2, D4)

`tools/check_hu_density.py` builds the density universe the Monte Carlo actually
tracks through — `ct_dosemc_core.phantom.patient_density_map` — and checks it on a
sample of series. That map is **body-contour masked**: outside the patient outline
(threshold + largest connected component + slice-wise hole fill) every voxel is set
to air, and inside, the Schneider `hu_to_density` calibration applies. This is a
structural decision, not a clamp: a reconstruction fills the out-of-field region
with a padding value (−2048 HU on the Canon/Toshiba series here, with no DICOM
padding tag to declare it), and that region is *nothing*, not a material — so it is
made air explicitly rather than mapped near air by luck. A voxel **inside** the body
above the top Schneider breakpoint (metal, dense contrast, artefact) is held at the
top density **and counted in the report**, never silently clamped, because clamping
an in-body high value to cortical-bone density would shield the organ behind it and
bias its dose downward with no error anywhere.

The check confirms the density grid equals the CT grid, every density is positive
and in range, the in-body air/soft-tissue calibration is sane (air/lung near
−800…−1000 HU, soft tissue near −100…+50 across all four vendors), and the volume is
not a decoded-padding block of air — the failure that destroyed four GE series in
IORN-006. Run early, per vendor, so a defect is seen before the cohort is committed
to:

```powershell
python tools/check_hu_density.py --per-vendor 1   # writes results/phase2_cohort/hu_density_check.json
```

## 2c. Segmentation resolution and the ICRP 89 cross-check

`tools/organ_volume_vs_icrp89.py` tabulates solid-organ mass and volume; results in
`results/phase2_cohort/organ_volume_vs_icrp89.json`.

* **Methods — the port is device-independent.** IORN-007's CPU (`torch cpu`) 1.5 mm
  organ volumes reproduce IORN-006's GPU (`torch cu128`) 1.5 mm volumes on the same
  40 series (median ratio **1.00**, pancreas 0.99), both TotalSegmentator 2.17.0.
  This is an independent verification that the ported segmentation is
  device-independent — structurally the **same claim as the G5 CPU/GPU bit-identity
  gate** on the transport engine, applied here to the anatomy input.
* **A 3 mm pass is deliberately not run.** The handover asked for a *second
  segmentation model*, not a second resolution; the same TotalSegmentator at 3 mm
  shares the boundary-definition behaviour and so does not separate model from
  anatomy, and resolution-independence is already shown by the same-resolution,
  same-version reproduction above.
* **Discussion (one paragraph) — ICRP 89 agreement is not a requirement.** IORN-007
  computes dose on each patient's own segmented organ mass, so departure from a
  reference-phantom mass is expected, not a defect. The pancreas (−38.5%) and spleen
  (+72.4%) deviations are reproduced at *fixed* 1.5 mm with the same model, so they
  are not a resolution artefact; they are tabulated as descriptive context only, not
  as a validation gate.

## 2d. Density-calibration eligibility (the one pixel-based gate)

**The governing principle, stated once:** *if admitting one series would require a
new rule written for that series, the series is excluded instead.* A rule is
defensible in review; a per-case exception is not, and per-series special-case code
is what a reviewer distrusts most. Every criterion is a uniform threshold on a
measured quantity; no bespoke per-series handling is written.

`ct_dosemc_core.eligibility` is header-only. The one criterion that must read pixels
is its sibling in `ct_dosemc_core.phantom`, applied over the cohort by
`tools/cohort_density_eligibility.py` on top of the per-voxel distribution from
`tools/metal_distribution.py`:

* **Definition (vendor-neutral).** An *out-of-calibration voxel* is inside the body
  contour with **HU ≥ 3071** — the 12-bit reconstruction saturation ceiling. Clipping
  (12-bit exports) and exceeding (16-bit exports) are treated identically, so the
  metric is not a 16-bit-export detector. (`HU > 3071` would be: only Canon's 16-bit
  export can exceed it, so it would exclude Canon alone — a vendor detector, not a
  metal detector.)
* **The single gate.** A series is **excluded** if its **largest connected
  out-of-calibration component ≥ 1 cm³** — a compact metal implant, whose atomic
  number Schneider cannot represent (photoelectric cross section misassigned). The
  threshold sits in the cohort's **natural gap (0.91–2.06 cm³)**, so it is not fitted
  to any one series. Scattered clips, calcification, contrast and beam-hardening
  speckle are all below 1 cm³ and are kept.
* **Result.** 8 series excluded → **N = 32**. Eligible **by vendor, with N**: GE 8/10,
  Siemens 9/10, Canon/Toshiba 6/10, Philips 9/10. The exclusions fire on **all four
  vendors**, the signature of a material rule rather than a vendor detector; Canon's
  higher count is corroborated by in-body HU ≫ 3071 (true 16-bit metal) and is a
  **cohort finding, reported not corrected**.
* **The vendor imbalance (8/9/6/9) is not fixed.** Adding probes would restart
  selection; trimming would discard survivors of a declared rule. It is reported as a
  consequence of the pre-declared criterion, and every by-vendor table carries N.
* **Distances are reported, not gated.** `density_eligibility.json` carries each
  excluded series' distance to every scored organ (`excluded_distance_table_mm`):
  measure everything, gate on one thing.

**How to describe the cohort.** "The cohort is IORN-006's 40 series. Of these, 8 were
excluded from the absorbed-dose analysis by a pre-declared density-calibration
criterion (a metal implant ≥ 1 cm³ inside the body contour, beyond the Schneider
range). Absorbed dose is computed on N = 32 (GE 8, Siemens 9, Canon/Toshiba 6,
Philips 9); the index-correspondence comparison uses the common 32." Cohort identity
is not lost — the archive and the 40-series origin are unchanged.

## 2e. Patient phantom geometry and the 2.5 mm resampling cost (Phase 2, (a))

The dose grid is isotropic **2.5 mm**, not the native ~0.7 mm image: G3 needs the
air box to reach the focal spot (~130 cm box), which at 0.7 mm is ~2.4×10⁹ voxels
and not runnable; at 2.5 mm it is ~520×520×200 = 5.4×10⁷, about twice the G2 phantom
and the same 0.25 cm at which G2/G3 convergence was measured
(`MC_SOURCE_MODEL.md` §5.2a). `ct_dosemc_core.patient.build_patient_phantom`
resamples the HU volume to 2.5 mm, then derives the body contour, Schneider density
and composition groups on that grid so materials and density are mutually
consistent; the dose ROI is the organ's bounding box (`organ_bounding_box`).

The price of resampling is measured, not assumed:

```
python tools/resample_cost.py     # -> results/phase2_cohort/resample_cost.json
```

Organ mass on the native grid vs the 2.5 mm grid, over the 32 eligible series. The
**median mass change is 0.8–1.1 % for every scored abdominal organ** (a slight loss
from partial-volume smoothing), **consistent across all four vendors** (per-vendor
median 0.990–0.993); only the smallest structures rise higher (adrenals: median
1.5–2.7 %, worst 16.5 % on a few-voxel gland). This is a declared limitation of the
same size as the Phase-1a voxel-size term, and its device-independence is the same
kind of cross-check as G5.

## 3. `data/PROVENANCE.json`

One record per series, carrying at minimum:

```json
{
  "collection": "...",
  "series_instance_uid": "1.3.6.1.4.1.....",
  "study_instance_uid": "1.3.6.1.4.1.....",
  "manufacturer": "...",
  "licence": "CC BY 4.0",
  "licence_url": "https://creativecommons.org/licenses/by/4.0/",
  "retrieved_utc": "2026-...",
  "n_instances": 0,
  "sha256_manifest": "..."
}
```

The `sha256_manifest` pins the bytes that were actually processed, so a re-fetch
that returns different pixels is detected rather than silently absorbed.

## 4. Regenerating the material files

Not data in the imaging sense, but an input that changes results, so it is
version-pinned the same way.

```
git clone --depth 1 https://github.com/andreubs/MCGPU_materials vendor/MCGPU_materials
python tools/make_materials.py                                          # Phase-1 anchor: PMMA, air, water
python tools/make_materials.py --only lung adipose soft_tissue bone_cortical air  # Phase-2 soft + endpoint
python tools/make_materials.py --only-bones --bones 11                  # Phase-2 graded bone series (√f edges)
```

This writes `materials/*.mcgpu.gz` (git-ignored) and `materials/PROVENANCE.json`
(committed), which records for each material its PENDBASE entry number and label,
the nominal density the database supplies, the energy grid, and the SHA-256 of
the generated file. The generator refuses to continue if a PENDBASE id does not
resolve to the expected material name — the ids in the upstream README are not
all correct, and simulating photographic emulsion instead of PMMA is the kind of
mistake that produces perfectly plausible numbers.

The **Phase-2 patient set** is the Schneider tissue-group universe (§2b,
`MC_SOURCE_MODEL.md` §5.2a): 4 merged soft tissues (`air`, `lung`, `adipose`,
`soft_tissue`) as named ICRP compositions (PENDBASE 104/191/103/262) plus 11 graded
bone bins, edges uniform in √*f* so the finest bins sit at the scored-soft-tissue
boundary. PENELOPE has no marrow/spongiosa gradation, so each bone bin is a
**volume-fraction mix** of `TISSUE, SOFT (ICRP)` and `BONE, CORTICAL (ICRP)`:
*f* is linear in HU, and the elemental weight fractions follow from
w_bone = f·ρ_bone/ρ_mix (Schneider 2000). `--bones N` shares the group-table edges.
`materials/PROVENANCE.json` records each bin's HU interval, *f*, w_bone, elemental
weight fractions and SHA-256. The 11-bin √*f* discretisation error in μ(60 keV) is
measured (`tools/bone_bin_error.py`): max 2.64% at HU 700, median 1.03%; at the
soft-tissue boundary (HU 100) 0.40% (was 5.80% under 8 equal-HU bins).
MC-GPU v1.3's MAX_MATERIALS = 15
caps the set; the default of 15 fills it. Metal is excluded upstream (§2d),
so the set only spans air → cortical bone.

## 5. Re-running Phase 1

```powershell
powershell -File tools/build_mcgpu.ps1 -Target cpu
python tools/make_materials.py
python tools/run_validation.py --kvp 120 --phantom-diameter 32 --collimation 2.0 `
    --voxel-size 0.25 --projections 180 --histories 5.6e6 --mas 100
python -m pytest
```

The run is seeded (`--seed`, default 1234567890) and MC-GPU's PRNG is
deterministic, so the same command on the same binary reproduces the same numbers
bit for bit. `results/phase1/<tag>/` keeps the spectrum, the engine input, the log
and the results JSON; the bulky voxel geometry and raw tallies are regenerated
rather than committed.

## 6. What is committed, and why

| Committed | Not committed |
|---|---|
| `results/*.json` — every paper number, with provenance | `results/phase1/**/*.raw`, `*.vox.gz`, projection images |
| `materials/PROVENANCE.json` | `materials/*.mcgpu.gz` |
| `data/PROVENANCE.json` | any DICOM, any NIfTI, any segmentation |
| `vendor/build/build_info.json` (via the results files) | compiled binaries, vendored toolchains, `vendor/MCGPU` |

Vendored third-party source (`vendor/MCGPU`, `vendor/MCGPU_materials`,
`vendor/zlib-*`) is cloned by the build scripts rather than committed, so this
repository redistributes no one else's code — even the code whose licence would
permit it.

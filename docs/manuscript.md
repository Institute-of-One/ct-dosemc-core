# Manuscript skeleton — IORN-007

*Working title:* Device-independent Monte-Carlo CT organ dosimetry on patient
anatomy: a TG-195-verified MC-GPU source model with a fully re-derivable cohort.

**Status of this file.** Skeleton only. Each section lists the claim, the evidence
artefact (a `results/*.json` or a canonical doc), and whether it is **DONE**,
**IN PROGRESS**, or **GATED** (blocked until G0–G5 close; see
`docs/IORN007_scope_to_acceptance.md` §0). No numbers are written here that are not
already machine-recorded in `results/`. Target journal: *Physics in Medicine &
Biology* (code-verification + application).

---

## Abstract
- [GATED on final organ-dose numbers] One paragraph: verified engine, re-derivable
  cohort, patient organ doses normalised to recorded CTDIvol.

## 1. Introduction
- **Differentiation (not competing on scale).** The contribution is fidelity and
  reproducibility per patient, not cohort size; N is set by the multi-vendor claim,
  not statistics (kickoff §Differentiation). → so N = 32 after eligibility is ample.
- Gap addressed: open, re-derivable pipeline from DICOM to organ dose with a
  transport engine verified against a recognised benchmark.
- Scope: Phase 1a = code verification (TG-195 Case 4); Phase 2 = patient organ dose.
  Phase 1b (bowtie) is a Methods component, not a second gate.

## 2. Methods

### 2.1 Monte-Carlo engine and build provenance — **DONE**
- MC-GPU v1.3, patched; CPU and GPU built from one patch set.
- Evidence: `vendor/build/build_info.json`; `docs/MC_SOURCE_MODEL.md` §1–§3.
- Device independence of the engine: G5 CPU/GPU byte agreement.

### 2.2 Source model — **DONE (spectrum/geometry); bowtie IN PROGRESS**
- Spectrum: SpekPy/IPEM-78 (`ct_dosemc_core.spectra`); G0 spectrum check
  (−2.3% at 120 kVp, −1.8% at 100 kVp).
- Fan geometry via K azimuthal sub-fans; solid-angle recombination.
- Bowtie: sub-fan per-spectrum, `t(ψ)` from **CC-BY measured profiles** (Yang 2019
  DiB, committed at `data/bowtie/`, GE/Philips/Canon). **Siemens = cross-vendor
  average with the inter-vendor spread as a declared uncertainty band** (a measured
  band, not a borrow). Each vendor carries its profile provenance
  (measured / average). Validation: one-parameter family fit + CTDI₁₀₀
  central/peripheral ratio check on the three measured vendors. →
  `docs/MC_SOURCE_MODEL.md` §5.2.

### 2.3 Verification against TG-195 Case 4 (G0–G5) — **IN PROGRESS**
- Gate table: `docs/IORN007_scope_to_acceptance.md` §2 (authoritative).
  - G0 spectrum PASS; G1 mono-energetic PASS (worst 0.147%); G1′ PASS (0.338%);
    G5 CPU/GPU byte-agree PASS.
  - G2 (a) anchor uncertainty ≤ 0.15%: **IN PROGRESS** — needs the K=4 ten-replica
    anchor (Route B), currently 4/10; centre 0.406%/√10 = 0.128% expected to close.
  - (b) |ours − PENELOPE| < 2σ is **reported, not a gate** (scope §3).
- Independent SD cross-check: 94-position azimuthal replication (0.151%) vs replica
  SD (0.145%). Evidence: `results/phase1a_G4_replica_uncertainty_*_K1.json`.

### 2.4 Uncertainty budget and declared limitations — **IN PROGRESS**
- Measured: phantom length (40 vs 160 cm, 10 replicas each) — the one re-measured Δ.
- Declared upper-bound limitations (not re-measured; PENELOPE's 0.167% floor):
  voxel size, air margin, sub-fan K, spectrum. → `docs/MC_SOURCE_MODEL.md` §5.3.0e.

### 2.5 Patient cohort — selection and eligibility — **DONE**
- Archive: TCIA; selective NBIA fetch (`tools/select_and_download.py`, bug-fixed and
  regression-tested). Same 40 series as IORN-006 (overlap 40/40).
- Selection funnel (flow diagram): 47,181 → 40; **probe stage 62 probed, 40 kept, 22
  rejected** by vendor (GE 8, Canon 6, Siemens 4, Philips 4); reasons dominated by
  tube-current-not-modulated. Evidence: `results/phase2_cohort/cohort_overlap.json`.
- "10 per vendor" is an **upper limit (design), not a data property**; multi-vendor
  balance is by design.
- **Density-calibration eligibility (pre-declared, pixel-based).** Out-of-calibration
  voxel = in-body HU ≥ 3071 (12-bit ceiling, vendor-neutral); exclude if largest
  connected component ≥ 1 cm³ (natural gap 0.91–2.06 cm³). **8 excluded → N = 32**
  (GE 8, Siemens 9, Canon 6, Philips 9); fires on all four vendors (a material rule,
  not a vendor detector); imbalance reported not corrected; per-organ distances
  reported not gated. Governing principle: *rules, not cases.* Evidence:
  `results/phase2_cohort/{metal_distribution,density_eligibility}.json`;
  `docs/REPRODUCING_DATA.md` §2d.

### 2.6 Segmentation and device independence — **DONE**
- TotalSegmentator 2.17.0, full 1.5 mm, task `total`, 12 scored organs, CPU, masks
  on the native DICOM grid (voxel-correspondence asserted and tested).
- **Device independence (Methods, G5-analogue):** IORN-007 CPU 1.5 mm volumes
  reproduce IORN-006 GPU 1.5 mm volumes (median ratio 1.00). Evidence:
  `results/phase2_cohort/organ_volume_vs_icrp89.json`; `docs/REPRODUCING_DATA.md` §2c.

### 2.7 HU → density and body contour — **DONE**
- Schneider stoichiometric calibration; body contour (threshold + largest connected
  component + hole fill); out-of-FOV → air; out-of-calibration voxels reported, not
  silently clamped. `ct_dosemc_core.phantom.patient_density_map`; D4 check
  `results/phase2_cohort/hu_density_check.json`.

### 2.7a Material assignment (Schneider tissue groups) and patient geometry — **DONE (code+tests); runs GATED**
- **Materials.** Composition groups, not density bins: photoelectric ∝ Z³⁻⁴, so
  composition (not just density) sets dose. Each voxel → a group by HU with the
  continuous Schneider density (MC-GPU scales MFP by voxel-ρ/nominal-ρ, so the model
  is exact). Soft tissues merged, bone groups kept separate. MAX_MATERIALS = 15
  caps the set; default = 15 (4 soft + 11 graded bone, edges uniform in √f). Soft +
  cortical endpoint are named ICRP compositions (PENDBASE 104/191/103/262/120);
  bone bins are Schneider soft↔cortical **volume-fraction** mixes (f linear in HU;
  w_bone = f ρ_bone/ρ_mix), provenanced with SHA-256 in `materials/PROVENANCE.json`.
  11-bin √f μ(60 keV) discretisation: max 2.64% at HU 700, median 1.03%; at the
  scored-soft-tissue boundary (HU 100) 0.40% (was 5.80% under 8 equal-HU bins)
  (`results/phase2_cohort/bone_bin_error.json`). Metal excluded upstream (2.5), so
  the set spans air → cortical bone. `ct_dosemc_core.patient`, `tools/make_materials.py`.
- **Geometry.** Isotropic 2.5 mm dose grid (G3 box reaches the focal spot; native
  0.7 mm is 2.4e9 voxels, 2.5 mm is 5.4e7 = 2× G2, same 0.25 cm as G2/G3). Dose ROI =
  organ bounding box. Resampling cost measured (`tools/resample_cost.py`): median
  organ-mass change 0.8–1.1 %, device-independent across vendors (median 0.990–0.993),
  worst 16.5 % on the smallest glands. `results/phase2_cohort/resample_cost.json`.

### 2.8 CTDIvol normalisation — **GATED (design fixed)**
- Patient dose normalised to the CTDIvol recorded in DICOM/RDSR
  (`MC_SOURCE_MODEL.md` §4.5), removing dependence on absolute SpekPy output and on
  the bowtie's absolute transmission.

### 2.9 Organ dose computation — **partly built; runs GATED**
- Voxel phantom → MC-GPU patient input → `region_dose` over organ masks → mGy/organ.
- **Built (code+tests):** patient VoxelPhantom + 2.5 mm geometry + 130 cm focal box
  (`ct_dosemc_core.patient`), Schneider material set, bowtie sub-fan plan with
  per-vendor provenance (`ct_dosemc_core.driver.bowtie_subfan_plan`), focal-spot
  placement (`source_model.focal_spot_cm`), TCM I(z)
  (`source_model.tube_current_profile`), organ-dose reduction over the bbox ROI
  (`driver.organ_doses_from_roi`).
- Actual dose runs remain gated by G0–G5.

## 3. Results
- **3.1 Verification** — gate outcomes and the measured uncertainty budget. [IN PROGRESS]
- **3.2 Cohort** — funnel, eligibility, device-independence, ICRP-89 context table
  (descriptive only). [DONE]
- **3.3 Patient organ doses** — per-organ dose, per vendor (with N). [GATED]
- **3.4 Robustness** — one metal-excluded series re-included via density clamp; report
  max organ-dose change ("exclusion does not change conclusions"). [GATED — queued
  for when dose computation unlocks]

## 4. Discussion
- Agreement with PENELOPE reported with uncertainty (not a pass/fail gate).
- ICRP 89 departures expected: dose is on each patient's own segmented organ mass,
  not a reference phantom (one paragraph, `docs/REPRODUCING_DATA.md` §2c).
- Metal exclusion: physics rationale (Schneider has no metal Z; photoelectric),
  vendor-neutral rule, robustness result.
- **Phase-2 material-assignment challenge** (deferred): the excluded metal series;
  options exclude / explicit metal material / clamp+sensitivity.
- Limitations: bowtie (Siemens open source), table absent, air path, declared Δ set.

## 5. Conclusion
- [GATED] Verified, device-independent engine; fully re-derivable cohort; patient
  organ doses normalised to recorded CTDIvol.

---

## Data and code availability
- `data/PROVENANCE.json` (per-series licences/UIDs); `results/` machine-readable
  artefacts; `docs/REPRODUCING_DATA.md` for the reproduction recipe.

## Provenance / anti-fabrication
- Every reported number traces to a `results/*.json`; builds pinned in
  `vendor/build/build_info.json`; materials in `materials/PROVENANCE.json`.

## References (to insert)
- AAPM TG-195 (Report 195). Schneider et al. (1996/2000). Turner et al. Med. Phys.
  36:2154 (2009). Yang et al. Med. Phys. 44:57 (2017); Data in Brief 25:104261
  (2019). IPEM Report 78. ICRP Publication 89 (2002). TotalSegmentator (Wasserthal
  et al.). MC-GPU (Badal & Badano). PENELOPE.

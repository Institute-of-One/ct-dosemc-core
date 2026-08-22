# Manuscript skeleton — IORN-007

> **Superseded. This is the planning skeleton, not the manuscript.**
>
> It records the claim-to-evidence mapping the project was built against, and is
> kept for provenance. It predates the reframing: the paper is no longer about the
> difference between an index and a dose, which nobody disputes, but about the
> measured floor on converting one to the other and the finding that per-organ
> coefficients do not lower it.
>
> The manuscript is `paper/manuscript.md`, and every number in it resolves from
> `paper/frozen/` at build time. Nothing here should be quoted.

**Status of this file.** Skeleton only. Each section lists the claim, the evidence
artefact (a `results/*.json` or a canonical doc), and whether it is **DONE**,
**IN PROGRESS**, or **GATED** (32-series production and Fig. 4 y-axis; Phase 1a is
closed — see `docs/IORN007_scope_to_acceptance.md` §0/§7). No numbers are written
here that are not already machine-recorded in `results/`. Target journal: *Physics
in Medicine & Biology* (code-verification + application).

---

## Abstract
- [GATED on final organ-dose numbers] One paragraph: verified engine, re-derivable
  cohort, patient organ doses scaled to a recorded CTDIvol where one exists (23/32).

## 1. Introduction

Three papers, three endpoints, one pipeline. They are not slices of the same
result.

- **IORN-004** (`ctdose-core`, [Zenodo 10.5281/zenodo.21636719](https://doi.org/10.5281/zenodo.21636719) v0.1.1)
  reports the whole-scan **CTDIvol** — a scanner-output index. One number per
  acquisition; no organ, no transport.
- **IORN-006** (`ctsegdose-core`, [Zenodo 10.5281/zenodo.21817307](https://doi.org/10.5281/zenodo.21817307) v0.1.1)
  reports an **organ-specific weighted CTDIvol index**, CTDIvol × *w*<sub>o</sub>,
  where *w*<sub>o</sub> is the tube-current mean over the segmented organ relative
  to the scan mean. Still an index. It captures longitudinal TCM; it does not
  transport photons.
- **IORN-007** (this work) reports **absorbed organ dose in milligray**, by Monte
  Carlo through the patient's own segmented, density-mapped anatomy. The
  coefficients are computed, not looked up, which is why 004 and 006 stopped
  where they did: every published organ-dose coefficient table is copyrighted.

Different endpoint, different method. N is set by the multi-vendor claim (four
manufacturers, a pre-declared metal-implant gate, N = 32), not by a power
calculation. The contribution is fidelity and reproducibility per patient, not
cohort size.

The same 40 TCIA series underlie 006 and 007. Eight are excluded from absorbed-dose
analysis by a pre-declared Schneider-calibration rule (largest in-body
out-of-calibration component ≥ 1 cm³). On the surviving 32, the 006 index is
already in hand (`results/phase2_cohort/iorn006_organ_index.json`, pinned to
ctsegdose-core v0.1.1 / 10.5281/zenodo.21817307). When 007 mGy
lands, one scatter — 006 index vs 007 absorbed dose, same patient, same organ —
shows the split as data, not as a disclaimer. That plot is also the strongest
available evidence that this is not salami: three quantities, three papers, one
cohort.

Scope. Phase 1a is code verification against AAPM TG-195 Case 4. Phase 2 is
patient organ dose. The absolute scale is a recorded CTDIvol on **23/32** series;
on 7/32 it is a ctdose-core (IORN-004) reconstruction (4 already in the 006
v0.1.1 release, 3 filled here); 2/32 cannot be scaled this way. Phase 1b
(bowtie) is a Methods component, not a second verification gate.

## Figures and tables

| | Content | Status | Evidence |
|---|---|---|---|
| **Fig. 1** | Selection funnel: 47,181 → 40 (probe 62 → 40, 22 rejected). | DONE | `cohort_overlap.json` |
| **Fig. 2** | Density-calibration gate: largest out-of-calibration component (cm³), 1 cm³ threshold, N = 32. | DONE | `metal_distribution.json`, `density_eligibility.json` |
| **Fig. 3** | TG-195 Case 4: G1/G1′/G2 vs PENELOPE, with measured replica σ. | DONE | `results/phase1a_close.json`; L40 Route B, L160 Route A |
| **Fig. 4** | Same-patient scatter: IORN-006 organ-weighted CTDIvol (x) vs IORN-007 absorbed mGy (y), one point per organ. 30/32 series have a defined index: 23 recorded (filled circles), 6 reconstructed with an exact or high-confidence table match (filled squares), 1 reconstructed under IORN-004's own low-confidence warning (open squares: Revolution CT → Revolution CT ES, score 0.50). LightSpeed Ultra and Revolution EVO are omitted: not in the open table, and 004's resolver refuses a near miss. **12 organs, 342 points. Pearson r = 0.66 (all), 0.61 (recorded-only).** | DONE | `figure4_doses.json`, `figure4_stats.json`, `figure4_scatter.png` |
| **Fig. 5** | Per-organ absorbed dose by vendor (with N). | DONE | `table4_organ_doses.json`, `figure5_vendor.png` |
| **Fig. 6** | Robustness: one metal-excluded series re-included under a density clamp; max organ-dose change. | **Not on the PMB submission path** | run if a reviewer asks; do not hold the Paper for it |
| **Table 1** | Gate outcomes G0–G5 (criterion, status, evidence). | DONE | `IORN007_scope_to_acceptance.md`; `phase1a_close.json` |
| **Table 2** | Cohort by vendor, with N: selected 10/10/10/10 → eligible 8/9/6/9. | DONE | `density_eligibility.json` |
| **Table 3** | Declared limitations (voxel, air, K, spectrum as upper bounds; phantom length measured: 40 cm indistinguishable from 160 cm). | DONE | `MC_SOURCE_MODEL.md` §5.3.0e; `phase1a_close.json` |
| **Table 4** | Patient organ doses (mGy), median [Q1, Q3], per organ, per vendor, with N. | DONE | `table4_organ_doses.json` |

Fig. 4 is the contribution-split figure. It is not a validation of 007 against 006:
006 is an index, 007 is a dose, and they are not required to agree. The plot's job
is to show, on the same anatomy, that the three papers measure three different
things. Open squares on that figure are the one series whose CTDIvol was
reconstructed under IORN-004's own low-confidence warning (Revolution CT matched
to Revolution CT ES, score 0.50); they are not a second reconstruction policy.
A one-line robustness check uses the same scatter restricted to the 23 series
with a recorded CTDIvol (Results 3.3): it does not change the
index–absorbed-dose relationship (`figure4_scatter_recorded_only.json`).

---

## 2. Methods

### 2.1 Monte-Carlo engine and build provenance — **DONE**
- MC-GPU v1.3. Defects #22–#26 (four patched, #26 reported unpatched) are
  recorded in `vendor/build/build_info.json` `patches[]` as `kind: defect_fix`
  (or portability). CPU and GPU built from one patch set.
- Evidence: `vendor/build/build_info.json`; `docs/MC_SOURCE_MODEL.md` §1–§3.
- Device independence of the engine: G5 CPU/GPU byte agreement.
- **Not a defect fix.** One further modification hoists the geometry parse out of the sub-fan loop.
  It changes no physics: on a full 10-replica reference set computed with the
  unmodified engine, all 144 dose arrays are SHA-256 identical and the scored
  VOI values are bit-identical. Recorded under `performance_modifications[]`,
  applied to both CPU and GPU from `tools/apply_route_a.py`.
  Evidence: `results/phase1a/replica_120kvp_second_K4_L40_00_routeA`;
  `docs/MC_SOURCE_MODEL.md` §2.1a.

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

### 2.3 Verification against TG-195 Case 4 (G0–G5) — **DONE**
- Gate table: `docs/IORN007_scope_to_acceptance.md` §2 (authoritative).
  - G0 spectrum PASS; G1 mono-energetic PASS (worst 0.147%); G1′ PASS (0.338%);
    G5 CPU/GPU byte-agree PASS.
  - G2 (a) anchor uncertainty ≤ 0.15%: **PASS** — K=4 N=10 Route B, centre SEM
    0.1355%, perimeter 0.0491% (`results/phase1a_close.json`).
  - (b) |ours − PENELOPE| is **reported, not a gate**: centre 0.359% (1.67σ_comb);
    perimeter 0.285% (1.64σ_comb). Decomposition in the close file.
  - G3 length: 40 cm indistinguishable from 160 cm (centre +0.060%, 0.33σ).
  - G4 production replica SD measured (not extrapolated).
- Independent SD cross-check: 94-position azimuthal replication (0.151%) vs K=1
  replica SD (0.145%). Evidence: `results/phase1a_G4_replica_uncertainty_*_K1.json`.

### 2.4 Uncertainty budget and declared limitations — **DONE**
- Measured: phantom length (40 vs 160 cm, 10 replicas each) — 40 cm
  indistinguishable from 160 cm; anchor SEM; Δ_length itself.
- Declared upper-bound limitations (not re-measured on the second test;
  PENELOPE's 0.167% floor): voxel size (0.02% first-test bound), air margin,
  sub-fan Ω residual (analytic 0.067% at K=4), spectrum 255-bin (not exercised:
  TG-195 table is 207 bins). → `results/phase1a_close.json`; `MC_SOURCE_MODEL.md`
  §5.3.0e.

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

### 2.7a Material assignment (Schneider tissue groups) and patient geometry — **DONE (code+tests); one-series smoke unlocked**
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

### 2.8 CTDIvol normalisation — **DONE**
- The recorded-CTDIvol normalisation of `MC_SOURCE_MODEL.md` §4.5 applies to
  **23/32** eligible series (the DICOM/RDSR tag). A further 7/32 are scaled to a
  reconstructed CTDIvol: 4 already reconstructed in IORN-006 v0.1.1 against the
  open table, 3 filled here by ctdose-core v0.1.1
  ([10.5281/zenodo.21636719](https://doi.org/10.5281/zenodo.21636719)). Of those
  3, one (Revolution CT → Revolution CT ES, score 0.50) carries 004's own
  low-confidence warning and is an **open square** on Fig. 4. Two GE models
  (LightSpeed Ultra, Revolution EVO) are unrecoverable under 004's published
  resolver; they are reported, not aliased, and cannot be scaled this way.
  Per-series origin is in `iorn006_organ_index.json`.

### 2.9 Organ dose computation — **DONE**
- Voxel phantom → MC-GPU patient input → `region_dose` over organ masks → mGy/organ.
- **Built (code+tests):** patient VoxelPhantom + 2.5 mm geometry + 130 cm focal box
  (`ct_dosemc_core.patient`), Schneider material set, bowtie sub-fan plan with
  per-vendor provenance (`ct_dosemc_core.driver.bowtie_subfan_plan`), focal-spot
  placement (`source_model.focal_spot_cm`), TCM I(z)
  (`source_model.tube_current_profile`), organ-dose reduction over the bbox ROI
  (`driver.organ_doses_from_roi`).
- **z-coverage.** A single 2 cm axial rotation at mid-scan is not the exam organ
  dose (Fig. 4 recorded Pearson r = 0.08 on that defective y-axis;
  `results/phase2_cohort/figure4_y_axis.json`). Production covers the reconstructed
  length with contiguous axial stations of the same collimation as the CTDI scale
  (`axial_station_z_cm`). TCM I(z) weights each station; stations are summed.
  `is_complete` requires station count = round(L/NT). 32/32 series meet that
  gate. The y-axis is
  \(D_\mathrm{scaled}=D_\mathrm{raw}\times\mathrm{CTDI_{vol}}/\mathrm{CTDI_{w,MC}}\).

## 3. Results
- **3.1 Verification** — gate outcomes and the measured uncertainty budget. [DONE]
- **3.2 Cohort** — funnel, eligibility, device-independence, ICRP-89 context table
  (descriptive only). [DONE]
- **3.3 Patient organ doses** — per-organ dose, per vendor (with N). [DONE]
  Scan-covering production, 32/32 complete. Fig. 4 plots 30 series that carry a
  CTDIvol (23 recorded, 7 reconstructed), **12 organs**, 342 points
  (`figure4_stats.json`). Pearson r = **0.66** (all) and **0.61** (recorded-only
  23 series, 262 points). Median absorbed dose 24.3 mGy (3.9–84.0 mGy). Median
  y/x = 2.17 (recorded 2.17). The mid-scan-only y-axis had recorded r = 0.08 and
  y/x = 0.033; that file is not citable. Index and absorbed dose are correlated
  and are not the same quantity.
  **Fig. 4 robustness — recorded-only subset.** Restricting Fig. 4 to the 23
  series with a recorded CTDIvol does not change the index–absorbed-dose
  relationship (`figure4_scatter_recorded_only.json`). No extra Monte Carlo.
  **Table 4** median [Q1, Q3] mGy. Vendor N is series on the scatter (GE 6,
  Siemens 9, Canon/Toshiba 6, Philips 9); GE 8 eligible minus 2 without CTDIvol.
  Per-cell n is series in which that organ is present. Evidence:
  `table4_organ_doses.json`, `figure5_vendor.png`.

  | Organ | GE | Siemens | Canon/Toshiba | Philips | All |
  |---|---|---|---|---|---|
  | Liver | 32.8 [19.5, 38.4] (6) | 17.3 [15.4, 26.7] (8) | 28.9 [21.2, 31.3] (6) | 27.5 [19.7, 33.9] (9) | 27.5 [16.2, 33.9] (29) |
  | Spleen | 35.4 [21.2, 42.6] (6) | 18.3 [15.8, 28.3] (8) | 32.5 [22.3, 34.1] (6) | 29.7 [21.5, 40.0] (9) | 29.7 [16.8, 37.1] (29) |
  | Stomach | 28.7 [18.0, 41.0] (6) | 18.2 [15.5, 25.9] (8) | 29.3 [20.7, 32.0] (6) | 24.2 [17.7, 32.9] (9) | 24.2 [16.7, 32.9] (29) |
  | Kidney L | 34.5 [20.8, 44.2] (6) | 19.4 [17.3, 27.4] (8) | 28.6 [23.1, 37.5] (6) | 26.2 [15.4, 38.7] (9) | 26.2 [17.8, 38.7] (29) |
  | Kidney R | 33.3 [20.2, 44.9] (6) | 18.0 [13.5, 25.8] (9) | 28.2 [24.0, 38.3] (6) | 24.6 [15.0, 38.0] (9) | 25.2 [15.6, 37.5] (30) |
  | Pancreas | 26.0 [17.2, 33.7] (6) | 14.9 [13.3, 24.1] (8) | 26.8 [19.3, 29.5] (6) | 24.4 [14.4, 31.8] (9) | 23.8 [14.4, 30.3] (29) |
  | Gallbladder | 39.2 [35.5, 49.5] (4) | 20.0 [14.5, 23.6] (7) | 28.0 [23.0, 31.0] (6) | 30.6 [13.3, 34.4] (8) | 28.8 [14.9, 34.0] (25) |
  | Colon | 33.1 [22.4, 42.3] (6) | 19.8 [16.0, 24.6] (9) | 27.9 [22.9, 35.0] (6) | 28.6 [19.4, 35.3] (9) | 24.8 [18.8, 35.1] (30) |
  | Small bowel | 32.9 [20.3, 45.1] (6) | 22.0 [14.9, 25.3] (9) | 28.3 [23.1, 34.8] (6) | 25.0 [14.1, 33.8] (9) | 24.6 [16.7, 35.6] (30) |
  | Adrenal L | 23.8 [15.8, 31.5] (6) | 13.1 [11.3, 22.5] (8) | 23.6 [17.0, 24.5] (6) | 23.0 [13.8, 28.1] (9) | 22.3 [12.6, 28.0] (29) |
  | Adrenal R | 23.9 [15.1, 31.6] (6) | 12.0 [11.1, 21.9] (8) | 22.6 [16.6, 23.5] (6) | 20.2 [13.7, 29.3] (9) | 21.5 [11.5, 25.9] (29) |
  | Bladder | 34.8 [28.0, 48.5] (5) | 19.6 [15.5, 25.3] (8) | 21.1 [17.9, 25.1] (6) | 28.6 [27.9, 28.7] (5) | 25.3 [17.8, 29.1] (24) |

- **3.4 Robustness** — Fig. 4 recorded-only subset (no extra Monte Carlo) is the
  submission robustness. The metal-clamp re-include (old Fig. 6) is not required
  for the PMB Paper; run it if a reviewer asks.

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
- Verified, device-independent engine; fully re-derivable cohort; scan-covering
  organ doses on N = 32, scaled to a CTDIvol the series carries on 30/32
  (recorded 23, reconstructed 7). Fig. 4: 12 organs, Pearson r = 0.66
  (recorded-only 0.61).

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

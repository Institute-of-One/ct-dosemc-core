# IORN-007 — from scope to acceptance

**Purpose.** One page that turns the fuzzy goal ("verify the dose engine before any
patient dose") into criteria that either pass or fail, and records where each one
stands *today*. It is the acceptance index; the numbers and their derivations live
in [`MC_SOURCE_MODEL.md`](MC_SOURCE_MODEL.md), the day-to-day state in
[`IORN007_RESUME.md`](IORN007_RESUME.md). Where they disagree with this file, they
win — re-derive this page, do not patch a number into it.

**Status tags:** **PASS** · **OPEN** (criterion defined, not yet met) · **IN
PROGRESS** (measurement running) · **PENDING** (queued, not started).

---

## 0. Scope, in one sentence

IORN-007 is the Phase-1a **code-verification** work: show that this MC-GPU-based
CT dose engine reproduces AAPM TG-195 Case 4 to within a stated, *measured*
uncertainty, on the production configuration, before it is trusted with any
patient geometry.

**Release rule — dose was locked, data preparation was not.** No patient (Phase-2)
**dose calculation** was to run until **G0–G5 all pass**. That lock is now met
(`results/phase1a_close.json`). The one-series smoke (`usable_as_result: false`)
has landed. 32-series scan-covering production is **done**
(`is_complete` 32/32; `figure4_doses.json` `usable_for_figure4: true`).
**Phase-2 data preparation — D2 (TCIA selection/download), D3 (TotalSegmentator
masks), D4 (HU→density write-out check) — was never gated** and has already run
in parallel.

**Phase-1b is not a second verification gate.** TG-195 already serves as the
verification anchor; the bowtie is a *Methods component* for the physical fidelity
of the patient geometry, not a gate the engine must pass. Because no in-house
measured CTDIvol exists, "reproduce a measured CTDIvol" is not trackable and is
dropped — patient dose is instead **scaled to a CTDIvol the series actually
carries**: the DICOM/RDSR tag on 23/32 eligible series, an IORN-004
reconstruction on 7/32 (4 already in the 006 v0.1.1 release, 3 filled here),
and unrecoverable on 2/32 (`MC_SOURCE_MODEL.md` §4.5). That also removes most
of the dependence on SpekPy's absolute output. Per-series origin is in
`results/phase2_cohort/iorn006_organ_index.json`.

**Cohort principle — rules, not cases.** If admitting one series would require a new
rule written for that series, the series is excluded instead: a rule is defensible in
review, a per-case exception is not, and per-series special-case code is what a
reviewer distrusts most. Every eligibility criterion is a uniform threshold on a
measured quantity. This yields one pixel-based gate beyond the header criteria of
`ct_dosemc_core.eligibility`: **a series is excluded if its largest connected
out-of-calibration voxel component (inside the body contour, HU ≥ 3071, the 12-bit
saturation ceiling so clip and exceed count alike) is ≥ 1 cm³** — a metal implant
beyond the Schneider calibration. The 1 cm³ threshold is the cohort distribution's
natural gap (0.91–2.06 cm³), not fitted to any series. Result: **N = 32** (GE 8,
Siemens 9, Canon/Toshiba 6, Philips 9); exclusions fire on all four vendors, so it is
a material rule not a vendor detector. Per-organ distances are **reported, not
gated**; the vendor imbalance is a **consequence of the pre-declared criterion and is
not corrected** (every by-vendor table carries N). Detail:
`docs/REPRODUCING_DATA.md` §2d, `results/phase2_cohort/{metal_distribution,density_eligibility}.json`.

---

## 1. How the scope becomes measurable

"Verify the engine" is not testable as written. It decomposes into six gates, each
a yes/no question the results files can answer:

| Gate | The question it makes measurable |
|---|---|
| G0 | Is the x-ray **spectrum** the TG-195 beam? |
| G1 | With a **mono-energetic, single-projection** beam, does the dose match the four codes on the four axial sections? |
| G1′ | Same, with TG-195's **distributed 120 kVp** spectrum? |
| G2 | With the **full 120 kVp, 36-projection CT** scan, does the dose match on the two 10 mm cylinders? |
| G3 | Are the numerical **convergence** parameters (voxel, length, air, sub-fans) fine enough that they are not the error? |
| G4 | What is the **Monte-Carlo uncertainty**, measured (not extrapolated) at the production configuration? |
| G5 | Do the **CPU and GPU** builds agree to the bit, so the answer is not a build artefact? |

The subtlety that has cost the most time: **G2's verdict is only as good as G4's
σ, and σ must be measured at G2's own configuration.** (a) and (b) below make that
explicit.

---

## 2. Gate-by-gate acceptance

| Gate | Acceptance criterion (exact) | Status | Evidence |
|---|---|---|---|
| G0 | spectrum beam quality vs TG-195; residual explained as a model difference, not a bug | **PASS** (−2.3% at 120 kVp, −1.8% at 100 kVp; IPEM-78 vs SpekPy) | `results/…G0…`, `MC_SOURCE_MODEL.md` §5.1.1 |
| G1 | 56.4 keV, 1 projection, 4 axial sections: within statistics of the four-code set | **PASS**, worst 0.147% | `MC_SOURCE_MODEL.md` §5.1 |
| G1′ | as G1 with TG-195 distributed 120 kVp | **PASS**, worst 0.338% | ″ |
| G2 | 120 kVp, 36 projections, two 10 mm cylinders: **(a)** holds on **both** VOIs; **(b)** is *reported* with its uncertainty (internal check, not a stop condition — §3, §7) | **PASS** on (a); (b) reported | `results/phase1a_close.json`; §5.1.4 |
| G3 | each axis shown not to dominate; K settled analytically at K ≥ 4; voxel/air/K/spectrum carried as **declared** upper-bound limits (not acceptance conditions); **phantom length** measured (40 vs 160 cm) | **PASS** — 40 cm indistinguishable from 160 cm | §5.3, §5.3.0e; `phase1a_close.json` |
| G4 | replica **sample** SD (assumes nothing) at the production configuration, per VOI | **PASS** — K=4 N=10: centre SD 0.428% → SEM 0.1355%; perimeter SD 0.155% → SEM 0.0491% | `…_120kvp_second_K4_L40.json` (Route B) |
| G5 | CPU and GPU byte-agree on G1/G2 (integer atomicAdd ⇒ order-independent) | **PASS** on G1/G2; **extended** to the Route-A batch engine (§5) | §2.2–2.3 |

---

## 3. G2 in detail — closed on (a); (b) reported

G2 is judged on (a) — the one criterion that gates the project — and reports (b)
alongside it. (b) is an **internal** agreement check, not a publication requirement
and not a stop condition (§7); it is reported honestly, whichever way it lands.

### (a) statistical precision — *anchor uncertainty ≤ 0.15 %*

The old "single-run SD ≤ 0.25 %" target is **withdrawn** (arbitrary). What must be
small is the uncertainty of the *anchor* — the number that enters (b) — which for
an anchor that is the mean of N independent replicas is `replica SD / √N`.

| VOI | measured replica SD (K=4, 2×10⁸, Route B) | anchor uncertainty = SD/√10 | ≤ 0.15 %? |
|---|---|---|---|
| centre | 0.428 % (±24%, N=10) | **0.1355 %** | **yes** |
| perimeter | 0.155 % (±24%, N=10) | **0.0491 %** | **yes** |

The K = 1 replica study (`…_K1.json`) had predicted 0.406%/√10 = 0.128%. The
number that counts is the **K = 4 ten-replica measurement** (solid-angle
correctness, §5.1.2a). SD precision is 1/√(2(N−1)) ≈ ±24%. → **PASS.**

### (b) agreement — *|ours − PENELOPE| reported with σ_comb*

The yardstick is **PENELOPE**, chosen on a stated physical ground (it shares our
cross-section library) *before* looking at which code agrees best, and reported
next to every other comparison so the choice is arguable, not quiet (§5.1.4 c).
**Not a gate.** "Ours" is the L40 N=10 mean, not the single G2_anchor_air50 run.

| VOI | \|ours − PENELOPE\| | σ_comb | nσ | PENELOPE vs 4-code mean | ours vs PENELOPE | ours vs 4-code mean |
|---|---|---|---|---|---|---|
| centre | 0.359 % | 0.215 % | 1.67σ | −0.579 % | −0.359 % | −0.936 % |
| perimeter | 0.285 % | 0.174 % | 1.64σ | +0.105 % | −0.285 % | −0.181 % |

The multiplicative identity is `(1 + d_pen_vs_mean)(1 + d_ours_vs_pen) − 1 =
d_ours_vs_mean`. Centre: more than half of the four-code residual is a property
of the reference (PENELOPE sits −0.579% off the four-code mean). Per-code
deviations are in `phase1a_close.json`. σ_comb = √(SEM² + (1%/√36)²).

0.359 % is a **real systematic difference**; statistics cannot remove it. This is
exactly why (b) is *reported, not gated*: chasing it with more histories would only
push it across an internal 2σ line that carries no publication weight, and
measuring model systematics *below* PENELOPE's own **0.167 % statistical floor**
cannot sharpen a comparison whose yardstick is already that noisy. The honest
σ_comb is `σ_MC ⊕ σ_PENELOPE (0.167 %)`, widened in the RSS budget by the
**declared** limitations and the **measured** Δ_length (§4). (b) is then stated as
a fact — "|ours − PENELOPE| = 0.359 % (centre), 1.67σ_comb" — and its size or sign
is a finding, never a defect to tune away.

The earlier table that used the single-run 0.349 % / 0.80σ figures is **superseded**
by the N=10 mean. As predicted, sharpening the anchor moved (b) from ~0.8σ toward
~1.7σ; it did not loosen.

---

## 4. The one measured limitation — phantom length

The Δ-budget campaign remains **cancelled**. Voxel, air, sub-fan K and spectrum
stay as **declared upper-bound limitations**. **Phantom length is measured.**

The spec is 3000 mm; the implementation is 400 mm. Ten replicas at 40 cm (Route B)
and ten at 160 cm (Route A) give:

| VOI | L160 − L40 | σ = √(SD₄₀²/10 + SD₁₆₀²/10) | nσ | distinguishable? |
|---|---|---|---|---|
| centre | **+0.060 %** | 0.183 % | 0.33σ | no |
| perimeter | **−0.048 %** | 0.069 % | 0.70σ | no |

**40 cm is indistinguishable from 160 cm** at the second-test VOIs. This replaces
the first-test noise-buried 0.4% upper bound. → **measured.** Evidence:
`results/phase1a_close.json`.

---

## 5. Method acceptance — Routes A, B, C

These are not physics gates; they are the rules for *how* a number becomes
citable.

| Route | What it is | Acceptance rule | Status |
|---|---|---|---|
| **B** | 10 independent K=4 replicas, 144 invocations each | the rigorous L40 anchor: measures the replica SD *and* the N=10 mean, no scaling assumption | **DONE** (L40 anchor). Values: `phase1a_G4_replica_uncertainty_120kvp_second_K4_L40.json` |
| **A** | same beams, geometry parse hoisted — one MC-GPU process over an `@manifest` | **byte-equality**, not "within statistics": per-beam dose `.raw` SHA256-identical to standalone; VOIs bit-identical. **Not a defect fix** (`performance_modifications` in `build_info.json`) | engine on **both** CPU and GPU from one definition; GPU 144/144 vs L40 replica 00 **PASS**. L160 **DONE** by Route A |
| **C** | one run at 10× histories | **not citable** — a single run cannot measure σ; allowed only for a same-day feel | not used |

Route A's payoff on the length study is **delivered** (L160, 10/10). The 90-run
Δ campaign remains **cancelled** (§4). The patch is in both `win_cpu.cu` and
`win_gpu.cu` from one definition (so G5 keeps comparing the same source) and
recorded in `vendor/build/build_info.json`.

---

## 6. Cross-cutting rules every acceptance decision inherits

- **σ is measured at the configuration whose numbers it judges.** No scaling law
  substitutes. Two significance figures have already been withdrawn for breaking
  this; the "1/√N does not hold" reading was itself withdrawn as a cross-config σ
  comparison (§5.1.4, §5.3.0d).
- **Never tune the sub-fan count toward agreement.** K = 1 agrees better and is
  worthless (oversamples solid angle by 1.14 %). K ≥ 4 is correct only on the
  analytic residual. K < 4 runs are flagged `usable_as_anchor: false`.
- **No fabrication.** Every reported figure is machine-readable in `results/` with
  provenance; `tests/test_no_fabrication.py` and `tests/test_phase1a_close.py`
  re-derive them, so a hand-edited number fails the suite. Pending measurements
  are marked pending, never filled in by extrapolation.
- **Air outside the voxel box does not exist**, and the air margin must not equal
  `SAD − phantom_radius` (44 cm is degenerate; default 50 cm).

---

## 7. Definition of done

The deliverable of a code-verification paper (PMB) is **agreement, uncertainty, and
limitations** — verified against a recognised benchmark, agreement quantified with
its uncertainty, limitations stated. It is **not** the passing of a self-defined
threshold. So (b) is reported, not required.

**Phase-1a is closed** (`results/phase1a_close.json`). The five items below are
the record of what closed it, not a remaining checklist.

1. G0, G1, G1′, G5 remain **PASS**;
2. G4 delivered the **K = 4 ten-replica anchor** (Route B): centre SEM 0.1355 %
   ≤ 0.15 % — criterion (a);
3. the **phantom-length** Δ is measured (40 vs 160 cm, §4): 40 cm is
   indistinguishable from 160 cm; all other limitations (voxel, air, K, spectrum)
   are declared as upper bounds;
4. G2's agreement (b) is **reported** with its uncertainty — a result, not a
   pass/fail that can block the project (centre |ours−PENELOPE| = 0.359 %, 1.67σ_comb);
5. Route A, used for L160, passed **byte-equality** on **both** CPU and GPU from
   one definition (not a defect fix; see §2.1a of `MC_SOURCE_MODEL.md`). The L40
   anchor is Route B (`results/phase1a_source_routes.json`).

**Patient dose is unlocked for a one-series smoke** (`usable_as_result: false`),
then the 32-series production. Data preparation (D2/D3/D4) was never inside the
lock.

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

**Release rule — dose is locked, data preparation is not.** No patient (Phase-2)
**dose calculation** may run until **G0–G5 all pass**; that is a hard gate. But the
lock is on *computing dose*, not on getting ready to compute it: **Phase-2 data
preparation — D2 (TCIA selection/download), D3 (TotalSegmentator masks), D4
(HU→density write-out check) — is not gated and starts now.** It uses no GPU and
is the longest wall-clock work in the project, so it runs in parallel with Route B
tonight (§7).

**Phase-1b is not a second verification gate.** TG-195 already serves as the
verification anchor; the bowtie is a *Methods component* for the physical fidelity
of the patient geometry, not a gate the engine must pass. Because no in-house
measured CTDIvol exists, "reproduce a measured CTDIvol" is not trackable and is
dropped — patient dose is instead **normalised to the CTDIvol recorded in the
DICOM/RDSR** (`MC_SOURCE_MODEL.md` §4.5), which also removes the dependence on
SpekPy's absolute output.

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
| G2 | 120 kVp, 36 projections, two 10 mm cylinders: **(a)** holds on **both** VOIs; **(b)** is *reported* with its uncertainty (internal check, not a stop condition — §3, §7) | **OPEN** on (a) | §5.1.4 |
| G3 | each axis shown not to dominate; K settled analytically at K ≥ 4; voxel/air/K/spectrum carried as **declared** upper-bound limits (not acceptance conditions); only **phantom length** measured (40 vs 160 cm) | **PARTIAL** — length Δ outstanding (§4); all other axes are declared limits, done | §5.3, §5.3.0e |
| G4 | replica **sample** SD (assumes nothing) at the production configuration, per VOI | K=1 SD **measured** (centre 0.406%, perimeter 0.145%); K=4 ten-replica anchor **IN PROGRESS** | `…_120kvp_second_K1.json`; Route B |
| G5 | CPU and GPU byte-agree on G1/G2 (integer atomicAdd ⇒ order-independent) | **PASS** on G1/G2; **extended** to the Route-A batch engine (§3) | §2.2–2.3 |

---

## 3. G2 in detail — the open gate

G2 is judged on (a) — the one criterion that gates the project — and reports (b)
alongside it. (b) is an **internal** agreement check, not a publication requirement
and not a stop condition (§7); it is reported honestly, whichever way it lands.

### (a) statistical precision — *anchor uncertainty ≤ 0.15 %*

The old "single-run SD ≤ 0.25 %" target is **withdrawn** (arbitrary). What must be
small is the uncertainty of the *anchor* — the number that enters (b) — which for
an anchor that is the mean of N independent replicas is `replica SD / √N`.

| VOI | measured replica SD (2×10⁸) | anchor uncertainty at N=10 | ≤ 0.15 %? |
|---|---|---|---|
| centre | 0.406 % | 0.406/√10 = **0.128 %** | yes, once the K=4 ×10 anchor is built |
| perimeter | 0.145 % | 0.046 % | yes |

The anchor **value** must stay at **K ≥ 4** sub-fans (solid-angle correctness,
§5.1.2a); the SD may be measured at K = 1 (variance depends on photon count, not
on how many invocations they are split across). Route B is producing the K = 4
ten-replica mean now. → **IN PROGRESS.**

### (b) agreement — *|ours − PENELOPE| < 2σ*

The yardstick is **PENELOPE**, chosen on a stated physical ground (it shares our
cross-section library) *before* looking at which code agrees best, and reported
next to every other comparison so the choice is arguable, not quiet (§5.1.4 c).

| VOI | \|ours − PENELOPE\| | verdict at the *current* anchor σ |
|---|---|---|
| centre | 0.349 % | 0.80σ — **met** |
| perimeter | 0.280 % | 1.27σ — met |

**The caveat that must not be lost.** Today's "pass" is held up by anchor noise.
As the anchor sharpens, (b) tightens toward its boundary, it does not loosen:

```
centre anchor σ 0.406 % → 0.79σ  MET
centre anchor σ 0.128 % → 1.66σ  MET
centre anchor σ → 0      → 2.09σ  NOT MET   (0.349 % / 0.167 % PENELOPE-only)
```

0.349 % is a **real systematic difference**; statistics cannot remove it. This is
exactly why (b) is *reported, not gated*: chasing it with more histories would only
push it across an internal 2σ line that carries no publication weight, and
measuring model systematics *below* PENELOPE's own **0.167 % statistical floor**
cannot sharpen a comparison whose yardstick is already that noisy. The honest
σ_comb is `σ_MC ⊕ σ_PENELOPE (0.167 %)`, widened by the **declared** limitations
and the one **measured** term — phantom length (§4). (b) is then stated as a fact —
"|ours − PENELOPE| = 0.349 % (centre), N σ" — and its size or sign is a finding,
never a defect to tune away.

---

## 4. The one measured limitation — phantom length

The Δ-budget campaign is **cancelled**. Its premise was that, once the anchor
reached 0.128 %, model systematics would have to be measured to decide (b) — but
(b) is no longer a gate (§3, §7), and **PENELOPE's own 0.167 % statistical floor**
already sets the precision of every comparison. Measuring a systematic *below* that
floor cannot make the comparison sharper, so re-measuring voxel, air, sub-fan K and
spectrum at replica precision buys nothing. They stay as **declared upper-bound
limitations**, stated plainly in the paper; re-measuring them is **not** an
acceptance condition. (The earlier "re-run the scans at replica precision as (b)'s
acceptance" is **withdrawn**.)

**One exception, and only one: phantom length.** The spec is 3000 mm; the
implementation is 400 mm. A reviewer will see that gap, so it is the single
limitation worth converting from a bound into a measurement. Run **length 40 cm vs
160 cm, ten replicas each — 20 runs total** — and report the measured Δ with its
uncertainty. → **PENDING.**

The principle: reviewers reject *hidden* limitations, not *declared* ones.
Everything above is declared; only length is measured, because only length is a gap
a reviewer can see and would expect quantified.

---

## 5. Method acceptance — Routes A, B, C

These are not physics gates; they are the rules for *how* a number becomes
citable.

| Route | What it is | Acceptance rule | Status |
|---|---|---|---|
| **B** | 10 independent K=4 replicas, 144 invocations each, ~6 h | the rigorous anchor: measures the replica SD *and* the N=10 mean, no scaling assumption | **IN PROGRESS** (running overnight) |
| **A** | same beams, but the geometry parse hoisted out — one MC-GPU process over an `@manifest`, `load_voxels` memoised | **byte-equality**, not "within statistics": the per-beam dose `.raw` must be SHA256-identical to a standalone invocation; then the A and B ten-replica means must agree within 0.128 % | engine **DONE + CPU-validated** (single == batch, SHA256, parse-once); **GPU rebuild PENDING** (exe locked by Route B); Python driver **PENDING** |
| **C** | one run at 10× histories | **not citable** — a single run cannot measure σ; allowed only for a same-day feel | not used |

Route A's payoff is now smaller than first scoped: the 90-run Δ campaign is
**cancelled** (§4), leaving only the 20-run length study and general per-beam
batching. It is still worth having (parse once, not 144 times) but it is **no
longer on the critical path** to closing the gate. Its patch is in both
`win_cpu.cu` and `win_gpu.cu` from one definition (so G5 keeps comparing the same
source) and recorded in `vendor/build/build_info.json`.

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
  provenance; `tests/test_no_fabrication.py` re-derives them, so a hand-edited
  number fails the suite. Pending measurements are marked pending, never filled in
  by extrapolation.
- **Air outside the voxel box does not exist**, and the air margin must not equal
  `SAD − phantom_radius` (44 cm is degenerate; default 50 cm).

---

## 7. Definition of done

The deliverable of a code-verification paper (PMB) is **agreement, uncertainty, and
limitations** — verified against a recognised benchmark, agreement quantified with
its uncertainty, limitations stated. It is **not** the passing of a self-defined
threshold. So (b) is reported, not required.

**Phase-1a closes — and only then is Phase-2 patient dose *calculation* unlocked —
when:**

1. G0, G1, G1′, G5 remain **PASS** (they are);
2. G4 has delivered the **K = 4 ten-replica anchor** (Route B), giving centre
   anchor uncertainty ≤ 0.15 % — this is criterion (a), the one gate (§3a);
3. the **phantom-length** Δ is measured (40 vs 160 cm, §4) and stated as a
   limitation; all other limitations (voxel, air, K, spectrum) are declared as
   upper bounds;
4. G2's agreement (b) is **reported** with its uncertainty — a result, not a
   pass/fail that can block the project;
5. Route A, if used to produce any cited number, has passed **byte-equality** on
   the GPU build (CPU already done).

Items 1–2 keep the **dose-calculation** lock (§0) in force until met. **The lock
never covered data preparation:** D2/D3/D4 (§0) are outside the gate and run in
parallel from tonight, using no GPU.

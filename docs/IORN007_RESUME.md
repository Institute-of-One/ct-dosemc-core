# IORN-007 — resume here

**Written:** 2026-08-14 · **Phase 1a closed.** Evidence:
[`results/phase1a_close.json`](../results/phase1a_close.json) (re-derived by
`tests/test_phase1a_close.py`). The authoritative technical record is
[`MC_SOURCE_MODEL.md`](MC_SOURCE_MODEL.md) — this file is the index into it.

---

## 1. One-line status

**32/32 scan-covering production is complete.** Fig. 4 is usable
(`figure4_stats.json`: 12 organs, r = 0.66 / recorded 0.61). Results 3.3,
Table 4, and Fig. 5 are filled from those files. Send
`docs/PMB_PRESUBMISSION.md` (Paper, not Note). Do not first-submit Medical
Physics.

Remaining PMB path:

1. Send the PMB inquiry. Submit the Paper after the Board confirms article type.
2. Do not fill tables from `figure4_y_axis.json` (mid-scan defect).

**Not on the submission path** (do after accept, or if a reviewer asks):
Fig. 6 metal-clamp re-include, launcher polish, extra engine work, Phase 1b as
a second gate, SpekPy absolute mAs as the patient scale.

| Gate | What | State |
|---|---|---|
| G0 | spectrum beam quality vs TG-195 | **PASS** (−2.3% 120 kVp, −1.8% 100 kVp; model difference, IPEM-78 vs SpekPy) |
| G1 | 56.4 keV, single projection, 4 axial sections | **PASS**, worst 0.147% |
| G1′ | as G1 with TG-195's distributed 120 kVp spectrum | **PASS**, worst 0.338% |
| G2 | 120 kVp, 36 projections, two 10 mm cylinders | **PASS on (a)**; (b) **reported** — see §2 |
| G3 | convergence (voxel, length, air, sub-fans) | **PASS** — length measured; other axes declared limits |
| G4 | replica uncertainty at the production configuration | **PASS** — K=4, N=10, L40 Route B |
| G5 | CPU/GPU agreement | **PASS** on G1/G2; Route A byte-equality |

---

## 2. What closed, and the next command

The close file is `results/phase1a_close.json`. It is not a typed-in verdict:
`tools/close_phase1a.py` recomputes every figure from the L40/L160 replica JSON
and the TG-195 per-code values stored beside G2.

**(a)** L40 K=4 replica SD / √10: centre **0.1355%** (SD 0.428%, ±24% on the SD
itself), perimeter **0.0491%** (SD 0.155%). Both ≤ 0.15%. The K=1 prediction
was 0.406%/√10 = 0.128%; the K=4 measurement is the number that counts.

**(b)** |ours − PENELOPE| using the N=10 mean, **reported, not gated.** Centre
0.359% (1.67 σ_comb); perimeter 0.285% (1.64 σ_comb). Decomposition (centre):
PENELOPE vs four-code mean **−0.579%**, ours vs PENELOPE **−0.359%**, product
= ours vs mean **−0.936%**. Yardstick chosen before looking at which code agrees
best (shared PENDBASE cross-sections).

**Δ_length.** L160 − L40: centre **+0.060%** (0.33σ), perimeter **−0.048%**
(0.70σ). **40 cm is indistinguishable from 160 cm.** This replaces the first-test
noise-buried 0.4% upper bound. L40 is Route B; L160 is Route A
(`results/phase1a_source_routes.json`).

**Budget RSS** (measured vs declared, listed in the close file): centre
σ_total **0.234%**, |ours−PENELOPE|/σ_total **1.54**; perimeter 0.193% / 1.47.
Voxel 2.5 mm is a first-test upper bound (0.02%); the second test did not
re-measure it. Spectrum 255-bin is not exercised (TG-195 table is 207 bins).

The one-series smoke has landed:
`results/phase2_patient/phase1a_close_smoke/organ_doses.json` (`usable_as_result:
false`). Geometry write → MC-GPU → dose ROI readback → organ reduction. The first
attempt died on `MAX_SHELLS=30` (Schneider bone mixes emit up to 32 Compton
shells); the GPU and CPU engines were rebuilt with a copied header at 40. That is
a capacity bound, not a physics change, and is after Phase 1a close.

**Next — 32-series production** at the G2 configuration (36 projections, K=4,
2×10⁸ histories, Route A, `usable_as_result: true`). Resume-safe: finished
series are skipped. Standalone window:

```powershell
cd d:\DevGit\ct_dosemc_core
powershell.exe -NoExit -ExecutionPolicy Bypass -File tools\watch_phase2_prod.ps1
```

The watchdog waits while MC-GPU / `run_patient.py` / `run_cohort.py` are alive,
then calls `run_phase2_prod.ps1`. Log: `results/phase2_patient/watchdog.log`
and `cohort.log`. Do not start a second GPU job beside a live engine. After
32/32 the watchdog runs `collect_figure4_doses.py` → `figure4_scatter.py`.
The smoke command below is already done; do not reuse it as production.

**2026-08-17 — 140 kVp still open.** 5–150 keV tables exist, but MC-GPU
`MAX_ENERGYBINS_RAYLEIGH=25005` rejects 29002 bins. Capacity bump to 32000
(array size only, same 5 eV grid; do not coarsen the spectrum). Rebuild GPU,
then re-run that one series. 31/32 results are intact.

`-u` / `PYTHONUNBUFFERED=1` is required when stdout is redirected. Route A is a
**performance** modification, not a sixth defect (`performance_modifications` in
`build_info.json`). The L40 anchor remains Route B.

---

## 3. Rules learned the hard way — do not relearn them

**σ must be measured at the configuration whose numbers it judges.** Two
significance figures have already been withdrawn for applying an uncertainty from
one run to a value from another. No scaling law substitutes for measurement. This
is the single most repeated mistake in this project so far.

**Never tune the sub-fan count towards better agreement.** K = 1 agrees with the
reference better and it is worthless — it oversamples the solid angle by 1.14%.
K ≥ 4 is correct on the analytic solid-angle residual, and *only* on that.
Runs with K < 4 are flagged `usable_as_anchor: false` in their results file.

**The air margin must not equal `SAD − phantom_radius`.** At 44 cm the source sits
exactly on the voxel-box face, a branch ambiguity in `move_to_bbox`. Default is
now 50 cm. Rule: contain the whole air path *and* keep the source strictly inside.

**Air outside the voxel box does not exist.** MC-GPU carries photons from the
focal spot to the box without interaction. This applies to patient geometry too,
and is a Phase-2 design constraint, not a TG-195 quirk.

**Partial-volume weights only where a region floats inside a uniform medium.** The
TG-195 second-test VOIs and the CTDI chambers: yes. The first test's axial
sections: no — their edge *is* the phantom edge. Segmentation masks: never, a mask
*is* the organ definition.

**Compare per-code, not only against the four-code mean.** The mean spans four
different cross-section libraries; ours is PENELOPE's. See §5.1.2a.

---

## 4. Environment — all of this survives a reboot

Nothing below needs redoing unless the machine is rebuilt.

| Thing | Where | Note |
|---|---|---|
| venv | `.venv` (Python 3.12) | spekpy, numpy, scipy, pydicom, pytest, ruff, openpyxl, pypdf |
| CPU engine | `vendor/build/MC-GPU_v1.3_CPU.exe` | MSVC, 5 patches applied to a *copy* |
| GPU engine | `vendor/build/MC-GPU_v1.3_GPU.exe` | CUDA 12.9.86, `sm_86`; `cudart64_12.dll` sits beside it |
| CUDA | `vendor/cuda-12.9/` | assembled from `D:\DevGit\ExposureRendererRelease20200331\_cudaenv` — **no admin install was needed** |
| cuda-samples | `vendor/cuda-samples/` | tag `v12.9`, matching the toolkit |
| MC-GPU source | `vendor/MCGPU/` | byte-identical to upstream; patches live in `vendor/build/` |
| materials | `materials/*.mcgpu.gz` | gitignored; `tools/make_materials.py` regenerates, SHA-256 in `PROVENANCE.json` |
| TG-195 data | `data/tg195/` | **copyrighted, never committed**; `tools/fetch_tg195.py` re-fetches |

Rebuild commands, if ever needed:

```powershell
powershell -File tools\build_mcgpu.ps1 -Target cpu
powershell -File tools\build_mcgpu.ps1 -Target gpu `
    -CudaPath   d:\DevGit\ct_dosemc_core\vendor\cuda-12.9 `
    -CudaSamples d:\DevGit\ct_dosemc_core\vendor\cuda-samples
.venv\Scripts\python.exe tools\fetch_tg195.py
.venv\Scripts\python.exe tools\make_materials.py
.venv\Scripts\python.exe -m pytest -q
```

**Known performance wall — and why it no longer bites the §2 command.** The wall
was the 48M-line ASCII geometry parse, paid *once per engine invocation*. It
dominated only because G2 at K = 4 sub-fans × 36 projections drove the rotation
externally and paid the parse 144 times (67 min on GPU vs ~26 on CPU at a smaller
geometry). At **`--sub-fans 1` the projection loop stays inside MC-GPU** — one
centred fan aims at the axis, so `drive_projections_here` is false
(`tools/run_tg195.py`) and the engine's native CT trajectory carries all 36
projections in a *single* invocation. A replica is therefore one parse, not 144,
and the cost is now the transport of its full history count, not the parse.

The earlier "remaining lever is 5 mm voxels" is **withdrawn**: it only ever
mattered against the per-invocation parse, which `--sub-fans 1` already removes,
and shrinking the voxels would change the physics comparison on the second test's
small VOIs (an effect measured only on the first test, ≤0.12%). Do not touch voxel
size to buy speed.

The "several hours" this file quoted for the §2 command is **also suspect** and
should be re-measured, not repeated. One invocation at the production geometry
(voxel 0.25, air-margin 50, ~5.8×10⁷ voxels) initialises in ~15 s (MC-GPU log,
`-- INITIALIZATION finished`) and the engine self-reports ~7×10⁷ histories/s on
the RTX 3080. At those rates 10 replicas × 2×10⁸ histories is minutes, not hours;
the old figure came from the 144-invocation regime that `--sub-fans 1` retires.
The `--replicas 2` smoke run records its own wall time in each
`replica_result.json`, so believe that, not this paragraph.

**A trap the smoke run found:** MC-GPU reads the histories-per-projection field as
a *time in seconds* when it is below 95000 (`MC-GPU_v1.3.cu:654`). At
`--sub-fans 1 --projections 36`, `--histories` below 3.6×10⁶ crosses that line and
the engine silently runs by time instead of by count. `run_sub_fan_set` now
refuses it. The production `--histories 2×10⁸` (5.6×10⁶ per projection) is well
clear.

---

## 5. What is gated, and what is not

**The gate locked *dose calculation*, not preparation for it.** That lock is now
released: G0–G5 are closed on (a). The one-series smoke (`usable_as_result:
false`) has landed. The GPU is now on the 32-series production (G2 configuration,
Route A). (Authoritative scope:
[`IORN007_scope_to_acceptance.md`](IORN007_scope_to_acceptance.md) §0/§7.)

**Not gated — data preparation (already running in parallel):**

1. **Task D data preparation.** `ct_dosemc_core/eligibility.py` and its 13 tests
   are written (criterion re-derived for absorbed dose, not inherited from
   IORN-006). The remaining work is data-only, uses **no GPU**, and is the longest
   wall-clock task in the project, so it does not conflict with Route B on the GPU
   and must not wait behind it:
   * **D2** — TCIA selection/download (network + CPU),
   * **D3** — TotalSegmentator masks (CPU),
   * **D4** — HU→density write-out verification.

**Unlocked — after G0–G5 close:**

2. **Phase 2 cohort dose** — smoke done. 32-series production is the current
   GPU job (`tools/run_phase2_prod.ps1`).

**Downgraded — no longer a verification gate:**

3. **Phase 1b is a Methods component, not a second gate.** TG-195 already serves as
   the verification anchor; the bowtie (per-sub-fan spectra, §5.2 — the machinery
   exists), filtration to a measured HVL, and PMMA→air-kerma are needed for the
   *physical fidelity of the patient geometry*, not to pass verification. Because no
   in-house measured CTDIvol exists, the old "reproduce a measured CTDIvol" goal is
   dropped: patient dose is **scaled to a CTDIvol the series actually carries** —
   recorded in the DICOM/RDSR on 23/32 eligible series, reconstructed via
   ctdose-core (IORN-004) on 7/32, unrecoverable on 2/32
   (`MC_SOURCE_MODEL.md` §4.5). That also removes the dependence on SpekPy's
   absolute output. It may run in parallel with Phase 2, not before it.

---

## 6. Upstream

Five defects found in MC-GPU v1.3, all reported:
[#22](https://github.com/DIDSR/MCGPU/issues/22) `abs()` on a `double` ·
[#23](https://github.com/DIDSR/MCGPU/issues/23) CPU PRNG not advanced ·
[#24](https://github.com/DIDSR/MCGPU/issues/24) binary files in text mode ·
[#25](https://github.com/DIDSR/MCGPU/issues/25) aperture order ·
[#26](https://github.com/DIDSR/MCGPU/issues/26) sub-cutoff energy discarded.

Four are patched on a copy; #26 is not, because its effect here is ≤0.012% and
patching for no measurable benefit is its own kind of unfaithfulness. No replies
yet — worth checking, and they belong in the paper's Data Availability statement.

---

## 7. Where the numbers live

`results/` holds every reported figure, machine-readable, with per-value
provenance. `tests/test_no_fabrication.py` re-derives the quoted figures from the
recorded inputs, so a hand-edited number fails the suite.

The G2 production anchor is `results/phase1a_G4_replica_uncertainty_120kvp_second_K4_L40.json`
(air 50 cm, K = 4, N = 10, Route B). The close arithmetic is
`results/phase1a_close.json`. The 44 cm run (`results/phase1a/G2_gpu_air44/`) is
the degenerate-margin diagnostic, not the anchor.

# IORN-007 — resume here

**Written:** 2026-08-10 · **HEAD at time of writing:** `e26d27e` · **Tests:** 134 passing

Read this first after a reboot. It is the state of play, the one thing that is
blocking, and the traps that have already cost time.

The authoritative technical record is [`MC_SOURCE_MODEL.md`](MC_SOURCE_MODEL.md) —
this file is the index into it, not a replacement.

---

## 1. One-line status

**Phase 1a (code verification against AAPM TG-195 Case 4) is open on exactly one
unmeasured quantity.** Everything else in the phase passes. No patient dose has
been computed and none may be until the gate closes.

| Gate | What | State |
|---|---|---|
| G0 | spectrum beam quality vs TG-195 | pass (−2.3% 120 kVp, −1.8% 100 kVp; model difference, IPEM-78 vs SpekPy) |
| G1 | 56.4 keV, single projection, 4 axial sections | **pass**, worst 0.147% |
| G1′ | as G1 with TG-195's distributed 120 kVp spectrum | **pass**, worst 0.338% |
| G2 | 120 kVp, 36 projections, two 10 mm cylinders | **open** — see §2 |
| G3 | convergence (voxel, length, air, sub-fans) | done; K axis closed analytically |
| G4 | replica uncertainty | done for first test; **second test at production statistics is the blocker** |
| G5 | CPU/GPU agreement | **pass** on both G1 and G2 |

---

## 2. The one thing blocking, and its exact command

The **K = 1 replica SD at the production configuration is now measured** — centre
0.406%, perimeter 0.145% at 2×10⁸ histories, air 50 cm
(`results/phase1a_G4_replica_uncertainty_120kvp_second_K1.json`, §5.1.4). That
retired the old 5×10⁷→2×10⁸ extrapolation and confirmed the air-margin scatter was
ordinary run-to-run noise, not a geometry artefact (§5.3.0d).

What blocks now is the **anchor**: criterion (a) is no longer a single-run SD
bound (the 0.25% target is withdrawn) but *anchor uncertainty = replica SD/√N ≤
0.15%*, and the anchor value must stay at K ≥ 4 for the solid-angle correctness of
§5.1.2a. So the outstanding measurement is a **K = 4 ten-replica anchor** whose
mean has centre uncertainty 0.406%/√10 = 0.128%. This is **Route B** — the K = 4
sub-fan decomposition forces 144 engine invocations per replica (the projection
loop cannot move inside MC-GPU for off-axis sub-fans, §5.3.0c / §5.3.0e), so at
~15 s parse per invocation a replica is ~36 min and the ten-replica anchor is ~6 h.

```powershell
cd d:\DevGit\ct_dosemc_core
powercfg /change standby-timeout-ac 0   # do not sleep mid-run
$env:PYTHONUNBUFFERED = "1"
.venv\Scripts\python.exe -u tools\run_tg195.py --gate G2 --beam 120kvp --test second `
    --replicas 10 --projections 36 --sub-fans 4 --histories 2e8 `
    --voxel-size 0.25 --phantom-length 40 --air-margin 50 --air-margin-z 6 `
    --executable vendor\build\MC-GPU_v1.3_GPU.exe >> results\phase1a\routeB_K4.log 2>&1
```

`-u` / `PYTHONUNBUFFERED=1` is required when stdout is redirected: a fully-buffered
log stays empty until the process dies, which is how a stall at replica 4/10 went
unnoticed for hours. With line buffering a dead replica is visible immediately.

Run it in a shell that survives — the harness's background tasks do not outlive a
session. Each replica is written to
`results/phase1a/replica_120kvp_second_K4_L{length}_XX/replica_result.json` as it
completes and reused on a re-run, so an interrupted job resumes without
recomputing finished replicas. The length is in the tag because the 40 cm K=4
anchor and the 160 cm length arm must not clobber each other.

* Output: `results/phase1a_G4_replica_uncertainty_120kvp_second_K4_L40.json` (the
  filename carries `K{sub_fans}_L{length}` so the K = 1 SD run, the K = 4 40 cm
  anchor, and the K = 4 160 cm length arm do not clobber each other).
* **Route A** is an engine change: loop over the K sub-fan aperture sets *inside
  one MC-GPU process* so the geometry is parsed once. Its acceptance is
  byte-equality (single == `@manifest` batch, already shown on CPU); the GPU
  rebuild waits for Route B to release the `.exe`. Its remaining payoff is now the
  20-run phantom-length study (§5.3.0e), not the withdrawn ~90-run Δ campaign, so
  it is **off the critical path** to closing the gate.
* The single-run 2×10⁹ shortcut (Route C) is **not** used: a single run cannot
  measure σ, so its number is not citable; only run it for a same-day feel.

**When Route B lands:** the anchor uncertainty row of §5.1.4 becomes measured, and
criterion (a) is met. Criterion (b) (|ours − PENELOPE|) is **reported, not gated**
(`IORN007_scope_to_acceptance.md` §3/§7): it cannot be sharpened below PENELOPE's
own 0.167% floor, so the only model term still re-measured is **phantom length**
(40 vs 160 cm); voxel, air, K and spectrum are carried as **declared** upper-bound
limitations (§5.3.0e). The earlier "(b) depends on a re-measured Δ budget" is
withdrawn.

The 40 cm arm of the length study **is** Route B once tags include `L40`. After
B finishes, only the 160 cm arm is new (same production config, `--phantom-length 160`,
10 replicas). Then Phase 1a closes. Then **one** patient path-through, not the 40:

```powershell
$env:PYTHONUNBUFFERED = "1"
.venv\Scripts\python.exe -u tools\run_tg195.py --gate G2 --beam 120kvp --test second `
    --replicas 10 --projections 36 --sub-fans 4 --histories 2e8 `
    --voxel-size 0.25 --phantom-length 160 --air-margin 50 --air-margin-z 6 `
    --executable vendor\build\MC-GPU_v1.3_GPU.exe >> results\phase1a\routeB_K4_L160.log 2>&1

# after that, one series (GPU). Plan-only (no GPU) already passed:
#   python -u tools/run_patient.py --plan-only
.venv\Scripts\python.exe -u tools\run_patient.py --run --histories 3.2e6 --projections 8
```

Do not start `--run` while Route B still owns the GPU. Forty-series production
is after this one-series smoke.

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

**The gate locks *dose calculation*, not preparation for it.** Only the Phase-2
cohort **dose** waits on G0–G5. Everything that does not compute dose can and
should run now — see the split below. (Authoritative scope:
[`IORN007_scope_to_acceptance.md`](IORN007_scope_to_acceptance.md) §0/§7.)

**Not gated — start in parallel now:**

1. **Task D data preparation.** `ct_dosemc_core/eligibility.py` and its 13 tests
   are written (criterion re-derived for absorbed dose, not inherited from
   IORN-006). The remaining work is data-only, uses **no GPU**, and is the longest
   wall-clock task in the project, so it does not conflict with Route B on the GPU
   and must not wait behind it:
   * **D2** — TCIA selection/download (network + CPU),
   * **D3** — TotalSegmentator masks (CPU),
   * **D4** — HU→density write-out verification.

**Gated — after G0–G5 close:**

2. **Phase 2 cohort dose** — the actual dose computation, released only by G0–G5.

**Downgraded — no longer a verification gate:**

3. **Phase 1b is a Methods component, not a second gate.** TG-195 already serves as
   the verification anchor; the bowtie (per-sub-fan spectra, §5.2 — the machinery
   exists), filtration to a measured HVL, and PMMA→air-kerma are needed for the
   *physical fidelity of the patient geometry*, not to pass verification. Because no
   in-house measured CTDIvol exists, the old "reproduce a measured CTDIvol" goal is
   dropped: patient dose is **normalised to the CTDIvol recorded in the DICOM/RDSR**
   (`MC_SOURCE_MODEL.md` §4.5), which also removes the dependence on SpekPy's
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

The G2 anchor currently on disk (`results/phase1a/G2_gpu_air44/`) was computed at
the **44 cm** margin now known to be degenerate. It should be re-taken at 50 cm
once §2 has established what its uncertainty actually is — in that order, not
before.

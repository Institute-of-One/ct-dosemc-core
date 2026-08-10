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

The centre VOI's **replica standard deviation at the production configuration**
has never been measured. It has only been measured at 5×10⁷ histories (0.484%)
and then extrapolated by 1/√N, and an air-margin scan showed run-to-run scatter
about **three times** what that extrapolation predicted.

Consequently the significance of G2's centre deviation (−0.7…−0.9% against
PENELOPE) is **unknown** — not large, not small. Criterion (b) has no denominator.

```powershell
cd d:\DevGit\ct_dosemc_core
.venv\Scripts\python.exe tools\run_tg195.py --gate G2 --beam 120kvp --test second `
    --replicas 10 --projections 36 --sub-fans 1 --histories 2e8 `
    --voxel-size 0.25 --phantom-length 40 --air-margin 50 --air-margin-z 6 `
    --executable vendor\build\MC-GPU_v1.3_GPU.exe
```

Several hours. Run it in a shell that survives — a previous attempt to detach it
did not, and the harness's background tasks do not outlive a session.

* `--sub-fans 1` is deliberate: the variance depends on the photon count, not on
  how many invocations they are split across, so one invocation per replica
  measures the same SD at 1/144 of the cost.
* The **value** it produces is not an anchor (§5.3.3 of `MC_SOURCE_MODEL.md`).
  Only its scatter is used.
* Output: `results/phase1a_G4_replica_uncertainty_120kvp_second.json`.

**When it lands:** fill the `(a)` row of `MC_SOURCE_MODEL.md` §5.1.4, then and
only then evaluate `(b)` = `|ours − PENELOPE| < 2σ`.

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

**Known performance wall:** with 144 invocations per G2, the 48M-line ASCII
geometry parse dominates and the GPU does not help it (G2 took 67 min on GPU
against ~26 on CPU at a smaller geometry). The remaining lever is 5 mm voxels,
~8× fewer lines, measured effect ≤0.12% on the first test — **but not yet measured
on the second test's small VOIs**, so do not adopt it silently.

---

## 5. After the gate closes

In order. None of it may start before §2 lands.

1. **Phase 1b** — bowtie via per-sub-fan spectra (§5.2, the machinery already
   exists), filtration to a measured HVL, PMMA→air-kerma from NIST, then the
   measured-CTDIvol comparison.
2. **Task D** — Phase-2 data. `ct_dosemc_core/eligibility.py` and its 13 tests are
   written (criterion re-derived for absorbed dose, not inherited from IORN-006).
   Untouched: D2 TCIA selection/download, D3 TotalSegmentator masks, D4 HU→density
   write-out verification.
3. **Phase 2** cohort dose — released only by G0–G5.

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

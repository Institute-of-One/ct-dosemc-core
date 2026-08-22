# Defects found in MC-GPU v1.3, for reporting to DIDSR/MCGPU

Five defects were found in the vendored engine while building the Phase-1
validation. **Three of them produce wrong results silently** — the simulation
runs to completion and reports plausible-looking numbers.

They are patched on a *copy* of the source, so `vendor/MCGPU` stays byte-identical
to upstream and every substitution is recorded in `vendor/build/build_info.json`.
See `docs/MC_SOURCE_MODEL.md` §2.1.

A later **performance** change (`@manifest` / Route A) hoists the geometry parse
out of the sub-fan loop. It is **not** a sixth defect: it changes no physics
(byte-equality vs the unmodified engine; `docs/MC_SOURCE_MODEL.md` §2.1a) and is
recorded separately in `build_info.json` under `performance_modifications`.

> **Status: filed 2026-08-08.**
>
> | # | Defect | Upstream issue |
> |---|---|---|
> | 1 | `abs()` on a `double` collapses sub-1° apertures | [DIDSR/MCGPU#22](https://github.com/DIDSR/MCGPU/issues/22) |
> | 2 | CPU branch reuses one PRNG sequence per projection | [DIDSR/MCGPU#23](https://github.com/DIDSR/MCGPU/issues/23) |
> | 3 | Binary outputs opened in text mode | [DIDSR/MCGPU#24](https://github.com/DIDSR/MCGPU/issues/24) |
> | 4 | Aperture line documented in the wrong order | [DIDSR/MCGPU#25](https://github.com/DIDSR/MCGPU/issues/25) |
> | 5 | Sub-cutoff Compton residual energy discarded, not deposited | [DIDSR/MCGPU#26](https://github.com/DIDSR/MCGPU/issues/26) |
>
> A paper that argues for openness and returns defects to the open code it
> depends on is making its own case; these belong in the Data Availability
> statement.

All line numbers refer to `MC-GPU_v1.3.cu` at commit as cloned from
`https://github.com/DIDSR/MCGPU` (see `vendor/build/build_info.json` for the
SHA-256 of the exact source file).

---

## Issue 1 — `abs()` applied to a `double` silently collapses any aperture below 1° to a pencil beam

**Severity: high. Wrong results, no warning. Affects the CPU build on every platform.**

```c
1386:  if (abs(theta_aperture) < 1.0e-7)
1393:  if (abs(phi_aperture) < 1.0e-7)
```

The guard is meant to catch a pencil-beam input. But `theta_aperture` and
`phi_aperture` are `double`, and in **C** `abs` is `int abs(int)` from
`<stdlib.h>`: the argument is truncated toward zero before the comparison.

Any aperture with magnitude below 1° therefore truncates to `0`, tests as
`< 1.0e-7`, and is replaced by a pencil beam (`D_cos_theta = 0` /
`D_phi = 0`). No diagnostic is printed, and the reported aperture in the header
becomes `0.000000`.

This is not an exotic input. A 10 mm nominal collimation at a 600 mm
source-to-axis distance subtends 0.95°, so the polar aperture of an ordinary CT
acquisition — and of AAPM TG-195 Case 4 — vanishes.

**Why it has survived:** the recommended GPU build uses `nvcc`, which compiles
`.cu` as **C++**, where `abs` has a `double` overload and the code behaves as
intended. The defect only bites the CPU build that the README documents as
`gcc -x c -O3 MC-GPU_v1.3.cu`.

**Fix:** use `fabs`.

```diff
-  if (abs(theta_aperture) < 1.0e-7)
+  if (fabs(theta_aperture) < 1.0e-7)
...
-  if (abs(phi_aperture) < 1.0e-7)
+  if (fabs(phi_aperture) < 1.0e-7)
```

**How it was caught:** by reading the engine's own echoed apertures
(`MC-GPU_v1.3.cu:509`) back from the log and asserting they matched what was
requested. A tally-value check would not have caught it — the doses looked
entirely reasonable.

---

## Issue 2 — the CPU branch reuses one random sequence for every projection

**Severity: high. Wrong uncertainties and correlated projections, no warning.**

The CUDA branch advances the seed between projections:

```c
869:  update_seed_PRNG(numprocs, total_histories, &seed_input);   // Do not repeat seed for each projection.
```

but that call is inside `#ifdef USING_CUDA`. The CPU branch (`#else`, around
lines 913–958) calls

```c
957:  track_particles(CPU_batch, histories_per_thread, num_p, seed_input, ...);
```

with `seed_input` unchanged from projection to projection, and `CPU_batch`
restarting at 0 each time. Every projection of a CT trajectory therefore replays
an identical photon sequence at a rotated source position.

Consequences: the tally comes out exactly invariant under the rotation step (in a
CTDI phantom, the four cardinal chamber positions returned identical values to
every decimal place); and the reported statistical uncertainty is meaningless,
because the projections are perfectly correlated rather than independent.

**Fix:** `init_PRNG` already leaps ahead by
`(history_batch + 1) * histories_per_thread * LEAP_DISTANCE`
(`MC-GPU_kernel_v1.3.cu:841-847`), so offsetting the batch index by one
projection's worth of batches gives each projection a disjoint stretch of the
sequence — the same guarantee the CUDA branch has:

```diff
-      track_particles(CPU_batch, histories_per_thread, num_p, seed_input, ...);
+      track_particles(CPU_batch + num_p*total_threads, histories_per_thread, num_p, seed_input, ...);
```

Adding the missing `update_seed_PRNG` call after the CPU batch loop would work
equally well.

---

## Issue 3 — binary output files are opened in text mode

**Severity: high on Windows, harmless on Linux. Silent data corruption.**

```c
2841:  FILE* file_binary_ptr       = fopen(file_binary, "w");        // !!BINARY!!
2919:  FILE* file_binary_mean_ptr  = fopen(file_binary_mean, "w");   // !!BINARY!!
2920:  FILE* file_binary_sigma_ptr = fopen(file_binary_sigma, "w");  // !!BINARY!!
```

All three are written with `fwrite` of 32-bit floats and are marked `!!BINARY!!`
in the source, but opened with mode `"w"`. On POSIX that is identical to `"wb"`.
On Windows the CRT translates every `0x0A` byte inside the float data to
`0x0D 0x0A`, so the `.raw` dose map, its uncertainty map and the projection
images are corrupted — every value read back is garbage (we saw doses wrong by
tens of orders of magnitude).

**Fix:** `"wb"` in all three places. This is portable and changes nothing on
Linux.

---

## Issue 4 — the aperture input line is documented in the opposite order to the one it is parsed in

**Severity: medium. Documentation defect that produces a wrong geometry silently.**

```c
1351:  // Read input fan beam polar (theta) and azimuthal (phi) aperture angles (deg):
1353:  sscanf(new_line, "%lf %lf", &phi_aperture, &theta_aperture);
```

The comment, and the corresponding line in every distributed sample input file —

```
-15.0 -15.0   # POLAR AND AZIMUTHAL APERTURES FOR THE FAN BEAM [degrees]
```

— read *polar then azimuthal*, but the `sscanf` assigns **azimuthal first**. The
sample files are unaffected because both values are equal, which is exactly why
the discrepancy has gone unnoticed.

A user following the documented order gets a beam collimated across the fan and
wide open along Z. The simulation runs happily and produces plausible CTDI-like
numbers; only the *shape* of the dose profile reveals it.

**Fix:** either swap the `sscanf` arguments (breaking existing input files) or —
better — correct the comment and the sample input files to read
`# AZIMUTHAL AND POLAR APERTURES`. The engine already echoes the parsed values in
the correct order at line 509, which is the only reason the mismatch is
diagnosable at all; that echo is worth keeping and documenting.

---

## Suggested framing for the issue text

These were found while building an openly-licensed CT organ-dosimetry pipeline on
MC-GPU, and verifying it against AAPM TG-195 Case 4. Issues 1–3 are one-line
fixes; issue 4 is a documentation correction. Happy to send pull requests if
that is useful.


---

## Issue 5 — sub-cutoff Compton residual energy is discarded rather than deposited

**Severity: negligible at CT energies (measured); potentially material at mammography energies.**

MC-GPU has no separate absorption energy: the cutoff is the first tabulated entry
of the material file. After a Compton interaction only the energy transferred to
the electron is tallied (`MC-GPU_kernel_v1.3.cu:301`, `:359`); if the scattered
photon's new energy falls below the table's lower bound, the index goes negative
and the track breaks (`:311`, `:372`) **without depositing the remainder**. Energy
is not conserved. The photoelectric path is fine — `:351` deposits the whole
photon energy.

Measured at 120 kVp in PMMA: regenerating the tables at 1 keV instead of 5 keV
moved every scored region by ≤0.012%, because at 5 keV photoelectric absorption
dominates so strongly that almost nothing degrades past the cutoff.

That argument weakens as the beam softens, and MC-GPU's principal use is
mammography and tomosynthesis at 20–40 kVp, scoring mean glandular *dose*. We have
not measured it there and claim no number, but the mechanism is energy
non-conservation, it grows as the beam softens, and it is invisible in the output.
Reported for that reason.

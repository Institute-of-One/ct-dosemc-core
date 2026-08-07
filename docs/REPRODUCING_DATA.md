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

The cohort is the one assembled for IORN-006 (`ctsegdose-core`), re-stated here so
IORN-007 stands on its own rather than by reference:

* four vendors, so that the multi-vendor claim is a property of the data and not
  of the discussion section;
* contrast-free or arterial-phase abdominal/chest series with the acquisition
  attributes the dose model needs — in particular **X-Ray Tube Current
  (0018,1151)** per slice, kVp, collimation, pitch and CTDIvol;
* series that are complete, single-acquisition and geometrically regular.

**Not yet present in this repository.** The selective NBIA fetch — which
downloads only the series that pass the filter rather than a 600 GB collection —
lives in `ctsegdose-core` as `tools/select_and_download.py`, on top of its
`nbia`, `selection` and `eligibility` modules. It is ported here at the start of
Phase 2, not before, for two reasons: the eligibility criteria for an
*absorbed-dose* study are not identical to those for an index study and must be
re-derived rather than inherited wholesale, and Phase 1 needs no patient data at
all, so a downloader that cannot yet be exercised would be untested code
pretending to be a capability.

When it lands it will write `data/PROVENANCE.json`, the only thing under `data/`
that is committed.

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
python tools/make_materials.py
```

This writes `materials/*.mcgpu.gz` (git-ignored) and `materials/PROVENANCE.json`
(committed), which records for each material its PENDBASE entry number and label,
the nominal density the database supplies, the energy grid, and the SHA-256 of
the generated file. The generator refuses to continue if a PENDBASE id does not
resolve to the expected material name — the ids in the upstream README are not
all correct, and simulating photographic emulsion instead of PMMA is the kind of
mistake that produces perfectly plausible numbers.

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

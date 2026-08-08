# ct-dosemc-core

**Patient-specific absorbed organ dose in CT (mGy) by open Monte Carlo.**

Photon transport through the patient's own segmented, density-mapped anatomy,
using a public-domain engine, open spectra and openly-licensed inputs — so the
dose coefficients are *computed* rather than looked up, and there is no licensing
exposure anywhere in the chain.

> **Status: Phase 1a — code verification. Not yet usable for patient dose.**
> The transport, geometry and source model are verified against **AAPM TG-195
> Case 4**: the monoenergetic single-projection gate agrees with the four-code
> published mean to **0.147%** against a ±1% tolerance. Remaining gates and open
> items: [docs/MC_SOURCE_MODEL.md](docs/MC_SOURCE_MODEL.md) §5.1 and §7.

Institute of One, LISIT Co., Ltd., Tokyo, Japan · MIT licence.

---

## Why this exists

Two earlier projects stopped short of absorbed dose, for the same reason:

* **ctdose-core** computes the whole-scan **CTDIvol** — a scanner-output index.
* **ctsegdose-core** computes an organ-specific **weighted CTDIvol index** —
  deliberately *not* mGy, because no CC-BY organ-dose coefficient dataset exists.
  Every published coefficient table (Turner, Tian, ImPACT, NCICT) is copyrighted.

This project goes to **absorbed dose in mGy** by simulating photon transport
directly. The coefficients are ours, so the licensing barrier disappears.

The contribution split, stated plainly because it will be asked: whole-scan index
→ organ index → absorbed mGy by own Monte Carlo. Different endpoint, different
method.

### What it is not

It does not compete on scale. Patient-specific CT organ dose by DL segmentation
plus GPU Monte Carlo already exists — Peng et al. (Med. Phys. 2020) originated it,
and later work has run it over ten thousand subjects at a single centre. The
distinction here is **openness × provenance × multi-vendor**:

1. open **end to end** — public-domain engine, MIT wrapper, CC BY inputs, and
   material cross-sections generated locally from a permissively-licensed database;
2. **per-value provenance**, fixed seeds, and a Monte-Carlo statistical
   uncertainty on every reported dose, with anti-fabrication tests that re-derive
   the quoted figures from the recorded inputs;
3. **multi-vendor**, not single-centre;
4. the first pipeline to resolve the "coefficients are not openly licensed"
   barrier by generating them openly.

---

## The stack

| Component | Role | Licence |
|---|---|---|
| [MC-GPU v1.3](https://github.com/DIDSR/MCGPU) (DIDSR/FDA) | photon transport | public domain |
| [SpekPy](https://bitbucket.org/spekpy/spekpy_release) | tube spectra, HVL, air kerma | BSD-3 |
| PENELOPE 2006 PENDBASE (photon subset) | material cross-sections | permissive (UB notice) |
| [TotalSegmentator](https://github.com/wasserth/TotalSegmentator) | anatomy (Phase 2) | Apache-2.0 |
| this repository | phantoms, dosimetry, provenance | MIT |

TOPAS is deliberately avoided: free for academia, but redistribution-restricted,
which would undermine the whole claim.

---

## Layout

```
ct_dosemc_core/
  spectra.py       SpekPy wrapper: spectra, HVL, absolute photons/sr/mAs
  source_model.py  beam geometry, solid angle, mAs <-> histories, TCM (Phase 2)
  phantom.py       voxel phantom container; Schneider HU -> density
  ctdi.py          IEC CTDI phantoms, chamber positions, CTDI100/w/vol
  tg195.py         AAPM TG-195 Case 4: geometry, sub-fans, reference reader
  mcgpu_io.py      write engine inputs, run it, read the tallies back
  dosimetry.py     region absorbed dose in mGy with MC uncertainty
  provenance.py    per-value provenance records and results writing
tools/
  build_mcgpu.ps1     build MC-GPU on Windows (CPU or CUDA)
  make_materials.py   generate the material files from PENDBASE
  fetch_tg195.py      fetch the AAPM reference data (never committed)
  run_tg195.py        Phase 1a: the code-verification gates
  run_validation.py   Phase 1b: the CTDI anchor
tests/               closed-form, format and anti-fabrication checks
docs/
  MC_SOURCE_MODEL.md  what the simulation models, and every assumption
  REPRODUCING_DATA.md exact provenance rules; no DICOM redistributed
  UPSTREAM_ISSUES.md  engine defects found here, drafted for DIDSR/MCGPU
results/             every reported number, machine-readable
```

---

## Getting started

```powershell
# 1. dependencies
python -m venv .venv; .venv\Scripts\pip install -e ".[spectra,dev]"

# 2. the engine (vendored, public domain; the script never edits upstream source)
git clone --depth 1 https://github.com/DIDSR/MCGPU.git vendor/MCGPU
#    plus zlib 1.3.1 source into vendor/zlib-1.3.1
powershell -File tools/build_mcgpu.ps1 -Target cpu

# 3. material cross-sections
git clone --depth 1 https://github.com/andreubs/MCGPU_materials vendor/MCGPU_materials
python tools/make_materials.py

# 4. the Phase-1a gate: AAPM TG-195 Case 4
python tools/fetch_tg195.py                 # copyrighted; fetched, never committed
python tools/run_tg195.py --gate G0         # spectrum beam quality
python tools/run_tg195.py --gate G1 --histories 6e7 --sub-fans 8 \
    --voxel-size 0.5 --phantom-length 60 --air-margin 44 --air-margin-z 4
python tools/run_tg195.py --scan air_margin=1,10,20,30,40   # convergence

# 5. checks
python -m pytest
```

The CPU build needs no CUDA toolkit and is the reference; the CUDA build is
20–40× faster and is what a cohort run requires.

---

## Phases

| Phase | What | State |
|---|---|---|
| 0 | scaffold, engine build, spectra, source model | done |
| **1a** | **code verification against AAPM TG-195 Case 4** — the gate | G0 done, **G1 passed (0.147%)**, G2 running, G3–G5 open |
| 1b | physical anchor: bowtie, filtration, μ_en/ρ, measured CTDIvol | not started; may run in parallel with Phase 2 |
| 2 | multi-vendor cohort → per-organ mGy + MC uncertainty | released by Phase 1a |
| 3 | cross-check against published ranges (comparison only) | — |
| 4 | openness package, Zenodo DOI | — |
| 5 | manuscript | — |

### Why TG-195 is the gate, and not a measured CTDIvol

This simulation has no bowtie, a flat fan and a homogeneous PMMA cylinder. Every
published CTDIvol was measured on a scanner *with* a bowtie, so a disagreement
between them is unattributable — coding error or missing physical component, with
no way to tell which. TG-195 Case 4 **specifies** the configuration we have, and
publishes results from four independent Monte Carlo packages, so a disagreement
there is attributable to us.

The bowtie, the PMMA→air-kerma conversion and the absolute mAs normalisation all
drop out of that comparison — not because they were waved away, but because Case 4
has no bowtie, scores energy in PMMA directly, and reports per emitted photon.
They come back in Phase 1b, where they are tests of the *scanner* model.

Reviewers of Monte Carlo dosimetry papers check code verification before measured
agreement, and TG-195 has been the de-facto standard for that since 2015.

---

## Honesty notes

Read [docs/MC_SOURCE_MODEL.md](docs/MC_SOURCE_MODEL.md) before quoting any number
from here. The current state, in brief:

* **The CTDI numbers in `results/` are Phase-1b material and are not validated
  against any measurement.** They report absorbed dose to PMMA, not air kerma in a
  bore, and they come from a beam with no bowtie. The central/peripheral ratio of
  0.293 against a literature "≈0.5" is the *expected* consequence of a flat fan,
  not evidence of an error — and not evidence of correctness either. Code
  correctness is settled by TG-195, not by that comparison.
* **No bowtie filter.** Correct for TG-195 Case 4, which specifies none; the
  largest bias against a real scanner. Phase 1b, gate G6.
* **MC-GPU tallies collision kerma** — electrons are not transported.
* **Air outside the voxel box does not exist.** MC-GPU jumps photons from the
  focal spot to the box without interaction. Modelling 1 cm of TG-195's 44 cm
  air path rather than all of it biases the result by ~0.8%; this applies to
  patient geometry too.
* Within a single run, region uncertainties combine per-voxel σ as if independent
  — they are not, and the quadrature estimate understates σ by roughly 4–13×
  (point estimate 7.2×, from only four degrees of freedom). Independent-seed
  replicas are gate G4.

**Four defects in the vendored engine** were found and patched, three of which
produce wrong results silently — including one that turns any beam narrower than
1° into a pencil beam, and one that made every projection of a CT rotation replay
the same random sequence. Write-ups ready to file upstream:
[docs/UPSTREAM_ISSUES.md](docs/UPSTREAM_ISSUES.md).

---

## Citation

See `CITATION.cff`. Cite the **version DOI** of the release a result was produced
with; the concept DOI in the README and `CITATION.cff` resolves to the latest.
Please also cite MC-GPU (Badal & Badano, Med. Phys. 36, 4878, 2009) and SpekPy.

## Licence

MIT — see `LICENSE`. Third-party components keep their own licences; none of them
is redistributed by this repository.

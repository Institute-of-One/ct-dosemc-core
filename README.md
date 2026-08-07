# ct-dosemc-core

**Patient-specific absorbed organ dose in CT (mGy) by open Monte Carlo.**

Photon transport through the patient's own segmented, density-mapped anatomy,
using a public-domain engine, open spectra and openly-licensed inputs — so the
dose coefficients are *computed* rather than looked up, and there is no licensing
exposure anywhere in the chain.

> **Status: Phase 1 — validation anchor. Not yet usable for patient dose.**
> No patient data is processed until the CTDI anchor passes review. See
> [docs/MC_SOURCE_MODEL.md](docs/MC_SOURCE_MODEL.md) §6 for the open items.

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
  mcgpu_io.py      write engine inputs, run it, read the tallies back
  dosimetry.py     region absorbed dose in mGy with MC uncertainty
  provenance.py    per-value provenance records and results writing
tools/
  build_mcgpu.ps1     build MC-GPU on Windows (CPU or CUDA)
  make_materials.py   generate the material files from PENDBASE
  run_validation.py   Phase 1: the CTDI anchor
tests/               closed-form, format and anti-fabrication checks
docs/
  MC_SOURCE_MODEL.md  what the simulation models, and every assumption
  REPRODUCING_DATA.md exact provenance rules; no DICOM redistributed
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

# 4. the Phase-1 anchor
python tools/run_validation.py --kvp 120 --phantom-diameter 32 --collimation 2.0 \
    --voxel-size 0.25 --projections 180 --histories 5.6e6 --mas 100

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
| 1 | **CTDI validation anchor** — gate for everything after | first run done; open items in `MC_SOURCE_MODEL.md` §6 |
| 2 | multi-vendor cohort → per-organ mGy + MC uncertainty | blocked on Phase 1 |
| 3 | cross-check against published ranges (comparison only) | — |
| 4 | openness package, Zenodo DOI | — |
| 5 | manuscript | — |

Phase 1 is anchored to **CTDIvol, a physical standard**, and not to IORN-006's
organ index, so that this project does not inherit the fate of another review.

---

## Honesty notes

Read [docs/MC_SOURCE_MODEL.md](docs/MC_SOURCE_MODEL.md) before quoting any number
from here. The current state, in brief:

* **No bowtie filter.** The largest known bias. The fan is flat, so peripheral
  dose is overestimated relative to a real scanner.
* **Absorbed dose to PMMA is reported, not air kerma in a bore.** The
  `(μ_en/ρ)_air/(μ_en/ρ)_PMMA` conversion is not yet implemented, so only the
  dimensionless ratios are directly comparable with the literature.
* **MC-GPU tallies collision kerma** — electrons are not transported.
* Region uncertainties combine per-voxel σ as if independent, which understates
  them; the spread across the four physically-equivalent peripheral chambers is
  reported alongside as a more trustworthy estimate.

Three defects in the vendored engine were found and patched during Phase 0 — two
of them silent, one of them producing plausible-looking but entirely wrong doses.
They are documented in `MC_SOURCE_MODEL.md` §2.1 and should be reported upstream.

---

## Citation

See `CITATION.cff`. Cite the **version DOI** of the release a result was produced
with; the concept DOI in the README and `CITATION.cff` resolves to the latest.
Please also cite MC-GPU (Badal & Badano, Med. Phys. 36, 4878, 2009) and SpekPy.

## Licence

MIT — see `LICENSE`. Third-party components keep their own licences; none of them
is redistributed by this repository.

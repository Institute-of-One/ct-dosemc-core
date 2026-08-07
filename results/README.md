# results/

Every number that appears in the paper lives here, in machine-readable form, with
its provenance. Nothing is quoted from a notebook, a log tail or a memory.

## Layout

```
results/
  phase1_ctdi_anchor_<tag>.json   the headline copy of each Phase-1 run
  phase1/<tag>/
    ctdi_anchor.json              the same content, next to what produced it
    spectrum.spc                  the spectrum MC-GPU actually sampled
    ctdi.in                       the engine input file, verbatim
    mcgpu.log                     the engine's own stdout, including the
                                  apertures it parsed
    (dose.dat*, *.vox.gz          regenerated, not committed -- see .gitignore)
```

## Reading a results file

Any object with `value` and `unit` also carries `provenance`:

```json
{
  "value": 5.2517,
  "unit": "mGy",
  "uncertainty": 0.0004,
  "uncertainty_kind": "1sigma_mc_statistical",
  "provenance": {
    "formula": "CTDIw = (1/3)*CTDI100_centre + (2/3)*CTDI100_peripheral",
    "inputs": { "...": 0 },
    "assumptions": ["..."],
    "source": "IEC 60601-2-44; AAPM Report 96"
  }
}
```

`uncertainty` is **one** standard deviation. MC-GPU reports two; the conversion
happens once, in `mcgpu_io.read_dose_map`, so nothing downstream has to remember
the factor.

Each file also carries:

* `environment` — python, platform, git commit, library versions;
* `engine` — the executable's SHA-256, the patches applied to the vendored
  source, the seed, the history count;
* `materials` — the SHA-256 of each cross-section file actually loaded;
* `known_gaps` — what the run does *not* model. A run that claims none is not
  being honest, and `tests/test_provenance.py` enforces that the list is
  non-empty.

## The reconciliation tests

`tests/test_no_fabrication.py` reads these files as they sit on disk and
recomputes the reported values from the components stored beside them — CTDIw
from the five CTDI100s, CTDI100 from the region dose and the collimation, the
region dose from the per-history tally and the photon count, the photon count from
the spectrum and the solid angle, the solid angle from the two apertures. A
hand-edited number breaks the chain.

It also checks two things arithmetic cannot: that the engine echoed the apertures
it was asked for, and that the measured dose profile has the right *shape* — a
longitudinal beam width matching the geometric prediction, and a surface dose
exceeding the central dose. Those shape checks exist because a mis-parsed beam
aperture produced perfectly plausible CTDI values during Phase 0.

## Status

Phase-1 results are a **validation anchor under review**, not paper numbers. The
open items are listed in `docs/MC_SOURCE_MODEL.md` §6; until they are closed, the
absolute values here should not be compared with a measured scanner CTDIvol.

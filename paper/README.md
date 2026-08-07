# paper/

The manuscript is written last, from `results/`. Nothing here quotes a number
that is not read out of a results file at build time.

Planned contents, following the pattern of the earlier IoO papers:

```
manuscript.md         the Original Article, in markdown
make_figures.py       every figure, regenerated from results/
build_manuscript.py   substitutes numbers from results/ into the text and
                      fails if a placeholder has no matching result
references.bib
```

## Target

**Physics in Medicine & Biology** (IOP) — hybrid, non-OA is free, first decision
around 35 days, and the canonical home for Monte-Carlo CT dosimetry. Alternates:
Medical Physics (AAPM/Wiley), then Physica Medica (Elsevier).

Full Original Article.

## Title

Finding-led or method-led, and **must not begin with "Open"**. Working title:

> Patient-specific absorbed organ dose in CT from routine metadata using open
> Monte Carlo and deep-learning segmentation: a multi-vendor, fully reproducible
> pipeline.

To be finalised once Phase 3 shows what the finding actually is.

## Introduction must state the contribution split explicitly

* IORN-004 (ctdose-core) — whole-scan CTDIvol, a scanner-output index.
* IORN-006 (ctsegdose-core) — organ-specific weighted CTDIvol, still an index.
* IORN-007 (this) — absorbed dose in mGy, by our own Monte Carlo.

Different endpoint, different method. Cite 004 and 006 by Zenodo DOI, and re-state
the shared pipeline steps (segmentation, HU→density, TCM) inside this paper so it
stands alone rather than depending on their acceptance.

## Validation section

Anchored to CTDIvol — a physical standard — and not to IORN-006's organ index.
Every assumption from `docs/MC_SOURCE_MODEL.md` belongs in the methods, including
the ones that are uncomfortable: the bowtie approximation, the collision-kerma
tally, and the absence of table attenuation.

# paper/

The manuscript is written last, from `results/`. Nothing here quotes a number that
is not read out of a results file at build time.

## Contents

```
manuscript.md         the Original Article, in markdown  (still docs/manuscript.md)
freeze.py             copies the cited results into frozen/ and derives the metrics
build_manuscript.py   resolves [[results:...]] markers; an unresolved marker is an error
make_figures.py       Figures 1-3, at the size they print
frozen/               the results the manuscript may quote, as of the freeze
figures/              the rendered figures
```

Figures 4 and 5 come from `tools/figure4_scatter.py` and
`tools/collect_phase2_results.py`, which run as part of the production pipeline.

Run `python paper/freeze.py` before `python paper/make_figures.py`: the figures are
drawn from `frozen/`, not from `results/`, so a re-run cannot change a figure that
has already been placed in the manuscript.

## Target

**Physics in Medicine & Biology** (IOP) — hybrid, non-OA is free, first decision
around 35 days, and the canonical home for Monte-Carlo CT dosimetry. Alternates:
Medical Physics (AAPM/Wiley), then Physica Medica (Elsevier).

Full Paper. PMB has a Note category and this programme has already had one paper
reclassified into one, so the pre-submission inquiry in `docs/pmb_inquiry_send.txt`
asks the Board to confirm the type before the manuscript is written.

## Title

Finding-led, not artefact-led, and **must not begin with "Open"**. Three working
titles were in circulation, each naming what was built — a source model, a cohort,
a pipeline — which is the shape that had a companion paper desk-rejected as a
resource description. The title names the measured difference instead:

> How far an organ-weighted CTDIvol index is from absorbed organ dose:
> TG-195-verified Monte-Carlo measurement on the same patient anatomy across
> four vendors

## Figure captions

Written here once. The manuscript places the image and takes the caption from this
table. A caption written twice — as image alt text and again as a numbered
paragraph — prints twice in the converted document, in two wordings.

| Fig | Caption |
|---|---|
| Fig 1 | Cohort selection. (a) Series remaining at each stage, from the 47 181 rows of the collection index to the 40 series carried forward, on a logarithmic axis. Position carries the count: a bar length on a logarithmic axis would encode the ratio to the axis floor rather than the number. (b) The reason each of the 22 probed-and-rejected series was rejected; almost all lacked the per-slice tube current the pipeline requires |
| Fig 2 | The pre-declared density gate. Largest out-of-calibration component per series — voxels inside the body contour at or above the calibration ceiling — for all 40 assessed series, ordered by that volume, on a symmetric-logarithmic axis so that the 14 series with no such voxel are visible rather than dropped. Filled markers are the 32 eligible series, open markers the 8 excluded. The gate at 1 cm³ was declared before the volumes were computed |
| Fig 3 | Verification against AAPM TG-195 Case 4, at the centre and perimeter volumes of interest. Each point is the relative difference between this engine and one published code, with error bars of the combined standard uncertainty. PENELOPE, marked with a diamond, is the yardstick, and was chosen before any comparison was run because it shares the photon cross-section database this work generates its materials from; the other three codes are shown so the choice can be seen not to have been made after the fact |
| Fig 4 | Same-patient scatter: the IORN-006 organ-weighted CTDIvol index against absorbed organ dose in mGy, one point per organ per series. 12 organs, 342 points, 30 series. Filled circles are the 23 series carrying a recorded CTDIvol, filled squares the 6 reconstructed on an exact or high-confidence table match, open squares the 1 reconstructed under IORN-004's own low-confidence warning. Index and absorbed dose are correlated and are not the same quantity |
| Fig 5 | Absorbed organ dose by vendor, per organ, with the number of series in which each organ is present |

## Data provenance

`data/PROVENANCE.json` records collection, Series Instance UID, licence and
retrieval date for every series; no imaging is redistributed. `results/` holds the
machine-readable artefacts and `docs/REPRODUCING_DATA.md` the reproduction recipe.

`results/phase2_cohort/figure4_y_axis.json` carries the mid-scan defect — its
y-axis is not an exam dose — and `freeze.py` names it as excluded so it cannot
reach the paper. The file that supersedes it declares `usable_for_figure4`.

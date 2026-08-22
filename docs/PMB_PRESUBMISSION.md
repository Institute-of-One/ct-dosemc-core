# PMB pre-submission inquiry — ready to send

Fig. 4 now has a scaled y-axis from *scan-covering* production
(`n_z_stations = round(L/NT)`; `results/phase2_cohort/figure4_stats.json`,
`usable_for_figure4: true`). Do **not** send on
`figure4_y_axis.json` (mid-scan defect). Paper, not Note. Do not first-submit
Medical Physics.

**To:** Editor-in-Chief, *Physics in Medicine & Biology*  
**Subject:** Pre-submission inquiry — Paper (not Note): TG-195-verified CT organ dose vs organ-weighted CTDIvol on one multi-vendor cohort

---

Dear Editor,

We would like to confirm that the following manuscript is appropriate as a
**Paper** (not a Note) for *Physics in Medicine & Biology*.

**Working title.** Device-independent Monte-Carlo CT organ dosimetry on patient
anatomy: a TG-195-verified MC-GPU source model with a fully re-derivable cohort.

**Hypothesis.** On the same patient anatomy, absorbed organ dose (mGy) and the
organ-weighted CTDIvol index are different quantities. We measure that split
after verifying the transport engine against AAPM TG-195 Case 4 with a stated,
replica-measured uncertainty.

**Why this is a Paper.** PMB defines Papers as original scientific research,
techniques *and* applications. The manuscript has both: (i) Case 4 second-test
agreement with PENELOPE reported with combined uncertainty (not a homemade
pass/fail) — centre |ours−PENELOPE| = 0.359% (1.67σ_comb); a measured
phantom-length term; and a declared limitation budget; (ii) absorbed organ
doses on N = 32 TCIA series (four vendors; a pre-declared metal-implant
exclusion), scaled to a CTDIvol the series actually carries (recorded 23/32,
reconstructed 7/32, unrecoverable 2/32). The same-patient scatter (Fig. 4) is
12 organs, 342 points (30 series): Pearson r = 0.66 (all) and 0.61 on the 23
series with a recorded CTDIvol. Restricting Fig. 4 to those 23 series does not
change the index–absorbed-dose relationship. That scatter is the application
result, not a software demo.

**Why this is not a Note.** A Note would be the engine or the TG-195
reproduction alone. Those are Methods. The claim is the measured difference
between two published endpoints on one cohort.

**Related work, not salami.** IORN-004 reports whole-scan CTDIvol. IORN-006
reports an organ-weighted CTDIvol *index*. This manuscript reports absorbed
mGy. Three endpoints, one pipeline. The scatter is the evidence that they are
not slices of the same number.

**Length.** Within the Paper limit (≤ 10 000 words, ≤ 12 figures). Planned:
six figures, four tables. Fig. 6 (metal-clamp re-include) is not on the
submission path.

If the Board would prefer a different article type, we would rather hear that
now than after review. We are not submitting a Note.

Yours sincerely,  
[authors]

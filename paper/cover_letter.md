<!--
The source of the cover letter. Numbers are [[results:...]] markers resolved from
paper/frozen/ at build time, and the title is taken from the manuscript, so the
letter cannot quote a figure or a title the paper no longer has. A companion
paper's letter kept a withdrawn claim for two revision rounds.

[[title]] resolves to the manuscript's own level-1 heading.
-->

Dear Editor-in-Chief,

I submit the enclosed manuscript, "[[title]]", for consideration as a Research
Article in *Radiological Physics and Technology*.

The volume CT dose index is a scanner output and the field converts it to organ
dose with size corrections, dose-length-product factors and per-organ coefficient
libraries. How close such a conversion can get has not been measured against
transport on the same anatomy. This study measures it for five conversions, each
scored under leave-one-patient-out cross-validation on
[[results:manifest.json:metrics.n_scaled]] multi-vendor abdominal CT series from
a public archive.

Three findings are, I believe, of direct interest to this journal's readers. A
single conversion factor recovers absorbed organ dose to a median
[[results:manifest.json:metrics.ceiling_global_factor_median_pct|.0f]] %, and one
factor per organ — the form in which published coefficient libraries are used —
is not separable from it on this cohort: the difference in median error is
[[results:manifest.json:metrics.compare_per_organ_factor_vs_global_factor_diff_pp|+.1f]]
points with a 95 % interval of
[[results:manifest.json:metrics.compare_per_organ_factor_vs_global_factor_ci_low_pp|+.1f]]
to
[[results:manifest.json:metrics.compare_per_organ_factor_vs_global_factor_ci_high_pp|+.1f]].
The best of the five reaches
[[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] %.
[[results:manifest.json:metrics.variance_between_patient|.0%]] of the variance in
the dose-to-index ratio lies between patients against
[[results:manifest.json:metrics.variance_between_organ|.0%]] between organs, so
what an index withholds is patient-specific rather than organ-specific, and
neither the per-organ table nor the size correction scored here supplies it. The
residual is three orders of magnitude above the Monte-Carlo sampling uncertainty,
so sampling does not account for it.

A reader is left with something to act on rather than a negative result. Where a
median of
[[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] % is
adequate — protocol comparison, registry-scale surveillance, a department
tracking itself — the conversion to use is a scan-length term with a per-organ or
patient-size offset, which is where that number comes from; a coefficient library
without a length term adds twelve parameters to reach
[[results:manifest.json:metrics.ceiling_per_organ_factor_median_pct|.0f]] %. Where
it is not adequate, the missing
quantity is transport through that patient's own anatomy, computed here from the
metadata a routine abdominal CT already records, with no added exposure and no
phantom matched to the patient.

I offer the manuscript to this journal because it has published the nearest work
to it. Fujibuchi, Han and Anam (*Radiol Phys Technol* 2026;19(4):1787–1801)
compared three organ-dose packages under identical scan conditions and attributed
the spread between them to phantom anatomy and size rather than to inaccuracy in
any one package. That is the same mechanism this study bounds from the other
side: their experiment varies the anatomy a fixed index is converted through,
while this one varies the patient and holds the transport fixed.

The engine is verified against Case 4 of AAPM Task Group 195 with a
replica-measured uncertainty and a reference code fixed before any comparison was
run; the difference from PENELOPE at the centre volume of interest is
[[results:manifest.json:metrics.tg195_centre_abs_pct|.3f]] %. The software, the
frozen result tables and the commands that regenerate every figure are openly
archived under the MIT licence at https://doi.org/10.5281/zenodo.24029358. No
imaging is redistributed: every series is identified by collection, Series
Instance UID and licence so that a reader can re-fetch it.

I confirm that this manuscript is original, that it is not under consideration
elsewhere and has not been published before, and that I am its sole author and
take full responsibility for its content. Ethics approval was waived: the study
uses only de-identified images and acquisition metadata already placed in the
public domain by their depositing institutions. I am Representative Director of
LISIT Co., Ltd., which funds Institute of One; I declare no other competing
interest. The research received no external funding. The use of a generative
artificial intelligence assistant is declared in the manuscript.

For completeness: an earlier version of this work was submitted to *Physics in
Medicine and Biology* and was not accepted after review. It was then submitted
to the *Journal of Radiological Protection* and withdrawn by that journal
without review, under IOP Publishing's policy of not considering an article
rejected by another of its journals. The manuscript has since been rewritten,
and the referees' central objection has been addressed: the claim now states the
five conversions it is a bound over, and the scope of that bound is declared in
a paragraph of its own.

Thank you for considering it.

| Yours sincerely,
|
| Shuji Yamamoto
| Institute of One, LISIT Co., Ltd., Tokyo 150-0044, Japan
| yamamoto@lisit.jp
| ORCID 0000-0001-9211-1071

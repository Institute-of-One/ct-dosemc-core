<!--
Every number in this file is a [[results:...]] marker resolved from paper/frozen/
at build time. A marker that cannot be resolved is a build error, and a test fails
if a frozen metric appears here as a typed literal. Do not type numbers.
-->

# A measured floor on index-based organ dose estimation in CT, where per-organ coefficients do not improve on a single conversion factor

## Abstract

**Objective.** The volume CT dose index is a scanner output, not a patient dose, and
the field converts it to organ dose with size corrections, dose-length-product
factors and libraries of per-organ coefficients. How close such a conversion can get
has not been measured against transport on the same anatomy. We measure that floor.

**Approach.** A GPU Monte-Carlo pipeline computes absorbed organ dose in patient
anatomy from routine metadata alone. The transport engine is verified against AAPM
TG-195 Case 4 with a replica-measured uncertainty and a yardstick fixed before any
comparison. On [[results:manifest.json:metrics.n_scaled]] multi-vendor abdominal CT
series from a public archive, [[results:manifest.json:metrics.n_points]] organ-series
pairs across [[results:manifest.json:metrics.n_organs]] organs, we ask how well the
absorbed dose is recovered from an organ-weighted CTDIvol index by conversions of
increasing richness, each scored under leave-one-patient-out cross-validation.

**Main results.** At the centre volume of interest the engine differs from PENELOPE
by [[results:manifest.json:metrics.tg195_centre_abs_pct|.3f]] %, or
[[results:manifest.json:metrics.tg195_centre_n_sigma|.2f]] combined standard
deviations. A single conversion factor for the whole cohort recovers absorbed organ
dose to a median [[results:manifest.json:metrics.ceiling_global_factor_median_pct|.0f]] %.
One factor per organ does not improve on it
([[results:manifest.json:metrics.ceiling_per_organ_factor_median_pct|.0f]] %). Adding a
scan-length term reaches
[[results:manifest.json:metrics.ceiling_scan_length_median_pct|.0f]] %, and adding
either organ identity or patient size to that reaches a floor of
[[results:manifest.json:metrics.ceiling_scan_length_and_organ_median_pct|.0f]] % and
[[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] %
respectively. [[results:manifest.json:metrics.variance_between_patient|.0%]] of the
variance in the index-to-dose ratio lies between patients;
[[results:manifest.json:metrics.variance_between_organ|.0%]] lies between organs.
Monte-Carlo statistical uncertainty is
[[results:manifest.json:metrics.mc_sigma_median_pct|.3f]] % of the dose at the median,
so the residual is physical.

**Significance.** The information an index withholds is a property of the patient,
not of the organ. A per-organ coefficient table cannot supply it, and neither can a
size correction; on this cohort the best index-based conversion still misses absorbed
organ dose by a median of [[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] %
and by [[results:manifest.json:metrics.ceiling_scan_length_and_size_p90_pct|.0f]] % at
the ninetieth percentile.

**Keywords:** computed tomography, organ dose, Monte Carlo, CTDIvol, dose index,
cross-validation

---

## 1. Introduction

The volume CT dose index is a property of the scanner and a standard phantom, not of
the patient in it, and saying so has been necessary often enough to have its own
paper [1]. It is nonetheless the number every scanner reports, the number archived in
dose-monitoring systems, and therefore the number from which patient dose is
estimated in practice [2].

The field has three established ways of getting from that index to something closer
to a dose. Size-specific dose estimates rescale CTDIvol by the patient's attenuating
size [3], with water-equivalent diameter as the size that matters [4]. Dose-length
product is converted to effective dose by protocol-specific factors [5]. And organ
dose is estimated from libraries of per-organ coefficients, computed once by Monte
Carlo on reference phantoms and looked up thereafter [6,7], including under tube
current modulation [8].

All three are conversions from an index. Each replaces transport through this
patient's anatomy with a coefficient obtained from someone else's. The question this
paper asks is not whether such a conversion is exact — it is not, and no one claims
it is — but how close it can get, and what the irreducible part is made of.

That question needs absorbed organ dose on the same anatomy as the index, which is
what we compute. A companion study reports an organ-weighted CTDIvol index: CTDIvol
multiplied by the tube-current mean over each segmented organ relative to the scan
mean [9]. It is an index, and a good one: it is organ-specific and it carries the
longitudinal modulation. It does not transport photons. Against it we place absorbed
dose in milligray, computed by Monte Carlo through each patient's own segmented,
density-mapped anatomy, with every dose coefficient computed rather than looked up.

We then fit conversions of increasing richness from the index to the dose — a single
factor, a per-organ factor, a scan-length term, and combinations — and score each on
patients the fit has not seen. The result is a floor, and a decomposition of what
sits beneath it.

**What this paper does not claim.** It does not claim that an index and an absorbed
dose are the same quantity, nor that anyone believes they are. It does not claim
novelty for GPU Monte-Carlo photon transport [10], for spectrum modelling [11,12],
for HU-to-density calibration [13,14], or for deep-learning organ segmentation [15];
each is used as published. It does not claim that a scan-length term is a discovery:
CTDIvol is defined per rotation and carries no length, dose-length product is the
standard quantity that does, and the fitted length dependence is close to
proportional. The term is included because a conversion that omitted it would be a
straw man, and its slope is reported so that a reader can judge that for themselves.

---

## 2. Methods

### 2.1 Monte-Carlo engine and build provenance

Photon transport uses MC-GPU [10], a public-domain voxelised Monte-Carlo code, built
locally. The build is pinned: the source patches applied, their kind, and the
SHA-256 of the resulting binary are recorded in a build manifest that ships with the
software. Patches are of three kinds — defect fixes, portability changes, and
capacity increases that raise a compile-time array bound without touching the
physics — and each capacity patch records the bound, the new value, and why it was
needed. Two were required here: the Schneider tissue groups at 140 kVp exceed the
upstream limits on Compton shells and on Rayleigh energy bins.

Material cross-sections are generated locally from the photon subset of the PENELOPE
2006 database [16] rather than transcribed, so that no coefficient table is
redistributed and each material file carries the digest of the data it came from.

### 2.2 Source model

X-ray spectra come from SpekPy [11,12], which supplies the spectrum, the half-value
layer and the absolute tube output for each tube potential. The source is modelled as
an equivalent spectrum and filtration in the manner of Turner *et al* [17], with a
bowtie profile represented as a set of sub-fans, each carrying its own spectrum.
Geometry, collimation, source-to-axis distance and the number of projections come
from the series metadata.

### 2.3 Verification against TG-195 Case 4

The engine is verified against Case 4 of AAPM Task Group 195 [18], the voxelised
phantom case with published results from four independent codes. Two properties of
this verification matter for what follows.

The yardstick was fixed before any comparison was run. PENELOPE was chosen because it
shares the photon cross-section database from which our material files are generated,
not because it agreed best; the other three codes are reported alongside so that the
choice is visible.

The uncertainty is measured rather than assumed. Ten independent replicas of the
anchor configuration give a sample standard deviation, from which the standard error
of the anchor follows, and this is combined with the reported reference uncertainty
to give a combined standard deviation against which the difference is expressed.
Agreement is reported with that uncertainty; it is not converted into a pass or a
fail against a threshold of our own choosing.

The phantom length term was measured, not bounded: a 40 cm phantom is
indistinguishable from a 160 cm phantom at these volumes of interest.

### 2.4 Cohort selection

Series were selected from a public archive [19,20] by a recorded funnel that begins
at the collection index and ends at the series carried forward, with every exclusion
counted and named (figure 1). The selection is re-derivable: the criteria are in
code, and the surviving Series Instance UIDs, their collection and their licence are
recorded so that any series can be re-fetched. No imaging is redistributed.

A metadata screen removes series that are not diagnostic reconstructed abdominal
images or that carry too few or too many slices; one series per patient is kept; the
remainder are probed in vendor-balanced order until ten series per vendor are
accepted. The probe reads the header and rejects a series that lacks the per-slice
tube current the pipeline requires, which accounts for most of the rejections
(figure 1b).

### 2.5 Eligibility: a pre-declared density gate

Voxels inside the body contour at or above the top of the density calibration are
metal, concentrated contrast, or artefact, and are not tissue. A series is excluded
if its largest connected out-of-calibration component exceeds 1 cm³. The threshold and
the criterion were declared before the volumes were computed. Of
[[results:density_eligibility.json:n_assessed]] assessed series,
[[results:manifest.json:metrics.n_eligible]] are eligible and
[[results:density_eligibility.json:n_excluded]] are excluded (figure 2). The
distance from the offending component to the nearest scored organ is reported but is
not part of the gate.

### 2.6 Segmentation, density and materials

Organ boundaries come from TotalSegmentator [15] run at inference on each series, so
that no manual contour enters the pipeline and the same procedure applies to every
vendor. Hounsfield units are mapped to mass density and to Schneider tissue groups
[13,14]; voxels above the top calibration breakpoint are held at its density and
counted, and it is that count the eligibility gate reads.

### 2.7 CTDIvol normalisation

Absorbed dose per emitted photon is converted to dose per examination by a scale
derived from a simulated CTDI phantom measurement at the same tube potential and
vendor, matched to the CTDIvol the series carries. Where the series records a
CTDIvol, that value is used; where it does not, the value reconstructed from scanner
model and technique by a companion tool is used, and the two are distinguished
throughout [21]. Of [[results:manifest.json:metrics.n_eligible]] eligible series,
[[results:manifest.json:metrics.n_recorded]] carry a recorded CTDIvol,
[[results:manifest.json:metrics.n_reconstructed]] carry a reconstructed one, and
[[results:manifest.json:metrics.n_omitted_no_ctdivol]] carry neither and are omitted
from every analysis that needs one.

### 2.8 Organ dose

Dose is tallied on an isotropic grid over the scan-covering geometry, with the number
of longitudinal stations set by the scan length and the nominal collimation, and is
reported per organ as the mass-weighted mean over the segmented voxels of that organ,
with its Monte-Carlo statistical uncertainty.

### 2.9 Index-based conversions, and how they are scored

Let $r$ be the ratio of absorbed organ dose to the organ-weighted CTDIvol index for
one organ in one series. Five conversions are compared, each predicting $r$ and
therefore predicting the dose from the index:

1. **a single factor** for the whole cohort;
2. **one factor per organ**, which is what a per-organ coefficient table offers;
3. **a scan-length term**, fitted as $\log r = a + b \log n_z$ on the number of
   longitudinal stations;
4. **scan length and a per-organ offset**, which is everything an index can carry;
5. **scan length and patient size**, with size as the effective diameter derived from
   the segmented body volume and the scan length.

All are fitted in log ratio, because the quantity is a multiplicative factor spanning
several fold and its errors are relative.

Each is scored under leave-one-patient-out cross-validation: for each series, the
conversion is fitted on the other [[results:manifest.json:metrics.n_scaled]] minus one
series and evaluated on the held-out one. Fitting twelve organ offsets on thirty
patients and reporting the error on those same thirty is optimistic by construction,
and thirty is small enough for that to matter. Every error reported below is on a
patient the fit did not see.

---

## 3. Results

### 3.1 Verification

At the centre volume of interest the engine differs from PENELOPE by
[[results:manifest.json:metrics.tg195_centre_abs_pct|.3f]] %, which is
[[results:manifest.json:metrics.tg195_centre_n_sigma|.2f]] combined standard
deviations (figure 3). The difference from the other three published codes is larger
and in the same direction at the centre, and smaller at the perimeter; showing all
four is what makes the choice of yardstick auditable rather than convenient. The
phantom length term is measured and null.

### 3.2 Cohort

[[results:cohort_overlap.json:selection_funnel.index_rows]] index rows reduce
to [[results:cohort_overlap.json:selection_funnel.kept]] series through the
funnel of figure 1, of which
[[results:cohort_overlap.json:selection_funnel.probed]] were probed and
[[results:cohort_overlap.json:selection_funnel.n_probe_rejected]] rejected. The
density gate leaves [[results:manifest.json:metrics.n_eligible]] eligible series
(figure 2), and [[results:manifest.json:metrics.n_scaled]] of those carry a CTDIvol
and enter the analysis.

### 3.3 Absorbed organ doses

Across [[results:manifest.json:metrics.n_points]] organ-series pairs the median
absorbed organ dose is [[results:manifest.json:metrics.dose_median_mgy|.1f]] mGy, with
a range of [[results:manifest.json:metrics.dose_min_mgy|.1f]] to
[[results:manifest.json:metrics.dose_max_mgy|.1f]] mGy. Per-organ values by vendor are
given in table 1 and figure 6; with six to nine series per vendor the cohort is not
powered for a vendor comparison and none is offered.

[[table:organ_doses]]

Plotted against the organ-weighted index on the same anatomy (figure 4), the two are
correlated — Pearson $r$ = [[results:manifest.json:metrics.pearson_r_all|.2f]] over all
[[results:manifest.json:metrics.n_scaled]] series and
[[results:manifest.json:metrics.pearson_r_recorded|.2f]] over the
[[results:manifest.json:metrics.n_recorded]] with a recorded CTDIvol — and the median
ratio of dose to index is
[[results:manifest.json:metrics.ratio_median|.2f]]. That the two differ is not the
result; how far apart they remain after every available correction is.

### 3.4 The floor on an index-based conversion

Figure 5a gives the held-out error of each conversion. A single factor for the whole
cohort recovers absorbed organ dose to a median
[[results:manifest.json:metrics.ceiling_global_factor_median_pct|.0f]] %, with
[[results:manifest.json:metrics.ceiling_global_factor_p90_pct|.0f]] % at the ninetieth
percentile.

**One factor per organ does not improve on it.** Cross-validated, the per-organ
conversion is slightly worse — a median
[[results:manifest.json:metrics.ceiling_per_organ_factor_median_pct|.0f]] % against
[[results:manifest.json:metrics.ceiling_global_factor_median_pct|.0f]] % — and the
fraction of organs recovered to within 20 % moves from
[[results:manifest.json:metrics.ceiling_global_factor_within20|.0%]] to
[[results:manifest.json:metrics.ceiling_per_organ_factor_within20|.0%]]. Twelve organ
means fitted on twenty-nine patients do not transfer to the thirtieth. This is the
form in which published organ-dose coefficient libraries are used [6,7], and on this
cohort that form carries no information a single number does not.

A scan-length term does improve on it, to a median
[[results:manifest.json:metrics.ceiling_scan_length_median_pct|.0f]] % and
[[results:manifest.json:metrics.ceiling_scan_length_p90_pct|.0f]] % at the ninetieth
percentile. This is expected rather than surprising: CTDIvol is defined per rotation,
dose-length product is the quantity that carries length [5], and the fitted slope on
$\log n_z$ is [[results:manifest.json:metrics.length_slope|.2f]] — close enough to one
that the dependence is largely accumulation.

Adding to the length term everything else an index could know changes little. A
per-organ offset on top of length reaches
[[results:manifest.json:metrics.ceiling_scan_length_and_organ_median_pct|.0f]] %, and
the patient's effective diameter reaches
[[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] %, with
[[results:manifest.json:metrics.ceiling_scan_length_and_size_p90_pct|.0f]] % at the
ninetieth percentile and
[[results:manifest.json:metrics.ceiling_scan_length_and_size_within20|.0%]] of organs
inside 20 %. That is the floor: nothing an index carries closes the remaining gap.

### 3.5 The residual is a property of the patient

Figure 5b decomposes the variance of the log index-to-dose ratio.
[[results:manifest.json:metrics.variance_between_patient|.0%]] of it lies between
patients, [[results:manifest.json:metrics.variance_between_organ|.0%]] between organs
and [[results:manifest.json:metrics.variance_between_vendor|.0%]] between vendors.

The same fact stated the other way: within one patient, a single number converts the
index to absorbed dose for every one of that patient's organs to within a factor of
[[results:manifest.json:metrics.ratio_within_patient_fold|.2f]]; across patients that
number ranges from [[results:manifest.json:metrics.ratio_patient_min|.2f]] to
[[results:manifest.json:metrics.ratio_patient_max|.2f]], a span of
[[results:manifest.json:metrics.ratio_patient_fold|.1f]]-fold. The information an
index withholds is not organ-specific. It is patient-specific, and it is nearly common
to all of that patient's organs at once.

This explains section 3.4 completely. A per-organ coefficient addresses the
[[results:manifest.json:metrics.variance_between_organ|.0%]]; it cannot address the
[[results:manifest.json:metrics.variance_between_patient|.0%]], and cross-validated it
does not even secure the [[results:manifest.json:metrics.variance_between_organ|.0%]].

### 3.6 Patient size does not stand in for it

The obvious candidate for a patient-level correction is patient size, which is what
size-specific dose estimates apply [3,4]. It does not carry this. The correlation
between the patient-level factor and the effective diameter is Pearson $r$ =
[[results:manifest.json:metrics.size_pearson_r|.2f]] in log, over a cohort spanning
[[results:conversion_ceiling.json:size_dependence.effective_diameter_cm_range[0]|.1f]]
to
[[results:conversion_ceiling.json:size_dependence.effective_diameter_cm_range[1]|.1f]]
cm, and adding size on top of the length term moves the median error from
[[results:manifest.json:metrics.ceiling_scan_length_median_pct|.0f]] % to
[[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] %, the
same place a per-organ offset reaches.

### 3.7 The residual is physical, not statistical

Per-organ Monte-Carlo statistical uncertainty is
[[results:manifest.json:metrics.mc_sigma_median_pct|.3f]] % of the organ dose at the
median and [[results:manifest.json:metrics.mc_sigma_max_pct|.2f]] % at worst. The floor
of section 3.4 is more than three orders of magnitude above it. The scatter that no
index-based conversion removes is a property of the transport, not of the sampling.

### 3.8 Robustness

Restricting the analysis to the [[results:manifest.json:metrics.n_recorded]] series
that carry a recorded CTDIvol, rather than a reconstructed one, does not change the
index-to-dose relationship: the correlation is
[[results:manifest.json:metrics.pearson_r_recorded|.2f]] against
[[results:manifest.json:metrics.pearson_r_all|.2f]], and the median ratio is
[[results:manifest.json:metrics.y_over_x_median_recorded|.2f]] against
[[results:manifest.json:metrics.y_over_x_median|.2f]]. No additional Monte Carlo was
run for this check.

---

## 4. Discussion

The result is a limit on a class of methods, and it is quantitative. Every conversion
from a dose index to an organ dose — whether by a size correction, a length factor or
a coefficient table — is estimating a patient-level quantity from measurements that do
not contain it. On this cohort, the best such conversion misses absorbed organ dose by
a median of [[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] %
and by [[results:manifest.json:metrics.ceiling_scan_length_and_size_p90_pct|.0f]] % at
the ninetieth percentile, and the part it misses is nearly the same multiplicative
error for every organ in a given patient.

That last property is the useful one, and it cuts both ways. It means an index is a
sound instrument for questions internal to a patient: which organ received more, how
one protocol compares with another on the same person, whether a change in modulation
moved dose from one organ to another. Within a patient the conversion factor is
constant to within
[[results:manifest.json:metrics.ratio_within_patient_fold|.2f]]-fold, so those
comparisons survive. It also means an index is a poor instrument for questions across
patients in absolute milligray, which is exactly what epidemiological and
risk-estimation uses require, because there the
[[results:manifest.json:metrics.ratio_patient_fold|.1f]]-fold between-patient span is
the whole of the signal being estimated.

The negative result on per-organ coefficients deserves stating carefully. It does not
say that published coefficient libraries [6,7] are wrong; they are computed on
reference phantoms and are correct for those phantoms. It says that the residual they
are asked to absorb, when applied to a real patient through an index, is not organ
structured. Cross-validated on this cohort, twelve fitted organ coefficients did not
beat one number — and a table with more coefficients, fitted on more organs, would be
fitting more finely into the [[results:manifest.json:metrics.variance_between_organ|.0%]]
of variance that organ identity explains.

Whether the floor found here is the floor everywhere is not something one cohort can
settle. It is a floor on abdominal CT, on twelve abdominal organs, in a cohort selected
for having per-slice tube current recorded. What is more likely to generalise is the
structure of the residual rather than its size: an index conditions on the scanner and
the protocol, and the transport it omits is a function of the patient.

---

## 5. Limitations

The cohort is [[results:manifest.json:metrics.n_scaled]] series across four vendors,
six to nine per vendor. That is adequate for the patient-level question, which has
[[results:manifest.json:metrics.n_scaled]] independent units, and inadequate for a
vendor-level one, which would have four. No vendor claim is made; table 1 and figure 6
are descriptive.

There is no ground-truth absorbed dose in a patient. The engine is verified against a
published reference phantom case [18] with a measured uncertainty, and the patient
doses inherit that verification, but they are not independently measured. What the
verification supports is the transport; what it cannot support is the segmentation, the
HU-to-density mapping, or the source model as applied to a particular scanner.

Organ boundaries come from an automatic segmentation [15] applied uniformly. Its errors
propagate into both the index and the dose, since both are computed over the same
masks, and would tend to reduce rather than inflate the difference between them.

The eligibility gate excludes series with more than 1 cm³ of out-of-calibration
material. Patients with implants are therefore under-represented, and the floor
reported here is a floor for anatomy the density calibration covers.

The scan-length term is fitted on the number of longitudinal stations, which is derived
from the scan length and the nominal collimation, not on a directly recorded irradiated
length. The fitted slope of [[results:manifest.json:metrics.length_slope|.2f]] is
reported so that the reader can see how much of that term is accumulation.

Doses are computed for the acquisition as reconstructed and recorded. Over-ranging,
localiser exposures and any repeat series are outside the scope of the metadata used.

---

## 6. Conclusions

Absorbed organ dose in CT can be recovered from an organ-weighted CTDIvol index to a
median of [[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] %
and no better, held out on patients the conversion has not seen. A per-organ coefficient
does not improve on a single conversion factor for the whole cohort, because
[[results:manifest.json:metrics.variance_between_patient|.0%]] of the variance in the
index-to-dose ratio is between patients and only
[[results:manifest.json:metrics.variance_between_organ|.0%]] is between organs. Patient
size, the standard patient-level correction, does not carry it either. The residual is
more than three orders of magnitude above the Monte-Carlo statistical uncertainty, so it
is physical: it is the transport that an index does not perform.

---

## Data and code

The software is under the MIT licence at
`https://github.com/Institute-of-One/ct-dosemc-core`, with the frozen result tables and
the commands that regenerate every figure. No imaging is redistributed: the collection,
Series Instance UID, licence and retrieval date of every series are recorded so that each
can be re-fetched from the archive [19,20]. Every number reported here is resolved at
build time from a machine-readable result file, and the build fails if a number cannot be
traced to one.

## Acknowledgements

The author thanks the maintainers of MC-GPU, SpekPy, PENELOPE and TotalSegmentator, whose
published work this pipeline is assembled from.

## Declaration of competing interest

The author is Representative Director of LISIT Co., Ltd., which funds Institute of One.
No other competing interest is declared.

## Funding

This research received no external funding.

## References

1. C. H. McCollough, S. Leng, L. Yu, D. D. Cody, J. M. Boone, and M. F. McNitt-Gray, "CT dose index and patient dose: they are not the same thing," *Radiology* **259**(2), 311–316 (2011) [doi:10.1148/radiol.11101800].
2. C. H. McCollough, D. D. Cody, S. Edyvean, *et al.*, *The Measurement, Reporting, and Management of Radiation Dose in CT*, AAPM Report 96 (American Association of Physicists in Medicine, 2008) [doi:10.37206/97].
3. J. M. Boone, K. J. Strauss, D. D. Cody, C. H. McCollough, M. F. McNitt-Gray, and T. L. Toth, *Size-Specific Dose Estimates (SSDE) in Pediatric and Adult Body CT Examinations*, AAPM Report 204 (American Association of Physicists in Medicine, 2011) [doi:10.37206/143].
4. C. H. McCollough, D. Bakalyar, M. Bostani, *et al.*, *Use of Water Equivalent Diameter for Calculating Patient Size and Size-Specific Dose Estimates (SSDE) in CT*, AAPM Report 220 (American Association of Physicists in Medicine, 2014) [doi:10.37206/146].
5. P. D. Deak, Y. Smal, and W. A. Kalender, "Multisection CT protocols: sex- and age-specific conversion factors used to determine effective dose from dose-length product," *Radiology* **257**(1), 158–166 (2010) [doi:10.1148/radiol.10100047].
6. C. Lee, K. P. Kim, D. Long, *et al.*, "Organ doses for reference adult male and female undergoing computed tomography estimated by Monte Carlo simulations," *Med. Phys.* **39**(4), 2129–2146 (2012) [doi:10.1118/1.3693052].
7. C. Lee, K. P. Kim, D. Bolch, B. E. Moroz, and L. Folio, "NCICT: a computational solution to estimate organ doses for pediatric and adult patients undergoing CT scans," *J. Radiol. Prot.* **35**(4), 891–909 (2015) [doi:10.1088/0952-4746/35/4/891].
8. X. Tian, X. Li, W. P. Segars, D. P. Frush, and E. Samei, "Prospective estimation of organ dose in CT under tube current modulation," *Med. Phys.* **42**(4), 1575–1585 (2015) [doi:10.1118/1.4907955].
9. S. Yamamoto, *ctsegdose-core: anatomy-weighted CTDIvol from routine CT metadata, using deep-learning organ segmentation*, v0.1.1, Zenodo (2026) [doi:10.5281/zenodo.21817307].
10. A. Badal and A. Badano, "Accelerating Monte Carlo simulations of photon transport in a voxelized geometry using a massively parallel Graphics Processing Unit," *Med. Phys.* **36**(11), 4878–4880 (2009) [doi:10.1118/1.3231824].
11. G. Poludniowski, A. Omar, R. Bujila, and P. Andreo, "Technical Note: SpekPy v2.0 — a software toolkit for modeling x-ray tube spectra," *Med. Phys.* **48**(7), 3630–3637 (2021) [doi:10.1002/mp.14945].
12. R. Bujila, A. Omar, and G. Poludniowski, "A validation of SpekPy: a software toolkit for modelling X-ray tube spectra," *Phys. Med.* **75**, 44–54 (2020) [doi:10.1016/j.ejmp.2020.04.026].
13. U. Schneider, E. Pedroni, and A. Lomax, "The calibration of CT Hounsfield units for radiotherapy treatment planning," *Phys. Med. Biol.* **41**(1), 111–124 (1996) [doi:10.1088/0031-9155/41/1/009].
14. W. Schneider, T. Bortfeld, and W. Schlegel, "Correlation between CT numbers and tissue parameters needed for Monte Carlo simulations of clinical dose distributions," *Phys. Med. Biol.* **45**(2), 459–478 (2000) [doi:10.1088/0031-9155/45/2/314].
15. J. Wasserthal, H.-C. Breit, M. T. Meyer, *et al.*, "TotalSegmentator: robust segmentation of 104 anatomic structures in CT images," *Radiol. Artif. Intell.* **5**(5), e230024 (2023) [doi:10.1148/ryai.230024].
16. F. Salvat, J. M. Fernández-Varea, and J. Sempau, *PENELOPE — a code system for Monte Carlo simulation of electron and photon transport* (NEA-OECD, Issy-les-Moulineaux, 2006).
17. A. C. Turner, D. Zhang, H. J. Kim, *et al.*, "A method to generate equivalent energy spectra and filtration models based on measurement for multidetector CT Monte Carlo dosimetry simulations," *Med. Phys.* **36**(6), 2154–2164 (2009) [doi:10.1118/1.3117683].
18. I. Sechopoulos, E. S. M. Ali, A. Badal, *et al.*, "Monte Carlo reference data sets for imaging research: executive summary of the report of AAPM Research Committee Task Group 195," *Med. Phys.* **42**(10), 5679–5691 (2015) [doi:10.1118/1.4928676].
19. K. Clark, B. Vendt, K. Smith, *et al.*, "The Cancer Imaging Archive (TCIA): maintaining and operating a public information repository," *J. Digit. Imaging* **26**(6), 1045–1057 (2013) [doi:10.1007/s10278-013-9622-7].
20. A. M. Moawad, D. Fuentes, M. M. ElBanan, *et al.*, "Multimodality annotated hepatocellular carcinoma data set including pre- and post-TACE with imaging segmentation," *Sci. Data* **10**, 33 (2023) [doi:10.1038/s41597-023-01928-3].
21. S. Yamamoto, *ctdose-core: open, auditable CT dose surveillance from DICOM, with a physics reconstruction when the dose attributes are missing*, v0.1.1, Zenodo (2026) [doi:10.5281/zenodo.21636719].

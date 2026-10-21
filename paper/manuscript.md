<!--
Every number in this file is a [[results:...]] marker resolved from paper/frozen/
at build time. A marker that cannot be resolved is a build error, and a test fails
if a frozen metric appears here as a typed literal. Do not type numbers.
-->

# Between-patient variation sets the limit on index-based organ dose in abdominal CT: a cross-validated bound on five conversions

**Shuji Yamamoto**

Institute of One, LISIT Co., Ltd., Tokyo 150-0044, Japan

E-mail: yamamoto@lisit.jp

ORCID: 0000-0001-9211-1071

## Abstract

**Objective.** The volume CT dose index is a scanner output, not a patient dose, and the
field converts it with size corrections, dose-length-product factors and per-organ
coefficient libraries. How close such a conversion can get has not been measured against
transport on the same anatomy. We measure five.

**Approach.** A GPU Monte-Carlo pipeline computes absorbed organ dose in patient anatomy
from routine metadata alone, verified against AAPM TG-195 Case 4 with a replica-measured
uncertainty and a yardstick fixed beforehand. On
[[results:manifest.json:metrics.n_scaled]] multi-vendor abdominal CT series from a public
archive — [[results:manifest.json:metrics.n_points]] organ-series pairs across
[[results:manifest.json:metrics.n_organs]] organs — five conversions of increasing
richness are scored under leave-one-patient-out cross-validation.

**Main results.** At the centre volume of interest the engine differs from PENELOPE
by [[results:manifest.json:metrics.tg195_centre_abs_pct|.3f]] %, or
[[results:manifest.json:metrics.tg195_centre_n_sigma|.2f]] combined standard
deviations. A single conversion factor recovers absorbed organ dose to a median
[[results:manifest.json:metrics.ceiling_global_factor_median_pct|.0f]] %; one factor per
organ does not improve on it
([[results:manifest.json:metrics.ceiling_per_organ_factor_median_pct|.0f]] %); a
scan-length term reaches
[[results:manifest.json:metrics.ceiling_scan_length_median_pct|.0f]] %, and adding either
organ identity or patient size to it reaches
[[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] % either way.
[[results:manifest.json:metrics.variance_between_patient|.0%]] of the variance in the
dose-to-index ratio lies between patients and
[[results:manifest.json:metrics.variance_between_organ|.0%]] between organs, and the
residual is three orders of magnitude above the Monte-Carlo statistical uncertainty, so it
is physical.

**Significance.** What an index withholds is a property of the patient, not of the organ, so
no coefficient table or size correction can supply it. Where a median
[[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] % suffices —
protocol comparison, registry-scale surveillance — a single factor with a scan-length term
is what should be used, and a coefficient library adds parameters without accuracy. Where it
does not, the missing quantity is transport through that patient's own anatomy, computed
here from the metadata a routine CT already records, with no added exposure and no matched
phantom.

**Keywords:** computed tomography, organ dose, Monte Carlo, CTDIvol, dose index,
cross-validation

---

## 1. Introduction

The volume CT dose index is a property of the scanner and a standard phantom, not of
the patient in it, and saying so has been necessary often enough to have its own
paper (McCollough et al 2011). It is nonetheless the number every scanner reports, the number archived in
dose-monitoring systems, and therefore the number from which patient dose is
estimated in practice (McCollough et al 2008).

The field has three established ways of getting from that index to something closer
to a dose. Size-specific dose estimates rescale CTDIvol by the patient's attenuating
size (Boone et al 2011), with water-equivalent diameter as the size that matters (McCollough et al 2014). Dose-length
product is converted to effective dose by protocol-specific factors (Deak et al 2010). And organ
dose is estimated from libraries of per-organ coefficients, computed once by Monte
Carlo on reference phantoms and looked up thereafter (Lee et al 2011, Lee et al 2015), including under tube
current modulation (Tian et al 2015).

All three are conversions from an index. Each replaces transport through this
patient's anatomy with a coefficient obtained from someone else's. The question this
paper asks is not whether such a conversion is exact — it is not, and no one claims
it is — but how close it can get, and what the irreducible part is made of.

That question needs absorbed organ dose on the same anatomy as the index, which is
what we compute. A companion study reports an organ-weighted CTDIvol index: CTDIvol
multiplied by the tube-current mean over each segmented organ relative to the scan
mean (Yamamoto 2026a). It is an index, and a good one: it is organ-specific and it carries the
longitudinal modulation. It does not transport photons. Against it we place absorbed
dose in milligray, computed by Monte Carlo through each patient's own segmented,
density-mapped anatomy, with every dose coefficient computed rather than looked up.

We then fit conversions of increasing richness from the index to the dose — a single
factor, a per-organ factor, a scan-length term, and combinations — and score each on
patients the fit has not seen. The result is a floor, and a decomposition of what
sits beneath it.

**What this paper does not claim.** It does not claim that an index and an absorbed
dose are the same quantity, nor that anyone believes they are. It does not claim
novelty for GPU Monte-Carlo photon transport (Badal and Badano 2009), for spectrum modelling (Bujila et al 2020, Poludniowski et al 2021),
for HU-to-density calibration (Schneider U et al 1996, Schneider W et al 2000), or for deep-learning organ segmentation (Wasserthal et al 2023);
each is used as published. It does not claim that a scan-length term is a discovery:
CTDIvol is defined per rotation and carries no length, dose-length product is the
standard quantity that does, and the fitted length dependence is close to
proportional. The term is included because a conversion that omitted it would be a
straw man, and its slope is reported so that a reader can judge that for themselves.

---

## 2. Methods

### 2.1 Monte-Carlo engine and build provenance

Photon transport uses MC-GPU (Badal and Badano 2009), a public-domain voxelised Monte-Carlo code, built
locally. The build is pinned: the source patches applied, their kind, and the
SHA-256 of the resulting binary are recorded in a build manifest that ships with the
software. Patches are of three kinds — defect fixes, portability changes, and
capacity increases that raise a compile-time array bound without touching the
physics — and each capacity patch records the bound, the new value, and why it was
needed. Two were required here: the Schneider tissue groups at 140 kVp exceed the
upstream limits on Compton shells and on Rayleigh energy bins.

Material cross-sections are generated locally from the photon subset of the PENELOPE
2006 database (Salvat et al 2006) rather than transcribed, so that no coefficient table is
redistributed and each material file carries the digest of the data it came from.

### 2.2 Source model

X-ray spectra come from SpekPy (Bujila et al 2020, Poludniowski et al 2021), which supplies the spectrum, the half-value
layer and the absolute tube output for each tube potential. The source is modelled as
an equivalent spectrum and filtration in the manner of Turner *et al* (2009), with a
bowtie profile represented as a set of sub-fans, each carrying its own spectrum. The
profiles are derived from the published measurements of Yang *et al* (2019), which
cover three vendors; the fourth is represented by the cross-vendor average with its
spread declared.
Geometry, collimation, source-to-axis distance and the number of projections come
from the series metadata.

### 2.3 Verification against TG-195 Case 4

The engine is verified against Case 4 of AAPM Task Group 195 (Sechopoulos et al 2015), the voxelised
phantom case with published results from four independent codes.

The scored quantity is the task group's own and is compared in the task group's own units:
the energy imparted in a volume of interest, normalised per source photon and reported in
eV per photon, so that it does not depend on the number of histories run. Two volumes are
scored, both cylinders of
1 cm diameter and 10 cm length lying along the rotation axis of the phantom: the central
one centred on that axis, and the peripheral one with its axis 15 cm from it. The
peripheral volume is scored at every non-overlapping azimuth around that circle and
averaged, which the task group permits and which also provides a symmetry test — the
spread across azimuths must agree with the spread across independent seeds, and it is this
test that caught a defect in the random number stream. The reference values the relative
differences are taken against are the four codes' published results for the same two
volumes in that report; PENELOPE's is the one the difference is quoted against, and the
other three are reported beside it.

Two further properties of this verification matter for what follows.

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

Series were selected from a public archive (Clark et al 2013, Moawad et al 2023) by a recorded funnel that begins
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

A voxel is out of calibration when it lies inside the body contour and its value reaches
the twelve-bit saturation ceiling of
[[results:manifest.json:metrics.density_gate_hu_ceiling|.0f]] HU; clipping at the ceiling
and exceeding it are
treated identically, so the measure does not depend on how a vendor handles overflow. Such
voxels are metal, concentrated contrast, or artefact, and are not tissue: a compact
implant has an atomic number the Schneider conversion cannot represent, and its
photoelectric cross-section would be misassigned.

A series is excluded if its largest connected out-of-calibration component reaches
[[results:density_eligibility.json:threshold_cm3|.0f]] cm³. The threshold is not fitted to
any series: the cohort's largest components fall in two groups, the biggest among the
eligible series being
[[results:manifest.json:metrics.density_gate_largest_kept_cm3|.2f]] cm³ and the smallest
among the excluded ones
[[results:manifest.json:metrics.density_gate_smallest_dropped_cm3|.2f]] cm³, and the
threshold sits in that gap (figure 2). It and the criterion were
declared before the volumes were computed. Of
[[results:density_eligibility.json:n_assessed]] assessed series,
[[results:manifest.json:metrics.n_eligible]] are eligible and
[[results:density_eligibility.json:n_excluded]] are excluded (figure 2). The
distance from the offending component to the nearest scored organ is reported but is
not part of the gate.

### 2.6 Segmentation, density and materials

Organ boundaries come from TotalSegmentator (Wasserthal et al 2023) run at inference on each series, so
that no manual contour enters the pipeline and the same procedure applies to every
vendor. Hounsfield units are mapped to mass density and to Schneider tissue groups
(Schneider U et al 1996, Schneider W et al 2000); voxels above the top calibration breakpoint are held at its density and
counted, and it is that count the eligibility gate reads.

### 2.7 CTDIvol normalisation

Absorbed dose per emitted photon is converted to dose per examination by a scale
derived from a simulated CTDI phantom measurement at the same tube potential and
vendor, matched to the CTDIvol the series carries. Where the series records a
CTDIvol, that value is used; where it does not, the value reconstructed from scanner
model and technique by a companion tool is used, and the two are distinguished
throughout (Yamamoto 2026b). Of [[results:manifest.json:metrics.n_eligible]] eligible series,
[[results:manifest.json:metrics.n_recorded]] carry a recorded CTDIvol,
[[results:manifest.json:metrics.n_reconstructed]] carry a reconstructed one, and
[[results:manifest.json:metrics.n_omitted_no_ctdivol]] carry neither and are omitted
from every analysis that needs one.

### 2.8 Organ dose

Dose is tallied on an isotropic grid of
[[results:resample_cost.json:dose_grid_mm|.1f]] mm over the scan-covering geometry, with
the number of longitudinal stations set by the scan length and the nominal collimation,
and is reported per organ as the mass-weighted mean over the segmented voxels of that
organ, with its Monte-Carlo statistical uncertainty. Histories are set per series so that
the statistical uncertainty of every reported organ dose stays below a fixed target; the
uncertainty achieved is reported in section 3.7 rather than the number of histories,
because it is the quantity the result depends on. Transport is deterministic given the
recorded random seed.

Masks and densities reach that grid as volume-conserving zooms from the native series
voxels, and what the zoom costs is measured rather than assumed. Over the
[[results:resample_cost.json:n_series]] series, organ mass is preserved to within
[[results:resample_cost.json:by_organ.liver.median_abs_pct|.1f]] % at the median for the
liver and [[results:resample_cost.json:by_organ.colon.median_abs_pct|.1f]] % for the
colon. The cost is carried by the smallest organs: the right adrenal gland, a few grams of
tissue, shifts by [[results:resample_cost.json:by_organ.adrenal_gland_right.median_abs_pct|.1f]] %
at the median and [[results:resample_cost.json:by_organ.adrenal_gland_right.max_abs_pct|.1f]] %
in the worst series. The adrenal glands are therefore the organs whose dose is least
secure here, and they are reported with the rest rather than dropped, because dropping the
organs a method serves worst would overstate how well the method performs.

### 2.9 Index-based conversions, and how they are scored

Let $r$ be the dose-to-index ratio: absorbed organ dose divided by the organ-weighted
CTDIvol index, for one organ in one series. It is called the dose-to-index ratio
throughout, in that order, because that is the order of the division. Five conversions are
compared, each predicting $r$ and therefore predicting the dose from the index:

1. **a single factor** for the whole cohort;
2. **one factor per organ**, which is what a per-organ coefficient table offers;
3. **a scan-length term**, fitted here on this cohort rather than taken from any
   published formula, as $\log r = a + b \log n_z$ on the number of
   longitudinal stations;
4. **scan length and a per-organ offset**, which is everything an index can carry;
5. **scan length and patient size**, with size as the effective diameter derived from
   the segmented body volume and the scan length.

All are fitted in log ratio, because the quantity is a multiplicative factor spanning
several fold and its errors are relative.

Each is scored under leave-one-patient-out cross-validation. Every series takes a turn as
the held-out one: the conversion is re-fitted from scratch on the other
[[results:manifest.json:metrics.n_scaled]] minus one series, and the error is recorded on
the series left out — [[results:manifest.json:metrics.n_scaled]] fits per conversion, and
every organ in the cohort contributing exactly one held-out error. No conversion is ever
scored on a patient it was fitted on. Fitting twelve organ offsets on thirty patients and
reporting the error on those same thirty is optimistic by construction, and thirty is
small enough for that to matter.

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
given in table 1, whose caption states what the table is and is not powered to support.

[[table:organ_doses]]

Plotted against the organ-weighted index on the same anatomy (figure 4), the two are
correlated — Pearson $r$ = [[results:manifest.json:metrics.pearson_r_all|.2f]] over all
[[results:manifest.json:metrics.n_scaled]] series and
[[results:manifest.json:metrics.pearson_r_recorded|.2f]] over the
[[results:manifest.json:metrics.n_recorded]] with a recorded CTDIvol — and the median
ratio of dose to index is
[[results:manifest.json:metrics.ratio_median|.2f]]. That the two differ is not the
result; how far apart they remain after every available correction is.

### 3.4 How close an index-based conversion gets

Every error in this section is a held-out error, in the sense of section 2.9: the
conversion was fitted without the patient it is scored on. Figure 5a gives them. A single
factor for the whole cohort recovers absorbed organ dose to a median
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
form in which published organ-dose coefficient libraries are used (Lee et al 2011, Lee et al 2015), and on this
cohort that form carries no information a single number does not.

A scan-length term does improve on it, to a median
[[results:manifest.json:metrics.ceiling_scan_length_median_pct|.0f]] % and
[[results:manifest.json:metrics.ceiling_scan_length_p90_pct|.0f]] % at the ninetieth
percentile. This is expected rather than surprising: CTDIvol is defined per rotation,
dose-length product is the quantity that carries length (Deak et al 2010), and the fitted slope on
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

Figure 5b decomposes the variance of the log dose-to-index ratio.
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
size-specific dose estimates apply (Boone et al 2011, McCollough et al 2014). It does not carry this. The correlation
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
relationship between index and dose: the correlation is
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
itself the quantity being estimated.

The negative result on per-organ coefficients deserves stating carefully. It does not
say that published coefficient libraries (Lee et al 2011, Lee et al 2015) are wrong; they are computed on
reference phantoms and are correct for those phantoms. It says that the residual they
are asked to absorb, when applied to a real patient through an index, is not organ
structured. Cross-validated on this cohort, twelve fitted organ coefficients did not
beat one number — and a table with more coefficients, fitted on more organs, would be
fitting more finely into the [[results:manifest.json:metrics.variance_between_organ|.0%]]
of variance that organ identity explains.

*What this adds to what is already known.* That a Monte-Carlo engine can reproduce measured
dose is established, and real-time patient-specific engines are in use (Sharma et al 2019); so is the
observation that index-based surrogates disagree with each other and with transport
(Ria et al 2021). What has not been available is the size of the gap that remains after every
correction an index can carry, measured on the same anatomy by the same transport, and
held out. That is the number this paper supplies, and the use for it is immediate: a centre
deciding whether to adopt a per-organ coefficient table over a single factor now has a
measured answer, and it is that the table does not repay the effort. A centre that needs organ
dose to better than a third needs the anatomy, not a better coefficient.

*What this does not establish.* The quantity here is absorbed organ dose, not risk. Which
surrogate suits which question is a separate matter and has been compared elsewhere across a
clinical population (Ria et al 2021); a risk statement additionally needs age and sex, which this
cohort does not carry — the public archive supplies the images and the acquisition metadata,
not the demographics — and needs a risk model this paper does not use. The result is
therefore about how well a conversion recovers dose, and says nothing about how well dose
predicts detriment.

<!-- scope-of-claim -->
Whether the floor found here is the floor everywhere is not something one cohort can
settle, and it is not something five conversions can settle either. The bound is over
the five conversions scored in section 2.9 — a single cohort factor, one factor per
organ, a scan-length term, and that term combined with either the organ or the patient's
size — each cross-validated on this cohort. It is a floor on those, on abdominal CT, on
twelve abdominal organs, in a cohort selected for having per-slice tube current recorded.
It is not a proof that no index-based conversion can do better: a richer predictor,
given more of the patient than an index carries, is not excluded by anything measured
here. What is more likely to generalise is the
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
published reference phantom case (Sechopoulos et al 2015) with a measured uncertainty, and the patient
doses inherit that verification, but they are not independently measured. What the
verification supports is the transport; what it cannot support is the segmentation, the
HU-to-density mapping, or the source model as applied to a particular scanner.

Organ boundaries come from an automatic segmentation (Wasserthal et al 2023) applied uniformly. Its errors
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
dose-to-index ratio is between patients and only
[[results:manifest.json:metrics.variance_between_organ|.0%]] is between organs. Patient
size, the standard patient-level correction, does not carry it either. The residual is
more than three orders of magnitude above the Monte-Carlo statistical uncertainty, so it
is physical: it is the transport that an index does not perform.

What follows for practice is specific. Where a median of
[[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] %, with
[[results:manifest.json:metrics.ceiling_scan_length_and_size_p90_pct|.0f]] % at the
ninetieth percentile, is adequate — protocol comparison, registry-scale surveillance,
tracking a department against itself — a single conversion factor with a scan-length term
is the whole of what an index can offer, and is what should be used. A per-organ
coefficient library adds parameters and maintenance without adding accuracy, and the
measurement saying so is cross-validated rather than asserted.

Where that is not adequate — a dose compared against an organ-level threshold, or carried
into an individual risk estimate — the missing quantity is the transport through that
patient's own anatomy, which no refinement of the index supplies. The step is a different
calculation, not a better coefficient, and its barrier is lower than it is usually taken
to be: every organ dose here was computed from the metadata a routine abdominal CT already
records, with no added exposure, no phantom matched to the patient, and no input a
department does not have.

---

## Acknowledgements

The author thanks the maintainers of MC-GPU, SpekPy, PENELOPE and TotalSegmentator, whose
published work this pipeline is assembled from.

A generative artificial intelligence assistant (Claude Opus 5, Anthropic) was used as a tool
in developing the software, in preparing figures from result files already computed, and in
language editing of this manuscript. It was not used to generate, impute or select any
reported value: every number in the text is resolved at build time from a machine-readable
result file produced by the code, and the build fails if a number cannot be traced to one.
The study design, the dosimetry, and all scientific judgements, interpretations and
conclusions are the author's, who takes full responsibility for the content of this paper.

The author is Representative Director of LISIT Co., Ltd., which funds Institute of One.
No other competing interest is declared.

This research received no external funding.

## Data availability

The data that support the findings of this study are openly available at the following
URL/DOI: https://doi.org/10.5281/zenodo.22233153.

That archive is the release of the software described here, under the MIT licence, and
holds the frozen result tables and the commands that regenerate every figure; development
continues at `https://github.com/Institute-of-One/ct-dosemc-core`. No imaging is
redistributed: the collection, Series Instance UID, licence and retrieval date of every
series are recorded so that each can be re-fetched from the archive (Clark et al 2013,
Moawad et al 2023). Every number reported here is resolved at build time from a
machine-readable result file, and the build fails if a number cannot be traced to one.

## References

Badal A and Badano A 2009 Accelerating Monte Carlo simulations of photon transport in a
voxelized geometry using a massively parallel Graphics Processing Unit *Med. Phys.*
**36** 4878–4880 [doi:10.1118/1.3231824]

Boone J M, Strauss K J, Cody D D, McCollough C H, McNitt-Gray M F and Toth T L 2011
*Size-Specific Dose Estimates (SSDE) in Pediatric and Adult Body CT Examinations* AAPM
Report 204 (College Park, MD: American Association of Physicists in Medicine)
[doi:10.37206/143]

Bujila R, Omar A and Poludniowski G 2020 A validation of SpekPy: a software toolkit for
modelling X-ray tube spectra *Phys. Med.* **75** 44–54 [doi:10.1016/j.ejmp.2020.04.026]

Clark K, Vendt B, Smith K, Freymann J, Kirby J, Koppel P, Moore S, Phillips S, Maffitt D,
Pringle M, Tarbox L and Prior F 2013 The Cancer Imaging Archive (TCIA): maintaining and
operating a public information repository *J. Digit. Imaging* **26** 1045–1057
[doi:10.1007/s10278-013-9622-7]

Deak P D, Smal Y and Kalender W A 2010 Multisection CT protocols: sex- and age-specific
conversion factors used to determine effective dose from dose-length product *Radiology*
**257** 158–166 [doi:10.1148/radiol.10100047]

Lee C, Kim K P, Long D, Fisher R, Tien C, Simon S L, Bouville A and Bolch W E 2011 Organ
doses for reference adult male and female undergoing computed tomography estimated by
Monte Carlo simulations *Med. Phys.* **38** 1196–1206 [doi:10.1118/1.3544658]

Lee C, Kim K P, Bolch W E, Moroz B E and Folio L 2015 NCICT: a computational solution to
estimate organ doses for pediatric and adult patients undergoing CT scans *J. Radiol.
Prot.* **35** 891–909 [doi:10.1088/0952-4746/35/4/891]

McCollough C H, Cody D D, Edyvean S, Geise R, Gould B, Keat N, Huda W, Judy P, Kalender W,
McNitt-Gray M, Morin R, Payne T, Stern S, Rothenberg L, Shrimpton P, Timmer J and Wilson C
2008 *The Measurement, Reporting, and Management of Radiation Dose in CT* AAPM Report 96
(College Park, MD: American Association of Physicists in Medicine) [doi:10.37206/97]

McCollough C H, Leng S, Yu L, Cody D D, Boone J M and McNitt-Gray M F 2011 CT dose index
and patient dose: they are not the same thing *Radiology* **259** 311–316
[doi:10.1148/radiol.11101800]

McCollough C H, Bakalyar D M, Bostani M, Brady S, Boedeker K, Boone J M, Chen-Mayer H H,
Christianson O I, Leng S, Li B, McNitt-Gray M F, Nilsen R A, Supanich M P and Wang J 2014
*Use of Water Equivalent Diameter for Calculating Patient Size and Size-Specific Dose
Estimates (SSDE) in CT* AAPM Report 220 (College Park, MD: American Association of
Physicists in Medicine) [doi:10.37206/146]

Moawad A M, Fuentes D, ElBanan M M, Shalaby A S, Guccione J, Kamel S, Jensen C T and
Elsayes K M 2023 Multimodality annotated hepatocellular carcinoma data set including pre-
and post-TACE with imaging segmentation *Sci. Data* **10** 33
[doi:10.1038/s41597-023-01928-3]

Poludniowski G, Omar A, Bujila R and Andreo P 2021 Technical Note: SpekPy v2.0 — a
software toolkit for modeling x-ray tube spectra *Med. Phys.* **48** 3630–3637
[doi:10.1002/mp.14945]

Ria F, Fu W, Hoye J, Segars W P, Kapadia A J and Samei E 2021 Comparison of 12 surrogates
to characterize CT radiation risk across a clinical population *Eur. Radiol.* **31**
7022–7030 [doi:10.1007/s00330-021-07753-9]

Salvat F, Fernández-Varea J M and Sempau J 2006 *PENELOPE — a code system for Monte Carlo
simulation of electron and photon transport* (Issy-les-Moulineaux: NEA-OECD)

Schneider U, Pedroni E and Lomax A 1996 The calibration of CT Hounsfield units for
radiotherapy treatment planning *Phys. Med. Biol.* **41** 111–124
[doi:10.1088/0031-9155/41/1/009]

Schneider W, Bortfeld T and Schlegel W 2000 Correlation between CT numbers and tissue
parameters needed for Monte Carlo simulations of clinical dose distributions *Phys. Med.
Biol.* **45** 459–478 [doi:10.1088/0031-9155/45/2/314]

Sechopoulos I, Ali E S M, Badal A, Badano A, Boone J M, Kyprianou I S, Mainegra-Hing E,
McMillan K L, McNitt-Gray M F, Rogers D W O, Samei E and Turner A C 2015 Monte Carlo
reference data sets for imaging research: executive summary of the report of AAPM Research
Committee Task Group 195 *Med. Phys.* **42** 5679–5691 [doi:10.1118/1.4928676]

Sharma S, Kapadia A, Fu W, Abadi E, Segars W P and Samei E 2019 A real-time Monte Carlo
tool for individualized dose estimations in clinical CT *Phys. Med. Biol.* **64** 215020
[doi:10.1088/1361-6560/ab467f]

Tian X, Li X, Segars W P, Frush D P and Samei E 2015 Prospective estimation of organ dose
in CT under tube current modulation *Med. Phys.* **42** 1575–1585 [doi:10.1118/1.4907955]

Turner A C, Zhang D, Kim H J, DeMarco J J, Cagnon C H, Angel E, Cody D D, Stevens D M,
Primak A N, McCollough C H and McNitt-Gray M F 2009 A method to generate equivalent energy
spectra and filtration models based on measurement for multidetector CT Monte Carlo
dosimetry simulations *Med. Phys.* **36** 2154–2164 [doi:10.1118/1.3117683]

Wasserthal J, Breit H-C, Meyer M T, Pradella M, Hinck D, Sauter A W, Heye T, Boll D T,
Cyriac J, Yang S, Bach M and Segeroth M 2023 TotalSegmentator: robust segmentation of 104
anatomic structures in CT images *Radiol. Artif. Intell.* **5** e230024
[doi:10.1148/ryai.230024]

Yamamoto S 2026a *ctsegdose-core: anatomy-weighted CTDIvol from routine CT metadata, using
deep-learning organ segmentation* v0.1.1 (Zenodo) [doi:10.5281/zenodo.21817307]

Yamamoto S 2026b *ctdose-core: open, auditable CT dose surveillance from DICOM, with a
physics reconstruction when the dose attributes are missing* v0.1.1 (Zenodo)
[doi:10.5281/zenodo.21636719]

Yang K, Ruan C, Li X and Liu B 2019 Data of CT bow tie filter profiles from three modern
CT scanners *Data in Brief* **25** 104261 [doi:10.1016/j.dib.2019.104261]. Licensed
CC BY 4.0

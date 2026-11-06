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

The volume CT dose index is a scanner output, not a patient dose, and the field converts
it with size corrections, dose-length-product factors and per-organ coefficient libraries.
How close such a conversion can get has never been measured against transport on the same
anatomy. A GPU Monte-Carlo pipeline computed absorbed organ dose in patient anatomy from
routine metadata, verified against AAPM TG-195 Case 4 with a measured uncertainty and a
yardstick fixed beforehand. On [[results:manifest.json:metrics.n_scaled]]
multi-vendor abdominal CT series from a public archive —
[[results:manifest.json:metrics.n_points]] organ-series pairs across
[[results:manifest.json:metrics.n_organs]] organs — five conversions of increasing
richness were scored under leave-one-patient-out cross-validation. The engine differed
from PENELOPE by [[results:manifest.json:metrics.tg195_centre_abs_pct|.3f]] % at the
centre volume of interest, or [[results:manifest.json:metrics.tg195_centre_n_sigma|.2f]]
combined standard deviations. A single factor recovered absorbed organ dose to a median
[[results:manifest.json:metrics.ceiling_global_factor_median_pct|.0f]] %; one
factor per organ did not improve on it
([[results:manifest.json:metrics.ceiling_per_organ_factor_median_pct|.0f]] %); a
scan-length term reached
[[results:manifest.json:metrics.ceiling_scan_length_median_pct|.0f]] %, and adding either
organ identity or patient size reached
[[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] % either
way. [[results:manifest.json:metrics.variance_between_patient|.0%]] of the variance in the
dose-to-index ratio lay between patients and
[[results:manifest.json:metrics.variance_between_organ|.0%]] between organs, and the
residual was three orders of magnitude above the Monte-Carlo statistical uncertainty, so
it is physical. What an index withholds is therefore patient-specific, not organ-specific,
and no coefficient table or size correction can supply it. Where a median
[[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] % suffices, a
single factor with a scan-length term should be used; where it does not, the missing
quantity is transport through the patient's own anatomy, computed here from routine CT
metadata.

**Keywords:** computed tomography, organ dose, Monte Carlo, CTDIvol, dose index,
cross-validation

## 1. Introduction

The volume CT dose index is a property of the scanner and a standard phantom, not of
the patient in it, and saying so has been necessary often enough to have its own
paper [[cite:mccollough2011]]. It is nonetheless the number every scanner reports, the number archived in
dose-monitoring systems, and therefore the number from which patient dose is
estimated in practice [[cite:mccollough2008]].

The field has three established ways of getting from that index to something closer
to a dose. Size-specific dose estimates rescale CTDIvol by the patient's attenuating
size [[cite:boone2011]], with water-equivalent diameter as the size that matters [[cite:mccollough2014]]. Dose-length
product is converted to effective dose by protocol-specific factors [[cite:deak2010]]. And organ
dose is estimated from libraries of per-organ coefficients, computed once by Monte
Carlo on reference phantoms and looked up thereafter [[cite:lee2011,lee2015]], including under tube
current modulation [[cite:tian2015]].

All three are conversions from an index, and each replaces transport through this
patient's anatomy with a coefficient obtained from someone else's. The question asked here
is not whether such a conversion is exact — it is not, and no one claims it is — but how
close it can get, and what the irreducible part is made of.

That question needs absorbed organ dose on the same anatomy as the index. A companion
study reports an organ-weighted CTDIvol index: CTDIvol multiplied by the tube-current mean
over each segmented organ relative to the scan mean [[cite:yamamoto2026tomography]]. It is
an index, and a good one — organ-specific, and carrying the longitudinal modulation — but
it does not transport photons. Against it I place absorbed dose in milligray, computed by
Monte Carlo through each patient's own segmented, density-mapped anatomy, with every dose
coefficient computed rather than looked up. I then fit conversions of increasing richness
from the index to the dose and score each on patients the fit has not seen. The result is
a floor, and a decomposition of what sits beneath it.

Three things are not claimed. An index and an absorbed dose are not the same quantity, and
no one holds that they are. No novelty is claimed for GPU Monte-Carlo photon transport
[[cite:badal2009]], spectrum modelling [[cite:bujila2020,poludniowski2021]], HU-to-density
calibration [[cite:schneider1996,schneider2000]] or deep-learning organ segmentation
[[cite:wasserthal2023]]; each is used as published. And a scan-length term is not a
discovery: CTDIvol is defined per rotation and carries no length, while dose-length
product is the standard quantity that does. The term is included so that the comparison is
not against a straw man, and its fitted slope is reported so that a reader can judge how
much of it is accumulation.

## 2. Materials and methods

### 2.1 Monte-Carlo engine and build provenance

Photon transport uses MC-GPU [[cite:badal2009]], a public-domain voxelised Monte-Carlo code, built
locally. The build is pinned: the source patches applied, their kind, and the
SHA-256 of the resulting binary are recorded in a build manifest that ships with the
software. Patches are of three kinds — defect fixes, portability changes, and capacity
increases that raise a compile-time array bound without touching the physics — and each
capacity patch records the bound, its new value and why it was needed. Two were needed
here: the Schneider tissue groups at 140 kVp exceed the upstream limits on Compton shells
and on Rayleigh energy bins.

Material cross-sections are generated locally from the photon subset of the PENELOPE
2006 database [[cite:salvat2006]] rather than transcribed, so that no coefficient table is
redistributed and each material file carries the digest of the data it came from.

### 2.2 Source model

X-ray spectra come from SpekPy [[cite:bujila2020,poludniowski2021]], which supplies the spectrum, the half-value
layer and the absolute tube output for each tube potential. The source is modelled as
an equivalent spectrum and filtration in the manner of Turner et al [[cite:turner2009]], with a
bowtie profile represented as a set of sub-fans, each carrying its own spectrum. The
profiles are derived from the published measurements of Yang et al [[cite:yang2019]], which
cover three vendors; the fourth is represented by the cross-vendor average with its
spread declared.
Geometry, collimation, source-to-axis distance and the number of projections come
from the series metadata.

### 2.3 Verification against TG-195 Case 4

The engine is verified against Case 4 of AAPM Task Group 195 [[cite:sechopoulos2015]], the voxelised
phantom case with published results from four independent codes.

The scored quantity and its units are the task group's own: the energy imparted in a
volume of interest, normalised per source photon, so that it does not depend on the number
of histories run. Two volumes are scored, both cylinders of 1 cm diameter and 10 cm length
along the rotation axis — one centred on it, one with its axis 15 cm from it. The
peripheral volume is scored at every non-overlapping azimuth and averaged, which the task
group permits and which also gives a symmetry test: the spread across azimuths must agree
with the spread across independent seeds, and that test caught a defect in the random
number stream.

Three properties of this verification matter for what follows. The yardstick was fixed
before any comparison was run: PENELOPE was chosen because it shares the photon
cross-section database the material files here are generated from, not because it agreed
best, and the published results of the other three codes are reported beside it so that
the choice is visible. The uncertainty is measured rather than assumed — ten independent
replicas of the anchor configuration give a sample standard deviation, whose standard
error is combined with the reported reference uncertainty — and agreement is reported with
that uncertainty rather than converted into a pass against a threshold of my own choosing.
The phantom length term was measured, not bounded: a 40 cm phantom is indistinguishable
from a 160 cm phantom at these volumes of interest.

### 2.4 Cohort selection

Series were selected from a public archive [[cite:clark2013,moawad2023]] by a recorded
funnel running from the collection index to the series carried forward, with every
exclusion counted and named (Fig. 1). The selection is re-derivable: the criteria are in
code, and the surviving Series Instance UIDs, their collection and their licence are
recorded so that any series can be re-fetched. No imaging is redistributed.

A metadata screen removes series that are not diagnostic reconstructed abdominal images or
that carry too few or too many slices; one series per patient is kept; the remainder are
probed in vendor-balanced order until ten series per vendor are accepted. The probe reads
the header and rejects a series lacking the per-slice tube current the pipeline requires,
which accounts for most rejections (Fig. 1b).

### 2.5 Eligibility: a pre-declared density gate

A voxel is out of calibration when it lies inside the body contour and its value reaches
the twelve-bit saturation ceiling of
[[results:manifest.json:metrics.density_gate_hu_ceiling|.0f]] HU; clipping at the ceiling
and exceeding it are treated identically, so the measure does not depend on how a vendor
handles overflow. Such voxels are metal, concentrated contrast or artefact rather than
tissue: a compact implant has an atomic number the Schneider conversion cannot represent,
so its photoelectric cross-section would be misassigned.

A series is excluded if its largest connected out-of-calibration component reaches
[[results:density_eligibility.json:threshold_cm3|.0f]] cm³. The threshold was not fitted
to any series: the cohort's largest components fall in two groups, the biggest among the
eligible series being
[[results:manifest.json:metrics.density_gate_largest_kept_cm3|.2f]] cm³ and the smallest
among the excluded ones
[[results:manifest.json:metrics.density_gate_smallest_dropped_cm3|.2f]] cm³, and the
threshold sits in that gap (Fig. 2). It and the criterion were declared before the volumes
were computed. Of [[results:density_eligibility.json:n_assessed]] assessed series,
[[results:manifest.json:metrics.n_eligible]] are eligible and
[[results:density_eligibility.json:n_excluded]] are excluded.

### 2.6 Segmentation, density and materials

Organ boundaries come from TotalSegmentator [[cite:wasserthal2023]] run at inference on each series, so
that no manual contour enters the pipeline and the same procedure applies to every
vendor. Hounsfield units are mapped to mass density and to Schneider tissue groups
[[cite:schneider1996,schneider2000]]; voxels above the top calibration breakpoint are held at its density and
counted, and it is that count the eligibility gate reads.

### 2.7 CTDIvol normalisation

Absorbed dose per emitted photon is converted to dose per examination by a scale derived
from a simulated CTDI phantom measurement at the same tube potential and vendor, matched
to the CTDIvol the series carries. Where the series records a CTDIvol that value is used;
where it does not, the value reconstructed from scanner model and technique by a companion
tool is used, and the two are distinguished throughout [[cite:yamamoto2026ctdose]]. Of
[[results:manifest.json:metrics.n_eligible]] eligible series,
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
because it is what the result depends on. Transport is deterministic given the recorded
random seed.

Masks and densities reach that grid as volume-conserving zooms from the native series
voxels, and what the zoom costs is measured rather than assumed. Over the
[[results:resample_cost.json:n_series]] series, organ mass is preserved to within
[[results:resample_cost.json:by_organ.liver.median_abs_pct|.1f]] % at the median for the
liver and [[results:resample_cost.json:by_organ.colon.median_abs_pct|.1f]] % for the
colon. The cost is carried by the smallest organs: the right adrenal gland, a few grams of
tissue, shifts by [[results:resample_cost.json:by_organ.adrenal_gland_right.median_abs_pct|.1f]] %
at the median and [[results:resample_cost.json:by_organ.adrenal_gland_right.max_abs_pct|.1f]] %
in the worst series. The adrenal glands are therefore the organs whose dose is least
secure here. They are reported with the rest rather than dropped: dropping the organs a
method serves worst would overstate how well the method performs.

### 2.9 Index-based conversions, and how they are scored

Let $r$ be the dose-to-index ratio: absorbed organ dose divided by the organ-weighted
CTDIvol index, for one organ in one series. Five conversions are compared, each predicting
$r$ and therefore predicting the dose from the index:

1. a single factor for the whole cohort;
2. one factor per organ, which is what a per-organ coefficient table offers;
3. a scan-length term, fitted here on this cohort rather than taken from any
   published formula, as $\log r = a + b \log n_z$ on the number of
   longitudinal stations;
4. scan length and a per-organ offset, which is everything an index can carry;
5. scan length and patient size, with size as the effective diameter derived from
   the segmented body volume and the scan length.

All are fitted in log ratio, because the quantity is a multiplicative factor spanning
several fold and its errors are relative.

Each is scored under leave-one-patient-out cross-validation. Every series takes a turn as
the held-out one: the conversion is re-fitted from scratch on the other series and the
error is recorded on the series left out — [[results:manifest.json:metrics.n_scaled]] fits
per conversion, with every organ in the cohort contributing exactly one held-out error, and
no conversion ever scored on a patient it was fitted on. Fitting twelve organ offsets on
thirty patients and reporting the error on those same thirty is optimistic by
construction, and thirty is small enough for that to matter.

## 3. Results

### 3.1 Verification

At the centre volume of interest the engine differs from PENELOPE by
[[results:manifest.json:metrics.tg195_centre_abs_pct|.3f]] %, which is
[[results:manifest.json:metrics.tg195_centre_n_sigma|.2f]] combined standard
deviations (Fig. 3). The difference from the other three published codes is larger and in
the same direction at the centre, and smaller at the perimeter; showing all four makes the
choice of yardstick auditable. The phantom length term is measured and null.

### 3.2 Cohort

[[results:cohort_overlap.json:selection_funnel.index_rows]] index rows reduce
to [[results:cohort_overlap.json:selection_funnel.kept]] series through the
funnel of Fig. 1, of which
[[results:cohort_overlap.json:selection_funnel.probed]] were probed and
[[results:cohort_overlap.json:selection_funnel.n_probe_rejected]] rejected. The
density gate leaves [[results:manifest.json:metrics.n_eligible]] eligible series
(Fig. 2), and [[results:manifest.json:metrics.n_scaled]] of those carry a CTDIvol
and enter the analysis.

### 3.3 Absorbed organ doses

Across [[results:manifest.json:metrics.n_points]] organ-series pairs the median
absorbed organ dose is [[results:manifest.json:metrics.dose_median_mgy|.1f]] mGy, with
a range of [[results:manifest.json:metrics.dose_min_mgy|.1f]] to
[[results:manifest.json:metrics.dose_max_mgy|.1f]] mGy. Per-organ values by vendor are
given in Table 1.

[[table:organ_doses]]

Plotted against the organ-weighted index on the same anatomy (Fig. 4), the two are
correlated — Pearson $r$ = [[results:manifest.json:metrics.pearson_r_all|.2f]] over all
[[results:manifest.json:metrics.n_scaled]] series and
[[results:manifest.json:metrics.pearson_r_recorded|.2f]] over the
[[results:manifest.json:metrics.n_recorded]] with a recorded CTDIvol — and the median
ratio of dose to index is [[results:manifest.json:metrics.ratio_median|.2f]]. That the two
differ is not the result; how far apart they remain after every available correction is.

### 3.4 How close an index-based conversion gets

Every error in this section is a held-out error, in the sense of section 2.9: the
conversion was fitted without the patient it is scored on. Figure 5a gives them. A single
factor for the whole cohort recovers absorbed organ dose to a median
[[results:manifest.json:metrics.ceiling_global_factor_median_pct|.0f]] %, with
[[results:manifest.json:metrics.ceiling_global_factor_p90_pct|.0f]] % at the ninetieth
percentile.

One factor per organ does not improve on it. Cross-validated, the per-organ
conversion is slightly worse — a median
[[results:manifest.json:metrics.ceiling_per_organ_factor_median_pct|.0f]] % against
[[results:manifest.json:metrics.ceiling_global_factor_median_pct|.0f]] % — and the
fraction of organs recovered to within 20 % moves from
[[results:manifest.json:metrics.ceiling_global_factor_within20|.0%]] to
[[results:manifest.json:metrics.ceiling_per_organ_factor_within20|.0%]]. Twelve organ
means fitted on twenty-nine patients do not transfer to the thirtieth. This is the form in
which published organ-dose coefficient libraries are used [[cite:lee2011,lee2015]], and on
this cohort it carries no information a single number does not.

A scan-length term does improve on it, to a median
[[results:manifest.json:metrics.ceiling_scan_length_median_pct|.0f]] % and
[[results:manifest.json:metrics.ceiling_scan_length_p90_pct|.0f]] % at the ninetieth
percentile. That is expected: CTDIvol is defined per rotation, dose-length product is the
quantity that carries length [[cite:deak2010]], and the fitted slope on $\log n_z$ is
[[results:manifest.json:metrics.length_slope|.2f]] — close enough to one that the
dependence is largely accumulation.

Adding everything else an index could know changes little. A per-organ offset on top of
length reaches
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
[[results:manifest.json:metrics.ratio_patient_fold|.1f]]-fold. The information an index
withholds is not organ-specific but patient-specific, and it is nearly common to all of
that patient's organs at once. That explains section 3.4: a per-organ coefficient
addresses the [[results:manifest.json:metrics.variance_between_organ|.0%]], cannot address
the [[results:manifest.json:metrics.variance_between_patient|.0%]], and cross-validated
does not even secure the [[results:manifest.json:metrics.variance_between_organ|.0%]].

### 3.6 Patient size does not stand in for it

The obvious candidate for a patient-level correction is patient size, which is what
size-specific dose estimates apply [[cite:boone2011,mccollough2014]]. It does not carry
it. The correlation between the patient-level factor and the effective diameter is $r$ =
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
median and [[results:manifest.json:metrics.mc_sigma_max_pct|.2f]] % at worst, so the floor
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

Absorbed organ doses by vendor are described in Fig. 6. With six to nine series per vendor
the cohort is not powered for a vendor comparison and none is made; the figure and Table 1
show the spread the cohort contains.

## 4. Discussion

### 4.1 A quantitative limit on a class of methods

Every conversion from a dose index to an organ dose — whether by a size correction, a
length factor or a coefficient table — is estimating a patient-level quantity from
measurements that do not contain it. On this cohort the best such conversion misses
absorbed organ dose by a median of
[[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] % and by
[[results:manifest.json:metrics.ceiling_scan_length_and_size_p90_pct|.0f]] % at the
ninetieth percentile, and the part it misses is nearly the same multiplicative error for
every organ in a given patient.

That last property is the useful one, and it cuts both ways. An index is a sound
instrument for questions internal to a patient — which organ received more, how one
protocol compares with another on the same person, whether a change in modulation moved
dose between organs — because within a patient the conversion factor is constant to
within [[results:manifest.json:metrics.ratio_within_patient_fold|.2f]]-fold. It is a poor
instrument for questions across patients in absolute milligray, which is what
epidemiological and risk-estimation uses require, because there the
[[results:manifest.json:metrics.ratio_patient_fold|.1f]]-fold between-patient span is
itself the quantity being estimated.

### 4.2 Why a per-organ coefficient does not help

The negative result on per-organ coefficients needs stating carefully. It does not say
that published coefficient libraries [[cite:lee2011,lee2015]] are wrong: they are computed
on reference phantoms and are correct for those phantoms. It says the residual they are
asked to absorb, when applied to a real patient through an index, is not organ structured.
Cross-validated here, twelve fitted organ coefficients did not beat one number, and a
table with more coefficients would fit more finely into the
[[results:manifest.json:metrics.variance_between_organ|.0%]] of variance that organ
identity explains.

### 4.3 Agreement with the spread between established packages

A second kind of evidence points at the same place. Fujibuchi et al compared three
established organ-dose packages — NCICT, WAZA-ARI v2 and VirtualDose CT — under identical
scan conditions and reported organ doses differing by up to 28 % for a reference male and
47 % for a reference female relative to one of them, attributing the differences to phantom
anatomy and size and to calculation algorithm rather than to inaccuracy in any one package
[[cite:fujibuchi2026]]. They also found that moving the scan limits by 2 cm markedly
changed the dose to organs at the scan boundary. That is the present result approached from
the other side: theirs varies the anatomy a fixed index is converted through and holds the
patient nominal, while this one varies the patient and holds the transport fixed. Both
place the quantity an index does not carry in the anatomy and the irradiated length rather
than in the coefficient.

### 4.4 What this adds, and what it does not establish

That a Monte-Carlo engine can reproduce measured dose is established, and real-time
patient-specific engines are in use [[cite:sharma2019]]; so is the observation that
index-based surrogates disagree with each other and with transport [[cite:ria2021]]. What
has not been available is the size of the gap remaining after every correction an index
can carry, measured on the same anatomy by the same transport and held out. The use for
that number is immediate: a centre choosing between a per-organ coefficient table and a
single factor now has a measured answer, and it is that the table does not repay the
effort.

The quantity here is absorbed organ dose, not risk. A risk statement additionally needs
age and sex, which this cohort does not carry — the public archive supplies the images and
the acquisition metadata, not the demographics — and needs a risk model this paper does
not use. Which surrogate suits which risk question has been compared elsewhere across a
clinical population [[cite:ria2021]]. This result is about how well a conversion recovers
dose, and says nothing about how well dose predicts detriment.

### 4.5 Scope of the bound

<!-- scope-of-claim -->
Whether the floor found here is the floor everywhere is not something one cohort can
settle, and it is not something five conversions can settle either. The bound is over
the five conversions scored in section 2.9 — a single cohort factor, one factor per
organ, a scan-length term, and that term combined with either the organ or the patient's
size — each cross-validated on this cohort. It is a floor on those, on abdominal CT, on
twelve abdominal organs, in a cohort selected for having per-slice tube current recorded.
It is not a proof that no index-based conversion can do better: a richer predictor, given
more of the patient than an index carries, is not excluded by anything measured here. What
is more likely to generalise is the structure of the residual rather than its size — an
index conditions on the scanner and the protocol, and the transport it omits is a function
of the patient.

### 4.6 Limitations

The cohort is [[results:manifest.json:metrics.n_scaled]] series across four vendors, six
to nine per vendor: adequate for the patient-level question, which has
[[results:manifest.json:metrics.n_scaled]] independent units, and inadequate for a
vendor-level one, which would have four. No vendor claim is made; Table 1 and Fig. 6 are
descriptive.

There is no ground-truth absorbed dose in a patient. The engine is verified against a
published reference phantom case [[cite:sechopoulos2015]] with a measured uncertainty and
the patient doses inherit that verification, but they are not independently measured. The
verification supports the transport; it cannot support the segmentation, the HU-to-density
mapping, or the source model as applied to a particular scanner. Organ boundaries come
from an automatic segmentation [[cite:wasserthal2023]] applied uniformly; its errors
propagate into both the index and the dose, since both are computed over the same masks,
and would tend to reduce rather than inflate the difference between them.

The eligibility gate excludes series with more than 1 cm³ of out-of-calibration material,
so patients with implants are under-represented and the floor reported here is a floor for
anatomy the density calibration covers. The scan-length term is fitted on the number of
longitudinal stations, derived from the scan length and the nominal collimation rather
than from a recorded irradiated length; its fitted slope of
[[results:manifest.json:metrics.length_slope|.2f]] is reported so that a reader can see
how much of the term is accumulation. Doses are computed for the acquisition as
reconstructed and recorded: over-ranging, localiser exposures and repeat series are
outside the scope of the metadata used.

## 5. Conclusions

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

Two things follow for practice. Where a median of
[[results:manifest.json:metrics.ceiling_scan_length_and_size_median_pct|.0f]] %, with
[[results:manifest.json:metrics.ceiling_scan_length_and_size_p90_pct|.0f]] % at the
ninetieth percentile, is adequate — protocol comparison, registry-scale surveillance,
tracking a department against itself — a single factor with a scan-length term is the
whole of what an index can offer and is what should be used; a per-organ coefficient
library adds parameters and maintenance without adding accuracy.

Where that is not adequate — a dose compared against an organ-level threshold, or carried
into an individual risk estimate — the missing quantity is transport through the patient's
own anatomy, which no refinement of the index supplies. That step is a different
calculation, not a better coefficient, and its barrier is lower than usually supposed:
every organ dose here was computed from the metadata a routine abdominal CT already
records, with no added exposure and no phantom matched to the patient.

## Acknowledgments

The author thanks the maintainers of MC-GPU, SpekPy, PENELOPE and TotalSegmentator, whose
published work this pipeline is assembled from.

## Declarations

**Funding.** This research received no external funding.

**Conflict of interest.** The author is Representative Director of LISIT Co., Ltd., which
funds Institute of One. The author has no other competing interest to declare regarding
the research, authorship or publication of this work.

**Ethics approval.** Ethics approval was waived. The study uses only de-identified images
and acquisition metadata already placed in the public domain by their depositing
institutions [[cite:clark2013,moawad2023]]; no patient was recruited, no additional
exposure was delivered, and no identifiable data were accessed.

**Informed consent.** Not applicable. Consent for the deposited images was obtained by the
depositing institutions under the terms of the public archive.

**Data availability.** The results, the frozen result tables and the commands that
regenerate every figure are openly available at https://doi.org/10.5281/zenodo.23537665,
under the MIT licence. No imaging is redistributed: the collection, Series Instance UID,
licence and retrieval date of every series are recorded there, so that each series can be
re-fetched from the public archive by any reader. Every number in this paper is resolved at
build time from a machine-readable result file produced by that code, and the build fails
if a number cannot be traced to one.

**Code availability.** The software is the same archive, under the MIT licence;
development continues at https://github.com/Institute-of-One/ct-dosemc-core.

**Use of generative artificial intelligence.** A generative artificial intelligence
assistant (Claude Opus 5, Anthropic) was used as a tool in developing the software, in
preparing figures from result files already computed, and in language editing of this
manuscript. It was not used to generate, impute or select any reported value. The study
design, the dosimetry, and all scientific judgements, interpretations and conclusions are
the author's, who takes full responsibility for the content of this paper.

**Prior presentation.** No part of this work has been presented or published elsewhere.

## References

[[references]]

<!--
The "Novel Scientific Points" the submission system asks for: three to five
catchphrases, each at most 100 characters including spaces, saying what is new.
They are not published; they are read by the editors and reviewers.

One per line, beginning with "- ". Numbers are markers resolved from
paper/frozen/ like everywhere else, and build_submission.py measures the length
of the *resolved* line, because "[[results:...]]" is not what anyone counts.
-->

- Measures how close an index can get to organ dose, against transport on the same anatomy
- Thirty patients do not separate a per-organ coefficient table from one factor, held out
- [[results:manifest.json:metrics.variance_between_patient|.0%]] of the dose-to-index variance is between patients, [[results:manifest.json:metrics.variance_between_organ|.0%]] between organs
- The residual sits three orders of magnitude above the Monte-Carlo sampling uncertainty
- Organ dose from routine CT metadata alone: no added exposure, no phantom matched to the patient

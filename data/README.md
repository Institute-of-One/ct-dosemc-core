# data/

**No DICOM is committed here, ever.** `.gitignore` excludes everything in this
directory except this file and `PROVENANCE.json`.

The imaging used in Phase 2 is public and CC BY, but this project does not
redistribute it. What is committed is the record needed to fetch the identical
series again: collection, Series Instance UID, licence, retrieval date, and the
SHA-256 manifest of the bytes that were actually processed.

See [../docs/REPRODUCING_DATA.md](../docs/REPRODUCING_DATA.md) for the exact
queries and filters, and for the rule in the other direction — no proprietary
organ-dose coefficient table is shipped, transcribed or paraphrased anywhere in
this repository.

Phase 1, the CTDI validation anchor, needs nothing in this directory: the
dosimetry phantom is built analytically from IEC 60601-2-44.

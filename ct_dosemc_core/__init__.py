"""ct_dosemc_core -- patient-specific absorbed organ dose in CT by open Monte Carlo.

IORN-007.  The dose coefficients are computed here rather than looked up, so the
pipeline carries no licensing exposure: the transport engine is MC-GPU v1.3
(DIDSR/FDA, public domain), the spectra come from SpekPy (BSD-3), the anatomy from
TotalSegmentator (Apache-2.0), and the inputs from CC BY TCIA collections.

Validation is in two stages, and the order matters.  :mod:`ct_dosemc_core.tg195`
holds the Phase-1a gate -- code verification against AAPM TG-195 Case 4, whose
specification matches this simulation exactly and whose reference values come
from four independent Monte Carlo packages.  :mod:`ct_dosemc_core.ctdi` holds the
Phase-1b physical anchor, which tests the *scanner* model and cannot begin until
the code itself is known to be right.  Nothing patient-specific is computed until
Phase 1a passes.

Institute of One, LISIT Co., Ltd., Tokyo, Japan.  MIT licence.
"""

from __future__ import annotations

__version__ = "0.2.1"

__all__ = [
    "ctdi",
    "dosimetry",
    "mcgpu_io",
    "phantom",
    "provenance",
    "source_model",
    "spectra",
    "tg195",
]

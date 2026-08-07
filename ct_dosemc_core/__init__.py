"""ct_dosemc_core -- patient-specific absorbed organ dose in CT by open Monte Carlo.

IORN-007.  The dose coefficients are computed here rather than looked up, so the
pipeline carries no licensing exposure: the transport engine is MC-GPU v1.3
(DIDSR/FDA, public domain), the spectra come from SpekPy (BSD-3), the anatomy from
TotalSegmentator (Apache-2.0), and the inputs from CC BY TCIA collections.

Phase 1, the CTDI validation anchor, lives in :mod:`ct_dosemc_core.ctdi`, and
nothing patient-specific should be computed until it passes.

Institute of One, LISIT Co., Ltd., Tokyo, Japan.  MIT licence.
"""

from __future__ import annotations

__version__ = "0.1.0.dev0"

__all__ = [
    "ctdi",
    "dosimetry",
    "mcgpu_io",
    "phantom",
    "provenance",
    "source_model",
    "spectra",
]

"""Choosing a small, balanced, multi-vendor abdominal CT sample without bulk download.

The chain is: **index -> screen -> probe -> keep**. Only the last step transfers a
series, and only for series that have already been shown to carry what the organ-dose
calculation needs.

*Index* is series-level JSON from the archive (:mod:`ctsegdose_core.nbia`) or the
already-published IORN-004 survey, which catalogued 400 series across four
manufacturers and 92 collections through the same API without bulk download.

*Screen* is metadata-only and rejects, in order: non-CT modality, projection/raw and
derived series, localisers, and series too short or too long to be a diagnostic
abdominal acquisition. This is where the 600 GB of projection data is refused.

*Probe* fetches a handful of single images -- header only, a few megabytes -- and
answers the three questions that decide whether a series can be used at all:

1. is per-slice tube current (0018,1151) recorded, and does it actually vary along z?
   Without it there is no modulation to weight with, and a fixed-mA series is a
   different acquisition, not a weaker case of the same one;
2. is the pixel data convertible to Hounsfield units (RescaleSlope/Intercept), which
   the density step requires;
3. is the geometry abdominal and long enough to contain whole organs?

A series that fails 1 is dropped and the reason recorded per vendor: which vendors omit
per-slice tube current is a Limitation to report, not a failure to hide.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from typing import Any

from .nbia import vendor_of

VENDORS: tuple[str, ...] = ("GE", "Siemens", "Canon/Toshiba", "Philips")

#: Reconstructed-image SOP classes. Anything else -- raw data storage, secondary
#: capture, a structured report -- is not an image series this work can use.
IMAGE_SOP_CLASSES = {
    "1.2.840.10008.5.1.4.1.1.2": "CT Image Storage",
    "1.2.840.10008.5.1.4.1.1.2.1": "Enhanced CT Image Storage",
}

#: Description substrings that mark projection/raw/derived data rather than a
#: reconstructed image series. The low-dose CT collection publishes its sinograms
#: alongside its images and both are indexed under modality CT, so the description is
#: the only pre-download discriminator.
PROJECTION_MARKERS = (
    "projection",
    "sinogram",
    "raw data",
    "rawdata",
    "raw_data",
    "phantom scan data",
)

#: Collections that do not contain patients being scanned clinically: imaging phantoms,
#: and the de-identification benchmark sets whose images are synthesised or curated to
#: carry deliberate pseudo-PHI. A patient-specific organ dose cannot be computed for a
#: phantom, and a de-identification benchmark is not a dosimetry cohort.
NON_PATIENT_COLLECTION_MARKERS = (
    "phantom",
    "pseudo-phi",
    "midi-b",
    "synthetic",
)

#: Series that are images but not a diagnostic acquisition of the patient.
NON_DIAGNOSTIC_MARKERS = (
    "phantom",
    "localizer",
    "localiser",
    "scout",
    "topogram",
    "surview",
    "dose report",
    "dose_report",
    "patient protocol",
    "screen save",
    "screen capture",
    "secondary capture",
    "summary",
    "key images",
    "segmentation",
    "rtstruct",
)

#: BodyPartExamined values, and description words, that place a series in the abdomen.
ABDOMINAL_BODY_PARTS = (
    "ABDOMEN",
    "ABDOMENPELVIS",
    "ABDPEL",
    "CHESTABDPELVIS",
    "CHESTABDOMEN",
    "LIVER",
    "KIDNEY",
    "PANCREAS",
    "SPLEEN",
    "ADRENAL",
    "STOMACH",
    "COLON",
    "RECTUM",
    "BLADDER",
    "PELVIS",
)

ABDOMINAL_WORDS = (
    "abdomen",
    "abdominal",
    "abd",
    "liver",
    "hepat",
    "kidney",
    "renal",
    "kits",
    "pancrea",
    "spleen",
    "adrenal",
    "colon",
    "colorectal",
    "gastric",
    "stomach",
    "urogram",
    "portal",
    "ct ap",
    "cap",
)

#: A whole-organ dose needs the organ inside the scan. Forty slices is the floor the
#: specification sets; the upper bound keeps whole-body and multi-phase concatenations
#: out of a per-series analysis.
MIN_IMAGES = 40
MAX_IMAGES = 1200
#: Axial extent that comfortably contains the abdominal organs, in millimetres.
MIN_Z_COVERAGE_MM = 120.0
#: Relative spread of tube current above which the modulation is real rather than
#: rounding in the header.
MODULATION_TOLERANCE = 0.02

TUBE_CURRENT_TAG = (0x0018, 0x1151)
TUBE_CURRENT_IN_MA_TAG = (0x0018, 0x9330)
RESCALE_SLOPE_TAG = (0x0028, 0x1053)
RESCALE_INTERCEPT_TAG = (0x0028, 0x1052)


def _text(row: dict[str, Any], *keys: str) -> str:
    return " ".join(str(row.get(k) or "") for k in keys).lower()


def _contains(haystack: str, needles: Iterable[str]) -> str | None:
    for needle in needles:
        if needle in haystack:
            return needle
    return None


@dataclass
class Candidate:
    """One series the archive index offers, before anything has been downloaded."""

    vendor: str
    manufacturer_raw: str
    model_name: str
    collection: str
    collection_uri: str
    patient_id: str
    series_uid: str
    study_uid: str
    series_description: str
    protocol_name: str
    study_description: str
    body_part: str
    n_images: int
    file_size_bytes: int
    licence: str
    licence_uri: str
    source: str  # "tcia-index" | "iorn004-survey"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def candidate_from_index_row(row: dict[str, Any]) -> Candidate | None:
    """Build a candidate from one ``getSeries`` row, or ``None`` for an unknown vendor."""
    vendor = vendor_of(str(row.get("Manufacturer") or ""))
    if vendor is None:
        return None
    return Candidate(
        vendor=vendor,
        manufacturer_raw=str(row.get("Manufacturer") or ""),
        model_name=str(row.get("ManufacturerModelName") or ""),
        collection=str(row.get("Collection") or ""),
        collection_uri=str(row.get("CollectionURI") or ""),
        patient_id=str(row.get("PatientID") or ""),
        series_uid=str(row.get("SeriesInstanceUID") or ""),
        study_uid=str(row.get("StudyInstanceUID") or ""),
        series_description=str(row.get("SeriesDescription") or ""),
        protocol_name=str(row.get("ProtocolName") or ""),
        study_description=str(row.get("StudyDesc") or row.get("StudyDescription") or ""),
        body_part=str(row.get("BodyPartExamined") or "").upper(),
        n_images=int(row.get("ImageCount") or 0),
        file_size_bytes=int(row.get("FileSize") or 0),
        licence=str(row.get("LicenseName") or ""),
        licence_uri=str(row.get("LicenseURI") or ""),
        source="tcia-index",
    )


def candidate_from_survey_row(row: dict[str, Any]) -> Candidate | None:
    """Build a candidate from one row of the IORN-004 ``results/survey.json``.

    That survey screened 400 series across the four vendors over the same public API,
    recording per-series licence, body part and which acquisition attributes the header
    carries. Reusing it means the multi-vendor candidate list starts from work that has
    already been done and published, rather than from a fresh crawl.
    """
    vendor = row.get("vendor") or vendor_of(str(row.get("manufacturer_raw") or ""))
    if vendor not in VENDORS:
        return None
    return Candidate(
        vendor=str(vendor),
        manufacturer_raw=str(row.get("manufacturer_raw") or ""),
        model_name=str(row.get("model_name") or ""),
        collection=str(row.get("collection") or ""),
        collection_uri="",
        patient_id="",
        series_uid=str(row.get("series_uid") or ""),
        study_uid="",
        series_description="",
        protocol_name="",
        study_description="",
        body_part=str(row.get("body_part") or "").upper(),
        n_images=int(row.get("n_images") or 0),
        file_size_bytes=0,
        licence=str(row.get("licence") or ""),
        licence_uri=str(row.get("licence_url") or row.get("licence_uri") or ""),
        source="iorn004-survey",
    )


def screen_reason(cand: Candidate) -> str | None:
    """Why this candidate cannot be used, judged from metadata alone.

    Returns ``None`` when the candidate survives the metadata screen. Every rejection
    names its reason so the counts in ``results/`` add up and the exclusions are
    reportable rather than invisible.
    """
    marker = _contains(cand.collection.lower(), NON_PATIENT_COLLECTION_MARKERS)
    if marker:
        return f"non-patient-collection:{marker}"
    text = " ".join(
        (cand.series_description, cand.protocol_name, cand.study_description)
    ).lower()
    marker = _contains(text, PROJECTION_MARKERS)
    if marker:
        return f"projection-or-raw:{marker}"
    marker = _contains(text, NON_DIAGNOSTIC_MARKERS)
    if marker:
        return f"non-diagnostic:{marker}"
    if cand.n_images and cand.n_images < MIN_IMAGES:
        return f"too-few-images:{cand.n_images}"
    if cand.n_images > MAX_IMAGES:
        return f"too-many-images:{cand.n_images}"
    if not is_abdominal(cand):
        return "not-abdominal"
    return None


def is_abdominal(cand: Candidate) -> bool:
    """Whether the index places this series in the abdomen.

    BodyPartExamined is authoritative when present; many collections leave it empty, so
    the series/protocol/study descriptions are read as a fallback. Both are indexed
    strings entered at the scanner, so this is a *candidate* filter -- the anatomy is
    confirmed against the image header at the probe stage and, finally, by the
    segmentation itself.
    """
    if cand.body_part:
        return any(part in cand.body_part for part in ABDOMINAL_BODY_PARTS)
    text = " ".join((cand.series_description, cand.protocol_name, cand.study_description)).lower()
    return any(re.search(_word_pattern(word), text) for word in ABDOMINAL_WORDS)


def _word_pattern(word: str) -> str:
    """Match a keyword the way its length allows.

    Long words are matched as prefixes so "hepat" catches "hepatic" and "hepatobiliary".
    Short ones are matched whole, because a bare prefix of "abd" or "cap" would also
    fire on "abdication" or "capture" and pull non-abdominal series into the sample.
    """
    escaped = re.escape(word)
    return rf"\b{escaped}\b" if len(word) <= 4 else rf"\b{escaped}"


def screen(candidates: Iterable[Candidate]) -> tuple[list[Candidate], dict[str, int]]:
    """Apply the metadata screen, returning survivors and a reason -> count tally."""
    kept: list[Candidate] = []
    excluded: dict[str, int] = {}
    for cand in candidates:
        reason = screen_reason(cand)
        if reason is None:
            kept.append(cand)
        else:
            key = reason.split(":")[0]
            excluded[key] = excluded.get(key, 0) + 1
    return kept, excluded


def one_series_per_patient(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Keep one series per patient per vendor.

    Two reconstructions of the same acquisition are not two patients, and a sample that
    counts them as such overstates how many subjects the results rest on. The longest
    series wins, being the one most likely to contain whole organs.
    """
    best: dict[tuple[str, str, str], Candidate] = {}
    for cand in candidates:
        key = (cand.vendor, cand.collection, cand.patient_id or cand.series_uid)
        current = best.get(key)
        if current is None or cand.n_images > current.n_images:
            best[key] = cand
    return sorted(best.values(), key=lambda c: (c.vendor, c.collection, c.patient_id))


def diversify(candidates: Sequence[Candidate], *, per_vendor: int) -> list[Candidate]:
    """Order candidates so a vendor's quota is spread over its collections.

    Taking the first N of an index run means taking N series from whichever collection
    happens to sort first, which would confound vendor with site and protocol. This
    round-robins over collections instead, so a vendor's quota comes from as many
    distinct collections as the index offers.
    """
    by_vendor: dict[str, dict[str, list[Candidate]]] = {}
    for cand in candidates:
        by_vendor.setdefault(cand.vendor, {}).setdefault(cand.collection, []).append(cand)
    ordered: list[Candidate] = []
    for vendor in VENDORS:
        collections = by_vendor.get(vendor, {})
        # Within a collection, a series the IORN-004 survey already screened comes first:
        # its header was inspected in that run, so it is the likelier probe hit.
        queues = [
            sorted(v, key=lambda c: (c.source != "iorn004-survey", c.series_uid))
            for _, v in sorted(collections.items())
        ]
        vendor_order: list[Candidate] = []
        while queues:
            for queue in list(queues):
                if queue:
                    vendor_order.append(queue.pop(0))
                else:
                    queues.remove(queue)
        ordered.extend(vendor_order[: per_vendor * 4])  # a probing margin over the quota
    return ordered


# --- probe: what the image header actually says --------------------------------------


@dataclass
class Probe:
    """The header evidence gathered from a few single images of one series."""

    series_uid: str
    vendor: str
    n_probed: int = 0
    n_instances: int = 0
    sop_class_uid: str = ""
    image_type: str = ""
    body_part: str = ""
    kvp: float | None = None
    tube_currents_ma: list[float] = field(default_factory=list)
    z_positions_mm: list[float] = field(default_factory=list)
    slice_thickness_mm: float | None = None
    pixel_spacing_mm: list[float] = field(default_factory=list)
    has_rescale: bool = False
    rescale_slope: float | None = None
    rescale_intercept: float | None = None
    error: str = ""

    # -- derived judgements ------------------------------------------------------------

    @property
    def is_reconstructed_image(self) -> bool:
        return self.sop_class_uid in IMAGE_SOP_CLASSES

    @property
    def is_localizer(self) -> bool:
        return "LOCALIZER" in self.image_type.upper()

    @property
    def has_per_slice_tube_current(self) -> bool:
        """Tube current recorded on every probed slice, not just the first.

        A series that carries (0018,1151) on one image and omits it on the next cannot
        supply I(z), which is the whole input to the modulation weighting.
        """
        return self.n_probed > 0 and len(self.tube_currents_ma) == self.n_probed

    @property
    def tube_current_spread(self) -> float:
        """Peak-to-peak tube current as a fraction of the mean, 0.0 when fixed."""
        vals = self.tube_currents_ma
        if len(vals) < 2:
            return 0.0
        mean = statistics.fmean(vals)
        return 0.0 if mean <= 0 else (max(vals) - min(vals)) / mean

    @property
    def tube_current_is_modulated(self) -> bool:
        return self.tube_current_spread >= MODULATION_TOLERANCE

    @property
    def z_coverage_mm(self) -> float:
        """Axial extent spanned by the probed slices -- a *lower bound* on the series.

        The archive does not promise that ``getSOPInstanceUIDs`` returns instances in
        acquisition order, so probes spread across that list sample the series without
        necessarily reaching its two ends. Under-reporting the extent is the safe
        direction: it can only reject a usable series, never admit an unusable one.
        """
        if len(self.z_positions_mm) < 2:
            return 0.0
        return max(self.z_positions_mm) - min(self.z_positions_mm)

    @property
    def axial_extent_mm(self) -> float:
        """Best available estimate of the scanned length.

        Slice thickness times the instance count is the more complete estimate when the
        probes happen to land close together, but it assumes contiguous slices, so the
        measured span of the probes is preferred whenever it is larger.
        """
        nominal = 0.0
        if self.slice_thickness_mm and self.n_instances > 1:
            nominal = self.slice_thickness_mm * (self.n_instances - 1)
        return max(self.z_coverage_mm, nominal)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.update(
            {
                "is_reconstructed_image": self.is_reconstructed_image,
                "is_localizer": self.is_localizer,
                "has_per_slice_tube_current": self.has_per_slice_tube_current,
                "tube_current_spread": round(self.tube_current_spread, 4),
                "tube_current_is_modulated": self.tube_current_is_modulated,
                "z_coverage_mm": round(self.z_coverage_mm, 1),
                "axial_extent_mm": round(self.axial_extent_mm, 1),
                "verdict": verdict(self),
            }
        )
        return d


def _float(ds: Any, tag: tuple[int, int]) -> float | None:
    if tag not in ds:
        return None
    value = ds[tag].value
    try:
        if isinstance(value, (list, tuple)) or type(value).__name__ == "MultiValue":
            value = value[0]
        return float(value)
    except (TypeError, ValueError, IndexError):
        return None


def read_probe(datasets: Sequence[Any], *, series_uid: str, vendor: str, n_instances: int) -> Probe:
    """Reduce the sampled image headers of one series to a :class:`Probe`.

    Pure: it takes datasets and returns evidence, so the whole screen can be tested
    offline against synthesised headers.
    """
    probe = Probe(series_uid=series_uid, vendor=vendor, n_instances=n_instances)
    probe.n_probed = len(datasets)
    for ds in datasets:
        probe.sop_class_uid = probe.sop_class_uid or str(ds.get("SOPClassUID", "") or "")
        if not probe.image_type:
            raw_type = ds.get("ImageType", "") or ""
            probe.image_type = "\\".join(raw_type) if isinstance(raw_type, (list, tuple)) else str(raw_type)
        probe.body_part = probe.body_part or str(ds.get("BodyPartExamined", "") or "").upper()
        if probe.kvp is None:
            probe.kvp = _float(ds, (0x0018, 0x0060))
        if probe.slice_thickness_mm is None:
            probe.slice_thickness_mm = _float(ds, (0x0018, 0x0050))
        if not probe.pixel_spacing_mm and (0x0028, 0x0030) in ds:
            with suppress(TypeError, ValueError):
                probe.pixel_spacing_mm = [float(v) for v in ds[(0x0028, 0x0030)].value]

        current = _float(ds, TUBE_CURRENT_TAG)
        if current is None:
            current = _float(ds, TUBE_CURRENT_IN_MA_TAG)
        if current is not None and current > 0:
            probe.tube_currents_ma.append(current)

        if (0x0020, 0x0032) in ds:
            with suppress(TypeError, ValueError, IndexError):
                probe.z_positions_mm.append(float(ds[(0x0020, 0x0032)].value[2]))

        slope = _float(ds, RESCALE_SLOPE_TAG)
        intercept = _float(ds, RESCALE_INTERCEPT_TAG)
        if slope is not None and intercept is not None:
            probe.has_rescale = True
            probe.rescale_slope = slope if probe.rescale_slope is None else probe.rescale_slope
            probe.rescale_intercept = (
                intercept if probe.rescale_intercept is None else probe.rescale_intercept
            )
    return probe


def verdict(probe: Probe) -> str:
    """``"keep"``, or the first reason this series cannot be used.

    The order matters for the exclusion table: a series is reported against the first
    requirement it fails, so the counts partition the candidates instead of
    double-counting them.
    """
    if probe.error:
        return f"probe-failed:{probe.error}"
    if probe.n_probed == 0:
        return "probe-failed:no-images-returned"
    if not probe.is_reconstructed_image:
        return f"not-a-reconstructed-image:{probe.sop_class_uid or 'unknown-sop-class'}"
    if probe.is_localizer:
        return "localizer"
    if probe.n_instances < MIN_IMAGES:
        return f"too-few-slices:{probe.n_instances}"
    if not probe.has_per_slice_tube_current:
        return "no-per-slice-tube-current"
    if not probe.tube_current_is_modulated:
        return f"tube-current-not-modulated:{probe.tube_current_spread:.3f}"
    if not probe.has_rescale:
        return "no-hu-rescale"
    if probe.axial_extent_mm < MIN_Z_COVERAGE_MM:
        return f"z-coverage-too-short:{probe.axial_extent_mm:.0f}mm"
    if probe.body_part and not any(part in probe.body_part for part in ABDOMINAL_BODY_PARTS):
        return f"not-abdominal-in-header:{probe.body_part}"
    return "keep"

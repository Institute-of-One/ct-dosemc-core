"""Metadata-first access to The Cancer Imaging Archive's public NBIA REST API.

The point of this module is what it *does not* do. Handing a collection manifest to
NBIA Data Retriever downloads the whole collection -- for the low-dose CT collection
that is roughly 600 GB, most of it raw projection data this work has no use for. Here
the catalogue is read first as metadata (``getSeries`` returns small JSON with no pixel
data), single images are probed one SOP instance at a time to check the header, and
only the series that survive that screen are fetched in full (``getImage``).

Nothing is written back to the archive and no credentials are used: only public,
de-identified collections are read. Each series' licence and collection DOI travel with
it into the provenance record, because no imaging is redistributed from this repository
and a reader has to be able to re-fetch exactly what was used.

``tcia_utils`` is used for the series index when it imports cleanly. It is not
required: its transitive ``idc-index`` dependency does not install on every supported
Python, and the endpoints used here are stable public URLs.
"""

from __future__ import annotations

import io
import json
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import pydicom

NBIA_BASE = "https://services.cancerimagingarchive.net/nbia-api/services/v1"

#: Manufacturer strings as TCIA indexes them, grouped to a vendor label. TCIA stores the
#: DICOM Manufacturer verbatim, so one vendor appears under several spellings.
VENDOR_ALIASES: dict[str, tuple[str, ...]] = {
    "GE": ("GE MEDICAL SYSTEMS", "GE HEALTHCARE", "GE"),
    "Siemens": ("SIEMENS", "SIEMENS HEALTHINEERS"),
    "Canon/Toshiba": ("TOSHIBA", "CANON MEDICAL SYSTEMS", "CANON"),
    "Philips": ("PHILIPS", "PHILIPS MEDICAL SYSTEMS", "PHILIPS HEALTHCARE"),
}

DATA_USE_NOTE = (
    "TCIA data are subject to the TCIA Data Usage Policy and to each collection's own "
    "licence. The per-series licence recorded here must be reproduced in any "
    "publication, together with the collection name and the retrieval date. No imaging "
    "is redistributed by this repository."
)


def vendor_of(manufacturer: str) -> str | None:
    """Map a raw DICOM Manufacturer string to one of the four vendor labels.

    Returns ``None`` for a manufacturer outside the four, so an unknown vendor is
    dropped from a balanced sample rather than silently counted as one of them.
    """
    raw = (manufacturer or "").strip().upper()
    if not raw:
        return None
    for vendor, aliases in VENDOR_ALIASES.items():
        if any(alias in raw for alias in aliases):
            return vendor
    return None


class NbiaClient:
    """Minimal public NBIA REST client with an on-disk cache.

    Args:
        base_url: API root. Overridable so the tests can run against a stub.
        timeout: per-request timeout in seconds. Series archives are large; the default
            is generous because a slow archive is not an error.
        cache_dir: when set, every fetched object is cached, so a re-run of the
            selection costs no bandwidth and reproduces the same choice.
    """

    def __init__(
        self,
        base_url: str = NBIA_BASE,
        *,
        timeout: float = 900.0,
        cache_dir: Path | str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.bytes_downloaded = 0

    # -- transport ---------------------------------------------------------------------

    def _url(self, endpoint: str, params: dict[str, Any]) -> str:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return f"{self.base_url}/{endpoint}" + (f"?{query}" if query else "")

    def get_json(self, endpoint: str, **params: Any) -> list[dict[str, Any]]:
        url = self._url(endpoint, params)
        with urllib.request.urlopen(url, timeout=self.timeout) as resp:  # noqa: S310
            body = resp.read().decode("utf-8").strip()
        return json.loads(body) if body else []

    def get_bytes(self, endpoint: str, *, cache_key: str | None = None, **params: Any) -> bytes:
        cached = self.cache_dir / cache_key if (self.cache_dir and cache_key) else None
        if cached is not None and cached.exists():
            return cached.read_bytes()
        url = self._url(endpoint, params)
        with urllib.request.urlopen(url, timeout=self.timeout) as resp:  # noqa: S310
            data = resp.read()
        self.bytes_downloaded += len(data)
        if cached is not None:
            cached.write_bytes(data)
        return data

    # -- endpoints ---------------------------------------------------------------------

    def series(
        self,
        *,
        collection: str | None = None,
        modality: str = "CT",
        manufacturer: str | None = None,
    ) -> list[dict[str, Any]]:
        """Series-level index entries. Metadata only -- no pixel data is transferred."""
        if collection is not None:
            rows = self._series_via_tcia_utils(collection=collection, modality=modality)
            if rows is not None:
                return rows
        return self.get_json(
            "getSeries", Collection=collection, Modality=modality, Manufacturer=manufacturer
        )

    def _series_via_tcia_utils(self, *, collection: str, modality: str) -> list[dict] | None:
        try:  # pragma: no cover - depends on an optional install
            from tcia_utils import nbia
        except Exception:
            return None
        try:  # pragma: no cover - network path
            rows = nbia.getSeries(collection=collection, modality=modality)
        except Exception:
            return None
        return list(rows) if rows else None

    def sop_instance_uids(self, series_uid: str) -> list[str]:
        """Every SOP Instance UID in a series. Metadata only; this is how slice count is
        confirmed without fetching a single image."""
        rows = self.get_json("getSOPInstanceUIDs", SeriesInstanceUID=series_uid)
        return [r["SOPInstanceUID"] for r in rows if r.get("SOPInstanceUID")]

    def single_image(self, series_uid: str, sop_uid: str) -> pydicom.Dataset:
        """One image of a series, read header-only.

        This is the cheap probe that replaces downloading a series to find out whether
        it is usable: a handful of these answers "does this series record per-slice tube
        current, and is that current modulated along z?" for a few megabytes.
        """
        raw = self.get_bytes(
            "getSingleImage",
            cache_key=f"img_{sop_uid}.dcm",
            SeriesInstanceUID=series_uid,
            SOPInstanceUID=sop_uid,
        )
        return pydicom.dcmread(io.BytesIO(raw), stop_before_pixels=True, force=True)

    def download_series(self, series_uid: str, dest: Path | str) -> tuple[Path, int]:
        """Fetch one whole series and extract its DICOM files into ``dest``.

        Returns the destination and the number of files written. Only the chosen series
        is transferred; the rest of the collection is never touched.
        """
        raw = self.get_bytes("getImage", cache_key=f"series_{series_uid}.zip", SeriesInstanceUID=series_uid)
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        written = 0
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".dcm"):
                    continue  # the archive also packs a LICENSE text file
                (dest / Path(name).name).write_bytes(zf.read(name))
                written += 1
        return dest, written

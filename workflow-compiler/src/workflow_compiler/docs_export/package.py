"""Make Office packages byte-deterministic.

python-docx and openpyxl stamp every zip member with the current time (and
openpyxl overwrites ``dcterms:modified`` on save). :func:`stabilise_package`
re-zips the package with a fixed member timestamp and a fixed ``modified``
property so identical input yields identical bytes — the property that lets
exports be cached, diffed and asserted in tests.
"""

from __future__ import annotations

import io
import re
import zipfile

FIXED_DATE_TIME = (2026, 1, 1, 0, 0, 0)
_MODIFIED = re.compile(rb"<dcterms:modified([^>]*)>[^<]*</dcterms:modified>")
_CREATED = re.compile(rb"<dcterms:created([^>]*)>[^<]*</dcterms:created>")
_FIXED_ISO = b"2026-01-01T00:00:00Z"


def stabilise_package(data: bytes) -> bytes:
    """Rewrite an OOXML zip (docx / xlsx) with fixed timestamps."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            payload = src.read(info)
            if info.filename == "docProps/core.xml":
                payload = _MODIFIED.sub(
                    rb"<dcterms:modified\1>" + _FIXED_ISO + rb"</dcterms:modified>", payload
                )
                payload = _CREATED.sub(
                    rb"<dcterms:created\1>" + _FIXED_ISO + rb"</dcterms:created>", payload
                )
            new_info = zipfile.ZipInfo(info.filename, date_time=FIXED_DATE_TIME)
            new_info.compress_type = zipfile.ZIP_DEFLATED
            new_info.external_attr = info.external_attr
            dst.writestr(new_info, payload)
    return out.getvalue()

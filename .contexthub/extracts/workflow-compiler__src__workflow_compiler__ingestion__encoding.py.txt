"""Byte-to-text decoding with BOM awareness and charset detection."""

from __future__ import annotations

import codecs

from charset_normalizer import from_bytes

# Order matters: UTF-32 BOMs must be checked before UTF-16 because the UTF-32-LE
# BOM (FF FE 00 00) begins with the UTF-16-LE BOM (FF FE).
_BOM_TABLE: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def detect_and_decode(data: bytes, *, fallback: str = "utf-8") -> tuple[str, str]:
    """Decode ``data`` to text, returning ``(text, encoding_name)``.

    Strategy, in order: empty short-circuit, BOM sniffing, strict UTF-8,
    statistical detection via charset-normalizer, and finally a lossy decode
    using ``fallback`` so ingestion never hard-fails on encoding alone.
    """
    if not data:
        return "", fallback

    for bom, encoding in _BOM_TABLE:
        if data.startswith(bom):
            return data.decode(encoding), encoding

    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    best = from_bytes(data).best()
    if best is not None:
        return str(best), (best.encoding or fallback)

    return data.decode(fallback, errors="replace"), fallback

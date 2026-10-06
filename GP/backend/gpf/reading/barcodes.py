"""Stage 5: QR/barcode decoding — deterministic, NO model (spec §9).

Production uses zxing-cpp + OpenCV with a multi-binarizer, tiled, upscaled
sweep. This module defines the decoder seam and provides:

* `ZxingBarcodeDecoder` — the real decoder (used when zxing-cpp is installed);
* `NullBarcodeDecoder` — returns nothing (air-gapped dev without the library);
* `ScriptedBarcodeDecoder` — canned results for tests.

A decoded payload that disagrees with the document on identity/money is a hard
stop; an unreadable/unsupplied code is an observation (handled by the QR rule).
Comparison against the document is the rules engine's job, not the decoder's.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


@dataclass
class DecodedCode:
    symbology: str                 # "QR code", "PDF417 barcode", "Code 39", "1-D barcode"
    payload: Optional[str]         # decoded text, or None if unreadable
    page: int
    bbox: Optional[list] = None
    decoded: bool = True
    why: Optional[str] = None      # reason it could not be read, when decoded is False


@runtime_checkable
class BarcodeDecoder(Protocol):
    def decode_page(self, image_ref: str, page: int) -> list[DecodedCode]: ...


class NullBarcodeDecoder:
    """No decoding available (e.g. zxing-cpp not installed in this environment)."""

    def decode_page(self, image_ref: str, page: int) -> list[DecodedCode]:
        return []


class ScriptedBarcodeDecoder:
    """Deterministic decoder for tests/demo: {page: [DecodedCode, ...]}."""

    def __init__(self, script: dict[int, list[DecodedCode]]):
        self._script = script

    def decode_page(self, image_ref: str, page: int) -> list[DecodedCode]:
        return list(self._script.get(page, []))


class ZxingBarcodeDecoder:  # pragma: no cover - needs zxing-cpp + a real image
    """Real decoder. Multi-binarizer + tiled upscaled sweep (spec §9.1).

    Imports are lazy so the package works with no imaging libraries installed.
    """

    def __init__(self, dpi: int = 300):
        self.dpi = dpi

    def decode_page(self, image_ref: str, page: int) -> list[DecodedCode]:
        try:
            import zxingcpp  # type: ignore
            from PIL import Image  # type: ignore
        except Exception as e:
            raise RuntimeError("ZxingBarcodeDecoder needs zxing-cpp and Pillow installed.") from e
        img = Image.open(image_ref).convert("RGB")
        out: list[DecodedCode] = []
        for r in zxingcpp.read_barcodes(img):
            out.append(DecodedCode(symbology=str(r.format), payload=r.text, page=page,
                                   bbox=None, decoded=bool(r.text)))
        # A production build adds the tiled/upscaled/CLAHE second pass here (spec §9.1).
        return out

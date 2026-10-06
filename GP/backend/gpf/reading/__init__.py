"""The reading pipeline (spec §3 stages 1-5) and the facts assembler.

Turns scans into the case facts object the rules engine consumes. Uses the
language model only for schema-constrained classification and extraction
(stages 3-4); stage 5 (barcodes) is deterministic. Runs end-to-end today with
a ScriptedModelClient; swaps to the real VllmModelClient on the DGX Spark.
"""
from .artefacts import ALL_TYPES, Artefact, CARRIES_QR
from .barcodes import (BarcodeDecoder, DecodedCode, NullBarcodeDecoder,
                       ScriptedBarcodeDecoder, ZxingBarcodeDecoder)
from .pipeline import (Page, PageResult, ReadingPipeline, ReadingResult,
                       assemble_facts, ingest_pages)
from .schemas import SCHEMAS, FieldSpec, field_map, to_json_schema

__all__ = [
    "Artefact", "ALL_TYPES", "CARRIES_QR",
    "BarcodeDecoder", "DecodedCode", "NullBarcodeDecoder", "ScriptedBarcodeDecoder", "ZxingBarcodeDecoder",
    "Page", "PageResult", "ReadingPipeline", "ReadingResult", "ingest_pages", "assemble_facts",
    "SCHEMAS", "FieldSpec", "field_map", "to_json_schema",
]

"""Canonical provider-free commitments for managed benchmark Infinity writes."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Final

from infinity_context_core.domain.errors import MemoryValidationError

MANAGED_INFINITY_OPERATION_SCHEMA_VERSION: Final = "memory-comparison-managed-infinity-operation.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FACT_KEYS = {
    "schema_version",
    "lane",
    "source_external_id_sha256",
    "content_sha256",
    "kind",
    "classification",
    "source_refs_sha256",
}
_DOCUMENT_KEYS = {
    "schema_version",
    "lane",
    "source_external_id_sha256",
    "content_sha256",
    "title_sha256",
    "source_type",
    "classification",
    "source_refs_sha256",
    "fragment_count",
    "fragments_sha256",
}


def managed_benchmark_text_sha256(value: str) -> str:
    if type(value) is not str:
        raise MemoryValidationError("Managed benchmark text commitment is invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise MemoryValidationError("Managed benchmark text commitment is invalid") from None
    return hashlib.sha256(encoded).hexdigest()


def managed_benchmark_sequence_sha256(value: Sequence[dict[str, object]]) -> str:
    """Commit one ordered exact JSON descriptor sequence."""

    if type(value) not in {tuple, list} or any(type(item) is not dict for item in value):
        raise MemoryValidationError("Managed benchmark descriptor sequence is invalid")
    return _canonical_sha256(list(value))


def managed_benchmark_infinity_operation_sha256(material: dict[str, object]) -> str:
    """Validate and commit one exact fact or document operation descriptor."""

    if type(material) is not dict:
        raise MemoryValidationError("Managed benchmark Infinity operation is invalid")
    lane = material.get("lane")
    expected_keys = _FACT_KEYS if lane == "fact" else _DOCUMENT_KEYS if lane == "document" else None
    if expected_keys is None or set(material) != expected_keys:
        raise MemoryValidationError("Managed benchmark Infinity operation is invalid")
    if material["schema_version"] != MANAGED_INFINITY_OPERATION_SCHEMA_VERSION:
        raise MemoryValidationError("Managed benchmark Infinity operation is invalid")
    for key in (
        "source_external_id_sha256",
        "content_sha256",
        "source_refs_sha256" if lane == "fact" else "title_sha256",
    ):
        _require_sha256(material[key])
    for key in (
        ("kind", "classification")
        if lane == "fact"
        else (
            "source_type",
            "classification",
        )
    ):
        if type(material[key]) is not str or not material[key]:
            raise MemoryValidationError("Managed benchmark Infinity operation is invalid")
    if lane == "document":
        _require_sha256(material["source_refs_sha256"])
        _require_sha256(material["fragments_sha256"])
        count = material["fragment_count"]
        if type(count) is not int or count < 1:
            raise MemoryValidationError("Managed benchmark Infinity operation is invalid")
    return _canonical_sha256(material)


def managed_benchmark_fact_operation_material(
    *,
    source_external_id_sha256: str,
    content_sha256: str,
    kind: str,
    classification: str,
    source_refs: Sequence[dict[str, object]],
) -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": MANAGED_INFINITY_OPERATION_SCHEMA_VERSION,
        "lane": "fact",
        "source_external_id_sha256": source_external_id_sha256,
        "content_sha256": content_sha256,
        "kind": kind,
        "classification": classification,
        "source_refs_sha256": managed_benchmark_sequence_sha256(source_refs),
    }
    managed_benchmark_infinity_operation_sha256(material)
    return material


def managed_benchmark_fact_source_ref_descriptor(
    *,
    source_type: str,
    source_id: str,
    chunk_id: str | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
    quote_preview: str | None = None,
    page_number: int | None = None,
    time_start_ms: int | None = None,
    time_end_ms: int | None = None,
    bbox: Sequence[float] | None = None,
) -> dict[str, object]:
    if (
        type(source_type) is not str
        or not source_type
        or type(source_id) is not str
        or not source_id
    ):
        raise MemoryValidationError("Managed benchmark fact source reference is invalid")
    optional_ints = (char_start, char_end, page_number, time_start_ms, time_end_ms)
    if any(item is not None and (type(item) is not int or item < 0) for item in optional_ints):
        raise MemoryValidationError("Managed benchmark fact source reference is invalid")
    if bbox is not None and (
        type(bbox) not in {tuple, list}
        or len(bbox) != 4
        or any(type(item) not in {int, float} for item in bbox)
    ):
        raise MemoryValidationError("Managed benchmark fact source reference is invalid")
    return {
        "source_type": source_type,
        "source_id_sha256": managed_benchmark_text_sha256(source_id),
        "chunk_id_sha256": (
            managed_benchmark_text_sha256(chunk_id) if chunk_id is not None else None
        ),
        "char_start": char_start,
        "char_end": char_end,
        "quote_preview_sha256": (
            managed_benchmark_text_sha256(quote_preview) if quote_preview is not None else None
        ),
        "page_number": page_number,
        "time_start_ms": time_start_ms,
        "time_end_ms": time_end_ms,
        "bbox": list(bbox) if bbox is not None else None,
    }


def managed_benchmark_document_operation_material(
    *,
    source_external_id_sha256: str,
    content_sha256: str,
    title_sha256: str,
    source_type: str,
    classification: str,
    source_refs: Sequence[dict[str, object]],
    fragments: Sequence[dict[str, object]],
) -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": MANAGED_INFINITY_OPERATION_SCHEMA_VERSION,
        "lane": "document",
        "source_external_id_sha256": source_external_id_sha256,
        "content_sha256": content_sha256,
        "title_sha256": title_sha256,
        "source_type": source_type,
        "classification": classification,
        "source_refs_sha256": managed_benchmark_sequence_sha256(source_refs),
        "fragment_count": len(fragments),
        "fragments_sha256": managed_benchmark_sequence_sha256(fragments),
    }
    managed_benchmark_infinity_operation_sha256(material)
    return material


def managed_benchmark_document_fragment_descriptor(
    *,
    sequence: int,
    char_start: int,
    char_end: int,
    kind: str,
    text: str,
    node_kind: str,
    heading: str | None,
    ordinal_in_heading: int | None,
) -> dict[str, object]:
    if (
        type(sequence) is not int
        or sequence < 0
        or type(char_start) is not int
        or char_start < 0
        or type(char_end) is not int
        or char_end <= char_start
        or type(kind) is not str
        or not kind
        or type(text) is not str
        or not text
        or type(node_kind) is not str
        or not node_kind
        or (heading is not None and type(heading) is not str)
        or (
            ordinal_in_heading is not None
            and (type(ordinal_in_heading) is not int or ordinal_in_heading < 0)
        )
    ):
        raise MemoryValidationError("Managed benchmark document fragment is invalid")
    return {
        "sequence": sequence,
        "char_start": char_start,
        "char_end": char_end,
        "kind": kind,
        "text_sha256": managed_benchmark_text_sha256(text),
        "node_kind": node_kind,
        "heading_sha256": (managed_benchmark_text_sha256(heading) if heading is not None else None),
        "ordinal_in_heading": ordinal_in_heading,
    }


def _require_sha256(value: object) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise MemoryValidationError("Managed benchmark Infinity operation is invalid")


def _canonical_sha256(value: object) -> str:
    try:
        payload = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        if json.loads(payload) != value:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError("Managed benchmark commitment material is invalid") from exc
    return hashlib.sha256(payload).hexdigest()


__all__ = (
    "MANAGED_INFINITY_OPERATION_SCHEMA_VERSION",
    "managed_benchmark_document_operation_material",
    "managed_benchmark_document_fragment_descriptor",
    "managed_benchmark_fact_operation_material",
    "managed_benchmark_fact_source_ref_descriptor",
    "managed_benchmark_infinity_operation_sha256",
    "managed_benchmark_sequence_sha256",
    "managed_benchmark_text_sha256",
)

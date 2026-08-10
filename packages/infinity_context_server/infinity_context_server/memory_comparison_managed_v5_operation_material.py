"""Pure managed-v5 Infinity operation-material formulas shared by projectors."""

from __future__ import annotations

import hashlib

from infinity_context_core.application.document_fragments import (
    DocumentFragment,
    fragment_document_text,
)
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_document_fragment_descriptor,
    managed_benchmark_document_operation_material,
    managed_benchmark_fact_operation_material,
    managed_benchmark_fact_source_ref_descriptor,
    managed_benchmark_text_sha256,
)

from infinity_context_server.memory_comparison_canonical_source_hash import (
    document_source_hash,
    memory_source_hash,
)
from infinity_context_server.memory_comparison_conversation_ingestion import (
    sanitize_source_refs,
)
from infinity_context_server.memory_comparison_http_ingest_request import (
    source_reference_payload,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
)


def managed_v5_infinity_fact_operation_material(
    memory: BenchmarkMemoryInput,
) -> dict[str, object]:
    identity = memory_source_hash(memory)
    source_ref = source_reference_payload(
        source_type="memory_comparison_benchmark",
        source_id=identity.source_id,
        quote_preview=memory.text,
    )
    return managed_benchmark_fact_operation_material(
        source_external_id_sha256=_text_sha(identity.source_id),
        content_sha256=identity.source_sha256,
        kind=memory.kind,
        classification="internal",
        source_refs=(
            managed_benchmark_fact_source_ref_descriptor(
                source_type=str(source_ref["source_type"]),
                source_id=str(source_ref["source_id"]),
                quote_preview=str(source_ref["quote_preview"]),
            ),
        ),
    )


def managed_v5_infinity_document_operation_material(
    document: BenchmarkDocumentInput,
    *,
    fragments: tuple[DocumentFragment, ...] | None = None,
) -> dict[str, object]:
    identity = document_source_hash(document)
    rendered = fragment_document_text(document.text) if fragments is None else fragments
    return managed_benchmark_document_operation_material(
        source_external_id_sha256=_text_sha(identity.source_id),
        content_sha256=identity.source_sha256,
        title_sha256=managed_benchmark_text_sha256(document.title),
        source_type=document.source_type,
        classification=document.classification,
        fragments=tuple(managed_v5_infinity_fragment_descriptor(item) for item in rendered),
        source_refs=tuple(sanitize_source_refs(document.source_refs)),
    )


def managed_v5_infinity_fragment_descriptor(fragment: DocumentFragment) -> dict[str, object]:
    return managed_benchmark_document_fragment_descriptor(
        sequence=fragment.sequence,
        char_start=fragment.char_start,
        char_end=fragment.char_end,
        kind=fragment.kind.value,
        text=fragment.text,
        node_kind=fragment.node_kind,
        heading=fragment.heading,
        ordinal_in_heading=fragment.ordinal_in_heading,
    )


def _text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = (
    "managed_v5_infinity_document_operation_material",
    "managed_v5_infinity_fact_operation_material",
    "managed_v5_infinity_fragment_descriptor",
)

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_document_fragment_descriptor,
    managed_benchmark_document_operation_material,
    managed_benchmark_fact_operation_material,
    managed_benchmark_fact_source_ref_descriptor,
    managed_benchmark_infinity_operation_sha256,
    managed_benchmark_text_sha256,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    corpus_identity_sha256,
    fragment_commitments,
    fragment_descriptor_sha256,
    memory_scope_external_ref_sha256,
    source_ref_commitments,
    thread_external_ref_sha256,
)

_EVIDENCE = "__authority_evidence"
_KINDS = {
    "memory_scopes",
    "memory_threads",
    "facts",
    "fact_source_refs",
    "documents",
    "chunks",
}


class ExpectedRowIndexLookup(Protocol):
    def lookup_source(self, source_identity_sha256: str) -> Any | None: ...
    def has_corpus(self, corpus_identity_sha256: str) -> bool: ...
    def lookup_fragment(
        self, *, sequence: int, ordinal: int, descriptor_sha256: str
    ) -> tuple[Any, int] | None: ...
    def lookup_source_ref_descriptors(self, sequence: int) -> tuple[str, ...]: ...
    def lookup_fragment_descriptors(self, sequence: int) -> tuple[str, ...]: ...


def verify_expected_row(
    *,
    index: ExpectedRowIndexLookup,
    context: ManagedCleanupV3Context,
    kind: str,
    locator_json: Mapping[str, object],
    row_json: Mapping[str, object],
) -> tuple[str, str | int, Mapping[str, object]]:
    if (
        type(context) is not ManagedCleanupV3Context
        or kind not in _KINDS
        or not isinstance(locator_json, Mapping)
        or not isinstance(row_json, Mapping)
    ):
        _fail("binding_invalid")
    context.__post_init__()
    row, evidence = _split_row(row_json)
    locator = _locator(kind, locator_json, row)
    if kind == "memory_scopes":
        item = _scope(index, context, row, evidence)
    elif kind == "memory_threads":
        item = _thread(index, context, row, evidence)
    elif kind == "facts":
        item = _fact(index, context, row, evidence)
    elif kind == "fact_source_refs":
        item = _fact_ref(index, context, row, evidence)
    elif kind == "documents":
        item = _document(index, context, row, evidence)
    else:
        item = _chunk(index, context, row, evidence)
    return kind, item, locator


def _scope(
    index: ExpectedRowIndexLookup,
    context: ManagedCleanupV3Context,
    row: dict[str, object],
    evidence: dict[str, object],
) -> str:
    _require_keys(evidence, {"memory_scope_external_ref", "thread_external_ref", "lane"})
    external_ref, thread_ref, lane = _identity_evidence(evidence)
    if row.get("external_ref") != external_ref:
        _fail("scope_invalid")
    _base(context, row, scope=False, thread=False)
    _, _, corpus_sha = _identity_shas(external_ref, thread_ref, lane)
    if not index.has_corpus(corpus_sha):
        _fail("scope_invalid")
    return corpus_sha


def _thread(
    index: ExpectedRowIndexLookup,
    context: ManagedCleanupV3Context,
    row: dict[str, object],
    evidence: dict[str, object],
) -> str:
    _require_keys(evidence, {"memory_scope_external_ref", "thread_external_ref", "lane"})
    scope_ref, thread_ref, lane = _identity_evidence(evidence)
    _base(context, row, scope=True, thread=False)
    if row.get("external_ref") != thread_ref:
        _fail("thread_invalid")
    _, _, corpus_sha = _identity_shas(scope_ref, thread_ref, lane)
    if not index.has_corpus(corpus_sha):
        _fail("thread_invalid")
    return corpus_sha


def _fact(
    index: ExpectedRowIndexLookup,
    context: ManagedCleanupV3Context,
    row: dict[str, object],
    evidence: dict[str, object],
) -> int:
    _require_keys(
        evidence,
        {"memory_scope_external_ref", "thread_external_ref", "ordered_source_refs"},
    )
    scope_ref, thread_ref = _scope_thread_evidence(evidence)
    refs = _mapping_list(evidence["ordered_source_refs"])
    return _fact_operation(index, context, row, scope_ref, thread_ref, refs).sequence


def _fact_ref(
    index: ExpectedRowIndexLookup,
    context: ManagedCleanupV3Context,
    row: dict[str, object],
    evidence: dict[str, object],
) -> str:
    _require_keys(
        evidence,
        {
            "canonical_fact",
            "memory_scope_external_ref",
            "thread_external_ref",
            "ordered_source_refs",
            "source_ref_ordinal",
        },
    )
    fact = _plain_mapping(evidence["canonical_fact"])
    scope_ref, thread_ref = _scope_thread_evidence(evidence)
    refs = _mapping_list(evidence["ordered_source_refs"])
    ordinal = _exact_int(evidence["source_ref_ordinal"])
    if (
        ordinal >= len(refs)
        or row != refs[ordinal]
        or row.get("fact_id") != fact.get("id")
        or row.get("fact_version") != fact.get("version")
    ):
        _fail("fact_source_ref_invalid")
    operation = _fact_operation(index, context, fact, scope_ref, thread_ref, refs)
    return operation.sequence


def _fact_operation(
    index: ExpectedRowIndexLookup,
    context: ManagedCleanupV3Context,
    fact: dict[str, object],
    scope_ref: str,
    thread_ref: str,
    refs: list[dict[str, object]],
) -> Any:
    _base(context, fact, scope=True, thread=True)
    descriptors = [_fact_ref_descriptor(item) for item in refs]
    source_refs_sha, descriptor_sha, source_ref_root = source_ref_commitments(descriptors)
    source_ids = {item.get("source_id") for item in refs}
    if len(refs) != 1 or len(source_ids) != 1 or not _nonempty_text(next(iter(source_ids))):
        _fail("fact_invalid")
    if type(refs[0].get("id")) is not int or type(refs[0].get("fact_version")) is not int:
        _fail("fact_invalid")
    source_id = str(next(iter(source_ids)))
    operation = index.lookup_source(managed_benchmark_text_sha256(source_id))
    material = managed_benchmark_fact_operation_material(
        source_external_id_sha256=managed_benchmark_text_sha256(source_id),
        content_sha256=managed_benchmark_text_sha256(_text(fact, "text")),
        kind=_text(fact, "kind"),
        classification=_text(fact, "classification"),
        source_refs=descriptors,
    )
    if (
        not _operation_matches(operation, "fact", scope_ref, thread_ref)
        or operation is None
        or index.lookup_source_ref_descriptors(operation.sequence) != descriptor_sha
        or operation.source_refs_sha256 != source_refs_sha
        or operation.source_ref_root_sha256 != source_ref_root
    ):
        _fail("fact_invalid")
    assert operation is not None
    if operation.source_content_sha256 != material[
        "content_sha256"
    ] or operation.operation_commitment_sha256 != managed_benchmark_infinity_operation_sha256(
        material
    ):
        _fail("fact_invalid")
    return operation


def _document(
    index: ExpectedRowIndexLookup,
    context: ManagedCleanupV3Context,
    row: dict[str, object],
    evidence: dict[str, object],
) -> int:
    _require_keys(
        evidence,
        {"memory_scope_external_ref", "thread_external_ref", "ordered_chunks"},
    )
    scope_ref, thread_ref = _scope_thread_evidence(evidence)
    chunks = _mapping_list(evidence["ordered_chunks"])
    return _document_operation(index, context, row, scope_ref, thread_ref, chunks).sequence


def _chunk(
    index: ExpectedRowIndexLookup,
    context: ManagedCleanupV3Context,
    row: dict[str, object],
    evidence: dict[str, object],
) -> str:
    _require_keys(
        evidence,
        {
            "document",
            "memory_scope_external_ref",
            "thread_external_ref",
            "chunk_ordinal",
        },
    )
    document = _plain_mapping(evidence["document"])
    scope_ref, thread_ref = _scope_thread_evidence(evidence)
    ordinal = _exact_int(evidence["chunk_ordinal"])
    _base(context, document, scope=True, thread=True)
    _base(context, row, scope=True, thread=True)
    operation = index.lookup_source(
        managed_benchmark_text_sha256(_text(document, "source_external_id"))
    )
    if (
        operation is None
        or not _operation_matches(operation, "document", scope_ref, thread_ref)
        or row.get("document_id") != document.get("id")
        or row.get("source_external_id") != document.get("source_external_id")
    ):
        _fail("chunk_invalid")
    descriptor_sha = _fragment_sha(row)
    hit = index.lookup_fragment(
        sequence=operation.sequence,
        ordinal=ordinal,
        descriptor_sha256=descriptor_sha,
    )
    if hit is None or hit[0].sequence != operation.sequence or hit[1] != ordinal:
        _fail("chunk_invalid")
    return f"{operation.sequence}:{ordinal}"


def _document_operation(
    index: ExpectedRowIndexLookup,
    context: ManagedCleanupV3Context,
    document: dict[str, object],
    scope_ref: str,
    thread_ref: str,
    chunks: list[dict[str, object]],
) -> Any:
    _base(context, document, scope=True, thread=True)
    source = _text(document, "source_external_id")
    operation = index.lookup_source(managed_benchmark_text_sha256(source))
    for chunk_row in chunks:
        _base(context, chunk_row, scope=True, thread=True)
    fragments = [_fragment(item) for item in chunks]
    if not _operation_matches(operation, "document", scope_ref, thread_ref):
        _fail("document_invalid")
    assert operation is not None
    raw_refs = _document_source_refs(chunks, operation.source_ref_count)
    source_refs_sha, descriptor_sha, source_ref_root = source_ref_commitments(raw_refs)
    if (
        not chunks
        or any(
            item.get("document_id") != document.get("id")
            or item.get("space_id") != document.get("space_id")
            or item.get("memory_scope_id") != document.get("memory_scope_id")
            or item.get("thread_id") != document.get("thread_id")
            for item in chunks
        )
        or [item.get("sequence") for item in chunks] != list(range(len(chunks)))
        or index.lookup_source_ref_descriptors(operation.sequence) != descriptor_sha
        or operation.source_refs_sha256 != source_refs_sha
        or operation.source_ref_root_sha256 != source_ref_root
    ):
        _fail("document_invalid")
    material = managed_benchmark_document_operation_material(
        source_external_id_sha256=managed_benchmark_text_sha256(source),
        content_sha256=_text(document, "content_hash"),
        title_sha256=managed_benchmark_text_sha256(_text(document, "title")),
        source_type=_text(document, "source_type"),
        classification=_text(document, "classification"),
        source_refs=raw_refs,
        fragments=fragments,
    )
    fragments_sha, fragment_sha, fragment_root = fragment_commitments(fragments)
    if (
        operation.source_content_sha256 != material["content_sha256"]
        or index.lookup_fragment_descriptors(operation.sequence) != fragment_sha
        or operation.fragments_sha256 != fragments_sha
        or operation.fragment_root_sha256 != fragment_root
        or operation.operation_commitment_sha256
        != managed_benchmark_infinity_operation_sha256(material)
    ):
        _fail("document_invalid")
    return operation


def _operation_matches(
    operation: Any | None,
    lane: str,
    scope_ref: str,
    thread_ref: str,
) -> bool:
    scope_sha, thread_sha, corpus_sha = _identity_shas(scope_ref, thread_ref, lane)
    return bool(
        operation is not None
        and operation.lane == lane
        and operation.memory_scope_external_ref_sha256 == scope_sha
        and operation.thread_external_ref_sha256 == thread_sha
        and operation.corpus_identity_sha256 == corpus_sha
    )


def _document_source_refs(
    chunks: list[dict[str, object]], expected_count: int
) -> list[dict[str, object]]:  # noqa: E501
    if not chunks or expected_count not in {3, 4}:
        _fail("document_invalid")
    first_metadata = chunks[0].get("metadata_json")
    if not isinstance(first_metadata, Mapping):
        _fail("document_invalid")
    refs = _mapping_list(first_metadata.get("source_refs"))
    if len(refs) != expected_count:
        _fail("document_invalid")
    for chunk in chunks[1:]:
        metadata = chunk.get("metadata_json")
        if not isinstance(metadata, Mapping) or metadata.get("source_refs") != []:
            _fail("document_invalid")
    return refs


def _identity_shas(scope_ref: str, thread_ref: str, lane: str) -> tuple[str, str, str]:
    scope_sha = memory_scope_external_ref_sha256(scope_ref)
    thread_sha = thread_external_ref_sha256(thread_ref)
    return (
        scope_sha,
        thread_sha,
        corpus_identity_sha256(
            lane=lane,
            memory_scope_external_ref_sha256=scope_sha,
            thread_external_ref_sha256=thread_sha,
        ),
    )


def _fragment(row: Mapping[str, object]) -> dict[str, object]:
    metadata = row.get("metadata_json")
    if not isinstance(metadata, Mapping):
        _fail("chunk_invalid")
    return managed_benchmark_document_fragment_descriptor(
        sequence=_exact_int(row.get("sequence")),
        char_start=_exact_int(row.get("char_start")),
        char_end=_exact_int(row.get("char_end")),
        kind=_text(row, "kind"),
        text=_text(row, "text"),
        node_kind=_text(metadata, "node_kind"),
        heading=_optional_text(metadata.get("heading")),
        ordinal_in_heading=_optional_int(metadata.get("ordinal_in_heading")),
    )


def _fragment_sha(row: Mapping[str, object]) -> str:
    return fragment_descriptor_sha256(_fragment(row))


def _fact_ref_descriptor(row: Mapping[str, object]) -> dict[str, object]:
    return managed_benchmark_fact_source_ref_descriptor(
        source_type=_text(row, "source_type"),
        source_id=_text(row, "source_id"),
        chunk_id=_optional_text(row.get("chunk_id")),
        char_start=_optional_int(row.get("char_start")),
        char_end=_optional_int(row.get("char_end")),
        quote_preview=_optional_text(row.get("quote_preview")),
        page_number=_optional_int(row.get("page_number")),
        time_start_ms=_optional_int(row.get("time_start_ms")),
        time_end_ms=_optional_int(row.get("time_end_ms")),
        bbox=row.get("bbox_json"),
    )


def _base(
    context: ManagedCleanupV3Context,
    row: Mapping[str, object],
    *,
    scope: bool,
    thread: bool,
) -> None:
    if (
        row.get("space_id") != context.space_id
        or row.get("status") != "deleted"
        or (scope and not _nonempty_text(row.get("memory_scope_id")))
        or (thread and not _nonempty_text(row.get("thread_id")))
    ):
        _fail("row_binding_invalid")


def _locator(
    kind: str, locator: Mapping[str, object], row: Mapping[str, object]
) -> dict[str, object]:
    expected = {"id": row.get("id")}
    if kind == "fact_source_refs":
        expected.update(fact_id=row.get("fact_id"), fact_version=row.get("fact_version"))
    row_id = expected["id"]
    valid_id = (type(row_id) is str and bool(row_id)) or (type(row_id) is int and row_id >= 0)
    if dict(locator) != expected or not valid_id:
        _fail("locator_invalid")
    return expected


def _split_row(value: Mapping[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    row = dict(value)
    evidence = row.pop(_EVIDENCE, None)
    if type(evidence) is not dict or _EVIDENCE in row:
        _fail("evidence_invalid")
    return row, dict(evidence)


def _scope_thread_evidence(evidence: Mapping[str, object]) -> tuple[str, str]:
    return _text(evidence, "memory_scope_external_ref"), _text(evidence, "thread_external_ref")


def _identity_evidence(evidence: Mapping[str, object]) -> tuple[str, str, str]:
    scope_ref, thread_ref = _scope_thread_evidence(evidence)
    lane = _text(evidence, "lane")
    if lane not in {"fact", "document"}:
        _fail("evidence_invalid")
    return scope_ref, thread_ref, lane


def _plain_mapping(value: object) -> dict[str, object]:
    if type(value) is not dict or _EVIDENCE in value:
        _fail("evidence_invalid")
    return dict(value)


def _mapping_list(value: object) -> list[dict[str, object]]:
    if type(value) is not list or any(
        type(item) is not dict or _EVIDENCE in item for item in value
    ):
        _fail("evidence_invalid")
    return [dict(item) for item in value]


def _require_keys(value: Mapping[str, object], keys: set[str]) -> None:
    if set(value) != keys:
        _fail("evidence_invalid")


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not _nonempty_text(value):
        _fail("row_shape_invalid")
    return value  # type: ignore[return-value]


def _nonempty_text(value: object) -> bool:
    return type(value) is str and bool(value)


def _exact_int(value: object) -> int:
    if type(value) is not int or value < 0:
        _fail("row_shape_invalid")
    return value


def _optional_text(value: object) -> str | None:
    if value is not None and type(value) is not str:
        _fail("row_shape_invalid")
    return value


def _optional_int(value: object) -> int | None:
    if value is not None and (type(value) is not int or value < 0):
        _fail("row_shape_invalid")
    return value


def _fail(suffix: str) -> None:
    raise ManagedCleanupV3Error(f"managed_cleanup_v3_expected_row_{suffix}")

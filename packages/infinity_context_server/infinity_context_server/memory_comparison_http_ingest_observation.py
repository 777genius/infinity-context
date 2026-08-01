"""Bounded response-derived identities for managed HTTP ingestion evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

_MAX_ID_LENGTH = 512
_MAX_EVENT_LENGTH = 64
_MAX_INDEXING_STATUS_LENGTH = 128
_MAX_SOURCE_REFS = 64
_MAX_CREATED_ITEMS = 2_048
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class HttpIngestIdentityObservation:
    """Sanitized identity material derived only from an authenticated response."""

    backend: Literal["infinity", "mem0"]
    operation_type: Literal["fact", "document", "messages"]
    complete: bool
    issues: tuple[str, ...]
    canonical_record_ids: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()
    created_memory_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    source_sha256: tuple[str, ...] = ()
    status: str | None = None
    version: int | None = None
    indexing_status: str | None = None
    request_id: str | None = None
    events: tuple[str, ...] = ()

    def metadata(self) -> dict[str, object]:
        """Return a stable primitive-only representation suitable for HMAC binding."""

        return {
            "schema_version": "http_ingest_identity_observation.v1",
            "backend": self.backend,
            "operation_type": self.operation_type,
            "complete": self.complete,
            "issues": list(self.issues),
            "canonical_record_ids": list(self.canonical_record_ids),
            "fact_ids": list(self.fact_ids),
            "document_ids": list(self.document_ids),
            "chunk_ids": list(self.chunk_ids),
            "created_memory_ids": list(self.created_memory_ids),
            "source_ids": list(self.source_ids),
            "source_sha256": list(self.source_sha256),
            "status": self.status,
            "version": self.version,
            "indexing_status": self.indexing_status,
            "request_id": self.request_id,
            "events": list(self.events),
        }


@dataclass(frozen=True)
class HttpIngestIdentityManifest:
    """Exact ordered identities across all operations in one corpus ingest."""

    complete: bool
    operation_count: int
    issues: tuple[str, ...]
    operations: tuple[HttpIngestIdentityObservation, ...]
    canonical_record_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    document_ids: tuple[str, ...]
    chunk_ids: tuple[str, ...]
    created_memory_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    source_sha256: tuple[str, ...]

    def metadata(self) -> dict[str, object]:
        return {
            "schema_version": "http_ingest_identity_manifest.v1",
            "complete": self.complete,
            "operation_count": self.operation_count,
            "issues": list(self.issues),
            "operations": [operation.metadata() for operation in self.operations],
            "canonical_record_ids": list(self.canonical_record_ids),
            "fact_ids": list(self.fact_ids),
            "document_ids": list(self.document_ids),
            "chunk_ids": list(self.chunk_ids),
            "created_memory_ids": list(self.created_memory_ids),
            "source_ids": list(self.source_ids),
            "source_sha256": list(self.source_sha256),
        }


def infinity_ingest_identity_observation(
    response: httpx.Response,
    *,
    operation_type: Literal["fact", "document"],
) -> HttpIngestIdentityObservation:
    """Parse exact Infinity identities without copying response content or errors."""

    issues: list[str] = []
    data = _success_data(response, issues)
    record_id = _identifier(data.get("id"), "canonical_record_id", issues)
    status = _bounded_text(data.get("status"), "status", issues, required=True)
    indexing_status = _bounded_text(
        data.get("indexing_status"),
        "indexing_status",
        issues,
        required=True,
        max_length=_MAX_INDEXING_STATUS_LENGTH,
    )
    version = _positive_int(data.get("version"), "version", issues)
    source_ids, source_hashes = _source_identity_fields(data, issues)
    request_id = _response_request_id(response, data, issues)
    fact_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()
    if operation_type == "fact":
        fact_ids = (record_id,) if record_id is not None else ()
        if not source_ids:
            issues.append("source_ids_missing")
        if not source_hashes:
            issues.append("source_sha256_missing")
    else:
        document_ids = (record_id,) if record_id is not None else ()
        chunk_ids = _document_chunk_ids(data, issues)
        document_hash = _sha256(data.get("content_hash"), "source_sha256", issues)
        if document_hash is not None:
            source_hashes = _ordered_unique((*source_hashes, document_hash))
        source_external_id = _identifier(
            data.get("source_external_id"),
            "source_external_id",
            issues,
        )
        if source_external_id is not None:
            source_ids = _ordered_unique((*source_ids, source_external_id))
        if not source_ids:
            issues.append("source_ids_missing")
        if not source_hashes:
            issues.append("source_sha256_missing")
    canonical_ids = (record_id,) if record_id is not None else ()
    return HttpIngestIdentityObservation(
        backend="infinity",
        operation_type=operation_type,
        complete=not issues,
        issues=tuple(issues),
        canonical_record_ids=canonical_ids,
        fact_ids=fact_ids,
        document_ids=document_ids,
        chunk_ids=chunk_ids,
        source_ids=source_ids,
        source_sha256=source_hashes,
        status=status,
        version=version,
        indexing_status=indexing_status,
        request_id=request_id,
    )


def mem0_ingest_identity_observation(
    response: httpx.Response,
) -> HttpIngestIdentityObservation:
    """Parse exact Mem0 created-memory identities and bounded source metadata."""

    issues: list[str] = []
    payload = _success_payload(response, issues)
    raw_results = payload.get("results")
    if raw_results is None and isinstance(payload.get("data"), Mapping):
        raw_results = payload["data"].get("results")
    results = _bounded_mapping_sequence(raw_results, "results", issues)
    created_ids: list[str] = []
    events: list[str] = []
    source_ids: list[str] = []
    source_hashes: list[str] = []
    for index, item in enumerate(results):
        item_id = _identifier(item.get("id"), f"results[{index}].id", issues)
        if item_id is not None:
            created_ids.append(item_id)
        event = _bounded_text(
            item.get("event"),
            f"results[{index}].event",
            issues,
            required=True,
            max_length=_MAX_EVENT_LENGTH,
        )
        if event is not None:
            events.append(event)
        item_source_ids, item_hashes = _source_identity_fields(item, issues, prefix=index)
        source_ids.extend(item_source_ids)
        source_hashes.extend(item_hashes)
    _duplicate_issue(created_ids, "created_memory_id_duplicate", issues)
    request_id = _response_request_id(response, payload, issues)
    if request_id is None:
        issues.append("request_id_missing")
    if created_ids and not source_ids:
        issues.append("source_ids_missing")
    if created_ids and not source_hashes:
        issues.append("source_sha256_missing")
    return HttpIngestIdentityObservation(
        backend="mem0",
        operation_type="messages",
        complete=not issues,
        issues=tuple(issues),
        created_memory_ids=tuple(created_ids),
        source_ids=_ordered_unique(source_ids),
        source_sha256=_ordered_unique(source_hashes),
        request_id=request_id,
        events=tuple(events),
    )


def ingest_identity_manifest(
    observations: Sequence[HttpIngestIdentityObservation],
) -> HttpIngestIdentityManifest:
    """Aggregate ordered per-operation observations without synthesizing identities."""

    exact = tuple(observations)
    issues = (
        *(issue for observation in exact for issue in observation.issues),
        *_manifest_duplicate_issues(exact),
    )
    return HttpIngestIdentityManifest(
        complete=bool(exact) and not issues and all(item.complete for item in exact),
        operation_count=len(exact),
        issues=issues,
        operations=exact,
        canonical_record_ids=_flatten(exact, "canonical_record_ids"),
        fact_ids=_flatten(exact, "fact_ids"),
        document_ids=_flatten(exact, "document_ids"),
        chunk_ids=_flatten(exact, "chunk_ids"),
        created_memory_ids=_flatten(exact, "created_memory_ids"),
        source_ids=_flatten(exact, "source_ids"),
        source_sha256=_flatten(exact, "source_sha256"),
    )


def response_metadata(response: httpx.Response) -> dict[str, object]:
    """Operational response metadata, kept separate from identity evidence."""

    from infinity_context_core.application.sensitive_text import redact_sensitive_text

    metadata: dict[str, object] = {"status_code": response.status_code}
    if response.reason_phrase:
        metadata["reason_phrase"] = response.reason_phrase
    if response.status_code >= 400:
        preview = redact_sensitive_text(response.text.strip())[:500]
        if preview:
            metadata["error_preview"] = preview
    return metadata


def mem0_created_memory_count(response: httpx.Response) -> int:
    """Count mapping-shaped Mem0 results for backward-compatible telemetry."""

    try:
        payload = response.json()
    except ValueError:
        return 0
    if not isinstance(payload, Mapping):
        return 0
    results = payload.get("results")
    if not isinstance(results, Sequence) or isinstance(results, str | bytes):
        return 0
    return sum(1 for item in results if isinstance(item, Mapping))


def _success_data(response: httpx.Response, issues: list[str]) -> Mapping[str, object]:
    payload = _success_payload(response, issues)
    data = payload.get("data")
    if not isinstance(data, Mapping):
        issues.append("response_data_missing_or_invalid")
        return {}
    return data


def _success_payload(response: httpx.Response, issues: list[str]) -> Mapping[str, object]:
    if response.status_code >= 400:
        issues.append("http_status_not_success")
        return {}
    try:
        payload = response.json()
    except ValueError:
        issues.append("response_json_invalid")
        return {}
    if not isinstance(payload, Mapping):
        issues.append("response_payload_invalid")
        return {}
    return payload


def _document_chunk_ids(data: Mapping[str, object], issues: list[str]) -> tuple[str, ...]:
    raw_ids = data.get("chunk_ids")
    if raw_ids is None and isinstance(data.get("chunk_items"), Sequence):
        raw_ids = [
            item.get("id") if isinstance(item, Mapping) else None
            for item in data["chunk_items"]
        ]
    declared_count = data.get("chunks")
    if raw_ids is None:
        if type(declared_count) is int and declared_count == 0:
            return ()
        issues.append("chunk_ids_missing")
        return ()
    values = _bounded_sequence(raw_ids, "chunk_ids", issues)
    ids = [
        value
        for index, raw in enumerate(values)
        if (value := _identifier(raw, f"chunk_ids[{index}]", issues)) is not None
    ]
    _duplicate_issue(ids, "chunk_id_duplicate", issues)
    if type(declared_count) is int and declared_count != len(ids):
        issues.append("chunk_count_mismatch")
    return tuple(ids)


def _source_identity_fields(
    item: Mapping[str, object],
    issues: list[str],
    prefix: int | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    label = "source" if prefix is None else f"results[{prefix}].source"
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    source_ids: list[str] = []
    source_hashes: list[str] = []
    for key in ("source_id", "source_external_id"):
        raw = item.get(key, metadata.get(key))
        if raw is not None:
            value = _identifier(raw, f"{label}.{key}", issues)
            if value is not None:
                source_ids.append(value)
    refs = item.get("source_refs", metadata.get("source_refs"))
    if refs is not None:
        refs_exact = _bounded_mapping_sequence(
            refs,
            f"{label}.source_refs",
            issues,
            limit=_MAX_SOURCE_REFS,
        )
        for index, ref in enumerate(refs_exact):
            value = _identifier(
                ref.get("source_id"),
                f"{label}.source_refs[{index}].source_id",
                issues,
            )
            if value is not None:
                source_ids.append(value)
            for hash_key in ("source_sha256", "sha256", "content_hash"):
                if ref.get(hash_key) is not None:
                    digest = _sha256(
                        ref.get(hash_key),
                        f"{label}.source_refs[{index}].{hash_key}",
                        issues,
                    )
                    if digest is not None:
                        source_hashes.append(digest)
    for hash_key in ("source_sha256", "content_hash", "hash"):
        raw_hash = item.get(hash_key, metadata.get(hash_key))
        if raw_hash is not None:
            digest = _sha256(raw_hash, f"{label}.{hash_key}", issues)
            if digest is not None:
                source_hashes.append(digest)
    return _ordered_unique(source_ids), _ordered_unique(source_hashes)


def _response_request_id(
    response: httpx.Response,
    payload: Mapping[str, object],
    issues: list[str],
) -> str | None:
    raw = payload.get("request_id") or response.headers.get("x-request-id")
    if raw is None:
        return None
    return _identifier(raw, "request_id", issues)


def _bounded_mapping_sequence(
    value: object,
    label: str,
    issues: list[str],
    *,
    limit: int = _MAX_CREATED_ITEMS,
) -> tuple[Mapping[str, object], ...]:
    values = _bounded_sequence(value, label, issues, limit=limit)
    result: list[Mapping[str, object]] = []
    for index, item in enumerate(values):
        if not isinstance(item, Mapping):
            issues.append(f"{label}[{index}]_invalid")
        else:
            result.append(item)
    return tuple(result)


def _bounded_sequence(
    value: object,
    label: str,
    issues: list[str],
    *,
    limit: int = _MAX_CREATED_ITEMS,
) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        issues.append(f"{label}_missing_or_invalid")
        return ()
    exact = tuple(value)
    if len(exact) > limit:
        issues.append(f"{label}_limit_exceeded")
        return exact[:limit]
    return exact


def _identifier(value: object, label: str, issues: list[str]) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_ID_LENGTH
    ):
        issues.append(f"{label}_missing_or_invalid")
        return None
    return value


def _bounded_text(
    value: object,
    label: str,
    issues: list[str],
    *,
    required: bool,
    max_length: int = _MAX_ID_LENGTH,
) -> str | None:
    if value is None and not required:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_length
    ):
        issues.append(f"{label}_missing_or_invalid")
        return None
    return value


def _positive_int(value: object, label: str, issues: list[str]) -> int | None:
    if type(value) is not int or value < 1:
        issues.append(f"{label}_missing_or_invalid")
        return None
    return value


def _sha256(value: object, label: str, issues: list[str]) -> str | None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        issues.append(f"{label}_missing_or_invalid")
        return None
    return value


def _duplicate_issue(values: Sequence[str], issue: str, issues: list[str]) -> None:
    if len(values) != len(set(values)):
        issues.append(issue)


def _manifest_duplicate_issues(
    observations: Sequence[HttpIngestIdentityObservation],
) -> tuple[str, ...]:
    issues: list[str] = []
    for field_name, issue in (
        ("canonical_record_ids", "canonical_record_id_duplicate"),
        ("fact_ids", "fact_id_duplicate"),
        ("document_ids", "document_id_duplicate"),
        ("chunk_ids", "chunk_id_duplicate"),
        ("created_memory_ids", "created_memory_id_duplicate"),
    ):
        values = _flatten(observations, field_name)
        if len(values) != len(set(values)):
            issues.append(issue)
    return tuple(issues)


def _ordered_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _flatten(
    observations: Sequence[HttpIngestIdentityObservation],
    field_name: str,
) -> tuple[str, ...]:
    return tuple(
        value
        for observation in observations
        for value in getattr(observation, field_name)
    )

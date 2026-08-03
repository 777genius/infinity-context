"""Bounded response-derived identities for managed HTTP ingestion evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from typing import Literal

import httpx
from infinity_context_core.application.sensitive_text import (
    contains_sensitive_text,
    redact_sensitive_text,
)

_MAX_ID_LENGTH = 512
_MAX_SOURCE_REFS = 64
_MAX_CREATED_ITEMS = 2_048
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ASCII_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+~-]{0,511}")
_ISSUE_RE = re.compile(r"[a-z0-9_.\[\]-]{1,160}")
_INFINITY_STATUSES = frozenset({"active"})
_INDEXING_STATUSES = frozenset(
    {
        "already_indexed_or_pending",
        "indexed",
        "indexing_failed",
        "nothing_to_process",
        "pending",
    }
)
_MEM0_EVENTS = frozenset({"ADD", "UPDATE", "DELETE"})
_GOLD_MARKERS = (
    "answerpreview",
    "evaluatorgold",
    "evaluatorgroundtruth",
    "expectedanswer",
    "expectedterms",
    "goldanswer",
    "groundtruth",
    "referenceanswer",
)


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
    space_id: str | None = None
    memory_scope_id: str | None = None
    thread_id: str | None = None
    observed_memory_ids: tuple[str, ...] = ()
    created_memory_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    source_sha256: tuple[str, ...] = ()
    status: str | None = None
    version: int | None = None
    indexing_status: str | None = None
    request_id: str | None = None
    events: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.backend not in {"infinity", "mem0"}:
            raise ValueError("HTTP ingest observation backend is invalid")
        if self.operation_type not in {"fact", "document", "messages"}:
            raise ValueError("HTTP ingest observation operation is invalid")
        if type(self.complete) is not bool:
            raise ValueError("HTTP ingest observation completeness is invalid")
        for lane in (
            self.canonical_record_ids,
            self.fact_ids,
            self.document_ids,
            self.chunk_ids,
            self.observed_memory_ids,
            self.created_memory_ids,
            self.source_ids,
        ):
            _safe_identifier_tuple(lane)
        for scope_identity in (self.space_id, self.memory_scope_id, self.thread_id):
            if scope_identity is not None and not _safe_identifier(scope_identity):
                raise ValueError("HTTP ingest observation scope identity is invalid")
        if self.complete and self.backend == "infinity" and (
            self.space_id is None or self.memory_scope_id is None
        ):
            raise ValueError("Complete Infinity observation requires canonical scope")
        _sha256_tuple(self.source_sha256)
        _safe_issue_tuple(self.issues)
        if self.complete != (not self.issues):
            raise ValueError("HTTP ingest observation completeness is inconsistent")
        if self.status is not None and self.status not in _INFINITY_STATUSES:
            raise ValueError("HTTP ingest observation status is invalid")
        if (
            self.indexing_status is not None
            and self.indexing_status not in _INDEXING_STATUSES
        ):
            raise ValueError("HTTP ingest observation indexing status is invalid")
        if self.request_id is not None and not _safe_identifier(self.request_id):
            raise ValueError("HTTP ingest observation request ID is invalid")
        if type(self.events) is not tuple or any(
            event not in _MEM0_EVENTS for event in self.events
        ):
            raise ValueError("HTTP ingest observation event is invalid")
        if any(item not in self.observed_memory_ids for item in self.created_memory_ids):
            raise ValueError("Created memory identity was not observed")
        if self.complete and self.backend == "mem0":
            expected_created = tuple(
                item_id
                for item_id, event in zip(self.observed_memory_ids, self.events, strict=True)
                if event == "ADD"
            )
            if expected_created != self.created_memory_ids:
                raise ValueError("Created memory event semantics are inconsistent")

    def metadata(self) -> dict[str, object]:
        """Return a stable primitive-only representation suitable for HMAC binding."""

        return {
            "schema_version": "http_ingest_identity_observation.v2",
            "backend": self.backend,
            "operation_type": self.operation_type,
            "complete": self.complete,
            "issues": list(self.issues),
            "canonical_record_ids": list(self.canonical_record_ids),
            "fact_ids": list(self.fact_ids),
            "document_ids": list(self.document_ids),
            "chunk_ids": list(self.chunk_ids),
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "thread_id": self.thread_id,
            "observed_memory_ids": list(self.observed_memory_ids),
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
    space_id: str | None
    memory_scope_id: str | None
    thread_id: str | None
    observed_memory_ids: tuple[str, ...]
    created_memory_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    source_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.complete) is not bool or type(self.operation_count) is not int:
            raise ValueError("HTTP ingest identity manifest shape is invalid")
        if self.operation_count != len(self.operations):
            raise ValueError("HTTP ingest identity manifest operation count is invalid")
        if type(self.operations) is not tuple or any(
            type(item) is not HttpIngestIdentityObservation for item in self.operations
        ):
            raise ValueError("HTTP ingest identity manifest operations are invalid")
        _safe_issue_tuple(self.issues)
        expected_complete = bool(self.operations) and not self.issues and all(
            item.complete for item in self.operations
        )
        if self.complete != expected_complete:
            raise ValueError("HTTP ingest identity manifest completeness is inconsistent")
        for lane in (
            self.canonical_record_ids,
            self.fact_ids,
            self.document_ids,
            self.chunk_ids,
            self.observed_memory_ids,
            self.created_memory_ids,
            self.source_ids,
        ):
            _safe_identifier_tuple(lane)
        for field_name in ("space_id", "memory_scope_id", "thread_id"):
            value = getattr(self, field_name)
            if value is not None and not _safe_identifier(value):
                raise ValueError("HTTP ingest manifest scope identity is invalid")
            if value != _shared_scope_identity(self.operations, field_name, []):
                raise ValueError("HTTP ingest manifest scope identity is inconsistent")
        _sha256_tuple(self.source_sha256)
        for field_name in (
            "canonical_record_ids",
            "fact_ids",
            "document_ids",
            "chunk_ids",
            "observed_memory_ids",
            "created_memory_ids",
            "source_ids",
            "source_sha256",
        ):
            if getattr(self, field_name) != _flatten(self.operations, field_name):
                raise ValueError("HTTP ingest identity manifest lane is inconsistent")

    def metadata(self) -> dict[str, object]:
        return {
            "schema_version": "http_ingest_identity_manifest.v2",
            "complete": self.complete,
            "operation_count": self.operation_count,
            "issues": list(self.issues),
            "operations": [operation.metadata() for operation in self.operations],
            "canonical_record_ids": list(self.canonical_record_ids),
            "fact_ids": list(self.fact_ids),
            "document_ids": list(self.document_ids),
            "chunk_ids": list(self.chunk_ids),
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "thread_id": self.thread_id,
            "observed_memory_ids": list(self.observed_memory_ids),
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
    space_id = _identifier(data.get("space_id"), "space_id", issues)
    memory_scope_id = _identifier(
        data.get("memory_scope_id"), "memory_scope_id", issues
    )
    thread_id = (
        _identifier(data.get("thread_id"), "thread_id", issues)
        if data.get("thread_id") is not None
        else None
    )
    record_id = _identifier(data.get("id"), "canonical_record_id", issues)
    status = _enum_value(
        data.get("status"),
        "status",
        _INFINITY_STATUSES,
        issues,
    )
    indexing_status = _enum_value(
        data.get("indexing_status"),
        "indexing_status",
        _INDEXING_STATUSES,
        issues,
    )
    source_ids, source_hashes = _source_identity_fields(data, issues)
    request_id = _response_request_id(response, data, issues)
    fact_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()
    if operation_type == "fact":
        version = _positive_int(data.get("version"), "version", issues)
        fact_ids = (record_id,) if record_id is not None else ()
        if not source_ids:
            issues.append("source_ids_missing")
        if not source_hashes:
            issues.append("source_sha256_missing")
    else:
        version = (
            _positive_int(data.get("version"), "version", issues)
            if "version" in data
            else None
        )
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
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
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
    observed_ids: list[str] = []
    created_ids: list[str] = []
    events: list[str] = []
    source_ids: list[str] = []
    source_hashes: list[str] = []
    for index, item in enumerate(results):
        item_id = _identifier(item.get("id"), f"results[{index}].id", issues)
        if item_id is not None:
            observed_ids.append(item_id)
        event = _enum_value(
            item.get("event"),
            f"results[{index}].event",
            _MEM0_EVENTS,
            issues,
        )
        if event is not None:
            events.append(event)
        if item_id is not None and event == "ADD":
            created_ids.append(item_id)
        item_source_ids, item_hashes = _source_identity_fields(item, issues, prefix=index)
        source_ids.extend(item_source_ids)
        source_hashes.extend(item_hashes)
    _duplicate_issue(observed_ids, "observed_memory_id_duplicate", issues)
    _duplicate_issue(created_ids, "created_memory_id_duplicate", issues)
    request_id = _response_request_id(response, payload, issues)
    if request_id is None:
        issues.append("request_id_missing")
    if observed_ids and not source_ids:
        issues.append("source_ids_missing")
    if observed_ids and not source_hashes:
        issues.append("source_sha256_missing")
    return HttpIngestIdentityObservation(
        backend="mem0",
        operation_type="messages",
        complete=not issues,
        issues=tuple(issues),
        observed_memory_ids=tuple(observed_ids),
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
    issues = [
        *(issue for observation in exact for issue in observation.issues),
        *_manifest_duplicate_issues(exact),
    ]
    space_id = _shared_scope_identity(exact, "space_id", issues)
    memory_scope_id = _shared_scope_identity(exact, "memory_scope_id", issues)
    thread_id = _shared_scope_identity(exact, "thread_id", issues)
    return HttpIngestIdentityManifest(
        complete=bool(exact) and not issues and all(item.complete for item in exact),
        operation_count=len(exact),
        issues=tuple(issues),
        operations=exact,
        canonical_record_ids=_flatten(exact, "canonical_record_ids"),
        fact_ids=_flatten(exact, "fact_ids"),
        document_ids=_flatten(exact, "document_ids"),
        chunk_ids=_flatten(exact, "chunk_ids"),
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        observed_memory_ids=_flatten(exact, "observed_memory_ids"),
        created_memory_ids=_flatten(exact, "created_memory_ids"),
        source_ids=_flatten(exact, "source_ids"),
        source_sha256=_flatten(exact, "source_sha256"),
    )


def response_metadata(response: httpx.Response) -> dict[str, object]:
    """Operational response metadata, kept separate from identity evidence."""

    metadata: dict[str, object] = {"status_code": response.status_code}
    try:
        canonical_reason = HTTPStatus(response.status_code).phrase
    except ValueError:
        canonical_reason = None
    if canonical_reason:
        metadata["reason_phrase"] = canonical_reason
    if response.status_code >= 400:
        body = response.text.strip()
        if contains_sensitive_text(body) or _contains_gold_marker(body):
            preview = "[redacted]"
        else:
            preview = redact_sensitive_text(body)[:500]
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
    for hash_key in ("source_sha256", "content_sha256", "content_hash", "hash"):
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
    if not isinstance(value, str) or not _safe_identifier(value):
        issues.append(f"{label}_missing_or_invalid")
        return None
    return value


def _enum_value(
    value: object,
    label: str,
    accepted: frozenset[str],
    issues: list[str],
) -> str | None:
    if not isinstance(value, str) or value not in accepted:
        issues.append(f"{label}_missing_or_invalid")
        return None
    return value


def _safe_identifier(value: str) -> bool:
    if len(value) > _MAX_ID_LENGTH or not _ASCII_ID_RE.fullmatch(value):
        return False
    if contains_sensitive_text(value):
        return False
    return not _contains_gold_marker(value)


def _contains_gold_marker(value: str) -> bool:
    normalized = "".join(character.lower() for character in value if character.isalnum())
    return any(marker in normalized for marker in _GOLD_MARKERS)


def _safe_identifier_tuple(values: object) -> None:
    if type(values) is not tuple or any(
        not isinstance(value, str) or not _safe_identifier(value) for value in values
    ):
        raise ValueError("HTTP ingest observation identity lane is invalid")


def _sha256_tuple(values: object) -> None:
    if type(values) is not tuple or any(
        not isinstance(value, str) or not _SHA256_RE.fullmatch(value) for value in values
    ):
        raise ValueError("HTTP ingest observation hash lane is invalid")


def _safe_issue_tuple(values: object) -> None:
    if type(values) is not tuple or any(
        not isinstance(value, str) or not _ISSUE_RE.fullmatch(value) for value in values
    ):
        raise ValueError("HTTP ingest observation issue lane is invalid")


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
        ("observed_memory_ids", "observed_memory_id_duplicate"),
        ("created_memory_ids", "created_memory_id_duplicate"),
    ):
        values = _flatten(observations, field_name)
        if len(values) != len(set(values)):
            issues.append(issue)
    return tuple(issues)


def _shared_scope_identity(
    observations: Sequence[HttpIngestIdentityObservation],
    field_name: str,
    issues: list[str],
) -> str | None:
    values = tuple(getattr(observation, field_name) for observation in observations)
    if not values or all(value is None for value in values):
        return None
    non_null = tuple(value for value in values if value is not None)
    if len(non_null) != len(values) or len(set(non_null)) != 1:
        issue = f"{field_name}_mismatch"
        if issue not in issues:
            issues.append(issue)
        return None
    return non_null[0]


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

"""Strict pairing of authenticated managed HTTP ingest identity manifests."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from infinity_context_server.memory_comparison_http_ingest_observation import (
    HttpIngestIdentityManifest,
    HttpIngestIdentityObservation,
)
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedCanonicalProjectionScope,
    ManagedIngestIdentityManifest,
    ManagedPolicyObservationContractError,
)
from infinity_context_server.memory_comparison_models import BackendIngestResult

if TYPE_CHECKING:
    from infinity_context_server.memory_comparison_managed_http_lifecycle import (
        ManagedHttpIngestEvidenceView,
    )

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROLES = ("infinity-context", "mem0")
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "complete",
        "operation_count",
        "issues",
        "operations",
        "canonical_record_ids",
        "fact_ids",
        "document_ids",
        "chunk_ids",
        "space_id",
        "memory_scope_id",
        "thread_id",
        "observed_memory_ids",
        "created_memory_ids",
        "source_ids",
        "source_sha256",
    }
)
_OBSERVATION_KEYS = frozenset(
    {
        "schema_version",
        "backend",
        "operation_type",
        "complete",
        "issues",
        "canonical_record_ids",
        "fact_ids",
        "document_ids",
        "chunk_ids",
        "space_id",
        "memory_scope_id",
        "thread_id",
        "observed_memory_ids",
        "created_memory_ids",
        "source_ids",
        "source_sha256",
        "status",
        "version",
        "indexing_status",
        "request_id",
        "events",
    }
)


class ManagedIngestManifestParseError(ValueError):
    """Stable fail-closed error raised for malformed or misbound evidence."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedCorpusIngestIdentity:
    """One exact cross-backend ingest identity bundle for a unique corpus."""

    case_id: str
    corpus_id: str
    infinity_target_identity_sha256: str
    mem0_target_identity_sha256: str
    manifest: ManagedIngestIdentityManifest
    scope: ManagedCanonicalProjectionScope

    def __post_init__(self) -> None:
        if type(self.manifest) is not ManagedIngestIdentityManifest:
            raise ManagedIngestManifestParseError("managed_ingest_manifest_type_invalid")
        if type(self.scope) is not ManagedCanonicalProjectionScope:
            raise ManagedIngestManifestParseError("managed_ingest_scope_type_invalid")
        if not self.case_id or self.manifest.corpus_id != self.corpus_id:
            raise ManagedIngestManifestParseError("managed_ingest_corpus_binding_invalid")
        for target in (
            self.infinity_target_identity_sha256,
            self.mem0_target_identity_sha256,
        ):
            if type(target) is not str or _SHA256.fullmatch(target) is None:
                raise ManagedIngestManifestParseError("managed_ingest_target_invalid")


def parse_managed_ingest_identity_manifests(
    views: tuple[ManagedHttpIngestEvidenceView, ...],
) -> tuple[ManagedCorpusIngestIdentity, ...]:
    """Parse and pair exact Infinity/Mem0 manifests for every unique corpus."""

    from infinity_context_server.memory_comparison_managed_http_lifecycle import (
        ManagedHttpIngestEvidenceView,
    )

    if type(views) is not tuple or not views:
        raise ManagedIngestManifestParseError("managed_ingest_views_invalid")
    if any(type(view) is not ManagedHttpIngestEvidenceView for view in views):
        raise ManagedIngestManifestParseError("managed_ingest_view_type_invalid")

    targets: dict[str, str] = {}
    case_corpora: dict[str, str] = {}
    corpus_order: list[str] = []
    paired: dict[str, dict[str, ManagedHttpIngestEvidenceView]] = {}
    for view in views:
        if view.backend_role not in _ROLES:
            raise ManagedIngestManifestParseError("managed_ingest_backend_role_invalid")
        _digest(view.target_identity_sha256, "managed_ingest_target_invalid")
        known_target = targets.setdefault(view.backend_role, view.target_identity_sha256)
        if known_target != view.target_identity_sha256:
            raise ManagedIngestManifestParseError("managed_ingest_target_mismatch")
        if not view.case_id or not view.corpus_id:
            raise ManagedIngestManifestParseError("managed_ingest_corpus_binding_invalid")
        known_corpus = case_corpora.setdefault(view.case_id, view.corpus_id)
        if known_corpus != view.corpus_id:
            raise ManagedIngestManifestParseError("managed_ingest_cross_corpus_mismatch")
        if view.corpus_id not in paired:
            paired[view.corpus_id] = {}
            corpus_order.append(view.corpus_id)
        corpus_views = paired[view.corpus_id]
        if view.backend_role in corpus_views:
            raise ManagedIngestManifestParseError("managed_ingest_duplicate_view")
        corpus_views[view.backend_role] = view

    if set(targets) != set(_ROLES):
        raise ManagedIngestManifestParseError("managed_ingest_backend_coverage_invalid")

    bundles: list[ManagedCorpusIngestIdentity] = []
    for corpus_id in corpus_order:
        corpus_views = paired[corpus_id]
        if set(corpus_views) != set(_ROLES):
            raise ManagedIngestManifestParseError("managed_ingest_corpus_coverage_invalid")
        infinity_view = corpus_views["infinity-context"]
        mem0_view = corpus_views["mem0"]
        if infinity_view.case_id != mem0_view.case_id:
            raise ManagedIngestManifestParseError("managed_ingest_cross_corpus_mismatch")
        infinity = _manifest(infinity_view, expected_backend="infinity")
        mem0 = _manifest(mem0_view, expected_backend="mem0")
        scope = _scope(infinity)
        _mem0_scope_absent(mem0)
        infinity_sources = tuple(zip(infinity.source_ids, infinity.source_sha256, strict=True))
        mem0_sources = tuple(zip(mem0.source_ids, mem0.source_sha256, strict=True))
        if infinity_sources != mem0_sources:
            raise ManagedIngestManifestParseError("managed_ingest_source_pair_mismatch")

        try:
            manifest = ManagedIngestIdentityManifest(
                corpus_id=corpus_id,
                infinity_fact_ids=infinity.fact_ids,
                infinity_document_ids=infinity.document_ids,
                infinity_chunk_ids=infinity.chunk_ids,
                infinity_source_ids=infinity.source_ids,
                infinity_source_sha256=infinity.source_sha256,
                mem0_created_memory_ids=mem0.created_memory_ids,
                mem0_source_ids=mem0.source_ids,
                mem0_source_sha256=mem0.source_sha256,
                operation_count=infinity.operation_count + mem0.operation_count,
                complete=True,
                issues=(),
            )
        except ManagedPolicyObservationContractError as exc:
            raise ManagedIngestManifestParseError(
                "managed_ingest_combined_manifest_invalid"
            ) from exc
        bundles.append(
            ManagedCorpusIngestIdentity(
                case_id=infinity_view.case_id,
                corpus_id=corpus_id,
                infinity_target_identity_sha256=infinity_view.target_identity_sha256,
                mem0_target_identity_sha256=mem0_view.target_identity_sha256,
                manifest=manifest,
                scope=scope,
            )
        )
    return tuple(bundles)


def _manifest(
    view: ManagedHttpIngestEvidenceView,
    *,
    expected_backend: str,
) -> HttpIngestIdentityManifest:
    result = view.ingest_result
    if type(result) is not BackendIngestResult or not isinstance(result.metadata, Mapping):
        raise ManagedIngestManifestParseError("managed_ingest_result_invalid")
    if result.metadata.get("corpus_key") != view.corpus_id:
        raise ManagedIngestManifestParseError("managed_ingest_cross_corpus_mismatch")
    raw = result.metadata.get("ingest_identity_manifest")
    manifest_map = _exact_mapping(raw, _MANIFEST_KEYS, "managed_ingest_manifest_shape_invalid")
    if manifest_map["schema_version"] != "http_ingest_identity_manifest.v2":
        raise ManagedIngestManifestParseError("managed_ingest_manifest_schema_invalid")
    raw_operations = _list(manifest_map["operations"], "managed_ingest_manifest_shape_invalid")
    operations = tuple(
        _observation(value, expected_backend=expected_backend) for value in raw_operations
    )
    try:
        manifest = HttpIngestIdentityManifest(
            complete=_bool(manifest_map["complete"]),
            operation_count=_integer(manifest_map["operation_count"]),
            issues=_texts(manifest_map["issues"]),
            operations=operations,
            canonical_record_ids=_texts(manifest_map["canonical_record_ids"]),
            fact_ids=_texts(manifest_map["fact_ids"]),
            document_ids=_texts(manifest_map["document_ids"]),
            chunk_ids=_texts(manifest_map["chunk_ids"]),
            space_id=_optional_text(manifest_map["space_id"]),
            memory_scope_id=_optional_text(manifest_map["memory_scope_id"]),
            thread_id=_optional_text(manifest_map["thread_id"]),
            observed_memory_ids=_texts(manifest_map["observed_memory_ids"]),
            created_memory_ids=_texts(manifest_map["created_memory_ids"]),
            source_ids=_texts(manifest_map["source_ids"]),
            source_sha256=_texts(manifest_map["source_sha256"]),
        )
    except (TypeError, ValueError) as exc:
        raise ManagedIngestManifestParseError("managed_ingest_manifest_invalid") from exc
    if not manifest.complete or manifest.issues or manifest.metadata() != dict(manifest_map):
        raise ManagedIngestManifestParseError("managed_ingest_manifest_incomplete")
    _validate_backend_lanes(manifest, expected_backend=expected_backend)
    _validate_result_operations(result, raw_operations)
    return manifest


def _observation(value: object, *, expected_backend: str) -> HttpIngestIdentityObservation:
    raw = _exact_mapping(value, _OBSERVATION_KEYS, "managed_ingest_observation_shape_invalid")
    if raw["schema_version"] != "http_ingest_identity_observation.v2":
        raise ManagedIngestManifestParseError("managed_ingest_observation_schema_invalid")
    if raw["backend"] != expected_backend:
        raise ManagedIngestManifestParseError("managed_ingest_backend_mismatch")
    operation_type = raw["operation_type"]
    allowed_operations = {"fact", "document"} if expected_backend == "infinity" else {"messages"}
    if operation_type not in allowed_operations:
        raise ManagedIngestManifestParseError("managed_ingest_operation_backend_mismatch")
    try:
        observation = HttpIngestIdentityObservation(
            backend=expected_backend,  # type: ignore[arg-type]
            operation_type=operation_type,  # type: ignore[arg-type]
            complete=_bool(raw["complete"]),
            issues=_texts(raw["issues"]),
            canonical_record_ids=_texts(raw["canonical_record_ids"]),
            fact_ids=_texts(raw["fact_ids"]),
            document_ids=_texts(raw["document_ids"]),
            chunk_ids=_texts(raw["chunk_ids"]),
            space_id=_optional_text(raw["space_id"]),
            memory_scope_id=_optional_text(raw["memory_scope_id"]),
            thread_id=_optional_text(raw["thread_id"]),
            observed_memory_ids=_texts(raw["observed_memory_ids"]),
            created_memory_ids=_texts(raw["created_memory_ids"]),
            source_ids=_texts(raw["source_ids"]),
            source_sha256=_texts(raw["source_sha256"]),
            status=_optional_text(raw["status"]),
            version=_optional_integer(raw["version"]),
            indexing_status=_optional_text(raw["indexing_status"]),
            request_id=_optional_text(raw["request_id"]),
            events=_texts(raw["events"]),
        )
    except (TypeError, ValueError) as exc:
        raise ManagedIngestManifestParseError("managed_ingest_observation_invalid") from exc
    if not observation.complete or observation.issues or observation.metadata() != dict(raw):
        raise ManagedIngestManifestParseError("managed_ingest_observation_incomplete")
    return observation


def _validate_backend_lanes(manifest: HttpIngestIdentityManifest, *, expected_backend: str) -> None:
    if expected_backend == "infinity":
        operation_lanes_valid = all(_infinity_operation_valid(item) for item in manifest.operations)
        if (
            not operation_lanes_valid
            or not manifest.canonical_record_ids
            or manifest.canonical_record_ids != manifest.fact_ids + manifest.document_ids
            or manifest.observed_memory_ids
            or manifest.created_memory_ids
            or not manifest.source_ids
            or len(manifest.source_ids) != len(manifest.source_sha256)
            or (manifest.document_ids and not manifest.chunk_ids)
        ):
            raise ManagedIngestManifestParseError("managed_ingest_infinity_lanes_invalid")
        return
    if (
        any(not _mem0_operation_valid(item) for item in manifest.operations)
        or manifest.canonical_record_ids
        or manifest.fact_ids
        or manifest.document_ids
        or manifest.chunk_ids
        or not manifest.created_memory_ids
        or manifest.observed_memory_ids != manifest.created_memory_ids
        or not manifest.source_ids
        or len(manifest.source_ids) != len(manifest.source_sha256)
    ):
        raise ManagedIngestManifestParseError("managed_ingest_mem0_lanes_invalid")


def _infinity_operation_valid(item: HttpIngestIdentityObservation) -> bool:
    common = (
        len(item.canonical_record_ids) == 1
        and bool(item.source_ids)
        and len(item.source_ids) == len(item.source_sha256)
        and item.status == "active"
        and not item.observed_memory_ids
        and not item.created_memory_ids
    )
    if item.operation_type == "fact":
        return (
            common
            and item.canonical_record_ids == item.fact_ids
            and len(item.fact_ids) == 1
            and not item.document_ids
            and not item.chunk_ids
            and item.version is not None
        )
    return (
        common
        and item.operation_type == "document"
        and item.canonical_record_ids == item.document_ids
        and len(item.document_ids) == 1
        and bool(item.chunk_ids)
        and not item.fact_ids
        and item.indexing_status is not None
    )


def _mem0_operation_valid(item: HttpIngestIdentityObservation) -> bool:
    return (
        item.operation_type == "messages"
        and not item.canonical_record_ids
        and not item.fact_ids
        and not item.document_ids
        and not item.chunk_ids
        and item.observed_memory_ids == item.created_memory_ids
        and bool(item.created_memory_ids)
        and item.events == ("ADD",) * len(item.created_memory_ids)
    )


def _validate_result_operations(result: BackendIngestResult, raw_operations: list[object]) -> None:
    if (
        result.items_failed != 0
        or result.items_processed != len(raw_operations)
        or len(result.operations) != len(raw_operations)
    ):
        raise ManagedIngestManifestParseError("managed_ingest_result_coverage_invalid")
    for operation, raw in zip(result.operations, raw_operations, strict=True):
        if (
            operation.success is not True
            or operation.operation_type != raw["operation_type"]
            or not isinstance(operation.metadata, Mapping)
            or operation.metadata.get("ingest_identity_observation") != raw
        ):
            raise ManagedIngestManifestParseError("managed_ingest_result_binding_invalid")


def _scope(manifest: HttpIngestIdentityManifest) -> ManagedCanonicalProjectionScope:
    if manifest.space_id is None or manifest.memory_scope_id is None:
        raise ManagedIngestManifestParseError("managed_ingest_scope_incomplete")
    try:
        return ManagedCanonicalProjectionScope(
            manifest.space_id, manifest.memory_scope_id, manifest.thread_id
        )
    except ManagedPolicyObservationContractError as exc:
        raise ManagedIngestManifestParseError("managed_ingest_scope_invalid") from exc


def _mem0_scope_absent(manifest: HttpIngestIdentityManifest) -> None:
    if any(
        value is not None
        for value in (manifest.space_id, manifest.memory_scope_id, manifest.thread_id)
    ):
        raise ManagedIngestManifestParseError("managed_ingest_scope_mismatch")


def _exact_mapping(value: object, keys: frozenset[str], code: str) -> Mapping[str, object]:
    if (
        not isinstance(value, Mapping)
        or set(value) != keys
        or any(type(key) is not str for key in value)
    ):
        raise ManagedIngestManifestParseError(code)
    return value


def _list(value: object, code: str) -> list[object]:
    if type(value) is not list:
        raise ManagedIngestManifestParseError(code)
    return value


def _texts(value: object) -> tuple[str, ...]:
    items = _list(value, "managed_ingest_manifest_shape_invalid")
    if any(type(item) is not str for item in items):
        raise ManagedIngestManifestParseError("managed_ingest_manifest_shape_invalid")
    return tuple(items)


def _optional_text(value: object) -> str | None:
    if value is None or type(value) is str:
        return value
    raise ManagedIngestManifestParseError("managed_ingest_manifest_shape_invalid")


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise ManagedIngestManifestParseError("managed_ingest_manifest_shape_invalid")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ManagedIngestManifestParseError("managed_ingest_manifest_shape_invalid")
    return value


def _optional_integer(value: object) -> int | None:
    if value is None or type(value) is int:
        return value
    raise ManagedIngestManifestParseError("managed_ingest_manifest_shape_invalid")


def _digest(value: object, code: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedIngestManifestParseError(code)


__all__ = [
    "ManagedCorpusIngestIdentity",
    "ManagedIngestManifestParseError",
    "parse_managed_ingest_identity_manifests",
]

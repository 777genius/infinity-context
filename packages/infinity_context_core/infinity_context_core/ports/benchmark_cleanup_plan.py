"""Immutable cleanup authority sealed with a managed benchmark registration."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Final, final

from infinity_context_core.domain.errors import MemoryConflictError, MemoryValidationError

CLEANUP_PLAN_SCHEMA_VERSION: Final = "memory-comparison-unsealed-cleanup-plan.v2"
MAX_CLEANUP_PLAN_BYTES: Final = 128 * 1024 * 1024
MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND: Final = 5_000
MAX_CLEANUP_PLAN_RECOVERY_TOTAL_ROWS: Final = 20_000
MAX_CLEANUP_PLAN_CASES: Final = 5_000
MAX_CLEANUP_PLAN_CORPORA: Final = MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND
MAX_CLEANUP_PLAN_SOURCES: Final = MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND
MAX_CLEANUP_PLAN_UNITS: Final = MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_SPACE_SLUG = re.compile(r"^memory-comparison-[a-z0-9-]{1,80}$")
_TOP_LEVEL_KEYS = {
    "schema_version",
    "run_id_sha256",
    "binding_commitment_sha256",
    "infinity_target_identity_sha256",
    "space_id",
    "space_slug",
    "profile_id",
    "ordered_case_sha256",
    "corpora",
    "mem0",
    "infinity_namespace_policy_sha256",
    "qdrant",
    "graphiti",
    "cognee",
    "cardinality",
    "limits_policy_sha256",
}
_CORPUS_KEYS = {
    "ordinal",
    "corpus_id_sha256",
    "managed_corpus_projection_sha256",
    "memory_scope_external_ref_sha256",
    "thread_external_ref_sha256",
    "infinity_lane",
    "ordered_infinity_operation_sha256",
    "ordered_infinity_source_external_id_sha256",
    "ordered_infinity_content_sha256",
    "ordered_document_fragment_count",
    "expected_fact_count",
    "expected_document_count",
    "expected_chunk_count",
    "mem0_corpus_identity_sha256",
    "ordered_mem0_source_id_sha256",
    "ordered_mem0_unit_identity_sha256",
    "expected_ingest_unit_count",
}
_MEM0_KEYS = {
    "admission_commitment_sha256",
    "ingestion_manifest_sha256",
    "ingestion_root_sha256",
    "expected_operation_count",
}
_QDRANT_KEYS = {
    "target_commitment_sha256",
    "collection_projection_policy_sha256",
    "deterministic_scope_mapping_policy_sha256",
    "space_wide_scan_policy_sha256",
}
_GRAPHITI_KEYS = {
    "target_commitment_sha256",
    "group_mapping_policy_sha256",
    "space_prefix_scan_policy_sha256",
}
_CARDINALITY_KEYS = {
    "case_count",
    "corpus_count",
    "mem0_source_identity_count",
    "expected_ingest_unit_count",
    "infinity_operation_count",
    "expected_fact_count",
    "expected_document_count",
    "expected_chunk_count",
}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _commitment(value: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def managed_benchmark_cleanup_plan_material_sha256(value: object) -> str:
    """Digest strict canonical JSON plan material without exposing internals."""

    if type(value) is not dict:
        raise MemoryValidationError("Benchmark cleanup plan material is invalid")
    try:
        encoded = _canonical_bytes(value)
        canonical = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError("Benchmark cleanup plan material is invalid") from exc
    if canonical != value or len(encoded) > MAX_CLEANUP_PLAN_BYTES:
        raise MemoryValidationError("Benchmark cleanup plan material is invalid")
    return hashlib.sha256(encoded).hexdigest()


CLEANUP_PLAN_LIMITS_POLICY_SHA256: Final = _commitment(
    {
        "schema_version": "memory-comparison-cleanup-plan-limits-policy.v2",
        "max_bytes": MAX_CLEANUP_PLAN_BYTES,
        "max_cases": MAX_CLEANUP_PLAN_CASES,
        "max_corpora": MAX_CLEANUP_PLAN_CORPORA,
        "max_source_identities": MAX_CLEANUP_PLAN_SOURCES,
        "max_ingest_units": MAX_CLEANUP_PLAN_UNITS,
        "max_recovery_rows_per_kind": MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND,
        "max_recovery_total_rows": MAX_CLEANUP_PLAN_RECOVERY_TOTAL_ROWS,
        "recovery_row_expansion": {
            "memory_scopes_per_corpus": 1,
            "threads_per_corpus": 1,
            "facts": "exact_plan_count",
            "fact_source_refs": "exactly_one_per_fact",
            "documents": "exact_plan_count",
            "chunks": "exact_fragment_document_text_count",
            "episodes": 0,
        },
    }
)
INFINITY_NAMESPACE_POLICY_SHA256: Final = _commitment(
    {
        "schema_version": "memory-comparison-infinity-namespace-policy.v1",
        "canonical_identity_owner": "registered_benchmark_space",
        "space_id_policy": "benchmark-space-run-sha256-prefix-48",
        "scope_mapping": "managed_corpus_projection",
    }
)
COGNEE_NOT_PROJECTED_POLICY_SHA256: Final = _commitment(
    {
        "disposition": "not_projected",
        "schema_version": "memory-comparison-cognee-not-projected-policy.v1",
    }
)
QDRANT_COLLECTION_PROJECTION_POLICY_SHA256: Final = _commitment(
    {
        "schema_version": "memory-comparison-qdrant-collection-projection-policy.v1",
        "projection_version": "v1",
        "point_id": "uuid5(NAMESPACE_URL,chunk_id)",
        "identity_payload_fields": [
            "chunk_id",
            "space_id",
            "memory_scope_id",
            "thread_id",
            "projection_version",
        ],
    }
)
QDRANT_SCOPE_MAPPING_POLICY_SHA256: Final = _commitment(
    {
        "schema_version": "memory-comparison-qdrant-deterministic-scope-mapping-policy.v2",
        "identity_resolution": (
            "actual_canonical_space_scope_thread_chunk_ids_from_postgres_inventory"
        ),
        "ownership": "exact_registered_benchmark_space_id",
        "scope_admission": (
            "sha256(actual_memory_scope.external_ref) equals "
            "corpus.memory_scope_external_ref_sha256"
        ),
        "lineage_admission": "exact_canonical_document_and_fragment_commitments",
        "point_id": "uuid5(NAMESPACE_URL,actual_chunk_id)",
        "mem0_unit_identity_is_infinity_chunk_id": False,
        "block_on": ["unknown", "malformed", "foreign"],
    }
)
QDRANT_SPACE_WIDE_SCAN_POLICY_SHA256: Final = _commitment(
    {
        "schema_version": "memory-comparison-qdrant-space-wide-scan-policy.v1",
        "filter": {"field": "space_id", "match": "exact_registered_space_id"},
        "enumeration": "exhaustive_scroll_with_exact_count",
        "fresh_passes": 2,
        "block_on": ["unknown", "malformed"],
    }
)
GRAPHITI_GROUP_MAPPING_POLICY_SHA256: Final = _commitment(
    {
        "schema_version": "memory-comparison-graphiti-group-mapping-policy.v2",
        "group_id": "memory__{safe(space_id)}__{safe(memory_scope_id)}",
        "safe_normalization": "lowercase_non_alnum_to_underscore_collapse_trim",
        "space_id": "registered_benchmark_space_id",
        "memory_scope_id": "actual_canonical_memory_scope_id",
    }
)
GRAPHITI_SPACE_PREFIX_SCAN_POLICY_SHA256: Final = _commitment(
    {
        "schema_version": "memory-comparison-graphiti-space-prefix-scan-policy.v1",
        "enumeration": "collision_safe_space_prefix",
        "required_readback": ["expected_groups", "captured_uuid_global_readback"],
        "fresh_passes": 2,
        "block_on": ["unknown", "cross_group", "malformed"],
    }
)


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkCleanupPlan:
    """Validated exact plan plus its canonical external digest."""

    value: dict[str, object]
    sha256: str


@final
@dataclass(frozen=True, slots=True)
class CanonicalCleanupPlanSeal:
    """Nominal immutable seal; DB plan state and digest remain authoritative."""

    run_id_sha256: str
    cleanup_plan_sha256: str


@final
@dataclass(frozen=True, slots=True)
class ManagedBenchmarkCleanupTargetAuthority:
    """Provider-free authenticated target and mapping policy authority."""

    value: dict[str, object]
    authority_sha256: str


def build_managed_benchmark_cleanup_target_authority(
    *,
    infinity_target_identity_sha256: str,
    qdrant_target_commitment_sha256: str,
    graphiti_target_commitment_sha256: str,
) -> ManagedBenchmarkCleanupTargetAuthority:
    for digest in (
        infinity_target_identity_sha256,
        qdrant_target_commitment_sha256,
        graphiti_target_commitment_sha256,
    ):
        _require_digest(digest)
    material: dict[str, object] = {
        "schema_version": "memory-comparison-cleanup-target-authority.v1",
        "infinity_target_identity_sha256": infinity_target_identity_sha256,
        "qdrant": {
            "target_commitment_sha256": qdrant_target_commitment_sha256,
            "collection_projection_policy_sha256": (QDRANT_COLLECTION_PROJECTION_POLICY_SHA256),
            "deterministic_scope_mapping_policy_sha256": (QDRANT_SCOPE_MAPPING_POLICY_SHA256),
            "space_wide_scan_policy_sha256": QDRANT_SPACE_WIDE_SCAN_POLICY_SHA256,
        },
        "graphiti": {
            "target_commitment_sha256": graphiti_target_commitment_sha256,
            "group_mapping_policy_sha256": GRAPHITI_GROUP_MAPPING_POLICY_SHA256,
            "space_prefix_scan_policy_sha256": GRAPHITI_SPACE_PREFIX_SCAN_POLICY_SHA256,
        },
        "cognee": {
            "disposition": "not_projected",
            "policy_sha256": COGNEE_NOT_PROJECTED_POLICY_SHA256,
        },
    }
    authority_sha256 = _commitment(material)
    return ManagedBenchmarkCleanupTargetAuthority(
        value={**material, "authority_sha256": authority_sha256},
        authority_sha256=authority_sha256,
    )


def validate_managed_benchmark_cleanup_target_authority(
    value: object,
    *,
    infinity_target_identity_sha256: str,
) -> ManagedBenchmarkCleanupTargetAuthority:
    _require_digest(infinity_target_identity_sha256)
    if type(value) is not dict or set(value) != {
        "schema_version",
        "infinity_target_identity_sha256",
        "qdrant",
        "graphiti",
        "cognee",
        "authority_sha256",
    }:
        raise MemoryValidationError("Benchmark cleanup target authority is invalid")
    authority_sha256 = value["authority_sha256"]
    _require_digest(authority_sha256)
    material = {key: item for key, item in value.items() if key != "authority_sha256"}
    if (
        value["schema_version"] != "memory-comparison-cleanup-target-authority.v1"
        or value["infinity_target_identity_sha256"] != infinity_target_identity_sha256
        or not hmac.compare_digest(str(authority_sha256), _commitment(material))
    ):
        raise MemoryConflictError("Benchmark cleanup target authority conflicted")
    _digest_policy(value["qdrant"], _QDRANT_KEYS)
    _digest_policy(value["graphiti"], _GRAPHITI_KEYS)
    if value["cognee"] != {
        "disposition": "not_projected",
        "policy_sha256": COGNEE_NOT_PROJECTED_POLICY_SHA256,
    }:
        raise MemoryValidationError("Benchmark cleanup target authority is invalid")
    if (
        value["qdrant"]["collection_projection_policy_sha256"]
        != QDRANT_COLLECTION_PROJECTION_POLICY_SHA256
        or value["qdrant"]["deterministic_scope_mapping_policy_sha256"]
        != QDRANT_SCOPE_MAPPING_POLICY_SHA256
        or value["qdrant"]["space_wide_scan_policy_sha256"] != QDRANT_SPACE_WIDE_SCAN_POLICY_SHA256
        or value["graphiti"]["group_mapping_policy_sha256"] != GRAPHITI_GROUP_MAPPING_POLICY_SHA256
        or value["graphiti"]["space_prefix_scan_policy_sha256"]
        != GRAPHITI_SPACE_PREFIX_SCAN_POLICY_SHA256
    ):
        raise MemoryConflictError("Benchmark cleanup target authority conflicted")
    canonical = json.loads(_canonical_bytes(value))
    return ManagedBenchmarkCleanupTargetAuthority(canonical, str(authority_sha256))


def require_cleanup_plan_target_authority(
    plan: ManagedBenchmarkCleanupPlan,
    authority: ManagedBenchmarkCleanupTargetAuthority,
) -> None:
    if (
        type(plan) is not ManagedBenchmarkCleanupPlan
        or type(authority) is not ManagedBenchmarkCleanupTargetAuthority
    ):
        raise MemoryValidationError("Benchmark cleanup target authority is invalid")
    expected = authority.value
    if (
        plan.value.get("infinity_target_identity_sha256")
        != expected["infinity_target_identity_sha256"]
        or plan.value.get("qdrant") != expected["qdrant"]
        or plan.value.get("graphiti") != expected["graphiti"]
        or plan.value.get("cognee") != expected["cognee"]
    ):
        raise MemoryConflictError("Benchmark cleanup target authority conflicted")


def validate_managed_benchmark_cleanup_plan(
    value: object,
    cleanup_plan_sha256: object,
    *,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    infinity_target_identity_sha256: str,
    space_slug: str,
) -> ManagedBenchmarkCleanupPlan:
    """Validate exact shape, caps, recomputed cardinality, digest, and binding."""

    for digest in (
        cleanup_plan_sha256,
        run_id_sha256,
        binding_commitment_sha256,
        infinity_target_identity_sha256,
    ):
        _require_digest(digest)
    try:
        encoded = _canonical_bytes(value)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError("Benchmark cleanup plan is not canonical JSON") from exc
    if len(encoded) > MAX_CLEANUP_PLAN_BYTES:
        raise MemoryValidationError("Benchmark cleanup plan exceeds size limit")
    if type(value) is not dict or set(value) != _TOP_LEVEL_KEYS:
        raise MemoryValidationError("Benchmark cleanup plan envelope is invalid")
    if value["schema_version"] != CLEANUP_PLAN_SCHEMA_VERSION:
        raise MemoryValidationError("Benchmark cleanup plan schema is invalid")
    canonical = json.loads(encoded)
    if canonical != value:
        raise MemoryValidationError("Benchmark cleanup plan is not canonical JSON")
    digest = managed_benchmark_cleanup_plan_material_sha256(value)
    if not hmac.compare_digest(str(cleanup_plan_sha256), digest):
        raise MemoryValidationError("Benchmark cleanup plan digest is invalid")

    expected_space_id = f"benchmark-space-{run_id_sha256[:48]}"
    expected_binding = (
        run_id_sha256,
        binding_commitment_sha256,
        infinity_target_identity_sha256,
        expected_space_id,
        space_slug,
    )
    actual_binding = tuple(
        value[key]
        for key in (
            "run_id_sha256",
            "binding_commitment_sha256",
            "infinity_target_identity_sha256",
            "space_id",
            "space_slug",
        )
    )
    if actual_binding != expected_binding:
        raise MemoryConflictError("Benchmark cleanup plan binding conflicted")
    if _SPACE_SLUG.fullmatch(space_slug) is None:
        raise MemoryValidationError("Benchmark cleanup plan space slug is invalid")
    if type(value["profile_id"]) is not str or _PROFILE_ID.fullmatch(value["profile_id"]) is None:
        raise MemoryValidationError("Benchmark cleanup plan profile is invalid")

    cases = _ordered_unique_digests(
        value["ordered_case_sha256"], limit=MAX_CLEANUP_PLAN_CASES, nonempty=True
    )
    corpora = value["corpora"]
    if type(corpora) is not list or not corpora or len(corpora) > MAX_CLEANUP_PLAN_CORPORA:
        raise MemoryValidationError("Benchmark cleanup plan corpora are invalid")
    corpus_ids: list[str] = []
    projection_ids: list[str] = []
    scope_external_ref_ids: list[str] = []
    thread_external_ref_ids: list[str] = []
    all_mem0_sources: list[str] = []
    all_units: list[str] = []
    all_infinity_operations: list[str] = []
    all_infinity_sources: list[str] = []
    expected_units = 0
    expected_facts = 0
    expected_documents = 0
    expected_chunks = 0
    for ordinal, corpus in enumerate(corpora):
        if type(corpus) is not dict or set(corpus) != _CORPUS_KEYS or corpus["ordinal"] != ordinal:
            raise MemoryValidationError("Benchmark cleanup plan corpus is invalid")
        for key in (
            "corpus_id_sha256",
            "managed_corpus_projection_sha256",
            "memory_scope_external_ref_sha256",
            "thread_external_ref_sha256",
            "mem0_corpus_identity_sha256",
        ):
            _require_digest(corpus[key])
        mem0_sources = _ordered_unique_digests(
            corpus["ordered_mem0_source_id_sha256"],
            limit=MAX_CLEANUP_PLAN_SOURCES,
            nonempty=True,
        )
        units = _ordered_unique_digests(
            corpus["ordered_mem0_unit_identity_sha256"],
            limit=MAX_CLEANUP_PLAN_UNITS,
            nonempty=True,
        )
        count = corpus["expected_ingest_unit_count"]
        if type(count) is not int or count < 1 or count != len(units) or count != len(mem0_sources):
            raise MemoryValidationError("Benchmark cleanup plan ingest count is invalid")
        lane = corpus["infinity_lane"]
        operations = _ordered_unique_digests(
            corpus["ordered_infinity_operation_sha256"],
            limit=MAX_CLEANUP_PLAN_UNITS,
            nonempty=True,
        )
        infinity_sources = _ordered_unique_digests(
            corpus["ordered_infinity_source_external_id_sha256"],
            limit=MAX_CLEANUP_PLAN_SOURCES,
            nonempty=True,
        )
        content = _ordered_digests(
            corpus["ordered_infinity_content_sha256"],
            limit=MAX_CLEANUP_PLAN_SOURCES,
            nonempty=True,
        )
        fragment_counts = corpus["ordered_document_fragment_count"]
        fact_count = corpus["expected_fact_count"]
        document_count = corpus["expected_document_count"]
        chunk_count = corpus["expected_chunk_count"]
        if (
            lane not in {"fact", "document"}
            or len(operations) != count
            or len(infinity_sources) != count
            or len(content) != count
            or type(fact_count) is not int
            or type(document_count) is not int
            or type(chunk_count) is not int
            or min(fact_count, document_count, chunk_count) < 0
        ):
            raise MemoryValidationError("Benchmark cleanup plan Infinity lane is invalid")
        if lane == "fact":
            lane_valid = (
                fragment_counts == []
                and fact_count == count
                and document_count == 0
                and chunk_count == 0
            )
        else:
            lane_valid = (
                type(fragment_counts) is list
                and len(fragment_counts) == count
                and all(type(item) is int and item >= 1 for item in fragment_counts)
                and len(content) == len(set(content))
                and fact_count == 0
                and document_count == count
                and chunk_count == sum(fragment_counts)
            )
        if not lane_valid:
            raise MemoryValidationError("Benchmark cleanup plan Infinity lane is invalid")
        corpus_ids.append(corpus["corpus_id_sha256"])
        projection_ids.append(corpus["managed_corpus_projection_sha256"])
        scope_external_ref_ids.append(corpus["memory_scope_external_ref_sha256"])
        thread_external_ref_ids.append(corpus["thread_external_ref_sha256"])
        all_mem0_sources.extend(mem0_sources)
        all_units.extend(units)
        all_infinity_operations.extend(operations)
        all_infinity_sources.extend(infinity_sources)
        expected_units += count
        expected_facts += fact_count
        expected_documents += document_count
        expected_chunks += chunk_count
    _require_globally_unique(corpus_ids, "corpus")
    _require_globally_unique(projection_ids, "corpus projection")
    _require_globally_unique(scope_external_ref_ids, "scope external ref")
    _require_globally_unique(thread_external_ref_ids, "thread external ref")
    _require_globally_unique(all_mem0_sources, "Mem0 source identity")
    _require_globally_unique(all_units, "Mem0 unit identity")
    _require_globally_unique(all_infinity_operations, "Infinity operation")
    _require_globally_unique(all_infinity_sources, "Infinity source identity")
    if (
        len(all_mem0_sources) > MAX_CLEANUP_PLAN_SOURCES
        or len(all_infinity_sources) > MAX_CLEANUP_PLAN_SOURCES
        or len(all_units) > MAX_CLEANUP_PLAN_UNITS
        or max(expected_facts, expected_documents, expected_chunks)
        > MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND
    ):
        raise MemoryValidationError("Benchmark cleanup plan cardinality exceeds limit")
    recovery_rows = (2 * len(corpora)) + (2 * expected_facts) + expected_documents + expected_chunks
    if recovery_rows > MAX_CLEANUP_PLAN_RECOVERY_TOTAL_ROWS:
        raise MemoryValidationError("Benchmark cleanup plan recovery expansion exceeds limit")

    _validate_mem0(value["mem0"])
    mem0_count = value["mem0"]["expected_operation_count"]
    if type(mem0_count) is not int or mem0_count < 1 or mem0_count != expected_units:
        raise MemoryValidationError("Benchmark cleanup plan Mem0 count is invalid")
    _digest_policy(value["qdrant"], _QDRANT_KEYS)
    _digest_policy(value["graphiti"], _GRAPHITI_KEYS)
    if value["cognee"] != {
        "disposition": "not_projected",
        "policy_sha256": COGNEE_NOT_PROJECTED_POLICY_SHA256,
    }:
        raise MemoryValidationError("Benchmark cleanup plan Cognee policy is invalid")
    cardinality = value["cardinality"]
    if type(cardinality) is not dict or set(cardinality) != _CARDINALITY_KEYS:
        raise MemoryValidationError("Benchmark cleanup plan cardinality is invalid")
    if any(type(item) is not int for item in cardinality.values()):
        raise MemoryValidationError("Benchmark cleanup plan cardinality is invalid")
    if cardinality != {
        "case_count": len(cases),
        "corpus_count": len(corpora),
        "mem0_source_identity_count": len(all_mem0_sources),
        "expected_ingest_unit_count": expected_units,
        "infinity_operation_count": len(all_infinity_operations),
        "expected_fact_count": expected_facts,
        "expected_document_count": expected_documents,
        "expected_chunk_count": expected_chunks,
    }:
        raise MemoryValidationError("Benchmark cleanup plan cardinality differs")
    if value["limits_policy_sha256"] != CLEANUP_PLAN_LIMITS_POLICY_SHA256:
        raise MemoryValidationError("Benchmark cleanup plan limits policy is invalid")
    if value["infinity_namespace_policy_sha256"] != INFINITY_NAMESPACE_POLICY_SHA256:
        raise MemoryValidationError("Benchmark cleanup plan namespace policy is invalid")
    return ManagedBenchmarkCleanupPlan(value=canonical, sha256=digest)


def _require_digest(value: object) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise MemoryValidationError("Benchmark cleanup plan digest is invalid")


def _ordered_unique_digests(value: object, *, limit: int, nonempty: bool = False) -> list[str]:
    if type(value) is not list or len(value) > limit or (nonempty and not value):
        raise MemoryValidationError("Benchmark cleanup plan digest list is invalid")
    for item in value:
        _require_digest(item)
    if len(set(value)) != len(value):
        raise MemoryValidationError("Benchmark cleanup plan digest list is not unique")
    return value


def _ordered_digests(value: object, *, limit: int, nonempty: bool = False) -> list[str]:
    if type(value) is not list or len(value) > limit or (nonempty and not value):
        raise MemoryValidationError("Benchmark cleanup plan digest list is invalid")
    for item in value:
        _require_digest(item)
    return value


def _validate_mem0(value: object) -> None:
    if type(value) is not dict or set(value) != _MEM0_KEYS:
        raise MemoryValidationError("Benchmark cleanup plan Mem0 policy is invalid")
    for key in (
        "admission_commitment_sha256",
        "ingestion_manifest_sha256",
        "ingestion_root_sha256",
    ):
        _require_digest(value[key])
    count = value["expected_operation_count"]
    if type(count) is not int or count < 1:
        raise MemoryValidationError("Benchmark cleanup plan Mem0 count is invalid")


def _digest_policy(value: object, expected_keys: set[str]) -> None:
    if type(value) is not dict or set(value) != expected_keys:
        raise MemoryValidationError("Benchmark cleanup plan policy is invalid")
    for item in value.values():
        _require_digest(item)


def _require_globally_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise MemoryValidationError(f"Benchmark cleanup plan {label} is not globally unique")


__all__ = (
    "CLEANUP_PLAN_LIMITS_POLICY_SHA256",
    "CLEANUP_PLAN_SCHEMA_VERSION",
    "COGNEE_NOT_PROJECTED_POLICY_SHA256",
    "CanonicalCleanupPlanSeal",
    "INFINITY_NAMESPACE_POLICY_SHA256",
    "ManagedBenchmarkCleanupPlan",
    "ManagedBenchmarkCleanupTargetAuthority",
    "MAX_CLEANUP_PLAN_CASES",
    "MAX_CLEANUP_PLAN_CORPORA",
    "MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND",
    "MAX_CLEANUP_PLAN_RECOVERY_TOTAL_ROWS",
    "MAX_CLEANUP_PLAN_SOURCES",
    "MAX_CLEANUP_PLAN_UNITS",
    "build_managed_benchmark_cleanup_target_authority",
    "managed_benchmark_cleanup_plan_material_sha256",
    "require_cleanup_plan_target_authority",
    "validate_managed_benchmark_cleanup_target_authority",
    "validate_managed_benchmark_cleanup_plan",
)

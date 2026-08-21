"""Pure projector for the canonical managed-v5 cleanup plan."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import final

from infinity_context_core.ports.benchmark_cleanup_plan import (
    CLEANUP_PLAN_LIMITS_POLICY_SHA256,
    CLEANUP_PLAN_SCHEMA_VERSION,
    INFINITY_NAMESPACE_POLICY_SHA256,
    ManagedBenchmarkCleanupPlan,
    ManagedBenchmarkCleanupTargetAuthority,
    managed_benchmark_cleanup_plan_material_sha256,
    require_cleanup_plan_target_authority,
    validate_managed_benchmark_cleanup_plan,
    validate_managed_benchmark_cleanup_target_authority,
)

from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    ManagedPublicRunProjection,
)
from infinity_context_server.memory_comparison_managed_v5_infinity_cleanup_projection import (
    project_managed_v5_infinity_cleanup,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
)


class ManagedV5CleanupPlanBuilderError(RuntimeError):
    """Stable pure-projection error."""


@final
@dataclass(frozen=True, slots=True)
class ManagedV5CleanupPlanInputs:
    projection: ManagedPublicRunProjection
    manifest_authority: ManagedMem0V5ManifestAuthority
    admission: Mem0OssFullRunAdmission
    profile_id: str
    run_id: str

    def __post_init__(self) -> None:
        if (
            type(self.projection) is not ManagedPublicRunProjection
            or type(self.manifest_authority) is not ManagedMem0V5ManifestAuthority
            or type(self.admission) is not Mem0OssFullRunAdmission
            or type(self.profile_id) is not str
            or not self.profile_id
            or type(self.run_id) is not str
            or not self.run_id
        ):
            _fail("managed_v5_cleanup_plan_inputs_invalid")


def build_managed_v5_cleanup_plan(
    *,
    inputs: ManagedV5CleanupPlanInputs,
    target_authority: ManagedBenchmarkCleanupTargetAuthority,
) -> ManagedBenchmarkCleanupPlan:
    """Derive and independently validate one exact provider-free plan."""

    if (
        type(inputs) is not ManagedV5CleanupPlanInputs
        or type(target_authority) is not ManagedBenchmarkCleanupTargetAuthority
    ):
        _fail("managed_v5_cleanup_plan_inputs_invalid")
    projection = inputs.projection
    infinity_cleanup = project_managed_v5_infinity_cleanup(projection)
    manifest = inputs.manifest_authority
    admission = inputs.admission
    bindings = projection.bindings
    infinity_target = _infinity_target(bindings.backend_targets)
    if target_authority.value.get("authority_sha256") != target_authority.authority_sha256:
        _fail("managed_v5_cleanup_plan_target_mismatch")
    try:
        target_authority = validate_managed_benchmark_cleanup_target_authority(
            target_authority.value,
            infinity_target_identity_sha256=infinity_target,
        )
    except Exception:
        _fail("managed_v5_cleanup_plan_target_mismatch")
    target = target_authority.value
    if (
        admission.ingestion_manifest_sha256 != manifest.ingestion_manifest_sha256
        or admission.ingestion_root_sha256 != manifest.ingestion_root_sha256
        or admission.ingestion_unit_count != manifest.operation_count
        or admission.request.expected_operation_count != manifest.operation_count
    ):
        _fail("managed_v5_cleanup_plan_manifest_mismatch")

    records: dict[str, dict[str, object]] = {}
    projection_order: list[str] = []
    ordered_cases: list[str] = []
    for case in projection.cases:
        record = _thaw(case.record)
        digest = managed_benchmark_cleanup_plan_material_sha256(record)
        existing = records.get(case.corpus_id)
        if existing is None:
            records[case.corpus_id] = record
            projection_order.append(case.corpus_id)
        elif existing != record:
            _fail("managed_v5_cleanup_plan_record_conflict")
        ordered_cases.append(
            managed_benchmark_cleanup_plan_material_sha256(
                {
                    "case_id": case.case_id,
                    "corpus_id": case.corpus_id,
                    "managed_corpus_projection_sha256": digest,
                }
            )
        )

    units_by_corpus: dict[str, list[object]] = {}
    manifest_order: list[str] = []
    source_ids: set[str] = set()
    unit_ids: set[str] = set()
    for unit in manifest.units:
        if unit.corpus_id not in units_by_corpus:
            units_by_corpus[unit.corpus_id] = []
            manifest_order.append(unit.corpus_id)
        if unit.source_id in source_ids or unit.unit_identity_sha256 in unit_ids:
            _fail("managed_v5_cleanup_plan_identity_duplicate")
        source_ids.add(unit.source_id)
        unit_ids.add(unit.unit_identity_sha256)
        units_by_corpus[unit.corpus_id].append(unit)
    if manifest_order != projection_order or set(units_by_corpus) != set(records):
        _fail("managed_v5_cleanup_plan_corpus_order_mismatch")
    infinity_by_corpus = {item.corpus_id: item for item in infinity_cleanup.corpora}
    if tuple(infinity_by_corpus) != tuple(manifest_order):
        _fail("managed_v5_cleanup_plan_corpus_order_mismatch")

    corpora: list[dict[str, object]] = []
    for ordinal, corpus_id in enumerate(manifest_order):
        units = units_by_corpus[corpus_id]
        infinity_corpus = infinity_by_corpus[corpus_id]
        if not units:
            _fail("managed_v5_cleanup_plan_corpus_empty")
        infinity_sources = infinity_corpus.sources
        lanes = {item.lane for item in infinity_sources}
        if len(lanes) != 1 or len(infinity_sources) != len(units):
            _fail("managed_v5_cleanup_plan_infinity_projection_mismatch")
        lane = next(iter(lanes))
        corpora.append(
            {
                "ordinal": ordinal,
                "corpus_id_sha256": managed_benchmark_cleanup_plan_material_sha256(
                    {"corpus_id": corpus_id}
                ),
                "managed_corpus_projection_sha256": (
                    managed_benchmark_cleanup_plan_material_sha256(records[corpus_id])
                ),
                "memory_scope_external_ref_sha256": _text_sha(corpus_id),
                "thread_external_ref_sha256": infinity_corpus.thread_external_ref_sha256,
                "infinity_lane": lane,
                "ordered_infinity_operation_sha256": [
                    item.operation_commitment_sha256 for item in infinity_sources
                ],
                "ordered_infinity_source_external_id_sha256": [
                    item.source_id_sha256 for item in infinity_sources
                ],
                "ordered_infinity_content_sha256": [
                    item.source_content_sha256 for item in infinity_sources
                ],
                "ordered_document_fragment_count": (
                    [item.expected_chunk_count for item in infinity_sources]
                    if lane == "document"
                    else []
                ),
                "expected_fact_count": infinity_corpus.expected_fact_count,
                "expected_document_count": infinity_corpus.expected_document_count,
                "expected_chunk_count": infinity_corpus.expected_chunk_count,
                "mem0_corpus_identity_sha256": (
                    managed_benchmark_cleanup_plan_material_sha256({"corpus_id": corpus_id})
                ),
                "ordered_mem0_source_id_sha256": [_text_sha(unit.source_id) for unit in units],
                "ordered_mem0_unit_identity_sha256": [unit.unit_identity_sha256 for unit in units],
                "expected_ingest_unit_count": len(units),
            }
        )
    run_sha = _text_sha(bindings.run_id)
    plan = {
        "schema_version": CLEANUP_PLAN_SCHEMA_VERSION,
        "run_id_sha256": run_sha,
        "binding_commitment_sha256": bindings.binding_commitment_sha256,
        "infinity_target_identity_sha256": infinity_target,
        "space_id": f"benchmark-space-{run_sha[:48]}",
        "space_slug": _space_slug(inputs.run_id),
        "profile_id": inputs.profile_id,
        "ordered_case_sha256": ordered_cases,
        "corpora": corpora,
        "mem0": {
            "admission_commitment_sha256": admission.commitment_sha256,
            "ingestion_manifest_sha256": manifest.ingestion_manifest_sha256,
            "ingestion_root_sha256": manifest.ingestion_root_sha256,
            "expected_operation_count": manifest.operation_count,
        },
        "infinity_namespace_policy_sha256": INFINITY_NAMESPACE_POLICY_SHA256,
        "qdrant": _copy_json(target["qdrant"]),
        "graphiti": _copy_json(target["graphiti"]),
        "cognee": _copy_json(target["cognee"]),
        "cardinality": {
            "case_count": len(ordered_cases),
            "corpus_count": len(corpora),
            "mem0_source_identity_count": len(source_ids),
            "expected_ingest_unit_count": manifest.operation_count,
            "infinity_operation_count": infinity_cleanup.expected_source_count,
            "expected_fact_count": infinity_cleanup.expected_fact_count,
            "expected_document_count": infinity_cleanup.expected_document_count,
            "expected_chunk_count": infinity_cleanup.expected_chunk_count,
        },
        "limits_policy_sha256": CLEANUP_PLAN_LIMITS_POLICY_SHA256,
    }
    digest = managed_benchmark_cleanup_plan_material_sha256(plan)
    try:
        validated = validate_managed_benchmark_cleanup_plan(
            plan,
            digest,
            run_id_sha256=run_sha,
            binding_commitment_sha256=bindings.binding_commitment_sha256,
            infinity_target_identity_sha256=infinity_target,
            space_slug=_space_slug(inputs.run_id),
        )
        require_cleanup_plan_target_authority(validated, target_authority)
        return validated
    except Exception:
        _fail("managed_v5_cleanup_plan_validation_failed")


def _infinity_target(targets: tuple[object, ...]) -> str:
    matches = [
        item.target_identity_sha256
        for item in targets
        if getattr(item, "backend_role", None) == "infinity-context"
    ]
    if len(matches) != 1 or not _sha(matches[0]):
        _fail("managed_v5_cleanup_plan_target_invalid")
    return matches[0]


def _space_slug(run_id: str) -> str:
    from infinity_context_server.memory_comparison_managed_http_lifecycle import (
        managed_http_lifecycle_space_slug,
    )

    return managed_http_lifecycle_space_slug(run_id)


def _thaw(value: object) -> dict[str, object]:
    thawed = _copy_json(value)
    if type(thawed) is not dict:
        _fail("managed_v5_cleanup_plan_record_invalid")
    return thawed


def _copy_json(value: object) -> object:
    if isinstance(value, (dict, MappingProxyType, Mapping)):
        if any(type(key) is not str for key in value):
            _fail("managed_v5_cleanup_plan_json_invalid")
        return {key: _copy_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_copy_json(item) for item in value]
    if value is None or type(value) in {str, int, bool, float}:
        return value
    _fail("managed_v5_cleanup_plan_json_invalid")


def _text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= set("0123456789abcdef")


def _fail(code: str) -> None:
    raise ManagedV5CleanupPlanBuilderError(code)


__all__ = (
    "ManagedV5CleanupPlanBuilderError",
    "ManagedV5CleanupPlanInputs",
    "build_managed_v5_cleanup_plan",
)

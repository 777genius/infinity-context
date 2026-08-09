import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from infinity_context_core.application.dto_benchmark_runs import RegisterBenchmarkRunCommand
from infinity_context_core.application.use_cases.benchmark_cleanup_plan import (
    RegisterBenchmarkRunUseCase,
)
from infinity_context_core.domain.errors import MemoryConflictError, MemoryValidationError
from infinity_context_core.ports.benchmark_cleanup_plan import (
    CLEANUP_PLAN_LIMITS_POLICY_SHA256,
    CLEANUP_PLAN_SCHEMA_VERSION,
    COGNEE_NOT_PROJECTED_POLICY_SHA256,
    GRAPHITI_GROUP_MAPPING_POLICY_SHA256,
    GRAPHITI_SPACE_PREFIX_SCAN_POLICY_SHA256,
    INFINITY_NAMESPACE_POLICY_SHA256,
    MAX_CLEANUP_PLAN_CASES,
    MAX_CLEANUP_PLAN_CORPORA,
    MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND,
    QDRANT_COLLECTION_PROJECTION_POLICY_SHA256,
    QDRANT_SCOPE_MAPPING_POLICY_SHA256,
    QDRANT_SPACE_WIDE_SCAN_POLICY_SHA256,
    validate_managed_benchmark_cleanup_plan,
)

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SLUG = "memory-comparison-cleanup-plan"


def test_projection_policy_commitment_oracles_are_pinned() -> None:
    assert QDRANT_COLLECTION_PROJECTION_POLICY_SHA256 == (
        "1012ec7a8aceb42d13897a6773cc128c473063f2001d46647ee6ba82e344d2a4"
    )
    assert QDRANT_SCOPE_MAPPING_POLICY_SHA256 == (
        "f3ed09953ebb94e108a39d6e67116a506498b07b5542415e86d0442574244aa4"
    )
    assert QDRANT_SPACE_WIDE_SCAN_POLICY_SHA256 == (
        "c0981efcf9cf2b07c676f3c033306fcc40b5d0e14cfa14413619f944b77b2238"
    )
    assert GRAPHITI_GROUP_MAPPING_POLICY_SHA256 == (
        "36a26acd3a3c382262b3c3b066d767564a9307a81463dd8fc3f6f93e3c7c392c"
    )
    assert GRAPHITI_SPACE_PREFIX_SCAN_POLICY_SHA256 == (
        "934e2e26c4b1ee10d0f01db525298bfe99c800b5f39e5b70e7943fff1f0adefb"
    )


def _digest(character: str) -> str:
    return character * 64


def _plan() -> dict[str, object]:
    return {
        "schema_version": CLEANUP_PLAN_SCHEMA_VERSION,
        "run_id_sha256": RUN,
        "binding_commitment_sha256": BINDING,
        "infinity_target_identity_sha256": TARGET,
        "space_id": f"benchmark-space-{RUN[:48]}",
        "space_slug": SLUG,
        "profile_id": "locomo-top-50",
        "ordered_case_sha256": [_digest("1"), _digest("2")],
        "corpora": [
            {
                "ordinal": 0,
                "corpus_id_sha256": _digest("3"),
                "managed_corpus_projection_sha256": _digest("4"),
                "memory_scope_external_ref_sha256": _digest("5"),
                "thread_external_ref_sha256": _digest("6"),
                "infinity_lane": "fact",
                "ordered_infinity_operation_sha256": [_digest("a")],
                "ordered_infinity_source_external_id_sha256": [_digest("b")],
                "ordered_infinity_content_sha256": [_digest("c")],
                "ordered_document_fragment_count": [],
                "expected_fact_count": 1,
                "expected_document_count": 0,
                "expected_chunk_count": 0,
                "mem0_corpus_identity_sha256": _digest("7"),
                "ordered_mem0_source_id_sha256": [_digest("6")],
                "ordered_mem0_unit_identity_sha256": [_digest("8")],
                "expected_ingest_unit_count": 1,
            }
        ],
        "mem0": {
            "admission_commitment_sha256": _digest("9"),
            "ingestion_manifest_sha256": _digest("d"),
            "ingestion_root_sha256": _digest("e"),
            "expected_operation_count": 1,
        },
        "infinity_namespace_policy_sha256": INFINITY_NAMESPACE_POLICY_SHA256,
        "qdrant": {
            "target_commitment_sha256": _digest("f"),
            "collection_projection_policy_sha256": _digest("0"),
            "deterministic_scope_mapping_policy_sha256": _digest("1"),
            "space_wide_scan_policy_sha256": _digest("2"),
        },
        "graphiti": {
            "target_commitment_sha256": _digest("3"),
            "group_mapping_policy_sha256": _digest("4"),
            "space_prefix_scan_policy_sha256": _digest("5"),
        },
        "cognee": {
            "disposition": "not_projected",
            "policy_sha256": COGNEE_NOT_PROJECTED_POLICY_SHA256,
        },
        "cardinality": {
            "case_count": 2,
            "corpus_count": 1,
            "mem0_source_identity_count": 1,
            "expected_ingest_unit_count": 1,
            "infinity_operation_count": 1,
            "expected_fact_count": 1,
            "expected_document_count": 0,
            "expected_chunk_count": 0,
        },
        "limits_policy_sha256": CLEANUP_PLAN_LIMITS_POLICY_SHA256,
    }


def _sha(plan: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _indexed_digest(namespace: str, index: int) -> str:
    return hashlib.sha256(f"{namespace}:{index}".encode()).hexdigest()


def _max_recoverable_plan() -> dict[str, object]:
    plan = _plan()
    plan["ordered_case_sha256"] = [
        _indexed_digest("case", index) for index in range(MAX_CLEANUP_PLAN_CASES)
    ]
    plan["corpora"] = [
        {
            "ordinal": index,
            "corpus_id_sha256": _indexed_digest("corpus", index),
            "managed_corpus_projection_sha256": _indexed_digest("projection", index),
            "memory_scope_external_ref_sha256": _indexed_digest("scope", index),
            "thread_external_ref_sha256": _indexed_digest("thread", index),
            "infinity_lane": "document",
            "ordered_infinity_operation_sha256": [_indexed_digest("operation", index)],
            "ordered_infinity_source_external_id_sha256": [
                _indexed_digest("infinity-source", index)
            ],
            "ordered_infinity_content_sha256": [_indexed_digest("content", index)],
            "ordered_document_fragment_count": [1],
            "expected_fact_count": 0,
            "expected_document_count": 1,
            "expected_chunk_count": 1,
            "mem0_corpus_identity_sha256": _indexed_digest("mem0-corpus", index),
            "ordered_mem0_source_id_sha256": [_indexed_digest("source", index)],
            "ordered_mem0_unit_identity_sha256": [_indexed_digest("unit", index)],
            "expected_ingest_unit_count": 1,
        }
        for index in range(MAX_CLEANUP_PLAN_CORPORA)
    ]
    plan["mem0"]["expected_operation_count"] = MAX_CLEANUP_PLAN_CORPORA
    plan["cardinality"] = {
        "case_count": MAX_CLEANUP_PLAN_CASES,
        "corpus_count": MAX_CLEANUP_PLAN_CORPORA,
        "mem0_source_identity_count": MAX_CLEANUP_PLAN_CORPORA,
        "expected_ingest_unit_count": MAX_CLEANUP_PLAN_CORPORA,
        "infinity_operation_count": MAX_CLEANUP_PLAN_CORPORA,
        "expected_fact_count": 0,
        "expected_document_count": MAX_CLEANUP_PLAN_CORPORA,
        "expected_chunk_count": MAX_CLEANUP_PLAN_CORPORA,
    }
    return plan


def _validate(plan: dict[str, object]):
    return validate_managed_benchmark_cleanup_plan(
        plan,
        _sha(plan),
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_slug=SLUG,
    )


def test_exact_plan_is_copied_and_sealed_by_canonical_digest() -> None:
    plan = _plan()
    validated = _validate(plan)
    plan["profile_id"] = "mutated-after-validation"

    assert validated.value["profile_id"] == "locomo-top-50"
    assert validated.sha256 == _sha(validated.value)


def test_max_recovery_expansion_is_admitted_and_plus_one_fails_before_add() -> None:
    plan = _max_recoverable_plan()
    assert _validate(plan).value["cardinality"]["corpus_count"] == 5_000

    extra = {
        **plan["corpora"][-1],
        "ordinal": MAX_CLEANUP_PLAN_CORPORA,
        "corpus_id_sha256": _indexed_digest("corpus", MAX_CLEANUP_PLAN_CORPORA),
        "managed_corpus_projection_sha256": _indexed_digest("projection", MAX_CLEANUP_PLAN_CORPORA),
        "memory_scope_external_ref_sha256": _indexed_digest("scope", MAX_CLEANUP_PLAN_CORPORA),
        "thread_external_ref_sha256": _indexed_digest("thread", MAX_CLEANUP_PLAN_CORPORA),
        "ordered_infinity_operation_sha256": [
            _indexed_digest("operation", MAX_CLEANUP_PLAN_CORPORA)
        ],
        "ordered_infinity_source_external_id_sha256": [
            _indexed_digest("infinity-source", MAX_CLEANUP_PLAN_CORPORA)
        ],
        "ordered_infinity_content_sha256": [_indexed_digest("content", MAX_CLEANUP_PLAN_CORPORA)],
        "ordered_mem0_source_id_sha256": [_indexed_digest("source", MAX_CLEANUP_PLAN_CORPORA)],
        "mem0_corpus_identity_sha256": _indexed_digest("mem0-corpus", MAX_CLEANUP_PLAN_CORPORA),
        "ordered_mem0_unit_identity_sha256": [_indexed_digest("unit", MAX_CLEANUP_PLAN_CORPORA)],
    }
    plan["corpora"].append(extra)
    plan["mem0"]["expected_operation_count"] += 1
    plan["cardinality"]["corpus_count"] += 1
    plan["cardinality"]["mem0_source_identity_count"] += 1
    plan["cardinality"]["expected_ingest_unit_count"] += 1
    plan["cardinality"]["infinity_operation_count"] += 1
    plan["cardinality"]["expected_document_count"] += 1
    plan["cardinality"]["expected_chunk_count"] += 1
    repository = _Repository()
    use_case = RegisterBenchmarkRunUseCase(
        uow_factory=lambda: _Uow(repository),
        clock=type("Clock", (), {"now": lambda _self: datetime(2026, 1, 1, tzinfo=UTC)})(),
    )
    with pytest.raises(MemoryValidationError, match="corpora"):
        asyncio.run(use_case.execute(_command(plan)))
    assert repository.record is None


def test_exact_document_fragment_cap_is_admitted_and_plus_one_rejected() -> None:
    plan = _plan()
    corpus = plan["corpora"][0]
    corpus.update(
        {
            "infinity_lane": "document",
            "ordered_document_fragment_count": [MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND],
            "expected_fact_count": 0,
            "expected_document_count": 1,
            "expected_chunk_count": MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND,
        }
    )
    plan["cardinality"].update(
        {
            "expected_fact_count": 0,
            "expected_document_count": 1,
            "expected_chunk_count": MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND,
        }
    )
    assert _validate(plan).value["cardinality"]["expected_chunk_count"] == 5_000

    corpus["ordered_document_fragment_count"] = [MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND + 1]
    corpus["expected_chunk_count"] += 1
    plan["cardinality"]["expected_chunk_count"] += 1
    with pytest.raises(MemoryValidationError, match="cardinality exceeds limit"):
        _validate(plan)


def test_document_lane_rejects_distinct_sources_with_duplicate_content() -> None:
    plan = _plan()
    corpus = plan["corpora"][0]
    corpus.update(
        {
            "infinity_lane": "document",
            "ordered_infinity_operation_sha256": [_digest("a"), _digest("b")],
            "ordered_infinity_source_external_id_sha256": [_digest("c"), _digest("d")],
            "ordered_infinity_content_sha256": [_digest("e"), _digest("e")],
            "ordered_document_fragment_count": [1, 1],
            "expected_fact_count": 0,
            "expected_document_count": 2,
            "expected_chunk_count": 2,
            "ordered_mem0_source_id_sha256": [_digest("1"), _digest("2")],
            "ordered_mem0_unit_identity_sha256": [_digest("3"), _digest("4")],
            "expected_ingest_unit_count": 2,
        }
    )
    plan["mem0"]["expected_operation_count"] = 2
    plan["cardinality"].update(
        {
            "mem0_source_identity_count": 2,
            "expected_ingest_unit_count": 2,
            "infinity_operation_count": 2,
            "expected_fact_count": 0,
            "expected_document_count": 2,
            "expected_chunk_count": 2,
        }
    )

    with pytest.raises(MemoryValidationError, match="Infinity lane"):
        _validate(plan)


def test_binding_and_unknown_fields_fail_closed() -> None:
    changed = _plan()
    changed["space_id"] = f"benchmark-space-{'f' * 48}"
    with pytest.raises(MemoryConflictError, match="binding conflicted"):
        _validate(changed)

    unknown = _plan()
    unknown["caller_cap"] = 99
    with pytest.raises(MemoryValidationError, match="envelope"):
        _validate(unknown)


def test_duplicate_scope_external_ref_authority_is_rejected() -> None:
    plan = _plan()
    duplicate = deepcopy(plan["corpora"][0])
    duplicate.update(
        {
            "ordinal": 1,
            "corpus_id_sha256": _indexed_digest("corpus", 1),
            "managed_corpus_projection_sha256": _indexed_digest("projection", 1),
            "thread_external_ref_sha256": _indexed_digest("thread", 1),
            "ordered_infinity_operation_sha256": [_indexed_digest("operation", 1)],
            "ordered_infinity_source_external_id_sha256": [_indexed_digest("infinity-source", 1)],
            "ordered_infinity_content_sha256": [_indexed_digest("content", 1)],
            "ordered_mem0_source_id_sha256": [_indexed_digest("source", 1)],
            "mem0_corpus_identity_sha256": _indexed_digest("mem0-corpus", 1),
            "ordered_mem0_unit_identity_sha256": [_indexed_digest("unit", 1)],
        }
    )
    plan["corpora"].append(duplicate)
    plan["mem0"]["expected_operation_count"] = 2
    plan["cardinality"].update(
        {
            "corpus_count": 2,
            "mem0_source_identity_count": 2,
            "expected_ingest_unit_count": 2,
            "infinity_operation_count": 2,
            "expected_fact_count": 2,
        }
    )
    with pytest.raises(MemoryValidationError, match="scope external ref"):
        _validate(plan)


@pytest.mark.parametrize("bad", [0, True])
def test_mem0_count_must_be_positive_exact_int(bad: object) -> None:
    plan = _plan()
    plan["mem0"]["expected_operation_count"] = bad
    with pytest.raises(MemoryValidationError, match="Mem0 count"):
        _validate(plan)


@pytest.mark.parametrize("lane", ["qdrant", "graphiti"])
@pytest.mark.parametrize("bad", [1, True])
def test_every_projection_policy_field_is_a_digest(lane: str, bad: object) -> None:
    plan = _plan()
    first = next(iter(plan[lane]))
    plan[lane][first] = bad
    with pytest.raises(MemoryValidationError, match="digest"):
        _validate(plan)


@pytest.mark.parametrize("field", ["case_count", "expected_ingest_unit_count"])
def test_cardinality_rejects_bool(field: str) -> None:
    plan = _plan()
    plan["cardinality"][field] = True
    with pytest.raises(MemoryValidationError, match="cardinality"):
        _validate(plan)


@pytest.mark.parametrize(
    "field", ["ordered_mem0_source_id_sha256", "ordered_mem0_unit_identity_sha256"]
)
def test_every_corpus_has_a_nonempty_cleanup_namespace(field: str) -> None:
    plan = _plan()
    plan["corpora"][0][field] = []
    with pytest.raises(MemoryValidationError, match="digest list"):
        _validate(plan)


class _Repository:
    def __init__(self) -> None:
        self.record = None

    async def get_by_run_id_sha256(self, _value: str, *, for_update: bool = False):
        return self.record

    async def get_by_idempotency_key_sha256(self, _value: str):
        return self.record

    async def add(self, record) -> None:
        self.record = record


class _Uow:
    def __init__(self, repository: _Repository) -> None:
        self.benchmark_runs = repository
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def commit(self) -> None:
        self.commits += 1


def _command(plan: dict[str, object]) -> RegisterBenchmarkRunCommand:
    return RegisterBenchmarkRunCommand(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_slug=SLUG,
        idempotency_key_sha256="f" * 64,
        cleanup_plan_json=plan,
        cleanup_plan_sha256=_sha(plan),
    )


def test_registration_atomically_seals_exact_plan_and_rejects_divergent_replay() -> None:
    repository = _Repository()
    uow = _Uow(repository)
    use_case = RegisterBenchmarkRunUseCase(
        uow_factory=lambda: uow,
        clock=type("Clock", (), {"now": lambda _self: datetime(2026, 1, 1, tzinfo=UTC)})(),
    )
    first = asyncio.run(use_case.execute(_command(_plan())))
    replay = asyncio.run(use_case.execute(_command(_plan())))

    assert first.created is True and replay.created is False
    assert first.record.cleanup_plan_state == "sealed"
    assert first.cleanup_plan_seal == replay.cleanup_plan_seal
    changed = _plan()
    changed["profile_id"] = "locomo-top-200"
    with pytest.raises(MemoryConflictError, match="fingerprint conflicted"):
        asyncio.run(use_case.execute(_command(changed)))

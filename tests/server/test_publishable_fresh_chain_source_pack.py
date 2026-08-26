from __future__ import annotations

import json
from dataclasses import replace

import pytest
from infinity_context_server.public_benchmark_models import (
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)
from infinity_context_server.publishable_fresh_chain_canary.contracts import (
    FreshChainCanaryError,
)
from infinity_context_server.publishable_fresh_chain_canary.source_pack import (
    FRESH_CHAIN_WHOLE_CORPUS_PACK_POLICY_SHA256,
    FRESH_CHAIN_WHOLE_CORPUS_PACK_SCHEMA,
    FRESH_CHAIN_WHOLE_CORPUS_SPEAKER,
    FreshChainWholeCorpusProjection,
    project_fresh_chain_whole_corpus,
)


def _memory(
    ordinal: int,
    *,
    speaker: str,
    role: str,
    text: str,
    session_date: str,
    timestamp: int,
) -> BenchmarkMemoryInput:
    session = f"session_{ordinal}"
    dia_id = f"D{ordinal}:1"
    return BenchmarkMemoryInput(
        text=f"{session} date: {session_date}\n{dia_id} {speaker}: {text}",
        source_external_id=f"locomo:conv-26:{session}:{dia_id}:turn",
        metadata={
            "dia_id": dia_id,
            "official_mem0_content": f"{speaker}: {text}",
            "role": role,
            "session_date": session_date,
            "session_key": session,
            "speaker": speaker,
            "timestamp": timestamp,
        },
    )


def _case(*, first_text: str = "I planted basil today.") -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id="conv-26:qa:1",
        question="What herb was planted?",
        expected_terms=("basil",),
        forbidden_terms=("mint",),
        memories=(
            _memory(
                1,
                speaker="Caroline",
                role="user",
                text=first_text,
                session_date="1:00 PM on 1 May, 2023",
                timestamp=1_682_946_000,
            ),
            _memory(
                2,
                speaker="Melanie",
                role="assistant",
                text="That will smell wonderful.",
                session_date="2:00 PM on 2 May, 2023",
                timestamp=1_683_036_000,
            ),
        ),
        memory_scope_external_ref="locomo-conv-26",
        thread_external_ref="locomo-conv-26",
        metadata={
            "_evaluator_ground_truth": "basil",
            "answer_terms": ("basil",),
            "evidence": ("D1:1",),
            "locomo_ingest_mode": "official-turns",
            "sample_id": "conv-26",
        },
    )


def _packed_payload(
    case: PublicBenchmarkCase,
) -> tuple[FreshChainWholeCorpusProjection, dict[str, object]]:
    projection = project_fresh_chain_whole_corpus(case, current_date="2026-08-12")
    content = projection.extraction_unit.source_messages[0].content
    prefix = f"{FRESH_CHAIN_WHOLE_CORPUS_SPEAKER}: "
    assert content.startswith(prefix)
    return projection, json.loads(content.removeprefix(prefix))


def test_whole_corpus_projection_is_exactly_one_ordered_extraction_unit() -> None:
    projection, packed = _packed_payload(_case())

    assert projection.full_source_manifest.operation_count == 2
    assert projection.packed_manifest.operation_count == 1
    assert projection.packed_manifest.units == (projection.extraction_unit,)
    assert projection.extraction_unit.source_messages[0].role == "user"
    assert packed["schema_version"] == FRESH_CHAIN_WHOLE_CORPUS_PACK_SCHEMA
    assert packed["packing_policy_sha256"] == FRESH_CHAIN_WHOLE_CORPUS_PACK_POLICY_SHA256
    assert [unit["messages"] for unit in packed["units"]] == [
        [{"content": "Caroline: I planted basil today.", "role": "user"}],
        [{"content": "Melanie: That will smell wonderful.", "role": "assistant"}],
    ]
    assert [unit["observation_date"] for unit in packed["units"]] == [
        "2023-05-01",
        "2023-05-02",
    ]


def test_projection_commits_full_manifest_policy_pack_and_request() -> None:
    projection, _ = _packed_payload(_case())
    material = projection.commitment_material()
    public = projection.public_payload()

    assert projection.source_commitment_sha256 == projection.projection_commitment_sha256
    assert material["packing_policy_sha256"] == FRESH_CHAIN_WHOLE_CORPUS_PACK_POLICY_SHA256
    assert material["full_source_manifest"] == projection.full_source_manifest.public_payload()
    assert material["packed_manifest"] == projection.packed_manifest.public_payload()
    assert material["packed_content_sha256"] == projection.packed_content_sha256
    assert material["extraction_request_body_sha256"] == projection.extraction_request_body_sha256
    assert public["projection_commitment_sha256"] == projection.projection_commitment_sha256


def test_projection_is_deterministic_and_gold_blind() -> None:
    original = _case()
    different_gold = replace(
        original,
        question="A deliberately unrelated evaluation question?",
        expected_terms=("secret-answer",),
        forbidden_terms=("basil",),
        metadata={
            **original.metadata,
            "_evaluator_ground_truth": "secret-answer",
            "answer_terms": ("secret-answer",),
            "evidence": ("never include this",),
        },
    )

    first = project_fresh_chain_whole_corpus(original, current_date="2026-08-12")
    replay = project_fresh_chain_whole_corpus(original, current_date="2026-08-12")
    gold_changed = project_fresh_chain_whole_corpus(
        different_gold,
        current_date="2026-08-12",
    )

    assert replay == first
    assert gold_changed == first


def test_source_mutation_changes_every_downstream_source_authority() -> None:
    original = project_fresh_chain_whole_corpus(_case(), current_date="2026-08-12")
    changed = project_fresh_chain_whole_corpus(
        _case(first_text="I planted rosemary today."),
        current_date="2026-08-12",
    )

    assert (
        changed.full_source_manifest.authority_commitment_sha256
        != original.full_source_manifest.authority_commitment_sha256
    )
    assert changed.packed_content_sha256 != original.packed_content_sha256
    assert changed.packed_manifest != original.packed_manifest
    assert changed.extraction_request_body_sha256 != original.extraction_request_body_sha256
    assert changed.source_commitment_sha256 != original.source_commitment_sha256


@pytest.mark.parametrize(
    "changed",
    (
        {"case_id": "conv-26:qa:2"},
        {"benchmark": "longmemeval"},
        {"metadata": {"locomo_ingest_mode": "rich-documents"}},
    ),
)
def test_projection_rejects_every_nonofficial_case_shape(changed: dict[str, object]) -> None:
    with pytest.raises(FreshChainCanaryError) as raised:
        project_fresh_chain_whole_corpus(
            replace(_case(), **changed),
            current_date="2026-08-12",
        )

    assert raised.value.code == "fresh_chain_source_case_invalid"


def test_projection_fails_closed_when_single_call_source_limit_is_exceeded() -> None:
    with pytest.raises(FreshChainCanaryError) as raised:
        project_fresh_chain_whole_corpus(
            _case(first_text="x" * 131_000),
            current_date="2026-08-12",
        )

    assert raised.value.code == "fresh_chain_source_pack_too_large"


def test_projection_constructor_rejects_commitment_tampering() -> None:
    projection = project_fresh_chain_whole_corpus(_case(), current_date="2026-08-12")

    with pytest.raises(FreshChainCanaryError) as raised:
        replace(projection, packed_content_sha256="0" * 64)

    assert raised.value.code == "fresh_chain_source_pack_invalid"

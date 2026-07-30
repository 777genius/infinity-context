from __future__ import annotations

from dataclasses import replace

import pytest
from infinity_context_server.public_benchmark_checkpoint import safe_identifier
from infinity_context_server.public_benchmark_models import (
    BenchmarkMemoryInput,
    BenchmarkValidationError,
    PublicBenchmarkCase,
)
from infinity_context_server.ranked_evidence_evaluator_helpers import (
    benchmark_memory_source_id,
    evaluator_only_payload,
    source_ref_id,
)
from infinity_context_server.ranked_evidence_seed_case import ranked_evidence_seed_case


def _case(**overrides: object) -> PublicBenchmarkCase:
    values: dict[str, object] = {
        "benchmark": "locomo",
        "case_id": "case-1",
        "question": "What happened?",
        "expected_terms": ("fallback", "answer"),
        "memories": (BenchmarkMemoryInput(text="gold-free corpus", source_external_id="source-1"),),
        "metadata": {
            "_evaluator_ground_truth": "full exact answer",
            "answer_preview": "preview",
            "evidence": ["must-not-cross-retrieval-boundary"],
        },
    }
    values.update(overrides)
    return PublicBenchmarkCase(**values)


def test_evaluator_payload_projects_only_exact_gold_after_boundary() -> None:
    payload = evaluator_only_payload(_case())

    assert payload == {
        "schema_version": "memory-comparison-evaluator-only.v1",
        "ground_truth": "full exact answer",
    }
    assert "evidence" not in payload
    assert "expected_terms" not in payload


def test_evaluator_payload_uses_existing_fallback_order() -> None:
    preview_case = _case(metadata={"answer_preview": "preview only"})
    terms_case = replace(preview_case, metadata={})

    assert evaluator_only_payload(preview_case)["ground_truth"] == "preview only"
    assert evaluator_only_payload(terms_case)["ground_truth"] == "fallback | answer"


@pytest.mark.parametrize(
    "ground_truth",
    (
        object(),
        float("inf"),
        [[[[[[[[[[1]]]]]]]]]],
    ),
)
def test_evaluator_payload_fails_closed_for_unbounded_or_private_shapes(
    ground_truth: object,
) -> None:
    case = _case(metadata={"_evaluator_ground_truth": ground_truth})

    with pytest.raises(BenchmarkValidationError):
        evaluator_only_payload(case)


def test_evaluator_payload_rejects_gold_free_seed_dto() -> None:
    seed_case = ranked_evidence_seed_case(_case())

    with pytest.raises(BenchmarkValidationError):
        evaluator_only_payload(seed_case)  # type: ignore[arg-type]


def test_memory_source_id_preserves_explicit_and_fallback_identities() -> None:
    explicit = "source-" + ("x" * 200)
    explicit_memory = BenchmarkMemoryInput(text="content", source_external_id=explicit)
    fallback_memory = BenchmarkMemoryInput(text="content")
    case = _case()
    seed_case = ranked_evidence_seed_case(case)

    assert benchmark_memory_source_id(case, explicit_memory, step=1) == safe_identifier(
        explicit,
        max_chars=160,
    )
    assert benchmark_memory_source_id(seed_case, fallback_memory, step=7) == "case-1:memory:7"


@pytest.mark.parametrize("step", (0, -1, True, "1"))
def test_memory_source_id_rejects_invalid_steps(step: object) -> None:
    with pytest.raises(BenchmarkValidationError):
        benchmark_memory_source_id(_case(), BenchmarkMemoryInput(text="content"), step=step)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("ref", "expected"),
    (
        (" source-1 ", "source-1"),
        ({"source_id": " primary ", "id": "fallback"}, "primary"),
        ({"source_external_id": " external "}, "external"),
        ({"id": " local "}, "local"),
        ({"source_id": 7, "id": "valid"}, "valid"),
        ({"source_id": "  "}, None),
        (b"source-1", None),
        (object(), None),
    ),
)
def test_source_ref_id_accepts_only_public_string_or_mapping_shapes(
    ref: object,
    expected: str | None,
) -> None:
    assert source_ref_id(ref) == expected

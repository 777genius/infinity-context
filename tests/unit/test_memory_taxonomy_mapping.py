import asyncio

from memo_stack_core.application.auto_memory import RuleBasedMemoryClassifier
from memo_stack_core.domain.entities import Confidence, MemoryKind, TrustLevel
from memo_stack_core.domain.taxonomy import DefaultTaxonomyPolicy
from memo_stack_core.ports.auto_memory import (
    ALLOWED_TTL_POLICIES,
    CandidateOperation,
    MemoryCandidate,
    SourceProvenance,
)


def test_taxonomy_maps_kind_to_default_category_and_durable_ttl() -> None:
    policy = DefaultTaxonomyPolicy()
    result = policy.normalize(
        MemoryCandidate(
            text="Use Graphiti for temporal facts.",
            kind=MemoryKind.ARCHITECTURE_DECISION,
            confidence=Confidence.MEDIUM,
            source_refs=(),
            safe_reason="explicit_marker",
            tags=("Graphiti", "Memory", "Graphiti"),
        )
    )

    assert result.category == "architecture"
    assert result.tags == ("graphiti", "memory")
    assert result.ttl_policy.name == "durable"
    assert result.ttl_policy.duration is None


def test_taxonomy_supports_port_ttl_contract() -> None:
    policy = DefaultTaxonomyPolicy()

    for ttl_policy in ALLOWED_TTL_POLICIES:
        result = policy.normalize(
            MemoryCandidate(
                text=f"TTL contract must support {ttl_policy}.",
                kind=MemoryKind.NOTE,
                confidence=Confidence.MEDIUM,
                source_refs=(),
                safe_reason="test",
                ttl_policy=ttl_policy,
            )
        )

        assert result.ttl_policy.name == ttl_policy
        assert not result.unknown_labels


def test_taxonomy_unknown_labels_are_not_persisted_raw() -> None:
    policy = DefaultTaxonomyPolicy()
    result = policy.normalize(
        MemoryCandidate(
            text="Temporary note.",
            kind=MemoryKind.NOTE,
            confidence=Confidence.LOW,
            source_refs=(),
            safe_reason="test",
            category="Very Strange Category",
            tags=("safe", "DROP TABLE memory", "x" * 80),
            ttl_policy="foreverish",
        )
    )

    assert result.category == "uncategorized"
    assert "very_strange_category" not in result.category
    assert result.ttl_policy.name == "review"
    assert result.unknown_labels
    assert all(len(tag) <= 48 for tag in result.tags)


def test_rule_based_classifier_marks_current_task_as_temporary() -> None:
    classifier = RuleBasedMemoryClassifier()

    candidates = asyncio.run(
        classifier.classify(
            text="Current task: finish the memo stack hook preflight.",
            source=SourceProvenance(
                source_type="capture:hook",
                source_id="cap_task",
                trust_level=TrustLevel.MEDIUM,
            ),
        )
    )

    assert len(candidates) == 1
    assert candidates[0].category == "current_task"
    assert candidates[0].ttl_policy == "task"
    assert candidates[0].safe_reason == "explicit_current_task_marker"


def test_rule_based_classifier_extracts_update_delete_and_review_operations() -> None:
    classifier = RuleBasedMemoryClassifier()

    candidates = asyncio.run(
        classifier.classify(
            text=(
                "Update memory: old provider is REST -> new provider is GraphQL.\n"
                "Forget: legacy Angular frontend.\n"
                "Review memory: maybe the deployment moved to Fly.io."
            ),
            source=SourceProvenance(
                source_type="capture:hook",
                source_id="cap_ops",
                trust_level=TrustLevel.MEDIUM,
            ),
        )
    )

    assert [candidate.operation_hint for candidate in candidates] == [
        CandidateOperation.UPDATE,
        CandidateOperation.DELETE,
        CandidateOperation.REVIEW,
    ]
    assert candidates[0].target_hint == "old provider is REST"
    assert candidates[0].text == "new provider is GraphQL."
    assert candidates[1].target_hint == "legacy Angular frontend."
    assert candidates[1].ttl_policy == "delete_review"
    assert candidates[2].confidence == Confidence.LOW


def test_rule_based_classifier_extracts_high_signal_semantic_memory() -> None:
    classifier = RuleBasedMemoryClassifier()

    candidates = asyncio.run(
        classifier.classify(
            text=(
                "We decided that semantic Graphiti remains the temporal facts engine.\n"
                "We must not store raw API tokens in diagnostics.\n"
                "I prefer concise Russian summaries.\n"
                "The project uses Qdrant for document vectors."
            ),
            source=SourceProvenance(
                source_type="capture:hook",
                source_id="cap_semantic",
                trust_level=TrustLevel.MEDIUM,
            ),
        )
    )

    assert [candidate.kind for candidate in candidates] == [
        MemoryKind.ARCHITECTURE_DECISION,
        MemoryKind.CONSTRAINT,
        MemoryKind.USER_PREFERENCE,
        MemoryKind.NOTE,
    ]
    assert all(candidate.operation_hint == CandidateOperation.ADD for candidate in candidates)
    assert all(candidate.confidence == Confidence.LOW for candidate in candidates)
    assert candidates[0].safe_reason == "semantic_decision_statement"
    assert candidates[1].text == "Must not store raw API tokens in diagnostics."


def test_rule_based_classifier_keeps_semantic_questions_and_noise_out() -> None:
    classifier = RuleBasedMemoryClassifier()

    candidates = asyncio.run(
        classifier.classify(
            text=(
                "Should we decided that Graphiti is the engine?\n"
                "Can the project uses Qdrant here?\n"
                "# Remember: copied code comment."
            ),
            source=SourceProvenance(
                source_type="capture:hook",
                source_id="cap_semantic_noise",
                trust_level=TrustLevel.MEDIUM,
            ),
        )
    )

    assert candidates == ()

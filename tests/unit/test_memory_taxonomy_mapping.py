import asyncio

from memo_stack_core.application.auto_memory import RuleBasedMemoryClassifier
from memo_stack_core.domain.entities import Confidence, MemoryKind, TrustLevel
from memo_stack_core.domain.taxonomy import DefaultTaxonomyPolicy
from memo_stack_core.ports.auto_memory import MemoryCandidate, SourceProvenance


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

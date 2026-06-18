from pathlib import Path

from memo_stack_core.application import context_diagnostics, context_link_policy
from memo_stack_core.application.use_cases import context_link_reviews
from memo_stack_core.domain import assets
from memo_stack_server.api.v1 import context as context_api

ROOT = Path(__file__).resolve().parents[2]


def test_memory_platform_rules_lock_bounded_payload_budgets() -> None:
    rules = (ROOT / "docs" / "memory-platform-critical-rules.md").read_text(encoding="utf-8")

    assert "## Bounded payload budgets" in rules
    assert f"max {context_diagnostics._MAX_RETRIEVAL_SOURCES}" in rules
    assert f"max {context_api._MAX_PUBLIC_CONTEXT_SOURCE_REFS}" in rules
    assert f"max {context_diagnostics._MAX_DIAGNOSTIC_MAPPING_ITEMS}" in rules
    assert f"max {context_diagnostics._MAX_DIAGNOSTIC_LIST_ITEMS}" in rules
    assert f"max {context_diagnostics._MAX_DIAGNOSTIC_KEY_CHARS} chars" in rules
    assert f"max {context_diagnostics._MAX_DIAGNOSTIC_STRING_CHARS} chars" in rules
    assert f"max {context_diagnostics._MAX_RANKING_REASON_CHARS} chars" in rules
    assert f"max {context_link_policy.MAX_DENIED_DIAGNOSTIC_ITEMS}" in rules
    assert f"max {context_link_policy.MAX_SUGGESTIONS_PER_SOURCE}" in rules
    assert f"max {context_link_reviews.MAX_CONTEXT_LINK_BATCH_REVIEW_ITEMS}" in rules
    assert f"max {assets.MAX_CONTEXT_LINK_REVIEW_EVENTS}" in rules
    assert f"max {context_link_reviews.MAX_SAFE_BATCH_ERROR_CHARS} chars" in rules


def test_memory_platform_rules_lock_review_audit_contract() -> None:
    rules = (ROOT / "docs" / "memory-platform-critical-rules.md").read_text(encoding="utf-8")

    for required in (
        "## Review and audit event contract",
        "event_type",
        "space_id",
        "memory_scope_id",
        "source_type / source_id",
        "target_type / target_id",
        "policy_version",
        "previous_status",
        "new_status",
    ):
        assert required in rules


def test_memory_architecture_lockfile_covers_core_product_rules() -> None:
    lockfile = (ROOT / "docs" / "memory-architecture-research-lockfile.md").read_text(
        encoding="utf-8"
    )

    for required in (
        "### Locked Rule Index",
        "`memory-type-boundaries`",
        "`anchors-not-tags`",
        "`temporal-current-by-default`",
        "`review-over-weak-automation`",
        "`evidence-not-instruction`",
        "`postgres-canonical`",
        "`derived-indexes-only`",
        "`bounded-provenance`",
        "`legacy-compatible`",
        "`multimodal-evidence-first`",
        "## Feature Slice Readiness Gates",
        "semantic-linking-golden coverage",
        "quality-golden coverage",
        "provider-derived content is evidence-first",
    ):
        assert required in lockfile

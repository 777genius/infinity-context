from pathlib import Path

from infinity_context_core.application import context_diagnostics, context_link_policy
from infinity_context_core.application.use_cases import context_link_reviews
from infinity_context_core.domain import assets
from infinity_context_server.features.context_building import (
    legacy_api_responses as context_api_responses,
)

ROOT = Path(__file__).resolve().parents[2]


def test_memory_platform_rules_lock_bounded_payload_budgets() -> None:
    rules = (ROOT / "docs" / "memory-platform-critical-rules.md").read_text(encoding="utf-8")

    assert "## Bounded payload budgets" in rules
    assert f"max {context_diagnostics._MAX_RETRIEVAL_SOURCES}" in rules
    assert f"max {context_api_responses._MAX_PUBLIC_CONTEXT_SOURCE_REFS}" in rules
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
        "`public-multimodal-contract`",
        "### Public Capabilities Contract",
        "infinity_context.extraction_evidence_contract.v1",
        "source_ref_coordinate_fields",
        "input_modalities",
        "evidence_coordinates",
        "primary_artifact_types",
        "external_provider_egress",
        "requires_explicit_external_ai",
        "may_run_local_asr",
        "## Feature Slice Readiness Gates",
        "semantic-linking-golden coverage",
        "quality-golden coverage",
        "provider-derived content is evidence-first",
        "capabilities API/SDK contract tests",
    ):
        assert required in lockfile


def test_memory_architecture_lockfile_documents_public_policy_reason_codes() -> None:
    lockfile = (ROOT / "docs" / "memory-architecture-research-lockfile.md").read_text(
        encoding="utf-8"
    )

    for required in (
        "### Public Policy Reason Codes",
        "`score_threshold_met`",
        "`review_required`",
        "`auto_approve_eligible`",
        "`review_required_target_type`",
        "`insufficient_independent_signals`",
        "`score_below_review_threshold`",
        "`missing_reason_codes`",
        "`recent_context_only`",
        "`weak_signal_below_review_threshold`",
        "`unsupported_relation_type`",
        "`high_impact_relation_requires_explicit_signal`",
        "`evidence_relation_requires_source_signal`",
        "`mentions_relation_requires_entity_signal`",
        "`text_match`",
        "`recent_activity`",
        "`temporal_proximity`",
        "`temporal_intent_match`",
        "`same_thread`",
        "`shared_category`",
        "`explicit_project_reference`",
        "`known_project_tool_reference`",
        "`event_phrase`",
        "`person_name`",
        "`organization_reference`",
        "`recent_context`",
        "`rule_signal`",
        "`supersedes_signal`",
        "`contradicts_signal`",
        "`explicit_user_update`",
        "`explicit_correction`",
        "`duplicates_signal`",
        "`exact_duplicate`",
        "`semantic_duplicate`",
        "`same_kind`",
        "`same_source_hash`",
        "`equivalent_text`",
    ):
        assert required in lockfile

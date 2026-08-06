"""Required PostgreSQL catalog surface for the unversioned 0022 baseline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LegacySchemaManifest:
    name: str
    columns: dict[str, frozenset[str]]
    constraints: frozenset[str]
    indexes: frozenset[str]
    triggers: frozenset[str]
    extensions: frozenset[str]
    functions: frozenset[str]

LEGACY_0022_COLUMNS: dict[str, frozenset[str]] = {
    "memory_anchors": frozenset(
        {
            "id", "space_id", "memory_scope_id", "kind", "normalized_key", "label",
            "aliases_json", "description", "status", "confidence", "evidence_refs_json",
            "observed_at", "valid_from", "valid_to", "metadata_json", "created_at",
            "updated_at",
        }
    ),
    "memory_asset_extraction_artifacts": frozenset(
        {
            "id", "job_id", "asset_id", "artifact_type", "storage_backend", "storage_key",
            "sha256_hex", "byte_size", "metadata_json", "created_at",
        }
    ),
    "memory_asset_extraction_jobs": frozenset(
        {
            "id", "asset_id", "space_id", "memory_scope_id", "thread_id", "parser_profile",
            "parser_config_hash", "source_sha256_hex", "parser_name", "parser_version",
            "model_version", "status", "attempt_count", "safe_error_code",
            "safe_error_message", "result_document_ids_json", "metadata_json", "created_at",
            "updated_at", "started_at", "finished_at", "lease_owner", "lease_expires_at",
            "heartbeat_at", "retry_after_at", "cancellation_requested_at",
            "retry_disposition",
        }
    ),
    "memory_chunks": frozenset(
        {
            "id", "space_id", "memory_scope_id", "thread_id", "document_id", "episode_id",
            "source_type", "source_external_id", "source_hash", "kind", "text",
            "normalized_text", "status", "sequence", "char_start", "char_end",
            "token_estimate", "classification", "created_at", "updated_at", "metadata_json",
        }
    ),
    "memory_comparison_benchmark_runs": frozenset(
        {
            "run_id_sha256", "binding_commitment_sha256", "infinity_target_identity_sha256",
            "space_id", "space_slug", "idempotency_key_sha256",
            "registration_fingerprint_sha256", "state", "cleanup_fingerprint_sha256",
            "cleanup_receipt_json", "created_at", "updated_at", "projection_manifest_json",
            "projection_manifest_sha256", "projection_cleanup_state",
            "finalization_fingerprint_sha256", "completion_receipt_json", "completed_at",
        }
    ),
    "memory_context_link_suggestions": frozenset(
        {
            "id", "space_id", "memory_scope_id", "source_type", "source_id", "target_type",
            "target_id", "relation_type", "confidence", "reason", "score", "status",
            "metadata_json", "created_at", "updated_at", "reviewed_at", "review_reason",
        }
    ),
    "memory_documents": frozenset(
        {
            "id", "space_id", "memory_scope_id", "thread_id", "title", "source_type",
            "source_external_id", "content_hash", "classification", "status", "created_at",
            "updated_at",
        }
    ),
    "memory_episodes": frozenset(
        {
            "id", "space_id", "memory_scope_id", "thread_id", "source_type",
            "source_external_id", "text", "speaker", "trust_level", "status", "occurred_at",
            "created_at", "metadata_json",
        }
    ),
    "memory_fact_versions": frozenset(
        {
            "id", "fact_id", "version", "text", "status", "source_refs_json", "reason",
            "created_at",
        }
    ),
    "memory_facts": frozenset(
        {
            "id", "space_id", "memory_scope_id", "thread_id", "kind", "text", "status",
            "confidence", "trust_level", "classification", "version", "created_at",
            "updated_at", "category", "tags_json", "ttl_policy", "expires_at",
        }
    ),
    "memory_idempotency_records": frozenset(
        {"id", "space_id", "key", "fingerprint", "result_type", "result_id", "created_at"}
    ),
    "memory_outbox": frozenset(
        {
            "id", "event_type", "aggregate_type", "aggregate_id", "aggregate_version",
            "payload_json", "status", "attempt_count", "next_attempt_at", "last_safe_error",
            "created_at", "updated_at", "workload_class", "fairness_key",
            "last_safe_diagnostic_code",
        }
    ),
    "memory_scopes": frozenset(
        {"id", "space_id", "external_ref", "name", "status", "created_at", "updated_at"}
    ),
    "memory_service_tokens": frozenset(
        {
            "id", "space_id", "memory_scope_ids_json", "description", "token_hash",
            "permissions_json", "status", "created_at", "last_used_at", "expires_at",
            "revoked_at",
        }
    ),
    "memory_source_refs": frozenset(
        {
            "id", "fact_id", "fact_version", "source_type", "source_id", "chunk_id",
            "char_start", "char_end", "quote_preview",
        }
    ),
    "memory_space_memberships": frozenset(
        {"id", "space_id", "user_id", "role", "status", "created_at", "updated_at"}
    ),
    "memory_spaces": frozenset(
        {"id", "slug", "name", "status", "created_at", "updated_at"}
    ),
    "memory_suggestions": frozenset(
        {
            "id", "space_id", "memory_scope_id", "candidate_text", "kind", "status",
            "source_refs_json", "confidence", "trust_level", "safe_reason", "target_fact_id",
            "target_fact_version", "review_reason", "created_at", "updated_at", "reviewed_at",
        }
    ),
    "memory_threads": frozenset(
        {"id", "space_id", "memory_scope_id", "external_ref", "status", "created_at", "updated_at"}
    ),
    "memory_usage_records": frozenset(
        {
            "id", "subject_type", "subject_id", "space_id", "memory_scope_id", "resource",
            "quantity", "status", "source_type", "source_id", "idempotency_key",
            "window_start", "window_end", "metadata_json", "created_at",
        }
    ),
    "memory_users": frozenset(
        {
            "id", "external_ref", "display_name", "email", "status", "metadata_json",
            "created_at", "updated_at",
        }
    ),
}

LEGACY_0022_CONSTRAINTS = frozenset(
    {
        "ck_chunk_owner", "ck_fact_version_positive",
        "ck_memory_comparison_benchmark_run_cleanup_state",
        "ck_memory_comparison_benchmark_run_manifest_coupling",
        "ck_memory_comparison_benchmark_run_projection_cleanup_state",
        "ck_memory_comparison_benchmark_run_projection_lifecycle",
        "ck_memory_comparison_benchmark_run_state", "memory_anchors_pkey",
        "memory_asset_extraction_artifacts_pkey", "memory_asset_extraction_jobs_pkey",
        "memory_chunks_pkey", "memory_comparison_benchmark_runs_pkey",
        "memory_comparison_benchmark_runs_space_id_fkey",
        "memory_context_link_suggestions_pkey", "memory_documents_pkey",
        "memory_episodes_pkey", "memory_fact_versions_fact_id_fkey",
        "memory_fact_versions_pkey", "memory_facts_pkey", "memory_idempotency_records_pkey",
        "memory_outbox_pkey", "memory_scopes_pkey", "memory_scopes_space_id_fkey",
        "memory_service_tokens_pkey", "memory_service_tokens_token_hash_key",
        "memory_source_refs_fact_id_fkey", "memory_source_refs_pkey",
        "memory_space_memberships_pkey", "memory_space_memberships_space_id_fkey",
        "memory_space_memberships_user_id_fkey", "memory_spaces_pkey",
        "memory_spaces_slug_key", "memory_suggestions_pkey", "memory_threads_pkey",
        "memory_usage_records_pkey", "memory_users_pkey", "uq_chunk_source_hash",
        "uq_episode_source", "uq_fact_version", "uq_idempotency_space_key",
        "uq_memory_comparison_benchmark_run_idempotency",
        "uq_memory_comparison_benchmark_run_space_id",
        "uq_memory_comparison_benchmark_run_space_slug", "uq_memory_scope_external_ref",
        "uq_thread_external_ref",
    }
)

LEGACY_0022_INDEXES = frozenset(
    {
        "ix_asset_extraction_artifacts_asset", "ix_asset_extraction_artifacts_job",
        "ix_asset_extraction_jobs_asset_status", "ix_asset_extraction_jobs_running_lease",
        "ix_asset_extraction_jobs_scope_status", "ix_context_link_suggestions_source",
        "ix_context_link_suggestions_status", "ix_memory_anchors_scope_kind",
        "ix_memory_chunks_canonical_keyword_trgm", "ix_memory_chunks_document",
        "ix_memory_chunks_scope_status", "ix_memory_chunks_thread_status",
        "ix_memory_documents_scope_status", "ix_memory_episodes_thread_status",
        "ix_memory_facts_scope_status", "ix_memory_facts_taxonomy",
        "ix_memory_outbox_status_next", "ix_memory_outbox_workload_fairness",
        "ix_memory_service_tokens_status", "ix_memory_source_refs_fact",
        "ix_memory_space_memberships_space", "ix_memory_space_memberships_user",
        "ix_memory_suggestions_scope_status", "ix_memory_suggestions_target",
        "ix_memory_threads_scope_status", "ix_memory_usage_space_created",
        "ix_memory_usage_subject_window", "ix_memory_users_status",
        "uq_asset_extraction_jobs_active_profile", "uq_chunk_source_hash",
        "uq_context_link_suggestion_pending", "uq_document_content_hash_memory_scope_wide",
        "uq_document_content_hash_thread", "uq_episode_source", "uq_fact_version",
        "uq_idempotency_space_key", "uq_memory_anchor_active_key",
        "uq_memory_comparison_benchmark_run_idempotency",
        "uq_memory_comparison_benchmark_run_space_id",
        "uq_memory_comparison_benchmark_run_space_slug", "uq_memory_scope_external_ref",
        "uq_memory_space_membership_active_user", "uq_memory_usage_idempotency",
        "uq_memory_user_external_ref", "uq_thread_external_ref",
    }
)

LEGACY_0022_TRIGGERS = frozenset(
    {
        "trg_memory_anchors_benchmark_writer_fence",
        "trg_memory_asset_extraction_jobs_benchmark_writer_fence",
        "trg_memory_chunks_benchmark_writer_fence",
        "trg_memory_context_link_suggestions_benchmark_writer_fence",
        "trg_memory_documents_benchmark_writer_fence",
        "trg_memory_episodes_benchmark_writer_fence",
        "trg_memory_facts_benchmark_writer_fence",
        "trg_memory_scopes_benchmark_writer_fence",
        "trg_memory_spaces_benchmark_writer_fence",
        "trg_memory_suggestions_benchmark_writer_fence",
        "trg_memory_threads_benchmark_writer_fence",
    }
)

LEGACY_0022_EXTENSIONS = frozenset({"pg_trgm"})
LEGACY_0022_FUNCTIONS = frozenset({"memory_comparison_enforce_benchmark_writer_fence"})

_METADATA_EXTRA_COLUMNS: dict[str, frozenset[str]] = {
    "memory_assets": frozenset(
        {
            "id", "space_id", "memory_scope_id", "thread_id", "filename", "content_type",
            "byte_size", "sha256_hex", "storage_backend", "storage_key", "status",
            "classification", "metadata_json", "created_at", "updated_at",
        }
    ),
    "memory_captures": frozenset(
        {
            "id", "space_id", "memory_scope_id", "thread_id", "source_agent", "source_kind",
            "event_type", "actor_role", "text_redacted", "evidence_refs_json", "payload_hash",
            "idempotency_key", "status", "consolidation_status", "trust_level",
            "source_authority", "sensitivity", "data_classification", "occurred_at",
            "received_at", "created_at", "updated_at", "metadata_json", "source_event_id",
            "source_actor_external_ref", "client_instance_id", "agent_session_external_ref",
            "turn_external_ref", "parent_capture_id", "sequence_index", "trace_id",
            "schema_version", "parser_version", "redaction_version", "admission_version",
            "normalization_version", "policy_version", "extractor_version",
            "extractor_prompt_version", "resolver_version", "last_error_code",
            "last_error_message",
        }
    ),
    "memory_context_links": frozenset(
        {
            "id", "space_id", "memory_scope_id", "source_type", "source_id", "target_type",
            "target_id", "relation_type", "confidence", "reason", "status", "metadata_json",
            "created_at", "updated_at",
        }
    ),
    "memory_fact_relations": frozenset(
        {
            "id", "space_id", "memory_scope_id", "source_fact_id", "target_fact_id",
            "relation_type", "reason", "status", "observed_at", "valid_from", "valid_to",
            "created_at", "updated_at",
        }
    ),
}

RAW_0022_MANIFEST = LegacySchemaManifest(
    name="raw_0022",
    columns=LEGACY_0022_COLUMNS,
    constraints=LEGACY_0022_CONSTRAINTS,
    indexes=LEGACY_0022_INDEXES,
    triggers=LEGACY_0022_TRIGGERS,
    extensions=LEGACY_0022_EXTENSIONS,
    functions=LEGACY_0022_FUNCTIONS,
)

ORIGIN_MAIN_METADATA_MANIFEST = LegacySchemaManifest(
    name="origin_main_metadata",
    columns={**LEGACY_0022_COLUMNS, **_METADATA_EXTRA_COLUMNS},
    constraints=(LEGACY_0022_CONSTRAINTS - {"ck_chunk_owner"})
    | {
        "memory_assets_pkey", "memory_captures_pkey", "memory_context_links_pkey",
        "memory_fact_relations_pkey", "memory_fact_relations_source_fact_id_fkey",
        "memory_fact_relations_target_fact_id_fkey", "uq_capture_idempotency",
    },
    indexes=LEGACY_0022_INDEXES
    | {
        "ix_memory_assets_hash_scope", "ix_memory_assets_scope_status",
        "ix_memory_assets_thread_status", "ix_memory_captures_consolidation",
        "ix_memory_captures_scope_status", "ix_memory_captures_source",
        "ix_memory_context_links_source", "ix_memory_context_links_target",
        "ix_memory_fact_relations_scope", "ix_memory_fact_relations_source",
        "ix_memory_fact_relations_target", "uq_memory_context_link_active",
        "uq_memory_fact_relation_active",
    },
    triggers=LEGACY_0022_TRIGGERS
    - {
        "trg_memory_anchors_benchmark_writer_fence",
        "trg_memory_asset_extraction_jobs_benchmark_writer_fence",
        "trg_memory_context_link_suggestions_benchmark_writer_fence",
        "trg_memory_suggestions_benchmark_writer_fence",
    },
    extensions=LEGACY_0022_EXTENSIONS,
    functions=LEGACY_0022_FUNCTIONS,
)

LEGACY_SCHEMA_MANIFESTS = (RAW_0022_MANIFEST, ORIGIN_MAIN_METADATA_MANIFEST)

__all__ = (
    "LEGACY_SCHEMA_MANIFESTS",
    "LegacySchemaManifest",
)

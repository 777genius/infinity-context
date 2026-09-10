"""Reviewed execution inventory at e7035c32; remove exact entries as migration progresses.

Eight semantic overlaps: six unused legacy fact fields, active context/doc pairs.
Locator retrieval is a separate owner. Compatibility imports are not overlaps.
Entries record Python route/helper -> executing Container member, including local
forwarding calls. Helpers are retained to make hidden/legacy consumers visible.
"""

CONTAINER_OVERLAPS = {
    ("build_context", "build_canonical_fact_context"),
    ("forget_fact", "memory_fact_lifecycle.forget_fact"),
    ("get_fact", "memory_fact_reads.get_fact"),
    ("ingest_document", "projected_document_ingestion"),
    ("list_fact_versions", "memory_fact_reads.list_versions"),
    ("list_facts", "memory_fact_reads.list_facts"),
    ("remember_fact", "memory_fact_lifecycle.remember_fact"),
    ("update_fact", "memory_fact_lifecycle.update_fact"),
}

ROUTE_OWNERS = {
    ("api.legacy_client._legacy_scope", "ensure_scope.execute"),
    ("api.legacy_client.legacy_context", "build_context.execute"),
    ("api.legacy_client.legacy_context", "ensure_scope.execute"),
    ("api.legacy_client.legacy_delete_session", "delete_thread_memory.execute"),
    ("api.legacy_client.legacy_delete_session", "ensure_scope.execute"),
    ("api.legacy_client.legacy_ingest", "ensure_scope.execute"),
    ("api.legacy_client.legacy_ingest", "ingest_episode.execute"),
    ("api.legacy_client.legacy_session_status", "ensure_scope.execute"),
    ("api.legacy_client.legacy_session_status", "get_session_status.execute"),
    ("api.v1.assets.cancel_asset_extraction", "cancel_asset_extraction.execute"),
    ("api.v1.assets.delete_asset", "delete_asset.execute"),
    ("api.v1.assets.download_asset", "read_asset_bytes.execute"),
    ("api.v1.assets.download_extraction_artifact", "read_extraction_artifact_bytes.execute"),
    ("api.v1.assets.get_asset", "get_asset.execute"),
    ("api.v1.assets.get_asset_extraction", "get_asset_extraction.execute"),
    ("api.v1.assets.list_asset_extractions", "list_asset_extractions.execute"),
    ("api.v1.assets.list_assets", "ensure_scope.execute"),
    ("api.v1.assets.list_assets", "list_assets.execute"),
    ("api.v1.assets.list_scope_asset_extractions", "ensure_scope.execute"),
    ("api.v1.assets.list_scope_asset_extractions", "list_asset_extractions.execute"),
    ("api.v1.assets.request_asset_extraction", "request_asset_extraction.execute"),
    ("api.v1.assets.retry_asset_extraction", "retry_asset_extraction.execute"),
    ("api.v1.assets.upload_asset", "create_asset.execute"),
    ("api.v1.assets.upload_asset", "ensure_scope.execute"),
    ("api.v1.assets.upload_asset", "request_asset_extraction.execute"),
    ("api.v1.context._build_context_bundle", "build_canonical_fact_context.execute"),
    ("api.v1.context._build_context_bundle", "build_context.execute"),
    ("api.v1.context.benchmark_search_memory", "build_canonical_fact_context.execute"),
    ("api.v1.context.benchmark_search_memory", "build_context.execute"),
    ("api.v1.context.benchmark_search_memory", "ensure_scope.execute"),
    ("api.v1.context.build_context", "build_canonical_fact_context.execute"),
    ("api.v1.context.build_context", "build_context.execute"),
    ("api.v1.context.build_context", "ensure_scope.execute"),
    ("api.v1.context.search_memory", "build_canonical_fact_context.execute"),
    ("api.v1.context.search_memory", "build_context.execute"),
    ("api.v1.context.search_memory", "ensure_scope.execute"),
    ("api.v1.context_retrieval._resolve_scope", "ensure_scope.execute"),
    # V3 shares the admitted retrieval owner; explicit route/helper edges remain audited.
    ("api.v1.context_retrieval._retrieve_context", "ensure_scope.execute"),
    ("api.v1.context_retrieval._retrieve_context", "locator_retrieval.execute"),
    ("api.v1.context_retrieval.retrieval_v3_descriptor", "locator_retrieval.descriptor"),
    ("api.v1.context_retrieval.retrieve_context_v3", "ensure_scope.execute"),
    ("api.v1.context_retrieval.retrieve_context_v3", "locator_retrieval.execute"),
    ("api.v1.context_retrieval.retrieve_context", "ensure_scope.execute"),
    ("api.v1.context_retrieval.retrieve_context", "locator_retrieval.execute"),
    ("api.v1.digest.build_digest", "build_memory_digest.execute"),
    ("api.v1.digest.build_digest", "ensure_scope.execute"),
    ("api.v1.documents.delete_document", "delete_document.execute"),
    ("api.v1.documents.get_document", "get_document.execute"),
    ("api.v1.documents.ingest_document", "ensure_scope.execute"),
    ("api.v1.documents.ingest_document", "ingest_document.execute"),
    ("api.v1.documents.ingest_document", "projected_document_ingestion.execute"),
    ("api.v1.documents.list_document_chunks", "list_document_chunks.execute"),
    ("api.v1.documents.list_documents", "ensure_scope.execute"),
    ("api.v1.documents.list_documents", "list_documents.execute"),
    ("api.v1.documents.process_document", "process_document.execute"),
    ("api.v1.documents.reconcile_exact_document", "reconcile_exact_document.execute"),
    ("api.v1.export.export_graph_json", "ensure_scope.execute"),
    ("api.v1.export.export_graph_json", "export_graph.execute"),
    ("api.v1.export.import_memory_scope_snapshot", "ensure_scope.execute"),
    ("api.v1.export.preview_memory_scope_snapshot_import", "ensure_scope.execute"),
    ("api.v1.facts._resolve_temporal_scope", "ensure_scope.execute"),
    ("api.v1.facts._scope_for_existing_fact", "memory_fact_reads.get_fact"),
    ("api.v1.facts.confirm_fact", "ensure_scope.execute"),
    ("api.v1.facts.confirm_fact", "memory_fact_temporal.confirm_fact"),
    ("api.v1.facts.dispute_fact", "ensure_scope.execute"),
    ("api.v1.facts.dispute_fact", "memory_fact_temporal.dispute_facts"),
    ("api.v1.facts.end_fact_validity", "ensure_scope.execute"),
    ("api.v1.facts.end_fact_validity", "memory_fact_temporal.end_validity"),
    ("api.v1.facts.forget_fact", "memory_fact_lifecycle.forget_fact"),
    ("api.v1.facts.forget_fact", "memory_fact_reads.get_fact"),
    ("api.v1.facts.get_fact", "memory_fact_reads.get_fact"),
    ("api.v1.facts.link_fact_relation", "link_facts.execute"),
    ("api.v1.facts.list_fact_relations", "list_fact_relations.execute"),
    ("api.v1.facts.list_fact_relations", "memory_fact_reads.get_fact.get_many"),
    ("api.v1.facts.list_fact_versions", "memory_fact_reads.list_versions"),
    ("api.v1.facts.list_facts", "ensure_scope.execute"),
    ("api.v1.facts.list_facts", "memory_fact_reads.list_facts.execute"),
    ("api.v1.facts.reinstate_supersession", "ensure_scope.execute"),
    ("api.v1.facts.reinstate_supersession", "memory_fact_temporal.reinstate_supersession"),
    ("api.v1.facts.related_facts", "memory_fact_reads.get_fact.get_many"),
    ("api.v1.facts.related_facts", "related_facts.execute"),
    ("api.v1.facts.remember_fact", "ensure_scope.execute"),
    ("api.v1.facts.remember_fact", "memory_fact_lifecycle.remember_fact"),
    ("api.v1.facts.supersede_fact", "ensure_scope.execute"),
    ("api.v1.facts.supersede_fact", "memory_fact_temporal.supersede_fact"),
    ("api.v1.facts.unlink_fact_relation", "unlink_fact_relation.execute"),
    ("api.v1.facts.update_fact", "memory_fact_lifecycle.update_fact"),
    ("api.v1.facts.update_fact", "memory_fact_reads.get_fact"),
    ("api.v1.insights.build_insights", "build_memory_insights.execute"),
    ("api.v1.insights.build_insights", "ensure_scope.execute"),
    ("api.v1.memory_browser.get_memory_browser", "build_memory_browser.execute"),
    ("api.v1.memory_browser.get_memory_browser", "ensure_scope.execute"),
    ("api.v1.operations.get_operations_console", "build_memory_operations_console.execute"),
    ("api.v1.operations.get_operations_console", "ensure_scope.execute"),
    ("api.v1.scope_resolution._resolve_context_scope", "ensure_scope.execute"),
    ("api.v1.scope_resolution._resolve_single_scope", "ensure_scope.execute"),
    ("api.v1.scope_resolution.resolve_context_scope", "ensure_scope.execute"),
    ("api.v1.scope_resolution.resolve_existing_context_scope", "ensure_scope.execute"),
    ("api.v1.scope_resolution.resolve_existing_single_scope", "ensure_scope.execute"),
    ("api.v1.scope_resolution.resolve_single_scope", "ensure_scope.execute"),
    ("api.v1.spaces_memory_scopes.create_memory_scope", "create_memory_scope.execute"),
    ("api.v1.spaces_memory_scopes.create_space", "create_space.execute"),
    ("api.v1.spaces_memory_scopes.delete_memory_scope", "delete_memory_scope.execute"),
    ("api.v1.spaces_memory_scopes.list_memory_scopes", "list_memory_scopes.execute"),
    ("api.v1.spaces_memory_scopes.list_spaces", "list_spaces.execute"),
    ("api.v1.spaces_memory_scopes.update_memory_scope", "update_memory_scope.execute"),
    ("api.v1.suggestions.approve_suggestion", "approve_suggestion.execute"),
    ("api.v1.suggestions.create_suggestion", "create_suggestion.execute"),
    ("api.v1.suggestions.create_suggestion", "ensure_scope.execute"),
    ("api.v1.suggestions.create_suggestions_batch", "create_suggestions_batch.execute"),
    ("api.v1.suggestions.create_suggestions_batch", "ensure_scope.execute"),
    ("api.v1.suggestions.expire_suggestion", "expire_suggestion.execute"),
    ("api.v1.suggestions.list_suggestions", "ensure_scope.execute"),
    ("api.v1.suggestions.list_suggestions", "list_suggestions.execute"),
    ("api.v1.suggestions.reject_suggestion", "reject_suggestion.execute"),
    ("api.v1.suggestions.resolve_duplicate_merge", "resolve_duplicate_merge.execute"),
    ("api.v1.suggestions.resolve_suggestion_conflict", "resolve_suggestion_conflict.execute"),
    ("api.v1.suggestions.review_suggestions_batch", "review_suggestions_batch.execute"),
    ("api.v1.thread_memory.delete_thread_memory", "delete_thread_memory.execute"),
    ("api.v1.thread_memory.delete_thread_memory", "ensure_scope.execute"),
    ("api.v1.thread_memory.delete_thread_memory_compat", "delete_thread_memory.execute"),
    ("api.v1.thread_memory.delete_thread_memory_compat", "ensure_scope.execute"),
    ("api.v1.thread_memory.thread_memory_status", "ensure_scope.execute"),
    ("api.v1.thread_memory.thread_memory_status", "get_session_status.execute"),
}

# Exact existing policy and strict-v4 compatibility exceptions; no wildcard debt.
FROZEN_INTERNAL_IMPORTS = {
    (
        "packages/infinity_context_core/infinity_context_core/application/benchmark_managed_write_admission.py",
        "infinity_context_core.features.memory_facts.application.commands",
    ),
    (
        "packages/infinity_context_core/infinity_context_core/application/context_packer_selection.py",
        "infinity_context_core.features.context_building.application.coverage_reservation_selector",
    ),
    (
        "packages/infinity_context_core/infinity_context_core/application/context_packer_selection.py",
        "infinity_context_core.features.context_building.domain.evidence_obligations",
    ),
    (
        "packages/infinity_context_server/infinity_context_server/memory_comparison_managed_v5_strict_v4_fact_ingest.py",
        "infinity_context_core.features.memory_facts.application.commands",
    ),
    (
        "packages/infinity_context_server/infinity_context_server/memory_comparison_managed_v5_strict_v4_fact_ingest.py",
        "infinity_context_core.features.memory_facts.domain",
    ),
    (
        "tests/e2e/test_strict_v4_writer_fence_postgres.py",
        "infinity_context_core.features.memory_facts.application.commands",
    ),
    (
        "tests/e2e/test_strict_v4_writer_fence_postgres.py",
        "infinity_context_core.features.memory_facts.domain",
    ),
    (
        "tests/unit/test_benchmark_managed_write_admission.py",
        "infinity_context_core.features.memory_facts.application.commands",
    ),
    (
        "tests/unit/test_benchmark_managed_write_admission.py",
        "infinity_context_core.features.memory_facts.domain",
    ),
    (
        "tests/unit/test_context_coverage_reservation_selector.py",
        "infinity_context_core.features.context_building.application.coverage_reservation_selector",
    ),
    (
        "tests/unit/test_context_coverage_reservation_selector.py",
        "infinity_context_core.features.context_building.domain.evidence_obligations",
    ),
    (
        "tests/unit/test_postgres_managed_fact_admission.py",
        "infinity_context_core.features.memory_facts.application.commands",
    ),
    (
        "tests/unit/test_postgres_managed_fact_admission.py",
        "infinity_context_core.features.memory_facts.application.handlers",
    ),
    (
        "tests/unit/test_postgres_managed_fact_admission.py",
        "infinity_context_core.features.memory_facts.domain",
    ),
    (
        "tests/unit/test_projection_result_receipts.py",
        "infinity_context_core.features.memory_facts.domain",
    ),
    (
        "tests/unit/test_projection_result_receipts.py",
        "infinity_context_core.features.memory_facts.ports",
    ),
}

# Executing field types prevent a same-name field from silently changing owner.
ROUTE_OWNER_TYPES = {
    (
        "approve_suggestion",
        "infinity_context_core.application.use_cases.suggestions.ApproveSuggestionUseCase",
    ),
    (
        "build_canonical_fact_context",
        "infinity_context_core.features.context_building.application.handlers.BuildContextHandler",
    ),
    (
        "build_context",
        "infinity_context_core.application.use_cases.build_context.BuildContextUseCase",
    ),
    (
        "build_memory_browser",
        "infinity_context_core.application.use_cases.memory_browser.BuildMemoryBrowserUseCase",
    ),
    (
        "build_memory_digest",
        "infinity_context_core.application.use_cases.build_memory_digest.BuildMemoryDigestUseCase",
    ),
    (
        "build_memory_insights",
        "infinity_context_core.application.use_cases.build_memory_insights.BuildMemoryInsightsUseCase",
    ),
    (
        "build_memory_operations_console",
        "infinity_context_core.application.use_cases.operations_console.BuildMemoryOperationsConsoleUseCase",
    ),
    (
        "cancel_asset_extraction",
        "infinity_context_core.application.use_cases.asset_extractions.CancelAssetExtractionUseCase",
    ),
    ("create_asset", "infinity_context_core.application.use_cases.assets.CreateAssetUseCase"),
    (
        "create_memory_scope",
        "infinity_context_core.application.use_cases.spaces_memory_scopes.CreateMemoryScopeUseCase",
    ),
    (
        "create_space",
        "infinity_context_core.application.use_cases.spaces_memory_scopes.CreateSpaceUseCase",
    ),
    (
        "create_suggestion",
        "infinity_context_core.application.use_cases.suggestions.CreateSuggestionUseCase",
    ),
    (
        "create_suggestions_batch",
        "infinity_context_core.application.use_cases.suggestions.CreateSuggestionsBatchUseCase",
    ),
    ("delete_asset", "infinity_context_core.application.use_cases.assets.DeleteAssetUseCase"),
    (
        "delete_document",
        "infinity_context_core.application.use_cases.delete_document.DeleteDocumentUseCase",
    ),
    (
        "delete_memory_scope",
        "infinity_context_core.application.use_cases.spaces_memory_scopes.DeleteMemoryScopeUseCase",
    ),
    (
        "delete_thread_memory",
        "infinity_context_core.application.use_cases.delete_thread_memory.DeleteThreadMemoryUseCase",
    ),
    ("ensure_scope", "infinity_context_core.application.use_cases.ensure_scope.EnsureScopeUseCase"),
    (
        "expire_suggestion",
        "infinity_context_core.application.use_cases.suggestions.ExpireSuggestionUseCase",
    ),
    ("export_graph", "infinity_context_core.application.use_cases.export_graph.ExportGraphUseCase"),
    ("get_asset", "infinity_context_core.application.use_cases.assets.GetAssetUseCase"),
    (
        "get_asset_extraction",
        "infinity_context_core.application.use_cases.asset_extractions.GetAssetExtractionUseCase",
    ),
    (
        "get_document",
        "infinity_context_core.application.use_cases.query_documents.GetDocumentUseCase",
    ),
    (
        "get_session_status",
        "infinity_context_core.application.use_cases.get_session_status.GetSessionStatusUseCase",
    ),
    (
        "ingest_document",
        "infinity_context_core.application.use_cases.ingest_document.IngestDocumentUseCase",
    ),
    (
        "ingest_episode",
        "infinity_context_core.application.use_cases.ingest_episode.IngestEpisodeUseCase",
    ),
    ("link_facts", "infinity_context_core.application.use_cases.fact_relations.LinkFactsUseCase"),
    (
        "list_asset_extractions",
        "infinity_context_core.application.use_cases.asset_extractions.ListAssetExtractionsUseCase",
    ),
    ("list_assets", "infinity_context_core.application.use_cases.assets.ListAssetsUseCase"),
    (
        "list_document_chunks",
        "infinity_context_core.application.use_cases.query_documents.ListDocumentChunksUseCase",
    ),
    (
        "list_documents",
        "infinity_context_core.application.use_cases.query_documents.ListDocumentsUseCase",
    ),
    (
        "list_fact_relations",
        "infinity_context_core.application.use_cases.fact_relations.ListFactRelationsUseCase",
    ),
    (
        "list_memory_scopes",
        "infinity_context_core.application.use_cases.spaces_memory_scopes.ListMemoryScopesUseCase",
    ),
    (
        "list_spaces",
        "infinity_context_core.application.use_cases.spaces_memory_scopes.ListSpacesUseCase",
    ),
    (
        "list_suggestions",
        "infinity_context_core.application.use_cases.suggestions.ListSuggestionsUseCase",
    ),
    (
        "locator_retrieval",
        "infinity_context_server.features.context_building.retrieval_service.LocatorRetrievalService",
    ),
    (
        "memory_fact_lifecycle",
        "infinity_context_core.features.memory_facts.application.use_cases.MemoryFactLifecycleUseCases",
    ),
    (
        "memory_fact_reads",
        "infinity_context_core.features.memory_facts.application.reads.MemoryFactReadUseCases",
    ),
    (
        "memory_fact_temporal",
        "infinity_context_core.features.memory_facts.application.use_cases.MemoryFactTemporalUseCases",
    ),
    (
        "process_document",
        "infinity_context_core.application.use_cases.process_document.ProcessDocumentUseCase",
    ),
    (
        "projected_document_ingestion",
        "infinity_context_adapters.postgres.projected_document_ingestion.PostgresProjectedDocumentIngestor",
    ),
    (
        "read_asset_bytes",
        "infinity_context_core.application.use_cases.assets.ReadAssetBytesUseCase",
    ),
    (
        "read_extraction_artifact_bytes",
        "infinity_context_core.application.use_cases.asset_extractions.ReadExtractionArtifactBytesUseCase",
    ),
    (
        "reconcile_exact_document",
        "infinity_context_core.features.document_ingestion.application.reconciliation.ReconcileExactDocumentHandler",
    ),
    (
        "reject_suggestion",
        "infinity_context_core.application.use_cases.suggestions.RejectSuggestionUseCase",
    ),
    (
        "related_facts",
        "infinity_context_core.application.use_cases.related_facts.RelatedFactsUseCase",
    ),
    (
        "request_asset_extraction",
        "infinity_context_core.application.use_cases.asset_extractions.RequestAssetExtractionUseCase",
    ),
    (
        "resolve_duplicate_merge",
        "infinity_context_core.application.use_cases.duplicate_merge_resolution.ResolveDuplicateMergeUseCase",
    ),
    (
        "resolve_suggestion_conflict",
        "infinity_context_core.application.use_cases.suggestions.ResolveSuggestionConflictUseCase",
    ),
    (
        "retry_asset_extraction",
        "infinity_context_core.application.use_cases.asset_extractions.RetryAssetExtractionUseCase",
    ),
    (
        "review_suggestions_batch",
        "infinity_context_core.application.use_cases.suggestions.ReviewSuggestionsBatchUseCase",
    ),
    (
        "unlink_fact_relation",
        "infinity_context_core.application.use_cases.fact_relations.UnlinkFactRelationUseCase",
    ),
    (
        "update_memory_scope",
        "infinity_context_core.application.use_cases.spaces_memory_scopes.UpdateMemoryScopeUseCase",
    ),
}

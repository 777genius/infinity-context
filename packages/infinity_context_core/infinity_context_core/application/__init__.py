"""Demand-loaded compatibility exports with original object identities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from infinity_context_core.application._compatibility_exports import EXPORTS as _EXPORTS
from infinity_context_core.shared_kernel.lazy_exports import resolve_lazy_export

if TYPE_CHECKING:
    import infinity_context_core.features.context_building.public as context_building_public
    import infinity_context_core.features.document_ingestion.public as document_ingestion_public
    import infinity_context_core.features.memory_facts.public as memory_facts_public
    import infinity_context_core.features.memory_scopes.public as memory_scopes_public
    from infinity_context_core.application.context_collectors import (
        ContextRetrievalDeadlines as ContextRetrievalDeadlines,
    )
    from infinity_context_core.application.dto import (
        AnchorBackfillSourceSummary as AnchorBackfillSourceSummary,
    )
    from infinity_context_core.application.dto import (
        AnchorMergeCandidate as AnchorMergeCandidate,
    )
    from infinity_context_core.application.dto import (
        AnchorMergeSuggestionsQuery as AnchorMergeSuggestionsQuery,
    )
    from infinity_context_core.application.dto import (
        AnchorMergeSuggestionsResult as AnchorMergeSuggestionsResult,
    )
    from infinity_context_core.application.dto import (
        AnchorRelationItem as AnchorRelationItem,
    )
    from infinity_context_core.application.dto import (
        AnchorRelationsResult as AnchorRelationsResult,
    )
    from infinity_context_core.application.dto import (
        AnchorResult as AnchorResult,
    )
    from infinity_context_core.application.dto import (
        AnchorsResult as AnchorsResult,
    )
    from infinity_context_core.application.dto import (
        ApproveSuggestionCommand as ApproveSuggestionCommand,
    )
    from infinity_context_core.application.dto import (
        AssetExtractionResult as AssetExtractionResult,
    )
    from infinity_context_core.application.dto import (
        AssetExtractionsResult as AssetExtractionsResult,
    )
    from infinity_context_core.application.dto import (
        AssetResult as AssetResult,
    )
    from infinity_context_core.application.dto import (
        BackfillAnchorsCommand as BackfillAnchorsCommand,
    )
    from infinity_context_core.application.dto import (
        BackfillAnchorsResult as BackfillAnchorsResult,
    )
    from infinity_context_core.application.dto import (
        BuildContextQuery as BuildContextQuery,
    )
    from infinity_context_core.application.dto import (
        BuildMemoryDigestQuery as BuildMemoryDigestQuery,
    )
    from infinity_context_core.application.dto import (
        BuildMemoryInsightsQuery as BuildMemoryInsightsQuery,
    )
    from infinity_context_core.application.dto import (
        CancelAssetExtractionCommand as CancelAssetExtractionCommand,
    )
    from infinity_context_core.application.dto import (
        CaptureResult as CaptureResult,
    )
    from infinity_context_core.application.dto import (
        CheckSpaceAccessQuery as CheckSpaceAccessQuery,
    )
    from infinity_context_core.application.dto import (
        ConsistencyMode as ConsistencyMode,
    )
    from infinity_context_core.application.dto import (
        ConsolidateCaptureCommand as ConsolidateCaptureCommand,
    )
    from infinity_context_core.application.dto import (
        ContextBundle as ContextBundle,
    )
    from infinity_context_core.application.dto import (
        ContextItem as ContextItem,
    )
    from infinity_context_core.application.dto import (
        ContextLinkCandidate as ContextLinkCandidate,
    )
    from infinity_context_core.application.dto import (
        ContextLinkResult as ContextLinkResult,
    )
    from infinity_context_core.application.dto import (
        ContextLinkSuggestionResult as ContextLinkSuggestionResult,
    )
    from infinity_context_core.application.dto import (
        ContextLinkSuggestionsResult as ContextLinkSuggestionsResult,
    )
    from infinity_context_core.application.dto import (
        ContextLinkSuggestionVisibleFilter as ContextLinkSuggestionVisibleFilter,
    )
    from infinity_context_core.application.dto import (
        CreateAnchorCommand as CreateAnchorCommand,
    )
    from infinity_context_core.application.dto import (
        CreateAssetCommand as CreateAssetCommand,
    )
    from infinity_context_core.application.dto import (
        CreateContextLinkCommand as CreateContextLinkCommand,
    )
    from infinity_context_core.application.dto import (
        CreateMemoryScopeCommand as CreateMemoryScopeCommand,
    )
    from infinity_context_core.application.dto import (
        CreateSpaceCommand as CreateSpaceCommand,
    )
    from infinity_context_core.application.dto import (
        CreateSpaceMembershipCommand as CreateSpaceMembershipCommand,
    )
    from infinity_context_core.application.dto import (
        CreateSuggestionBatchItemResult as CreateSuggestionBatchItemResult,
    )
    from infinity_context_core.application.dto import (
        CreateSuggestionCommand as CreateSuggestionCommand,
    )
    from infinity_context_core.application.dto import (
        CreateSuggestionsBatchCommand as CreateSuggestionsBatchCommand,
    )
    from infinity_context_core.application.dto import (
        CreateSuggestionsBatchResult as CreateSuggestionsBatchResult,
    )
    from infinity_context_core.application.dto import (
        CreateUserCommand as CreateUserCommand,
    )
    from infinity_context_core.application.dto import (
        DeleteAnchorCommand as DeleteAnchorCommand,
    )
    from infinity_context_core.application.dto import (
        DeleteAssetCommand as DeleteAssetCommand,
    )
    from infinity_context_core.application.dto import (
        DeleteContextLinkCommand as DeleteContextLinkCommand,
    )
    from infinity_context_core.application.dto import (
        DeleteDocumentCommand as DeleteDocumentCommand,
    )
    from infinity_context_core.application.dto import (
        DeleteDocumentResult as DeleteDocumentResult,
    )
    from infinity_context_core.application.dto import (
        DeleteMemoryScopeCommand as DeleteMemoryScopeCommand,
    )
    from infinity_context_core.application.dto import (
        DeleteThreadMemoryCommand as DeleteThreadMemoryCommand,
    )
    from infinity_context_core.application.dto import (
        DeleteThreadMemoryResult as DeleteThreadMemoryResult,
    )
    from infinity_context_core.application.dto import (
        DocumentChunksQueryResult as DocumentChunksQueryResult,
    )
    from infinity_context_core.application.dto import (
        DocumentQueryResult as DocumentQueryResult,
    )
    from infinity_context_core.application.dto import (
        DocumentsQueryResult as DocumentsQueryResult,
    )
    from infinity_context_core.application.dto import (
        EnsureScopeCommand as EnsureScopeCommand,
    )
    from infinity_context_core.application.dto import (
        ExpireSuggestionCommand as ExpireSuggestionCommand,
    )
    from infinity_context_core.application.dto import (
        ExportGraphQuery as ExportGraphQuery,
    )
    from infinity_context_core.application.dto import (
        ExtractionArtifactBytesResult as ExtractionArtifactBytesResult,
    )
    from infinity_context_core.application.dto import (
        FactQueryResult as FactQueryResult,
    )
    from infinity_context_core.application.dto import (
        FactRelationItem as FactRelationItem,
    )
    from infinity_context_core.application.dto import (
        FactRelationResult as FactRelationResult,
    )
    from infinity_context_core.application.dto import (
        FactRelationsResult as FactRelationsResult,
    )
    from infinity_context_core.application.dto import (
        FactResult as FactResult,
    )
    from infinity_context_core.application.dto import (
        FactsQueryResult as FactsQueryResult,
    )
    from infinity_context_core.application.dto import (
        FactVersionsQuery as FactVersionsQuery,
    )
    from infinity_context_core.application.dto import (
        ForgetFactCommand as ForgetFactCommand,
    )
    from infinity_context_core.application.dto import (
        GetAssetExtractionQuery as GetAssetExtractionQuery,
    )
    from infinity_context_core.application.dto import (
        GetAssetQuery as GetAssetQuery,
    )
    from infinity_context_core.application.dto import (
        GetCaptureQuery as GetCaptureQuery,
    )
    from infinity_context_core.application.dto import (
        GetDocumentQuery as GetDocumentQuery,
    )
    from infinity_context_core.application.dto import (
        GetExtractionArtifactQuery as GetExtractionArtifactQuery,
    )
    from infinity_context_core.application.dto import (
        GetFactQuery as GetFactQuery,
    )
    from infinity_context_core.application.dto import (
        GetSessionStatusQuery as GetSessionStatusQuery,
    )
    from infinity_context_core.application.dto import (
        GraphExportEdge as GraphExportEdge,
    )
    from infinity_context_core.application.dto import (
        GraphExportNode as GraphExportNode,
    )
    from infinity_context_core.application.dto import (
        GraphExportResult as GraphExportResult,
    )
    from infinity_context_core.application.dto import (
        IngestDocumentCommand as IngestDocumentCommand,
    )
    from infinity_context_core.application.dto import (
        IngestDocumentResult as IngestDocumentResult,
    )
    from infinity_context_core.application.dto import (
        IngestEpisodeCommand as IngestEpisodeCommand,
    )
    from infinity_context_core.application.dto import (
        IngestEpisodeResult as IngestEpisodeResult,
    )
    from infinity_context_core.application.dto import (
        LinkFactsCommand as LinkFactsCommand,
    )
    from infinity_context_core.application.dto import (
        ListAnchorRelationsQuery as ListAnchorRelationsQuery,
    )
    from infinity_context_core.application.dto import (
        ListAnchorsQuery as ListAnchorsQuery,
    )
    from infinity_context_core.application.dto import (
        ListAssetExtractionsQuery as ListAssetExtractionsQuery,
    )
    from infinity_context_core.application.dto import (
        ListAssetsQuery as ListAssetsQuery,
    )
    from infinity_context_core.application.dto import (
        ListCapturesQuery as ListCapturesQuery,
    )
    from infinity_context_core.application.dto import (
        ListContextLinksQuery as ListContextLinksQuery,
    )
    from infinity_context_core.application.dto import (
        ListContextLinkSuggestionsQuery as ListContextLinkSuggestionsQuery,
    )
    from infinity_context_core.application.dto import (
        ListDocumentChunksQuery as ListDocumentChunksQuery,
    )
    from infinity_context_core.application.dto import (
        ListDocumentsQuery as ListDocumentsQuery,
    )
    from infinity_context_core.application.dto import (
        ListFactRelationsQuery as ListFactRelationsQuery,
    )
    from infinity_context_core.application.dto import (
        ListFactsQuery as ListFactsQuery,
    )
    from infinity_context_core.application.dto import (
        ListSpaceMembershipsQuery as ListSpaceMembershipsQuery,
    )
    from infinity_context_core.application.dto import (
        ListSuggestionsQuery as ListSuggestionsQuery,
    )
    from infinity_context_core.application.dto import (
        ListUsersQuery as ListUsersQuery,
    )
    from infinity_context_core.application.dto import (
        MemoryActivityItem as MemoryActivityItem,
    )
    from infinity_context_core.application.dto import (
        MemoryBrowserQuery as MemoryBrowserQuery,
    )
    from infinity_context_core.application.dto import (
        MemoryBrowserResult as MemoryBrowserResult,
    )
    from infinity_context_core.application.dto import (
        MemoryConsolidationPlanItem as MemoryConsolidationPlanItem,
    )
    from infinity_context_core.application.dto import (
        MemoryDigest as MemoryDigest,
    )
    from infinity_context_core.application.dto import (
        MemoryDigestSection as MemoryDigestSection,
    )
    from infinity_context_core.application.dto import (
        MemoryInsightActionItem as MemoryInsightActionItem,
    )
    from infinity_context_core.application.dto import (
        MemoryInsightsResult as MemoryInsightsResult,
    )
    from infinity_context_core.application.dto import (
        MemoryOperationsConsoleQuery as MemoryOperationsConsoleQuery,
    )
    from infinity_context_core.application.dto import (
        MemoryOperationsConsoleResult as MemoryOperationsConsoleResult,
    )
    from infinity_context_core.application.dto import (
        MemoryScopeResult as MemoryScopeResult,
    )
    from infinity_context_core.application.dto import (
        MergeAnchorsCommand as MergeAnchorsCommand,
    )
    from infinity_context_core.application.dto import (
        ProcessDocumentCommand as ProcessDocumentCommand,
    )
    from infinity_context_core.application.dto import (
        ProcessDocumentResult as ProcessDocumentResult,
    )
    from infinity_context_core.application.dto import (
        PurgeCaptureCommand as PurgeCaptureCommand,
    )
    from infinity_context_core.application.dto import (
        ReceiveCaptureCommand as ReceiveCaptureCommand,
    )
    from infinity_context_core.application.dto import (
        RejectSuggestionCommand as RejectSuggestionCommand,
    )
    from infinity_context_core.application.dto import (
        RelatedFactItem as RelatedFactItem,
    )
    from infinity_context_core.application.dto import (
        RelatedFactsQuery as RelatedFactsQuery,
    )
    from infinity_context_core.application.dto import (
        RelatedFactsResult as RelatedFactsResult,
    )
    from infinity_context_core.application.dto import (
        RememberFactCommand as RememberFactCommand,
    )
    from infinity_context_core.application.dto import (
        RequestAssetExtractionCommand as RequestAssetExtractionCommand,
    )
    from infinity_context_core.application.dto import (
        ResolveDuplicateMergeCommand as ResolveDuplicateMergeCommand,
    )
    from infinity_context_core.application.dto import (
        ResolveSuggestionConflictCommand as ResolveSuggestionConflictCommand,
    )
    from infinity_context_core.application.dto import (
        RetryAssetExtractionCommand as RetryAssetExtractionCommand,
    )
    from infinity_context_core.application.dto import (
        ReviewContextLinkSuggestionBatchItemCommand as ReviewContextLinkSuggestionBatchItemCommand,
    )
    from infinity_context_core.application.dto import (
        ReviewContextLinkSuggestionBatchItemResult as ReviewContextLinkSuggestionBatchItemResult,
    )
    from infinity_context_core.application.dto import (
        ReviewContextLinkSuggestionCommand as ReviewContextLinkSuggestionCommand,
    )
    from infinity_context_core.application.dto import (
        ReviewContextLinkSuggestionsBatchCommand as ReviewContextLinkSuggestionsBatchCommand,
    )
    from infinity_context_core.application.dto import (
        ReviewContextLinkSuggestionsBatchResult as ReviewContextLinkSuggestionsBatchResult,
    )
    from infinity_context_core.application.dto import (
        ReviewSuggestionBatchItemCommand as ReviewSuggestionBatchItemCommand,
    )
    from infinity_context_core.application.dto import (
        ReviewSuggestionBatchItemResult as ReviewSuggestionBatchItemResult,
    )
    from infinity_context_core.application.dto import (
        ReviewSuggestionsBatchCommand as ReviewSuggestionsBatchCommand,
    )
    from infinity_context_core.application.dto import (
        ReviewSuggestionsBatchResult as ReviewSuggestionsBatchResult,
    )
    from infinity_context_core.application.dto import (
        RunAssetExtractionCommand as RunAssetExtractionCommand,
    )
    from infinity_context_core.application.dto import (
        ScopeResult as ScopeResult,
    )
    from infinity_context_core.application.dto import (
        SessionStatusResult as SessionStatusResult,
    )
    from infinity_context_core.application.dto import (
        SpaceAccessResult as SpaceAccessResult,
    )
    from infinity_context_core.application.dto import (
        SpaceMembershipResult as SpaceMembershipResult,
    )
    from infinity_context_core.application.dto import (
        SpaceMembershipsResult as SpaceMembershipsResult,
    )
    from infinity_context_core.application.dto import (
        SpaceResult as SpaceResult,
    )
    from infinity_context_core.application.dto import (
        SplitAnchorCommand as SplitAnchorCommand,
    )
    from infinity_context_core.application.dto import (
        SuggestContextLinksCommand as SuggestContextLinksCommand,
    )
    from infinity_context_core.application.dto import (
        SuggestionResult as SuggestionResult,
    )
    from infinity_context_core.application.dto import (
        UnlinkFactRelationCommand as UnlinkFactRelationCommand,
    )
    from infinity_context_core.application.dto import (
        UpdateAnchorCommand as UpdateAnchorCommand,
    )
    from infinity_context_core.application.dto import (
        UpdateContextLinkCommand as UpdateContextLinkCommand,
    )
    from infinity_context_core.application.dto import (
        UpdateFactCommand as UpdateFactCommand,
    )
    from infinity_context_core.application.dto import (
        UpdateMemoryScopeCommand as UpdateMemoryScopeCommand,
    )
    from infinity_context_core.application.dto import (
        UsageSummaryQuery as UsageSummaryQuery,
    )
    from infinity_context_core.application.dto import (
        UsageSummaryResult as UsageSummaryResult,
    )
    from infinity_context_core.application.dto import (
        UserResult as UserResult,
    )
    from infinity_context_core.application.dto import (
        UsersResult as UsersResult,
    )
    from infinity_context_core.application.dto_benchmark_runs import (
        CleanupBenchmarkRunCommand as CleanupBenchmarkRunCommand,
    )
    from infinity_context_core.application.dto_benchmark_runs import (
        CleanupBenchmarkRunResult as CleanupBenchmarkRunResult,
    )
    from infinity_context_core.application.dto_benchmark_runs import (
        FinalizeBenchmarkRunCleanupCommand as FinalizeBenchmarkRunCleanupCommand,
    )
    from infinity_context_core.application.dto_benchmark_runs import (
        FinalizeBenchmarkRunCleanupResult as FinalizeBenchmarkRunCleanupResult,
    )
    from infinity_context_core.application.dto_benchmark_runs import (
        FinalizeUnsealedBenchmarkAbortCommand as FinalizeUnsealedBenchmarkAbortCommand,
    )
    from infinity_context_core.application.dto_benchmark_runs import (
        FinalizeUnsealedBenchmarkAbortResult as FinalizeUnsealedBenchmarkAbortResult,
    )
    from infinity_context_core.application.dto_benchmark_runs import (
        GetBenchmarkRunLifecycleQuery as GetBenchmarkRunLifecycleQuery,
    )
    from infinity_context_core.application.dto_benchmark_runs import (
        GetBenchmarkRunLifecycleResult as GetBenchmarkRunLifecycleResult,
    )
    from infinity_context_core.application.dto_benchmark_runs import (
        RegisterBenchmarkRunCommand as RegisterBenchmarkRunCommand,
    )
    from infinity_context_core.application.dto_benchmark_runs import (
        RegisterBenchmarkRunResult as RegisterBenchmarkRunResult,
    )
    from infinity_context_core.application.dto_benchmark_runs import (
        SealProjectionManifestCommand as SealProjectionManifestCommand,
    )
    from infinity_context_core.application.dto_benchmark_runs import (
        SealProjectionManifestResult as SealProjectionManifestResult,
    )
    from infinity_context_core.application.use_cases.anchors import (
        BackfillAnchorsUseCase as BackfillAnchorsUseCase,
    )
    from infinity_context_core.application.use_cases.anchors import (
        CreateAnchorUseCase as CreateAnchorUseCase,
    )
    from infinity_context_core.application.use_cases.anchors import (
        DeleteAnchorUseCase as DeleteAnchorUseCase,
    )
    from infinity_context_core.application.use_cases.anchors import (
        ListAnchorRelationsUseCase as ListAnchorRelationsUseCase,
    )
    from infinity_context_core.application.use_cases.anchors import (
        ListAnchorsUseCase as ListAnchorsUseCase,
    )
    from infinity_context_core.application.use_cases.anchors import (
        MergeAnchorsUseCase as MergeAnchorsUseCase,
    )
    from infinity_context_core.application.use_cases.anchors import (
        SplitAnchorUseCase as SplitAnchorUseCase,
    )
    from infinity_context_core.application.use_cases.anchors import (
        SuggestAnchorMergesUseCase as SuggestAnchorMergesUseCase,
    )
    from infinity_context_core.application.use_cases.anchors import (
        UpdateAnchorUseCase as UpdateAnchorUseCase,
    )
    from infinity_context_core.application.use_cases.asset_extractions import (
        CancelAssetExtractionUseCase as CancelAssetExtractionUseCase,
    )
    from infinity_context_core.application.use_cases.asset_extractions import (
        GetAssetExtractionUseCase as GetAssetExtractionUseCase,
    )
    from infinity_context_core.application.use_cases.asset_extractions import (
        ListAssetExtractionsUseCase as ListAssetExtractionsUseCase,
    )
    from infinity_context_core.application.use_cases.asset_extractions import (
        ReadExtractionArtifactBytesUseCase as ReadExtractionArtifactBytesUseCase,
    )
    from infinity_context_core.application.use_cases.asset_extractions import (
        RequestAssetExtractionUseCase as RequestAssetExtractionUseCase,
    )
    from infinity_context_core.application.use_cases.asset_extractions import (
        RetryAssetExtractionUseCase as RetryAssetExtractionUseCase,
    )
    from infinity_context_core.application.use_cases.asset_extractions import (
        RunAssetExtractionUseCase as RunAssetExtractionUseCase,
    )
    from infinity_context_core.application.use_cases.assets import (
        CreateAssetUseCase as CreateAssetUseCase,
    )
    from infinity_context_core.application.use_cases.assets import (
        DeleteAssetUseCase as DeleteAssetUseCase,
    )
    from infinity_context_core.application.use_cases.assets import (
        GetAssetUseCase as GetAssetUseCase,
    )
    from infinity_context_core.application.use_cases.assets import (
        ListAssetsUseCase as ListAssetsUseCase,
    )
    from infinity_context_core.application.use_cases.assets import (
        ReadAssetBytesUseCase as ReadAssetBytesUseCase,
    )
    from infinity_context_core.application.use_cases.benchmark_runs import (
        BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256 as _benchmark_policy_sha,
    )
    from infinity_context_core.application.use_cases.benchmark_runs import (
        CleanupBenchmarkRunUseCase as CleanupBenchmarkRunUseCase,
    )
    from infinity_context_core.application.use_cases.benchmark_runs import (
        FinalizeBenchmarkRunCleanupUseCase as FinalizeBenchmarkRunCleanupUseCase,
    )
    from infinity_context_core.application.use_cases.benchmark_runs import (
        GetBenchmarkRunLifecycleUseCase as GetBenchmarkRunLifecycleUseCase,
    )
    from infinity_context_core.application.use_cases.benchmark_runs import (
        RegisterBenchmarkRunUseCase as RegisterBenchmarkRunUseCase,
    )
    from infinity_context_core.application.use_cases.benchmark_runs import (
        SealProjectionManifestUseCase as SealProjectionManifestUseCase,
    )
    from infinity_context_core.application.use_cases.benchmark_runs import (
        validate_projection_manifest as validate_projection_manifest,
    )
    from infinity_context_core.application.use_cases.benchmark_unsealed_abort import (
        FinalizeUnsealedBenchmarkAbortUseCase as FinalizeUnsealedBenchmarkAbortUseCase,
    )
    from infinity_context_core.application.use_cases.blob_storage_cleanup import (
        BlobStorageCleanupCommand as BlobStorageCleanupCommand,
    )
    from infinity_context_core.application.use_cases.blob_storage_cleanup import (
        BlobStorageCleanupDecision as BlobStorageCleanupDecision,
    )
    from infinity_context_core.application.use_cases.blob_storage_cleanup import (
        BlobStorageCleanupResult as BlobStorageCleanupResult,
    )
    from infinity_context_core.application.use_cases.blob_storage_cleanup import (
        RunBlobStorageCleanupUseCase as RunBlobStorageCleanupUseCase,
    )
    from infinity_context_core.application.use_cases.blob_storage_integrity import (
        BlobStorageIntegrityAuditCommand as BlobStorageIntegrityAuditCommand,
    )
    from infinity_context_core.application.use_cases.blob_storage_integrity import (
        BlobStorageIntegrityAuditResult as BlobStorageIntegrityAuditResult,
    )
    from infinity_context_core.application.use_cases.blob_storage_integrity import (
        BlobStorageIntegrityIssue as BlobStorageIntegrityIssue,
    )
    from infinity_context_core.application.use_cases.blob_storage_integrity import (
        RunBlobStorageIntegrityAuditUseCase as RunBlobStorageIntegrityAuditUseCase,
    )
    from infinity_context_core.application.use_cases.build_context import (
        BuildContextUseCase as BuildContextUseCase,
    )
    from infinity_context_core.application.use_cases.build_memory_digest import (
        BuildMemoryDigestUseCase as BuildMemoryDigestUseCase,
    )
    from infinity_context_core.application.use_cases.build_memory_insights import (
        BuildMemoryInsightsUseCase as BuildMemoryInsightsUseCase,
    )
    from infinity_context_core.application.use_cases.consolidate_capture import (
        ConsolidateCaptureUseCase as ConsolidateCaptureUseCase,
    )
    from infinity_context_core.application.use_cases.context_links import (
        CreateContextLinkUseCase as CreateContextLinkUseCase,
    )
    from infinity_context_core.application.use_cases.context_links import (
        DeleteContextLinkUseCase as DeleteContextLinkUseCase,
    )
    from infinity_context_core.application.use_cases.context_links import (
        ListContextLinkSuggestionsUseCase as ListContextLinkSuggestionsUseCase,
    )
    from infinity_context_core.application.use_cases.context_links import (
        ListContextLinksUseCase as ListContextLinksUseCase,
    )
    from infinity_context_core.application.use_cases.context_links import (
        ReviewContextLinkSuggestionsBatchUseCase as ReviewContextLinkSuggestionsBatchUseCase,
    )
    from infinity_context_core.application.use_cases.context_links import (
        ReviewContextLinkSuggestionUseCase as ReviewContextLinkSuggestionUseCase,
    )
    from infinity_context_core.application.use_cases.context_links import (
        SuggestContextLinksUseCase as SuggestContextLinksUseCase,
    )
    from infinity_context_core.application.use_cases.context_links import (
        UpdateContextLinkUseCase as UpdateContextLinkUseCase,
    )
    from infinity_context_core.application.use_cases.delete_document import (
        DeleteDocumentUseCase as DeleteDocumentUseCase,
    )
    from infinity_context_core.application.use_cases.delete_thread_memory import (
        DeleteThreadMemoryUseCase as DeleteThreadMemoryUseCase,
    )
    from infinity_context_core.application.use_cases.duplicate_merge_resolution import (
        ResolveDuplicateMergeUseCase as ResolveDuplicateMergeUseCase,
    )
    from infinity_context_core.application.use_cases.ensure_scope import (
        EnsureScopeUseCase as EnsureScopeUseCase,
    )
    from infinity_context_core.application.use_cases.expire_suggestions import (
        ExpirePendingSuggestionsResult as ExpirePendingSuggestionsResult,
    )
    from infinity_context_core.application.use_cases.expire_suggestions import (
        ExpirePendingSuggestionsUseCase as ExpirePendingSuggestionsUseCase,
    )
    from infinity_context_core.application.use_cases.export_graph import (
        ExportGraphUseCase as ExportGraphUseCase,
    )
    from infinity_context_core.application.use_cases.fact_relations import (
        LinkFactsUseCase as LinkFactsUseCase,
    )
    from infinity_context_core.application.use_cases.fact_relations import (
        ListFactRelationsUseCase as ListFactRelationsUseCase,
    )
    from infinity_context_core.application.use_cases.fact_relations import (
        UnlinkFactRelationUseCase as UnlinkFactRelationUseCase,
    )
    from infinity_context_core.application.use_cases.forget_fact import (
        ForgetFactUseCase as ForgetFactUseCase,
    )
    from infinity_context_core.application.use_cases.get_capabilities import (
        CapabilitiesResult as CapabilitiesResult,
    )
    from infinity_context_core.application.use_cases.get_capabilities import (
        GetCapabilitiesUseCase as GetCapabilitiesUseCase,
    )
    from infinity_context_core.application.use_cases.get_capture import (
        GetCaptureUseCase as GetCaptureUseCase,
    )
    from infinity_context_core.application.use_cases.get_session_status import (
        GetSessionStatusUseCase as GetSessionStatusUseCase,
    )
    from infinity_context_core.application.use_cases.ingest_document import (
        IngestDocumentUseCase as IngestDocumentUseCase,
    )
    from infinity_context_core.application.use_cases.ingest_episode import (
        IngestEpisodeUseCase as IngestEpisodeUseCase,
    )
    from infinity_context_core.application.use_cases.list_captures import (
        ListCapturesUseCase as ListCapturesUseCase,
    )
    from infinity_context_core.application.use_cases.memory_browser import (
        BuildMemoryBrowserUseCase as BuildMemoryBrowserUseCase,
    )
    from infinity_context_core.application.use_cases.operations_console import (
        BuildMemoryOperationsConsoleUseCase as BuildMemoryOperationsConsoleUseCase,
    )
    from infinity_context_core.application.use_cases.process_document import (
        ProcessDocumentUseCase as ProcessDocumentUseCase,
    )
    from infinity_context_core.application.use_cases.purge_capture import (
        PurgeCaptureUseCase as PurgeCaptureUseCase,
    )
    from infinity_context_core.application.use_cases.query_documents import (
        GetDocumentUseCase as GetDocumentUseCase,
    )
    from infinity_context_core.application.use_cases.query_documents import (
        ListDocumentChunksUseCase as ListDocumentChunksUseCase,
    )
    from infinity_context_core.application.use_cases.query_documents import (
        ListDocumentsUseCase as ListDocumentsUseCase,
    )
    from infinity_context_core.application.use_cases.query_facts import (
        GetFactUseCase as GetFactUseCase,
    )
    from infinity_context_core.application.use_cases.query_facts import (
        ListFactsUseCase as ListFactsUseCase,
    )
    from infinity_context_core.application.use_cases.query_facts import (
        ListFactVersionsUseCase as ListFactVersionsUseCase,
    )
    from infinity_context_core.application.use_cases.receive_capture import (
        ReceiveCaptureUseCase as ReceiveCaptureUseCase,
    )
    from infinity_context_core.application.use_cases.related_facts import (
        RelatedFactsUseCase as RelatedFactsUseCase,
    )
    from infinity_context_core.application.use_cases.remember_fact import (
        RememberFactUseCase as RememberFactUseCase,
    )
    from infinity_context_core.application.use_cases.spaces_memory_scopes import (
        CreateMemoryScopeUseCase as CreateMemoryScopeUseCase,
    )
    from infinity_context_core.application.use_cases.spaces_memory_scopes import (
        CreateSpaceUseCase as CreateSpaceUseCase,
    )
    from infinity_context_core.application.use_cases.spaces_memory_scopes import (
        DeleteMemoryScopeUseCase as DeleteMemoryScopeUseCase,
    )
    from infinity_context_core.application.use_cases.spaces_memory_scopes import (
        ListMemoryScopesUseCase as ListMemoryScopesUseCase,
    )
    from infinity_context_core.application.use_cases.spaces_memory_scopes import (
        ListSpacesUseCase as ListSpacesUseCase,
    )
    from infinity_context_core.application.use_cases.spaces_memory_scopes import (
        UpdateMemoryScopeUseCase as UpdateMemoryScopeUseCase,
    )
    from infinity_context_core.application.use_cases.suggestions import (
        ApproveSuggestionUseCase as ApproveSuggestionUseCase,
    )
    from infinity_context_core.application.use_cases.suggestions import (
        CreateSuggestionsBatchUseCase as CreateSuggestionsBatchUseCase,
    )
    from infinity_context_core.application.use_cases.suggestions import (
        CreateSuggestionUseCase as CreateSuggestionUseCase,
    )
    from infinity_context_core.application.use_cases.suggestions import (
        ExpireSuggestionUseCase as ExpireSuggestionUseCase,
    )
    from infinity_context_core.application.use_cases.suggestions import (
        ListSuggestionsUseCase as ListSuggestionsUseCase,
    )
    from infinity_context_core.application.use_cases.suggestions import (
        RejectSuggestionUseCase as RejectSuggestionUseCase,
    )
    from infinity_context_core.application.use_cases.suggestions import (
        ResolveSuggestionConflictUseCase as ResolveSuggestionConflictUseCase,
    )
    from infinity_context_core.application.use_cases.suggestions import (
        ReviewSuggestionsBatchUseCase as ReviewSuggestionsBatchUseCase,
    )
    from infinity_context_core.application.use_cases.update_fact import (
        UpdateFactUseCase as UpdateFactUseCase,
    )
    from infinity_context_core.application.use_cases.usage import (
        GetUsageSummaryUseCase as GetUsageSummaryUseCase,
    )
    from infinity_context_core.application.use_cases.users import (
        CheckSpaceAccessUseCase as CheckSpaceAccessUseCase,
    )
    from infinity_context_core.application.use_cases.users import (
        CreateSpaceMembershipUseCase as CreateSpaceMembershipUseCase,
    )
    from infinity_context_core.application.use_cases.users import (
        CreateUserUseCase as CreateUserUseCase,
    )
    from infinity_context_core.application.use_cases.users import (
        ListSpaceMembershipsUseCase as ListSpaceMembershipsUseCase,
    )
    from infinity_context_core.application.use_cases.users import (
        ListUsersUseCase as ListUsersUseCase,
    )

    BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256 = _benchmark_policy_sha
    ContextBuildingUseCases = context_building_public.ContextBuildingUseCases
    DocumentIngestionUseCases = document_ingestion_public.DocumentIngestionUseCases
    MemoryFactLifecycleUseCases = memory_facts_public.MemoryFactLifecycleUseCases
    MemoryScopeUseCases = memory_scopes_public.MemoryScopeUseCases

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> object:
    return resolve_lazy_export(name, _EXPORTS, globals(), __name__)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

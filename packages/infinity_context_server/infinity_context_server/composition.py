"""Composition root for infinity_context_server."""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from infinity_context_adapters.extraction import SimpleFileTypeDetector, build_standard_extractor
from infinity_context_adapters.local_blob import LocalBlobStorage
from infinity_context_adapters.noop import (
    NoopEmbeddingAdapter,
    NoopGraphMemoryAdapter,
    NoopVectorMemoryAdapter,
    SystemClock,
    UuidIdGenerator,
)
from infinity_context_adapters.postgres import (
    PostgresUnitOfWorkFactory,
    build_async_engine,
    build_session_factory,
)
from infinity_context_adapters.s3_blob import S3BlobStorage
from infinity_context_core.application import (
    ApproveSuggestionUseCase,
    BackfillAnchorsUseCase,
    BuildContextUseCase,
    BuildMemoryBrowserUseCase,
    BuildMemoryDigestUseCase,
    BuildMemoryInsightsUseCase,
    BuildMemoryOperationsConsoleUseCase,
    CancelAssetExtractionUseCase,
    CheckSpaceAccessUseCase,
    ConsolidateCaptureUseCase,
    CreateAnchorUseCase,
    CreateAssetUseCase,
    CreateContextLinkUseCase,
    CreateMemoryScopeUseCase,
    CreateSpaceMembershipUseCase,
    CreateSpaceUseCase,
    CreateSuggestionsBatchUseCase,
    CreateSuggestionUseCase,
    CreateUserUseCase,
    DeleteAnchorUseCase,
    DeleteAssetUseCase,
    DeleteContextLinkUseCase,
    DeleteDocumentUseCase,
    DeleteMemoryScopeUseCase,
    DeleteThreadMemoryUseCase,
    EnsureScopeUseCase,
    ExpirePendingSuggestionsUseCase,
    ExpireSuggestionUseCase,
    ExportGraphUseCase,
    ForgetFactUseCase,
    GetAssetExtractionUseCase,
    GetAssetUseCase,
    GetCapabilitiesUseCase,
    GetCaptureUseCase,
    GetDocumentUseCase,
    GetFactUseCase,
    GetSessionStatusUseCase,
    GetUsageSummaryUseCase,
    IngestDocumentUseCase,
    IngestEpisodeUseCase,
    LinkFactsUseCase,
    ListAnchorRelationsUseCase,
    ListAnchorsUseCase,
    ListAssetExtractionsUseCase,
    ListAssetsUseCase,
    ListCapturesUseCase,
    ListContextLinkSuggestionsUseCase,
    ListContextLinksUseCase,
    ListDocumentChunksUseCase,
    ListFactRelationsUseCase,
    ListFactsUseCase,
    ListFactVersionsUseCase,
    ListMemoryScopesUseCase,
    ListSpaceMembershipsUseCase,
    ListSpacesUseCase,
    ListSuggestionsUseCase,
    ListUsersUseCase,
    MergeAnchorsUseCase,
    ProcessDocumentUseCase,
    PurgeCaptureUseCase,
    ReadAssetBytesUseCase,
    ReadExtractionArtifactBytesUseCase,
    ReceiveCaptureUseCase,
    RejectSuggestionUseCase,
    RelatedFactsUseCase,
    RememberFactUseCase,
    RequestAssetExtractionUseCase,
    ResolveDuplicateMergeUseCase,
    ResolveSuggestionConflictUseCase,
    RetryAssetExtractionUseCase,
    ReviewContextLinkSuggestionsBatchUseCase,
    ReviewContextLinkSuggestionUseCase,
    ReviewSuggestionsBatchUseCase,
    RunAssetExtractionUseCase,
    RunBlobStorageCleanupUseCase,
    RunBlobStorageIntegrityAuditUseCase,
    SplitAnchorUseCase,
    SuggestAnchorMergesUseCase,
    SuggestContextLinksUseCase,
    UnlinkFactRelationUseCase,
    UpdateAnchorUseCase,
    UpdateContextLinkUseCase,
    UpdateFactUseCase,
    UpdateMemoryScopeUseCase,
)
from infinity_context_core.application.auto_memory import RuleBasedMemoryClassifier
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.extractor import (
    NoopMemoryExtractor,
    RuleBasedMemoryExtractor,
)
from infinity_context_core.domain.usage import ProductPlan
from infinity_context_core.ports.adapters import (
    EmbeddingPort,
    GraphMemoryPort,
    MemoryAdapterPort,
    VectorMemoryPort,
)
from infinity_context_core.ports.assets import BlobStorageMaintenancePort
from infinity_context_core.ports.auto_memory import MemoryExtractorPort
from infinity_context_core.ports.capabilities import DocumentMemoryPort
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.extraction import ExtractionLimits
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort
from sqlalchemy.ext.asyncio import AsyncEngine

from infinity_context_server.config import CaptureMode, MemoryPolicyMode, Settings
from infinity_context_server.metrics import RuntimeMetrics
from infinity_context_server.provider_budget import QueryEmbeddingBudgetAdapter
from infinity_context_server.provider_circuit import (
    CircuitBreakingEmbeddingAdapter,
    CircuitBreakingGraphMemoryAdapter,
    CircuitBreakingVectorMemoryAdapter,
    ProviderCircuitBreaker,
)

SUPPORTED_POLICY_MODES = (
    "disabled",
    "manual_only",
    "suggestions",
    "active_context",
)


@dataclass(frozen=True)
class Container:
    settings: Settings
    engine: AsyncEngine
    clock: ClockPort
    ids: IdGeneratorPort
    uow_factory: UnitOfWorkFactoryPort
    adapters: tuple[MemoryAdapterPort, ...]
    cognee_memory: DocumentMemoryPort
    vector_index: VectorMemoryPort
    graph_index: GraphMemoryPort
    embedder: EmbeddingPort
    blob_storage: BlobStorageMaintenancePort
    get_capabilities: GetCapabilitiesUseCase
    create_space: CreateSpaceUseCase
    list_spaces: ListSpacesUseCase
    create_memory_scope: CreateMemoryScopeUseCase
    list_memory_scopes: ListMemoryScopesUseCase
    update_memory_scope: UpdateMemoryScopeUseCase
    delete_memory_scope: DeleteMemoryScopeUseCase
    create_user: CreateUserUseCase
    list_users: ListUsersUseCase
    create_space_membership: CreateSpaceMembershipUseCase
    list_space_memberships: ListSpaceMembershipsUseCase
    check_space_access: CheckSpaceAccessUseCase
    remember_fact: RememberFactUseCase
    list_facts: ListFactsUseCase
    get_fact: GetFactUseCase
    list_fact_versions: ListFactVersionsUseCase
    related_facts: RelatedFactsUseCase
    link_facts: LinkFactsUseCase
    list_fact_relations: ListFactRelationsUseCase
    unlink_fact_relation: UnlinkFactRelationUseCase
    create_asset: CreateAssetUseCase
    get_asset: GetAssetUseCase
    list_assets: ListAssetsUseCase
    delete_asset: DeleteAssetUseCase
    read_asset_bytes: ReadAssetBytesUseCase
    request_asset_extraction: RequestAssetExtractionUseCase
    get_asset_extraction: GetAssetExtractionUseCase
    list_asset_extractions: ListAssetExtractionsUseCase
    read_extraction_artifact_bytes: ReadExtractionArtifactBytesUseCase
    retry_asset_extraction: RetryAssetExtractionUseCase
    cancel_asset_extraction: CancelAssetExtractionUseCase
    run_asset_extraction: RunAssetExtractionUseCase
    create_anchor: CreateAnchorUseCase
    update_anchor: UpdateAnchorUseCase
    delete_anchor: DeleteAnchorUseCase
    list_anchors: ListAnchorsUseCase
    list_anchor_relations: ListAnchorRelationsUseCase
    suggest_anchor_merges: SuggestAnchorMergesUseCase
    merge_anchors: MergeAnchorsUseCase
    split_anchor: SplitAnchorUseCase
    backfill_anchors: BackfillAnchorsUseCase
    suggest_context_links: SuggestContextLinksUseCase
    create_context_link: CreateContextLinkUseCase
    list_context_links: ListContextLinksUseCase
    list_context_link_suggestions: ListContextLinkSuggestionsUseCase
    review_context_link_suggestion: ReviewContextLinkSuggestionUseCase
    review_context_link_suggestions_batch: ReviewContextLinkSuggestionsBatchUseCase
    update_context_link: UpdateContextLinkUseCase
    delete_context_link: DeleteContextLinkUseCase
    update_fact: UpdateFactUseCase
    forget_fact: ForgetFactUseCase
    ensure_scope: EnsureScopeUseCase
    ingest_episode: IngestEpisodeUseCase
    ingest_document: IngestDocumentUseCase
    get_document: GetDocumentUseCase
    list_document_chunks: ListDocumentChunksUseCase
    process_document: ProcessDocumentUseCase
    delete_document: DeleteDocumentUseCase
    build_context: BuildContextUseCase
    build_memory_digest: BuildMemoryDigestUseCase
    build_memory_insights: BuildMemoryInsightsUseCase
    build_memory_browser: BuildMemoryBrowserUseCase
    build_memory_operations_console: BuildMemoryOperationsConsoleUseCase
    export_graph: ExportGraphUseCase
    delete_thread_memory: DeleteThreadMemoryUseCase
    get_session_status: GetSessionStatusUseCase
    get_usage_summary: GetUsageSummaryUseCase
    create_suggestion: CreateSuggestionUseCase
    create_suggestions_batch: CreateSuggestionsBatchUseCase
    list_suggestions: ListSuggestionsUseCase
    approve_suggestion: ApproveSuggestionUseCase
    reject_suggestion: RejectSuggestionUseCase
    expire_suggestion: ExpireSuggestionUseCase
    resolve_duplicate_merge: ResolveDuplicateMergeUseCase
    resolve_suggestion_conflict: ResolveSuggestionConflictUseCase
    review_suggestions_batch: ReviewSuggestionsBatchUseCase
    receive_capture: ReceiveCaptureUseCase
    get_capture: GetCaptureUseCase
    list_captures: ListCapturesUseCase
    purge_capture: PurgeCaptureUseCase
    consolidate_capture: ConsolidateCaptureUseCase
    expire_pending_suggestions: ExpirePendingSuggestionsUseCase
    run_blob_storage_cleanup: RunBlobStorageCleanupUseCase
    run_blob_storage_integrity_audit: RunBlobStorageIntegrityAuditUseCase
    runtime_metrics: RuntimeMetrics
    provider_circuits: tuple[ProviderCircuitBreaker, ...]

    async def aclose(self) -> None:
        closed: set[int] = set()
        for resource in (
            *self.adapters,
            self.cognee_memory,
            self.vector_index,
            self.graph_index,
            self.embedder,
        ):
            resource_id = id(resource)
            if resource_id in closed:
                continue
            closed.add(resource_id)
            await _close_resource(resource)
        await self.engine.dispose()


def build_container(settings: Settings | None = None) -> Container:
    resolved_settings = settings or Settings()
    resolved_settings.validate_for_startup()

    clock = SystemClock()
    ids = UuidIdGenerator()
    engine = build_async_engine(resolved_settings.database_url)
    session_factory = build_session_factory(engine)
    uow_factory = PostgresUnitOfWorkFactory(session_factory=session_factory, clock=clock)

    raw_vector = _build_vector_adapter(resolved_settings)
    raw_graph = _build_graph_adapter(resolved_settings)
    raw_embeddings = _build_embedding_adapter(resolved_settings)
    provider_circuits = (
        _provider_circuit("qdrant", "vector", clock, resolved_settings),
        _provider_circuit("graphiti", "graph", clock, resolved_settings),
        _provider_circuit("embeddings", "embeddings", clock, resolved_settings),
    )
    vector = CircuitBreakingVectorMemoryAdapter(raw_vector, provider_circuits[0])
    graph = CircuitBreakingGraphMemoryAdapter(raw_graph, provider_circuits[1])
    embeddings = CircuitBreakingEmbeddingAdapter(raw_embeddings, provider_circuits[2])
    query_embeddings = QueryEmbeddingBudgetAdapter(
        inner=embeddings,
        clock=clock,
        max_per_minute=resolved_settings.max_query_embeddings_per_minute,
    )
    blob_storage = _build_blob_storage(resolved_settings)
    product_plan = ProductPlan.create(
        tier=resolved_settings.product_plan_tier,
        media_analysis_seconds_per_month=(resolved_settings.plan_media_analysis_seconds_per_month),
    )
    cognee = _build_cognee_adapter(resolved_settings)
    adapters: tuple[MemoryAdapterPort, ...] = (vector, graph, embeddings, cognee)

    get_capabilities = GetCapabilitiesUseCase(
        service_name=resolved_settings.service_name,
        deploy_profile=resolved_settings.deploy_profile.value,
        policy_mode=resolved_settings.policy_mode.value,
        adapters=adapters,
        supported_policy_modes=SUPPORTED_POLICY_MODES,
        limits={
            "max_context_tokens": resolved_settings.max_context_tokens,
            "max_context_chars": resolved_settings.max_context_chars,
            "max_memory_candidates": resolved_settings.max_memory_candidates,
            "max_memory_results": resolved_settings.max_memory_results,
            "max_capture_text_chars": resolved_settings.max_capture_text_chars,
            "max_pending_captures_per_memory_scope": (
                resolved_settings.max_pending_captures_per_memory_scope
            ),
            "max_pending_suggestions_per_memory_scope": (
                resolved_settings.max_pending_suggestions_per_memory_scope
            ),
            "max_asset_upload_bytes": resolved_settings.max_asset_upload_bytes,
            "asset_storage_bytes_per_memory_scope": (
                resolved_settings.plan_asset_storage_bytes_per_memory_scope
            ),
            "media_analysis_seconds_per_month": (product_plan.media_analysis_seconds_per_month),
        },
    )
    create_space = CreateSpaceUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    list_spaces = ListSpacesUseCase(uow_factory=uow_factory)
    create_memory_scope = CreateMemoryScopeUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    list_memory_scopes = ListMemoryScopesUseCase(uow_factory=uow_factory)
    update_memory_scope = UpdateMemoryScopeUseCase(uow_factory=uow_factory, clock=clock)
    delete_memory_scope = DeleteMemoryScopeUseCase(uow_factory=uow_factory, clock=clock)
    create_user = CreateUserUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    list_users = ListUsersUseCase(uow_factory=uow_factory)
    create_space_membership = CreateSpaceMembershipUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
    )
    list_space_memberships = ListSpaceMembershipsUseCase(uow_factory=uow_factory)
    check_space_access = CheckSpaceAccessUseCase(uow_factory=uow_factory)
    remember_fact = RememberFactUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    list_facts = ListFactsUseCase(uow_factory=uow_factory)
    get_fact = GetFactUseCase(uow_factory=uow_factory)
    list_fact_versions = ListFactVersionsUseCase(uow_factory=uow_factory)
    related_facts = RelatedFactsUseCase(uow_factory=uow_factory)
    link_facts = LinkFactsUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    list_fact_relations = ListFactRelationsUseCase(uow_factory=uow_factory)
    unlink_fact_relation = UnlinkFactRelationUseCase(uow_factory=uow_factory, clock=clock)
    create_asset = CreateAssetUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
        blob_storage=blob_storage,
        storage_backend=resolved_settings.asset_storage_backend,
        max_bytes=resolved_settings.max_asset_upload_bytes,
        max_image_pixels=resolved_settings.extraction_max_image_pixels,
        max_storage_bytes_per_memory_scope=(
            resolved_settings.plan_asset_storage_bytes_per_memory_scope
        ),
    )
    get_asset = GetAssetUseCase(uow_factory=uow_factory)
    list_assets = ListAssetsUseCase(uow_factory=uow_factory)
    delete_asset = DeleteAssetUseCase(
        uow_factory=uow_factory,
        clock=clock,
        blob_storage=blob_storage,
    )
    read_asset_bytes = ReadAssetBytesUseCase(
        uow_factory=uow_factory,
        blob_storage=blob_storage,
    )
    suggest_context_links = SuggestContextLinksUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
    )
    create_context_link = CreateContextLinkUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
    )
    list_context_links = ListContextLinksUseCase(uow_factory=uow_factory)
    list_context_link_suggestions = ListContextLinkSuggestionsUseCase(uow_factory=uow_factory)
    review_context_link_suggestion = ReviewContextLinkSuggestionUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
    )
    review_context_link_suggestions_batch = ReviewContextLinkSuggestionsBatchUseCase(
        review_context_link_suggestion=review_context_link_suggestion,
        list_context_link_suggestions=list_context_link_suggestions,
    )
    update_context_link = UpdateContextLinkUseCase(uow_factory=uow_factory, clock=clock)
    delete_context_link = DeleteContextLinkUseCase(uow_factory=uow_factory, clock=clock)
    update_fact = UpdateFactUseCase(uow_factory=uow_factory, clock=clock)
    forget_fact = ForgetFactUseCase(uow_factory=uow_factory, clock=clock)
    ensure_scope = EnsureScopeUseCase(uow_factory=uow_factory, clock=clock)
    ingest_episode = IngestEpisodeUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
        classifier=RuleBasedMemoryClassifier(),
        auto_suggestions_enabled=resolved_settings.policy_mode.value == "suggestions",
    )
    ingest_document = IngestDocumentUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    extraction_limits = ExtractionLimits(
        max_bytes=resolved_settings.extraction_max_bytes,
        max_pages=resolved_settings.extraction_max_pages,
        max_media_seconds=resolved_settings.extraction_max_media_seconds,
        max_output_chars=resolved_settings.extraction_max_output_chars,
        max_tables=resolved_settings.extraction_max_tables,
        parser_timeout_seconds=resolved_settings.extraction_parser_timeout_seconds,
        subprocess_timeout_seconds=resolved_settings.extraction_subprocess_timeout_seconds,
        max_image_pixels=resolved_settings.extraction_max_image_pixels,
        max_archive_entries=resolved_settings.extraction_max_archive_entries,
        max_archive_uncompressed_bytes=(
            resolved_settings.extraction_max_archive_uncompressed_bytes
        ),
        max_archive_single_entry_bytes=(
            resolved_settings.extraction_max_archive_single_entry_bytes
        ),
        max_archive_compression_ratio=(
            resolved_settings.extraction_max_archive_compression_ratio
        ),
        enable_ocr=resolved_settings.extraction_ocr_enabled,
        enable_external_ai=resolved_settings.extraction_external_ai_enabled,
    )
    request_asset_extraction = RequestAssetExtractionUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
        plan=product_plan,
        default_parser_profile=resolved_settings.extraction_default_profile,
        default_unknown_media_seconds=resolved_settings.extraction_max_media_seconds,
    )
    get_asset_extraction = GetAssetExtractionUseCase(uow_factory=uow_factory)
    list_asset_extractions = ListAssetExtractionsUseCase(uow_factory=uow_factory)
    read_extraction_artifact_bytes = ReadExtractionArtifactBytesUseCase(
        uow_factory=uow_factory,
        blob_storage=blob_storage,
    )
    retry_asset_extraction = RetryAssetExtractionUseCase(
        uow_factory=uow_factory,
        clock=clock,
    )
    cancel_asset_extraction = CancelAssetExtractionUseCase(
        uow_factory=uow_factory,
        clock=clock,
    )
    run_asset_extraction = RunAssetExtractionUseCase(
        uow_factory=uow_factory,
        blob_storage=blob_storage,
        detector=SimpleFileTypeDetector(),
        extractor=build_standard_extractor(
            openai_api_key=resolved_settings.openai_api_key,
            vision_model=resolved_settings.extraction_vision_model,
            vision_detail=resolved_settings.extraction_vision_detail,
            provider_timeout_seconds=resolved_settings.extraction_provider_timeout_seconds,
            transcription_provider=resolved_settings.transcription_provider,
            transcription_model=resolved_settings.transcription_openai_model,
            transcription_max_upload_bytes=(
                resolved_settings.transcription_openai_max_upload_bytes
            ),
            asr_model=resolved_settings.extraction_asr_model,
            asr_device=resolved_settings.extraction_asr_device,
            asr_compute_type=resolved_settings.extraction_asr_compute_type,
        ),
        ingest_document=ingest_document,
        clock=clock,
        ids=ids,
        limits=extraction_limits,
        artifact_storage_backend=resolved_settings.asset_storage_backend,
        execution_lease_seconds=resolved_settings.extraction_execution_lease_seconds,
        cancellation_poll_seconds=resolved_settings.extraction_cancellation_poll_seconds,
        heartbeat_seconds=resolved_settings.extraction_heartbeat_seconds,
    )
    create_anchor = CreateAnchorUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    update_anchor = UpdateAnchorUseCase(uow_factory=uow_factory, clock=clock)
    delete_anchor = DeleteAnchorUseCase(uow_factory=uow_factory, clock=clock)
    list_anchors = ListAnchorsUseCase(uow_factory=uow_factory)
    list_anchor_relations = ListAnchorRelationsUseCase(uow_factory=uow_factory)
    suggest_anchor_merges = SuggestAnchorMergesUseCase(uow_factory=uow_factory)
    merge_anchors = MergeAnchorsUseCase(uow_factory=uow_factory, clock=clock)
    split_anchor = SplitAnchorUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    backfill_anchors = BackfillAnchorsUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    get_document = GetDocumentUseCase(uow_factory=uow_factory)
    list_document_chunks = ListDocumentChunksUseCase(uow_factory=uow_factory)
    process_document = ProcessDocumentUseCase(uow_factory=uow_factory)
    delete_document = DeleteDocumentUseCase(uow_factory=uow_factory, clock=clock)
    build_context = BuildContextUseCase(
        uow_factory=uow_factory,
        ids=ids,
        vector_index=vector,
        graph_index=graph,
        embedder=query_embeddings,
        clock=clock,
        rag_recall=cognee,
        packer=ContextPacker(),
        blob_storage=blob_storage,
    )
    build_memory_digest = BuildMemoryDigestUseCase(
        uow_factory=uow_factory,
        ids=ids,
        context_builder=build_context,
    )
    build_memory_insights = BuildMemoryInsightsUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
    )
    build_memory_browser = BuildMemoryBrowserUseCase(
        uow_factory=uow_factory,
        clock=clock,
    )
    build_memory_operations_console = BuildMemoryOperationsConsoleUseCase(
        uow_factory=uow_factory,
        clock=clock,
    )
    export_graph = ExportGraphUseCase(uow_factory=uow_factory)
    delete_thread_memory = DeleteThreadMemoryUseCase(uow_factory=uow_factory)
    get_session_status = GetSessionStatusUseCase(uow_factory=uow_factory)
    get_usage_summary = GetUsageSummaryUseCase(
        uow_factory=uow_factory,
        clock=clock,
        plan=product_plan,
    )
    create_suggestion = CreateSuggestionUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    create_suggestions_batch = CreateSuggestionsBatchUseCase(create_suggestion=create_suggestion)
    list_suggestions = ListSuggestionsUseCase(uow_factory=uow_factory)
    approve_suggestion = ApproveSuggestionUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    reject_suggestion = RejectSuggestionUseCase(uow_factory=uow_factory, clock=clock)
    expire_suggestion = ExpireSuggestionUseCase(uow_factory=uow_factory, clock=clock)
    resolve_duplicate_merge = ResolveDuplicateMergeUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
    )
    resolve_suggestion_conflict = ResolveSuggestionConflictUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
    )
    review_suggestions_batch = ReviewSuggestionsBatchUseCase(
        approve_suggestion=approve_suggestion,
        reject_suggestion=reject_suggestion,
        expire_suggestion=expire_suggestion,
    )
    receive_capture = ReceiveCaptureUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
        max_pending_captures_per_memory_scope=resolved_settings.max_pending_captures_per_memory_scope,
    )
    get_capture = GetCaptureUseCase(uow_factory=uow_factory)
    list_captures = ListCapturesUseCase(uow_factory=uow_factory)
    purge_capture = PurgeCaptureUseCase(uow_factory=uow_factory, clock=clock)
    consolidate_capture = ConsolidateCaptureUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
        extractor=_build_capture_extractor(resolved_settings),
        external_ai_enabled=resolved_settings.capture_external_ai_enabled,
        auto_apply_safe_enabled=(
            resolved_settings.capture_mode == CaptureMode.AUTO_APPLY_SAFE
            and resolved_settings.auto_apply_safe_enabled
        ),
        capture_consolidation_enabled=(
            resolved_settings.policy_mode
            in {MemoryPolicyMode.SUGGESTIONS, MemoryPolicyMode.ACTIVE_CONTEXT}
            and resolved_settings.capture_mode in {CaptureMode.SUGGEST, CaptureMode.AUTO_APPLY_SAFE}
        ),
        max_pending_suggestions_per_memory_scope=(
            resolved_settings.max_pending_suggestions_per_memory_scope
        ),
    )
    expire_pending_suggestions = ExpirePendingSuggestionsUseCase(
        uow_factory=uow_factory,
        clock=clock,
    )
    run_blob_storage_cleanup = RunBlobStorageCleanupUseCase(
        uow_factory=uow_factory,
        blob_storage=blob_storage,
        clock=clock,
    )
    run_blob_storage_integrity_audit = RunBlobStorageIntegrityAuditUseCase(
        uow_factory=uow_factory,
        blob_storage=blob_storage,
        clock=clock,
    )
    runtime_metrics = RuntimeMetrics()

    return Container(
        settings=resolved_settings,
        engine=engine,
        clock=clock,
        ids=ids,
        uow_factory=uow_factory,
        adapters=adapters,
        cognee_memory=cognee,
        vector_index=vector,
        graph_index=graph,
        embedder=embeddings,
        blob_storage=blob_storage,
        get_capabilities=get_capabilities,
        create_space=create_space,
        list_spaces=list_spaces,
        create_memory_scope=create_memory_scope,
        list_memory_scopes=list_memory_scopes,
        update_memory_scope=update_memory_scope,
        delete_memory_scope=delete_memory_scope,
        create_user=create_user,
        list_users=list_users,
        create_space_membership=create_space_membership,
        list_space_memberships=list_space_memberships,
        check_space_access=check_space_access,
        remember_fact=remember_fact,
        list_facts=list_facts,
        get_fact=get_fact,
        list_fact_versions=list_fact_versions,
        related_facts=related_facts,
        link_facts=link_facts,
        list_fact_relations=list_fact_relations,
        unlink_fact_relation=unlink_fact_relation,
        create_asset=create_asset,
        get_asset=get_asset,
        list_assets=list_assets,
        delete_asset=delete_asset,
        read_asset_bytes=read_asset_bytes,
        request_asset_extraction=request_asset_extraction,
        get_asset_extraction=get_asset_extraction,
        list_asset_extractions=list_asset_extractions,
        read_extraction_artifact_bytes=read_extraction_artifact_bytes,
        retry_asset_extraction=retry_asset_extraction,
        cancel_asset_extraction=cancel_asset_extraction,
        run_asset_extraction=run_asset_extraction,
        create_anchor=create_anchor,
        update_anchor=update_anchor,
        delete_anchor=delete_anchor,
        list_anchors=list_anchors,
        list_anchor_relations=list_anchor_relations,
        suggest_anchor_merges=suggest_anchor_merges,
        merge_anchors=merge_anchors,
        split_anchor=split_anchor,
        backfill_anchors=backfill_anchors,
        suggest_context_links=suggest_context_links,
        create_context_link=create_context_link,
        list_context_links=list_context_links,
        list_context_link_suggestions=list_context_link_suggestions,
        review_context_link_suggestion=review_context_link_suggestion,
        review_context_link_suggestions_batch=review_context_link_suggestions_batch,
        update_context_link=update_context_link,
        delete_context_link=delete_context_link,
        update_fact=update_fact,
        forget_fact=forget_fact,
        ensure_scope=ensure_scope,
        ingest_episode=ingest_episode,
        ingest_document=ingest_document,
        get_document=get_document,
        list_document_chunks=list_document_chunks,
        process_document=process_document,
        delete_document=delete_document,
        build_context=build_context,
        build_memory_digest=build_memory_digest,
        build_memory_insights=build_memory_insights,
        build_memory_browser=build_memory_browser,
        build_memory_operations_console=build_memory_operations_console,
        export_graph=export_graph,
        delete_thread_memory=delete_thread_memory,
        get_session_status=get_session_status,
        get_usage_summary=get_usage_summary,
        create_suggestion=create_suggestion,
        create_suggestions_batch=create_suggestions_batch,
        list_suggestions=list_suggestions,
        approve_suggestion=approve_suggestion,
        reject_suggestion=reject_suggestion,
        expire_suggestion=expire_suggestion,
        resolve_duplicate_merge=resolve_duplicate_merge,
        resolve_suggestion_conflict=resolve_suggestion_conflict,
        review_suggestions_batch=review_suggestions_batch,
        receive_capture=receive_capture,
        get_capture=get_capture,
        list_captures=list_captures,
        purge_capture=purge_capture,
        consolidate_capture=consolidate_capture,
        expire_pending_suggestions=expire_pending_suggestions,
        run_blob_storage_cleanup=run_blob_storage_cleanup,
        run_blob_storage_integrity_audit=run_blob_storage_integrity_audit,
        runtime_metrics=runtime_metrics,
        provider_circuits=provider_circuits,
    )


async def _close_resource(resource: object) -> None:
    for method_name in ("aclose", "close"):
        close = getattr(resource, method_name, None)
        if not callable(close):
            continue
        result = close()
        if inspect.isawaitable(result):
            await result
        return


def _build_blob_storage(settings: Settings) -> BlobStorageMaintenancePort:
    if settings.asset_storage_backend == "local":
        return LocalBlobStorage(root_dir=settings.asset_storage_dir)
    if settings.asset_storage_backend == "s3":
        return S3BlobStorage(
            bucket=settings.asset_storage_s3_bucket or "",
            prefix=settings.asset_storage_s3_prefix,
            endpoint_url=settings.asset_storage_s3_endpoint_url,
            region_name=settings.asset_storage_s3_region,
            access_key_id=settings.asset_storage_s3_access_key_id,
            secret_access_key=settings.asset_storage_s3_secret_access_key,
            session_token=settings.asset_storage_s3_session_token,
            force_path_style=settings.asset_storage_s3_force_path_style,
        )
    raise RuntimeError("Unsupported asset storage backend")


def _build_vector_adapter(settings: Settings) -> MemoryAdapterPort:
    if not settings.qdrant_enabled:
        return NoopVectorMemoryAdapter(name="qdrant")
    from infinity_context_adapters.qdrant import QdrantVectorMemoryAdapter

    return QdrantVectorMemoryAdapter(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        collection_name=settings.qdrant_collection,
        vector_size=settings.embeddings_dimensions,
        hybrid_sparse_enabled=settings.qdrant_hybrid_sparse_enabled,
        sparse_model=settings.qdrant_sparse_model,
        dense_vector_name=settings.qdrant_dense_vector_name,
        sparse_vector_name=settings.qdrant_sparse_vector_name,
    )


def _build_graph_adapter(settings: Settings) -> MemoryAdapterPort:
    if not settings.graphiti_enabled:
        return NoopGraphMemoryAdapter(name="graphiti")
    from infinity_context_adapters.graphiti import GraphitiGraphMemoryAdapter

    return GraphitiGraphMemoryAdapter(
        neo4j_uri=settings.graphiti_neo4j_uri,
        neo4j_user=settings.graphiti_neo4j_user,
        neo4j_password=settings.graphiti_neo4j_password,
        build_indices=settings.graphiti_build_indices,
    )


def _build_embedding_adapter(settings: Settings) -> MemoryAdapterPort:
    if not settings.embeddings_enabled:
        return NoopEmbeddingAdapter(name="embeddings")
    if settings.embeddings_provider == "openai":
        from infinity_context_adapters.embeddings import OpenAIEmbeddingAdapter

        return OpenAIEmbeddingAdapter(
            api_key=settings.openai_api_key,
            model=settings.embeddings_model,
            dimensions=settings.embeddings_dimensions,
        )
    return NoopEmbeddingAdapter(name="embeddings")


def _build_capture_extractor(settings: Settings) -> MemoryExtractorPort:
    if settings.capture_extractor_provider == "noop":
        return NoopMemoryExtractor()
    if settings.capture_extractor_provider == "openai":
        from infinity_context_adapters.extraction import OpenAIJsonMemoryExtractor

        return OpenAIJsonMemoryExtractor(
            api_key=settings.openai_api_key,
            model=settings.capture_extractor_model,
        )
    return RuleBasedMemoryExtractor()


def _build_cognee_adapter(settings: Settings) -> MemoryAdapterPort:
    from infinity_context_adapters.cognee import CogneeMemoryAdapter

    return CogneeMemoryAdapter(
        enabled=settings.cognee_enabled,
        configured=settings.cognee_runtime_configured,
        dataset_prefix=settings.cognee_dataset_prefix,
    )


def _provider_circuit(
    adapter_name: str,
    operation_kind: str,
    clock: ClockPort,
    settings: Settings,
) -> ProviderCircuitBreaker:
    return ProviderCircuitBreaker(
        adapter_name=adapter_name,
        operation_kind=operation_kind,
        clock=clock,
        failure_threshold=settings.provider_circuit_failure_threshold,
        reset_after_seconds=settings.provider_circuit_reset_after_seconds,
    )

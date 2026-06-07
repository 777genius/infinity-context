"""Composition root for memo_stack_server."""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from memo_stack_adapters.noop import (
    NoopEmbeddingAdapter,
    NoopGraphMemoryAdapter,
    NoopVectorMemoryAdapter,
    SystemClock,
    UuidIdGenerator,
)
from memo_stack_adapters.postgres import (
    PostgresUnitOfWorkFactory,
    build_async_engine,
    build_session_factory,
)
from memo_stack_core.application import (
    ApproveSuggestionUseCase,
    BuildContextUseCase,
    BuildMemoryDigestUseCase,
    BuildMemoryInsightsUseCase,
    ConsolidateCaptureUseCase,
    CreateProfileUseCase,
    CreateSpaceUseCase,
    CreateSuggestionUseCase,
    DeleteDocumentUseCase,
    DeleteThreadMemoryUseCase,
    EnsureScopeUseCase,
    ExpirePendingSuggestionsUseCase,
    ExpireSuggestionUseCase,
    ExportGraphUseCase,
    ForgetFactUseCase,
    GetCapabilitiesUseCase,
    GetCaptureUseCase,
    GetDocumentUseCase,
    GetFactUseCase,
    GetSessionStatusUseCase,
    IngestDocumentUseCase,
    IngestEpisodeUseCase,
    ListCapturesUseCase,
    ListDocumentChunksUseCase,
    ListFactsUseCase,
    ListFactVersionsUseCase,
    ListProfilesUseCase,
    ListSpacesUseCase,
    ListSuggestionsUseCase,
    ProcessDocumentUseCase,
    PurgeCaptureUseCase,
    ReceiveCaptureUseCase,
    RejectSuggestionUseCase,
    RelatedFactsUseCase,
    RememberFactUseCase,
    UpdateFactUseCase,
)
from memo_stack_core.application.auto_memory import RuleBasedMemoryClassifier
from memo_stack_core.application.context_packer import ContextPacker
from memo_stack_core.application.extractor import NoopMemoryExtractor, RuleBasedMemoryExtractor
from memo_stack_core.ports.adapters import (
    EmbeddingPort,
    GraphMemoryPort,
    MemoryAdapterPort,
    VectorMemoryPort,
)
from memo_stack_core.ports.auto_memory import MemoryExtractorPort
from memo_stack_core.ports.capabilities import DocumentMemoryPort
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort
from sqlalchemy.ext.asyncio import AsyncEngine

from memo_stack_server.config import CaptureMode, MemoryPolicyMode, Settings
from memo_stack_server.metrics import RuntimeMetrics
from memo_stack_server.provider_budget import QueryEmbeddingBudgetAdapter
from memo_stack_server.provider_circuit import (
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
    get_capabilities: GetCapabilitiesUseCase
    create_space: CreateSpaceUseCase
    list_spaces: ListSpacesUseCase
    create_profile: CreateProfileUseCase
    list_profiles: ListProfilesUseCase
    remember_fact: RememberFactUseCase
    list_facts: ListFactsUseCase
    get_fact: GetFactUseCase
    list_fact_versions: ListFactVersionsUseCase
    related_facts: RelatedFactsUseCase
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
    export_graph: ExportGraphUseCase
    delete_thread_memory: DeleteThreadMemoryUseCase
    get_session_status: GetSessionStatusUseCase
    create_suggestion: CreateSuggestionUseCase
    list_suggestions: ListSuggestionsUseCase
    approve_suggestion: ApproveSuggestionUseCase
    reject_suggestion: RejectSuggestionUseCase
    expire_suggestion: ExpireSuggestionUseCase
    receive_capture: ReceiveCaptureUseCase
    get_capture: GetCaptureUseCase
    list_captures: ListCapturesUseCase
    purge_capture: PurgeCaptureUseCase
    consolidate_capture: ConsolidateCaptureUseCase
    expire_pending_suggestions: ExpirePendingSuggestionsUseCase
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
            "max_pending_captures_per_profile": (
                resolved_settings.max_pending_captures_per_profile
            ),
            "max_pending_suggestions_per_profile": (
                resolved_settings.max_pending_suggestions_per_profile
            ),
        },
    )
    create_space = CreateSpaceUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    list_spaces = ListSpacesUseCase(uow_factory=uow_factory)
    create_profile = CreateProfileUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    list_profiles = ListProfilesUseCase(uow_factory=uow_factory)
    remember_fact = RememberFactUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    list_facts = ListFactsUseCase(uow_factory=uow_factory)
    get_fact = GetFactUseCase(uow_factory=uow_factory)
    list_fact_versions = ListFactVersionsUseCase(uow_factory=uow_factory)
    related_facts = RelatedFactsUseCase(uow_factory=uow_factory)
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
    export_graph = ExportGraphUseCase(uow_factory=uow_factory)
    delete_thread_memory = DeleteThreadMemoryUseCase(uow_factory=uow_factory)
    get_session_status = GetSessionStatusUseCase(uow_factory=uow_factory)
    create_suggestion = CreateSuggestionUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    list_suggestions = ListSuggestionsUseCase(uow_factory=uow_factory)
    approve_suggestion = ApproveSuggestionUseCase(uow_factory=uow_factory, clock=clock, ids=ids)
    reject_suggestion = RejectSuggestionUseCase(uow_factory=uow_factory, clock=clock)
    expire_suggestion = ExpireSuggestionUseCase(uow_factory=uow_factory, clock=clock)
    receive_capture = ReceiveCaptureUseCase(
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
        max_pending_captures_per_profile=resolved_settings.max_pending_captures_per_profile,
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
            and resolved_settings.capture_mode
            in {CaptureMode.SUGGEST, CaptureMode.AUTO_APPLY_SAFE}
        ),
        max_pending_suggestions_per_profile=(
            resolved_settings.max_pending_suggestions_per_profile
        ),
    )
    expire_pending_suggestions = ExpirePendingSuggestionsUseCase(
        uow_factory=uow_factory,
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
        get_capabilities=get_capabilities,
        create_space=create_space,
        list_spaces=list_spaces,
        create_profile=create_profile,
        list_profiles=list_profiles,
        remember_fact=remember_fact,
        list_facts=list_facts,
        get_fact=get_fact,
        list_fact_versions=list_fact_versions,
        related_facts=related_facts,
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
        export_graph=export_graph,
        delete_thread_memory=delete_thread_memory,
        get_session_status=get_session_status,
        create_suggestion=create_suggestion,
        list_suggestions=list_suggestions,
        approve_suggestion=approve_suggestion,
        reject_suggestion=reject_suggestion,
        expire_suggestion=expire_suggestion,
        receive_capture=receive_capture,
        get_capture=get_capture,
        list_captures=list_captures,
        purge_capture=purge_capture,
        consolidate_capture=consolidate_capture,
        expire_pending_suggestions=expire_pending_suggestions,
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


def _build_vector_adapter(settings: Settings) -> MemoryAdapterPort:
    if not settings.qdrant_enabled:
        return NoopVectorMemoryAdapter(name="qdrant")
    from memo_stack_adapters.qdrant import QdrantVectorMemoryAdapter

    return QdrantVectorMemoryAdapter(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        collection_name=settings.qdrant_collection,
        vector_size=settings.embeddings_dimensions,
    )


def _build_graph_adapter(settings: Settings) -> MemoryAdapterPort:
    if not settings.graphiti_enabled:
        return NoopGraphMemoryAdapter(name="graphiti")
    from memo_stack_adapters.graphiti import GraphitiGraphMemoryAdapter

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
        from memo_stack_adapters.embeddings import OpenAIEmbeddingAdapter

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
        from memo_stack_adapters.extraction import OpenAIJsonMemoryExtractor

        return OpenAIJsonMemoryExtractor(
            api_key=settings.openai_api_key,
            model=settings.capture_extractor_model,
        )
    return RuleBasedMemoryExtractor()


def _build_cognee_adapter(settings: Settings) -> MemoryAdapterPort:
    from memo_stack_adapters.cognee import CogneeMemoryAdapter

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

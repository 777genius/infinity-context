"""Contracts for the document memory pipeline process."""

from __future__ import annotations

from dataclasses import dataclass

import infinity_context_core.features.context_building.public as context_building_public
import infinity_context_core.features.document_ingestion.public as document_ingestion_public
import infinity_context_core.features.memory_facts.public as memory_facts_public


@dataclass(frozen=True, slots=True)
class DocumentMemoryPipelineCommand:
    """Process request composed only from feature-owned public contracts."""

    ingest_document: document_ingestion_public.IngestDocumentCommand
    remember_facts: tuple[memory_facts_public.RememberFactCommand, ...] = ()
    build_context: context_building_public.BuildContextQuery | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentMemoryPipelineResult:
    """Process result returned after the selected feature boundaries run."""

    document: document_ingestion_public.IngestDocumentResult
    remembered_facts: tuple[memory_facts_public.RememberFactResult, ...] = ()
    context: context_building_public.BuildContextResult | None = None


@dataclass(frozen=True, slots=True)
class DocumentMemoryPipelineUseCases:
    """Feature public API bundle required by the process orchestrator."""

    document_ingestion: document_ingestion_public.DocumentIngestionUseCases
    memory_facts: memory_facts_public.MemoryFactLifecycleUseCases | None = None
    context_building: context_building_public.ContextBuildingUseCases | None = None


__all__ = (
    "DocumentMemoryPipelineCommand",
    "DocumentMemoryPipelineResult",
    "DocumentMemoryPipelineUseCases",
)

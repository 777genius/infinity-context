"""Infinity Context Core public package."""

import infinity_context_core.features.context_building.public as context_building_public
import infinity_context_core.features.document_ingestion.public as document_ingestion_public
import infinity_context_core.features.memory_facts.public as memory_facts_public
import infinity_context_core.features.memory_scopes.public as memory_scopes_public
from infinity_context_core.application.dto import (
    FactResult,
    ForgetFactCommand,
    RememberFactCommand,
    UpdateFactCommand,
)
from infinity_context_core.application.use_cases.forget_fact import ForgetFactUseCase
from infinity_context_core.application.use_cases.get_capabilities import (
    CapabilitiesResult,
    GetCapabilitiesUseCase,
)
from infinity_context_core.application.use_cases.remember_fact import RememberFactUseCase
from infinity_context_core.application.use_cases.update_fact import UpdateFactUseCase
from infinity_context_core.domain.entities import (
    Confidence,
    FactStatus,
    MemoryFact,
    MemoryKind,
    SourceRef,
    TrustLevel,
)
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryError,
    MemoryForbiddenError,
    MemoryInfrastructureError,
    MemoryInvariantError,
    MemoryNotFoundError,
    MemoryUnauthorizedError,
    MemoryValidationError,
)

ContextBuildingUseCases = context_building_public.ContextBuildingUseCases
DocumentIngestionUseCases = document_ingestion_public.DocumentIngestionUseCases
MemoryFactLifecycleUseCases = memory_facts_public.MemoryFactLifecycleUseCases
MemoryScopeUseCases = memory_scopes_public.MemoryScopeUseCases

__all__ = [
    "CapabilitiesResult",
    "Confidence",
    "ContextBuildingUseCases",
    "DocumentIngestionUseCases",
    "FactResult",
    "FactStatus",
    "ForgetFactCommand",
    "ForgetFactUseCase",
    "GetCapabilitiesUseCase",
    "MemoryFactLifecycleUseCases",
    "MemoryConflictError",
    "MemoryError",
    "MemoryFact",
    "MemoryForbiddenError",
    "MemoryInfrastructureError",
    "MemoryInvariantError",
    "MemoryKind",
    "MemoryNotFoundError",
    "MemoryScopeUseCases",
    "MemoryUnauthorizedError",
    "MemoryValidationError",
    "RememberFactCommand",
    "RememberFactUseCase",
    "SourceRef",
    "TrustLevel",
    "UpdateFactCommand",
    "UpdateFactUseCase",
    "context_building_public",
    "document_ingestion_public",
    "memory_facts_public",
    "memory_scopes_public",
]

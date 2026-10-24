"""Demand-loaded compatibility exports with original object identities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from infinity_context_core.shared_kernel.lazy_exports import resolve_lazy_export

_EXPORTS: dict[str, tuple[str, str | None]] = {
    "CapabilitiesResult": (
        "infinity_context_core.application.use_cases.get_capabilities",
        "CapabilitiesResult",
    ),
    "Confidence": ("infinity_context_core.domain.entities", "Confidence"),
    "ContextBuildingUseCases": (
        "infinity_context_core.features.context_building.public",
        "ContextBuildingUseCases",
    ),
    "DocumentIngestionUseCases": (
        "infinity_context_core.features.document_ingestion.public",
        "DocumentIngestionUseCases",
    ),
    "FactResult": ("infinity_context_core.application.dto", "FactResult"),
    "FactStatus": ("infinity_context_core.domain.entities", "FactStatus"),
    "ForgetFactCommand": ("infinity_context_core.application.dto", "ForgetFactCommand"),
    "ForgetFactUseCase": (
        "infinity_context_core.application.use_cases.forget_fact",
        "ForgetFactUseCase",
    ),
    "GetCapabilitiesUseCase": (
        "infinity_context_core.application.use_cases.get_capabilities",
        "GetCapabilitiesUseCase",
    ),
    "MemoryFactLifecycleUseCases": (
        "infinity_context_core.features.memory_facts.public",
        "MemoryFactLifecycleUseCases",
    ),
    "MemoryConflictError": ("infinity_context_core.domain.errors", "MemoryConflictError"),
    "MemoryError": ("infinity_context_core.domain.errors", "MemoryError"),
    "MemoryFact": ("infinity_context_core.domain.entities", "MemoryFact"),
    "MemoryForbiddenError": ("infinity_context_core.domain.errors", "MemoryForbiddenError"),
    "MemoryInfrastructureError": (
        "infinity_context_core.domain.errors",
        "MemoryInfrastructureError",
    ),
    "MemoryInvariantError": ("infinity_context_core.domain.errors", "MemoryInvariantError"),
    "MemoryKind": ("infinity_context_core.domain.entities", "MemoryKind"),
    "MemoryNotFoundError": ("infinity_context_core.domain.errors", "MemoryNotFoundError"),
    "MemoryScopeUseCases": (
        "infinity_context_core.features.memory_scopes.public",
        "MemoryScopeUseCases",
    ),
    "MemoryUnauthorizedError": ("infinity_context_core.domain.errors", "MemoryUnauthorizedError"),
    "MemoryValidationError": ("infinity_context_core.domain.errors", "MemoryValidationError"),
    "RememberFactCommand": ("infinity_context_core.application.dto", "RememberFactCommand"),
    "RememberFactUseCase": (
        "infinity_context_core.application.use_cases.remember_fact",
        "RememberFactUseCase",
    ),
    "SourceRef": ("infinity_context_core.domain.entities", "SourceRef"),
    "TrustLevel": ("infinity_context_core.domain.entities", "TrustLevel"),
    "UpdateFactCommand": ("infinity_context_core.application.dto", "UpdateFactCommand"),
    "UpdateFactUseCase": (
        "infinity_context_core.application.use_cases.update_fact",
        "UpdateFactUseCase",
    ),
    "context_building_public": ("infinity_context_core.features.context_building.public", None),
    "document_ingestion_public": ("infinity_context_core.features.document_ingestion.public", None),
    "memory_facts_public": ("infinity_context_core.features.memory_facts.public", None),
    "memory_scopes_public": ("infinity_context_core.features.memory_scopes.public", None),
}

if TYPE_CHECKING:
    import infinity_context_core.features.context_building.public as context_building_public
    import infinity_context_core.features.document_ingestion.public as document_ingestion_public
    import infinity_context_core.features.memory_facts.public as memory_facts_public
    import infinity_context_core.features.memory_scopes.public as memory_scopes_public
    from infinity_context_core.application.dto import (
        FactResult as FactResult,
    )
    from infinity_context_core.application.dto import (
        ForgetFactCommand as ForgetFactCommand,
    )
    from infinity_context_core.application.dto import (
        RememberFactCommand as RememberFactCommand,
    )
    from infinity_context_core.application.dto import (
        UpdateFactCommand as UpdateFactCommand,
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
    from infinity_context_core.application.use_cases.remember_fact import (
        RememberFactUseCase as RememberFactUseCase,
    )
    from infinity_context_core.application.use_cases.update_fact import (
        UpdateFactUseCase as UpdateFactUseCase,
    )
    from infinity_context_core.domain.entities import (
        Confidence as Confidence,
    )
    from infinity_context_core.domain.entities import (
        FactStatus as FactStatus,
    )
    from infinity_context_core.domain.entities import (
        MemoryFact as MemoryFact,
    )
    from infinity_context_core.domain.entities import (
        MemoryKind as MemoryKind,
    )
    from infinity_context_core.domain.entities import (
        SourceRef as SourceRef,
    )
    from infinity_context_core.domain.entities import (
        TrustLevel as TrustLevel,
    )
    from infinity_context_core.domain.errors import (
        MemoryConflictError as MemoryConflictError,
    )
    from infinity_context_core.domain.errors import (
        MemoryError as MemoryError,
    )
    from infinity_context_core.domain.errors import (
        MemoryForbiddenError as MemoryForbiddenError,
    )
    from infinity_context_core.domain.errors import (
        MemoryInfrastructureError as MemoryInfrastructureError,
    )
    from infinity_context_core.domain.errors import (
        MemoryInvariantError as MemoryInvariantError,
    )
    from infinity_context_core.domain.errors import (
        MemoryNotFoundError as MemoryNotFoundError,
    )
    from infinity_context_core.domain.errors import (
        MemoryUnauthorizedError as MemoryUnauthorizedError,
    )
    from infinity_context_core.domain.errors import (
        MemoryValidationError as MemoryValidationError,
    )

    ContextBuildingUseCases = context_building_public.ContextBuildingUseCases
    DocumentIngestionUseCases = document_ingestion_public.DocumentIngestionUseCases
    MemoryFactLifecycleUseCases = memory_facts_public.MemoryFactLifecycleUseCases
    MemoryScopeUseCases = memory_scopes_public.MemoryScopeUseCases

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> object:
    return resolve_lazy_export(name, _EXPORTS, globals(), __name__)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

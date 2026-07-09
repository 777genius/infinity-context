"""Thin process orchestrator for document ingestion to memory workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.processes.document_memory_pipeline.contracts import (
    DocumentMemoryPipelineCommand,
    DocumentMemoryPipelineResult,
    DocumentMemoryPipelineUseCases,
)


class DocumentMemoryPipelineUseCase(Protocol):
    async def execute(
        self,
        command: DocumentMemoryPipelineCommand,
    ) -> DocumentMemoryPipelineResult:
        """Run the process through feature public APIs only."""


@dataclass(frozen=True, slots=True)
class DocumentMemoryPipelineProcess:
    """Coordinate existing feature use cases without owning feature business rules."""

    use_cases: DocumentMemoryPipelineUseCases

    async def execute(
        self,
        command: DocumentMemoryPipelineCommand,
    ) -> DocumentMemoryPipelineResult:
        memory_facts = self.use_cases.memory_facts
        context_building = self.use_cases.context_building

        if command.remember_facts and memory_facts is None:
            raise ValueError(
                "memory_facts use cases are required when remember_facts are provided"
            )
        if command.build_context is not None and context_building is None:
            raise ValueError(
                "context_building use cases are required when build_context is provided"
            )

        document = await self.use_cases.document_ingestion.ingest_document.execute(
            command.ingest_document
        )

        remembered_facts = []
        if command.remember_facts:
            for remember_fact in command.remember_facts:
                remembered_facts.append(
                    await memory_facts.remember_fact.execute(remember_fact)
                )

        context = None
        if command.build_context is not None:
            context = await context_building.build_context.execute(
                command.build_context
            )

        return DocumentMemoryPipelineResult(
            document=document,
            remembered_facts=tuple(remembered_facts),
            context=context,
        )


__all__ = (
    "DocumentMemoryPipelineProcess",
    "DocumentMemoryPipelineUseCase",
)

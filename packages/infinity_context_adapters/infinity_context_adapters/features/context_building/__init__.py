"""Adapter seams for the context_building feature.

The adapters in this package implement the feature-owned context candidate
port without importing provider SDKs. Postgres remains the canonical source,
while Qdrant and Graphiti are derived candidate sources behind deferred seams.
"""

from infinity_context_core.features.context_building.public import FEATURE_ID

from infinity_context_adapters.features.context_building.candidate_provider_chain import (
    ContextCandidateProviderChain,
    create_context_candidate_provider_chain,
)
from infinity_context_adapters.features.context_building.graphiti_candidate_provider import (
    GraphitiContextCandidateProvider,
    create_graphiti_context_candidate_provider,
)
from infinity_context_adapters.features.context_building.in_memory_candidate_provider import (
    InMemoryContextCandidateProvider,
    create_in_memory_context_candidate_provider,
)
from infinity_context_adapters.features.context_building.postgres_candidate_provider import (
    PostgresContextCandidateProvider,
    create_postgres_context_candidate_provider,
)
from infinity_context_adapters.features.context_building.qdrant_candidate_provider import (
    QdrantContextCandidateProvider,
    create_qdrant_context_candidate_provider,
)
from infinity_context_adapters.features.context_building.records import (
    ContextCandidateRecord,
)

__all__ = (
    "FEATURE_ID",
    "ContextCandidateProviderChain",
    "ContextCandidateRecord",
    "GraphitiContextCandidateProvider",
    "InMemoryContextCandidateProvider",
    "PostgresContextCandidateProvider",
    "QdrantContextCandidateProvider",
    "create_context_candidate_provider_chain",
    "create_graphiti_context_candidate_provider",
    "create_in_memory_context_candidate_provider",
    "create_postgres_context_candidate_provider",
    "create_qdrant_context_candidate_provider",
)

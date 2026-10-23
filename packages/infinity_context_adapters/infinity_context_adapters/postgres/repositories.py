"""Compatibility exports for capability-owned canonical Postgres repositories."""

from infinity_context_adapters.postgres.anchor_repositories import (
    PostgresAnchorRepository as PostgresAnchorRepository,
)
from infinity_context_adapters.postgres.capture_repositories import (
    PostgresCaptureRepository as PostgresCaptureRepository,
)
from infinity_context_adapters.postgres.document_repositories import (
    PostgresChunkRepository as PostgresChunkRepository,
)
from infinity_context_adapters.postgres.document_repositories import (
    PostgresDocumentRepository as PostgresDocumentRepository,
)
from infinity_context_adapters.postgres.document_repositories import (
    _keyword_search_statement as _keyword_search_statement,
)
from infinity_context_adapters.postgres.episode_repositories import (
    PostgresEpisodeRepository as PostgresEpisodeRepository,
)
from infinity_context_adapters.postgres.record_repositories import (
    PostgresIdempotencyRepository as PostgresIdempotencyRepository,
)
from infinity_context_adapters.postgres.record_repositories import (
    PostgresOutbox as PostgresOutbox,
)
from infinity_context_adapters.postgres.suggestion_repositories import (
    PostgresSuggestionRepository as PostgresSuggestionRepository,
)

"""Memory server configuration."""

from enum import StrEnum

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeployProfile(StrEnum):
    TEST = "test"
    LOCAL = "local"
    CANARY = "canary"
    SERVER = "server"


class MemoryPolicyMode(StrEnum):
    DISABLED = "disabled"
    MANUAL_ONLY = "manual_only"
    SUGGESTIONS = "suggestions"
    ACTIVE_CONTEXT = "active_context"


class CaptureMode(StrEnum):
    OFF = "off"
    RETRIEVE_ONLY = "retrieve_only"
    CAPTURE_ONLY = "capture_only"
    SUGGEST = "suggest"
    AUTO_APPLY_SAFE = "auto_apply_safe"


class Settings(BaseSettings):
    service_name: str = "memo-stack"
    deploy_profile: DeployProfile = DeployProfile.LOCAL
    database_url: str = "postgresql+asyncpg://memo_stack:memo_stack@127.0.0.1:54329/memo_stack"
    auto_create_schema: bool = False
    host: str = "127.0.0.1"
    port: int = 7788
    service_token: str | None = None
    policy_mode: MemoryPolicyMode = MemoryPolicyMode.ACTIVE_CONTEXT
    auto_memory_mode: CaptureMode | None = None
    capture_mode: CaptureMode = CaptureMode.RETRIEVE_ONLY
    capture_external_ai_enabled: bool = False
    capture_extractor_provider: str = "rule_based"
    capture_extractor_model: str = "gpt-4.1-mini"
    capture_default_consolidate: bool = True
    auto_apply_safe_enabled: bool = False
    max_capture_text_chars: int = Field(default=20_000, ge=100, le=100_000)
    max_pending_captures_per_profile: int = Field(default=5_000, ge=1, le=100_000)
    max_pending_suggestions_per_profile: int = Field(default=500, ge=1, le=10_000)
    qdrant_enabled: bool = False
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "memo_stack_chunks_v1"
    graphiti_enabled: bool = False
    graphiti_neo4j_uri: str = "bolt://127.0.0.1:7687"
    graphiti_neo4j_user: str = "neo4j"
    graphiti_neo4j_password: str | None = None
    graphiti_build_indices: bool = False
    cognee_enabled: bool = False
    cognee_runtime_configured: bool = False
    cognee_dataset_prefix: str = "memory"
    embeddings_enabled: bool = False
    embeddings_provider: str = "noop"
    embeddings_model: str = "text-embedding-3-small"
    embeddings_dimensions: int = Field(default=1536, ge=1, le=8192)
    openai_api_key: str | None = None
    legacy_client_enabled: bool = False
    default_space_slug: str = "default"
    default_profile_external_ref: str = "default"
    max_context_tokens: int = Field(default=1800, ge=256, le=16000)
    max_context_chars: int = Field(default=18000, ge=1000, le=60000)
    max_memory_candidates: int = Field(default=2000, ge=1, le=10000)
    max_memory_results: int = Field(default=32, ge=1, le=96)
    outbox_backpressure_pending_threshold: int = Field(default=0, ge=0)
    max_embedding_tokens_per_document: int = Field(default=0, ge=0)
    max_query_embeddings_per_minute: int = Field(default=0, ge=0)
    provider_circuit_failure_threshold: int = Field(default=3, ge=1, le=100)
    provider_circuit_reset_after_seconds: int = Field(default=60, ge=1, le=3600)

    model_config = SettingsConfigDict(
        env_prefix="MEMORY_",
        env_file=".env",
        extra="ignore",
    )

    @model_validator(mode="after")
    def apply_auto_memory_mode_alias(self) -> "Settings":
        if self.auto_memory_mode is not None:
            self.capture_mode = self.auto_memory_mode
        return self

    def validate_for_startup(self) -> None:
        if self.deploy_profile == DeployProfile.SERVER and not self.service_token:
            raise RuntimeError("MEMORY_SERVICE_TOKEN is required for server profile")
        if self.deploy_profile == DeployProfile.SERVER and self.auto_create_schema:
            raise RuntimeError("MEMORY_AUTO_CREATE_SCHEMA is not allowed for server profile")
        if self.deploy_profile == DeployProfile.TEST and (
            self.qdrant_enabled or self.graphiti_enabled or self.embeddings_enabled
        ):
            raise RuntimeError("test profile cannot use external adapters")
        if self.qdrant_enabled and not self.embeddings_enabled:
            raise RuntimeError("MEMORY_QDRANT_ENABLED requires MEMORY_EMBEDDINGS_ENABLED")
        if self.embeddings_enabled and self.embeddings_provider != "openai":
            raise RuntimeError(
                "MEMORY_EMBEDDINGS_PROVIDER must be openai when embeddings are enabled"
            )
        if self.embeddings_enabled and not self.openai_api_key:
            raise RuntimeError("MEMORY_OPENAI_API_KEY is required when embeddings are enabled")
        if self.capture_extractor_provider not in {"rule_based", "noop", "openai"}:
            raise RuntimeError(
                "MEMORY_CAPTURE_EXTRACTOR_PROVIDER must be rule_based, noop or openai"
            )
        if (
            self.capture_extractor_provider == "openai"
            and self.capture_external_ai_enabled
            and not self.openai_api_key
        ):
            raise RuntimeError(
                "MEMORY_OPENAI_API_KEY is required when OpenAI capture extractor is enabled"
            )
        if self.graphiti_enabled and not self.graphiti_neo4j_password:
            raise RuntimeError("MEMORY_GRAPHITI_ENABLED requires MEMORY_GRAPHITI_NEO4J_PASSWORD")

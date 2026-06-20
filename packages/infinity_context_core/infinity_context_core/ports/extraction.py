"""Ports and DTOs for provider-neutral asset content extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from infinity_context_core.domain.extraction import AssetExtractionJob, ExtractionArtifact
from infinity_context_core.ports.assets import StoredBlobReference


@dataclass(frozen=True)
class FileTypeDetectionRequest:
    filename: str
    declared_content_type: str
    content: bytes


@dataclass(frozen=True)
class FileTypeDetectionResult:
    content_type: str
    extension: str | None = None
    confidence: str = "medium"
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionLimits:
    max_bytes: int
    max_pages: int = 100
    max_media_seconds: int = 600
    max_output_chars: int = 500_000
    max_tables: int = 100
    parser_timeout_seconds: float = 300
    subprocess_timeout_seconds: float = 60
    max_image_pixels: int = 50_000_000
    max_archive_entries: int = 2_000
    max_archive_uncompressed_bytes: int = 250 * 1024 * 1024
    max_archive_compression_ratio: int = 100
    enable_ocr: bool = True
    enable_external_ai: bool = False


@dataclass(frozen=True)
class ExtractionRequest:
    job_id: str
    asset_id: str
    filename: str
    declared_content_type: str
    detected_content_type: str
    byte_size: int
    sha256_hex: str
    content: bytes
    parser_profile: str
    limits: ExtractionLimits


@dataclass(frozen=True)
class ExtractedElement:
    kind: str
    text: str
    page_number: int | None = None
    time_start_ms: int | None = None
    time_end_ms: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    confidence: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionArtifactCandidate:
    artifact_type: str
    filename: str
    content_type: str
    content: bytes
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionResult:
    status: str
    normalized_content_type: str
    title: str
    elements: tuple[ExtractedElement, ...] = ()
    markdown: str | None = None
    artifacts: tuple[ExtractionArtifactCandidate, ...] = ()
    technical_metadata: dict[str, object] = field(default_factory=dict)
    diagnostics: dict[str, object] = field(default_factory=dict)
    language: str | None = None
    parser_name: str = "unknown"
    parser_version: str | None = None
    model_version: str | None = None
    safe_error_code: str | None = None
    safe_error_message: str | None = None


class FileTypeDetectorPort(Protocol):
    async def detect(self, request: FileTypeDetectionRequest) -> FileTypeDetectionResult:
        """Detect file type independently from user-supplied content type."""


class ContentExtractionPort(Protocol):
    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        """Extract provider-neutral content and metadata from an asset."""


class AssetExtractionRepositoryPort(Protocol):
    async def create(self, job: AssetExtractionJob) -> AssetExtractionJob:
        """Persist a new extraction job."""

    async def get_by_id(self, job_id: str) -> AssetExtractionJob | None:
        """Load one extraction job."""

    async def find_active_for_asset_profile(
        self,
        *,
        asset_id: str,
        parser_profile: str,
        parser_config_hash: str,
        source_sha256_hex: str,
    ) -> AssetExtractionJob | None:
        """Find an active idempotent extraction job for an asset/profile/config."""

    async def find_reusable_succeeded_for_scope_source(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        asset_id: str,
        parser_profile: str,
        parser_config_hash: str,
        source_sha256_hex: str,
    ) -> AssetExtractionJob | None:
        """Find a succeeded same-source extraction from another stored asset in the scope."""

    async def save(self, job: AssetExtractionJob) -> AssetExtractionJob:
        """Persist changed extraction job state."""

    async def create_artifact(self, artifact: ExtractionArtifact) -> ExtractionArtifact:
        """Persist an extraction artifact row."""

    async def list_artifacts(self, *, job_id: str) -> list[ExtractionArtifact]:
        """List artifacts for a job."""

    async def list_artifacts_for_asset(self, *, asset_id: str) -> list[ExtractionArtifact]:
        """List artifacts derived from one asset."""

    async def get_artifact_by_id(self, artifact_id: str) -> ExtractionArtifact | None:
        """Load one extraction artifact."""

    async def list_retained_artifact_storage_keys(
        self,
        *,
        storage_backend: str,
        storage_keys: tuple[str, ...],
    ) -> set[str]:
        """Return artifact storage keys retained by active stored assets."""

    async def list_retained_artifact_blob_references(
        self,
        *,
        storage_backend: str,
        prefix: str,
        limit: int,
    ) -> list[StoredBlobReference]:
        """List retained extraction artifact blob references for storage maintenance."""

    async def list_for_asset(
        self,
        *,
        asset_id: str,
        status: str | None,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[AssetExtractionJob]:
        """List extraction jobs for one asset."""

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        status: str | None,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[AssetExtractionJob]:
        """List extraction jobs for one memory scope."""

    async def count_by_status_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
    ) -> dict[str, int]:
        """Count extraction jobs by lifecycle status for one memory scope."""

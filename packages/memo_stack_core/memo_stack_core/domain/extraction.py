"""Asset extraction domain entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import NewType

from memo_stack_core.domain.assets import MemoryAssetId
from memo_stack_core.domain.entities import MemoryScopeId, SpaceId, ThreadId
from memo_stack_core.domain.errors import MemoryValidationError

AssetExtractionJobId = NewType("AssetExtractionJobId", str)
ExtractionArtifactId = NewType("ExtractionArtifactId", str)

MAX_EXTRACTION_METADATA_KEYS = 120
MAX_EXTRACTION_ERROR_CHARS = 500


class AssetExtractionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    CANCELED = "canceled"
    STALE = "stale"


class ExtractionRetryDisposition(StrEnum):
    RETRYABLE = "retryable"
    PERMANENT = "permanent"


class ExtractionArtifactType(StrEnum):
    EXTRACTED_JSON = "extracted_json"
    NORMALIZED_JSON = "normalized_json"
    MARKDOWN = "markdown"
    TRANSCRIPT = "transcript"
    TRANSCRIPT_JSON = "transcript_json"
    MEDIA_MANIFEST = "media_manifest"
    KEYFRAME = "keyframe"
    VIDEO_FRAME_TIMELINE = "video_frame_timeline"
    TABLE_HTML = "table_html"
    IMAGE_REGIONS = "image_regions"
    VISION_JSON = "vision_json"


@dataclass(frozen=True)
class AssetExtractionJob:
    id: AssetExtractionJobId
    asset_id: MemoryAssetId
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId | None
    parser_profile: str
    parser_config_hash: str
    source_sha256_hex: str
    status: AssetExtractionStatus
    attempt_count: int
    safe_error_code: str | None
    safe_error_message: str | None
    parser_name: str | None
    parser_version: str | None
    model_version: str | None
    result_document_ids: tuple[str, ...]
    metadata: Mapping[str, object]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    retry_after_at: datetime | None = None
    cancellation_requested_at: datetime | None = None
    retry_disposition: ExtractionRetryDisposition | None = None

    @classmethod
    def create(
        cls,
        *,
        job_id: AssetExtractionJobId,
        asset_id: MemoryAssetId,
        space_id: SpaceId,
        memory_scope_id: MemoryScopeId,
        parser_profile: str,
        parser_config_hash: str,
        source_sha256_hex: str,
        now: datetime,
        thread_id: ThreadId | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AssetExtractionJob:
        safe_profile = _required(parser_profile, "parser_profile", max_chars=80)
        safe_config_hash = _required(parser_config_hash, "parser_config_hash", max_chars=80)
        safe_source_hash = _required(source_sha256_hex, "source_sha256_hex", max_chars=80).lower()
        return cls(
            id=job_id,
            asset_id=asset_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            parser_profile=safe_profile,
            parser_config_hash=safe_config_hash,
            source_sha256_hex=safe_source_hash,
            status=AssetExtractionStatus.PENDING,
            attempt_count=0,
            safe_error_code=None,
            safe_error_message=None,
            parser_name=None,
            parser_version=None,
            model_version=None,
            result_document_ids=(),
            metadata=_safe_metadata(metadata),
            created_at=now,
            updated_at=now,
        )

    def mark_running(
        self,
        *,
        now: datetime,
        lease_owner: str | None = None,
        lease_expires_at: datetime | None = None,
    ) -> AssetExtractionJob:
        if self.status in {
            AssetExtractionStatus.SUCCEEDED,
            AssetExtractionStatus.CANCELED,
            AssetExtractionStatus.UNSUPPORTED,
        }:
            raise MemoryValidationError("Asset extraction job cannot run from current status")
        return replace(
            self,
            status=AssetExtractionStatus.RUNNING,
            attempt_count=self.attempt_count + 1,
            safe_error_code=None,
            safe_error_message=None,
            started_at=now,
            finished_at=None,
            lease_owner=_optional(lease_owner, max_chars=120),
            lease_expires_at=lease_expires_at,
            heartbeat_at=now,
            retry_after_at=None,
            retry_disposition=None,
            cancellation_requested_at=None,
            updated_at=now,
        )

    def with_metadata_updates(
        self,
        *,
        now: datetime,
        metadata: Mapping[str, object],
    ) -> AssetExtractionJob:
        return replace(
            self,
            metadata=_safe_metadata({**dict(self.metadata), **dict(metadata)}),
            updated_at=now,
        )

    def record_heartbeat(
        self,
        *,
        now: datetime,
        lease_expires_at: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AssetExtractionJob:
        if self.status != AssetExtractionStatus.RUNNING:
            raise MemoryValidationError("Only running extraction jobs can heartbeat")
        return replace(
            self,
            heartbeat_at=now,
            lease_expires_at=lease_expires_at or self.lease_expires_at,
            metadata=_safe_metadata({**dict(self.metadata), **dict(metadata or {})}),
            updated_at=now,
        )

    def request_cancellation(self, *, now: datetime) -> AssetExtractionJob:
        if self.status in {
            AssetExtractionStatus.SUCCEEDED,
            AssetExtractionStatus.FAILED,
            AssetExtractionStatus.UNSUPPORTED,
            AssetExtractionStatus.CANCELED,
            AssetExtractionStatus.STALE,
        }:
            return self
        if self.status == AssetExtractionStatus.PENDING:
            return self.mark_canceled(
                now=now,
                code="asset_extraction.canceled",
                message="Extraction was canceled before worker execution",
            )
        return replace(
            self,
            cancellation_requested_at=now,
            metadata=_safe_metadata(
                {
                    **dict(self.metadata),
                    "processing_stage": "cancel_requested",
                    "progress_message": "Cancellation requested",
                }
            ),
            updated_at=now,
        )

    def mark_succeeded(
        self,
        *,
        now: datetime,
        result_document_ids: tuple[str, ...],
        parser_name: str,
        parser_version: str | None,
        model_version: str | None,
        metadata: Mapping[str, object] | None = None,
    ) -> AssetExtractionJob:
        if self.status != AssetExtractionStatus.RUNNING:
            raise MemoryValidationError("Asset extraction job must be running to succeed")
        if not result_document_ids and not metadata:
            raise MemoryValidationError("Successful extraction requires documents or metadata")
        return replace(
            self,
            status=AssetExtractionStatus.SUCCEEDED,
            result_document_ids=tuple(str(value) for value in result_document_ids if str(value)),
            parser_name=_optional(parser_name, max_chars=120) or "unknown",
            parser_version=_optional(parser_version, max_chars=120),
            model_version=_optional(model_version, max_chars=120),
            metadata=_safe_metadata(
                {
                    **dict(self.metadata),
                    **dict(metadata or {}),
                    "processing_stage": "succeeded",
                    "progress_percent": 100,
                    "progress_message": "Extraction complete",
                }
            ),
            safe_error_code=None,
            safe_error_message=None,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            retry_after_at=None,
            retry_disposition=None,
            cancellation_requested_at=None,
            finished_at=now,
            updated_at=now,
        )

    def mark_failed(
        self,
        *,
        now: datetime,
        code: str,
        message: str,
        metadata: Mapping[str, object] | None = None,
        retry_disposition: ExtractionRetryDisposition = ExtractionRetryDisposition.RETRYABLE,
        retry_after_at: datetime | None = None,
    ) -> AssetExtractionJob:
        if self.status == AssetExtractionStatus.SUCCEEDED:
            raise MemoryValidationError("Succeeded extraction job cannot fail")
        return replace(
            self,
            status=AssetExtractionStatus.FAILED,
            safe_error_code=_required(code, "safe_error_code", max_chars=120),
            safe_error_message=_optional(message, max_chars=MAX_EXTRACTION_ERROR_CHARS),
            metadata=_safe_metadata(
                {
                    **dict(self.metadata),
                    **dict(metadata or {}),
                    "processing_stage": "failed",
                    "progress_percent": 100,
                    "progress_message": "Extraction failed",
                }
            ),
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            retry_after_at=retry_after_at,
            retry_disposition=retry_disposition,
            finished_at=now,
            updated_at=now,
        )

    def mark_unsupported(
        self,
        *,
        now: datetime,
        code: str,
        message: str,
        metadata: Mapping[str, object] | None = None,
    ) -> AssetExtractionJob:
        if self.status == AssetExtractionStatus.SUCCEEDED:
            raise MemoryValidationError("Succeeded extraction job cannot become unsupported")
        return replace(
            self,
            status=AssetExtractionStatus.UNSUPPORTED,
            safe_error_code=_required(code, "safe_error_code", max_chars=120),
            safe_error_message=_optional(message, max_chars=MAX_EXTRACTION_ERROR_CHARS),
            metadata=_safe_metadata(
                {
                    **dict(self.metadata),
                    **dict(metadata or {}),
                    "processing_stage": "unsupported",
                    "progress_percent": 100,
                    "progress_message": "Asset type is unsupported",
                }
            ),
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            retry_after_at=None,
            retry_disposition=ExtractionRetryDisposition.PERMANENT,
            cancellation_requested_at=None,
            finished_at=now,
            updated_at=now,
        )

    def mark_canceled(
        self,
        *,
        now: datetime,
        code: str,
        message: str,
        metadata: Mapping[str, object] | None = None,
    ) -> AssetExtractionJob:
        if self.status == AssetExtractionStatus.SUCCEEDED:
            raise MemoryValidationError("Succeeded extraction job cannot be canceled")
        return replace(
            self,
            status=AssetExtractionStatus.CANCELED,
            safe_error_code=_required(code, "safe_error_code", max_chars=120),
            safe_error_message=_optional(message, max_chars=MAX_EXTRACTION_ERROR_CHARS),
            metadata=_safe_metadata(
                {
                    **dict(self.metadata),
                    **dict(metadata or {}),
                    "processing_stage": "canceled",
                    "progress_percent": 100,
                    "progress_message": "Extraction canceled",
                }
            ),
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            retry_after_at=None,
            retry_disposition=ExtractionRetryDisposition.PERMANENT,
            cancellation_requested_at=now,
            finished_at=now,
            updated_at=now,
        )

    def reset_for_retry(self, *, now: datetime) -> AssetExtractionJob:
        if self.status == AssetExtractionStatus.RUNNING:
            raise MemoryValidationError("Running extraction job cannot be retried")
        if self.status == AssetExtractionStatus.SUCCEEDED:
            raise MemoryValidationError("Succeeded extraction job does not need retry")
        return replace(
            self,
            status=AssetExtractionStatus.PENDING,
            safe_error_code=None,
            safe_error_message=None,
            metadata=_safe_metadata(
                {
                    **dict(self.metadata),
                    "processing_stage": "queued",
                    "progress_percent": 0,
                    "progress_message": "Waiting for extraction worker",
                }
            ),
            started_at=None,
            finished_at=None,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=None,
            retry_after_at=None,
            cancellation_requested_at=None,
            retry_disposition=None,
            updated_at=now,
        )


@dataclass(frozen=True)
class ExtractionArtifact:
    id: ExtractionArtifactId
    job_id: AssetExtractionJobId
    asset_id: MemoryAssetId
    artifact_type: ExtractionArtifactType
    storage_backend: str
    storage_key: str
    sha256_hex: str
    byte_size: int
    metadata: Mapping[str, object]
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        artifact_id: ExtractionArtifactId,
        job_id: AssetExtractionJobId,
        asset_id: MemoryAssetId,
        artifact_type: str,
        storage_backend: str,
        storage_key: str,
        sha256_hex: str,
        byte_size: int,
        now: datetime,
        metadata: Mapping[str, object] | None = None,
    ) -> ExtractionArtifact:
        if byte_size <= 0:
            raise MemoryValidationError("Extraction artifact byte_size must be positive")
        return cls(
            id=artifact_id,
            job_id=job_id,
            asset_id=asset_id,
            artifact_type=ExtractionArtifactType(artifact_type),
            storage_backend=_required(storage_backend, "storage_backend", max_chars=80),
            storage_key=_required(storage_key, "storage_key", max_chars=500),
            sha256_hex=_required(sha256_hex, "sha256_hex", max_chars=80).lower(),
            byte_size=byte_size,
            metadata=_safe_metadata(metadata),
            created_at=now,
        )


def _required(value: str, field: str, *, max_chars: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise MemoryValidationError(f"{field} is required")
    return normalized[:max_chars]


def _optional(value: str | None, *, max_chars: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized[:max_chars] or None


def _safe_metadata(metadata: Mapping[str, object] | None) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in dict(metadata or {}).items():
        if len(safe) >= MAX_EXTRACTION_METADATA_KEYS:
            break
        key_text = str(key).strip()[:80]
        if not key_text:
            continue
        if isinstance(value, str):
            safe[key_text] = value[:500]
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key_text] = value
    return safe

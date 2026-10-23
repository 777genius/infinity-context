"""Persist bounded extraction artifacts with compensating blob cleanup."""

from __future__ import annotations

import json
from contextlib import suppress
from hashlib import sha256

from infinity_context_core.application.asset_extraction_mapping import (
    artifact_storage_key,
    result_json,
)
from infinity_context_core.application.multimodal_manifest import (
    multimodal_manifest_artifact_candidate,
    should_store_generic_multimodal_manifest,
)
from infinity_context_core.application.safe_payload import safe_metadata, safe_metadata_text
from infinity_context_core.domain.assets import MemoryAsset
from infinity_context_core.domain.extraction import (
    AssetExtractionJob,
    ExtractionArtifact,
    ExtractionArtifactId,
)
from infinity_context_core.ports.assets import BlobStoragePort
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.extraction import (
    ExtractionArtifactCandidate,
    ExtractionLimits,
    ExtractionResult,
)
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_MIN_ARTIFACT_BYTE_LIMIT = 16_384
_MAX_ARTIFACT_BYTE_LIMIT = 5_000_000
_ARTIFACT_PREVIEW_CHARS = 1_000


async def store_artifacts(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    blob_storage: BlobStoragePort,
    clock: ClockPort,
    ids: IdGeneratorPort,
    limits: ExtractionLimits,
    artifact_storage_backend: str,
    asset: MemoryAsset,
    job: AssetExtractionJob,
    result: ExtractionResult,
    markdown: str,
) -> list[ExtractionArtifact]:
    candidates = [
        ExtractionArtifactCandidate(
            artifact_type="markdown",
            filename="extracted.md",
            content_type="text/markdown",
            content=markdown.encode("utf-8"),
            metadata={"parser": result.parser_name},
        ),
        ExtractionArtifactCandidate(
            artifact_type="extracted_json",
            filename="extracted.json",
            content_type="application/json",
            content=result_json(result).encode("utf-8"),
            metadata={"parser": result.parser_name},
        ),
    ]
    if should_store_generic_multimodal_manifest(result):
        candidates.append(
            multimodal_manifest_artifact_candidate(asset=asset, job=job, result=result)
        )
    candidates.extend(result.artifacts)
    byte_limit = _artifact_byte_limit(limits)
    stored: list[ExtractionArtifact] = []
    written_storage_keys: list[str] = []
    now = clock.now()
    try:
        for raw_candidate in candidates:
            candidate = _bounded_artifact_candidate(
                raw_candidate,
                byte_limit=byte_limit,
            )
            if not candidate.content:
                continue
            digest = sha256(candidate.content).hexdigest()
            artifact = ExtractionArtifact.create(
                artifact_id=ExtractionArtifactId(ids.new_id("artifact")),
                job_id=job.id,
                asset_id=job.asset_id,
                artifact_type=candidate.artifact_type,
                storage_backend=artifact_storage_backend,
                storage_key=artifact_storage_key(
                    space_id=str(job.space_id),
                    memory_scope_id=str(job.memory_scope_id),
                    job_id=str(job.id),
                    digest=digest,
                    filename=candidate.filename,
                ),
                sha256_hex=digest,
                byte_size=len(candidate.content),
                now=now,
                metadata={
                    "content_type": safe_metadata_text(candidate.content_type),
                    "filename": safe_metadata_text(candidate.filename),
                    "artifact_byte_limit": byte_limit,
                    **safe_metadata(candidate.metadata),
                },
            )
            await blob_storage.write_bytes(
                storage_key=artifact.storage_key,
                content=candidate.content,
            )
            written_storage_keys.append(artifact.storage_key)
            stored.append(artifact)
        if stored:
            async with uow_factory() as uow:
                persisted = []
                for artifact in stored:
                    persisted.append(await uow.asset_extractions.create_artifact(artifact))
                await uow.commit()
            return persisted
        return []
    except Exception:
        for storage_key in written_storage_keys:
            with suppress(Exception):
                await blob_storage.delete(storage_key=storage_key)
        raise


def _artifact_byte_limit(limits: ExtractionLimits) -> int:
    requested = max(1, int(limits.max_output_chars)) * 4
    return min(max(requested, _MIN_ARTIFACT_BYTE_LIMIT), _MAX_ARTIFACT_BYTE_LIMIT)


def _bounded_artifact_candidate(
    candidate: ExtractionArtifactCandidate,
    *,
    byte_limit: int,
) -> ExtractionArtifactCandidate:
    if len(candidate.content) <= byte_limit:
        return candidate
    original_size = len(candidate.content)
    return ExtractionArtifactCandidate(
        artifact_type=candidate.artifact_type,
        filename=_truncated_artifact_filename(candidate.filename),
        content_type="application/json",
        content=_artifact_summary_bytes(
            candidate,
            original_size=original_size,
            byte_limit=byte_limit,
        ),
        metadata={
            **candidate.metadata,
            "artifact_truncated": True,
            "artifact_original_byte_size": original_size,
            "artifact_original_content_type": candidate.content_type,
            "artifact_original_filename": candidate.filename,
        },
    )


def _artifact_summary_bytes(
    candidate: ExtractionArtifactCandidate,
    *,
    original_size: int,
    byte_limit: int,
) -> bytes:
    preview = safe_metadata_text(
        candidate.content[: min(original_size, _ARTIFACT_PREVIEW_CHARS * 4)].decode(
            "utf-8",
            errors="replace",
        ),
        limit=_ARTIFACT_PREVIEW_CHARS,
    )
    payload = {
        "truncated": True,
        "reason": "artifact_byte_limit",
        "original_byte_size": original_size,
        "byte_limit": byte_limit,
        "original_filename": safe_metadata_text(candidate.filename),
        "original_content_type": safe_metadata_text(candidate.content_type),
        "preview": preview,
    }
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(content) <= byte_limit:
        return content
    payload["preview"] = ""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _truncated_artifact_filename(filename: str) -> str:
    safe_name = filename.strip() or "artifact"
    if safe_name.endswith(".truncated.json"):
        return safe_name
    return f"{safe_name}.truncated.json"

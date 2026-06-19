"""Canonical multimodal artifact evidence retrieval."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from json import JSONDecodeError
from math import isfinite

from infinity_context_core.application.context_relevance import score_query_relevance
from infinity_context_core.application.context_snippets import (
    query_focused_snippet,
    query_snippet_diagnostics,
    query_snippet_score_signals,
    source_refs_with_query_snippet,
)
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.application.safe_payload import safe_metadata_text
from infinity_context_core.application.sensitive_text import contains_sensitive_text
from infinity_context_core.application.source_refs import source_ref_location_summary
from infinity_context_core.domain.assets import AssetStatus
from infinity_context_core.domain.entities import SourceRef
from infinity_context_core.domain.extraction import ExtractionArtifact, ExtractionArtifactType
from infinity_context_core.ports.assets import BlobStoragePort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_MEDIA_MANIFEST_SCHEMA_VERSION = "infinity_context.multimodal_manifest.v1"
_MAX_MANIFEST_BYTES = 1_000_000
_MAX_EVIDENCE_CANDIDATES = 240
_MAX_EVIDENCE_TEXT_CHARS = 700
_MAX_QUOTE_PREVIEW_CHARS = 240
_MAX_JOBS_PER_SCOPE = 120
_EVIDENCE_KIND_BOOSTS = {
    "transcript_segment": 0.035,
    "ocr_region": 0.03,
    "vision_summary": 0.025,
    "document_chunk": 0.02,
    "table": 0.015,
}
_EVIDENCE_MODALITY_BOOSTS = {
    "audio": 0.012,
    "video": 0.012,
    "image": 0.01,
    "document": 0.008,
}
_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+instructions\b", re.I),
    re.compile(r"\b(system|developer|hidden)\s+(prompt|message|instructions?)\b", re.I),
    re.compile(r"\b(reveal|print|exfiltrate|leak)\s+.*\b(prompt|secret|token|key)\b", re.I),
)
_SECRET_MARKERS = (
    "authorization:",
    "bearer ",
    "api_key",
    "apikey",
    "password=",
    "password:",
    "private_key",
    "secret=",
    "sk-",
    "token=",
    "token:",
)


@dataclass(frozen=True)
class _ManifestCandidate:
    artifact: ExtractionArtifact
    job_id: str
    memory_scope_id: str


class ArtifactEvidenceContextCollector:
    """Collects prompt-safe context items from first-party media manifests."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        blob_storage: BlobStoragePort | None = None,
        max_manifest_bytes: int = _MAX_MANIFEST_BYTES,
    ) -> None:
        self._uow_factory = uow_factory
        self._blob_storage = blob_storage
        self._max_manifest_bytes = max(1, max_manifest_bytes)

    async def collect(
        self,
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
        diagnostics: dict[str, object],
    ) -> tuple[ContextItem, ...]:
        _init_diagnostics(diagnostics)
        if query.max_evidence_items <= 0:
            diagnostics["artifact_evidence_status"] = "skipped"
            return ()
        if self._blob_storage is None:
            diagnostics["artifact_evidence_status"] = "disabled"
            return ()

        manifests = await self._list_candidate_manifests(
            query=query,
            memory_scope_ids=memory_scope_ids,
            diagnostics=diagnostics,
        )
        if not manifests:
            diagnostics["artifact_evidence_status"] = "ok"
            return ()

        ranked_candidates: list[ContextItem] = []
        candidate_limit = min(
            _MAX_EVIDENCE_CANDIDATES,
            max(query.max_evidence_items * 8, query.max_evidence_items),
        )
        for candidate in manifests:
            payload = await self._read_manifest(candidate.artifact, diagnostics=diagnostics)
            if payload is None:
                continue
            diagnostics["artifact_evidence_manifests_used"] = (
                int(diagnostics["artifact_evidence_manifests_used"]) + 1
            )
            ranked_candidates.extend(
                _context_items_from_manifest(
                    candidate=candidate,
                    payload=payload,
                    query=query,
                    diagnostics=diagnostics,
                )
            )
            if len(ranked_candidates) > candidate_limit:
                ranked_candidates = sorted(
                    ranked_candidates,
                    key=_artifact_evidence_rank_key,
                )[:candidate_limit]
                diagnostics["artifact_evidence_candidate_cap_reached_count"] = (
                    int(diagnostics["artifact_evidence_candidate_cap_reached_count"]) + 1
                )
        ranked_candidates = sorted(ranked_candidates, key=_artifact_evidence_rank_key)
        items = tuple(ranked_candidates[: query.max_evidence_items])
        diagnostics["artifact_evidence_ranked_candidate_count"] = len(ranked_candidates)
        diagnostics["artifact_evidence_items_used"] = len(items)
        diagnostics["artifact_evidence_status"] = "ok"
        return items

    async def _list_candidate_manifests(
        self,
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
        diagnostics: dict[str, object],
    ) -> tuple[_ManifestCandidate, ...]:
        job_limit = min(
            _MAX_JOBS_PER_SCOPE,
            max(query.max_evidence_items * 4, query.max_evidence_items),
        )
        manifests: list[_ManifestCandidate] = []
        async with self._uow_factory() as uow:
            for memory_scope_id in memory_scope_ids:
                jobs = await uow.asset_extractions.list_for_scope(
                    space_id=str(query.space_id),
                    memory_scope_id=memory_scope_id,
                    thread_id=str(query.thread_id) if query.thread_id else None,
                    status="succeeded",
                    limit=job_limit,
                )
                diagnostics["artifact_evidence_jobs_considered"] = (
                    int(diagnostics["artifact_evidence_jobs_considered"]) + len(jobs)
                )
                for job in jobs:
                    for artifact in await uow.asset_extractions.list_artifacts(job_id=str(job.id)):
                        if artifact.artifact_type != ExtractionArtifactType.MEDIA_MANIFEST:
                            continue
                        asset = await uow.assets.get_by_id(str(artifact.asset_id))
                        if asset is None or asset.status != AssetStatus.STORED:
                            diagnostics["artifact_evidence_stale_asset_drop_count"] = (
                                int(diagnostics["artifact_evidence_stale_asset_drop_count"]) + 1
                            )
                            continue
                        manifests.append(
                            _ManifestCandidate(
                                artifact=artifact,
                                job_id=str(job.id),
                                memory_scope_id=str(job.memory_scope_id),
                            )
                        )
                        diagnostics["artifact_evidence_manifests_considered"] = (
                            int(diagnostics["artifact_evidence_manifests_considered"]) + 1
                        )
                        if len(manifests) >= job_limit:
                            return tuple(manifests)
        return tuple(manifests)

    async def _read_manifest(
        self,
        artifact: ExtractionArtifact,
        *,
        diagnostics: dict[str, object],
    ) -> Mapping[str, object] | None:
        return await read_media_manifest_payload(
            blob_storage=self._blob_storage,
            artifact=artifact,
            diagnostics=diagnostics,
            max_manifest_bytes=self._max_manifest_bytes,
        )


async def read_media_manifest_payload(
    *,
    blob_storage: BlobStoragePort,
    artifact: ExtractionArtifact,
    diagnostics: dict[str, object],
    diagnostic_prefix: str = "artifact_evidence",
    max_manifest_bytes: int = _MAX_MANIFEST_BYTES,
) -> Mapping[str, object] | None:
    if artifact.byte_size > max_manifest_bytes:
        _increment_diagnostic(diagnostics, f"{diagnostic_prefix}_manifest_too_large_count")
        return None
    try:
        content = await blob_storage.read_bytes(storage_key=artifact.storage_key)
    except Exception:
        _increment_diagnostic(diagnostics, f"{diagnostic_prefix}_read_error_count")
        return None
    if len(content) > max_manifest_bytes:
        _increment_diagnostic(diagnostics, f"{diagnostic_prefix}_manifest_too_large_count")
        return None
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, JSONDecodeError):
        _increment_diagnostic(diagnostics, f"{diagnostic_prefix}_parse_error_count")
        return None
    if not isinstance(payload, Mapping):
        _increment_diagnostic(diagnostics, f"{diagnostic_prefix}_parse_error_count")
        return None
    if payload.get("schema_version") != _MEDIA_MANIFEST_SCHEMA_VERSION:
        _increment_diagnostic(diagnostics, f"{diagnostic_prefix}_schema_skip_count")
        return None
    return payload


def context_items_from_media_manifest_payload(
    *,
    artifact: ExtractionArtifact,
    job_id: str,
    memory_scope_id: str,
    payload: Mapping[str, object],
    query: BuildContextQuery,
    diagnostics: dict[str, object],
    retrieval_source: str = "artifact_evidence",
    ranking_reason: str = "matched first-party multimodal extraction evidence",
    require_query_match: bool = True,
    extra_diagnostics: Mapping[str, object] | None = None,
    extra_provenance: Mapping[str, object] | None = None,
) -> tuple[ContextItem, ...]:
    _init_diagnostics(diagnostics)
    return _context_items_from_manifest(
        candidate=_ManifestCandidate(
            artifact=artifact,
            job_id=job_id,
            memory_scope_id=memory_scope_id,
        ),
        payload=payload,
        query=query,
        diagnostics=diagnostics,
        retrieval_source=retrieval_source,
        ranking_reason=ranking_reason,
        require_query_match=require_query_match,
        extra_diagnostics=extra_diagnostics,
        extra_provenance=extra_provenance,
    )


def _context_items_from_manifest(
    *,
    candidate: _ManifestCandidate,
    payload: Mapping[str, object],
    query: BuildContextQuery,
    diagnostics: dict[str, object],
    retrieval_source: str = "artifact_evidence",
    ranking_reason: str = "matched first-party multimodal extraction evidence",
    require_query_match: bool = True,
    extra_diagnostics: Mapping[str, object] | None = None,
    extra_provenance: Mapping[str, object] | None = None,
) -> tuple[ContextItem, ...]:
    evidence_items = payload.get("evidence_items")
    if not isinstance(evidence_items, list):
        return ()
    items: list[ContextItem] = []
    for index, raw_item in enumerate(evidence_items):
        if not isinstance(raw_item, Mapping):
            continue
        diagnostics["artifact_evidence_items_considered"] = (
            int(diagnostics["artifact_evidence_items_considered"]) + 1
        )
        raw_text = str(raw_item.get("text_preview") or "")
        text = safe_metadata_text(raw_text, limit=_MAX_EVIDENCE_TEXT_CHARS)
        if not text.strip():
            continue
        if _looks_sensitive(raw_text):
            diagnostics["artifact_evidence_sensitive_drop_count"] = (
                int(diagnostics["artifact_evidence_sensitive_drop_count"]) + 1
            )
            continue
        if _looks_like_prompt_injection(text):
            diagnostics["artifact_evidence_prompt_injection_drop_count"] = (
                int(diagnostics["artifact_evidence_prompt_injection_drop_count"]) + 1
            )
            continue
        relevance = score_query_relevance(
            query=query.query,
            text=" ".join(
                (
                    text,
                    str(raw_item.get("kind") or ""),
                    str(raw_item.get("modality") or ""),
                )
            ),
        )
        if (
            require_query_match
            and relevance.query_term_count > 0
            and relevance.unique_term_hits <= 0
        ):
            diagnostics["artifact_evidence_query_drop_count"] = (
                int(diagnostics["artifact_evidence_query_drop_count"]) + 1
            )
            continue
        artifact = candidate.artifact
        snippet = query_focused_snippet(query=query.query, text=text)
        source_refs = source_refs_with_query_snippet(
            (
                _source_ref(
                    artifact=artifact,
                    raw_item=raw_item,
                    index=index,
                    text=snippet.text if snippet else text,
                ),
            ),
            snippet,
        )
        source_ref = source_refs[0]
        confidence = _confidence(raw_item.get("confidence"))
        kind = safe_metadata_text(str(raw_item.get("kind") or "unknown"))
        modality = safe_metadata_text(str(raw_item.get("modality") or "unknown"))
        kind_boost = _evidence_kind_boost(kind)
        modality_boost = _evidence_modality_boost(modality)
        confidence_boost = _confidence_boost(confidence)
        coordinate_boost = _coordinate_boost(source_ref)
        if confidence is not None:
            diagnostics["artifact_evidence_confidence_signal_count"] = (
                int(diagnostics["artifact_evidence_confidence_signal_count"]) + 1
            )
        if coordinate_boost > 0:
            diagnostics["artifact_evidence_coordinate_signal_count"] = (
                int(diagnostics["artifact_evidence_coordinate_signal_count"]) + 1
            )
        score = min(
            0.92,
            round(
                0.68
                + relevance.score_boost
                + confidence_boost
                + coordinate_boost
                + kind_boost
                + modality_boost,
                4,
            ),
        )
        items.append(
            ContextItem(
                item_id=f"{artifact.id}:{_safe_evidence_id(raw_item, index=index)}",
                item_type="extraction_artifact",
                text=text,
                score=score,
                source_refs=source_refs,
                diagnostics={
                    "memory_scope_id": candidate.memory_scope_id,
                    "retrieval_source": retrieval_source,
                    "retrieval_sources": [retrieval_source],
                    "ranking_reason": ranking_reason,
                    "score_signals": {
                        "base_score": 0.68,
                        "final_score": score,
                        "retrieval_channel": retrieval_source,
                        "evidence_confidence": confidence,
                        "confidence_boost": confidence_boost,
                        "coordinate_boost": coordinate_boost,
                        "evidence_kind_boost": kind_boost,
                        "evidence_modality_boost": modality_boost,
                        "query_term_count": relevance.query_term_count,
                        "unique_term_hits": relevance.unique_term_hits,
                        "capped_frequency_hits": relevance.capped_frequency_hits,
                        "hit_ratio": relevance.hit_ratio,
                        "query_relevance_boost": relevance.score_boost,
                        **query_snippet_score_signals(snippet),
                    },
                    "provenance": {
                        "retrieval_sources": [retrieval_source],
                        "source_ref_count": 1,
                        "artifact_id": str(artifact.id),
                        "asset_id": str(artifact.asset_id),
                        "job_id": candidate.job_id,
                        "artifact_type": artifact.artifact_type.value,
                        "manifest_schema_version": _MEDIA_MANIFEST_SCHEMA_VERSION,
                        "evidence_kind": kind,
                        "evidence_modality": modality,
                        "evidence_confidence": confidence,
                        **source_ref_location_summary(source_refs),
                        **query_snippet_diagnostics(snippet),
                        **dict(extra_provenance or {}),
                    },
                    "artifact_id": str(artifact.id),
                    "asset_id": str(artifact.asset_id),
                    "evidence_kind": kind,
                    "evidence_modality": modality,
                    "evidence_confidence": confidence,
                    **source_ref_location_summary(source_refs),
                    **query_snippet_diagnostics(snippet),
                    **dict(extra_diagnostics or {}),
                },
            )
        )
    return tuple(items)


def _source_ref(
    *,
    artifact: ExtractionArtifact,
    raw_item: Mapping[str, object],
    index: int,
    text: str,
) -> SourceRef:
    return SourceRef(
        source_type="extraction_artifact",
        source_id=str(artifact.id),
        chunk_id=_safe_evidence_id(raw_item, index=index),
        quote_preview=safe_metadata_text(text, limit=_MAX_QUOTE_PREVIEW_CHARS),
        page_number=_positive_int(raw_item.get("page_number")),
        time_start_ms=_time_ms(raw_item, "start_ms"),
        time_end_ms=_time_ms(raw_item, "end_ms"),
        bbox=_bbox(raw_item.get("bbox")),
    )


def _safe_evidence_id(raw_item: Mapping[str, object], *, index: int) -> str:
    raw_id = safe_metadata_text(str(raw_item.get("id") or ""), limit=80).strip()
    return raw_id or f"element:{index}"


def _time_ms(raw_item: Mapping[str, object], key: str) -> int | None:
    time_range = raw_item.get("time_range")
    if not isinstance(time_range, Mapping):
        return None
    return _non_negative_int(time_range.get(key))


def _positive_int(value: object) -> int | None:
    parsed = _non_negative_int(value)
    return parsed if parsed is not None and parsed >= 1 else None


def _non_negative_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        parsed = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if not all(isfinite(item) for item in parsed):
        return None
    return (parsed[0], parsed[1], parsed[2], parsed[3])


def _confidence(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(parsed):
        return None
    return min(1.0, max(0.0, parsed))


def _confidence_boost(confidence: float | None) -> float:
    if confidence is None:
        return 0.0
    return round(confidence * 0.045, 4)


def _coordinate_boost(source_ref: SourceRef) -> float:
    coordinate_count = sum(
        (
            source_ref.page_number is not None,
            source_ref.bbox is not None,
            source_ref.time_start_ms is not None or source_ref.time_end_ms is not None,
        )
    )
    return min(0.03, round(coordinate_count * 0.012, 4))


def _evidence_kind_boost(kind: str) -> float:
    return _EVIDENCE_KIND_BOOSTS.get(kind.casefold().strip(), 0.0)


def _evidence_modality_boost(modality: str) -> float:
    return _EVIDENCE_MODALITY_BOOSTS.get(modality.casefold().strip(), 0.0)


def _artifact_evidence_rank_key(item: ContextItem) -> tuple[float, float, str, str, str]:
    diagnostics = item.diagnostics if isinstance(item.diagnostics, dict) else {}
    score_signals = diagnostics.get("score_signals")
    confidence = 0.0
    if isinstance(score_signals, dict):
        raw_confidence = score_signals.get("evidence_confidence")
        if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool):
            confidence = float(raw_confidence)
    return (
        -round(item.score, 8),
        -round(confidence, 8),
        str(diagnostics.get("asset_id") or ""),
        str(item.source_refs[0].chunk_id if item.source_refs else ""),
        item.item_id,
    )


def _looks_like_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def _looks_sensitive(text: str) -> bool:
    if contains_sensitive_text(text):
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def _init_diagnostics(diagnostics: dict[str, object]) -> None:
    diagnostics.setdefault("artifact_evidence_status", "unknown")
    for key in (
        "artifact_evidence_jobs_considered",
        "artifact_evidence_manifests_considered",
        "artifact_evidence_manifests_used",
        "artifact_evidence_items_considered",
        "artifact_evidence_items_used",
        "artifact_evidence_ranked_candidate_count",
        "artifact_evidence_candidate_cap_reached_count",
        "artifact_evidence_confidence_signal_count",
        "artifact_evidence_coordinate_signal_count",
        "artifact_evidence_query_drop_count",
        "artifact_evidence_sensitive_drop_count",
        "artifact_evidence_prompt_injection_drop_count",
        "artifact_evidence_manifest_too_large_count",
        "artifact_evidence_read_error_count",
        "artifact_evidence_parse_error_count",
        "artifact_evidence_schema_skip_count",
        "artifact_evidence_stale_asset_drop_count",
    ):
        diagnostics.setdefault(key, 0)


def _increment_diagnostic(diagnostics: dict[str, object], key: str) -> None:
    diagnostics[key] = int(diagnostics.get(key, 0)) + 1

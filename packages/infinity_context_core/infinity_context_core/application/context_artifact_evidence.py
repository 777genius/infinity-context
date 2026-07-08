"""Canonical multimodal artifact evidence retrieval."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from json import JSONDecodeError
from math import isfinite

from infinity_context_core.application.context_link_candidate_policy import (
    prompt_injection_signal_codes,
)
from infinity_context_core.application.context_media_time import (
    media_time_match_for_source_ref,
    media_time_match_score_signals,
    media_time_query_diagnostics,
    media_time_windows_from_query,
)
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_ranking import query_expansion_reason_priority
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_query_relevance_sufficient,
    query_relevance_score_signals,
    score_query_relevance,
)
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
_VISUAL_REGION_QUERY_RE = re.compile(
    r"\b(?:bbox|box|region)\b|"
    r"where\s+on\s+screen|"
    r"област[ьи]|регион|на\s+скрин[еа]|на\s+экране",
    re.IGNORECASE,
)
_DOCUMENT_LOCATION_QUERY_RE = re.compile(
    r"\b(?:page|paragraph|section)\b|"
    r"строк[аеуи]?|страниц[аеуы]?|абзац|раздел",
    re.IGNORECASE,
)
_EXTRACTED_TEXT_QUERY_RE = re.compile(
    r"\b(?:detected text|extracted text|ocr text|read text|written|what text|"
    r"what is written|what does it say)\b|"
    r"текст|написано|что\s+написано|прочитай|распознай|надпись",
    re.IGNORECASE,
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
        query_expansion_plan: QueryExpansionPlan | None = None,
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
                    query_expansion_plan=query_expansion_plan,
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
    query_expansion_plan: QueryExpansionPlan | None = None,
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
        query_expansion_plan=query_expansion_plan,
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
    query_expansion_plan: QueryExpansionPlan | None = None,
    extra_diagnostics: Mapping[str, object] | None = None,
    extra_provenance: Mapping[str, object] | None = None,
) -> tuple[ContextItem, ...]:
    evidence_items = payload.get("evidence_items")
    if not isinstance(evidence_items, list):
        return ()
    time_windows = media_time_windows_from_query(query.query)
    if time_windows:
        diagnostics["artifact_evidence_time_query_count"] = (
            int(diagnostics["artifact_evidence_time_query_count"]) + len(time_windows)
        )
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
        kind = safe_metadata_text(str(raw_item.get("kind") or "unknown"))
        modality = safe_metadata_text(str(raw_item.get("modality") or "unknown"))
        evidence_retrieval_text = " ".join(
            (
                text,
                kind,
                modality,
            )
        )
        relevance_query, expansion_reason, relevance = _best_evidence_relevance(
            query=query,
            text=evidence_retrieval_text,
            query_expansion_plan=query_expansion_plan,
        )
        artifact = candidate.artifact
        snippet = query_focused_snippet(query=relevance_query, text=text)
        evidence_text = snippet.text if snippet is not None else text
        evidence_id = _safe_evidence_id(raw_item, index=index, diagnostics=diagnostics)
        source_refs = source_refs_with_query_snippet(
            (
                _source_ref(
                    artifact=artifact,
                    raw_item=raw_item,
                    evidence_id=evidence_id,
                    text=snippet.text if snippet else text,
                    diagnostics=diagnostics,
                ),
            ),
            snippet,
            include_char_range=True,
        )
        source_ref = source_refs[0]
        missing_coordinate = (
            _missing_requested_coordinate(
                query=query.query,
                kind=kind,
                modality=modality,
                source_ref=source_ref,
            )
            if require_query_match
            else None
        )
        if missing_coordinate is not None:
            _increment_diagnostic(
                diagnostics,
                f"artifact_evidence_{missing_coordinate}_query_drop_count",
            )
            continue
        time_match = media_time_match_for_source_ref(source_ref, time_windows)
        if time_windows and time_match is None and require_query_match:
            diagnostics["artifact_evidence_time_query_drop_count"] = (
                int(diagnostics["artifact_evidence_time_query_drop_count"]) + 1
            )
            continue
        elif time_match is not None:
            diagnostics["artifact_evidence_time_query_match_count"] = (
                int(diagnostics["artifact_evidence_time_query_match_count"]) + 1
            )
        if (
            not time_windows
            and require_query_match
            and not is_query_relevance_sufficient(relevance)
        ):
            diagnostics["artifact_evidence_query_drop_count"] = (
                int(diagnostics["artifact_evidence_query_drop_count"]) + 1
            )
            continue
        confidence = _confidence(raw_item.get("confidence"))
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
                + modality_boost
                + (time_match.boost if time_match else 0.0),
                4,
            ),
        )
        score = max(
            score,
            _strong_evidence_score_floor(
                confidence=confidence,
                coordinate_boost=coordinate_boost,
                kind=kind,
                modality=modality,
                relevance=relevance,
            ),
        )
        items.append(
            ContextItem(
                item_id=f"{artifact.id}:{evidence_id}",
                item_type="extraction_artifact",
                text=evidence_text,
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
                        "query_expansion_reason": expansion_reason,
                        **query_relevance_score_signals(relevance),
                        **query_snippet_score_signals(snippet),
                        **media_time_match_score_signals(time_match),
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
                        "query_expansion_reason": expansion_reason,
                        **query_snippet_diagnostics(snippet),
                        **media_time_query_diagnostics(time_windows),
                        **dict(extra_provenance or {}),
                    },
                    "artifact_id": str(artifact.id),
                    "asset_id": str(artifact.asset_id),
                    "evidence_kind": kind,
                    "evidence_modality": modality,
                    "evidence_confidence": confidence,
                    "query_expansion_reason": expansion_reason,
                    **source_ref_location_summary(source_refs),
                    **query_snippet_diagnostics(snippet),
                    **media_time_query_diagnostics(time_windows),
                    **dict(extra_diagnostics or {}),
                },
            )
        )
    return tuple(items)


def _source_ref(
    *,
    artifact: ExtractionArtifact,
    raw_item: Mapping[str, object],
    evidence_id: str,
    text: str,
    diagnostics: dict[str, object],
) -> SourceRef:
    time_start_ms, time_end_ms = _time_range_ms(raw_item, diagnostics=diagnostics)
    return SourceRef(
        source_type="extraction_artifact",
        source_id=str(artifact.id),
        chunk_id=evidence_id,
        quote_preview=safe_metadata_text(text, limit=_MAX_QUOTE_PREVIEW_CHARS),
        page_number=_positive_int(raw_item.get("page_number")),
        time_start_ms=time_start_ms,
        time_end_ms=time_end_ms,
        bbox=_bbox(raw_item.get("bbox"), diagnostics=diagnostics),
    )


def _best_evidence_relevance(
    *,
    query: BuildContextQuery,
    text: str,
    query_expansion_plan: QueryExpansionPlan | None,
) -> tuple[str, str, QueryRelevance]:
    candidates = (
        query_expansion_plan.retrieval_queries
        if query_expansion_plan is not None
        else ()
    )
    if not candidates:
        relevance = score_query_relevance(query=query.query, text=text)
        return query.query, "original_query", relevance
    ranked = [
        (
            expansion.query,
            expansion.reason,
            score_query_relevance(query=expansion.query, text=text),
        )
        for expansion in candidates
    ]
    return max(
        ranked,
        key=lambda item: (
            _artifact_evidence_reason_intent_priority(query.query, item[1]),
            item[2].phrase_bigram_hits,
            item[2].unique_term_hits,
            query_expansion_reason_priority(item[1]),
            item[2].hit_ratio,
            item[2].score_boost,
            item[2].capped_frequency_hits,
            1 if item[1] == "original_query" else 0,
        ),
    )


def _artifact_evidence_reason_intent_priority(query: str, reason: str) -> int:
    query_key = query.casefold()
    if (
        reason == "outdoor_preference_bridge"
        and re.search(r"\b(?:prefer|preferred|preference|rather)\b", query_key)
    ):
        return 2
    return 0


def _safe_evidence_id(
    raw_item: Mapping[str, object],
    *,
    index: int,
    diagnostics: dict[str, object],
) -> str:
    fallback = f"element:{index}"
    raw_value = raw_item.get("id")
    raw_id = str(raw_value or "").strip()
    if not raw_id:
        return fallback
    if contains_sensitive_text(raw_id):
        _increment_diagnostic(diagnostics, "artifact_evidence_unsafe_evidence_id_count")
        return fallback
    redacted = safe_metadata_text(raw_id, limit=160).strip()
    token = _safe_evidence_id_token(redacted)
    if not token:
        _increment_diagnostic(diagnostics, "artifact_evidence_unsafe_evidence_id_count")
        return fallback
    if token != raw_id or len(raw_id) > 160:
        _increment_diagnostic(diagnostics, "artifact_evidence_unsafe_evidence_id_count")
    return token[:80]


def _safe_evidence_id_token(value: str) -> str:
    chars: list[str] = []
    previous_dash = False
    for char in value[:160]:
        if char.isalnum() or char in {":", "_", ".", "-"}:
            chars.append(char)
            previous_dash = False
        elif not previous_dash:
            chars.append("-")
            previous_dash = True
        if len(chars) >= 80:
            break
    return "".join(chars).strip("-_.:")


def _time_range_ms(
    raw_item: Mapping[str, object],
    *,
    diagnostics: dict[str, object],
) -> tuple[int | None, int | None]:
    time_range = raw_item.get("time_range")
    if not isinstance(time_range, Mapping):
        return None, None
    start_present = "start_ms" in time_range
    end_present = "end_ms" in time_range
    start = _non_negative_int(time_range.get("start_ms"))
    end = _non_negative_int(time_range.get("end_ms"))
    if (start_present and start is None) or (end_present and end is None):
        _increment_diagnostic(diagnostics, "artifact_evidence_invalid_time_range_count")
        return None, None
    if start is not None and end is not None and end < start:
        _increment_diagnostic(diagnostics, "artifact_evidence_invalid_time_range_count")
        return None, None
    return start, end


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


def _bbox(
    value: object,
    *,
    diagnostics: dict[str, object],
) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        _increment_diagnostic(diagnostics, "artifact_evidence_invalid_bbox_count")
        return None
    try:
        parsed = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        _increment_diagnostic(diagnostics, "artifact_evidence_invalid_bbox_count")
        return None
    if not all(isfinite(item) for item in parsed):
        _increment_diagnostic(diagnostics, "artifact_evidence_invalid_bbox_count")
        return None
    if any(item < 0 for item in parsed) or parsed[2] <= parsed[0] or parsed[3] <= parsed[1]:
        _increment_diagnostic(diagnostics, "artifact_evidence_invalid_bbox_count")
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


def _missing_requested_coordinate(
    *,
    query: str,
    kind: str,
    modality: str,
    source_ref: SourceRef,
) -> str | None:
    if (
        _VISUAL_REGION_QUERY_RE.search(query)
        and _is_visual_evidence(kind=kind, modality=modality)
        and source_ref.bbox is None
    ):
        return "visual_region"
    if (
        _DOCUMENT_LOCATION_QUERY_RE.search(query)
        and _is_document_evidence(kind=kind, modality=modality)
        and source_ref.page_number is None
        and source_ref.char_start is None
        and source_ref.char_end is None
    ):
        return "document_location"
    if (
        _EXTRACTED_TEXT_QUERY_RE.search(query)
        and _is_multimodal_evidence(kind=kind, modality=modality)
        and not _is_extracted_text_evidence(kind=kind, source_ref=source_ref)
    ):
        return "extracted_text"
    return None


def _is_visual_evidence(*, kind: str, modality: str) -> bool:
    normalized = f"{kind} {modality}".casefold()
    return any(token in normalized for token in ("image", "ocr", "vision", "keyframe"))


def _is_document_evidence(*, kind: str, modality: str) -> bool:
    normalized = f"{kind} {modality}".casefold()
    return any(token in normalized for token in ("document", "pdf", "page"))


def _is_multimodal_evidence(*, kind: str, modality: str) -> bool:
    normalized = f"{kind} {modality}".casefold()
    return any(
        token in normalized
        for token in ("audio", "document", "image", "ocr", "pdf", "video", "vision")
    )


def _is_extracted_text_evidence(*, kind: str, source_ref: SourceRef) -> bool:
    normalized = " ".join(
        (
            kind,
            source_ref.source_type,
            source_ref.source_id,
            source_ref.chunk_id or "",
        )
    ).casefold()
    return any(
        token in normalized
        for token in (
            "ocr",
            "transcript",
            "document_chunk",
            "pdf_text",
            "plain_text",
            "detected_text",
            "extracted_text",
        )
    )


def _evidence_kind_boost(kind: str) -> float:
    return _EVIDENCE_KIND_BOOSTS.get(kind.casefold().strip(), 0.0)


def _evidence_modality_boost(modality: str) -> float:
    return _EVIDENCE_MODALITY_BOOSTS.get(modality.casefold().strip(), 0.0)


def _artifact_evidence_rank_key(
    item: ContextItem,
) -> tuple[float, int, int, float, float, float, str, str, str]:
    diagnostics = item.diagnostics if isinstance(item.diagnostics, dict) else {}
    score_signals = diagnostics.get("score_signals")
    confidence = 0.0
    phrase_bigram_hits = 0
    unique_term_hits = 0
    hit_ratio = 0.0
    query_relevance_boost = 0.0
    if isinstance(score_signals, dict):
        raw_confidence = score_signals.get("evidence_confidence")
        if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool):
            confidence = float(raw_confidence)
        raw_phrase_bigram_hits = score_signals.get("phrase_bigram_hits")
        if isinstance(raw_phrase_bigram_hits, int) and not isinstance(raw_phrase_bigram_hits, bool):
            phrase_bigram_hits = raw_phrase_bigram_hits
        raw_unique_term_hits = score_signals.get("unique_term_hits")
        if isinstance(raw_unique_term_hits, int) and not isinstance(raw_unique_term_hits, bool):
            unique_term_hits = raw_unique_term_hits
        raw_hit_ratio = score_signals.get("hit_ratio")
        if isinstance(raw_hit_ratio, (int, float)) and not isinstance(raw_hit_ratio, bool):
            hit_ratio = float(raw_hit_ratio)
        raw_query_relevance_boost = score_signals.get("query_relevance_boost")
        if isinstance(raw_query_relevance_boost, (int, float)) and not isinstance(
            raw_query_relevance_boost,
            bool,
        ):
            query_relevance_boost = float(raw_query_relevance_boost)
    return (
        -round(item.score, 8),
        -phrase_bigram_hits,
        -unique_term_hits,
        -round(hit_ratio, 8),
        -round(query_relevance_boost, 8),
        -round(confidence, 8),
        str(diagnostics.get("asset_id") or ""),
        str(item.source_refs[0].chunk_id if item.source_refs else ""),
        item.item_id,
    )


def _strong_evidence_score_floor(
    *,
    confidence: float | None,
    coordinate_boost: float,
    kind: str,
    modality: str,
    relevance: QueryRelevance,
) -> float:
    if (
        confidence is not None
        and confidence >= 0.9
        and coordinate_boost > 0
        and (relevance.unique_term_hits >= 3 or relevance.phrase_bigram_hits >= 1)
        and kind.casefold().strip() in {"ocr_region", "transcript_segment"}
        and modality.casefold().strip() in {"image", "audio", "video", "document"}
    ):
        return 0.9
    return 0.0


def _looks_like_prompt_injection(text: str) -> bool:
    return bool(prompt_injection_signal_codes(text))


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
        "artifact_evidence_time_query_count",
        "artifact_evidence_time_query_match_count",
        "artifact_evidence_time_query_drop_count",
        "artifact_evidence_invalid_time_range_count",
        "artifact_evidence_invalid_bbox_count",
        "artifact_evidence_visual_region_query_drop_count",
        "artifact_evidence_document_location_query_drop_count",
        "artifact_evidence_extracted_text_query_drop_count",
        "artifact_evidence_query_drop_count",
        "artifact_evidence_sensitive_drop_count",
        "artifact_evidence_prompt_injection_drop_count",
        "artifact_evidence_unsafe_evidence_id_count",
        "artifact_evidence_manifest_too_large_count",
        "artifact_evidence_read_error_count",
        "artifact_evidence_parse_error_count",
        "artifact_evidence_schema_skip_count",
        "artifact_evidence_stale_asset_drop_count",
    ):
        diagnostics.setdefault(key, 0)


def _increment_diagnostic(diagnostics: dict[str, object], key: str) -> None:
    diagnostics[key] = int(diagnostics.get(key, 0)) + 1

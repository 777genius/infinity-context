"""Context item builders for approved context-link expansion."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.application.context_anchors import (
    anchor_context_item,
    anchor_identity_retrieval_text,
    anchor_retrieval_text,
)
from infinity_context_core.application.context_media_time import (
    enrich_context_item_with_media_time,
)
from infinity_context_core.application.context_relevance import score_query_relevance
from infinity_context_core.application.context_snippets import (
    query_focused_snippet,
    query_snippet_diagnostics,
    query_snippet_score_signals,
    source_refs_with_query_snippet,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.source_refs import (
    chunk_source_refs,
    source_ref_location_summary,
)
from infinity_context_core.domain.assets import MemoryAsset, MemoryContextLink
from infinity_context_core.domain.entities import (
    MemoryAnchor,
    MemoryChunk,
    MemoryFact,
    SourceRef,
)
from infinity_context_core.domain.extraction import (
    AssetExtractionJob,
    ExtractionArtifact,
)


def _linked_anchor_context_item(
    anchor: MemoryAnchor,
    *,
    link: MemoryContextLink,
    query_text: str,
    now: datetime | None,
) -> ContextItem:
    retrieval_text = anchor_retrieval_text(anchor)
    relevance = score_query_relevance(query=query_text, text=retrieval_text)
    identity_relevance = score_query_relevance(
        query=query_text,
        text=anchor_identity_retrieval_text(anchor),
    )
    base_item = anchor_context_item(
        anchor,
        relevance=relevance,
        identity_relevance=identity_relevance,
        now=now,
    )
    base_diagnostics = base_item.diagnostics if isinstance(base_item.diagnostics, dict) else {}
    score = min(0.94, round(max(base_item.score, _linked_item_score(link) + 0.02), 4))
    score_signals = base_diagnostics.get("score_signals")
    anchor_score_signals = score_signals if isinstance(score_signals, dict) else {}
    return ContextItem(
        item_id=str(anchor.id),
        item_type="anchor",
        text=base_item.text,
        score=score,
        source_refs=base_item.source_refs,
        diagnostics=_linked_item_diagnostics(
            link=link,
            retrieval_source="approved_context_linked_anchors",
            memory_scope_id=str(anchor.memory_scope_id),
            score=score,
            source_ref_count=len(base_item.source_refs),
            ranking_reason=(
                "approved context link connected visible evidence or memory to canonical anchor"
            ),
            score_signals_extra={
                "anchor_query_score": base_item.score,
                "anchor_kind": anchor.kind.value,
                "anchor_query_unique_term_hits": int(
                    anchor_score_signals.get("unique_term_hits") or 0
                ),
                "anchor_identity_unique_term_hits": int(
                    anchor_score_signals.get("identity_unique_term_hits") or 0
                ),
            },
            extra_provenance={
                "anchor_kind": anchor.kind.value,
                "anchor_status": anchor.status.value,
                "anchor_confidence": anchor.confidence.value,
                "normalized_key": anchor.normalized_key,
                "observed_at": anchor.observed_at.isoformat(),
                "valid_from": anchor.valid_from.isoformat() if anchor.valid_from else None,
                "valid_to": anchor.valid_to.isoformat() if anchor.valid_to else None,
                "identity_metadata": base_diagnostics.get("identity_metadata") or {},
            },
            extra_diagnostics={
                **_anchor_base_diagnostics(base_diagnostics),
                "anchor_kind": anchor.kind.value,
                "normalized_key": anchor.normalized_key,
                "confidence": anchor.confidence.value,
                "observed_at": anchor.observed_at.isoformat(),
                "updated_at": anchor.updated_at.isoformat(),
            },
        ),
    )

def _linked_chunk_context_item(
    chunk: MemoryChunk,
    *,
    link: MemoryContextLink,
    query_text: str,
) -> ContextItem:
    score = _linked_item_score(link)
    text = document_chunk_retrieval_text(text=chunk.text, metadata=chunk.metadata)
    snippet = query_focused_snippet(query=query_text, text=text)
    evidence_text = snippet.text if snippet is not None else text
    source_refs = source_refs_with_query_snippet(
        chunk_source_refs(chunk, text_preview=snippet.text if snippet else text[:200]),
        snippet,
        include_char_range=True,
    )
    return enrich_context_item_with_media_time(
        ContextItem(
            item_id=str(chunk.id),
            item_type="chunk",
            text=evidence_text,
            score=score,
            source_refs=source_refs,
            diagnostics=_linked_item_diagnostics(
                link=link,
                retrieval_source="approved_context_linked_chunks",
                memory_scope_id=str(chunk.memory_scope_id),
                score=score,
                source_ref_count=len(source_refs),
                score_signals_extra=query_snippet_score_signals(snippet),
                extra_provenance={
                    "source_type": chunk.source_type,
                    "source_id": chunk.source_external_id,
                    "chunk_id": str(chunk.id),
                    "sequence": chunk.sequence,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    **source_ref_location_summary(source_refs),
                    **query_snippet_diagnostics(snippet),
                },
                extra_diagnostics={
                    "source_type": chunk.source_type,
                    "source_id": chunk.source_external_id,
                    "chunk_sequence": chunk.sequence,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    **source_ref_location_summary(source_refs),
                    **query_snippet_diagnostics(snippet),
                },
            ),
        ),
        query_text=query_text,
    )

def _linked_fact_context_item(
    fact: MemoryFact,
    *,
    link: MemoryContextLink,
    query_text: str,
) -> ContextItem:
    score = min(0.93, round(_linked_item_score(link) + 0.015, 4))
    snippet = query_focused_snippet(query=query_text, text=fact.text)
    source_refs = source_refs_with_query_snippet(fact.source_refs, snippet)
    return enrich_context_item_with_media_time(
        ContextItem(
            item_id=str(fact.id),
            item_type="fact",
            text=fact.text,
            score=score,
            source_refs=source_refs,
            diagnostics=_linked_item_diagnostics(
                link=link,
                retrieval_source="approved_context_linked_facts",
                memory_scope_id=str(fact.memory_scope_id),
                score=score,
                source_ref_count=len(source_refs),
                score_signals_extra=query_snippet_score_signals(snippet),
                extra_provenance={
                    "fact_status": fact.status.value,
                    "fact_version": fact.version,
                    **query_snippet_diagnostics(snippet),
                },
                extra_diagnostics={
                    "confidence": fact.confidence.value,
                    "trust_level": fact.trust_level.value,
                    "updated_at": fact.updated_at.isoformat(),
                    **query_snippet_diagnostics(snippet),
                },
            ),
        ),
        query_text=query_text,
    )

def _linked_asset_context_item(asset: MemoryAsset, *, link: MemoryContextLink) -> ContextItem:
    score = min(0.9, round(_linked_item_score(link) + 0.005, 4))
    text = f"Linked file {asset.filename} ({asset.content_type}, {asset.byte_size} bytes)"
    source_refs = (
        SourceRef(
            source_type="asset",
            source_id=str(asset.id),
            quote_preview=asset.filename,
        ),
    )
    return ContextItem(
        item_id=str(asset.id),
        item_type="asset",
        text=text,
        score=score,
        source_refs=source_refs,
        diagnostics=_linked_item_diagnostics(
            link=link,
            retrieval_source="approved_context_linked_assets",
            memory_scope_id=str(asset.memory_scope_id),
            score=score,
            source_ref_count=len(source_refs),
            extra_provenance={
                "asset_id": str(asset.id),
                "asset_filename": asset.filename,
                "asset_content_type": asset.content_type,
                "asset_byte_size": asset.byte_size,
                "asset_status": asset.status.value,
            },
            extra_diagnostics={
                "asset_id": str(asset.id),
                "asset_filename": asset.filename,
                "asset_content_type": asset.content_type,
                "asset_byte_size": asset.byte_size,
                "asset_status": asset.status.value,
                **source_ref_location_summary(source_refs),
            },
        ),
    )

def _linked_extraction_artifact_context_item(
    artifact: ExtractionArtifact,
    *,
    job: AssetExtractionJob,
    asset: MemoryAsset,
    link: MemoryContextLink,
) -> ContextItem:
    score = min(0.89, round(_linked_item_score(link) + 0.01, 4))
    filename = (
        _artifact_metadata_text(artifact, "filename") or f"{artifact.artifact_type.value}.bin"
    )
    content_type = _artifact_metadata_text(artifact, "content_type") or "application/octet-stream"
    text = (
        f"Linked extraction artifact {filename} "
        f"({artifact.artifact_type.value}, {content_type}, {artifact.byte_size} bytes)"
    )
    source_refs = (
        SourceRef(
            source_type="extraction_artifact",
            source_id=str(artifact.id),
            quote_preview=filename,
        ),
    )
    return ContextItem(
        item_id=str(artifact.id),
        item_type="extraction_artifact",
        text=text,
        score=score,
        source_refs=source_refs,
        diagnostics=_linked_item_diagnostics(
            link=link,
            retrieval_source="approved_context_linked_extraction_artifacts",
            memory_scope_id=str(job.memory_scope_id),
            score=score,
            source_ref_count=len(source_refs),
            extra_provenance=_linked_extraction_artifact_extra_provenance(
                artifact=artifact,
                job=job,
                asset=asset,
                link=link,
            ),
            extra_diagnostics={
                **_linked_extraction_artifact_extra_diagnostics(
                    artifact=artifact,
                    job=job,
                    asset=asset,
                    link=link,
                ),
                **source_ref_location_summary(source_refs),
            },
        ),
    )

def _linked_item_diagnostics(
    *,
    link: MemoryContextLink,
    retrieval_source: str,
    memory_scope_id: str,
    score: float,
    source_ref_count: int,
    extra_provenance: dict[str, object],
    extra_diagnostics: dict[str, object],
    score_signals_extra: dict[str, object] | None = None,
    ranking_reason: str = "approved context link connected visible memory to related evidence",
) -> dict[str, object]:
    return {
        "memory_scope_id": memory_scope_id,
        "retrieval_source": retrieval_source,
        "retrieval_sources": [retrieval_source],
        "ranking_reason": ranking_reason,
        "context_link_id": str(link.id),
        "context_link_relation_type": link.relation_type,
        "context_link_confidence": link.confidence,
        "score_signals": {
            "base_score": 0.8,
            "final_score": score,
            "retrieval_channel": retrieval_source,
            "context_link_confidence_boost": round(score - 0.8, 4),
            "source_ref_count": source_ref_count,
            **(score_signals_extra or {}),
        },
        "provenance": {
            "retrieval_sources": [retrieval_source],
            "source_ref_count": source_ref_count,
            "context_link_id": str(link.id),
            "context_link_relation_type": link.relation_type,
            "context_link_source_type": link.source_type,
            "context_link_source_id": link.source_id,
            "context_link_target_type": link.target_type,
            "context_link_target_id": link.target_id,
            **extra_provenance,
        },
        **extra_diagnostics,
    }

def _anchor_base_diagnostics(base_diagnostics: dict[str, object]) -> dict[str, object]:
    excluded = {
        "memory_scope_id",
        "retrieval_source",
        "retrieval_sources",
        "ranking_reason",
        "score_signals",
        "provenance",
    }
    return {key: value for key, value in base_diagnostics.items() if key not in excluded}

def _linked_item_score(link: MemoryContextLink) -> float:
    confidence_boost = {
        "high": 0.06,
        "medium": 0.035,
        "low": 0.015,
    }.get(link.confidence, 0.025)
    relation_boost = 0.015 if link.relation_type in {"evidence_of", "mentions"} else 0.0
    return min(0.91, round(0.8 + confidence_boost + relation_boost, 4))

def _linked_extraction_artifact_extra_diagnostics(
    *,
    artifact: ExtractionArtifact,
    job: AssetExtractionJob,
    asset: MemoryAsset,
    link: MemoryContextLink,
) -> dict[str, object]:
    return {
        "artifact_id": str(artifact.id),
        "asset_id": str(asset.id),
        "asset_filename": asset.filename,
        "artifact_type": artifact.artifact_type.value,
        "artifact_byte_size": artifact.byte_size,
        "artifact_content_type": _artifact_metadata_text(artifact, "content_type"),
        "extraction_job_id": str(job.id),
        "context_link_id": str(link.id),
        "context_link_relation_type": link.relation_type,
        "context_link_confidence": link.confidence,
    }

def _linked_asset_manifest_extra_diagnostics(
    *,
    artifact: ExtractionArtifact,
    job: AssetExtractionJob,
    asset: MemoryAsset,
    link: MemoryContextLink,
) -> dict[str, object]:
    return {
        "artifact_id": str(artifact.id),
        "asset_id": str(asset.id),
        "asset_filename": asset.filename,
        "asset_content_type": asset.content_type,
        "asset_byte_size": asset.byte_size,
        "artifact_type": artifact.artifact_type.value,
        "artifact_byte_size": artifact.byte_size,
        "artifact_content_type": _artifact_metadata_text(artifact, "content_type"),
        "extraction_job_id": str(job.id),
        "context_link_id": str(link.id),
        "context_link_relation_type": link.relation_type,
        "context_link_confidence": link.confidence,
    }

def _linked_asset_manifest_extra_provenance(
    *,
    artifact: ExtractionArtifact,
    job: AssetExtractionJob,
    asset: MemoryAsset,
    link: MemoryContextLink,
) -> dict[str, object]:
    return {
        "artifact_id": str(artifact.id),
        "artifact_type": artifact.artifact_type.value,
        "artifact_storage_backend": artifact.storage_backend,
        "asset_id": str(asset.id),
        "asset_filename": asset.filename,
        "asset_content_type": asset.content_type,
        "extraction_job_id": str(job.id),
        "context_link_id": str(link.id),
        "context_link_relation_type": link.relation_type,
        "context_link_confidence": link.confidence,
    }

def _linked_extraction_artifact_extra_provenance(
    *,
    artifact: ExtractionArtifact,
    job: AssetExtractionJob,
    asset: MemoryAsset,
    link: MemoryContextLink,
) -> dict[str, object]:
    return {
        "artifact_id": str(artifact.id),
        "artifact_type": artifact.artifact_type.value,
        "artifact_storage_backend": artifact.storage_backend,
        "asset_id": str(asset.id),
        "asset_filename": asset.filename,
        "asset_content_type": asset.content_type,
        "extraction_job_id": str(job.id),
        "context_link_id": str(link.id),
        "context_link_relation_type": link.relation_type,
        "context_link_confidence": link.confidence,
    }

def _artifact_metadata_text(artifact: ExtractionArtifact, key: str) -> str:
    value = artifact.metadata.get(key)
    return value.strip()[:240] if isinstance(value, str) else ""

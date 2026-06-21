"""Computed evidence profiles for prompt context items."""

from __future__ import annotations

from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def with_context_item_evidence_diagnostics(
    item: ContextItem,
    diagnostics: dict[str, object],
) -> dict[str, object]:
    evidence_profile = context_item_evidence_profile(item)
    enriched = dict(diagnostics)
    enriched.update(
        {
            "evidence_profile": evidence_profile,
            "citation_count": evidence_profile["citation_count"],
            "has_citations": evidence_profile["has_citations"],
            "has_quote_preview": evidence_profile["has_quote_preview"],
            "has_precise_location": evidence_profile["has_precise_location"],
            "has_multimodal_location": evidence_profile["has_multimodal_location"],
            "source_refs_with_quote_preview_count": evidence_profile[
                "source_refs_with_quote_preview_count"
            ],
            "source_refs_with_char_range_count": evidence_profile[
                "source_refs_with_char_range_count"
            ],
            "source_refs_with_page_count": evidence_profile["source_refs_with_page_count"],
            "source_refs_with_bbox_count": evidence_profile["source_refs_with_bbox_count"],
            "source_refs_with_time_range_count": evidence_profile[
                "source_refs_with_time_range_count"
            ],
        }
    )
    provenance = (
        dict(enriched["provenance"])
        if isinstance(enriched.get("provenance"), dict)
        else {}
    )
    provenance.setdefault("source_ref_count", evidence_profile["source_ref_count"])
    provenance.setdefault(
        "evidence_profile_schema_version",
        evidence_profile["schema_version"],
    )
    enriched["provenance"] = provenance
    return enriched


def context_item_evidence_profile(item: ContextItem) -> dict[str, object]:
    refs = item.source_refs
    char_range_count = sum(1 for ref in refs if _has_char_range(ref))
    page_count = sum(1 for ref in refs if ref.page_number is not None)
    bbox_count = sum(1 for ref in refs if ref.bbox is not None)
    time_range_count = sum(1 for ref in refs if _has_time_range(ref))
    quote_preview_count = sum(1 for ref in refs if _has_quote_preview(ref))
    location_kinds = _location_kinds(
        char_range_count=char_range_count,
        page_count=page_count,
        bbox_count=bbox_count,
        time_range_count=time_range_count,
    )
    return {
        "schema_version": "context-item-evidence-profile-v1",
        "citation_count": len(refs),
        "source_ref_count": len(refs),
        "has_citations": bool(refs),
        "has_quote_preview": quote_preview_count > 0,
        "has_precise_location": bool(location_kinds),
        "has_multimodal_location": page_count > 0 or bbox_count > 0 or time_range_count > 0,
        "source_refs_with_quote_preview_count": quote_preview_count,
        "source_refs_with_char_range_count": char_range_count,
        "source_refs_with_page_count": page_count,
        "source_refs_with_bbox_count": bbox_count,
        "source_refs_with_time_range_count": time_range_count,
        "location_kinds": list(location_kinds),
    }


def _has_quote_preview(ref: SourceRef) -> bool:
    return bool(ref.quote_preview and ref.quote_preview.strip())


def _has_char_range(ref: SourceRef) -> bool:
    return ref.char_start is not None or ref.char_end is not None


def _has_time_range(ref: SourceRef) -> bool:
    return ref.time_start_ms is not None or ref.time_end_ms is not None


def _location_kinds(
    *,
    char_range_count: int,
    page_count: int,
    bbox_count: int,
    time_range_count: int,
) -> tuple[str, ...]:
    kinds: list[str] = []
    if char_range_count:
        kinds.append("char_range")
    if page_count:
        kinds.append("page")
    if bbox_count:
        kinds.append("bbox")
    if time_range_count:
        kinds.append("time_range")
    return tuple(kinds)

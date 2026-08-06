"""Anti-corruption mapping from feature-owned context to the legacy HTTP bundle."""

from __future__ import annotations

import infinity_context_core.features.context_building.public as context_building
from infinity_context_core.application import ContextBundle as LegacyContextBundle
from infinity_context_core.application import ContextItem as LegacyContextItem
from infinity_context_core.domain.entities import SourceRef


def legacy_bundle_from_canonical_facts(
    result: context_building.BuildContextResult,
    *,
    bundle_id: str,
    memory_scope_id: str,
) -> LegacyContextBundle:
    """Preserve the established response while changing fact ownership underneath it."""

    bundle = result.bundle
    items = tuple(
        LegacyContextItem(
            item_id=item.item_id,
            item_type=item.kind,
            text=item.text,
            score=item.score,
            source_refs=_source_refs(item),
            is_instruction=False,
            diagnostics={
                "memory_scope_id": memory_scope_id,
                "canonical_hydration": True,
                "role": item.role,
                "temporal": _temporal_diagnostics(item),
            },
        )
        for item in bundle.items
    )
    return LegacyContextBundle(
        bundle_id=bundle_id,
        rendered_text=bundle.rendered_evidence,
        items=items,
        token_estimate=bundle.total_estimated_tokens,
        diagnostics={
            "context_owner": context_building.FEATURE_ID,
            "canonical_hydration": True,
            "candidate_count": len(items),
            "dropped_item_count": len(bundle.dropped_items),
            "repository_isolation_mode": "canonical_facts_only",
            "non_fact_evidence_status": "deferred_until_repository_scoped",
        },
    )


def _source_refs(item: context_building.ContextItem) -> tuple[SourceRef, ...]:
    unique: dict[tuple[object, ...], SourceRef] = {}
    for evidence in item.evidence:
        for ref in evidence.source_refs:
            key = (
                ref.source_type,
                ref.source_id,
                ref.chunk_id,
                ref.char_start,
                ref.char_end,
            )
            unique.setdefault(
                key,
                SourceRef(
                    source_type=ref.source_type,
                    source_id=ref.source_id,
                    chunk_id=ref.chunk_id,
                    char_start=ref.char_start,
                    char_end=ref.char_end,
                    quote_preview=ref.quote_preview,
                ),
            )
    return tuple(unique.values())


def _temporal_diagnostics(item: context_building.ContextItem) -> dict[str, object]:
    evidence = item.evidence[0]
    return {
        "lifecycle": evidence.lifecycle_label,
        "currentness": evidence.temporal_label,
        "assurance": evidence.temporal_assurance,
        "reason_codes": evidence.temporal_reason_codes,
        "kind": evidence.temporal_kind,
        "observed_at": _iso(evidence.observed_at),
        "valid_from": _iso(evidence.valid_from),
        "valid_to": _iso(evidence.valid_to),
        "last_confirmed_at": _iso(evidence.last_confirmed_at),
        "canonical_version": evidence.canonical_version,
    }


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = ("legacy_bundle_from_canonical_facts",)

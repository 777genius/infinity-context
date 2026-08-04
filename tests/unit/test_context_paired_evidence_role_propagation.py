from __future__ import annotations

from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_paired_evidence_roles import (
    PAIRED_EVIDENCE_ROLE_MEMBERSHIPS_KEY,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef

_QUERY = (
    "How many days passed between the day Morgan started watering a herb garden "
    "and the day Morgan harvested fresh herbs?"
)
_ENDPOINT_1 = "decomposition_temporal_interval_endpoint_1"
_ENDPOINT_2 = "decomposition_temporal_interval_endpoint_2"


def test_packer_materializes_top_level_typed_endpoint_roles_for_reservation() -> None:
    result = ContextPacker().pack(
        bundle_id="ctx-paired-role-propagation",
        items=(
            *(
                _item(
                    item_id=f"noise-{index}",
                    text=f"Morgan discussed unrelated gardening details number {index}.",
                    source_id=f"benchmark:session:{index + 10}:pair:1",
                    score=0.99 - index * 0.01,
                )
                for index in range(8)
            ),
            _item(
                item_id="endpoint-1",
                text="Morgan started watering a herb garden every morning.",
                source_id="benchmark:session:1:pair:1",
                score=0.05,
                query_expansion_reason=_ENDPOINT_1,
            ),
            _item(
                item_id="endpoint-2",
                text="Morgan harvested fresh herbs from the garden later.",
                source_id="benchmark:session:2:pair:1",
                score=0.04,
                query_expansion_reason=_ENDPOINT_2,
            ),
        ),
        token_budget=2_000,
        query=_QUERY,
        max_rendered_chars=900,
    )

    selected = {item.item_id: item for item in result.bundle.items}

    assert {"endpoint-1", "endpoint-2"}.issubset(selected)
    assert selected["endpoint-2"].diagnostics["score_signals"][
        PAIRED_EVIDENCE_ROLE_MEMBERSHIPS_KEY
    ] == [_ENDPOINT_2]
    assert result.bundle.diagnostics["paired_evidence_reservations_selected"] == 2


def test_packer_does_not_override_explicit_nested_query_reason() -> None:
    result = ContextPacker().pack(
        bundle_id="ctx-paired-role-conflict",
        items=(
            _item(
                item_id="endpoint-1",
                text="Morgan started watering a herb garden every morning.",
                source_id="benchmark:session:1:pair:1",
                score=0.05,
                query_expansion_reason=_ENDPOINT_1,
                nested_query_expansion_reason="original_query",
            ),
            _item(
                item_id="endpoint-2",
                text="Morgan harvested fresh herbs from the garden later.",
                source_id="benchmark:session:2:pair:1",
                score=0.04,
                query_expansion_reason=_ENDPOINT_2,
                nested_query_expansion_reason="original_query",
            ),
        ),
        token_budget=2_000,
        query=_QUERY,
        max_rendered_chars=900,
    )

    assert result.bundle.diagnostics["paired_evidence_reservations_planned"] == 0
    assert result.bundle.diagnostics["paired_evidence_reservations_selected"] == 0


def _item(
    *,
    item_id: str,
    text: str,
    source_id: str,
    score: float,
    query_expansion_reason: str | None = None,
    nested_query_expansion_reason: str | None = None,
) -> ContextItem:
    diagnostics: dict[str, object] = {
        "memory_scope_id": "scope-paired-role-propagation",
        "retrieval_source": "keyword_chunks",
        "retrieval_sources": ["keyword_chunks"],
        "score_signals": {
            "unique_term_hits": 4,
            "distinctive_term_hits": 3,
            "phrase_bigram_hits": 2,
            "hit_ratio": 0.75,
        },
    }
    if query_expansion_reason is not None:
        diagnostics["query_expansion_reason"] = query_expansion_reason
    if nested_query_expansion_reason is not None:
        diagnostics["score_signals"]["query_expansion_reason"] = (
            nested_query_expansion_reason
        )
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="episode", source_id=source_id),),
        diagnostics=diagnostics,
    )

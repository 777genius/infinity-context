from datetime import UTC, datetime

from infinity_context_core.application.context_link_expansion import (
    _linked_fact_context_item,
)
from infinity_context_core.domain.assets import MemoryContextLink, MemoryContextLinkId
from infinity_context_core.domain.entities import (
    MemoryFact,
    MemoryFactId,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)


def test_linked_fact_context_item_uses_query_focused_source_quote() -> None:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    fact = MemoryFact.create(
        fact_id=MemoryFactId("fact_linked_launch"),
        space_id=SpaceId("space_client_app"),
        memory_scope_id=MemoryScopeId("memory_scope_default"),
        text=(
            "Intro context. " * 10
            + "Atlas launch decision was approved by Alex after the review. "
            + "Trailing context. " * 10
        ),
        kind=MemoryKind.NOTE,
        source_refs=(
            SourceRef(
                source_type="manual",
                source_id="linked-launch-note",
                quote_preview="old broad quote",
            ),
        ),
        now=now,
    )
    link = MemoryContextLink.create(
        link_id=MemoryContextLinkId("context_link_anchor_fact"),
        space_id=SpaceId("space_client_app"),
        memory_scope_id=MemoryScopeId("memory_scope_default"),
        source_type="anchor",
        source_id="anchor_event_alex",
        target_type="fact",
        target_id=str(fact.id),
        relation_type="references",
        confidence="high",
        reason="event anchor references launch decision",
        now=now,
    )

    item = _linked_fact_context_item(
        fact,
        link=link,
        query_text="Atlas launch decision Alex",
    )

    diagnostics = item.diagnostics or {}
    snippet = diagnostics["query_snippet"]
    assert "Atlas launch decision was approved by Alex" in snippet
    assert item.source_refs[0].quote_preview == snippet
    assert diagnostics["retrieval_source"] == "approved_context_linked_facts"
    assert diagnostics["context_link_relation_type"] == "references"
    assert diagnostics["score_signals"]["query_snippet_unique_term_hits"] == 4

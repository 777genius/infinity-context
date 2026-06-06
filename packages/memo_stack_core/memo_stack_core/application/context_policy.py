"""Context visibility policy helpers."""

from __future__ import annotations

from memo_stack_core.application.dto import BuildContextQuery
from memo_stack_core.domain.entities import MemoryFact


def thread_is_visible(item_thread_id: object | None, query_thread_id: object | None) -> bool:
    if query_thread_id is None:
        return True
    return item_thread_id is None or str(item_thread_id) == str(query_thread_id)


def is_graph_fact_visible(
    fact: MemoryFact,
    *,
    query: BuildContextQuery,
    profile_ids: tuple[str, ...],
) -> bool:
    return (
        str(fact.space_id) == str(query.space_id)
        and str(fact.profile_id) in profile_ids
        and fact.status.value == "active"
        and thread_is_visible(fact.thread_id, query.thread_id)
    )


def is_context_fact_visible(
    fact: MemoryFact,
    *,
    query: BuildContextQuery,
    profile_ids: tuple[str, ...],
) -> bool:
    return is_graph_fact_visible(fact, query=query, profile_ids=profile_ids) and (
        fact.classification != "restricted"
    )

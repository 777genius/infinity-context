from types import SimpleNamespace

import pytest
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_requirement_guard import (
    _apply_explicit_requirement_guard,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import MemoryScopeId, SourceRef, SpaceId
from infinity_context_server.features.context_building.context_requests import (
    ContextRequest,
    build_legacy_context_query_from_request,
)
from pydantic import ValidationError


def test_meeting_policy_keeps_projectless_candidates_in_deterministic_order() -> None:
    first = _item("meeting_turn_1", "Maria proposed shipping the billing fix on Friday.")
    second = _item("meeting_turn_2", "Vlad agreed to verify it before release.")
    query = "What did we decide about Project Atlas billing?"

    guarded, diagnostics = _apply_explicit_requirement_guard(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(first, second),
        project_anchor_policy="advisory",
    )

    assert guarded == (first, second)
    assert diagnostics["requirement_guard_status"] == "advisory_missing_project_anchor"
    assert diagnostics["requirement_guard_project_anchor_policy"] == "advisory"
    assert diagnostics["requirement_guard_project_anchor_missing"] is True
    assert diagnostics["requirement_guard_items_dropped"] == 0


def test_required_and_unknown_project_anchor_policies_remain_fail_closed() -> None:
    item = _item("meeting_turn", "The team agreed to ship the billing fix on Friday.")
    query = "What did we decide about Project Atlas billing?"

    for policy in ("required", "unknown"):
        guarded, diagnostics = _apply_explicit_requirement_guard(
            query=query,
            query_anchor_intent=build_query_anchor_intent(query),
            items=(item,),
            project_anchor_policy=policy,
        )

        assert guarded == ()
        assert diagnostics["requirement_guard_status"] == "dropped_missing_project_anchor"
        assert diagnostics["requirement_guard_items_dropped"] == 1


def test_http_request_maps_advisory_policy_and_rejects_unknown_values() -> None:
    request = ContextRequest(query="Project Atlas decision", project_anchor_policy="advisory")
    query = build_legacy_context_query_from_request(
        request,
        scope=SimpleNamespace(
            space_id=SpaceId("space_test"),
            memory_scope_ids=(MemoryScopeId("scope_test"),),
            thread_id=None,
        ),
        max_rendered_chars=4_000,
    )

    assert query.project_anchor_policy == "advisory"
    with pytest.raises(ValidationError):
        ContextRequest(query="Project Atlas decision", project_anchor_policy="unknown")


def _item(item_id: str, text: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.8,
        source_refs=(SourceRef(source_type="meeting_turn", source_id=item_id),),
        diagnostics={"retrieval_source": "vector_chunks"},
    )

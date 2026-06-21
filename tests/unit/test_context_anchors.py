from datetime import UTC, datetime

from infinity_context_core.application.anchor_extraction import (
    structured_anchor_metadata_for_label,
)
from infinity_context_core.application.context_anchors import (
    anchor_context_item,
    anchor_retrieval_text,
    related_anchor_context_item,
)
from infinity_context_core.application.context_relevance import score_query_relevance
from infinity_context_core.domain.entities import (
    Confidence,
    MemoryAnchor,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryScopeId,
    SpaceId,
)


def test_event_anchor_context_includes_project_identity_metadata() -> None:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    anchor = MemoryAnchor.create(
        anchor_id=MemoryAnchorId("anchor_call_atlas"),
        space_id=SpaceId("space_context_anchors"),
        memory_scope_id=MemoryScopeId("memory_scope_context_anchors"),
        kind=MemoryAnchorKind.EVENT,
        normalized_key="call with alex about atlas 2 hours ago",
        label="Call with Alex about Atlas 2 hours ago",
        aliases=(),
        confidence=Confidence.HIGH,
        metadata=structured_anchor_metadata_for_label(
            MemoryAnchorKind.EVENT,
            "Call with Alex about Atlas 2 hours ago",
        ),
        now=now,
    )

    retrieval_text = anchor_retrieval_text(anchor)
    item = anchor_context_item(
        anchor,
        relevance=score_query_relevance(query="Atlas call", text=retrieval_text),
        identity_relevance=score_query_relevance(
            query="Atlas call",
            text=retrieval_text,
        ),
        now=now,
    )

    assert "atlas" in retrieval_text
    assert "about: atlas" in item.text
    assert item.diagnostics["identity_scope"] == "event"
    assert item.diagnostics["identity_key"] == "event:call with aleks about atlas 2 hours ago"
    assert item.diagnostics["event_project_label"] == "atlas"
    assert item.diagnostics["project_canonical_key"] == "atlas"
    profile = item.diagnostics["anchor_identity_profile"]
    assert profile["schema_version"] == "anchor-identity-profile-v1"
    assert profile["anchor_kind"] == "event"
    assert profile["has_event_participant"] is True
    assert profile["has_event_project"] is True
    assert profile["has_event_temporal_hint"] is True
    assert profile["event_type"] == "call"
    assert "event_participant" in profile["identity_components"]
    assert "event_project" in profile["identity_components"]
    assert "event_temporal_hint" in profile["identity_components"]
    assert item.diagnostics["provenance"]["anchor_identity_profile"] == profile


def test_person_anchor_context_includes_alias_identity_terms() -> None:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    anchor = MemoryAnchor.create(
        anchor_id=MemoryAnchorId("anchor_alexander"),
        space_id=SpaceId("space_context_anchors"),
        memory_scope_id=MemoryScopeId("memory_scope_context_anchors"),
        kind=MemoryAnchorKind.PERSON,
        normalized_key="alexander",
        label="Alexander",
        aliases=("Alex", "Алекс"),
        confidence=Confidence.HIGH,
        metadata=structured_anchor_metadata_for_label(
            MemoryAnchorKind.PERSON,
            "Alexander",
            aliases=("Alex", "Алекс"),
        ),
        now=now,
    )

    retrieval_text = anchor_retrieval_text(anchor)
    item = anchor_context_item(
        anchor,
        relevance=score_query_relevance(query="Alex", text=retrieval_text),
        identity_relevance=score_query_relevance(
            query="aleks",
            text=retrieval_text,
        ),
        now=now,
    )

    assert "aleksander" in retrieval_text
    assert "aleks" in retrieval_text
    assert "identity: aleksander, aleks" in item.text
    assert item.diagnostics["alias_identity_terms"] == ["aleks"]
    assert item.diagnostics["identity_metadata"]["alias_identity_terms"] == ["aleks"]
    profile = item.diagnostics["anchor_identity_profile"]
    assert profile["primary_identity_key"] == "person:aleksander"
    assert profile["identity_scope"] == "person"
    assert profile["identity_term_count"] == 2
    assert profile["alias_identity_term_count"] == 1
    assert profile["identity_terms"] == ["aleks", "aleksander"]


def test_anchor_identity_profile_does_not_leak_sensitive_alias_metadata() -> None:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    secret = "sk-proj-anchor-secret1234567890"
    anchor = MemoryAnchor.create(
        anchor_id=MemoryAnchorId("anchor_sensitive_alias"),
        space_id=SpaceId("space_context_anchors"),
        memory_scope_id=MemoryScopeId("memory_scope_context_anchors"),
        kind=MemoryAnchorKind.PERSON,
        normalized_key="alex",
        label="Alex",
        aliases=("Alex",),
        confidence=Confidence.HIGH,
        metadata={
            "identity_scope": "person",
            "person_canonical_key": "alex",
            "alias_identity_terms": [secret],
        },
        now=now,
    )

    item = anchor_context_item(
        anchor,
        relevance=score_query_relevance(query="Alex", text=anchor_retrieval_text(anchor)),
        identity_relevance=score_query_relevance(query="Alex", text="alex"),
        now=now,
    )

    profile = item.diagnostics["anchor_identity_profile"]
    assert secret not in str(profile)
    assert profile["identity_terms"] == ["alex"]


def test_related_anchor_context_includes_identity_profile() -> None:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    source = MemoryAnchor.create(
        anchor_id=MemoryAnchorId("anchor_event"),
        space_id=SpaceId("space_context_anchors"),
        memory_scope_id=MemoryScopeId("memory_scope_context_anchors"),
        kind=MemoryAnchorKind.EVENT,
        normalized_key="call with alex about atlas",
        label="Call with Alex about Atlas",
        aliases=(),
        confidence=Confidence.HIGH,
        metadata=structured_anchor_metadata_for_label(
            MemoryAnchorKind.EVENT,
            "Call with Alex about Atlas",
        ),
        now=now,
    )
    project = MemoryAnchor.create(
        anchor_id=MemoryAnchorId("anchor_project_atlas"),
        space_id=SpaceId("space_context_anchors"),
        memory_scope_id=MemoryScopeId("memory_scope_context_anchors"),
        kind=MemoryAnchorKind.PROJECT,
        normalized_key="atlas",
        label="Atlas",
        aliases=("Project Atlas",),
        confidence=Confidence.HIGH,
        metadata=structured_anchor_metadata_for_label(
            MemoryAnchorKind.PROJECT,
            "Atlas",
            aliases=("Project Atlas",),
        ),
        now=now,
    )

    item = related_anchor_context_item(
        project,
        source_anchor=source,
        relation_type="event_project",
        relation_key="atlas",
        parent_score=0.9,
        now=now,
    )

    profile = item.diagnostics["anchor_identity_profile"]
    assert profile["anchor_kind"] == "project"
    assert profile["primary_identity_key"] == "project:atlas"
    assert profile["identity_components"] == ["project", "identity_terms"]
    assert item.diagnostics["provenance"]["anchor_identity_profile"] == profile

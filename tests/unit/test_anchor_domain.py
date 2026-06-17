from datetime import UTC, datetime

from memo_stack_core.domain.entities import (
    Confidence,
    MemoryAnchor,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)


def test_anchor_audit_reasons_redact_obvious_secret_markers() -> None:
    now = datetime(2026, 6, 17, tzinfo=UTC)
    target = _anchor(
        "anchor_target",
        label="Acme",
        confidence=Confidence.MEDIUM,
        evidence_refs=(SourceRef(source_type="manual", source_id="target-evidence"),),
        now=now,
    )
    source = _anchor(
        "anchor_source",
        label="Acme Research",
        confidence=Confidence.HIGH,
        evidence_refs=(SourceRef(source_type="manual", source_id="source-evidence"),),
        now=now,
    )

    merged = target.merge_source(
        source=source,
        reason="Authorization: Bearer sk-proj-anchor-secret-value",
        now=now,
    )
    deleted = merged.delete(reason="token sk-proj-delete-secret-value", now=now)
    split_source = merged.remove_alias(
        alias="Acme Research",
        reason="private_key sk-proj-split-secret-value",
        now=now,
    )
    merged_source = source.mark_merged_into(
        target_anchor_id=MemoryAnchorId("anchor_target"),
        reason="secret sk-proj-merge-secret-value",
        now=now,
    )

    assert merged.confidence == Confidence.HIGH
    assert {ref.source_id for ref in merged.evidence_refs} == {
        "target-evidence",
        "source-evidence",
    }
    assert merged.metadata["merge_events"][-1]["reason"] == "[redacted]"
    assert deleted.metadata["delete_reason"] == "[redacted]"
    assert split_source.metadata["split_events"][-1]["reason"] == "[redacted]"
    assert merged_source.metadata["merge_reason"] == "[redacted]"


def _anchor(
    anchor_id: str,
    *,
    label: str,
    confidence: Confidence,
    evidence_refs: tuple[SourceRef, ...],
    now: datetime,
) -> MemoryAnchor:
    return MemoryAnchor.create(
        anchor_id=MemoryAnchorId(anchor_id),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("memory_scope_1"),
        kind=MemoryAnchorKind.ORGANIZATION,
        normalized_key=label.lower(),
        label=label,
        aliases=(),
        confidence=confidence,
        evidence_refs=evidence_refs,
        now=now,
    )

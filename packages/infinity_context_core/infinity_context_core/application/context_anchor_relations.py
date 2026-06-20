"""Related canonical anchor expansion for prompt context."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.application.context_anchors import related_anchor_context_item
from infinity_context_core.application.context_policy import is_context_anchor_visible
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.domain.entities import MemoryAnchor, MemoryAnchorKind

_MAX_RELATED_ANCHOR_ITEMS = 8


def related_anchor_context_items(
    *,
    anchors: tuple[MemoryAnchor, ...],
    selected_anchor_items: tuple[tuple[MemoryAnchor, ContextItem], ...],
    query: BuildContextQuery,
    memory_scope_ids: tuple[str, ...],
    now: datetime | None,
) -> tuple[tuple[ContextItem, ...], int]:
    if not anchors or not selected_anchor_items:
        return (), 0
    anchors_by_identity = _anchors_by_identity_key(anchors)
    items: list[ContextItem] = []
    emitted_target_ids: set[str] = set()
    candidates_considered = 0
    item_limit = min(_MAX_RELATED_ANCHOR_ITEMS, max(1, query.max_facts))
    for source_anchor, source_item in selected_anchor_items:
        if source_anchor.kind != MemoryAnchorKind.EVENT:
            continue
        for target_kind, relation_type, relation_key in _event_relation_specs(source_anchor):
            candidates = anchors_by_identity.get((target_kind, relation_key.casefold()), ())
            candidates_considered += len(candidates)
            for target_anchor in candidates:
                target_id = str(target_anchor.id)
                if target_id == str(source_anchor.id) or target_id in emitted_target_ids:
                    continue
                if not is_context_anchor_visible(
                    target_anchor,
                    query=query,
                    memory_scope_ids=memory_scope_ids,
                    now=now,
                ):
                    continue
                emitted_target_ids.add(target_id)
                items.append(
                    related_anchor_context_item(
                        target_anchor,
                        source_anchor=source_anchor,
                        relation_type=relation_type,
                        relation_key=relation_key,
                        parent_score=source_item.score,
                        now=now,
                    )
                )
                if len(items) >= item_limit:
                    return tuple(items), candidates_considered
    return tuple(items), candidates_considered


def _anchors_by_identity_key(
    anchors: tuple[MemoryAnchor, ...],
) -> dict[tuple[MemoryAnchorKind, str], tuple[MemoryAnchor, ...]]:
    grouped: dict[tuple[MemoryAnchorKind, str], list[MemoryAnchor]] = {}
    for anchor in anchors:
        for key in _anchor_identity_keys(anchor):
            grouped.setdefault((anchor.kind, key), []).append(anchor)
    return {key: tuple(value) for key, value in grouped.items()}


def _anchor_identity_keys(anchor: MemoryAnchor) -> tuple[str, ...]:
    keys: list[str] = []
    for value in (
        anchor.normalized_key,
        anchor.label,
        *anchor.aliases,
        anchor.metadata.get("canonical_key"),
        anchor.metadata.get("person_canonical_key"),
        anchor.metadata.get("project_canonical_key"),
        anchor.metadata.get("organization_canonical_key"),
    ):
        text = _metadata_key(value)
        if text:
            keys.append(text)
    alias_terms = anchor.metadata.get("alias_identity_terms")
    if isinstance(alias_terms, (list, tuple)):
        keys.extend(text for item in alias_terms if (text := _metadata_key(item)))
    return _dedupe_keys(keys)


def _event_relation_specs(
    anchor: MemoryAnchor,
) -> tuple[tuple[MemoryAnchorKind, str, str], ...]:
    participant_key = _metadata_key(anchor.metadata.get("event_participant_canonical_key"))
    if not participant_key:
        participant_key = _metadata_key(anchor.metadata.get("event_participant_label"))
    project_key = _metadata_key(
        anchor.metadata.get("event_project_canonical_key")
        or anchor.metadata.get("project_canonical_key")
    )
    if not project_key:
        project_key = _metadata_key(anchor.metadata.get("event_project_label"))
    specs: list[tuple[MemoryAnchorKind, str, str]] = []
    if participant_key:
        specs.append((MemoryAnchorKind.PERSON, "event_participant", participant_key))
    if project_key:
        specs.append((MemoryAnchorKind.PROJECT, "event_project", project_key))
    return tuple(specs)


def _metadata_key(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().casefold().split())[:160]


def _dedupe_keys(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)

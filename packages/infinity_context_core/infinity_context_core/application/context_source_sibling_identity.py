"""Source-sibling source identity and seed-group policies."""

from __future__ import annotations

import re

from infinity_context_core.application.context_source_sibling_contracts import _SourceGroupSeed
from infinity_context_core.application.context_source_sibling_patterns import (
    _MAX_SOURCE_GROUPS,
    _SOURCE_GROUP_SUFFIXES,
    _TURN_SOURCE_ID_RE,
)
from infinity_context_core.domain.entities import MemoryChunk


def source_group_seed_turns(
    seed_chunks: tuple[MemoryChunk, ...],
) -> dict[str, _SourceGroupSeed]:
    groups: dict[str, tuple[int, int, set[int], bool]] = {}
    for chunk in seed_chunks:
        marker = source_turn_marker(chunk.source_external_id)
        if marker is None:
            group = _source_session_group(
                chunk.source_external_id,
                allow_opaque_document_source=getattr(chunk, "document_id", None) is not None,
            )
            if group is None:
                continue
            if group not in groups:
                groups[group] = (len(groups), 0, set(), True)
            else:
                priority, primary_turn, turns, _ = groups[group]
                groups[group] = (priority, primary_turn, turns, True)
            if len(groups) >= _MAX_SOURCE_GROUPS:
                break
            continue
        group, turn = marker
        if group not in groups:
            groups[group] = (len(groups), turn, set(), False)
        priority, primary_turn, turns, group_level = groups[group]
        turns.add(turn)
        groups[group] = (priority, primary_turn or turn, turns, group_level)
        if len(groups) >= _MAX_SOURCE_GROUPS:
            break
    return {
        group: _SourceGroupSeed(
            priority=priority,
            primary_turn=primary_turn,
            turns=frozenset(turns),
            group_level=group_level,
        )
        for group, (priority, primary_turn, turns, group_level) in groups.items()
    }


def source_sibling_seed_group(chunk: MemoryChunk) -> str:
    """Return one seed chunk's source group without admitting a group collection."""

    marker = source_turn_marker(chunk.source_external_id)
    if marker is not None:
        return marker[0]
    return (
        _source_session_group(
            chunk.source_external_id,
            allow_opaque_document_source=chunk.document_id is not None,
        )
        or ""
    )


def source_turn_marker(source_external_id: str) -> tuple[str, int] | None:
    source_id = " ".join(str(source_external_id).split())
    if not source_id:
        return None
    match = _TURN_SOURCE_ID_RE.match(source_id)
    if match is None:
        return None
    group = match.group("group").strip()
    if not group or len(group.split(":")) < 3:
        return None
    try:
        turn = int(match.group("turn"))
    except ValueError:
        return None
    return group, turn


def _source_session_group(
    source_external_id: str,
    *,
    allow_opaque_document_source: bool = False,
) -> str | None:
    source_id = " ".join(str(source_external_id).split())
    if not source_id:
        return None
    parts = source_id.split(":")
    if len(parts) >= 4 and parts[-1].casefold() in _SOURCE_GROUP_SUFFIXES:
        group = ":".join(parts[:-1])
        return group if _source_group_has_session_tail(group) else None
    if _source_group_has_session_tail(source_id):
        return source_id
    if (
        allow_opaque_document_source
        and len(parts) >= 3
        and all(part.strip() for part in parts)
        and parts[-1].casefold() not in _SOURCE_GROUP_SUFFIXES
    ):
        return source_id
    return None


def _source_group_has_session_tail(source_id: str) -> bool:
    parts = source_id.split(":")
    return bool(parts and re.fullmatch(r"session_\d+", parts[-1], re.IGNORECASE))

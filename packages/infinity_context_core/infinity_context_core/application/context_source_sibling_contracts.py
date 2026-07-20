"""Source-sibling policy value contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _SourceGroupSeed:
    priority: int
    primary_turn: int
    turns: frozenset[int]
    group_level: bool = False


@dataclass(frozen=True)
class _SourceSiblingRank:
    score: float
    group_priority: int
    turn_distance: int
    turn_delta: int
    group_level_seed: bool = False


@dataclass(frozen=True)
class _ObligationEvidenceProjection:
    """Prompt-facing evidence selected from an unchanged canonical chunk."""

    rank: int
    text: str
    spans: tuple[tuple[int, int], ...] = ()

    @property
    def applied(self) -> bool:
        return bool(self.spans)

"""Types for source-turn temporal retrieval."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceTurnRef:
    dialogue: int
    turn: int
    source_identity: str = ""

    def label(self) -> str:
        return f"D{self.dialogue}:{self.turn}"

    def _order_key(self) -> tuple[int, int]:
        return self.dialogue, self.turn

    def __lt__(self, other: SourceTurnRef) -> bool:
        return self._order_key() < other._order_key()

    def __le__(self, other: SourceTurnRef) -> bool:
        return self._order_key() <= other._order_key()

    def __gt__(self, other: SourceTurnRef) -> bool:
        return self._order_key() > other._order_key()

    def __ge__(self, other: SourceTurnRef) -> bool:
        return self._order_key() >= other._order_key()


@dataclass(frozen=True)
class SourceTurnSequenceRequest:
    after_turns: tuple[SourceTurnRef, ...] = ()
    before_turns: tuple[SourceTurnRef, ...] = ()
    near_turns: tuple[SourceTurnRef, ...] = ()
    after_turn_radius: int = 0
    before_turn_radius: int = 0
    near_turn_radius: int = 1

    @property
    def empty(self) -> bool:
        return not self.after_turns and not self.before_turns and not self.near_turns

    @property
    def has_source_identity(self) -> bool:
        return any(
            source_turn.source_identity
            for source_turn in (*self.after_turns, *self.before_turns, *self.near_turns)
        )


@dataclass(frozen=True)
class SourceTurnSequenceSignal:
    boost: float = 0.0
    reason: str = ""
    code: str = ""

    @property
    def empty(self) -> bool:
        return self.boost == 0.0

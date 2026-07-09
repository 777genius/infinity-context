"""Shared domain rerank contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainRerankSignal:
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""
    rank_signal_key: str = ""
    rank_signal: float = 0.0

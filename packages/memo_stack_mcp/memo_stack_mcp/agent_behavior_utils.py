"""Small shared helpers for agent behavior benchmark modules."""

from __future__ import annotations

import os
import re

from memo_stack_mcp.agent_behavior_types import AgentBenchFailure


def bounded_int_env(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise AgentBenchFailure(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise AgentBenchFailure(f"{name} must be between {minimum} and {maximum}")
    return value


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.:-]+", "-", value).strip("-").lower()

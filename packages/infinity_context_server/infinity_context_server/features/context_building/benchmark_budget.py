"""Character-budget policy for the hidden benchmark context route."""

from __future__ import annotations

BENCHMARK_CONTEXT_CHARS_PER_TOKEN = 4
BENCHMARK_CONTEXT_MAX_CHARS = 256_000


def benchmark_context_char_budget(
    *,
    token_budget: int,
    deployment_max_context_chars: int,
) -> int:
    """Derive the hidden benchmark character budget with a fixed hard cap."""

    if token_budget < 0:
        raise ValueError("Benchmark token budget cannot be negative")
    if not 1 <= deployment_max_context_chars <= BENCHMARK_CONTEXT_MAX_CHARS:
        raise ValueError("Deployment context character budget is outside supported bounds")
    return min(
        BENCHMARK_CONTEXT_MAX_CHARS,
        max(
            deployment_max_context_chars,
            token_budget * BENCHMARK_CONTEXT_CHARS_PER_TOKEN,
        ),
    )


__all__ = ("benchmark_context_char_budget",)

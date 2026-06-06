"""Provider cost budget adapters."""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta

from memo_stack_core.ports.adapters import AdapterCapabilities, EmbeddingPort, EmbeddingResult
from memo_stack_core.ports.clock import ClockPort


class QueryEmbeddingBudgetAdapter:
    """Rate-limit query embeddings without changing the underlying provider."""

    def __init__(
        self,
        *,
        inner: EmbeddingPort,
        clock: ClockPort,
        max_per_minute: int,
    ) -> None:
        self._inner = inner
        self._clock = clock
        self._max_per_minute = max(0, max_per_minute)
        self._window_started_at: datetime | None = None
        self._used_in_window = 0

    async def capabilities(self) -> AdapterCapabilities:
        return await self._inner.capabilities()

    async def embed_texts(self, texts: tuple[str, ...]) -> EmbeddingResult:
        if self._max_per_minute <= 0:
            return await self._inner.embed_texts(texts)
        now = self._clock.now()
        self._reset_window_if_needed(now)
        requested = max(1, len(texts))
        if self._used_in_window + requested > self._max_per_minute:
            return EmbeddingResult.degraded("embeddings.query_rate_limited", retryable=True)
        self._used_in_window += requested
        return await self._inner.embed_texts(texts)

    async def aclose(self) -> None:
        for method_name in ("aclose", "close"):
            close = getattr(self._inner, method_name, None)
            if not callable(close):
                continue
            result = close()
            if inspect.isawaitable(result):
                await result
            return

    def _reset_window_if_needed(self, now: datetime) -> None:
        if self._window_started_at is None:
            self._window_started_at = now
            self._used_in_window = 0
            return
        if now - self._window_started_at >= timedelta(minutes=1):
            self._window_started_at = now
            self._used_in_window = 0

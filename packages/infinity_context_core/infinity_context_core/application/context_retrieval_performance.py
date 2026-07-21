"""Request-local caches for pure retrieval computations.

The cache lives in the current async context, so canonical adapters and core
ranking stages can reuse pure lexical work without adding cache details to a
repository port or retaining memory text between requests.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import ParamSpec, TypeVar, cast

_MAX_PROFILE_ENTRIES = 2_048
_MAX_PROFILE_TEXT_CHARS = 4_000_000
_MAX_SINGLE_PROFILE_TEXT_CHARS = 32_000

TextVariantProfileSnapshot = tuple[
    tuple[tuple[str, int], ...],
    tuple[tuple[str, ...], ...],
]
_ProfileKey = tuple[str, int]
_P = ParamSpec("_P")
_R = TypeVar("_R")


@dataclass
class _RequestTextProfileCache:
    profiles: OrderedDict[_ProfileKey, TextVariantProfileSnapshot] = field(
        default_factory=OrderedDict
    )
    text_chars: int = 0

    def get(self, key: _ProfileKey) -> TextVariantProfileSnapshot | None:
        profile = self.profiles.get(key)
        if profile is not None:
            self.profiles.move_to_end(key)
        return profile

    def remember(
        self,
        key: _ProfileKey,
        profile: TextVariantProfileSnapshot,
    ) -> None:
        text_chars = len(key[0])
        if text_chars > _MAX_SINGLE_PROFILE_TEXT_CHARS:
            return
        existing = self.profiles.pop(key, None)
        if existing is not None:
            self.text_chars -= text_chars
        self.profiles[key] = profile
        self.text_chars += text_chars
        while (
            len(self.profiles) > _MAX_PROFILE_ENTRIES or self.text_chars > _MAX_PROFILE_TEXT_CHARS
        ):
            evicted_key, _ = self.profiles.popitem(last=False)
            self.text_chars -= len(evicted_key[0])


_REQUEST_TEXT_PROFILE_CACHE: ContextVar[_RequestTextProfileCache | None] = ContextVar(
    "infinity_context_request_text_profile_cache",
    default=None,
)


def with_request_retrieval_performance_cache(
    function: Callable[_P, Awaitable[_R]],
) -> Callable[_P, Awaitable[_R]]:
    """Reuse pure retrieval profiles within one top-level async request."""

    @wraps(function)
    async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        if _REQUEST_TEXT_PROFILE_CACHE.get() is not None:
            return await function(*args, **kwargs)
        token = _REQUEST_TEXT_PROFILE_CACHE.set(_RequestTextProfileCache())
        try:
            return await function(*args, **kwargs)
        finally:
            _REQUEST_TEXT_PROFILE_CACHE.reset(token)

    return cast(Callable[_P, Awaitable[_R]], wrapped)


def cached_text_variant_profile(
    text: str,
    *,
    min_chars: int,
) -> TextVariantProfileSnapshot | None:
    """Return an immutable lexical profile snapshot for the current request."""

    cache = _REQUEST_TEXT_PROFILE_CACHE.get()
    return cache.get((text, min_chars)) if cache is not None else None


def remember_text_variant_profile(
    text: str,
    *,
    min_chars: int,
    profile: TextVariantProfileSnapshot,
) -> None:
    """Remember a pure lexical profile only for the current request."""

    cache = _REQUEST_TEXT_PROFILE_CACHE.get()
    if cache is not None:
        cache.remember((text, min_chars), profile)


__all__ = (
    "TextVariantProfileSnapshot",
    "cached_text_variant_profile",
    "remember_text_variant_profile",
    "with_request_retrieval_performance_cache",
)

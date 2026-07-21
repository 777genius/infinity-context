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
class _RequestRetrievalCache:
    profiles: OrderedDict[_ProfileKey, TextVariantProfileSnapshot] = field(
        default_factory=OrderedDict
    )
    text_chars: int = 0
    safe_texts: OrderedDict[str, str] = field(default_factory=OrderedDict)
    safe_text_chars: int = 0

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

    def get_safe_text(self, text: str) -> str | None:
        safe_text = self.safe_texts.get(text)
        if safe_text is not None:
            self.safe_texts.move_to_end(text)
        return safe_text

    def remember_safe_text(self, text: str, safe_text: str) -> None:
        text_chars = len(text)
        if text_chars > _MAX_SINGLE_PROFILE_TEXT_CHARS:
            return
        existing = self.safe_texts.pop(text, None)
        if existing is not None:
            self.safe_text_chars -= text_chars
        self.safe_texts[text] = safe_text
        self.safe_text_chars += text_chars
        while (
            len(self.safe_texts) > _MAX_PROFILE_ENTRIES
            or self.safe_text_chars > _MAX_PROFILE_TEXT_CHARS
        ):
            evicted_text, _ = self.safe_texts.popitem(last=False)
            self.safe_text_chars -= len(evicted_text)


_REQUEST_RETRIEVAL_CACHE: ContextVar[_RequestRetrievalCache | None] = ContextVar(
    "infinity_context_request_retrieval_cache",
    default=None,
)


def with_request_retrieval_performance_cache(
    function: Callable[_P, Awaitable[_R]],
) -> Callable[_P, Awaitable[_R]]:
    """Reuse pure retrieval profiles within one top-level async request."""

    @wraps(function)
    async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        if _REQUEST_RETRIEVAL_CACHE.get() is not None:
            return await function(*args, **kwargs)
        token = _REQUEST_RETRIEVAL_CACHE.set(_RequestRetrievalCache())
        try:
            return await function(*args, **kwargs)
        finally:
            _REQUEST_RETRIEVAL_CACHE.reset(token)

    return cast(Callable[_P, Awaitable[_R]], wrapped)


def cached_text_variant_profile(
    text: str,
    *,
    min_chars: int,
) -> TextVariantProfileSnapshot | None:
    """Return an immutable lexical profile snapshot for the current request."""

    cache = _REQUEST_RETRIEVAL_CACHE.get()
    return cache.get((text, min_chars)) if cache is not None else None


def remember_text_variant_profile(
    text: str,
    *,
    min_chars: int,
    profile: TextVariantProfileSnapshot,
) -> None:
    """Remember a pure lexical profile only for the current request."""

    cache = _REQUEST_RETRIEVAL_CACHE.get()
    if cache is not None:
        cache.remember((text, min_chars), profile)


def cached_safe_metadata_text(text: str) -> str | None:
    cache = _REQUEST_RETRIEVAL_CACHE.get()
    return cache.get_safe_text(text) if cache is not None else None


def remember_safe_metadata_text(text: str, safe_text: str) -> None:
    cache = _REQUEST_RETRIEVAL_CACHE.get()
    if cache is not None:
        cache.remember_safe_text(text, safe_text)


__all__ = (
    "TextVariantProfileSnapshot",
    "cached_safe_metadata_text",
    "cached_text_variant_profile",
    "remember_safe_metadata_text",
    "remember_text_variant_profile",
    "with_request_retrieval_performance_cache",
)

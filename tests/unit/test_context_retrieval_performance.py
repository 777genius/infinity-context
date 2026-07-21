from __future__ import annotations

import asyncio

import infinity_context_core.application.context_lexical as lexical_module
import infinity_context_core.application.safe_payload as safe_payload_module
import pytest
from infinity_context_core.application.context_retrieval_performance import (
    with_request_retrieval_performance_cache,
)


def test_request_cache_profiles_each_unique_text_once_and_returns_independent_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    real_text_token_variants = lexical_module._text_token_variants

    def counting_text_token_variants(token: str) -> tuple[str, ...]:
        calls.append(token)
        return real_text_token_variants(token)

    monkeypatch.setattr(
        lexical_module,
        "_text_token_variants",
        counting_text_token_variants,
    )

    @with_request_retrieval_performance_cache
    async def exercise() -> None:
        first_counts, first_sequence = lexical_module.text_variant_profile("alpha beta gamma")
        first_counts["request-local-mutation"] = 1
        second_counts, second_sequence = lexical_module.text_variant_profile("alpha beta gamma")

        assert "request-local-mutation" not in second_counts
        assert first_sequence == second_sequence

    asyncio.run(exercise())

    assert calls == ["alpha", "beta", "gamma"]


def test_request_cache_reuses_profiles_across_counts_and_profile_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0
    real_text_token_variants = lexical_module._text_token_variants

    def counting_text_token_variants(token: str) -> tuple[str, ...]:
        nonlocal call_count
        call_count += 1
        return real_text_token_variants(token)

    monkeypatch.setattr(
        lexical_module,
        "_text_token_variants",
        counting_text_token_variants,
    )

    @with_request_retrieval_performance_cache
    async def exercise() -> None:
        counts = lexical_module.text_variant_counts("clothing pickup return")
        profile_counts, sequence = lexical_module.text_variant_profile("clothing pickup return")

        assert counts == profile_counts
        assert len(sequence) == 3

    asyncio.run(exercise())

    assert call_count == 3


def test_request_cache_is_not_shared_between_top_level_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0
    real_text_token_variants = lexical_module._text_token_variants

    def counting_text_token_variants(token: str) -> tuple[str, ...]:
        nonlocal call_count
        call_count += 1
        return real_text_token_variants(token)

    monkeypatch.setattr(
        lexical_module,
        "_text_token_variants",
        counting_text_token_variants,
    )

    @with_request_retrieval_performance_cache
    async def profile_once() -> None:
        lexical_module.text_variant_profile("bounded request")

    asyncio.run(profile_once())
    asyncio.run(profile_once())

    assert call_count == 4


def test_request_cache_skips_oversized_text_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0
    real_text_token_variants = lexical_module._text_token_variants

    def counting_text_token_variants(token: str) -> tuple[str, ...]:
        nonlocal call_count
        call_count += 1
        return real_text_token_variants(token)

    monkeypatch.setattr(
        lexical_module,
        "_text_token_variants",
        counting_text_token_variants,
    )
    oversized_text = "x" * 32_001

    @with_request_retrieval_performance_cache
    async def exercise() -> None:
        lexical_module.text_variant_profile(oversized_text)
        lexical_module.text_variant_profile(oversized_text)

    asyncio.run(exercise())

    assert call_count == 2


def test_request_cache_redacts_each_unique_diagnostic_text_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    real_redact_sensitive_text = safe_payload_module.redact_sensitive_text

    def counting_redact_sensitive_text(text: str) -> str:
        calls.append(text)
        return real_redact_sensitive_text(text)

    monkeypatch.setattr(
        safe_payload_module,
        "redact_sensitive_text",
        counting_redact_sensitive_text,
    )

    @with_request_retrieval_performance_cache
    async def exercise() -> None:
        first = safe_payload_module.safe_metadata_text("token=private-value", limit=80)
        second = safe_payload_module.safe_metadata_text("token=private-value", limit=8)

        assert "private-value" not in first
        assert second == first[:8]

    asyncio.run(exercise())

    assert calls == ["token=private-value"]

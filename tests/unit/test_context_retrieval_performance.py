from __future__ import annotations

import asyncio

import infinity_context_core.application.context_lexical as lexical_module
import infinity_context_core.application.safe_payload as safe_payload_module
import pytest
from infinity_context_core.application.context_relevance import score_query_relevance
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


def test_request_cache_reuses_approximate_term_frequency_per_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0
    real_approximate = lexical_module._approximate_term_frequency

    def counting_approximate(
        variants: tuple[str, ...],
        text_counts: object,
        **kwargs: object,
    ) -> int:
        nonlocal call_count
        call_count += 1
        return real_approximate(variants, text_counts, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        lexical_module,
        "_approximate_term_frequency",
        counting_approximate,
    )

    term = lexical_module.LexicalQueryTerm(raw="aleksandry", variants=("aleksandry",))
    text = "aleksandra visited atlas cafe"

    @with_request_retrieval_performance_cache
    async def exercise() -> int:
        first = lexical_module.query_term_frequency_for_text(term, text)
        second = lexical_module.query_term_frequency_for_text(term, text)
        assert first == second
        return first

    assert asyncio.run(exercise()) == 1
    assert call_count == 1


def test_query_term_frequency_for_text_matches_uncached_frequency() -> None:
    term = lexical_module.LexicalQueryTerm(raw="aleksandry", variants=("aleksandry",))
    text = "aleksandra visited atlas cafe"
    expected = lexical_module.query_term_frequency(term, lexical_module.text_variant_counts(text))

    @with_request_retrieval_performance_cache
    async def exercise() -> tuple[int, int]:
        with_cache = lexical_module.query_term_frequency_for_text(term, text)
        without_cache = lexical_module.query_term_frequency_for_text(term, text)
        return with_cache, without_cache

    cached_first, cached_second = asyncio.run(exercise())
    uncached = lexical_module.query_term_frequency_for_text(term, text)
    assert cached_first == cached_second == uncached == expected


def test_request_cache_builds_length_buckets_once_per_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0
    real_length_buckets = lexical_module._length_buckets

    def counting_length_buckets(text_counts: object) -> object:
        nonlocal call_count
        call_count += 1
        return real_length_buckets(text_counts)  # type: ignore[arg-type]

    monkeypatch.setattr(
        lexical_module,
        "_length_buckets",
        counting_length_buckets,
    )

    text = "aleksandra visited atlas cafe museum"
    first_term = lexical_module.LexicalQueryTerm(raw="aleksandry", variants=("aleksandry",))
    second_term = lexical_module.LexicalQueryTerm(raw="visite", variants=("visite",))

    @with_request_retrieval_performance_cache
    async def exercise() -> tuple[int, int]:
        return (
            lexical_module.query_term_frequency_for_text(first_term, text),
            lexical_module.query_term_frequency_for_text(second_term, text),
        )

    first_frequency, second_frequency = asyncio.run(exercise())
    assert first_frequency == 1
    assert second_frequency == 1
    assert call_count == 1


def test_stateless_frequency_scan_skips_length_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0
    real_length_buckets = lexical_module._length_buckets

    def counting_length_buckets(text_counts: object) -> object:
        nonlocal call_count
        call_count += 1
        return real_length_buckets(text_counts)  # type: ignore[arg-type]

    monkeypatch.setattr(
        lexical_module,
        "_length_buckets",
        counting_length_buckets,
    )

    counts = lexical_module.text_variant_counts("aleksandra visited atlas cafe museum")
    term = lexical_module.LexicalQueryTerm(raw="aleksandry", variants=("aleksandry",))

    assert lexical_module.query_term_frequency(term, counts) == 1
    assert call_count == 0


def test_approximate_term_frequency_replays_text_order_across_length_buckets() -> None:
    # The first edit-distance hit in text order is a length+1 candidate, while a
    # length-1 candidate sits in an earlier bucket; position replay must win.
    counts = lexical_module.Counter({"visitingg": 5, "visitin": 3, "atlascafe": 2})
    term = lexical_module.LexicalQueryTerm(raw="visiting", variants=("visiting",))
    buckets = lexical_module._length_buckets(counts)

    assert (
        lexical_module._approximate_term_frequency(
            ("visiting",),
            counts,
            length_buckets=buckets,
        )
        == 5
    )
    assert lexical_module.query_term_frequency(term, counts) == 5


def test_score_query_relevance_reuses_frequency_work_within_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0
    real_approximate = lexical_module._approximate_term_frequency

    def counting_approximate(
        variants: tuple[str, ...],
        text_counts: object,
        **kwargs: object,
    ) -> int:
        nonlocal call_count
        call_count += 1
        return real_approximate(variants, text_counts, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        lexical_module,
        "_approximate_term_frequency",
        counting_approximate,
    )

    query = "aleksandry"
    text = "aleksandra visited atlas cafe"

    @with_request_retrieval_performance_cache
    async def exercise() -> object:
        first = score_query_relevance(query=query, text=text)
        second = score_query_relevance(query=query, text=text)
        assert first == second
        return first

    assert asyncio.run(exercise()) is not None
    assert call_count == 1

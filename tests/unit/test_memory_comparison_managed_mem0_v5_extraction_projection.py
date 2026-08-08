from __future__ import annotations

# ruff: noqa: E402 - upstream Mem0 is an explicit parity oracle used only by tests.
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER_ROOT = ROOT / "benchmarks" / "mem0-oss-adapter-v5"
sys.path.insert(0, str(ADAPTER_ROOT))

from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_projection import (
    MEM0_V5_EXTRACTION_IMPLEMENTATION_DOMAIN,
    MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256,
    ManagedMem0V5ExtractionProjectionError,
    PinnedMem0V5ExtractionRequestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5SourceMessage,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256
from mem0_oss_adapter_v5.domain import AdapterContractError
from mem0_oss_adapter_v5.extraction_contract import build_extraction_request

_PREVIOUS_SOURCE_CONTENT_CAP_BYTES = 16_384
_SOURCE_CONTENT_CAP_BYTES = 131_072


def _unit(
    messages: tuple[tuple[str, str], ...],
    *,
    observation_date: str,
) -> ManagedMem0V5SourceUnit:
    typed = tuple(ManagedMem0V5SourceMessage(*item) for item in messages)
    unit_sha256 = canonical_sha256({"source_messages": [item.payload() for item in typed]})
    source_sha256 = hashlib.sha256(b"source").hexdigest()
    scope_sha256 = canonical_sha256(
        {
            "corpus_id": "corpus-1",
            "source_id": "source-1",
            "source_sha256": source_sha256,
            "unit_sha256": unit_sha256,
        }
    )
    return ManagedMem0V5SourceUnit(
        sequence=0,
        corpus_id="corpus-1",
        source_id="source-1",
        observation_date=observation_date,
        source_messages=typed,
        unit_identity_sha256=canonical_sha256(
            {
                "sequence": 0,
                "scope_sha256": scope_sha256,
                "unit_sha256": unit_sha256,
            }
        ),
        unit_sha256=unit_sha256,
        source_sha256=source_sha256,
        scope_sha256=scope_sha256,
    )


def _official_longmemeval_pairs() -> tuple[tuple[str, tuple[tuple[str, str], ...], str], ...]:
    dataset = os.environ.get("MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET")
    if not dataset or not Path(dataset).is_file():
        pytest.skip("MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET is opt-in")
    result: list[tuple[str, tuple[tuple[str, str], ...], str]] = []
    for raw_case in json.loads(Path(dataset).read_bytes()):
        sessions = sorted(
            enumerate(zip(raw_case["haystack_dates"], raw_case["haystack_sessions"], strict=True)),
            key=lambda item: (
                datetime.strptime(item[1][0], "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC),
                item[0],
            ),
        )
        for _index, (raw_date, messages) in sessions:
            observation_date = (
                datetime.strptime(raw_date, "%Y/%m/%d (%a) %H:%M")
                .replace(tzinfo=UTC)
                .date()
                .isoformat()
            )
            for offset in range(0, len(messages), 2):
                pair = tuple(
                    (message["role"].casefold(), message["content"])
                    for message in messages[offset : offset + 2]
                    if message["role"].casefold() in {"user", "assistant"}
                    and message["content"].strip()
                )
                if pair:
                    result.append((raw_case["question_id"], pair, observation_date))
    return tuple(result)


@pytest.mark.parametrize(
    ("messages", "current_date", "observation_date"),
    (
        ((("user", "Alice likes tea."),), "2026-08-08", "2024-03-10"),
        (
            (
                ("user", "Remember that I moved to Kyiv in spring."),
                ("assistant", "Your relocation checklist includes utilities and transit."),
            ),
            "2026-12-31",
            "2024-02-29",
        ),
        (
            (("user", "Я люблю каву ☕\nОсобливо вранці."),),
            "2027-01-01",
            "2026-08-08",
        ),
    ),
)
def test_server_native_request_hash_matches_mem0_2_0_15(
    messages: tuple[tuple[str, str], ...],
    current_date: str,
    observation_date: str,
) -> None:
    unit = _unit(messages, observation_date=observation_date)
    native = PinnedMem0V5ExtractionRequestProjector().project(
        unit,
        current_date=current_date,
    )
    upstream = build_extraction_request(
        source_messages=tuple(item.payload() for item in unit.source_messages),
        current_date=current_date,
        timestamp=observation_date,
    )
    assert native.request_body_sha256 == upstream.request_body_sha256
    assert native.request_body_bytes == len(upstream.body)
    assert native.response_format_sha256 == upstream.response_format_sha256
    assert native.response_schema_sha256 == upstream.response_schema_sha256
    assert native.requested_output_tokens == upstream.max_tokens


def test_native_and_upstream_accept_exact_128_kib_and_reject_one_byte_more() -> None:
    exact_content = "é" * (_SOURCE_CONTENT_CAP_BYTES // 2)
    exact = _unit((("user", exact_content),), observation_date="2024-03-10")
    native = PinnedMem0V5ExtractionRequestProjector().project(
        exact,
        current_date="2026-08-08",
    )
    upstream = build_extraction_request(
        source_messages=tuple(item.payload() for item in exact.source_messages),
        current_date="2026-08-08",
        timestamp=exact.observation_date,
    )

    assert len(exact_content.encode("utf-8")) == _SOURCE_CONTENT_CAP_BYTES
    assert native.request_body_sha256 == upstream.request_body_sha256
    assert native.request_body_bytes == len(upstream.body) <= 1_048_576

    oversized = _unit(
        (("user", exact_content + "x"),),
        observation_date="2024-03-10",
    )
    with pytest.raises(ManagedMem0V5ExtractionProjectionError):
        PinnedMem0V5ExtractionRequestProjector().project(
            oversized,
            current_date="2026-08-08",
        )
    with pytest.raises(AdapterContractError, match="mem0_v5_source_messages_invalid"):
        build_extraction_request(
            source_messages=tuple(item.payload() for item in oversized.source_messages),
            current_date="2026-08-08",
            timestamp=oversized.observation_date,
        )


def test_all_12_official_oversized_cases_match_native_and_upstream_request_bytes() -> None:
    pairs = _official_longmemeval_pairs()
    oversized_pairs = tuple(
        item
        for item in pairs
        if any(
            len(content.encode("utf-8")) > _PREVIOUS_SOURCE_CONTENT_CAP_BYTES
            for _role, content in item[1]
        )
    )

    assert len({case_id for case_id, _messages, _date in oversized_pairs}) == 12
    for _case_id, messages, observation_date in oversized_pairs:
        unit = _unit(messages, observation_date=observation_date)
        native = PinnedMem0V5ExtractionRequestProjector().project(
            unit,
            current_date="2026-08-08",
        )
        upstream = build_extraction_request(
            source_messages=tuple(item.payload() for item in unit.source_messages),
            current_date="2026-08-08",
            timestamp=observation_date,
        )
        assert native.request_body_sha256 == upstream.request_body_sha256
        assert native.request_body_bytes == len(upstream.body) <= 1_048_576


def test_full_official_longmemeval_500_composes_bounded_native_requests() -> None:
    pairs = _official_longmemeval_pairs()
    maximum_source_bytes = 0
    maximum_request_bytes = 0

    for _case_id, messages, observation_date in pairs:
        maximum_source_bytes = max(
            maximum_source_bytes,
            *(len(content.encode("utf-8")) for _role, content in messages),
        )
        projected = PinnedMem0V5ExtractionRequestProjector().project(
            _unit(messages, observation_date=observation_date),
            current_date="2026-08-08",
        )
        maximum_request_bytes = max(maximum_request_bytes, projected.request_body_bytes)

    assert len(pairs) == 124_344
    assert maximum_source_bytes == 76_719
    assert maximum_request_bytes <= 1_048_576


def test_preloaded_adapter_spoof_is_never_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit = _unit((("user", "Alice likes tea."),), observation_date="2024-03-10")
    calls = 0

    def attacker(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("mutable adapter boundary executed")

    foreign = ModuleType("mem0_oss_adapter_v5.extraction_contract")
    foreign.build_extraction_request = attacker
    monkeypatch.setitem(sys.modules, foreign.__name__, foreign)
    projected = PinnedMem0V5ExtractionRequestProjector().project(
        unit,
        current_date="2026-08-08",
    )
    assert calls == 0
    assert len(projected.request_body_sha256) == 64
    assert MEM0_V5_EXTRACTION_IMPLEMENTATION_DOMAIN.endswith(".v1")
    assert len(MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256) == 64

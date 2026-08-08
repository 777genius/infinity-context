from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_http_ingest_request import case_message_groups
from infinity_context_server.memory_comparison_locomo_cases import (
    _official_mem0_turn_content,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _reconstruct_managed_corpus_case,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    managed_policy_cases_from_dataset,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError


def _dataset_bytes(env_name: str) -> bytes:
    value = os.environ.get(env_name)
    if not value:
        pytest.skip(f"{env_name} is opt-in")
    path = Path(value)
    if not path.is_file():
        pytest.skip(f"{env_name} is not staged")
    return path.read_bytes()


def _locomo_cases(dataset_bytes: bytes):
    return managed_policy_cases_from_dataset(
        profile=resolve_full_comparison_profile("mem0-locomo-top200-v1"),
        dataset_bytes=dataset_bytes,
        scope="full",
        selected_case_ids=(),
    )


def _frozen_session_to_chunks(
    dataset_bytes: bytes,
) -> tuple[tuple[str, str, str], ...]:
    samples = json.loads(dataset_bytes)
    result: list[tuple[str, str, str]] = []
    for sample in samples:
        conversation = sample["conversation"]
        speaker_a = conversation["speaker_a"]
        sessions = sorted(
            (
                (key, conversation[f"{key}_date_time"], turns)
                for key, turns in conversation.items()
                if key.startswith("session_") and key.removeprefix("session_").isdigit()
            ),
            key=lambda item: _locomo_datetime(item[1]),
        )
        for _session_key, date_value, turns in sessions:
            observation_date = _locomo_datetime(date_value).date().isoformat()
            for turn in turns:
                text = turn.get("text", "")
                caption = turn.get("blip_caption", "")
                query = turn.get("query", "")
                if query and caption:
                    photo_tag = f"[Sharing image - query: {query}. The image shows: {caption}]"
                elif query:
                    photo_tag = f"[Sharing image - query for: {query}]"
                elif caption:
                    photo_tag = f"[Sharing image that shows: {caption}]"
                else:
                    photo_tag = ""
                if photo_tag:
                    text = f"{text} {photo_tag}" if text else photo_tag
                if not text:
                    continue
                role = "user" if turn.get("speaker", "") == speaker_a else "assistant"
                result.append((role, f"{turn.get('speaker', '')}: {text}", observation_date))
    return tuple(result)


def _locomo_datetime(value: str) -> datetime:
    for date_format in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
        try:
            return datetime.strptime(value, date_format).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise AssertionError(f"invalid frozen LoCoMo date: {value!r}")


def _longmemeval_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y/%m/%d (%a) %H:%M").replace(tzinfo=UTC)


def _frozen_longmemeval_pairs(
    raw: dict[str, object],
) -> tuple[tuple[tuple[dict[str, str], ...], str], ...]:
    sessions = sorted(
        enumerate(
            zip(
                raw["haystack_dates"],
                raw["haystack_sessions"],
                strict=True,
            )
        ),
        key=lambda item: (_longmemeval_datetime(item[1][0]), item[0]),
    )
    result: list[tuple[tuple[dict[str, str], ...], str]] = []
    for _index, (raw_date, messages) in sessions:
        observation_date = _longmemeval_datetime(raw_date).date().isoformat()
        for offset in range(0, len(messages), 2):
            pair = tuple(
                {"role": message["role"].casefold(), "content": message["content"]}
                for message in messages[offset : offset + 2]
                if message["role"].casefold() in {"user", "assistant"}
                and message["content"].strip()
            )
            if pair:
                result.append((pair, observation_date))
    return tuple(result)


def test_official_locomo_conv26_matches_all_419_frozen_runner_calls() -> None:
    dataset_bytes = _dataset_bytes("MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET")
    cases = _locomo_cases(dataset_bytes)
    authority = ManagedMem0V5ManifestProjector().project(
        (cases[0],),
        current_date="2026-08-08",
    )
    expected = _frozen_session_to_chunks(dataset_bytes)[:419]
    actual = tuple(
        (unit.source_messages[0].role, unit.source_messages[0].content, unit.observation_date)
        for unit in authority.units
    )

    assert authority.operation_count == len(expected) == 419
    assert actual == expected
    assert len({unit.unit_identity_sha256 for unit in authority.units}) == 419
    assert len({unit.scope_sha256 for unit in authority.units}) == 419
    assert all(len(unit.source_messages) == 1 for unit in authority.units)


def test_full_official_locomo_payload_preserves_every_frozen_byte() -> None:
    dataset_bytes = _dataset_bytes("MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET")
    raw = json.loads(dataset_bytes)
    raw_texts = tuple(
        turn["text"]
        for sample in raw
        for key, turns in sample["conversation"].items()
        if key.startswith("session_") and key.removeprefix("session_").isdigit()
        for turn in turns
    )
    assert sum(text != text.strip() for text in raw_texts) == 209
    assert sum("\n" in text for text in raw_texts) == 37

    authority = ManagedMem0V5ManifestProjector().project(
        _locomo_cases(dataset_bytes),
        current_date="2026-08-08",
    )
    expected = _frozen_session_to_chunks(dataset_bytes)
    actual = tuple(
        (unit.source_messages[0].role, unit.source_messages[0].content, unit.observation_date)
        for unit in authority.units
    )

    assert authority.operation_count == len(expected) == 5_882
    assert actual == expected
    assert len({unit.unit_identity_sha256 for unit in authority.units}) == 5_882
    assert len({unit.scope_sha256 for unit in authority.units}) == 5_882


@pytest.mark.parametrize(
    ("turn", "expected"),
    (
        ({"text": "exact text  "}, "A: exact text  "),
        (
            {"text": "", "query": "q", "blip_caption": "caption"},
            "A: [Sharing image - query: q. The image shows: caption]",
        ),
        (
            {"text": "text", "query": "q"},
            "A: text [Sharing image - query for: q]",
        ),
        (
            {"text": "text", "blip_caption": "caption"},
            "A: text [Sharing image that shows: caption]",
        ),
        ({"text": ""}, None),
    ),
)
def test_frozen_mem0_turn_content_preserves_image_and_empty_semantics(
    turn: dict[str, object],
    expected: str | None,
) -> None:
    assert _official_mem0_turn_content(turn, speaker="A") == expected


@pytest.mark.parametrize("key", ["text", "query", "blip_caption"])
def test_official_mem0_turn_content_rejects_malformed_fields(key: str) -> None:
    with pytest.raises(BenchmarkValidationError, match=key):
        _official_mem0_turn_content({"text": "valid", key: 7}, speaker="A")


def test_official_longmemeval_277_pair_payloads_remain_canonical() -> None:
    dataset_bytes = _dataset_bytes("MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET")
    cases = managed_policy_cases_from_dataset(
        profile=resolve_full_comparison_profile("mem0-longmemeval-top200-v1"),
        dataset_bytes=dataset_bytes,
        scope="canary",
        selected_case_ids=("e47becba",),
    )
    authority = ManagedMem0V5ManifestProjector().project(
        cases,
        current_date="2026-08-08",
    )
    reconstructed = _reconstruct_managed_corpus_case(
        cases[0].record,
        case_id=cases[0].case_id,
        question="Managed source projection sentinel.",
        temporal_context={},
    )
    expected = tuple(
        (messages, datetime.fromtimestamp(timestamp, tz=UTC).date().isoformat())
        for messages, timestamp, _metadata in case_message_groups(reconstructed)
        if timestamp is not None
    )
    actual = tuple(
        (
            tuple(message.payload() for message in unit.source_messages),
            unit.observation_date,
        )
        for unit in authority.units
    )

    assert authority.operation_count == len(expected) == 277
    assert actual == expected


def test_official_longmemeval_c5e8278d_preserves_whitespace_source_bytes() -> None:
    dataset_bytes = _dataset_bytes("MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET")
    raw = next(item for item in json.loads(dataset_bytes) if item["question_id"] == "c5e8278d")
    cases = managed_policy_cases_from_dataset(
        profile=resolve_full_comparison_profile("mem0-longmemeval-top200-v1"),
        dataset_bytes=dataset_bytes,
        scope="canary",
        selected_case_ids=("c5e8278d",),
    )

    authority = ManagedMem0V5ManifestProjector().project(
        cases,
        current_date="2026-08-08",
    )
    expected = _frozen_longmemeval_pairs(raw)
    actual = tuple(
        (
            tuple(message.payload() for message in unit.source_messages),
            unit.observation_date,
        )
        for unit in authority.units
    )

    assert authority.operation_count == len(expected) == 236
    assert actual == expected
    assert (
        sum(
            message["content"] != message["content"].strip()
            for pair, _date in actual
            for message in pair
        )
        == 1
    )
    assert tuple(
        message["content"].encode("utf-8") for pair, _date in actual for message in pair
    ) == tuple(message["content"].encode("utf-8") for pair, _date in expected for message in pair)


def test_full_official_longmemeval_500_project_source_byte_and_date_parity() -> None:
    dataset_bytes = _dataset_bytes("MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET")
    raw = json.loads(dataset_bytes)
    cases = managed_policy_cases_from_dataset(
        profile=resolve_full_comparison_profile("mem0-longmemeval-top200-v1"),
        dataset_bytes=dataset_bytes,
        scope="full",
        selected_case_ids=(),
    )
    projector = ManagedMem0V5ManifestProjector()
    total_units = 0
    whitespace_messages = 0

    assert len(raw) == len(cases) == 500
    for case, raw_case in zip(cases, raw, strict=True):
        authority = projector.project((case,), current_date="2026-08-08")
        expected = _frozen_longmemeval_pairs(raw_case)
        reconstructed = _reconstruct_managed_corpus_case(
            case.record,
            case_id=case.case_id,
            question="Managed source projection sentinel.",
            temporal_context={},
        )
        expected_source_hashes = tuple(
            metadata["source_sha256"]
            for _messages, _timestamp, metadata in case_message_groups(reconstructed)
        )
        actual = tuple(
            (
                tuple(message.payload() for message in unit.source_messages),
                unit.observation_date,
            )
            for unit in authority.units
        )
        assert actual == expected
        assert len({unit.source_id for unit in authority.units}) == len(expected)
        assert tuple(unit.source_sha256 for unit in authority.units) == expected_source_hashes
        assert tuple(
            message["content"].encode("utf-8") for pair, _date in actual for message in pair
        ) == tuple(
            message["content"].encode("utf-8") for pair, _date in expected for message in pair
        )
        total_units += len(actual)
        whitespace_messages += sum(
            message["content"] != message["content"].strip()
            for pair, _date in actual
            for message in pair
        )

    assert total_units == sum(len(_frozen_longmemeval_pairs(item)) for item in raw) == 124_344
    assert whitespace_messages == 92

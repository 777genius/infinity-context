from __future__ import annotations

import json

import pytest
from mem0 import __version__ as mem0_version
from mem0.configs.prompts import ADDITIVE_EXTRACTION_PROMPT, generate_additive_extraction_prompt
from mem0.memory.utils import parse_messages

from mem0_oss_adapter_v5.domain import AdapterContractError
from mem0_oss_adapter_v5.extraction_contract import (
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_RESPONSE_FORMAT_SHA256,
    EXTRACTION_SCHEMA_SHA256,
    EXTRACTION_SYSTEM_PROMPT_SHA256,
    MAX_EXTRACTED_MEMORIES,
    MAX_EXTRACTED_TEXT_BYTES,
    MAX_SOURCE_CONTENT_BYTES,
    build_extraction_request,
    extraction_response_format,
    parse_extraction_output,
    require_authentic_extraction_request,
)

CURRENT_DATE = "2026-08-06"
OBSERVATION_DATE = "2024-03-10"


def _build(messages: list[dict[str, str]], **kwargs: object) -> object:
    return build_extraction_request(
        messages,
        current_date=CURRENT_DATE,
        timestamp=OBSERVATION_DATE,
        **kwargs,
    )


def _output(memories: list[dict[str, object]]) -> str:
    return json.dumps({"memory": memories}, separators=(",", ":"))


def _memory(
    identifier: str = "0",
    *,
    text: str = "Alice likes tea.",
    attributed_to: str = "user",
    links: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": identifier,
        "text": text,
        "attributed_to": attributed_to,
        "linked_memory_ids": [] if links is None else links,
    }


def test_schema_and_prompt_authorities_are_snapshot_stable() -> None:
    assert EXTRACTION_SCHEMA_SHA256 == (
        "17c002c4bc8c4aa9d9131253ef0763fd5769c039985c65885e5877fda443120b"
    )
    assert EXTRACTION_RESPONSE_FORMAT_SHA256 == (
        "f45055c9f24f763294c0c96c3d71cd3ae494d96376596f34a6203cf171f9a516"
    )
    assert EXTRACTION_SYSTEM_PROMPT_SHA256 == (
        "ad19187a37813ef77ee156e714c0650e6ec749e0264bdc07d499bc9b24115155"
    )
    response_format = extraction_response_format()
    schema = response_format["json_schema"]["schema"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert schema["required"] == ["memory"]
    assert schema["additionalProperties"] is False
    item = schema["properties"]["memory"]["items"]
    assert item["required"] == ["id", "text", "attributed_to", "linked_memory_ids"]
    assert item["additionalProperties"] is False


def test_response_format_is_defensively_copied() -> None:
    first = extraction_response_format()
    first["json_schema"]["schema"]["additionalProperties"] = True
    assert extraction_response_format()["json_schema"]["schema"]["additionalProperties"] is False


def test_request_projection_is_golden_equal_to_pinned_mem0_2_0_15() -> None:
    assert mem0_version == "2.0.15"
    new_messages = [
        {"role": "user", "content": "Poppy visited the vet yesterday."},
        {"role": "assistant", "content": "The vet recommended a new diet."},
    ]
    existing = [{"id": f"existing-{index}", "text": f"memory {index}"} for index in range(12)]
    history = [{"role": "user", "content": f"history {index}"} for index in range(12)]
    recent = [{"id": f"recent-{index}", "text": f"recent {index}"} for index in range(22)]
    request = _build(
        new_messages,
        existing_memories=existing,
        last_k_messages=history,
        recently_extracted_memories=recent,
        summary="User has a dog named Poppy.",
        custom_instructions="Preserve pet health details.",
    )
    payload = json.loads(request.body)
    expected_existing = existing[:10]
    expected_history = history[-10:]
    expected_recent = recent[-20:]
    expected_user_prompt = generate_additive_extraction_prompt(
        summary="User has a dog named Poppy.",
        recently_extracted_memories=expected_recent,
        existing_memories=expected_existing,
        new_messages=parse_messages(new_messages),
        last_k_messages=expected_history,
        current_date=CURRENT_DATE,
        timestamp=OBSERVATION_DATE,
        custom_instructions="Preserve pet health details.",
        use_input_language=False,
    )
    assert payload["messages"] == [
        {"content": ADDITIVE_EXTRACTION_PROMPT, "role": "system"},
        {"content": expected_user_prompt, "role": "user"},
    ]
    assert request.allowed_existing_memory_ids == tuple(item["id"] for item in expected_existing)


def test_context_windows_are_selected_before_normalizing_discarded_items() -> None:
    existing = [{"id": f"existing-{index}", "text": "valid"} for index in range(10)]
    existing.extend([{"unexpected": "discarded"}] * 3)
    history = [{"unexpected": "discarded"}] * 3
    history.extend([{"role": "user", "content": f"history {index}"} for index in range(10)])
    recent = [{"unexpected": "discarded"}] * 3
    recent.extend([{"id": f"recent-{index}", "text": "valid"} for index in range(20)])
    request = _build(
        [{"role": "user", "content": "new fact"}],
        existing_memories=existing,
        last_k_messages=history,
        recently_extracted_memories=recent,
    )
    assert request.allowed_existing_memory_ids == tuple(f"existing-{index}" for index in range(10))


def test_oversized_and_bomb_sequence_inputs_fail_without_iteration() -> None:
    class BombList(list[dict[str, str]]):
        def __len__(self) -> int:
            raise AssertionError("must not inspect subclass length")

        def __iter__(self) -> object:
            raise AssertionError("must not iterate subclass")

        def __getitem__(self, _: object) -> object:
            raise AssertionError("must not index subclass")

    source = [{"role": "user", "content": "fact"}]
    with pytest.raises(AdapterContractError, match="mem0_v5_memory_context_invalid"):
        _build(source, existing_memories=BombList())
    with pytest.raises(AdapterContractError, match="mem0_v5_history_invalid"):
        _build(source, last_k_messages=BombList())

    oversized = [{"id": "same", "text": "not visited"}] * 10_001
    with pytest.raises(AdapterContractError, match="mem0_v5_memory_context_invalid"):
        _build(source, existing_memories=oversized)


def test_existing_memory_ids_are_the_only_valid_link_targets() -> None:
    raw = _output([_memory(links=["existing-poppy"])])
    memories = parse_extraction_output(
        raw,
        allowed_existing_memory_ids=("existing-poppy",),
    )
    assert memories[0].linked_memory_ids == ("existing-poppy",)
    with pytest.raises(AdapterContractError, match="mem0_v5_extraction_output_invalid"):
        parse_extraction_output(raw, allowed_existing_memory_ids=("different",))


def test_request_authenticity_rejects_mutation_new_and_subclass_impostors() -> None:
    request = _build([{"role": "user", "content": "fact"}])
    require_authentic_extraction_request(request)
    with pytest.raises(AdapterContractError, match="mem0_v5_extraction_request_unissued"):
        type(request)(
            body=request.body,
            request_body_sha256=request.request_body_sha256,
        )
    object.__setattr__(request, "body", b"{}")
    with pytest.raises(AdapterContractError, match="mem0_v5_extraction_request_unauthentic"):
        require_authentic_extraction_request(request)

    forged = object.__new__(type(request))
    with pytest.raises(AdapterContractError, match="mem0_v5_extraction_request_unauthentic"):
        require_authentic_extraction_request(forged)

    class RequestImpostor(type(request)):
        pass

    impostor = object.__new__(RequestImpostor)
    with pytest.raises(AdapterContractError, match="mem0_v5_extraction_request_unauthentic"):
        require_authentic_extraction_request(impostor)


def test_request_is_canonical_exact_and_private_content_is_not_in_repr() -> None:
    secret_content = "private-source-content"
    request = _build([{"role": "user", "content": secret_content}])
    payload = json.loads(request.body)
    assert request.request_body_sha256 == (
        "ec102d6764f5bf84712bf8ac37b6e2347a92eecca3cdb96e6b77706a22868ae6"
    )
    assert payload["model"] == "gpt-5.6-sol"
    assert payload["temperature"] == 0
    assert payload["max_tokens"] == EXTRACTION_MAX_TOKENS
    assert payload["response_format"] == extraction_response_format()
    assert [item["role"] for item in payload["messages"]] == ["system", "user"]
    assert secret_content not in repr(request)


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "system", "content": "not allowed"}],
        [{"role": "user", "content": ""}],
        [{"role": "user", "content": "x", "private": "leak"}],
        [{"role": "user", "content": "x" * (MAX_SOURCE_CONTENT_BYTES + 1)}],
    ],
)
def test_source_message_bounds_fail_closed(messages: list[dict[str, str]]) -> None:
    with pytest.raises(AdapterContractError, match="mem0_v5_source_messages_invalid"):
        _build(messages)


def test_source_message_accepts_exact_128_kib_utf8_boundary() -> None:
    content = "é" * (MAX_SOURCE_CONTENT_BYTES // 2)
    request = _build([{"role": "user", "content": content}])

    assert len(content.encode("utf-8")) == MAX_SOURCE_CONTENT_BYTES
    assert len(request.body) <= 1_048_576


def test_output_parses_exact_memories_and_commitments_hide_text() -> None:
    memories = parse_extraction_output(
        _output(
            [
                _memory(),
                _memory(
                    "1",
                    text="Alice drinks tea at breakfast.",
                    links=["existing-tea"],
                ),
            ]
        ),
        allowed_existing_memory_ids=("existing-tea",),
    )
    assert [item.id for item in memories] == ["0", "1"]
    assert memories[1].linked_memory_ids == ("existing-tea",)
    assert memories[0].text == "Alice likes tea."
    assert "Alice likes tea" not in repr(memories[0])
    assert "text" not in memories[0].commitment_payload()
    assert "text_sha256" in memories[0].commitment_payload()


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "{}",
        '{"memory":[],"memory":[]}',
        '{"memory":[],"extra":true}',
        _output([_memory("1")]),
        _output([_memory(text=" padded ")]),
        _output([_memory(attributed_to="system")]),
        _output([_memory(links=["0"])]),
        _output([_memory(links=["9"])]),
        _output([_memory() | {"private": "leak"}]),
    ],
)
def test_malformed_or_schema_drifted_output_is_rejected(raw: str) -> None:
    with pytest.raises(AdapterContractError, match="mem0_v5_extraction_output_invalid"):
        parse_extraction_output(raw)


def test_output_size_count_and_text_bounds_are_enforced() -> None:
    too_many = [
        _memory(str(index), text=f"fact {index}") for index in range(MAX_EXTRACTED_MEMORIES + 1)
    ]
    with pytest.raises(AdapterContractError, match="mem0_v5_extraction_output_invalid"):
        parse_extraction_output(_output(too_many))
    with pytest.raises(AdapterContractError, match="mem0_v5_extraction_output_invalid"):
        parse_extraction_output(_output([_memory(text="x" * (MAX_EXTRACTED_TEXT_BYTES + 1))]))


def test_nondefault_output_budget_is_rejected() -> None:
    with pytest.raises(AdapterContractError, match="mem0_v5_extraction_token_limit_invalid"):
        _build([{"role": "user", "content": "fact"}], max_tokens=2048)

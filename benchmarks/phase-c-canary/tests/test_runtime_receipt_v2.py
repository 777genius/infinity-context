from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from conftest import RUNTIME_REPO, SECRET, sign_receipt, unsigned_receipt

import phase_c_canary.runtime_binding as runtime_binding_module
from phase_c_canary.receipt import NodePublicReceiptVerifier, ReceiptVerificationError
from phase_c_canary.receipt_aggregation import RuntimeReceiptAggregator
from phase_c_canary.runtime_binding import (
    PinnedRuntimeBindingService,
    RuntimeBindingComposition,
    TrustedRuntimeBinding,
)
from phase_c_canary.runtime_receipt_v2 import (
    ProviderObservedUsage,
    RuntimeCallKind,
    RuntimeReceiptExpectation,
    RuntimeReceiptV2Boundary,
    SafeRuntimeReceipt,
)

RUNTIME_SOURCE = hashlib.sha256(b"e904ec95fda4b04c333e5a7613c7729bf7abb125").hexdigest()
OPERATION = "8" * 64
TRANSPORT_ROUTE = "http://127.0.0.1:8890/v1"
ROUTE_BINDING = hashlib.sha256(TRANSPORT_ROUTE.encode()).hexdigest()
RUNTIME_ARTIFACT = RUNTIME_REPO.parent / "artifact-manifest.json"


def trusted_binding() -> TrustedRuntimeBinding:
    return runtime_binding_service().issue()


def runtime_binding_service() -> PinnedRuntimeBindingService:
    return RuntimeBindingComposition.compose_phase_c_canary()


def expectation(receipt: dict[str, Any]) -> RuntimeReceiptExpectation:
    metadata = receipt["metadata"]
    selection = metadata["runtime_selection"]
    request = metadata["request_identity"]
    output = metadata["output_identity"]
    return RuntimeReceiptExpectation(
        model=selection["model"],
        reasoning_effort=selection["reasoning_effort"],
        service_tier=selection["service_tier"],
        base_instructions_sha256=selection["base_instructions_sha256"],
        runtime_source_sha256=RUNTIME_SOURCE,
        route_binding_sha256=ROUTE_BINDING,
        account_binding_hmac_sha256=selection["account_binding_hmac_sha256"],
        thread_id=selection["thread_id"],
        turn_id=selection["turn_id"],
        request_body_sha256=request["request_body_sha256"],
        output_text_sha256=output["output_text_sha256"],
        response_format_type=request["response_format_type"],
        response_format_sha256=request["response_format_sha256"],
        response_schema_sha256=request["response_schema_sha256"],
        requested_output_tokens=metadata["output_token_limit"]["requested_tokens"],
    )


def verify(
    receipt: dict[str, Any],
    *,
    expected: RuntimeReceiptExpectation | None = None,
    sequence: int = 0,
    kind: RuntimeCallKind = RuntimeCallKind.EXTRACTION,
    operation_id_sha256: str = OPERATION,
    binding: TrustedRuntimeBinding | None = None,
):
    return RuntimeReceiptV2Boundary(NodePublicReceiptVerifier(RUNTIME_REPO)).verify(
        receipt=receipt,
        secret=SECRET,
        expectation=expected or expectation(receipt),
        runtime_binding=binding or trusted_binding(),
        call_kind=kind,
        sequence=sequence,
        operation_id_sha256=operation_id_sha256,
    )


def test_golden_fixture_matches_immutable_public_verifier(receipt: dict[str, Any]) -> None:
    safe = verify(receipt)
    assert safe.schema_version == 2
    assert safe.usage.total_tokens == 14
    assert (
        safe.identity_sha256
        == hashlib.sha256(
            (
                '{"account_binding_hmac_sha256":"'
                + "4" * 64
                + '","thread_id":"thread-provider-free","turn_id":"turn-provider-free"}'
            ).encode()
        ).hexdigest()
    )
    assert "provider-free" not in repr(safe)
    assert SECRET not in repr(safe)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model", "gpt-5.6-terra"),
        ("reasoning_effort", "medium"),
        ("service_tier", "priority"),
        ("base_instructions_sha256", "9" * 64),
        ("runtime_source_sha256", "9" * 64),
        ("route_binding_sha256", "9" * 64),
        ("account_binding_hmac_sha256", "9" * 64),
        ("thread_id", "other-thread"),
        ("turn_id", "other-turn"),
        ("request_body_sha256", "9" * 64),
        ("output_text_sha256", "9" * 64),
        ("response_format_type", "text"),
        ("response_format_sha256", "9" * 64),
        ("response_schema_sha256", "9" * 64),
        ("requested_output_tokens", 1),
    ],
)
def test_every_authority_binding_fails_closed(
    receipt: dict[str, Any], field: str, value: object
) -> None:
    with pytest.raises(ReceiptVerificationError, match="authority mismatch"):
        verify(receipt, expected=replace(expectation(receipt), **{field: value}))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("metadata", "schema_version"), True),
        (("metadata", "output_token_limit", "requested_tokens"), True),
        (("metadata", "output_token_limit", "enforced"), 0),
        (("usage", "prompt_tokens"), True),
        (("usage", "total_tokens"), True),
        (("usage", "completion_tokens_details", "reasoning_tokens"), False),
        (("metadata", "runtime_selection", "thread_id"), 7),
    ],
)
def test_type_impostors_fail_before_hmac(
    receipt: dict[str, Any], path: tuple[str, ...], value: object
) -> None:
    target = receipt
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ReceiptVerificationError):
        verify(receipt)


def test_plain_dict_only_and_unknown_nested_fields_rejected(receipt: dict[str, Any]) -> None:
    class DictImpostor(dict[str, Any]):
        pass

    with pytest.raises(ReceiptVerificationError, match="plain object"):
        verify(DictImpostor(receipt))
    receipt["metadata"]["runtime_selection"]["email"] = "private@example.test"
    with pytest.raises(ReceiptVerificationError, match="keys"):
        verify(receipt)


@pytest.mark.parametrize(
    "field",
    (
        "public_model",
        "client_requested_model",
        "configured_codex_model",
        "requested_codex_model",
    ),
)
def test_every_request_model_binding_is_required(field: str) -> None:
    raw = unsigned_receipt()
    raw["metadata"]["request_identity"][field] = "gpt-5.6-terra"
    signed = sign_receipt(raw)
    with pytest.raises(ReceiptVerificationError, match=field):
        verify(signed, expected=expectation(unsigned_receipt()))


def test_receipt_hmac_and_call_kind_type_are_strict(receipt: dict[str, Any]) -> None:
    receipt["metadata"]["receipt_hmac_sha256"] = 0
    with pytest.raises(ReceiptVerificationError, match="receipt_hmac_sha256"):
        verify(receipt)
    signed = sign_receipt(unsigned_receipt())
    with pytest.raises(ReceiptVerificationError, match="call_kind"):
        RuntimeReceiptV2Boundary(NodePublicReceiptVerifier(RUNTIME_REPO)).verify(
            receipt=signed,
            secret=SECRET,
            expectation=expectation(signed),
            runtime_binding=trusted_binding(),
            call_kind="answer",  # type: ignore[arg-type]
            sequence=0,
            operation_id_sha256=OPERATION,
        )


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("usage", "total_tokens"), 99, "does not equal"),
        (("usage", "prompt_tokens_details", "cached_tokens"), 11, "exceed"),
        (("usage", "completion_tokens_details", "reasoning_tokens"), 5, "exceeds"),
    ],
)
def test_semantically_invalid_but_resigned_usage_is_rejected(
    path: tuple[str, ...], value: int, message: str
) -> None:
    raw = unsigned_receipt()
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    signed = sign_receipt(raw)
    with pytest.raises(ReceiptVerificationError, match=message):
        verify(signed)


def test_authenticated_zero_usage_issues_safe_receipt() -> None:
    raw = unsigned_receipt()
    raw["usage"] = {
        "prompt_tokens": 0,
        "prompt_tokens_details": {"cached_tokens": 0},
        "completion_tokens": 0,
        "completion_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 0,
    }

    safe = verify(sign_receipt(raw), expected=expectation(raw))

    assert isinstance(safe, SafeRuntimeReceipt)
    assert safe.usage == ProviderObservedUsage(0, 0, 0, 0, None, 0)


@pytest.mark.parametrize(
    "field",
    ("prompt_tokens", "completion_tokens", "total_tokens"),
)
def test_authenticated_negative_usage_is_rejected(field: str) -> None:
    raw = unsigned_receipt()
    raw["usage"][field] = -1

    with pytest.raises(ReceiptVerificationError, match="non-negative"):
        verify(sign_receipt(raw))


def test_same_boundary_handles_extraction_answer_and_judge(receipt: dict[str, Any]) -> None:
    kinds = (RuntimeCallKind.EXTRACTION, RuntimeCallKind.ANSWER, RuntimeCallKind.JUDGE)
    assert [
        verify(receipt, sequence=i, kind=kind).call_kind for i, kind in enumerate(kinds)
    ] == list(kinds)


def test_aggregation_is_exact_deterministic_and_bounded(receipt: dict[str, Any]) -> None:
    first = verify(receipt, sequence=0, kind=RuntimeCallKind.EXTRACTION)
    second_raw = unsigned_receipt()
    second_raw["metadata"]["runtime_selection"]["turn_id"] = "turn-two"
    second_raw["metadata"]["request_identity"]["request_body_sha256"] = "a" * 64
    second_raw["metadata"]["output_identity"]["output_text_sha256"] = "b" * 64
    second = verify(
        sign_receipt(second_raw),
        expected=expectation(second_raw),
        sequence=1,
        kind=RuntimeCallKind.ANSWER,
        operation_id_sha256="9" * 64,
    )
    left = RuntimeReceiptAggregator(max_receipts=2, evidence_page_size=1)
    right = RuntimeReceiptAggregator(max_receipts=2, evidence_page_size=1)
    left.add(second)
    left.add(first)
    right.add(first)
    right.add(second)
    aggregate = left.snapshot()
    assert aggregate == right.snapshot()
    assert aggregate.receipt_count == aggregate.provider_call_count == 2
    assert aggregate.usage.prompt_tokens == 20
    assert aggregate.usage.completion_tokens == 8
    assert aggregate.usage.total_tokens == 28
    assert len(aggregate.evidence_pages) == 2
    assert all(page.receipt_count == 1 for page in aggregate.evidence_pages)
    assert aggregate.runtime_binding_commitment_sha256 == first.runtime_binding_commitment_sha256


def test_aggregation_rejects_duplicate_gap_and_limit(receipt: dict[str, Any]) -> None:
    safe = verify(receipt)
    duplicate = RuntimeReceiptAggregator(max_receipts=2)
    duplicate.add(safe)
    with pytest.raises(ReceiptVerificationError, match="sequence"):
        duplicate.add(safe)
    gap = RuntimeReceiptAggregator(max_receipts=2)
    gap.add(verify(receipt, sequence=1, operation_id_sha256="9" * 64))
    with pytest.raises(ReceiptVerificationError, match="contiguous"):
        gap.snapshot()
    limited = RuntimeReceiptAggregator(max_receipts=1)
    limited.add(safe)
    with pytest.raises(ReceiptVerificationError, match="limit"):
        limited.add(verify(receipt, sequence=1, operation_id_sha256="9" * 64))


def test_safe_receipt_and_runtime_binding_cannot_be_directly_forged(
    receipt: dict[str, Any],
) -> None:
    safe = verify(receipt)
    values = {
        name: getattr(safe, name)
        for name in (
            "schema_version",
            "call_kind",
            "sequence",
            "operation_id_sha256",
            "receipt_sha256",
            "identity_sha256",
            "request_body_sha256",
            "output_text_sha256",
            "runtime_source_sha256",
            "route_binding_sha256",
            "runtime_binding_commitment_sha256",
            "usage",
        )
    }
    values["runtime_binding"] = trusted_binding()
    with pytest.raises(ReceiptVerificationError, match="verifier-issued"):
        SafeRuntimeReceipt(**values)
    forged_receipt = object.__new__(SafeRuntimeReceipt)
    for name, value in values.items():
        stored_name = "_runtime_binding" if name == "runtime_binding" else name
        object.__setattr__(forged_receipt, stored_name, value)
    with pytest.raises(ReceiptVerificationError, match="verifier-issued"):
        RuntimeReceiptAggregator(max_receipts=1).add(forged_receipt)
    with pytest.raises(ReceiptVerificationError, match="validator-issued"):
        TrustedRuntimeBinding(
            runtime_source_sha256=RUNTIME_SOURCE,
            route_binding_sha256=ROUTE_BINDING,
            commitment_sha256="9" * 64,
        )
    forged_binding = object.__new__(TrustedRuntimeBinding)
    with pytest.raises(ReceiptVerificationError, match="trusted runtime binding"):
        RuntimeReceiptV2Boundary(NodePublicReceiptVerifier(RUNTIME_REPO)).verify(
            receipt=receipt,
            secret=SECRET,
            expectation=expectation(receipt),
            runtime_binding=forged_binding,
            call_kind=RuntimeCallKind.EXTRACTION,
            sequence=0,
            operation_id_sha256=OPERATION,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("runtime_artifact", Path("/etc/hosts")),
        ("runtime_artifact_sha256", "a" * 64),
        ("runtime_source_sha256", "a" * 64),
        ("pinned_transport_route", "http://localhost:8890/v1"),
        ("configured_transport_route", "http://attacker.invalid:8890/v1"),
    ],
)
def test_public_composition_accepts_no_self_attested_authority_input(
    field_name: str, value: object
) -> None:
    assert not hasattr(RuntimeBindingComposition, "compose_reviewed")
    with pytest.raises(TypeError):
        RuntimeBindingComposition.compose_phase_c_canary(**{field_name: value})


def test_route_and_runtime_source_substitution_fail_closed() -> None:
    raw = sign_receipt(unsigned_receipt())
    with pytest.raises(ReceiptVerificationError, match="runtime_source_sha256"):
        verify(
            raw,
            expected=replace(expectation(raw), runtime_source_sha256="a" * 64),
        )
    binding = trusted_binding()
    with pytest.raises(AttributeError, match="immutable"):
        binding._runtime_source_sha256 = "a" * 64  # type: ignore[misc]


def test_publishable_aggregation_rejects_missing_or_mixed_runtime_binding(
    receipt: dict[str, Any],
) -> None:
    with pytest.raises(ReceiptVerificationError, match="trusted runtime-bound"):
        RuntimeReceiptAggregator(max_receipts=1).snapshot()
    assert trusted_binding().commitment_sha256 == trusted_binding().commitment_sha256


def test_aggregation_rejects_duplicate_operation_and_runtime_identity() -> None:
    first_raw = unsigned_receipt()
    first = verify(sign_receipt(first_raw))
    operation_raw = unsigned_receipt()
    operation_raw["metadata"]["runtime_selection"]["turn_id"] = "different-turn"
    duplicate_operation = verify(
        sign_receipt(operation_raw), sequence=1, operation_id_sha256=OPERATION
    )
    aggregate = RuntimeReceiptAggregator(max_receipts=2)
    aggregate.add(first)
    with pytest.raises(ReceiptVerificationError, match="operation identity"):
        aggregate.add(duplicate_operation)

    identity_raw = unsigned_receipt()
    identity_raw["metadata"]["request_identity"]["request_body_sha256"] = "a" * 64
    identity_raw["metadata"]["output_identity"]["output_text_sha256"] = "b" * 64
    duplicate_identity = verify(
        sign_receipt(identity_raw), sequence=1, operation_id_sha256="9" * 64
    )
    aggregate = RuntimeReceiptAggregator(max_receipts=2)
    aggregate.add(first)
    with pytest.raises(ReceiptVerificationError, match="account/thread/turn"):
        aggregate.add(duplicate_identity)


def test_optional_usage_aggregates_only_when_present_in_every_receipt() -> None:
    first = verify(sign_receipt(unsigned_receipt()))
    raw = unsigned_receipt()
    raw["metadata"]["runtime_selection"]["turn_id"] = "turn-without-details"
    raw["metadata"]["request_identity"]["request_body_sha256"] = "a" * 64
    raw["metadata"]["output_identity"]["output_text_sha256"] = "b" * 64
    del raw["usage"]["prompt_tokens_details"]
    del raw["usage"]["completion_tokens_details"]
    second = verify(sign_receipt(raw), sequence=1, operation_id_sha256="9" * 64)
    aggregate = RuntimeReceiptAggregator(max_receipts=2)
    aggregate.add(first)
    aggregate.add(second)
    usage = aggregate.snapshot().usage
    assert usage.cached_tokens is None
    assert usage.reasoning_tokens is None


@pytest.mark.parametrize(
    ("field_name", "mutated_value"),
    [
        ("schema_version", 3),
        ("call_kind", RuntimeCallKind.JUDGE),
        ("sequence", 7),
        ("operation_id_sha256", "a" * 64),
        ("receipt_sha256", "a" * 64),
        ("identity_sha256", "a" * 64),
        ("request_body_sha256", "a" * 64),
        ("output_text_sha256", "a" * 64),
        ("runtime_source_sha256", "a" * 64),
        ("route_binding_sha256", "a" * 64),
        ("runtime_binding_commitment_sha256", "a" * 64),
        ("usage", ProviderObservedUsage(1, 1, 2, None, None, None)),
        ("_seal", object()),
        ("_runtime_binding", None),
    ],
)
def test_every_post_issue_safe_receipt_mutation_is_rejected(
    receipt: dict[str, Any], field_name: str, mutated_value: object
) -> None:
    safe = verify(receipt)
    object.__setattr__(safe, field_name, mutated_value)
    with pytest.raises(ReceiptVerificationError, match="verifier-issued"):
        RuntimeReceiptAggregator(max_receipts=1).add(safe)


@pytest.mark.parametrize(
    ("field_name", "mutated_value"),
    [
        ("_runtime_source_sha256", "a" * 64),
        ("_route_binding_sha256", "a" * 64),
        ("_commitment_sha256", "a" * 64),
        ("_seal", object()),
    ],
)
def test_every_post_issue_runtime_binding_mutation_is_rejected(
    receipt: dict[str, Any], field_name: str, mutated_value: object
) -> None:
    binding = trusted_binding()
    object.__setattr__(binding, field_name, mutated_value)
    with pytest.raises(ReceiptVerificationError, match="trusted runtime binding"):
        verify(receipt, binding=binding)


def test_aggregation_rechecks_receipt_and_binding_snapshots_at_snapshot(
    receipt: dict[str, Any],
) -> None:
    mutated_receipt = verify(receipt)
    aggregate = RuntimeReceiptAggregator(max_receipts=1)
    aggregate.add(mutated_receipt)
    object.__setattr__(mutated_receipt, "receipt_sha256", "a" * 64)
    with pytest.raises(ReceiptVerificationError, match="verifier-issued"):
        aggregate.snapshot()
    mutated_binding = trusted_binding()
    safe = verify(receipt, binding=mutated_binding)
    aggregate = RuntimeReceiptAggregator(max_receipts=1)
    aggregate.add(safe)
    object.__setattr__(mutated_binding, "_runtime_source_sha256", "a" * 64)
    with pytest.raises(ReceiptVerificationError, match="verifier-issued"):
        aggregate.snapshot()


def test_snapshot_ignores_every_mutable_aggregation_cache(receipt: dict[str, Any]) -> None:
    safe = verify(receipt)
    aggregate = RuntimeReceiptAggregator(max_receipts=2)
    aggregate.add(safe)
    expected = aggregate.snapshot()
    aggregate._receipt_hashes.clear()  # type: ignore[attr-defined]
    aggregate._receipt_hashes.add("a" * 64)  # type: ignore[attr-defined]
    aggregate._operation_hashes.clear()  # type: ignore[attr-defined]
    aggregate._operation_hashes.add("b" * 64)  # type: ignore[attr-defined]
    aggregate._identity_hashes.clear()  # type: ignore[attr-defined]
    aggregate._identity_hashes.add("c" * 64)  # type: ignore[attr-defined]
    aggregate._binding_commitment = "d" * 64  # type: ignore[attr-defined]
    assert aggregate.snapshot() == expected


def test_snapshot_rejects_mutated_primary_receipt_collection(receipt: dict[str, Any]) -> None:
    aggregate = RuntimeReceiptAggregator(max_receipts=1)
    aggregate.add(verify(receipt))
    aggregate._receipts.clear()  # type: ignore[attr-defined]
    with pytest.raises(ReceiptVerificationError, match="primary log was mutated"):
        aggregate.snapshot()


def test_aggregation_config_is_immutable_after_issuance(receipt: dict[str, Any]) -> None:
    first = verify(receipt)
    raw = unsigned_receipt()
    raw["metadata"]["runtime_selection"]["turn_id"] = "second-turn"
    raw["metadata"]["request_identity"]["request_body_sha256"] = "a" * 64
    raw["metadata"]["output_identity"]["output_text_sha256"] = "b" * 64
    second = verify(
        sign_receipt(raw),
        sequence=1,
        operation_id_sha256="9" * 64,
    )
    bounded = RuntimeReceiptAggregator(max_receipts=1, evidence_page_size=1)
    bounded.add(first)
    bounded._max_receipts = 2  # type: ignore[attr-defined]
    with pytest.raises(ReceiptVerificationError, match="configuration"):
        bounded.add(second)

    paged = RuntimeReceiptAggregator(max_receipts=1, evidence_page_size=1)
    paged.add(first)
    paged._page_size = 2  # type: ignore[attr-defined]
    with pytest.raises(ReceiptVerificationError, match="configuration"):
        paged.snapshot()


@pytest.mark.parametrize(
    ("owner", "field_name", "mutated_value"),
    [
        ("authority", "runtime_artifact", Path("/etc/hosts")),
        ("authority", "runtime_artifact_sha256", "a" * 64),
        ("authority", "runtime_source_sha256", "a" * 64),
        ("authority", "transport_route", "http://localhost:8890/v1"),
        ("authority", "_seal", object()),
        ("observer", "_runtime_artifact", Path("/etc/hosts")),
        ("observer", "_transport_route", "http://localhost:8890/v1"),
        ("observer", "_seal", object()),
        ("service", "_seal", object()),
    ],
)
def test_reviewed_composition_objects_detect_post_issue_mutation(
    owner: str, field_name: str, mutated_value: object
) -> None:
    service = runtime_binding_service()
    target = service if owner == "service" else getattr(service, f"_{owner}")
    object.__setattr__(target, field_name, mutated_value)
    with pytest.raises(ReceiptVerificationError, match="authority drifted"):
        service.issue()


def test_transport_observation_snapshot_detects_object_level_mutation() -> None:
    service = runtime_binding_service()
    observation = service._observer.observe()  # type: ignore[attr-defined]
    assert observation._is_authentic()
    object.__setattr__(observation, "transport_route", "http://localhost:8890/v1")
    assert not observation._is_authentic()


def test_self_attested_authority_route_and_hosts_alias_cannot_enter_verifier(
    receipt: dict[str, Any],
) -> None:
    with pytest.raises(ReceiptVerificationError, match="composition-issued"):
        PinnedRuntimeBindingService(authority=object(), observer=object())  # type: ignore[arg-type]
    with pytest.raises(ReceiptVerificationError, match="composition-issued"):
        runtime_binding_module._PinnedRuntimeBindingAuthority(
            runtime_artifact=RUNTIME_ARTIFACT,
            runtime_artifact_sha256=hashlib.sha256(RUNTIME_ARTIFACT.read_bytes()).hexdigest(),
            runtime_source_sha256=RUNTIME_SOURCE,
            transport_route=TRANSPORT_ROUTE,
        )
    with pytest.raises(ReceiptVerificationError, match="observer-issued"):
        runtime_binding_module._TransportObservation(
            runtime_artifact=RUNTIME_ARTIFACT,
            transport_route=TRANSPORT_ROUTE,
        )
    service = runtime_binding_service()
    with pytest.raises(TypeError):
        service.issue(observed_transport_route="http://attacker.invalid:8890/v1")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        RuntimeBindingComposition.compose_phase_c_canary(
            configured_transport_route="http://localhost:8890/v1",  # type: ignore[call-arg]
        )
    forged_binding = object.__new__(TrustedRuntimeBinding)
    object.__setattr__(forged_binding, "_runtime_source_sha256", RUNTIME_SOURCE)
    object.__setattr__(forged_binding, "_route_binding_sha256", ROUTE_BINDING)
    object.__setattr__(forged_binding, "_commitment_sha256", "a" * 64)
    with pytest.raises(ReceiptVerificationError, match="trusted runtime binding"):
        verify(receipt, binding=forged_binding)


def test_safe_receipt_never_contains_raw_content_or_secret(receipt: dict[str, Any]) -> None:
    private_prompt = "the raw private prompt"
    private_output = "the raw private output"
    raw = copy.deepcopy(receipt)
    raw["metadata"]["request_identity"]["request_body_sha256"] = hashlib.sha256(
        private_prompt.encode()
    ).hexdigest()
    raw["metadata"]["output_identity"]["output_text_sha256"] = hashlib.sha256(
        private_output.encode()
    ).hexdigest()
    signed = sign_receipt(raw)
    rendered = repr(verify(signed))
    assert private_prompt not in rendered
    assert private_output not in rendered
    assert SECRET not in rendered

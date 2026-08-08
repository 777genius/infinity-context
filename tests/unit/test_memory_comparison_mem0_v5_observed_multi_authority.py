from __future__ import annotations

# ruff: noqa: E402, I001 - bootstrap hermetic Phase-C imports during collection.

import copy
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

# The module must collect hermetically even when it runs before its helper module.
ROOT = Path(__file__).resolve().parents[2]
PHASE_C_ROOT = ROOT / "benchmarks" / "phase-c-canary"
UNIT_TEST_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PHASE_C_ROOT))
sys.path.insert(0, str(UNIT_TEST_ROOT))

import pytest
from _phase_c_hermetic import install_hermetic_phase_c_authority
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_composition as composition_subject,
)
from infinity_context_server import (
    memory_comparison_mem0_oss_v5_observed_receipt as observed_subject,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
    RuntimeReceiptVerificationContext,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5HttpError,
    Mem0V5RuntimeReceiptEnvelope,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionOperationAuthority,
    Mem0V5ObservedExtractionReceiptAuthority,
    Mem0V5ObservedExtractionReceiptVerifier,
)
from phase_c_canary.runtime_receipt_v2 import RuntimeReceiptV2Boundary
from test_memory_comparison_managed_mem0_v5_composition import (
    _inputs as _composition_inputs,
)
from test_memory_comparison_managed_mem0_v5_composition import (
    _Transport,
)
from test_memory_comparison_mem0_oss_v5_observed_receipt import (
    SECRET,
    _authority,
    _binding,
    _DeterministicReceiptHmacVerifier,
    _sha,
    _sign,
    _unsigned_receipt,
)


@pytest.fixture(autouse=True)
def _use_hermetic_phase_c_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_hermetic_phase_c_authority(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        phase_c_root=PHASE_C_ROOT,
    )


class _CountingReceiptHmacVerifier(_DeterministicReceiptHmacVerifier):
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, **kwargs: object) -> None:
        self.calls += 1
        super().verify(**kwargs)  # type: ignore[arg-type]


class _OperationImpostor(Mem0V5ObservedExtractionOperationAuthority):
    pass


def _multi_authority(binding: object) -> Mem0V5ObservedExtractionReceiptAuthority:
    base = _authority(binding)
    second_identity = _sha("unit-identity-2")
    second = Mem0V5ObservedExtractionOperationAuthority(
        operation_id_sha256=canonical_sha256(
            {
                "admission_commitment_sha256": base.admission_commitment_sha256,
                "unit_index": 1,
                "unit_identity_sha256": second_identity,
            }
        ),
        unit_identity_sha256=second_identity,
        unit_sha256=base.operations[0].unit_sha256,
        scope_sha256=_sha("scope-2"),
        sequence=1,
        request_body_sha256=_sha("request-body-2"),
    )
    return replace(base, operations=(base.operations[0], second))


def _operation(
    *, admission: str, index: int, unit: object, request_body: str
) -> Mem0V5ObservedExtractionOperationAuthority:
    return Mem0V5ObservedExtractionOperationAuthority(
        operation_id_sha256=canonical_sha256(
            {
                "admission_commitment_sha256": admission,
                "unit_index": index,
                "unit_identity_sha256": unit.unit_identity_sha256,
            }
        ),
        unit_identity_sha256=unit.unit_identity_sha256,
        unit_sha256=unit.unit_sha256,
        scope_sha256=unit.scope_sha256,
        sequence=index,
        request_body_sha256=request_body,
    )


def _extra_operation(
    authority: Mem0V5ObservedExtractionReceiptAuthority,
) -> Mem0V5ObservedExtractionOperationAuthority:
    index = len(authority.operations)
    identity = _sha(f"unit-identity-{index + 1}")
    return Mem0V5ObservedExtractionOperationAuthority(
        canonical_sha256(
            {
                "admission_commitment_sha256": authority.admission_commitment_sha256,
                "unit_index": index,
                "unit_identity_sha256": identity,
            }
        ),
        identity,
        _sha(f"unit-{index + 1}"),
        _sha(f"scope-{index + 1}"),
        index,
        _sha(f"request-body-{index + 1}"),
    )


def _two_operation_composition_inputs(
    tmp_path: Path,
) -> tuple[dict[str, object], Mem0V5ObservedExtractionReceiptAuthority]:
    inputs, values = _composition_inputs(tmp_path)
    first = inputs["cases"][0]
    record = json.loads(json.dumps(first.record, default=dict))
    second_corpus = f"locomo-corpus-{'c' * 64}"
    record["corpus_id"] = second_corpus
    record["thread_id"] = f"locomo-thread-{'d' * 64}"
    cases = (
        first,
        ManagedRunCase("case-2", second_corpus, record),
    )
    current_date = inputs["current_date"]
    assert isinstance(current_date, str)
    manifest = ManagedMem0V5ManifestProjector().project(cases, current_date=current_date)
    request = replace(inputs["request"], expected_operation_count=2)
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=manifest.ingestion_manifest_sha256,
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        ingestion_unit_count=2,
    )
    old = inputs["receipt_authority"]
    operations = tuple(
        _operation(
            admission=admission.commitment_sha256,
            index=index,
            unit=unit,
            request_body=_sha(f"observed-request-{index}"),
        )
        for index, unit in enumerate(manifest.units)
    )
    observed = Mem0V5ObservedExtractionReceiptAuthority(
        admission_commitment_sha256=admission.commitment_sha256,
        model=old.model,
        reasoning_effort=old.reasoning_effort,
        service_tier=old.service_tier,
        base_instructions_sha256=old.base_instructions_sha256,
        runtime_source_sha256=old.runtime_source_sha256,
        route_binding_sha256=old.route_binding_sha256,
        account_binding_hmac_sha256=old.account_binding_hmac_sha256,
        node_executable_path="/usr/local/bin/node",
        node_executable_sha256=("b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"),
        response_format_type=old.response_format_type,
        response_format_sha256=old.response_format_sha256,
        response_schema_sha256=old.response_schema_sha256,
        operations=operations,
        requested_output_tokens=old.requested_output_tokens,
    )
    inputs.update(
        cases=cases,
        request=request,
        receipt_authority=observed,
        transport=_Transport(values["evidence"], manifest),
    )
    return inputs, observed


def _verifier(
    authority: Mem0V5ObservedExtractionReceiptAuthority,
    binding: object,
) -> tuple[Mem0V5ObservedExtractionReceiptVerifier, _CountingReceiptHmacVerifier]:
    hmac_verifier = _CountingReceiptHmacVerifier()
    verifier = Mem0V5ObservedExtractionReceiptVerifier._for_provider_free_tests(
        boundary=RuntimeReceiptV2Boundary(hmac_verifier),
        runtime_binding=binding,
        receipt_secret=SECRET,
        authority=authority,
    )
    return verifier, hmac_verifier


def _context(
    authority: Mem0V5ObservedExtractionReceiptAuthority,
    operation: Mem0V5ObservedExtractionOperationAuthority,
    *,
    readback: bool,
) -> RuntimeReceiptVerificationContext:
    return RuntimeReceiptVerificationContext(
        admission_commitment_sha256=authority.admission_commitment_sha256,
        operation_id_sha256=operation.operation_id_sha256,
        unit_identity_sha256=operation.unit_identity_sha256,
        unit_sha256=operation.unit_sha256,
        route_sha256=authority.route_binding_sha256,
        scope_sha256=operation.scope_sha256,
        readback_only=readback,
    )


def _payload(
    authority: Mem0V5ObservedExtractionReceiptAuthority,
    operation: Mem0V5ObservedExtractionOperationAuthority,
    *,
    authentic: bool = True,
) -> Mem0V5RuntimeReceiptEnvelope:
    receipt = copy.deepcopy(_unsigned_receipt(authority))
    receipt["metadata"]["request_identity"]["request_body_sha256"] = operation.request_body_sha256
    signed = _sign(receipt)
    if not authentic:
        signed["metadata"]["receipt_hmac_sha256"] = "f" * 64
    return Mem0V5RuntimeReceiptEnvelope(
        admission_commitment_sha256=authority.admission_commitment_sha256,
        operation_id_sha256=operation.operation_id_sha256,
        runtime_receipt=signed,
    )


def test_authority_accepts_duplicate_unit_content_but_rejects_invalid_ordering() -> None:
    binding = _binding()
    authority = _multi_authority(binding)

    assert authority.operations[0].unit_sha256 == authority.operations[1].unit_sha256
    with pytest.raises(Mem0V5HttpError, match="configuration_invalid"):
        replace(authority, operations=())
    with pytest.raises(Mem0V5HttpError, match="configuration_invalid"):
        replace(authority, operations=tuple(reversed(authority.operations)))
    with pytest.raises(Mem0V5HttpError, match="configuration_invalid"):
        replace(authority.operations[0], sequence=True)


def test_authority_accepts_configured_max_and_rejects_oversize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(observed_subject, "MEM0_OSS_FULL_RUN_MAX_OPERATIONS", 2)
    authority = _multi_authority(_binding())

    Mem0V5ObservedExtractionReceiptAuthority.__post_init__(authority)
    with pytest.raises(Mem0V5HttpError, match="configuration_invalid"):
        replace(authority, operations=authority.operations + (_extra_operation(authority),))


@pytest.mark.parametrize(
    "mutation",
    ("duplicate-operation", "duplicate-unit", "sequence-gap", "canonical-id", "impostor"),
)
def test_authority_rejects_ambiguous_or_non_exact_operations(mutation: str) -> None:
    authority = _multi_authority(_binding())
    first, second = authority.operations
    if mutation == "duplicate-operation":
        changed = replace(second, operation_id_sha256=first.operation_id_sha256)
    elif mutation == "duplicate-unit":
        identity = first.unit_identity_sha256
        changed = replace(
            second,
            operation_id_sha256=canonical_sha256(
                {
                    "admission_commitment_sha256": authority.admission_commitment_sha256,
                    "unit_index": 1,
                    "unit_identity_sha256": identity,
                }
            ),
            unit_identity_sha256=identity,
        )
    elif mutation == "sequence-gap":
        changed = replace(second, sequence=2)
    elif mutation == "canonical-id":
        changed = replace(second, operation_id_sha256=_sha("non-canonical-operation"))
    else:
        changed = _OperationImpostor(
            second.operation_id_sha256,
            second.unit_identity_sha256,
            second.unit_sha256,
            second.scope_sha256,
            second.sequence,
            second.request_body_sha256,
        )

    with pytest.raises(Mem0V5HttpError, match="configuration_invalid"):
        replace(authority, operations=(first, changed))


def test_nested_operation_mutation_is_revalidated_before_boundary() -> None:
    binding = _binding()
    authority = _multi_authority(binding)
    object.__setattr__(authority.operations[0], "request_body_sha256", "invalid")

    with pytest.raises(Mem0V5HttpError, match="configuration_invalid"):
        Mem0V5ObservedExtractionReceiptAuthority.__post_init__(authority)
    hmac_verifier = _CountingReceiptHmacVerifier()
    with pytest.raises(Mem0V5HttpError, match="configuration_invalid"):
        Mem0V5ObservedExtractionReceiptVerifier._for_provider_free_tests(
            boundary=RuntimeReceiptV2Boundary(hmac_verifier),
            runtime_binding=binding,
            receipt_secret=SECRET,
            authority=authority,
        )
    assert hmac_verifier.calls == 0


def test_unknown_a_blocks_only_a_dispatch_while_b_and_a_readback_succeed() -> None:
    binding = _binding()
    authority = _multi_authority(binding)
    verifier, _ = _verifier(authority, binding)
    first, second = authority.operations
    verifier.mark_outcome_unknown(context=_context(authority, first, readback=False))

    with pytest.raises(Mem0V5HttpError, match="state_invalid"):
        verifier.verify_dispatch_receipt(
            payload=_payload(authority, first),
            context=_context(authority, first, readback=False),
        )
    assert (
        verifier.verify_dispatch_receipt(
            payload=_payload(authority, second),
            context=_context(authority, second, readback=False),
        ).operation_id_sha256
        == second.operation_id_sha256
    )
    assert (
        verifier.verify_status_readback(
            payload=_payload(authority, first),
            context=_context(authority, first, readback=True),
        ).operation_id_sha256
        == first.operation_id_sha256
    )


def test_consumed_or_failed_a_does_not_poison_b_and_failure_does_not_consume() -> None:
    binding = _binding()
    authority = _multi_authority(binding)
    first, second = authority.operations
    verifier, _ = _verifier(authority, binding)

    with pytest.raises(Mem0V5HttpError, match="unauthenticated"):
        verifier.verify_dispatch_receipt(
            payload=_payload(authority, first, authentic=False),
            context=_context(authority, first, readback=False),
        )
    assert (
        verifier.verify_dispatch_receipt(
            payload=_payload(authority, first),
            context=_context(authority, first, readback=False),
        ).operation_id_sha256
        == first.operation_id_sha256
    )
    assert (
        verifier.verify_dispatch_receipt(
            payload=_payload(authority, second),
            context=_context(authority, second, readback=False),
        ).operation_id_sha256
        == second.operation_id_sha256
    )


def test_mark_unknown_after_consumption_is_rejected_per_operation() -> None:
    binding = _binding()
    authority = _multi_authority(binding)
    first, second = authority.operations
    verifier, _ = _verifier(authority, binding)
    verifier.verify_dispatch_receipt(
        payload=_payload(authority, first),
        context=_context(authority, first, readback=False),
    )

    with pytest.raises(Mem0V5HttpError, match="state_invalid"):
        verifier.mark_outcome_unknown(context=_context(authority, first, readback=False))
    verifier.mark_outcome_unknown(context=_context(authority, second, readback=False))


def test_cross_operation_context_and_envelope_swaps_do_not_consume_target() -> None:
    binding = _binding()
    authority = _multi_authority(binding)
    first, second = authority.operations
    verifier, hmac_verifier = _verifier(authority, binding)

    mixed_context = replace(
        _context(authority, second, readback=False),
        scope_sha256=first.scope_sha256,
    )
    with pytest.raises(Mem0V5HttpError, match="runtime_receipt_invalid"):
        verifier.verify_dispatch_receipt(
            payload=_payload(authority, second),
            context=mixed_context,
        )
    with pytest.raises(Mem0V5HttpError, match="runtime_receipt_invalid"):
        verifier.verify_dispatch_receipt(
            payload=_payload(authority, first),
            context=_context(authority, second, readback=False),
        )
    assert hmac_verifier.calls == 0

    authentic_a_as_b = replace(
        _payload(authority, first),
        operation_id_sha256=second.operation_id_sha256,
    )
    with pytest.raises(Mem0V5HttpError, match="unauthenticated"):
        verifier.verify_dispatch_receipt(
            payload=authentic_a_as_b,
            context=_context(authority, second, readback=False),
        )
    assert (
        verifier.verify_dispatch_receipt(
            payload=_payload(authority, second),
            context=_context(authority, second, readback=False),
        ).operation_id_sha256
        == second.operation_id_sha256
    )


def test_same_operation_concurrency_has_one_success_and_one_replay() -> None:
    binding = _binding()
    authority = _multi_authority(binding)
    operation = authority.operations[0]
    verifier, _ = _verifier(authority, binding)
    barrier = Barrier(2)

    def verify() -> str:
        barrier.wait()
        try:
            verifier.verify_dispatch_receipt(
                payload=_payload(authority, operation),
                context=_context(authority, operation, readback=False),
            )
        except Mem0V5HttpError as error:
            return error.code
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: verify(), range(2)))
    assert sorted(outcomes) == ["mem0_v5_runtime_receipt_replayed", "success"]


def test_different_operations_can_verify_concurrently() -> None:
    binding = _binding()
    authority = _multi_authority(binding)
    verifier, _ = _verifier(authority, binding)
    barrier = Barrier(2)

    def verify(operation: Mem0V5ObservedExtractionOperationAuthority) -> str:
        barrier.wait()
        return verifier.verify_dispatch_receipt(
            payload=_payload(authority, operation),
            context=_context(authority, operation, readback=False),
        ).operation_id_sha256

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(verify, authority.operations))
    assert outcomes == tuple(operation.operation_id_sha256 for operation in authority.operations)


def test_fresh_verifier_can_read_back_either_authorized_operation() -> None:
    binding = _binding()
    authority = _multi_authority(binding)
    for operation in authority.operations:
        verifier, _ = _verifier(authority, binding)
        assert (
            verifier.verify_status_readback(
                payload=_payload(authority, operation),
                context=_context(authority, operation, readback=True),
            ).operation_id_sha256
            == operation.operation_id_sha256
        )


def test_partial_restart_can_read_back_remaining_operation() -> None:
    binding = _binding()
    authority = _multi_authority(binding)
    first, second = authority.operations
    initial, _ = _verifier(authority, binding)
    initial.verify_dispatch_receipt(
        payload=_payload(authority, first),
        context=_context(authority, first, readback=False),
    )

    restarted, _ = _verifier(authority, binding)
    assert (
        restarted.verify_status_readback(
            payload=_payload(authority, second),
            context=_context(authority, second, readback=True),
        ).operation_id_sha256
        == second.operation_id_sha256
    )


def test_two_operation_composition_accepts_exact_order_without_provider_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, authority = _two_operation_composition_inputs(tmp_path)
    boundary_calls = 0

    def accept_boundary(**_kwargs: object) -> None:
        nonlocal boundary_calls
        boundary_calls += 1

    monkeypatch.setattr(
        composition_subject,
        "require_mem0_v5_observed_extraction_receipt_boundary",
        accept_boundary,
    )
    composition = composition_subject.compose_managed_mem0_v5(**inputs)
    transport = inputs["transport"]
    assert type(transport) is _Transport
    assert composition.authority.operation_count == 2
    assert composition.request.expected_operation_count == 2
    assert authority.operations[1].sequence == 1
    assert boundary_calls == 1
    assert transport.calls == []
    assert inputs["runtime_receipt_boundary"].hmac_verifier.calls == 0


@pytest.mark.parametrize("mutation", ("missing", "extra", "reordered"))
def test_two_operation_composition_rejects_order_drift_before_external_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    inputs, authority = _two_operation_composition_inputs(tmp_path)
    if mutation == "missing":
        operations = authority.operations[:1]
    elif mutation == "extra":
        operations = authority.operations + (_extra_operation(authority),)
    else:
        operations = tuple(reversed(authority.operations))
    object.__setattr__(authority, "operations", operations)
    boundary_calls = 0
    credential_calls = 0

    def boundary_must_not_run(**_kwargs: object) -> None:
        nonlocal boundary_calls
        boundary_calls += 1

    def credentials_must_not_load(_paths: object) -> None:
        nonlocal credential_calls
        credential_calls += 1
        raise AssertionError("invalid authority reached credential loading")

    monkeypatch.setattr(
        composition_subject,
        "require_mem0_v5_observed_extraction_receipt_boundary",
        boundary_must_not_run,
    )
    monkeypatch.setattr(
        composition_subject,
        "load_managed_mem0_v5_credentials",
        credentials_must_not_load,
    )
    with pytest.raises(ManagedRunError, match="observed receipt binding differs"):
        composition_subject.compose_managed_mem0_v5(**inputs)
    transport = inputs["transport"]
    assert type(transport) is _Transport
    assert boundary_calls == 0
    assert credential_calls == 0
    assert transport.calls == []
    assert inputs["runtime_receipt_boundary"].hmac_verifier.calls == 0


def test_mutated_request_body_fails_composition_before_boundary_credentials_or_hmac(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, authority = _two_operation_composition_inputs(tmp_path)
    object.__setattr__(authority.operations[1], "request_body_sha256", "invalid")
    with pytest.raises(Mem0V5HttpError, match="configuration_invalid"):
        Mem0V5ObservedExtractionReceiptAuthority.__post_init__(authority)
    boundary_calls = 0
    credential_calls = 0

    def boundary_must_not_run(**_kwargs: object) -> None:
        nonlocal boundary_calls
        boundary_calls += 1

    def credentials_must_not_load(_paths: object) -> None:
        nonlocal credential_calls
        credential_calls += 1
        raise AssertionError("invalid authority reached credential loading")

    monkeypatch.setattr(
        composition_subject,
        "require_mem0_v5_observed_extraction_receipt_boundary",
        boundary_must_not_run,
    )
    monkeypatch.setattr(
        composition_subject,
        "load_managed_mem0_v5_credentials",
        credentials_must_not_load,
    )
    with pytest.raises(ManagedRunError, match="observed receipt binding differs"):
        composition_subject.compose_managed_mem0_v5(**inputs)
    assert boundary_calls == 0
    assert credential_calls == 0
    assert inputs["transport"].calls == []
    assert inputs["runtime_receipt_boundary"].hmac_verifier.calls == 0


@pytest.mark.parametrize("mutation", ("aggregate", "operation", "tuple", "index", "state"))
def test_authenticated_authority_graph_mutation_fails_before_boundary(mutation: str) -> None:
    binding = _binding()
    authority = _multi_authority(binding)
    verifier, hmac_verifier = _verifier(authority, binding)
    operation = authority.operations[0]
    payload = _payload(authority, operation)
    if mutation == "aggregate":
        object.__setattr__(authority, "model", "gpt-5.6-terra")
    elif mutation == "operation":
        object.__setattr__(operation, "scope_sha256", _sha("mutated-scope"))
    elif mutation == "tuple":
        object.__setattr__(authority, "operations", tuple(list(authority.operations)))
    elif mutation == "index":
        verifier._operation_index[operation.operation_id_sha256] = authority.operations[1]
    else:
        object.__setattr__(verifier, "_unknown", set())

    with pytest.raises(Mem0V5HttpError, match="state_invalid"):
        verifier.verify_dispatch_receipt(
            payload=payload,
            context=_context(authority, operation, readback=False),
        )
    assert hmac_verifier.calls == 0

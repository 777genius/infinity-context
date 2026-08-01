from __future__ import annotations

import json

import httpx
import pytest
from infinity_context_server.memory_comparison_managed_http_policy_lifecycle import (
    ManagedHttpPolicyCanonicalSourceReceipt,
    ManagedHttpPolicyLifecycleError,
    managed_http_policy_production_blockers,
)
from infinity_context_server.memory_comparison_managed_http_policy_validation import (
    VerifiedManagedHttpPolicyValidation,
    public_managed_http_policy_validation,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
)
from memory_comparison_managed_http_policy_lifecycle_test_support import (
    _ATTESTATION,
    _adapter,
    _complete_lifecycle,
    _factory,
    _locomo_case,
    _longmem_case,
    _presence_data,
    _seal,
    _thaw,
    _TrackingTransport,
    _views,
)


def test_static_blockers_keep_only_honest_remaining_capability_gaps() -> None:
    expected = ()
    assert managed_http_policy_production_blockers((_locomo_case(),)) == expected
    assert managed_http_policy_production_blockers((_longmem_case(),)) == expected


def test_presence_is_observed_once_per_corpus_and_receipts_cover_original_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _locomo_case()
    second = ManagedRunCase("case-two", first.corpus_id, _thaw(first.record))
    requests: list[httpx.Request] = []
    transports: list[_TrackingTransport] = []

    def derived(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": _presence_data()})

    adapter, bindings = _adapter(
        cases=(first, second),
        derived_factory=_factory(derived, transports),
    )
    receipts = _seal(adapter, bindings, (first, second), _views(first), monkeypatch)

    assert len(receipts) == 2
    assert all(type(item) is ManagedHttpPolicyCanonicalSourceReceipt for item in receipts)
    assert len({id(item) for item in receipts}) == 2
    assert [request.url.path for request in requests] == [
        "/api/v1/diagnostics/derived-evidence/presence"
    ]
    assert transports[0].closed is True


def test_aggregate_rejects_replay_after_issuing_one_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, bindings, canonical, terminal, _ = _complete_lifecycle(monkeypatch)
    validation = adapter.aggregate_policy(
        bindings=bindings,
        managed_attestation=_ATTESTATION,
        managed_attestation_commitment_sha256="6" * 64,
        canonical_source=canonical,
        terminal_delete=terminal,
    )
    assert type(validation) is VerifiedManagedHttpPolicyValidation
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_aggregate_replay$",
    ):
        adapter.aggregate_policy(
            bindings=bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256="6" * 64,
            canonical_source=canonical,
            terminal_delete=terminal,
        )


def test_aggregate_rejects_wrong_canonical_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _locomo_case()
    second = ManagedRunCase("case-two", first.corpus_id, _thaw(first.record))
    adapter, bindings, canonical, terminal, _ = _complete_lifecycle(monkeypatch, (first, second))
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_canonical_order_invalid$",
    ):
        adapter.aggregate_policy(
            bindings=bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256="6" * 64,
            canonical_source=tuple(reversed(canonical)),
            terminal_delete=terminal,
        )


def test_aggregate_rejects_wrong_terminal_type_and_foreign_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, bindings, canonical, _, _ = _complete_lifecycle(monkeypatch)
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_terminal_receipt_type_invalid$",
    ):
        adapter.aggregate_policy(
            bindings=bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256="6" * 64,
            canonical_source=canonical,
            terminal_delete=object(),
        )

    owner, owner_bindings, owner_canonical, _, _ = _complete_lifecycle(monkeypatch)
    _, _, _, foreign_terminal, _ = _complete_lifecycle(monkeypatch)
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_terminal_binding_invalid$",
    ):
        owner.aggregate_policy(
            bindings=owner_bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256="6" * 64,
            canonical_source=owner_canonical,
            terminal_delete=foreign_terminal,
        )


def test_aggregate_rejects_wrong_canonical_type_and_foreign_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typed, typed_bindings, _, typed_terminal, _ = _complete_lifecycle(monkeypatch)
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_canonical_receipt_type_invalid$",
    ):
        typed.aggregate_policy(
            bindings=typed_bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256="6" * 64,
            canonical_source=(object(),),
            terminal_delete=typed_terminal,
        )

    owner, owner_bindings, _, owner_terminal, _ = _complete_lifecycle(monkeypatch)
    _, _, foreign_canonical, _, _ = _complete_lifecycle(monkeypatch)
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_canonical_binding_invalid$",
    ):
        owner.aggregate_policy(
            bindings=owner_bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256="6" * 64,
            canonical_source=foreign_canonical,
            terminal_delete=owner_terminal,
        )


def test_terminal_seal_is_one_shot(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, bindings, _, _, deletes = _complete_lifecycle(monkeypatch)
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_terminal_delete_phase_invalid$",
    ):
        adapter.seal_terminal_delete(
            bindings=bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256="6" * 64,
            receipts=deletes,
        )


def test_public_validation_does_not_expose_raw_evidence_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, bindings, canonical, terminal, _ = _complete_lifecycle(monkeypatch)
    validation = adapter.aggregate_policy(
        bindings=bindings,
        managed_attestation=_ATTESTATION,
        managed_attestation_commitment_sha256="6" * 64,
        canonical_source=canonical,
        terminal_delete=terminal,
    )
    encoded = json.dumps(public_managed_http_policy_validation(validation))
    assert "fact-1" not in encoded
    assert "memory-1" not in encoded

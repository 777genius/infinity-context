from __future__ import annotations

import json

import pytest
from infinity_context_server import (
    memory_comparison_managed_production_composition as subject,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    VerifiedManagedLiveRunPreparation,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase

_PRIVATE_GOLD = "PRIVATE-GOLD-MUST-NOT-LEAK"
_PRIVATE_SECRET = "PRIVATE-CREDENTIAL-MUST-NOT-LEAK"


def _prepared() -> VerifiedManagedLiveRunPreparation:
    return object.__new__(VerifiedManagedLiveRunPreparation)


@pytest.mark.parametrize(
    ("benchmark", "expected"),
    (
        (
            "locomo",
            (
                "managed_production_ingest_manifest_binding_unavailable",
                "managed_http_policy_infinity_document_chunk_identity_unavailable",
                "managed_http_policy_mem0_exact_source_identity_unavailable",
                "managed_http_policy_exact_derived_identity_manifest_unavailable",
                "managed_http_policy_terminal_manifest_binding_unavailable",
            ),
        ),
        (
            "longmemeval",
            (
                "managed_production_ingest_manifest_binding_unavailable",
                "managed_http_policy_infinity_document_chunk_identity_unavailable",
                "managed_http_policy_mem0_exact_source_identity_unavailable",
                "managed_http_policy_exact_derived_identity_manifest_unavailable",
                "managed_http_policy_terminal_manifest_binding_unavailable",
            ),
        ),
    ),
)
def test_current_policy_blockers_return_no_go_before_consume_or_io(
    monkeypatch: pytest.MonkeyPatch,
    benchmark: str,
    expected: tuple[str, ...],
) -> None:
    prepared = _prepared()
    cases = (
        ManagedRunCase(
            "managed-case-1",
            "managed-corpus-1",
            {
                "benchmark": benchmark,
                "private_gold": _PRIVATE_GOLD,
                "private_secret": _PRIVATE_SECRET,
            },
        ),
    )
    inspected = 0

    def inspect(value: object) -> tuple[ManagedRunCase, ...]:
        nonlocal inspected
        assert value is prepared
        inspected += 1
        return cases

    monkeypatch.setattr(subject, "_inspect_managed_live_policy_cases", inspect)
    decision = subject.run_verified_managed_production_comparison(prepared)

    assert inspected == 1
    assert decision.blockers == expected
    assert decision.preparation_consumed is False
    assert decision.readiness_provider_calls_already_performed == 1
    assert decision.additional_provider_calls_performed == 0
    assert decision.additional_backend_calls_performed == 0
    payload = decision.public_payload()
    rendered = json.dumps(payload, sort_keys=True)
    assert payload["decision"] == "no-go"
    assert _PRIVATE_GOLD not in rendered
    assert _PRIVATE_SECRET not in rendered


def test_pre_readiness_gate_returns_same_static_no_go_with_zero_live_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = (
        ManagedRunCase(
            "managed-case-1",
            "managed-corpus-1",
            {"benchmark": "locomo", "private_gold": _PRIVATE_GOLD},
        ),
    )
    monkeypatch.setattr(
        subject,
        "_inspect_managed_live_policy_cases",
        lambda _: pytest.fail("pre-readiness gate must not inspect preparation"),
    )

    decision = subject.evaluate_managed_production_pre_readiness(cases)

    assert decision.decision == "no-go"
    assert decision.preparation_consumed is False
    assert decision.readiness_provider_calls_already_performed == 0
    assert decision.additional_provider_calls_performed == 0
    assert decision.additional_backend_calls_performed == 0
    assert decision.blockers == (
        "managed_production_ingest_manifest_binding_unavailable",
        "managed_http_policy_infinity_document_chunk_identity_unavailable",
        "managed_http_policy_mem0_exact_source_identity_unavailable",
        "managed_http_policy_exact_derived_identity_manifest_unavailable",
        "managed_http_policy_terminal_manifest_binding_unavailable",
    )
    assert _PRIVATE_GOLD not in json.dumps(decision.public_payload(), sort_keys=True)


def test_pre_readiness_gate_rejects_invalid_cases_without_live_work() -> None:
    with pytest.raises(subject.ManagedProductionCompositionError) as caught:
        subject.evaluate_managed_production_pre_readiness(())
    assert caught.value.code == "managed_production_pre_readiness_failed"


def test_structural_blockers_remain_when_policy_contracts_become_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared()
    cases = (ManagedRunCase("case-1", "corpus-1", {"benchmark": "locomo"}),)
    monkeypatch.setattr(subject, "_inspect_managed_live_policy_cases", lambda _: cases)
    monkeypatch.setattr(subject, "managed_http_policy_production_blockers", lambda _: ())

    decision = subject.run_verified_managed_production_comparison(prepared)
    assert decision.blockers == ("managed_production_ingest_manifest_binding_unavailable",)
    assert decision.preparation_consumed is False


def test_forged_preparation_is_rejected_without_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "_inspect_managed_live_policy_cases",
        lambda _: pytest.fail("forged preparation must fail before inspection"),
    )
    with pytest.raises(subject.ManagedProductionCompositionError) as caught:
        subject.run_verified_managed_production_comparison(object())  # type: ignore[arg-type]
    assert caught.value.code == "managed_production_preparation_invalid"

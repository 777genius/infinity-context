from __future__ import annotations

import json

import pytest
from infinity_context_server import (
    memory_comparison_managed_production_composition as subject,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    VerifiedManagedLiveRunPreparation,
)
from infinity_context_server.memory_comparison_managed_run import ManagedRunOutcome
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase

_PRIVATE_GOLD = "PRIVATE-GOLD-MUST-NOT-LEAK"
_PRIVATE_SECRET = "PRIVATE-CREDENTIAL-MUST-NOT-LEAK"


def _prepared() -> VerifiedManagedLiveRunPreparation:
    return object.__new__(VerifiedManagedLiveRunPreparation)


@pytest.mark.parametrize("benchmark", ("locomo", "longmemeval"))
def test_go_policy_delegates_and_returns_exact_runner_outcome(
    monkeypatch: pytest.MonkeyPatch,
    benchmark: str,
) -> None:
    prepared = _prepared()
    expected = object.__new__(ManagedRunOutcome)
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
    runner_calls = 0

    def inspect(value: object) -> tuple[ManagedRunCase, ...]:
        nonlocal inspected
        assert value is prepared
        inspected += 1
        return cases

    def run(value: object) -> ManagedRunOutcome:
        nonlocal runner_calls
        assert value is prepared
        runner_calls += 1
        return expected

    monkeypatch.setattr(subject, "_inspect_managed_live_policy_cases", inspect)
    monkeypatch.setattr(
        subject,
        "managed_http_policy_production_blockers",
        lambda value: () if value is cases else pytest.fail("unexpected cases"),
    )
    monkeypatch.setattr(subject, "run_verified_managed_production_execution", run)

    outcome = subject.run_verified_managed_production_comparison(prepared)

    assert inspected == 1
    assert runner_calls == 1
    assert outcome is expected


def test_pre_readiness_gate_returns_static_go_with_zero_live_calls(
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
    monkeypatch.setattr(
        subject,
        "managed_http_policy_production_blockers",
        lambda value: () if value is cases else pytest.fail("unexpected cases"),
    )

    decision = subject.evaluate_managed_production_pre_readiness(cases)

    assert decision.decision == "go"
    assert decision.preparation_consumed is False
    assert decision.readiness_provider_calls_already_performed == 0
    assert decision.additional_provider_calls_performed == 0
    assert decision.additional_backend_calls_performed == 0
    assert decision.blockers == ()
    assert _PRIVATE_GOLD not in json.dumps(decision.public_payload(), sort_keys=True)


def test_pre_readiness_gate_reports_explicit_policy_no_go_without_live_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = (ManagedRunCase("case-1", "corpus-1", {"benchmark": "locomo"}),)
    monkeypatch.setattr(
        subject,
        "_inspect_managed_live_policy_cases",
        lambda _: pytest.fail("pre-readiness gate must not inspect preparation"),
    )
    monkeypatch.setattr(
        subject,
        "managed_http_policy_production_blockers",
        lambda value: (
            ("explicit-policy-blocker",) if value is cases else pytest.fail("unexpected cases")
        ),
    )

    decision = subject.evaluate_managed_production_pre_readiness(cases)

    assert decision.decision == "no-go"
    assert decision.blockers == ("explicit-policy-blocker",)
    assert decision.preparation_consumed is False
    assert decision.readiness_provider_calls_already_performed == 0
    assert decision.additional_provider_calls_performed == 0
    assert decision.additional_backend_calls_performed == 0


def test_pre_readiness_gate_rejects_invalid_cases_without_live_work() -> None:
    with pytest.raises(subject.ManagedProductionCompositionError) as caught:
        subject.evaluate_managed_production_pre_readiness(())
    assert caught.value.code == "managed_production_pre_readiness_failed"


def test_policy_blocker_raises_before_runner_delegation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared()
    cases = (ManagedRunCase("case-1", "corpus-1", {"benchmark": "locomo"}),)
    monkeypatch.setattr(subject, "_inspect_managed_live_policy_cases", lambda _: cases)
    monkeypatch.setattr(
        subject,
        "managed_http_policy_production_blockers",
        lambda _: ("explicit-policy-blocker",),
    )
    monkeypatch.setattr(
        subject,
        "run_verified_managed_production_execution",
        lambda _: pytest.fail("blocked preparation must not reach runner"),
    )

    with pytest.raises(subject.ManagedProductionCompositionError) as caught:
        subject.run_verified_managed_production_comparison(prepared)

    assert caught.value.code == "managed_production_blocked"


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


def test_decision_contract_accepts_go_only_without_blockers() -> None:
    decision = subject.ManagedProductionCompositionDecision(
        schema_version=subject.MANAGED_PRODUCTION_COMPOSITION_SCHEMA_VERSION,
        decision="go",
        blockers=(),
        preparation_consumed=False,
        readiness_provider_calls_already_performed=0,
        additional_provider_calls_performed=0,
        additional_backend_calls_performed=0,
    )

    assert decision.public_payload()["decision"] == "go"
    assert decision.public_payload()["blockers"] == []


@pytest.mark.parametrize(
    ("decision", "blockers"),
    (
        ("go", ("unexpected-blocker",)),
        ("no-go", ()),
        ("unknown", ()),
    ),
)
def test_decision_contract_rejects_inconsistent_readiness(
    decision: str,
    blockers: tuple[str, ...],
) -> None:
    with pytest.raises(
        subject.ManagedProductionCompositionError,
        match="managed_production_decision_invalid",
    ):
        subject.ManagedProductionCompositionDecision(
            schema_version=subject.MANAGED_PRODUCTION_COMPOSITION_SCHEMA_VERSION,
            decision=decision,
            blockers=blockers,
            preparation_consumed=False,
            readiness_provider_calls_already_performed=0,
            additional_provider_calls_performed=0,
            additional_backend_calls_performed=0,
        )

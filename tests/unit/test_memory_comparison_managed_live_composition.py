from __future__ import annotations

import copy
import hashlib
import pickle
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from infinity_context_server import memory_comparison_managed_live_composition as subject
from infinity_context_server.memory_comparison_managed_live_admission import (
    MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
    ManagedLiveBudget,
    ManagedLiveProviderUsageBudget,
)
from infinity_context_server.memory_comparison_managed_mem0_runtime_http import (
    ManagedMem0RuntimeHttpError,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_subscription_chat import (
    SUBSCRIPTION_RUNTIME_ESTIMATED_USAGE_SOURCE,
)
from test_memory_comparison_managed_live_admission import _runtime_port

_DATASET = b'{"benchmark":"test"}'
_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _material() -> SimpleNamespace:
    budget = ManagedLiveBudget(
        max_cases=2,
        max_provider_calls=8,
        max_total_tokens=50_000,
    )
    usage = ManagedLiveProviderUsageBudget(
        provider_kind=MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        benchmark_max_provider_calls=8,
        readiness_probe_provider_calls=1,
        total_provider_attempt_ceiling=9,
        benchmark_reserved_token_ceiling=50_000,
        readiness_probe_estimated_tokens=321,
        readiness_probe_usage_source=SUBSCRIPTION_RUNTIME_ESTIMATED_USAGE_SOURCE,
        total_accounted_tokens=50_321,
        token_accounting_publishable=False,
    )
    preflight = SimpleNamespace(
        dataset_sha256=hashlib.sha256(_DATASET).hexdigest(),
        profile_id="locomo",
        answerer_model="gpt-5.6-sol",
        judge_model="gpt-5.6-sol",
        backend_endpoints=(
            SimpleNamespace(target=object()),
            SimpleNamespace(target=object()),
        ),
        scope="canary",
        mem0_expected_runtime_mode="oss",
    )
    runtime_port = _runtime_port(expected_runtime_mode="oss")
    return SimpleNamespace(
        preflight=preflight,
        run_id="managed-run-1",
        run_nonce_commitment_sha256="1" * 64,
        canary_case_ids=("case-1", "case-2"),
        provider_kind=MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        live_provider_evidence=object(),
        mem0_runtime_port=runtime_port,
        mem0_runtime_descriptor=runtime_port.authority_descriptor(),
        budget=budget,
        provider_usage_budget=usage,
        issued_at=_NOW,
        deadline=_NOW + timedelta(minutes=15),
    )


def _prepare(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[subject.VerifiedManagedLiveRunPreparation, SimpleNamespace, dict[str, object]]:
    material = _material()
    captured: dict[str, object] = {}
    admitted = object()
    request = object()
    credential_authority = object()
    readiness_claim = object()
    profile = object()
    route = object()
    plan = object()

    def consume(
        observed: object,
        *,
        expected_request: object,
        now: datetime,
    ) -> SimpleNamespace:
        captured["consume"] = (observed, expected_request, now)
        return material

    def build(**kwargs: object) -> object:
        captured["build"] = kwargs
        return plan

    monkeypatch.setattr(subject, "_consume_verified_managed_live_admission", consume)
    monkeypatch.setattr(subject, "resolve_full_comparison_profile", lambda _: profile)
    monkeypatch.setattr(subject, "_provider_route", lambda *args, **kwargs: route)
    monkeypatch.setattr(subject, "build_verified_managed_run_plan", build)
    monkeypatch.setattr(
        subject,
        "_credential_context_fingerprint",
        lambda authority, claim, **context: hashlib.sha256(
            f"{id(authority)}:{id(claim)}:{context!r}".encode()
        ).hexdigest(),
    )
    prepared = subject.prepare_verified_managed_live_run(
        admitted,
        expected_request=request,
        credential_authority=credential_authority,
        readiness_claim=readiness_claim,
        dataset_bytes=_DATASET,
        now=_NOW,
    )
    captured.update(
        {
            "admitted": admitted,
            "request": request,
            "credential_authority": credential_authority,
            "readiness_claim": readiness_claim,
            "profile": profile,
            "route": route,
            "plan": plan,
        }
    )
    return prepared, material, captured


def test_prepare_derives_every_authority_field_from_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, material, captured = _prepare(monkeypatch)

    assert type(prepared) is subject.VerifiedManagedLiveRunPreparation
    assert repr(prepared) == "VerifiedManagedLiveRunPreparation(<sealed-one-shot>)"
    assert not hasattr(prepared, "plan")
    assert not hasattr(prepared, "mem0_runtime_port")
    assert not hasattr(prepared, "mem0_runtime_descriptor")
    assert captured["consume"] == (
        captured["admitted"],
        captured["request"],
        _NOW,
    )
    built = captured["build"]
    assert isinstance(built, dict)
    assert built == {
        "run_id": material.run_id,
        "run_nonce_commitment_sha256": material.run_nonce_commitment_sha256,
        "runtime_probe_nonce_sha256": material.mem0_runtime_descriptor.probe_nonce_sha256,
        "profile": captured["profile"],
        "dataset_bytes": _DATASET,
        "backend_targets": tuple(item.target for item in material.preflight.backend_endpoints),
        "provider_route": captured["route"],
        "scope": material.preflight.scope,
        "mem0_expected_runtime_mode": material.preflight.mem0_expected_runtime_mode,
        "selected_case_ids": material.canary_case_ids,
    }


def test_limits_bind_total_readiness_and_benchmark_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, material, _ = _prepare(monkeypatch)

    limits = subject.managed_live_execution_limits(prepared)
    assert limits == subject.ManagedLiveExecutionLimits(
        provider_kind=material.provider_kind,
        answerer_model=material.preflight.answerer_model,
        judge_model=material.preflight.judge_model,
        max_cases=2,
        benchmark_max_provider_calls=8,
        readiness_probe_provider_calls=1,
        total_provider_attempt_ceiling=9,
        benchmark_reserved_token_ceiling=50_000,
        readiness_probe_estimated_tokens=321,
        readiness_probe_usage_source=SUBSCRIPTION_RUNTIME_ESTIMATED_USAGE_SOURCE,
        total_accounted_tokens=50_321,
        token_accounting_publishable=False,
        post_reset_mem0_probe_attempt_ceiling=1,
        issued_at=material.issued_at,
        deadline=material.deadline,
    )
    assert limits.public_payload() == {
        "provider_kind": MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        "answerer_model": "gpt-5.6-sol",
        "judge_model": "gpt-5.6-sol",
        "max_cases": 2,
        "benchmark_max_provider_calls": 8,
        "benchmark_provider_call_scope": "answer_judge_only",
        "readiness_probe_provider_calls": 1,
        "total_provider_attempt_ceiling": 9,
        "total_provider_attempt_ceiling_scope": "answer_judge_and_readiness_only",
        "backend_internal_provider_calls": "unmeasured",
        "backend_internal_provider_cost": "unmeasured",
        "total_provider_calls_claimed": False,
        "benchmark_reserved_token_ceiling": 50_000,
        "readiness_probe_estimated_tokens": 321,
        "readiness_probe_usage_source": SUBSCRIPTION_RUNTIME_ESTIMATED_USAGE_SOURCE,
        "total_accounted_tokens": 50_321,
        "token_accounting_publishable": False,
        "post_reset_mem0_probe_attempt_ceiling": 1,
        "issued_at": "2026-08-01T12:00:00.000000Z",
        "deadline": "2026-08-01T12:15:00.000000Z",
    }
    with pytest.raises(ManagedRunError, match="execution limits are invalid"):
        replace(
            limits,
            readiness_probe_usage_source="estimated_by_untrusted_runtime",
        )


def test_prepare_burns_admission_before_dataset_hash_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = _material()
    calls = 0

    def consume(*args: object, **kwargs: object) -> SimpleNamespace:
        nonlocal calls
        del args, kwargs
        calls += 1
        return material

    monkeypatch.setattr(subject, "_consume_verified_managed_live_admission", consume)
    monkeypatch.setattr(
        subject,
        "build_verified_managed_run_plan",
        lambda **_: pytest.fail("builder must not receive an unbound dataset"),
    )

    with pytest.raises(
        ManagedRunError,
        match="dataset differs from admitted preflight",
    ):
        subject.prepare_verified_managed_live_run(
            object(),
            expected_request=object(),
            credential_authority=object(),
            readiness_claim=object(),
            dataset_bytes=b"different",
            now=_NOW,
        )

    assert calls == 1


def test_prepare_rejects_runtime_descriptor_mode_that_differs_from_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = _material()
    material.mem0_runtime_descriptor = replace(
        material.mem0_runtime_descriptor,
        expected_runtime_mode="managed_platform",
    )

    monkeypatch.setattr(
        subject,
        "_consume_verified_managed_live_admission",
        lambda *args, **kwargs: material,
    )

    with pytest.raises(ManagedRunError, match="runtime mode differs from admitted preflight"):
        subject.prepare_verified_managed_live_run(
            object(),
            expected_request=object(),
            credential_authority=object(),
            readiness_claim=object(),
            dataset_bytes=_DATASET,
            now=_NOW,
        )


def test_preparation_is_opaque_noncopyable_and_nonserializable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _, _ = _prepare(monkeypatch)

    with pytest.raises(ManagedRunError, match="authoritatively"):
        subject.VerifiedManagedLiveRunPreparation(
            commitment="0" * 64,
            _token=object(),
        )
    with pytest.raises(TypeError, match="noncopyable"):
        copy.copy(prepared)
    with pytest.raises(TypeError, match="noncopyable"):
        copy.deepcopy(prepared)
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(prepared)


def test_no_public_execution_bypass_is_exposed() -> None:
    assert not hasattr(subject, "run_verified_managed_live_comparison")
    assert "run_verified_managed_live_comparison" not in subject.__all__


def test_private_consume_enforces_deadline_and_burns_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, material, _ = _prepare(monkeypatch)

    with pytest.raises(ManagedRunError, match="expired or not yet current"):
        subject._consume_verified_managed_live_run_preparation(
            prepared,
            now=material.deadline + timedelta(microseconds=1),
        )

    with pytest.raises(ManagedRunError, match="unavailable or consumed"):
        subject._consume_verified_managed_live_run_preparation(
            prepared,
            now=material.deadline,
        )


def test_private_consume_returns_exact_plan_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, admitted_material, captured = _prepare(monkeypatch)

    material = subject._consume_verified_managed_live_run_preparation(
        prepared,
        now=_NOW,
    )
    assert material.plan is captured["plan"]
    assert material.preflight_request is captured["request"]
    assert material.credential_authority is captured["credential_authority"]
    assert material.readiness_claim is captured["readiness_claim"]
    assert material.mem0_runtime_port is admitted_material.mem0_runtime_port
    assert material.mem0_runtime_descriptor is admitted_material.mem0_runtime_descriptor

    with pytest.raises(ManagedRunError, match="unavailable or consumed"):
        subject._consume_verified_managed_live_run_preparation(
            prepared,
            now=_NOW,
        )


def test_runtime_authority_identity_is_bound_to_sealed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _, _ = _prepare(monkeypatch)
    state = subject._PREPARED_RUNS[prepared]
    subject._PREPARED_RUNS[prepared] = replace(
        state,
        mem0_runtime_port=_runtime_port(),
    )

    with pytest.raises(ManagedRunError, match="integrity failed"):
        subject.managed_live_execution_limits(prepared)


def test_credential_authority_identity_is_bound_to_sealed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _, _ = _prepare(monkeypatch)
    state = subject._PREPARED_RUNS[prepared]
    subject._PREPARED_RUNS[prepared] = replace(
        state,
        credential_authority=object(),
    )

    with pytest.raises(ManagedRunError, match="integrity failed"):
        subject.managed_live_execution_limits(prepared)


def test_runtime_authority_evidence_key_rejects_unverified_objects() -> None:
    with pytest.raises(ManagedRunError, match="type is invalid"):
        subject._runtime_authority_evidence_key(object(), object())


def test_unspent_runtime_authority_is_required_until_private_consume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, admitted_material, _ = _prepare(monkeypatch)
    port = admitted_material.mem0_runtime_port
    descriptor = admitted_material.mem0_runtime_descriptor

    assert port.authority_descriptor() is descriptor
    with pytest.raises(ManagedMem0RuntimeHttpError):
        port.attest(
            run_id=admitted_material.run_id,
            probe_nonce_sha256="0" * 64,
            target_identity_sha256=descriptor.target_identity_sha256,
        )

    with pytest.raises(ManagedRunError, match="authority is unavailable"):
        subject._consume_verified_managed_live_run_preparation(
            prepared,
            now=_NOW,
        )


def test_models_are_bound_into_preparation_commitment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _, _ = _prepare(monkeypatch)
    state = subject._PREPARED_RUNS[prepared]
    subject._PREPARED_RUNS[prepared] = replace(
        state,
        limits=replace(state.limits, answerer_model="different-model"),
    )

    with pytest.raises(ManagedRunError, match="integrity failed"):
        subject.managed_live_execution_limits(prepared)


def test_usage_source_is_bound_into_preparation_commitment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _, _ = _prepare(monkeypatch)
    state = subject._PREPARED_RUNS[prepared]
    object.__setattr__(
        state.limits,
        "readiness_probe_usage_source",
        "estimated_by_untrusted_runtime",
    )

    with pytest.raises(ManagedRunError, match="integrity failed"):
        subject.managed_live_execution_limits(prepared)


def test_integrity_tampering_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _, _ = _prepare(monkeypatch)
    object.__setattr__(
        prepared,
        "_VerifiedManagedLiveRunPreparation__commitment",
        "0" * 64,
    )

    with pytest.raises(ManagedRunError, match="integrity failed"):
        subject.managed_live_execution_limits(prepared)

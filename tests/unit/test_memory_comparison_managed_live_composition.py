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
    MANAGED_PROVIDER_OPENAI_API_KEY,
    ManagedLiveBudget,
    ManagedLiveProviderUsageBudget,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError

_DATASET = b'{"benchmark":"test"}'
_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _material() -> SimpleNamespace:
    budget = ManagedLiveBudget(
        max_cases=2,
        max_provider_calls=8,
        max_total_tokens=50_000,
    )
    usage = ManagedLiveProviderUsageBudget(
        benchmark_max_provider_calls=8,
        readiness_probe_provider_calls=1,
        total_provider_attempt_ceiling=9,
        benchmark_max_total_tokens=50_000,
        readiness_probe_observed_tokens=321,
        total_token_ceiling=50_321,
    )
    preflight = SimpleNamespace(
        dataset_sha256=hashlib.sha256(_DATASET).hexdigest(),
        profile_id="locomo",
        backend_endpoints=(
            SimpleNamespace(target=object()),
            SimpleNamespace(target=object()),
        ),
        scope="canary",
    )
    return SimpleNamespace(
        preflight=preflight,
        run_id="managed-run-1",
        run_nonce_commitment_sha256="1" * 64,
        runtime_probe_nonce_sha256="2" * 64,
        canary_case_ids=("case-1", "case-2"),
        provider_kind=MANAGED_PROVIDER_OPENAI_API_KEY,
        live_provider_evidence=object(),
        runtime_validation=object(),
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
        "_runtime_validation_evidence_key",
        lambda validation: (str(id(validation)), "a" * 64),
    )
    prepared = subject.prepare_verified_managed_live_run(
        admitted,
        expected_request=request,
        dataset_bytes=_DATASET,
        now=_NOW,
    )
    captured.update(
        {
            "admitted": admitted,
            "request": request,
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
    assert not hasattr(prepared, "runtime_validation")
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
        "runtime_probe_nonce_sha256": material.runtime_probe_nonce_sha256,
        "profile": captured["profile"],
        "dataset_bytes": _DATASET,
        "backend_targets": tuple(item.target for item in material.preflight.backend_endpoints),
        "provider_route": captured["route"],
        "scope": material.preflight.scope,
        "selected_case_ids": material.canary_case_ids,
    }


def test_limits_bind_total_readiness_and_benchmark_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, material, _ = _prepare(monkeypatch)

    assert subject.managed_live_execution_limits(prepared) == subject.ManagedLiveExecutionLimits(
        provider_kind=material.provider_kind,
        max_cases=2,
        benchmark_max_provider_calls=8,
        readiness_probe_provider_calls=1,
        total_provider_attempt_ceiling=9,
        benchmark_max_total_tokens=50_000,
        readiness_probe_observed_tokens=321,
        total_token_ceiling=50_321,
        issued_at=material.issued_at,
        deadline=material.deadline,
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
            dataset_bytes=b"different",
            now=_NOW,
        )

    assert calls == 1


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
    assert material.runtime_validation is admitted_material.runtime_validation

    with pytest.raises(ManagedRunError, match="unavailable or consumed"):
        subject._consume_verified_managed_live_run_preparation(
            prepared,
            now=_NOW,
        )


def test_runtime_validation_identity_is_bound_to_sealed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _, _ = _prepare(monkeypatch)
    state = subject._PREPARED_RUNS[prepared]
    subject._PREPARED_RUNS[prepared] = replace(
        state,
        runtime_validation=object(),
    )

    with pytest.raises(ManagedRunError, match="integrity failed"):
        subject.managed_live_execution_limits(prepared)


def test_runtime_validation_evidence_key_rejects_unverified_objects() -> None:
    with pytest.raises(ManagedRunError, match="type is invalid"):
        subject._runtime_validation_evidence_key(object())


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

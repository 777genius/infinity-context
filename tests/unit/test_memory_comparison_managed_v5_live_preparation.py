from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from _phase_c_hermetic import install_hermetic_phase_c_authority
from infinity_context_server import (
    memory_comparison_managed_benchmark_registry_http as registry,
)
from infinity_context_server import (
    memory_comparison_managed_live_composition as live,
)
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_composition as mem0_composition,
)
from infinity_context_server import (
    memory_comparison_managed_v5_infinity_credentials as infinity_credentials,
)
from infinity_context_server import (
    memory_comparison_managed_v5_live_preparation as subject,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_managed_runtime_credentials_models import (
    ManagedRuntimeCredentialError,
)
from test_memory_comparison_managed_mem0_v5_production_foundation import (
    PHASE_C_ROOT,
    _public_inputs,
)
from test_memory_comparison_managed_runtime_credentials import (
    _DEADLINE,
    _NOW,
    _RUN_ID,
    _authority,
    _bind,
)


@pytest.fixture(autouse=True)
def _hermetic_public_authority(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_hermetic_phase_c_authority(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        phase_c_root=PHASE_C_ROOT,
    )
    monkeypatch.setattr(
        mem0_composition,
        "require_mem0_v5_observed_extraction_receipt_boundary",
        lambda **_values: None,
    )


def _preparation_values(tmp_path) -> dict[str, object]:
    values, _ = _public_inputs(tmp_path)
    accepted = {
        "cases",
        "current_date",
        "request",
        "composition_binding",
        "origin",
        "timeout_seconds",
        "state_paths",
        "credential_paths",
        "runtime_receipt_boundary",
        "trusted_runtime_binding",
        "receipt_authority",
        "dispatch_guard",
        "transport",
    }
    return {key: value for key, value in values.items() if key in accepted}


def _prepare(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    values = _preparation_values(tmp_path)
    return values, subject.prepare_managed_v5_public_run(**values)


def _plan_for(state: object) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=state.request.run_id,
        cases=state.cases,
        backend_targets=state.composition_binding.backend_targets,
    )


def _activate(
    preparation: object,
    state: object,
    *,
    production_authority: object | None = None,
):
    return subject._activate_managed_v5_public_run(
        preparation,
        cases=state.cases,
        request=state.request,
        composition_binding=state.composition_binding,
        receipt_authority=state.receipt_authority,
        production_authority=(
            state.production_authority if production_authority is None else production_authority
        ),
        plan=_plan_for(state),
        now=state.deadline.replace(year=state.deadline.year - 1),
    )


def test_public_preparation_finishes_before_any_private_or_live_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    calls = {"secret": 0, "compose": 0, "readiness": 0, "registry": 0}

    def trap(name: str):
        def fail(*_args: object, **_kwargs: object) -> None:
            calls[name] += 1
            raise AssertionError(f"forbidden public-stage call: {name}")

        return fail

    monkeypatch.setattr(mem0_composition, "load_managed_mem0_v5_credentials", trap("secret"))
    monkeypatch.setattr(mem0_composition, "compose_managed_mem0_v5", trap("compose"))
    monkeypatch.setattr(live, "prepare_verified_managed_live_run", trap("readiness"))
    monkeypatch.setattr(registry.ManagedBenchmarkRegistryHttpAdapter, "__init__", trap("registry"))

    _values, preparation = _prepare(tmp_path)

    assert type(preparation) is subject.ManagedV5PublicRunPreparation
    assert calls == {"secret": 0, "compose": 0, "readiness": 0, "registry": 0}


def test_activation_rejects_hmac_tamper_without_activating(tmp_path) -> None:
    _values, preparation = _prepare(tmp_path)
    state = subject._STATES[preparation]
    subject._STATES[preparation] = replace(state, integrity_mac=b"tampered")

    with pytest.raises(ManagedRunError, match="unavailable"):
        _activate(preparation, state)
    assert preparation in subject._STATES

    with pytest.raises(ManagedRunError, match="unavailable"):
        _activate(preparation, state)


def test_activation_rejects_cross_wire_and_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(subject, "_inspect_verified_managed_run_plan", lambda plan: plan)
    _first_values, first = _prepare(tmp_path / "first")
    _second_values, second = _prepare(tmp_path / "second")
    first_state = subject._STATES[first]
    second_state = subject._STATES[second]
    with pytest.raises(ManagedRunError, match="activation invalid"):
        _activate(first, first_state, production_authority=second_state.production_authority)
    with pytest.raises(ManagedRunError, match="unavailable"):
        _activate(first, first_state)

    activated = _activate(second, second_state)
    assert activated.production_authority is second_state.production_authority
    with pytest.raises(ManagedRunError, match="unavailable"):
        _activate(second, second_state)


def test_infinity_credentials_require_public_preparation_before_secret_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infinity_context_server import memory_comparison_managed_http_execution as legacy

    mem0_constructions = 0

    def mem0_forbidden(*_args: object, **_kwargs: object) -> None:
        nonlocal mem0_constructions
        mem0_constructions += 1
        raise AssertionError("legacy Mem0 config constructed")

    monkeypatch.setattr(legacy.ManagedMem0HttpConfig, "__init__", mem0_forbidden)
    authority = _authority()
    request = _bind(authority)
    infinity_origin = request.backend_endpoints[0].base_url
    with pytest.raises(
        ManagedRuntimeCredentialError,
        match="managed_credentials_configuration_invalid",
    ):
        authority.issue_managed_v5_infinity_credentials(
            expected_request=request,
            public_preparation=object(),
            run_id=_RUN_ID,
            infinity_origin=infinity_origin,
            deadline=_DEADLINE,
            now=_NOW,
        )
    assert mem0_constructions == 0
    assert "ManagedMem0HttpConfig" not in infinity_credentials.__dict__

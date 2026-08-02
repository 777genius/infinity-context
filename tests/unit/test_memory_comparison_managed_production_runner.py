from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from infinity_context_server import memory_comparison_managed_production_runner as subject
from infinity_context_server.memory_comparison_managed_live_composition import (
    VerifiedManagedLiveRunPreparation,
)
from infinity_context_server.memory_comparison_managed_run import ManagedRunOutcome

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
_PRIVATE = "PRIVATE-SECRET-MUST-NOT-LEAK"


@dataclass
class _Capture:
    constructors: dict[str, dict[str, object]]
    runner: dict[str, object] | None = None


class _Subscription:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Provider:
    def __init__(
        self,
        *,
        delegate: object,
        budget: object,
        monotonic_clock: object,
        fail_close: bool = False,
    ) -> None:
        self.delegate = delegate
        self.budget = budget
        self.monotonic_clock = monotonic_clock
        self.fail_close = fail_close
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self.delegate.close()
        if self.fail_close:
            raise RuntimeError("close failed")


class _Http:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _BackendCredentials:
    def __init__(self, capture: _Capture) -> None:
        self.capture = capture
        self.registry_calls = 0
        self.registry_credential = SimpleNamespace(
            base_url="https://infinity.test",
            auth_token="registry-secret",
            target_identity_sha256="a" * 64,
            timeout_seconds=15.0,
            transport=object(),
        )

    def consume_for_benchmark_registry(self, **kwargs: object) -> object:
        self.registry_calls += 1
        self.capture.constructors["registry_credential"] = kwargs
        return self.registry_credential


class _Registry:
    def __init__(
        self,
        config: object,
        *,
        created: bool,
        register_failure_once: bool = False,
        close_warning_code: str | None = None,
    ) -> None:
        self.config = config
        self.created = created
        self.register_failure_once = register_failure_once
        self.close_warning_code = close_warning_code
        self.closed = False
        self.register_calls: list[dict[str, object]] = []
        self.registration = SimpleNamespace(created=created)
        self.cleanup_receipt = None
        self.begin_cleanup_calls = 0
        self.finalize_abort_calls = 0

    def register(self, **kwargs: object) -> object:
        self.register_calls.append(kwargs)
        if self.register_failure_once and len(self.register_calls) == 1:
            raise RuntimeError(_PRIVATE)
        return self.registration

    def begin_cleanup(self) -> object:
        self.begin_cleanup_calls += 1
        self.cleanup_receipt = SimpleNamespace(
            projection_cleanup="blocked",
            receipt_sha256="f" * 64,
        )
        return self.cleanup_receipt

    def finalize_unsealed_abort(self, **kwargs: object) -> object:
        assert kwargs == {
            "cleanup_initiation_receipt_sha256": "f" * 64,
        }
        self.finalize_abort_calls += 1
        return SimpleNamespace(state="cleanup_aborted")

    def close(self) -> None:
        self.closed = True


class _Authority:
    def __init__(self, subscription: _Subscription, capture: _Capture) -> None:
        self.subscription = subscription
        self.capture = capture
        self.backend_credentials = _BackendCredentials(capture)
        self.execution_calls = 0
        self.backend_calls = 0

    def issue_subscription_execution_adapter(self, **kwargs: object) -> _Subscription:
        self.execution_calls += 1
        self.capture.constructors["subscription"] = kwargs
        return self.subscription

    def issue_backend_credential_material(self, **kwargs: object) -> object:
        self.backend_calls += 1
        self.capture.constructors["credentials"] = kwargs
        return self.backend_credentials


def _prepared() -> VerifiedManagedLiveRunPreparation:
    return object.__new__(VerifiedManagedLiveRunPreparation)


def _outcome() -> ManagedRunOutcome:
    return object.__new__(ManagedRunOutcome)


def _install_success_wiring(
    monkeypatch: pytest.MonkeyPatch,
    *,
    benchmark: str = "locomo",
    runner_failure: BaseException | None = None,
    provider_close_failure: bool = False,
    registry_created: bool = True,
    registry_register_failure_once: bool = False,
    registry_close_warning_code: str | None = None,
    completion_state: str | None = "cleanup_complete",
) -> tuple[
    VerifiedManagedLiveRunPreparation,
    _Capture,
    _Authority,
    _Subscription,
    SimpleNamespace,
    _Http,
    ManagedRunOutcome,
]:
    prepared = _prepared()
    case = object()
    cases = (case,)
    route = object()
    targets = (object(), object())
    plan_authority = object()
    plan = SimpleNamespace(
        run_id="run-1",
        cases=cases,
        backend_targets=targets,
        provider_route=route,
        profile=SimpleNamespace(benchmark=benchmark),
    )
    request = SimpleNamespace(
        provider_route=SimpleNamespace(origin="http://127.0.0.1:8890"),
        backend_endpoints=(
            SimpleNamespace(
                target=SimpleNamespace(backend_role="infinity-context"),
                base_url="https://infinity.test",
            ),
            SimpleNamespace(
                target=SimpleNamespace(backend_role="mem0"),
                base_url="https://mem0.test",
            ),
        ),
    )
    limits = SimpleNamespace(
        deadline=_NOW + timedelta(minutes=2),
        benchmark_reserved_token_ceiling=100_000,
        benchmark_max_provider_calls=4,
    )
    capture = _Capture({})
    subscription = _Subscription()
    authority = _Authority(subscription, capture)
    attestation_port = object()
    material = SimpleNamespace(
        plan=plan_authority,
        preflight_request=request,
        limits=limits,
        credential_authority=authority,
        readiness_claim=object(),
        mem0_runtime_port=attestation_port,
    )
    bindings = SimpleNamespace(binding_commitment_sha256="b" * 64)
    reset_port = object()
    ingest_port = object()
    execution_port = object()
    judge_port = object()
    expected_outcome = _outcome()
    created_http = _Http()

    monkeypatch.setattr(subject, "_inspect_managed_live_policy_cases", lambda value: cases)
    monkeypatch.setattr(subject, "managed_http_policy_production_blockers", lambda value: ())
    monkeypatch.setattr(
        subject,
        "_consume_verified_managed_live_run_preparation",
        lambda value, **kwargs: material,
    )
    monkeypatch.setattr(subject, "_inspect_verified_managed_run_plan", lambda value: plan)
    monkeypatch.setattr(
        subject,
        "create_managed_comparison_run_bindings",
        lambda value: bindings,
    )

    def provider_factory(**kwargs: object) -> _Provider:
        capture.constructors["provider"] = kwargs
        return _Provider(**kwargs, fail_close=provider_close_failure)

    def http_factory(**kwargs: object) -> _Http:
        capture.constructors["http"] = kwargs
        created_http.kwargs = kwargs
        return created_http

    def registry_config_factory(**kwargs: object) -> object:
        capture.constructors["registry_config"] = kwargs
        return SimpleNamespace(**kwargs)

    def registry_factory(config: object) -> _Registry:
        capture.constructors["registry_adapter"] = {"config": config}
        registry = _Registry(
            config,
            created=registry_created,
            register_failure_once=registry_register_failure_once,
            close_warning_code=registry_close_warning_code,
        )
        capture.constructors["registry_instance"] = {"value": registry}
        return registry

    def lifecycle_factory(**kwargs: object) -> object:
        capture.constructors["lifecycle"] = kwargs
        return SimpleNamespace(name="lifecycle")

    def policy_factory(**kwargs: object) -> object:
        capture.constructors["policy"] = kwargs
        policy = SimpleNamespace(name="policy")
        capture.constructors["policy_instance"] = {"value": policy}
        return policy

    def registry_policy_factory(**kwargs: object) -> object:
        capture.constructors["registry_policy"] = kwargs
        completion = None if completion_state is None else SimpleNamespace(state=completion_state)
        registry_policy = SimpleNamespace(
            name="registry-policy",
            terminal_completion_receipt=completion,
        )
        capture.constructors["registry_policy_instance"] = {"value": registry_policy}
        return registry_policy

    def assembler_factory(**kwargs: object) -> object:
        capture.constructors["assembler"] = kwargs
        return SimpleNamespace(name="assembler")

    monkeypatch.setattr(subject, "BoundedProviderChatCompletions", provider_factory)
    monkeypatch.setattr(subject, "ManagedBenchmarkRegistryHttpConfig", registry_config_factory)
    monkeypatch.setattr(subject, "ManagedBenchmarkRegistryHttpAdapter", registry_factory)
    monkeypatch.setattr(subject, "ManagedComparisonHttpExecutionAdapter", http_factory)
    monkeypatch.setattr(subject, "ManagedComparisonHttpLifecycleAdapter", lifecycle_factory)
    monkeypatch.setattr(
        subject,
        "create_managed_production_lifecycle_ports",
        lambda lifecycle: SimpleNamespace(reset=reset_port, ingest=ingest_port),
    )
    monkeypatch.setattr(
        subject,
        "ManagedComparisonHttpPolicyLifecycleAdapter",
        policy_factory,
    )
    monkeypatch.setattr(
        subject,
        "ManagedComparisonRegistryPolicyLifecycleAdapter",
        registry_policy_factory,
    )
    monkeypatch.setattr(
        subject,
        "create_managed_comparison_execution_ports",
        lambda **kwargs: (
            capture.constructors.__setitem__("execution", kwargs)
            or SimpleNamespace(
                execution_port=execution_port,
                judge_port=judge_port,
            )
        ),
    )
    monkeypatch.setattr(subject, "ManagedFullComparisonAssembler", assembler_factory)

    def run(admission: object, **kwargs: object) -> ManagedRunOutcome:
        kwargs["admission"] = admission
        capture.runner = kwargs
        if runner_failure is not None:
            raise runner_failure
        return expected_outcome

    monkeypatch.setattr(subject, "run_managed_comparison_with_bindings", run)
    return (
        prepared,
        capture,
        authority,
        subscription,
        bindings,
        created_http,
        expected_outcome,
    )


@pytest.mark.parametrize(
    ("clock_argument", "value"),
    (
        ("now", _NOW),
        ("wall_clock", lambda: _NOW),
        ("monotonic_clock", lambda: 100.0),
    ),
)
def test_public_entrypoint_does_not_accept_clock_injection(
    clock_argument: str, value: object
) -> None:
    assert tuple(
        inspect.signature(subject.run_verified_managed_production_execution).parameters
    ) == ("prepared",)
    with pytest.raises(TypeError):
        subject.run_verified_managed_production_execution(_prepared(), **{clock_argument: value})


def test_composes_exact_shared_bindings_and_closes_owned_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        prepared,
        capture,
        authority,
        subscription,
        bindings,
        http,
        expected,
    ) = _install_success_wiring(monkeypatch)

    observed = subject._run_verified_managed_production_execution(
        prepared,
        now=_NOW,
        wall_clock=lambda: _NOW,
        monotonic_clock=lambda: 100.0,
    )

    assert observed is expected
    assert capture.runner is not None
    assert capture.runner["bindings"] is bindings
    assert capture.constructors["policy"]["bindings"] is bindings
    registry = capture.constructors["registry_instance"]["value"]
    assert isinstance(registry, _Registry)
    registry_policy = capture.constructors["registry_policy_instance"]["value"]
    assert capture.runner["policy_port"] is registry_policy
    assert (
        capture.constructors["registry_policy"]["delegate"]
        is (capture.constructors["policy_instance"]["value"])
    )
    assert capture.constructors["registry_policy"]["registry"] is registry
    assert capture.constructors["registry_policy"]["bindings"] is bindings
    assert (
        capture.constructors["registry_policy"]["cases"]
        is (capture.constructors["policy"]["cases"])
    )
    assert capture.constructors["registry_policy"]["registration"] is registry.registration
    assert (
        capture.constructors["lifecycle"]["binding_commitment_sha256"]
        == bindings.binding_commitment_sha256
    )
    assert capture.constructors["lifecycle"]["benchmark_registration"] is (registry.registration)
    assert capture.constructors["execution"]["provider_route"] is not None
    assert capture.constructors["assembler"]["reset_port"] is capture.runner["reset_port"]
    assert capture.constructors["assembler"]["ingest_port"] is capture.runner["ingest_port"]
    assert capture.constructors["assembler"]["clock"] is capture.runner["clock"]
    assert authority.execution_calls == 1
    assert authority.backend_calls == 1
    assert capture.constructors["credentials"]["mem0_send_timestamps"] is True
    assert authority.backend_credentials.registry_calls == 1
    assert capture.constructors["registry_credential"] == {
        "expected_request": capture.constructors["credentials"]["expected_request"],
        "run_id": "run-1",
        "deadline": _NOW + timedelta(minutes=2),
    }
    registry_config = capture.constructors["registry_config"]
    credential = authority.backend_credentials.registry_credential
    assert registry_config["base_url"] == credential.base_url
    assert registry_config["admin_bearer_token"] == credential.auth_token
    assert registry_config["target_identity_sha256"] == credential.target_identity_sha256
    assert registry_config["timeout_seconds"] == credential.timeout_seconds
    assert registry_config["benchmark_deadline"] == _NOW + timedelta(minutes=2)
    assert registry_config["cleanup_recovery_timeout_seconds"] == (credential.timeout_seconds)
    assert registry_config["transport"] is credential.transport
    assert registry_config["clock"].__self__ is capture.runner["clock"]
    assert registry.register_calls == [
        {
            "run_id_sha256": hashlib.sha256(b"run-1").hexdigest(),
            "binding_commitment_sha256": bindings.binding_commitment_sha256,
            "space_slug": subject.managed_http_lifecycle_space_slug("run-1"),
        }
    ]
    budget = capture.constructors["provider"]["budget"]
    assert budget.max_total_tokens == 100_000
    assert budget.max_calls == 4
    assert budget.max_output_tokens_per_call == 4096
    assert budget.deadline_monotonic == 220.0
    assert subscription.closed is True
    assert http.closed is True
    assert registry.closed is True


def test_static_blocker_prevents_preparation_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared()
    monkeypatch.setattr(subject, "_inspect_managed_live_policy_cases", lambda value: (object(),))
    monkeypatch.setattr(
        subject,
        "managed_http_policy_production_blockers",
        lambda value: ("blocked",),
    )
    monkeypatch.setattr(
        subject,
        "_consume_verified_managed_live_run_preparation",
        lambda *args, **kwargs: pytest.fail("blocked preparation must not be consumed"),
    )

    with pytest.raises(subject.ManagedProductionRunnerError) as caught:
        subject._run_verified_managed_production_execution(
            prepared,
            now=_NOW,
            wall_clock=lambda: _NOW,
            monotonic_clock=lambda: 100.0,
        )

    assert caught.value.code == "managed_production_runner_blocked"


def test_runner_failure_is_sanitized_and_resources_are_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, capture, _, subscription, _, http, _ = _install_success_wiring(
        monkeypatch,
        runner_failure=RuntimeError(_PRIVATE),
    )

    with pytest.raises(subject.ManagedProductionRunnerError) as caught:
        subject._run_verified_managed_production_execution(
            prepared,
            now=_NOW,
            wall_clock=lambda: _NOW,
            monotonic_clock=lambda: 100.0,
        )

    assert caught.value.code == "managed_production_runner_failed"
    assert _PRIVATE not in str(caught.value)
    assert subscription.closed is True
    assert http.closed is True
    registry = capture.constructors["registry_instance"]["value"]
    assert isinstance(registry, _Registry)
    assert registry.begin_cleanup_calls == 1
    assert registry.finalize_abort_calls == 1
    assert registry.closed is True


def test_cleanup_failure_after_success_is_typed_and_http_still_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, capture, _, subscription, _, http, _ = _install_success_wiring(
        monkeypatch,
        provider_close_failure=True,
    )

    with pytest.raises(subject.ManagedProductionRunnerError) as caught:
        subject._run_verified_managed_production_execution(
            prepared,
            now=_NOW,
            wall_clock=lambda: _NOW,
            monotonic_clock=lambda: 100.0,
        )

    assert caught.value.code == "managed_production_runner_cleanup_failed"
    assert subscription.closed is True
    assert http.closed is True
    registry = capture.constructors["registry_instance"]["value"]
    assert isinstance(registry, _Registry)
    assert registry.closed is True


def test_unknown_initial_registration_is_recovered_and_aborted_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, capture, _, subscription, _, http, _ = _install_success_wiring(
        monkeypatch,
        registry_register_failure_once=True,
    )

    with pytest.raises(subject.ManagedProductionRunnerError) as caught:
        subject._run_verified_managed_production_execution(
            prepared,
            now=_NOW,
            wall_clock=lambda: _NOW,
            monotonic_clock=lambda: 100.0,
        )

    assert caught.value.code == "managed_production_runner_failed"
    assert _PRIVATE not in str(caught.value)
    registry = capture.constructors["registry_instance"]["value"]
    assert isinstance(registry, _Registry)
    assert len(registry.register_calls) == 2
    assert registry.register_calls[0] == registry.register_calls[1]
    assert registry.begin_cleanup_calls == 1
    assert registry.finalize_abort_calls == 1
    assert registry.closed is True
    assert subscription.closed is True
    assert http.closed is False
    assert capture.runner is None


def test_registry_close_warning_after_success_is_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, capture, _, subscription, _, http, _ = _install_success_wiring(
        monkeypatch,
        registry_close_warning_code="managed_benchmark_registry_close_failed",
    )

    with pytest.raises(subject.ManagedProductionRunnerError) as caught:
        subject._run_verified_managed_production_execution(
            prepared,
            now=_NOW,
            wall_clock=lambda: _NOW,
            monotonic_clock=lambda: 100.0,
        )

    assert caught.value.code == "managed_production_runner_cleanup_failed"
    assert capture.runner is not None
    registry_policy = capture.constructors["registry_policy_instance"]["value"]
    assert registry_policy.terminal_completion_receipt.state == "cleanup_complete"
    registry = capture.constructors["registry_instance"]["value"]
    assert isinstance(registry, _Registry)
    assert registry.begin_cleanup_calls == 0
    assert registry.finalize_abort_calls == 0
    assert registry.closed is True
    assert subscription.closed is True
    assert http.closed is True


def test_registry_replay_is_rejected_and_owned_resources_are_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, capture, authority, subscription, _, http, _ = _install_success_wiring(
        monkeypatch,
        registry_created=False,
    )

    with pytest.raises(subject.ManagedProductionRunnerError) as caught:
        subject._run_verified_managed_production_execution(
            prepared,
            now=_NOW,
            wall_clock=lambda: _NOW,
            monotonic_clock=lambda: 100.0,
        )

    assert caught.value.code == "managed_production_registry_replay"
    registry = capture.constructors["registry_instance"]["value"]
    assert isinstance(registry, _Registry)
    assert registry.register_calls
    assert registry.closed is True
    assert authority.backend_credentials.registry_calls == 1
    assert subscription.closed is True
    assert http.closed is False
    assert capture.runner is None
    assert "registry_policy" not in capture.constructors


@pytest.mark.parametrize("completion_state", (None, "cleanup_pending"))
def test_missing_terminal_registry_completion_proof_is_rejected_after_run(
    monkeypatch: pytest.MonkeyPatch,
    completion_state: str | None,
) -> None:
    prepared, capture, _, subscription, _, http, _ = _install_success_wiring(
        monkeypatch,
        completion_state=completion_state,
    )

    with pytest.raises(subject.ManagedProductionRunnerError) as caught:
        subject._run_verified_managed_production_execution(
            prepared,
            now=_NOW,
            wall_clock=lambda: _NOW,
            monotonic_clock=lambda: 100.0,
        )

    assert caught.value.code == "managed_production_registry_incomplete"
    assert capture.runner is not None
    registry = capture.constructors["registry_instance"]["value"]
    assert isinstance(registry, _Registry)
    assert registry.closed is True
    assert subscription.closed is True
    assert http.closed is True


def test_expired_deadline_rejects_before_consuming_credential_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, _, authority, subscription, _, _, _ = _install_success_wiring(monkeypatch)

    with pytest.raises(subject.ManagedProductionRunnerError) as caught:
        subject._run_verified_managed_production_execution(
            prepared,
            now=_NOW,
            wall_clock=lambda: _NOW + timedelta(minutes=3),
            monotonic_clock=lambda: 100.0,
        )

    assert caught.value.code == "managed_production_deadline_expired"
    assert authority.execution_calls == 0
    assert authority.backend_calls == 0
    assert subscription.closed is False


def test_forged_preparation_is_rejected_before_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "_inspect_managed_live_policy_cases",
        lambda value: pytest.fail("forged preparation must not be inspected"),
    )

    with pytest.raises(subject.ManagedProductionRunnerError) as caught:
        subject._run_verified_managed_production_execution(
            object(),  # type: ignore[arg-type]
            now=_NOW,
            wall_clock=lambda: _NOW,
            monotonic_clock=lambda: 100.0,
        )

    assert caught.value.code == "managed_production_preparation_invalid"

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from infinity_context_server import memory_comparison_managed_v5_live_preparation as prep
from infinity_context_server import memory_comparison_managed_v5_production_runner as runner
from infinity_context_server.memory_comparison_managed_infinity_http_execution import (
    ManagedInfinityHttpExecutionAdapter,
    ManagedInfinityHttpExecutionError,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_managed_runtime_credentials_models import (
    ManagedRuntimeCredentialError,
)
from infinity_context_server.memory_comparison_managed_v5_infinity_credentials import (
    ManagedV5InfinityCredentialBundle,
)
from infinity_context_server.memory_comparison_managed_v5_ingest_identity_projector import (
    ManagedV5IngestIdentityProjectionError,
    project_managed_infinity_v5_ingest_identities,
)
from infinity_context_server.memory_comparison_managed_v5_owned_resources import (
    ManagedV5OwnedResources,
)
from infinity_context_server.memory_comparison_managed_v5_runtime_factory import (
    ManagedV5ProductionRuntimeFactoryError,
    _tracked_factory,
)
from test_memory_comparison_managed_mem0_v5_runner_foundation import _authority_and_case


class _RetryingBackend:
    def __init__(self) -> None:
        self.calls = 0

    def close(self) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("private close failure")


class _TrackedTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.closed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        del request
        raise AssertionError("transport must not perform I/O")

    def close(self) -> None:
        self.closed = True


def test_infinity_execution_close_is_retryable_idempotent_and_deadline_independent() -> None:
    adapter = object.__new__(ManagedInfinityHttpExecutionAdapter)
    backend = _RetryingBackend()
    object.__setattr__(adapter, "_backend", backend)
    object.__setattr__(adapter, "_closed", False)

    with pytest.raises(ManagedInfinityHttpExecutionError, match="close_failed"):
        adapter.close()
    assert adapter._closed is False

    adapter.close()
    adapter.close()

    assert adapter._closed is True
    assert backend.calls == 2


def test_ingest_projector_normalizes_foreign_binding_before_field_access() -> None:
    _authority, case = _authority_and_case()

    with pytest.raises(
        ManagedV5IngestIdentityProjectionError,
        match="composition_invalid",
    ):
        project_managed_infinity_v5_ingest_identities(
            composition_binding=object(),  # type: ignore[arg-type]
            cases=(case,),
            infinity_evidence=(),
            mem0_projection=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "error",
    (
        ManagedV5ProductionRuntimeFactoryError("factory-specific"),
        ManagedRuntimeCredentialError("credential-specific"),
    ),
)
def test_production_activation_preserves_runtime_boundary_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    monkeypatch.setattr(runner, "_activate_managed_v5_public_run", lambda *_a, **_k: object())

    def fail_runtime(**_kwargs: object) -> object:
        raise error

    monkeypatch.setattr(runner, "create_managed_v5_production_runtime", fail_runtime)
    with pytest.raises(type(error)) as caught:
        runner.activate_managed_v5_production_runtime(
            object(),  # type: ignore[arg-type]
            cases=(),
            request=object(),  # type: ignore[arg-type]
            composition_binding=object(),  # type: ignore[arg-type]
            receipt_authority=object(),  # type: ignore[arg-type]
            production_authority=object(),  # type: ignore[arg-type]
            plan=object(),  # type: ignore[arg-type]
            now=datetime.now(UTC),
        )

    assert caught.value is error


def test_tracked_transport_factory_normalizes_creation_and_closes_on_registration_failure() -> None:
    owner = ManagedV5OwnedResources()

    def fail_creation() -> httpx.BaseTransport:
        raise RuntimeError("private factory detail")

    with pytest.raises(ManagedV5ProductionRuntimeFactoryError) as creation:
        _tracked_factory(owner, fail_creation)()
    assert creation.value.code == "managed_v5_runtime_transport_invalid"
    assert "private factory detail" not in str(creation.value)

    transport = _TrackedTransport()
    owner.close()
    with pytest.raises(ManagedV5ProductionRuntimeFactoryError) as registration:
        _tracked_factory(owner, lambda: transport)()
    assert registration.value.code == "managed_v5_runtime_transport_invalid"
    assert transport.closed is True


def test_infinity_credential_bundle_rejects_subclass_and_state_protocols() -> None:
    with pytest.raises(TypeError, match="sealed"):

        class _Subclass(ManagedV5InfinityCredentialBundle):
            pass

    bundle = object.__new__(ManagedV5InfinityCredentialBundle)
    with pytest.raises(TypeError, match="state is inaccessible"):
        bundle.__getstate__()
    with pytest.raises(TypeError, match="nonserializable"):
        bundle.__reduce_ex__(5)


def test_activated_preparation_authentication_normalizes_mac_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = prep._ActivatedManagedV5PublicRun(
        1,
        "a" * 64,
        (),
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        b"mac",
    )

    def fail_mac(_value: object) -> bytes:
        raise RuntimeError("private inspector detail")

    monkeypatch.setattr(prep, "_activated_mac", fail_mac)
    with pytest.raises(ManagedRunError, match="activation invalid"):
        prep._authenticate_activated_managed_v5_public_run(value)

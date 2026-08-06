from __future__ import annotations

from pathlib import Path

import pytest

from mem0_oss_adapter_v5 import bootstrap


def test_invalid_source_pin_fails_before_runtime_state_or_provider_initialization(
    monkeypatch,
) -> None:
    events = []

    class InvalidPin(RuntimeError):
        pass

    def reject_authority(**_kwargs):
        events.append("source-authority")
        raise InvalidPin

    def forbidden(name: str):
        def call(*_args, **_kwargs):
            events.append(name)
            raise AssertionError(f"{name} initialized before source authority")

        return call

    monkeypatch.setattr(bootstrap, "SealedInputManifest", lambda _path: object())
    monkeypatch.setattr(bootstrap, "_required_environment", lambda _name: "/tmp/value")
    monkeypatch.setattr(bootstrap, "_read_secret_file", lambda _name: "a" * 64)
    monkeypatch.setattr(bootstrap, "verify_source_authority", reject_authority)
    monkeypatch.setattr(bootstrap, "_receipt_authority", forbidden("receipt-runtime"))
    monkeypatch.setattr(bootstrap, "SubscriptionRuntimeClient", forbidden("runtime-client"))
    monkeypatch.setattr(bootstrap, "SqliteOperationState", forbidden("sqlite"))
    monkeypatch.setattr(bootstrap, "_build_pinned_memory", forbidden("mem0-qdrant"))
    with pytest.raises(InvalidPin):
        bootstrap.build_app_from_environment()
    assert events == ["source-authority"]


def test_tampered_phase_c_authority_blocks_runtime_binding_issue(monkeypatch) -> None:
    phase_package = Path(__file__).resolve().parents[2] / "phase-c-canary"
    monkeypatch.syspath_prepend(str(phase_package))
    from phase_c_canary import attestation, runtime_binding

    events = []

    def reject(_authority) -> None:
        events.append("attestation")
        raise attestation.AuthorityError("tampered")

    def forbidden_issue():
        events.append("binding")
        raise AssertionError("runtime binding issued before immutable preflight")

    monkeypatch.setattr(attestation, "verify_immutable_authority", reject)
    monkeypatch.setattr(
        runtime_binding.RuntimeBindingComposition,
        "compose_phase_c_canary",
        forbidden_issue,
    )
    with pytest.raises(attestation.AuthorityError, match="tampered"):
        bootstrap._receipt_authority("receipt-secret")
    assert events == ["attestation"]

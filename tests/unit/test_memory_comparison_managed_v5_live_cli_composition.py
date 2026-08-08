from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server import (
    memory_comparison_managed_v5_live_cli_composition as subject,
)
from infinity_context_server.memory_comparison_managed_v5_extraction_budget import (
    ManagedV5ExtractionBudgetError,
    ManagedV5ExtractionReservationUnit,
    ManagedV5ExtractionTokenBudget,
)
from infinity_context_server.memory_comparison_managed_v5_live_config import (
    ManagedV5LiveConfig,
)

ROOT = Path(__file__).resolve().parents[2]


def test_v5_attestation_prevalidation_is_before_paid_readiness_in_private_stage() -> None:
    source = inspect.getsource(subject._prepare_and_activate_private_stage)

    assert source.index("runtime_port.prevalidate(") < source.index(
        "run_readiness=lambda: readiness_claim.run("
    )
    assert "ManagedMem0RuntimeAttestationPort" not in source
    assert "MEM0_V5_RUNTIME_ATTESTATION_ROOT_SECRET" not in source


def test_failed_v5_attestation_executes_zero_paid_readiness_calls() -> None:
    calls = {"prevalidate": 0, "readiness": 0}

    def reject_attestation() -> None:
        calls["prevalidate"] += 1
        raise RuntimeError("tampered runtime attestation")

    def paid_readiness() -> object:
        calls["readiness"] += 1
        return object()

    with pytest.raises(RuntimeError, match="tampered runtime attestation"):
        subject._prevalidate_before_paid_readiness(
            prevalidate=reject_attestation,
            run_readiness=paid_readiness,
        )

    assert calls == {"prevalidate": 1, "readiness": 0}


class _NoPrivateReads(dict[str, str]):
    def get(self, key: object, default: object = None) -> object:
        del default
        pytest.fail(f"private environment read before public gate: {key!r}")

    def __getitem__(self, key: object) -> str:
        pytest.fail(f"private environment read before public gate: {key!r}")


def test_public_rejection_precedes_every_private_or_provider_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(_: object) -> object:
        raise subject.ManagedV5LiveCliCompositionError("public_rejected")

    monkeypatch.setattr(subject, "prepare_managed_v5_live_cli_public_stage", reject)
    monkeypatch.setattr(
        subject,
        "_prepare_and_activate_private_stage",
        lambda *_args, **_kwargs: pytest.fail("private stage must not start"),
    )
    monkeypatch.setattr(
        subject,
        "run_selected_managed_production_comparison",
        lambda **_kwargs: pytest.fail("provider execution must not start"),
    )

    with pytest.raises(subject.ManagedV5LiveCliCompositionError, match="public_rejected"):
        subject.run_managed_v5_live_cli_composition(  # type: ignore[arg-type]
            object(),
            env=_NoPrivateReads(),
        )


def test_insufficient_extraction_cap_rejects_before_private_environment_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_for_budget(_: object) -> object:
        return ManagedV5ExtractionTokenBudget.reserve(
            (ManagedV5ExtractionReservationUnit(100, 4096),),
            operator_extraction_token_ceiling=4195,
            operator_total_token_ceiling=10_000,
        )

    monkeypatch.setattr(subject, "prepare_managed_v5_live_cli_public_stage", reject_for_budget)
    monkeypatch.setattr(
        subject,
        "_prepare_and_activate_private_stage",
        lambda *_args, **_kwargs: pytest.fail("private stage started after insufficient cap"),
    )
    with pytest.raises(ManagedV5ExtractionBudgetError):
        subject.run_managed_v5_live_cli_composition(  # type: ignore[arg-type]
            object(),
            env=_NoPrivateReads(),
        )


def test_wrong_extraction_contract_hash_is_read_and_rejected_before_private_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = object.__new__(ManagedV5LiveConfig)
    object.__setattr__(
        config,
        "runtime",
        SimpleNamespace(mem0_adapter_origin="http://127.0.0.1:19091"),
    )
    reviewed_contract = tmp_path / "extraction_contract.py"
    reviewed_contract.write_bytes(
        (
            ROOT
            / "benchmarks"
            / "mem0-oss-adapter-v5"
            / "mem0_oss_adapter_v5"
            / "extraction_contract.py"
        ).read_bytes()
    )
    reviewed_contract.chmod(0o444)
    request = subject.ManagedV5LiveCliCompositionRequest(
        dataset_path=ROOT / "unused-dataset.json",
        profile_id="locomo-top-50",
        selected_case_ids=("case-1",),
        run_id="binding-pre-secret",
        infinity_api_url="http://127.0.0.1:8080",
        mem0_api_url="http://127.0.0.1:19091",
        subscription_runtime_url="http://127.0.0.1:8891",
        max_extraction_tokens=5000,
        max_total_tokens=10_000,
        mem0_runtime_implementation_sha256="a" * 64,
        managed_v5_config=config,
        extraction_contract_file=reviewed_contract.resolve(),
        extraction_contract_sha256="f" * 64,
        mem0_local_auth_disabled_managed=True,
        mem0_oss_ingress_protected=True,
        allowed_mem0_hosts=("127.0.0.1",),
        connect_timeout_seconds=5.0,
        request_timeout_seconds=30.0,
        run_timeout_seconds=60.0,
    )
    monkeypatch.setattr(
        subject,
        "_dataset_bytes",
        lambda _path: pytest.fail("dataset read preceded extraction contract rejection"),
    )
    monkeypatch.setattr(
        subject,
        "_prepare_and_activate_private_stage",
        lambda *_args, **_kwargs: pytest.fail("private stage started after public rejection"),
    )

    with pytest.raises(
        subject.ManagedV5LiveCliCompositionError,
        match="managed_v5_live_extraction_contract_invalid",
    ):
        subject.run_managed_v5_live_cli_composition(request, env=_NoPrivateReads())


def test_orchestrator_selects_exact_v5_without_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    public = object()
    provider = SimpleNamespace(close=lambda: events.append("provider.close"))
    selected = SimpleNamespace(selection=SimpleNamespace(provider=provider))
    private = subject.ActivatedManagedV5LiveCliPrivateStage(selected, "probe-token")
    outcome = object()

    def prepare_public(_: object) -> object:
        events.append("public")
        return public

    def activate(value: object, *, env: object) -> object:
        assert value is public
        assert env == {"PRIVATE": "opaque"}
        events.append("private")
        return private

    def execute(**kwargs: object) -> object:
        assert kwargs == {
            "execution_mode": subject.MANAGED_PRODUCTION_EXECUTION_V5,
            "v5_execution": selected.selection,
        }
        events.append("execute-v5")
        return outcome

    monkeypatch.setattr(subject, "prepare_managed_v5_live_cli_public_stage", prepare_public)
    monkeypatch.setattr(subject, "_prepare_and_activate_private_stage", activate)
    monkeypatch.setattr(subject, "run_selected_managed_production_comparison", execute)
    monkeypatch.setattr(
        subject,
        "public_managed_run",
        lambda value: {"sealed": value is outcome},
    )
    monkeypatch.setattr(
        subject,
        "_append_required_usage_attestation",
        lambda _public, value, result: (
            events.append("usage-proof") or result
            if value is private
            else pytest.fail("wrong private stage")
        ),
    )

    result = subject.run_managed_v5_live_cli_composition(  # type: ignore[arg-type]
        object(),
        env={"PRIVATE": "opaque"},
    )

    assert result == {"sealed": True}
    assert events == [
        "public",
        "private",
        "execute-v5",
        "usage-proof",
    ]
    assert "run_verified_managed_production_comparison" not in vars(subject)


def test_orchestrator_does_not_double_close_runner_owned_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    provider = SimpleNamespace(close=lambda: events.append("provider.close"))
    selected = SimpleNamespace(selection=SimpleNamespace(provider=provider))
    private = subject.ActivatedManagedV5LiveCliPrivateStage(selected, "probe-token")
    monkeypatch.setattr(
        subject,
        "prepare_managed_v5_live_cli_public_stage",
        lambda _: object(),
    )
    monkeypatch.setattr(
        subject,
        "_prepare_and_activate_private_stage",
        lambda *_args, **_kwargs: private,
    )

    def fail(**_: object) -> object:
        raise RuntimeError("sealed failure")

    monkeypatch.setattr(subject, "run_selected_managed_production_comparison", fail)

    with pytest.raises(RuntimeError, match="sealed failure"):
        subject.run_managed_v5_live_cli_composition(  # type: ignore[arg-type]
            object(),
            env={},
        )
    assert events == []


@pytest.mark.parametrize("fail", (False, True))
def test_post_sealed_usage_proof_never_discards_sealed_result(
    monkeypatch: pytest.MonkeyPatch,
    fail: bool,
) -> None:
    from infinity_context_server import (
        memory_comparison_managed_mem0_oss_usage_http,
        memory_comparison_mem0_oss_ingress,
    )

    now = datetime(2026, 8, 8, tzinfo=UTC)
    ingress = object()
    captured: dict[str, object] = {}

    class _UsagePort:
        def attest(self, **kwargs: object) -> object:
            captured["attest"] = kwargs
            if fail:
                raise RuntimeError("private provider detail")
            return SimpleNamespace(public_payload=lambda: {"verified": True})

    def usage_port(**kwargs: object) -> object:
        captured["port"] = kwargs
        return _UsagePort()

    monkeypatch.setattr(
        memory_comparison_managed_mem0_oss_usage_http,
        "ManagedMem0OssUsageAttestationPort",
        usage_port,
    )
    monkeypatch.setattr(
        memory_comparison_mem0_oss_ingress,
        "inspect_mem0_oss_ingress_authority",
        lambda value: (
            SimpleNamespace(target_identity_sha256="a" * 64)
            if value is ingress
            else pytest.fail("wrong ingress authority")
        ),
    )
    selected = SimpleNamespace(
        selection=SimpleNamespace(
            attestation_port=SimpleNamespace(usage_attestation_required=lambda: True)
        )
    )
    private = subject.ActivatedManagedV5LiveCliPrivateStage(
        selected,
        "probe-token",
        ingress,
    )
    public = SimpleNamespace(
        request=SimpleNamespace(
            mem0_api_url="http://127.0.0.1:19091",
            request_timeout_seconds=30.0,
            allowed_mem0_hosts=("127.0.0.1",),
            run_id="run-1",
        ),
        deadline=now + timedelta(minutes=5),
    )
    sealed = {"sealed": True}

    if fail:
        with pytest.raises(subject.ManagedV5LiveCliCompositionError) as raised:
            subject._append_required_usage_attestation(public, private, sealed)  # type: ignore[arg-type]
        assert raised.value.code == "mem0_oss_usage_attestation_failed"
        assert raised.value.sealed_result == sealed
    else:
        result = subject._append_required_usage_attestation(  # type: ignore[arg-type]
            public,
            private,
            sealed,
        )
        assert result == {"sealed": True, "mem0_oss_usage_attestation": {"verified": True}}
        assert captured["attest"] == {
            "run_id": "run-1",
            "target_identity_sha256": "a" * 64,
        }

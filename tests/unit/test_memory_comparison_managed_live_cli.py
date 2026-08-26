from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server import memory_comparison_managed_live_cli as subject
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    REGISTRATION_SCHEMA_VERSION,
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_v5_live_private_dependencies import (
    ManagedV5RegistryRecoveryEnvelope,
)

_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
_PRIVATE = "PRIVATE-SECRET-MUST-NOT-LEAK"
_ENV = {
    "MEMORY_EVAL_AUTH_TOKEN": "infinity-private-token",
    "MEM0_BENCHMARK_PROBE_TOKEN": "mem0-private-probe-token",
    "SUBSCRIPTION_RUNTIME_BRIDGE_BEARER_TOKEN": "subscription-private-token",
}


class _ManagedProductionRunnerErrorSubclass(subject.ManagedProductionRunnerError):
    pass


def _config(tmp_path: Path, **changes: object) -> subject.ManagedLiveCliConfig:
    dataset = tmp_path / "official.json"
    dataset.write_bytes(b'{"official":true}')
    values: dict[str, object] = {
        "dataset_path": dataset,
        "profile_id": "mem0-locomo-top50-v1",
        "selected_case_ids": ("case-1", "case-2"),
        "run_id": "managed-live-1",
        "infinity_api_url": "http://127.0.0.1:7788",
        "mem0_api_url": "http://127.0.0.1:8888",
        "subscription_runtime_url": "http://127.0.0.1:8890",
        "max_total_tokens": 50_000,
        "max_extraction_tokens": 20_000,
        "mem0_runtime_implementation_sha256": "a" * 64,
        "allow_live": True,
        "allow_paid_llm": True,
        "operator_notified": True,
        "mem0_local_auth_disabled_managed": True,
        "allowed_mem0_hosts": ("127.0.0.1",),
    }
    values.update(changes)
    return subject.ManagedLiveCliConfig(**values)  # type: ignore[arg-type]


def _managed_v5_config(tmp_path: Path, **changes: object) -> subject.ManagedLiveCliConfig:
    report_file = tmp_path / "reports" / "managed-v5-terminal.json"
    report_file.parent.mkdir(exist_ok=True)
    filesystem = SimpleNamespace(report_file=report_file)
    managed_v5 = object.__new__(subject.ManagedV5LiveConfig)
    object.__setattr__(managed_v5, "filesystem", filesystem)
    object.__setattr__(managed_v5, "runtime", object())
    values = {"managed_v5_config": managed_v5, "report_out": report_file, **changes}
    return _config(tmp_path, **values)


def test_operator_flags_block_before_files_env_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, operator_notified=False)
    config.dataset_path.unlink()
    monkeypatch.setattr(
        subject,
        "_run_managed_live",
        lambda *_: pytest.fail("live composition must not start"),
    )

    report = subject.run_managed_live_cli(config, env={})

    assert report["status"] == "no-go"
    assert report["reason_code"] == "authorization_required"
    assert report["publishable"] is False


@pytest.mark.parametrize(
    ("runner_code", "expected_reason_code"),
    (
        (
            "managed_production_execution_seal_failed",
            "managed_production_execution_seal_failed",
        ),
        (_PRIVATE, "managed_live_execution_failed"),
    ),
)
def test_cli_reports_only_allowlisted_production_failure_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_code: str,
    expected_reason_code: str,
) -> None:
    config = _managed_v5_config(tmp_path)

    def fail(*_: object) -> dict[str, object]:
        raise subject.ManagedProductionRunnerError(runner_code)

    monkeypatch.setattr(subject, "_run_managed_live", fail)

    report = subject.run_managed_live_cli(config, env={})

    assert report["status"] == "failed"
    assert report["reason_code"] == expected_reason_code
    serialized = json.dumps(report, sort_keys=True)
    assert _PRIVATE not in serialized
    assert "ManagedProductionRunnerError" not in serialized


def test_cli_retains_secret_free_durable_registry_recovery_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _managed_v5_config(tmp_path)
    registry = object.__new__(ManagedBenchmarkRegistryHttpAdapter)
    registration = ManagedBenchmarkRunRegistration(
        schema_version=REGISTRATION_SCHEMA_VERSION,
        authority="infinity_canonical",
        run_id_sha256="1" * 64,
        binding_commitment_sha256="2" * 64,
        infinity_target_identity_sha256="3" * 64,
        space_id="space-1",
        space_slug="memory-comparison-run-1",
        state="active",
        created=False,
        cleanup_plan_sha256="4" * 64,
        cleanup_plan_state="sealed",
    )
    envelope = ManagedV5RegistryRecoveryEnvelope(
        stage="begin_cleanup",
        primary_reason_code="managed_v5_production_activation_failed",
        run_id_sha256=registration.run_id_sha256,
        binding_commitment_sha256=registration.binding_commitment_sha256,
        infinity_target_identity_sha256=registration.infinity_target_identity_sha256,
        space_slug=registration.space_slug,
        recovery_registry=registry,
        registration=registration,
    )
    failure = subject.ManagedV5ProductionRecoveryRequiredError(
        envelope=envelope,
    )

    def fail(*_: object) -> dict[str, object]:
        raise failure

    monkeypatch.setattr(subject, "_run_managed_live", fail)
    report = subject.run_managed_live_cli(config, env={})

    assert report["reason_code"] == "cleanup_required"
    assert report["registry_recovery"] == {
        "schema_version": "managed-v5-registry-recovery.v1",
        "cleanup_required": True,
        "canonical_state": "active",
        "canonical_state_retained": True,
        "cleanup_stage": "begin_cleanup",
        "primary_reason_code": "managed_v5_production_activation_failed",
        "run_id_sha256": "1" * 64,
        "binding_commitment_sha256": "2" * 64,
        "infinity_target_identity_sha256": "3" * 64,
        "space_slug": "memory-comparison-run-1",
        "registration": {
            "run_id_sha256": "1" * 64,
            "binding_commitment_sha256": "2" * 64,
            "infinity_target_identity_sha256": "3" * 64,
            "space_id": "space-1",
            "space_slug": "memory-comparison-run-1",
            "state": "active",
            "created": False,
        },
        "cleanup_receipt_sha256": None,
    }
    serialized = json.dumps(report, sort_keys=True)
    assert _PRIVATE not in serialized
    assert "recovery_registry" not in serialized
    assert json.loads(config.report_out.read_text()) == report


def test_cli_unknown_registration_outcome_writes_exact_secret_free_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _managed_v5_config(tmp_path)
    registry = object.__new__(ManagedBenchmarkRegistryHttpAdapter)
    envelope = ManagedV5RegistryRecoveryEnvelope(
        stage="registration_outcome_unknown",
        primary_reason_code=("managed_v5_live_private_dependencies_registration_failed"),
        run_id_sha256="a" * 64,
        binding_commitment_sha256="b" * 64,
        infinity_target_identity_sha256="c" * 64,
        space_slug="memory-comparison-unknown",
        recovery_registry=registry,
    )
    failure = subject.ManagedV5ProductionRecoveryRequiredError(envelope=envelope)
    monkeypatch.setattr(
        subject,
        "_run_managed_live",
        lambda *_: (_ for _ in ()).throw(failure),
    )

    report = subject.run_managed_live_cli(config, env={})

    recovery = report["registry_recovery"]
    assert recovery["canonical_state"] == "unknown_may_exist"
    assert recovery["canonical_state_retained"] is False
    assert recovery["registration"] is None
    assert recovery["cleanup_stage"] == "registration_outcome_unknown"
    assert json.loads(config.report_out.read_text()) == report
    assert "recovery_registry" not in json.dumps(report, sort_keys=True)


def test_managed_v5_cli_requires_exact_validated_report_path(tmp_path: Path) -> None:
    config = _managed_v5_config(tmp_path, report_out=tmp_path / "wrong.json")

    with pytest.raises(subject.ManagedLiveCliError) as caught:
        subject.run_managed_live_cli(config, env={})

    assert caught.value.code == "config_invalid"


@pytest.mark.parametrize(
    ("internal_code", "public_code"),
    tuple(subject._MANAGED_V5_COMPOSITION_PUBLIC_CODES.items())
    + (("PRIVATE-SECRET-CODE", "managed_live_execution_failed"),),
)
def test_managed_v5_composition_codes_are_exhaustively_normalized(
    internal_code: str,
    public_code: str,
) -> None:
    mapped = subject._managed_v5_composition_public_code(internal_code)

    assert mapped == public_code
    assert "PRIVATE" not in mapped


def test_managed_v5_cli_persists_authorization_terminal_report(tmp_path: Path) -> None:
    config = _managed_v5_config(tmp_path, operator_notified=False)
    config.dataset_path.unlink()

    report = subject.run_managed_live_cli(config, env={})

    assert report["reason_code"] == "authorization_required"
    assert json.loads(config.report_out.read_text()) == report


def test_managed_v5_cli_report_write_failure_is_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _managed_v5_config(tmp_path, operator_notified=False)
    monkeypatch.setattr(
        subject,
        "write_json_atomic",
        lambda *_: (_ for _ in ()).throw(OSError("private write failure")),
    )

    with pytest.raises(subject.ManagedLiveCliError) as caught:
        subject.run_managed_live_cli(config, env={})

    assert caught.value.code == "artifact_write_failed"


@pytest.mark.parametrize(
    "failure",
    (
        pytest.param(
            subject.ManagedLiveCliError("managed_production_execution_seal_failed"),
            id="cli-error-cannot-spoof-phase",
        ),
        pytest.param(
            _ManagedProductionRunnerErrorSubclass("managed_production_execution_seal_failed"),
            id="runner-subclass-cannot-spoof-phase",
        ),
        pytest.param(
            subject.ManagedProductionRunnerError(_PRIVATE),
            id="runner-wrong-code-is-generic",
        ),
    ),
)
def test_cli_requires_exact_trusted_runner_provenance_for_phase_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    config = _config(tmp_path)

    def fail(*_: object) -> dict[str, object]:
        raise failure

    monkeypatch.setattr(subject, "_run_managed_live", fail)

    report = subject.run_managed_live_cli(config, env={})

    assert report["reason_code"] == "managed_live_execution_failed"
    serialized = json.dumps(report, sort_keys=True)
    assert _PRIVATE not in serialized
    assert "ManagedProductionRunnerError" not in serialized


@pytest.mark.parametrize(
    "subscription_runtime_url",
    (
        "http://127.0.0.1:8890/v1",
        "http://127.0.0.1:8890?path=query",
        "http://127.0.0.1:8890#fragment",
        "http://user:pass@127.0.0.1:8890",
        "https://192.0.2.1:8890",
    ),
)
def test_subscription_runtime_url_fails_closed_before_credentials_or_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    subscription_runtime_url: str,
) -> None:
    config = _config(tmp_path, subscription_runtime_url=subscription_runtime_url)
    profile = SimpleNamespace(profile_id=config.profile_id)
    dataset = object()
    cases = (object(),)

    monkeypatch.setattr(subject, "_profile", lambda _: profile)
    monkeypatch.setattr(subject, "managed_dataset_metadata_from_bytes", lambda **_: dataset)
    monkeypatch.setattr(subject, "managed_policy_cases_from_dataset", lambda **_: cases)
    monkeypatch.setattr(
        subject,
        "evaluate_managed_production_pre_readiness",
        lambda _: SimpleNamespace(decision="go", blockers=()),
    )
    monkeypatch.setattr(
        subject,
        "issue_managed_runtime_credential_authority",
        lambda **_: pytest.fail("authority must not be issued for an invalid URL"),
    )

    class _NoCredentialReads(dict[str, str]):
        def get(self, key: object, default: object = None) -> object:
            pytest.fail(f"credentials must not be read for invalid URL: {key!r}")

    report = subject.run_managed_live_cli(config, env=_NoCredentialReads())

    assert report == {
        "suite": subject.MANAGED_LIVE_CLI_SUITE,
        "schema_version": subject.MANAGED_LIVE_CLI_SCHEMA_VERSION,
        "ok": False,
        "status": "failed",
        "reason_code": "subscription_runtime_url_invalid",
        "blockers": [],
        "provider_kind": "subscription-runtime",
        "scope": "canary",
        "publishable": False,
    }
    serialized = json.dumps(report, sort_keys=True)
    assert subscription_runtime_url not in serialized
    assert "ValueError" not in serialized


def test_no_key_mem0_requires_explicit_loopback_auth_disabled_managed(
    tmp_path: Path,
) -> None:
    without_flag = _config(tmp_path, mem0_local_auth_disabled_managed=False)
    with pytest.raises(subject.ManagedLiveCliError, match="credential_missing"):
        subject._mem0_api_key(without_flag, {})
    assert subject._mem0_data_plane_auth(
        without_flag,
        {"MEM0_API_KEY": "platform-private-key"},
    ) == ("api_key", "platform-private-key")

    remote = _config(
        tmp_path,
        mem0_api_url="https://mem0.example.test",
        mem0_local_auth_disabled_managed=True,
    )
    with pytest.raises(subject.ManagedLiveCliError, match="local_mem0_target_required"):
        subject._mem0_api_key(remote, {})
    with pytest.raises(subject.ManagedLiveCliError, match="local_mem0_target_required"):
        subject._mem0_api_key(remote, {"MEM0_API_KEY": "must-not-bypass-target-policy"})

    no_allowlist = _config(
        tmp_path,
        mem0_local_auth_disabled_managed=True,
        allowed_mem0_hosts=(),
    )
    with pytest.raises(subject.ManagedLiveCliError, match="local_mem0_target_required"):
        subject._mem0_api_key(no_allowlist, {})

    wrong_allowlist = _config(
        tmp_path,
        mem0_local_auth_disabled_managed=True,
        allowed_mem0_hosts=("127.0.0.2",),
    )
    with pytest.raises(subject.ManagedLiveCliError, match="local_mem0_target_required"):
        subject._mem0_api_key(wrong_allowlist, {})

    localhost = _config(
        tmp_path,
        mem0_api_url="http://localhost:8888",
        mem0_local_auth_disabled_managed=True,
        allowed_mem0_hosts=("localhost",),
    )
    with pytest.raises(subject.ManagedLiveCliError, match="local_mem0_target_required"):
        subject._mem0_api_key(localhost, {})

    ipv6_loopback = _config(
        tmp_path,
        mem0_api_url="http://[::1]:8888",
        mem0_local_auth_disabled_managed=True,
        allowed_mem0_hosts=("::1",),
    )
    with pytest.raises(subject.ManagedLiveCliError, match="local_mem0_target_required"):
        subject._mem0_api_key(ipv6_loopback, {})

    class _NoAmbientMem0Key(dict[str, str]):
        def get(self, key: object, default: object = None) -> object:
            if key == "MEM0_API_KEY":
                pytest.fail("keyless lane must not read an ambient Mem0 API key")
            return super().get(key, default)  # type: ignore[arg-type]

    local = _config(tmp_path, mem0_local_auth_disabled_managed=True)
    environment = _NoAmbientMem0Key({"MEM0_API_KEY": "ambient-private-key"})
    assert subject._mem0_data_plane_auth(local, environment) == ("none", None)
    assert subject._mem0_api_key(local, environment) is None


def test_runtime_request_timeout_is_bounded_by_attestation_adapter(tmp_path: Path) -> None:
    with pytest.raises(subject.ManagedLiveCliError, match="config_invalid"):
        _config(tmp_path, request_timeout_seconds=120.001)


def test_oss_ingress_env_requires_explicit_keyless_config_and_never_falls_back(
    tmp_path: Path,
) -> None:
    ambient = {"MEM0_OSS_INGRESS_API_KEY": "private-ingress-key"}
    legacy_keyless = _config(tmp_path, mem0_oss_ingress_protected=False)
    with pytest.raises(
        subject.ManagedLiveCliError,
        match="mem0_oss_ingress_configuration_invalid",
    ):
        subject._mem0_oss_ingress_authority(legacy_keyless, ambient)

    platform = _config(
        tmp_path,
        mem0_local_auth_disabled_managed=False,
        mem0_oss_ingress_protected=True,
    )
    with pytest.raises(
        subject.ManagedLiveCliError,
        match="mem0_oss_ingress_configuration_invalid",
    ):
        subject._mem0_oss_ingress_authority(platform, ambient)

    protected = _config(tmp_path, mem0_oss_ingress_protected=True)
    with pytest.raises(subject.ManagedLiveCliError, match="credential_missing"):
        subject._mem0_oss_ingress_authority(protected, {"MEM0_API_KEY": "ambient-platform"})

    authority = subject._mem0_oss_ingress_authority(
        protected,
        {
            "MEM0_OSS_INGRESS_API_KEY": "private-ingress-key",
            "MEM0_API_KEY": "must-not-be-used-as-ingress",
        },
    )
    assert authority is not None
    assert "private-ingress-key" not in repr(authority)
    assert subject._mem0_data_plane_auth(
        protected,
        {"MEM0_API_KEY": "must-not-be-used-as-provider-auth"},
    ) == ("none", None)


def test_oss_ingress_protected_target_must_be_vetted_local_or_private(tmp_path: Path) -> None:
    remote = _config(
        tmp_path,
        mem0_api_url="https://93.184.216.34:8888",
        allowed_mem0_hosts=("93.184.216.34",),
        mem0_oss_ingress_protected=True,
    )

    with pytest.raises(
        subject.ManagedLiveCliError,
        match="mem0_oss_ingress_configuration_invalid",
    ):
        subject._mem0_oss_ingress_authority(
            remote,
            {"MEM0_OSS_INGRESS_API_KEY": "private-ingress-key"},
        )


@pytest.mark.parametrize(
    ("usage_required", "usage_fails"),
    ((True, False), (False, False), (True, True)),
)
def test_legacy_helper_retains_v4_post_sealed_usage_proof_without_real_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    usage_required: bool,
    usage_fails: bool,
) -> None:
    config = _config(
        tmp_path,
        run_timeout_seconds=180,
        mem0_oss_ingress_protected=True,
        subscription_runtime_url="http://127.0.0.1:8890/",
    )
    captured: dict[str, object] = {}
    profile = SimpleNamespace(
        profile_id=config.profile_id,
        required_mem0_runtime_mode="managed_platform",
    )
    dataset = object()
    cases = (object(), object())
    route = object()
    provider_credential = object()
    endpoints = (object(), object())
    probe_credential = object()
    request = object()
    proof = object()

    class _Runtime:
        def usage_attestation_required(self) -> bool:
            return usage_required

    runtime = _Runtime()
    admission = object()
    prepared = object()
    outcome = object()

    class _Clock:
        def __init__(self) -> None:
            self._instants = iter(
                (
                    _NOW,
                    _NOW + timedelta(seconds=1),
                    _NOW + timedelta(seconds=9),
                    _NOW + timedelta(seconds=9),
                    _NOW + timedelta(seconds=9),
                )
            )

        def now(self) -> datetime:
            return next(self._instants)

    class _Claim:
        def run(self, **kwargs: object) -> object:
            captured["readiness_run"] = kwargs
            return proof

    class _Authority:
        def preflight_material(self) -> object:
            return SimpleNamespace(
                provider_route=route,
                provider_credential=provider_credential,
                backend_endpoints=endpoints,
                mem0_probe_credential=probe_credential,
                mem0_data_plane_auth_mode="none",
            )

        def bind_preflight_request(self, value: object, **kwargs: object) -> None:
            captured["bind"] = (value, kwargs)

        def issue_subscription_readiness_claim(self, **kwargs: object) -> object:
            captured["readiness_claim"] = kwargs
            return _Claim()

    monkeypatch.setattr(subject, "_profile", lambda _: profile)
    monkeypatch.setattr(subject, "managed_dataset_metadata_from_bytes", lambda **_: dataset)
    monkeypatch.setattr(subject, "managed_policy_cases_from_dataset", lambda **_: cases)
    monkeypatch.setattr(
        subject,
        "evaluate_managed_production_pre_readiness",
        lambda _: SimpleNamespace(decision="go", blockers=()),
    )
    monkeypatch.setattr(subject, "ManagedUtcClockPort", _Clock)
    monkeypatch.setattr(subject, "full_comparison_methodology_contract", lambda _: object())

    def authority_factory(**kwargs: object) -> object:
        captured["authority"] = kwargs
        return _Authority()

    monkeypatch.setattr(subject, "issue_managed_runtime_credential_authority", authority_factory)
    monkeypatch.setattr(
        subject,
        "ManagedPreflightTimeouts",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    def request_factory(**kwargs: object) -> object:
        captured["request_fields"] = kwargs
        return request

    monkeypatch.setattr(subject, "ManagedPreflightRequest", request_factory)

    def runtime_factory(**kwargs: object) -> object:
        captured["runtime"] = kwargs
        return runtime

    class _UsagePort:
        def attest(self, **kwargs: object) -> object:
            captured["usage_attest"] = kwargs
            if usage_fails:
                raise subject.ManagedMem0OssUsageHttpError("mem0_oss_usage_probe_failed")
            return SimpleNamespace(
                public_payload=lambda: {
                    "verified": True,
                    "usage": {"mode": "raw_passthrough", "operation_count": 2},
                }
            )

    def usage_port_factory(**kwargs: object) -> object:
        captured["usage_port"] = kwargs
        return _UsagePort()

    def admission_factory(**kwargs: object) -> object:
        captured["admission"] = kwargs
        return admission

    def prepare(value: object, **kwargs: object) -> object:
        captured["prepare"] = (value, kwargs)
        return prepared

    monkeypatch.setattr(subject, "ManagedMem0RuntimeAttestationPort", runtime_factory)
    monkeypatch.setattr(subject, "ManagedMem0OssUsageAttestationPort", usage_port_factory)
    monkeypatch.setattr(subject, "issue_verified_managed_live_admission", admission_factory)
    monkeypatch.setattr(subject, "prepare_verified_managed_live_run", prepare)
    monkeypatch.setattr(
        subject,
        "run_verified_managed_production_comparison",
        lambda value: outcome if value is prepared else pytest.fail("wrong preparation"),
    )
    monkeypatch.setattr(
        subject,
        "public_managed_run",
        lambda value: {"sealed": value is outcome},
    )
    token_hex_calls: list[int] = []

    def adapter_compatible_probe_nonce(bytes_count: int) -> str:
        token_hex_calls.append(bytes_count)
        return "a" * 64

    monkeypatch.setattr(
        subject.secrets,
        "token_urlsafe",
        lambda _: pytest.fail("runtime probe nonce must use the adapter hex contract"),
    )
    monkeypatch.setattr(subject.secrets, "token_hex", adapter_compatible_probe_nonce)

    report = subject._run_managed_live_legacy(
        config,
        env={
            **_ENV,
            "MEM0_API_KEY": "ambient-private-key",
            "MEM0_OSS_INGRESS_API_KEY": "private-ingress-key",
        },
    )

    if usage_fails:
        assert report == {
            "suite": subject.MANAGED_LIVE_CLI_SUITE,
            "schema_version": subject.MANAGED_LIVE_CLI_SCHEMA_VERSION,
            "ok": False,
            "status": "failed",
            "reason_code": "mem0_oss_usage_attestation_failed",
            "blockers": [],
            "provider_kind": "subscription-runtime",
            "scope": "canary",
            "publishable": False,
            "post_sealed_usage_attestation": {
                "schema_version": "managed-mem0-oss-post-sealed-usage.v1",
                "status": "failed",
                "attempts": 1,
                "retryable": False,
            },
            "sealed_outcome": {
                "status": "retained_not_publishable",
                "publishable": False,
                "result": {"sealed": True},
            },
        }
    else:
        expected_result = {"sealed": True}
        if usage_required:
            expected_result["mem0_oss_usage_attestation"] = {
                "verified": True,
                "usage": {"mode": "raw_passthrough", "operation_count": 2},
            }
        assert report == {
            "suite": subject.MANAGED_LIVE_CLI_SUITE,
            "schema_version": subject.MANAGED_LIVE_CLI_SCHEMA_VERSION,
            "ok": True,
            "status": "completed",
            "provider_kind": "subscription-runtime",
            "profile_id": config.profile_id,
            "scope": "canary",
            "selected_case_count": 2,
            "publishable": False,
            "result": expected_result,
        }
    assert "OPENAI_API_KEY" not in captured["authority"]
    assert captured["authority"]["subscription_origin"] == "http://127.0.0.1:8890"
    assert captured["authority"]["mem0_api_key"] is None
    assert captured["authority"]["mem0_data_plane_auth_mode"] == "none"
    ingress = captured["authority"]["mem0_oss_ingress_authority"]
    assert ingress is captured["runtime"]["mem0_oss_ingress_authority"]
    assert "private-ingress-key" not in repr(ingress)
    assert captured["request_fields"]["mem0_data_plane_auth_mode"] == "none"
    assert captured["readiness_run"]["model"] == subject.MANAGED_LIVE_CLI_MODEL
    assert captured["readiness_claim"]["subscription_origin"] == "http://127.0.0.1:8890"
    assert captured["admission"]["budget"].max_provider_calls == 8
    assert captured["admission"]["budget"].max_total_tokens == 50_000
    assert captured["admission"]["allow_full_run"] is False
    assert captured["runtime"]["deadline_budget_seconds"] == pytest.approx(170.999)
    assert captured["admission"]["issued_at"] == _NOW + timedelta(seconds=9)
    assert captured["admission"]["now"] == _NOW + timedelta(seconds=9)
    assert captured["prepare"][0] is admission
    assert captured["runtime"]["base_url"] == config.mem0_api_url
    assert captured["runtime"]["expected_runtime_mode"] == "oss"
    assert captured["runtime"]["probe_nonce"] == "a" * 64
    assert token_hex_calls
    assert all(bytes_count == 32 for bytes_count in token_hex_calls)
    if usage_required:
        assert captured["usage_port"]["ingress_authority"] is ingress
        assert captured["usage_port"]["deadline"] == _NOW + timedelta(seconds=180)
        assert callable(captured["usage_port"]["clock"])
        assert captured["usage_attest"]["run_id"] == config.run_id
        assert captured["usage_attest"]["target_identity_sha256"] == (
            ingress.descriptor().target_identity_sha256
        )
    else:
        assert "usage_port" not in captured
        assert "usage_attest" not in captured


def test_project_registers_live_canary_entrypoint() -> None:
    project = Path(__file__).parents[2] / "pyproject.toml"
    text = project.read_text()
    assert (
        "infinity-context-managed-live-canary = "
        '"infinity_context_server.memory_comparison_managed_live_cli:main"'
    ) in text


def test_subscription_runtime_url_help_describes_pathless_origin() -> None:
    action = next(
        item for item in subject._parser()._actions if item.dest == "subscription_runtime_url"
    )

    assert action.metavar == "LOOPBACK_ORIGIN"
    assert action.help is not None
    assert "pathless loopback HTTP(S) origin" in action.help
    assert "/v1/chat/completions" in action.help

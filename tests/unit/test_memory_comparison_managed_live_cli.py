from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server import memory_comparison_managed_live_cli as subject

_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
_ENV = {
    "MEMORY_EVAL_AUTH_TOKEN": "infinity-private-token",
    "MEM0_BENCHMARK_PROBE_TOKEN": "mem0-private-probe-token",
    "SUBSCRIPTION_RUNTIME_BRIDGE_BEARER_TOKEN": "subscription-private-token",
}


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
        "mem0_runtime_implementation_sha256": "a" * 64,
        "allow_live": True,
        "allow_paid_llm": True,
        "operator_notified": True,
        "mem0_local_auth_disabled_managed": True,
        "allowed_mem0_hosts": ("127.0.0.1",),
    }
    values.update(changes)
    return subject.ManagedLiveCliConfig(**values)  # type: ignore[arg-type]


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


def test_public_composition_wires_every_sealed_stage_without_real_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, run_timeout_seconds=180)
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
    runtime = object()
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

    def admission_factory(**kwargs: object) -> object:
        captured["admission"] = kwargs
        return admission

    def prepare(value: object, **kwargs: object) -> object:
        captured["prepare"] = (value, kwargs)
        return prepared

    monkeypatch.setattr(subject, "ManagedMem0RuntimeAttestationPort", runtime_factory)
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
    monkeypatch.setattr(subject.secrets, "token_urlsafe", lambda _: "n" * 43)

    report = subject.run_managed_live_cli(
        config,
        env={**_ENV, "MEM0_API_KEY": "ambient-private-key"},
    )

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
        "result": {"sealed": True},
    }
    assert "OPENAI_API_KEY" not in captured["authority"]
    assert captured["authority"]["mem0_api_key"] is None
    assert captured["authority"]["mem0_data_plane_auth_mode"] == "none"
    assert captured["request_fields"]["mem0_data_plane_auth_mode"] == "none"
    assert captured["readiness_run"]["model"] == subject.MANAGED_LIVE_CLI_MODEL
    assert captured["admission"]["budget"].max_provider_calls == 8
    assert captured["admission"]["budget"].max_total_tokens == 50_000
    assert captured["admission"]["allow_full_run"] is False
    assert captured["runtime"]["deadline_budget_seconds"] == pytest.approx(170.999)
    assert captured["admission"]["issued_at"] == _NOW + timedelta(seconds=9)
    assert captured["admission"]["now"] == _NOW + timedelta(seconds=9)
    assert captured["prepare"][0] is admission
    assert captured["runtime"]["base_url"] == config.mem0_api_url
    assert captured["runtime"]["expected_runtime_mode"] == "oss"


def test_project_registers_live_canary_entrypoint() -> None:
    project = Path(__file__).parents[2] / "pyproject.toml"
    text = project.read_text()
    assert (
        "infinity-context-managed-live-canary = "
        '"infinity_context_server.memory_comparison_managed_live_cli:main"'
    ) in text

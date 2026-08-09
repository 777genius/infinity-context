from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from infinity_context_core.ports.benchmark_cleanup_plan import ManagedBenchmarkCleanupPlan
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    managed_http_lifecycle_space_slug,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_contracts import (
    ManagedV5LiveRecoveryAuthority,
)
from infinity_context_server.memory_comparison_managed_v5_recovery_journal import (
    ManagedV5LiveRecoveryJournalStore,
    RecoveryJournalAuthenticator,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _authority(tmp_path: Path) -> ManagedV5LiveRecoveryAuthority:
    state = tmp_path / "state"
    run_id = "recovery-cli-test"
    infinity = "http://127.0.0.1:17789"
    return ManagedV5LiveRecoveryAuthority(
        run_id=run_id,
        run_id_sha256=_sha(run_id),
        binding_commitment_sha256=_sha("binding"),
        infinity_target_identity_sha256=managed_backend_target_identity_sha256(
            backend_role="infinity-context", base_url=infinity
        ),
        space_slug=managed_http_lifecycle_space_slug(run_id),
        profile_id="mem0-locomo-top50-v1",
        selected_case_ids=("conv-26:qa:1",),
        current_date="2026-08-09",
        issued_at="2026-08-09T00:00:00Z",
        deadline="2026-08-09T06:00:00Z",
        run_nonce_commitment_sha256=_sha("nonce"),
        runtime_probe_nonce_sha256=_sha("probe"),
        dataset_path=tmp_path / "dataset.json",
        dataset_sha256=_sha("dataset"),
        managed_v5_config_commitment_sha256=_sha("config"),
        extraction_contract_file=tmp_path / "extraction.json",
        extraction_contract_sha256=_sha("extraction"),
        infinity_origin=infinity,
        mem0_origin="http://127.0.0.1:19091",
        max_extraction_tokens=17_500_000,
        max_total_tokens=17_600_000,
        mem0_runtime_implementation_sha256=_sha("runtime"),
        mem0_local_auth_disabled_managed=True,
        mem0_oss_ingress_protected=True,
        allowed_mem0_hosts=("127.0.0.1",),
        connect_timeout_seconds=5.0,
        request_timeout_seconds=120.0,
        run_timeout_seconds=3600.0,
        adapter_runtime_pin_sha256=_sha("pin"),
        state_root=state,
        checkpoint_file=state / "checkpoint.json",
        checkpoint_head_file=state / "checkpoint-head.sqlite3",
        dispatch_journal=state / "dispatch.json",
        operation_journal=state / "operations.sqlite3",
        durable_clean_state=state / "clean.json",
    )


def test_prepared_only_cli_is_zero_network_and_zero_environment(
    tmp_path: Path, monkeypatch
) -> None:
    from infinity_context_server import memory_comparison_managed_v5_recovery_cli as subject

    state = tmp_path / "state"
    secret_root = tmp_path / "secrets"
    report_root = tmp_path / "reports"
    for root in (state, secret_root, report_root):
        root.mkdir(mode=0o700)
    authority = _authority(tmp_path)
    secret_path = secret_root / "recovery.key"
    secret_path.write_bytes(b"r" * 64)
    secret_path.chmod(0o600)
    journal_path = state / "recovery.json"
    store = ManagedV5LiveRecoveryJournalStore(
        path=journal_path,
        state_root=state,
        authenticator=RecoveryJournalAuthenticator(
            secret=b"r" * 64, run_id_sha256=authority.run_id_sha256
        ),
    )
    store.initialize(
        authority=authority,
        recorded_at="2026-08-09T00:00:00Z",
        details={"authority_sha256": authority.sha256},
    )
    store.close()
    report_path = report_root / "recovery-report.json"
    filesystem = SimpleNamespace(
        recovery_hmac_secret_file=secret_path,
        recovery_journal=journal_path,
        recovery_report_file=report_path,
        report_root=report_root,
        state_root=state,
    )
    config = SimpleNamespace(
        filesystem=filesystem,
        runtime=SimpleNamespace(mem0_adapter_origin=authority.mem0_origin),
    )
    monkeypatch.setattr(
        subject,
        "load_managed_v5_live_cli_config",
        lambda _path: (
            config,
            authority.extraction_contract_file,
            authority.extraction_contract_sha256,
        ),
    )
    monkeypatch.setattr(
        subject,
        "rebuild_managed_v5_recovery_public_projection",
        lambda **_kwargs: object(),
    )

    class _NoEnvironment(dict):
        def get(self, key, default=None):
            raise AssertionError(f"environment read forbidden: {key}")

    exit_code = subject.run_recovery_cli(
        argv=(
            "--managed-v5-config-json",
            str(tmp_path / "config.json"),
            "--expected-run-id-sha256",
            authority.run_id_sha256,
        ),
        env=_NoEnvironment(),
    )
    assert exit_code == 0
    report = json.loads(report_path.read_bytes())
    assert report["reason_code"] == "no_registration"
    assert report["provider_calls_performed"] == 0
    assert report["subscription_runtime_calls_performed"] == 0


def test_recovery_cli_import_traps_paid_modules() -> None:
    script = r"""
import sys
class Trap:
    def find_spec(self, fullname, path=None, target=None):
        if any(item in fullname for item in ('subscription_chat', 'readiness', 'bounded_provider')):
            raise RuntimeError(fullname)
        return None
sys.meta_path.insert(0, Trap())
import infinity_context_server.memory_comparison_managed_v5_recovery_cli
"""
    result = subprocess.run(
        [sys.executable, "-c", script], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_expired_original_deadline_uses_fresh_bounded_recovery_deadline(
    tmp_path: Path,
) -> None:
    from infinity_context_server import memory_comparison_managed_v5_recovery_cli as subject

    authority = _authority(tmp_path)
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    config = subject._registry_config(authority, "t" * 64, lambda: now, now)

    assert datetime.fromisoformat(authority.deadline.replace("Z", "+00:00")) < now
    assert config.benchmark_deadline == now + timedelta(seconds=authority.request_timeout_seconds)
    assert config.benchmark_deadline != datetime.fromisoformat(
        authority.deadline.replace("Z", "+00:00")
    )


def test_failure_report_reloads_latest_authenticated_journal(tmp_path: Path) -> None:
    from infinity_context_server import memory_comparison_managed_v5_recovery_cli as subject

    state = tmp_path / "state"
    report_root = tmp_path / "reports"
    state.mkdir(mode=0o700)
    report_root.mkdir(mode=0o700)
    authority = _authority(tmp_path)
    store = ManagedV5LiveRecoveryJournalStore(
        path=state / "recovery.json",
        state_root=state,
        authenticator=RecoveryJournalAuthenticator(
            secret=b"r" * 64, run_id_sha256=authority.run_id_sha256
        ),
    )
    stale = store.initialize(
        authority=authority,
        recorded_at="2026-08-09T00:00:00Z",
        details={"authority_sha256": authority.sha256},
    )
    plan_value, plan_sha = cleanup_plan_pair(
        run_id=authority.run_id_sha256,
        binding=authority.binding_commitment_sha256,
        target=authority.infinity_target_identity_sha256,
        space_slug=authority.space_slug,
    )
    current = store.append(
        expected_authority=authority,
        kind="cleanup_plan_prepared",
        recorded_at="2026-08-09T00:00:01Z",
        details={
            "cleanup_plan_sha256": plan_sha,
            "cleanup_target_authority_sha256": _sha("target-authority"),
        },
        cleanup_plan=ManagedBenchmarkCleanupPlan(plan_value, plan_sha),
    )
    report_path = report_root / "recovery-report.json"
    config = SimpleNamespace(
        filesystem=SimpleNamespace(
            recovery_report_file=report_path,
            report_root=report_root,
        )
    )

    exit_code = subject._write_failure(
        {"journal": stale, "store": store, "config": config},
        "managed_v5_recovery_transport_unknown",
        2,
    )

    assert exit_code == 2
    report = json.loads(report_path.read_bytes())
    assert report["journal_last_event_sha256"] == current.events[-1].event_sha256
    assert report["journal_body_sha256"] == current.body_sha256


@pytest.mark.parametrize(
    ("runner_exit", "expected_exit", "expected_status"),
    (
        (None, 0, "completed"),
        (2, 2, "retry_required"),
        (3, 3, "blocked"),
        ("pristine_failure", 3, "blocked"),
        ("mem0_constructor_failure", 3, "blocked"),
    ),
)
def test_live_cleanup_cli_normalizes_exit_and_redacts_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_exit: int | str | None,
    expected_exit: int,
    expected_status: str,
) -> None:
    from infinity_context_core.ports.benchmark_cleanup_plan import (
        build_managed_benchmark_cleanup_target_authority,
    )
    from infinity_context_server import memory_comparison_managed_v5_recovery_cli as subject

    state = tmp_path / "state"
    secrets = tmp_path / "secrets"
    reports = tmp_path / "reports"
    for root in (state, secrets, reports):
        root.mkdir(mode=0o700)
    authority = _authority(tmp_path)
    secret_path = secrets / "recovery.key"
    secret_path.write_bytes(b"r" * 64)
    secret_path.chmod(0o600)
    report_path = reports / "recovery-report.json"
    journal_path = state / "recovery.json"
    store = ManagedV5LiveRecoveryJournalStore(
        path=journal_path,
        state_root=state,
        authenticator=RecoveryJournalAuthenticator(
            secret=b"r" * 64, run_id_sha256=authority.run_id_sha256
        ),
    )
    store.initialize(
        authority=authority,
        recorded_at="2026-08-09T00:00:00Z",
        details={"authority_sha256": authority.sha256},
    )
    plan_value, plan_sha = cleanup_plan_pair(
        run_id=authority.run_id_sha256,
        binding=authority.binding_commitment_sha256,
        target=authority.infinity_target_identity_sha256,
        space_slug=authority.space_slug,
    )
    plan = ManagedBenchmarkCleanupPlan(plan_value, plan_sha)
    target = build_managed_benchmark_cleanup_target_authority(
        infinity_target_identity_sha256=authority.infinity_target_identity_sha256,
        qdrant_target_commitment_sha256=plan.value["qdrant"]["target_commitment_sha256"],
        graphiti_target_commitment_sha256=plan.value["graphiti"]["target_commitment_sha256"],
    )
    current = store.append(
        expected_authority=authority,
        kind="cleanup_plan_prepared",
        recorded_at="2026-08-09T00:00:01Z",
        details={
            "cleanup_plan_sha256": plan.sha256,
            "cleanup_target_authority_sha256": target.authority_sha256,
        },
        cleanup_plan=plan,
    )
    store.close()
    filesystem = SimpleNamespace(
        recovery_hmac_secret_file=secret_path,
        recovery_journal=journal_path,
        recovery_report_file=report_path,
        report_root=reports,
        state_root=state,
        dispatch_journal=state / "dispatch.json",
        operation_journal=state / "operations.sqlite3",
        durable_clean_state=state / "clean.json",
    )
    config = SimpleNamespace(
        filesystem=filesystem,
        runtime=SimpleNamespace(mem0_adapter_origin=authority.mem0_origin),
    )
    public_composition = SimpleNamespace(
        manifest_authority=object(),
        extraction_token_budget=object(),
        admission=object(),
        inputs=SimpleNamespace(credential_paths=object()),
    )
    public = SimpleNamespace(cleanup_plan_inputs=object(), public_composition=public_composition)

    class _Material:
        credentials = object()
        operation_signer_secret = bytearray(b"o" * 64)
        checkpoint_head_secret = bytearray(b"h" * 64)
        durable_clean_state_secret = bytearray(b"d" * 64)

        def close(self) -> None:
            pass

    cleanup_closes: list[str] = []
    pristine_closes: list[str] = []

    class _Cleanup:
        def close(self) -> None:
            cleanup_closes.append("close")

    cleanup = _Cleanup()

    class _Composition:
        coordinator = object()
        authority = object()
        request = object()

        def issue_recovery_capabilities(self, *, hmac_secret: bytes):
            assert hmac_secret == b"r" * 64
            return SimpleNamespace(
                cleanup_readback=cleanup, clean_snapshot=object(), clean_verifier=object()
            )

    class _Mem0:
        def __init__(self, **_kwargs: object) -> None:
            if runner_exit == "mem0_constructor_failure":
                raise RuntimeError("private material must never reach report")

        def close(self) -> None:
            cleanup.close()

    class _Pristine:
        def close(self) -> None:
            pristine_closes.append("close")

    class _Budget:
        total_call_count = 1

        @classmethod
        def for_authority(cls, _authority: object):
            return cls()

    class _Runner:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def run(self):
            if type(runner_exit) is int:
                raise subject.ManagedV5RecoveryError(
                    "managed_v5_recovery_transport_unknown", exit_code=runner_exit
                )
            return subject._no_registration_report(current)

    monkeypatch.setattr(
        subject,
        "load_managed_v5_live_cli_config",
        lambda _path: (
            config,
            authority.extraction_contract_file,
            authority.extraction_contract_sha256,
        ),
    )
    monkeypatch.setattr(
        subject, "rebuild_managed_v5_recovery_public_projection", lambda **_kwargs: public
    )
    monkeypatch.setattr(subject, "build_managed_v5_cleanup_plan", lambda **_kwargs: plan)
    monkeypatch.setattr(subject, "ManagedMem0V5Budget", _Budget)
    monkeypatch.setattr(subject, "ManagedMem0V5BudgetPolicy", lambda *_args: object())
    monkeypatch.setattr(subject, "load_recovery_distinct_secrets", lambda **_kwargs: _Material())
    monkeypatch.setattr(subject, "_compose_mem0", lambda *_args: _Composition())

    def _build_pristine(**_kwargs: object):
        if runner_exit == "pristine_failure":
            raise RuntimeError("private material must never reach report")
        return _Pristine()

    monkeypatch.setattr(subject, "build_managed_v5_recovery_pristine_verifier", _build_pristine)
    monkeypatch.setattr(subject, "ManagedV5RecoveryMem0Adapter", _Mem0)
    monkeypatch.setattr(subject, "ManagedV5RecoveryRunner", _Runner)
    token = "top-secret-memory-token"

    exit_code = subject.run_recovery_cli(
        argv=(
            "--managed-v5-config-json",
            str(tmp_path / "config.json"),
            "--expected-run-id-sha256",
            authority.run_id_sha256,
            "--allow-live-cleanup",
        ),
        env={"MEMORY_EVAL_AUTH_TOKEN": token},
        clock=lambda: datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
    )

    assert exit_code == expected_exit
    raw_report = report_path.read_text()
    assert token not in raw_report
    assert json.loads(raw_report)["status"] == expected_status
    assert cleanup_closes == ["close"]
    assert pristine_closes == ([] if runner_exit == "pristine_failure" else ["close"])


def test_store_construction_failure_closes_authenticator_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infinity_context_server import memory_comparison_managed_v5_recovery_cli as subject

    state = tmp_path / "state"
    secrets = tmp_path / "secrets"
    reports = tmp_path / "reports"
    for root in (state, secrets, reports):
        root.mkdir(mode=0o700)
    authority = _authority(tmp_path)
    secret = secrets / "recovery.key"
    secret.write_bytes(b"r" * 64)
    secret.chmod(0o600)
    filesystem = SimpleNamespace(
        recovery_hmac_secret_file=secret,
        recovery_journal=state / "recovery.json",
        recovery_report_file=reports / "report.json",
        report_root=reports,
        state_root=state,
    )
    config = SimpleNamespace(
        filesystem=filesystem,
        runtime=SimpleNamespace(mem0_adapter_origin=authority.mem0_origin),
    )
    closes: list[str] = []

    class _Authenticator:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def close(self) -> None:
            closes.append("close")

    monkeypatch.setattr(
        subject,
        "load_managed_v5_live_cli_config",
        lambda _path: (
            config,
            authority.extraction_contract_file,
            authority.extraction_contract_sha256,
        ),
    )
    monkeypatch.setattr(subject, "RecoveryJournalAuthenticator", _Authenticator)
    monkeypatch.setattr(
        subject,
        "ManagedV5LiveRecoveryJournalStore",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("store construction failed")),
    )

    exit_code = subject.run_recovery_cli(
        argv=(
            "--managed-v5-config-json",
            str(tmp_path / "config.json"),
            "--expected-run-id-sha256",
            authority.run_id_sha256,
        ),
        env={},
    )

    assert exit_code == 3
    assert closes == ["close"]

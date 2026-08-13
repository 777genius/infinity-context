"""Fake-process lifecycle tests for the production subscription bridge launcher."""

from __future__ import annotations

import json
import signal
import stat
import subprocess
from pathlib import Path

import pytest
from infinity_context_server.features.subscription_runtime_bridge import process_launcher
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    CODEX_EXECUTABLE_MAX_BYTES,
    BridgeProcessError,
    GracefulStopMetadata,
    ProcessIdentity,
)
from infinity_context_server.processes.subscription_runtime_bridge_process_composition import (
    create_new_subscription_runtime_bridge_processes,
    reopen_subscription_runtime_bridge_processes,
)
from subscription_runtime_bridge_process_test_support import (
    ACCOUNT_I_PID,
    API_SECRET,
    ATTESTATION_SECRET,
    BRIDGE_PORTS,
    LAUNCHER_KEY,
    FakeProcessHarness,
    build_fleet_spec,
    private_state_bytes,
)


def test_fake_launches_are_isolated_secret_safe_ready_and_gracefully_stopped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-secret-must-not-cross-boundary")
    monkeypatch.setenv("CODEX_API_KEY", "another-ambient-secret")
    spec = build_fleet_spec(tmp_path)
    harness = FakeProcessHarness()
    harness.install(monkeypatch)

    composition = create_new_subscription_runtime_bridge_processes(
        spec,
        control=harness.control,
    )

    assert len(harness.spawn_records) == 3
    assert harness.health_calls == list(BRIDGE_PORTS)
    assert harness.provider_dispatches == 0
    assert composition.readiness.public_payload()["provider_calls"] == 0
    assert composition.bridge_pool == spec.pool == composition.readiness.pool
    assert composition.bridge_boot.runtime_authority_sha256 == spec.pool.commitment_sha256
    assert composition.bridge_boot.boot_nonce_sha256 == composition.readiness.commitment_sha256
    assert composition.fleet_readiness_sha256 == composition.readiness.commitment_sha256
    assert composition.bridge_pool_authority_sha256 == spec.pool.commitment_sha256
    assert composition.bridge_boot_nonce_sha256 == composition.fleet_readiness_sha256
    assert [item.readiness.pending.generation for item in composition.fleet.processes] == [1, 1, 1]
    assert not spec.account_i_fence.state_root.exists()
    assert not spec.account_i_fence.auth_root.exists()
    assert all(
        secret not in repr(composition)
        for secret in (API_SECRET, ATTESTATION_SECRET, LAUNCHER_KEY.decode())
    )
    ordered_processes = composition.readiness.public_payload()["ordered_processes"]
    for index, (bridge, launch, process_spec) in enumerate(
        zip(
            composition.bridge_pool.bridges,
            composition.readiness.launches,
            spec.processes,
            strict=True,
        )
    ):
        assert bridge.bridge_id == launch.pending.bridge_id
        assert bridge.public_model == "gpt-5.6-sol"
        assert bridge.REASONING_EFFORT == "high"
        assert bridge.SERVICE_TIER == "priority"
        assert bridge.base_instructions_sha256 == process_spec.authority.base_instructions_sha256
        assert ordered_processes[index]["readiness_receipt_sha256"] == launch.commitment_sha256
        assert ordered_processes[index]["runtime_authority_sha256"] == (
            launch.runtime_authority_sha256
        )

    for process_spec, running, spawn in zip(
        spec.processes,
        composition.fleet.processes,
        harness.spawn_records,
        strict=True,
    ):
        assert spawn.command == (
            str(process_spec.node_executable),
            str(process_spec.runtime_entrypoint),
            "serve",
        )
        assert running.command == spawn.command
        assert spawn.cwd == process_spec.state_root
        assert spawn.stdin is subprocess.DEVNULL
        assert spawn.stdout is subprocess.DEVNULL
        assert spawn.stderr is subprocess.DEVNULL
        assert spawn.close_fds and spawn.start_new_session and spawn.restore_signals
        assert spawn.shell is False
        assert spawn.umask == 0o077
        assert spawn.environment["SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_ACCOUNTS"] == (
            process_spec.account_name
        )
        assert spawn.environment["SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_PORT"] == str(
            process_spec.port
        )
        assert spawn.environment["SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_CODEX_MODEL"] == (
            "gpt-5.6-sol"
        )
        assert spawn.environment["SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_PUBLIC_MODEL"] == (
            "gpt-5.6-sol"
        )
        assert spawn.environment["SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_REASONING_EFFORT"] == ("high")
        assert spawn.environment["SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_SERVICE_TIER"] == ("priority")
        assert spawn.environment["SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_MAX_CONCURRENT"] == "1"
        assert spawn.environment["SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_MAX_ACCOUNT_CYCLES"] == ("1")
        assert spawn.environment["SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_API_KEY"] == API_SECRET
        assert (
            spawn.environment["SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_ATTESTATION_SECRET"]
            == ATTESTATION_SECRET
        )
        assert "OPENAI_API_KEY" not in spawn.environment
        assert "CODEX_API_KEY" not in spawn.environment
        secret_values = (API_SECRET, ATTESTATION_SECRET, LAUNCHER_KEY.decode())
        assert all(secret not in "\0".join(spawn.command) for secret in secret_values)
        assert all(secret not in repr(spawn) for secret in secret_values)
        state_material = private_state_bytes(process_spec)
        assert all(secret.encode() not in state_material for secret in secret_values)
        assert running.readiness.health.public_payload()["provider_calls"] == 0
        identity = running.readiness.pending.process
        assert identity.start_ticks > 0
        assert identity.pgid == identity.pid == spawn.pid
        assert harness.control.identity(identity.pid) == identity
        for path in (
            process_spec.private_files.api_key,
            process_spec.private_files.attestation_secret,
            process_spec.private_files.launcher_receipt_key,
            process_spec.auth_root / process_spec.account_name / "auth.json",
        ):
            assert stat.S_IMODE(path.stat().st_mode) == 0o600

    stop_receipts = composition.stop_all(reason="test-complete")
    assert len(stop_receipts) == 3
    assert harness.control.signals == [
        (record.pid, signal.SIGTERM) for record in reversed(harness.spawn_records)
    ]
    assert all(item.public_payload()["graceful"] is True for item in stop_receipts)
    assert all(item.public_payload()["provider_calls"] == 0 for item in stop_receipts)
    assert all(not item.escalated for item in stop_receipts)
    assert composition.stop_all(reason="test-complete") == stop_receipts
    assert ACCOUNT_I_PID not in {pgid for pgid, _ in harness.control.signals}
    assert not spec.account_i_fence.state_root.exists()
    assert not spec.account_i_fence.auth_root.exists()


def test_public_material_uses_shared_codex_size_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = build_fleet_spec(tmp_path).processes[0]
    observed: list[tuple[Path, str, bool, int, str]] = []

    def verify(
        path: Path,
        expected_sha256: str,
        *,
        executable: bool,
        maximum_bytes: int,
        label: str,
    ) -> None:
        observed.append((path, expected_sha256, executable, maximum_bytes, label))

    monkeypatch.setattr(process_launcher, "_verify_public_file", verify)

    process_launcher._verify_public_material(process)  # noqa: SLF001

    by_label = {item[-1]: item for item in observed}
    assert by_label["codex_executable"] == (
        process.codex_executable,
        process.codex_executable_sha256,
        True,
        CODEX_EXECUTABLE_MAX_BYTES,
        "codex_executable",
    )


def test_readiness_is_exact_provider_free_get_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_spec = build_fleet_spec(tmp_path).processes[0]
    raw = (
        b'{"accountCount":1,"activeRequests":0,"model":"gpt-5.6-sol",'
        b'"ok":true,"queuedRequests":0,'
        b'"service":"subscription-runtime-openai-compatible-codex"}'
    )
    requests: list[tuple[str, str, dict[str, str]]] = []

    class FakeResponse:
        status = 200

        def read(self, maximum_bytes: int) -> bytes:
            assert maximum_bytes == 4097
            return raw

    class FakeConnection:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            assert (host, port, timeout) == ("127.0.0.1", process_spec.port, 0.5)

        def request(self, method: str, route: str, *, headers: dict[str, str]) -> None:
            requests.append((method, route, headers))

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            return None

    monkeypatch.setattr(process_launcher.http.client, "HTTPConnection", FakeConnection)

    evidence = process_launcher._probe_health_once(process_spec)  # noqa: SLF001

    assert requests == [("GET", "/health", {"Accept": "application/json", "Connection": "close"})]
    assert evidence.public_payload()["provider_calls"] == 0
    assert evidence.public_payload()["active_requests"] == 0
    assert evidence.public_payload()["queued_requests"] == 0


def test_exact_live_reopen_has_zero_additional_spawns_or_provider_dispatches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = build_fleet_spec(tmp_path)
    harness = FakeProcessHarness()
    harness.install(monkeypatch)
    created = create_new_subscription_runtime_bridge_processes(spec, control=harness.control)
    original_readiness = created.readiness
    original_boot = created.bridge_boot
    original_pool = created.bridge_pool
    original_identities = tuple(
        process.readiness.pending.process for process in created.fleet.processes
    )
    created.close_controller()

    reopened = reopen_subscription_runtime_bridge_processes(spec, control=harness.control)

    assert len(harness.spawn_records) == 3
    assert harness.provider_dispatches == 0
    assert harness.health_calls == [*BRIDGE_PORTS, *BRIDGE_PORTS]
    assert reopened.readiness == original_readiness
    assert reopened.bridge_pool == original_pool
    assert reopened.bridge_boot == original_boot
    assert reopened.readiness.commitment_sha256 == original_readiness.commitment_sha256
    assert reopened.bridge_boot_nonce_sha256 == created.bridge_boot_nonce_sha256
    assert all(process.reopened for process in reopened.fleet.processes)
    assert (
        tuple(process.readiness.pending.process for process in reopened.fleet.processes)
        == original_identities
    )
    reopened.stop_all(reason="reopen-test-complete")


def test_dead_generation_restarts_once_without_provider_redispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = build_fleet_spec(tmp_path)
    harness = FakeProcessHarness()
    harness.install(monkeypatch)
    created = create_new_subscription_runtime_bridge_processes(spec, control=harness.control)
    original_readiness = created.readiness
    victim = created.fleet.processes[0].readiness.pending.process
    created.close_controller()
    harness.control.lose_identity(victim.pid)

    restarted = reopen_subscription_runtime_bridge_processes(spec, control=harness.control)

    generations = [item.readiness.pending.generation for item in restarted.fleet.processes]
    assert generations == [2, 1, 1]
    assert restarted.fleet.processes[0].readiness.pending.mode == "reopen"
    assert restarted.fleet.processes[0].reopened is False
    assert all(item.reopened for item in restarted.fleet.processes[1:])
    assert len(harness.spawn_records) == 4
    assert harness.provider_dispatches == 0
    assert restarted.readiness.commitment_sha256 != original_readiness.commitment_sha256
    assert restarted.bridge_pool == created.bridge_pool
    assert restarted.bridge_boot != created.bridge_boot
    assert restarted.bridge_boot_nonce_sha256 != created.bridge_boot_nonce_sha256
    prior_stop_path = (
        spec.processes[0].state_root
        / ".infinity-context-bridge-launcher/generation-0000001/stop.json"
    )
    prior_stop = GracefulStopMetadata.from_payload(json.loads(prior_stop_path.read_bytes()))
    prior_stop.verify(LAUNCHER_KEY)
    assert prior_stop.reason == "process-exit-observed"
    assert prior_stop.signal_sent is False
    assert prior_stop.public_payload()["provider_calls"] == 0
    restarted.stop_all(reason="restart-test-complete")


def test_pid_reuse_with_different_start_ticks_is_never_adopted_or_signaled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = build_fleet_spec(tmp_path)
    harness = FakeProcessHarness()
    harness.install(monkeypatch)
    created = create_new_subscription_runtime_bridge_processes(spec, control=harness.control)
    victim = created.fleet.processes[0].readiness.pending.process
    created.close_controller()
    harness.control.lose_identity(
        victim.pid,
        replacement_start_ticks=victim.start_ticks + 1,
    )

    reopened = reopen_subscription_runtime_bridge_processes(spec, control=harness.control)

    replacement = reopened.fleet.processes[0].readiness.pending.process
    assert replacement.pid != victim.pid
    assert replacement.start_ticks != victim.start_ticks
    assert reopened.fleet.processes[0].readiness.pending.generation == 2
    assert harness.control.signals == []
    assert harness.provider_dispatches == 0
    reopened.stop_all(reason="pid-reuse-test-complete")
    assert victim.pgid not in {pgid for pgid, _ in harness.control.signals}


def test_identity_change_during_readiness_fails_without_signaling_reused_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = build_fleet_spec(tmp_path)
    harness = FakeProcessHarness()
    harness.install(monkeypatch)

    def replace_identity_during_health(process_spec):
        latest = harness.spawn_records[-1]
        current = harness.control.identity(latest.pid)
        assert current is not None
        harness.control.lose_identity(
            current.pid,
            replacement_start_ticks=current.start_ticks + 1,
        )
        return harness.probe_health(process_spec)

    monkeypatch.setattr(process_launcher, "_probe_health_once", replace_identity_during_health)

    with pytest.raises(BridgeProcessError, match="identity_changed_before_ready"):
        create_new_subscription_runtime_bridge_processes(spec, control=harness.control)

    assert len(harness.spawn_records) == 1
    assert harness.control.signals == []
    assert harness.provider_dispatches == 0
    assert ACCOUNT_I_PID not in {record.pid for record in harness.spawn_records}


def test_account_i_pid_collision_is_never_terminated_or_signaled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = build_fleet_spec(tmp_path)
    harness = FakeProcessHarness()
    harness.next_pid = ACCOUNT_I_PID
    harness.install(monkeypatch)

    with pytest.raises(BridgeProcessError, match="account_i_pid_collision"):
        create_new_subscription_runtime_bridge_processes(spec, control=harness.control)

    assert [record.pid for record in harness.spawn_records] == [ACCOUNT_I_PID]
    assert harness.control.signals == []
    assert harness.control.identity(ACCOUNT_I_PID) is not None
    assert not spec.account_i_fence.state_root.exists()
    assert not spec.account_i_fence.auth_root.exists()


@pytest.mark.parametrize("protected_pid", (False, True, 0, 1))
def test_invalid_optional_protected_pid_rejected_before_any_side_effect(
    tmp_path: Path,
    protected_pid: object,
) -> None:
    item = build_fleet_spec(tmp_path).processes[0]

    class Bomb:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"side effect before validation: {name}")

    with pytest.raises(BridgeProcessError, match="protected_pid_invalid"):
        process_launcher._start_generation(  # noqa: SLF001
            item,
            lock=Bomb(),  # type: ignore[arg-type]
            generation=1,
            mode="create",
            protected_pid=protected_pid,  # type: ignore[arg-type]
            control=Bomb(),  # type: ignore[arg-type]
        )


def test_none_protected_pid_preserves_identity_and_current_pgid_guards() -> None:
    identity = ProcessIdentity(
        pid=99111,
        start_ticks=123,
        pgid=99111,
        boot_id="11111111-1111-1111-1111-111111111111",
    )

    class Process:
        pid = identity.pid

        @staticmethod
        def poll() -> None:
            return None

    class Control:
        @staticmethod
        def identity(pid: int) -> ProcessIdentity:
            assert pid == identity.pid
            return identity

        @staticmethod
        def current_pgid() -> int:
            return 777

    assert process_launcher._await_process_identity(  # noqa: SLF001
        Process(), Control(), None  # type: ignore[arg-type]
    ) == identity

    class SameGroup(Control):
        @staticmethod
        def current_pgid() -> int:
            return identity.pgid

    with pytest.raises(BridgeProcessError, match="session_isolation_failed"):
        process_launcher._await_process_identity(  # noqa: SLF001
            Process(), SameGroup(), None  # type: ignore[arg-type]
        )

"""Fail-closed contracts for the three new runtime bridge processes."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server.features.subscription_runtime_bridge import process_control
from infinity_context_server.features.subscription_runtime_bridge.contracts import (
    BridgeAuthority,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    AccountIRuntimeFence,
    BridgeFleetSpec,
    BridgeProcessError,
    ProcessIdentity,
    RuntimeProcessAuthority,
)
from infinity_context_server.features.subscription_runtime_bridge.process_control import (
    LinuxProcessControl,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
)
from subscription_runtime_bridge_process_test_support import (
    ACCOUNT_I_PID,
    ACCOUNT_I_PORT,
    BOOT_ID,
    BRIDGE_ACCOUNTS,
    BRIDGE_PORTS,
    build_fleet_spec,
)


def test_exact_three_new_bridges_are_private_distinct_and_account_i_fenced(
    tmp_path: Path,
) -> None:
    fleet = build_fleet_spec(tmp_path)

    assert tuple(item.account_name for item in fleet.processes) == BRIDGE_ACCOUNTS
    assert tuple(item.port for item in fleet.processes) == BRIDGE_PORTS
    assert len({item.state_root for item in fleet.processes}) == 3
    assert len({item.auth_root for item in fleet.processes}) == 3
    assert all(item.state_root.stat().st_mode & 0o777 == 0o700 for item in fleet.processes)
    assert all(item.auth_root.stat().st_mode & 0o777 == 0o700 for item in fleet.processes)
    assert fleet.account_i_fence.pid == ACCOUNT_I_PID
    assert fleet.account_i_fence.port == ACCOUNT_I_PORT
    assert not fleet.account_i_fence.state_root.exists()
    assert not fleet.account_i_fence.auth_root.exists()

    for reserved_name in ("account-i", "account_i", "ACCOUNT-I"):
        with pytest.raises(BridgeProcessError, match="account_i_reserved"):
            replace(fleet.processes[0], account_name=reserved_name)


@pytest.mark.parametrize("collision", ("port", "state-root", "auth-root"))
def test_fleet_rejects_new_bridge_resource_collisions(
    tmp_path: Path,
    collision: str,
) -> None:
    fleet = build_fleet_spec(tmp_path)
    first, second, third = fleet.processes
    if collision == "port":
        authority = replace(second.authority, origin=first.authority.origin)
        second = replace(second, port=first.port, authority=authority)
    elif collision == "state-root":
        second = replace(second, state_root=first.state_root)
    else:
        second = replace(second, auth_root=first.auth_root, private_files=first.private_files)

    with pytest.raises(BridgeProcessError, match="fleet_(port_duplicate|roots_overlap)"):
        BridgeFleetSpec(
            pool_id=fleet.pool_id,
            processes=(first, second, third),
            account_i_fence=fleet.account_i_fence,
        )


def test_fleet_rejects_every_account_i_resource_collision(tmp_path: Path) -> None:
    fleet = build_fleet_spec(tmp_path)
    first, second, third = fleet.processes
    protected = AccountIRuntimeFence(
        pid=ACCOUNT_I_PID,
        port=first.port,
        state_root=fleet.account_i_fence.state_root,
        auth_root=fleet.account_i_fence.auth_root,
    )
    with pytest.raises(BridgeProcessError, match="account_i_port_collision"):
        BridgeFleetSpec(
            pool_id=fleet.pool_id,
            processes=(first, second, third),
            account_i_fence=protected,
        )

    protected = replace(fleet.account_i_fence, state_root=first.state_root)
    with pytest.raises(BridgeProcessError, match="account_i_root_collision"):
        BridgeFleetSpec(
            pool_id=fleet.pool_id,
            processes=(first, second, third),
            account_i_fence=protected,
        )

    protected = replace(fleet.account_i_fence, auth_root=first.auth_root)
    with pytest.raises(BridgeProcessError, match="account_i_root_collision"):
        BridgeFleetSpec(
            pool_id=fleet.pool_id,
            processes=(first, second, third),
            account_i_fence=protected,
        )

    protected = replace(fleet.account_i_fence, state_root=first.runtime_root)
    with pytest.raises(BridgeProcessError, match="account_i_public_path_collision"):
        BridgeFleetSpec(
            pool_id=fleet.pool_id,
            processes=(first, second, third),
            account_i_fence=protected,
        )


def test_runtime_authority_pins_reviewed_provider_profile(tmp_path: Path) -> None:
    process = build_fleet_spec(tmp_path).processes[0]
    authority = RuntimeProcessAuthority(
        account_name=process.account_name,
        bridge_authority=process.authority,
        state_root_identity_sha256="1" * 64,
        auth_root_identity_sha256="2" * 64,
        private_material_binding_hmac_sha256="3" * 64,
        runtime_artifact_manifest_sha256=process.runtime_artifact_manifest_sha256,
        runtime_entrypoint_sha256=process.runtime_entrypoint_sha256,
        node_executable_sha256=process.node_executable_sha256,
        codex_executable_sha256=process.codex_executable_sha256,
    )

    payload = authority.public_payload()
    assert payload["codex_model"] == BridgeAuthority.CODEX_MODEL == "gpt-5.6-sol"
    assert payload["reasoning_effort"] == BridgeAuthority.REASONING_EFFORT == "high"
    assert payload["service_tier"] == BridgeAuthority.SERVICE_TIER == "priority"
    assert (
        payload["bridge_authority"]["base_instructions_sha256"]
        == SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256
    )
    assert payload["max_concurrent_requests"] == 1
    assert payload["max_account_cycles"] == 1
    assert payload["readiness_route"] == "/health"
    assert payload["readiness_provider_calls"] == 0
    assert payload["provider_call_recovery"] == "durable-intent-readback-no-redispatch"


def test_linux_control_binds_pid_pgid_start_ticks_and_kernel_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = 52_345
    suffix = ["S", "1", str(pid)] + ["0"] * 16 + ["987654321"]
    stat = f"{pid} (runtime worker with ) in name) {' '.join(suffix)}\n".encode()

    def fake_read(path: Path, *, maximum_bytes: int) -> bytes:
        del maximum_bytes
        if path == Path(f"/proc/{pid}/stat"):
            return stat
        if path == Path("/proc/sys/kernel/random/boot_id"):
            return f"{BOOT_ID}\n".encode()
        raise AssertionError(f"unexpected proc read: {path}")

    monkeypatch.setattr(process_control, "bounded_read", fake_read)

    assert LinuxProcessControl().identity(pid) == ProcessIdentity(
        pid=pid,
        start_ticks=987_654_321,
        pgid=pid,
        boot_id=BOOT_ID,
    )


def test_linux_control_rejects_zombie_or_non_group_leader_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = 52_346

    def fake_read(path: Path, *, maximum_bytes: int) -> bytes:
        del maximum_bytes
        if path.name == "stat":
            return f"{pid} (runtime) Z 1 {pid} ".encode() + b"0 " * 20
        raise AssertionError("zombie identity must not read boot id")

    monkeypatch.setattr(process_control, "bounded_read", fake_read)
    assert LinuxProcessControl().identity(pid) is None

    suffix = ["S", "1", str(pid + 1)] + ["0"] * 16 + ["99"]

    def non_leader(path: Path, *, maximum_bytes: int) -> bytes:
        del maximum_bytes
        if path.name == "stat":
            return f"{pid} (runtime) {' '.join(suffix)}".encode()
        return BOOT_ID.encode()

    monkeypatch.setattr(process_control, "bounded_read", non_leader)
    assert LinuxProcessControl().identity(pid) is None

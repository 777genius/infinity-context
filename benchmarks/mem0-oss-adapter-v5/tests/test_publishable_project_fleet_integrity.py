from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest
from infinity_context_runtime_bridge.contracts import BridgeAuthority
from infinity_context_runtime_bridge.process_contracts import (
    RuntimeProcessAuthority,
)
from publishable_mem0_v5 import runtime_integrity
from publishable_mem0_v5.config import BASE_INSTRUCTIONS_SHA256, PublishableLaneConfig

from tests.publishable_deployment_runtime_fixture import (
    build_config,
    private_directory,
    private_file,
)


def _install_project_lifecycle(
    config: PublishableLaneConfig,
    *,
    generations: tuple[int, ...] = (1, 2),
) -> None:
    for index, (account, port) in enumerate(
        zip(config.bridges, (8891, 8892, 8893), strict=True)
    ):
        authority = BridgeAuthority(
            bridge_id=account.bridge_id,
            origin=f"http://127.0.0.1:{port}",
            account_binding_hmac_sha256=account.account_binding_hmac_sha256,
            public_model="gpt-5.6-sol",
            base_instructions_sha256=BASE_INSTRUCTIONS_SHA256,
        )
        runtime_authority = RuntimeProcessAuthority(
            account_name=account.account_name,
            bridge_authority=authority,
            state_root_identity_sha256=f"{index + 1:x}" * 64,
            auth_root_identity_sha256=f"{index + 4:x}" * 64,
            private_material_binding_hmac_sha256=f"{index + 7:x}" * 64,
            runtime_artifact_manifest_sha256=config.runtime.runtime_artifact_manifest_sha256,
            runtime_entrypoint_sha256=config.runtime.runtime_entrypoint_sha256,
            node_executable_sha256=config.runtime.node_executable_sha256,
            codex_executable_sha256=config.runtime.codex_executable_sha256,
        )
        state_base = config.paths.fleet_state_dir / account.account_name
        current = state_base / "current"
        lifecycle = current / ".infinity-context-bridge-launcher"
        for path in (state_base, current, lifecycle):
            private_directory(path)
        private_file(lifecycle / "launcher.lock", b"")
        private_file(
            lifecycle / "active.json",
            b"FORBIDDEN_PROCESS_IDENTITY:pid=991,start_ticks=123,boot_id=secret",
        )
        private_file(
            lifecycle / "runtime-authority.json",
            _canonical_json(runtime_authority.public_payload()),
        )
        for generation in generations:
            generation_root = lifecycle / f"generation-{generation:07d}"
            private_directory(generation_root)
            private_file(
                generation_root / "pending.json",
                b"FORBIDDEN_PROCESS_IDENTITY:pid=992,start_ticks=124",
            )
            private_file(
                generation_root / "readiness.json",
                b"FORBIDDEN_PROCESS_IDENTITY:pid=993,start_ticks=125",
            )
            if generation != generations[-1]:
                private_file(
                    generation_root / "stop.json",
                    b"FORBIDDEN_PROCESS_IDENTITY:pid=994,start_ticks=126",
                )


def test_project_fleet_attestation_opens_no_process_identity_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, proc_root = build_config(tmp_path)
    _install_project_lifecycle(config)
    original_read = runtime_integrity._read_private_json
    original_open = os.open
    original_path_open = Path.open
    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text
    read_paths: list[Path] = []

    def authority_only(path: Path, **arguments: int) -> dict[str, object]:
        assert path.name == "runtime-authority.json"
        read_paths.append(path)
        return original_read(path, **arguments)

    def reject_namespace(path: Path) -> tuple[int, int]:
        raise AssertionError(f"project scope touched host namespace identity: {path}")

    def authority_only_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        assert Path(path).name == "runtime-authority.json"
        return original_open(path, flags, mode, dir_fd=dir_fd)

    def authority_only_path_open(path: Path, *arguments: object, **keywords: object) -> object:
        assert path.name == "runtime-authority.json"
        return original_path_open(path, *arguments, **keywords)

    def authority_only_read_bytes(path: Path) -> bytes:
        assert path.name == "runtime-authority.json"
        return original_read_bytes(path)

    def authority_only_read_text(path: Path, *arguments: object, **keywords: object) -> str:
        assert path.name == "runtime-authority.json"
        return original_read_text(path, *arguments, **keywords)

    monkeypatch.setattr(runtime_integrity, "_read_private_json", authority_only)
    monkeypatch.setattr(runtime_integrity, "_namespace_tuple", reject_namespace)
    monkeypatch.setattr(runtime_integrity.os, "open", authority_only_open)
    monkeypatch.setattr(Path, "open", authority_only_path_open)
    monkeypatch.setattr(Path, "read_bytes", authority_only_read_bytes)
    monkeypatch.setattr(Path, "read_text", authority_only_read_text)

    signature = inspect.signature(runtime_integrity.attest_project_fleet_evidence)
    assert tuple(signature.parameters) == (
        "config",
        "fleet_mode",
        "expected_uid",
        "expected_gid",
    )
    evidence = runtime_integrity.attest_project_fleet_evidence(
        config,
        fleet_mode="reopen",
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )

    assert len({item.lifecycle_inventory_sha256 for item in evidence.bridges}) == 3
    assert len(evidence.fleet_evidence_sha256) == 64
    assert len(read_paths) == 3
    rendered = json.dumps(evidence.payload(), sort_keys=True)
    for forbidden in (
        "controller_pid",
        "process",
        "pid",
        "start_ticks",
        "boot_id",
        "generation",
        "launch_mode",
        "readiness_receipt",
    ):
        assert forbidden not in rendered
    assert all(proc_root != path and proc_root not in path.parents for path in read_paths)


@pytest.mark.parametrize(
    ("generations", "reason"),
    (
        ((1, 3), "fleet_generation_invalid"),
        ((), "fleet_generation_invalid"),
    ),
)
def test_project_fleet_rejects_non_contiguous_or_empty_generation_inventory(
    tmp_path: Path,
    generations: tuple[int, ...],
    reason: str,
) -> None:
    config, _proc_root = build_config(tmp_path)
    _install_project_lifecycle(config, generations=generations)

    with pytest.raises(runtime_integrity.RuntimeIntegrityError, match=reason):
        runtime_integrity.attest_project_fleet_evidence(
            config,
            fleet_mode="reopen",
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )


def test_project_fleet_rejects_unexpected_lifecycle_file_without_opening_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _proc_root = build_config(tmp_path)
    _install_project_lifecycle(config)
    lifecycle = (
        config.paths.fleet_state_dir
        / config.bridges[0].account_name
        / "current/.infinity-context-bridge-launcher"
    )
    private_file(lifecycle / "ambiguous-process.json", b"pid=unrelated")
    original_read = runtime_integrity._read_private_json

    def authority_only(path: Path, **arguments: int) -> dict[str, object]:
        assert path.name == "runtime-authority.json"
        return original_read(path, **arguments)

    monkeypatch.setattr(runtime_integrity, "_read_private_json", authority_only)

    with pytest.raises(
        runtime_integrity.RuntimeIntegrityError,
        match="fleet_lifecycle_inventory_invalid",
    ):
        runtime_integrity.attest_project_fleet_evidence(
            config,
            fleet_mode="reopen",
            expected_uid=os.geteuid(),
            expected_gid=os.getegid(),
        )


def test_project_fleet_binds_requested_create_mode_without_claiming_receipt_identity(
    tmp_path: Path,
) -> None:
    config, _proc_root = build_config(tmp_path)
    _install_project_lifecycle(config, generations=(1,))

    evidence = runtime_integrity.attest_project_fleet_evidence(
        config,
        fleet_mode="create",
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
    )

    assert evidence.requested_mode == "create"
    assert "generation" not in json.dumps(evidence.payload(), sort_keys=True)
    assert "launch_mode" not in json.dumps(evidence.payload(), sort_keys=True)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

from __future__ import annotations

import copy
import os
import shutil
import time
from pathlib import Path

import pytest
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
)
from publishable_mem0_v5.acceptance import run_docker_acceptance
from publishable_mem0_v5.run_provider import PublishableProductionOpenMode
from publishable_mem0_v5.run_provider_config import parse_run_provider_inputs
from publishable_mem0_v5.run_provider_preflight import preflight_run_provider
from test_publishable_docker_acceptance import (
    _RUNTIME_ATTESTATION_KEY,
    FakeDockerRunner,
    FakeLaneDeployer,
    FakeProviderProbe,
    _acceptance_config,
    _fake_deployment_attestor,
)
from test_publishable_operator_staging import _build
from test_publishable_run_provider_preflight import (
    _authenticate_host_attestation,
    _build_lane,
    _install_authentic_endpoint,
    _write_host_attestation,
    _write_private,
)


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


def _append_evidence(source: Path, destination: Path) -> None:
    for path in sorted(source.iterdir()):
        target = destination / path.name
        assert not target.exists()
        shutil.copy2(path, target)


def _activate_recovery(current: object, recovery: object) -> None:
    for source, target in zip(
        recovery.control_paths,
        current.control_paths,
        strict=True,
    ):
        shutil.copyfile(source, target)
        target.chmod(0o600)
    for source, target in zip(
        recovery.runtime_authority_paths,
        current.runtime_authority_paths,
        strict=True,
    ):
        shutil.copyfile(source, target)
        target.chmod(0o600)
    target = current.attestation_directory / recovery.attestation_path.name
    assert not target.exists()
    shutil.copy2(recovery.attestation_path, target)


def test_generated_production_order_composes_acceptance_paid_create_and_crash_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated_root = tmp_path / "generated"
    generated_root.mkdir()
    commands = _build(generated_root).commands.payload()
    assert [item["name"] for item in commands["initial_paid_create_order"]] == [
        "acceptance",
        "start_reopen",
        "attest_reopen",
        "prepare_inputs",
        "run_2040",
    ]
    assert [item["name"] for item in commands["crash_reopen_resume_order"]] == [
        "start_reopen",
        "attest_reopen",
        "run_2040",
    ]
    assert "--fleet-mode reopen" in commands["start_reopen"]
    assert "--fleet-mode reopen" in commands["attest_reopen"]

    acceptance, proc_root, config_file = _acceptance_config(tmp_path / "acceptance")
    runner = FakeDockerRunner()
    deployer = FakeLaneDeployer()
    probe = FakeProviderProbe(acceptance)
    outcome = run_docker_acceptance(
        config_file=config_file,
        runner=runner,
        proc_root=proc_root,
        expected_uid=os.geteuid(),
        expected_gid=os.getegid(),
        lane_deployer=deployer,
        runtime_probe=probe,
        deployment_attestor=_fake_deployment_attestor,
    )
    assert outcome.payload()["outcome"] == "ACCEPTED_PROVIDER_FREE"
    acceptance_evidence = _snapshot(acceptance.paths.attestation_dir)
    assert any(name.startswith("runtime-attestation-") for name in acceptance_evidence)
    assert any(name.startswith("provider-attestation-") for name in acceptance_evidence)
    assert any(name.startswith("docker-acceptance-") for name in acceptance_evidence)

    observed_at = time.time_ns()
    paid = _build_lane(
        tmp_path / "paid-create",
        project=acceptance.project_name,
        generation=3,
        identity_offset=300,
        observed_at_unix_ns=observed_at,
        requested_mode="reopen",
        retained_launch_mode="reopen",
        runtime_root_secret=_RUNTIME_ATTESTATION_KEY,
    )
    _append_evidence(acceptance.paths.attestation_dir, paid.attestation_directory)
    immutable_before_create = _snapshot(paid.attestation_directory)
    config, secrets = parse_run_provider_inputs(paid.inputs)
    endpoint_calls = _install_authentic_endpoint(monkeypatch, paid)

    assert (
        preflight_run_provider(
            config=config,
            secrets=secrets,
            mode=PublishableProductionOpenMode.CREATE,
        )
        == paid.readiness
    )

    recovery = _build_lane(
        tmp_path / "paid-crash-reopen",
        project=acceptance.project_name,
        generation=4,
        identity_offset=400,
        observed_at_unix_ns=observed_at + 1,
        requested_mode="reopen",
        retained_launch_mode="reopen",
        runtime_root_secret=_RUNTIME_ATTESTATION_KEY,
    )
    _activate_recovery(paid, recovery)
    assert (
        preflight_run_provider(
            config=config,
            secrets=secrets,
            mode=PublishableProductionOpenMode.RESUME,
        )
        == recovery.readiness
    )

    evidence_after_resume = _snapshot(paid.attestation_directory)
    assert evidence_after_resume.items() >= immutable_before_create.items()
    assert acceptance_evidence.items() <= evidence_after_resume.items()
    assert len(endpoint_calls) == 2
    assert paid.readiness.launches[0].pending.generation == 3
    assert recovery.readiness.launches[0].pending.generation == 4
    assert paid.readiness.launches[0].pending.process != (
        recovery.readiness.launches[0].pending.process
    )
    assert paid.attestation_payload["services"] != recovery.attestation_payload["services"]


def test_stale_current_receipt_is_not_rescued_by_fresh_unrelated_runtime_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _build_lane(
        tmp_path,
        observed_at_unix_ns=time.time_ns() - 301_000_000_000,
        requested_mode="reopen",
        retained_launch_mode="reopen",
    )
    unrelated = copy.deepcopy(lane.attestation_payload)
    unrelated["observed_at_unix_ns"] = time.time_ns()
    unrelated["project_name"] = "unrelated-paid-lane"
    _write_host_attestation(
        lane.attestation_directory,
        _authenticate_host_attestation(unrelated, lane.runtime_root_secret),
    )
    config, secrets = parse_run_provider_inputs(lane.inputs)
    endpoint_calls = _install_authentic_endpoint(monkeypatch, lane)

    with pytest.raises(PublishableRunError, match="stale_or_cross_mode"):
        preflight_run_provider(
            config=config,
            secrets=secrets,
            mode=PublishableProductionOpenMode.CREATE,
        )

    assert endpoint_calls == []


def test_paid_provider_config_rejects_create_as_runtime_fleet_authority(tmp_path: Path) -> None:
    lane = _build_lane(tmp_path, retained_launch_mode="reopen")
    hostile = copy.deepcopy(lane.config)
    hostile["runtime"]["attestation"]["required_fleet_mode"] = "create"

    with pytest.raises(PublishableRunError, match="config_invalid"):
        parse_run_provider_inputs(lane.provider_inputs(config=hostile))


@pytest.mark.parametrize(
    "cross_wire",
    (
        "generation",
        "controller_pid",
        "process_pid",
        "container_id",
        "project",
        "requested_mode",
    ),
)
def test_newer_mixed_generation_or_identity_receipt_never_selects_as_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cross_wire: str,
) -> None:
    observed_at = time.time_ns()
    lane = _build_lane(
        tmp_path,
        generation=3,
        identity_offset=300,
        observed_at_unix_ns=observed_at,
        requested_mode="reopen",
        retained_launch_mode="reopen",
    )
    mixed = copy.deepcopy(lane.attestation_payload)
    mixed["observed_at_unix_ns"] = observed_at + 1
    if cross_wire == "generation":
        mixed["fleet"]["bridges"][0]["generation"] = 4
    elif cross_wire == "controller_pid":
        mixed["fleet"]["bridges"][0]["controller_pid"] += 1
    elif cross_wire == "process_pid":
        mixed["fleet"]["bridges"][0]["process"]["pid"] += 1
    elif cross_wire == "container_id":
        mixed["services"]["publishable-adapter"]["container_id"] = "f" * 64
    elif cross_wire == "project":
        mixed["project_name"] = "unrelated-paid-lane"
    elif cross_wire == "requested_mode":
        mixed["fleet"]["requested_mode"] = "create"
    else:
        raise AssertionError(cross_wire)
    _write_host_attestation(
        lane.attestation_directory,
        _authenticate_host_attestation(mixed, lane.runtime_root_secret),
    )
    config, secrets = parse_run_provider_inputs(lane.inputs)
    endpoint_calls = _install_authentic_endpoint(monkeypatch, lane)

    with pytest.raises(PublishableRunError):
        preflight_run_provider(
            config=config,
            secrets=secrets,
            mode=PublishableProductionOpenMode.RESUME,
        )

    assert endpoint_calls == []


def test_runtime_prefixed_malformed_filename_still_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _build_lane(tmp_path, retained_launch_mode="reopen")
    _write_private(
        lane.attestation_directory / "runtime-attestation-not-a-digest.json",
        {"untrusted": True},
    )
    config, secrets = parse_run_provider_inputs(lane.inputs)
    endpoint_calls = _install_authentic_endpoint(monkeypatch, lane)

    with pytest.raises(PublishableRunError, match="attestation_file_invalid"):
        preflight_run_provider(
            config=config,
            secrets=secrets,
            mode=PublishableProductionOpenMode.CREATE,
        )

    assert endpoint_calls == []

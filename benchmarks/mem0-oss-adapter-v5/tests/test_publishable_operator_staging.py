from __future__ import annotations

import json
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server.publishable_durable_scheduler import publishable_run_cli
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PUBLISHABLE_RUN_SECRETS_SCHEMA,
)
from publishable_mem0_v5.config import load_lane_config
from publishable_mem0_v5.run_provider import (
    PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME,
    Mem0InfinityPublishableRunDependencyFactory,
)

from tools.build_publishable_staging import (
    OperatorStagingError,
    StagingPublicInputs,
    build_staging_bundle,
    load_staging_template,
    main,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "operator" / "publishable-staging.template.json"
REQUIRED_R16_PORTS = (6334, 8891, 8892, 19091)


def _public_inputs(
    *,
    protected_ports: tuple[int, ...] = REQUIRED_R16_PORTS,
    occupied_ports: tuple[int, ...] = (),
) -> StagingPublicInputs:
    return StagingPublicInputs(
        adapter_image_id="sha256:" + "a" * 64,
        codex_executable_sha256="d" * 64,
        bridge_account_binding_sha256=("1" * 64, "2" * 64, "3" * 64),
        config_hmac_sha256="4" * 64,
        deployment_closure_sha256="5" * 64,
        deployment_closure_hmac_sha256="6" * 64,
        server_closure_sha256="7" * 64,
        server_closure_hmac_sha256="8" * 64,
        account_i_pid=99101,
        account_i_start_ticks=812345,
        account_i_boot_id="11111111-1111-4111-8111-111111111111",
        account_i_netns_inode=4026532991,
        account_i_port=28891,
        account_i_protected_host_ports=protected_ports,
        account_i_container_ids=("9" * 64,),
        occupied_host_ports=occupied_ports,
    )


def _build(tmp_path: Path):
    return build_staging_bundle(
        template=load_staging_template(TEMPLATE),
        output_root=tmp_path / "operator-private-r17-6f2c",
        authority_root=tmp_path / "public-authorities-r17-6f2c",
        public_inputs=_public_inputs(),
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_builds_exact_secret_free_lane_and_2040_configs_with_private_modes(
    tmp_path: Path,
) -> None:
    bundle = _build(tmp_path)
    lane = json.loads(bundle.lane_config_path.read_bytes())
    run = json.loads(bundle.run_config_path.read_bytes())

    assert lane["schema_version"] == "publishable-mem0-v5-isolated-lane.v2"
    assert lane["bind_mount_authority"] == {
        "config_hmac_sha256": "4" * 64,
        "deployment_closure_hmac_sha256": "6" * 64,
        "deployment_closure_sha256": "5" * 64,
        "server_closure_hmac_sha256": "8" * 64,
        "server_closure_sha256": "7" * 64,
    }
    assert load_lane_config(bundle.lane_config_path).public_payload() == lane
    assert lane["project_name"] == "mem0-v5-publishable-staging-r17-6f2c"
    assert lane["host_adapter_port"] == 29192
    assert lane["docker_host"] == (
        "unix:///run/infinity-context/mem0-v5-publishable-staging-r17-6f2c/docker.sock"
    )
    assert [item["account_name"] for item in lane["bridges"]] == [
        "publishable-r17-6f2c-a",
        "publishable-r17-6f2c-b",
        "publishable-r17-6f2c-c",
    ]
    assert [item["account_binding_hmac_sha256"] for item in lane["bridges"]] == [
        "1" * 64,
        "2" * 64,
        "3" * 64,
    ]
    fence = lane["account_i_r16_fence"]
    assert fence == {
        "auth_root": "/var/data/codex-home/live-codex-auth/account-i",
        "boot_id": "11111111-1111-4111-8111-111111111111",
        "container_ids": ["9" * 64],
        "netns_inode": 4026532991,
        "pid": 99101,
        "port": 28891,
        "protected_host_ports": list(REQUIRED_R16_PORTS),
        "start_ticks": 812345,
        "state_root": (
            "/mnt/volume_ams3_1784742570542/infinity-context/live-canaries/"
            "mem0-v5-live-d7bf1ac4-r16"
        ),
    }
    private_lane_paths = [
        Path(value)
        for key, value in lane["paths"].items()
        if key
        in {
            "adapter_secret_dir",
            "adapter_state_dir",
            "attestation_dir",
            "fleet_auth_dir",
            "fleet_state_dir",
            "input_dir",
            "qdrant_state_dir",
        }
    ]
    assert len(set(private_lane_paths)) == 7
    assert all(path.parent == Path(lane["paths"]["run_root"]) for path in private_lane_paths)
    assert lane["runtime"]["codex_executable_sha256"] == "d" * 64

    assert run == {
        "adapter": {
            "expected_case_count": 2040,
            "expected_evaluation_call_count": 8160,
            "expected_extraction_operation_count": 130226,
            "expected_total_call_count": 138386,
            "lane_project_name": "mem0-v5-publishable-staging-r17-6f2c",
            "public_endpoint": "http://127.0.0.1:29192",
            "runtime_attestation_directory": str(
                bundle.output_root
                / "mem0-v5-publishable-staging-r17-6f2c"
                / "runtime-attestations-r17-6f2c"
            ),
        },
        "dependency_provider": "mem0-infinity-production-v1",
        "max_dispatches_per_batch": 64,
        "publication_key_id": "publishable-staging-r17-6f2c-publication-2040",
        "schema_version": "memory-comparison-publishable-run-config.v1",
        "state": {
            "longmemeval_scheduler_database_path": str(
                bundle.run_private_root
                / "state-2040-r17-6f2c"
                / "longmemeval-2040-r17-6f2c.sqlite3"
            ),
            "locomo_scheduler_database_path": str(
                bundle.run_private_root / "state-2040-r17-6f2c" / "locomo-2040-r17-6f2c.sqlite3"
            ),
            "official_case_authority_path": str(
                bundle.run_private_root
                / "state-2040-r17-6f2c"
                / "official-cases-2040-r17-6f2c.sqlite3"
            ),
            "publication_receipt_path": str(
                bundle.run_private_root
                / "state-2040-r17-6f2c"
                / "publication-receipt-2040-r17-6f2c.json"
            ),
            "suite_seal_database_path": str(
                bundle.run_private_root
                / "state-2040-r17-6f2c"
                / "suite-seals-2040-r17-6f2c.sqlite3"
            ),
        },
    }
    assert not bundle.secrets_path.exists()
    assert _mode(bundle.lane_config_path) == 0o600
    assert _mode(bundle.run_config_path) == 0o600
    directories = (
        bundle.output_root,
        Path(lane["paths"]["run_root"]),
        *private_lane_paths,
        bundle.run_private_root,
        bundle.run_private_root / "state-2040-r17-6f2c",
    )
    assert all(_mode(path) == 0o700 for path in directories)
    assert "publishable-run-2040.secrets.json" not in bundle.run_config_path.read_text()
    assert "credentials" not in bundle.run_config_path.read_text().casefold()


def test_generated_run_config_resolves_exact_installed_factory_provider_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = _build(tmp_path)
    run = json.loads(bundle.run_config_path.read_bytes())
    assert (
        run["dependency_provider"]
        == PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME
        == "mem0-infinity-production-v1"
    )

    secrets = {
        "adapter": {},
        "keys": {
            "official_case_authentication_key_hex": "1" * 64,
            "locomo_scheduler_authentication_key_hex": "2" * 64,
            "longmemeval_scheduler_authentication_key_hex": "3" * 64,
            "suite_seal_authentication_key_hex": "4" * 64,
            "publication_receipt_authentication_key_hex": "5" * 64,
        },
        "schema_version": PUBLISHABLE_RUN_SECRETS_SCHEMA,
    }
    bundle.secrets_path.write_text(json.dumps(secrets))
    bundle.secrets_path.chmod(0o600)
    resolved: list[object] = []

    class ProviderFreeOrchestrator:
        def __init__(self, *, dependency_factory: object) -> None:
            resolved.append(dependency_factory)

        def run(self, **_arguments: object) -> SimpleNamespace:
            return SimpleNamespace(
                payload=lambda: {"publishable": True},
                publishable=True,
            )

    monkeypatch.setattr(publishable_run_cli, "PublishableRunOrchestrator", ProviderFreeOrchestrator)

    assert publishable_run_cli.main(bundle.commands.run_2040[1:]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {"publishable": True}
    assert len(resolved) == 1
    assert type(resolved[0]) is Mem0InfinityPublishableRunDependencyFactory


def test_commands_are_exact_for_acceptance_reopen_attest_and_run(tmp_path: Path) -> None:
    bundle = _build(tmp_path)
    lane = str(bundle.lane_config_path)
    run_root = str(bundle.run_private_root)
    run_config = str(bundle.run_config_path)
    secrets = str(bundle.secrets_path)

    assert bundle.commands.acceptance == (
        "infinity-context-publishable-mem0-v5",
        "acceptance",
        "--config",
        lane,
    )
    assert bundle.commands.run_2040 == (
        "infinity-context-publishable-run",
        "--private-root",
        run_root,
        "--config",
        run_config,
        "--secrets",
        secrets,
        "--allow-live",
    )
    assert bundle.commands.start_reopen[-2:] == ("--fleet-mode", "reopen")
    assert bundle.commands.attest_reopen[-2:] == ("--fleet-mode", "reopen")
    assert bundle.commands.payload() == {
        "acceptance": f"infinity-context-publishable-mem0-v5 acceptance --config {lane}",
        "attest_reopen": (
            f"infinity-context-publishable-mem0-v5 attest --config {lane} --fleet-mode reopen"
        ),
        "operator_order": [
            {
                "command": f"infinity-context-publishable-mem0-v5 acceptance --config {lane}",
                "name": "acceptance",
            },
            {
                "command": (
                    f"infinity-context-publishable-mem0-v5 start --config {lane} "
                    "--fleet-mode reopen"
                ),
                "name": "start_reopen",
            },
            {
                "command": (
                    f"infinity-context-publishable-mem0-v5 attest --config {lane} "
                    "--fleet-mode reopen"
                ),
                "name": "attest_reopen",
            },
            {
                "command": (
                    f"infinity-context-publishable-run --private-root {run_root} "
                    f"--config {run_config} --secrets {secrets} --allow-live"
                ),
                "name": "run_2040",
            },
        ],
        "run_2040": (
            f"infinity-context-publishable-run --private-root {run_root} "
            f"--config {run_config} --secrets {secrets} --allow-live"
        ),
        "start_reopen": (
            f"infinity-context-publishable-mem0-v5 start --config {lane} --fleet-mode reopen"
        ),
    }


@pytest.mark.parametrize("mode", (0o755, 0o750, 0o711))
def test_rejects_non_private_existing_output_root(tmp_path: Path, mode: int) -> None:
    output = tmp_path / "operator-private-r17-6f2c"
    output.mkdir(mode=mode)
    output.chmod(mode)

    with pytest.raises(
        OperatorStagingError,
        match="operator_staging_private_directory_invalid",
    ):
        build_staging_bundle(
            template=load_staging_template(TEMPLATE),
            output_root=output,
            authority_root=tmp_path / "public-authorities-r17-6f2c",
            public_inputs=_public_inputs(),
        )

    assert not any(output.iterdir())
    assert _mode(output) == mode


@pytest.mark.parametrize("source", ("protected", "occupied"))
def test_rejects_host_port_collision_before_writing(tmp_path: Path, source: str) -> None:
    protected = (*REQUIRED_R16_PORTS, 29192) if source == "protected" else REQUIRED_R16_PORTS
    occupied = (29192,) if source == "occupied" else ()
    output = tmp_path / "operator-private-r17-6f2c"

    with pytest.raises(OperatorStagingError, match="operator_staging_host_port_collision"):
        build_staging_bundle(
            template=load_staging_template(TEMPLATE),
            output_root=output,
            authority_root=tmp_path / "public-authorities-r17-6f2c",
            public_inputs=_public_inputs(
                protected_ports=protected,
                occupied_ports=occupied,
            ),
        )

    assert not output.exists()


def test_rejects_existing_output_without_overwriting_it(tmp_path: Path) -> None:
    template = load_staging_template(TEMPLATE)
    output = tmp_path / "operator-private-r17-6f2c"
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    existing = output / template.lane_config_file_name
    existing.write_text("operator-owned-existing-config")
    existing.chmod(0o600)

    with pytest.raises(OperatorStagingError, match="operator_staging_output_collision"):
        build_staging_bundle(
            template=template,
            output_root=output,
            authority_root=tmp_path / "public-authorities-r17-6f2c",
            public_inputs=_public_inputs(),
        )

    assert existing.read_text() == "operator-owned-existing-config"


def test_rejects_template_path_and_bridge_name_collisions(tmp_path: Path) -> None:
    raw = json.loads(TEMPLATE.read_bytes())
    names = raw["lane"]["private_directory_names"]
    names["qdrant_state_dir"] = names["adapter_state_dir"]
    collision = tmp_path / "path-collision.json"
    collision.write_text(json.dumps(raw))

    with pytest.raises(OperatorStagingError, match="operator_staging_private_path_collision"):
        load_staging_template(collision)

    raw = json.loads(TEMPLATE.read_bytes())
    raw["lane"]["bridge_accounts"][2]["account_name"] = raw["lane"]["bridge_accounts"][0][
        "account_name"
    ]
    collision.write_text(json.dumps(raw))
    with pytest.raises(OperatorStagingError, match="operator_staging_bridge_name_collision"):
        load_staging_template(collision)


def test_rejects_any_account_i_r16_fence_root_change(tmp_path: Path) -> None:
    raw = json.loads(TEMPLATE.read_bytes())
    raw["account_i_r16_fence"]["auth_root"] = str(tmp_path / "lookalike-account-i")
    changed = tmp_path / "changed-fence.json"
    changed.write_text(json.dumps(raw))

    with pytest.raises(OperatorStagingError, match="operator_staging_account_i_r16_fence_invalid"):
        load_staging_template(changed)


def test_cli_reports_only_secret_free_paths_and_exact_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "operator-private-r17-6f2c"
    authority = tmp_path / "public-authorities-r17-6f2c"
    argv = [
        "--template",
        str(TEMPLATE),
        "--output-root",
        str(output),
        "--authority-root",
        str(authority),
        "--adapter-image-id",
        "sha256:" + "a" * 64,
        "--codex-executable-sha256",
        "d" * 64,
        "--config-hmac-sha256",
        "4" * 64,
        "--deployment-closure-sha256",
        "5" * 64,
        "--deployment-closure-hmac-sha256",
        "6" * 64,
        "--server-closure-sha256",
        "7" * 64,
        "--server-closure-hmac-sha256",
        "8" * 64,
    ]
    for binding in ("1" * 64, "2" * 64, "3" * 64):
        argv.extend(("--bridge-binding-sha256", binding))
    argv.extend(
        (
            "--account-i-pid",
            "99101",
            "--account-i-start-ticks",
            "812345",
            "--account-i-boot-id",
            "11111111-1111-4111-8111-111111111111",
            "--account-i-netns-inode",
            "4026532991",
            "--account-i-port",
            "28891",
        )
    )
    for port in REQUIRED_R16_PORTS:
        argv.extend(("--account-i-protected-host-port", str(port)))
    argv.extend(("--account-i-container-id", "9" * 64))

    assert main(argv) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["status"] == "STAGED_SECRET_FREE"
    assert payload["secrets_path_not_created"].endswith("/publishable-run-2040.secrets.json")
    assert payload["commands"]["run_2040"].endswith(
        "/publishable-run-2040.secrets.json --allow-live"
    )
    assert [item["name"] for item in payload["commands"]["operator_order"]] == [
        "acceptance",
        "start_reopen",
        "attest_reopen",
        "run_2040",
    ]
    assert "start_create" not in payload["commands"]
    assert "attest_create" not in payload["commands"]
    assert not Path(payload["secrets_path_not_created"]).exists()


def test_public_input_bindings_must_be_three_distinct_commitments() -> None:
    with pytest.raises(OperatorStagingError, match="operator_staging_bridge_bindings_invalid"):
        replace(
            _public_inputs(),
            bridge_account_binding_sha256=("1" * 64, "1" * 64, "3" * 64),
        )

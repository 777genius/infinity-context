from __future__ import annotations

import copy
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_runtime_attestation as managed_attestation,
)
from infinity_context_server.features.subscription_runtime_bridge import (
    BridgeAuthority,
    BridgePoolAuthority,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    BridgeFleetReadinessReceipt,
    BridgeLaunchReceipt,
    PendingLaunchMetadata,
    ProcessIdentity,
    RuntimeHealthEvidence,
    RuntimeProcessAuthority,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
    PublishableRunProviderInputs,
)
from publishable_mem0_v5 import (
    run_provider,
    run_provider_preflight,
)
from publishable_mem0_v5 import (
    runtime_attestation as host_runtime_attestation,
)
from publishable_mem0_v5.run_provider import (
    Mem0InfinityPublishableRunDependencyFactory,
    PublishableProductionOpenMode,
)
from publishable_mem0_v5.run_provider_config import parse_run_provider_inputs
from publishable_mem0_v5.runtime_integrity import (
    BridgeRuntimeIdentity,
    FleetRuntimeEvidence,
)

_HERE = Path(__file__).resolve().parents[1]
_RUNTIME_PIN_SOURCE = _HERE / "authority/runtime-pin.json"
_CONTROL_SCHEMA = "publishable-mem0-v5-bridge-controller-readiness.v2"
_HOST_ATTESTATION_SCHEMA = "publishable-mem0-v5-runtime-attestation.v3"
_HOST_ATTESTATION_DOMAIN = b"publishable-mem0-v5/host-runtime-attestation/v1\0"
_COMPOSE_SHA256 = "93a9f46a4a0ac1ee6c37a16e60bf30bfbd5dd58d4b2ef01fc474d2cd7a01809c"
_ADAPTER_IMAGE = f"sha256:{'a' * 64}"
_QDRANT_IMAGE = f"sha256:{'b' * 64}"
_RUNTIME_MANIFEST = "789018b5b15a1299252895babdc550c3d5322c54a1d9c82656f93d31423a0850"
_RUNTIME_ENTRYPOINT = "83db85671ec5da675706c903e5b8ed1ae0cb307014d7c10a10be34f1700762fd"
_NODE_EXECUTABLE = "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"
_CODEX_EXECUTABLE = hashlib.sha256(b"reviewed-codex-executable").hexdigest()
_RUNTIME_SOURCE = "6c0bfa587ea52cea8b3cfff75980836ffa157efcc3f074ce97faa55d9bed4695"
_RUNTIME_ROUTE = "aaff3d27c7ca1b964a86355622e87b2bbd7841722dbcff782292ea02e1fa0935"
_SUBSCRIPTION_BINDING = "9636a031655ad158b5864217ca400ee6d6d294fdd799757296f38f7c926786fa"
_EXTRACTION_SYSTEM = "ad19187a37813ef77ee156e714c0650e6ec749e0264bdc07d499bc9b24115155"
_EXTRACTION_FORMAT = "f45055c9f24f763294c0c96c3d71cd3ae494d96376596f34a6203cf171f9a516"
_EXTRACTION_SCHEMA = "17c002c4bc8c4aa9d9131253ef0763fd5769c039985c65885e5877fda443120b"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _key(label: str) -> bytes:
    return hashlib.sha256(f"private-key:{label}".encode()).digest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _json_sha(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _write_private(path: Path, value: object) -> None:
    _private_directory(path.parent)
    path.write_bytes(_json_bytes(value))
    path.chmod(0o600)


def _write_host_attestation(directory: Path, payload: dict[str, object]) -> Path:
    raw = _json_bytes(payload)
    digest = hashlib.sha256(raw).hexdigest()
    path = directory / f"runtime-attestation-{digest}.json"
    path.write_bytes(raw + b"\n")
    path.chmod(0o600)
    return path


def _authenticate_host_attestation(
    payload: dict[str, object],
    authentication_key: bytes,
) -> dict[str, object]:
    unsigned = copy.deepcopy(payload)
    unsigned.pop("attestation_hmac_sha256", None)
    return {
        **unsigned,
        "attestation_hmac_sha256": hmac.new(
            authentication_key,
            _HOST_ATTESTATION_DOMAIN + _json_bytes(unsigned),
            hashlib.sha256,
        ).hexdigest(),
    }


@dataclass(slots=True)
class _Lane:
    config: dict[str, object]
    secrets: dict[str, object]
    inputs: PublishableRunProviderInputs
    attestation_directory: Path
    attestation_path: Path
    attestation_payload: dict[str, object]
    control_paths: tuple[Path, Path, Path]
    runtime_authority_paths: tuple[Path, Path, Path]
    readiness: BridgeFleetReadinessReceipt
    runtime_pin: Path
    runtime_root_secret: bytes

    def provider_inputs(
        self,
        *,
        config: dict[str, object] | None = None,
        secrets: dict[str, object] | None = None,
    ) -> PublishableRunProviderInputs:
        return PublishableRunProviderInputs(
            state_root=self.inputs.state_root,
            adapter_config_json=_json_bytes(config or self.config),
            adapter_secrets_json=_json_bytes(secrets or self.secrets),
        )

    def replace_attestation(
        self,
        payload: dict[str, object],
        *,
        authenticate: bool = True,
    ) -> None:
        for path in self.attestation_directory.iterdir():
            path.unlink()
        if authenticate:
            payload = _authenticate_host_attestation(payload, self.runtime_root_secret)
        self.attestation_payload = payload
        self.attestation_path = _write_host_attestation(
            self.attestation_directory,
            payload,
        )


def _build_lane(
    tmp_path: Path,
    *,
    requested_mode: str = "create",
    retained_launch_mode: str = "create",
) -> _Lane:
    project = "publishable-test-lane-a"
    lane_root = _private_directory(tmp_path / project)
    state_root = _private_directory(tmp_path / "provider-state")
    attestation_directory = _private_directory(lane_root / "runtime-attestations")
    fleet_state = _private_directory(lane_root / "fleet-state")
    input_root = _private_directory(lane_root / "sealed-input")
    authority_root = tmp_path / "authority"
    authority_root.mkdir(mode=0o755)
    official_root = authority_root / "official-cases"
    official_root.mkdir(mode=0o755)
    runtime_pin = authority_root / "runtime-pin.json"
    runtime_pin.write_bytes(_RUNTIME_PIN_SOURCE.read_bytes())
    runtime_pin.chmod(0o444)
    runtime_pin_raw = runtime_pin.read_bytes()
    runtime_pin_payload = json.loads(runtime_pin_raw)

    accounts = ("publishable-account-a", "publishable-account-b", "publishable-account-c")
    bridge_ids = ("publishable-bridge-a", "publishable-bridge-b", "publishable-bridge-c")
    account_bindings = tuple(_sha(f"account-binding-{index}") for index in range(3))
    launcher_keys = tuple(_key(f"launcher-{index}") for index in range(3))
    attestation_secrets = tuple(_key(f"bridge-attestation-{index}") for index in range(3))
    bearers = tuple(
        f"publishable-bearer-{index}-{_sha(f'bearer-{index}')[:16]}" for index in range(3)
    )
    bridges = tuple(
        BridgeAuthority(
            bridge_id=bridge_ids[index],
            origin=f"http://127.0.0.1:{8891 + index}",
            account_binding_hmac_sha256=account_bindings[index],
            public_model="gpt-5.6-sol",
            base_instructions_sha256=SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
        )
        for index in range(3)
    )
    pool = BridgePoolAuthority(pool_id=f"{project}-runtime-pool", bridges=bridges)

    launches: list[BridgeLaunchReceipt] = []
    controls: list[Path] = []
    runtime_authority_paths: list[Path] = []
    now_ms = time.time_ns() // 1_000_000
    for index, (account, bridge, launcher_key) in enumerate(
        zip(accounts, bridges, launcher_keys, strict=True)
    ):
        runtime = RuntimeProcessAuthority(
            account_name=account,
            bridge_authority=bridge,
            state_root_identity_sha256=_sha(f"state-root-{index}"),
            auth_root_identity_sha256=_sha(f"auth-root-{index}"),
            private_material_binding_hmac_sha256=_sha(f"private-material-{index}"),
            runtime_artifact_manifest_sha256=_RUNTIME_MANIFEST,
            runtime_entrypoint_sha256=_RUNTIME_ENTRYPOINT,
            node_executable_sha256=_NODE_EXECUTABLE,
            codex_executable_sha256=_CODEX_EXECUTABLE,
        )
        process = ProcessIdentity(
            pid=41_000 + index,
            start_ticks=900_000 + index,
            pgid=41_000 + index,
            boot_id=f"00000000-0000-4000-8000-{index + 1:012d}",
        )
        pending = PendingLaunchMetadata.issue(
            account_name=account,
            bridge_id=bridge.bridge_id,
            generation=7,
            launch_id=_sha(f"launch-{index}"),
            mode=retained_launch_mode,
            process=process,
            runtime_authority_sha256=runtime.commitment_sha256,
            started_at_unix_ms=now_ms - 20,
            key=launcher_key,
        )
        launch = BridgeLaunchReceipt.issue(
            pending=pending,
            health=RuntimeHealthEvidence(
                response_body_sha256=_sha(f"health-{index}"),
                observed_at_unix_ms=now_ms - 10,
            ),
            bridge_authority_sha256=bridge.commitment_sha256,
            runtime_authority_sha256=runtime.commitment_sha256,
            ready_at_unix_ms=now_ms - 5,
            key=launcher_key,
        )
        account_root = _private_directory(fleet_state / account)
        control_path = account_root / ".controller-readiness.json"
        readiness_payload = launch.public_payload()
        _write_private(
            control_path,
            {
                "account_index": index,
                "account_name": account,
                "anchor_namespace_sha256": _sha(f"anchor-namespace-{index}"),
                "bridge_id": bridge.bridge_id,
                "bridge_port": 8891 + index,
                "bridge_readiness": readiness_payload,
                "bridge_readiness_sha256": _json_sha(readiness_payload),
                "controller_pid": 51_000 + index,
                "project_name": project,
                "schema_version": _CONTROL_SCHEMA,
            },
        )
        runtime_path = (
            account_root
            / "current"
            / ".infinity-context-bridge-launcher"
            / "runtime-authority.json"
        )
        _write_private(runtime_path, runtime.public_payload())
        controls.append(control_path)
        runtime_authority_paths.append(runtime_path)
        launches.append(launch)

    readiness = BridgeFleetReadinessReceipt(pool=pool, launches=tuple(launches))
    runtime_root_secret = b"provider-free-runtime-attestation-root-v1"
    output_key = _key("output-cipher")
    secrets: dict[str, object] = {
        "bridge_journal_authentication_key_hex": _key("bridge-journal").hex(),
        "bridges": [
            {
                "attestation_secret_hex": attestation_secrets[index].hex(),
                "authorization_bearer": bearers[index],
                "bridge_id": bridge_ids[index],
                "launcher_receipt_key_hex": launcher_keys[index].hex(),
            }
            for index in range(3)
        ],
        "extraction_authentication_keys_hex": [
            _key("extraction-locomo").hex(),
            _key("extraction-longmemeval").hex(),
        ],
        "output_cipher_key_hex": output_key.hex(),
        "retrieval_authentication_key_hex": _key("retrieval").hex(),
        "runtime_attestation_root_secret_hex": runtime_root_secret.hex(),
        "schema_version": "publishable-mem0-infinity-run-provider-secrets.v2",
    }
    endpoint_port = 29_192
    endpoint = f"http://127.0.0.1:{endpoint_port}"
    source = runtime_pin_payload["source_a"]
    suite_id = "publishable-test-suite-2040"
    config: dict[str, object] = {
        "extraction": {
            "locomo_terminal_path": str(input_root / "locomo-terminal.json"),
            "longmemeval_terminal_path": str(input_root / "longmemeval-terminal.json"),
        },
        "fleet": {
            "bridges": [
                {
                    "account_binding_hmac_sha256": account_bindings[index],
                    "account_name": accounts[index],
                    "bridge_id": bridge_ids[index],
                    "origin": f"http://127.0.0.1:{8891 + index}",
                    "readiness_receipt_path": str(controls[index]),
                }
                for index in range(3)
            ],
            "pool_id": pool.pool_id,
        },
        "official_cases": {
            "locomo": {
                "path": str(official_root / "locomo.json"),
                "sha256": _sha("locomo"),
            },
            "longmemeval": {
                "path": str(official_root / "longmemeval.json"),
                "sha256": _sha("longmemeval"),
            },
        },
        "retrieval": {
            "authority_root_sha256": _sha("retrieval-authority"),
            "database_path": str(input_root / "retrieval.sqlite3"),
        },
        "runtime": {
            "attestation": {
                "endpoint_timeout_seconds": 3,
                "lane_project_name": project,
                "maximum_age_seconds": 300,
                "public_endpoint": endpoint,
                "runtime_attestation_directory": str(attestation_directory),
            },
            "authority": {
                "adapter_image_id": _ADAPTER_IMAGE,
                "codex_executable_sha256": _CODEX_EXECUTABLE,
                "extraction_response_format_sha256": _EXTRACTION_FORMAT,
                "extraction_response_schema_sha256": _EXTRACTION_SCHEMA,
                "extraction_system_prompt_sha256": _EXTRACTION_SYSTEM,
                "node_executable_sha256": _NODE_EXECUTABLE,
                "runtime_artifact_manifest_sha256": _RUNTIME_MANIFEST,
                "runtime_entrypoint_sha256": _RUNTIME_ENTRYPOINT,
                "runtime_pin_path": str(runtime_pin),
                "runtime_pin_sha256": hashlib.sha256(runtime_pin_raw).hexdigest(),
                "runtime_route_binding_sha256": _RUNTIME_ROUTE,
                "runtime_source_sha256": _RUNTIME_SOURCE,
                "source_manifest_sha256": source["manifest_sha256"],
                "subscription_runtime_binding_commitment_sha256": _SUBSCRIPTION_BINDING,
            },
            "bridge_connect_timeout_seconds": 3,
            "bridge_read_timeout_seconds": 60,
            "bridge_write_timeout_seconds": 30,
            "lease_duration_ms": 120_000,
            "maximum_bridge_request_bytes": 4 * 1024 * 1024,
            "maximum_ciphertext_bytes": 8 * 1024 * 1024,
            "output_cipher_key_id": "publishable-test-output-key-v1",
        },
        "schema_version": "publishable-mem0-infinity-run-provider.v2",
        "suite": {
            "dispatch_deadline_unix_ms": now_ms + 86_400_000,
            "dispatch_not_before_unix_ms": now_ms - 60_000,
            "infinity_base_url": "http://127.0.0.1:29292",
            "locomo_run_id": "publishable-test-locomo",
            "longmemeval_run_id": "publishable-test-longmemeval",
            "mem0_base_url": endpoint,
            "publication_bundle_sha256": _sha("publication-bundle"),
            "source_commit_sha256": hashlib.sha256(source["commit_sha1"].encode()).hexdigest(),
            "suite_id": suite_id,
        },
    }
    primary_cross_wire = (
        hashlib.sha256(bearers[0].encode()).hexdigest(),
        hashlib.sha256(attestation_secrets[0]).hexdigest(),
        hashlib.sha256(account_bindings[0].encode()).hexdigest(),
        hashlib.sha256(SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256.encode()).hexdigest(),
        hashlib.sha256(b"http://127.0.0.1:8891").hexdigest(),
    )
    host_fleet = {
        "bridges": [
            {
                "account_name": launch.pending.account_name,
                "bridge_id": bridge.bridge_id,
                "controller_pid": 51_000 + index,
                "generation": launch.pending.generation,
                "launch_mode": launch.pending.mode,
                "process": launch.pending.process.public_payload(),
                "readiness_receipt_sha256": launch.commitment_sha256,
                "runtime_authority_sha256": launch.runtime_authority_sha256,
            }
            for index, (bridge, launch) in enumerate(zip(bridges, launches, strict=True))
        ],
        "fleet_readiness_sha256": _json_sha(readiness.public_payload()),
        "pool_authority_sha256": pool.commitment_sha256,
        "requested_mode": requested_mode,
    }
    services = {
        name: {
            "bind_mounts_sha256": _sha(f"mounts-{name}"),
            "container_id": _sha(f"container-{name}"),
            "image_id": _QDRANT_IMAGE if name == "publishable-qdrant" else _ADAPTER_IMAGE,
            "pid": 61_000 + index,
        }
        for index, name in enumerate(
            (
                "publishable-adapter",
                "publishable-bridge-a",
                "publishable-bridge-b",
                "publishable-bridge-c",
                "publishable-qdrant",
                "publishable-relay-anchor",
            )
        )
    }
    host_attestation: dict[str, object] = {
        "account_i_fence_commitment_sha256": _sha("account-i-fence"),
        "adapter_image_id": _ADAPTER_IMAGE,
        "anchor_container_inventory_sha256": _sha("anchor-inventory"),
        "anchor_netns": {"device": 1, "inode": 2},
        "anchor_pidns": {"device": 1, "inode": 3},
        "bridge_ports": [8891, 8892, 8893],
        "compose_sha256": _COMPOSE_SHA256,
        "deployment_inputs_sha256": _sha("deployment-inputs"),
        "fleet": host_fleet,
        "host_exposure": {
            "container_port": 19_191,
            "host_ip": "127.0.0.1",
            "host_port": endpoint_port,
            "relayed_adapter_port": 19_091,
        },
        "loopback_bindings_sha256": _sha("loopback-bindings"),
        "observed_at_unix_ns": time.time_ns(),
        "project_name": project,
        "qdrant_image_id": _QDRANT_IMAGE,
        "qdrant_ports": {"grpc": 6335, "http": 6334},
        "schema_version": _HOST_ATTESTATION_SCHEMA,
        "secret_cross_wire_sha256": hashlib.sha256(
            "".join(primary_cross_wire).encode("ascii")
        ).hexdigest(),
        "services": services,
    }
    host_attestation = _authenticate_host_attestation(
        host_attestation,
        runtime_root_secret,
    )
    attestation_path = _write_host_attestation(attestation_directory, host_attestation)
    inputs = PublishableRunProviderInputs(
        state_root=state_root,
        adapter_config_json=_json_bytes(config),
        adapter_secrets_json=_json_bytes(secrets),
    )
    return _Lane(
        config=config,
        secrets=secrets,
        inputs=inputs,
        attestation_directory=attestation_directory,
        attestation_path=attestation_path,
        attestation_payload=host_attestation,
        control_paths=tuple(controls),
        runtime_authority_paths=tuple(runtime_authority_paths),
        readiness=readiness,
        runtime_pin=runtime_pin,
        runtime_root_secret=runtime_root_secret,
    )


def _install_authentic_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    lane: _Lane,
    *,
    mismatch_target: bool = False,
) -> list[dict[str, object]]:
    pin = json.loads(lane.runtime_pin.read_bytes())
    source = pin["source_a"]
    phase = pin["phase_c"]
    runtime = lane.config["runtime"]
    assert isinstance(runtime, dict)
    authority_config = runtime["authority"]
    assert isinstance(authority_config, dict)
    fleet = lane.config["fleet"]
    assert isinstance(fleet, dict)
    bridges = fleet["bridges"]
    assert isinstance(bridges, list)
    primary = bridges[0]
    assert isinstance(primary, dict)
    del source, phase
    expected = managed_attestation.expected_managed_mem0_v5_runtime_authority_from_pin(
        runtime_pin_file=lane.runtime_pin,
        runtime_pin_sha256=authority_config["runtime_pin_sha256"],
        runtime_source_sha256=authority_config["runtime_source_sha256"],
        runtime_route_binding_sha256=authority_config["runtime_route_binding_sha256"],
        subscription_runtime_binding_commitment_sha256=authority_config[
            "subscription_runtime_binding_commitment_sha256"
        ],
        expected_account_binding_hmac_sha256=primary["account_binding_hmac_sha256"],
        expected_base_instructions_sha256=SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
        expected_extraction_system_prompt_sha256=authority_config[
            "extraction_system_prompt_sha256"
        ],
        expected_extraction_response_format_sha256=authority_config[
            "extraction_response_format_sha256"
        ],
        expected_extraction_response_schema_sha256=authority_config[
            "extraction_response_schema_sha256"
        ],
        expected_requested_output_tokens=4096,
    )
    calls: list[dict[str, object]] = []

    def post_runtime_attestation(
        *,
        endpoint: str,
        timeout_seconds: float,
        root_secret: bytes,
        request: dict[str, object],
    ) -> dict[str, object]:
        calls.append(copy.deepcopy(request))
        assert endpoint == "http://127.0.0.1:29192"
        assert timeout_seconds == 3
        assert root_secret == lane.runtime_root_secret
        actual_request = copy.deepcopy(request)
        if mismatch_target:
            actual_request["target_origin_sha256"] = _sha("foreign-endpoint")
        now = int(time.time())
        implementation = {
            "schema_version": "mem0-oss-adapter-v5.implementation-binding.v1",
            "route_contract_sha256": managed_attestation._ROUTE_SHA256,
            **expected.public_payload(),
        }
        unsigned = {
            "schema_version": managed_attestation.RESPONSE_SCHEMA,
            "service": "mem0-oss-adapter-v5",
            "route_contract_sha256": managed_attestation._ROUTE_SHA256,
            **expected.public_payload(),
            "target_origin_sha256": actual_request["target_origin_sha256"],
            "run_id_sha256": actual_request["run_id_sha256"],
            "probe_nonce_sha256": actual_request["probe_nonce_sha256"],
            "implementation_binding_sha256": _json_sha(implementation),
            "issued_at_unix": now,
            "expires_at_unix": now + int(actual_request["validity_seconds"]),
            "provider_calls": 0,
        }
        signing_key = hmac.new(
            lane.runtime_root_secret,
            managed_attestation._RESPONSE_KEY_DOMAIN,
            hashlib.sha256,
        ).digest()
        return {
            **unsigned,
            "attestation_hmac_sha256": hmac.new(
                signing_key,
                managed_attestation._RESPONSE_DOMAIN + _json_bytes(unsigned),
                hashlib.sha256,
            ).hexdigest(),
        }

    monkeypatch.setattr(
        run_provider_preflight,
        "_post_runtime_attestation",
        post_runtime_attestation,
    )
    return calls


def _install_downstream_traps(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    reached: list[str] = []

    def trap(label: str):
        def fail(*_args: object, **_kwargs: object) -> object:
            reached.append(label)
            raise AssertionError(f"downstream opened before preflight: {label}")

        return fail

    monkeypatch.setattr(run_provider, "open_sealed_extraction_suite", trap("extraction"))
    monkeypatch.setattr(run_provider._OfficialCaseProjection, "load", trap("datasets"))
    monkeypatch.setattr(run_provider, "_suite", trap("suite"))
    monkeypatch.setattr(run_provider, "_ProductionRunSession", trap("session"))
    return reached


def test_real_parser_and_factory_open_complete_preflight_before_downstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _build_lane(tmp_path)
    parsed, secrets = parse_run_provider_inputs(lane.inputs)
    assert parsed.runtime_attestation.directory == lane.attestation_directory
    assert (
        parsed.runtime_authority.source_manifest_sha256
        == (json.loads(lane.runtime_pin.read_bytes())["source_a"]["manifest_sha256"])
    )
    assert len(secrets.bridges) == 3
    endpoint_calls = _install_authentic_endpoint(monkeypatch, lane)

    downstream: list[str] = []
    extraction = object()
    projection = object()
    suite = object()

    def open_extraction(*_args: object, **_kwargs: object) -> object:
        downstream.append("extraction")
        return extraction

    def load_projection(*_args: object, **_kwargs: object) -> object:
        downstream.append("datasets")
        return projection

    def build_suite(*_args: object, **_kwargs: object) -> object:
        downstream.append("suite")
        return suite

    monkeypatch.setattr(run_provider, "open_sealed_extraction_suite", open_extraction)
    monkeypatch.setattr(run_provider._OfficialCaseProjection, "load", load_projection)
    monkeypatch.setattr(run_provider, "_suite", build_suite)
    session = Mem0InfinityPublishableRunDependencyFactory().open_session(
        inputs=lane.inputs,
        mode=PublishableProductionOpenMode.CREATE,
    )
    assert session.suite is suite
    assert session.readiness == lane.readiness
    assert len(endpoint_calls) == 1
    assert downstream == ["extraction", "datasets", "suite"]
    session.close()


def test_reopen_attestation_accepts_retained_create_launches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _build_lane(
        tmp_path,
        requested_mode="reopen",
        retained_launch_mode="create",
    )
    _install_authentic_endpoint(monkeypatch, lane)
    config, secrets = parse_run_provider_inputs(lane.inputs)
    readiness = run_provider_preflight.preflight_run_provider(
        config=config,
        secrets=secrets,
        mode=PublishableProductionOpenMode.RESUME,
    )
    assert tuple(item.pending.mode for item in readiness.launches) == (
        "create",
        "create",
        "create",
    )
    assert lane.attestation_payload["fleet"]["requested_mode"] == "reopen"


def test_producer_receipt_is_consumed_by_the_real_provider_verifier(tmp_path: Path) -> None:
    lane = _build_lane(tmp_path)
    payload = lane.attestation_payload
    fleet_payload = payload["fleet"]
    services_payload = payload["services"]
    assert isinstance(fleet_payload, dict)
    assert isinstance(services_payload, dict)
    bridges = tuple(
        BridgeRuntimeIdentity(**bridge)
        for bridge in fleet_payload["bridges"]
        if isinstance(bridge, dict)
    )
    fleet = FleetRuntimeEvidence(
        requested_mode=str(fleet_payload["requested_mode"]),
        pool_authority_sha256=str(fleet_payload["pool_authority_sha256"]),
        fleet_readiness_sha256=str(fleet_payload["fleet_readiness_sha256"]),
        bridges=bridges,  # type: ignore[arg-type]
    )
    services = {
        name: host_runtime_attestation.ServiceRuntimeIdentity(**identity)
        for name, identity in services_payload.items()
        if isinstance(identity, dict)
    }
    attestation = host_runtime_attestation.LaneRuntimeAttestation(
        project_name=str(payload["project_name"]),
        compose_sha256=str(payload["compose_sha256"]),
        observed_at_unix_ns=int(payload["observed_at_unix_ns"]),
        adapter_image_id=str(payload["adapter_image_id"]),
        qdrant_image_id=str(payload["qdrant_image_id"]),
        anchor_netns=host_runtime_attestation.NamespaceIdentity(**payload["anchor_netns"]),
        anchor_pidns=host_runtime_attestation.NamespaceIdentity(**payload["anchor_pidns"]),
        account_i_fence_commitment_sha256=str(payload["account_i_fence_commitment_sha256"]),
        secret_cross_wire_sha256=str(payload["secret_cross_wire_sha256"]),
        deployment_inputs_sha256=str(payload["deployment_inputs_sha256"]),
        anchor_container_inventory_sha256=str(payload["anchor_container_inventory_sha256"]),
        loopback_bindings_sha256=str(payload["loopback_bindings_sha256"]),
        fleet=fleet,
        services=services,
        host_adapter_port=int(payload["host_exposure"]["host_port"]),
    )
    lane.attestation_path.unlink()
    receipt = host_runtime_attestation.write_runtime_attestation(
        attestation,
        lane.attestation_directory,
        authentication_key=lane.runtime_root_secret,
    )

    assert run_provider_preflight._read_lane_attestation(
        receipt.path,
        authentication_key=lane.runtime_root_secret,
    ) == json.loads(receipt.path.read_bytes())


@pytest.mark.parametrize(
    "attack",
    (
        "missing_attestation",
        "tampered_attestation",
        "stale_attestation",
        "cross_mode_attestation",
        "divergent_attestation",
        "recomputed_filename_invalid_host_hmac",
        "tampered_launch_hmac",
        "tampered_runtime_authority",
        "tampered_runtime_pin",
    ),
)
def test_hostile_runtime_evidence_fails_before_any_downstream_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    lane = _build_lane(tmp_path)
    endpoint_calls = _install_authentic_endpoint(monkeypatch, lane)
    if attack == "missing_attestation":
        lane.attestation_path.unlink()
    elif attack == "tampered_attestation":
        lane.attestation_path.write_bytes(lane.attestation_path.read_bytes() + b" ")
    elif attack == "stale_attestation":
        stale = copy.deepcopy(lane.attestation_payload)
        stale["observed_at_unix_ns"] = time.time_ns() - 301_000_000_000
        lane.replace_attestation(stale)
    elif attack == "cross_mode_attestation":
        foreign = copy.deepcopy(lane.attestation_payload)
        foreign["fleet"]["requested_mode"] = "reopen"
        lane.replace_attestation(foreign)
    elif attack == "divergent_attestation":
        divergent = copy.deepcopy(lane.attestation_payload)
        divergent["observed_at_unix_ns"] = time.time_ns() + 1
        divergent["deployment_inputs_sha256"] = _sha("foreign-deployment-inputs")
        _write_host_attestation(
            lane.attestation_directory,
            _authenticate_host_attestation(divergent, lane.runtime_root_secret),
        )
    elif attack == "recomputed_filename_invalid_host_hmac":
        invalid = copy.deepcopy(lane.attestation_payload)
        invalid["deployment_inputs_sha256"] = _sha("tampered-deployment-inputs")
        lane.replace_attestation(invalid, authenticate=False)
    elif attack == "tampered_launch_hmac":
        control = json.loads(lane.control_paths[0].read_bytes())
        control["bridge_readiness"]["receipt_hmac_sha256"] = "0" * 64
        control["bridge_readiness_sha256"] = _json_sha(control["bridge_readiness"])
        _write_private(lane.control_paths[0], control)
    elif attack == "tampered_runtime_authority":
        runtime = json.loads(lane.runtime_authority_paths[0].read_bytes())
        runtime["state_root_identity_sha256"] = _sha("foreign-state-root")
        _write_private(lane.runtime_authority_paths[0], runtime)
    elif attack == "tampered_runtime_pin":
        lane.runtime_pin.chmod(0o644)
        lane.runtime_pin.write_bytes(lane.runtime_pin.read_bytes() + b"\n")
        lane.runtime_pin.chmod(0o444)
    else:
        raise AssertionError(attack)
    reached = _install_downstream_traps(monkeypatch)

    with pytest.raises(PublishableRunError):
        Mem0InfinityPublishableRunDependencyFactory().open_session(
            inputs=lane.inputs,
            mode=PublishableProductionOpenMode.CREATE,
        )

    assert reached == []
    assert endpoint_calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source_manifest_sha256", "f" * 64),
        ("suite_source_commit_sha256", "e" * 64),
    ),
)
def test_reviewed_source_mismatch_fails_before_endpoint_or_downstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    lane = _build_lane(tmp_path)
    config = copy.deepcopy(lane.config)
    if field == "source_manifest_sha256":
        config["runtime"]["authority"][field] = value
    else:
        config["suite"]["source_commit_sha256"] = value
    inputs = lane.provider_inputs(config=config)
    endpoint_calls = _install_authentic_endpoint(monkeypatch, lane)
    reached = _install_downstream_traps(monkeypatch)

    with pytest.raises(PublishableRunError, match="reviewed_source_mismatch"):
        Mem0InfinityPublishableRunDependencyFactory().open_session(
            inputs=inputs,
            mode=PublishableProductionOpenMode.CREATE,
        )

    assert endpoint_calls == []
    assert reached == []


def test_signed_endpoint_response_for_foreign_target_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _build_lane(tmp_path)
    endpoint_calls = _install_authentic_endpoint(monkeypatch, lane, mismatch_target=True)
    reached = _install_downstream_traps(monkeypatch)

    with pytest.raises(PublishableRunError):
        Mem0InfinityPublishableRunDependencyFactory().open_session(
            inputs=lane.inputs,
            mode=PublishableProductionOpenMode.CREATE,
        )

    assert len(endpoint_calls) == 1
    assert reached == []


def test_cross_lane_and_endpoint_config_are_rejected_by_real_parser(
    tmp_path: Path,
) -> None:
    lane = _build_lane(tmp_path)
    cross_lane = copy.deepcopy(lane.config)
    account = cross_lane["fleet"]["bridges"][0]["account_name"]
    cross_lane["fleet"]["bridges"][0]["readiness_receipt_path"] = str(
        tmp_path / "foreign-lane" / "fleet-state" / account / ".controller-readiness.json"
    )
    with pytest.raises(PublishableRunError, match="config_cross_wire"):
        parse_run_provider_inputs(lane.provider_inputs(config=cross_lane))

    endpoint = copy.deepcopy(lane.config)
    endpoint["suite"]["mem0_base_url"] = "http://127.0.0.1:29193"
    with pytest.raises(PublishableRunError, match="config_cross_wire"):
        parse_run_provider_inputs(lane.provider_inputs(config=endpoint))


@pytest.mark.parametrize(
    "infinity_base_url",
    (
        "http://reviewer:private@127.0.0.1:29292",
        "http://192.0.2.10:29292",
        "http://127.0.0.1:29192",
    ),
)
def test_real_parser_rejects_unsafe_or_cross_lane_infinity_endpoint(
    tmp_path: Path,
    infinity_base_url: str,
) -> None:
    lane = _build_lane(tmp_path)
    baseline, _ = parse_run_provider_inputs(lane.inputs)
    assert baseline.suite.infinity_base_url == "http://127.0.0.1:29292"

    hostile = copy.deepcopy(lane.config)
    hostile["suite"]["infinity_base_url"] = infinity_base_url
    with pytest.raises(PublishableRunError, match="config_"):
        parse_run_provider_inputs(lane.provider_inputs(config=hostile))


def test_shallow_or_extra_provider_config_never_reaches_preflight(tmp_path: Path) -> None:
    lane = _build_lane(tmp_path)
    shallow = {
        "schema_version": "publishable-mem0-infinity-run-provider.v2",
        "runtime_attestation_directory": str(lane.attestation_directory),
    }
    with pytest.raises(PublishableRunError, match="config_invalid"):
        parse_run_provider_inputs(lane.provider_inputs(config=shallow))

    extra = copy.deepcopy(lane.config)
    extra["expected_total_call_count"] = 138_386
    with pytest.raises(PublishableRunError, match="config_invalid"):
        parse_run_provider_inputs(lane.provider_inputs(config=extra))


def test_private_material_never_appears_in_provider_repr(tmp_path: Path) -> None:
    lane = _build_lane(tmp_path)
    config, secrets = parse_run_provider_inputs(lane.inputs)
    rendered = f"{lane.inputs!r}\n{config!r}\n{secrets!r}"
    for private in (
        lane.runtime_root_secret.hex(),
        lane.secrets["output_cipher_key_hex"],
        lane.secrets["bridges"][0]["authorization_bearer"],
    ):
        assert private not in rendered


def test_parser_rejects_runtime_root_secret_the_deployment_cannot_load(tmp_path: Path) -> None:
    lane = _build_lane(tmp_path)
    secrets = copy.deepcopy(lane.secrets)
    secrets["runtime_attestation_root_secret_hex"] = "ff" * 32

    with pytest.raises(PublishableRunError, match="secrets_invalid"):
        parse_run_provider_inputs(lane.provider_inputs(secrets=secrets))

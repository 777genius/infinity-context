"""Provider-free runtime preflight for the installed publishable run provider."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex
from typing import final

from infinity_context_server.features.subscription_runtime_bridge import (
    BridgeAuthority,
    BridgePoolAuthority,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    BridgeFleetReadinessReceipt,
    BridgeLaunchReceipt,
    RuntimeProcessAuthority,
)
from infinity_context_server.features.subscription_runtime_bridge.process_files import (
    read_private_json,
    verify_private_directory,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_runtime_attestation import (
    _AUTH_DOMAIN,
    _IDEMPOTENCY_DOMAIN,
    REQUEST_SCHEMA,
    _verify_and_issue,
    expected_managed_mem0_v5_runtime_authority_from_pin,
    managed_mem0_v5_runtime_validation_is_publishable,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
)
from infinity_context_server.memory_comparison_target_identity import (
    mem0_runtime_target_identity_sha256,
)
from infinity_context_server.publishable_durable_scheduler import (
    scheduler_subscription_bridge_adapter,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
)

from .config import COMPOSE_SHA256
from .run_provider_config import RunProviderConfig, RunProviderSecrets

_ATTESTATION_SCHEMA = "publishable-mem0-v5-runtime-attestation.v3"
_ATTESTATION_PREFIX = "runtime-attestation-"
_HOST_ATTESTATION_DOMAIN = b"publishable-mem0-v5/host-runtime-attestation/v1\0"
_CONTROL_SCHEMA = "publishable-mem0-v5-bridge-controller-readiness.v2"
_MAX_ATTESTATION_BYTES = 256 * 1024
_MAX_READINESS_BYTES = 256 * 1024
_RUNTIME_AUTHORITY_RELATIVE = Path(
    "current/.infinity-context-bridge-launcher/runtime-authority.json"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ATTESTATION_NAME = re.compile(r"runtime-attestation-([0-9a-f]{64})\.json\Z")
_SERVICES = frozenset(
    {
        "publishable-adapter",
        "publishable-bridge-a",
        "publishable-bridge-b",
        "publishable-bridge-c",
        "publishable-qdrant",
        "publishable-relay-anchor",
    }
)


@final
@dataclass(frozen=True, slots=True)
class _ControlSnapshot:
    path: Path
    payload: dict[str, object]
    controller_pid: int


@final
@dataclass(frozen=True, slots=True)
class _VerifiedFleet:
    readiness: BridgeFleetReadinessReceipt
    controls: tuple[_ControlSnapshot, _ControlSnapshot, _ControlSnapshot]


def preflight_run_provider(
    *,
    config: RunProviderConfig,
    secrets: RunProviderSecrets,
    mode: object,
) -> BridgeFleetReadinessReceipt:
    """Bind current lane, fleet, source, runtime, and endpoint before session open."""

    expected_mode = _expected_fleet_mode(
        mode,
        required_fleet_mode=config.runtime_attestation.required_fleet_mode,
    )
    try:
        verified = _verified_fleet(config, secrets)
        _verify_runtime_authorities(config, verified)
        attestation_paths = _verify_lane_attestation(
            config,
            secrets,
            verified,
            expected_mode=expected_mode,
        )
        _verify_endpoint_runtime_authority(config, secrets)
        _require_controls_unchanged(verified.controls)
        _require_attestation_directory_unchanged(
            config.runtime_attestation.directory,
            attestation_paths,
            authentication_key=secrets.runtime_attestation_root_secret,
        )
        return verified.readiness
    except PublishableRunError:
        raise
    except Exception:
        _fail("publishable_run_provider_runtime_preflight_failed")


def _expected_fleet_mode(mode: object, *, required_fleet_mode: str) -> str:
    value = getattr(mode, "value", None)
    if value not in {"create", "resume"} or required_fleet_mode != "reopen":
        _fail("publishable_run_provider_mode_invalid")
    return required_fleet_mode


def _verified_fleet(
    config: RunProviderConfig,
    secrets: RunProviderSecrets,
) -> _VerifiedFleet:
    try:
        pool = BridgePoolAuthority(
            pool_id=config.fleet_pool_id,
            bridges=tuple(
                BridgeAuthority(
                    bridge_id=item.bridge_id,
                    origin=item.origin,
                    account_binding_hmac_sha256=item.account_binding_hmac_sha256,
                    public_model="gpt-5.6-sol",
                    base_instructions_sha256=SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
                )
                for item in config.fleet_bridges
            ),
        )
        launches: list[BridgeLaunchReceipt] = []
        controls: list[_ControlSnapshot] = []
        keys = {item.bridge_id: item for item in secrets.bridges}
        for index, (item, port) in enumerate(
            zip(config.fleet_bridges, (8891, 8892, 8893), strict=True)
        ):
            _require_canonical_existing(item.readiness_receipt_path)
            control = read_private_json(
                item.readiness_receipt_path,
                maximum_bytes=_MAX_READINESS_BYTES,
            )
            readiness_payload = _control_readiness(
                control,
                config=config,
                bridge=item,
                account_index=index,
                bridge_port=port,
            )
            launch = BridgeLaunchReceipt.from_payload(readiness_payload)
            launch.verify(keys[item.bridge_id].launcher_receipt_key)
            launches.append(launch)
            controls.append(
                _ControlSnapshot(
                    path=item.readiness_receipt_path,
                    payload=control,
                    controller_pid=int(control["controller_pid"]),
                )
            )
        readiness = BridgeFleetReadinessReceipt(pool=pool, launches=tuple(launches))
        bridge_keys = _BridgeReceiptKeys(secrets)
        scheduler_subscription_bridge_adapter.verify_fleet_launch_receipts(
            readiness,
            bridge_keys,
        )
        return _VerifiedFleet(
            readiness=readiness,
            controls=tuple(controls),
        )
    except PublishableRunError:
        raise
    except Exception:
        _fail("publishable_run_provider_fleet_unverified")


def _control_readiness(
    control: dict[str, object],
    *,
    config: RunProviderConfig,
    bridge: object,
    account_index: int,
    bridge_port: int,
) -> dict[str, object]:
    expected_keys = {
        "account_index",
        "account_name",
        "anchor_namespace_sha256",
        "bridge_id",
        "bridge_port",
        "bridge_readiness",
        "bridge_readiness_sha256",
        "controller_pid",
        "project_name",
        "schema_version",
    }
    readiness = control.get("bridge_readiness")
    controller_pid = control.get("controller_pid")
    if (
        set(control) != expected_keys
        or control.get("schema_version") != _CONTROL_SCHEMA
        or control.get("project_name") != config.runtime_attestation.lane_project_name
        or control.get("account_index") != account_index
        or control.get("account_name") != bridge.account_name
        or control.get("bridge_id") != bridge.bridge_id
        or control.get("bridge_port") != bridge_port
        or not _sha(control.get("anchor_namespace_sha256"))
        or type(controller_pid) is not int
        or controller_pid <= 1
        or type(readiness) is not dict
        or control.get("bridge_readiness_sha256") != _canonical_sha256(readiness)
    ):
        _fail("publishable_run_provider_fleet_control_invalid")
    return readiness


@final
class _BridgeReceiptKeys:
    __slots__ = ("_by_id",)

    def __init__(self, secrets: RunProviderSecrets) -> None:
        self._by_id = {item.bridge_id: item for item in secrets.bridges}

    def launcher_receipt_key(self, bridge_id: str) -> bytes:
        try:
            return bytes(self._by_id[bridge_id].launcher_receipt_key)
        except (KeyError, TypeError):
            _fail("publishable_run_provider_bridge_secret_unavailable")


def _verify_runtime_authorities(config: RunProviderConfig, verified: _VerifiedFleet) -> None:
    authority = config.runtime_authority
    for index, (bridge, launch, control) in enumerate(
        zip(
            config.fleet_bridges,
            verified.readiness.launches,
            verified.controls,
            strict=True,
        )
    ):
        runtime_authority_path = control.path.parent / _RUNTIME_AUTHORITY_RELATIVE
        _require_canonical_existing(runtime_authority_path)
        payload = read_private_json(
            runtime_authority_path,
            maximum_bytes=_MAX_READINESS_BYTES,
        )
        expected_keys = set(
            RuntimeProcessAuthority(
                account_name=bridge.account_name,
                bridge_authority=verified.readiness.pool.bridges[index],
                state_root_identity_sha256="0" * 64,
                auth_root_identity_sha256="0" * 64,
                private_material_binding_hmac_sha256="0" * 64,
                runtime_artifact_manifest_sha256=authority.runtime_artifact_manifest_sha256,
                runtime_entrypoint_sha256=authority.runtime_entrypoint_sha256,
                node_executable_sha256=authority.node_executable_sha256,
                codex_executable_sha256=authority.codex_executable_sha256,
            ).public_payload()
        )
        if set(payload) != expected_keys:
            _fail("publishable_run_provider_runtime_authority_invalid")
        runtime = RuntimeProcessAuthority(
            account_name=bridge.account_name,
            bridge_authority=verified.readiness.pool.bridges[index],
            state_root_identity_sha256=_required_sha(payload, "state_root_identity_sha256"),
            auth_root_identity_sha256=_required_sha(payload, "auth_root_identity_sha256"),
            private_material_binding_hmac_sha256=_required_sha(
                payload,
                "private_material_binding_hmac_sha256",
            ),
            runtime_artifact_manifest_sha256=authority.runtime_artifact_manifest_sha256,
            runtime_entrypoint_sha256=authority.runtime_entrypoint_sha256,
            node_executable_sha256=authority.node_executable_sha256,
            codex_executable_sha256=authority.codex_executable_sha256,
        )
        if (
            payload != runtime.public_payload()
            or runtime.commitment_sha256 != launch.runtime_authority_sha256
        ):
            _fail("publishable_run_provider_runtime_authority_invalid")


def _verify_lane_attestation(
    config: RunProviderConfig,
    secrets: RunProviderSecrets,
    verified: _VerifiedFleet,
    *,
    expected_mode: str,
) -> tuple[Path, ...]:
    directory = config.runtime_attestation.directory
    try:
        _require_canonical_existing(directory)
        verify_private_directory(directory, "runtime_attestation_directory")
        paths = tuple(sorted(directory.iterdir()))
    except Exception:
        _fail("publishable_run_provider_runtime_attestation_directory_invalid")
    runtime_paths = _runtime_attestation_paths(paths)
    if not runtime_paths:
        _fail("publishable_run_provider_runtime_attestation_missing")
    receipts = tuple(
        _read_lane_attestation(
            path,
            authentication_key=secrets.runtime_attestation_root_secret,
        )
        for path in runtime_paths
    )
    now_ns = time.time_ns()
    observed = tuple(_observed_ns(item) for item in receipts)
    latest_ns = max(observed)
    latest = tuple(
        item for item, timestamp in zip(receipts, observed, strict=True) if timestamp == latest_ns
    )
    expected_fleet = _expected_fleet_payload(verified, expected_mode=expected_mode)
    current = tuple(
        item
        for item in receipts
        if item.get("project_name") == config.runtime_attestation.lane_project_name
        and item.get("fleet") == expected_fleet
    )
    if not current:
        _fail("publishable_run_provider_runtime_attestation_stale_or_cross_mode")
    current_latest_ns = max(_observed_ns(item) for item in current)
    current_latest = tuple(item for item in current if _observed_ns(item) == current_latest_ns)
    maximum_age_ns = config.runtime_attestation.maximum_age_seconds * 1_000_000_000
    if (
        len(latest) != 1
        or len(current_latest) != 1
        or latest[0] is not current_latest[0]
        or current_latest_ns > now_ns + 1_000_000_000
        or now_ns - current_latest_ns > maximum_age_ns
    ):
        _fail("publishable_run_provider_runtime_attestation_stale_or_cross_mode")
    bindings = {_canonical_sha256(_without_observation(item)) for item in current}
    if len(bindings) != 1:
        _fail("publishable_run_provider_runtime_attestation_divergent")
    _cross_check_lane_attestation(
        current_latest[0],
        config=config,
        secrets=secrets,
        verified=verified,
        expected_mode=expected_mode,
    )
    return paths


def _runtime_attestation_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    selected: list[Path] = []
    for path in paths:
        if _ATTESTATION_NAME.fullmatch(path.name) is not None:
            selected.append(path)
        elif path.name.startswith(_ATTESTATION_PREFIX):
            _fail("publishable_run_provider_runtime_attestation_file_invalid")
    return tuple(selected)


def _read_lane_attestation(
    path: Path,
    *,
    authentication_key: bytes,
) -> dict[str, object]:
    match = _ATTESTATION_NAME.fullmatch(path.name)
    if match is None:
        _fail("publishable_run_provider_runtime_attestation_file_invalid")
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or not 1 < opened.st_size <= _MAX_ATTESTATION_BYTES
        ):
            raise OSError
        raw = os.read(descriptor, _MAX_ATTESTATION_BYTES + 1)
        final = os.fstat(descriptor)
        if len(raw) != opened.st_size or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ) != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns):
            raise OSError
    except OSError:
        _fail("publishable_run_provider_runtime_attestation_file_invalid")
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except Exception:
        _fail("publishable_run_provider_runtime_attestation_file_invalid")
    if type(payload) is not dict or raw != _canonical_json(payload) + b"\n":
        _fail("publishable_run_provider_runtime_attestation_file_invalid")
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    if not hmac.compare_digest(digest, match.group(1)):
        _fail("publishable_run_provider_runtime_attestation_file_invalid")
    authentication = payload.get("attestation_hmac_sha256")
    unsigned = dict(payload)
    unsigned.pop("attestation_hmac_sha256", None)
    expected_authentication = hmac.new(
        authentication_key,
        _HOST_ATTESTATION_DOMAIN + _canonical_json(unsigned),
        hashlib.sha256,
    ).hexdigest()
    if not _sha(authentication) or not hmac.compare_digest(
        str(authentication),
        expected_authentication,
    ):
        _fail("publishable_run_provider_runtime_attestation_authentication_invalid")
    return payload


def _cross_check_lane_attestation(
    payload: dict[str, object],
    *,
    config: RunProviderConfig,
    secrets: RunProviderSecrets,
    verified: _VerifiedFleet,
    expected_mode: str,
) -> None:
    root_keys = {
        "account_i_fence_commitment_sha256",
        "adapter_image_id",
        "attestation_hmac_sha256",
        "anchor_container_inventory_sha256",
        "anchor_netns",
        "anchor_pidns",
        "bridge_ports",
        "compose_sha256",
        "deployment_inputs_sha256",
        "fleet",
        "host_exposure",
        "observed_at_unix_ns",
        "project_name",
        "qdrant_image_id",
        "qdrant_ports",
        "relay_reachability_sha256",
        "schema_version",
        "secret_cross_wire_sha256",
        "services",
        "socket_bindings_sha256",
    }
    host = payload.get("host_exposure")
    services = payload.get("services")
    expected_fleet = _expected_fleet_payload(verified, expected_mode=expected_mode)
    if (
        set(payload) != root_keys
        or payload.get("schema_version") != _ATTESTATION_SCHEMA
        or payload.get("project_name") != config.runtime_attestation.lane_project_name
        or payload.get("compose_sha256") != COMPOSE_SHA256
        or payload.get("adapter_image_id") != config.runtime_authority.adapter_image_id
        or payload.get("bridge_ports") != [8891, 8892, 8893]
        or payload.get("qdrant_ports") != {"grpc": 6335, "http": 6334}
        or payload.get("fleet") != expected_fleet
        or host
        != {
            "container_port": 19191,
            "host_ip": "127.0.0.1",
            "host_port": int(config.runtime_attestation.endpoint.rsplit(":", 1)[1]),
            "relayed_adapter_port": 19091,
        }
        or type(services) is not dict
        or set(services) != _SERVICES
        or payload.get("secret_cross_wire_sha256") != _secret_cross_wire(config, secrets)
        or not all(
            _sha(payload.get(key))
            for key in (
                "account_i_fence_commitment_sha256",
                "anchor_container_inventory_sha256",
                "deployment_inputs_sha256",
                "relay_reachability_sha256",
                "socket_bindings_sha256",
            )
        )
        or not _image_id(payload.get("qdrant_image_id"))
        or not _namespace(payload.get("anchor_netns"))
        or not _namespace(payload.get("anchor_pidns"))
        or not _services_valid(
            services,
            adapter_image_id=config.runtime_authority.adapter_image_id,
            qdrant_image_id=str(payload.get("qdrant_image_id")),
        )
    ):
        _fail("publishable_run_provider_runtime_attestation_mismatch")


def _expected_fleet_payload(verified: _VerifiedFleet, *, expected_mode: str) -> dict[str, object]:
    bridges = []
    for bridge, launch, control in zip(
        verified.readiness.pool.bridges,
        verified.readiness.launches,
        verified.controls,
        strict=True,
    ):
        bridges.append(
            {
                "account_name": launch.pending.account_name,
                "bridge_id": bridge.bridge_id,
                "controller_pid": control.controller_pid,
                "generation": launch.pending.generation,
                "launch_mode": launch.pending.mode,
                "process": launch.pending.process.public_payload(),
                "readiness_receipt_sha256": launch.commitment_sha256,
                "runtime_authority_sha256": launch.runtime_authority_sha256,
            }
        )
    return {
        "bridges": bridges,
        "fleet_readiness_sha256": _canonical_sha256(verified.readiness.public_payload()),
        "pool_authority_sha256": verified.readiness.pool.commitment_sha256,
        "requested_mode": expected_mode,
    }


def _secret_cross_wire(config: RunProviderConfig, secrets: RunProviderSecrets) -> str:
    primary = secrets.bridges[0]
    commitments = (
        hashlib.sha256(primary.authorization_bearer.encode()).hexdigest(),
        hashlib.sha256(primary.attestation_secret).hexdigest(),
        hashlib.sha256(config.fleet_bridges[0].account_binding_hmac_sha256.encode()).hexdigest(),
        hashlib.sha256(SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256.encode()).hexdigest(),
        hashlib.sha256(b"http://127.0.0.1:8891").hexdigest(),
    )
    return hashlib.sha256("".join(commitments).encode("ascii")).hexdigest()


def _verify_endpoint_runtime_authority(
    config: RunProviderConfig,
    secrets: RunProviderSecrets,
) -> None:
    authority = config.runtime_authority
    expected = expected_managed_mem0_v5_runtime_authority_from_pin(
        runtime_pin_file=authority.runtime_pin_path,
        runtime_pin_sha256=authority.runtime_pin_sha256,
        runtime_source_sha256=authority.runtime_source_sha256,
        runtime_route_binding_sha256=authority.runtime_route_binding_sha256,
        subscription_runtime_binding_commitment_sha256=(
            authority.subscription_runtime_binding_commitment_sha256
        ),
        expected_account_binding_hmac_sha256=(config.fleet_bridges[0].account_binding_hmac_sha256),
        expected_base_instructions_sha256=SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
        expected_extraction_system_prompt_sha256=authority.extraction_system_prompt_sha256,
        expected_extraction_response_format_sha256=authority.extraction_response_format_sha256,
        expected_extraction_response_schema_sha256=authority.extraction_response_schema_sha256,
        expected_requested_output_tokens=4096,
    )
    if (
        expected.source_manifest_sha256 != authority.source_manifest_sha256
        or hashlib.sha256(expected.source_commit_sha1.encode("ascii")).hexdigest()
        != config.suite.source_commit_sha256
    ):
        _fail("publishable_run_provider_reviewed_source_mismatch")
    nonce = token_hex(32)
    target = mem0_runtime_target_identity_sha256(config.runtime_attestation.endpoint)
    request = {
        "schema_version": REQUEST_SCHEMA,
        "target_origin_sha256": target,
        "run_id_sha256": hashlib.sha256(config.suite.suite_id.encode()).hexdigest(),
        "probe_nonce_sha256": nonce,
        "validity_seconds": 60,
    }
    response = _post_runtime_attestation(
        endpoint=config.runtime_attestation.endpoint,
        timeout_seconds=config.runtime_attestation.endpoint_timeout_seconds,
        root_secret=secrets.runtime_attestation_root_secret,
        request=request,
    )
    verified = _verify_and_issue(
        response,
        request=request,
        root_secret=secrets.runtime_attestation_root_secret,
        expected_authority=expected,
        now_unix=int(time.time()),
    )
    if not managed_mem0_v5_runtime_validation_is_publishable(
        verified,
        required_runtime_mode="oss",
    ):
        _fail("publishable_run_provider_endpoint_attestation_invalid")


def _post_runtime_attestation(
    *,
    endpoint: str,
    timeout_seconds: float,
    root_secret: bytes,
    request: dict[str, object],
) -> dict[str, object]:
    import httpx

    request_sha256 = _canonical_sha256(request)
    authentication = hmac.new(root_secret, _AUTH_DOMAIN, hashlib.sha256).hexdigest()
    idempotency = hashlib.sha256(_IDEMPOTENCY_DOMAIN + bytes.fromhex(request_sha256)).hexdigest()
    maximum_bytes = 32 * 1024
    with (
        httpx.Client(
            base_url=endpoint,
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ) as client,
        client.stream(
            "POST",
            "/v5/runtime/attest",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Authorization": f"Bearer {authentication}",
                "Idempotency-Key": idempotency,
                "X-Request-Commitment-SHA256": request_sha256,
            },
            json=request,
        ) as response,
    ):
        if response.status_code != 200:
            _fail("publishable_run_provider_endpoint_attestation_failed")
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length, 10)
            except ValueError:
                _fail("publishable_run_provider_endpoint_attestation_failed")
            if declared < 0 or declared > maximum_bytes:
                _fail("publishable_run_provider_endpoint_attestation_failed")
        raw = bytearray()
        for chunk in response.iter_raw(chunk_size=8_192):
            if type(chunk) is not bytes or len(raw) + len(chunk) > maximum_bytes:
                _fail("publishable_run_provider_endpoint_attestation_failed")
            raw.extend(chunk)
    try:
        payload = json.loads(
            bytes(raw),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except Exception:
        _fail("publishable_run_provider_endpoint_attestation_failed")
    if type(payload) is not dict:
        _fail("publishable_run_provider_endpoint_attestation_failed")
    return payload


def _require_controls_unchanged(controls: tuple[_ControlSnapshot, ...]) -> None:
    for item in controls:
        if read_private_json(item.path, maximum_bytes=_MAX_READINESS_BYTES) != item.payload:
            _fail("publishable_run_provider_fleet_changed_during_preflight")


def _require_attestation_directory_unchanged(
    directory: Path,
    expected_paths: tuple[Path, ...],
    *,
    authentication_key: bytes,
) -> None:
    try:
        observed = tuple(sorted(directory.iterdir()))
    except OSError:
        _fail("publishable_run_provider_runtime_attestation_directory_invalid")
    if observed != expected_paths:
        _fail("publishable_run_provider_runtime_attestation_changed_during_preflight")
    for path in _runtime_attestation_paths(observed):
        _read_lane_attestation(path, authentication_key=authentication_key)


def _require_canonical_existing(path: Path) -> None:
    try:
        if path.resolve(strict=True) != path:
            raise OSError
    except OSError:
        _fail("publishable_run_provider_runtime_path_invalid")


def _services_valid(
    services: dict[str, object],
    *,
    adapter_image_id: str,
    qdrant_image_id: str,
) -> bool:
    for name, value in services.items():
        if type(value) is not dict or set(value) != {
            "bind_mounts_sha256",
            "container_id",
            "image_id",
            "pid",
        }:
            return False
        expected_image = qdrant_image_id if name == "publishable-qdrant" else adapter_image_id
        if (
            not _sha(value.get("bind_mounts_sha256"))
            or not isinstance(value.get("container_id"), str)
            or re.fullmatch(r"[0-9a-f]{64}", str(value.get("container_id"))) is None
            or value.get("image_id") != expected_image
            or type(value.get("pid")) is not int
            or value["pid"] <= 1
        ):
            return False
    return True


def _namespace(value: object) -> bool:
    return bool(
        type(value) is dict
        and set(value) == {"device", "inode"}
        and type(value.get("device")) is int
        and value["device"] >= 0
        and type(value.get("inode")) is int
        and value["inode"] > 0
    )


def _observed_ns(value: dict[str, object]) -> int:
    observed = value.get("observed_at_unix_ns")
    if type(observed) is not int or observed <= 0:
        _fail("publishable_run_provider_runtime_attestation_time_invalid")
    return observed


def _without_observation(value: dict[str, object]) -> dict[str, object]:
    result = dict(value)
    result.pop("observed_at_unix_ns", None)
    result.pop("attestation_hmac_sha256", None)
    return result


def _required_sha(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not _sha(item):
        _fail("publishable_run_provider_runtime_authority_invalid")
    return str(item)


def _sha(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _image_id(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    raise ValueError


def _fail(code: str) -> None:
    raise PublishableRunError(code) from None


__all__ = ("preflight_run_provider",)

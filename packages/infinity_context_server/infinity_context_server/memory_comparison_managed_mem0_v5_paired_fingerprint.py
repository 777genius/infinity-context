"""Registered deep binding for immutable managed Mem0 v5 paired delegates."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import weakref
from dataclasses import dataclass
from pathlib import Path

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
)

_FINGERPRINT_KEY = secrets.token_bytes(32)
_REGISTRY_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class _ExpectedBinding:
    run_identity: int
    snapshot_sha256: str
    commitment_sha256: str
    registry_mac: bytes


_EXPECTED: weakref.WeakKeyDictionary[object, _ExpectedBinding] = weakref.WeakKeyDictionary()


def _register_paired_run_binding(run: object) -> None:
    """Register one construction-time baseline; never update an existing run."""

    snapshot_sha256 = _snapshot_sha256(run)
    commitment = hmac.new(
        _FINGERPRINT_KEY,
        b"managed-mem0-v5/paired-commitment/v1\x00"
        + str(id(run)).encode()
        + b"\x00"
        + snapshot_sha256.encode(),
        hashlib.sha256,
    ).hexdigest()
    provisional = _ExpectedBinding(id(run), snapshot_sha256, commitment, b"")
    state = _ExpectedBinding(
        provisional.run_identity,
        provisional.snapshot_sha256,
        provisional.commitment_sha256,
        _registry_mac(provisional),
    )
    with _REGISTRY_LOCK:
        if run in _EXPECTED:
            raise RuntimeError("managed Mem0 v5 paired binding is already registered")
        _EXPECTED[run] = state


def authenticate_paired_run_binding(run: object) -> str:
    """Return the registered commitment only while the exact graph still matches."""

    with _REGISTRY_LOCK:
        state = _EXPECTED.get(run)
        if (
            state is None
            or state.run_identity != id(run)
            or not hmac.compare_digest(state.registry_mac, _registry_mac(state))
        ):
            raise RuntimeError("managed Mem0 v5 paired binding is unavailable")
        current = _snapshot_sha256(run)
        if not hmac.compare_digest(state.snapshot_sha256, current):
            raise RuntimeError("managed Mem0 v5 paired binding differs")
        return state.commitment_sha256


def _registry_mac(state: _ExpectedBinding) -> bytes:
    payload = {
        "run_identity": state.run_identity,
        "snapshot_sha256": state.snapshot_sha256,
        "commitment_sha256": state.commitment_sha256,
    }
    return hmac.new(
        _FINGERPRINT_KEY,
        b"managed-mem0-v5/paired-registry/v1\x00" + _canonical(payload),
        hashlib.sha256,
    ).digest()


def _snapshot_sha256(run: object) -> str:
    return hashlib.sha256(_canonical(_paired_run_snapshot(run))).hexdigest()


def _paired_run_snapshot(run: object) -> dict[str, object]:
    authority = run._authority
    authority.__post_init__()
    admission = Mem0OssFullRunAdmission(
        request=run._request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    coordinator = run._coordinator
    service = getattr(coordinator, "_service", None)
    lane = getattr(coordinator, "_lane", None)
    progress = getattr(coordinator, "_progress", None)
    corpus_storage_verifier = run._corpus_projector._storage_verifier
    return {
        "run_identity": id(run),
        "authority": {"identity": id(authority), "payload": authority.public_payload()},
        "request_identity": id(run._request),
        "admission": admission.public_payload(),
        "budget_policy": {
            "identity": id(run._budget_policy),
            "maximum_total_call_count": run._budget_policy.maximum_total_call_count,
        },
        "coordinator": _coordinator_binding(coordinator, service, lane, progress),
        "clean_state_snapshot": _snapshot_binding(run._clean_state_snapshot),
        "clean_state_verifier": _clean_verifier_binding(run._clean_state_verifier),
        "durable_clean_state": _durable_binding(run._durable_clean_state),
        "corpus_projector": {
            **_identity(run._corpus_projector),
            "admission_commitment_sha256": run._corpus_projector._admission,
            "authority_identity": id(run._corpus_projector._authority),
            "authority": run._corpus_projector._authority.public_payload(),
            "storage_verifier_identity": id(corpus_storage_verifier),
            "storage_verifier_state_identity": _attribute_identity(
                corpus_storage_verifier, "_state"
            ),
        },
        "answer_projector": {
            **_identity(run._projector),
            "authority_commitment_sha256": run._projector._authority_commitment_sha256,
            "expected_admission_commitment_sha256": (
                run._projector._expected_admission_commitment_sha256
            ),
            "sources": [
                [corpus_id, source_id, source_sha256, observation_date]
                for (corpus_id, source_id), (source_sha256, observation_date) in sorted(
                    run._projector._sources.items()
                )
            ],
        },
        "lock_identity": id(run._lock),
        "expected_admission_commitment_sha256": run._expected_admission_commitment_sha256,
        "expected_clean_scopes": [item.payload() for item in run._expected_clean_scopes],
    }


def _coordinator_binding(
    coordinator: object, service: object, lane: object, progress: object
) -> dict[str, object]:
    return {
        **_identity(coordinator),
        "service": _service_binding(service),
        "lane": _lane_binding(lane),
        "progress": _progress_binding(progress),
        "fixture_authority_identity": _attribute_identity(coordinator, "authority"),
        "fixture_request_identity": _attribute_identity(coordinator, "request"),
        "fixture_storage_verifier_identity": _attribute_identity(coordinator, "storage_verifier"),
    }


def _service_binding(service: object) -> dict[str, object] | None:
    if service is None:
        return None
    manifest = getattr(service, "_manifest_port", None)
    receipt = getattr(service, "_receipt_port", None)
    storage = getattr(service, "_storage_port", None)
    cleanup = getattr(service, "_cleanup_port", None)
    return {
        **_identity(service),
        "manifest_port": _identity(manifest),
        "receipt_port": _receipt_binding(receipt),
        "storage_port": _storage_bridge_binding(storage),
        "cleanup_port": _identity(cleanup),
    }


def _receipt_binding(receipt: object) -> dict[str, object]:
    authority = getattr(receipt, "_authority", None)
    module = getattr(receipt, "_module", None)
    boundary = getattr(receipt, "_boundary", None)
    operation_index = getattr(receipt, "_operation_index", None)
    return {
        **_identity(receipt),
        "module_identity": id(module),
        "module_name": getattr(module, "__name__", None),
        "boundary": {
            **_identity(boundary),
            "hmac_verifier_identity": _first_attribute_identity(
                boundary, ("_hmac_verifier", "hmac_verifier", "_verifier")
            ),
        },
        "runtime_binding": _runtime_binding(getattr(receipt, "_runtime_binding", None)),
        "authority": _receipt_authority(authority),
        "operation_index": {
            **_identity(operation_index),
            "entries": (
                [
                    [operation_id, id(operation)]
                    for operation_id, operation in operation_index.items()
                ]
                if type(operation_index) is dict  # noqa: E721 - exact container is bound
                else None
            ),
        },
        "unknown_identity": _attribute_identity(receipt, "_unknown"),
        "consumed_identity": _attribute_identity(receipt, "_consumed"),
        "secret_identity": _attribute_identity(receipt, "_secret"),
        "lock_identity": _attribute_identity(receipt, "_lock"),
    }


def _runtime_binding(binding: object) -> dict[str, object]:
    return {
        **_identity(binding),
        "runtime_source_sha256": getattr(binding, "runtime_source_sha256", None),
        "route_binding_sha256": getattr(binding, "route_binding_sha256", None),
        "commitment_sha256": getattr(binding, "commitment_sha256", None),
    }


def _receipt_authority(authority: object) -> dict[str, object]:
    if authority is None:
        return _identity(authority)
    fields = (
        "admission_commitment_sha256",
        "model",
        "reasoning_effort",
        "service_tier",
        "base_instructions_sha256",
        "runtime_source_sha256",
        "route_binding_sha256",
        "account_binding_hmac_sha256",
        "node_executable_path",
        "node_executable_sha256",
        "response_format_type",
        "response_format_sha256",
        "response_schema_sha256",
        "requested_output_tokens",
    )
    operations = getattr(authority, "operations", ())
    return {
        **_identity(authority),
        "fields": {name: getattr(authority, name, None) for name in fields},
        "operations": [
            {
                **_identity(operation),
                "fields": {
                    name: getattr(operation, name, None)
                    for name in (
                        "operation_id_sha256",
                        "unit_identity_sha256",
                        "unit_sha256",
                        "scope_sha256",
                        "sequence",
                        "request_body_sha256",
                        "thread_id",
                        "turn_id",
                        "output_text_sha256",
                    )
                },
            }
            for operation in operations
        ],
    }


def _storage_bridge_binding(storage: object) -> dict[str, object]:
    authority = getattr(storage, "_authority", None)
    units = getattr(storage, "_units", {})
    return {
        **_identity(storage),
        "authority_identity": id(authority),
        "authority": None if authority is None else authority.public_payload(),
        "authority_commitment_sha256": getattr(storage, "_authority_commitment", None),
        "units": [item.public_payload() for _, item in sorted(units.items())],
        "witness_verifier_identity": _attribute_identity(storage, "_witness_verifier"),
        "witness_verifier_state_identity": _attribute_identity(
            getattr(storage, "_witness_verifier", None), "_state"
        ),
    }


def _lane_binding(lane: object) -> dict[str, object] | None:
    if lane is None:
        return None
    control = getattr(lane, "_control", None)
    lane_transport = getattr(lane, "_transport", None)
    control_transport = getattr(control, "_transport", None)
    cleanup_binding = getattr(lane, "_cleanup_binding", None)
    verifier = getattr(lane, "_verifier", None)
    guard = getattr(lane, "_dispatch_guard", None)
    return {
        **_identity(lane),
        "origin": getattr(lane, "_origin", None),
        "timeout": getattr(lane, "_timeout", None),
        "bearer_identity": _attribute_identity(lane, "_bearer"),
        "transport": _identity(lane_transport),
        "verifier": _evidence_verifier_binding(verifier),
        "binding_identity": _attribute_identity(lane, "_binding"),
        "cleanup_binding": {
            **_identity(cleanup_binding),
            "service_identity": _attribute_identity(cleanup_binding, "_service"),
        },
        "dispatch_guard": {
            **_identity(guard),
            "path": _path(getattr(guard, "_path", None)),
        },
        "control": {
            **_identity(control),
            "origin": getattr(control, "_origin", None),
            "timeout": getattr(control, "_timeout", None),
            "bearer_identity": _attribute_identity(control, "_bearer"),
            "transport": _identity(control_transport),
        },
        "control_matches_lane": (
            control_transport is lane_transport
            and getattr(control, "_origin", None) == getattr(lane, "_origin", None)
            and getattr(control, "_timeout", None) == getattr(lane, "_timeout", None)
        ),
        "control_bearer_matches_lane": getattr(control, "_bearer", None)
        is getattr(lane, "_bearer", None),
        "control_bearer_equals_lane": getattr(control, "_bearer", None)
        == getattr(lane, "_bearer", None),
        "transport_collector_identity": _attribute_identity(lane, "_transport_collector"),
    }


def _evidence_verifier_binding(verifier: object) -> dict[str, object]:
    issuer = getattr(verifier, "_storage_witness_issuer", None)
    return {
        **_identity(verifier),
        "key_commitment_sha256": getattr(verifier, "key_commitment_sha256", None),
        "derived_key_identities": {
            name: _attribute_identity(verifier, name)
            for name in (
                "_observation_key",
                "_request_binding_key",
                "_request_binding_v2_key",
                "_search_key",
                "_clean_state_key",
            )
        },
        "storage_witness_issuer_identity": id(issuer),
        "storage_witness_issuer_state_identity": _attribute_identity(issuer, "_state"),
    }


def _progress_binding(progress: object) -> dict[str, object] | None:
    if progress is None:
        return None
    store = getattr(progress, "_store", None)
    signer = getattr(progress, "_signer", None)
    head = getattr(progress, "_head", None)
    descriptor = getattr(store, "_dirfd", None)
    descriptor_identity = None
    if descriptor.__class__ is int and descriptor >= 0:
        metadata = os.fstat(descriptor)
        descriptor_identity = [metadata.st_dev, metadata.st_ino]
    return {
        **_identity(progress),
        "store": {
            **_identity(store),
            "dirfd": descriptor,
            "directory_identity": descriptor_identity,
            "name": getattr(store, "_name", None),
            "lock_name": getattr(store, "_lock_name", None),
            "signer_identity": _attribute_identity(store, "_signer"),
        },
        "signer": {
            **_identity(signer),
            "key_identity": _attribute_identity(signer, "_key"),
        },
        "store_signer_matches": getattr(store, "_signer", None) is signer,
        "head": {
            **_identity(head),
            "path": _path(getattr(head, "_path", None)),
            "hmac_key_identity": _attribute_identity(head, "_hmac_key"),
        },
    }


def _snapshot_binding(snapshot: object) -> dict[str, object]:
    authority = getattr(snapshot, "_authority", None)
    admission = getattr(snapshot, "_admission", None)
    return {
        **_identity(snapshot),
        "authority_identity": id(authority),
        "authority": None if authority is None else authority.public_payload(),
        "admission_identity": id(admission),
        "admission": None if admission is None else admission.public_payload(),
        "issuer_identity": _attribute_identity(snapshot, "_issuer"),
        "issuer_state_identity": _attribute_identity(getattr(snapshot, "_issuer", None), "_state"),
        "lane_identity": _attribute_identity(snapshot, "_lane"),
    }


def _clean_verifier_binding(verifier: object) -> dict[str, object]:
    return {
        **_identity(verifier),
        "state_identity": _attribute_identity(verifier, "_state"),
    }


def _durable_binding(durable: object) -> dict[str, object]:
    issuer = getattr(durable, "_issuer", None)
    verifier = getattr(durable, "_verifier", None)
    return {
        **_identity(durable),
        "path": _path(getattr(durable, "_path", None)),
        "lock_path": _path(getattr(durable, "_lock_path", None)),
        "issuer_identity": id(issuer),
        "issuer_state_identity": _attribute_identity(issuer, "_state"),
        "verifier_identity": id(verifier),
        "verifier_state_identity": _attribute_identity(verifier, "_state"),
        "hmac_key_identity": _attribute_identity(durable, "_hmac_key"),
        "lock_identity": _attribute_identity(durable, "_lock"),
    }


def _path(value: object) -> str | None:
    return str(value) if isinstance(value, Path) else None


def _attribute_identity(value: object, name: str) -> int | None:
    item = getattr(value, name, None)
    return None if item is None else id(item)


def _first_attribute_identity(value: object, names: tuple[str, ...]) -> int | None:
    for name in names:
        item = getattr(value, name, None)
        if item is not None:
            return id(item)
    return None


def _identity(value: object) -> dict[str, object]:
    if value is None:
        return {"identity": None, "type": None}
    return {
        "identity": id(value),
        "type": f"{type(value).__module__}.{type(value).__qualname__}",
    }


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


__all__ = ("authenticate_paired_run_binding",)

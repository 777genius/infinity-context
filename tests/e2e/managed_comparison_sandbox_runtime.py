"""Real managed runtime capability behind deterministic in-process ports."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from infinity_context_server.memory_comparison_clean_state import (
    clean_state_identity_sha256,
    fresh_namespace_clean_state_proof,
    mem0_delete_clean_state_proof,
    validate_typed_clean_state_proofs,
)
from infinity_context_server.memory_comparison_full_execution_validation import (
    FullExecutionCleanScope,
)
from infinity_context_server.memory_comparison_mem0_contract import (
    MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    VerifiedMem0RuntimeAttestationValidation,
    build_verified_mem0_runtime_attestation,
    public_mem0_runtime_attestation_validation,
    validate_mem0_runtime_attestation_for_backends,
)
from managed_comparison_sandbox_adapters import (
    INFINITY_BACKEND,
    MEM0_BACKEND,
    RUNTIME_NONCE,
    CleanStateBundle,
    SandboxBackendState,
    SandboxTrace,
    implementation_sha256,
)


class _Port:
    def __init__(self, role: str, trace: SandboxTrace) -> None:
        self.adapter_id = f"managed-locomo-sandbox-{role}"
        self.implementation_sha256 = implementation_sha256(role)
        self.trace = trace


@dataclass(frozen=True, slots=True)
class SandboxIngestReceipt:
    backend_role: str
    corpus_id: str


class SandboxResetPort(_Port):
    def __init__(self, trace: SandboxTrace, state: SandboxBackendState) -> None:
        super().__init__("reset", trace)
        self._state = state

    def reset(
        self,
        *,
        run_id: str,
        binding_commitment_sha256: str,
        backend_targets: tuple[tuple[str, str], ...],
    ) -> None:
        assert run_id and len(binding_commitment_sha256) == 64
        assert tuple(role for role, _target in backend_targets) == (
            INFINITY_BACKEND,
            MEM0_BACKEND,
        )
        self._state.require_pristine()
        self._state.clean_state = _clean_state_bundle(run_id)
        self.trace.add("reset")


class SandboxAttestationPort(_Port):
    def __init__(
        self,
        trace: SandboxTrace,
        validation: VerifiedMem0RuntimeAttestationValidation,
        *,
        run_id: str,
        probe_nonce_sha256: str,
        target_identity_sha256: str,
    ) -> None:
        super().__init__("attestation", trace)
        self._validation = validation
        self._expected = (run_id, probe_nonce_sha256, target_identity_sha256)

    def attest(
        self,
        *,
        run_id: str,
        probe_nonce_sha256: str,
        target_identity_sha256: str,
    ) -> VerifiedMem0RuntimeAttestationValidation:
        assert (run_id, probe_nonce_sha256, target_identity_sha256) == self._expected
        self.trace.add("attest")
        return self._validation


class SandboxIngestPort(_Port):
    def __init__(self, trace: SandboxTrace, state: SandboxBackendState) -> None:
        super().__init__("ingest", trace)
        self._state = state
        self.receipts: list[SandboxIngestReceipt] = []

    def ingest(
        self,
        *,
        run_id: str,
        backend_role: str,
        target_identity_sha256: str,
        record: Mapping[str, object],
    ) -> SandboxIngestReceipt:
        assert run_id and len(target_identity_sha256) == 64
        assert type(record) is dict and record["sample_id"] == "sandbox-locomo-1"
        corpus_id = str(record["sample_id"])
        source = self._state.ingest(backend_role, corpus_id, record)
        assert source.source_sha256 == hashlib.sha256(source.canonical_bytes).hexdigest()
        receipt = SandboxIngestReceipt(backend_role, corpus_id)
        self.receipts.append(receipt)
        self.trace.add(f"ingest:{backend_role}")
        return receipt


class SandboxClockPort(_Port):
    def __init__(self, trace: SandboxTrace, current: datetime) -> None:
        super().__init__("clock", trace)
        self._current = current

    def now(self) -> datetime:
        return self._current


@dataclass(frozen=True, slots=True)
class SandboxRuntimePorts:
    reset: SandboxResetPort
    attestation: SandboxAttestationPort
    ingest: SandboxIngestPort
    clock: SandboxClockPort
    started_at: datetime


def build_runtime_ports(
    trace: SandboxTrace,
    state: SandboxBackendState,
    *,
    run_id: str,
    probe_nonce_sha256: str,
    target_identity_sha256: str,
) -> SandboxRuntimePorts:
    started_at = datetime.now(UTC)
    validation = _runtime_validation(
        run_id=run_id,
        target_identity_sha256=target_identity_sha256,
        observed_at=started_at,
    )
    return SandboxRuntimePorts(
        SandboxResetPort(trace, state),
        SandboxAttestationPort(
            trace,
            validation,
            run_id=run_id,
            probe_nonce_sha256=probe_nonce_sha256,
            target_identity_sha256=target_identity_sha256,
        ),
        SandboxIngestPort(trace, state),
        SandboxClockPort(trace, started_at),
        started_at,
    )


class _RuntimeBackend:
    def __init__(self, name: str, target: str | None = None) -> None:
        self.name = name
        if target is not None:
            self.runtime_target_identity_sha256 = target


def _runtime_validation(
    *,
    run_id: str,
    target_identity_sha256: str,
    observed_at: datetime,
) -> VerifiedMem0RuntimeAttestationValidation:
    checked_at = observed_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    artifact = "9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"
    manifest = {
        "schema_version": MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
        "runtime_mode": "managed_platform",
        "wrapper_source_sha256": "a" * 64,
        "wrapper_source_revision": "b" * 40,
        "config_fingerprint_sha256": "c" * 64,
        "sdk": {
            "distribution": "mem0ai",
            "version": "2.0.14",
            "source_revision": "b357a5a1b03c299ec8229c268e63cfac0f7c6566",
            "artifact_sha256": artifact,
            "verification": {
                "method": "direct_url_archive_info_sha256",
                "observed_sha256": artifact,
                "passed": True,
            },
        },
        "platform": {
            "api_origin": "https://api.mem0.ai",
            "api_generation": "v3",
            "add_path": "/v3/memories/add/",
            "search_path": "/v3/memories/search/",
            "event_path_template": "/v1/event/{event_id}/",
            "server_source_revision": None,
            "server_revision_attestable": False,
        },
        "timestamp": {
            "request_supported": True,
            "sdk_forwarding_supported": True,
            "event_completion_supported": True,
            "readback_supported": True,
            "attestation": {
                "status": "passed",
                "checked_at": checked_at,
                "probe_mode": "live_sentinel",
                "input_epoch_seconds": 1_672_531_200,
                "expected_created_at": "2023-01-01T00:00:00Z",
                "event_terminal_status": "SUCCEEDED",
                "readback_result_count": 1,
                "persisted_created_at": "2023-01-01T00:00:00Z",
                "delta_seconds": 0.0,
                "cleanup_succeeded": True,
                "failure_code": None,
            },
        },
        "refresh_binding": {
            "status": "passed",
            "run_id_sha256": hashlib.sha256(run_id.encode()).hexdigest(),
            "probe_nonce_sha256": hashlib.sha256(RUNTIME_NONCE.encode()).hexdigest(),
            "target_identity_sha256": target_identity_sha256,
            "refreshed_at": checked_at,
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    binding = manifest["refresh_binding"]
    assert isinstance(binding, dict)
    message = "\n".join(
        (
            "mem0-benchmark-runtime-witness.v1",
            str(binding["run_id_sha256"]),
            str(binding["probe_nonce_sha256"]),
            str(binding["target_identity_sha256"]),
            str(binding["refreshed_at"]),
            fingerprint,
        )
    ).encode()
    token = "managed-locomo-sandbox-token"
    manifest["refresh_witness"] = {
        "algorithm": "hmac-sha256",
        "manifest_fingerprint_sha256": fingerprint,
        "signature": hmac.new(token.encode(), message, hashlib.sha256).hexdigest(),
    }
    verified = build_verified_mem0_runtime_attestation(
        runtime_manifest=manifest,
        benchmark_probe_token=token,
        openapi_fingerprint_sha256="d" * 64,
        openapi_contract_violations=(),
        probe_passed=True,
        run_id=run_id,
        probe_nonce=RUNTIME_NONCE,
        target_identity_sha256=target_identity_sha256,
    )
    assert verified is not None
    validation = validate_mem0_runtime_attestation_for_backends(
        verified,
        (
            _RuntimeBackend(INFINITY_BACKEND),
            _RuntimeBackend(MEM0_BACKEND, target_identity_sha256),
        ),
        run_id,
        RUNTIME_NONCE,
        validated_at=observed_at,
    )
    assert type(validation) is VerifiedMem0RuntimeAttestationValidation
    assert public_mem0_runtime_attestation_validation(validation)["eligible"] is True
    return validation


def _clean_state_bundle(run_id: str) -> CleanStateBundle:
    clean_key = hashlib.sha256(f"{run_id}:clean-state".encode()).digest()
    corpus = clean_state_identity_sha256("sandbox-locomo-1")
    infinity_scope = clean_state_identity_sha256("managed-locomo-fresh-space")
    mem0_scope = clean_state_identity_sha256("managed-locomo-private-user")
    validation = validate_typed_clean_state_proofs(
        {
            INFINITY_BACKEND: (
                fresh_namespace_clean_state_proof(
                    backend=INFINITY_BACKEND,
                    run_id=run_id,
                    expected_slug="managed-locomo-fresh-space",
                    corpus_identity_sha256=corpus,
                    expected_scope_count=1,
                    status_code=201,
                    payload={"data": {"slug": "managed-locomo-fresh-space"}},
                    attestation_key=clean_key,
                ),
            ),
            MEM0_BACKEND: (
                mem0_delete_clean_state_proof(
                    run_id=run_id,
                    scope_identity="managed-locomo-private-user",
                    corpus_identity_sha256=corpus,
                    expected_scope_count=1,
                    status_code=200,
                    payload={"deleted": True, "verified_absent": True},
                    attestation_key=clean_key,
                ),
            ),
        },
        expected_run_id_sha256=clean_state_identity_sha256(run_id),
        expected_scopes_by_backend={
            INFINITY_BACKEND: {corpus: infinity_scope},
            MEM0_BACKEND: {corpus: mem0_scope},
        },
        attestation_key=clean_key,
    )
    return CleanStateBundle(
        validation,
        (
            FullExecutionCleanScope(INFINITY_BACKEND, corpus, infinity_scope),
            FullExecutionCleanScope(MEM0_BACKEND, corpus, mem0_scope),
        ),
        clean_key,
    )


__all__ = (
    "SandboxRuntimePorts",
    "build_runtime_ports",
)

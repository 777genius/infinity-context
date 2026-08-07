"""One-shot authenticated pre-dispatch readback of every sealed Mem0 scope."""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Callable
from pathlib import Path

from mem0_oss_adapter_v5.app import AdapterServiceError
from mem0_oss_adapter_v5.domain import canonical_json_bytes, canonical_sha256
from mem0_oss_adapter_v5.http_models import (
    CleanStateCorpusScope,
    CleanStateRequest,
    CleanStateResponse,
)
from mem0_oss_adapter_v5.mem0_storage import (
    Mem0StorageBackend,
    StorageScope,
    independent_clean_state_snapshot,
)
from mem0_oss_adapter_v5.sealed_manifest import InputUnit, SealedInputManifest
from mem0_oss_adapter_v5.state_sqlite import OperationState, SqliteOperationState
from mem0_oss_adapter_v5.subscription_runtime import SUBSCRIPTION_RUNTIME_ROUTE_SHA256

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_KEY_DOMAIN = b"mem0-oss-adapter-v5/evidence-key/v1"
_SIGNATURE_DOMAIN = b"clean-state/v1"
_ADMISSION_SCHEMA = "mem0-benchmark-full-run.v5"
_AUTHORITY_SCHEMA = "managed-mem0-v5-manifest.v1"
_SEALED_SCHEMA = "mem0-oss-adapter-v5.sealed-input.v2"


class AuthenticatedCleanStateService:
    """Reads real storage once and seals the original zero-state witness."""

    def __init__(
        self,
        *,
        manifest: SealedInputManifest,
        state: SqliteOperationState,
        backend: Mem0StorageBackend,
        current_admission: Callable[[], str | None],
        runtime_binding_commitment_sha256: str,
        runtime_source_sha256: str,
        evidence_directory: Path,
        hmac_key: bytes,
    ) -> None:
        if type(hmac_key) is not bytes or len(hmac_key) < 32:
            raise ValueError("adapter_configuration_invalid")
        self._manifest = manifest
        self._state = state
        self._backend = backend
        self._current_admission = current_admission
        self._runtime_binding = runtime_binding_commitment_sha256
        self._runtime_source = runtime_source_sha256
        self._evidence_path = evidence_directory / "clean-state.json"
        root = hmac.new(hmac_key, _KEY_DOMAIN, hashlib.sha256).digest()
        self._signing_key = hmac.new(root, _SIGNATURE_DOMAIN, hashlib.sha256).digest()

    def prove_empty(
        self,
        request: CleanStateRequest,
        *,
        idempotency_key: str,
        request_commitment_sha256: str,
    ) -> CleanStateResponse:
        self._require_binding(request)
        if self._evidence_path.exists():
            raise AdapterServiceError("clean_state_conflict")
        self._require_pre_dispatch_state()
        expected_scopes = self._expected_scopes(request.admission_commitment_sha256)
        if request.scopes != expected_scopes:
            raise AdapterServiceError("clean_state_binding_invalid", status_code=400)
        try:
            for unit in self._manifest.units:
                snapshot = independent_clean_state_snapshot(
                    self._backend,
                    scope=StorageScope(
                        user_id=unit.corpus_id,
                        run_id=request.admission_commitment_sha256,
                        source_id=unit.source_id,
                        source_sha256=unit.source_sha256,
                    ),
                )
                if not snapshot.empty:
                    raise AdapterServiceError("clean_state_not_empty")
        except AdapterServiceError:
            raise
        except Exception:
            raise AdapterServiceError("clean_state_failed", status_code=503) from None
        self._require_pre_dispatch_state()
        base = {
            "schema_version": "mem0-oss-adapter-v5.clean-state.v1",
            "admission_commitment_sha256": request.admission_commitment_sha256,
            "run_id_sha256": request.run_id_sha256,
            "authority_commitment_sha256": request.authority_commitment_sha256,
            "ingestion_manifest_sha256": self._manifest.ingestion_manifest_sha256,
            "ingestion_root_sha256": self._manifest.ingestion_root_sha256,
            "runtime_binding_commitment_sha256": self._runtime_binding,
            "request_commitment_sha256": request_commitment_sha256,
            "request_id_sha256": idempotency_key,
            "scope_count": len(expected_scopes),
            "scope_inventory_root_sha256": canonical_sha256(
                {"scopes": [item.model_dump(mode="json") for item in expected_scopes]}
            ),
            "scopes": [item.model_dump(mode="json") for item in expected_scopes],
        }
        signed = {
            **base,
            "evidence_commitment_sha256": canonical_sha256(base),
        }
        payload = {
            **signed,
            "clean_state_hmac_sha256": _signature(self._signing_key, signed),
        }
        response = CleanStateResponse.model_validate(payload)
        try:
            _write_once(self._evidence_path, canonical_json_bytes(payload))
        except FileExistsError:
            raise AdapterServiceError("clean_state_conflict") from None
        except OSError:
            raise AdapterServiceError("clean_state_failed", status_code=503) from None
        return response

    def _require_binding(self, request: CleanStateRequest) -> None:
        if self._current_admission() != request.admission_commitment_sha256:
            raise AdapterServiceError("run_not_found", status_code=404)
        if (
            request.runtime_binding_commitment_sha256 != self._runtime_binding
            or request.runtime_source_sha256 != self._runtime_source
        ):
            raise AdapterServiceError("clean_state_binding_invalid", status_code=400)
        sealed_payload_sha256 = self._sealed_payload_sha256()
        grouped = self._grouped_units()
        authority = canonical_sha256(
            {
                "schema_version": _AUTHORITY_SCHEMA,
                "case_count": request.manifest_case_count,
                "corpus_count": len(grouped),
                "operation_count": len(self._manifest.units),
                "ingestion_manifest_sha256": self._manifest.ingestion_manifest_sha256,
                "ingestion_root_sha256": self._manifest.ingestion_root_sha256,
                "sealed_payload_sha256": sealed_payload_sha256,
            }
        )
        admission = canonical_sha256(
            {
                "schema_version": _ADMISSION_SCHEMA,
                "run_id_sha256": request.run_id_sha256,
                "ingestion_manifest_sha256": self._manifest.ingestion_manifest_sha256,
                "ingestion_root_sha256": self._manifest.ingestion_root_sha256,
                "ingestion_unit_count": len(self._manifest.units),
                "route_sha256": SUBSCRIPTION_RUNTIME_ROUTE_SHA256,
                "credential_binding_sha256": request.credential_binding_sha256,
                "model": "gpt-5.6-sol",
                "reasoning_effort": "high",
                "service_tier": "default",
                "runtime_source_revision": request.runtime_source_revision,
                "runtime_source_sha256": request.runtime_source_sha256,
                "runtime_base_sha256": request.runtime_base_sha256,
                "expected_operation_count": len(self._manifest.units),
                "retries": 0,
                "extraction_calls_per_unit": 1,
            }
        )
        if (
            request.manifest_case_count < len(grouped)
            or authority != request.authority_commitment_sha256
            or admission != request.admission_commitment_sha256
        ):
            raise AdapterServiceError("clean_state_binding_invalid", status_code=400)

    def _require_pre_dispatch_state(self) -> None:
        try:
            if any(
                self._state.get(unit.unit_identity_sha256).state is not OperationState.ADMITTED
                for unit in self._manifest.units
            ):
                raise AdapterServiceError("clean_state_conflict")
        except AdapterServiceError:
            raise
        except Exception:
            raise AdapterServiceError("clean_state_failed", status_code=503) from None

    def _expected_scopes(self, admission: str) -> tuple[CleanStateCorpusScope, ...]:
        values = []
        for corpus_id, units in self._grouped_units():
            source_scopes = [
                {"source_id": unit.source_id, "source_sha256": unit.source_sha256} for unit in units
            ]
            source_root = canonical_sha256({"source_scopes": source_scopes})
            values.append(
                CleanStateCorpusScope(
                    corpus_identity_sha256=canonical_sha256({"corpus_id": corpus_id}),
                    scope_identity_sha256=canonical_sha256(
                        {
                            "admission_commitment_sha256": admission,
                            "corpus_id": corpus_id,
                            "source_scope_root_sha256": source_root,
                        }
                    ),
                    source_scope_count=len(units),
                    residual_record_count=0,
                    residual_root_sha256=_EMPTY_SHA256,
                )
            )
        return tuple(values)

    def _grouped_units(self) -> tuple[tuple[str, tuple[InputUnit, ...]], ...]:
        grouped: dict[str, list[InputUnit]] = {}
        seen_sources: set[tuple[str, str, str]] = set()
        for unit in self._manifest.units:
            source_scope = (unit.corpus_id, unit.source_id, unit.source_sha256)
            if source_scope in seen_sources:
                raise AdapterServiceError("clean_state_failed", status_code=503)
            seen_sources.add(source_scope)
            grouped.setdefault(unit.corpus_id, []).append(unit)
        return tuple((key, tuple(value)) for key, value in grouped.items())

    def _sealed_payload_sha256(self) -> str:
        unsigned = {
            "schema_version": _SEALED_SCHEMA,
            "ingestion_manifest_sha256": self._manifest.ingestion_manifest_sha256,
            "ingestion_root_sha256": self._manifest.ingestion_root_sha256,
            "current_date": self._manifest.current_date,
            "units": [
                {
                    "sequence": unit.sequence,
                    "unit_identity_sha256": unit.unit_identity_sha256,
                    "unit_sha256": unit.unit_sha256,
                    "source_sha256": unit.source_sha256,
                    "scope_sha256": unit.scope_sha256,
                    "corpus_id": unit.corpus_id,
                    "source_id": unit.source_id,
                    "observation_date": unit.observation_date,
                    "source_messages": list(unit.source_messages),
                }
                for unit in self._manifest.units
            ],
        }
        return canonical_sha256(unsigned)


def verify_clean_state_response(response: CleanStateResponse, *, hmac_key: bytes) -> bool:
    """Verify the complete public response for adapter-side and HTTP contract tests."""

    if type(hmac_key) is not bytes or len(hmac_key) < 32:
        return False
    payload = response.model_dump(mode="json")
    presented = payload.pop("clean_state_hmac_sha256")
    evidence = payload.pop("evidence_commitment_sha256")
    if evidence != canonical_sha256(payload):
        return False
    if payload["scope_inventory_root_sha256"] != canonical_sha256({"scopes": payload["scopes"]}):
        return False
    signed = {**payload, "evidence_commitment_sha256": evidence}
    root = hmac.new(hmac_key, _KEY_DOMAIN, hashlib.sha256).digest()
    key = hmac.new(root, _SIGNATURE_DOMAIN, hashlib.sha256).digest()
    return hmac.compare_digest(_signature(key, signed), presented)


def _signature(key: bytes, payload: dict[str, object]) -> str:
    return hmac.new(key, canonical_json_bytes(payload), hashlib.sha256).hexdigest()


def _write_once(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


__all__ = (
    "AuthenticatedCleanStateService",
    "verify_clean_state_response",
)

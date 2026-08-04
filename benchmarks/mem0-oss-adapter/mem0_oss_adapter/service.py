"""Provider-neutral verification workflow for the isolated Mem0 OSS adapter."""

from __future__ import annotations

import hashlib
import secrets
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from mem0_oss_adapter.models import AddRequest, SearchRequest, TimestampAttestation
from mem0_oss_adapter.port import OssPort

_Mode = Literal["raw_passthrough", "subscription_llm"]


class AdapterError(RuntimeError):
    """Sanitized error boundary for untrusted SDK and storage responses."""

    status_code = 502
    code = "mem0_oss_operation_failed"


class SourceReadbackError(AdapterError):
    code = "mem0_oss_source_readback_failed"


class DeleteVerificationError(AdapterError):
    code = "mem0_oss_delete_verification_failed"


@dataclass(frozen=True, slots=True)
class DeleteVerification:
    deleted: bool
    verified_absent: bool


@dataclass(frozen=True, slots=True)
class PersistedMemoryIdentityProof:
    memory_id: str
    source_id: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class AddVerification:
    request_id: str
    results: tuple[PersistedMemoryIdentityProof, ...]


class OssCompatibilityService:
    """Verifies metadata timestamp and source identity through the actual provider port."""

    def __init__(self, port: OssPort, *, token_factory: Any = secrets.token_hex) -> None:
        self._port = port
        self._token_factory = token_factory
        self._source_transaction_lock = threading.RLock()
        self.attestation = TimestampAttestation()

    @property
    def configured(self) -> bool:
        return self._port.configured

    @property
    def extraction_mode(self) -> _Mode:
        return self._port.extraction_mode

    def add(self, request: AddRequest) -> AddVerification:
        return self._add_and_readback(request)

    def search(self, request: SearchRequest) -> list[dict[str, Any]]:
        self._require_configured()
        try:
            payload = self._port.search(
                query=request.query,
                filters=request.filters,
                top_k=request.limit,
            )
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError("Mem0 OSS search failed") from exc
        return _sanitize_search_results(payload)

    def delete(self, *, user_id: str, run_id: str) -> DeleteVerification:
        self._require_configured()
        try:
            acknowledged = self._port.delete_memories(user_id=user_id, run_id=run_id)
        except Exception as exc:
            raise DeleteVerificationError("Mem0 OSS delete failed") from exc
        if acknowledged is not True:
            raise DeleteVerificationError("Mem0 OSS delete was not acknowledged")
        try:
            payload = self._port.get_all(filters=_entity_filters(user_id, run_id), limit=1000)
        except Exception as exc:
            raise DeleteVerificationError("Mem0 OSS delete readback failed") from exc
        try:
            remaining = _result_items(payload)
        except AdapterError as exc:
            raise DeleteVerificationError("Mem0 OSS delete readback was invalid") from exc
        if remaining:
            raise DeleteVerificationError("Mem0 OSS delete scope remains present")
        return DeleteVerification(deleted=True, verified_absent=True)

    def attest_timestamp(self) -> TimestampAttestation:
        """Run a raw, isolated write/read/delete witness with no extraction call."""

        checked_at = _utc_now()
        token = self._safe_token()
        user_id = f"mem0-attest-user-{token}"
        run_id = f"mem0-attest-run-{token}"
        source_id = f"mem0-attest-source-{token}"
        sentinel = "Mem0 OSS timestamp attestation sentinel."
        request = AddRequest(
            messages=[{"role": "user", "content": sentinel}],
            user_id=user_id,
            run_id=run_id,
            metadata={
                "source_id": source_id,
                "source_sha256": hashlib.sha256(sentinel.encode()).hexdigest(),
                "benchmark_probe": True,
            },
            timestamp=1_672_531_200,
        )
        passed = False
        cleanup_succeeded: bool | None = None
        try:
            self._add_and_readback(request, mode_override="raw_passthrough")
            passed = True
        except Exception:
            passed = False
        try:
            cleanup_succeeded = self.delete(user_id=user_id, run_id=run_id).verified_absent
        except Exception:
            cleanup_succeeded = False
        passed = passed and cleanup_succeeded is True
        self.attestation = TimestampAttestation(
            status="passed" if passed else "failed",
            checked_at=checked_at,
            metadata_created_at_roundtrip_attested=passed,
            cleanup_succeeded=cleanup_succeeded,
        )
        return self.attestation

    def _add_and_readback(
        self,
        request: AddRequest,
        *,
        mode_override: _Mode | None = None,
    ) -> AddVerification:
        with self._source_transaction_lock:
            return self._add_and_readback_locked(request, mode_override=mode_override)

    def _add_and_readback_locked(
        self,
        request: AddRequest,
        *,
        mode_override: _Mode | None,
    ) -> AddVerification:
        self._require_configured()
        source_id = str(request.metadata["source_id"])
        source_sha256 = str(request.metadata["source_sha256"])
        filters = _source_filters(
            user_id=request.user_id,
            run_id=request.run_id,
            source_id=source_id,
            source_sha256=source_sha256,
        )
        try:
            existing = _result_items(self._port.get_all(filters=filters, limit=1000))
        except AdapterError:
            raise
        except Exception as exc:
            raise SourceReadbackError("Mem0 OSS source preflight failed") from exc
        if existing:
            raise SourceReadbackError("Mem0 OSS source identity is already present for this run")

        effective_mode = mode_override or self._port.extraction_mode
        try:
            add_payload = self._port.add(
                messages=[message.model_dump() for message in request.messages],
                user_id=request.user_id,
                agent_id=request.agent_id,
                run_id=request.run_id,
                metadata=request.metadata,
                timestamp=request.timestamp,
                mode_override=mode_override,
            )
            created_ids = _created_memory_ids(add_payload)
            readback = self._port.get_all(filters=filters, limit=1000)
            persisted = _prove_persisted_results(
                _result_items(readback),
                created_ids=created_ids,
                source_id=source_id,
                source_sha256=source_sha256,
                expected_created_at=_timestamp_created_at(request.timestamp),
            )
        except Exception as exc:
            self._compensate_source_failure(
                user_id=request.user_id,
                run_id=request.run_id,
                source_id=source_id,
                source_sha256=source_sha256,
                full_scope=effective_mode == "subscription_llm",
            )
            if isinstance(exc, AdapterError):
                raise
            raise AdapterError("Mem0 OSS add or source readback failed") from exc
        request_id = _request_id(add_payload, created_ids)
        return AddVerification(request_id=request_id, results=tuple(persisted))

    def _compensate_source_failure(
        self,
        *,
        user_id: str,
        run_id: str,
        source_id: str,
        source_sha256: str,
        full_scope: bool,
    ) -> None:
        try:
            acknowledged = self._port.delete_source_memories(
                user_id=user_id,
                run_id=run_id,
                source_id=source_id,
                source_sha256=source_sha256,
            )
        except Exception as exc:
            raise DeleteVerificationError("Mem0 OSS post-write rollback failed") from exc
        if acknowledged is not True:
            raise DeleteVerificationError("Mem0 OSS post-write rollback was not acknowledged")
        try:
            remaining = _result_items(
                self._port.get_all(
                    filters=_source_filters(
                        user_id=user_id,
                        run_id=run_id,
                        source_id=source_id,
                        source_sha256=source_sha256,
                    ),
                    limit=1000,
                )
            )
        except Exception as exc:
            raise DeleteVerificationError("Mem0 OSS post-write rollback readback failed") from exc
        if remaining:
            raise DeleteVerificationError("Mem0 OSS post-write rollback left source rows")
        if full_scope:
            try:
                acknowledged = self._port.delete_memories(user_id=user_id, run_id=run_id)
            except Exception as exc:
                raise DeleteVerificationError("Mem0 OSS subscription rollback failed") from exc
            if acknowledged is not True:
                raise DeleteVerificationError("Mem0 OSS subscription rollback was not acknowledged")
            try:
                remaining_scope = _result_items(
                    self._port.get_all(
                        filters=_entity_filters(user_id, run_id),
                        limit=1000,
                    )
                )
            except Exception as exc:
                raise DeleteVerificationError(
                    "Mem0 OSS subscription rollback readback failed"
                ) from exc
            if remaining_scope:
                raise DeleteVerificationError("Mem0 OSS subscription rollback left scope rows")

    def _require_configured(self) -> None:
        if not self._port.configured:
            error = AdapterError("Mem0 OSS runtime is unconfigured")
            error.status_code = 503
            error.code = "missing_mem0_oss_runtime_configuration"
            raise error

    def _safe_token(self) -> str:
        try:
            token = self._token_factory(12)
        except TypeError:
            token = self._token_factory()
        if (
            not isinstance(token, str)
            or not token
            or any(char not in "0123456789abcdef" for char in token)
        ):
            raise RuntimeError("attestation token factory is invalid")
        return token


def _entity_filters(user_id: str, run_id: str) -> dict[str, str]:
    return {"user_id": user_id, "run_id": run_id}


def _source_filters(
    *,
    user_id: str,
    run_id: str,
    source_id: str,
    source_sha256: str,
) -> dict[str, str]:
    return {
        "user_id": user_id,
        "run_id": run_id,
        "source_id": source_id,
        "source_sha256": source_sha256,
    }


def _result_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = payload.get("results")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise SourceReadbackError("Mem0 OSS response has no result list")
    if any(not isinstance(item, Mapping) for item in raw):
        raise SourceReadbackError("Mem0 OSS response result is malformed")
    return list(raw)


def _prove_persisted_results(
    rows: Sequence[Mapping[str, Any]],
    *,
    created_ids: Sequence[str],
    source_id: str,
    source_sha256: str,
    expected_created_at: str,
) -> list[PersistedMemoryIdentityProof]:
    expected_ids = set(created_ids)
    observed_ids = {row.get("id") for row in rows if isinstance(row.get("id"), str)}
    if (
        not rows
        or len(rows) != len(created_ids)
        or len(expected_ids) != len(created_ids)
        or observed_ids != expected_ids
    ):
        raise SourceReadbackError("Mem0 OSS source readback is empty")
    proofs: list[PersistedMemoryIdentityProof] = []
    ids: set[str] = set()
    for row in rows:
        memory_id = row.get("id")
        metadata = row.get("metadata")
        if (
            not isinstance(memory_id, str)
            or not memory_id
            or not isinstance(metadata, Mapping)
            or metadata.get("source_id") != source_id
            or metadata.get("source_sha256") != source_sha256
            or row.get("created_at") != expected_created_at
            or (
                metadata.get("created_at") is not None
                and metadata.get("created_at") != expected_created_at
            )
            or memory_id in ids
        ):
            raise SourceReadbackError("Mem0 OSS source identity did not round trip")
        ids.add(memory_id)
        proofs.append(
            PersistedMemoryIdentityProof(
                memory_id=memory_id,
                source_id=source_id,
                source_sha256=source_sha256,
            )
        )
    return proofs


def _created_memory_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    rows = _result_items(payload)
    ids = tuple(row.get("id") for row in rows)
    if not ids or any(not isinstance(memory_id, str) or not memory_id for memory_id in ids):
        raise SourceReadbackError("Mem0 OSS add response did not identify created memories")
    if len(ids) != len(set(ids)):
        raise SourceReadbackError("Mem0 OSS add response repeated a created memory id")
    return ids


def _request_id(
    payload: Mapping[str, Any],
    created_ids: Sequence[str],
) -> str:
    candidate = payload.get("request_id") or payload.get("id")
    if isinstance(candidate, str) and candidate:
        return candidate
    return created_ids[0]


def _sanitize_search_results(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _result_items(payload)
    sanitized: list[dict[str, Any]] = []
    for row in rows:
        candidate: dict[str, Any] = {}
        if isinstance(row.get("id"), str) and row["id"]:
            candidate["id"] = row["id"]
        if isinstance(row.get("memory"), str):
            candidate["memory"] = row["memory"]
        score = row.get("score")
        if type(score) in {int, float}:
            candidate["score"] = float(score)
        if isinstance(row.get("created_at"), str):
            candidate["created_at"] = row["created_at"]
        metadata = row.get("metadata")
        if isinstance(metadata, Mapping):
            identity = {
                key: metadata[key]
                for key in ("source_id", "source_sha256", "created_at")
                if isinstance(metadata.get(key), str)
            }
            if identity:
                candidate["metadata"] = identity
        sanitized.append(candidate)
    return sanitized


def _timestamp_created_at(timestamp: int) -> str:
    value = datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")
    return value.replace("+00:00", "Z")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

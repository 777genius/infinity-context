"""Exact LoCoMo observations at the mem0 OSS wrapper HTTP boundary."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from threading import RLock
from typing import NamedTuple

import httpx

from infinity_context_server.memory_comparison_locomo_expected_turn import (
    ExpectedOfficialLocomoTurn,
    canonical_locomo_source_id,
)
from infinity_context_server.memory_comparison_locomo_transport import (
    LOCOMO_OFFICIAL_INGEST_MODE,
    LocomoOfficialTurnsTransportRequest,
    LocomoTimestampTransportEvidence,
    RunScopedLocomoTransportEvidenceKey,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

MEM0_HTTP_OBSERVATION_BOUNDARY = "mem0_oss_wrapper_http_client_transport"
MEM0_HTTP_OBSERVED_REPRESENTATION = "decoded_json_canonical_projection"
_EXPECTED_REQUEST_KEYS = {
    "messages",
    "user_id",
    "run_id",
    "metadata",
    "timestamp",
}
_OBSERVATION_CONTEXT_EXTENSION = "infinity_context.mem0_observation_context"
_EVIDENCE_EXTENSION = "infinity_context.mem0_locomo_transport_evidence"
_MANAGED_TRIGGER_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class _RequestObservationContext(NamedTuple):
    run_id: str
    generation: int
    verifier: RunScopedLocomoTransportEvidenceKey
    expected_turn: ExpectedOfficialLocomoTurn
    public_trigger_case_id: str | None


class Mem0HttpObservationRecorder:
    """Own thread-safe run observations and reset-fenced HTTP completions."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._generations: dict[str, int] = {}
        self._verifiers: dict[str, RunScopedLocomoTransportEvidenceKey] = {}
        self._evidence: dict[str, list[LocomoTimestampTransportEvidence]] = {}

    def reset(self, *, run_id: str) -> None:
        with self._lock:
            self._generations[run_id] = self._generations.get(run_id, 0) + 1
            self._verifiers.pop(run_id, None)
            self._evidence.pop(run_id, None)

    def prepare_request(
        self,
        request: httpx.Request,
        *,
        run_id: str,
        expected_turn: ExpectedOfficialLocomoTurn,
        public_trigger_case_id: str | None = None,
    ) -> None:
        public_trigger = _validated_public_trigger_case_id(public_trigger_case_id)
        with self._lock:
            generation = self._generations.get(run_id, 0)
            verifier = self._verifiers.get(run_id)
            if verifier is None:
                verifier = RunScopedLocomoTransportEvidenceKey.generate(run_id=run_id)
                self._verifiers[run_id] = verifier
            request.extensions[_OBSERVATION_CONTEXT_EXTENSION] = _RequestObservationContext(
                run_id=run_id,
                generation=generation,
                verifier=verifier,
                expected_turn=expected_turn,
                public_trigger_case_id=public_trigger,
            )

    def observe_at_transport_boundary(self, request: httpx.Request) -> None:
        context = request.extensions.get(_OBSERVATION_CONTEXT_EXTENSION)
        if context is None:
            return
        if type(context) is not _RequestObservationContext:
            raise ValueError("mem0 HTTP observation context is invalid")
        request.extensions[_EVIDENCE_EXTENSION] = observe_mem0_add_request(
            request,
            expected_turn=context.expected_turn,
            verifier=context.verifier,
            public_trigger_case_id=context.public_trigger_case_id,
        )

    def record_completed_request(self, request: httpx.Request, *, run_id: str) -> bool:
        context = request.extensions.pop(_OBSERVATION_CONTEXT_EXTENSION, None)
        evidence = request.extensions.pop(_EVIDENCE_EXTENSION, None)
        if context is None and evidence is None:
            return False
        if (
            type(context) is not _RequestObservationContext
            or type(evidence) is not LocomoTimestampTransportEvidence
            or context.run_id != run_id
        ):
            raise ValueError("mem0 HTTP transport completion context is invalid")
        with self._lock:
            current_generation = self._generations.get(run_id, 0)
            current_verifier = self._verifiers.get(run_id)
            if context.generation != current_generation or context.verifier is not current_verifier:
                raise ValueError("stale mem0 HTTP transport completion after reset")
            self._evidence.setdefault(run_id, []).append(evidence)
            return True

    def verifier(self, *, run_id: str) -> RunScopedLocomoTransportEvidenceKey | None:
        with self._lock:
            return self._verifiers.get(run_id)

    def evidence(
        self,
        *,
        run_id: str,
    ) -> tuple[LocomoTimestampTransportEvidence, ...]:
        with self._lock:
            return tuple(self._evidence.get(run_id, ()))

    def evidence_count(self, *, run_id: str) -> int:
        with self._lock:
            return len(self._evidence.get(run_id, ()))


def expected_official_locomo_turn_for_group(
    case: PublicBenchmarkCase,
    *,
    group_index: int,
    run_id: str,
    corpus_key: str,
) -> ExpectedOfficialLocomoTurn | None:
    """Build the sealed provider-neutral loader projection before HTTP mapping."""

    if case.metadata.get("locomo_ingest_mode") != LOCOMO_OFFICIAL_INGEST_MODE:
        return None
    if case.benchmark != "locomo":
        raise ValueError("official-turns ingestion requires the locomo benchmark")
    if case.conversations or case.documents:
        raise ValueError("official-turns ingestion must contain only turn memories")
    if type(group_index) is not int or not 1 <= group_index <= len(case.memories):
        raise ValueError("official-turns group does not map to exactly one loader turn")

    memory = case.memories[group_index - 1]
    metadata = memory.metadata
    source_external_id = memory.source_external_id
    if type(source_external_id) is not str:
        raise ValueError("official LoCoMo turn requires source_external_id")
    timestamp = metadata.get("timestamp")
    if type(timestamp) is not int:
        raise ValueError("official LoCoMo turn requires an exact integer timestamp")
    return ExpectedOfficialLocomoTurn.create(
        run_id=run_id,
        corpus_key=corpus_key,
        source_external_id=source_external_id,
        source_id=canonical_locomo_source_id(source_external_id),
        session_key=_exact_string(metadata, "session_key"),
        dia_id=_exact_string(metadata, "dia_id"),
        speaker=_exact_string(metadata, "speaker"),
        session_date=_exact_string(metadata, "session_date"),
        trigger_case_id=case.case_id,
        role=_exact_string(metadata, "role"),
        content=memory.text,
        timestamp=timestamp,
    )


def observe_mem0_add_request(
    request: httpx.Request,
    *,
    expected_turn: ExpectedOfficialLocomoTurn,
    verifier: RunScopedLocomoTransportEvidenceKey,
    public_trigger_case_id: str | None = None,
) -> LocomoTimestampTransportEvidence:
    """Observe wrapper HTTP JSON, without claiming downstream SDK wire bytes."""

    if request.method != "POST" or request.url.path != "/memories":
        raise ValueError("expected the mem0 OSS wrapper POST /memories boundary")
    content_type = request.headers.get("Content-Type", "").partition(";")[0].strip().lower()
    if content_type != "application/json":
        raise ValueError("mem0 AddRequest must use application/json")
    payload = _exact_json_object(request.content)
    if set(payload) != _EXPECTED_REQUEST_KEYS:
        raise ValueError("observed mem0 AddRequest fields are not exact")

    messages = payload["messages"]
    metadata = payload["metadata"]
    idempotency_key = request.headers.get("Idempotency-Key")
    if type(messages) is not list or any(type(message) is not dict for message in messages):
        raise ValueError("observed mem0 messages must be exact JSON objects")
    if type(metadata) is not dict:
        raise ValueError("observed mem0 metadata must be an exact JSON object")
    if type(idempotency_key) is not str:
        raise ValueError("observed mem0 AddRequest requires Idempotency-Key")

    projection = LocomoOfficialTurnsTransportRequest.create(
        messages=messages,
        user_id=_payload_string(payload, "user_id"),
        run_id=_payload_string(payload, "run_id"),
        metadata=metadata,
        timestamp=_payload_int(payload, "timestamp"),
        idempotency_key=idempotency_key,
    )
    return verifier.issue(
        projection,
        expected_turn=expected_turn,
        public_trigger_case_id=_validated_public_trigger_case_id(public_trigger_case_id),
    )


def _validated_public_trigger_case_id(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or _MANAGED_TRIGGER_CASE_ID.fullmatch(value) is None:
        raise ValueError("managed public trigger case_id is invalid")
    return value


def mem0_http_observation_metadata(
    *,
    required: bool,
    evidence_count: int,
) -> dict[str, object]:
    """Describe exactly what runtime evidence does and does not attest."""

    if type(required) is not bool:
        raise ValueError("required must be an exact boolean")
    if type(evidence_count) is not int or evidence_count < 0:
        raise ValueError("evidence_count must be a non-negative exact integer")
    return {
        "required": required,
        "evidence_count": evidence_count,
        "boundary": MEM0_HTTP_OBSERVATION_BOUNDARY,
        "observed_representation": MEM0_HTTP_OBSERVED_REPRESENTATION,
        "downstream_provider_sdk_wire_bytes_observed": False,
    }


def _exact_json_object(payload: object) -> dict[str, object]:
    if type(payload) is not bytes or not payload:
        raise ValueError("observed mem0 AddRequest body must be non-empty exact bytes")
    try:
        parsed = json.loads(payload, object_pairs_hook=_exact_object_pairs)
    except (TypeError, ValueError, UnicodeDecodeError) as error:
        raise ValueError("observed mem0 AddRequest body is malformed") from error
    if type(parsed) is not dict:
        raise ValueError("observed mem0 AddRequest body must be an exact JSON object")
    return parsed


def _exact_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("observed mem0 AddRequest contains a duplicate field")
        result[key] = value
    return result


def _exact_string(metadata: Mapping[str, object], key: str) -> str:
    value = metadata.get(key)
    if type(value) is not str:
        raise ValueError(f"official LoCoMo turn requires exact {key}")
    return value


def _payload_string(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    if type(value) is not str:
        raise ValueError(f"observed mem0 AddRequest {key} must be an exact string")
    return value


def _payload_int(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    if type(value) is not int:
        raise ValueError(f"observed mem0 AddRequest {key} must be an exact integer")
    return value


__all__ = (
    "MEM0_HTTP_OBSERVATION_BOUNDARY",
    "MEM0_HTTP_OBSERVED_REPRESENTATION",
    "Mem0HttpObservationRecorder",
    "expected_official_locomo_turn_for_group",
    "mem0_http_observation_metadata",
    "observe_mem0_add_request",
)

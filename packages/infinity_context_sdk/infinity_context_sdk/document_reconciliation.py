"""Runtime validation for the exact-document reconciliation SDK surface."""

from __future__ import annotations

from typing import Any

import infinity_context_sdk._payloads as _payloads

CONTRACT_VERSION = "document-reconciliation.v1"
MAX_RESPONSE_BYTES = 65_536
STATES = {
    "present",
    "processing",
    "indexed",
    "deleted_or_proven_absent",
    "conflict",
    "unavailable",
}
VISIBILITY = {"accepted", "processing", "indexed", "not_queryable", "unavailable"}


class InfinityContextDocumentReconciliationMixin:
    """Official read-only exact-document reconciliation surface."""

    def reconcile_exact_document(
        self,
        *,
        capability: dict[str, Any],
        space_id: str,
        memory_scope_id: str,
        source_type: str,
        source_external_id: str,
        thread_id: str | None = None,
        projection_generation: str | None = None,
        profile_generation: str | None = None,
        idempotency_key: str | None = None,
        deadline_ms: int = 5_000,
    ) -> dict[str, Any]:
        validate_capability(capability)
        if (
            not isinstance(deadline_ms, int)
            or isinstance(deadline_ms, bool)
            or not 50 <= deadline_ms <= 10_000
        ):
            raise ValueError("deadline_ms must be between 50 and 10000")
        capability_deadline = capability["exact_reconciliation"]["max_deadline_ms"]
        if not isinstance(capability_deadline, int) or deadline_ms > capability_deadline:
            raise ValueError("deadline_ms exceeds the attested capability")
        for value, maximum, name in (
            (space_id, 80, "space_id"),
            (memory_scope_id, 80, "memory_scope_id"),
            (source_type, 80, "source_type"),
            (source_external_id, 240, "source_external_id"),
        ):
            validate_text(value, max_bytes=maximum, field_name=name)
        for value, maximum, name in (
            (thread_id, 80, "thread_id"),
            (projection_generation, 256, "projection_generation"),
            (profile_generation, 160, "profile_generation"),
            (idempotency_key, 200, "idempotency_key"),
        ):
            if value is not None:
                validate_text(value, max_bytes=maximum, field_name=name)
        payload = _payloads.without_none(
            {
                "contract_version": CONTRACT_VERSION,
                "space_id": space_id,
                "memory_scope_id": memory_scope_id,
                "thread_id": thread_id,
                "source_type": source_type,
                "source_external_id": source_external_id,
                "projection_generation": projection_generation,
                "profile_generation": profile_generation,
                "idempotency_key": idempotency_key,
                "deadline_ms": deadline_ms,
            }
        )
        response = self._request_bounded_json(
            "POST",
            "/v1/documents/reconcile-exact",
            json=payload,
            max_response_bytes=MAX_RESPONSE_BYTES,
            timeout=(deadline_ms + 250) / 1000,
        )
        return validate_response(response, payload)


def validate_capability(value: dict[str, Any]) -> None:
    exact = value.get("exact_reconciliation") if isinstance(value, dict) else None
    if not isinstance(exact, dict):
        raise ValueError("exact document reconciliation capability is required")
    if (
        exact.get("contract_version") != CONTRACT_VERSION
        or exact.get("endpoint") != "/v1/documents/reconcile-exact"
        or exact.get("max_response_bytes") != MAX_RESPONSE_BYTES
        or exact.get("read_only") is not True
        or not isinstance(exact.get("max_deadline_ms"), int)
        or not 50 <= exact["max_deadline_ms"] <= 10_000
    ):
        raise ValueError("exact document reconciliation capability attestation failed")


def validate_response(value: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    data = value.get("data")
    if not isinstance(data, dict) or data.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("exact document reconciliation response is malformed")
    scope = data.get("scope")
    if not isinstance(scope, dict) or any(
        (
            scope.get("space_id") != expected["space_id"],
            scope.get("memory_scope_id") != expected["memory_scope_id"],
            scope.get("thread_id") != expected.get("thread_id"),
            data.get("source_type") != expected["source_type"],
            data.get("source_external_id") != expected["source_external_id"],
        )
    ):
        raise ValueError("exact document reconciliation response identity mismatch")
    state, visibility = data.get("state"), data.get("visibility")
    if state not in STATES or visibility not in VISIBILITY:
        raise ValueError("exact document reconciliation response state is invalid")
    if state == "indexed" and visibility != "indexed":
        raise ValueError("indexed reconciliation lacks indexed visibility evidence")
    if state in {"deleted_or_proven_absent", "conflict", "unavailable"} and visibility == "indexed":
        raise ValueError("non-queryable reconciliation claimed indexed visibility")
    if (
        expected.get("projection_generation") is not None
        and state != "conflict"
        and data.get("projection_generation") != expected["projection_generation"]
    ):
        raise ValueError("exact document reconciliation weakened projection binding")
    if (
        expected.get("profile_generation") is not None
        and state not in {"conflict", "unavailable"}
        and data.get("profile_generation") != expected["profile_generation"]
    ):
        raise ValueError("exact document reconciliation weakened profile binding")
    return value


def validate_text(value: object, *, max_bytes: int, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.encode("utf-8")) > max_bytes
        or any(ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value)
    ):
        raise ValueError(f"{field_name} is invalid")
    return value


__all__ = (
    "CONTRACT_VERSION",
    "InfinityContextDocumentReconciliationMixin",
    "MAX_RESPONSE_BYTES",
    "validate_capability",
    "validate_response",
    "validate_text",
)

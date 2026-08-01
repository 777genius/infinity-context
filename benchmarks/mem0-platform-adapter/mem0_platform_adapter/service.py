"""Bounded event polling and timestamp readback orchestration."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from mem0_platform_adapter.models import AddRequest, SearchRequest, TimestampAttestation
from mem0_platform_adapter.port import PlatformPort
from mem0_platform_adapter.runtime_pin import PLATFORM_API_ORIGIN

_MEMORY_READBACK_PATH = "/v3/memories/"


class AdapterError(RuntimeError):
    status_code = 502
    code = "platform_operation_failed"


class EventTimeoutError(AdapterError):
    status_code = 504
    code = "event_poll_timeout"


class TimestampReadbackError(AdapterError):
    code = "timestamp_readback_failed"

    def __init__(self, message: str, *, attestation_code: str) -> None:
        super().__init__(message)
        self.attestation_code = attestation_code


class ReadbackPaginationError(AdapterError):
    def __init__(self, message: str, *, attestation_code: str) -> None:
        super().__init__(message)
        self.attestation_code = attestation_code


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


@dataclass(frozen=True, slots=True)
class _AddReadback:
    request_id: str
    event_status: str
    persisted: tuple[PersistedMemoryIdentityProof, ...]
    raw_results: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class PollingPolicy:
    max_attempts: int = 60
    interval_seconds: float = 0.5
    timestamp_tolerance_seconds: float = 1.0
    readback_page_size: int = 200
    max_readback_pages: int = 10

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.interval_seconds < 0:
            raise ValueError("interval_seconds must be non-negative")
        if not 1 <= self.readback_page_size <= 200:
            raise ValueError("readback_page_size must be between 1 and 200")
        if self.max_readback_pages < 1:
            raise ValueError("max_readback_pages must be positive")


class Mem0CompatibilityService:
    def __init__(
        self,
        platform: PlatformPort,
        *,
        policy: PollingPolicy | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        token_factory: Callable[[], str] = lambda: secrets.token_hex(12),
    ) -> None:
        self.platform = platform
        self.policy = policy or PollingPolicy()
        self._sleep = sleeper
        self._token_factory = token_factory
        self.attestation = TimestampAttestation(
            failure_code=None if platform.configured else "missing_mem0_api_key"
        )

    def add(self, request: AddRequest) -> AddVerification:
        readback = self._add_and_readback(request)
        if request.timestamp is not None:
            self._verify_timestamp(request, readback.raw_results)
        return AddVerification(request_id=readback.request_id, results=readback.persisted)

    def attest_timestamp(self) -> TimestampAttestation:
        token = self._token_factory()
        user_id = f"mem0-attest-user-{token}"
        run_id = f"mem0-attest-run-{token}"
        source_id = f"mem0-attest-source-{token}"
        request = AddRequest(
            messages=[{"role": "user", "content": "Mem0 timestamp attestation sentinel."}],
            user_id=user_id,
            run_id=run_id,
            metadata={
                "source_id": source_id,
                "source_sha256": hashlib.sha256(
                    b"Mem0 timestamp attestation sentinel."
                ).hexdigest(),
                "benchmark_probe": True,
            },
            timestamp=1672531200,
        )
        event_status: str | None = None
        correlated: list[dict[str, Any]] = []
        observed: list[datetime] = []
        expected = datetime.fromtimestamp(request.timestamp, tz=UTC)
        max_delta: float | None = None
        failure_code: str | None = None
        try:
            readback = self._add_and_readback(request)
            correlated = list(readback.raw_results)
            event_status = readback.event_status
            observed, max_delta = self._verify_timestamp(request, readback.raw_results)
        except TimestampReadbackError as exc:
            failure_code = exc.attestation_code
        except AdapterError as exc:
            failure_code = exc.code
        except Exception:
            failure_code = "attestation_operation_failed"

        cleanup_succeeded = False
        try:
            cleanup_succeeded = self.delete(user_id=user_id, run_id=run_id).verified_absent
        except Exception:
            cleanup_succeeded = False
        if failure_code is None and not cleanup_succeeded:
            failure_code = "cleanup_failed"

        passed = failure_code is None and cleanup_succeeded
        self.attestation = TimestampAttestation(
            status="passed" if passed else "failed",
            checked_at=datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
            input_epoch_seconds=request.timestamp,
            expected_created_at=_iso_z(expected),
            event_terminal_status=event_status.upper() if event_status else None,
            readback_result_count=len(correlated),
            persisted_created_at=_iso_z(observed[0]) if observed else None,
            delta_seconds=max_delta,
            cleanup_succeeded=cleanup_succeeded,
            failure_code=failure_code,
        )
        return self.attestation

    def mark_attestation_failed(self, code: str) -> None:
        self.attestation = TimestampAttestation(
            status="failed",
            checked_at=datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
            cleanup_succeeded=False,
            failure_code=code,
        )

    def _add_and_readback(self, request: AddRequest) -> _AddReadback:
        payload = self.platform.add(
            messages=[message.model_dump() for message in request.messages],
            user_id=request.user_id,
            agent_id=request.agent_id,
            run_id=request.run_id,
            metadata=request.metadata,
            timestamp=request.timestamp,
        )
        event_id = payload.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise AdapterError("Mem0 add response did not include event_id")

        event = self._wait_for_event(event_id)
        source_id = str(request.metadata["source_id"])
        source_sha256 = str(request.metadata["source_sha256"])
        raw_results, persisted = self._readback_source_results(
            filters=_source_filters(request, source_id=source_id),
            source_id=source_id,
            source_sha256=source_sha256,
        )
        return _AddReadback(
            request_id=event_id,
            event_status=event.status,
            persisted=tuple(persisted),
            raw_results=tuple(raw_results),
        )

    def _readback_source_results(
        self,
        *,
        filters: Mapping[str, Any],
        source_id: str,
        source_sha256: str,
    ) -> tuple[list[dict[str, Any]], list[PersistedMemoryIdentityProof]]:
        try:
            results = self._readback_all(filters=filters)
        except ReadbackPaginationError as exc:
            raise TimestampReadbackError(
                str(exc),
                attestation_code=exc.attestation_code,
            ) from exc
        persisted = _prove_persisted_source_results(results, source_id, source_sha256)
        return results, persisted

    def _readback_all(
        self,
        *,
        filters: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        accumulated: list[dict[str, Any]] = []
        expected_count: int | None = None
        page = 1
        visited_pages: set[int] = set()
        for _ in range(self.policy.max_readback_pages):
            if page in visited_pages:
                raise ReadbackPaginationError(
                    "readback pagination repeated a visited page",
                    attestation_code="invalid_source_pagination",
                )
            visited_pages.add(page)
            payload = self.platform.get_all(
                filters=filters,
                page=page,
                page_size=self.policy.readback_page_size,
            )
            page_results = _page_results(payload)
            count = _page_count(payload)
            if count is not None:
                if expected_count is None:
                    expected_count = count
                elif count != expected_count:
                    raise ReadbackPaginationError(
                        "readback count changed between pages",
                        attestation_code="invalid_source_pagination",
                    )
            accumulated.extend(page_results)
            if expected_count is not None and len(accumulated) > expected_count:
                raise ReadbackPaginationError(
                    "readback returned more results than count",
                    attestation_code="invalid_source_pagination",
                )
            next_page = _next_page(
                payload,
                current_page=page,
                page_size=self.policy.readback_page_size,
                visited_pages=visited_pages,
            )
            if next_page is None:
                if expected_count is not None and len(accumulated) != expected_count:
                    raise ReadbackPaginationError(
                        "terminal readback count did not match results",
                        attestation_code="invalid_source_pagination",
                    )
                return accumulated
            if expected_count is not None and len(accumulated) >= expected_count:
                raise ReadbackPaginationError(
                    "readback continuation contradicted count",
                    attestation_code="invalid_source_pagination",
                )
            page = next_page
        raise ReadbackPaginationError(
            "readback exceeded the configured page bound",
            attestation_code="source_readback_page_limit",
        )

    def search(self, request: SearchRequest) -> list[dict[str, Any]]:
        payload = self.platform.search(
            query=request.query,
            filters=request.filters,
            top_k=request.limit,
        )
        return _results(payload)

    def delete(self, *, user_id: str, run_id: str) -> DeleteVerification:
        deleted = self.platform.delete_memories(user_id=user_id, run_id=run_id)
        if deleted is not True:
            raise AdapterError("Mem0 delete was not acknowledged")
        filters = {"AND": [{"user_id": user_id}, {"run_id": run_id}]}
        for attempt in range(self.policy.max_attempts):
            if not self._readback_all(filters=filters):
                return DeleteVerification(deleted=True, verified_absent=True)
            if attempt + 1 < self.policy.max_attempts:
                self._sleep(self.policy.interval_seconds)
        raise AdapterError("Mem0 delete scope remained present after bounded readback")

    def _wait_for_event(self, event_id: str):
        for attempt in range(self.policy.max_attempts):
            event = self.platform.get_event(event_id)
            status = event.status.upper()
            if status == "SUCCEEDED":
                return event
            if status == "FAILED":
                raise AdapterError("Mem0 add event failed")
            if status not in {"PENDING", "RUNNING"}:
                raise AdapterError(f"unexpected Mem0 event status: {status}")
            if attempt + 1 < self.policy.max_attempts:
                self._sleep(self.policy.interval_seconds)
        raise EventTimeoutError("Mem0 add event did not complete within the polling bound")

    def _verify_timestamp(
        self,
        request: AddRequest,
        correlated: Sequence[Mapping[str, Any]],
    ) -> tuple[list[datetime], float]:
        assert request.timestamp is not None
        expected = datetime.fromtimestamp(request.timestamp, tz=UTC)
        observed: list[datetime] = []
        try:
            observed = [_parse_created_at(item.get("created_at")) for item in correlated]
        except (TypeError, ValueError):
            raise TimestampReadbackError(
                "persisted created_at is absent or invalid",
                attestation_code="invalid_created_at",
            ) from None
        deltas = [abs((item - expected).total_seconds()) for item in observed]
        if any(delta > self.policy.timestamp_tolerance_seconds for delta in deltas):
            raise TimestampReadbackError(
                "persisted created_at does not match request timestamp",
                attestation_code="created_at_mismatch",
            )
        return observed, max(deltas)


def _source_filters(request: AddRequest, *, source_id: str) -> dict[str, Any]:
    return {
        "AND": [
            {"user_id": request.user_id},
            {"run_id": request.run_id},
            {"metadata": {"source_id": source_id}},
        ]
    }


def _results(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("results")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise AdapterError("Mem0 response did not contain a results list")
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _page_results(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("results")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise ReadbackPaginationError(
            "Mem0 readback did not contain a results list",
            attestation_code="invalid_source_pagination",
        )
    if any(not isinstance(item, Mapping) for item in raw):
        raise ReadbackPaginationError(
            "Mem0 readback contained malformed results",
            attestation_code="invalid_source_pagination",
        )
    return [dict(item) for item in raw]


def _page_count(payload: Mapping[str, Any]) -> int | None:
    count = payload.get("count")
    if count is None:
        return None
    if type(count) is not int or count < 0:
        raise ReadbackPaginationError(
            "Mem0 readback count was invalid",
            attestation_code="invalid_source_pagination",
        )
    return count


def _next_page(
    payload: Mapping[str, Any],
    *,
    current_page: int,
    page_size: int,
    visited_pages: set[int],
) -> int | None:
    continuation = payload.get("next")
    if continuation is None:
        return None
    if not isinstance(continuation, str) or not continuation:
        raise ReadbackPaginationError(
            "Mem0 readback continuation was invalid",
            attestation_code="invalid_source_pagination",
        )
    expected_origin = urlparse(PLATFORM_API_ORIGIN)
    parsed = urlparse(continuation)
    if (
        parsed.scheme != expected_origin.scheme
        or parsed.netloc != expected_origin.netloc
        or parsed.path != _MEMORY_READBACK_PATH
        or parsed.params
        or parsed.fragment
    ):
        raise ReadbackPaginationError(
            "Mem0 readback continuation target was invalid",
            attestation_code="invalid_source_pagination",
        )
    try:
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise ReadbackPaginationError(
            "Mem0 readback continuation query was malformed",
            attestation_code="invalid_source_pagination",
        ) from None
    if set(query) - {"page", "page_size"} or len(query.get("page", ())) != 1:
        raise ReadbackPaginationError(
            "Mem0 readback continuation query was invalid",
            attestation_code="invalid_source_pagination",
        )
    page_value = query["page"][0]
    if not page_value.isdecimal() or page_value != str(current_page + 1):
        raise ReadbackPaginationError(
            "Mem0 readback continuation page was invalid",
            attestation_code="invalid_source_pagination",
        )
    next_page = int(page_value)
    if next_page in visited_pages:
        raise ReadbackPaginationError(
            "Mem0 readback continuation did not advance exactly one page",
            attestation_code="invalid_source_pagination",
        )
    page_size_values = query.get("page_size")
    if page_size_values is not None and page_size_values != [str(page_size)]:
        raise ReadbackPaginationError(
            "Mem0 readback continuation page size changed",
            attestation_code="invalid_source_pagination",
        )
    return next_page


def _prove_persisted_source_results(
    results: Sequence[Mapping[str, Any]],
    source_id: str,
    source_sha256: str,
) -> list[PersistedMemoryIdentityProof]:
    if not results:
        raise TimestampReadbackError(
            "no persisted memory matched metadata.source_id",
            attestation_code="source_id_not_found",
        )
    persisted: list[PersistedMemoryIdentityProof] = []
    seen_ids: set[str] = set()
    for item in results:
        memory_id = item.get("id")
        if (
            not isinstance(memory_id, str)
            or not memory_id
            or memory_id != memory_id.strip()
            or len(memory_id) > 160
        ):
            raise TimestampReadbackError(
                "persisted memory id is absent or invalid",
                attestation_code="invalid_persisted_memory_id",
            )
        if memory_id in seen_ids:
            raise TimestampReadbackError(
                "persisted memory id was duplicated",
                attestation_code="duplicate_persisted_memory_id",
            )
        seen_ids.add(memory_id)
        metadata = item.get("metadata")
        if not isinstance(metadata, Mapping) or metadata.get("source_id") != source_id:
            raise TimestampReadbackError(
                "persisted metadata.source_id does not match request",
                attestation_code="source_id_mismatch",
            )
        if metadata.get("source_sha256") != source_sha256:
            raise TimestampReadbackError(
                "persisted metadata.source_sha256 does not match request",
                attestation_code="source_sha256_mismatch",
            )
        persisted.append(
            PersistedMemoryIdentityProof(
                memory_id=memory_id,
                source_id=source_id,
                source_sha256=source_sha256,
            )
        )
    return persisted


def _parse_created_at(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("created_at must be an ISO datetime")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("created_at must include a timezone")
    return parsed.astimezone(UTC)


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

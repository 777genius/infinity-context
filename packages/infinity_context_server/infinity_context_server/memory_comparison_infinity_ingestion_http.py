"""Bounded loopback HTTP adapter for provider-neutral Infinity ingestion."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from infinity_context_server.memory_comparison_infinity_ingestion_contracts import (
    InfinityIngestionError,
    InfinityIngestionReceipt,
    make_infinity_ingestion_receipt,
)
from infinity_context_server.memory_comparison_ingestion_contracts import IngestionUnit

_MAX_REQUEST_BYTES = 550_000
_MAX_RESPONSE_BYTES = 65_536
_DATA_KEYS = {
    "chunk_ids",
    "created_suggestions",
    "duplicate_chunks",
    "durability",
    "episode_id",
    "memory_scope_id",
    "space_id",
    "stored_chunks",
    "suggestion_ids",
    "thread_id",
}


class InfinityEpisodeHttpAdapter:
    """Send one sealed unit to the canonical episode API and return evidence."""

    def __init__(
        self,
        *,
        origin: str,
        service_token: str,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._origin = _loopback_origin(origin)
        if type(service_token) is not str or not service_token:
            raise InfinityIngestionError("service token must be non-empty")
        if not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 30:
            raise InfinityIngestionError("timeout must be within (0, 30] seconds")
        self._token = service_token
        self._timeout = float(timeout_seconds)
        self._transport = transport

    def ingest(
        self, unit: IngestionUnit, *, run_id: str, manifest_sha256: str
    ) -> InfinityIngestionReceipt:
        _validate_authority(unit, run_id, manifest_sha256)
        request_bytes = self.sealed_request_bytes(unit, run_id=run_id)
        try:
            with (
                httpx.Client(
                    transport=self._transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(self._timeout),
                ) as client,
                client.stream(
                    "POST",
                    f"{self._origin}/v1/episodes",
                    content=request_bytes,
                    headers={
                        "authorization": f"Bearer {self._token}",
                        "content-type": "application/json",
                    },
                ) as response,
            ):
                if 300 <= response.status_code < 400:
                    raise InfinityIngestionError(
                        "redirects are forbidden on the ingestion boundary"
                    )
                if response.status_code != 200:
                    raise InfinityIngestionError(
                        f"Infinity episode API returned {response.status_code}"
                    )
                response_bytes = _bounded_response_bytes(response)
        except httpx.HTTPError as exc:
            raise InfinityIngestionError("Infinity episode transport failed") from exc
        data = _response_data(response_bytes)
        return make_infinity_ingestion_receipt(
            unit=unit,
            run_id=run_id,
            manifest_sha256=manifest_sha256,
            episode_id=data["episode_id"],
            chunk_ids=tuple(data["chunk_ids"]),
            space_id=data["space_id"],
            memory_scope_id=data["memory_scope_id"],
            thread_id=data["thread_id"],
            request_sha256=hashlib.sha256(request_bytes).hexdigest(),
            response_sha256=hashlib.sha256(response_bytes).hexdigest(),
        )

    def sealed_request_bytes(self, unit: IngestionUnit, *, run_id: str) -> bytes:
        _validate_authority(unit, run_id, "0" * 64)
        request_bytes = _canonical_bytes(_episode_payload(unit, run_id=run_id))
        if len(request_bytes) > _MAX_REQUEST_BYTES:
            raise InfinityIngestionError("episode request exceeds the sealed byte limit")
        return request_bytes

    def request_commitment_sha256(self, unit: IngestionUnit, *, run_id: str) -> str:
        return hashlib.sha256(self.sealed_request_bytes(unit, run_id=run_id)).hexdigest()


def _episode_payload(unit: IngestionUnit, *, run_id: str) -> dict[str, object]:
    message = unit.messages[0]
    if message.role not in {"user", "assistant"}:
        raise InfinityIngestionError("Infinity transcript ingestion accepts user/assistant only")
    try:
        occurred_at = datetime.fromtimestamp(unit.metadata.timestamp, tz=UTC)
    except (OSError, OverflowError, ValueError) as exc:
        raise InfinityIngestionError("unit timestamp is outside the UTC datetime range") from exc
    return {
        "idempotency_key": unit.metadata.source_id,
        "kind_hint": "raw_transcript_chunk",
        "memory_scope_external_ref": unit.corpus_id,
        "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
        "source_external_id": unit.metadata.source_id,
        "source_type": "transcript",
        "space_slug": "benchmark-" + hashlib.sha256(run_id.encode()).hexdigest()[:32],
        "speaker": message.role,
        "text": message.content,
        "thread_external_ref": unit.corpus_id,
        "trust_level": "medium",
    }


def _response_data(raw: bytes) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InfinityIngestionError("episode response is not exact JSON") from exc
    if type(payload) is not dict or set(payload) != {"data"} or type(payload["data"]) is not dict:
        raise InfinityIngestionError("episode response envelope is invalid")
    data = payload["data"]
    if set(data) != _DATA_KEYS:
        raise InfinityIngestionError("episode response schema is invalid")
    for key in ("episode_id", "space_id", "memory_scope_id", "thread_id"):
        if type(data[key]) is not str or not data[key]:
            raise InfinityIngestionError(f"episode response {key} is invalid")
    if (
        type(data["chunk_ids"]) is not list
        or not data["chunk_ids"]
        or any(type(value) is not str or not value for value in data["chunk_ids"])
        or len(set(data["chunk_ids"])) != len(data["chunk_ids"])
    ):
        raise InfinityIngestionError("episode response chunk_ids are invalid")
    if data["durability"] != "durable":
        raise InfinityIngestionError("episode response is not durable")
    for key in ("stored_chunks", "duplicate_chunks", "created_suggestions"):
        if type(data[key]) is not int or data[key] < 0:
            raise InfinityIngestionError(f"episode response {key} is invalid")
    if type(data["suggestion_ids"]) is not list or any(
        type(value) is not str for value in data["suggestion_ids"]
    ):
        raise InfinityIngestionError("episode response suggestion_ids are invalid")
    if data["created_suggestions"] != 0 or data["suggestion_ids"] != []:
        raise InfinityIngestionError("episode response contains forbidden suggestions")
    if (data["stored_chunks"] > 0) == (data["duplicate_chunks"] > 0):
        raise InfinityIngestionError("episode response create/replay disposition is ambiguous")
    if data["stored_chunks"] + data["duplicate_chunks"] != len(data["chunk_ids"]):
        raise InfinityIngestionError("episode response chunk count is inconsistent")
    return data


def _bounded_response_bytes(response: httpx.Response) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise InfinityIngestionError("episode response content-length is invalid") from exc
        if declared < 0 or declared > _MAX_RESPONSE_BYTES:
            raise InfinityIngestionError("episode response exceeds the sealed byte limit")
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > _MAX_RESPONSE_BYTES:
            raise InfinityIngestionError("episode response exceeds the sealed byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _loopback_origin(value: str) -> str:
    if type(value) is not str or value.endswith("/") or "?" in value or "#" in value:
        raise InfinityIngestionError("origin must be an exact loopback HTTP origin")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise InfinityIngestionError("origin must be an exact loopback HTTP origin") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or port is None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise InfinityIngestionError("origin must be an exact loopback HTTP origin")
    return value


def _validate_authority(unit: IngestionUnit, run_id: str, manifest_sha256: str) -> None:
    if type(unit) is not IngestionUnit:
        raise InfinityIngestionError("ingestion unit must have the exact contract type")
    unit.validate()
    if type(run_id) is not str or not run_id.strip():
        raise InfinityIngestionError("run_id must be non-empty")
    if (
        type(manifest_sha256) is not str
        or len(manifest_sha256) != 64
        or any(value not in "0123456789abcdef" for value in manifest_sha256)
    ):
        raise InfinityIngestionError("manifest_sha256 is invalid")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


__all__ = ["InfinityEpisodeHttpAdapter"]

"""Exact terminal cleanup for managed Infinity comparison corpora.

The coordinator consumes the immutable ingest and derived-presence receipts. It
never discovers IDs by listing mutable state: every delete and authenticated
readback is tied to the original manifest and canonical scope.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import final

import httpx
from infinity_context_core.ports.derived_projection_policy import (
    DerivedProjectionLaneDisposition,
)

from infinity_context_server.memory_comparison_managed_http_derived_evidence import (
    ManagedDerivedEvidenceHttpClient,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedInfinityHttpConfig,
)
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedCanonicalProjectionScope,
    ManagedDerivedPresenceObservation,
    ManagedGraphitiDeleteObservation,
    ManagedGraphitiPresenceObservation,
    ManagedIngestIdentityManifest,
    ManagedQdrantDeleteObservation,
    ManagedQdrantPresenceObservation,
    managed_ingest_identity_manifest_sha256,
)

_MAX_RESPONSE_BYTES = 2_000_000


class ManagedExactCleanupError(RuntimeError):
    """Stable secret-free failure code for exact cleanup."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedCanonicalDeleteReceipt:
    """One exact canonical delete acknowledged and read back as deleted."""

    identity_kind: str
    identity: str
    disposition: str

    def __post_init__(self) -> None:
        if self.identity_kind not in {"infinity_fact", "infinity_document"}:
            raise ManagedExactCleanupError("managed_exact_cleanup_receipt_invalid")
        if (
            type(self.identity) is not str
            or not self.identity
            or self.identity.strip() != self.identity
        ):
            raise ManagedExactCleanupError("managed_exact_cleanup_receipt_invalid")
        if self.disposition not in {"deleted", "already_absent", "recovered_absent"}:
            raise ManagedExactCleanupError("managed_exact_cleanup_receipt_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedExactCleanupObservation:
    """One externally replayable cleanup pass over an immutable manifest."""

    lifecycle_target_identity_sha256: str
    ingest_manifest_sha256: str
    corpus_id: str
    scope: ManagedCanonicalProjectionScope
    pass_index: int
    qdrant: ManagedQdrantDeleteObservation | None
    graphiti: ManagedGraphitiDeleteObservation | None
    canonical: tuple[ManagedCanonicalDeleteReceipt, ...]
    verified_absent: bool

    def __post_init__(self) -> None:
        if type(self.pass_index) is not int or self.pass_index not in (1, 2):
            raise ManagedExactCleanupError("managed_exact_cleanup_observation_invalid")
        if type(self.scope) is not ManagedCanonicalProjectionScope:
            raise ManagedExactCleanupError("managed_exact_cleanup_observation_invalid")
        if (
            type(self.canonical) is not tuple
            or any(type(item) is not ManagedCanonicalDeleteReceipt for item in self.canonical)
            or len({(item.identity_kind, item.identity) for item in self.canonical})
            != len(self.canonical)
        ):
            raise ManagedExactCleanupError("managed_exact_cleanup_observation_invalid")
        if type(self.verified_absent) is not bool or not self.verified_absent:
            raise ManagedExactCleanupError("managed_exact_cleanup_observation_invalid")
        allowed = (
            {"deleted", "already_absent"}
            if self.pass_index == 1
            else {"already_absent", "recovered_absent"}
        )
        if any(item.disposition not in allowed for item in self.canonical):
            raise ManagedExactCleanupError("managed_exact_cleanup_replay_invalid")


@final
class ManagedInfinityExactCleanupCoordinator:
    """Delete derived projections and canonical rows by original exact IDs."""

    def __init__(
        self,
        *,
        config: ManagedInfinityHttpConfig,
        derived_evidence: ManagedDerivedEvidenceHttpClient,
        transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    ) -> None:
        if type(config) is not ManagedInfinityHttpConfig or config.transport is not None:
            raise ManagedExactCleanupError("managed_exact_cleanup_config_invalid")
        if type(derived_evidence) is not ManagedDerivedEvidenceHttpClient:
            raise ManagedExactCleanupError("managed_exact_cleanup_derived_client_invalid")
        if (
            derived_evidence.lifecycle_target_identity_sha256 != config.target_identity_sha256
            or derived_evidence.retries != 0
        ):
            raise ManagedExactCleanupError("managed_exact_cleanup_target_mismatch")
        if transport_factory is not None and not callable(transport_factory):
            raise ManagedExactCleanupError("managed_exact_cleanup_transport_factory_invalid")
        self._config = config
        self._derived_evidence = derived_evidence
        self._transport_factory = transport_factory
        self._owned_transports: list[httpx.BaseTransport] = []
        self._transport_lock = threading.Lock()

    def __repr__(self) -> str:
        return "ManagedInfinityExactCleanupCoordinator(<redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedInfinityExactCleanupCoordinator is nonserializable")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedInfinityExactCleanupCoordinator is final")

    @property
    def retries(self) -> int:
        return 0

    def cleanup(
        self,
        *,
        scope: ManagedCanonicalProjectionScope,
        manifest: ManagedIngestIdentityManifest,
        presence: ManagedDerivedPresenceObservation,
        pass_index: int,
    ) -> ManagedExactCleanupObservation:
        manifest_sha256 = self._validate_request(
            scope=scope,
            manifest=manifest,
            presence=presence,
            pass_index=pass_index,
        )
        failure: ManagedExactCleanupError | None = None
        qdrant = None
        if type(presence.qdrant) is ManagedQdrantPresenceObservation:
            try:
                qdrant = self._derived_evidence.delete_qdrant(
                    scope=scope,
                    manifest=manifest,
                    target_commitment_sha256=presence.qdrant.target_commitment_sha256,
                    manifest_binding_sha256=presence.qdrant.manifest_binding_sha256,
                )
            except BaseException as exc:
                failure = _first_failure(failure, exc)
        graphiti = None
        if type(presence.graphiti) is ManagedGraphitiPresenceObservation:
            try:
                graphiti = self._derived_evidence.delete_graphiti(
                    scope=scope,
                    manifest=manifest,
                    identity_manifest=presence.graphiti.identity_manifest,
                    target_commitment_sha256=presence.graphiti.target_commitment_sha256,
                    manifest_binding_sha256=presence.graphiti.manifest_binding_sha256,
                )
            except BaseException as exc:
                failure = _first_failure(failure, exc)

        canonical: list[ManagedCanonicalDeleteReceipt] = []
        identities = (
            *(("infinity_fact", item) for item in manifest.infinity_fact_ids),
            *(("infinity_document", item) for item in manifest.infinity_document_ids),
        )
        for identity_kind, identity in identities:
            try:
                canonical.append(
                    self._delete_and_readback(
                        identity_kind=identity_kind,
                        identity=identity,
                        scope=scope,
                        pass_index=pass_index,
                    )
                )
            except BaseException as exc:
                failure = _first_failure(failure, exc)
        if len(canonical) != manifest.infinity_canonical_count:
            failure = failure or ManagedExactCleanupError("managed_exact_cleanup_coverage_invalid")
        if failure is not None:
            raise failure from None
        return ManagedExactCleanupObservation(
            lifecycle_target_identity_sha256=self._config.target_identity_sha256,
            ingest_manifest_sha256=manifest_sha256,
            corpus_id=manifest.corpus_id,
            scope=scope,
            pass_index=pass_index,
            qdrant=qdrant,
            graphiti=graphiti,
            canonical=tuple(canonical),
            verified_absent=True,
        )

    def cleanup_all(
        self,
        requests: tuple[
            tuple[
                ManagedCanonicalProjectionScope,
                ManagedIngestIdentityManifest,
                ManagedDerivedPresenceObservation,
            ],
            ...,
        ],
        *,
        pass_index: int,
    ) -> tuple[ManagedExactCleanupObservation, ...]:
        """Attempt every corpus and return evidence only for complete coverage."""
        if type(requests) is not tuple or not requests:
            raise ManagedExactCleanupError("managed_exact_cleanup_batch_invalid")
        observations: list[ManagedExactCleanupObservation] = []
        failure: ManagedExactCleanupError | None = None
        for request in requests:
            try:
                scope, manifest, presence = request
                observations.append(
                    self.cleanup(
                        scope=scope,
                        manifest=manifest,
                        presence=presence,
                        pass_index=pass_index,
                    )
                )
            except BaseException as exc:
                failure = _first_failure(failure, exc)
        if failure is not None or len(observations) != len(requests):
            raise failure or ManagedExactCleanupError("managed_exact_cleanup_batch_incomplete")
        return tuple(observations)

    def _validate_request(
        self,
        *,
        scope: ManagedCanonicalProjectionScope,
        manifest: ManagedIngestIdentityManifest,
        presence: ManagedDerivedPresenceObservation,
        pass_index: int,
    ) -> str:
        if type(scope) is not ManagedCanonicalProjectionScope:
            raise ManagedExactCleanupError("managed_exact_cleanup_scope_invalid")
        if type(manifest) is not ManagedIngestIdentityManifest or not manifest.complete:
            raise ManagedExactCleanupError("managed_exact_cleanup_manifest_invalid")
        if type(presence) is not ManagedDerivedPresenceObservation:
            raise ManagedExactCleanupError("managed_exact_cleanup_presence_invalid")
        if type(pass_index) is not int or pass_index not in (1, 2):
            raise ManagedExactCleanupError("managed_exact_cleanup_pass_invalid")
        try:
            manifest_sha256 = managed_ingest_identity_manifest_sha256(manifest, scope)
        except ValueError:
            raise ManagedExactCleanupError("managed_exact_cleanup_manifest_invalid") from None
        if (
            presence.lifecycle_target_identity_sha256 != self._config.target_identity_sha256
            or presence.ingest_manifest_sha256 != manifest_sha256
            or presence.scope != scope
            or not presence.outbox.complete
            or presence.outbox.done_chunk_ids != manifest.infinity_chunk_ids
            or presence.outbox.done_fact_ids != manifest.infinity_fact_ids
        ):
            raise ManagedExactCleanupError("managed_exact_cleanup_binding_mismatch")
        if not _matches_qdrant_disposition(presence.qdrant, manifest.infinity_chunk_ids):
            raise ManagedExactCleanupError("managed_exact_cleanup_qdrant_binding_invalid")
        if not _matches_graphiti_disposition(presence.graphiti, manifest.infinity_fact_ids, scope):
            raise ManagedExactCleanupError("managed_exact_cleanup_graphiti_binding_invalid")
        return manifest_sha256

    def _delete_and_readback(
        self,
        *,
        identity_kind: str,
        identity: str,
        scope: ManagedCanonicalProjectionScope,
        pass_index: int,
    ) -> ManagedCanonicalDeleteReceipt:
        segment = "facts" if identity_kind == "infinity_fact" else "documents"
        path = f"/v1/{segment}/{identity}"
        acknowledgement = self._request("DELETE", path)
        disposition = self._validate_canonical_payload(
            acknowledgement,
            identity=identity,
            scope=scope,
            acknowledgement=True,
        )
        readback = self._request("GET", path)
        self._validate_canonical_payload(
            readback,
            identity=identity,
            scope=scope,
            acknowledgement=False,
        )
        if pass_index == 2 and disposition == "deleted":
            disposition = "recovered_absent"
        return ManagedCanonicalDeleteReceipt(identity_kind, identity, disposition)

    def _validate_canonical_payload(
        self,
        payload: object,
        *,
        identity: str,
        scope: ManagedCanonicalProjectionScope,
        acknowledgement: bool,
    ) -> str:
        root = _object(payload)
        if set(root) != {"data"}:
            raise ManagedExactCleanupError("managed_exact_cleanup_response_invalid")
        data = _object(root["data"])
        expected = {
            "id": identity,
            "space_id": scope.space_id,
            "memory_scope_id": scope.memory_scope_id,
            "thread_id": scope.thread_id,
            "status": "deleted",
        }
        if any(data.get(key) != value for key, value in expected.items()):
            raise ManagedExactCleanupError("managed_exact_cleanup_readback_mismatch")
        indexing_status = data.get("indexing_status")
        if not acknowledgement:
            if indexing_status is not None:
                raise ManagedExactCleanupError("managed_exact_cleanup_response_invalid")
            return "already_absent"
        if indexing_status == "already_deleted":
            return "already_absent"
        if indexing_status == "pending":
            return "deleted"
        raise ManagedExactCleanupError("managed_exact_cleanup_ack_invalid")

    def _request(self, method: str, path: str) -> object:
        transport = self._new_transport()
        try:
            client = httpx.Client(
                base_url=self._config.base_url,
                headers={"Authorization": f"Bearer {self._config.auth_token}"},
                timeout=self._config.timeout_seconds,
                transport=transport,
                follow_redirects=False,
                trust_env=False,
            )
        except BaseException:
            transport.close()
            raise ManagedExactCleanupError("managed_exact_cleanup_client_failed") from None
        try:
            try:
                with client.stream(method, path) as response:
                    if response.status_code != 200:
                        raise ManagedExactCleanupError("managed_exact_cleanup_request_rejected")
                    if (
                        not response.headers.get("content-type", "")
                        .lower()
                        .startswith("application/json")
                    ):
                        raise ManagedExactCleanupError("managed_exact_cleanup_response_invalid")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_RESPONSE_BYTES:
                            raise ManagedExactCleanupError(
                                "managed_exact_cleanup_response_too_large"
                            )
            except ManagedExactCleanupError:
                raise
            except httpx.HTTPError:
                raise ManagedExactCleanupError("managed_exact_cleanup_request_failed") from None
            try:
                return json.loads(bytes(body), object_pairs_hook=_unique_object)
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                ManagedExactCleanupError,
            ):
                raise ManagedExactCleanupError("managed_exact_cleanup_response_invalid") from None
        finally:
            client.close()

    def _new_transport(self) -> httpx.BaseTransport:
        try:
            transport = (
                httpx.HTTPTransport(retries=0)
                if self._transport_factory is None
                else self._transport_factory()
            )
        except BaseException:
            raise ManagedExactCleanupError(
                "managed_exact_cleanup_transport_factory_failed"
            ) from None
        if not isinstance(transport, httpx.BaseTransport):
            raise ManagedExactCleanupError("managed_exact_cleanup_transport_invalid")
        with self._transport_lock:
            if any(item is transport for item in self._owned_transports):
                raise ManagedExactCleanupError("managed_exact_cleanup_transport_reused")
            self._owned_transports.append(transport)
        return transport


def _matches_qdrant_disposition(
    lane: object,
    chunk_ids: tuple[str, ...],
) -> bool:
    if not chunk_ids:
        return lane is None
    if type(lane) is DerivedProjectionLaneDisposition:
        return lane.lane == "qdrant" and lane.is_not_projected
    return type(lane) is ManagedQdrantPresenceObservation and (
        tuple(item.chunk_id for item in lane.expected) == chunk_ids
    )


def _matches_graphiti_disposition(
    lane: object,
    fact_ids: tuple[str, ...],
    scope: ManagedCanonicalProjectionScope,
) -> bool:
    if not fact_ids:
        return lane is None
    if type(lane) is DerivedProjectionLaneDisposition:
        return lane.lane == "graphiti" and lane.is_not_projected
    return type(lane) is ManagedGraphitiPresenceObservation and lane.group_scope == scope


def _object(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ManagedExactCleanupError("managed_exact_cleanup_response_invalid")
    return value


def _first_failure(
    current: ManagedExactCleanupError | None,
    failure: BaseException,
) -> ManagedExactCleanupError:
    if current is not None:
        return current
    if type(failure) is ManagedExactCleanupError:
        return failure
    return ManagedExactCleanupError("managed_exact_cleanup_incomplete")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManagedExactCleanupError("managed_exact_cleanup_response_invalid")
        result[key] = value
    return result


__all__ = [
    "ManagedCanonicalDeleteReceipt",
    "ManagedExactCleanupError",
    "ManagedExactCleanupObservation",
    "ManagedInfinityExactCleanupCoordinator",
]

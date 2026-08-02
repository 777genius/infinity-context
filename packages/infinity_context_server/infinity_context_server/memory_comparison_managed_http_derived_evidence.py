"""Strict one-shot HTTP client for managed derived identity evidence."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from typing import final

import httpx
from infinity_context_core.ports.derived_projection_policy import (
    DerivedProjectionLaneDisposition,
    DerivedProjectionLanePolicyError,
)

from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedInfinityHttpConfig,
)
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedCanonicalProjectionScope,
    ManagedDerivedPresenceObservation,
    ManagedGraphitiDeleteObservation,
    ManagedGraphitiDeletePassObservation,
    ManagedGraphitiIdentitySnapshot,
    ManagedGraphitiPresenceObservation,
    ManagedIngestIdentityManifest,
    ManagedPolicyObservationContractError,
    ManagedProjectionOutboxObservation,
    ManagedQdrantDeleteObservation,
    ManagedQdrantDeletePassObservation,
    ManagedQdrantPointIdentity,
    ManagedQdrantPresenceObservation,
    managed_ingest_identity_manifest_sha256,
)

_MAX_RESPONSE_BYTES = 2_000_000
_MAX_IDENTITIES = 20_000
_OPAQUE_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")


class ManagedDerivedEvidenceHttpError(RuntimeError):
    """Stable secret-free failure code for managed evidence transport/parsing."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedDerivedEvidenceHttpClient:
    """Use a fresh owned client/transport for every diagnostics request."""

    def __init__(
        self,
        *,
        config: ManagedInfinityHttpConfig,
        transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    ) -> None:
        if type(config) is not ManagedInfinityHttpConfig or config.transport is not None:
            raise ManagedDerivedEvidenceHttpError("managed_derived_evidence_config_invalid")
        if transport_factory is not None and not callable(transport_factory):
            raise ManagedDerivedEvidenceHttpError(
                "managed_derived_evidence_transport_factory_invalid"
            )
        self._config = config
        self._transport_factory = transport_factory
        self._owned_transports: list[httpx.BaseTransport] = []
        self._transport_lock = threading.Lock()

    def __repr__(self) -> str:
        return "ManagedDerivedEvidenceHttpClient(<redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedDerivedEvidenceHttpClient is nonserializable")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedDerivedEvidenceHttpClient is final")

    @property
    def lifecycle_target_identity_sha256(self) -> str:
        return self._config.target_identity_sha256

    @property
    def retries(self) -> int:
        return 0

    def observe_presence(
        self,
        *,
        scope: ManagedCanonicalProjectionScope,
        manifest: ManagedIngestIdentityManifest,
    ) -> ManagedDerivedPresenceObservation:
        manifest_sha256 = _request_manifest(scope, manifest)
        if not manifest.infinity_chunk_ids and not manifest.infinity_fact_ids:
            raise ManagedDerivedEvidenceHttpError(
                "managed_derived_evidence_expected_identity_missing"
            )
        payload = {
            **_scope_request(scope),
            "expected_chunk_ids": list(manifest.infinity_chunk_ids),
            "expected_fact_ids": list(manifest.infinity_fact_ids),
        }
        data = self._post("/v1/diagnostics/derived-evidence/presence", payload)
        try:
            return _presence_observation(
                data,
                target=self._config.target_identity_sha256,
                manifest_sha256=manifest_sha256,
                scope=scope,
                chunk_ids=manifest.infinity_chunk_ids,
                fact_ids=manifest.infinity_fact_ids,
            )
        except ManagedPolicyObservationContractError:
            raise ManagedDerivedEvidenceHttpError(
                "managed_derived_evidence_presence_invalid"
            ) from None

    def delete_qdrant(
        self,
        *,
        scope: ManagedCanonicalProjectionScope,
        manifest: ManagedIngestIdentityManifest,
        target_commitment_sha256: str,
        manifest_binding_sha256: str,
    ) -> ManagedQdrantDeleteObservation:
        manifest_sha256 = _request_manifest(scope, manifest)
        _digest_request(target_commitment_sha256)
        _digest_request(manifest_binding_sha256)
        if not manifest.infinity_chunk_ids:
            raise ManagedDerivedEvidenceHttpError("managed_derived_evidence_qdrant_manifest_empty")
        payload = {
            **_scope_request(scope),
            "expected_chunk_ids": list(manifest.infinity_chunk_ids),
            "target_commitment_sha256": target_commitment_sha256,
            "manifest_binding_sha256": manifest_binding_sha256,
        }
        data = self._post("/v1/diagnostics/derived-evidence/qdrant/delete", payload)
        try:
            return _qdrant_delete_observation(
                data,
                lifecycle_target=self._config.target_identity_sha256,
                manifest_sha256=manifest_sha256,
                target_commitment=target_commitment_sha256,
                manifest_binding=manifest_binding_sha256,
                expected_chunk_ids=manifest.infinity_chunk_ids,
            )
        except ManagedPolicyObservationContractError:
            raise ManagedDerivedEvidenceHttpError(
                "managed_derived_evidence_qdrant_delete_invalid"
            ) from None

    def delete_graphiti(
        self,
        *,
        scope: ManagedCanonicalProjectionScope,
        manifest: ManagedIngestIdentityManifest,
        identity_manifest: ManagedGraphitiIdentitySnapshot,
        target_commitment_sha256: str,
        manifest_binding_sha256: str,
    ) -> ManagedGraphitiDeleteObservation:
        manifest_sha256 = _request_manifest(scope, manifest)
        _digest_request(target_commitment_sha256)
        _digest_request(manifest_binding_sha256)
        if (
            not manifest.infinity_fact_ids
            or type(identity_manifest) is not ManagedGraphitiIdentitySnapshot
            or identity_manifest.empty
        ):
            raise ManagedDerivedEvidenceHttpError(
                "managed_derived_evidence_graphiti_manifest_invalid"
            )
        payload = {
            **_scope_request(scope),
            "expected_fact_ids": list(manifest.infinity_fact_ids),
            "identity_manifest": _snapshot_request(identity_manifest),
            "target_commitment_sha256": target_commitment_sha256,
            "manifest_binding_sha256": manifest_binding_sha256,
        }
        data = self._post("/v1/diagnostics/derived-evidence/graphiti/delete", payload)
        try:
            return _graphiti_delete_observation(
                data,
                lifecycle_target=self._config.target_identity_sha256,
                manifest_sha256=manifest_sha256,
                target_commitment=target_commitment_sha256,
                manifest_binding=manifest_binding_sha256,
                expected_fact_ids=manifest.infinity_fact_ids,
                expected=identity_manifest,
                scope=scope,
            )
        except ManagedPolicyObservationContractError:
            raise ManagedDerivedEvidenceHttpError(
                "managed_derived_evidence_graphiti_delete_invalid"
            ) from None

    def _post(self, path: str, payload: dict[str, object]) -> object:
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
            raise ManagedDerivedEvidenceHttpError(
                "managed_derived_evidence_client_failed"
            ) from None
        try:
            try:
                with client.stream("POST", path, json=payload) as response:
                    if response.status_code != 200:
                        raise ManagedDerivedEvidenceHttpError(
                            "managed_derived_evidence_request_rejected"
                        )
                    content_type = response.headers.get("content-type", "")
                    if not content_type.lower().startswith("application/json"):
                        raise ManagedDerivedEvidenceHttpError(
                            "managed_derived_evidence_response_invalid"
                        )
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_length = int(content_length)
                        except ValueError:
                            raise ManagedDerivedEvidenceHttpError(
                                "managed_derived_evidence_response_invalid"
                            ) from None
                        if declared_length < 0 or declared_length > _MAX_RESPONSE_BYTES:
                            raise ManagedDerivedEvidenceHttpError(
                                "managed_derived_evidence_response_too_large"
                            )
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_RESPONSE_BYTES:
                            raise ManagedDerivedEvidenceHttpError(
                                "managed_derived_evidence_response_too_large"
                            )
            except ManagedDerivedEvidenceHttpError:
                raise
            except httpx.HTTPError:
                raise ManagedDerivedEvidenceHttpError(
                    "managed_derived_evidence_request_failed"
                ) from None
            try:
                decoded: object = json.loads(
                    bytes(body),
                    object_pairs_hook=_unique_object,
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                ManagedPolicyObservationContractError,
            ):
                raise ManagedDerivedEvidenceHttpError(
                    "managed_derived_evidence_response_invalid"
                ) from None
            try:
                envelope = _object(decoded, {"data"})
            except ManagedPolicyObservationContractError:
                raise ManagedDerivedEvidenceHttpError(
                    "managed_derived_evidence_response_invalid"
                ) from None
            return envelope["data"]
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
            raise ManagedDerivedEvidenceHttpError(
                "managed_derived_evidence_transport_factory_failed"
            ) from None
        if not isinstance(transport, httpx.BaseTransport):
            raise ManagedDerivedEvidenceHttpError("managed_derived_evidence_transport_invalid")
        with self._transport_lock:
            if any(item is transport for item in self._owned_transports):
                raise ManagedDerivedEvidenceHttpError("managed_derived_evidence_transport_reused")
            self._owned_transports.append(transport)
        return transport


def _presence_observation(
    value: object,
    *,
    target: str,
    manifest_sha256: str,
    scope: ManagedCanonicalProjectionScope,
    chunk_ids: tuple[str, ...],
    fact_ids: tuple[str, ...],
) -> ManagedDerivedPresenceObservation:
    root = _object(value, {"scope", "outbox", "lanes"})
    if _parse_scope(root["scope"]) != scope:
        _invalid()
    outbox_value = _object(
        root["outbox"],
        {"complete", "done_chunk_ids", "done_fact_ids", "done_event_count"},
    )
    outbox = ManagedProjectionOutboxObservation(
        _identities(outbox_value["done_chunk_ids"]),
        _identities(outbox_value["done_fact_ids"]),
        _integer(outbox_value["done_event_count"]),
        _boolean(outbox_value["complete"]),
    )
    if (
        not outbox.complete
        or outbox.done_chunk_ids != chunk_ids
        or outbox.done_fact_ids != fact_ids
    ):
        _invalid()
    lanes = _object(root["lanes"], {"qdrant", "graphiti"})
    qdrant = _qdrant_lane(lanes["qdrant"])
    graphiti = _graphiti_lane(lanes["graphiti"], scope)
    if bool(chunk_ids) != (qdrant is not None) or bool(fact_ids) != (graphiti is not None):
        _invalid()
    if type(qdrant) is ManagedQdrantPresenceObservation and (
        tuple(item.chunk_id for item in qdrant.expected) != chunk_ids
    ):
        _invalid()
    return ManagedDerivedPresenceObservation(
        target,
        manifest_sha256,
        scope,
        outbox,
        qdrant,
        graphiti,
    )


def _qdrant_lane(
    value: object,
) -> ManagedQdrantPresenceObservation | DerivedProjectionLaneDisposition | None:
    if value is None:
        return None
    if _is_not_projected(value):
        return _not_projected_lane(value, lane="qdrant")
    return _qdrant_presence(value)


def _graphiti_lane(
    value: object,
    scope: ManagedCanonicalProjectionScope,
) -> ManagedGraphitiPresenceObservation | DerivedProjectionLaneDisposition | None:
    if value is None:
        return None
    if _is_not_projected(value):
        return _not_projected_lane(value, lane="graphiti")
    return _graphiti_presence(value, scope)


def _qdrant_presence(value: object) -> ManagedQdrantPresenceObservation:
    data = _object(
        value,
        {
            "disposition",
            "projection_version",
            "target_commitment_sha256",
            "manifest_binding_sha256",
            "expected",
            "observed",
            "scoped_point_ids",
            "exact_scoped_count",
            "complete",
        },
    )
    if data["disposition"] != "projected":
        _invalid()
    return ManagedQdrantPresenceObservation(
        _identity(data["projection_version"]),
        _digest(data["target_commitment_sha256"]),
        _digest(data["manifest_binding_sha256"]),
        _points(data["expected"]),
        _points(data["observed"]),
        _identities(data["scoped_point_ids"]),
        _integer(data["exact_scoped_count"]),
        _boolean(data["complete"]),
    )


def _graphiti_presence(
    value: object,
    scope: ManagedCanonicalProjectionScope,
) -> ManagedGraphitiPresenceObservation:
    data = _object(
        value,
        {
            "disposition",
            "target_commitment_sha256",
            "manifest_binding_sha256",
            "identity_manifest",
            "exact_identity_count",
            "complete",
        },
    )
    if data["disposition"] != "projected":
        _invalid()
    return ManagedGraphitiPresenceObservation(
        scope,
        _digest(data["target_commitment_sha256"]),
        _digest(data["manifest_binding_sha256"]),
        _snapshot(data["identity_manifest"]),
        _integer(data["exact_identity_count"]),
        _boolean(data["complete"]),
    )


def _is_not_projected(value: object) -> bool:
    return type(value) is dict and value.get("disposition") == "not_projected"


def _not_projected_lane(value: object, *, lane: str) -> DerivedProjectionLaneDisposition:
    data = _object(value, {"disposition", "policy_sha256"})
    try:
        return DerivedProjectionLaneDisposition(
            lane=lane,
            disposition=str(data["disposition"]),
            policy_sha256=_digest(data["policy_sha256"]),
        )
    except DerivedProjectionLanePolicyError:
        _invalid()
        raise AssertionError("unreachable") from None


def _qdrant_delete_observation(
    value: object,
    *,
    lifecycle_target: str,
    manifest_sha256: str,
    target_commitment: str,
    manifest_binding: str,
    expected_chunk_ids: tuple[str, ...],
) -> ManagedQdrantDeleteObservation:
    root = _object(
        value,
        {
            "lane",
            "target_commitment_sha256",
            "manifest_binding_sha256",
            "verified_absent",
            "passes",
        },
    )
    if (
        root["lane"] != "qdrant"
        or _digest(root["target_commitment_sha256"]) != target_commitment
        or _digest(root["manifest_binding_sha256"]) != manifest_binding
    ):
        _invalid()
    passes_value = _array(root["passes"], maximum=2)
    if len(passes_value) != 2:
        _invalid()
    passes = tuple(_qdrant_delete_pass(item) for item in passes_value)
    if (
        passes[0].present_before not in (passes[0].expected, ())
        or passes[1].present_before
        or any(item.target_commitment_sha256 != target_commitment for item in passes)
    ):
        _invalid()
    return ManagedQdrantDeleteObservation(
        lifecycle_target,
        manifest_sha256,
        target_commitment,
        manifest_binding,
        expected_chunk_ids,
        passes,
        _boolean(root["verified_absent"]),
    )


def _qdrant_delete_pass(value: object) -> ManagedQdrantDeletePassObservation:
    data = _object(
        value,
        {
            "pass_index",
            "target_commitment_sha256",
            "expected",
            "present_before",
            "remaining",
            "scoped_point_ids_after",
            "exact_scoped_count_after",
            "delete_completed",
            "verified_absent",
            "issues",
        },
    )
    if _array(data["issues"], maximum=20):
        _invalid()
    return ManagedQdrantDeletePassObservation(
        _integer(data["pass_index"]),
        _digest(data["target_commitment_sha256"]),
        _points(data["expected"]),
        _points(data["present_before"]),
        _points(data["remaining"]),
        _identities(data["scoped_point_ids_after"]),
        _integer(data["exact_scoped_count_after"]),
        _boolean(data["delete_completed"]),
        _boolean(data["verified_absent"]),
    )


def _graphiti_delete_observation(
    value: object,
    *,
    lifecycle_target: str,
    manifest_sha256: str,
    target_commitment: str,
    manifest_binding: str,
    expected_fact_ids: tuple[str, ...],
    expected: ManagedGraphitiIdentitySnapshot,
    scope: ManagedCanonicalProjectionScope,
) -> ManagedGraphitiDeleteObservation:
    root = _object(
        value,
        {
            "lane",
            "target_commitment_sha256",
            "manifest_binding_sha256",
            "verified_absent",
            "bound_expected",
            "delete_expected",
            "passes",
        },
    )
    bound_expected = _snapshot(root["bound_expected"])
    delete_expected = _snapshot(root["delete_expected"])
    if (
        root["lane"] != "graphiti"
        or _digest(root["target_commitment_sha256"]) != target_commitment
        or _digest(root["manifest_binding_sha256"]) != manifest_binding
        or bound_expected != expected
    ):
        _invalid()
    passes_value = _array(root["passes"], maximum=2)
    if len(passes_value) != 2:
        _invalid()
    passes = tuple(_graphiti_delete_pass(item) for item in passes_value)
    empty = ManagedGraphitiIdentitySnapshot((), (), (), ())
    if (
        delete_expected not in (bound_expected, empty)
        or passes[0].before != delete_expected
        or passes[0].deleted != delete_expected
    ):
        _invalid()
    return ManagedGraphitiDeleteObservation(
        lifecycle_target,
        manifest_sha256,
        target_commitment,
        manifest_binding,
        expected_fact_ids,
        expected,
        scope,
        passes,
        _boolean(root["verified_absent"]),
    )


def _graphiti_delete_pass(value: object) -> ManagedGraphitiDeletePassObservation:
    data = _object(
        value,
        {
            "pass_index",
            "before",
            "deleted",
            "group_readback",
            "global_readback",
            "verified_absent",
        },
    )
    return ManagedGraphitiDeletePassObservation(
        _integer(data["pass_index"]),
        _snapshot(data["before"]),
        _snapshot(data["deleted"]),
        _snapshot(data["group_readback"]),
        _snapshot(data["global_readback"]),
        _boolean(data["verified_absent"]),
    )


def _request_manifest(
    scope: ManagedCanonicalProjectionScope,
    manifest: ManagedIngestIdentityManifest,
) -> str:
    try:
        return managed_ingest_identity_manifest_sha256(manifest, scope)
    except ManagedPolicyObservationContractError:
        raise ManagedDerivedEvidenceHttpError("managed_derived_evidence_manifest_invalid") from None


def _scope_request(scope: ManagedCanonicalProjectionScope) -> dict[str, object]:
    if type(scope) is not ManagedCanonicalProjectionScope:
        raise ManagedDerivedEvidenceHttpError("managed_derived_evidence_scope_invalid")
    return {
        "space_id": scope.space_id,
        "memory_scope_id": scope.memory_scope_id,
        "thread_id": scope.thread_id,
    }


def _snapshot_request(value: ManagedGraphitiIdentitySnapshot) -> dict[str, object]:
    return {
        "episode_ids": list(value.episode_ids),
        "entity_ids": list(value.entity_ids),
        "mentions_edge_ids": list(value.mentions_edge_ids),
        "relates_to_edge_ids": list(value.relates_to_edge_ids),
    }


def _parse_scope(value: object) -> ManagedCanonicalProjectionScope:
    data = _object(value, {"space_id", "memory_scope_id", "thread_id"})
    thread = data["thread_id"]
    if thread is not None:
        thread = _identity(thread)
    return ManagedCanonicalProjectionScope(
        _identity(data["space_id"]),
        _identity(data["memory_scope_id"]),
        thread,
    )


def _snapshot(value: object) -> ManagedGraphitiIdentitySnapshot:
    data = _object(
        value,
        {"episode_ids", "entity_ids", "mentions_edge_ids", "relates_to_edge_ids"},
    )
    return ManagedGraphitiIdentitySnapshot(
        _identities(data["episode_ids"]),
        _identities(data["entity_ids"]),
        _identities(data["mentions_edge_ids"]),
        _identities(data["relates_to_edge_ids"]),
    )


def _points(value: object) -> tuple[ManagedQdrantPointIdentity, ...]:
    return tuple(
        ManagedQdrantPointIdentity(
            _identity(data["chunk_id"]),
            _identity(data["point_id"]),
        )
        for data in (
            _object(item, {"chunk_id", "point_id"})
            for item in _array(value, maximum=_MAX_IDENTITIES)
        )
    )


def _identities(value: object) -> tuple[str, ...]:
    return tuple(_identity(item) for item in _array(value, maximum=_MAX_IDENTITIES))


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        _invalid()
    return value


def _array(value: object, *, maximum: int) -> list[object]:
    if type(value) is not list or len(value) > maximum:
        _invalid()
    return value


def _identity(value: object) -> str:
    if type(value) is not str or _OPAQUE_IDENTITY.fullmatch(value) is None:
        _invalid()
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _digest(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _invalid()
    return value


def _digest_request(value: object) -> None:
    try:
        _digest(value)
    except ManagedPolicyObservationContractError:
        raise ManagedDerivedEvidenceHttpError("managed_derived_evidence_binding_invalid") from None


def _integer(value: object) -> int:
    if type(value) is not int or value < 0 or value > _MAX_IDENTITIES * 10:
        _invalid()
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        _invalid()
    return value


def _invalid() -> None:
    raise ManagedPolicyObservationContractError("managed evidence payload is invalid")


__all__ = (
    "ManagedDerivedEvidenceHttpClient",
    "ManagedDerivedEvidenceHttpError",
)

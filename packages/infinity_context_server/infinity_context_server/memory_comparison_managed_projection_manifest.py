"""Pure construction of the canonical managed projection manifest."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import final

from infinity_context_core.application import validate_projection_manifest
from infinity_context_core.domain.errors import MemoryConflictError, MemoryValidationError
from infinity_context_core.ports.derived_projection_policy import (
    DerivedProjectionLaneDisposition,
)

from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedCanonicalProjectionScope,
    ManagedDerivedPresenceObservation,
    ManagedGraphitiIdentitySnapshot,
    managed_ingest_identity_manifest_sha256,
)
from infinity_context_server.memory_comparison_managed_ingest_manifest import (
    ManagedCorpusIngestIdentity,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase

MANAGED_PROJECTION_MANIFEST_SCHEMA_VERSION = "memory-comparison-projection-manifest.v1"
MANAGED_PROJECTION_MANIFEST_V2_SCHEMA_VERSION = "memory-comparison-projection-manifest.v2"
MANAGED_COGNEE_NOT_PROJECTED_POLICY_SCHEMA_VERSION = (
    "memory-comparison-cognee-not-projected-policy.v1"
)
MANAGED_COGNEE_NOT_PROJECTED_POLICY_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "disposition": "not_projected",
            "schema_version": MANAGED_COGNEE_NOT_PROJECTED_POLICY_SCHEMA_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManagedProjectionManifestError(ValueError):
    """Fixed-code failure for malformed or mismatched projection evidence."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedProjectionEpisodeInventory:
    """Exact canonical episode identities owned by one projection scope."""

    scope: ManagedCanonicalProjectionScope
    episode_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.scope) is not ManagedCanonicalProjectionScope
            or type(self.episode_ids) is not tuple
            or any(type(item) is not str for item in self.episode_ids)
        ):
            raise ManagedProjectionManifestError("managed_projection_episode_inventory_invalid")


@final
@dataclass(frozen=True, slots=True, repr=False)
class ManagedProjectionManifest:
    """Immutable canonical JSON value with a defensive dictionary projection."""

    canonical_json: str
    projection_manifest_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.canonical_json) is not str
            or type(self.projection_manifest_sha256) is not str
            or _SHA256.fullmatch(self.projection_manifest_sha256) is None
        ):
            raise ManagedProjectionManifestError("managed_projection_output_invalid")
        try:
            value = json.loads(self.canonical_json)
        except (TypeError, ValueError):
            raise ManagedProjectionManifestError("managed_projection_output_invalid") from None
        if (
            type(value) is not dict
            or _canonical_json(value) != self.canonical_json
            or not hmac.compare_digest(_json_sha256(value), self.projection_manifest_sha256)
        ):
            raise ManagedProjectionManifestError("managed_projection_output_invalid")
        try:
            validate_projection_manifest(
                value,
                self.projection_manifest_sha256,
                run_id_sha256=value["run_id_sha256"],
                binding_commitment_sha256=value["binding_commitment_sha256"],
                infinity_target_identity_sha256=value["infinity_target_identity_sha256"],
                space_id=value["space_id"],
                cleanup_plan_sha256=value["cleanup_plan_sha256"],
            )
        except (KeyError, MemoryConflictError, MemoryValidationError):
            raise ManagedProjectionManifestError("managed_projection_output_invalid") from None

    @property
    def projection_manifest(self) -> dict[str, object]:
        """Return a fresh canonical dictionary safe for an HTTP request body."""

        value = json.loads(self.canonical_json)
        if type(value) is not dict:
            raise ManagedProjectionManifestError("managed_projection_output_invalid")
        return value

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedProjectionManifest is final")


def build_managed_projection_manifest(
    *,
    bindings: FullComparisonRunBindings,
    registration: ManagedBenchmarkRunRegistration,
    cases: tuple[ManagedRunCase, ...],
    corpora: tuple[ManagedCorpusIngestIdentity, ...],
    presence: tuple[ManagedDerivedPresenceObservation, ...],
    episode_inventory: tuple[ManagedProjectionEpisodeInventory, ...] | None = None,
) -> ManagedProjectionManifest:
    """Build and core-validate one exact manifest before any terminal cleanup."""

    expected_corpora = _validate_inputs(bindings, registration, cases, corpora, presence)
    _validate_expected_coverage(expected_corpora, corpora)
    episodes_by_scope = _episode_ids_by_scope(corpora, episode_inventory)
    infinity_target = _target(bindings, "infinity-context")
    mem0_target = _target(bindings, "mem0")
    _validate_registration_binding(bindings, registration, infinity_target)

    scopes: list[dict[str, object]] = []
    seen_case_ids: set[str] = set()
    seen_corpus_ids: set[str] = set()
    seen_scopes: set[tuple[str, str | None]] = set()
    canonical_ids: set[str] = set()
    graph_ids: set[str] = set()
    qdrant_point_ids: set[str] = set()
    for bundle, observation in zip(corpora, presence, strict=True):
        scope_key = (bundle.scope.memory_scope_id, bundle.scope.thread_id)
        if (
            bundle.case_id in seen_case_ids
            or bundle.corpus_id in seen_corpus_ids
            or scope_key in seen_scopes
        ):
            raise ManagedProjectionManifestError("managed_projection_coverage_invalid")
        seen_case_ids.add(bundle.case_id)
        seen_corpus_ids.add(bundle.corpus_id)
        seen_scopes.add(scope_key)
        _validate_pair(
            bundle,
            observation,
            registration=registration,
            infinity_target=infinity_target,
            mem0_target=mem0_target,
        )
        scope = _scope_projection(
            bundle,
            observation,
            episode_ids=(episodes_by_scope[scope_key] if episodes_by_scope is not None else None),
        )
        _require_globally_unique(
            canonical_ids,
            (
                *bundle.manifest.infinity_fact_ids,
                *bundle.manifest.infinity_document_ids,
                *bundle.manifest.infinity_chunk_ids,
                *(episodes_by_scope[scope_key] if episodes_by_scope is not None else ()),
            ),
            "managed_projection_canonical_ids_ambiguous",
        )
        if (
            observation.qdrant is not None
            and type(observation.qdrant) is not DerivedProjectionLaneDisposition
        ):
            _require_globally_unique(
                qdrant_point_ids,
                tuple(item.point_id for item in observation.qdrant.expected),
                "managed_projection_qdrant_ids_ambiguous",
            )
        if (
            observation.graphiti is not None
            and type(observation.graphiti) is not DerivedProjectionLaneDisposition
        ):
            _require_globally_unique(
                graph_ids,
                _graph_identities(observation.graphiti.identity_manifest),
                "managed_projection_graphiti_ids_ambiguous",
            )
        scopes.append(scope)

    manifest: dict[str, object] = {
        "schema_version": (
            MANAGED_PROJECTION_MANIFEST_V2_SCHEMA_VERSION
            if episodes_by_scope is not None
            else MANAGED_PROJECTION_MANIFEST_SCHEMA_VERSION
        ),
        "run_id_sha256": registration.run_id_sha256,
        "binding_commitment_sha256": registration.binding_commitment_sha256,
        "infinity_target_identity_sha256": registration.infinity_target_identity_sha256,
        "space_id": registration.space_id,
        "cleanup_plan_sha256": registration.cleanup_plan_sha256,
        "scopes": sorted(
            scopes,
            key=lambda item: (
                str(item["memory_scope_id"]),
                str(item["thread_id"] or ""),
            ),
        ),
    }
    digest = _json_sha256(manifest)
    try:
        canonical = validate_projection_manifest(
            manifest,
            digest,
            run_id_sha256=registration.run_id_sha256,
            binding_commitment_sha256=registration.binding_commitment_sha256,
            infinity_target_identity_sha256=registration.infinity_target_identity_sha256,
            space_id=registration.space_id,
            cleanup_plan_sha256=registration.cleanup_plan_sha256,
        )
    except (MemoryConflictError, MemoryValidationError):
        raise ManagedProjectionManifestError("managed_projection_core_validation_failed") from None
    return ManagedProjectionManifest(
        canonical_json=_canonical_json(canonical),
        projection_manifest_sha256=digest,
    )


def _validate_inputs(
    bindings: object,
    registration: object,
    cases: object,
    corpora: object,
    presence: object,
) -> tuple[tuple[str, str], ...]:
    if type(bindings) is not FullComparisonRunBindings:
        raise ManagedProjectionManifestError("managed_projection_bindings_invalid")
    if type(registration) is not ManagedBenchmarkRunRegistration:
        raise ManagedProjectionManifestError("managed_projection_registration_invalid")
    if (
        type(cases) is not tuple
        or not cases
        or any(type(item) is not ManagedRunCase for item in cases)
    ):
        raise ManagedProjectionManifestError("managed_projection_expected_coverage_invalid")
    case_ids = tuple(item.case_id for item in cases)
    if len(case_ids) != len(set(case_ids)):
        raise ManagedProjectionManifestError("managed_projection_expected_coverage_invalid")
    if (
        type(corpora) is not tuple
        or not corpora
        or any(type(item) is not ManagedCorpusIngestIdentity for item in corpora)
        or type(presence) is not tuple
        or len(presence) != len(corpora)
        or any(type(item) is not ManagedDerivedPresenceObservation for item in presence)
    ):
        raise ManagedProjectionManifestError("managed_projection_coverage_invalid")
    expected: list[tuple[str, str]] = []
    seen_corpora: set[str] = set()
    for case in cases:
        if case.corpus_id not in seen_corpora:
            expected.append((case.case_id, case.corpus_id))
            seen_corpora.add(case.corpus_id)
    return tuple(expected)


def _validate_expected_coverage(
    expected: tuple[tuple[str, str], ...],
    corpora: tuple[ManagedCorpusIngestIdentity, ...],
) -> None:
    actual = tuple((item.case_id, item.corpus_id) for item in corpora)
    if (
        len(actual) != len(expected)
        or len(actual) != len(set(actual))
        or set(actual) != set(expected)
    ):
        raise ManagedProjectionManifestError("managed_projection_coverage_invalid")


def _episode_ids_by_scope(
    corpora: tuple[ManagedCorpusIngestIdentity, ...],
    inventory: tuple[ManagedProjectionEpisodeInventory, ...] | None,
) -> dict[tuple[str, str | None], tuple[str, ...]] | None:
    if inventory is None:
        return None
    if type(inventory) is not tuple or any(
        type(item) is not ManagedProjectionEpisodeInventory for item in inventory
    ):
        raise ManagedProjectionManifestError("managed_projection_episode_inventory_invalid")
    expected_scopes = {(item.scope.memory_scope_id, item.scope.thread_id) for item in corpora}
    by_scope: dict[tuple[str, str | None], tuple[str, ...]] = {}
    seen_episode_ids: set[str] = set()
    for item in inventory:
        scope_key = (item.scope.memory_scope_id, item.scope.thread_id)
        episode_ids = item.episode_ids
        if (
            item.scope.space_id != corpora[0].scope.space_id
            or scope_key in by_scope
            or len(episode_ids) != len(set(episode_ids))
            or seen_episode_ids.intersection(episode_ids)
            or (episode_ids and item.scope.thread_id is None)
        ):
            raise ManagedProjectionManifestError("managed_projection_episode_inventory_invalid")
        seen_episode_ids.update(episode_ids)
        by_scope[scope_key] = tuple(sorted(episode_ids))
    if set(by_scope) != expected_scopes:
        raise ManagedProjectionManifestError("managed_projection_episode_inventory_invalid")
    return by_scope


def _validate_registration_binding(
    bindings: FullComparisonRunBindings,
    registration: ManagedBenchmarkRunRegistration,
    infinity_target: str,
) -> None:
    if (
        registration.run_id_sha256 != hashlib.sha256(bindings.run_id.encode()).hexdigest()
        or registration.binding_commitment_sha256 != bindings.binding_commitment_sha256
        or registration.infinity_target_identity_sha256 != infinity_target
    ):
        raise ManagedProjectionManifestError("managed_projection_registration_mismatch")


def _validate_pair(
    bundle: ManagedCorpusIngestIdentity,
    observation: ManagedDerivedPresenceObservation,
    *,
    registration: ManagedBenchmarkRunRegistration,
    infinity_target: str,
    mem0_target: str,
) -> None:
    manifest = bundle.manifest
    if (
        bundle.infinity_target_identity_sha256 != infinity_target
        or bundle.mem0_target_identity_sha256 != mem0_target
        or bundle.scope != observation.scope
        or bundle.scope.space_id != registration.space_id
        or observation.lifecycle_target_identity_sha256 != infinity_target
        or observation.ingest_manifest_sha256
        != managed_ingest_identity_manifest_sha256(manifest, bundle.scope)
        or not observation.outbox.complete
        or observation.outbox.done_chunk_ids != manifest.infinity_chunk_ids
        or observation.outbox.done_fact_ids != manifest.infinity_fact_ids
        or observation.outbox.done_event_count
        != len(manifest.infinity_chunk_ids) + len(manifest.infinity_fact_ids)
    ):
        raise ManagedProjectionManifestError("managed_projection_evidence_mismatch")
    if not _matches_qdrant_disposition(observation.qdrant, manifest.infinity_chunk_ids):
        raise ManagedProjectionManifestError("managed_projection_qdrant_mismatch")
    if not _matches_graphiti_disposition(observation.graphiti, manifest.infinity_fact_ids, bundle):
        raise ManagedProjectionManifestError("managed_projection_graphiti_mismatch")


def _scope_projection(
    bundle: ManagedCorpusIngestIdentity,
    observation: ManagedDerivedPresenceObservation,
    *,
    episode_ids: tuple[str, ...] | None,
) -> dict[str, object]:
    manifest = bundle.manifest
    qdrant = observation.qdrant
    graphiti = observation.graphiti
    scope: dict[str, object] = {
        "memory_scope_id": bundle.scope.memory_scope_id,
        "thread_id": bundle.scope.thread_id,
        "chunk_ids": sorted(manifest.infinity_chunk_ids),
        "fact_ids": sorted(manifest.infinity_fact_ids),
        "document_ids": sorted(manifest.infinity_document_ids),
        "qdrant": _qdrant_projection(qdrant),
        "graphiti": _graphiti_projection_value(graphiti),
        "cognee": {
            "disposition": "not_projected",
            "policy_sha256": MANAGED_COGNEE_NOT_PROJECTED_POLICY_SHA256,
        },
    }
    if episode_ids is not None:
        scope["episode_ids"] = list(episode_ids)
    return scope


def _graphiti_projection(
    snapshot: ManagedGraphitiIdentitySnapshot,
    target_commitment_sha256: str,
    manifest_binding_sha256: str,
) -> dict[str, object]:
    return {
        "target_commitment_sha256": target_commitment_sha256,
        "manifest_binding_sha256": manifest_binding_sha256,
        "episode_ids": sorted(snapshot.episode_ids),
        "entity_ids": sorted(snapshot.entity_ids),
        "mentions_edge_ids": sorted(snapshot.mentions_edge_ids),
        "relates_to_edge_ids": sorted(snapshot.relates_to_edge_ids),
    }


def _matches_qdrant_disposition(
    lane: object,
    chunk_ids: tuple[str, ...],
) -> bool:
    if not chunk_ids:
        return lane is None
    if type(lane) is DerivedProjectionLaneDisposition:
        return lane.lane == "qdrant" and lane.is_not_projected
    return lane is not None and tuple(item.chunk_id for item in lane.expected) == chunk_ids


def _matches_graphiti_disposition(
    lane: object,
    fact_ids: tuple[str, ...],
    bundle: ManagedCorpusIngestIdentity,
) -> bool:
    if not fact_ids:
        return lane is None
    if type(lane) is DerivedProjectionLaneDisposition:
        return lane.lane == "graphiti" and lane.is_not_projected
    return lane is not None and lane.group_scope == bundle.scope


def _qdrant_projection(lane: object) -> dict[str, object] | None:
    if lane is None:
        return None
    if type(lane) is DerivedProjectionLaneDisposition:
        return _not_projected_projection(lane)
    return {
        "target_commitment_sha256": lane.target_commitment_sha256,
        "manifest_binding_sha256": lane.manifest_binding_sha256,
    }


def _graphiti_projection_value(lane: object) -> dict[str, object] | None:
    if lane is None:
        return None
    if type(lane) is DerivedProjectionLaneDisposition:
        return _not_projected_projection(lane)
    return _graphiti_projection(
        lane.identity_manifest,
        lane.target_commitment_sha256,
        lane.manifest_binding_sha256,
    )


def _not_projected_projection(policy: DerivedProjectionLaneDisposition) -> dict[str, object]:
    return {"disposition": policy.disposition, "policy_sha256": policy.policy_sha256}


def _graph_identities(snapshot: ManagedGraphitiIdentitySnapshot) -> tuple[str, ...]:
    return (
        *snapshot.episode_ids,
        *snapshot.entity_ids,
        *snapshot.mentions_edge_ids,
        *snapshot.relates_to_edge_ids,
    )


def _require_globally_unique(seen: set[str], values: tuple[str, ...], code: str) -> None:
    if len(set(values)) != len(values) or seen.intersection(values):
        raise ManagedProjectionManifestError(code)
    seen.update(values)


def _target(bindings: FullComparisonRunBindings, role: str) -> str:
    matches = tuple(
        item.target_identity_sha256
        for item in bindings.backend_targets
        if item.backend_role == role
    )
    if len(matches) != 1:
        raise ManagedProjectionManifestError("managed_projection_target_invalid")
    return matches[0]


def _canonical_json(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json_sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


__all__ = (
    "MANAGED_COGNEE_NOT_PROJECTED_POLICY_SCHEMA_VERSION",
    "MANAGED_COGNEE_NOT_PROJECTED_POLICY_SHA256",
    "MANAGED_PROJECTION_MANIFEST_SCHEMA_VERSION",
    "MANAGED_PROJECTION_MANIFEST_V2_SCHEMA_VERSION",
    "ManagedProjectionManifest",
    "ManagedProjectionEpisodeInventory",
    "ManagedProjectionManifestError",
    "build_managed_projection_manifest",
)

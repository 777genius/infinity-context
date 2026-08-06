"""Registry-facing evidence projection and one-shot validation binding."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import final

from infinity_context_server.memory_comparison_managed_http_policy_material_projection import (
    project_exact_corpus_bindings,
)
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    ManagedDerivedPresenceObservation,
)
from infinity_context_server.memory_comparison_managed_http_policy_support import (
    ManagedHttpPolicyLifecycleError,
)
from infinity_context_server.memory_comparison_managed_http_policy_validation import (
    ManagedHttpPolicyCorpusMaterial,
    ManagedHttpPolicyRegistryMaterial,
    ManagedHttpPolicyValidationMaterial,
)
from infinity_context_server.memory_comparison_managed_ingest_manifest import (
    ManagedCorpusIngestIdentity,
)
from infinity_context_server.memory_comparison_managed_projection_manifest import (
    ManagedProjectionEpisodeInventory,
)


@dataclass(frozen=True, slots=True)
class ManagedHttpPolicyObservedCorpusEvidence:
    bundle: ManagedCorpusIngestIdentity
    presence: ManagedDerivedPresenceObservation


@final
@dataclass(frozen=True, slots=True)
class ManagedHttpPolicyExactProjectionEvidence:
    """Immutable exact inputs for the canonical projection manifest."""

    corpora: tuple[ManagedCorpusIngestIdentity, ...]
    presence: tuple[ManagedDerivedPresenceObservation, ...]
    episode_inventory: tuple[ManagedProjectionEpisodeInventory, ...] | None = None

    def __post_init__(self) -> None:
        if (
            type(self.corpora) is not tuple
            or not self.corpora
            or any(type(item) is not ManagedCorpusIngestIdentity for item in self.corpora)
            or type(self.presence) is not tuple
            or len(self.presence) != len(self.corpora)
            or any(type(item) is not ManagedDerivedPresenceObservation for item in self.presence)
        ):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_projection_evidence_invalid")
        expected_inventory = _episode_inventory(self.corpora)
        if self.episode_inventory != expected_inventory:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_episode_inventory_binding_invalid"
            )


@final
class ManagedHttpPolicyRegistryEvidenceBinding:
    """Own exact registry evidence validation, snapshotting, and projection."""

    __slots__ = ("_material",)

    def __init__(self) -> None:
        self._material: ManagedHttpPolicyRegistryMaterial | None = None

    def exact_projection_evidence(
        self,
        *,
        phase: str,
        evidence: tuple[ManagedHttpPolicyObservedCorpusEvidence, ...],
    ) -> ManagedHttpPolicyExactProjectionEvidence:
        if phase != "canonical-source-sealed" or not evidence:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_projection_evidence_unavailable"
            )
        corpora = tuple(item.bundle for item in evidence)
        return ManagedHttpPolicyExactProjectionEvidence(
            corpora=corpora,
            presence=tuple(item.presence for item in evidence),
            episode_inventory=_episode_inventory(corpora),
        )

    def observe_corpora(
        self,
        *,
        bundles: tuple[ManagedCorpusIngestIdentity, ...],
        infinity_target_identity_sha256: str,
        mem0_target_identity_sha256: str,
        observe_presence: Callable[..., ManagedDerivedPresenceObservation],
    ) -> tuple[ManagedHttpPolicyObservedCorpusEvidence, ...]:
        if not bundles or any(
            bundle.infinity_target_identity_sha256 != infinity_target_identity_sha256
            or bundle.mem0_target_identity_sha256 != mem0_target_identity_sha256
            for bundle in bundles
        ):
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_ingest_target_binding_invalid"
            )
        return tuple(
            ManagedHttpPolicyObservedCorpusEvidence(
                bundle=bundle,
                presence=observe_presence(
                    scope=bundle.scope,
                    manifest=bundle.manifest,
                ),
            )
            for bundle in bundles
        )

    def validate_corpus_evidence(
        self,
        *,
        evidence: tuple[ManagedHttpPolicyObservedCorpusEvidence, ...],
        expected_corpus_ids: set[str],
    ) -> None:
        corpus_ids = tuple(item.bundle.corpus_id for item in evidence)
        if (
            type(evidence) is not tuple
            or not evidence
            or any(type(item) is not ManagedHttpPolicyObservedCorpusEvidence for item in evidence)
            or len(evidence) != len(expected_corpus_ids)
            or set(corpus_ids) != expected_corpus_ids
        ):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_corpus_coverage_invalid")
        try:
            project_exact_corpus_bindings(tuple(item.bundle for item in evidence))
        except ValueError as exc:
            raise ManagedHttpPolicyLifecycleError(str(exc)) from None

    def bind_completion(
        self,
        *,
        material: ManagedHttpPolicyRegistryMaterial,
        phase: str,
    ) -> None:
        try:
            if type(material) is not ManagedHttpPolicyRegistryMaterial:
                raise TypeError
            captured = replace(material)
        except BaseException:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_registry_material_invalid"
            ) from None
        if self._material is not None:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_registry_binding_replay")
        if phase != "terminal-delete-sealed":
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_registry_binding_phase_invalid"
            )
        self._material = captured

    def corpus_material_for(
        self,
        *,
        corpora: tuple[ManagedHttpPolicyCorpusMaterial, ...],
        corpus_id: str,
    ) -> ManagedHttpPolicyCorpusMaterial:
        matches = tuple(item for item in corpora if item.corpus_id == corpus_id)
        if len(matches) != 1:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_corpus_binding_invalid")
        return matches[0]

    def bind_validation_material(
        self,
        material: ManagedHttpPolicyValidationMaterial,
    ) -> ManagedHttpPolicyValidationMaterial:
        registry = self._material
        if registry is None:
            return material
        return replace(
            material,
            adapter_id=registry.wrapper_adapter_id,
            implementation_sha256=registry.wrapper_implementation_sha256,
            registry=registry,
        )


def _episode_inventory(
    corpora: tuple[ManagedCorpusIngestIdentity, ...],
) -> tuple[ManagedProjectionEpisodeInventory, ...] | None:
    episode_lanes = tuple(item.canonical_episode_ids for item in corpora)
    if all(item is None for item in episode_lanes):
        return None
    if any(item is None for item in episode_lanes):
        raise ManagedHttpPolicyLifecycleError(
            "managed_http_policy_episode_inventory_coverage_invalid"
        )
    return tuple(
        ManagedProjectionEpisodeInventory(
            scope=corpus.scope,
            episode_ids=episode_ids,
        )
        for corpus, episode_ids in zip(corpora, episode_lanes, strict=True)
        if episode_ids is not None
    )


__all__ = (
    "ManagedHttpPolicyExactProjectionEvidence",
    "ManagedHttpPolicyObservedCorpusEvidence",
    "ManagedHttpPolicyRegistryEvidenceBinding",
)

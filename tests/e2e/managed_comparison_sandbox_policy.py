"""Canonical/source/delete evidence adapters over one shared sandbox state."""

from __future__ import annotations

from infinity_context_server import (
    memory_comparison_full_canonical_source_evidence_trust as canonical_source_trust,
)
from infinity_context_server.memory_comparison_full_canonical_evidence import (
    CanonicalEvidenceRequest,
    CanonicalLifecycleReceipt,
    CanonicalReadbackReceipt,
    issue_canonical_evidence_session,
    seal_canonical_evidence,
)
from infinity_context_server.memory_comparison_full_delete_evidence import (
    DeleteScopeRequest,
    InfinityCleanupWitness,
    InfinityReadbackWitness,
    Mem0CleanupWitness,
    Mem0ReadbackWitness,
    create_terminal_delete_evidence_session,
    create_trusted_delete_verification_coordinator,
    seal_terminal_delete_evidence,
)
from infinity_context_server.memory_comparison_full_delete_evidence_trust import (
    _create_delete_verification_trust_policy_issuer_for_composition_root,
    _issue_delete_verification_trust_policy_for_composition_root,
)
from infinity_context_server.memory_comparison_full_policy_component_validation import (
    FullPolicyEvidencePair,
    FullPolicyManifestItem,
    FullPolicyRunManifest,
    FullPolicyTerminalDeleteEvidence,
    create_full_policy_component_validation_session,
    seal_full_policy_component_validation,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_full_source_evidence import (
    InfinityIngestedSourceReceipt,
    InfinityRetrievedSourceReceipt,
    Mem0SourceReadbackReceipt,
    Mem0SourceRequestReceipt,
    SourceEvidenceRequest,
    issue_source_evidence_session,
    seal_source_evidence,
)
from infinity_context_server.memory_comparison_managed_attestation import (
    VerifiedManagedCompositionAttestation,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedExecutionArtifacts,
    ManagedRunCase,
)
from managed_comparison_sandbox_adapters import (
    INFINITY_BACKEND,
    MEM0_BACKEND,
    SandboxBackendState,
    SandboxTrace,
    implementation_sha256,
)


class SandboxPolicyPort:
    def __init__(self, trace: SandboxTrace, state: SandboxBackendState) -> None:
        self.adapter_id = f"{state.scenario.scenario_id}-policy"
        self.implementation_sha256 = implementation_sha256(
            "policy",
            scenario_id=state.scenario.scenario_id,
        )
        self.trace = trace
        self._state = state
        self._items: tuple[FullPolicyManifestItem, ...] = ()
        self._pairs: tuple[FullPolicyEvidencePair, ...] = ()
        self._attestation: str | None = None
        self._terminal: FullPolicyTerminalDeleteEvidence | None = None

    def seal_canonical_source(
        self,
        *,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
        ingest_receipts: tuple[object, ...],
        execution: ManagedExecutionArtifacts,
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
    ) -> tuple[object, ...]:
        assert type(managed_attestation) is VerifiedManagedCompositionAttestation
        assert cases and len(ingest_receipts) == 2 * len(cases)
        assert type(execution) is ManagedExecutionArtifacts
        assert len(self._state.stores) == 2 * len(cases)
        self._attestation = managed_attestation_commitment_sha256
        self._items = tuple(_policy_item(case, self._state) for case in cases)
        self.trace.add("canonical_source.issue")
        self._pairs = tuple(
            _policy_pair(
                bindings,
                item,
                index,
                managed_attestation_commitment_sha256,
                self._state,
                cases[index - 1].corpus_id,
            )
            for index, item in enumerate(self._items, start=1)
        )
        self.trace.add("canonical_source.seal")
        return self._pairs

    def terminal_delete(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        pass_index: int,
    ) -> object:
        assert len(bindings.backend_targets) == 2 and len(target_identity_sha256) == 64
        observation = self._state.delete_scope(
            backend_role,
            self._state.scenario.scope_id,
            pass_index,
        )
        self.trace.add(f"delete:{backend_role}:{pass_index}")
        return observation

    def seal_terminal_delete(
        self,
        *,
        bindings: FullComparisonRunBindings,
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        receipts: tuple[object, ...],
    ) -> object:
        assert type(managed_attestation) is VerifiedManagedCompositionAttestation
        assert len(managed_attestation_commitment_sha256) == 64
        expected = tuple(
            (role, attempt) for attempt in (1, 2) for role in (INFINITY_BACKEND, MEM0_BACKEND)
        )
        assert tuple((item.backend_role, item.pass_index) for item in receipts) == expected
        corpus_count = len(self._state.scenario.corpus_ids)
        assert tuple(item.deleted_count for item in receipts) == (
            corpus_count,
            corpus_count,
            0,
            0,
        )
        assert all(item.remaining_count == 0 for item in receipts)
        if self._attestation is not None:
            assert managed_attestation_commitment_sha256 == self._attestation
        self._attestation = managed_attestation_commitment_sha256
        self._terminal = _terminal_delete(
            bindings, managed_attestation_commitment_sha256, self._state
        )
        self.trace.add("delete.seal")
        return self._terminal

    def aggregate_policy(
        self,
        *,
        bindings: FullComparisonRunBindings,
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        canonical_source: tuple[object, ...],
        terminal_delete: object,
    ) -> object:
        assert type(managed_attestation) is VerifiedManagedCompositionAttestation
        assert canonical_source is self._pairs
        assert terminal_delete is self._terminal
        assert self._attestation is not None
        assert managed_attestation_commitment_sha256 == self._attestation
        assert self._terminal is not None
        manifest = FullPolicyRunManifest(
            run_id=bindings.run_id,
            profile_id=bindings.profile_id,
            infinity_backend_id=INFINITY_BACKEND,
            mem0_backend_id=MEM0_BACKEND,
            scope_id=self._state.scenario.scope_id,
            delete_source_id=self._state.scenario.delete_source_id,
            managed_attestation_commitment_sha256=self._attestation,
            items=self._items,
        )
        session = create_full_policy_component_validation_session(
            manifest=manifest,
            evidence_pairs=self._pairs,
            terminal_delete=self._terminal,
            consumer_id=self._state.scenario.scenario_id,
        )
        self.trace.add("policy.aggregate")
        return seal_full_policy_component_validation(session)


def _policy_item(
    case: ManagedRunCase,
    state: SandboxBackendState,
) -> FullPolicyManifestItem:
    source = f"source://{state.scenario.benchmark}/{case.corpus_id}"
    infinity = state.source(INFINITY_BACKEND, case.corpus_id)
    mem0 = state.source(MEM0_BACKEND, case.corpus_id)
    assert infinity.canonical_bytes == mem0.canonical_bytes
    assert infinity.source_sha256 == mem0.source_sha256
    return FullPolicyManifestItem(
        case_id=case.case_id,
        source_ref=source,
        source_revision=1,
        source_sha256=infinity.source_sha256,
    )


class _PolicyItemSandbox:
    def __init__(
        self,
        bindings: FullComparisonRunBindings,
        item: FullPolicyManifestItem,
        index: int,
        state: SandboxBackendState,
        corpus_id: str,
    ) -> None:
        self.bindings = bindings
        self.item = item
        self.index = index
        self.state = state
        self.corpus_id = corpus_id

    def _require_present(self) -> None:
        infinity = self.state.source(INFINITY_BACKEND, self.corpus_id)
        mem0 = self.state.source(MEM0_BACKEND, self.corpus_id)
        assert infinity.canonical_bytes == mem0.canonical_bytes
        assert infinity.source_sha256 == self.item.source_sha256
        assert mem0.source_sha256 == self.item.source_sha256

    def _identity(self, backend_id: str) -> dict[str, object]:
        return {
            "run_id": self.bindings.run_id,
            "profile_id": self.bindings.profile_id,
            "backend_id": backend_id,
            "scope_id": self.state.scenario.scope_id,
            "case_id": self.item.case_id,
            "source_ref": self.item.source_ref,
        }

    def _source_identity(self, backend_id: str) -> dict[str, object]:
        return {
            **self._identity(backend_id),
            "source_revision": self.item.source_revision,
            "source_sha256": self.item.source_sha256,
        }

    def observe_lifecycle(self, request: CanonicalEvidenceRequest) -> CanonicalLifecycleReceipt:
        del request
        self._require_present()
        return CanonicalLifecycleReceipt(
            **self._identity(INFINITY_BACKEND),
            canonical_record_id=f"record-{self.index}",
            status="active",
            generation=3,
            watermark=7,
            derived_only=False,
        )

    def read_canonical(
        self,
        request: CanonicalEvidenceRequest,
        *,
        canonical_record_id: str,
    ) -> CanonicalReadbackReceipt:
        del request
        self._require_present()
        return CanonicalReadbackReceipt(
            **self._identity(INFINITY_BACKEND),
            canonical_record_id=canonical_record_id,
            status="active",
            generation=3,
            watermark=7,
            found=True,
            derived_only=False,
        )

    def retrieve_source(self, request: SourceEvidenceRequest) -> InfinityRetrievedSourceReceipt:
        del request
        self._require_present()
        return InfinityRetrievedSourceReceipt(
            **self._source_identity(INFINITY_BACKEND),
            retrieved_item_id=f"retrieved-{self.index}",
            ingestion_id=f"ingestion-{self.index}",
            derived_only=False,
        )

    def read_ingested_source(
        self,
        request: SourceEvidenceRequest,
        *,
        ingestion_id: str,
    ) -> InfinityIngestedSourceReceipt:
        del request
        self._require_present()
        return InfinityIngestedSourceReceipt(
            **self._source_identity(INFINITY_BACKEND),
            ingestion_id=ingestion_id,
            present=True,
            deleted=False,
        )

    def observe_source_request(self, request: SourceEvidenceRequest) -> Mem0SourceRequestReceipt:
        del request
        self._require_present()
        return Mem0SourceRequestReceipt(
            **self._source_identity(MEM0_BACKEND),
            request_id=f"request-{self.index}",
            accepted=True,
        )

    def read_source_result(
        self,
        request: SourceEvidenceRequest,
        *,
        request_id: str,
    ) -> Mem0SourceReadbackReceipt:
        del request
        self._require_present()
        return Mem0SourceReadbackReceipt(
            **self._source_identity(MEM0_BACKEND),
            request_id=request_id,
            memory_item_id=f"memory-{self.index}",
            found=True,
        )


def _policy_pair(
    bindings: FullComparisonRunBindings,
    item: FullPolicyManifestItem,
    index: int,
    attestation: str,
    state: SandboxBackendState,
    corpus_id: str,
) -> FullPolicyEvidencePair:
    sandbox = _PolicyItemSandbox(bindings, item, index, state, corpus_id)
    policy = canonical_source_trust._composition_issue_canonical_source_evidence_trust_policy(
        policy_id=f"sandbox-item-policy-{index}",
        canonical_backend_id=INFINITY_BACKEND,
        infinity_source_backend_id=INFINITY_BACKEND,
        mem0_source_backend_id=MEM0_BACKEND,
        canonical_adapter_id=f"sandbox-canonical-{index}",
        infinity_source_adapter_id=f"sandbox-source-{index}",
        mem0_source_adapter_id=f"sandbox-mem0-source-{index}",
        canonical_implementation_sha256="1" * 64,
        infinity_source_implementation_sha256="2" * 64,
        mem0_source_implementation_sha256="3" * 64,
        runtime_attestation_commitment=attestation,
        canonical_lifecycle_port=sandbox,
        canonical_readback_port=sandbox,
        infinity_retrieved_port=sandbox,
        infinity_ingested_port=sandbox,
        mem0_request_port=sandbox,
        mem0_readback_port=sandbox,
    )
    canonical = issue_canonical_evidence_session(
        run_id=bindings.run_id,
        profile_id=bindings.profile_id,
        backend_id=INFINITY_BACKEND,
        scope_id=state.scenario.scope_id,
        case_id=item.case_id,
        source_ref=item.source_ref,
        minimum_generation=3,
        minimum_watermark=7,
        lifecycle_port=sandbox,
        readback_port=sandbox,
        trust_policy=policy,
    )
    source = issue_source_evidence_session(
        run_id=bindings.run_id,
        profile_id=bindings.profile_id,
        scope_id=state.scenario.scope_id,
        case_id=item.case_id,
        source_ref=item.source_ref,
        source_revision=item.source_revision,
        source_sha256=item.source_sha256,
        infinity_backend_id=INFINITY_BACKEND,
        mem0_backend_id=MEM0_BACKEND,
        retrieved_port=sandbox,
        ingested_port=sandbox,
        mem0_request_port=sandbox,
        mem0_readback_port=sandbox,
        trust_policy=policy,
    )
    return FullPolicyEvidencePair(
        seal_canonical_evidence(canonical, trust_policy=policy),
        seal_source_evidence(source, trust_policy=policy),
        policy,
    )


class _InfinityDeleteSandbox:
    def __init__(self, state: SandboxBackendState) -> None:
        self.state = state

    def cleanup(self, request: DeleteScopeRequest) -> InfinityCleanupWitness:
        observed = self.state.delete_observations[(INFINITY_BACKEND, request.attempt)]
        return InfinityCleanupWitness(
            run_id=request.run_id,
            profile_id=request.profile_id,
            backend_id=request.backend_id,
            scope_id=request.scope_id,
            source_id=request.source_id,
            attempt=request.attempt,
            acknowledged=True,
            canonical_deleted_count=observed.deleted_count,
            derived_deleted_count=observed.deleted_count,
            already_absent=observed.deleted_count == 0,
        )

    def readback(self, request: DeleteScopeRequest) -> InfinityReadbackWitness:
        observed = self.state.delete_observations[(INFINITY_BACKEND, request.attempt)]
        return InfinityReadbackWitness(
            run_id=request.run_id,
            profile_id=request.profile_id,
            backend_id=request.backend_id,
            scope_id=request.scope_id,
            source_id=request.source_id,
            attempt=request.attempt,
            canonical_remaining_count=observed.remaining_count,
            derived_remaining_count=observed.remaining_count,
        )


class _Mem0DeleteSandbox:
    def __init__(self, state: SandboxBackendState) -> None:
        self.state = state

    def cleanup(self, request: DeleteScopeRequest) -> Mem0CleanupWitness:
        observed = self.state.delete_observations[(MEM0_BACKEND, request.attempt)]
        return Mem0CleanupWitness(
            run_id=request.run_id,
            profile_id=request.profile_id,
            backend_id=request.backend_id,
            scope_id=request.scope_id,
            source_id=request.source_id,
            attempt=request.attempt,
            acknowledged=True,
            deleted_count=observed.deleted_count,
            already_absent=observed.deleted_count == 0,
        )

    def readback(self, request: DeleteScopeRequest) -> Mem0ReadbackWitness:
        observed = self.state.delete_observations[(MEM0_BACKEND, request.attempt)]
        return Mem0ReadbackWitness(
            run_id=request.run_id,
            profile_id=request.profile_id,
            backend_id=request.backend_id,
            scope_id=request.scope_id,
            source_id=request.source_id,
            attempt=request.attempt,
            remaining_count=observed.remaining_count,
        )


def _terminal_delete(
    bindings: FullComparisonRunBindings,
    attestation: str,
    state: SandboxBackendState,
) -> FullPolicyTerminalDeleteEvidence:
    infinity = _InfinityDeleteSandbox(state)
    mem0 = _Mem0DeleteSandbox(state)
    issuer = _create_delete_verification_trust_policy_issuer_for_composition_root(
        authority_id=f"{state.scenario.scenario_id}-delete",
        authority_implementation_sha256=implementation_sha256(
            "delete-authority",
            scenario_id=state.scenario.scenario_id,
        ),
    )
    policy = _issue_delete_verification_trust_policy_for_composition_root(
        issuer,
        infinity_port=infinity,
        mem0_port=mem0,
        infinity_backend_id=INFINITY_BACKEND,
        mem0_backend_id=MEM0_BACKEND,
        infinity_adapter_id=f"{state.scenario.scenario_id}-infinity-delete",
        mem0_adapter_id=f"{state.scenario.scenario_id}-mem0-delete",
        infinity_implementation_sha256=implementation_sha256(
            "infinity-delete",
            scenario_id=state.scenario.scenario_id,
        ),
        mem0_implementation_sha256=implementation_sha256(
            "mem0-delete",
            scenario_id=state.scenario.scenario_id,
        ),
        external_attestation_commitment=attestation,
    )
    session = create_terminal_delete_evidence_session(
        run_id=bindings.run_id,
        profile_id=bindings.profile_id,
        infinity_backend_id=INFINITY_BACKEND,
        mem0_backend_id=MEM0_BACKEND,
        scope_id=state.scenario.scope_id,
        source_id=state.scenario.delete_source_id,
    )
    evidence = seal_terminal_delete_evidence(
        session,
        policy=policy,
        coordinator=create_trusted_delete_verification_coordinator(policy=policy),
    )
    return FullPolicyTerminalDeleteEvidence(evidence, session, policy)


__all__ = ("SandboxPolicyPort",)

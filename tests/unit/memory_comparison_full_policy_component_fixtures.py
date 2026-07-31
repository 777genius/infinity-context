from __future__ import annotations

from dataclasses import dataclass

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

RUN = "run-policy-1"
PROFILE = "profile-policy-1"
INFINITY_BACKEND = "infinity-context"
MEM0_BACKEND = "mem0"
SCOPE = "scope-policy-1"
DELETE_SOURCE = "corpus-policy-1"
ATTESTATION = "a" * 64


@dataclass(frozen=True, slots=True)
class PolicyAggregateFixture:
    manifest: FullPolicyRunManifest
    pairs: tuple[FullPolicyEvidencePair, ...]
    terminal_delete: FullPolicyTerminalDeleteEvidence


class PolicyItemSandbox:
    def __init__(self, item: FullPolicyManifestItem, index: int) -> None:
        self.item = item
        self.index = index

    def _identity(self, backend_id: str) -> dict[str, object]:
        return {
            "run_id": RUN,
            "profile_id": PROFILE,
            "backend_id": backend_id,
            "scope_id": SCOPE,
            "case_id": self.item.case_id,
            "source_ref": self.item.source_ref,
        }

    def _source_identity(self, backend_id: str) -> dict[str, object]:
        return {
            **self._identity(backend_id),
            "source_revision": self.item.source_revision,
            "source_sha256": self.item.source_sha256,
        }

    def observe_lifecycle(
        self,
        request: CanonicalEvidenceRequest,
    ) -> CanonicalLifecycleReceipt:
        del request
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
        return CanonicalReadbackReceipt(
            **self._identity(INFINITY_BACKEND),
            canonical_record_id=canonical_record_id,
            status="active",
            generation=3,
            watermark=7,
            found=True,
            derived_only=False,
        )

    def retrieve_source(
        self,
        request: SourceEvidenceRequest,
    ) -> InfinityRetrievedSourceReceipt:
        del request
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
        return InfinityIngestedSourceReceipt(
            **self._source_identity(INFINITY_BACKEND),
            ingestion_id=ingestion_id,
            present=True,
            deleted=False,
        )

    def observe_source_request(
        self,
        request: SourceEvidenceRequest,
    ) -> Mem0SourceRequestReceipt:
        del request
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
        return Mem0SourceReadbackReceipt(
            **self._source_identity(MEM0_BACKEND),
            request_id=request_id,
            memory_item_id=f"memory-{self.index}",
            found=True,
        )


class InfinityDeleteSandbox:
    def cleanup(self, request: DeleteScopeRequest) -> InfinityCleanupWitness:
        deleted = 1 if request.attempt == 1 else 0
        return InfinityCleanupWitness(
            run_id=request.run_id,
            profile_id=request.profile_id,
            backend_id=request.backend_id,
            scope_id=request.scope_id,
            source_id=request.source_id,
            attempt=request.attempt,
            acknowledged=True,
            canonical_deleted_count=deleted,
            derived_deleted_count=deleted,
            already_absent=deleted == 0,
        )

    def readback(self, request: DeleteScopeRequest) -> InfinityReadbackWitness:
        return InfinityReadbackWitness(
            run_id=request.run_id,
            profile_id=request.profile_id,
            backend_id=request.backend_id,
            scope_id=request.scope_id,
            source_id=request.source_id,
            attempt=request.attempt,
            canonical_remaining_count=0,
            derived_remaining_count=0,
        )


class Mem0DeleteSandbox:
    def cleanup(self, request: DeleteScopeRequest) -> Mem0CleanupWitness:
        deleted = 1 if request.attempt == 1 else 0
        return Mem0CleanupWitness(
            run_id=request.run_id,
            profile_id=request.profile_id,
            backend_id=request.backend_id,
            scope_id=request.scope_id,
            source_id=request.source_id,
            attempt=request.attempt,
            acknowledged=True,
            deleted_count=deleted,
            already_absent=deleted == 0,
        )

    def readback(self, request: DeleteScopeRequest) -> Mem0ReadbackWitness:
        return Mem0ReadbackWitness(
            run_id=request.run_id,
            profile_id=request.profile_id,
            backend_id=request.backend_id,
            scope_id=request.scope_id,
            source_id=request.source_id,
            attempt=request.attempt,
            remaining_count=0,
        )


def build_policy_aggregate_fixture(
    *,
    item_attestation: str = ATTESTATION,
    delete_attestation: str = ATTESTATION,
    item_count: int = 2,
) -> PolicyAggregateFixture:
    items = tuple(
        FullPolicyManifestItem(
            case_id=f"case-{index}",
            source_ref=f"source://conversation/{index}",
            source_revision=index,
            source_sha256=f"{index}" * 64,
        )
        for index in range(1, item_count + 1)
    )
    pairs = tuple(
        _item_pair(item, index=index, attestation=item_attestation)
        for index, item in enumerate(items, start=1)
    )
    manifest = FullPolicyRunManifest(
        run_id=RUN,
        profile_id=PROFILE,
        infinity_backend_id=INFINITY_BACKEND,
        mem0_backend_id=MEM0_BACKEND,
        scope_id=SCOPE,
        delete_source_id=DELETE_SOURCE,
        managed_attestation_commitment_sha256=ATTESTATION,
        items=items,
    )
    return PolicyAggregateFixture(
        manifest,
        pairs,
        _terminal_delete(attestation=delete_attestation),
    )


def _item_pair(
    item: FullPolicyManifestItem,
    *,
    index: int,
    attestation: str,
) -> FullPolicyEvidencePair:
    sandbox = PolicyItemSandbox(item, index)
    policy = canonical_source_trust._composition_issue_canonical_source_evidence_trust_policy(
        policy_id=f"item-policy-{index}",
        canonical_backend_id=INFINITY_BACKEND,
        infinity_source_backend_id=INFINITY_BACKEND,
        mem0_source_backend_id=MEM0_BACKEND,
        canonical_adapter_id=f"canonical-adapter-{index}",
        infinity_source_adapter_id=f"source-adapter-{index}",
        mem0_source_adapter_id=f"mem0-adapter-{index}",
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
    canonical_session = issue_canonical_evidence_session(
        run_id=RUN,
        profile_id=PROFILE,
        backend_id=INFINITY_BACKEND,
        scope_id=SCOPE,
        case_id=item.case_id,
        source_ref=item.source_ref,
        minimum_generation=3,
        minimum_watermark=7,
        lifecycle_port=sandbox,
        readback_port=sandbox,
        trust_policy=policy,
    )
    source_session = issue_source_evidence_session(
        run_id=RUN,
        profile_id=PROFILE,
        scope_id=SCOPE,
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
        seal_canonical_evidence(canonical_session, trust_policy=policy),
        seal_source_evidence(source_session, trust_policy=policy),
        policy,
    )


def _terminal_delete(*, attestation: str) -> FullPolicyTerminalDeleteEvidence:
    infinity = InfinityDeleteSandbox()
    mem0 = Mem0DeleteSandbox()
    issuer = _create_delete_verification_trust_policy_issuer_for_composition_root(
        authority_id="policy-aggregate-sandbox",
        authority_implementation_sha256="4" * 64,
    )
    policy = _issue_delete_verification_trust_policy_for_composition_root(
        issuer,
        infinity_port=infinity,
        mem0_port=mem0,
        infinity_backend_id=INFINITY_BACKEND,
        mem0_backend_id=MEM0_BACKEND,
        infinity_adapter_id="infinity-delete-sandbox",
        mem0_adapter_id="mem0-delete-sandbox",
        infinity_implementation_sha256="5" * 64,
        mem0_implementation_sha256="6" * 64,
        external_attestation_commitment=attestation,
    )
    session = create_terminal_delete_evidence_session(
        run_id=RUN,
        profile_id=PROFILE,
        infinity_backend_id=INFINITY_BACKEND,
        mem0_backend_id=MEM0_BACKEND,
        scope_id=SCOPE,
        source_id=DELETE_SOURCE,
    )
    evidence = seal_terminal_delete_evidence(
        session,
        policy=policy,
        coordinator=create_trusted_delete_verification_coordinator(policy=policy),
    )
    return FullPolicyTerminalDeleteEvidence(evidence, session, policy)

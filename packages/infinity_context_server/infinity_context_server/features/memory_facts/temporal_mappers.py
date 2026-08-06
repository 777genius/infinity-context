"""Translate temporal HTTP decisions into the memory_facts public API."""

from __future__ import annotations

import infinity_context_core.features.memory_facts.public as memory_facts

from infinity_context_server.features.memory_facts.mappers import (
    source_ref_request_to_public,
)


def confirm_fact_command(
    fact_id: str,
    request,
    *,
    scope: memory_facts.MemoryFactScope,
    actor_id: str,
    idempotency_key: str,
    authorized_code_scope: memory_facts.FactCodeScopeReference | None,
) -> memory_facts.ConfirmFactCommand:
    return memory_facts.ConfirmFactCommand(
        identity=_identity(fact_id, scope),
        expected_version=request.expected_version,
        confirmed_at=request.confirmed_at,
        confirmation_basis=request.confirmation_basis,
        evidence_refs=_evidence_refs(request),
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        authorized_code_scope=authorized_code_scope,
    )


def end_fact_validity_command(
    fact_id: str,
    request,
    *,
    scope: memory_facts.MemoryFactScope,
    actor_id: str,
    idempotency_key: str,
    authorized_code_scope: memory_facts.FactCodeScopeReference | None,
) -> memory_facts.EndFactValidityCommand:
    return memory_facts.EndFactValidityCommand(
        identity=_identity(fact_id, scope),
        expected_version=request.expected_version,
        effective_at=request.effective_at,
        reason_code=request.reason_code,
        evidence_refs=_evidence_refs(request),
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        authorized_code_scope=authorized_code_scope,
    )


def supersede_fact_command(
    predecessor_fact_id: str,
    request,
    *,
    scope: memory_facts.MemoryFactScope,
    actor_id: str,
    idempotency_key: str,
    authorized_code_scope: memory_facts.FactCodeScopeReference | None,
) -> memory_facts.SupersedeFactCommand:
    return memory_facts.SupersedeFactCommand(
        successor_identity=_identity(request.successor_fact_id, scope),
        predecessor_identity=_identity(predecessor_fact_id, scope),
        expected_successor_version=request.expected_successor_version,
        expected_predecessor_version=request.expected_predecessor_version,
        effective_at=request.effective_at,
        evidence_refs=_evidence_refs(request),
        actor_id=actor_id,
        reason_code=request.reason_code,
        idempotency_key=idempotency_key,
        authorized_code_scope=authorized_code_scope,
    )


def dispute_facts_command(
    challenged_fact_id: str,
    request,
    *,
    scope: memory_facts.MemoryFactScope,
    actor_id: str,
    idempotency_key: str,
    authorized_code_scope: memory_facts.FactCodeScopeReference | None,
) -> memory_facts.DisputeFactsCommand:
    return memory_facts.DisputeFactsCommand(
        challenger_identity=_identity(request.challenger_fact_id, scope),
        challenged_identity=_identity(challenged_fact_id, scope),
        expected_challenger_version=request.expected_challenger_version,
        expected_challenged_version=request.expected_challenged_version,
        evidence_refs=_evidence_refs(request),
        actor_id=actor_id,
        reason_code=request.reason_code,
        idempotency_key=idempotency_key,
        authorized_code_scope=authorized_code_scope,
    )


def reinstate_supersession_command(
    request,
    *,
    scope: memory_facts.MemoryFactScope,
    actor_id: str,
    idempotency_key: str,
    authorized_code_scope: memory_facts.FactCodeScopeReference | None,
) -> memory_facts.ReinstateSupersededFactCommand:
    return memory_facts.ReinstateSupersededFactCommand(
        scope=scope,
        supersession_decision_id=request.supersession_decision_id,
        expected_rejected_successor_version=request.expected_rejected_successor_version,
        expected_original_predecessor_version=request.expected_original_predecessor_version,
        evidence_refs=_evidence_refs(request),
        actor_id=actor_id,
        reason_code=request.reason_code,
        idempotency_key=idempotency_key,
        authorized_code_scope=authorized_code_scope,
    )


def temporal_decision_to_response(decision) -> dict[str, object]:
    return {
        "id": decision.decision_id,
        "type": decision.decision_type.value,
        "source_fact_id": decision.source_fact_id,
        "source_fact_version": decision.source_fact_version,
        "target_fact_id": decision.target_fact_id,
        "target_fact_version": decision.target_fact_version,
        "effective_at": decision.effective_at.isoformat(),
        "applied_at": decision.applied_at.isoformat(),
        "actor_id": decision.actor_id,
        "policy_version": decision.policy_version,
        "reason_code": decision.reason_code,
        "compensates_decision_id": decision.compensates_decision_id,
        "outbox_message_ids": list(decision.outbox_message_ids),
    }


def supersession_relation_to_response(relation) -> dict[str, object]:
    return {
        "id": relation.relation_id,
        "successor_fact_id": relation.successor_fact_id,
        "successor_fact_version": relation.successor_fact_version,
        "predecessor_fact_id": relation.predecessor_fact_id,
        "predecessor_fact_version": relation.predecessor_fact_version,
        "effective_at": relation.effective_at.isoformat(),
        "decision_id": relation.decision_id,
    }


def _identity(
    fact_id: str,
    scope: memory_facts.MemoryFactScope,
) -> memory_facts.MemoryFactIdentity:
    return memory_facts.MemoryFactIdentity(fact_id=fact_id, scope=scope)


def _evidence_refs(request) -> tuple[memory_facts.MemoryFactEvidenceRef, ...]:
    return tuple(
        memory_facts.MemoryFactEvidenceRef(
            source_ref=source_ref_request_to_public(item.source_ref),
            evidence_id=item.evidence_id,
        )
        for item in request.evidence_refs
    )


__all__ = (
    "confirm_fact_command",
    "dispute_facts_command",
    "end_fact_validity_command",
    "reinstate_supersession_command",
    "supersede_fact_command",
    "supersession_relation_to_response",
    "temporal_decision_to_response",
)

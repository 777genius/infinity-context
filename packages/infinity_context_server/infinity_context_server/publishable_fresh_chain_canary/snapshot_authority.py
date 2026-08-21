"""Exact semantic validation for terminal fresh-chain ledger snapshots."""

from __future__ import annotations

from .authority import (
    FRESH_CHAIN_AUTHORITY_ID,
    FRESH_CHAIN_STATIC_AUTHORITY_SHA256,
    FreshChainCanaryAuthority,
    fresh_chain_static_authority_payload,
)
from .authorization import FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION
from .ledger_models import (
    FRESH_CHAIN_STAGES,
    FreshChainSnapshot,
    canonical_sha256,
)

_EXTRACTION_RESULT_KEYS = {
    "admission_commitment_sha256",
    "operation_id_sha256",
    "output_text_sha256",
    "request_body_sha256",
    "run_identity_commitment_sha256",
    "runtime_binding_commitment_sha256",
    "scope_sha256",
    "source_projection_commitment_sha256",
    "unit_identity_sha256",
    "unit_sha256",
}
_EVALUATION_RESULT_KEYS = {
    "bridge_intent_sha256",
    "encrypted_output_sha256",
    "output_text_sha256",
    "request_body_sha256",
    "response_body_sha256",
}
_HANDOFF_KEYS = {
    "extraction_intent_sha256",
    "handoff_sha256",
    "memory_count_sha256",
    "retrieval_material_sha256",
    "source_commitment_sha256",
    "source_projection_commitment_sha256",
}
_PLAN_KEYS = {
    "authorization_capability_sha256",
    "dynamic_authority_sha256",
    "static_authority_sha256",
}


def exact_success_snapshot_authority(snapshot: FreshChainSnapshot) -> bool:
    """Return whether a terminal snapshot proves the concrete fixed 1+4 seams."""

    if type(snapshot) is not FreshChainSnapshot or len(snapshot.stages) != 5:
        return False
    plan = snapshot.plan
    stages = snapshot.stages
    retrieval = snapshot.retrieval_handoff
    cleanup = snapshot.cleanup
    terminal = snapshot.terminal_outcome
    source_projection = snapshot.source_projection_commitment_sha256
    if (
        retrieval is None
        or cleanup is None
        or terminal is None
        or type(source_projection) is not str
        or len(source_projection) != 64
        or any(character not in "0123456789abcdef" for character in source_projection)
    ):
        return False
    static = fresh_chain_static_authority_payload()
    evaluation = static.get("evaluation")
    if type(evaluation) is not dict:
        return False
    plan_commitments = dict(plan.commitments)
    if (
        plan.run_id != FRESH_CHAIN_AUTHORITY_ID
        or set(plan_commitments) != _PLAN_KEYS
        or plan_commitments.get("authorization_capability_sha256")
        != FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION.commitment_sha256
        or plan_commitments.get("static_authority_sha256") != FRESH_CHAIN_STATIC_AUTHORITY_SHA256
        or plan_commitments.get("dynamic_authority_sha256")
        != FreshChainCanaryAuthority(
            plan.namespace_commitment_sha256,
            plan.source_commitment_sha256,
        ).commitment_sha256
        or plan.common_condition_policy_sha256
        != canonical_sha256(evaluation.get("common_condition"))
    ):
        return False
    handoff = dict(retrieval.commitments)
    if (
        set(handoff) != _HANDOFF_KEYS
        or handoff.get("extraction_intent_sha256") != stages[0].intent_sha256
        or handoff.get("source_commitment_sha256") != plan.source_commitment_sha256
        or handoff.get("source_projection_commitment_sha256") != source_projection
    ):
        return False
    for index, record in enumerate(stages):
        intents = dict(record.intent_commitments)
        expected_intents = {
            "namespace_commitment_sha256": plan.namespace_commitment_sha256,
            "source_commitment_sha256": plan.source_commitment_sha256,
            "source_projection_commitment_sha256": source_projection,
        }
        if record.stage == "mem0_answer":
            expected_intents["retrieval_handoff_sha256"] = handoff["handoff_sha256"]
        results = dict(record.result_commitments)
        expected_result_keys = _EXTRACTION_RESULT_KEYS if index == 0 else _EVALUATION_RESULT_KEYS
        if (
            record.status != "succeeded"
            or record.result_sha256 is None
            or record.failure_sha256 is not None
            or record.provider_disposition is not None
            or intents != expected_intents
            or set(results) != expected_result_keys
            or results.get("request_body_sha256") != record.request_sha256
        ):
            return False
    if (
        stages[0].input_authority_sha256 != source_projection
        or stages[1].input_authority_sha256 != plan.source_commitment_sha256
        or stages[2].input_authority_sha256 != stages[1].result_sha256
        or stages[3].input_authority_sha256 != retrieval.retrieval_authority_sha256
        or stages[4].input_authority_sha256 != stages[3].result_sha256
        or tuple(record.stage for record in stages) != FRESH_CHAIN_STAGES
        or dict(stages[0].result_commitments).get("source_projection_commitment_sha256")
        != source_projection
    ):
        return False
    expected_terminal = canonical_sha256(
        {
            "activation_evidence_only": True,
            "cleanup": cleanup.material(),
            "ordered_receipt_ids": list(snapshot.ordered_receipt_ids),
            "plan_commitment_sha256": plan.commitment_sha256,
            "publishable": False,
            "retrieval_handoff": retrieval.material(),
            "source_projection_commitment_sha256": source_projection,
        }
    )
    return terminal.status == "succeeded" and terminal.outcome_sha256 == expected_terminal


__all__ = ("exact_success_snapshot_authority",)

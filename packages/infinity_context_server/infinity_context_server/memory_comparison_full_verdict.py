"""Sealed verdict and the only public projection for full comparisons."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import threading
import weakref
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_full_run_evidence import (
    FULL_COMPARISON_CANARY_WAIVER_CODES,
    FULL_COMPARISON_COMPONENT_KINDS,
    FULL_COMPARISON_RUN_EVIDENCE_SCHEMA_VERSION,
    FullComparisonEvidenceError,
    FullComparisonRunEvidence,
    _consume_full_comparison_run_evidence,
    _InspectedRunEvidence,
    _revalidate_consumed_full_comparison_run_evidence,
)
from infinity_context_server.memory_comparison_full_scope import (
    FULL_COMPARISON_SCOPE_CANARY,
)

FULL_COMPARISON_VERDICT_SCHEMA_VERSION = "memory-comparison-full-verdict.v1"
_TOKEN = object()
_LOCK = threading.RLock()


class FullComparisonVerdictError(FullComparisonEvidenceError):
    """Raised when a full verdict is forged, stale, or replayed."""


@final
class FullComparisonVerdict:
    """Sealed typed output whose public form requires live revalidation."""

    __slots__ = ("__commitment", "__nonce", "__weakref__")

    def __init__(self, *, commitment: str, nonce: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise FullComparisonVerdictError("verdicts must be verified")
        self.__commitment = commitment
        self.__nonce = nonce

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullComparisonVerdict is final")

    def __repr__(self) -> str:
        return "FullComparisonVerdict(<sealed>)"

    def __copy__(self) -> object:
        raise TypeError("full comparison verdicts are noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("full comparison verdicts are noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("full comparison verdicts are nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("full comparison verdicts are nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("full comparison verdicts are nonserializable")


@dataclass(frozen=True, slots=True)
class _VerdictState:
    evidence: FullComparisonRunEvidence
    body: dict[str, object]
    body_sha256: str
    commitment: str
    nonce: str


_VERDICTS: weakref.WeakKeyDictionary[FullComparisonVerdict, _VerdictState] = (
    weakref.WeakKeyDictionary()
)


def verify_full_comparison_run(
    evidence: FullComparisonRunEvidence,
) -> FullComparisonVerdict:
    """Consume one exact evidence object and seal its current fail-closed verdict."""

    inspected = _consume_full_comparison_run_evidence(evidence)
    body = _verdict_body(inspected)
    body_sha256 = _json_sha256(body)
    nonce = hashlib.sha256(
        f"{inspected.evidence_commitment_sha256}:{id(evidence)}".encode()
    ).hexdigest()
    commitment = _json_sha256(
        {
            "body_sha256": body_sha256,
            "evidence_commitment_sha256": inspected.evidence_commitment_sha256,
            "nonce": nonce,
        }
    )
    verdict = FullComparisonVerdict(
        commitment=commitment,
        nonce=nonce,
        _token=_TOKEN,
    )
    with _LOCK:
        _VERDICTS[verdict] = _VerdictState(
            evidence=evidence,
            body=copy.deepcopy(body),
            body_sha256=body_sha256,
            commitment=commitment,
            nonce=nonce,
        )
    return verdict


def public_full_comparison_verdict(
    verdict: FullComparisonVerdict,
) -> dict[str, object]:
    """Return a fresh JSON projection only after exact live revalidation."""

    if type(verdict) is not FullComparisonVerdict:
        raise FullComparisonVerdictError("verdict type must be exact")
    with _LOCK:
        state = _VERDICTS.get(verdict)
    if state is None:
        raise FullComparisonVerdictError("verdict was not verified")
    _validate_verdict_fields(verdict, state)
    inspected = _revalidate_consumed_full_comparison_run_evidence(state.evidence)
    current = _verdict_body(inspected)
    current_sha256 = _json_sha256(current)
    current_commitment = _json_sha256(
        {
            "body_sha256": current_sha256,
            "evidence_commitment_sha256": inspected.evidence_commitment_sha256,
            "nonce": state.nonce,
        }
    )
    if (
        not hmac.compare_digest(current_sha256, state.body_sha256)
        or not hmac.compare_digest(current_commitment, state.commitment)
        or current != state.body
    ):
        raise FullComparisonVerdictError("verdict became stale")
    return {**copy.deepcopy(current), "verdict_commitment_sha256": state.commitment}


def _verdict_body(inspected: _InspectedRunEvidence) -> dict[str, object]:
    bindings = inspected.bindings
    by_kind = {item.component_kind: item for item in inspected.components}
    component_summaries: list[dict[str, object]] = []
    blockers: list[str] = []
    for kind in FULL_COMPARISON_COMPONENT_KINDS:
        component = by_kind.get(kind)
        if component is None:
            blocker = f"missing_{kind}_component"
            component_summaries.append(
                {
                    "component_kind": kind,
                    "status": "missing",
                    "binding_commitment_sha256": bindings.binding_commitment_sha256,
                }
            )
            blockers.append(blocker)
            continue
        component_summaries.append(
            {
                "component_kind": kind,
                "status": component.status,
                "binding_commitment_sha256": component.binding_commitment_sha256,
            }
        )
        if component.blocker is not None:
            blockers.append(component.blocker)

    policy_blockers = list(inspected.policy_blockers)
    blockers.extend(policy_blockers)
    waivers: list[str] = []
    if bindings.scope == FULL_COMPARISON_SCOPE_CANARY:
        waivers = [code for code in FULL_COMPARISON_CANARY_WAIVER_CODES if code in policy_blockers]
    effective_blockers = [code for code in blockers if code not in waivers]
    canary = bindings.scope == FULL_COMPARISON_SCOPE_CANARY
    publishable = bool(not canary and not effective_blockers)
    eligible = not effective_blockers

    return {
        "schema_version": FULL_COMPARISON_VERDICT_SCHEMA_VERSION,
        "evidence_schema_version": FULL_COMPARISON_RUN_EVIDENCE_SCHEMA_VERSION,
        "run_id": bindings.run_id,
        "profile_id": bindings.profile_id,
        "scope": bindings.scope,
        "claim_scope": "diagnostic_canary" if canary else "full_comparison",
        "publishable": publishable,
        "eligible": eligible,
        "blocking_reasons": effective_blockers,
        "waivers": waivers,
        "commitments": {
            "run_nonce_sha256": bindings.run_nonce_commitment_sha256,
            "runtime_probe_nonce_sha256": bindings.runtime_probe_nonce_sha256,
            "methodology_sha256": bindings.methodology_commitment_sha256,
            "dataset_sha256": bindings.dataset_sha256,
            "selection_sha256": bindings.selection_fingerprint_sha256,
            "binding_sha256": bindings.binding_commitment_sha256,
            "evidence_sha256": inspected.evidence_commitment_sha256,
        },
        "backend_targets": [
            {
                "backend_role": item.backend_role,
                "target_identity_sha256": item.target_identity_sha256,
            }
            for item in bindings.backend_targets
        ],
        "components": component_summaries,
    }


def _validate_verdict_fields(
    verdict: FullComparisonVerdict,
    state: _VerdictState,
) -> None:
    try:
        commitment = verdict._FullComparisonVerdict__commitment
        nonce = verdict._FullComparisonVerdict__nonce
    except (AttributeError, TypeError):
        raise FullComparisonVerdictError("verdict integrity failed") from None
    if (
        type(commitment) is not str
        or type(nonce) is not str
        or not hmac.compare_digest(commitment, state.commitment)
        or not hmac.compare_digest(nonce, state.nonce)
    ):
        raise FullComparisonVerdictError("verdict integrity failed")


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = (
    "FULL_COMPARISON_VERDICT_SCHEMA_VERSION",
    "FullComparisonVerdict",
    "FullComparisonVerdictError",
    "public_full_comparison_verdict",
    "verify_full_comparison_run",
)

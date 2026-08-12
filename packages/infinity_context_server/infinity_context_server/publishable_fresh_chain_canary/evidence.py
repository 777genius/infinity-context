"""Authenticated non-publishable activation evidence for the fresh chain."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from infinity_context_server.features.subscription_runtime_bridge.json_boundary import (
    BridgeJsonError,
    strict_json_loads,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    BridgeProcessError,
)
from infinity_context_server.features.subscription_runtime_bridge.process_files import (
    read_private_file,
    verify_private_directory,
    write_private_json_once,
)

from .contracts import (
    FRESH_CHAIN_AUTHENTICATION_KIND,
    FRESH_CHAIN_CASE_ID,
    FRESH_CHAIN_DISPLAY_NAME,
    FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS,
    FRESH_CHAIN_PROVIDER_KIND,
    FRESH_CHAIN_STAGES,
    FreshChainCallResult,
    FreshChainCanaryError,
    FreshChainCleanupResult,
    FreshChainRetrievalHandoff,
)
from .ledger_models import (
    CleanupBinding,
    FreshChainPlan,
    FreshChainSnapshot,
    FreshChainStageRecord,
    RetrievalHandoff,
    TerminalOutcome,
    TokenUsage,
)
from .ledger_models import (
    canonical_sha256 as ledger_canonical_sha256,
)
from .snapshot_authority import exact_success_snapshot_authority

FRESH_CHAIN_EVIDENCE_SCHEMA = "memory-comparison-publishable-fresh-chain-canary.v1"
_HMAC_DOMAIN = b"infinity-context/fresh-chain-canary/evidence/v1\0"
_MAX_BYTES = 256 * 1024


@final
@dataclass(frozen=True, slots=True)
class FreshChainCanaryEvidence:
    namespace_commitment_sha256: str
    source_commitment_sha256: str
    source_projection_commitment_sha256: str
    retrieval_handoff_sha256: str
    retrieval_authority_sha256: str
    cleanup_commitment_sha256: str
    ledger_plan_commitment_sha256: str
    ledger_terminal_sha256: str
    ledger_head_hmac_sha256: str
    ordered_physical_receipt_sha256: tuple[str, str, str, str, str]
    ordered_usage: tuple[
        dict[str, int],
        dict[str, int],
        dict[str, int],
        dict[str, int],
        dict[str, int],
    ]
    authentication_hmac_sha256: str
    evidence_sha256: str = field(init=False)
    publishable: bool = field(default=False, init=False)
    activation_evidence: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        digests = (
            self.namespace_commitment_sha256,
            self.source_commitment_sha256,
            self.source_projection_commitment_sha256,
            self.retrieval_handoff_sha256,
            self.retrieval_authority_sha256,
            self.cleanup_commitment_sha256,
            self.ledger_plan_commitment_sha256,
            self.ledger_terminal_sha256,
            self.ledger_head_hmac_sha256,
            *self.ordered_physical_receipt_sha256,
            self.authentication_hmac_sha256,
        )
        if (
            any(not _sha(value) for value in digests)
            or type(self.ordered_physical_receipt_sha256) is not tuple
            or len(self.ordered_physical_receipt_sha256) != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
            or len(set(self.ordered_physical_receipt_sha256))
            != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
            or type(self.ordered_usage) is not tuple
            or len(self.ordered_usage) != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
            or any(not _usage(value) for value in self.ordered_usage)
            or hmac.compare_digest(
                self.namespace_commitment_sha256,
                self.source_commitment_sha256,
            )
            or self.publishable is not False
            or self.activation_evidence is not True
        ):
            _fail("fresh_chain_evidence_invalid")
        object.__setattr__(
            self,
            "evidence_sha256",
            hashlib.sha256(_canonical(self.body())).hexdigest(),
        )

    def body(self) -> dict[str, object]:
        totals = {
            key: sum(item[key] for item in self.ordered_usage)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        return {
            "activation_evidence": True,
            "authentication": FRESH_CHAIN_AUTHENTICATION_KIND,
            "case_id": FRESH_CHAIN_CASE_ID,
            "cleanup_commitment_sha256": self.cleanup_commitment_sha256,
            "cleanup_terminal_state": "deleted",
            "display_name": FRESH_CHAIN_DISPLAY_NAME,
            "expected_physical_attempt_count": FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS,
            "fresh_namespace": True,
            "full_profile_execution_enabled": False,
            "full_publication_gate_satisfied": False,
            "full_receipt_eligible": False,
            "ledger_head_hmac_sha256": self.ledger_head_hmac_sha256,
            "ledger_plan_commitment_sha256": self.ledger_plan_commitment_sha256,
            "ledger_terminal_sha256": self.ledger_terminal_sha256,
            "measured_physical_attempt_count": len(self.ordered_physical_receipt_sha256),
            "namespace_commitment_sha256": self.namespace_commitment_sha256,
            "ordered_physical_receipt_sha256": list(self.ordered_physical_receipt_sha256),
            "ordered_stages": list(FRESH_CHAIN_STAGES),
            "ordered_usage": list(self.ordered_usage),
            "paid_go_ready": False,
            "provider": FRESH_CHAIN_PROVIDER_KIND,
            "publishable": False,
            "quality_or_superiority_claimed": False,
            "result_2040": False,
            "retrieval_authority_sha256": self.retrieval_authority_sha256,
            "retrieval_handoff_sha256": self.retrieval_handoff_sha256,
            "schema_version": FRESH_CHAIN_EVIDENCE_SCHEMA,
            "source_commitment_sha256": self.source_commitment_sha256,
            "source_projection_commitment_sha256": (self.source_projection_commitment_sha256),
            "total_usage": totals,
        }

    def payload(self) -> dict[str, object]:
        return {
            **self.body(),
            "authentication_hmac_sha256": self.authentication_hmac_sha256,
            "evidence_sha256": self.evidence_sha256,
            "receipt": {
                "authentication": FRESH_CHAIN_AUTHENTICATION_KIND,
                "hmac_sha256": self.authentication_hmac_sha256,
                "publishable": False,
            },
        }


def build_fresh_chain_evidence(
    *,
    namespace_commitment_sha256: str,
    source_commitment_sha256: str,
    source_projection_commitment_sha256: str,
    calls: tuple[
        FreshChainCallResult,
        FreshChainCallResult,
        FreshChainCallResult,
        FreshChainCallResult,
        FreshChainCallResult,
    ],
    retrieval: FreshChainRetrievalHandoff,
    cleanup: FreshChainCleanupResult,
    ledger_plan_commitment_sha256: str,
    ledger_terminal_sha256: str,
    ledger_head_hmac_sha256: str,
    authentication_key: bytes,
) -> FreshChainCanaryEvidence:
    if (
        type(calls) is not tuple
        or len(calls) != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
        or any(type(item) is not FreshChainCallResult for item in calls)
        or tuple(item.stage for item in calls) != FRESH_CHAIN_STAGES
        or tuple(item.ordinal for item in calls) != tuple(range(5))
        or len({item.receipt_id for item in calls}) != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
        or len({item.physical_receipt_sha256 for item in calls})
        != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
        or type(retrieval) is not FreshChainRetrievalHandoff
        or type(cleanup) is not FreshChainCleanupResult
        or cleanup.namespace_commitment_sha256 != namespace_commitment_sha256
        or retrieval.namespace_commitment_sha256 != namespace_commitment_sha256
        or retrieval.source_commitment_sha256 != source_commitment_sha256
        or retrieval.source_projection_commitment_sha256 != source_projection_commitment_sha256
        or retrieval.extraction_intent_sha256 != calls[0].intent_sha256
        or retrieval.extraction_result_sha256 != calls[0].result_sha256
        or retrieval.extraction_receipt_sha256 != calls[0].physical_receipt_sha256
        or calls[3].stage != "mem0_answer"
        or cleanup.receipt_id in {item.receipt_id for item in calls}
        or cleanup.receipt_sha256 in {item.physical_receipt_sha256 for item in calls}
        or not _sha(ledger_plan_commitment_sha256)
        or not _sha(ledger_terminal_sha256)
        or not _sha(ledger_head_hmac_sha256)
        or type(authentication_key) is not bytes
        or len(authentication_key) < 32
    ):
        _fail("fresh_chain_evidence_bindings_invalid")
    arguments = {
        "namespace_commitment_sha256": namespace_commitment_sha256,
        "source_commitment_sha256": source_commitment_sha256,
        "source_projection_commitment_sha256": (source_projection_commitment_sha256),
        "retrieval_handoff_sha256": retrieval.handoff_sha256,
        "retrieval_authority_sha256": retrieval.retrieval_authority_sha256,
        "cleanup_commitment_sha256": cleanup.cleanup_commitment_sha256,
        "ledger_plan_commitment_sha256": ledger_plan_commitment_sha256,
        "ledger_terminal_sha256": ledger_terminal_sha256,
        "ledger_head_hmac_sha256": ledger_head_hmac_sha256,
        "ordered_physical_receipt_sha256": tuple(item.physical_receipt_sha256 for item in calls),
        "ordered_usage": tuple(item.usage.payload() for item in calls),
    }
    return _authenticate_arguments(arguments, authentication_key=authentication_key)


def build_fresh_chain_evidence_from_snapshot(
    snapshot: FreshChainSnapshot,
    *,
    authentication_key: bytes,
) -> FreshChainCanaryEvidence:
    """Build final evidence entirely from one authenticated terminal ledger view."""

    if type(snapshot) is not FreshChainSnapshot or type(snapshot.plan) is not FreshChainPlan:
        _fail("fresh_chain_evidence_snapshot_invalid")
    stages = snapshot.stages
    retrieval = snapshot.retrieval_handoff
    cleanup = snapshot.cleanup
    terminal = snapshot.terminal_outcome
    source_projection = snapshot.source_projection_commitment_sha256
    if (
        not snapshot.succeeded
        or not exact_success_snapshot_authority(snapshot)
        or type(stages) is not tuple
        or len(stages) != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
        or any(type(item) is not FreshChainStageRecord for item in stages)
        or tuple(item.stage for item in stages) != FRESH_CHAIN_STAGES
        or any(item.status != "succeeded" for item in stages)
        or snapshot.intent_count != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
        or snapshot.result_count != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
        or snapshot.physical_attempt_count != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
        or any(
            item.intent_sha256 is None
            or item.request_sha256 is None
            or item.input_authority_sha256 is None
            or item.result_sha256 is None
            or item.receipt_id is None
            or item.receipt_sha256 is None
            or type(item.token_usage) is not TokenUsage
            or not all(
                _sha(value)
                for value in (
                    item.intent_sha256,
                    item.request_sha256,
                    item.input_authority_sha256,
                    item.result_sha256,
                    item.receipt_sha256,
                )
            )
            or not _identifier(item.receipt_id)
            or not _commitments(item.intent_commitments)
            or not _commitments(item.result_commitments)
            for item in stages
        )
        or len({item.intent_sha256 for item in stages}) != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
        or len({item.receipt_id for item in stages}) != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
        or len({item.receipt_sha256 for item in stages}) != FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS
        or type(retrieval) is not RetrievalHandoff
        or type(cleanup) is not CleanupBinding
        or type(terminal) is not TerminalOutcome
        or not _sha(source_projection)
        or terminal.status != "succeeded"
        or not all(
            _sha(value)
            for value in (
                retrieval.extraction_result_sha256,
                retrieval.extraction_receipt_sha256,
                retrieval.namespace_commitment_sha256,
                retrieval.memory_authority_sha256,
                retrieval.retrieval_authority_sha256,
                cleanup.namespace_commitment_sha256,
                cleanup.cleanup_authority_sha256,
                cleanup.receipt_sha256,
                cleanup.outcome_sha256,
            )
        )
        or not _commitments(retrieval.commitments)
        or not _identifier(cleanup.receipt_id)
        or retrieval.namespace_commitment_sha256 != snapshot.plan.namespace_commitment_sha256
        or retrieval.extraction_result_sha256 != stages[0].result_sha256
        or retrieval.extraction_receipt_sha256 != stages[0].receipt_sha256
        or stages[0].input_authority_sha256 != source_projection
        or stages[3].input_authority_sha256 != retrieval.retrieval_authority_sha256
        or stages[2].input_authority_sha256 != stages[1].result_sha256
        or stages[4].input_authority_sha256 != stages[3].result_sha256
        or cleanup.namespace_commitment_sha256 != snapshot.plan.namespace_commitment_sha256
        or cleanup.deleted is not True
        or cleanup.operation_count != 1
        or cleanup.residual_count != 0
        or cleanup.receipt_id in {item.receipt_id for item in stages}
        or cleanup.receipt_sha256 in {item.receipt_sha256 for item in stages}
        or not _sha(snapshot.event_head_hmac)
        or not _sha(snapshot.plan.namespace_commitment_sha256)
        or not _sha(snapshot.plan.source_commitment_sha256)
        or hmac.compare_digest(
            snapshot.plan.namespace_commitment_sha256,
            snapshot.plan.source_commitment_sha256,
        )
        or type(snapshot.event_count) is not int
        or snapshot.event_count < FRESH_CHAIN_EXPECTED_PHYSICAL_ATTEMPTS * 2 + 3
        or not _sha(snapshot.plan.commitment_sha256)
        or not _sha(terminal.outcome_sha256)
        or type(authentication_key) is not bytes
        or len(authentication_key) < 32
    ):
        _fail("fresh_chain_evidence_snapshot_invalid")
    arguments = {
        "namespace_commitment_sha256": snapshot.plan.namespace_commitment_sha256,
        "source_commitment_sha256": snapshot.plan.source_commitment_sha256,
        "source_projection_commitment_sha256": source_projection,
        "retrieval_handoff_sha256": ledger_canonical_sha256(retrieval.material()),
        "retrieval_authority_sha256": retrieval.retrieval_authority_sha256,
        "cleanup_commitment_sha256": ledger_canonical_sha256(cleanup.material()),
        "ledger_plan_commitment_sha256": snapshot.plan.commitment_sha256,
        "ledger_terminal_sha256": terminal.outcome_sha256,
        "ledger_head_hmac_sha256": snapshot.event_head_hmac,
        "ordered_physical_receipt_sha256": tuple(item.receipt_sha256 for item in stages),
        "ordered_usage": tuple(
            {
                "prompt_tokens": item.token_usage.input_tokens,
                "completion_tokens": item.token_usage.output_tokens,
                "total_tokens": item.token_usage.total_tokens,
            }
            for item in stages
        ),
    }
    return _authenticate_arguments(arguments, authentication_key=authentication_key)


def _authenticate_arguments(
    arguments: dict[str, object],
    *,
    authentication_key: bytes,
) -> FreshChainCanaryEvidence:
    unsigned = FreshChainCanaryEvidence(
        **arguments,  # type: ignore[arg-type]
        authentication_hmac_sha256="0" * 64,
    )
    authentication = hmac.new(
        authentication_key,
        _HMAC_DOMAIN + _canonical(unsigned.body()),
        hashlib.sha256,
    ).hexdigest()
    return FreshChainCanaryEvidence(
        **arguments,  # type: ignore[arg-type]
        authentication_hmac_sha256=authentication,
    )


def authenticate_fresh_chain_evidence(
    evidence: FreshChainCanaryEvidence,
    *,
    authentication_key: bytes,
) -> None:
    if (
        type(evidence) is not FreshChainCanaryEvidence
        or type(authentication_key) is not bytes
        or len(authentication_key) < 32
    ):
        _fail("fresh_chain_evidence_authentication_invalid")
    evidence.__post_init__()
    expected = hmac.new(
        authentication_key,
        _HMAC_DOMAIN + _canonical(evidence.body()),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, evidence.authentication_hmac_sha256):
        _fail("fresh_chain_evidence_authentication_invalid")


def write_fresh_chain_evidence(
    path: Path,
    evidence: FreshChainCanaryEvidence,
    *,
    authentication_key: bytes,
) -> FreshChainCanaryEvidence:
    if not _safe_path_shape(path):
        _fail("fresh_chain_evidence_write_failed")
    authenticate_fresh_chain_evidence(evidence, authentication_key=authentication_key)
    encoded = _canonical(evidence.payload())
    if not 1 <= len(encoded) <= _MAX_BYTES:
        _fail("fresh_chain_evidence_invalid")
    if path.exists() or path.is_symlink():
        observed = read_fresh_chain_evidence(path, authentication_key=authentication_key)
        if observed != evidence:
            _fail("fresh_chain_evidence_replay_conflict")
        return observed
    try:
        verify_private_directory(path.parent, "fresh_chain_evidence_parent")
        write_private_json_once(
            path,
            evidence.payload(),
            maximum_bytes=_MAX_BYTES,
        )
    except BridgeProcessError:
        # A concurrent writer is acceptable only when its authenticated payload
        # is byte-for-byte the same replay. Unsafe or divergent files still fail.
        try:
            observed = read_fresh_chain_evidence(
                path,
                authentication_key=authentication_key,
            )
        except FreshChainCanaryError:
            _fail("fresh_chain_evidence_write_failed")
        if observed != evidence:
            _fail("fresh_chain_evidence_replay_conflict")
        return observed
    return read_fresh_chain_evidence(path, authentication_key=authentication_key)


def read_fresh_chain_evidence(
    path: Path,
    *,
    authentication_key: bytes,
) -> FreshChainCanaryEvidence:
    try:
        if not _safe_path_shape(path):
            raise ValueError
        verify_private_directory(path.parent, "fresh_chain_evidence_parent")
        raw = read_private_file(
            path,
            "fresh_chain_evidence",
            maximum_bytes=_MAX_BYTES,
        )
        value = strict_json_loads(raw, maximum_bytes=_MAX_BYTES)
        if raw != _canonical(value) or type(value) is not dict:
            raise ValueError
        body_keys = set(
            FreshChainCanaryEvidence(
                namespace_commitment_sha256="0" * 64,
                source_commitment_sha256="a" * 64,
                source_projection_commitment_sha256="b" * 64,
                retrieval_handoff_sha256="0" * 64,
                retrieval_authority_sha256="0" * 64,
                cleanup_commitment_sha256="0" * 64,
                ledger_plan_commitment_sha256="0" * 64,
                ledger_terminal_sha256="0" * 64,
                ledger_head_hmac_sha256="0" * 64,
                ordered_physical_receipt_sha256=tuple(str(index) * 64 for index in range(1, 6)),
                ordered_usage=tuple(
                    {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                    for _ in range(5)
                ),
                authentication_hmac_sha256="0" * 64,
            ).body()
        )
        if set(value) != body_keys | {
            "authentication_hmac_sha256",
            "evidence_sha256",
            "receipt",
        }:
            raise ValueError
        evidence = FreshChainCanaryEvidence(
            namespace_commitment_sha256=value["namespace_commitment_sha256"],
            source_commitment_sha256=value["source_commitment_sha256"],
            source_projection_commitment_sha256=value["source_projection_commitment_sha256"],
            retrieval_handoff_sha256=value["retrieval_handoff_sha256"],
            retrieval_authority_sha256=value["retrieval_authority_sha256"],
            cleanup_commitment_sha256=value["cleanup_commitment_sha256"],
            ledger_plan_commitment_sha256=value["ledger_plan_commitment_sha256"],
            ledger_terminal_sha256=value["ledger_terminal_sha256"],
            ledger_head_hmac_sha256=value["ledger_head_hmac_sha256"],
            ordered_physical_receipt_sha256=tuple(value["ordered_physical_receipt_sha256"]),
            ordered_usage=tuple(dict(item) for item in value["ordered_usage"]),
            authentication_hmac_sha256=value["authentication_hmac_sha256"],
        )
        if (
            value["evidence_sha256"] != evidence.evidence_sha256
            or value["receipt"]
            != {
                "authentication": FRESH_CHAIN_AUTHENTICATION_KIND,
                "hmac_sha256": evidence.authentication_hmac_sha256,
                "publishable": False,
            }
            or any(value[key] != item for key, item in evidence.body().items())
        ):
            raise ValueError
        authenticate_fresh_chain_evidence(evidence, authentication_key=authentication_key)
        return evidence
    except (
        BridgeJsonError,
        BridgeProcessError,
        FreshChainCanaryError,
        OSError,
        TypeError,
        ValueError,
        KeyError,
    ):
        _fail("fresh_chain_evidence_read_invalid")


def _usage(value: object) -> bool:
    return bool(
        type(value) is dict
        and set(value) == {"prompt_tokens", "completion_tokens", "total_tokens"}
        and all(type(value[key]) is int and value[key] >= 0 for key in value)
        and value["total_tokens"] == value["prompt_tokens"] + value["completion_tokens"]
    )


def _commitments(value: object) -> bool:
    return bool(
        type(value) is tuple
        and all(
            type(item) is tuple and len(item) == 2 and _identifier(item[0]) and _sha(item[1])
            for item in value
        )
        and tuple(sorted(value)) == value
        and len({item[0] for item in value}) == len(value)
    )


def _identifier(value: object) -> bool:
    return bool(
        type(value) is str
        and 0 < len(value) <= 512
        and value == value.strip()
        and all(character.isalnum() or character in "._:-" for character in value)
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _safe_path_shape(path: object) -> bool:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        or path.name in {"", ".", ".."}
    ):
        return False
    try:
        return path.parent.resolve(strict=True) == path.parent
    except (OSError, RuntimeError):
        return False


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = (
    "FRESH_CHAIN_EVIDENCE_SCHEMA",
    "FreshChainCanaryEvidence",
    "authenticate_fresh_chain_evidence",
    "build_fresh_chain_evidence",
    "build_fresh_chain_evidence_from_snapshot",
    "read_fresh_chain_evidence",
    "write_fresh_chain_evidence",
)

"""Strict policy for optional auto-apply-safe capture consolidation."""

from __future__ import annotations

from dataclasses import dataclass

from memo_stack_core.domain.capture import (
    CanonicalCapture,
    CaptureActorRole,
    CaptureSensitivity,
    SourceAuthority,
)
from memo_stack_core.domain.entities import Confidence, DataClassification, TrustLevel
from memo_stack_core.ports.auto_memory import CandidateOperation, MemoryCandidate


@dataclass(frozen=True)
class AutoApplyDecision:
    allowed: bool
    reason: str


class AutoApplySafePolicy:
    """Allow direct writes only for strict, explicit, non-conflicting new facts."""

    def decide(
        self,
        *,
        enabled: bool,
        capture: CanonicalCapture,
        candidate: MemoryCandidate,
        ttl_policy: str,
        has_active_duplicate: bool,
        has_pending_duplicate: bool,
    ) -> AutoApplyDecision:
        if not enabled:
            return AutoApplyDecision(False, "auto_apply_disabled")
        if capture.actor_role != CaptureActorRole.USER:
            return AutoApplyDecision(False, "auto_apply_requires_user_actor")
        if capture.source_authority != SourceAuthority.EXPLICIT_USER_COMMAND:
            return AutoApplyDecision(False, "auto_apply_requires_explicit_user_command")
        if capture.trust_level != TrustLevel.HIGH:
            return AutoApplyDecision(False, "auto_apply_requires_high_trust_capture")
        if capture.sensitivity not in {CaptureSensitivity.LOW, CaptureSensitivity.MEDIUM}:
            return AutoApplyDecision(False, "auto_apply_blocks_sensitive_capture")
        if capture.data_classification not in {
            DataClassification.PUBLIC,
            DataClassification.INTERNAL,
        }:
            return AutoApplyDecision(False, "auto_apply_blocks_classification")
        if capture.metadata.get("admission_reason") != "accepted":
            return AutoApplyDecision(False, "auto_apply_requires_unredacted_capture")
        if candidate.operation_hint != CandidateOperation.ADD:
            return AutoApplyDecision(False, "auto_apply_add_only")
        if candidate.target_fact_id or candidate.target_fact_version is not None:
            return AutoApplyDecision(False, "auto_apply_target_not_allowed")
        if candidate.confidence != Confidence.HIGH:
            return AutoApplyDecision(False, "auto_apply_requires_high_confidence")
        if not candidate.source_refs:
            return AutoApplyDecision(False, "auto_apply_requires_source_refs")
        if ttl_policy != "durable":
            return AutoApplyDecision(False, "auto_apply_requires_durable_ttl")
        if "[redacted-secret]" in candidate.text:
            return AutoApplyDecision(False, "auto_apply_blocks_redacted_candidate")
        if has_active_duplicate:
            return AutoApplyDecision(False, "auto_apply_active_duplicate")
        if has_pending_duplicate:
            return AutoApplyDecision(False, "auto_apply_pending_duplicate")
        return AutoApplyDecision(True, "auto_apply_safe_explicit_user_memory")

"""Deterministic local policy for MCP memory operations."""

from __future__ import annotations

from memo_stack_mcp.domain.models import (
    contains_sensitive_value,
    has_control_characters,
    has_zero_width_characters,
)
from memo_stack_mcp.domain.policy import (
    MemoryMcpIngestMode,
    MemoryMcpWriteMode,
    MemoryPolicyDecision,
    MemoryPolicyInput,
    MemoryPolicyOperation,
    MemoryPolicyResult,
)

_LOW_TRUST_DIRECT_SOURCES = {
    "ai_response",
    "assistant_answer",
    "assistant_summary",
    "document",
    "tool_result",
    "retrieved_memory",
}


class MemoryPolicyService:
    """Local policy only. Canonical lifecycle remains in Memo Stack Server."""

    def decide(self, request: MemoryPolicyInput) -> MemoryPolicyResult:
        if contains_sensitive_value(request.text):
            return MemoryPolicyResult.reject(
                "memo_stack_mcp.policy.secret_detected",
                "Candidate contains a credential-like value",
            )
        if has_control_characters(request.text):
            return MemoryPolicyResult.reject(
                "memo_stack_mcp.policy.control_characters",
                "Candidate contains unsafe control characters",
            )
        if has_zero_width_characters(request.text):
            return MemoryPolicyResult.reject(
                "memo_stack_mcp.policy.invisible_characters",
                "Candidate contains invisible formatting characters",
            )
        if request.operation == MemoryPolicyOperation.FORGET:
            return self._decide_forget(request)
        if request.operation == MemoryPolicyOperation.INGEST_DOCUMENT:
            return self._decide_ingest(request)
        if request.operation == MemoryPolicyOperation.SUGGEST:
            return self._decide_suggestion(request)
        if request.operation == MemoryPolicyOperation.REVIEW:
            return self._decide_review(request)
        if request.operation == MemoryPolicyOperation.REMEMBER:
            return self._decide_remember(request)
        if request.operation == MemoryPolicyOperation.UPDATE:
            return self._decide_update(request)
        return MemoryPolicyResult.reject(
            "memo_stack_mcp.policy.unsupported_operation",
            "Unsupported memory operation",
        )

    def _decide_remember(self, request: MemoryPolicyInput) -> MemoryPolicyResult:
        write_check = self._write_check(request)
        if write_check.decision == MemoryPolicyDecision.REJECT:
            return write_check
        if request.write_mode == MemoryMcpWriteMode.SUGGEST:
            return MemoryPolicyResult.allow_suggestion(
                "memo_stack_mcp.policy.write_mode_suggest",
                "Write mode requires creating a suggestion",
            )
        if request.write_mode == MemoryMcpWriteMode.DIRECT_EXPLICIT and not request.user_confirmed:
            return MemoryPolicyResult.allow_suggestion(
                "memo_stack_mcp.policy.explicit_confirmation_required",
                "Direct write requires explicit user confirmation",
            )
        if request.source_type in _LOW_TRUST_DIRECT_SOURCES and not request.user_confirmed:
            return MemoryPolicyResult.allow_suggestion(
                "memo_stack_mcp.policy.source_requires_review",
                "Source type requires review before direct persistence",
            )
        return MemoryPolicyResult.allow_direct()

    def _decide_update(self, request: MemoryPolicyInput) -> MemoryPolicyResult:
        write_check = self._write_check(request)
        if write_check.decision == MemoryPolicyDecision.REJECT:
            return write_check
        if request.write_mode == MemoryMcpWriteMode.SUGGEST:
            return MemoryPolicyResult.reject(
                "memo_stack_mcp.policy.update_requires_direct_mode",
                "Direct update is disabled in suggest mode",
            )
        if request.write_mode == MemoryMcpWriteMode.DIRECT_EXPLICIT and not request.user_confirmed:
            return MemoryPolicyResult.reject(
                "memo_stack_mcp.policy.explicit_confirmation_required",
                "Direct update requires explicit user confirmation",
            )
        return MemoryPolicyResult.allow_direct()

    def _decide_suggestion(self, request: MemoryPolicyInput) -> MemoryPolicyResult:
        write_check = self._write_check(request)
        if write_check.decision == MemoryPolicyDecision.REJECT:
            return write_check
        return MemoryPolicyResult.allow_suggestion(
            "memo_stack_mcp.policy.suggestion_allowed",
            "Suggestion write is allowed",
        )

    def _decide_review(self, request: MemoryPolicyInput) -> MemoryPolicyResult:
        write_check = self._write_check(request)
        if write_check.decision == MemoryPolicyDecision.REJECT:
            return write_check
        return MemoryPolicyResult.allow_direct(
            "memo_stack_mcp.policy.review_allowed",
            "Suggestion review is allowed",
        )

    def _decide_forget(self, request: MemoryPolicyInput) -> MemoryPolicyResult:
        if not request.deletes_enabled:
            return MemoryPolicyResult.reject(
                "memo_stack_mcp.policy.delete_mode_off",
                "Memo Stack MCP deletes are disabled by local policy",
            )
        return MemoryPolicyResult.allow_direct(
            "memo_stack_mcp.policy.delete_allowed",
            "Delete is allowed by local MCP policy",
        )

    def _decide_ingest(self, request: MemoryPolicyInput) -> MemoryPolicyResult:
        write_check = self._write_check(request)
        if write_check.decision == MemoryPolicyDecision.REJECT:
            return write_check
        if request.ingest_mode == MemoryMcpIngestMode.OFF:
            return MemoryPolicyResult.reject(
                "memo_stack_mcp.policy.ingest_mode_off",
                "Document ingest is disabled by local policy",
            )
        if (
            request.ingest_mode == MemoryMcpIngestMode.SMALL_DOCS
            and request.text_length > request.small_doc_max_chars
        ):
            return MemoryPolicyResult.reject(
                "memo_stack_mcp.policy.ingest_too_large",
                "Document exceeds the configured small document limit",
            )
        return MemoryPolicyResult.allow_direct(
            "memo_stack_mcp.policy.ingest_allowed",
            "Document ingest is allowed",
        )

    @staticmethod
    def _write_check(request: MemoryPolicyInput) -> MemoryPolicyResult:
        if not request.writes_enabled:
            return MemoryPolicyResult.reject(
                "memo_stack_mcp.policy.write_mode_off",
                "Memo Stack MCP writes are disabled by local policy",
            )
        return MemoryPolicyResult.allow_direct()

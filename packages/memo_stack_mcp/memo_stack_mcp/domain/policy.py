"""Pure policy DTOs for MCP memory safety decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MemoryMcpWriteMode(StrEnum):
    OFF = "off"
    SUGGEST = "suggest"
    DIRECT_EXPLICIT = "direct_explicit"
    DIRECT = "direct"


class MemoryMcpDeleteMode(StrEnum):
    OFF = "off"
    EXPLICIT = "explicit"


class MemoryMcpIngestMode(StrEnum):
    OFF = "off"
    SMALL_DOCS = "small_docs"
    ALLOWED = "allowed"


class MemoryPolicyOperation(StrEnum):
    REMEMBER = "remember"
    SUGGEST = "suggest"
    UPDATE = "update"
    FORGET = "forget"
    REVIEW = "review"
    INGEST_DOCUMENT = "ingest_document"


class MemoryPolicyDecision(StrEnum):
    ALLOW_DIRECT = "allow_direct"
    ALLOW_SUGGESTION = "allow_suggestion"
    REJECT = "reject"


@dataclass(frozen=True)
class MemoryPolicyInput:
    operation: MemoryPolicyOperation
    text: str
    source_type: str | None
    write_mode: MemoryMcpWriteMode
    delete_mode: MemoryMcpDeleteMode
    ingest_mode: MemoryMcpIngestMode
    writes_enabled: bool
    deletes_enabled: bool
    user_confirmed: bool = False
    text_length: int = 0
    small_doc_max_chars: int = 500_000


@dataclass(frozen=True)
class MemoryPolicyResult:
    decision: MemoryPolicyDecision
    allowed: bool
    direct_allowed: bool
    code: str
    safe_message: str
    warnings: tuple[str, ...] = ()

    @classmethod
    def allow_direct(
        cls,
        code: str = "memo_stack_mcp.policy.allowed",
        safe_message: str = "Allowed by local MCP policy",
        warnings: tuple[str, ...] = (),
    ) -> MemoryPolicyResult:
        return cls(
            decision=MemoryPolicyDecision.ALLOW_DIRECT,
            allowed=True,
            direct_allowed=True,
            code=code,
            safe_message=safe_message,
            warnings=warnings,
        )

    @classmethod
    def allow_suggestion(
        cls,
        code: str,
        safe_message: str,
        warnings: tuple[str, ...] = (),
    ) -> MemoryPolicyResult:
        return cls(
            decision=MemoryPolicyDecision.ALLOW_SUGGESTION,
            allowed=True,
            direct_allowed=False,
            code=code,
            safe_message=safe_message,
            warnings=warnings,
        )

    @classmethod
    def reject(
        cls,
        code: str,
        safe_message: str,
        warnings: tuple[str, ...] = (),
    ) -> MemoryPolicyResult:
        return cls(
            decision=MemoryPolicyDecision.REJECT,
            allowed=False,
            direct_allowed=False,
            code=code,
            safe_message=safe_message,
            warnings=warnings,
        )

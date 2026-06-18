"""Shared eval data structures."""

from __future__ import annotations

from dataclasses import dataclass

DiagnosticRequirement = tuple[str, object] | tuple[str, str, object]


@dataclass(frozen=True)
class SeedResult:
    ok: bool
    checks: dict[str, bool]
    space_id: str
    alpha_memory_scope_id: str
    beta_memory_scope_id: str


@dataclass(frozen=True)
class QualitySeedResult:
    ok: bool
    checks: dict[str, bool]
    space_id: str
    alpha_memory_scope_id: str
    beta_memory_scope_id: str
    current_thread_id: str
    other_thread_id: str
    hybrid_chunk_id: str | None = None


@dataclass(frozen=True)
class LongMemorySeedResult:
    ok: bool
    checks: dict[str, bool]
    space_id: str
    alpha_memory_scope_id: str
    beta_memory_scope_id: str
    kickoff_thread_id: str
    current_thread_id: str
    other_thread_id: str


@dataclass(frozen=True)
class GraphNativeSeedResult:
    ok: bool
    checks: dict[str, bool]
    space_id: str
    alpha_memory_scope_id: str
    beta_memory_scope_id: str
    current_thread_id: str
    fact_ids: dict[str, str]


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str
    space_id: str
    memory_scope_ids: tuple[str, ...]
    query: str
    thread_id: str | None = None
    must_include: tuple[str, ...] = ()
    must_not_include: tuple[str, ...] = ()
    token_budget: int = 512
    max_facts: int = 20
    max_chunks: int = 30
    consistency_mode: str = "best_effort"
    include_stale: bool = False
    require_evidence_guard: bool = True
    required_diagnostics: tuple[DiagnosticRequirement, ...] = ()


@dataclass(frozen=True)
class EvalCaseResult:
    case: EvalCase
    status_code: int
    recall_ok: bool
    precision_ok: bool
    evidence_guard: bool
    token_overflow: bool
    item_ids: tuple[str, ...]
    diagnostics: dict[str, object]
    failures: tuple[dict[str, object], ...]

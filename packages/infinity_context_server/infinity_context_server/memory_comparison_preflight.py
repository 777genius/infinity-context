"""Safe preflight checks for memory-comparison benchmark runs."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

MEMORY_COMPARISON_PREFLIGHT_SUITE = "memory-comparison-preflight"
MEMORY_COMPARISON_PREFLIGHT_SCHEMA_VERSION = "memory-comparison-preflight.v1"
_MAX_DIAGNOSTIC_TEXT = 256
_MAX_DIAGNOSTIC_ITEMS = 20
_FAST_CASE_SETS = frozenset(
    {
        "locomo-fast",
        "locomo-fast-multi-hop",
        "locomo-fast-temporal",
        "locomo-fast-open-domain",
        "locomo-fast-single-hop",
    }
)
_FAST_CASES_PER_GROUP = 10
_FAST_CASE_SET_GROUPS = {
    "locomo-fast": (
        "multi-hop",
        "temporal",
        "open-domain",
        "single-hop",
    ),
    "locomo-fast-multi-hop": ("multi-hop",),
    "locomo-fast-temporal": ("temporal",),
    "locomo-fast-open-domain": ("open-domain",),
    "locomo-fast-single-hop": ("single-hop",),
}
_REQUIRED_FAST_CUTOFFS = frozenset({10, 20, 50, 200})
_SAFE_REPORTING_CONTRACTS = (
    ("quality_diagnostics", "quality_diagnostics.v2"),
    ("evidence_bundle_gap_report", "evidence_bundle_gap_report.v1"),
    ("answer_context_provenance", "answer_context_provenance.v1"),
    ("answer_context_support_gaps", "answer_context_support_gaps.v1"),
    ("temporal_grounding_table", "temporal_grounding.v1"),
)
_LOCOMO_DIA_ID_RE = re.compile(
    r"\bD(?P<dialogue>\d+)[:\-](?P<turn>\d+)\b",
    re.IGNORECASE,
)
_LOCOMO_DIALOGUE_ID_RE = re.compile(r"^D(?P<dialogue>\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class MemoryComparisonPreflightConfig:
    """Input contract for memory-comparison readiness checks."""

    dataset_path: Path
    memo_api_url: str
    mem0_url: str
    case_set: str
    locomo_ingest_mode: str
    report_mode: str
    top_k: int
    top_k_cutoffs: Sequence[int]
    allow_live: bool
    allow_paid_llm: bool
    answerer_provider: str
    judge_provider: str
    answerer_model: str | None
    judge_model: str | None
    openai_api_key_env: str
    mem0_api_key_env: str
    auth_token_configured: bool
    probe_services: bool = False
    probe_timeout_seconds: float = 1.5
    env: Mapping[str, str] = field(default_factory=lambda: os.environ)


@dataclass(frozen=True)
class MemoryComparisonPreflightCheck:
    """One sanitized preflight check."""

    name: str
    passed: bool
    severity: str
    reason: str | None = None
    reason_code: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def to_payload(self) -> dict[str, object]:
        return {
            "name": _compact_diagnostic_text(self.name),
            "passed": self.passed,
            "severity": _compact_diagnostic_text(self.severity),
            "reason": (
                _compact_diagnostic_text(self.reason)
                if self.reason is not None
                else None
            ),
            "reason_code": (
                _compact_diagnostic_text(self.reason_code)
                if self.reason_code is not None
                else None
            ),
            "details": _json_safe_mapping(self.details),
        }


def run_memory_comparison_preflight(
    config: MemoryComparisonPreflightConfig,
) -> dict[str, object]:
    """Return a sanitized readiness report without starting benchmark state."""

    normalized_cutoffs = _normalized_cutoffs(config.top_k_cutoffs)
    checks = [
        _dataset_check(config.dataset_path),
        _url_check("memo_api_url_valid", config.memo_api_url),
        _url_check("mem0_url_valid", config.mem0_url),
        _required_check(
            "allow_live_gate",
            passed=config.allow_live,
            reason="pass --allow-live before live benchmark execution",
        ),
        _required_check(
            "memo_auth_token_configured",
            passed=config.auth_token_configured,
            reason="configure MEMORY_EVAL_AUTH_TOKEN or MEMORY_SERVICE_TOKEN",
        ),
        *_llm_checks(config),
        _warning_check(
            "mem0_api_key_configured",
            passed=_env_is_set(config.env, config.mem0_api_key_env),
            reason=(
                f"{config.mem0_api_key_env} is not set; this is allowed only when "
                "the target mem0 OSS wrapper accepts unauthenticated requests"
            ),
            details={
                "env_var": config.mem0_api_key_env,
                "set": _env_is_set(config.env, config.mem0_api_key_env),
            },
        ),
        *_fast_readiness_checks(config),
        *_locomo_fast_dataset_checks(config),
    ]
    if config.probe_services:
        checks.extend(_service_probe_checks(config))
    else:
        checks.append(
            MemoryComparisonPreflightCheck(
                name="service_probe_skipped",
                passed=False,
                severity="info",
                reason="pass --preflight-probe-services to verify HTTP reachability",
                reason_code="service_probe_skipped",
            )
        )

    failed_required = tuple(
        check for check in checks if check.severity == "required" and not check.passed
    )
    warnings = tuple(
        check for check in checks if check.severity == "warning" and not check.passed
    )
    fast_blockers = tuple(
        check for check in checks if check.severity == "fast-readiness" and not check.passed
    )
    service_probe_failures = tuple(
        check for check in checks if check.severity == "service-probe" and not check.passed
    )
    blocking_failures = (*failed_required, *service_probe_failures)
    ok = not blocking_failures
    safe_to_run_paid_llm = _safe_to_run_paid_llm(config, checks)
    safe_to_run_live = ok and safe_to_run_paid_llm and not service_probe_failures
    ready_for_locomo_fast = safe_to_run_live and not fast_blockers
    status = "failed" if not ok else "degraded" if warnings or fast_blockers else "ok"
    return {
        "suite": MEMORY_COMPARISON_PREFLIGHT_SUITE,
        "schema_version": MEMORY_COMPARISON_PREFLIGHT_SCHEMA_VERSION,
        "ok": ok,
        "status": status,
        "safe_to_run_live": safe_to_run_live,
        "safe_to_run_paid_llm": safe_to_run_paid_llm,
        "ready_for_locomo_fast": ready_for_locomo_fast,
        "failed_checks": [check.name for check in blocking_failures],
        "warnings": [check.name for check in warnings],
        "fast_readiness_blockers": [check.name for check in fast_blockers],
        "checks": [check.to_payload() for check in checks],
        "diagnostics": {
            "dataset_path_label": config.dataset_path.name,
            "case_set": config.case_set,
            "locomo_ingest_mode": config.locomo_ingest_mode,
            "report_mode": config.report_mode,
            "top_k": config.top_k,
            "top_k_cutoffs": list(normalized_cutoffs[:_MAX_DIAGNOSTIC_ITEMS]),
            "top_k_cutoff_count": len(normalized_cutoffs),
            "answerer_provider": config.answerer_provider,
            "judge_provider": config.judge_provider,
            "uses_openai": _uses_openai(config),
            "probe_services": config.probe_services,
            "safe_reporting_contracts": _safe_reporting_contracts(config.report_mode),
            "secrets": _secret_diagnostics(config),
        },
    }


def _dataset_check(dataset_path: Path) -> MemoryComparisonPreflightCheck:
    if not dataset_path.exists():
        return _required_check(
            "dataset_readable",
            passed=False,
            reason="dataset file does not exist",
            reason_code="dataset_missing",
            details={"dataset_path_label": dataset_path.name},
        )
    if not dataset_path.is_file():
        return _required_check(
            "dataset_readable",
            passed=False,
            reason="dataset path is not a file",
            reason_code="dataset_not_file",
            details={"dataset_path_label": dataset_path.name},
        )
    try:
        size_bytes = dataset_path.stat().st_size
        payload = _read_dataset_payload(dataset_path)
    except Exception as exc:
        return _required_check(
            "dataset_readable",
            passed=False,
            reason="dataset file is not readable JSON",
            reason_code="dataset_unreadable_json",
            details={
                "dataset_path_label": dataset_path.name,
                "error_type": type(exc).__name__,
            },
        )
    top_level_count = _top_level_count(payload)
    return _required_check(
        "dataset_readable",
        passed=size_bytes > 0 and top_level_count > 0,
        reason="dataset must contain at least one top-level case/sample",
        reason_code="dataset_empty",
        details={
            "dataset_path_label": dataset_path.name,
            "size_bytes": size_bytes,
            "top_level_type": type(payload).__name__,
            "top_level_count": top_level_count,
        },
    )


def _url_check(name: str, value: str) -> MemoryComparisonPreflightCheck:
    parsed = urlparse(str(value or ""))
    valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    return _required_check(
        name,
        passed=valid,
        reason="URL must use http(s) and include a host",
        reason_code="invalid_url",
        details={
            "scheme": parsed.scheme or None,
            "host_configured": bool(parsed.netloc),
        },
    )


def _llm_checks(
    config: MemoryComparisonPreflightConfig,
) -> tuple[MemoryComparisonPreflightCheck, ...]:
    if not _uses_openai(config):
        return (
            _required_check(
                "paid_llm_gate",
                passed=True,
                reason=None,
                reason_code=None,
                details={"uses_openai": False},
            ),
        )
    checks: list[MemoryComparisonPreflightCheck] = [
        _required_check(
            "paid_llm_gate",
            passed=config.allow_paid_llm,
            reason="pass --allow-paid-llm before OpenAI answerer or judge calls",
            reason_code="paid_llm_not_allowed",
            details={"uses_openai": True},
        ),
        _required_check(
            "openai_api_key_configured",
            passed=_env_is_set(config.env, config.openai_api_key_env)
            or _env_is_set(config.env, "OPENAI_API_KEY"),
            reason=f"set {config.openai_api_key_env} or OPENAI_API_KEY",
            reason_code="openai_api_key_missing",
            details={
                "configured_env_var": config.openai_api_key_env,
                "configured_env_var_set": _env_is_set(
                    config.env,
                    config.openai_api_key_env,
                ),
                "fallback_env_var": "OPENAI_API_KEY",
                "fallback_env_var_set": _env_is_set(config.env, "OPENAI_API_KEY"),
            },
        ),
    ]
    if config.answerer_provider == "openai":
        checks.append(
            _required_check(
                "openai_answerer_model_configured",
                passed=bool(
                    (config.answerer_model or "").strip()
                    or _env_is_set(config.env, "MEMORY_COMPARISON_ANSWERER_MODEL")
                ),
                reason=(
                    "pass --answerer-model or set "
                    "MEMORY_COMPARISON_ANSWERER_MODEL"
                ),
                reason_code="openai_answerer_model_missing",
            )
        )
    if config.judge_provider == "openai":
        checks.append(
            _required_check(
                "openai_judge_model_configured",
                passed=bool(
                    (config.judge_model or "").strip()
                    or _env_is_set(config.env, "MEMORY_COMPARISON_JUDGE_MODEL")
                ),
                reason="pass --judge-model or set MEMORY_COMPARISON_JUDGE_MODEL",
                reason_code="openai_judge_model_missing",
            )
        )
    return tuple(checks)


def _fast_readiness_checks(
    config: MemoryComparisonPreflightConfig,
) -> tuple[MemoryComparisonPreflightCheck, ...]:
    cutoffs = frozenset(_normalized_cutoffs(config.top_k_cutoffs))
    return (
        _fast_check(
            "locomo_fast_case_set",
            passed=config.case_set in _FAST_CASE_SETS,
            reason="use --case-set locomo-fast or another locomo-fast subset",
            details={"case_set": config.case_set},
        ),
        _fast_check(
            "official_turn_ingest_mode",
            passed=config.locomo_ingest_mode == "official-turns",
            reason="use --locomo-ingest-mode official-turns for mem0-style parity",
            details={"locomo_ingest_mode": config.locomo_ingest_mode},
        ),
        _fast_check(
            "top_k_fast_gate",
            passed=config.top_k >= 200,
            reason="use --top-k 200 or higher before evaluating evidence-ref rank gates",
            details={"top_k": config.top_k},
        ),
        _fast_check(
            "top_k_cutoffs_fast_gate",
            passed=_REQUIRED_FAST_CUTOFFS.issubset(cutoffs),
            reason="include --top-k-cutoff 10/20/50/200 for comparable fast gates",
            details={
                "configured": sorted(cutoffs),
                "required": sorted(_REQUIRED_FAST_CUTOFFS),
            },
        ),
        _fast_check(
            "compact_report_mode",
            passed=config.report_mode == "compact",
            reason="use --report-mode compact for fast iteration unless debugging cases",
            details={"report_mode": config.report_mode},
        ),
    )


def _locomo_fast_dataset_checks(
    config: MemoryComparisonPreflightConfig,
) -> tuple[MemoryComparisonPreflightCheck, ...]:
    groups = _FAST_CASE_SET_GROUPS.get(config.case_set)
    if groups is None:
        return ()
    if config.locomo_ingest_mode != "official-turns":
        return ()

    try:
        payload = _read_dataset_payload(config.dataset_path)
        (
            official_case_count,
            selected_by_group,
            selected_with_turn_evidence_by_group,
        ) = _locomo_fast_dataset_case_counts(
            payload,
            groups=groups,
        )
    except Exception as exc:
        return (
            _fast_check(
                "locomo_fast_dataset_case_coverage",
                passed=False,
                reason="dataset must load as official LoCoMo cases for fast readiness",
                reason_code="locomo_fast_dataset_unloadable",
                details={
                    "dataset_path_label": config.dataset_path.name,
                    "error_type": type(exc).__name__,
                },
            ),
        )

    missing_groups = [
        group
        for group, count in selected_by_group.items()
        if count < _FAST_CASES_PER_GROUP
    ]
    missing_turn_evidence_groups = [
        group
        for group, count in selected_with_turn_evidence_by_group.items()
        if count < _FAST_CASES_PER_GROUP
    ]
    return (
        _fast_check(
            "locomo_fast_dataset_case_coverage",
            passed=not missing_groups and not missing_turn_evidence_groups,
            reason=(
                "dataset must provide at least 10 scored official-turn LoCoMo "
                "cases for each requested fast group, with evidence refs backed "
                "by conversation turns"
            ),
            reason_code=(
                "locomo_fast_dataset_insufficient_cases"
                if missing_groups
                else "locomo_fast_dataset_unbacked_evidence_refs"
            ),
            details={
                "dataset_path_label": config.dataset_path.name,
                "official_turn_case_count": official_case_count,
                "requested_groups": list(groups),
                "requested_per_group": _FAST_CASES_PER_GROUP,
                "selected_by_group": selected_by_group,
                "selected_with_turn_evidence_by_group": (
                    selected_with_turn_evidence_by_group
                ),
                "missing_groups": missing_groups,
                "missing_turn_evidence_groups": missing_turn_evidence_groups,
            },
        ),
    )


def _service_probe_checks(
    config: MemoryComparisonPreflightConfig,
) -> tuple[MemoryComparisonPreflightCheck, ...]:
    return (
        _probe_memo_api(
            "memo_api_reachable",
            config.memo_api_url,
            timeout_seconds=config.probe_timeout_seconds,
        ),
        _probe_mem0_api(
            "mem0_api_reachable",
            config.mem0_url,
            timeout_seconds=config.probe_timeout_seconds,
        ),
    )


def _safe_reporting_contracts(report_mode: str) -> list[dict[str, object]]:
    report_modes = ["compact"] if report_mode == "compact" else [report_mode]
    return [
        {
            "name": name,
            "schema_version": schema_version,
            "report_modes": report_modes,
            "safe_payload": True,
        }
        for name, schema_version in _SAFE_REPORTING_CONTRACTS
    ]


def _secret_diagnostics(config: MemoryComparisonPreflightConfig) -> dict[str, object]:
    return {
        "auth_token_configured": config.auth_token_configured,
        "mem0_api_key_configured": _env_is_set(config.env, config.mem0_api_key_env),
        "mem0_api_key_env": _compact_diagnostic_text(config.mem0_api_key_env),
        "openai_api_key_configured": _env_is_set(
            config.env,
            config.openai_api_key_env,
        ),
        "openai_api_key_env": _compact_diagnostic_text(config.openai_api_key_env),
        "fallback_openai_api_key_configured": _env_is_set(
            config.env,
            "OPENAI_API_KEY",
        ),
        "fallback_openai_api_key_env": "OPENAI_API_KEY",
    }


def _probe_memo_api(
    name: str,
    base_url: str,
    *,
    timeout_seconds: float,
) -> MemoryComparisonPreflightCheck:
    path = "/v1/health"
    try:
        import httpx

        with httpx.Client(
            base_url=str(base_url).rstrip("/"),
            timeout=max(0.1, timeout_seconds),
            follow_redirects=False,
        ) as client:
            response = client.get(path)
    except Exception as exc:
        return MemoryComparisonPreflightCheck(
            name=name,
            passed=False,
            severity="service-probe",
            reason="memo API did not respond to unauthenticated health probe",
            reason_code="memo_api_probe_failed",
            details={"path": path, "error_type": type(exc).__name__},
        )
    passed = response.status_code < 400
    return MemoryComparisonPreflightCheck(
        name=name,
        passed=passed,
        severity="service-probe",
        reason=None if passed else "memo API health endpoint did not return HTTP 2xx/3xx",
        reason_code=None if passed else "memo_api_unhealthy_status",
        details={"path": path, "status_code": response.status_code},
    )


def _probe_mem0_api(
    name: str,
    base_url: str,
    *,
    timeout_seconds: float,
) -> MemoryComparisonPreflightCheck:
    path = "/openapi.json"
    required_paths = frozenset({"/memories", "/search"})
    try:
        import httpx

        with httpx.Client(
            base_url=str(base_url).rstrip("/"),
            timeout=max(0.1, timeout_seconds),
            follow_redirects=False,
        ) as client:
            response = client.get(path)
            payload = response.json() if response.status_code < 400 else {}
    except Exception as exc:
        return MemoryComparisonPreflightCheck(
            name=name,
            passed=False,
            severity="service-probe",
            reason="mem0 API did not expose an unauthenticated OpenAPI contract",
            reason_code="mem0_api_openapi_probe_failed",
            details={"path": path, "error_type": type(exc).__name__},
        )

    available_paths = _openapi_paths(payload)
    matched_paths = required_paths.intersection(available_paths)
    passed = response.status_code < 400 and required_paths.issubset(available_paths)
    return MemoryComparisonPreflightCheck(
        name=name,
        passed=passed,
        severity="service-probe",
        reason=None if passed else "mem0 API contract is missing required OSS benchmark endpoints",
        reason_code=None if passed else "mem0_api_contract_missing_required_paths",
        details={
            "path": path,
            "status_code": response.status_code,
            "required_paths": sorted(required_paths),
            "matched_paths": sorted(matched_paths),
        },
    )


def _required_check(
    name: str,
    *,
    passed: bool,
    reason: str | None,
    reason_code: str | None = None,
    details: Mapping[str, object] | None = None,
) -> MemoryComparisonPreflightCheck:
    return MemoryComparisonPreflightCheck(
        name=name,
        passed=passed,
        severity="required",
        reason=None if passed else reason,
        reason_code=None if passed else reason_code or f"{name}_failed",
        details=details or {},
    )


def _warning_check(
    name: str,
    *,
    passed: bool,
    reason: str,
    reason_code: str | None = None,
    details: Mapping[str, object] | None = None,
) -> MemoryComparisonPreflightCheck:
    return MemoryComparisonPreflightCheck(
        name=name,
        passed=passed,
        severity="warning",
        reason=None if passed else reason,
        reason_code=None if passed else reason_code or f"{name}_warning",
        details=details or {},
    )


def _fast_check(
    name: str,
    *,
    passed: bool,
    reason: str,
    reason_code: str | None = None,
    details: Mapping[str, object] | None = None,
) -> MemoryComparisonPreflightCheck:
    return MemoryComparisonPreflightCheck(
        name=name,
        passed=passed,
        severity="fast-readiness",
        reason=None if passed else reason,
        reason_code=None if passed else reason_code or f"{name}_not_fast_ready",
        details=details or {},
    )


def _safe_to_run_paid_llm(
    config: MemoryComparisonPreflightConfig,
    checks: Sequence[MemoryComparisonPreflightCheck],
) -> bool:
    if not _uses_openai(config):
        return True
    return not any(
        check.name.startswith("openai_") and not check.passed
        or check.name == "paid_llm_gate" and not check.passed
        for check in checks
    )


def _uses_openai(config: MemoryComparisonPreflightConfig) -> bool:
    return config.answerer_provider == "openai" or config.judge_provider == "openai"


def _env_is_set(env: Mapping[str, str], name: str) -> bool:
    return bool(str(env.get(name, "")).strip())


def _normalized_cutoffs(values: Sequence[int]) -> tuple[int, ...]:
    return tuple(sorted({int(value) for value in values if int(value) > 0}))


def _top_level_count(payload: object) -> int:
    if isinstance(payload, Sequence) and not isinstance(payload, str | bytes):
        return len(payload)
    if isinstance(payload, Mapping):
        for key in ("data", "cases", "samples", "conversations"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, str | bytes):
                return len(value)
        return len(payload)
    return 0


def _read_dataset_payload(dataset_path: Path) -> object:
    return json.loads(dataset_path.read_text(encoding="utf-8"))


def _locomo_fast_dataset_case_counts(
    payload: object,
    *,
    groups: Sequence[str],
) -> tuple[int, dict[str, int], dict[str, int]]:
    selected_by_group = dict.fromkeys(groups, 0)
    selected_with_turn_evidence_by_group = dict.fromkeys(groups, 0)
    official_case_count = 0
    for sample in _official_locomo_samples(payload):
        if not _official_locomo_sample_has_turns(sample):
            continue
        turn_evidence_ids = _official_locomo_sample_turn_evidence_ids(sample)
        qas = sample.get("qa")
        if not isinstance(qas, Sequence) or isinstance(qas, str | bytes):
            continue
        for qa in qas:
            if not isinstance(qa, Mapping):
                continue
            group = _official_locomo_qa_group(qa)
            if group is None:
                continue
            if not _text_field(qa, "question", "query"):
                continue
            if not _has_locomo_answer_or_evidence(qa):
                continue
            official_case_count += 1
            if group in selected_by_group:
                selected_by_group[group] += 1
                if _qa_has_backed_turn_evidence(qa, turn_evidence_ids):
                    selected_with_turn_evidence_by_group[group] += 1
    return official_case_count, selected_by_group, selected_with_turn_evidence_by_group


def _official_locomo_samples(payload: object) -> tuple[Mapping[str, object], ...]:
    if isinstance(payload, Mapping):
        if _is_official_locomo_sample(payload):
            return (payload,)
        raw_samples = (
            payload.get("data")
            or payload.get("cases")
            or payload.get("samples")
            or payload.get("items")
        )
        if raw_samples is not None:
            return _official_locomo_samples(raw_samples)
    if isinstance(payload, Sequence) and not isinstance(payload, str | bytes):
        return tuple(
            item
            for item in payload
            if isinstance(item, Mapping) and _is_official_locomo_sample(item)
        )
    return ()


def _is_official_locomo_sample(value: Mapping[str, object]) -> bool:
    qas = value.get("qa")
    return (
        isinstance(value.get("conversation"), Mapping)
        and isinstance(qas, Sequence)
        and not isinstance(qas, str | bytes)
    )


def _official_locomo_sample_has_turns(sample: Mapping[str, object]) -> bool:
    conversation = sample.get("conversation")
    if not isinstance(conversation, Mapping):
        return False
    for key, value in conversation.items():
        if not str(key).startswith("session_"):
            continue
        if str(key).endswith("_date_time"):
            continue
        turns = _official_locomo_session_turns(value)
        if not turns:
            continue
        if any(
            isinstance(turn, Mapping)
            and _text_field(
                turn,
                "text",
                "content",
                "utterance",
                "caption",
                "blip_caption",
                "query",
                "image_query",
                "visual_query",
            )
            for turn in turns
        ):
            return True
    return False


def _official_locomo_sample_turn_evidence_ids(
    sample: Mapping[str, object],
) -> frozenset[str]:
    conversation = sample.get("conversation")
    if not isinstance(conversation, Mapping):
        return frozenset()
    evidence_ids: set[str] = set()
    for key, value in conversation.items():
        if not str(key).startswith("session_"):
            continue
        if str(key).endswith("_date_time"):
            continue
        turns = _official_locomo_session_turns(value)
        if not turns:
            continue
        for index, turn in enumerate(turns):
            if not isinstance(turn, Mapping):
                continue
            if not _text_field(
                turn,
                "text",
                "content",
                "utterance",
                "caption",
                "blip_caption",
                "query",
                "image_query",
                "visual_query",
            ):
                continue
            turn_evidence_ids = _locomo_evidence_ids_from_mapping(turn)
            if turn_evidence_ids:
                evidence_ids.update(turn_evidence_ids)
            evidence_ids.update(
                _locomo_synthesized_turn_evidence_ids(
                    turn,
                    session_key=key,
                    turn_index=index,
                )
            )
    return frozenset(evidence_ids)


def _official_locomo_session_turns(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(value)
    if isinstance(value, Mapping):
        for key in (
            "dialogue",
            "dialogues",
            "turns",
            "utterances",
            "messages",
            "items",
            "conversation",
        ):
            turns = value.get(key)
            if isinstance(turns, Sequence) and not isinstance(turns, str | bytes):
                return tuple(turns)
    return ()


def _locomo_synthesized_turn_evidence_ids(
    turn: Mapping[str, object],
    *,
    session_key: object,
    turn_index: int,
) -> tuple[str, ...]:
    session_key_text = str(session_key)
    fallback_id = f"{session_key_text}:{turn_index + 1}"
    dialogue_ref = _locomo_dialogue_ref_from_session_key(session_key_text)
    if not dialogue_ref:
        return (fallback_id,)
    raw_id = _text_field(turn, "dia_id", "id")
    if raw_id and _locomo_dia_ids_from_text(raw_id):
        return (*_locomo_dia_ids_from_text(raw_id), fallback_id)
    if raw_id and raw_id.isdigit() and int(raw_id) > 0:
        return (f"{dialogue_ref}:{int(raw_id)}", fallback_id)
    return (f"{dialogue_ref}:{turn_index + 1}", fallback_id)


def _qa_has_backed_turn_evidence(
    qa: Mapping[str, object],
    turn_evidence_ids: frozenset[str],
) -> bool:
    return any(
        evidence_id in turn_evidence_ids
        for evidence_id in _locomo_qa_evidence_ids(qa)
    )


def _locomo_qa_evidence_ids(value: object) -> tuple[str, ...]:
    evidence_ids: list[str] = []
    for item in _locomo_qa_evidence_values(value):
        evidence_id = str(item).strip()
        if evidence_id:
            evidence_ids.extend(_locomo_dia_ids_from_text(evidence_id))
            evidence_ids.append(evidence_id)
    return tuple(dict.fromkeys(evidence_ids))


def _locomo_qa_evidence_values(value: object) -> tuple[object, ...]:
    if isinstance(value, Mapping):
        values: list[object] = []
        structured_evidence_id = _locomo_structured_evidence_id(value)
        if structured_evidence_id:
            values.append(structured_evidence_id)
        for key in (
            "dia_id",
            "dialogue_id",
            "evidence",
            "evidence_id",
            "evidence_ids",
            "evidence_ref",
            "evidence_refs",
            "id",
            "locomo_evidence_ref",
            "locomo_evidence_refs",
            "source_identity",
            "source_identity_ref",
            "source_identity_refs",
            "source_identity_items",
            "source_dialogue",
            "source_dialogue_id",
            "source_dialogue_index",
            "source_dia_id",
            "source_evidence_ref",
            "source_evidence_refs",
            "source_ref",
            "source_refs",
            "source_turn",
            "source_turn_id",
            "source_turn_index",
            "source_turn_ref",
            "source_turn_refs",
            "supporting_evidence",
            "supporting_facts",
            "turn",
            "turn_id",
            "turn_index",
            "turn_ids",
            "turn_ref",
            "turn_refs",
        ):
            if key in value:
                values.extend(_locomo_qa_evidence_values(value.get(key)))
        return tuple(values)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        values = []
        for item in value:
            values.extend(_locomo_qa_evidence_values(item))
        return tuple(values)
    return (value,) if value is not None else ()


def _locomo_evidence_ids_from_mapping(value: Mapping[str, object]) -> tuple[str, ...]:
    evidence_ids: list[str] = []
    structured_evidence_id = _locomo_structured_evidence_id(value)
    if structured_evidence_id:
        evidence_ids.append(structured_evidence_id)
    for key in (
        "dia_id",
        "dialogue_id",
        "evidence_id",
        "evidence_ref",
        "id",
        "locomo_evidence_ref",
        "source_identity",
        "source_identity_ref",
        "source_dia_id",
        "source_evidence_ref",
        "source_ref",
        "source_turn_ref",
        "turn_id",
        "turn_ref",
    ):
        text = _text_field(value, key)
        if not text:
            continue
        evidence_ids.extend(_locomo_dia_ids_from_text(text))
        evidence_ids.append(text)
    for key in (
        "evidence",
        "evidence_refs",
        "locomo_evidence_refs",
        "source_identity_refs",
        "source_identity_items",
        "source_evidence_refs",
        "source_refs",
        "source_turn_refs",
        "supporting_evidence",
        "supporting_facts",
        "turn_refs",
    ):
        for raw_value in _locomo_qa_evidence_values(value.get(key)):
            text = str(raw_value or "").strip()
            if not text:
                continue
            evidence_ids.extend(_locomo_dia_ids_from_text(text))
            evidence_ids.append(text)
    return tuple(dict.fromkeys(evidence_ids))


def _locomo_structured_evidence_id(value: Mapping[str, object]) -> str:
    dialogue = _locomo_dialogue_number_from_mapping(value)
    turn = _locomo_turn_number_from_mapping(value)
    if dialogue is None or turn is None:
        return ""
    return f"D{dialogue}:{turn}"


def _locomo_dialogue_number_from_mapping(value: Mapping[str, object]) -> int | None:
    for key in (
        "source_dialogue",
        "source_dialogue_id",
        "source_dialogue_index",
        "source_dia_id",
        "source_conversation",
        "source_conversation_id",
        "source_conversation_index",
        "locomo_session",
        "locomo_session_id",
        "locomo_session_index",
        "locomo_session_number",
        "locomo_conversation",
        "locomo_conversation_id",
        "locomo_conversation_index",
        "locomo_conversation_number",
        "locomo_dialogue",
        "locomo_dialogue_id",
        "locomo_dialogue_index",
        "locomo_dialogue_number",
        "conversation",
        "conversation_id",
        "conversation_index",
        "conversation_number",
        "conv",
        "conv_id",
        "conv_index",
        "conv_number",
        "dialogue_id",
        "dialogue_index",
        "dia_id",
        "session",
        "session_id",
        "session_index",
        "session_number",
    ):
        parsed = _locomo_positive_int(value.get(key), allow_dialogue_prefix=True)
        if parsed is not None:
            return parsed
    return None


def _locomo_turn_number_from_mapping(value: Mapping[str, object]) -> int | None:
    for key in (
        "source_turn",
        "source_turn_id",
        "source_turn_idx",
        "source_turn_index",
        "source_turn_number",
        "source_utterance",
        "source_utterance_id",
        "source_utterance_idx",
        "source_utterance_index",
        "source_utterance_number",
        "locomo_turn",
        "locomo_turn_id",
        "locomo_turn_idx",
        "locomo_turn_index",
        "locomo_turn_number",
        "turn",
        "turn_id",
        "turn_idx",
        "turn_index",
        "turn_number",
        "utt",
        "utt_id",
        "utt_idx",
        "utt_index",
        "utt_number",
        "utterance_id",
        "utterance_index",
        "utterance_number",
    ):
        parsed = _locomo_positive_int(value.get(key), allow_dialogue_prefix=False)
        if parsed is not None:
            return parsed
    return None


def _locomo_positive_int(
    value: object,
    *,
    allow_dialogue_prefix: bool,
) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if allow_dialogue_prefix:
        match = _LOCOMO_DIALOGUE_ID_RE.fullmatch(stripped)
        if match is not None:
            return int(match.group("dialogue"))
        match = re.fullmatch(
            r"(?:session|conversation|conv|dialogue|dialog)[-_](?P<dialogue>\d+)",
            stripped,
            re.IGNORECASE,
        )
        if match is not None:
            return int(match.group("dialogue"))
    else:
        match = re.fullmatch(
            r"(?:turn|utt|utterance|t)[-_]?(?P<turn>\d+)",
            stripped,
            re.IGNORECASE,
        )
        if match is not None:
            parsed = int(match.group("turn"))
            return parsed if parsed > 0 else None
    if stripped.isdigit():
        parsed = int(stripped)
        return parsed if parsed > 0 else None
    return None


def _locomo_dia_ids_from_text(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            f"D{match.group('dialogue')}:{match.group('turn')}"
            for match in _LOCOMO_DIA_ID_RE.finditer(value)
        )
    )


def _locomo_dialogue_ref_from_session_key(value: object) -> str:
    match = re.fullmatch(r"session[_-](?P<dialogue>\d+)", str(value or ""))
    return f"D{match.group('dialogue')}" if match is not None else ""


def _official_locomo_qa_group(qa: Mapping[str, object]) -> str | None:
    category = qa.get("category")
    if isinstance(category, bool):
        return None
    if isinstance(category, str):
        normalized = re.sub(r"[\s_]+", "-", category.strip().lower())
        return {
            "multi-hop": "multi-hop",
            "temporal": "temporal",
            "open-domain": "open-domain",
            "single-hop": "single-hop",
        }.get(normalized)
    try:
        category_id = int(category) if category is not None else None
    except (TypeError, ValueError):
        return None
    return {
        1: "multi-hop",
        2: "temporal",
        3: "open-domain",
        4: "single-hop",
    }.get(category_id)


def _has_locomo_answer_or_evidence(qa: Mapping[str, object]) -> bool:
    for key in (
        "answer",
        "expected_answer",
        "answers",
        "evidence",
        "evidence_ref",
        "evidence_refs",
        "locomo_evidence_ref",
        "locomo_evidence_refs",
        "source_evidence_ref",
        "source_evidence_refs",
        "source_ref",
        "source_refs",
        "source_turn_ref",
        "source_turn_refs",
    ):
        if _has_text_value(qa.get(key)):
            return True
    return False


def _text_field(value: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def _has_text_value(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_text_value(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return any(_has_text_value(item) for item in value)
    return False


def _openapi_paths(payload: object) -> frozenset[str]:
    if not isinstance(payload, Mapping):
        return frozenset()
    paths = payload.get("paths")
    if not isinstance(paths, Mapping):
        return frozenset()
    return frozenset(str(path) for path in paths)


def _json_safe_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {
        safe_key: _json_safe_value(raw_value)
        for safe_key, raw_value in sorted(
            (
                (_compact_diagnostic_text(key), raw_value)
                for key, raw_value in value.items()
            ),
            key=lambda item: item[0],
        )[:_MAX_DIAGNOSTIC_ITEMS]
    }


def _json_safe_value(value: object) -> object:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _compact_diagnostic_text(value)
    if isinstance(value, str):
        return _compact_diagnostic_text(value)
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_json_safe_value(item) for item in tuple(value)[:_MAX_DIAGNOSTIC_ITEMS]]
    return _compact_diagnostic_text(value)


def _compact_diagnostic_text(value: object) -> str:
    text = str(value).strip()
    if len(text) <= _MAX_DIAGNOSTIC_TEXT:
        return text
    return f"{text[: _MAX_DIAGNOSTIC_TEXT - 3]}..."

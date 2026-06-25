"""Black-box API canary for semantic retrieval ranking regressions."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.eval_common import (
    _git_report,
    _remember_eval_fact_response,
    _response_data_id,
    _status_ok,
    _write_redacted_report,
)
from infinity_context_server.eval_constants import SEMANTIC_RETRIEVAL_API_CANARY_SUITE
from infinity_context_server.main import create_app


@dataclass(frozen=True)
class _ApiRetrievalDecoy:
    marker: str
    text: str


@dataclass(frozen=True)
class _ApiRetrievalCase:
    case_id: str
    category: str
    query: str
    target_marker: str
    target_text: str
    decoys: tuple[_ApiRetrievalDecoy, ...]
    expected_top_query_reason: str


def run_semantic_retrieval_api_canary(*, report_out: Path | None = None) -> dict[str, object]:
    """Run an offline HTTP-level canary against the public v1 memory API."""

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        app = create_app(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'semantic-api-canary.db'}",
                auto_create_schema=True,
                service_token="eval-token",
                qdrant_enabled=False,
                graphiti_enabled=False,
                embeddings_enabled=False,
                asset_storage_dir=str(tmp_path / "assets"),
            )
        )
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer eval-token"}
            cases = tuple(_run_api_case(client, headers, case) for case in _api_cases())

    failures = tuple(failure for case in cases for failure in _case_failures(case))
    case_count = len(cases)
    passed_case_count = sum(1 for case in cases if case["ok"] is True)
    top1_recall = _ratio(
        sum(1 for case in cases if case.get("top_item_has_target") is True),
        case_count,
    )
    top1_precision = _ratio(
        sum(1 for case in cases if case.get("top_item_has_forbidden_marker") is False),
        case_count,
    )
    metrics = {
        "case_count": case_count,
        "passed_case_count": passed_case_count,
        "failed_case_count": len(failures),
        "top1_recall": top1_recall,
        "top1_precision": top1_precision,
        "tight_budget_forbidden_rendered_count": sum(
            1 for case in cases if case.get("rendered_has_forbidden_marker") is True
        ),
    }
    gates = {
        "all_cases_passed": not failures,
        "case_count": case_count >= 4,
        "top1_recall": top1_recall == 1.0,
        "top1_precision": top1_precision == 1.0,
        "tight_budget_precision": metrics["tight_budget_forbidden_rendered_count"] == 0,
    }
    result = {
        "suite": SEMANTIC_RETRIEVAL_API_CANARY_SUITE,
        "status": "passed" if all(gates.values()) else "failed",
        "ok": all(gates.values()),
        "metrics": metrics,
        "gates": gates,
        "cases": list(cases),
        "failures": list(failures),
        "git": _git_report(),
    }
    _write_redacted_report(result, report_out)
    return result


def _api_cases() -> tuple[_ApiRetrievalCase, ...]:
    return (
        _ApiRetrievalCase(
            case_id="api_membership_self_identification_beats_ally_decoy",
            category="community_membership",
            query="Would Melanie be considered a member of the LGBTQ community?",
            target_marker="API_CANARY_MEMBER_TARGET",
            target_text=(
                "API_CANARY_MEMBER_TARGET Melanie identifies as part of the LGBTQ "
                "community and joined the pride group."
            ),
            decoys=(
                _ApiRetrievalDecoy(
                    marker="API_CANARY_MEMBER_ALLY_DECOY",
                    text=(
                        "API_CANARY_MEMBER_ALLY_DECOY Melanie is supportive of Caroline "
                        "and encourages the LGBTQ community as an ally."
                    ),
                ),
            ),
            expected_top_query_reason="community_membership_bridge",
        ),
        _ApiRetrievalCase(
            case_id="api_ally_support_beats_subject_identity_decoy",
            category="ally_support",
            query="Would Melanie be considered an ally to the transgender community?",
            target_marker="API_CANARY_ALLY_TARGET",
            target_text=(
                "API_CANARY_ALLY_TARGET Melanie used supportive and encouraging kind "
                "words about Caroline and accepted her transgender journey."
            ),
            decoys=(
                _ApiRetrievalDecoy(
                    marker="API_CANARY_ALLY_IDENTITY_DECOY",
                    text=(
                        "API_CANARY_ALLY_IDENTITY_DECOY Melanie shared her pronouns "
                        "and described her own gender identity as a trans woman."
                    ),
                ),
            ),
            expected_top_query_reason="decomposition_ally_support_evidence",
        ),
        _ApiRetrievalCase(
            case_id="api_religious_evidence_beats_political_topic_decoy",
            category="religious_inference",
            query="Would Caroline be considered religious?",
            target_marker="API_CANARY_RELIGIOUS_TARGET",
            target_text=(
                "API_CANARY_RELIGIOUS_TARGET Caroline made stained glass artwork "
                "for a local church."
            ),
            decoys=(
                _ApiRetrievalDecoy(
                    marker="API_CANARY_RELIGIOUS_POLITICAL_DECOY",
                    text=(
                        "API_CANARY_RELIGIOUS_POLITICAL_DECOY Caroline said religious "
                        "conservatives made her feel unwelcoming during her transgender "
                        "journey."
                    ),
                ),
            ),
            expected_top_query_reason="religious_inference_bridge",
        ),
        _ApiRetrievalCase(
            case_id="api_relative_conversation_recency_beats_old_topic_decoy",
            category="relative_time",
            query="What did Alex tell me an hour ago?",
            target_marker="API_CANARY_RECENCY_TARGET",
            target_text=(
                "API_CANARY_RECENCY_TARGET Call transcript from an hour ago: Alex "
                "told me the Atlas budget decision."
            ),
            decoys=(
                _ApiRetrievalDecoy(
                    marker="API_CANARY_RECENCY_OLD_DECOY",
                    text=(
                        "API_CANARY_RECENCY_OLD_DECOY Last week Alex told me about "
                        "a different Atlas topic."
                    ),
                ),
            ),
            expected_top_query_reason="decomposition_conversation_recency",
        ),
    )


def _run_api_case(
    client: TestClient,
    headers: dict[str, str],
    case: _ApiRetrievalCase,
) -> dict[str, object]:
    memory_scope_id = f"memory_scope_{case.case_id}"
    seeded_fact_ids = [
        _seed_fact(
            client,
            headers,
            memory_scope_id=memory_scope_id,
            source_id=f"{case.case_id}:target",
            text=case.target_text,
        )
    ]
    for decoy in case.decoys:
        seeded_fact_ids.append(
            _seed_fact(
                client,
                headers,
                memory_scope_id=memory_scope_id,
                source_id=f"{case.case_id}:decoy:{decoy.marker}",
                text=decoy.text,
            )
        )

    response = client.post(
        "/v1/context",
        json={
            "space_id": "space_semantic_api_canary",
            "memory_scope_ids": [memory_scope_id],
            "query": case.query,
            "token_budget": 900,
            "max_facts": 1,
            "max_chunks": 0,
            "max_evidence_items": 0,
        },
        headers=headers,
    )
    data = _response_data(response)
    items = _data_items(data)
    top_item = items[0] if items else {}
    top_text = str(top_item.get("text", ""))
    rendered_text = str(data.get("rendered_text", ""))
    forbidden_markers = tuple(decoy.marker for decoy in case.decoys)
    top_reason = _top_score_signal(top_item, "deterministic_rerank_query_reason")
    failures = _api_case_failures(
        case,
        context_status=response.status_code,
        seeded_fact_ids=seeded_fact_ids,
        top_text=top_text,
        rendered_text=rendered_text,
        top_reason=top_reason,
        forbidden_markers=forbidden_markers,
    )
    return {
        "case_id": case.case_id,
        "category": case.category,
        "type": "api_tight_budget_context",
        "ok": not failures,
        "query": case.query,
        "context_status": response.status_code,
        "seeded_fact_count": len([fact_id for fact_id in seeded_fact_ids if fact_id]),
        "top_item_id": str(top_item.get("item_id", "")),
        "top_item_score": top_item.get("score"),
        "top_item_query_reason": top_reason,
        "top_item_has_target": case.target_marker in top_text,
        "top_item_has_forbidden_marker": any(marker in top_text for marker in forbidden_markers),
        "rendered_has_target": case.target_marker in rendered_text,
        "rendered_has_forbidden_marker": any(
            marker in rendered_text for marker in forbidden_markers
        ),
        "diagnostics": _safe_case_diagnostics(top_item),
        "failures": failures,
    }


def _seed_fact(
    client: TestClient,
    headers: dict[str, str],
    *,
    memory_scope_id: str,
    source_id: str,
    text: str,
) -> str:
    response = _remember_eval_fact_response(
        client,
        headers,
        space_id="space_semantic_api_canary",
        memory_scope_id=memory_scope_id,
        text=text,
        source_id=source_id,
        idempotency_key=source_id,
    )
    if not _status_ok(response.status_code):
        return ""
    return _response_data_id(response) or ""


def _api_case_failures(
    case: _ApiRetrievalCase,
    *,
    context_status: int,
    seeded_fact_ids: list[str],
    top_text: str,
    rendered_text: str,
    top_reason: object,
    forbidden_markers: tuple[str, ...],
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    if len([fact_id for fact_id in seeded_fact_ids if fact_id]) != 1 + len(case.decoys):
        failures.append(
            {
                "reason": "seed_failed",
                "seeded_fact_count": len([fact_id for fact_id in seeded_fact_ids if fact_id]),
                "expected": 1 + len(case.decoys),
            }
        )
    if context_status != 200:
        failures.append({"reason": "context_request_failed", "status_code": context_status})
        return failures
    if case.target_marker not in top_text:
        failures.append({"reason": "target_not_top1", "expected_marker": case.target_marker})
    forbidden_top = tuple(marker for marker in forbidden_markers if marker in top_text)
    if forbidden_top:
        failures.append(
            {"reason": "forbidden_marker_top1", "forbidden_markers": list(forbidden_top)}
        )
    if case.target_marker not in rendered_text:
        failures.append(
            {"reason": "target_not_rendered", "expected_marker": case.target_marker}
        )
    forbidden_rendered = tuple(marker for marker in forbidden_markers if marker in rendered_text)
    if forbidden_rendered:
        failures.append(
            {
                "reason": "forbidden_marker_rendered_in_tight_budget",
                "forbidden_markers": list(forbidden_rendered),
            }
        )
    if top_reason != case.expected_top_query_reason:
        failures.append(
            {
                "reason": "unexpected_top_query_reason",
                "expected": case.expected_top_query_reason,
                "actual": top_reason,
            }
        )
    return failures


def _response_data(response) -> dict[str, object]:
    try:
        data = response.json()["data"]
    except (KeyError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _data_items(data: dict[str, object]) -> list[dict[str, object]]:
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _top_score_signal(item: dict[str, object], key: str) -> object:
    diagnostics = item.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    score_signals = diagnostics.get("score_signals")
    if not isinstance(score_signals, dict):
        return None
    return score_signals.get(key)


def _safe_case_diagnostics(item: dict[str, object]) -> dict[str, object]:
    diagnostics = item.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return {}
    score_signals = diagnostics.get("score_signals")
    if not isinstance(score_signals, dict):
        score_signals = {}
    return {
        "retrieval_source": diagnostics.get("retrieval_source"),
        "ranking_reason": diagnostics.get("ranking_reason"),
        "deterministic_rerank_net_adjustment": score_signals.get(
            "deterministic_rerank_net_adjustment"
        ),
        "deterministic_rerank_query_reason": score_signals.get(
            "deterministic_rerank_query_reason"
        ),
        "deterministic_rerank_requirement_coverage": score_signals.get(
            "deterministic_rerank_requirement_coverage"
        ),
    }


def _case_failures(case: dict[str, object]) -> tuple[dict[str, object], ...]:
    failures = case.get("failures")
    if not isinstance(failures, list):
        return ()
    return tuple(
        {
            "case_id": str(case.get("case_id", "")),
            "category": str(case.get("category", "")),
            **failure,
        }
        for failure in failures
        if isinstance(failure, dict)
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)

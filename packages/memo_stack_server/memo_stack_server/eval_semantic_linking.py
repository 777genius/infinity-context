"""Deterministic eval for semantic context-link suggestions."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from memo_stack_server.config import CaptureMode, DeployProfile, Settings
from memo_stack_server.eval_common import _write_redacted_report
from memo_stack_server.eval_constants import SEMANTIC_LINKING_GOLDEN_SUITE
from memo_stack_server.main import create_app


def run_semantic_linking_golden(
    *,
    api_url: str | None = None,
    auth_token: str | None = None,
    report_out: Path | None = None,
) -> dict[str, object]:
    if api_url:
        token = auth_token or Settings().service_token
        if not token:
            result = _setup_failure("auth_token_required")
            _write_redacted_report(result, report_out)
            return result
        with httpx.Client(base_url=api_url.rstrip("/"), timeout=30.0) as client:
            result = _execute_semantic_linking_golden(
                client,
                {"Authorization": f"Bearer {token}"},
            )
            _write_redacted_report(result, report_out)
            return result

    with tempfile.TemporaryDirectory() as tmp_dir:
        app = create_app(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{Path(tmp_dir) / 'semantic-linking-eval.db'}",
                auto_create_schema=True,
                service_token="semantic-linking-eval-token",
                capture_mode=CaptureMode.SUGGEST,
            )
        )
        headers = {"Authorization": "Bearer semantic-linking-eval-token"}
        with TestClient(app) as client:
            result = _execute_semantic_linking_golden(client, headers)
    _write_redacted_report(result, report_out)
    return result


def _execute_semantic_linking_golden(client: Any, headers: dict[str, str]) -> dict[str, object]:
    checks: dict[str, bool] = {}
    cases: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    target_fact = _remember_fact(
        client,
        headers,
        text=(
            "Alex and Project Atlas onboarding pricing summary from an hour ago. "
            "The action item is invoice threshold approval."
        ),
        source_id="atlas-pricing",
    )
    distractor_fact = _remember_fact(
        client,
        headers,
        text=(
            "Alex and Project Aurora branding notes from last week. "
            "The topic is logo color and launch copy."
        ),
        source_id="aurora-branding",
    )
    source_capture = _capture(
        client,
        headers,
        source_event_id="atlas-pricing-capture",
        text=(
            "Screenshot note from Alex an hour ago about Project Atlas onboarding "
            "pricing and invoice threshold approval."
        ),
        thread_external_ref="quality-review",
    )
    checks["fixture_seeded"] = bool(target_fact and distractor_fact and source_capture)
    if not checks["fixture_seeded"]:
        failures.append(_failure("fixture_seeded", "setup", "fixture_seed_failed"))
        return _report(checks=checks, cases=cases, failures=failures)

    suggestions = _suggest(
        client,
        headers,
        source_id=str(source_capture["id"]),
        text="Alex hour ago Project Atlas onboarding pricing invoice threshold",
        thread_external_ref="quality-review",
    )
    candidates = suggestions.get("candidates", [])
    fact_candidates = [item for item in candidates if item.get("target_type") == "fact"]
    top_fact = fact_candidates[0] if fact_candidates else {}
    distractor_score = _candidate_score(fact_candidates, str(distractor_fact["id"]))
    checks["top_fact_beats_distractor"] = (
        top_fact.get("target_id") == target_fact["id"]
        and float(top_fact.get("score", 0.0)) > distractor_score
    )
    checks["reviewable_suggestion_created"] = bool(top_fact.get("suggestion_id"))
    anchor_keys = {
        (
            item.get("metadata", {}).get("anchor_kind"),
            item.get("metadata", {}).get("normalized_key"),
        )
        for item in candidates
        if item.get("target_type") == "anchor"
    }
    checks["person_and_project_anchors_suggested"] = {
        ("person", "alex"),
        ("project", "atlas"),
    }.issubset(anchor_keys)
    cases.append(
        {
            "case_id": "specific_target_beats_similar_project",
            "ok": checks["top_fact_beats_distractor"],
            "target_type": top_fact.get("target_type"),
            "target_id": top_fact.get("target_id"),
            "score": top_fact.get("score"),
            "distractor_score": distractor_score,
        }
    )
    if not checks["top_fact_beats_distractor"]:
        failures.append(
            _failure(
                "specific_target_beats_similar_project",
                "ranking",
                "top_fact_did_not_beat_distractor",
                item_ids=[str(target_fact["id"]), str(distractor_fact["id"])],
            )
        )

    approved = _approve(client, headers, str(top_fact.get("suggestion_id") or ""))
    checks["top_suggestion_approves_to_link"] = approved.get("target_id") == target_fact["id"]
    if not checks["top_suggestion_approves_to_link"]:
        failures.append(_failure("top_suggestion_approves_to_link", "review", "approval_failed"))

    call_fact = _remember_fact(
        client,
        headers,
        text=(
            "Alex Project Atlas call from last week covered migration rollback "
            "window ownership and production risk handoff."
        ),
        source_id="atlas-migration-call",
    )
    chat_distractor_fact = _remember_fact(
        client,
        headers,
        text=(
            "Alex Project Atlas chat from an hour ago covered billing dashboard "
            "copy and button icons."
        ),
        source_id="atlas-billing-chat",
    )
    call_capture = _capture(
        client,
        headers,
        source_event_id="atlas-migration-call-capture",
        text=(
            "Please link this note to the Alex Project Atlas call last week "
            "about migration rollback window and production risk handoff."
        ),
        thread_external_ref="quality-review",
    )
    event_suggestions = _suggest(
        client,
        headers,
        source_id=str(call_capture.get("id", "")),
        text="Alex Project Atlas call last week migration rollback production risk handoff",
        thread_external_ref="quality-review",
    )
    event_fact_candidates = [
        item
        for item in event_suggestions.get("candidates", [])
        if item.get("target_type") == "fact"
    ]
    top_event_fact = event_fact_candidates[0] if event_fact_candidates else {}
    chat_distractor_score = _candidate_score(
        event_fact_candidates,
        str(chat_distractor_fact.get("id", "")),
    )
    checks["event_call_beats_recent_chat"] = (
        bool(call_fact)
        and bool(chat_distractor_fact)
        and bool(call_capture)
        and top_event_fact.get("target_id") == call_fact["id"]
        and float(top_event_fact.get("score", 0.0)) > chat_distractor_score
    )
    cases.append(
        {
            "case_id": "event_call_beats_recent_chat",
            "ok": checks["event_call_beats_recent_chat"],
            "target_type": top_event_fact.get("target_type"),
            "target_id": top_event_fact.get("target_id"),
            "score": top_event_fact.get("score"),
            "distractor_score": chat_distractor_score,
        }
    )
    if not checks["event_call_beats_recent_chat"]:
        failures.append(
            _failure(
                "event_call_beats_recent_chat",
                "ranking",
                "event_call_did_not_beat_recent_chat",
                item_ids=[
                    str(call_fact.get("id", "")),
                    str(chat_distractor_fact.get("id", "")),
                ],
            )
        )

    unrelated_capture = _capture(
        client,
        headers,
        source_event_id="unrelated-capture",
        text="lowercase grocery reminder about bananas milk and receipts",
    )
    unrelated = _suggest(
        client,
        headers,
        source_id=str(unrelated_capture.get("id", "")),
        text="lowercase grocery reminder bananas milk receipts",
    )
    checks["unrelated_capture_has_no_candidates"] = unrelated.get("candidates") == []
    cases.append(
        {
            "case_id": "unrelated_capture_has_no_candidates",
            "ok": checks["unrelated_capture_has_no_candidates"],
            "candidate_count": len(unrelated.get("candidates", [])),
        }
    )
    if not checks["unrelated_capture_has_no_candidates"]:
        failures.append(
            _failure(
                "unrelated_capture_has_no_candidates",
                "precision",
                "unexpected_candidates",
            )
        )
    return _report(checks=checks, cases=cases, failures=failures)


def _remember_fact(
    client: Any,
    headers: dict[str, str],
    *,
    text: str,
    source_id: str,
) -> dict[str, object]:
    response = client.post(
        "/v1/facts",
        json={
            "space_slug": "semantic-linking-eval",
            "memory_scope_external_ref": "default",
            "thread_external_ref": "quality-review",
            "text": text,
            "kind": "note",
            "source_refs": [{"source_type": "manual", "source_id": source_id}],
        },
        headers={**headers, "Idempotency-Key": f"semantic-linking-eval-{source_id}"},
    )
    return _data(response) if response.status_code == 201 else {}


def _capture(
    client: Any,
    headers: dict[str, str],
    *,
    source_event_id: str,
    text: str,
    thread_external_ref: str | None = None,
) -> dict[str, object]:
    response = client.post(
        "/v1/captures",
        json={
            "space_slug": "semantic-linking-eval",
            "memory_scope_external_ref": "default",
            "thread_external_ref": thread_external_ref,
            "source_agent": "memo-frontend",
            "source_kind": "manual",
            "event_type": "QuickCapture",
            "actor_role": "user",
            "source_event_id": source_event_id,
            "text": text,
            "source_authority": "user_statement",
        },
        headers=headers,
    )
    return _data(response) if response.status_code == 201 else {}


def _suggest(
    client: Any,
    headers: dict[str, str],
    *,
    source_id: str,
    text: str,
    thread_external_ref: str | None = None,
) -> dict[str, object]:
    response = client.post(
        "/v1/link-suggestions",
        json={
            "space_slug": "semantic-linking-eval",
            "memory_scope_external_ref": "default",
            "thread_external_ref": thread_external_ref,
            "source_type": "capture",
            "source_id": source_id,
            "text": text,
            "persist": True,
            "limit": 8,
        },
        headers=headers,
    )
    return _data(response) if response.status_code == 200 else {"candidates": []}


def _approve(client: Any, headers: dict[str, str], suggestion_id: str) -> dict[str, object]:
    if not suggestion_id:
        return {}
    response = client.post(
        f"/v1/context-link-suggestions/{suggestion_id}/review",
        json={"action": "approve", "reason": "semantic linking eval accepted top target"},
        headers=headers,
    )
    if response.status_code != 200:
        return {}
    data = _data(response)
    link = data.get("link")
    return link if isinstance(link, dict) else {}


def _data(response: Any) -> dict[str, object]:
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


def _candidate_score(candidates: list[dict[str, object]], target_id: str) -> float:
    for candidate in candidates:
        if candidate.get("target_id") == target_id:
            return float(candidate.get("score", 0.0))
    return 0.0


def _report(
    *,
    checks: dict[str, bool],
    cases: list[dict[str, object]],
    failures: list[dict[str, object]],
) -> dict[str, object]:
    metrics = {
        "case_count": len(cases),
        "ranking_accuracy": 1.0 if checks.get("top_fact_beats_distractor") else 0.0,
        "event_linking_accuracy": 1.0 if checks.get("event_call_beats_recent_chat") else 0.0,
        "anchor_recall_rate": 1.0 if checks.get("person_and_project_anchors_suggested") else 0.0,
        "review_approval_rate": 1.0 if checks.get("top_suggestion_approves_to_link") else 0.0,
        "false_positive_count": 0 if checks.get("unrelated_capture_has_no_candidates") else 1,
    }
    gates = {
        "case_count": metrics["case_count"] >= 2,
        "ranking_accuracy": metrics["ranking_accuracy"] == 1.0,
        "event_linking_accuracy": metrics["event_linking_accuracy"] == 1.0,
        "anchor_recall_rate": metrics["anchor_recall_rate"] == 1.0,
        "review_approval_rate": metrics["review_approval_rate"] == 1.0,
        "false_positive_count": metrics["false_positive_count"] == 0,
    }
    ok = all(checks.values()) and all(gates.values()) and not failures
    return {
        "suite": SEMANTIC_LINKING_GOLDEN_SUITE,
        "status": "ok" if ok else "failed",
        "ok": ok,
        "checks": checks,
        "metrics": metrics,
        "gates": gates,
        "cases": cases,
        "failures": failures,
    }


def _failure(
    case_id: str,
    category: str,
    reason: str,
    *,
    item_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "category": category,
        "reason": reason,
        "item_ids": item_ids or [],
    }


def _setup_failure(reason: str) -> dict[str, object]:
    return _report(
        checks={"auth_token_configured": False},
        cases=[],
        failures=[_failure("suite_setup", "setup", reason)],
    )

"""Deterministic eval for semantic context-link suggestions."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from infinity_context_core.application.context_link_policy import apply_context_link_policy
from infinity_context_core.application.dto import ContextLinkCandidate

from infinity_context_server.config import CaptureMode, DeployProfile, Settings
from infinity_context_server.eval_common import _ratio, _write_redacted_report
from infinity_context_server.eval_constants import (
    SEMANTIC_LINKING_GOLDEN_SUITE,
    SEMANTIC_LINKING_REQUIRED_CASE_IDS,
)
from infinity_context_server.main import create_app


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
    space_slug = f"semantic-linking-eval-{uuid4().hex[:12]}"
    target_fact = _remember_fact(
        client,
        headers,
        space_slug=space_slug,
        text=(
            "Alex and Project Atlas onboarding pricing summary from an hour ago. "
            "OpenAI vendor review is part of the invoice threshold approval."
        ),
        source_id="atlas-pricing",
    )
    distractor_fact = _remember_fact(
        client,
        headers,
        space_slug=space_slug,
        text=(
            "Alex and Project Aurora branding notes from last week. "
            "The topic is logo color and launch copy."
        ),
        source_id="aurora-branding",
    )
    source_capture = _capture(
        client,
        headers,
        space_slug=space_slug,
        source_event_id="atlas-pricing-capture",
        text=(
            "Screenshot note from Alex an hour ago about Project Atlas onboarding "
            "pricing, OpenAI vendor review and invoice threshold approval."
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
        space_slug=space_slug,
        source_id=str(source_capture["id"]),
        text="Alex hour ago Project Atlas OpenAI onboarding pricing invoice threshold",
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
    checks["person_project_and_org_anchors_suggested"] = {
        ("person", "alex"),
        ("project", "atlas"),
        ("organization", "openai"),
    }.issubset(anchor_keys)
    checks["person_and_project_anchors_suggested"] = checks[
        "person_project_and_org_anchors_suggested"
    ]
    persisted_anchors = _list_anchors(client, headers, space_slug=space_slug)
    anchors_by_key = {
        (item.get("kind"), item.get("normalized_key")): item for item in persisted_anchors
    }
    required_anchor_keys = {
        ("person", "alex"),
        ("project", "atlas"),
        ("organization", "openai"),
    }
    checks["anchor_evidence_confidence_and_observed_at_exposed"] = all(
        _anchor_has_review_evidence(anchors_by_key.get(key)) for key in required_anchor_keys
    )
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
    cases.append(
        {
            "case_id": "person_project_and_org_anchors_suggested",
            "ok": checks["person_project_and_org_anchors_suggested"],
            "anchor_keys": sorted(anchor_keys),
        }
    )
    cases.append(
        {
            "case_id": "anchor_evidence_confidence_and_observed_at_exposed",
            "ok": checks["anchor_evidence_confidence_and_observed_at_exposed"],
            "anchor_keys": sorted(required_anchor_keys),
        }
    )
    same_name_capture = _capture(
        client,
        headers,
        space_slug=space_slug,
        source_event_id="same-name-anchor-capture",
        text="Alex wrote that Project Alex is a separate workspace.",
        thread_external_ref="quality-review",
    )
    same_name_suggestions = _suggest(
        client,
        headers,
        space_slug=space_slug,
        source_id=str(same_name_capture.get("id", "")),
        text="Alex wrote that Project Alex is a separate workspace",
        thread_external_ref="quality-review",
    )
    same_name_anchor_keys = {
        (
            item.get("metadata", {}).get("anchor_kind"),
            item.get("metadata", {}).get("normalized_key"),
        )
        for item in same_name_suggestions.get("candidates", [])
        if item.get("target_type") == "anchor"
    }
    checks["same_name_person_project_anchors_separate"] = {
        ("person", "alex"),
        ("project", "alex"),
    }.issubset(same_name_anchor_keys)
    cases.append(
        {
            "case_id": "same_name_person_project_anchors_separate",
            "ok": checks["same_name_person_project_anchors_separate"],
            "anchor_keys": sorted(same_name_anchor_keys),
        }
    )
    cross_script_capture = _capture(
        client,
        headers,
        space_slug=space_slug,
        source_event_id="cross-script-project-anchor-capture",
        text=(
            "Сохрани заметку по проекту Атлас: onboarding pricing invoice "
            "threshold approval is tied to OpenAI vendor review."
        ),
        thread_external_ref="quality-review",
    )
    cross_script_suggestions = _suggest(
        client,
        headers,
        space_slug=space_slug,
        source_id=str(cross_script_capture.get("id", "")),
        text="проект Атлас onboarding pricing OpenAI invoice threshold",
        thread_external_ref="quality-review",
    )
    cross_script_anchor_candidates = [
        item
        for item in cross_script_suggestions.get("candidates", [])
        if item.get("target_type") == "anchor"
    ]
    cross_script_project_candidate = next(
        (
            item
            for item in cross_script_anchor_candidates
            if item.get("metadata", {}).get("anchor_kind") == "project"
            and item.get("metadata", {}).get("canonical_key") == "atlas"
        ),
        {},
    )
    cross_script_anchors = _list_anchors(client, headers, space_slug=space_slug)
    atlas_project_anchors = [
        item
        for item in cross_script_anchors
        if item.get("kind") == "project"
        and item.get("metadata", {}).get("canonical_key") == "atlas"
    ]
    checks["cross_script_project_anchor_resolves_canonical"] = (
        bool(cross_script_capture)
        and bool(cross_script_project_candidate)
        and len(atlas_project_anchors) == 1
        and "Атлас" in set(atlas_project_anchors[0].get("aliases", []))
    )
    cases.append(
        {
            "case_id": "cross_script_project_anchor_resolves_canonical",
            "ok": checks["cross_script_project_anchor_resolves_canonical"],
            "candidate_target_id": cross_script_project_candidate.get("target_id"),
            "candidate_score": cross_script_project_candidate.get("score"),
            "atlas_anchor_count": len(atlas_project_anchors),
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
    if not checks["anchor_evidence_confidence_and_observed_at_exposed"]:
        failures.append(
            _failure(
                "anchor_evidence_confidence_and_observed_at_exposed",
                "anchor_quality",
                "anchors_missing_review_evidence_or_confidence",
            )
        )
    if not checks["same_name_person_project_anchors_separate"]:
        failures.append(
            _failure(
                "same_name_person_project_anchors_separate",
                "anchor_disambiguation",
                "same_normalized_person_and_project_not_kept_separate",
            )
        )
    if not checks["cross_script_project_anchor_resolves_canonical"]:
        failures.append(
            _failure(
                "cross_script_project_anchor_resolves_canonical",
                "anchor_disambiguation",
                "cross_script_project_anchor_not_canonicalized",
            )
        )

    policy_case = _high_impact_relation_policy_case()
    checks["high_impact_relation_requires_explicit_signal"] = bool(policy_case["ok"])
    cases.append(policy_case)
    if not checks["high_impact_relation_requires_explicit_signal"]:
        failures.append(
            _failure(
                "high_impact_relation_requires_explicit_signal",
                "policy",
                "high_impact_relation_accepted_without_explicit_signal",
            )
        )
    weak_policy_case = _weak_overlap_policy_case()
    checks["weak_overlap_below_review_threshold_denied"] = bool(weak_policy_case["ok"])
    cases.append(weak_policy_case)
    if not checks["weak_overlap_below_review_threshold_denied"]:
        failures.append(
            _failure(
                "weak_overlap_below_review_threshold_denied",
                "policy",
                "weak_overlap_candidate_accepted",
            )
        )
    for relation_policy_case in _relation_specific_policy_cases():
        case_id = str(relation_policy_case["case_id"])
        checks[case_id] = bool(relation_policy_case["ok"])
        cases.append(relation_policy_case)
        if not checks[case_id]:
            failures.append(
                _failure(
                    case_id,
                    "policy",
                    "relation_specific_policy_guard_failed",
                )
            )

    approved = _approve(client, headers, str(top_fact.get("suggestion_id") or ""))
    checks["top_suggestion_approves_to_link"] = approved.get("target_id") == target_fact["id"]
    if not checks["top_suggestion_approves_to_link"]:
        failures.append(_failure("top_suggestion_approves_to_link", "review", "approval_failed"))

    call_fact = _remember_fact(
        client,
        headers,
        space_slug=space_slug,
        text=(
            "Alex Project Atlas call from last week covered migration rollback "
            "window ownership and production risk handoff."
        ),
        source_id="atlas-migration-call",
    )
    chat_distractor_fact = _remember_fact(
        client,
        headers,
        space_slug=space_slug,
        text=(
            "Alex Project Atlas chat from an hour ago covered billing dashboard "
            "copy and button icons."
        ),
        source_id="atlas-billing-chat",
    )
    call_capture = _capture(
        client,
        headers,
        space_slug=space_slug,
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
        space_slug=space_slug,
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

    temporal_space_slug = f"{space_slug}-temporal"
    temporal_fact = _remember_fact(
        client,
        headers,
        space_slug=temporal_space_slug,
        text="Payment exception window was confirmed for Atlas cutoff.",
        source_id="atlas-payment-window",
        thread_external_ref="alex-chat-hour-ago",
    )
    temporal_capture = _capture(
        client,
        headers,
        space_slug=temporal_space_slug,
        source_event_id="temporal-intent-capture",
        text="Сохрани заметку и привяжи к разговору час назад.",
        thread_external_ref="quick-save",
    )
    temporal_suggestions = _suggest(
        client,
        headers,
        space_slug=temporal_space_slug,
        source_id=str(temporal_capture.get("id", "")),
        text="привяжи к разговору час назад",
        thread_external_ref="quick-save",
    )
    temporal_fact_candidates = [
        item
        for item in temporal_suggestions.get("candidates", [])
        if item.get("target_type") == "fact"
    ]
    temporal_fact_candidate = next(
        (
            item
            for item in temporal_fact_candidates
            if item.get("target_id") == temporal_fact.get("id")
        ),
        {},
    )
    temporal_metadata = temporal_fact_candidate.get("metadata", {})
    checks["temporal_intent_links_recent_fact_without_text_match"] = (
        bool(temporal_fact)
        and bool(temporal_capture)
        and bool(temporal_fact_candidate)
        and temporal_metadata.get("matched_terms") == []
        and "temporal_intent_match" in set(temporal_metadata.get("reason_codes", []))
    )
    cases.append(
        {
            "case_id": "temporal_intent_links_recent_fact_without_text_match",
            "ok": checks["temporal_intent_links_recent_fact_without_text_match"],
            "target_type": temporal_fact_candidate.get("target_type"),
            "target_id": temporal_fact_candidate.get("target_id"),
            "score": temporal_fact_candidate.get("score"),
        }
    )
    if not checks["temporal_intent_links_recent_fact_without_text_match"]:
        failures.append(
            _failure(
                "temporal_intent_links_recent_fact_without_text_match",
                "temporal_intent",
                "recent_fact_not_linked_without_text_match",
                item_ids=[str(temporal_fact.get("id", ""))],
            )
        )

    document_space_slug = f"{space_slug}-documents"
    target_document = _ingest_document(
        client,
        headers,
        space_slug=document_space_slug,
        title="Project Atlas onboarding pricing SOP",
        text=(
            "Project Atlas onboarding pricing SOP. "
            "Screenshots showing invoice threshold approval should be attached "
            "to this document evidence before the finance handoff."
        ),
        source_external_id="atlas-pricing-sop",
    )
    document_capture = _capture(
        client,
        headers,
        space_slug=document_space_slug,
        source_event_id="atlas-pricing-sop-screenshot",
        text=(
            "Screenshot from the Project Atlas onboarding pricing SOP showing "
            "invoice threshold approval before finance handoff."
        ),
        thread_external_ref="document-review",
    )
    document_suggestions = _suggest(
        client,
        headers,
        space_slug=document_space_slug,
        source_id=str(document_capture.get("id", "")),
        text="Project Atlas onboarding pricing SOP invoice threshold approval finance handoff",
        thread_external_ref="document-review",
    )
    document_candidates = [
        item
        for item in document_suggestions.get("candidates", [])
        if item.get("target_type") == "document"
    ]
    chunk_candidates = [
        item
        for item in document_suggestions.get("candidates", [])
        if item.get("target_type") == "chunk"
    ]
    top_document = document_candidates[0] if document_candidates else {}
    top_chunk = chunk_candidates[0] if chunk_candidates else {}
    checks["document_chunk_evidence_suggested"] = (
        bool(target_document)
        and bool(document_capture)
        and top_document.get("target_id") == target_document.get("id")
        and top_chunk.get("metadata", {}).get("document_id") == target_document.get("id")
        and "text_match" in set(top_chunk.get("metadata", {}).get("reason_codes", []))
    )
    cases.append(
        {
            "case_id": "screenshot_note_links_uploaded_document_chunk",
            "ok": checks["document_chunk_evidence_suggested"],
            "document_target_id": top_document.get("target_id"),
            "chunk_target_id": top_chunk.get("target_id"),
            "chunk_document_id": top_chunk.get("metadata", {}).get("document_id"),
            "chunk_score": top_chunk.get("score"),
        }
    )
    if not checks["document_chunk_evidence_suggested"]:
        failures.append(
            _failure(
                "screenshot_note_links_uploaded_document_chunk",
                "document_chunk_linking",
                "uploaded_document_chunk_not_suggested",
                item_ids=[str(target_document.get("id", ""))],
            )
        )

    unrelated_capture = _capture(
        client,
        headers,
        space_slug=space_slug,
        source_event_id="unrelated-capture",
        text="lowercase grocery reminder about bananas milk and receipts",
    )
    unrelated = _suggest(
        client,
        headers,
        space_slug=space_slug,
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
    cross_scope_target_slug = f"{space_slug}-external-target"
    cross_scope_query_slug = f"{space_slug}-external-query"
    cross_scope_fact = _remember_fact(
        client,
        headers,
        space_slug=cross_scope_target_slug,
        text=(
            "Project Zephyr private renewal memo names Casey as owner for the "
            "vendor risk exception."
        ),
        source_id="zephyr-private-renewal",
    )
    cross_scope_capture = _capture(
        client,
        headers,
        space_slug=cross_scope_query_slug,
        source_event_id="zephyr-cross-scope-capture",
        text=(
            "Project Zephyr private renewal memo names Casey as owner for the "
            "vendor risk exception."
        ),
    )
    cross_scope_suggestions = _suggest(
        client,
        headers,
        space_slug=cross_scope_query_slug,
        source_id=str(cross_scope_capture.get("id", "")),
        text="Project Zephyr private renewal Casey vendor risk exception",
    )
    cross_scope_fact_candidates = [
        item
        for item in cross_scope_suggestions.get("candidates", [])
        if item.get("target_type") == "fact"
    ]
    checks["cross_scope_fact_not_suggested"] = (
        bool(cross_scope_fact)
        and bool(cross_scope_capture)
        and not cross_scope_fact_candidates
    )
    cases.append(
        {
            "case_id": "cross_scope_exact_match_fact_not_suggested",
            "ok": checks["cross_scope_fact_not_suggested"],
            "candidate_count": len(cross_scope_suggestions.get("candidates", [])),
            "fact_candidate_count": len(cross_scope_fact_candidates),
        }
    )
    if not checks["cross_scope_fact_not_suggested"]:
        failures.append(
            _failure(
                "cross_scope_exact_match_fact_not_suggested",
                "scope_safety",
                "out_of_scope_fact_candidate_leaked",
                item_ids=[str(cross_scope_fact.get("id", ""))],
            )
        )
    return _report(checks=checks, cases=cases, failures=failures)


def _remember_fact(
    client: Any,
    headers: dict[str, str],
    *,
    space_slug: str,
    text: str,
    source_id: str,
    thread_external_ref: str = "quality-review",
) -> dict[str, object]:
    response = client.post(
        "/v1/facts",
        json={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "thread_external_ref": thread_external_ref,
            "text": text,
            "kind": "note",
            "source_refs": [{"source_type": "manual", "source_id": source_id}],
        },
        headers={**headers, "Idempotency-Key": f"{space_slug}-{source_id}"},
    )
    return _data(response) if response.status_code == 201 else {}


def _ingest_document(
    client: Any,
    headers: dict[str, str],
    *,
    space_slug: str,
    title: str,
    text: str,
    source_external_id: str,
) -> dict[str, object]:
    response = client.post(
        "/v1/documents",
        json={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "thread_external_ref": "document-review",
            "title": title,
            "text": text,
            "source_type": "document",
            "source_external_id": source_external_id,
            "classification": "internal",
        },
        headers={**headers, "Idempotency-Key": f"{space_slug}-{source_external_id}"},
    )
    return _data(response) if response.status_code == 201 else {}


def _capture(
    client: Any,
    headers: dict[str, str],
    *,
    space_slug: str,
    source_event_id: str,
    text: str,
    thread_external_ref: str | None = None,
) -> dict[str, object]:
    response = client.post(
        "/v1/captures",
        json={
            "space_slug": space_slug,
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
    space_slug: str,
    source_id: str,
    text: str,
    thread_external_ref: str | None = None,
) -> dict[str, object]:
    response = client.post(
        "/v1/link-suggestions",
        json={
            "space_slug": space_slug,
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


def _list_anchors(client: Any, headers: dict[str, str], *, space_slug: str) -> list[dict[str, Any]]:
    response = client.get(
        "/v1/anchors",
        params={
            "space_slug": space_slug,
            "memory_scope_external_ref": "default",
            "limit": 100,
        },
        headers=headers,
    )
    payload = response.json() if response.status_code == 200 else {}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, list) else []


def _anchor_has_review_evidence(anchor: object) -> bool:
    if not isinstance(anchor, dict):
        return False
    evidence_refs = anchor.get("evidence_refs")
    return (
        anchor.get("confidence") in {"low", "medium", "high"}
        and bool(anchor.get("observed_at"))
        and isinstance(evidence_refs, list)
        and any(
            isinstance(ref, dict)
            and ref.get("source_type") == "capture"
            and bool(ref.get("source_id"))
            for ref in evidence_refs
        )
    )


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


def _high_impact_relation_policy_case() -> dict[str, object]:
    weak_supersedes = _policy_candidate(
        target_id="policy-old-fact",
        reason_codes=("text_match",),
        relation_type="supersedes",
    )
    explicit_supersedes = _policy_candidate(
        target_id="policy-old-fact",
        reason_codes=("temporal_intent_match",),
        relation_type="supersedes",
    )
    weak_duplicates = _policy_candidate(
        target_id="policy-duplicate-fact",
        reason_codes=("text_match",),
        relation_type="duplicates",
    )
    explicit_duplicates = _policy_candidate(
        target_id="policy-duplicate-fact",
        reason_codes=("exact_duplicate",),
        relation_type="duplicates",
    )

    weak_result = apply_context_link_policy((weak_supersedes,), limit=8, persist=True)
    explicit_result = apply_context_link_policy((explicit_supersedes,), limit=8, persist=True)
    weak_duplicate_result = apply_context_link_policy((weak_duplicates,), limit=8, persist=True)
    explicit_duplicate_result = apply_context_link_policy(
        (explicit_duplicates,),
        limit=8,
        persist=True,
    )
    explicit_candidate = explicit_result.candidates[0] if explicit_result.candidates else None
    explicit_metadata = explicit_candidate.metadata if explicit_candidate else {}
    explicit_duplicate_candidate = (
        explicit_duplicate_result.candidates[0]
        if explicit_duplicate_result.candidates
        else None
    )
    explicit_duplicate_metadata = (
        explicit_duplicate_candidate.metadata if explicit_duplicate_candidate else {}
    )
    ok = (
        weak_result.candidates == ()
        and weak_result.diagnostics.get("link_policy_denied_reason_counts")
        == {"high_impact_relation_requires_explicit_signal": 1}
        and weak_duplicate_result.candidates == ()
        and weak_duplicate_result.diagnostics.get("link_policy_denied_reason_counts")
        == {"high_impact_relation_requires_explicit_signal": 1}
        and explicit_candidate is not None
        and explicit_metadata.get("policy_relation_type") == "supersedes"
        and explicit_metadata.get("review_gate") == "required"
        and explicit_metadata.get("auto_approve_eligible") is False
        and explicit_duplicate_candidate is not None
        and explicit_duplicate_metadata.get("policy_relation_type") == "duplicates"
        and explicit_duplicate_metadata.get("review_gate") == "required"
        and explicit_duplicate_metadata.get("auto_approve_eligible") is False
    )
    return {
        "case_id": "high_impact_relation_requires_explicit_signal",
        "ok": ok,
        "weak_denied_reason_counts": weak_result.diagnostics.get(
            "link_policy_denied_reason_counts"
        ),
        "weak_duplicate_denied_reason_counts": weak_duplicate_result.diagnostics.get(
            "link_policy_denied_reason_counts"
        ),
        "explicit_policy_relation_type": explicit_metadata.get("policy_relation_type"),
        "explicit_duplicate_policy_relation_type": explicit_duplicate_metadata.get(
            "policy_relation_type"
        ),
        "explicit_auto_approve_eligible": explicit_metadata.get("auto_approve_eligible"),
        "explicit_duplicate_auto_approve_eligible": explicit_duplicate_metadata.get(
            "auto_approve_eligible"
        ),
    }


def _policy_candidate(
    *,
    target_id: str,
    reason_codes: tuple[str, ...],
    relation_type: str,
    score: float = 96.0,
    metadata: dict[str, object] | None = None,
) -> ContextLinkCandidate:
    return ContextLinkCandidate(
        target_type="fact",
        target_id=target_id,
        label="policy fact",
        preview="policy preview",
        score=score,
        tier="likely",
        reasons=("policy signal",),
        metadata={
            "reason_codes": list(reason_codes),
            "relation_type": relation_type,
            "matched_terms": [],
            **(metadata or {}),
        },
    )


def _weak_overlap_policy_case() -> dict[str, object]:
    weak_related = _policy_candidate(
        target_id="policy-weak-overlap",
        reason_codes=("text_match",),
        relation_type="related_to",
        score=39.0,
    )
    result = apply_context_link_policy((weak_related,), limit=8, persist=True)
    denied_reason_counts = result.diagnostics.get("link_policy_denied_reason_counts")
    ok = (
        result.candidates == ()
        and denied_reason_counts == {"score_below_review_threshold": 1}
        and result.diagnostics.get("link_policy_denied_count") == 1
        and result.diagnostics.get("link_policy_candidates_returned") == 0
    )
    return {
        "case_id": "weak_overlap_below_review_threshold_denied",
        "ok": ok,
        "denied_reason_counts": denied_reason_counts,
        "candidate_count": len(result.candidates),
        "denied_count": result.diagnostics.get("link_policy_denied_count"),
    }


def _relation_specific_policy_cases() -> tuple[dict[str, object], dict[str, object]]:
    weak_evidence = _policy_candidate(
        target_id="policy-weak-evidence",
        reason_codes=("temporal_intent_match",),
        relation_type="evidence_of",
        score=82.0,
    )
    sourced_evidence = _policy_candidate(
        target_id="policy-sourced-evidence",
        reason_codes=("temporal_intent_match",),
        relation_type="evidence_of",
        score=82.0,
        metadata={
            "evidence_source_ref_count": 1,
            "evidence_modalities": ["image"],
            "evidence_has_bbox_ref": True,
        },
    )
    evidence_result = apply_context_link_policy(
        (weak_evidence, sourced_evidence),
        limit=8,
        persist=True,
    )
    sourced_evidence_candidate = (
        evidence_result.candidates[0] if evidence_result.candidates else None
    )
    sourced_evidence_metadata = (
        sourced_evidence_candidate.metadata if sourced_evidence_candidate else {}
    )

    weak_mention = _policy_candidate(
        target_id="policy-weak-mention",
        reason_codes=("temporal_intent_match",),
        relation_type="mentions",
        score=82.0,
    )
    entity_mention = _policy_candidate(
        target_id="policy-entity-mention",
        reason_codes=("organization_reference",),
        relation_type="mentions",
        score=82.0,
    )
    mention_result = apply_context_link_policy(
        (weak_mention, entity_mention),
        limit=8,
        persist=True,
    )
    entity_mention_candidate = mention_result.candidates[0] if mention_result.candidates else None
    entity_mention_metadata = entity_mention_candidate.metadata if entity_mention_candidate else {}

    return (
        {
            "case_id": "evidence_relation_requires_source_signal",
            "ok": (
                evidence_result.diagnostics.get("link_policy_denied_reason_counts")
                == {"evidence_relation_requires_source_signal": 1}
                and sourced_evidence_candidate is not None
                and sourced_evidence_metadata.get("policy_relation_type") == "evidence_of"
                and sourced_evidence_metadata.get("review_gate") == "required"
                and sourced_evidence_metadata.get("auto_approve_eligible") is False
            ),
            "denied_reason_counts": evidence_result.diagnostics.get(
                "link_policy_denied_reason_counts"
            ),
            "accepted_relation_type": sourced_evidence_metadata.get("policy_relation_type"),
            "accepted_auto_approve_eligible": sourced_evidence_metadata.get(
                "auto_approve_eligible"
            ),
        },
        {
            "case_id": "mentions_relation_requires_entity_signal",
            "ok": (
                mention_result.diagnostics.get("link_policy_denied_reason_counts")
                == {"mentions_relation_requires_entity_signal": 1}
                and entity_mention_candidate is not None
                and entity_mention_metadata.get("policy_relation_type") == "mentions"
                and entity_mention_metadata.get("review_gate") == "required"
                and entity_mention_metadata.get("auto_approve_eligible") is False
            ),
            "denied_reason_counts": mention_result.diagnostics.get(
                "link_policy_denied_reason_counts"
            ),
            "accepted_relation_type": entity_mention_metadata.get("policy_relation_type"),
            "accepted_auto_approve_eligible": entity_mention_metadata.get(
                "auto_approve_eligible"
            ),
        },
    )


def _report(
    *,
    checks: dict[str, bool],
    cases: list[dict[str, object]],
    failures: list[dict[str, object]],
) -> dict[str, object]:
    required_case_metrics = _required_case_metrics(cases)
    metrics = {
        **required_case_metrics,
        "case_count": len(cases),
        "ranking_accuracy": 1.0 if checks.get("top_fact_beats_distractor") else 0.0,
        "event_linking_accuracy": 1.0 if checks.get("event_call_beats_recent_chat") else 0.0,
        "temporal_intent_recall": (
            1.0 if checks.get("temporal_intent_links_recent_fact_without_text_match") else 0.0
        ),
        "document_chunk_linking_accuracy": (
            1.0 if checks.get("document_chunk_evidence_suggested") else 0.0
        ),
        "anchor_recall_rate": 1.0 if checks.get("person_and_project_anchors_suggested") else 0.0,
        "anchor_disambiguation_rate": (
            1.0 if checks.get("same_name_person_project_anchors_separate") else 0.0
        ),
        "anchor_review_evidence_rate": (
            1.0
            if checks.get("anchor_evidence_confidence_and_observed_at_exposed")
            else 0.0
        ),
        "high_impact_relation_policy_safety": (
            1.0 if checks.get("high_impact_relation_requires_explicit_signal") else 0.0
        ),
        "weak_overlap_policy_safety": (
            1.0 if checks.get("weak_overlap_below_review_threshold_denied") else 0.0
        ),
        "evidence_relation_policy_safety": (
            1.0 if checks.get("evidence_relation_requires_source_signal") else 0.0
        ),
        "mentions_relation_policy_safety": (
            1.0 if checks.get("mentions_relation_requires_entity_signal") else 0.0
        ),
        "review_approval_rate": 1.0 if checks.get("top_suggestion_approves_to_link") else 0.0,
        "false_positive_count": 0 if checks.get("unrelated_capture_has_no_candidates") else 1,
        "cross_scope_leak_count": 0 if checks.get("cross_scope_fact_not_suggested") else 1,
    }
    gates = {
        "case_count": metrics["case_count"] >= 5,
        "required_case_coverage_rate": metrics["required_case_coverage_rate"] == 1.0,
        "missing_required_case_count": metrics["missing_required_case_count"] == 0,
        "ranking_accuracy": metrics["ranking_accuracy"] == 1.0,
        "event_linking_accuracy": metrics["event_linking_accuracy"] == 1.0,
        "temporal_intent_recall": metrics["temporal_intent_recall"] == 1.0,
        "document_chunk_linking_accuracy": metrics["document_chunk_linking_accuracy"] == 1.0,
        "anchor_recall_rate": metrics["anchor_recall_rate"] == 1.0,
        "anchor_disambiguation_rate": metrics["anchor_disambiguation_rate"] == 1.0,
        "anchor_review_evidence_rate": metrics["anchor_review_evidence_rate"] == 1.0,
        "high_impact_relation_policy_safety": (
            metrics["high_impact_relation_policy_safety"] == 1.0
        ),
        "weak_overlap_policy_safety": metrics["weak_overlap_policy_safety"] == 1.0,
        "evidence_relation_policy_safety": (
            metrics["evidence_relation_policy_safety"] == 1.0
        ),
        "mentions_relation_policy_safety": metrics["mentions_relation_policy_safety"] == 1.0,
        "review_approval_rate": metrics["review_approval_rate"] == 1.0,
        "false_positive_count": metrics["false_positive_count"] == 0,
        "cross_scope_leak_count": metrics["cross_scope_leak_count"] == 0,
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


def _required_case_metrics(cases: list[dict[str, object]]) -> dict[str, object]:
    case_ids = {str(case.get("case_id")) for case in cases}
    missing = tuple(
        case_id for case_id in SEMANTIC_LINKING_REQUIRED_CASE_IDS if case_id not in case_ids
    )
    present_count = len(SEMANTIC_LINKING_REQUIRED_CASE_IDS) - len(missing)
    return {
        "required_case_count": len(SEMANTIC_LINKING_REQUIRED_CASE_IDS),
        "required_cases_present": present_count,
        "missing_required_case_count": len(missing),
        "missing_required_cases": list(missing),
        "required_case_coverage_rate": _ratio(
            present_count,
            len(SEMANTIC_LINKING_REQUIRED_CASE_IDS),
        ),
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

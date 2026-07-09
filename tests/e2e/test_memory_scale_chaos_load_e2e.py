from __future__ import annotations

import asyncio
import json
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from infinity_context_adapters.postgres.models import MemoryOutboxRow
from infinity_context_adapters.postgres.unit_of_work import build_async_engine
from infinity_context_server_harness import run_infinity_context_server
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MAX_SCALE_P95_REQUEST_MS = 3_000.0
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ReliabilityProbe:
    client: httpx.Client
    timings_ms: list[float] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    def request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        started = time.perf_counter()
        response = self.client.request(
            method,
            path,
            json=json_body,
            params=params,
            headers=headers,
        )
        self.timings_ms.append((time.perf_counter() - started) * 1000)
        assert response.status_code == expected_status, response.text
        return response

    def check(self, name: str, value: bool) -> None:
        self.checks[name] = value

    def assert_effective(self, *, max_p95_ms: float = MAX_SCALE_P95_REQUEST_MS) -> None:
        assert self.checks, "reliability probe has no checks"
        failed = {name: value for name, value in self.checks.items() if not value}
        assert not failed, self.summary()
        assert self.p95_ms() < max_p95_ms, self.summary()

    def p95_ms(self) -> float:
        if not self.timings_ms:
            return 0.0
        ordered = sorted(self.timings_ms)
        index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
        return ordered[index]

    def summary(self) -> dict[str, Any]:
        return {
            "checks": self.checks,
            "request_count": len(self.timings_ms),
            "p50_ms": round(float(statistics.median(self.timings_ms)), 2)
            if self.timings_ms
            else 0.0,
            "p95_ms": round(self.p95_ms(), 2),
            "max_ms": round(max(self.timings_ms), 2) if self.timings_ms else 0.0,
        }


def test_scale_corpus_recall_isolation_update_delete_and_latency_e2e(
    tmp_path: Path,
) -> None:
    with (
        run_infinity_context_server(tmp_path, database_name="scale-corpus.db") as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        probe = ReliabilityProbe(client)
        marker = f"SCALE_LOAD_{time.time_ns()}"
        space_slug = "scale-load-e2e"
        memory_scopes = ("project-alpha", "project-beta", "project-gamma", "project-delta")
        alpha = memory_scopes[0]
        beta = memory_scopes[1]
        alpha_old = f"{marker}: ALPHA_CRITICAL_GATE uses old candidate cache invalidation."
        alpha_new = f"{marker}: ALPHA_CRITICAL_GATE uses append-only evidence snapshots."
        beta_only = f"{marker}: BETA_LEAK_SENTINEL must stay isolated in project beta."
        restricted_secret = f"{marker}: RESTRICTED_SCALE_SECRET must never enter context."
        title_only_marker = f"{marker}_TITLE_ONLY_RUNBOOK"

        alpha_fact = None
        for memory_scope in memory_scopes:
            for index in range(14):
                text = (
                    f"{marker}: {memory_scope} load fact {index} stores routine interview memory "
                    "with scoped retrieval and safe evidence rendering."
                )
                if memory_scope == alpha and index == 3:
                    text = alpha_old
                if memory_scope == beta and index == 5:
                    text = beta_only
                created = probe.request(
                    "POST",
                    "/v1/facts",
                    expected_status=201,
                    json_body=_fact_body(space_slug, memory_scope, text),
                    headers={"Idempotency-Key": f"{marker}:fact:{memory_scope}:{index}"},
                ).json()["data"]
                if text == alpha_old:
                    alpha_fact = created
        assert alpha_fact is not None

        relevant_doc = probe.request(
            "POST",
            "/v1/documents",
            expected_status=201,
            json_body=_document_body(
                space_slug,
                alpha,
                title=f"{title_only_marker} architecture runbook",
                text=(
                    "This document intentionally relies on the title for retrieval. "
                    "The body covers scale load reliability, source citations, and chunk packing."
                ),
                source_external_id=f"{marker}:alpha-title-runbook",
            ),
            headers={"Idempotency-Key": f"{marker}:doc:alpha:title-only"},
        ).json()["data"]
        restricted_doc = probe.request(
            "POST",
            "/v1/documents",
            expected_status=201,
            json_body=_document_body(
                space_slug,
                alpha,
                title=f"{marker} restricted runbook",
                text=restricted_secret,
                source_external_id=f"{marker}:alpha-restricted",
                classification="restricted",
            ),
            headers={"Idempotency-Key": f"{marker}:doc:alpha:restricted"},
        ).json()["data"]
        beta_doc_text = f"{marker}: BETA_DOCUMENT_SENTINEL should not leak into alpha context."
        probe.request(
            "POST",
            "/v1/documents",
            expected_status=201,
            json_body=_document_body(
                space_slug,
                beta,
                title=f"{marker} beta-only note",
                text=beta_doc_text,
                source_external_id=f"{marker}:beta-doc",
            ),
            headers={"Idempotency-Key": f"{marker}:doc:beta"},
        )

        alpha_context = _context(
            probe,
            space_slug=space_slug,
            memory_scope_ref=alpha,
            query=f"{marker} ALPHA_CRITICAL_GATE {title_only_marker}",
            token_budget=1400,
            max_facts=8,
            max_chunks=8,
        )
        dumped_alpha = _dump(alpha_context)
        chunk_source_ids = [
            ref["source_id"]
            for item in alpha_context["items"]
            for ref in item["source_refs"]
            if item["item_type"] == "chunk"
        ]
        probe.check("scale_recall_hits_target_fact", alpha_old in dumped_alpha)
        probe.check("scale_recall_hits_title_only_document", title_only_marker in dumped_alpha)
        probe.check(
            "scale_recall_keeps_source_citation",
            f"{marker}:alpha-title-runbook" in chunk_source_ids,
        )
        probe.check("scale_memory_scope_isolation_hides_beta_fact", beta_only not in dumped_alpha)
        probe.check(
            "scale_memory_scope_isolation_hides_beta_doc", beta_doc_text not in dumped_alpha
        )
        probe.check("scale_restricted_doc_hidden", restricted_secret not in dumped_alpha)

        updated = probe.request(
            "PATCH",
            f"/v1/facts/{alpha_fact['id']}",
            expected_status=200,
            json_body={
                "expected_version": alpha_fact["version"],
                "text": alpha_new,
                "reason": "scale e2e update under loaded corpus",
                "source_refs": [_source_ref(f"{marker}:alpha-update")],
            },
        ).json()["data"]
        stale = probe.request(
            "PATCH",
            f"/v1/facts/{alpha_fact['id']}",
            expected_status=409,
            json_body={
                "expected_version": alpha_fact["version"],
                "text": f"{marker}: stale writer should not win under load.",
                "reason": "scale e2e stale writer",
                "source_refs": [_source_ref(f"{marker}:alpha-stale")],
            },
        ).json()
        after_update = _context(
            probe,
            space_slug=space_slug,
            memory_scope_ref=alpha,
            query=f"{marker} ALPHA_CRITICAL_GATE append-only evidence snapshots",
            token_budget=1400,
            max_facts=8,
            max_chunks=4,
        )
        dumped_after_update = _dump(after_update)
        probe.check("scale_update_increments_version", updated["version"] == 2)
        probe.check("scale_stale_update_rejected", stale["error"]["code"] == "memory.conflict")
        probe.check("scale_updated_fact_visible", alpha_new in dumped_after_update)
        probe.check("scale_old_fact_hidden_after_update", alpha_old not in dumped_after_update)

        deleted_doc = probe.request(
            "DELETE",
            f"/v1/documents/{relevant_doc['id']}",
            expected_status=200,
        ).json()["data"]
        probe.request("DELETE", f"/v1/documents/{restricted_doc['id']}", expected_status=200)
        after_delete = _context(
            probe,
            space_slug=space_slug,
            memory_scope_ref=alpha,
            query=f"{title_only_marker} architecture runbook",
            token_budget=1400,
            max_facts=2,
            max_chunks=8,
        )
        probe.check("scale_delete_removes_document_chunks", deleted_doc["deleted_chunks"] >= 1)
        probe.check("scale_deleted_document_hidden", title_only_marker not in _dump(after_delete))

        packed_small = _context(
            probe,
            space_slug=space_slug,
            memory_scope_ref=alpha,
            query=f"{marker} load fact scoped retrieval safe evidence",
            token_budget=64,
            max_facts=100,
            max_chunks=100,
        )
        probe.check(
            "scale_tiny_budget_still_renders_guard",
            "Relevant memory evidence" in packed_small["rendered_text"],
        )
        probe.check(
            "scale_tiny_budget_reports_drops",
            packed_small["diagnostics"]["dropped_by_budget"] > 0,
        )

        metrics = probe.request(
            "GET",
            "/v1/diagnostics/metrics",
            expected_status=200,
        ).json()["data"]
        probe.check(
            "scale_metrics_record_context_requests", metrics["context"]["request_count"] >= 4
        )
        probe.assert_effective()


def test_load_concurrent_idempotent_writes_and_optimistic_locking_e2e(
    tmp_path: Path,
) -> None:
    with run_infinity_context_server(tmp_path, database_name="concurrent-load.db") as server:
        marker = f"CONCURRENT_LOAD_{time.time_ns()}"
        space_slug = "concurrent-load-e2e"
        memory_scope_ref = "project-concurrency"
        text = f"{marker}: duplicate writers must converge to one current fact."
        idempotency_key = f"{marker}:shared-idempotency"

        def create_duplicate(_: int) -> tuple[int, dict[str, Any]]:
            with httpx.Client(
                base_url=server.base_url,
                headers={"Authorization": f"Bearer {server.token}"},
                timeout=30,
            ) as client:
                response = client.post(
                    "/v1/facts",
                    json=_fact_body(space_slug, memory_scope_ref, text),
                    headers={"Idempotency-Key": idempotency_key},
                )
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=8) as pool:
            create_results = [
                future.result()
                for future in as_completed(
                    pool.submit(create_duplicate, index) for index in range(16)
                )
            ]

        statuses = [status for status, _body in create_results]
        created_ids = {
            body["data"]["id"]
            for status, body in create_results
            if status in {200, 201} and "data" in body
        }
        assert set(statuses) <= {200, 201}, create_results
        assert len(created_ids) == 1, create_results
        fact_id = next(iter(created_ids))

        with httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client:
            current = client.get(f"/v1/facts/{fact_id}")
            assert current.status_code == 200, current.text
            current_data = current.json()["data"]
        expected_version = current_data["version"]
        candidate_texts = (
            f"{marker}: writer A won the optimistic lock.",
            f"{marker}: writer B won the optimistic lock.",
        )

        def update_candidate(candidate_text: str) -> tuple[int, dict[str, Any]]:
            with httpx.Client(
                base_url=server.base_url,
                headers={"Authorization": f"Bearer {server.token}"},
                timeout=30,
            ) as client:
                response = client.patch(
                    f"/v1/facts/{fact_id}",
                    json={
                        "expected_version": expected_version,
                        "text": candidate_text,
                        "reason": "concurrent optimistic lock e2e",
                        "source_refs": [_source_ref(f"{marker}:{candidate_text[-24:]}")],
                    },
                )
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            update_results = [
                future.result()
                for future in as_completed(
                    pool.submit(update_candidate, candidate_text)
                    for candidate_text in candidate_texts
                )
            ]

        update_statuses = [status for status, _body in update_results]
        assert update_statuses.count(200) == 1, update_results
        assert update_statuses.count(409) == 1, update_results
        winning_text = next(
            body["data"]["text"] for status, body in update_results if status == 200
        )
        losing_text = next(text for text in candidate_texts if text != winning_text)

        with httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client:
            probe = ReliabilityProbe(client)
            context = _context(
                probe,
                space_slug=space_slug,
                memory_scope_ref=memory_scope_ref,
                query=f"{marker} optimistic lock",
                token_budget=800,
                max_facts=5,
                max_chunks=0,
            )
            dumped = _dump(context)
            probe.check("concurrent_idempotency_has_single_fact", len(created_ids) == 1)
            probe.check("concurrent_context_shows_winner", winning_text in dumped)
            probe.check("concurrent_context_hides_original", text not in dumped)
            probe.check("concurrent_context_hides_loser", losing_text not in dumped)
            probe.assert_effective()


def test_server_restart_preserves_memory_and_idempotency_filters_e2e(
    tmp_path: Path,
) -> None:
    database_name = "server-restart-continuity.db"
    marker = f"SERVER_RESTART_E2E_{time.time_ns()}"
    space_slug = "server-restart-e2e"
    memory_scope_ref = "project-server-restart"
    stable_text = f"{marker}: RESTART_STABLE_FACT remains durable across process restart."
    old_text = f"{marker}: RESTART_UPDATE_TARGET uses stale pre-restart routing."
    new_text = f"{marker}: RESTART_UPDATE_TARGET uses current post-restart routing."
    deleted_text = f"{marker}: RESTART_DELETE_TARGET must not resurrect after restart."
    restricted_text = f"{marker}: RESTART_RESTRICTED_SECRET must never enter context."
    doc_text = f"{marker}: RESTART_DOCUMENT_SENTINEL survives process restart as canonical chunk."
    idempotency_key = f"{marker}:stable-fact-idempotency"

    with (
        run_infinity_context_server(tmp_path, database_name=database_name) as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        setup_probe = ReliabilityProbe(client)
        stable_fact = setup_probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body(space_slug, memory_scope_ref, stable_text),
            headers={"Idempotency-Key": idempotency_key},
        ).json()["data"]
        update_fact = setup_probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body(space_slug, memory_scope_ref, old_text),
            headers={"Idempotency-Key": f"{marker}:update-target"},
        ).json()["data"]
        updated_fact = setup_probe.request(
            "PATCH",
            f"/v1/facts/{update_fact['id']}",
            expected_status=200,
            json_body={
                "expected_version": update_fact["version"],
                "text": new_text,
                "reason": "server restart continuity e2e",
                "source_refs": [_source_ref(f"{marker}:restart-update")],
            },
        ).json()["data"]
        deleted_fact = setup_probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body(space_slug, memory_scope_ref, deleted_text),
            headers={"Idempotency-Key": f"{marker}:delete-target"},
        ).json()["data"]
        setup_probe.request(
            "DELETE",
            f"/v1/facts/{deleted_fact['id']}",
            expected_status=200,
        )
        setup_probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body(
                space_slug,
                memory_scope_ref,
                restricted_text,
                classification="restricted",
            ),
            headers={"Idempotency-Key": f"{marker}:restricted"},
        )
        setup_probe.request(
            "POST",
            "/v1/documents",
            expected_status=201,
            json_body=_document_body(
                space_slug,
                memory_scope_ref,
                title=f"{marker} restart continuity runbook",
                text=doc_text,
                source_external_id=f"{marker}:restart-doc",
            ),
            headers={"Idempotency-Key": f"{marker}:restart-doc"},
        )
        before_restart = _context(
            setup_probe,
            space_slug=space_slug,
            memory_scope_ref=memory_scope_ref,
            query=f"{marker} RESTART_STABLE_FACT RESTART_UPDATE_TARGET",
            token_budget=1200,
            max_facts=8,
            max_chunks=4,
        )
        setup_dump = _dump(before_restart)
        setup_probe.check("restart_setup_stable_visible", stable_text in setup_dump)
        setup_probe.check("restart_setup_updated_visible", new_text in setup_dump)
        setup_probe.check("restart_setup_old_hidden", old_text not in setup_dump)
        setup_probe.assert_effective(max_p95_ms=3_500.0)

    with (
        run_infinity_context_server(tmp_path, database_name=database_name) as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        probe = ReliabilityProbe(client)
        health = probe.request("GET", "/v1/health", expected_status=200).json()
        duplicate_retry = probe.request(
            "POST",
            "/v1/facts",
            expected_status=200,
            json_body=_fact_body(space_slug, memory_scope_ref, stable_text),
            headers={"Idempotency-Key": idempotency_key},
        ).json()["data"]
        restarted_context = _context(
            probe,
            space_slug=space_slug,
            memory_scope_ref=memory_scope_ref,
            query=(
                f"{marker} RESTART_STABLE_FACT RESTART_UPDATE_TARGET "
                "RESTART_DOCUMENT_SENTINEL RESTART_DELETE_TARGET RESTART_RESTRICTED_SECRET"
            ),
            token_budget=1600,
            max_facts=10,
            max_chunks=6,
        )
        metrics = probe.request(
            "GET",
            "/v1/diagnostics/metrics",
            expected_status=200,
        ).json()["data"]
        restarted_dump = _dump({"context": restarted_context, "metrics": metrics})

        probe.check("restart_health_ok", health["status"] == "ok")
        probe.check(
            "restart_idempotency_retry_same_fact",
            duplicate_retry["id"] == stable_fact["id"],
        )
        probe.check("restart_idempotency_retry_no_new_version", duplicate_retry["version"] == 1)
        probe.check("restart_updated_fact_version_persisted", updated_fact["version"] == 2)
        probe.check("restart_stable_fact_visible", stable_text in restarted_dump)
        probe.check("restart_updated_fact_visible", new_text in restarted_dump)
        probe.check("restart_document_chunk_visible", doc_text in restarted_dump)
        probe.check("restart_old_fact_hidden", old_text not in restarted_dump)
        probe.check("restart_deleted_fact_hidden", deleted_text not in restarted_dump)
        probe.check("restart_restricted_fact_hidden", restricted_text not in restarted_dump)
        probe.check("restart_no_dead_outbox", metrics["outbox"]["dead"] == 0)
        probe.check(
            "restart_context_metrics_record_new_process",
            metrics["context"]["request_count"] >= 1,
        )
        probe.assert_effective(max_p95_ms=3_500.0)


def test_chaos_invalid_requests_restricted_data_and_recovery_e2e(tmp_path: Path) -> None:
    with (
        run_infinity_context_server(tmp_path, database_name="chaos-recovery.db") as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        probe = ReliabilityProbe(client)
        marker = f"CHAOS_RECOVERY_{time.time_ns()}"
        space_slug = "chaos-recovery-e2e"
        memory_scope_ref = "project-chaos"
        secret_text = f"{marker}: CHAOS_SECRET_PAYLOAD should stay out of context."
        public_text = f"{marker}: RECOVERY_PUBLIC_FACT survives invalid request flood."

        wrong_token = httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": "Bearer wrong-token"},
            timeout=5,
        )
        try:
            for index in range(12):
                unauthorized = wrong_token.post(
                    "/v1/facts",
                    json=_fact_body(
                        space_slug, memory_scope_ref, f"{marker}: unauthorized {index}"
                    ),
                )
                assert unauthorized.status_code == 401, unauthorized.text
                invalid_fact = probe.request(
                    "POST",
                    "/v1/facts",
                    expected_status=400,
                    json_body={
                        "space_slug": space_slug,
                        "memory_scope_external_ref": memory_scope_ref,
                        "text": "",
                        "kind": "note",
                        "source_refs": [],
                    },
                )
                assert "error" in invalid_fact.text or "detail" in invalid_fact.text
                probe.request(
                    "PATCH",
                    f"/v1/facts/missing-{marker}-{index}",
                    expected_status=404,
                    json_body={
                        "expected_version": 1,
                        "text": f"{marker}: missing update",
                        "reason": "chaos missing fact",
                        "source_refs": [_source_ref(f"{marker}:missing:{index}")],
                    },
                )
                probe.request(
                    "POST",
                    "/v1/context",
                    expected_status=400,
                    json_body={
                        "space_slug": space_slug,
                        "memory_scope_external_ref": memory_scope_ref,
                        "query": "",
                    },
                )
        finally:
            wrong_token.close()

        restricted_fact = probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body(
                space_slug,
                memory_scope_ref,
                secret_text,
                classification="restricted",
            ),
            headers={"Idempotency-Key": f"{marker}:restricted-fact"},
        ).json()["data"]
        public_fact = probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body(space_slug, memory_scope_ref, public_text),
            headers={"Idempotency-Key": f"{marker}:public-fact"},
        ).json()["data"]
        health = probe.request("GET", "/v1/health", expected_status=200).json()
        context = _context(
            probe,
            space_slug=space_slug,
            memory_scope_ref=memory_scope_ref,
            query=f"{marker} RECOVERY_PUBLIC_FACT CHAOS_SECRET_PAYLOAD",
            token_budget=900,
            max_facts=8,
            max_chunks=4,
        )
        dumped = _dump(context)
        memory_scope_metrics = probe.request(
            "GET",
            f"/v1/diagnostics/memory-scope/{public_fact['memory_scope_id']}",
            expected_status=200,
        ).json()["data"]
        operational_metrics = probe.request(
            "GET",
            "/v1/diagnostics/metrics",
            expected_status=200,
        ).json()["data"]
        safe_diagnostics_dump = _dump(
            {"memory_scope": memory_scope_metrics, "metrics": operational_metrics}
        )

        probe.check("chaos_health_recovers_after_invalid_flood", health["status"] == "ok")
        probe.check("chaos_public_fact_visible_after_flood", public_text in dumped)
        probe.check("chaos_restricted_fact_hidden", secret_text not in dumped)
        probe.check(
            "chaos_restricted_memory_scope_preview_redacted",
            secret_text not in safe_diagnostics_dump,
        )
        probe.check(
            "chaos_metrics_do_not_leak_raw_secret",
            "CHAOS_SECRET_PAYLOAD" not in safe_diagnostics_dump,
        )
        probe.check(
            "chaos_memory_scope_counts_include_active_public_and_restricted",
            memory_scope_metrics["facts"]["active"] >= 2,
        )
        probe.check(
            "chaos_restricted_fact_created_for_audit", restricted_fact["status"] == "active"
        )
        probe.assert_effective(max_p95_ms=3_500.0)


def test_backpressure_keeps_reads_and_cleanup_available_e2e(tmp_path: Path) -> None:
    with (
        run_infinity_context_server(
            tmp_path,
            database_name="backpressure-e2e.db",
            extra_env={"MEMORY_OUTBOX_BACKPRESSURE_PENDING_THRESHOLD": "3"},
        ) as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        probe = ReliabilityProbe(client)
        marker = f"BACKPRESSURE_E2E_{time.time_ns()}"
        space_slug = "backpressure-e2e"
        memory_scope_ref = "project-backpressure"
        fact_text = f"{marker}: BACKPRESSURE_READ_SENTINEL remains readable during ingest pressure."
        doc_text = f"{marker}: BACKPRESSURE_DELETE_DOC can be deleted while ingest is throttled."
        blocked_doc_text = f"{marker}: BACKPRESSURE_BLOCKED_DOC must not be accepted."

        fact = probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body(space_slug, memory_scope_ref, fact_text),
            headers={"Idempotency-Key": f"{marker}:fact"},
        ).json()["data"]
        document = probe.request(
            "POST",
            "/v1/documents",
            expected_status=201,
            json_body=_document_body(
                space_slug,
                memory_scope_ref,
                title=f"{marker} cleanup document",
                text=doc_text,
                source_external_id=f"{marker}:cleanup-doc",
            ),
            headers={"Idempotency-Key": f"{marker}:doc"},
        ).json()["data"]
        asyncio.run(
            _insert_pending_outbox(
                server.env["MEMORY_DATABASE_URL"],
                aggregate_id=f"{marker}:synthetic-backlog",
            )
        )

        blocked = probe.request(
            "POST",
            "/v1/documents",
            expected_status=429,
            json_body=_document_body(
                space_slug,
                memory_scope_ref,
                title=f"{marker} blocked document",
                text=blocked_doc_text,
                source_external_id=f"{marker}:blocked-doc",
            ),
            headers={"Idempotency-Key": f"{marker}:blocked-doc"},
        ).json()
        context = _context(
            probe,
            space_slug=space_slug,
            memory_scope_ref=memory_scope_ref,
            query=f"{marker} BACKPRESSURE_READ_SENTINEL BACKPRESSURE_BLOCKED_DOC",
            token_budget=1000,
            max_facts=6,
            max_chunks=4,
        )
        deleted_document = probe.request(
            "DELETE",
            f"/v1/documents/{document['id']}",
            expected_status=200,
        ).json()["data"]
        forgotten_fact = probe.request(
            "DELETE",
            f"/v1/facts/{fact['id']}",
            expected_status=200,
        ).json()["data"]
        diagnostics = probe.request(
            "GET",
            "/v1/diagnostics/outbox",
            expected_status=200,
        ).json()["data"]
        dumped_context = _dump(context)

        probe.check(
            "backpressure_blocks_ingest_with_retryable_429",
            blocked["error"]["retryable"],
        )
        probe.check(
            "backpressure_reports_safe_pending_details",
            blocked["error"]["code"] == "memory.backpressure",
        )
        probe.check("backpressure_read_path_stays_available", fact_text in dumped_context)
        probe.check("backpressure_blocked_doc_not_visible", blocked_doc_text not in dumped_context)
        probe.check(
            "backpressure_document_delete_bypasses_throttle",
            deleted_document["status"] == "deleted",
        )
        probe.check(
            "backpressure_forget_bypasses_throttle",
            forgotten_fact["status"] == "deleted",
        )
        probe.check(
            "backpressure_diagnostics_show_active_backlog",
            diagnostics["counts"].get("pending", 0) >= 3,
        )
        probe.assert_effective(max_p95_ms=3_500.0)


def test_outbox_lag_alert_and_worker_drain_recovery_e2e(tmp_path: Path) -> None:
    with (
        run_infinity_context_server(tmp_path, database_name="outbox-lag-e2e.db") as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        probe = ReliabilityProbe(client)
        marker = f"OUTBOX_LAG_E2E_{time.time_ns()}"
        aggregate_id = f"{marker}:lagged-projection"
        raw_payload_marker = f"RAW_LAGGED_OUTBOX_PAYLOAD_{time.time_ns()}"
        recovery_fact_text = f"{marker}: OUTBOX_LAG_RECOVERY_SENTINEL stays queryable."
        asyncio.run(
            _insert_lagged_pending_outbox(
                server.env["MEMORY_DATABASE_URL"],
                aggregate_id=aggregate_id,
                raw_payload_marker=raw_payload_marker,
            )
        )

        lagged_diagnostics = probe.request(
            "GET",
            "/v1/diagnostics/outbox",
            expected_status=200,
        ).json()["data"]
        lagged_metrics = probe.request(
            "GET",
            "/v1/diagnostics/metrics",
            expected_status=200,
        ).json()["data"]
        created = probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body("outbox-lag-e2e", "project-outbox-lag", recovery_fact_text),
            headers={"Idempotency-Key": f"{marker}:recovery-fact"},
        ).json()["data"]
        context_during_lag = _context(
            probe,
            space_slug="outbox-lag-e2e",
            memory_scope_ref="project-outbox-lag",
            query=f"{marker} OUTBOX_LAG_RECOVERY_SENTINEL",
            token_budget=900,
            max_facts=4,
            max_chunks=0,
        )
        worker = subprocess.run(
            [
                sys.executable,
                "-m",
                "infinity_context_server.worker",
                "--once",
                "--limit",
                "10",
            ],
            cwd=PROJECT_ROOT,
            env=server.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        drained_diagnostics = probe.request(
            "GET",
            "/v1/diagnostics/outbox",
            expected_status=200,
        ).json()["data"]
        drained_metrics = probe.request(
            "GET",
            "/v1/diagnostics/metrics",
            expected_status=200,
        ).json()["data"]
        context_after_drain = _context(
            probe,
            space_slug="outbox-lag-e2e",
            memory_scope_ref="project-outbox-lag",
            query=f"{marker} OUTBOX_LAG_RECOVERY_SENTINEL",
            token_budget=900,
            max_facts=4,
            max_chunks=0,
        )
        safe_dump = _dump(
            {
                "lagged_diagnostics": lagged_diagnostics,
                "lagged_metrics": lagged_metrics,
                "drained_diagnostics": drained_diagnostics,
                "drained_metrics": drained_metrics,
                "worker_stdout": worker.stdout,
                "worker_stderr": worker.stderr,
            }
        )

        probe.check(
            "outbox_lag_metrics_detect_active_backlog",
            lagged_metrics["outbox"]["pending_active"] >= 1,
        )
        probe.check(
            "outbox_lag_oldest_active_lag_above_threshold",
            (lagged_metrics["outbox"]["oldest_active_lag_seconds"] or 0) > 600,
        )
        probe.check(
            "outbox_lag_alert_fires",
            any(
                alert["name"] == "outbox_pending_lag_seconds" for alert in lagged_metrics["alerts"]
            ),
        )
        probe.check(
            "outbox_lag_diagnostics_show_lagged_job",
            _outbox_item(lagged_diagnostics, aggregate_id)["status"] == "pending",
        )
        probe.check("outbox_lag_recovery_write_succeeds", created["text"] == recovery_fact_text)
        probe.check(
            "outbox_lag_context_available_during_lag",
            recovery_fact_text in _dump(context_during_lag),
        )
        probe.check("outbox_lag_worker_cli_exits_zero", worker.returncode == 0)
        probe.check(
            "outbox_lag_worker_processed_jobs",
            "processed" in worker.stdout and "2" in worker.stdout,
        )
        probe.check(
            "outbox_lag_worker_drains_active_backlog",
            drained_metrics["outbox"]["pending_active"] == 0,
        )
        probe.check(
            "outbox_lag_alert_clears_after_drain",
            not any(
                alert["name"] == "outbox_pending_lag_seconds" for alert in drained_metrics["alerts"]
            ),
        )
        probe.check(
            "outbox_lag_context_available_after_drain",
            recovery_fact_text in _dump(context_after_drain),
        )
        probe.check(
            "outbox_lag_diagnostics_do_not_leak_payload",
            raw_payload_marker not in safe_dump and "payload_json" not in safe_dump,
        )
        probe.assert_effective(max_p95_ms=3_500.0)


def test_worker_cli_recovers_expired_running_outbox_job_e2e(tmp_path: Path) -> None:
    with (
        run_infinity_context_server(tmp_path, database_name="worker-lease-e2e.db") as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        probe = ReliabilityProbe(client)
        marker = f"WORKER_LEASE_E2E_{time.time_ns()}"
        aggregate_id = f"{marker}:expired-running-fact"
        asyncio.run(
            _insert_expired_running_outbox(
                server.env["MEMORY_DATABASE_URL"],
                aggregate_id=aggregate_id,
            )
        )

        before = probe.request(
            "GET",
            "/v1/diagnostics/outbox",
            expected_status=200,
        ).json()["data"]
        worker = subprocess.run(
            [
                sys.executable,
                "-m",
                "infinity_context_server.worker",
                "--once",
                "--limit",
                "10",
            ],
            cwd=PROJECT_ROOT,
            env=server.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        after = probe.request(
            "GET",
            "/v1/diagnostics/outbox",
            expected_status=200,
        ).json()["data"]
        health = probe.request("GET", "/v1/health", expected_status=200).json()
        row = _outbox_item(after, aggregate_id)

        probe.check("worker_lease_before_has_running_job", before["counts"].get("running", 0) == 1)
        probe.check("worker_lease_cli_exits_zero", worker.returncode == 0)
        probe.check(
            "worker_lease_cli_processed_job",
            "processed" in worker.stdout and "1" in worker.stdout,
        )
        probe.check("worker_lease_recovered_job_done", row["status"] == "done")
        probe.check("worker_lease_incremented_attempt", row["attempt_count"] == 1)
        probe.check("worker_lease_cleared_safe_error", row["last_safe_error"] is None)
        probe.check(
            "worker_lease_cleared_diagnostic_code",
            row["last_safe_diagnostic_code"] is None,
        )
        probe.check("worker_lease_no_active_or_dead_jobs", after["counts"] == {"done": 1})
        probe.check("worker_lease_server_stays_healthy", health["status"] == "ok")
        probe.assert_effective(max_p95_ms=3_500.0)


def test_worker_cli_dead_poison_job_keeps_service_safe_e2e(tmp_path: Path) -> None:
    with (
        run_infinity_context_server(tmp_path, database_name="worker-poison-e2e.db") as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        probe = ReliabilityProbe(client)
        marker = f"WORKER_POISON_E2E_{time.time_ns()}"
        aggregate_id = f"{marker}:poison-job"
        raw_payload_marker = f"RAW_POISON_E2E_PAYLOAD_{time.time_ns()}"
        recovery_fact_text = (
            f"{marker}: POISON_RECOVERY_SENTINEL proves canonical memory still works."
        )
        asyncio.run(
            _insert_poison_outbox(
                server.env["MEMORY_DATABASE_URL"],
                aggregate_id=aggregate_id,
                raw_payload_marker=raw_payload_marker,
            )
        )

        worker = subprocess.run(
            [
                sys.executable,
                "-m",
                "infinity_context_server.worker",
                "--once",
                "--limit",
                "10",
            ],
            cwd=PROJECT_ROOT,
            env=server.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        diagnostics = probe.request(
            "GET",
            "/v1/diagnostics/outbox",
            expected_status=200,
        ).json()["data"]
        metrics = probe.request(
            "GET",
            "/v1/diagnostics/metrics",
            expected_status=200,
        ).json()["data"]
        doctor = subprocess.run(
            [sys.executable, "-m", "infinity_context_server.doctor"],
            cwd=PROJECT_ROOT,
            env=server.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        doctor_report = json.loads(doctor.stdout)
        created = probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body("worker-poison-e2e", "project-worker-poison", recovery_fact_text),
            headers={"Idempotency-Key": f"{marker}:recovery-fact"},
        ).json()["data"]
        context = _context(
            probe,
            space_slug="worker-poison-e2e",
            memory_scope_ref="project-worker-poison",
            query=f"{marker} POISON_RECOVERY_SENTINEL",
            token_budget=900,
            max_facts=4,
            max_chunks=0,
        )
        row = _outbox_item(diagnostics, aggregate_id)
        safe_dump = _dump(
            {
                "worker_stdout": worker.stdout,
                "worker_stderr": worker.stderr,
                "doctor_stdout": doctor.stdout,
                "doctor_stderr": doctor.stderr,
                "diagnostics": diagnostics,
                "metrics": metrics,
                "context": context,
            }
        )

        probe.check("worker_poison_cli_exits_zero", worker.returncode == 0)
        probe.check(
            "worker_poison_cli_processed_job",
            "processed" in worker.stdout and "1" in worker.stdout,
        )
        probe.check("worker_poison_job_marked_dead", row["status"] == "dead")
        probe.check("worker_poison_attempts_exhausted", row["attempt_count"] == 5)
        probe.check("worker_poison_safe_error_class_only", row["last_safe_error"] == "ValueError")
        probe.check(
            "worker_poison_safe_diagnostic_class_only",
            row["last_safe_diagnostic_code"] == "ValueError",
        )
        probe.check(
            "worker_poison_metrics_alerts_dead_job",
            any(alert["name"] == "outbox_dead_count" for alert in metrics["alerts"]),
        )
        probe.check("worker_poison_doctor_reports_degraded", doctor.returncode == 1)
        probe.check("worker_poison_doctor_counts_dead_job", doctor_report["outbox"]["dead"] == 1)
        probe.check(
            "worker_poison_diagnostics_do_not_leak_payload",
            raw_payload_marker not in safe_dump and "payload_json" not in safe_dump,
        )
        probe.check("worker_poison_recovery_write_succeeds", created["text"] == recovery_fact_text)
        probe.check("worker_poison_recovery_context_succeeds", recovery_fact_text in _dump(context))
        probe.assert_effective(max_p95_ms=3_500.0)


def test_admin_cli_replays_dead_outbox_and_recovers_doctor_e2e(tmp_path: Path) -> None:
    with (
        run_infinity_context_server(tmp_path, database_name="outbox-replay-e2e.db") as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        probe = ReliabilityProbe(client)
        marker = f"OUTBOX_REPLAY_E2E_{time.time_ns()}"
        aggregate_id = f"{marker}:replayable-dead-job"
        raw_payload_marker = f"RAW_REPLAY_E2E_PAYLOAD_{time.time_ns()}"
        recovery_fact_text = f"{marker}: REPLAY_RECOVERY_SENTINEL remains queryable."
        asyncio.run(
            _insert_replayable_dead_outbox(
                server.env["MEMORY_DATABASE_URL"],
                aggregate_id=aggregate_id,
                raw_payload_marker=raw_payload_marker,
            )
        )

        degraded_metrics = probe.request(
            "GET",
            "/v1/diagnostics/metrics",
            expected_status=200,
        ).json()["data"]
        degraded_doctor = subprocess.run(
            [sys.executable, "-m", "infinity_context_server.doctor"],
            cwd=PROJECT_ROOT,
            env=server.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        created = probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body("outbox-replay-e2e", "project-outbox-replay", recovery_fact_text),
            headers={"Idempotency-Key": f"{marker}:recovery-fact"},
        ).json()["data"]
        replay = subprocess.run(
            [
                sys.executable,
                "-m",
                "infinity_context_server.admin",
                "replay-outbox",
                "--status",
                "dead",
                "--limit",
                "10",
            ],
            cwd=PROJECT_ROOT,
            env=server.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        replay_report = json.loads(replay.stdout)
        replayed_diagnostics = probe.request(
            "GET",
            "/v1/diagnostics/outbox",
            expected_status=200,
        ).json()["data"]
        worker = subprocess.run(
            [
                sys.executable,
                "-m",
                "infinity_context_server.worker",
                "--once",
                "--limit",
                "10",
            ],
            cwd=PROJECT_ROOT,
            env=server.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        recovered_metrics = probe.request(
            "GET",
            "/v1/diagnostics/metrics",
            expected_status=200,
        ).json()["data"]
        recovered_doctor = subprocess.run(
            [sys.executable, "-m", "infinity_context_server.doctor"],
            cwd=PROJECT_ROOT,
            env=server.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        context = _context(
            probe,
            space_slug="outbox-replay-e2e",
            memory_scope_ref="project-outbox-replay",
            query=f"{marker} REPLAY_RECOVERY_SENTINEL",
            token_budget=900,
            max_facts=4,
            max_chunks=0,
        )
        safe_dump = _dump(
            {
                "degraded_metrics": degraded_metrics,
                "degraded_doctor": degraded_doctor.stdout,
                "replay_stdout": replay.stdout,
                "replay_stderr": replay.stderr,
                "replayed_diagnostics": replayed_diagnostics,
                "worker_stdout": worker.stdout,
                "worker_stderr": worker.stderr,
                "recovered_metrics": recovered_metrics,
                "recovered_doctor": recovered_doctor.stdout,
                "context": context,
            }
        )

        probe.check("outbox_replay_initial_dead_count", degraded_metrics["outbox"]["dead"] == 1)
        probe.check(
            "outbox_replay_initial_dead_alert",
            any(alert["name"] == "outbox_dead_count" for alert in degraded_metrics["alerts"]),
        )
        probe.check("outbox_replay_initial_doctor_degraded", degraded_doctor.returncode == 1)
        probe.check("outbox_replay_recovery_write_succeeds", created["text"] == recovery_fact_text)
        probe.check("outbox_replay_admin_cli_exits_zero", replay.returncode == 0)
        probe.check("outbox_replay_admin_replayed_one", replay_report["replayed"] == 1)
        probe.check(
            "outbox_replay_dead_job_returns_pending",
            _outbox_item(replayed_diagnostics, aggregate_id)["status"] == "pending",
        )
        probe.check("outbox_replay_worker_cli_exits_zero", worker.returncode == 0)
        probe.check(
            "outbox_replay_worker_processed_jobs",
            "processed" in worker.stdout and "2" in worker.stdout,
        )
        probe.check("outbox_replay_recovered_dead_count", recovered_metrics["outbox"]["dead"] == 0)
        probe.check(
            "outbox_replay_recovered_no_active_backlog",
            recovered_metrics["outbox"]["pending_active"] == 0,
        )
        probe.check("outbox_replay_recovered_doctor_ok", recovered_doctor.returncode == 0)
        probe.check("outbox_replay_recovery_context_succeeds", recovery_fact_text in _dump(context))
        probe.check(
            "outbox_replay_diagnostics_do_not_leak_payload",
            raw_payload_marker not in safe_dump and "payload_json" not in safe_dump,
        )
        probe.assert_effective(max_p95_ms=3_500.0)


def test_admin_cli_compacts_done_outbox_without_breaking_memory_e2e(tmp_path: Path) -> None:
    with (
        run_infinity_context_server(tmp_path, database_name="outbox-compaction-e2e.db") as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        probe = ReliabilityProbe(client)
        marker = f"OUTBOX_COMPACT_E2E_{time.time_ns()}"
        space_slug = "outbox-compaction-e2e"
        memory_scope_ref = "project-outbox-compaction"
        aggregate_id = f"{marker}:done-compaction-row"
        raw_payload_marker = f"RAW_COMPACT_E2E_PAYLOAD_{time.time_ns()}"
        fact_text = f"{marker}: COMPACTION_FACT_SENTINEL remains readable after maintenance."
        doc_text = f"{marker}: COMPACTION_DOCUMENT_SENTINEL remains chunk-readable."

        probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body(space_slug, memory_scope_ref, fact_text),
            headers={"Idempotency-Key": f"{marker}:fact"},
        )
        probe.request(
            "POST",
            "/v1/documents",
            expected_status=201,
            json_body=_document_body(
                space_slug,
                memory_scope_ref,
                title=f"{marker} compaction runbook",
                text=doc_text,
                source_external_id=f"{marker}:compaction-doc",
            ),
            headers={"Idempotency-Key": f"{marker}:doc"},
        )
        worker_before_compaction = subprocess.run(
            [
                sys.executable,
                "-m",
                "infinity_context_server.worker",
                "--once",
                "--limit",
                "50",
            ],
            cwd=PROJECT_ROOT,
            env=server.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        asyncio.run(
            _insert_done_outbox_with_raw_payload(
                server.env["MEMORY_DATABASE_URL"],
                aggregate_id=aggregate_id,
                raw_payload_marker=raw_payload_marker,
            )
        )
        before_payload = asyncio.run(
            _outbox_payload_by_aggregate_id(server.env["MEMORY_DATABASE_URL"], aggregate_id)
        )
        dry_run = subprocess.run(
            [
                sys.executable,
                "-m",
                "infinity_context_server.admin",
                "compact-outbox",
                "--older-than-seconds",
                "0",
                "--limit",
                "50",
                "--dry-run",
            ],
            cwd=PROJECT_ROOT,
            env=server.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        dry_run_report = json.loads(dry_run.stdout)
        after_dry_run_payload = asyncio.run(
            _outbox_payload_by_aggregate_id(server.env["MEMORY_DATABASE_URL"], aggregate_id)
        )
        compact = subprocess.run(
            [
                sys.executable,
                "-m",
                "infinity_context_server.admin",
                "compact-outbox",
                "--older-than-seconds",
                "0",
                "--limit",
                "50",
            ],
            cwd=PROJECT_ROOT,
            env=server.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        compact_report = json.loads(compact.stdout)
        compacted_payload = asyncio.run(
            _outbox_payload_by_aggregate_id(server.env["MEMORY_DATABASE_URL"], aggregate_id)
        )
        worker_after_compaction = subprocess.run(
            [
                sys.executable,
                "-m",
                "infinity_context_server.worker",
                "--once",
                "--limit",
                "50",
            ],
            cwd=PROJECT_ROOT,
            env=server.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        metrics = probe.request(
            "GET",
            "/v1/diagnostics/metrics",
            expected_status=200,
        ).json()["data"]
        context = _context(
            probe,
            space_slug=space_slug,
            memory_scope_ref=memory_scope_ref,
            query=f"{marker} COMPACTION_FACT_SENTINEL COMPACTION_DOCUMENT_SENTINEL",
            token_budget=1200,
            max_facts=4,
            max_chunks=4,
        )
        safe_dump = _dump(
            {
                "dry_run_stdout": dry_run.stdout,
                "dry_run_stderr": dry_run.stderr,
                "compact_stdout": compact.stdout,
                "compact_stderr": compact.stderr,
                "worker_before_stdout": worker_before_compaction.stdout,
                "worker_after_stdout": worker_after_compaction.stdout,
                "metrics": metrics,
                "context": context,
            }
        )

        probe.check(
            "outbox_compact_worker_initial_drain_ok",
            worker_before_compaction.returncode == 0,
        )
        probe.check(
            "outbox_compact_raw_payload_seeded",
            raw_payload_marker in _dump(before_payload),
        )
        probe.check("outbox_compact_dry_run_exits_zero", dry_run.returncode == 0)
        probe.check("outbox_compact_dry_run_reports_matches", dry_run_report["would_compact"] >= 1)
        probe.check(
            "outbox_compact_dry_run_does_not_mutate",
            raw_payload_marker in _dump(after_dry_run_payload),
        )
        probe.check("outbox_compact_actual_exits_zero", compact.returncode == 0)
        probe.check("outbox_compact_actual_compacts_rows", compact_report["compacted"] >= 1)
        probe.check(
            "outbox_compact_payload_marked_compacted",
            compacted_payload["compacted"] is True,
        )
        probe.check(
            "outbox_compact_preserves_safe_keys",
            compacted_payload["preserved"]["chunk_id"] == aggregate_id,
        )
        probe.check(
            "outbox_compact_redacts_raw_payload",
            raw_payload_marker not in _dump(compacted_payload)
            and raw_payload_marker not in safe_dump,
        )
        probe.check(
            "outbox_compact_worker_after_maintenance_ok",
            worker_after_compaction.returncode == 0,
        )
        probe.check("outbox_compact_no_active_backlog", metrics["outbox"]["pending_active"] == 0)
        probe.check("outbox_compact_no_dead_jobs", metrics["outbox"]["dead"] == 0)
        probe.check("outbox_compact_context_keeps_fact", fact_text in _dump(context))
        probe.check("outbox_compact_context_keeps_document_chunk", doc_text in _dump(context))
        probe.assert_effective(max_p95_ms=3_500.0)


def test_load_concurrent_document_idempotency_and_cleanup_e2e(tmp_path: Path) -> None:
    with run_infinity_context_server(tmp_path, database_name="concurrent-docs.db") as server:
        marker = f"CONCURRENT_DOC_{time.time_ns()}"
        space_slug = "concurrent-document-e2e"
        memory_scope_ref = "project-concurrent-docs"
        doc_text = (
            f"{marker}: CONCURRENT_DOCUMENT_SENTINEL should be stored once even when "
            "several agents upload the same runbook at the same time."
        )
        idempotency_key = f"{marker}:shared-document-idempotency"

        def create_document(index: int) -> tuple[int, dict[str, Any]]:
            with httpx.Client(
                base_url=server.base_url,
                headers={"Authorization": f"Bearer {server.token}"},
                timeout=30,
            ) as client:
                response = client.post(
                    "/v1/documents",
                    json=_document_body(
                        space_slug,
                        memory_scope_ref,
                        title=f"{marker} shared runbook",
                        text=doc_text,
                        source_external_id=f"{marker}:shared-runbook",
                    ),
                    headers={"Idempotency-Key": idempotency_key},
                )
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=5) as pool:
            create_results = [
                future.result()
                for future in as_completed(
                    pool.submit(create_document, index) for index in range(8)
                )
            ]

        statuses = [status for status, _body in create_results]
        document_ids = {
            body["data"]["id"]
            for status, body in create_results
            if status in {200, 201} and "data" in body
        }
        assert set(statuses) <= {200, 201}, create_results
        assert len(document_ids) == 1, create_results
        document_id = next(iter(document_ids))

        with httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client:
            probe = ReliabilityProbe(client)
            context = _context(
                probe,
                space_slug=space_slug,
                memory_scope_ref=memory_scope_ref,
                query=f"{marker} CONCURRENT_DOCUMENT_SENTINEL shared runbook",
                token_budget=1000,
                max_facts=0,
                max_chunks=8,
            )
            deleted = probe.request(
                "DELETE",
                f"/v1/documents/{document_id}",
                expected_status=200,
            ).json()["data"]
            after_delete = _context(
                probe,
                space_slug=space_slug,
                memory_scope_ref=memory_scope_ref,
                query=f"{marker} CONCURRENT_DOCUMENT_SENTINEL shared runbook",
                token_budget=1000,
                max_facts=0,
                max_chunks=8,
            )
            probe.check("concurrent_document_idempotency_single_document", len(document_ids) == 1)
            probe.check("concurrent_document_recall_visible", doc_text in _dump(context))
            probe.check("concurrent_document_delete_removes_chunks", deleted["deleted_chunks"] >= 1)
            probe.check("concurrent_document_deleted_hidden", doc_text not in _dump(after_delete))
            probe.assert_effective(max_p95_ms=3_500.0)


def test_context_scale_pagination_and_multi_memory_scope_query_limits_e2e(tmp_path: Path) -> None:
    with (
        run_infinity_context_server(tmp_path, database_name="pagination-scale.db") as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        probe = ReliabilityProbe(client)
        marker = f"PAGINATION_SCALE_{time.time_ns()}"
        space_slug = "pagination-scale-e2e"
        memory_scopes = ("multi-a", "multi-b")
        facts_by_memory_scope: dict[str, list[str]] = {
            memory_scope: [] for memory_scope in memory_scopes
        }
        for memory_scope in memory_scopes:
            for index in range(18):
                text = (
                    f"{marker}: {memory_scope} paginated fact {index:02d} "
                    "for multi memory_scope recall."
                )
                if memory_scope == memory_scopes[0] and index == 0:
                    text = (
                        f"{marker}: MULTI_ALPHA_SENTINEL paginated fact for memory_scope A recall."
                    )
                if memory_scope == memory_scopes[1] and index == 0:
                    text = (
                        f"{marker}: MULTI_BETA_SENTINEL paginated fact for memory_scope B recall."
                    )
                facts_by_memory_scope[memory_scope].append(text)
                probe.request(
                    "POST",
                    "/v1/facts",
                    expected_status=201,
                    json_body=_fact_body(space_slug, memory_scope, text),
                    headers={"Idempotency-Key": f"{marker}:{memory_scope}:{index}"},
                )

        first_page = probe.request(
            "GET",
            "/v1/facts",
            expected_status=200,
            params={
                "space_slug": space_slug,
                "memory_scope_external_ref": memory_scopes[0],
                "limit": 7,
            },
        ).json()
        second_page = probe.request(
            "GET",
            "/v1/facts",
            expected_status=200,
            params={
                "space_slug": space_slug,
                "memory_scope_external_ref": memory_scopes[0],
                "limit": 7,
                "cursor": first_page["next_cursor"],
            },
        ).json()
        multi_memory_scope_context = probe.request(
            "POST",
            "/v1/context",
            expected_status=200,
            json_body={
                "space_slug": space_slug,
                "memory_scope_external_refs": list(memory_scopes),
                "query": f"{marker} MULTI_ALPHA_SENTINEL MULTI_BETA_SENTINEL",
                "token_budget": 1100,
                "max_facts": 12,
                "max_chunks": 0,
            },
        ).json()["data"]
        dumped = _dump(multi_memory_scope_context)
        first_page_ids = {item["id"] for item in first_page["data"]}
        second_page_ids = {item["id"] for item in second_page["data"]}

        probe.check("pagination_first_page_limited", len(first_page["data"]) == 7)
        probe.check("pagination_second_page_limited", len(second_page["data"]) == 7)
        probe.check("pagination_pages_do_not_overlap", not (first_page_ids & second_page_ids))
        probe.check("pagination_has_next_cursor", first_page["next_cursor"] is not None)
        probe.check(
            "multi_memory_scope_context_contains_memory_scope_a",
            any(text in dumped for text in facts_by_memory_scope[memory_scopes[0]]),
        )
        probe.check(
            "multi_memory_scope_context_contains_memory_scope_b",
            any(text in dumped for text in facts_by_memory_scope[memory_scopes[1]]),
        )
        probe.check(
            "multi_memory_scope_context_respects_requested_limit",
            len(multi_memory_scope_context["items"]) <= 12,
        )
        probe.check(
            "multi_memory_scope_context_reports_used_items",
            multi_memory_scope_context["diagnostics"]["items_used"]
            == len(multi_memory_scope_context["items"]),
        )
        probe.assert_effective()


def test_load_parallel_context_reads_during_mutation_storm_e2e(tmp_path: Path) -> None:
    with (
        run_infinity_context_server(tmp_path, database_name="mutation-storm.db") as server,
        httpx.Client(
            base_url=server.base_url,
            headers={"Authorization": f"Bearer {server.token}"},
            timeout=10,
        ) as client,
    ):
        probe = ReliabilityProbe(client)
        marker = f"MUTATION_STORM_{time.time_ns()}"
        space_slug = "mutation-storm-e2e"
        memory_scope_ref = "project-mutation-storm"
        update_text = f"{marker}: MUTATION_TARGET starts with the initial architecture decision."
        delete_text = f"{marker}: DELETE_TARGET must disappear after concurrent readers finish."
        restricted_text = f"{marker}: MUTATION_RESTRICTED_SECRET must stay hidden under read load."

        update_fact = probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body(space_slug, memory_scope_ref, update_text),
            headers={"Idempotency-Key": f"{marker}:update-target"},
        ).json()["data"]
        delete_fact = probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body(space_slug, memory_scope_ref, delete_text),
            headers={"Idempotency-Key": f"{marker}:delete-target"},
        ).json()["data"]
        probe.request(
            "POST",
            "/v1/facts",
            expected_status=201,
            json_body=_fact_body(
                space_slug,
                memory_scope_ref,
                restricted_text,
                classification="restricted",
            ),
            headers={"Idempotency-Key": f"{marker}:restricted"},
        )
        for index in range(20):
            probe.request(
                "POST",
                "/v1/facts",
                expected_status=201,
                json_body=_fact_body(
                    space_slug,
                    memory_scope_ref,
                    f"{marker}: background memory fact {index:02d} remains searchable.",
                ),
                headers={"Idempotency-Key": f"{marker}:background:{index}"},
            )

        stop_readers = threading.Event()
        reader_results: list[tuple[int, str]] = []
        reader_errors: list[str] = []
        reader_lock = threading.Lock()

        def read_context(worker_index: int) -> None:
            with httpx.Client(
                base_url=server.base_url,
                headers={"Authorization": f"Bearer {server.token}"},
                timeout=10,
            ) as reader:
                while not stop_readers.is_set():
                    try:
                        response = reader.post(
                            "/v1/context",
                            json={
                                "space_slug": space_slug,
                                "memory_scope_external_ref": memory_scope_ref,
                                "query": (
                                    f"{marker} MUTATION_TARGET DELETE_TARGET "
                                    f"background worker {worker_index}"
                                ),
                                "token_budget": 1200,
                                "max_facts": 12,
                                "max_chunks": 0,
                            },
                        )
                    except httpx.TimeoutException as exc:
                        with reader_lock:
                            reader_errors.append(f"timeout:{type(exc).__name__}")
                        continue
                    except httpx.HTTPError as exc:
                        with reader_lock:
                            reader_errors.append(f"http:{type(exc).__name__}")
                        continue
                    with reader_lock:
                        reader_results.append((response.status_code, response.text[:500]))
                    time.sleep(0.01)

        final_text = update_text
        with ThreadPoolExecutor(max_workers=6) as pool:
            readers = [pool.submit(read_context, index) for index in range(5)]
            read_pressure_deadline = time.perf_counter() + 2.0
            while time.perf_counter() < read_pressure_deadline:
                with reader_lock:
                    if len(reader_results) >= 10:
                        break
                time.sleep(0.01)
            for version_index in range(1, 6):
                current = probe.request(
                    "GET",
                    f"/v1/facts/{update_fact['id']}",
                    expected_status=200,
                ).json()["data"]
                final_text = (
                    f"{marker}: MUTATION_TARGET version {version_index} "
                    "is the current durable architecture decision."
                )
                probe.request(
                    "PATCH",
                    f"/v1/facts/{update_fact['id']}",
                    expected_status=200,
                    json_body={
                        "expected_version": current["version"],
                        "text": final_text,
                        "reason": "mutation storm version update",
                        "source_refs": [_source_ref(f"{marker}:mutation:{version_index}")],
                    },
                )
                time.sleep(0.02)
            probe.request(
                "DELETE",
                f"/v1/facts/{delete_fact['id']}",
                expected_status=200,
            )
            read_completion_deadline = time.perf_counter() + 6.0
            while time.perf_counter() < read_completion_deadline:
                with reader_lock:
                    if len(reader_results) >= 10:
                        break
                time.sleep(0.01)
            stop_readers.set()
            for reader in readers:
                reader.result()

        final_context = _context(
            probe,
            space_slug=space_slug,
            memory_scope_ref=memory_scope_ref,
            query=f"{marker} MUTATION_TARGET DELETE_TARGET MUTATION_RESTRICTED_SECRET",
            token_budget=1400,
            max_facts=12,
            max_chunks=0,
        )
        final_dump = _dump(final_context)
        server_errors = [item for item in reader_results if item[0] >= 500]
        unexpected_statuses = [item for item in reader_results if item[0] != 200]
        timeout_errors = [item for item in reader_errors if item.startswith("timeout:")]
        non_timeout_errors = [
            item for item in reader_errors if not item.startswith("timeout:")
        ]
        probe.check("mutation_storm_parallel_readers_ran", len(reader_results) >= 10)
        probe.check("mutation_storm_parallel_readers_no_5xx", not server_errors)
        probe.check("mutation_storm_parallel_readers_all_200", not unexpected_statuses)
        probe.check("mutation_storm_parallel_readers_no_http_errors", not non_timeout_errors)
        probe.check(
            "mutation_storm_parallel_reader_timeout_budget",
            len(timeout_errors) <= max(2, len(reader_results) // 2),
        )
        probe.check("mutation_storm_final_fact_visible", final_text in final_dump)
        probe.check("mutation_storm_initial_fact_hidden", update_text not in final_dump)
        probe.check("mutation_storm_deleted_fact_hidden", delete_text not in final_dump)
        probe.check("mutation_storm_restricted_fact_hidden", restricted_text not in final_dump)
        probe.assert_effective(max_p95_ms=3_500.0)


def _context(
    probe: ReliabilityProbe,
    *,
    space_slug: str,
    memory_scope_ref: str,
    query: str,
    token_budget: int,
    max_facts: int,
    max_chunks: int,
) -> dict[str, Any]:
    return probe.request(
        "POST",
        "/v1/context",
        expected_status=200,
        json_body={
            "space_slug": space_slug,
            "memory_scope_external_ref": memory_scope_ref,
            "query": query,
            "token_budget": token_budget,
            "max_facts": max_facts,
            "max_chunks": max_chunks,
        },
    ).json()["data"]


def _fact_body(
    space_slug: str,
    memory_scope_ref: str,
    text: str,
    *,
    classification: str = "internal",
) -> dict[str, Any]:
    return {
        "space_slug": space_slug,
        "memory_scope_external_ref": memory_scope_ref,
        "text": text,
        "kind": "architecture_decision",
        "source_refs": [_source_ref(f"{memory_scope_ref}:{text[:60]}")],
        "classification": classification,
    }


def _document_body(
    space_slug: str,
    memory_scope_ref: str,
    *,
    title: str,
    text: str,
    source_external_id: str,
    classification: str = "internal",
) -> dict[str, Any]:
    return {
        "space_slug": space_slug,
        "memory_scope_external_ref": memory_scope_ref,
        "title": title,
        "text": text,
        "source_type": "document",
        "source_external_id": source_external_id,
        "classification": classification,
    }


def _source_ref(source_id: str) -> dict[str, str]:
    return {
        "source_type": "manual",
        "source_id": source_id,
    }


async def _insert_pending_outbox(database_url: str, *, aggregate_id: str) -> None:
    await _insert_outbox(
        database_url,
        aggregate_id=aggregate_id,
        event_type="vector.upsert_chunk",
        aggregate_type="chunk",
        payload_json={"chunk_id": aggregate_id},
        status="pending",
        attempt_count=0,
        next_attempt_offset=timedelta(seconds=0),
        updated_offset=timedelta(seconds=0),
    )


async def _insert_lagged_pending_outbox(
    database_url: str,
    *,
    aggregate_id: str,
    raw_payload_marker: str,
) -> None:
    await _insert_outbox(
        database_url,
        aggregate_id=aggregate_id,
        event_type="graph.delete_fact",
        aggregate_type="fact",
        payload_json={"fact_id": aggregate_id, "raw": raw_payload_marker},
        status="pending",
        attempt_count=0,
        next_attempt_offset=timedelta(seconds=0),
        updated_offset=-timedelta(minutes=11),
        created_offset=-timedelta(minutes=11),
    )


async def _insert_expired_running_outbox(database_url: str, *, aggregate_id: str) -> None:
    await _insert_outbox(
        database_url,
        aggregate_id=aggregate_id,
        event_type="graph.delete_fact",
        aggregate_type="fact",
        payload_json={},
        status="running",
        attempt_count=0,
        next_attempt_offset=timedelta(hours=1),
        updated_offset=-timedelta(minutes=6),
        last_safe_error="Previous worker crashed mid-job",
        last_safe_diagnostic_code="previous.worker_crash",
    )


async def _insert_poison_outbox(
    database_url: str,
    *,
    aggregate_id: str,
    raw_payload_marker: str,
) -> None:
    await _insert_outbox(
        database_url,
        aggregate_id=aggregate_id,
        event_type="unknown.poison",
        aggregate_type="projection",
        payload_json={"raw": raw_payload_marker, "hint": "must stay out of diagnostics"},
        status="pending",
        attempt_count=4,
        next_attempt_offset=timedelta(seconds=0),
        updated_offset=timedelta(seconds=0),
    )


async def _insert_replayable_dead_outbox(
    database_url: str,
    *,
    aggregate_id: str,
    raw_payload_marker: str,
) -> None:
    await _insert_outbox(
        database_url,
        aggregate_id=aggregate_id,
        event_type="graph.delete_fact",
        aggregate_type="fact",
        payload_json={"fact_id": aggregate_id, "raw": raw_payload_marker},
        status="dead",
        attempt_count=5,
        next_attempt_offset=timedelta(hours=1),
        updated_offset=-timedelta(minutes=3),
        last_safe_error="OutboxProjectionError",
        last_safe_diagnostic_code="graph.unavailable",
    )


async def _insert_done_outbox_with_raw_payload(
    database_url: str,
    *,
    aggregate_id: str,
    raw_payload_marker: str,
) -> None:
    await _insert_outbox(
        database_url,
        aggregate_id=aggregate_id,
        event_type="vector.upsert_chunk",
        aggregate_type="chunk",
        payload_json={
            "space_id": "space_client_app",
            "memory_scope_id": "memory_scope_default",
            "chunk_id": aggregate_id,
            "raw": raw_payload_marker,
        },
        status="done",
        attempt_count=1,
        next_attempt_offset=timedelta(hours=1),
        updated_offset=-timedelta(minutes=3),
    )


async def _outbox_payload_by_aggregate_id(database_url: str, aggregate_id: str) -> dict[str, Any]:
    engine = build_async_engine(database_url)
    try:
        async with AsyncSession(engine) as session:
            row = (
                await session.execute(
                    select(MemoryOutboxRow).where(MemoryOutboxRow.aggregate_id == aggregate_id)
                )
            ).scalar_one()
            return dict(row.payload_json)
    finally:
        await engine.dispose()


async def _insert_outbox(
    database_url: str,
    *,
    aggregate_id: str,
    event_type: str,
    aggregate_type: str,
    payload_json: dict[str, object],
    status: str,
    attempt_count: int,
    next_attempt_offset: timedelta,
    updated_offset: timedelta,
    created_offset: timedelta = -timedelta(minutes=10),
    last_safe_error: str | None = None,
    last_safe_diagnostic_code: str | None = None,
) -> None:
    engine = build_async_engine(database_url)
    try:
        now = datetime.now(UTC)
        async with AsyncSession(engine) as session:
            session.add(
                MemoryOutboxRow(
                    event_type=event_type,
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    aggregate_version=None,
                    workload_class="projection",
                    fairness_key=f"{aggregate_type}:{aggregate_id}",
                    payload_json=payload_json,
                    status=status,
                    attempt_count=attempt_count,
                    next_attempt_at=now + next_attempt_offset,
                    last_safe_error=last_safe_error,
                    last_safe_diagnostic_code=last_safe_diagnostic_code,
                    created_at=now + created_offset,
                    updated_at=now + updated_offset,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


def _outbox_item(diagnostics: dict[str, Any], aggregate_id: str) -> dict[str, Any]:
    for item in diagnostics["items"]:
        if item["aggregate_id"] == aggregate_id:
            return item
    raise AssertionError(f"missing outbox item for {aggregate_id}: {diagnostics}")


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)

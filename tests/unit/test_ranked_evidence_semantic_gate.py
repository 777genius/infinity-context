from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server import ranked_evidence_semantic_gate as gate
from infinity_context_server.public_benchmark_models import (
    BenchmarkMemoryInput,
)
from infinity_context_server.public_benchmark_models import (
    TestClientBenchmarkAdapter as _Adapter,
)


@pytest.fixture(autouse=True)
def _supply_committed_head_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep gate tests independent of the uncommitted diagnostics producer."""

    original_request = gate._request_cutoff

    def request_with_telemetry(*args, **kwargs):
        snapshot = original_request(*args, **kwargs)
        if all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in snapshot.telemetry.values()
        ):
            return snapshot
        item_count = len(snapshot.item_ids)
        return replace(
            snapshot,
            telemetry={
                "ranked_evidence_candidate_count": 2,
                "ranked_evidence_selectable_candidate_count": 2,
                "ranked_evidence_eligible_candidate_count": 2,
                "ranked_evidence_returned_count": item_count,
                "ranked_evidence_source_diversity_count": int(item_count > 0),
            },
        )

    monkeypatch.setattr(gate, "_request_cutoff", request_with_telemetry)


def _dataset(tmp_path: Path) -> Path:
    payload = [
        {
            "sample_id": "semantic-gate",
            "conversation": {
                "speaker_a": "Alice",
                "speaker_b": "Bob",
                "session_1": [
                    {
                        "speaker": "Alice",
                        "text": "The launch key is sapphire blue.",
                        "dia_id": "D1:1",
                    },
                    {
                        "speaker": "Bob",
                        "text": "The fern needs water.",
                        "dia_id": "D1:2",
                    },
                ],
                "session_1_date_time": "10:00 AM on 01 May, 2024",
            },
            "qa": [
                {
                    "question": "What color is the launch key?",
                    "answer": "sapphire blue",
                    "category": 4,
                    "evidence": ["D1:1"],
                }
            ],
        }
    ]
    path = tmp_path / "locomo.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _run(dataset: Path, **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "dataset_path": dataset,
        "benchmark": "locomo",
        "case_ids": ("semantic-gate:qa:1",),
        "cutoffs": (1, 2),
        "reference_cutoff": 2,
        "max_facts": 20,
        "max_chunks": 20,
    }
    kwargs.update(overrides)
    return gate.run_ranked_evidence_semantic_gate(**kwargs)


def test_local_gate_reports_exact_selected_ids_without_gold_in_requests_or_dataset_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset(tmp_path)
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'custom.db'}"
    benchmark_requests: list[dict[str, object]] = []
    response_item_ids: list[list[str]] = []
    asset_dirs: list[Path] = []
    original_post = _Adapter.post
    original_create_app = gate.create_app

    def capture_app(settings):
        asset_dirs.append(Path(settings.asset_storage_dir))
        return original_create_app(settings)

    def capture_post(self, path, *, json_body, headers):
        response = original_post(self, path, json_body=json_body, headers=headers)
        if path == "/v1/context/benchmark-search":
            benchmark_requests.append(dict(json_body))
            response_item_ids.append([item["item_id"] for item in response.json()["data"]["items"]])
        return response

    monkeypatch.setattr(gate, "create_app", capture_app)
    monkeypatch.setattr(_Adapter, "post", capture_post)
    result = _run(dataset, local_database_url=database_url)

    assert result["ok"] is True
    public_item_ids = [snapshot["item_ids"] for snapshot in result["cases"][0]["snapshots"]]
    assert all(
        item_id.startswith("evidence-sha256:")
        for snapshot_ids in public_item_ids
        for item_id in snapshot_ids
    )
    assert public_item_ids != response_item_ids
    assert [request["max_evidence_items"] for request in benchmark_requests] == [1, 2]
    assert all("D1:1" not in json.dumps(request) for request in benchmark_requests)
    assert all(not asset_dir.is_relative_to(tmp_path) for asset_dir in asset_dirs)
    assert not (tmp_path / ".semantic-gate-assets").exists()
    assert database_url not in json.dumps(result)


def test_retrieval_boundary_receives_only_gold_free_request_dto(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset(tmp_path)
    seed_cases: list[object] = []
    request_cases: list[object] = []
    original_seed = gate._seed_case_once
    original_request = gate._request_cutoff

    def capture_seed(*args, **kwargs):
        seed_case = kwargs["seed_case"]
        seed_cases.append(seed_case)
        assert not hasattr(seed_case, "metadata")
        assert not hasattr(seed_case, "expected_terms")
        assert not hasattr(seed_case, "forbidden_terms")
        assert not hasattr(seed_case, "question")
        assert frozenset(seed_case.__slots__) == {
            "benchmark",
            "case_id",
            "memories",
            "documents",
            "memory_scope_external_ref",
            "thread_external_ref",
            "conversations",
        }
        assert all(frozenset(memory.metadata) <= {"role"} for memory in seed_case.memories)
        assert all(
            frozenset(conversation.metadata) <= {"session_original_index", "pair_index"}
            and all(not message.metadata for message in conversation.messages)
            for conversation in seed_case.conversations
        )
        return original_seed(*args, **kwargs)

    def capture_request(*args, **kwargs):
        request_case = kwargs["request_case"]
        request_cases.append(request_case)
        assert not hasattr(request_case, "metadata")
        assert not hasattr(request_case, "expected_terms")
        assert not hasattr(request_case, "forbidden_terms")
        assert not hasattr(request_case, "documents")
        assert frozenset(request_case.__slots__) == {
            "question",
            "memory_scope_external_ref",
            "thread_external_ref",
        }
        return original_request(*args, **kwargs)

    monkeypatch.setattr(gate, "_seed_case_once", capture_seed)
    monkeypatch.setattr(gate, "_request_cutoff", capture_request)

    result = _run(dataset)

    assert result["ok"] is True
    assert len(seed_cases) == 1
    assert len(request_cases) == 2


def test_gold_is_read_only_after_all_frozen_retrieval_responses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset(tmp_path)
    events: list[str] = []
    pending_snapshots: list[gate._PendingSnapshot] = []
    original_request = gate._request_cutoff
    original_evaluator_payload = gate.evaluator_only_payload
    original_expected_refs = gate._exact_case_evidence_refs
    original_expected_terms = gate._answer_support_expected_terms

    def capture_request(*args, **kwargs):
        snapshot = original_request(*args, **kwargs)
        pending_snapshots.append(snapshot)
        events.append(f"response:{snapshot.cutoff}")
        return snapshot

    def capture_evaluator_payload(case):
        assert tuple(events) == ("response:1", "response:2")
        assert all(isinstance(snapshot, gate._PendingSnapshot) for snapshot in pending_snapshots)
        events.append("gold:answer")
        return original_evaluator_payload(case)

    def capture_expected_terms(ground_truth):
        assert events[-1] == "gold:answer"
        events.append("gold:terms")
        return original_expected_terms(ground_truth)

    def capture_expected_refs(case):
        assert events[-1] == "gold:terms"
        events.append("gold:refs")
        return original_expected_refs(case)

    monkeypatch.setattr(gate, "_request_cutoff", capture_request)
    monkeypatch.setattr(gate, "evaluator_only_payload", capture_evaluator_payload)
    monkeypatch.setattr(gate, "_answer_support_expected_terms", capture_expected_terms)
    monkeypatch.setattr(gate, "_exact_case_evidence_refs", capture_expected_refs)

    result = _run(dataset)

    assert result["ok"] is True
    assert events == ["response:1", "response:2", "gold:answer", "gold:terms", "gold:refs"]


@pytest.mark.parametrize(
    "ground_truth",
    (True, 3.0, {"answer": "3"}, ("3", 3), (3,), [False]),
)
def test_answer_support_gold_normalization_rejects_unsupported_shapes(
    ground_truth: object,
) -> None:
    assert gate._answer_support_expected_terms(ground_truth) == ()


def test_total_gold_miss_fails_with_bounded_reference_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset(tmp_path)
    monkeypatch.setattr(
        gate,
        "_exact_case_evidence_refs",
        lambda case: ("never-retrieved",),
    )

    result = _run(dataset)

    assert result["ok"] is False
    assert result["cases"][0]["metrics"]["matches"] is True
    assert result["cases"][0]["metrics"]["retrieval_miss_ref_count"] == 1
    assert result["cases"][0]["failure_reason"] == "semantic_reference_miss"


def test_any_cutoff_crowd_out_fails_even_when_reference_recall_is_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset(tmp_path)

    original_metrics = gate.ranked_evidence_semantic_metrics

    def crowd_out_metrics(*args, **kwargs):
        metrics = copy.deepcopy(original_metrics(*args, **kwargs))
        metrics["cutoffs"][0]["crowd_out_refs"] = ["D1:1"]
        metrics["cutoffs"][0]["crowd_out_ref_count"] = 1
        return metrics

    monkeypatch.setattr(gate, "ranked_evidence_semantic_metrics", crowd_out_metrics)
    result = _run(dataset)

    assert result["ok"] is False
    assert result["cases"][0]["failure_reason"] == "semantic_cutoff_crowd_out"


def test_report_output_cannot_alias_dataset_even_when_other_config_is_invalid(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    original = dataset.read_bytes()

    result = _run(dataset, benchmark="invalid", report_out=dataset)

    assert result["failures"][0]["reason"] == "report_out_aliases_dataset"
    assert dataset.read_bytes() == original


def test_symlinked_report_output_cannot_alias_dataset(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    report_link = tmp_path / "report.json"
    report_link.symlink_to(dataset)
    original = dataset.read_bytes()

    result = _run(dataset, benchmark="invalid", report_out=report_link)

    assert result["failures"][0]["reason"] == "report_out_aliases_dataset"
    assert dataset.read_bytes() == original
    assert report_link.is_symlink()


@pytest.mark.parametrize("through_symlink", [False, True])
def test_report_output_cannot_alias_explicit_database_before_invalid_config_write(
    tmp_path: Path,
    through_symlink: bool,
) -> None:
    database = tmp_path / "scratch.db"
    database.touch()
    report_out = database
    if through_symlink:
        report_out = tmp_path / "report.json"
        report_out.symlink_to(database)
    database_url = f"sqlite+aiosqlite:///{database}"

    result = _run(
        _dataset(tmp_path),
        benchmark="invalid",
        local_database_url=database_url,
        report_out=report_out,
    )

    assert result["failures"][0]["reason"] == "report_out_aliases_database"
    assert database.stat().st_size == 0


def test_nonempty_explicit_database_is_rejected_without_mutation(tmp_path: Path) -> None:
    database = tmp_path / "existing.db"
    original = b"unrelated-user-data"
    database.write_bytes(original)

    result = _run(
        _dataset(tmp_path),
        local_database_url=f"sqlite+aiosqlite:///{database}",
    )

    assert result["failures"][0]["reason"] == "local_database_not_scratch"
    assert database.read_bytes() == original


def test_exact_gold_accessor_preserves_more_than_twenty_long_refs() -> None:
    refs = tuple(f"D{index}:" + "x" * 140 for index in range(1, 26))
    case = SimpleNamespace(metadata={"evidence": [list(refs[:12]), list(refs[12:])]})

    assert gate._exact_case_evidence_refs(case) == refs


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        (["x" * (gate._MAX_EXACT_GOLD_REF_CHARS + 1)], "gold_evidence_overflow"),
        (["D1:1", {"unexpected": "mapping"}], "malformed_gold_evidence"),
    ],
)
def test_exact_gold_accessor_fails_closed_on_overflow_or_malformed_values(
    evidence: object,
    reason: str,
) -> None:
    case = SimpleNamespace(metadata={"evidence": evidence})

    with pytest.raises(gate._GateFailure, match=reason):
        gate._exact_case_evidence_refs(case)


def test_observed_source_refs_extracts_identity_without_mapping_payload_leakage() -> None:
    private_quote = "private quote session-0042 " + "x" * 600
    item = {
        "source_refs": [
            {
                "source_id": "longmemeval:case:session-0031:pair:3",
                "quote_preview": private_quote,
            },
            {"source_id": "session-0031", "quote_preview": private_quote},
            {
                "source_id": "provider:private-session-0031",
                "quote_preview": private_quote,
            },
        ]
    }

    refs = gate._observed_source_refs(item)

    assert refs == (
        "longmemeval:case:session-0031:pair:3",
        "session-0031",
    )
    assert all(0 < len(ref) <= 512 for ref in refs)
    assert all("private quote" not in ref for ref in refs)


def test_observed_source_refs_preserves_mixed_sessions_for_fail_closed_policy() -> None:
    refs = gate._observed_source_refs(
        {
            "source_refs": [
                {"source_id": "longmemeval:case:session-0031"},
                {"source_id": "longmemeval:case:session-0042"},
            ]
        }
    )

    metrics = gate.ranked_evidence_answer_support_metrics(
        (
            gate.RankedEvidenceAnswerSupportObservation(
                cutoff=2,
                fingerprint="mixed-sessions",
                text="I still need to return my coat to the store.",
                source_refs=refs,
            ),
        ),
        question="How many items of clothing do I need to pick up or return from a store?",
        expected_terms=("1",),
        expected_refs=("session-0031",),
    )

    assert refs == (
        "longmemeval:case:session-0031",
        "longmemeval:case:session-0042",
    )
    assert metrics["applicable"] is False
    assert metrics["fallback_reason"] == "quantity_policy_error"


def test_public_evidence_fingerprint_ignores_database_item_ids() -> None:
    first = {
        "item_id": "database-row-1",
        "kind": "fact",
        "text": "  Stable   public evidence. ",
        "source_refs": ["source_turn_refs:D1:1"],
    }
    second = {**first, "item_id": "database-row-999"}

    assert gate._public_evidence_fingerprints((first,)) == gate._public_evidence_fingerprints(
        (second,)
    )


def test_malformed_metric_count_fails_closed_before_aggregation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_metrics = gate.ranked_evidence_semantic_metrics

    def malformed_metrics(*args, **kwargs):
        metrics = original_metrics(*args, **kwargs)
        metrics["retrieval_miss_ref_count"] = "0"
        return metrics

    monkeypatch.setattr(gate, "ranked_evidence_semantic_metrics", malformed_metrics)

    result = _run(_dataset(tmp_path))

    assert result["ok"] is False
    assert result["failures"] == [{"case_id": "suite_setup", "reason": "malformed_case_metrics"}]


def test_passing_metric_contract_requires_exact_nonempty_cutoff_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_metrics = gate.ranked_evidence_semantic_metrics

    def missing_cutoff_metrics(*args, **kwargs):
        metrics = original_metrics(*args, **kwargs)
        metrics["cutoffs"] = metrics["cutoffs"][:-1]
        return metrics

    monkeypatch.setattr(gate, "ranked_evidence_semantic_metrics", missing_cutoff_metrics)

    result = _run(_dataset(tmp_path))

    assert result["failures"] == [
        {"case_id": "semantic-gate:qa:1", "reason": "malformed_semantic_metrics"}
    ]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"benchmark": "mem0"}, "invalid_benchmark"),
        ({"locomo_ingest_mode": "unknown"}, "invalid_locomo_ingest_mode"),
    ],
)
def test_benchmark_and_ingest_mode_fail_closed_before_execution(
    tmp_path: Path,
    overrides: dict[str, object],
    reason: str,
) -> None:
    result = _run(_dataset(tmp_path), **overrides)

    assert result["ok"] is False
    assert result["gates"]["configuration_valid"] is False
    assert result["failures"] == [{"case_id": "suite_setup", "reason": reason}]


def _answer_support_payload(
    *,
    first_complete: bool,
    reference_complete: bool = True,
) -> dict[str, object]:
    first_count = 2 if first_complete else 1
    reference_count = 2 if reference_complete else first_count
    return {
        "schema_version": "ranked-evidence-answer-support-metrics.v1",
        "applicable": True,
        "fallback_reason": None,
        "expected_unit_count": 2,
        "cutoffs": [
            {
                "cutoff": 1,
                "supported_unit_count": first_count,
                "recall": first_count / 2,
                "complete": first_complete,
            },
            {
                "cutoff": 2,
                "supported_unit_count": reference_count,
                "recall": reference_count / 2,
                "complete": reference_complete,
            },
        ],
        "matches": first_complete and reference_complete,
    }


def test_semantically_qualified_reference_miss_passes_without_rewriting_raw_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset(tmp_path)
    observed_expected_refs: list[tuple[str, ...]] = []

    def complete_support(*args, **kwargs):
        observed_expected_refs.append(tuple(kwargs["expected_refs"]))
        assert tuple(kwargs["expected_terms"]) == ("3",)
        return _answer_support_payload(first_complete=True)

    monkeypatch.setattr(gate, "evaluator_only_payload", lambda case: {"ground_truth": 3})
    monkeypatch.setattr(
        gate,
        "_exact_case_evidence_refs",
        lambda case: ("never-retrieved",),
    )
    monkeypatch.setattr(gate, "ranked_evidence_answer_support_metrics", complete_support)

    result = _run(dataset)

    case = result["cases"][0]
    assert result["ok"] is True
    assert case["ok"] is True
    assert observed_expected_refs == [("never-retrieved",)]
    assert case["metrics"]["retrieval_miss_refs"] == ["never-retrieved"]
    assert case["metrics"]["retrieval_miss_ref_count"] == 1
    assert case["metrics"]["cutoffs"][-1]["recall"] == 0.0
    assert case["metrics"]["cutoffs"][-1]["missing_refs"] == ["never-retrieved"]
    assert "ground_truth" not in json.dumps(case)
    assert "expected_terms" not in json.dumps(case)


def test_incomplete_reference_support_cannot_waive_exact_reference_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset(tmp_path)
    monkeypatch.setattr(
        gate,
        "_exact_case_evidence_refs",
        lambda case: ("never-retrieved",),
    )
    monkeypatch.setattr(
        gate,
        "ranked_evidence_answer_support_metrics",
        lambda *args, **kwargs: _answer_support_payload(
            first_complete=False,
            reference_complete=False,
        ),
    )

    result = _run(dataset)

    assert result["ok"] is False
    assert result["cases"][0]["failure_reason"] == "semantic_reference_miss"


def test_complete_answer_support_waives_only_small_cutoff_exact_ref_crowdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset(tmp_path)
    original_metrics = gate.ranked_evidence_semantic_metrics

    def crowd_out(*args, **kwargs):
        metrics = copy.deepcopy(original_metrics(*args, **kwargs))
        metrics["cutoffs"][0]["crowd_out_refs"] = ["D1:1"]
        metrics["cutoffs"][0]["crowd_out_ref_count"] = 1
        return metrics

    monkeypatch.setattr(gate, "ranked_evidence_semantic_metrics", crowd_out)
    monkeypatch.setattr(
        gate,
        "ranked_evidence_answer_support_metrics",
        lambda *args, **kwargs: _answer_support_payload(first_complete=True),
    )

    result = _run(dataset)

    case = result["cases"][0]
    assert result["ok"] is True
    assert case["ok"] is True
    assert case["metrics"]["cutoffs"][0]["crowd_out_refs"] == ["D1:1"]
    assert case["metrics"]["cutoffs"][0]["crowd_out_ref_count"] == 1
    assert case["answer_support"]["matches"] is True


def test_partial_answer_support_cannot_waive_small_cutoff_crowdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset(tmp_path)
    original_metrics = gate.ranked_evidence_semantic_metrics

    def crowd_out(*args, **kwargs):
        metrics = copy.deepcopy(original_metrics(*args, **kwargs))
        metrics["cutoffs"][0]["crowd_out_refs"] = ["D1:1"]
        metrics["cutoffs"][0]["crowd_out_ref_count"] = 1
        return metrics

    monkeypatch.setattr(gate, "ranked_evidence_semantic_metrics", crowd_out)
    monkeypatch.setattr(
        gate,
        "ranked_evidence_answer_support_metrics",
        lambda *args, **kwargs: _answer_support_payload(first_complete=False),
    )

    result = _run(dataset)

    assert result["ok"] is False
    assert result["cases"][0]["failure_reason"] == "semantic_answer_support_miss"


def test_memory_seed_source_ref_has_no_speaker_role_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads: list[dict[str, object]] = []
    memory = BenchmarkMemoryInput(
        text="User-authored benchmark memory.",
        source_external_id="memory-1",
        metadata={"role": "user"},
    )
    seed_case = gate.RankedEvidenceSeedCase(
        benchmark="locomo",
        case_id="case-1",
        memories=(memory,),
        documents=(),
        memory_scope_external_ref="scope-1",
        thread_external_ref="thread-1",
        conversations=(),
    )

    def capture_post(*args, **kwargs):
        payloads.append(kwargs["payload"])
        return SimpleNamespace(status_code=201)

    monkeypatch.setattr(gate, "post_required", capture_post)

    gate._seed_case_once(
        SimpleNamespace(),
        headers={},
        slug="semantic-gate",
        seed_case=seed_case,
    )

    assert payloads[0]["source_refs"] == [
        {
            "source_type": "memory_comparison_benchmark",
            "source_id": "memory-1",
            "quote_preview": "User-authored benchmark memory.",
        }
    ]

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import pickle
from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_case_loader import (
    cases_from_payload,
    parse_memory_comparison_dataset_bytes,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    execution_case_manifest_sha256,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_identity,
    _managed_corpus_record,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    MANAGED_CANARY_MAX_CASES,
    ManagedPublicRunProjection,
    VerifiedManagedRunPlan,
    _inspect_verified_managed_run_plan,
    _managed_answer_cases,
    _managed_case_alias,
    _managed_cases_and_manifest,
    _validate_full_dataset,
    _validate_provider_route,
    build_managed_public_run_projection,
    build_verified_managed_run_plan,
    managed_execution_case_material_sha256,
    managed_policy_cases_from_dataset,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.public_benchmark_checkpoint import selected_case_fingerprint
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkMessageInput,
    BenchmarkValidationError,
    PublicBenchmarkCase,
)


def _profile():
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    return profile


def _route() -> ProviderRouteAttestation:
    origin = "https://api.openai.com"
    endpoint_path = "/v1/chat/completions"
    return ProviderRouteAttestation(
        trust="official_openai",
        origin=origin,
        endpoint_path=endpoint_path,
        route_sha256=hashlib.sha256(f"{origin}{endpoint_path}".encode()).hexdigest(),
        transport_evidence="httpx-direct-tls-no-env-v1",
        credential_binding_id="sha256:" + "7" * 64,
        request_method="POST",
        response_status=200,
    )


def _targets() -> tuple[FullComparisonBackendTarget, ...]:
    return (
        FullComparisonBackendTarget("infinity-context", "4" * 64),
        FullComparisonBackendTarget("mem0", "5" * 64),
    )


def _locomo_sample(
    sample_id: str,
    *,
    qas: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "conversation": {
            "speaker_a": "Alice",
            "speaker_b": "Bob",
            "session_1_date_time": "1:56 pm on 8 May, 2023",
            "session_1": [
                {
                    "dia_id": "D1:1",
                    "speaker": "Alice",
                    "text": "sanitized corpus memory",
                }
            ],
        },
        "qa": qas,
    }


def _qa(index: int, *, category: int = 4) -> dict[str, object]:
    return {
        "question": f"secret-question-{index}",
        "answer": f"secret-gold-{index}",
        "evidence": ["D1:1"],
        "category": category,
    }


def _canary_bytes() -> bytes:
    return json.dumps(
        [
            _locomo_sample("raw-sample-a", qas=[_qa(1), _qa(2)]),
            _locomo_sample("raw-sample-b", qas=[_qa(3)]),
        ],
        separators=(",", ":"),
    ).encode()


def _build(
    dataset_bytes: bytes,
    *,
    scope: str = "canary",
    mem0_expected_runtime_mode: str | None = None,
    selected_case_ids: tuple[str, ...] = (
        "raw-sample-a:qa:1",
        "raw-sample-a:qa:2",
    ),
) -> VerifiedManagedRunPlan:
    return build_verified_managed_run_plan(
        run_id="builder-test",
        run_nonce_commitment_sha256="1" * 64,
        runtime_probe_nonce_sha256="2" * 64,
        profile=_profile(),
        dataset_bytes=dataset_bytes,
        backend_targets=_targets(),
        provider_route=_route(),
        scope=scope,
        mem0_expected_runtime_mode=mem0_expected_runtime_mode,
        selected_case_ids=selected_case_ids,
    )


def test_exact_bytes_parser_accepts_pretty_json_object_and_jsonl() -> None:
    pretty = json.dumps({"cases": [{"id": "one"}]}, indent=2).encode()
    jsonl = b'{"id":"one"}\n{"id":"two"}\n'

    assert parse_memory_comparison_dataset_bytes(pretty) == {"cases": [{"id": "one"}]}
    assert parse_memory_comparison_dataset_bytes(jsonl) == (
        {"id": "one"},
        {"id": "two"},
    )


@pytest.mark.parametrize(
    "payload",
    (
        bytearray(b"[]"),
        "[]",
        b"not-json",
        b'{"case":1,"case":2}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":1e999}',
        b'{"case":1}\n{"case":2,"case":3}\n',
        b'{"case":1}\n{"value":-Infinity}\n',
        b'{"case":1}\n{"value":-1e999}\n',
    ),
)
def test_exact_bytes_parser_rejects_nonexact_or_invalid_payload(payload: object) -> None:
    with pytest.raises(BenchmarkValidationError):
        parse_memory_comparison_dataset_bytes(payload)  # type: ignore[arg-type]


def test_canary_builder_is_opaque_noncopyable_and_nonserializable() -> None:
    admission = _build(_canary_bytes())

    assert type(admission) is VerifiedManagedRunPlan
    assert repr(admission) == "VerifiedManagedRunPlan(<sealed>)"
    with pytest.raises(TypeError, match="noncopyable"):
        copy.copy(admission)
    with pytest.raises(TypeError, match="noncopyable"):
        copy.deepcopy(admission)
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(admission)
    with pytest.raises(ManagedRunError, match="built authoritatively"):
        VerifiedManagedRunPlan(commitment="0" * 64, _token=object())


def test_canary_oss_runtime_mode_is_sealed_in_verified_plan() -> None:
    admission = _build(_canary_bytes(), mem0_expected_runtime_mode="oss")
    plan = _inspect_verified_managed_run_plan(admission)

    assert plan.mem0_expected_runtime_mode == "oss"

    object.__setattr__(plan, "mem0_expected_runtime_mode", "managed_platform")
    with pytest.raises(ManagedRunError, match="integrity failed"):
        _inspect_verified_managed_run_plan(admission)


@pytest.mark.parametrize(
    ("case_ids", "message"),
    (
        ((), "requires selected_case_ids"),
        (("raw-sample-a:qa:1", "raw-sample-a:qa:1"), "duplicates"),
        (("missing",), "unknown profile case"),
        (("raw-sample-a:qa:2", "raw-sample-a:qa:1"), "dataset order"),
    ),
)
def test_canary_builder_rejects_ambiguous_case_selection(
    case_ids: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ManagedRunError, match=message):
        _build(_canary_bytes(), selected_case_ids=case_ids)


def test_policy_case_projection_is_pure_ordered_and_gold_free() -> None:
    cases = managed_policy_cases_from_dataset(
        profile=_profile(),
        dataset_bytes=_canary_bytes(),
        scope="canary",
        selected_case_ids=(
            "raw-sample-a:qa:1",
            "raw-sample-a:qa:2",
        ),
    )

    assert len(cases) == 2
    assert tuple(item.case_id for item in cases) == tuple(
        _managed_case_alias(case)
        for case in cases_from_payload(
            parse_memory_comparison_dataset_bytes(_canary_bytes()),
            locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
        )[:2]
    )
    rendered = repr(cases)
    assert "secret-question" not in rendered
    assert "secret-gold" not in rendered
    assert "raw-sample" not in rendered


def test_public_run_projection_is_provider_free_and_matches_verified_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_bytes = _canary_bytes()
    kwargs = {
        "run_id": "builder-test",
        "run_nonce_commitment_sha256": "1" * 64,
        "runtime_probe_nonce_sha256": "2" * 64,
        "profile": _profile(),
        "dataset_bytes": dataset_bytes,
        "backend_targets": _targets(),
        "scope": "canary",
        "selected_case_ids": (
            "raw-sample-a:qa:1",
            "raw-sample-a:qa:2",
        ),
    }
    assert "provider_route" not in inspect.signature(build_managed_public_run_projection).parameters
    monkeypatch.setattr(
        "infinity_context_server.memory_comparison_managed_plan_builder._validate_provider_route",
        lambda *_args, **_kwargs: pytest.fail("public projection touched provider route"),
    )

    projection = build_managed_public_run_projection(**kwargs)

    assert type(projection) is ManagedPublicRunProjection
    assert "secret-question" not in repr(projection)
    assert "secret-gold" not in repr(projection)
    monkeypatch.undo()
    admission = _build(dataset_bytes)
    plan = _inspect_verified_managed_run_plan(admission)
    private_bindings = create_full_comparison_run_bindings(
        run_id=plan.run_id,
        run_nonce_commitment_sha256=plan.run_nonce_commitment_sha256,
        runtime_probe_nonce_sha256=plan.runtime_probe_nonce_sha256,
        profile=plan.profile,
        methodology=plan.methodology,
        dataset_sha256=plan.dataset_sha256,
        selection_fingerprint_sha256=plan.selection_fingerprint_sha256,
        backend_targets=plan.backend_targets,
        mem0_expected_runtime_mode=plan.mem0_expected_runtime_mode,
        scope=plan.scope,
    )
    assert projection.cases == plan.cases
    assert projection.bindings == private_bindings


def test_public_run_projection_changes_with_nonce_or_selected_case() -> None:
    common = {
        "run_id": "builder-test",
        "runtime_probe_nonce_sha256": "2" * 64,
        "profile": _profile(),
        "dataset_bytes": _canary_bytes(),
        "backend_targets": _targets(),
        "scope": "canary",
    }
    baseline = build_managed_public_run_projection(
        **common,
        run_nonce_commitment_sha256="1" * 64,
        selected_case_ids=("raw-sample-a:qa:1",),
    )
    changed_nonce = build_managed_public_run_projection(
        **common,
        run_nonce_commitment_sha256="3" * 64,
        selected_case_ids=("raw-sample-a:qa:1",),
    )
    changed_case = build_managed_public_run_projection(
        **common,
        run_nonce_commitment_sha256="1" * 64,
        selected_case_ids=("raw-sample-a:qa:1", "raw-sample-a:qa:2"),
    )

    assert baseline.bindings != changed_nonce.bindings
    assert baseline.bindings.binding_commitment_sha256 != (
        changed_nonce.bindings.binding_commitment_sha256
    )
    assert baseline.cases != changed_case.cases
    assert baseline.bindings.selection_fingerprint_sha256 != (
        changed_case.bindings.selection_fingerprint_sha256
    )
    assert baseline.bindings != changed_case.bindings


def test_canary_builder_rejects_selection_above_hard_budget() -> None:
    selected_case_ids = tuple(
        f"raw-sample-a:qa:{index}" for index in range(1, MANAGED_CANARY_MAX_CASES + 2)
    )
    sample = _locomo_sample(
        "raw-sample-a",
        qas=[_qa(index) for index in range(1, MANAGED_CANARY_MAX_CASES + 2)],
    )

    with pytest.raises(ManagedRunError, match="bounded case budget"):
        _build(
            json.dumps([sample], separators=(",", ":")).encode(),
            selected_case_ids=selected_case_ids,
        )


def test_canary_builder_rejects_incomplete_official_timestamp_before_run_start() -> None:
    sample = _locomo_sample("raw-sample-a", qas=[_qa(1)])
    conversation = sample["conversation"]
    assert type(conversation) is dict
    conversation["session_1_date_time"] = "not-an-official-date"

    with pytest.raises(ManagedRunError, match="official turn semantics are incomplete"):
        _build(
            json.dumps([sample], separators=(",", ":")).encode(),
            selected_case_ids=("raw-sample-a:qa:1",),
        )


def test_managed_case_projection_rejects_missing_official_role_before_run_start() -> None:
    case = cases_from_payload(
        parse_memory_comparison_dataset_bytes(_canary_bytes()),
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )[0]
    memory = case.memories[0]
    malformed = replace(
        case,
        memories=(
            replace(
                memory,
                metadata={key: value for key, value in memory.metadata.items() if key != "role"},
            ),
        ),
    )

    with pytest.raises(ManagedRunError, match="memory role is invalid"):
        _managed_cases_and_manifest((malformed,))


def test_full_provider_route_is_exact_but_canary_can_use_subscription_runtime() -> None:
    profile = _profile()
    _validate_provider_route(profile, _route(), scope="full")
    subscription_origin = "http://127.0.0.1:8890"
    subscription_path = "/v1/chat/completions"
    subscription = ProviderRouteAttestation(
        trust="codex_subscription_runtime",
        origin=subscription_origin,
        endpoint_path=subscription_path,
        route_sha256=hashlib.sha256(
            f"{subscription_origin}{subscription_path}".encode()
        ).hexdigest(),
        transport_evidence="subscription-runtime-openai-codex-bridge.v1",
        credential_binding_id=None,
        request_method="POST",
        response_status=200,
    )

    _validate_provider_route(profile, subscription, scope="canary")
    with pytest.raises(ManagedRunError, match="differs from frozen methodology"):
        _validate_provider_route(profile, subscription, scope="full")


def test_full_builder_rejects_caller_selection_and_noncanonical_dataset_hash() -> None:
    with pytest.raises(ManagedRunError, match="cannot accept caller-selected"):
        _build(
            _canary_bytes(),
            scope="full",
            selected_case_ids=("raw-sample-a:qa:1",),
        )

    with pytest.raises(ManagedRunError, match="dataset hash"):
        _build(_full_shaped_bytes(), scope="full", selected_case_ids=())


def test_full_dataset_invariants_cover_count_distribution_and_corpus_cardinality() -> None:
    profile = _profile()
    cases = cases_from_payload(
        parse_memory_comparison_dataset_bytes(_full_shaped_bytes()),
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )

    _validate_full_dataset(
        profile,
        cases,
        dataset_sha256=profile.expected_dataset_hash,
    )
    with pytest.raises(ManagedRunError, match="case count"):
        _validate_full_dataset(
            profile,
            cases[:-1],
            dataset_sha256=profile.expected_dataset_hash,
        )
    changed_category = dict(cases[0].metadata)
    changed_category["category"] = 2
    with pytest.raises(ManagedRunError, match="distribution"):
        _validate_full_dataset(
            profile,
            (replace(cases[0], metadata=changed_category), *cases[1:]),
            dataset_sha256=profile.expected_dataset_hash,
        )
    changed_corpus = dict(cases[0].metadata)
    changed_corpus["sample_id"] = "extra-corpus"
    with pytest.raises(ManagedRunError, match="corpus count"):
        _validate_full_dataset(
            profile,
            (replace(cases[0], metadata=changed_corpus), *cases[1:]),
            dataset_sha256=profile.expected_dataset_hash,
        )


def test_selection_fingerprint_is_derived_from_authoritative_raw_case_order() -> None:
    dataset_bytes = _canary_bytes()
    admission = _build(dataset_bytes)
    plan = _inspect_verified_managed_run_plan(admission)
    cases = cases_from_payload(
        parse_memory_comparison_dataset_bytes(dataset_bytes),
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )

    assert plan.selection_fingerprint_sha256 == selected_case_fingerprint(cases[:2])
    assert tuple(item.case_id for item in plan.cases) == tuple(
        _managed_case_alias(case) for case in cases[:2]
    )


def test_locomo_qa_cases_share_exact_gold_blind_record_and_case_local_aliases() -> None:
    cases = cases_from_payload(
        parse_memory_comparison_dataset_bytes(_canary_bytes()),
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )
    managed, manifest = _managed_cases_and_manifest(cases[:2])

    assert managed[0].corpus_id == managed[1].corpus_id
    assert managed[0].record == managed[1].record
    assert manifest[0].thread_id == manifest[1].thread_id
    assert manifest[0].session_aliases == manifest[1].session_aliases
    assert manifest[0].session_roles == ("memory-0001",)
    assert tuple(item.case_id for item in manifest) == tuple(
        _managed_case_alias(case) for case in cases[:2]
    )
    assert all("raw-sample" not in item.case_id for item in manifest)
    assert len(execution_case_manifest_sha256(manifest)) == 64

    rendered = json.dumps(_managed_corpus_record(cases[0]), sort_keys=True)
    for forbidden in (
        "raw-sample-a",
        "secret-question",
        "secret-gold",
        "evidence",
        "D1:1",
        "session_1",
        "_evaluator_ground_truth",
    ):
        assert forbidden not in rendered


def test_two_case_manifest_preserves_case_major_provider_coverage_order() -> None:
    cases = cases_from_payload(
        parse_memory_comparison_dataset_bytes(_canary_bytes()),
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )
    _, manifest = _managed_cases_and_manifest((cases[0], cases[2]))

    provider_order = tuple(
        (case.case_id, backend, stage)
        for case in manifest
        for backend in ("infinity-context", "mem0")
        for stage in ("answerer", "judge")
    )
    assert provider_order == tuple(
        (case.case_id, backend, stage)
        for case in manifest
        for backend in ("infinity-context", "mem0")
        for stage in ("answerer", "judge")
    )
    assert all("raw-sample" not in case_id for case_id, _backend, _stage in provider_order)


def test_locomo_manifest_derives_all_projected_sessions_for_shared_corpus_qas() -> None:
    sample = _locomo_sample("raw-multi-session", qas=[_qa(1), _qa(2)])
    conversation = sample["conversation"]
    assert type(conversation) is dict
    for session_index in (2, 3):
        conversation[f"session_{session_index}_date_time"] = (
            f"1:56 pm on {7 + session_index} May, 2023"
        )
        conversation[f"session_{session_index}"] = [
            {
                "dia_id": f"D{session_index}:1",
                "speaker": "Bob",
                "text": f"session {session_index} memory",
            }
        ]
    cases = cases_from_payload(
        (sample,),
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )
    managed, manifest = _managed_cases_and_manifest(cases)

    assert len(cases) == len(managed) == len(manifest) == 2
    assert managed[0].record == managed[1].record
    assert manifest[0].corpus_id == manifest[1].corpus_id
    assert manifest[0].session_roles == (
        "memory-0001",
        "memory-0002",
        "memory-0003",
    )
    assert manifest[0].session_aliases == (
        "session-0001",
        "session-0002",
        "session-0003",
    )
    assert manifest[0].official_turn_count == 3
    assert manifest[0].session_roles == manifest[1].session_roles
    assert manifest[0].session_aliases == manifest[1].session_aliases


def test_longmemeval_pairs_share_neutral_session_alias_without_raw_ids() -> None:
    message = BenchmarkMessageInput("user", "neutral message", "raw-message-id", 123)
    conversations = tuple(
        BenchmarkConversationInput(
            messages=(message,),
            source_external_id=f"raw-pair-{index}",
            session_external_id="raw-session-id",
            timestamp=123,
        )
        for index in (1, 2)
    )
    case = PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id="long-case",
        question="secret question",
        expected_terms=("secret gold",),
        memory_scope_external_ref="raw-corpus-id",
        thread_external_ref="raw-thread-id",
        conversations=conversations,
        metadata={"_evaluator_ground_truth": "secret gold", "evidence": ["raw-id"]},
    )

    record = _managed_corpus_record(case)
    assert [item["session_alias"] for item in record["conversations"]] == [
        "session-0001",
        "session-0001",
    ]
    assert record["memories"] == []
    corpus_id, thread_id = _managed_corpus_identity(case)
    assert len(corpus_id.rsplit("-", 1)[-1]) == 64
    assert len(thread_id.rsplit("-", 1)[-1]) == 64
    rendered = json.dumps(record, sort_keys=True)
    for forbidden in (
        "raw-session-id",
        "raw-message-id",
        "raw-corpus-id",
        "raw-thread-id",
        "secret question",
        "secret gold",
        "evidence",
    ):
        assert forbidden not in rendered

    managed, manifest = _managed_cases_and_manifest((case,))
    assert managed[0].case_id == _managed_case_alias(case)
    assert manifest[0].session_roles == ("memory-0001",)
    assert manifest[0].session_aliases == ("session-0001",)


def test_longmemeval_manifest_preserves_first_seen_distinct_session_order() -> None:
    message = BenchmarkMessageInput("user", "neutral message")
    conversations = tuple(
        BenchmarkConversationInput(
            messages=(message,),
            session_external_id=session_id,
        )
        for session_id in ("distractor-session", "answer-session", "distractor-session")
    )
    case = PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id="raw-long-case",
        question="private question",
        expected_terms=("private gold",),
        memory_scope_external_ref="raw-corpus",
        thread_external_ref="raw-thread",
        conversations=conversations,
    )

    managed, manifest = _managed_cases_and_manifest((case,))

    assert managed[0].case_id == _managed_case_alias(case)
    assert manifest[0].session_roles == ("memory-0001", "memory-0002")
    assert manifest[0].session_aliases == ("session-0001", "session-0002")
    assert manifest[0].official_turn_count == 0
    rendered = repr((managed, manifest))
    for private in (
        "raw-long-case",
        "raw-corpus",
        "raw-thread",
        "distractor-session",
        "answer-session",
        "private question",
        "private gold",
    ):
        assert private not in rendered


def test_answer_projection_has_only_opaque_id_question_and_whitelisted_temporal_fields() -> None:
    case = cases_from_payload(
        parse_memory_comparison_dataset_bytes(_canary_bytes()),
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )[0]
    case = PublicBenchmarkCase(
        **{
            **case.__dict__,
            "metadata": {
                **case.metadata,
                "question_type": "temporal-reasoning",
                "question_date": "2023-05-08",
                "reference_date": "2023-05-09",
                "evidence": ["raw-evidence"],
                "forbidden_terms": ["secret"],
            },
        }
    )
    alias = _managed_case_alias(case)
    answer_case = _managed_answer_cases((case,), case_aliases=(alias,))[0]

    assert answer_case.case_id == alias
    assert answer_case.question == "secret-question-1"
    assert dict(answer_case.temporal_context) == {
        "question_type": "temporal-reasoning",
        "question_date": "2023-05-08",
        "reference_date": "2023-05-09",
    }
    rendered = repr(answer_case.temporal_context)
    assert "raw-evidence" not in rendered
    assert "secret-gold" not in rendered
    assert len(managed_execution_case_material_sha256(case, case_alias=alias)) == 64


def _full_shaped_bytes() -> bytes:
    distribution = ((1, 282), (2, 321), (3, 96), (4, 841))
    qas = [
        _qa(index, category=category) for category, count in distribution for index in range(count)
    ]
    samples = [
        _locomo_sample(
            f"full-sample-{sample_index}",
            qas=qas[sample_index::10],
        )
        for sample_index in range(10)
    ]
    return json.dumps(samples, separators=(",", ":")).encode()

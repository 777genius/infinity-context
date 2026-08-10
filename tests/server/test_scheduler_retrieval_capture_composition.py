from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from infinity_context_server.memory_comparison_http import (
    InfinityContextHttpComparisonBackend,
    Mem0HttpComparisonBackend,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_durable_scheduler import (
    retrieval_capture_contracts as capture_contracts,
)
from infinity_context_server.publishable_durable_scheduler import (
    retrieval_capture_service as capture_service,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerBackendAuthority,
    SchedulerBenchmark,
    SchedulerBridgeBootAuthority,
    SchedulerDeadlineTokenAuthority,
    SchedulerProfile,
    SchedulerRunBinding,
    SchedulerSuiteAuthority,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerCaseAuthority,
    build_scheduler_manifest,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerOfficialCaseAuthorityPage,
    SchedulerOfficialCaseAuthorityRow,
    SchedulerOfficialCaseRunScope,
)
from infinity_context_server.publishable_durable_scheduler.official_case_sqlite_authority import (
    SQLiteSchedulerOfficialCaseAuthorityBuilder,
    SQLiteSchedulerOfficialCaseReader,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_official_cases import (
    PreparedPublishableOfficialCases,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_composition import (
    compose_scheduler_retrieval_capture,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SchedulerRunStoreSpec,
    SchedulerSuiteSealStoreSpec,
)

_CASE_KEY = b"focused-composition-case-authority-key/v1"
_RETRIEVAL_KEY = b"focused-composition-retrieval-key/v1"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _profile(benchmark: SchedulerBenchmark, count: int) -> SchedulerProfile:
    """Create a small exact-type profile without weakening production validation."""

    profile = object.__new__(SchedulerProfile)
    object.__setattr__(profile, "benchmark", benchmark)
    object.__setattr__(profile, "profile_id", f"focused-{benchmark.value}")
    object.__setattr__(profile, "case_count", count)
    object.__setattr__(profile, "call_count", count * 4)
    object.__setattr__(profile, "shard_count", 1)
    return profile


def _suite_and_cases(
    *, infinity_target: str, mem0_target: str
) -> tuple[SchedulerSuiteAuthority, tuple[tuple[SchedulerCaseAuthority, ...], ...]]:
    profiles = (
        _profile(SchedulerBenchmark.LOCOMO, 2),
        _profile(SchedulerBenchmark.LONGMEMEVAL, 1),
    )
    cases = tuple(
        tuple(
            SchedulerCaseAuthority(
                case_id=f"{profile.benchmark.value}-case-{index}",
                case_alias=f"{profile.benchmark.value}-alias-{index}",
            )
            for index in range(profile.case_count)
        )
        for profile in profiles
    )
    backends = (
        SchedulerBackendAuthority("infinity-context", infinity_target),
        SchedulerBackendAuthority("mem0", mem0_target),
    )
    bindings = []
    for profile, identities in zip(profiles, cases, strict=True):
        answer_tokens = judge_tokens = 16
        limits = SchedulerDeadlineTokenAuthority(
            dispatch_not_before_unix_ms=1,
            dispatch_deadline_unix_ms=2,
            answer_max_output_tokens=answer_tokens,
            judge_max_output_tokens=judge_tokens,
            run_token_ceiling=(profile.case_count * 2 * (answer_tokens + judge_tokens)),
        )
        bindings.append(
            SchedulerRunBinding(
                run_id=f"focused-{profile.benchmark.value}-run",
                profile=profile,
                binding_commitment_sha256=_sha(f"binding:{profile.benchmark.value}"),
                dataset_sha256=_sha(f"dataset:{profile.benchmark.value}"),
                case_manifest_sha256=case_manifest_sha256(identities),
                backends=backends,
                limits=limits,
            )
        )
    suite = SchedulerSuiteAuthority(
        suite_id="focused-retrieval-capture-suite",
        publication_bundle_sha256=_sha("publication-bundle"),
        methodology_sha256=_sha("methodology"),
        source_commit_sha256=_sha("source-commit"),
        bridge_boot=SchedulerBridgeBootAuthority(
            bridge_id="focused-bridge",
            implementation_sha256=_sha("implementation"),
            runtime_authority_sha256=_sha("runtime"),
            boot_nonce_sha256=_sha("nonce"),
            receipt_verifier_policy_sha256=_sha("verifier"),
        ),
        ordered_runs=tuple(bindings),
    )
    return suite, cases


def _scope(suite, run) -> SchedulerOfficialCaseRunScope:
    binding = run.binding
    return SchedulerOfficialCaseRunScope(
        suite_authority_sha256=suite.commitment_sha256,
        run_authority_sha256=run.commitment_sha256,
        run_binding_commitment_sha256=binding.binding_commitment_sha256,
        run_id=binding.run_id,
        benchmark=binding.profile.benchmark,
        scheduler_profile_id=binding.profile.profile_id,
        publishable_profile_id=PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
        publishable_profile_sha256=PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
        methodology_sha256=suite.methodology_sha256,
        dataset_sha256=binding.dataset_sha256,
        case_manifest_sha256=binding.case_manifest_sha256,
        case_count=binding.profile.case_count,
    )


def _case(run, identity, index: int) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark=run.binding.profile.benchmark.value,
        case_id=identity.case_id,
        question=f"What is current for {identity.case_id}?",
        expected_terms=(f"gold-{identity.case_id}",),
        forbidden_terms=(f"forbidden-{identity.case_id}",),
        memory_scope_external_ref=f"scope-{identity.case_id}",
        thread_external_ref=f"thread-{identity.case_id}",
        metadata={"_evaluator_ground_truth": f"private-gold-{index}"},
    )


def _prepared_cases(
    tmp_path: Path,
    *,
    suite: SchedulerSuiteAuthority,
    identities: tuple[tuple[SchedulerCaseAuthority, ...], ...],
) -> tuple[PreparedPublishableOfficialCases, tuple[tuple[PublicBenchmarkCase, ...], ...]]:
    runs = tuple(run_authority_from_suite(suite, run_index=index) for index in (0, 1))
    manifests = tuple(
        build_scheduler_manifest(run, suite=suite, ordered_cases=run_cases)
        for run, run_cases in zip(runs, identities, strict=True)
    )
    scopes = tuple(_scope(suite, run) for run in runs)
    rows = []
    private_cases = []
    for run, run_cases in zip(runs, identities, strict=True):
        material = []
        for index, identity in enumerate(run_cases):
            case = _case(run, identity, index)
            material.append(case)
            rows.append(
                SchedulerOfficialCaseAuthorityRow(
                    run_id=run.binding.run_id,
                    case_index=index,
                    case_id=identity.case_id,
                    case_alias=identity.case_alias,
                    case=case,
                )
            )
        private_cases.append(tuple(material))
    case_path = tmp_path / "official-cases.sqlite3"
    builder = SQLiteSchedulerOfficialCaseAuthorityBuilder.create(
        case_path,
        run_scopes=scopes,
        authentication_key=_CASE_KEY,
    )
    builder.append_page(SchedulerOfficialCaseAuthorityPage(0, tuple(rows)))
    terminal = builder.finalize()
    builder.close()
    reader = SQLiteSchedulerOfficialCaseReader.open(
        case_path,
        authentication_key=_CASE_KEY,
        authority_root_sha256=terminal.authority_root_sha256,
    )
    run_stores = tuple(
        SchedulerRunStoreSpec(
            run=run,
            manifest=manifest,
            database_path=tmp_path / f"{run.binding.run_id}.sqlite3",
            private_directory=tmp_path,
            authentication_secret=f"run-store-{index}".encode().ljust(32, b"!"),
        )
        for index, (run, manifest) in enumerate(zip(runs, manifests, strict=True))
    )
    prepared = PreparedPublishableOfficialCases(
        runs=runs,
        manifests=manifests,
        run_stores=run_stores,
        seal_store=SchedulerSuiteSealStoreSpec(
            database_path=tmp_path / "seal.sqlite3",
            private_directory=tmp_path,
            authentication_secret=b"focused-suite-seal-key-material!",
        ),
        terminal=terminal,
        reader=reader,
    )
    return prepared, tuple(private_cases)


def test_focused_composition_seals_reopens_and_replays_without_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        capture_contracts,
        "LOCOMO_PROFILE",
        SimpleNamespace(case_count=2),
    )
    monkeypatch.setattr(
        capture_contracts,
        "LONGMEMEVAL_PROFILE",
        SimpleNamespace(case_count=1),
    )
    monkeypatch.setattr(capture_contracts, "PUBLISHABLE_SUITE_CASE_COUNT", 3)
    monkeypatch.setattr(capture_contracts, "SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT", 6)
    monkeypatch.setattr(capture_service, "SCHEDULER_RETRIEVAL_CAPTURE_GROUP_COUNT", 6)

    infinity_url = "http://127.0.0.1:17788"
    mem0_url = "http://127.0.0.1:18888"
    suite, identities = _suite_and_cases(
        infinity_target=managed_backend_target_identity_sha256(
            backend_role="infinity-context",
            base_url=infinity_url,
        ),
        mem0_target=managed_backend_target_identity_sha256(
            backend_role="mem0",
            base_url=mem0_url,
        ),
    )
    prepared, cases = _prepared_cases(tmp_path, suite=suite, identities=identities)
    calls: list[tuple[str, dict[str, object]]] = []

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(("infinity-context", payload))
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "item_id": "infinity-result",
                            "text": "retrieved infinity evidence",
                            "score": 1.0,
                            "source_refs": [],
                            "metadata": {},
                        }
                    ]
                }
            },
        )

    def mem0_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(("mem0", payload))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "mem0-result",
                        "memory": "retrieved mem0 evidence",
                        "score": 1.0,
                        "metadata": {},
                    }
                ]
            },
        )

    infinity = InfinityContextHttpComparisonBackend(
        base_url=infinity_url,
        auth_token="focused-token",
        retrieval_policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
        mirror_memories_as_documents=False,
        transport=httpx.MockTransport(infinity_handler),
    )
    mem0 = Mem0HttpComparisonBackend(
        base_url=mem0_url,
        reset_user_on_start=False,
        transport=httpx.MockTransport(mem0_handler),
    )
    for run, run_cases in zip(prepared.runs, cases, strict=True):
        for case in run_cases:
            mem0.ingest(case, run_id=run.binding.run_id, corpus_key=case.case_id)
    composition = compose_scheduler_retrieval_capture(
        tmp_path / "retrieval.sqlite3",
        suite=suite,
        official_cases=prepared,
        infinity_backend=infinity,
        mem0_backend=mem0,
        authentication_key=_RETRIEVAL_KEY,
    )
    sealed = composition.capture()
    try:
        assert sealed.terminal.group_count == 6
        assert sealed.terminal.page_count == 6
        assert (
            tuple(role for role, _payload in calls)
            == (
                "infinity-context",
                "mem0",
            )
            * 3
        )
        wire = json.dumps([payload for _role, payload in calls], sort_keys=True)
        assert "private-gold" not in wire
        assert "forbidden" not in wire
        call_count = len(calls)
        sealed.close()
        replay = composition.capture()
        try:
            assert replay.terminal == sealed.terminal
            assert len(calls) == call_count
        finally:
            replay.close()
    finally:
        sealed.close()
        prepared.close()
        infinity.close()
        mem0.close()

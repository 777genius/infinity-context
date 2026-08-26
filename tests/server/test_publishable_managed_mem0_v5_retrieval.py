from __future__ import annotations

import hashlib
import hmac
import json
import pickle
import re
from dataclasses import dataclass, replace

import pytest
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_identity,
    _managed_corpus_record,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_evidence import (
    HmacSha256ManagedMem0V5EvidenceVerifier,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    create_managed_mem0_v5_storage_witness_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
)
from infinity_context_server.memory_comparison_target_identity import (
    mem0_runtime_target_identity_sha256,
)
from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_composition as run_composition,
)
from infinity_context_server.processes import (
    publishable_full_extraction_managed_mem0_v5_suite_composition as suite_composition,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerBackendAuthority,
    SchedulerBenchmark,
    SchedulerSuiteAuthority,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT,
    SchedulerBackendRetrievalRequest,
    SchedulerRetrievalCaptureError,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
    SchedulerOfficialCaseKey,
)
from infinity_context_server.publishable_input_preparation import (
    ManagedMem0V5SchedulerRetrievalAdapter,
)
from scheduler_subscription_bridge_composition_test_support import (
    bridge_fleet_readiness,
    official_suite_and_manifests,
)

PublishableFullExtractionRunConfiguration = (
    run_composition.PublishableFullExtractionRunConfiguration
)
PublishableFullExtractionSuiteConfiguration = (
    suite_composition.PublishableFullExtractionSuiteConfiguration
)

_ORIGIN = "http://127.0.0.1:31991"
_ADMIT_PATH = "/v5/runs/admit"
_SEARCH_PATH = "/v5/runs/search"
_SEARCH_SCHEMA = "mem0-oss-adapter-v5.scoped-search.v1"
_KEY_DOMAIN = b"mem0-oss-adapter-v5/evidence-key/v1"
_SEARCH_DOMAIN = b"scoped-search/v1"
_OPAQUE_CORPUS = re.compile(r"(locomo|longmemeval)-corpus-[0-9a-f]{64}\Z")


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def _search_key(master: bytes) -> bytes:
    root = hmac.new(master, _KEY_DOMAIN, hashlib.sha256).digest()
    return hmac.new(root, _SEARCH_DOMAIN, hashlib.sha256).digest()


@dataclass(frozen=True, slots=True)
class _ExpectedSearch:
    benchmark: str
    admission_commitment_sha256: str
    ingestion_manifest_sha256: str
    ingestion_root_sha256: str
    expected_operation_count: int
    route_sha256: str
    runtime_binding_commitment_sha256: str
    corpus_id: str
    query: str
    bearer: str
    evidence_key: bytes
    source_id: str
    source_sha256: str
    observation_date: str
    result_count: int


@dataclass(frozen=True, slots=True)
class _ObservedSearch:
    admission_commitment_sha256: str
    corpus_id: str
    query: str
    limit: int


@dataclass(frozen=True, slots=True)
class _ObservedAdmission:
    admission_commitment_sha256: str
    runtime_binding_commitment_sha256: str


class _Response:
    status_code = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._content = _canonical(payload)

    def read_bounded(self, maximum_bytes: int) -> bytes:
        if len(self._content) > maximum_bytes:
            raise ValueError("synthetic managed search response exceeded bound")
        return self._content


class _SearchOnlyTransport:
    def __init__(self, expected: tuple[_ExpectedSearch, _ExpectedSearch]) -> None:
        self._expected = {item.admission_commitment_sha256: item for item in expected}
        self.admission_calls: list[_ObservedAdmission] = []
        self.calls: list[_ObservedSearch] = []
        self.events: list[tuple[str, str]] = []
        self.evidence_commitments: dict[str, str] = {}
        self.tamper_mode: str | None = None

    def reset(self) -> None:
        self.admission_calls.clear()
        self.calls.clear()
        self.events.clear()
        self.evidence_commitments.clear()
        self.tamper_mode = None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes,
        timeout: float,
        follow_redirects: bool,
    ) -> _Response:
        if method != "POST" or url not in {_ORIGIN + _ADMIT_PATH, _ORIGIN + _SEARCH_PATH}:
            raise AssertionError("managed retrieval used an unexpected route")
        body = json.loads(content)
        if type(body) is not dict:
            raise AssertionError("managed retrieval body was not an object")
        admission = body.get("admission_commitment_sha256")
        expected = self._expected.get(admission) if type(admission) is str else None
        if expected is None:
            raise AssertionError("managed retrieval selected an unknown admission")
        if url == _ORIGIN + _ADMIT_PATH:
            return self._admit(
                body=body,
                headers=headers,
                content=content,
                timeout=timeout,
                follow_redirects=follow_redirects,
                expected=expected,
            )
        return self._search(
            body=body,
            headers=headers,
            content=content,
            timeout=timeout,
            follow_redirects=follow_redirects,
            expected=expected,
        )

    def _admit(
        self,
        *,
        body: dict[str, object],
        headers: dict[str, str],
        content: bytes,
        timeout: float,
        follow_redirects: bool,
        expected: _ExpectedSearch,
    ) -> _Response:
        exact = {
            "admission_commitment_sha256": expected.admission_commitment_sha256,
            "expected_operation_count": expected.expected_operation_count,
            "ingestion_manifest_sha256": expected.ingestion_manifest_sha256,
            "ingestion_root_sha256": expected.ingestion_root_sha256,
            "route_sha256": expected.route_sha256,
        }
        assert body == exact
        assert headers == {
            "Authorization": "Bearer " + expected.bearer,
            "Content-Type": "application/json",
            "Idempotency-Key": canonical_sha256(
                {
                    "kind": "admit",
                    "binding": expected.admission_commitment_sha256,
                }
            ),
            "X-Request-Commitment-SHA256": hashlib.sha256(content).hexdigest(),
        }
        assert timeout == 1.0
        assert follow_redirects is False
        self.admission_calls.append(
            _ObservedAdmission(
                expected.admission_commitment_sha256,
                expected.runtime_binding_commitment_sha256,
            )
        )
        self.events.append(("admit", expected.admission_commitment_sha256))
        commitment = expected.admission_commitment_sha256
        runtime = expected.runtime_binding_commitment_sha256
        accepted = True
        if self.tamper_mode == "admission-commitment":
            commitment = _sha("cross-wired-admission")
        elif self.tamper_mode == "admission-runtime":
            runtime = _sha("cross-wired-runtime")
        elif self.tamper_mode == "admission-accepted":
            accepted = False
        return _Response(
            {
                "accepted": accepted,
                "admission_commitment_sha256": commitment,
                "runtime_binding_commitment_sha256": runtime,
            }
        )

    def _search(
        self,
        *,
        body: dict[str, object],
        headers: dict[str, str],
        content: bytes,
        timeout: float,
        follow_redirects: bool,
        expected: _ExpectedSearch,
    ) -> _Response:
        exact = {
            "admission_commitment_sha256": expected.admission_commitment_sha256,
            "corpus_id": expected.corpus_id,
            "limit": SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT,
            "query": expected.query,
        }
        assert body == exact
        assert _OPAQUE_CORPUS.fullmatch(expected.corpus_id) is not None
        assert headers == {
            "Authorization": "Bearer " + expected.bearer,
            "Content-Type": "application/json",
            "Idempotency-Key": canonical_sha256(
                {"kind": "search", "binding": canonical_sha256(exact)}
            ),
            "X-Request-Commitment-SHA256": hashlib.sha256(content).hexdigest(),
        }
        assert timeout == 1.0
        assert follow_redirects is False
        self.calls.append(
            _ObservedSearch(
                expected.admission_commitment_sha256,
                expected.corpus_id,
                expected.query,
                SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT,
            )
        )
        self.events.append(("search", expected.admission_commitment_sha256))
        results = [
            {
                "rank": rank,
                "record_id": f"{expected.benchmark}-record-{rank:03d}",
                "memory": f"{expected.benchmark} signed memory {rank:03d}",
                "memory_sha256": hashlib.sha256(
                    f"{expected.benchmark} signed memory {rank:03d}".encode()
                ).hexdigest(),
                "source_id": expected.source_id,
                "source_sha256": expected.source_sha256,
                "score": float(1.0 - rank / 1_000),
            }
            for rank in range(expected.result_count)
        ]
        if self.tamper_mode == "source":
            results[0]["source_sha256"] = _sha("signed-but-cross-wired-source")
        unsigned = {
            "schema_version": _SEARCH_SCHEMA,
            "admission_commitment_sha256": expected.admission_commitment_sha256,
            "corpus_id": expected.corpus_id,
            "query_commitment_sha256": canonical_sha256({"query": expected.query}),
            "limit": SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT,
            "result_count": len(results),
            "result_root_sha256": canonical_sha256({"results": results}),
            "results": results,
        }
        signature = hmac.new(
            _search_key(expected.evidence_key),
            _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        if self.tamper_mode == "hmac":
            signature = "0" * 64
        commitment = canonical_sha256(unsigned)
        self.evidence_commitments[expected.admission_commitment_sha256] = commitment
        return _Response({**unsigned, "search_hmac_sha256": signature})


class _BearerCapability:
    def __init__(self, value: str) -> None:
        self._value = value
        self.calls = 0

    def validate(self) -> None:
        assert self.calls == 0

    def consume(self) -> str:
        self.calls += 1
        if self.calls != 1:
            raise AssertionError("bearer consumed more than once")
        return self._value


class _EvidenceKeyCapability:
    def __init__(self, value: bytes) -> None:
        self._value = value
        self.calls = 0

    def validate(self) -> None:
        assert self.calls == 0

    def consume(self) -> bytes:
        self.calls += 1
        if self.calls != 1:
            raise AssertionError("evidence key consumed more than once")
        return self._value


class _UnusedLaneCollaborators:
    def verify_request_binding_v2(self, **_kwargs: object) -> object:
        raise AssertionError("retrieval attempted extraction request binding")

    def cleanup_context(self, **_kwargs: object) -> object:
        raise AssertionError("retrieval attempted cleanup")


@dataclass(frozen=True, slots=True)
class _RunFixture:
    benchmark: SchedulerBenchmark
    raw_scope: str
    raw_thread: str
    query: str
    manifest: ManagedMem0V5ManifestAuthority
    admission: Mem0OssFullRunAdmission
    runtime_binding_commitment_sha256: str
    lane: ManagedMem0V5HttpLane
    expected: _ExpectedSearch


@dataclass(frozen=True, slots=True)
class _ExpectedRuntime:
    subscription_runtime_binding_commitment_sha256: str


@dataclass(frozen=True, slots=True)
class _Harness:
    suite: SchedulerSuiteAuthority
    configuration: PublishableFullExtractionSuiteConfiguration
    adapter: ManagedMem0V5SchedulerRetrievalAdapter
    transport: _SearchOnlyTransport
    runs: tuple[_RunFixture, _RunFixture]


def _source_case(benchmark: SchedulerBenchmark) -> tuple[PublicBenchmarkCase, str, str]:
    raw_scope = f"raw-{benchmark.value}-shared-scope"
    raw_thread = f"raw-{benchmark.value}-shared-thread"
    if benchmark is SchedulerBenchmark.LOCOMO:
        case = PublicBenchmarkCase(
            benchmark=benchmark.value,
            case_id="locomo-source-case",
            question="Private source question",
            expected_terms=(),
            memories=(
                BenchmarkMemoryInput(
                    text="Alice moved to Oslo.",
                    kind="fact",
                    source_external_id="locomo-source-memory",
                    metadata={
                        "role": "user",
                        "speaker": "Alice",
                        "session_date": "2024-03-10",
                        "timestamp": 1_710_028_800,
                    },
                ),
            ),
            memory_scope_external_ref=raw_scope,
            thread_external_ref=raw_thread,
            metadata={"locomo_ingest_mode": "official-turns"},
        )
    else:
        case = PublicBenchmarkCase(
            benchmark=benchmark.value,
            case_id="longmemeval-source-case",
            question="Private source question",
            expected_terms=(),
            conversations=(
                BenchmarkConversationInput(
                    messages=(
                        BenchmarkMessageInput("user", "I moved to Oslo.", timestamp=1_700_000_000),
                        BenchmarkMessageInput(
                            "assistant",
                            "I will remember that.",
                            timestamp=1_700_000_001,
                        ),
                    ),
                    source_external_id="longmemeval-source-pair",
                    session_external_id="longmemeval-source-session",
                    session_date="2023-11-14",
                    timestamp=1_700_000_001,
                ),
            ),
            memory_scope_external_ref=raw_scope,
            thread_external_ref=raw_thread,
        )
    return case, raw_scope, raw_thread


def _manifest(benchmark: SchedulerBenchmark, *, case_count: int) -> ManagedMem0V5ManifestAuthority:
    case, _scope, _thread = _source_case(benchmark)
    record = _managed_corpus_record(case)
    corpus_id, _thread_id = _managed_corpus_identity(case)
    assert record["corpus_id"] == corpus_id
    cases = tuple(
        ManagedRunCase(
            case_id=f"{benchmark.value}-managed-case-{index}",
            corpus_id=corpus_id,
            record=dict(record),
        )
        for index in range(case_count)
    )
    return ManagedMem0V5ManifestProjector().project(
        cases,
        current_date="2026-08-10",
    )


def _admission(
    *, run_id: str, manifest: ManagedMem0V5ManifestAuthority, index: int
) -> Mem0OssFullRunAdmission:
    request = Mem0OssAdmissionRequest(
        run_id=run_id,
        route_sha256=_sha(f"route:{index}"),
        credential_binding_sha256=_sha(f"credential:{index}"),
        model="gpt-5.6-sol",
        reasoning_effort="high",
        service_tier="default",
        runtime_source_revision="mem0-oss-v5-pinned",
        runtime_source_sha256=_sha(f"runtime-source:{index}"),
        runtime_base_sha256=_sha(f"runtime-base:{index}"),
        expected_operation_count=manifest.operation_count,
    )
    return Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=manifest.ingestion_manifest_sha256,
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        ingestion_unit_count=manifest.operation_count,
    )


def _lane(
    *,
    bearer: str,
    evidence_key: bytes,
    transport: _SearchOnlyTransport,
) -> ManagedMem0V5HttpLane:
    issuer, _verifier = create_managed_mem0_v5_storage_witness_authority()
    verifier = HmacSha256ManagedMem0V5EvidenceVerifier(
        key_capability=_EvidenceKeyCapability(evidence_key),
        storage_witness_issuer=issuer,
    )
    unused = _UnusedLaneCollaborators()
    return ManagedMem0V5HttpLane(
        origin=_ORIGIN,
        bearer_capability=_BearerCapability(bearer),
        timeout_seconds=1,
        evidence_verifier=verifier,
        dispatch_binding=unused,
        cleanup_binding=unused,
        transport=transport,
    )


def _configuration(
    runs: tuple[_RunFixture, _RunFixture], *, target: str
) -> PublishableFullExtractionSuiteConfiguration:
    configurations = []
    for run in runs:
        value = object.__new__(PublishableFullExtractionRunConfiguration)
        object.__setattr__(value, "manifest_authority", run.manifest)
        object.__setattr__(value, "admission", run.admission)
        object.__setattr__(value, "http_lane", run.lane)
        object.__setattr__(value, "runtime_target_identity_sha256", target)
        object.__setattr__(
            value,
            "expected_runtime",
            _ExpectedRuntime(run.runtime_binding_commitment_sha256),
        )
        configurations.append(value)
    suite = object.__new__(PublishableFullExtractionSuiteConfiguration)
    object.__setattr__(suite, "locomo", configurations[0])
    object.__setattr__(suite, "longmemeval", configurations[1])
    return suite


@pytest.fixture(scope="module")
def base_harness() -> _Harness:
    base, _runs, _manifests, _cases = official_suite_and_manifests(bridge_fleet_readiness())
    target = mem0_runtime_target_identity_sha256(_ORIGIN)
    backends = (
        SchedulerBackendAuthority("infinity-context", _sha("infinity-target")),
        SchedulerBackendAuthority("mem0", target),
    )
    suite = SchedulerSuiteAuthority(
        suite_id=base.suite_id,
        publication_bundle_sha256=base.publication_bundle_sha256,
        methodology_sha256=base.methodology_sha256,
        source_commit_sha256=base.source_commit_sha256,
        bridge_boot=base.bridge_boot,
        ordered_runs=tuple(replace(binding, backends=backends) for binding in base.ordered_runs),
    )
    prepared: list[
        tuple[
            SchedulerBenchmark,
            str,
            str,
            str,
            ManagedMem0V5ManifestAuthority,
            Mem0OssFullRunAdmission,
            str,
            bytes,
            str,
            int,
        ]
    ] = []
    for index, binding in enumerate(suite.ordered_runs):
        benchmark = binding.profile.benchmark
        _case, raw_scope, raw_thread = _source_case(benchmark)
        manifest = _manifest(benchmark, case_count=binding.profile.case_count)
        admission = _admission(run_id=binding.run_id, manifest=manifest, index=index)
        query = f"What is the admitted {benchmark.value} fact?"
        bearer = f"managed-retrieval-bearer-{index}-private-value"
        evidence_key = bytes([71 + index]) * 32
        prepared.append(
            (
                benchmark,
                raw_scope,
                raw_thread,
                query,
                manifest,
                admission,
                bearer,
                evidence_key,
                manifest.units[0].source_id,
                51 if index == 0 else 1,
            )
        )
    expected = tuple(
        _ExpectedSearch(
            benchmark=benchmark.value,
            admission_commitment_sha256=admission.commitment_sha256,
            ingestion_manifest_sha256=manifest.ingestion_manifest_sha256,
            ingestion_root_sha256=manifest.ingestion_root_sha256,
            expected_operation_count=manifest.operation_count,
            route_sha256=admission.request.route_sha256,
            runtime_binding_commitment_sha256=_sha(
                f"subscription-runtime-binding:{benchmark.value}"
            ),
            corpus_id=manifest.units[0].corpus_id,
            query=query,
            bearer=bearer,
            evidence_key=evidence_key,
            source_id=source_id,
            source_sha256=manifest.units[0].source_sha256,
            observation_date=manifest.units[0].observation_date,
            result_count=result_count,
        )
        for (
            benchmark,
            _raw_scope,
            _raw_thread,
            query,
            manifest,
            admission,
            bearer,
            evidence_key,
            source_id,
            result_count,
        ) in prepared
    )
    transport = _SearchOnlyTransport(expected)  # type: ignore[arg-type]
    runs = tuple(
        _RunFixture(
            benchmark=benchmark,
            raw_scope=raw_scope,
            raw_thread=raw_thread,
            query=query,
            manifest=manifest,
            admission=admission,
            runtime_binding_commitment_sha256=(expected[index].runtime_binding_commitment_sha256),
            lane=_lane(
                bearer=bearer,
                evidence_key=evidence_key,
                transport=transport,
            ),
            expected=expected[index],
        )
        for index, (
            benchmark,
            raw_scope,
            raw_thread,
            query,
            manifest,
            admission,
            bearer,
            evidence_key,
            _source_id,
            _result_count,
        ) in enumerate(prepared)
    )
    configuration = _configuration(runs, target=target)  # type: ignore[arg-type]
    return _Harness(
        suite=suite,
        configuration=configuration,
        adapter=ManagedMem0V5SchedulerRetrievalAdapter(
            suite=suite,
            configuration=configuration,
        ),
        transport=transport,
        runs=runs,  # type: ignore[arg-type]
    )


@pytest.fixture
def harness(base_harness: _Harness) -> _Harness:
    base_harness.transport.reset()
    yield replace(
        base_harness,
        adapter=ManagedMem0V5SchedulerRetrievalAdapter(
            suite=base_harness.suite,
            configuration=base_harness.configuration,
        ),
    )
    base_harness.transport.reset()


def _request(harness: _Harness, index: int) -> SchedulerBackendRetrievalRequest:
    fixture = harness.runs[index]
    binding = harness.suite.ordered_runs[index]
    run = run_authority_from_suite(harness.suite, run_index=index)
    return SchedulerBackendRetrievalRequest(
        case_key=SchedulerOfficialCaseKey(
            suite_authority_sha256=harness.suite.commitment_sha256,
            run_authority_sha256=run.commitment_sha256,
            run_binding_commitment_sha256=binding.binding_commitment_sha256,
            run_id=binding.run_id,
            benchmark=binding.profile.benchmark,
            scheduler_profile_id=binding.profile.profile_id,
            publishable_profile_id=PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
            publishable_profile_sha256=(PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256),
            methodology_sha256=harness.suite.methodology_sha256,
            dataset_sha256=binding.dataset_sha256,
            case_manifest_sha256=binding.case_manifest_sha256,
            case_index=0,
            case_id=f"{binding.profile.benchmark.value}-case-0",
            case_alias=f"{binding.profile.benchmark.value}-0",
            authority_root_sha256=_sha("official-case-root"),
        ),
        case_material_sha256=_sha(f"case-material:{index}"),
        backend_index=1,
        backend_role="mem0",
        target_identity_sha256=(harness.suite.ordered_backend_identities[1].target_identity_sha256),
        question=fixture.query,
        memory_scope_external_ref=fixture.raw_scope,
        thread_external_ref=fixture.raw_thread,
    )


def test_managed_adapter_construction_is_provider_free(harness: _Harness) -> None:
    assert harness.adapter.target_identity_sha256 == (
        harness.suite.ordered_backend_identities[1].target_identity_sha256
    )
    assert harness.transport.admission_calls == []
    assert harness.transport.calls == []
    assert harness.transport.events == []


def test_managed_adapter_selects_each_run_and_maps_authenticated_evidence(
    harness: _Harness,
) -> None:
    locomo_request = _request(harness, 0)
    locomo = harness.adapter.retrieve_exact(request=locomo_request)
    longmemeval_request = _request(harness, 1)
    longmemeval = harness.adapter.retrieve_exact(request=longmemeval_request)

    assert locomo.is_bound_to(locomo_request)
    assert longmemeval.is_bound_to(longmemeval_request)
    assert len(locomo.memories) == SCHEDULER_OFFICIAL_ANSWER_CUTOFF == 50
    assert len(longmemeval.memories) == 1
    first = locomo.memories[0]
    expected = harness.runs[0].expected
    assert first.text == "locomo signed memory 000"
    assert first.rank == 1
    assert first.score == 0.0
    assert first.item_id == "locomo-record-000"
    assert first.created_at == expected.observation_date
    assert first.source_refs == ()
    assert first.metadata == {}
    assert locomo.memories[-1].rank == 50
    assert locomo.memories[-1].item_id == "locomo-record-049"
    assert all(item.item_id != "record-050" for item in locomo.memories)
    assert tuple(item.admission_commitment_sha256 for item in harness.transport.calls) == tuple(
        item.admission.commitment_sha256 for item in harness.runs
    )
    assert tuple(
        item.admission_commitment_sha256 for item in harness.transport.admission_calls
    ) == tuple(item.admission.commitment_sha256 for item in harness.runs)
    assert harness.transport.events == [
        ("admit", harness.runs[0].admission.commitment_sha256),
        ("search", harness.runs[0].admission.commitment_sha256),
        ("admit", harness.runs[1].admission.commitment_sha256),
        ("search", harness.runs[1].admission.commitment_sha256),
    ]
    assert all(item.limit == SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT for item in harness.transport.calls)


def test_managed_adapter_admits_once_for_repeated_run_searches(harness: _Harness) -> None:
    request = _request(harness, 0)

    harness.adapter.retrieve_exact(request=request)
    harness.adapter.retrieve_exact(request=request)

    assert len(harness.transport.admission_calls) == 1
    assert len(harness.transport.calls) == 2
    assert [event[0] for event in harness.transport.events] == ["admit", "search", "search"]


@pytest.mark.parametrize(
    ("tamper_mode", "expected_code"),
    (
        ("admission-commitment", "scheduler_managed_mem0_v5_admission_failed"),
        ("admission-runtime", "scheduler_managed_mem0_v5_admission_cross_wire"),
        ("admission-accepted", "scheduler_managed_mem0_v5_admission_failed"),
    ),
)
def test_managed_adapter_rejects_tampered_admission_before_search(
    harness: _Harness,
    tamper_mode: str,
    expected_code: str,
) -> None:
    harness.transport.tamper_mode = tamper_mode

    with pytest.raises(SchedulerRetrievalCaptureError) as error:
        harness.adapter.retrieve_exact(request=_request(harness, 0))

    assert error.value.code == expected_code
    assert len(harness.transport.admission_calls) == 1
    assert harness.transport.calls == []
    assert [event[0] for event in harness.transport.events] == ["admit"]


@pytest.mark.parametrize(
    ("tamper_mode", "expected_code"),
    (
        ("hmac", "scheduler_managed_mem0_v5_search_failed"),
        ("source", "scheduler_managed_mem0_v5_search_cross_wire"),
    ),
)
def test_managed_adapter_rejects_tampered_evidence_without_retry(
    harness: _Harness,
    tamper_mode: str,
    expected_code: str,
) -> None:
    harness.transport.tamper_mode = tamper_mode
    with pytest.raises(SchedulerRetrievalCaptureError) as error:
        harness.adapter.retrieve_exact(request=_request(harness, 0))
    assert error.value.code == expected_code
    assert len(harness.transport.calls) == 1


def test_managed_adapter_rejects_missing_corpus_and_cross_wire_without_http(
    harness: _Harness,
) -> None:
    request = _request(harness, 0)
    missing = replace(
        request,
        memory_scope_external_ref="not-the-admitted-corpus-scope",
    )
    with pytest.raises(SchedulerRetrievalCaptureError) as error:
        harness.adapter.retrieve_exact(request=missing)
    assert error.value.code == "scheduler_managed_mem0_v5_corpus_cross_wire"

    cross_run_key = replace(
        request.case_key,
        benchmark=SchedulerBenchmark.LONGMEMEVAL,
    )
    cross_run = replace(request, case_key=cross_run_key)
    with pytest.raises(SchedulerRetrievalCaptureError) as error:
        harness.adapter.retrieve_exact(request=cross_run)
    assert error.value.code == "scheduler_managed_mem0_v5_run_cross_wire"

    cross_target = replace(request, target_identity_sha256=_sha("other-mem0-target"))
    with pytest.raises(SchedulerRetrievalCaptureError) as error:
        harness.adapter.retrieve_exact(request=cross_target)
    assert error.value.code == "scheduler_managed_mem0_v5_request_invalid"
    assert harness.transport.admission_calls == []
    assert harness.transport.calls == []


def test_managed_adapter_is_not_serializable(harness: _Harness) -> None:
    with pytest.raises((TypeError, pickle.PicklingError, PublishableRunError)):
        pickle.dumps(harness.adapter)

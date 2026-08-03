from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from infinity_context_server import memory_comparison_managed_http_policy_lifecycle as policy
from infinity_context_server.memory_comparison_benchmark_identity import (
    mem0_benchmark_corpus_user_id,
)
from infinity_context_server.memory_comparison_managed_http_derived_evidence import (
    ManagedDerivedEvidenceHttpClient,
)
from infinity_context_server.memory_comparison_managed_http_exact_cleanup import (
    ManagedExactCleanupError,
    ManagedInfinityExactCleanupCoordinator,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedHttpIngestEvidenceView,
)
from infinity_context_server.memory_comparison_managed_http_policy_lifecycle import (
    ManagedHttpPolicyDeleteReceipt,
    ManagedHttpPolicyLifecycleError,
    ManagedHttpPolicyTerminalDeleteReceipt,
)
from infinity_context_server.memory_comparison_managed_http_policy_requirements import (
    managed_ingest_identity_manifest_sha256,
)
from infinity_context_server.memory_comparison_managed_http_policy_validation import (
    VerifiedManagedHttpPolicyValidation,
    public_managed_http_policy_validation,
)
from infinity_context_server.memory_comparison_models import BackendIngestResult
from memory_comparison_managed_http_policy_lifecycle_test_support import (
    _ATTESTATION,
    _SECRET_INFINITY,
    _SECRET_MEM0,
    _adapter,
    _cleanup_ready_lifecycle,
    _complete_lifecycle,
    _factory,
    _graph_manifest,
    _graphiti_delete_data,
    _locomo_case,
    _presence_data,
    _seal,
    _snapshot_json,
    _TrackingTransport,
    _views,
)
from test_memory_comparison_managed_http_exact_cleanup import (
    _config as _exact_config,
)
from test_memory_comparison_managed_http_exact_cleanup import (
    _factory as _exact_factory,
)
from test_memory_comparison_managed_http_exact_cleanup import (
    _graph_delete_data as _exact_graph_delete_data,
)
from test_memory_comparison_managed_http_exact_cleanup import (
    _manifest as _exact_manifest,
)
from test_memory_comparison_managed_http_exact_cleanup import (
    _presence as _exact_presence,
)
from test_memory_comparison_managed_http_exact_cleanup import (
    _qdrant_delete_data as _exact_qdrant_delete_data,
)
from test_memory_comparison_managed_http_exact_cleanup import (
    _scope as _exact_scope,
)


def test_exact_infinity_two_pass_cleanup_and_mem0_receipts_are_sealed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _locomo_case()
    derived_requests: list[httpx.Request] = []
    derived_transports: list[_TrackingTransport] = []
    graph_delete_count = 0

    def derived(request: httpx.Request) -> httpx.Response:
        nonlocal graph_delete_count
        derived_requests.append(request)
        if request.url.path.endswith("/presence"):
            return httpx.Response(200, json={"data": _presence_data()})
        data = _graphiti_delete_data()
        if graph_delete_count == 1:
            empty = {key: [] for key in _snapshot_json(_graph_manifest())}
            data["delete_expected"] = empty
            data["passes"][0]["before"] = empty  # type: ignore[index]
            data["passes"][0]["deleted"] = empty  # type: ignore[index]
        graph_delete_count += 1
        return httpx.Response(200, json={"data": data})

    canonical_transports: list[_TrackingTransport] = []
    delete_count = 0

    def canonical(request: httpx.Request) -> httpx.Response:
        nonlocal delete_count
        assert request.headers["Authorization"] == f"Bearer {_SECRET_INFINITY}"
        data: dict[str, object] = {
            "id": "fact-1",
            "space_id": "space-1",
            "memory_scope_id": "scope-1",
            "thread_id": "thread-1",
            "status": "deleted",
        }
        if request.method == "DELETE":
            delete_count += 1
            data["indexing_status"] = "pending" if delete_count == 1 else "already_deleted"
        return httpx.Response(200, json={"data": data})

    mem0_requests: list[httpx.Request] = []
    mem0_transports: list[_TrackingTransport] = []

    def mem0(request: httpx.Request) -> httpx.Response:
        mem0_requests.append(request)
        assert request.headers["X-API-Key"] == _SECRET_MEM0
        return httpx.Response(200, json={"deleted": True, "verified_absent": True})

    adapter, bindings = _adapter(
        cases=(case,),
        derived_factory=_factory(derived, derived_transports),
        cleanup_factory=_factory(canonical, canonical_transports),
        mem0_factory=_factory(mem0, mem0_transports),
    )
    canonical_receipts = _seal(adapter, bindings, (case,), _views(case), monkeypatch)
    delete_receipts = []
    for pass_index in (1, 2):
        for target in bindings.backend_targets:
            delete_receipts.append(
                adapter.terminal_delete(
                    bindings=bindings,
                    backend_role=target.backend_role,
                    target_identity_sha256=target.target_identity_sha256,
                    pass_index=pass_index,
                )
            )

    assert all(type(item) is ManagedHttpPolicyDeleteReceipt for item in delete_receipts)
    terminal = adapter.seal_terminal_delete(
        bindings=bindings,
        managed_attestation=_ATTESTATION,
        managed_attestation_commitment_sha256="6" * 64,
        receipts=tuple(delete_receipts),
    )
    assert type(terminal) is ManagedHttpPolicyTerminalDeleteReceipt
    assert [request.method for request in mem0_requests] == ["DELETE", "DELETE"]
    assert [request.method for request in derived_requests] == ["POST", "POST", "POST"]
    assert delete_count == 2
    assert len(canonical_transports) == 4
    assert all(
        item.closed for item in (*derived_transports, *canonical_transports, *mem0_transports)
    )
    validation = adapter.aggregate_policy(
        bindings=bindings,
        managed_attestation=_ATTESTATION,
        managed_attestation_commitment_sha256="6" * 64,
        canonical_source=canonical_receipts,
        terminal_delete=terminal,
    )
    assert type(validation) is VerifiedManagedHttpPolicyValidation
    report = public_managed_http_policy_validation(validation)
    assert report["execution_case_manifest_sha256"] == "4" * 64
    assert report["case_count"] == report["unique_corpus_count"] == 1
    assert report["cleanup_pass_count"] == 4


def test_mem0_terminal_cleanup_proves_each_exact_corpus_user_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, bindings, _ = _cleanup_ready_lifecycle(monkeypatch)
    first = adapter._corpora[0]
    second_manifest = replace(
        first.bundle.manifest,
        corpus_id="corpus-2",
        infinity_fact_ids=("fact-2",),
        infinity_source_ids=("source-2",),
        infinity_source_sha256=("b" * 64,),
        mem0_created_memory_ids=("memory-2",),
        mem0_source_ids=("source-2",),
        mem0_source_sha256=("b" * 64,),
    )
    second_bundle = replace(
        first.bundle,
        case_id="case-2",
        corpus_id="corpus-2",
        manifest=second_manifest,
    )
    adapter._corpora = (first, type(first)(second_bundle, first.presence))
    seen_scopes: list[tuple[str, str]] = []

    def mem0(request: httpx.Request) -> httpx.Response:
        seen_scopes.append((str(request.url.params["user_id"]), str(request.url.params["run_id"])))
        return httpx.Response(200, json={"deleted": True, "verified_absent": True})

    client = httpx.Client(
        base_url="https://mem0.test",
        transport=httpx.MockTransport(mem0),
    )
    try:
        state = adapter._delete_mem0(
            client,
            bindings.backend_targets[1].target_identity_sha256,
            1,
        )
    finally:
        client.close()

    assert seen_scopes == [
        (
            mem0_benchmark_corpus_user_id(bindings.run_id, first.bundle.corpus_id),
            bindings.run_id,
        ),
        (mem0_benchmark_corpus_user_id(bindings.run_id, "corpus-2"), bindings.run_id),
    ]
    assert state.source_scope_count == 2
    assert state.backend_verified_absent is True
    assert len(state.cleanup_commitment_sha256) == 64


def test_terminal_cleanup_before_presence_seal_fails_without_io() -> None:
    case = _locomo_case()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, bindings = _adapter(
        cases=(case,),
        derived_factory=lambda: httpx.MockTransport(handler),
        cleanup_factory=lambda: httpx.MockTransport(handler),
    )
    target = bindings.backend_targets[0]
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_delete_phase_invalid$",
    ):
        adapter.terminal_delete(
            bindings=bindings,
            backend_role=target.backend_role,
            target_identity_sha256=target.target_identity_sha256,
            pass_index=1,
        )
    assert calls == 0


def test_malformed_manifest_fails_before_presence_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _locomo_case()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, bindings = _adapter(
        cases=(case,), derived_factory=lambda: httpx.MockTransport(handler)
    )
    infinity, mem0 = _views(case)
    broken_metadata = dict(infinity.ingest_result.metadata)
    broken_metadata.pop("ingest_identity_manifest")
    broken = ManagedHttpIngestEvidenceView(
        infinity.backend_role,
        infinity.target_identity_sha256,
        infinity.case_id,
        infinity.corpus_id,
        infinity.clean_state_validation,
        BackendIngestResult(
            items_processed=1,
            operations=infinity.ingest_result.operations,
            metadata=broken_metadata,
        ),
        None,
        (),
    )
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_ingest_evidence_consumption_failed$",
    ):
        _seal(adapter, bindings, (case,), (broken, mem0), monkeypatch)
    assert calls == 0


@pytest.mark.parametrize(
    ("failure_stage", "expected_error"),
    (
        ("material", "managed_http_policy_ingest_evidence_consumption_failed"),
        ("registry", "managed_http_policy_canonical_receipt_issuance_failed"),
    ),
)
def test_complete_presence_allows_cleanup_only_after_late_canonical_seal_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    expected_error: str,
) -> None:
    case = _locomo_case()
    events: list[str] = []
    graph_delete_count = 0

    def derived(request: httpx.Request) -> httpx.Response:
        nonlocal graph_delete_count
        if request.url.path.endswith("/presence"):
            events.append("presence")
            return httpx.Response(200, json={"data": _presence_data()})
        graph_delete_count += 1
        events.append(f"graphiti-{graph_delete_count}")
        data = _graphiti_delete_data()
        if graph_delete_count == 2:
            empty = {key: [] for key in _snapshot_json(_graph_manifest())}
            data["delete_expected"] = empty
            data["passes"][0]["before"] = empty  # type: ignore[index]
            data["passes"][0]["deleted"] = empty  # type: ignore[index]
        return httpx.Response(200, json={"data": data})

    canonical_delete_count = 0

    def canonical(request: httpx.Request) -> httpx.Response:
        nonlocal canonical_delete_count
        events.append(f"canonical-{request.method.lower()}")
        data: dict[str, object] = {
            "id": "fact-1",
            "space_id": "space-1",
            "memory_scope_id": "scope-1",
            "thread_id": "thread-1",
            "status": "deleted",
        }
        if request.method == "DELETE":
            canonical_delete_count += 1
            data["indexing_status"] = (
                "pending" if canonical_delete_count == 1 else "already_deleted"
            )
        return httpx.Response(200, json={"data": data})

    mem0_pass = 0

    def mem0(request: httpx.Request) -> httpx.Response:
        nonlocal mem0_pass
        mem0_pass += 1
        events.append(f"mem0-{mem0_pass}")
        return httpx.Response(200, json={"deleted": True, "verified_absent": True})

    adapter, bindings = _adapter(
        cases=(case,),
        derived_factory=lambda: httpx.MockTransport(derived),
        cleanup_factory=lambda: httpx.MockTransport(canonical),
        mem0_factory=lambda: httpx.MockTransport(mem0),
    )
    receipt_issue_calls = 0
    real_issue_canonical_receipt = policy.issue_canonical_receipt

    def issue_canonical_receipt(state):
        nonlocal receipt_issue_calls
        receipt_issue_calls += 1
        if failure_stage == "registry":
            raise RuntimeError("injected registry failure")
        return real_issue_canonical_receipt(state)

    monkeypatch.setattr(policy, "issue_canonical_receipt", issue_canonical_receipt)
    if failure_stage == "material":

        def fail_material(*args, **kwargs):
            raise RuntimeError("injected material failure")

        monkeypatch.setattr(policy, "project_corpus_material", fail_material)

    with pytest.raises(ManagedHttpPolicyLifecycleError, match=f"^{expected_error}$"):
        _seal(adapter, bindings, (case,), _views(case), monkeypatch)

    assert receipt_issue_calls == (1 if failure_stage == "registry" else 0)
    delete_receipts = tuple(
        adapter.terminal_delete(
            bindings=bindings,
            backend_role=target.backend_role,
            target_identity_sha256=target.target_identity_sha256,
            pass_index=pass_index,
        )
        for pass_index in (1, 2)
        for target in bindings.backend_targets
    )
    assert all(type(item) is ManagedHttpPolicyDeleteReceipt for item in delete_receipts)
    terminal = adapter.seal_terminal_delete(
        bindings=bindings,
        managed_attestation=_ATTESTATION,
        managed_attestation_commitment_sha256="6" * 64,
        receipts=delete_receipts,
    )
    assert type(terminal) is ManagedHttpPolicyTerminalDeleteReceipt
    assert events == [
        "presence",
        "graphiti-1",
        "canonical-delete",
        "canonical-get",
        "mem0-1",
        "graphiti-2",
        "canonical-delete",
        "canonical-get",
        "mem0-2",
    ]
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_canonical_source_replay$",
    ):
        _seal(adapter, bindings, (case,), _views(case), monkeypatch)
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_canonical_coverage_invalid$",
    ):
        adapter.aggregate_policy(
            bindings=bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256="6" * 64,
            canonical_source=(),
            terminal_delete=terminal,
        )


def test_delete_reservation_blocks_pass_two_until_receipt_is_issued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, bindings, canonical = _cleanup_ready_lifecycle(monkeypatch)
    infinity, mem0 = bindings.backend_targets
    entered = Event()
    release = Event()
    issued: list[tuple[str, int]] = []
    real_issue_delete_receipt = policy.issue_delete_receipt

    def delayed_issue_delete_receipt(state):
        issued.append((state.backend_role, state.pass_index))
        if len(issued) == 1:
            entered.set()
            assert release.wait(timeout=5)
        return real_issue_delete_receipt(state)

    monkeypatch.setattr(policy, "issue_delete_receipt", delayed_issue_delete_receipt)
    first_arguments = {
        "bindings": bindings,
        "backend_role": infinity.backend_role,
        "target_identity_sha256": infinity.target_identity_sha256,
        "pass_index": 1,
    }
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(adapter.terminal_delete, **first_arguments)
        assert entered.wait(timeout=5)
        with pytest.raises(
            ManagedHttpPolicyLifecycleError,
            match="^managed_http_policy_delete_in_progress$",
        ):
            adapter.terminal_delete(
                bindings=bindings,
                backend_role=infinity.backend_role,
                target_identity_sha256=infinity.target_identity_sha256,
                pass_index=2,
            )
        assert issued == [("infinity-context", 1)]
        release.set()
        first_receipt = first.result(timeout=5)

    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_delete_order_invalid$",
    ):
        adapter.terminal_delete(
            bindings=bindings,
            backend_role=infinity.backend_role,
            target_identity_sha256=infinity.target_identity_sha256,
            pass_index=2,
        )

    remaining = tuple(
        adapter.terminal_delete(
            bindings=bindings,
            backend_role=target.backend_role,
            target_identity_sha256=target.target_identity_sha256,
            pass_index=pass_index,
        )
        for target, pass_index in ((mem0, 1), (infinity, 2), (mem0, 2))
    )
    terminal = adapter.seal_terminal_delete(
        bindings=bindings,
        managed_attestation=_ATTESTATION,
        managed_attestation_commitment_sha256="6" * 64,
        receipts=(first_receipt, *remaining),
    )
    assert type(terminal) is ManagedHttpPolicyTerminalDeleteReceipt
    assert len(canonical) == 1
    assert issued == [
        ("infinity-context", 1),
        ("mem0", 1),
        ("infinity-context", 2),
        ("mem0", 2),
    ]


@pytest.mark.parametrize(
    ("failure_stage", "expected_error"),
    (
        ("cleanup", "managed_http_policy_infinity_context_delete_failed"),
        ("receipt", "managed_http_policy_delete_receipt_issuance_failed"),
        ("close", "managed_http_policy_mem0_delete_failed"),
    ),
)
def test_delete_failure_consumes_ordinal_and_remaining_cleanup_still_runs(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    expected_error: str,
) -> None:
    adapter, bindings, _ = _cleanup_ready_lifecycle(monkeypatch)
    infinity, mem0 = bindings.backend_targets
    attempts: list[tuple[str, int]] = []
    real_infinity = adapter._delete_infinity
    real_mem0 = adapter._delete_mem0
    real_issue = policy.issue_delete_receipt
    real_client = adapter._client

    def delete_infinity(target, pass_index):
        attempts.append(("infinity-context", pass_index))
        if failure_stage == "cleanup" and pass_index == 1:
            raise RuntimeError(_SECRET_INFINITY)
        return real_infinity(target, pass_index)

    def delete_mem0(client, target, pass_index):
        attempts.append(("mem0", pass_index))
        return real_mem0(client, target, pass_index)

    def issue_receipt(state):
        if (
            failure_stage == "receipt"
            and state.backend_role == "infinity-context"
            and state.pass_index == 1
        ):
            raise RuntimeError(_SECRET_INFINITY)
        return real_issue(state)

    close_injected = False

    def client(role):
        nonlocal close_injected
        value = real_client(role)
        if failure_stage != "close" or close_injected:
            return value
        close_injected = True

        def fail_close() -> None:
            value.close()
            raise RuntimeError(_SECRET_MEM0)

        return SimpleNamespace(delete=value.delete, close=fail_close)

    monkeypatch.setattr(adapter, "_delete_infinity", delete_infinity)
    monkeypatch.setattr(adapter, "_delete_mem0", delete_mem0)
    monkeypatch.setattr(policy, "issue_delete_receipt", issue_receipt)
    monkeypatch.setattr(adapter, "_client", client)

    receipts: list[object] = []
    errors: list[ManagedHttpPolicyLifecycleError] = []
    for pass_index in (1, 2):
        for target in (infinity, mem0):
            try:
                receipts.append(
                    adapter.terminal_delete(
                        bindings=bindings,
                        backend_role=target.backend_role,
                        target_identity_sha256=target.target_identity_sha256,
                        pass_index=pass_index,
                    )
                )
            except ManagedHttpPolicyLifecycleError as exc:
                errors.append(exc)

    assert attempts == [
        ("infinity-context", 1),
        ("mem0", 1),
        ("infinity-context", 2),
        ("mem0", 2),
    ]
    assert errors and errors[0].code == expected_error
    assert all(_SECRET_INFINITY not in str(error) for error in errors)
    assert all(_SECRET_MEM0 not in str(error) for error in errors)
    assert len(receipts) < 4
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_delete_coverage_invalid$",
    ):
        adapter.seal_terminal_delete(
            bindings=bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256="6" * 64,
            receipts=tuple(receipts),
        )


def test_aggregate_reservation_rejects_concurrent_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, bindings, canonical, terminal, _ = _complete_lifecycle(monkeypatch)
    entered = Event()
    release = Event()
    real_seal = policy.seal_managed_http_policy_validation

    def delayed_seal(*, material):
        entered.set()
        assert release.wait(timeout=5)
        return real_seal(material=material)

    monkeypatch.setattr(policy, "seal_managed_http_policy_validation", delayed_seal)
    arguments = {
        "bindings": bindings,
        "managed_attestation": _ATTESTATION,
        "managed_attestation_commitment_sha256": "6" * 64,
        "canonical_source": canonical,
        "terminal_delete": terminal,
    }
    with ThreadPoolExecutor(max_workers=1) as executor:
        primary = executor.submit(adapter.aggregate_policy, **arguments)
        assert entered.wait(timeout=5)
        with pytest.raises(
            ManagedHttpPolicyLifecycleError,
            match="^managed_http_policy_aggregate_replay$",
        ):
            adapter.aggregate_policy(**arguments)
        release.set()
        assert type(primary.result(timeout=5)) is VerifiedManagedHttpPolicyValidation


def test_exact_cleanup_continues_all_lanes_and_recovers_with_readback() -> None:
    events: list[str] = []
    qdrant_calls = 0
    graphiti_calls = 0

    def derived_handler(request: httpx.Request) -> httpx.Response:
        nonlocal graphiti_calls, qdrant_calls
        if request.url.path.endswith("/qdrant/delete"):
            qdrant_calls += 1
            events.append("qdrant")
            if qdrant_calls == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"data": _exact_qdrant_delete_data()})
        graphiti_calls += 1
        events.append("graphiti")
        return httpx.Response(
            200,
            json={"data": _exact_graph_delete_data(replay=graphiti_calls == 2)},
        )

    derived = ManagedDerivedEvidenceHttpClient(
        config=_exact_config(),
        transport_factory=_exact_factory(derived_handler, []),
    )
    successful_deletes: dict[str, int] = {}
    fact_one_failed = False

    def canonical_handler(request: httpx.Request) -> httpx.Response:
        nonlocal fact_one_failed
        identity = request.url.path.rsplit("/", 1)[-1]
        events.append(f"{request.method}:{identity}")
        if request.method == "DELETE" and identity == "fact-1" and not fact_one_failed:
            fact_one_failed = True
            return httpx.Response(503)
        data: dict[str, object] = {
            "id": identity,
            "space_id": "space-1",
            "memory_scope_id": "scope-1",
            "thread_id": "thread-1",
            "status": "deleted",
        }
        if request.method == "DELETE":
            successful_deletes[identity] = successful_deletes.get(identity, 0) + 1
            data["indexing_status"] = (
                "pending" if successful_deletes[identity] == 1 else "already_deleted"
            )
        return httpx.Response(200, json={"data": data})

    coordinator = ManagedInfinityExactCleanupCoordinator(
        config=_exact_config(),
        derived_evidence=derived,
        transport_factory=_exact_factory(canonical_handler, []),
    )
    manifest = _exact_manifest(
        facts=("fact-1", "fact-2"),
        documents=("document-1", "document-2"),
    )
    presence = _exact_presence(manifest)

    with pytest.raises(ManagedExactCleanupError) as first_failure:
        coordinator.cleanup(
            scope=_exact_scope(),
            manifest=manifest,
            presence=presence,
            pass_index=1,
        )

    assert first_failure.value.code == "managed_exact_cleanup_incomplete"
    assert events == [
        "qdrant",
        "graphiti",
        "DELETE:fact-1",
        "DELETE:fact-2",
        "GET:fact-2",
        "DELETE:document-1",
        "GET:document-1",
        "DELETE:document-2",
        "GET:document-2",
    ]

    events.clear()
    recovered = coordinator.cleanup(
        scope=_exact_scope(),
        manifest=manifest,
        presence=presence,
        pass_index=2,
    )

    assert [item.disposition for item in recovered.canonical] == [
        "recovered_absent",
        "already_absent",
        "already_absent",
        "already_absent",
    ]
    assert events == [
        "qdrant",
        "graphiti",
        "DELETE:fact-1",
        "GET:fact-1",
        "DELETE:fact-2",
        "GET:fact-2",
        "DELETE:document-1",
        "GET:document-1",
        "DELETE:document-2",
        "GET:document-2",
    ]


def test_first_corpus_failure_attempts_later_corpus_and_blocks_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, bindings, canonical = _cleanup_ready_lifecycle(monkeypatch)
    first = adapter._corpora[0]
    second_manifest = replace(first.bundle.manifest, corpus_id="corpus-2")
    second_bundle = replace(
        first.bundle,
        case_id="case-2",
        corpus_id="corpus-2",
        manifest=second_manifest,
    )
    second_presence = replace(
        first.presence,
        ingest_manifest_sha256=managed_ingest_identity_manifest_sha256(
            second_manifest,
            first.bundle.scope,
        ),
    )
    adapter._corpora = (first, type(first)(second_bundle, second_presence))
    attempts: list[str] = []
    real_cleanup = adapter._exact_cleanup.cleanup

    def fail_first_corpus(**kwargs):
        attempts.append(kwargs["manifest"].corpus_id)
        if len(attempts) == 1:
            raise RuntimeError(_SECRET_INFINITY)
        return real_cleanup(**kwargs)

    monkeypatch.setattr(adapter._exact_cleanup, "cleanup", fail_first_corpus)
    infinity = bindings.backend_targets[0]
    with pytest.raises(ManagedHttpPolicyLifecycleError) as cleanup_failure:
        adapter.terminal_delete(
            bindings=bindings,
            backend_role=infinity.backend_role,
            target_identity_sha256=infinity.target_identity_sha256,
            pass_index=1,
        )

    assert cleanup_failure.value.code == "managed_http_policy_infinity_context_delete_failed"
    assert _SECRET_INFINITY not in str(cleanup_failure.value)
    assert attempts == [first.bundle.corpus_id, "corpus-2"]
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_delete_coverage_invalid$",
    ):
        adapter.seal_terminal_delete(
            bindings=bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256="6" * 64,
            receipts=(),
        )
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_aggregate_replay$",
    ):
        adapter.aggregate_policy(
            bindings=bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256="6" * 64,
            canonical_source=canonical,
            terminal_delete=object(),
        )

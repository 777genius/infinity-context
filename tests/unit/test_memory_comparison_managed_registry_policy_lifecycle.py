from __future__ import annotations

import hashlib
import json
import pickle
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from infinity_context_server import memory_comparison_managed_http_policy_lifecycle as policy
from infinity_context_server import (
    memory_comparison_managed_policy_delegate_capability as delegate_subject,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkCleanupCompletionReceipt,
    ManagedBenchmarkRegistryHttpConfig,
    ManagedBenchmarkRegistryHttpError,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_http_policy_support import (
    ManagedHttpPolicyLifecycleError,
)
from infinity_context_server.memory_comparison_managed_http_policy_validation import (
    public_managed_http_policy_validation,
)
from infinity_context_server.memory_comparison_managed_policy_delegate_capability import (
    ManagedPolicyDelegateCapabilityError,
    consume_managed_policy_delegate_capability,
)
from infinity_context_server.memory_comparison_managed_projection_manifest import (
    ManagedProjectionEpisodeInventory,
)
from infinity_context_server.memory_comparison_managed_registry_policy_lifecycle import (
    MANAGED_REGISTRY_POLICY_LIFECYCLE_ADAPTER_ID,
    ManagedComparisonRegistryPolicyLifecycleAdapter,
    ManagedRegistryPolicyLifecycleError,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from memory_comparison_managed_http_policy_lifecycle_test_support import (
    _ATTESTATION,
    _INFINITY_TARGET,
    _INFINITY_URL,
    _adapter,
    _locomo_case,
    _presence_data,
    _views,
)
from test_memory_comparison_managed_http_derived_evidence import (
    _graph_manifest,
    _graphiti_delete_data,
    _snapshot_json,
)

_SPACE_ID = "space-1"
_SPACE_SLUG = "memory-comparison-managed-registry-policy"
_TOKEN = "registry-secret"
_ATTESTATION_COMMITMENT = "6" * 64
_CASE_MANIFEST = "4" * 64


def _json_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass
class _RegistryBackend:
    run_id_sha256: str
    binding_commitment_sha256: str
    target_identity_sha256: str
    events: list[str]
    fail_seal: bool = False
    fail_begin_once: bool = False
    fail_finalize_once: bool = False

    def __post_init__(self) -> None:
        self.manifest_sha256: str | None = None
        self.manifest_json: dict[str, object] | None = None
        self.cleanup_receipt_sha256: str | None = None
        self.seal_attempts = 0
        self.begin_attempts = 0
        self.finalize_attempts = 0
        self.begin_keys: list[str] = []
        self.finalize_keys: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/runs"):
            self.events.append("registry.register")
            return httpx.Response(201, json={"data": self._registration()})
        if request.method == "PUT" and path.endswith("/projection-manifest"):
            self.events.append("registry.seal")
            self.seal_attempts += 1
            if self.fail_seal:
                raise RuntimeError("sealed response unavailable")
            payload = json.loads(request.content)
            self.manifest_sha256 = payload["projection_manifest_sha256"]
            self.manifest_json = payload["projection_manifest"]
            return httpx.Response(200, json={"data": self._seal()})
        if request.method == "DELETE" and path.endswith(self.run_id_sha256):
            self.events.append("registry.begin")
            self.begin_attempts += 1
            self.begin_keys.append(request.headers["Idempotency-Key"])
            if self.fail_begin_once and self.begin_attempts == 1:
                raise RuntimeError("cleanup response unavailable")
            return httpx.Response(200, json={"data": self._cleanup()})
        if request.method == "POST" and path.endswith("/cleanup/finalize"):
            self.events.append("registry.finalize")
            self.finalize_attempts += 1
            self.finalize_keys.append(request.headers["Idempotency-Key"])
            if self.fail_finalize_once and self.finalize_attempts == 1:
                raise RuntimeError("finalize response unavailable")
            payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={"data": self._completion(payload["receipt_sha256"])},
            )
        raise AssertionError(f"unexpected registry request: {request.method} {path}")

    def _registration(self) -> dict[str, object]:
        return {
            "schema_version": "memory-comparison-run-registration-response.v1",
            "authority": "infinity_canonical",
            "run_id_sha256": self.run_id_sha256,
            "binding_commitment_sha256": self.binding_commitment_sha256,
            "infinity_target_identity_sha256": self.target_identity_sha256,
            "space_id": _SPACE_ID,
            "space_slug": _SPACE_SLUG,
            "state": "active",
            "created": True,
        }

    def _seal(self) -> dict[str, object]:
        assert self.manifest_sha256 is not None
        return {
            "schema_version": "memory-comparison-projection-manifest-seal-response.v1",
            "authority": "infinity_canonical",
            "run_id_sha256": self.run_id_sha256,
            "binding_commitment_sha256": self.binding_commitment_sha256,
            "infinity_target_identity_sha256": self.target_identity_sha256,
            "projection_manifest_sha256": self.manifest_sha256,
            "state": "active",
            "projection_cleanup_state": "sealed",
            "replayed": False,
        }

    def _cleanup(self) -> dict[str, object]:
        material = {
            "run_id_sha256": self.run_id_sha256,
            "space_id": _SPACE_ID,
            "space_slug": _SPACE_SLUG,
            "disposition": "cleanup_pending",
            "projection_cleanup": "pending",
            "counts": {
                "facts": 1,
                "documents": 0,
                "chunks": 0,
                "episodes": 0,
                "threads": 1,
                "memory_scopes": 1,
                "obsolete_upsert_jobs": 0,
                "vector_delete_jobs": 0,
                "graph_delete_jobs": 1,
                "cognee_delete_jobs": 0,
            },
            "vector_delete_outbox_ids": [],
            "graph_delete_outbox_ids": [201],
            "cognee_delete_outbox_ids": [],
        }
        self.cleanup_receipt_sha256 = _json_digest(material)
        return {
            "schema_version": "memory-comparison-run-cleanup-response.v1",
            "authority": "infinity_canonical",
            **material,
            "state": "cleanup_pending",
            "receipt_sha256": self.cleanup_receipt_sha256,
            "replayed": self.begin_attempts > 1,
        }

    def _completion(self, initiation: str) -> dict[str, object]:
        assert self.manifest_sha256 is not None
        assert initiation == self.cleanup_receipt_sha256
        material = {
            "run_id_sha256": self.run_id_sha256,
            "space_id": _SPACE_ID,
            "space_slug": _SPACE_SLUG,
            "disposition": "cleanup_complete",
            "projection_cleanup": "complete",
            "projection_manifest_sha256": self.manifest_sha256,
            "cleanup_initiation_receipt_sha256": initiation,
            "projection_absence_proof_sha256": "c" * 64,
            "completed_at": "2026-08-02T04:05:06.123456Z",
        }
        return {
            "schema_version": "memory-comparison-run-cleanup-finalize-response.v1",
            "authority": "infinity_canonical",
            **material,
            "state": "cleanup_complete",
            "receipt_sha256": _json_digest(material),
            "replayed": self.finalize_attempts > 1,
        }


def _policy_adapter(
    events: list[str],
    cases: tuple[ManagedRunCase, ...],
    *,
    fail_mem0_once: bool = False,
):
    graph_delete_count = 0

    def derived(request: httpx.Request) -> httpx.Response:
        nonlocal graph_delete_count
        if request.url.path.endswith("/presence"):
            events.append("delegate.presence")
            return httpx.Response(200, json={"data": _presence_data()})
        events.append("delegate.graph-delete")
        data = _graphiti_delete_data()
        if graph_delete_count == 1:
            empty = {key: [] for key in _snapshot_json(_graph_manifest())}
            data["delete_expected"] = empty
            data["passes"][0]["before"] = empty
            data["passes"][0]["deleted"] = empty
        graph_delete_count += 1
        return httpx.Response(200, json={"data": data})

    delete_count = 0

    def canonical(request: httpx.Request) -> httpx.Response:
        nonlocal delete_count
        events.append(f"delegate.canonical-{request.method.lower()}")
        data: dict[str, object] = {
            "id": "fact-1",
            "space_id": _SPACE_ID,
            "memory_scope_id": "scope-1",
            "thread_id": "thread-1",
            "status": "deleted",
        }
        if request.method == "DELETE":
            delete_count += 1
            data["indexing_status"] = "pending" if delete_count == 1 else "already_deleted"
        return httpx.Response(200, json={"data": data})

    mem0_count = 0

    def mem0(_: httpx.Request) -> httpx.Response:
        nonlocal mem0_count
        events.append("delegate.mem0-delete")
        mem0_count += 1
        if fail_mem0_once and mem0_count == 1:
            raise RuntimeError("mem0 response unavailable")
        return httpx.Response(200, json={"deleted": True, "verified_absent": True})

    return _adapter(
        cases=cases,
        derived_factory=lambda: httpx.MockTransport(derived),
        cleanup_factory=lambda: httpx.MockTransport(canonical),
        mem0_factory=lambda: httpx.MockTransport(mem0),
    )


def _wrapper(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_seal: bool = False,
    fail_begin_once: bool = False,
    fail_finalize_once: bool = False,
    fail_mem0_once: bool = False,
    canonical_episode_ids: tuple[str, ...] | None = None,
):
    events: list[str] = []
    cases = (_locomo_case(),)
    delegate, bindings = _policy_adapter(
        events,
        cases,
        fail_mem0_once=fail_mem0_once,
    )
    run_id_sha256 = hashlib.sha256(bindings.run_id.encode()).hexdigest()
    backend = _RegistryBackend(
        run_id_sha256,
        bindings.binding_commitment_sha256,
        _INFINITY_TARGET,
        events,
        fail_seal=fail_seal,
        fail_begin_once=fail_begin_once,
        fail_finalize_once=fail_finalize_once,
    )
    registry = ManagedBenchmarkRegistryHttpAdapter(
        ManagedBenchmarkRegistryHttpConfig(
            base_url=_INFINITY_URL,
            admin_bearer_token=_TOKEN,
            target_identity_sha256=_INFINITY_TARGET,
            timeout_seconds=30,
            benchmark_deadline=datetime.now(UTC) + timedelta(minutes=5),
            cleanup_recovery_timeout_seconds=600,
            transport=httpx.MockTransport(backend),
        )
    )
    registration = registry.register(
        run_id_sha256=run_id_sha256,
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        space_slug=_SPACE_SLUG,
    )
    monkeypatch.setattr(policy, "_attestation", lambda *args: None)
    views = _views(cases[0])
    if canonical_episode_ids is not None:
        views = tuple(
            replace(
                view,
                ingest_result=replace(
                    view.ingest_result,
                    metadata={
                        **view.ingest_result.metadata,
                        "canonical_episode_ids": list(canonical_episode_ids),
                    },
                ),
            )
            if view.backend_role == "infinity-context"
            else view
            for view in views
        )
    monkeypatch.setattr(
        policy,
        "consume_managed_http_ingest_receipts",
        lambda *args, **kwargs: views,
    )
    capability = delegate.issue_registry_delegate_capability()
    wrapper = ManagedComparisonRegistryPolicyLifecycleAdapter(
        delegate_capability=capability,
        registry=registry,
        bindings=bindings,
        cases=cases,
        registration=registration,
    )
    return wrapper, bindings, cases, backend, events


def _seal_source(wrapper, bindings, cases):
    ingest_receipts = (object(),)
    canonical = wrapper.seal_canonical_source(
        bindings=bindings,
        cases=cases,
        managed_attestation=_ATTESTATION,
        managed_attestation_commitment_sha256=_ATTESTATION_COMMITMENT,
        ingest_receipts=ingest_receipts,
        case_manifest_sha256=_CASE_MANIFEST,
    )
    return canonical, ingest_receipts


def _delete_all(wrapper, bindings):
    receipts = tuple(
        wrapper.terminal_delete(
            bindings=bindings,
            backend_role=target.backend_role,
            target_identity_sha256=target.target_identity_sha256,
            pass_index=pass_index,
        )
        for pass_index in (1, 2)
        for target in bindings.backend_targets
    )
    return receipts


def _seal_terminal(wrapper, bindings, receipts):
    return wrapper.seal_terminal_delete(
        bindings=bindings,
        managed_attestation=_ATTESTATION,
        managed_attestation_commitment_sha256=_ATTESTATION_COMMITMENT,
        receipts=receipts,
    )


def test_happy_path_seals_before_retrieval_and_finalizes_after_exact_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper, bindings, cases, backend, events = _wrapper(monkeypatch)

    canonical, _ = _seal_source(wrapper, bindings, cases)
    deletes = _delete_all(wrapper, bindings)
    terminal = _seal_terminal(wrapper, bindings, deletes)

    completion = wrapper.terminal_completion_receipt
    assert wrapper.adapter_id == MANAGED_REGISTRY_POLICY_LIFECYCLE_ADAPTER_ID
    assert type(completion) is ManagedBenchmarkCleanupCompletionReceipt
    assert completion.projection_cleanup == "complete"
    assert events.index("delegate.presence") < events.index("registry.seal")
    assert events.index("registry.begin") < events.index("delegate.canonical-delete")
    assert events[-1] == "registry.finalize"
    assert backend.seal_attempts == backend.begin_attempts == backend.finalize_attempts == 1
    assert backend.manifest_json is not None
    assert backend.manifest_json["schema_version"] == ("memory-comparison-projection-manifest.v1")
    assert "episode_ids" not in backend.manifest_json["scopes"][0]
    assert backend.manifest_sha256 == (
        "b98f702b8f8ad897289f89a5e9342bc74c4744661baa52cd18ea8060d64e4cdb"
    )

    validation = wrapper.aggregate_policy(
        bindings=bindings,
        managed_attestation=_ATTESTATION,
        managed_attestation_commitment_sha256=_ATTESTATION_COMMITMENT,
        canonical_source=canonical,
        terminal_delete=terminal,
    )
    assert validation is not None
    report = public_managed_http_policy_validation(validation)
    assert report["adapter_id"] == MANAGED_REGISTRY_POLICY_LIFECYCLE_ADAPTER_ID
    assert report["implementation_sha256"] == wrapper.implementation_sha256
    assert report["registry_evidence"] == {
        "registration_commitment_sha256": _json_digest(backend._registration()),
        "projection_manifest_sha256": backend.manifest_sha256,
        "cleanup_initiation_receipt_sha256": backend.cleanup_receipt_sha256,
        "completion_receipt_sha256": completion.receipt_sha256,
        "projection_absence_proof_sha256": "c" * 64,
        "wrapper_adapter_id": MANAGED_REGISTRY_POLICY_LIFECYCLE_ADAPTER_ID,
        "wrapper_implementation_sha256": wrapper.implementation_sha256,
    }
    with pytest.raises(
        ManagedRegistryPolicyLifecycleError,
        match="^managed_registry_policy_aggregate_phase_invalid$",
    ):
        wrapper.aggregate_policy(
            bindings=bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256=_ATTESTATION_COMMITMENT,
            canonical_source=canonical,
            terminal_delete=terminal,
        )


def test_production_wrapper_seals_v2_from_authenticated_episode_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper, bindings, cases, backend, _ = _wrapper(
        monkeypatch,
        canonical_episode_ids=("episode-1",),
    )

    _seal_source(wrapper, bindings, cases)

    assert backend.seal_attempts == 1
    assert backend.manifest_json is not None
    assert backend.manifest_json["schema_version"] == ("memory-comparison-projection-manifest.v2")
    assert backend.manifest_json["scopes"][0]["episode_ids"] == ["episode-1"]


def test_substituted_episode_inventory_is_rejected_before_registry_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper, bindings, cases, backend, _ = _wrapper(
        monkeypatch,
        canonical_episode_ids=("episode-1",),
    )
    delegate_type = policy.ManagedComparisonHttpPolicyLifecycleAdapter
    original_getter = delegate_type.exact_projection_evidence.fget
    assert original_getter is not None

    def substituted(delegate):
        evidence = original_getter(delegate)
        object.__setattr__(
            evidence,
            "episode_inventory",
            (
                ManagedProjectionEpisodeInventory(
                    evidence.corpora[0].scope,
                    ("episode-substituted",),
                ),
            ),
        )
        return evidence

    monkeypatch.setattr(
        delegate_type,
        "exact_projection_evidence",
        property(substituted),
    )

    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_episode_inventory_binding_invalid$",
    ):
        _seal_source(wrapper, bindings, cases)

    assert backend.seal_attempts == 0


def test_registry_evidence_tamper_fails_closed_and_cannot_be_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper, bindings, cases, _, _ = _wrapper(monkeypatch)
    canonical, _ = _seal_source(wrapper, bindings, cases)
    deletes = _delete_all(wrapper, bindings)
    terminal = _seal_terminal(wrapper, bindings, deletes)
    assert wrapper._registry_material is not None
    object.__setattr__(
        wrapper._registry_material,
        "completion_receipt_sha256",
        "d" * 64,
    )

    with pytest.raises(
        ManagedRegistryPolicyLifecycleError,
        match="^managed_registry_policy_evidence_integrity_failed$",
    ):
        wrapper.aggregate_policy(
            bindings=bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256=_ATTESTATION_COMMITMENT,
            canonical_source=canonical,
            terminal_delete=terminal,
        )
    with pytest.raises(
        ManagedRegistryPolicyLifecycleError,
        match="^managed_registry_policy_aggregate_phase_invalid$",
    ):
        wrapper.aggregate_policy(
            bindings=bindings,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256=_ATTESTATION_COMMITMENT,
            canonical_source=canonical,
            terminal_delete=terminal,
        )


def test_projection_seal_failure_is_propagated_and_source_replay_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper, bindings, cases, backend, _ = _wrapper(monkeypatch, fail_seal=True)
    ingest = (object(),)

    with pytest.raises(
        ManagedBenchmarkRegistryHttpError,
        match="^managed_benchmark_registry_request_failed$",
    ):
        wrapper.seal_canonical_source(
            bindings=bindings,
            cases=cases,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256=_ATTESTATION_COMMITMENT,
            ingest_receipts=ingest,
            case_manifest_sha256=_CASE_MANIFEST,
        )
    with pytest.raises(
        ManagedRegistryPolicyLifecycleError,
        match="^managed_registry_policy_canonical_source_replay$",
    ):
        wrapper.seal_canonical_source(
            bindings=bindings,
            cases=cases,
            managed_attestation=_ATTESTATION,
            managed_attestation_commitment_sha256=_ATTESTATION_COMMITMENT,
            ingest_receipts=ingest,
            case_manifest_sha256=_CASE_MANIFEST,
        )
    assert backend.seal_attempts == 1
    assert wrapper.terminal_completion_receipt is None


def test_begin_cleanup_unknown_outcome_recovers_with_same_key_before_provider_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper, bindings, cases, backend, events = _wrapper(
        monkeypatch,
        fail_begin_once=True,
    )
    _seal_source(wrapper, bindings, cases)
    infinity = bindings.backend_targets[0]

    with pytest.raises(
        ManagedBenchmarkRegistryHttpError,
        match="^managed_benchmark_registry_request_failed$",
    ):
        wrapper.terminal_delete(
            bindings=bindings,
            backend_role=infinity.backend_role,
            target_identity_sha256=infinity.target_identity_sha256,
            pass_index=1,
        )
    assert not any(item.startswith("delegate.canonical-") for item in events)

    wrapper.terminal_delete(
        bindings=bindings,
        backend_role=infinity.backend_role,
        target_identity_sha256=infinity.target_identity_sha256,
        pass_index=1,
    )
    assert backend.begin_attempts == 2
    assert backend.begin_keys[0] == backend.begin_keys[1]
    assert events.index("registry.begin") < events.index("delegate.canonical-delete")


def test_finalize_unknown_outcome_recovers_without_replaying_delegate_terminal_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper, bindings, cases, backend, _ = _wrapper(
        monkeypatch,
        fail_finalize_once=True,
    )
    _seal_source(wrapper, bindings, cases)
    deletes = _delete_all(wrapper, bindings)

    with pytest.raises(
        ManagedBenchmarkRegistryHttpError,
        match="^managed_benchmark_registry_request_failed$",
    ):
        _seal_terminal(wrapper, bindings, deletes)
    assert wrapper.terminal_completion_receipt is None

    terminal = _seal_terminal(wrapper, bindings, deletes)
    assert terminal is not None
    assert type(wrapper.terminal_completion_receipt) is ManagedBenchmarkCleanupCompletionReceipt
    assert backend.finalize_attempts == 2
    assert backend.finalize_keys[0] == backend.finalize_keys[1]

    with pytest.raises(
        ManagedRegistryPolicyLifecycleError,
        match="^managed_registry_policy_terminal_delete_phase_invalid$",
    ):
        _seal_terminal(wrapper, bindings, deletes)


def test_delegate_delete_failure_freezes_without_false_advance_or_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper, bindings, cases, _, events = _wrapper(
        monkeypatch,
        fail_mem0_once=True,
    )
    _seal_source(wrapper, bindings, cases)
    infinity, mem0 = bindings.backend_targets

    wrapper.terminal_delete(
        bindings=bindings,
        backend_role=infinity.backend_role,
        target_identity_sha256=infinity.target_identity_sha256,
        pass_index=1,
    )
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_mem0_delete_failed$",
    ):
        wrapper.terminal_delete(
            bindings=bindings,
            backend_role=mem0.backend_role,
            target_identity_sha256=mem0.target_identity_sha256,
            pass_index=1,
        )

    assert wrapper._next_delete == 1
    assert wrapper._delete_in_flight is None
    assert events.count("delegate.mem0-delete") == 1

    for backend_role, target_identity_sha256, pass_index in (
        (mem0.backend_role, mem0.target_identity_sha256, 1),
        (infinity.backend_role, infinity.target_identity_sha256, 2),
    ):
        with pytest.raises(
            ManagedRegistryPolicyLifecycleError,
            match="^managed_registry_policy_delete_delegate_unrecoverable$",
        ):
            wrapper.terminal_delete(
                bindings=bindings,
                backend_role=backend_role,
                target_identity_sha256=target_identity_sha256,
                pass_index=pass_index,
            )

    assert wrapper._next_delete == 1
    assert events.count("delegate.mem0-delete") == 1


def test_delete_order_and_unsealed_projection_evidence_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper, bindings, cases, _, _ = _wrapper(monkeypatch)
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_projection_evidence_unavailable$",
    ):
        _ = wrapper._delegate_port.exact_projection_evidence

    _seal_source(wrapper, bindings, cases)
    mem0 = bindings.backend_targets[1]
    with pytest.raises(
        ManagedRegistryPolicyLifecycleError,
        match="^managed_registry_policy_delete_order_invalid$",
    ):
        wrapper.terminal_delete(
            bindings=bindings,
            backend_role=mem0.backend_role,
            target_identity_sha256=mem0.target_identity_sha256,
            pass_index=1,
        )


def test_constructor_rejects_non_exact_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper, bindings, cases, _, _ = _wrapper(monkeypatch)
    with pytest.raises(
        ManagedRegistryPolicyLifecycleError,
        match="^managed_registry_policy_registry_invalid$",
    ):
        ManagedComparisonRegistryPolicyLifecycleAdapter(
            delegate_capability=object(),
            registry=object(),
            bindings=bindings,
            cases=cases,
            registration=wrapper._registration,
        )


def test_constructor_rejects_raw_legacy_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper, bindings, cases, _, _ = _wrapper(monkeypatch)
    raw_delegate = delegate_subject._PORTS[wrapper._delegate_port].delegate

    with pytest.raises(
        ManagedRegistryPolicyLifecycleError,
        match="^managed_registry_policy_delegate_invalid$",
    ):
        ManagedComparisonRegistryPolicyLifecycleAdapter(
            delegate_capability=raw_delegate,
            registry=wrapper._registry,
            bindings=bindings,
            cases=cases,
            registration=wrapper._registration,
        )


def test_delegate_capability_has_exactly_one_concurrent_consumer() -> None:
    cases = (_locomo_case(),)
    delegate, bindings = _policy_adapter([], cases)
    capability = delegate.issue_registry_delegate_capability()
    with pytest.raises(ManagedHttpPolicyLifecycleError, match="capability_invalid"):
        delegate.issue_registry_delegate_capability()

    def attempt() -> str:
        try:
            consume_managed_policy_delegate_capability(
                capability,
                bindings=bindings,
                cases=cases,
            )
        except ManagedPolicyDelegateCapabilityError as exc:
            return exc.code
        return "accepted"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(lambda _index: attempt(), range(8)))

    assert results.count("accepted") == 1
    assert results.count("managed_policy_delegate_capability_replay") == 7


def test_delegate_capability_rejects_crosswire_tamper_copy_and_pickle() -> None:
    cases = (_locomo_case(),)
    delegate, bindings = _policy_adapter([], cases)
    capability = delegate.issue_registry_delegate_capability()
    foreign_delegate, foreign_bindings = _policy_adapter([], cases)
    del foreign_delegate
    with pytest.raises(ManagedPolicyDelegateCapabilityError, match="binding_invalid"):
        consume_managed_policy_delegate_capability(
            capability,
            bindings=foreign_bindings,
            cases=cases,
        )

    state = delegate_subject._CAPABILITIES[capability]
    delegate_subject._CAPABILITIES[capability] = replace(
        state,
        corpus_ids=("tampered",),
    )
    with pytest.raises(ManagedPolicyDelegateCapabilityError, match="capability_changed"):
        consume_managed_policy_delegate_capability(
            capability,
            bindings=bindings,
            cases=cases,
        )
    with pytest.raises(TypeError, match="noncopyable"):
        copy(capability)
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(capability)


def test_delegate_capability_issuer_rejects_crosswired_composition() -> None:
    cases = (_locomo_case(),)
    delegate, _bindings = _policy_adapter([], cases)
    _foreign_delegate, foreign_bindings = _policy_adapter([], cases)

    with pytest.raises(ManagedPolicyDelegateCapabilityError, match="binding_invalid"):
        delegate_subject._issue_legacy_managed_policy_delegate_capability(
            delegate=delegate,
            bindings=foreign_bindings,
            cases=cases,
        )


def test_delegate_capability_consume_rejects_distinct_same_corpus_case() -> None:
    cases = (_locomo_case(),)
    delegate, bindings = _policy_adapter([], cases)
    capability = delegate.issue_registry_delegate_capability()
    foreign_cases = (_locomo_case(),)
    assert foreign_cases[0] is not cases[0]
    assert foreign_cases[0].corpus_id == cases[0].corpus_id

    with pytest.raises(ManagedPolicyDelegateCapabilityError, match="binding_invalid"):
        consume_managed_policy_delegate_capability(
            capability,
            bindings=bindings,
            cases=foreign_cases,
        )

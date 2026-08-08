from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest
from _phase_c_hermetic import install_hermetic_phase_c_authority
from infinity_context_core.ports.derived_projection_policy import (
    derived_not_projected_policy_sha256,
)

sys.path.insert(0, str(Path(__file__).parents[1] / "e2e"))
import memory_comparison_managed_mem0_v5_custom_loopback_process_harness as loopback
import test_memory_comparison_managed_registry_policy_lifecycle as registry_support
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_composition as composition_subject,
)
from infinity_context_server import memory_comparison_managed_v5_production_runner as runner_subject
from infinity_context_server.memory_comparison_bounded_httpx_transport import (
    BoundedHttpResponse,
)
from infinity_context_server.memory_comparison_bounded_provider import (
    BoundedProviderChatCompletions,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    execution_case_manifest_sha256,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_managed_attestation import (
    VerifiedManagedCompositionAttestation,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRegistryHttpConfig,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_infinity_http_lifecycle import (
    self_space_slug,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    ManagedLiveExecutionLimits,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_http import (
    ManagedMem0V5HmacDurableCleanStateFactory,
    ManagedMem0V5HttpCleanStateSnapshotFactory,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_lifecycle import (
    ManagedMem0V5ProductionLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    _inspect_verified_managed_run_plan,
    build_verified_managed_run_plan,
)
from infinity_context_server.memory_comparison_managed_run import (
    ManagedAnswerCase,
    create_managed_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials import (
    issue_managed_runtime_credential_authority,
)
from infinity_context_server.memory_comparison_managed_v5_live_preparation import (
    _activate_managed_v5_public_run,
    prepare_managed_v5_public_run,
)
from infinity_context_server.memory_comparison_managed_v5_owned_resources import (
    ManagedV5OwnedResourcesError,
)
from infinity_context_server.memory_comparison_managed_v5_production_runner import (
    ManagedV5ProductionRunnerError,
    run_verified_managed_v5_production_execution,
)
from infinity_context_server.memory_comparison_managed_v5_runtime_factory import (
    create_managed_v5_production_runtime,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5OperationReceiptAuthority,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionOperationAuthority,
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from managed_run_test_support import CASE_IDS, _dataset_bytes
from phase_c_canary.runtime_receipt_v2 import RuntimeReceiptV2Boundary
from test_memory_comparison_managed_mem0_v5_composition import (
    PHASE_C_ROOT,
    _inputs,
    _Transport,
)
from test_memory_comparison_managed_mem0_v5_production_foundation import (
    _Capability,
    _journal_inputs,
)
from test_memory_comparison_managed_registry_policy_lifecycle import _RegistryBackend
from test_memory_comparison_managed_runtime_credentials import _request as credential_request

_NOW = datetime.now(UTC)
_DEADLINE = _NOW + timedelta(seconds=60)
_RUN_ID = "managed-v5-provider-free-e2e"
_INFINITY_ORIGIN = "http://127.0.0.1:8080"
_MEM0_ORIGIN = "http://127.0.0.1:8891"


class _FullProtocolTransport:
    def __init__(
        self,
        *,
        root: Path,
        clean_state: _Transport,
        authority: object,
        observed: Mem0V5ObservedExtractionReceiptAuthority,
        current_date: str,
    ) -> None:
        root.mkdir(mode=0o700)
        for name in ("barriers", "results"):
            (root / name).mkdir(mode=0o700)
        (root / "barriers" / "dispatch-released").touch()
        (root / "barriers" / "cleanup-released").touch()
        units = []
        operations = []
        for index, (unit, operation) in enumerate(
            zip(authority.units, observed.operations, strict=True)
        ):
            output = _sha(f"output-{index}")
            units.append(
                {
                    "sequence": index,
                    "operation_id_sha256": operation.operation_id_sha256,
                    "unit_identity_sha256": unit.unit_identity_sha256,
                    "unit_sha256": unit.unit_sha256,
                    "scope_sha256": unit.scope_sha256,
                    "source_id": unit.source_id,
                    "source_sha256": unit.source_sha256,
                    "corpus_id": unit.corpus_id,
                    "observation_date": unit.observation_date,
                    "request_body_sha256": operation.request_body_sha256,
                    "output_text_sha256": output,
                    "zero_memory": False,
                }
            )
            operations.append(
                {
                    "sequence": index,
                    "operation_id_sha256": operation.operation_id_sha256,
                    "thread_id": f"thread-{index}",
                    "turn_id": f"turn-{index}",
                    "request_body_sha256": operation.request_body_sha256,
                    "output_text_sha256": output,
                }
            )
        config = {
            "audit_db": str(root / "audit.sqlite3"),
            "admission_commitment_sha256": observed.admission_commitment_sha256,
            "authority": {
                "ingestion_manifest_sha256": authority.ingestion_manifest_sha256,
                "ingestion_root_sha256": authority.ingestion_root_sha256,
                "current_date_commitment_sha256": canonical_sha256({"current_date": current_date}),
            },
            "runtime": {
                "base_instructions_sha256": observed.base_instructions_sha256,
                "account_binding_hmac_sha256": observed.account_binding_hmac_sha256,
                "response_format_sha256": observed.response_format_sha256,
                "response_schema_sha256": observed.response_schema_sha256,
                "requested_output_tokens": observed.requested_output_tokens,
            },
            "units": units,
            "operations": operations,
        }
        (root / "config.json").write_text(json.dumps(config, sort_keys=True, separators=(",", ":")))
        self.service = loopback.DurableLoopbackService(root)
        self.clean_state = clean_state
        self.paths: list[str] = []
        self.errors: list[str] = []

    def request(self, method: str, url: str, **kwargs: object) -> BoundedHttpResponse:
        path = urlsplit(url).path
        self.paths.append(path)
        if path in {"/v5/runs/admit", "/v5/runs/clean-state"}:
            return self.clean_state.request(method, url, **kwargs)
        handlers = {
            "/v5/operations/request-binding": self._request_binding,
            "/v5/operations/dispatch": self.service.dispatch,
            "/v5/operations/status": self.service.status,
            "/v5/operations/storage-observation": self.service.storage_observation,
            "/v5/runs/search": self._scoped_search,
            "/v5/runs/cleanup": self.service.cleanup,
        }
        body = json.loads(kwargs["content"])
        headers = kwargs["headers"]
        try:
            result = handlers[path](
                SimpleNamespace(**body),
                idempotency_key=str(headers["Idempotency-Key"]),
            )
        except Exception as error:
            self.errors.append(f"{path}:{error!r}")
            raise
        return BoundedHttpResponse(200, json.dumps(result).encode())

    def _request_binding(self, request, *, idempotency_key: str) -> dict[str, object]:
        del idempotency_key
        unit = self.service._unit(request.operation_id_sha256)
        unsigned = {
            "schema_version": "mem0-oss-adapter-v5.request-binding.v2",
            "admission_commitment_sha256": request.admission_commitment_sha256,
            "operation_id_sha256": request.operation_id_sha256,
            "unit_identity_sha256": unit["unit_identity_sha256"],
            "unit_sha256": unit["unit_sha256"],
            "corpus_id": unit["corpus_id"],
            "source_id": unit["source_id"],
            "source_sha256": unit["source_sha256"],
            "observation_date": unit["observation_date"],
            "observation_date_commitment_sha256": canonical_sha256(
                {"observation_date": unit["observation_date"]}
            ),
            "request_body_sha256": unit["request_body_sha256"],
        }
        evidence = canonical_sha256(unsigned)
        signed = {**unsigned, "request_binding_evidence_sha256": evidence}
        return {
            **signed,
            "request_binding_hmac_sha256": self.service._evidence_hmac(
                signed, b"request-binding/v2"
            ),
        }

    def _scoped_search(self, request, *, idempotency_key: str) -> dict[str, object]:
        result = self.service.scoped_search(request, idempotency_key=idempotency_key)
        source_ids = {
            unit["source_id"]
            for unit in self.service.config["units"]
            if unit["corpus_id"] == request.corpus_id
        }
        records = [item for item in result["results"] if item["source_id"] in source_ids]
        records = [{**item, "rank": rank} for rank, item in enumerate(records)]
        unsigned = {
            **{
                key: value
                for key, value in result.items()
                if key
                not in {"search_hmac_sha256", "result_count", "result_root_sha256", "results"}
            },
            "result_count": len(records),
            "result_root_sha256": canonical_sha256({"results": records}),
            "results": records,
        }
        return {
            **unsigned,
            "search_hmac_sha256": self.service._evidence_hmac(unsigned, b"scoped-search/v1"),
        }


@pytest.fixture(autouse=True)
def _hermetic_phase_c(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_hermetic_phase_c_authority(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        phase_c_root=PHASE_C_ROOT,
    )
    monkeypatch.setattr(
        composition_subject,
        "require_mem0_v5_observed_extraction_receipt_boundary",
        lambda **_values: None,
    )


def _sha(value: object) -> str:
    raw = value if type(value) is bytes else str(value).encode()
    return hashlib.sha256(raw).hexdigest()


def _plan(authority: object):
    material = authority.preflight_material()
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    return build_verified_managed_run_plan(
        run_id=_RUN_ID,
        run_nonce_commitment_sha256="1" * 64,
        runtime_probe_nonce_sha256="2" * 64,
        profile=profile,
        dataset_bytes=_dataset_bytes(),
        backend_targets=tuple(item.target for item in material.backend_endpoints),
        provider_route=replace(material.provider_route, response_status=200),
        scope="canary",
        selected_case_ids=CASE_IDS,
    )


def _receipt_authorities(cases, current_date, request, template):
    authority = ManagedMem0V5ManifestProjector().project(cases, current_date=current_date)
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    operations = tuple(
        Mem0V5OperationReceiptAuthority(
            canonical_sha256(
                {
                    "admission_commitment_sha256": admission.commitment_sha256,
                    "unit_index": index,
                    "unit_identity_sha256": unit.unit_identity_sha256,
                }
            ),
            index,
            f"thread-{index}",
            f"turn-{index}",
            _sha(f"request-{index}"),
            _sha(f"output-{index}"),
        )
        for index, unit in enumerate(authority.units)
    )
    raw = replace(template, operations=operations)
    observed = Mem0V5ObservedExtractionReceiptAuthority(
        admission_commitment_sha256=admission.commitment_sha256,
        model=raw.model,
        reasoning_effort=raw.reasoning_effort,
        service_tier=raw.service_tier,
        base_instructions_sha256=raw.base_instructions_sha256,
        runtime_source_sha256=raw.runtime_source_sha256,
        route_binding_sha256=raw.route_binding_sha256,
        account_binding_hmac_sha256=raw.account_binding_hmac_sha256,
        response_format_type=raw.response_format_type,
        response_format_sha256=raw.response_format_sha256,
        response_schema_sha256=raw.response_schema_sha256,
        node_executable_path="/usr/local/bin/node",
        node_executable_sha256=("b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"),
        requested_output_tokens=raw.requested_output_tokens,
        operations=tuple(
            Mem0V5ObservedExtractionOperationAuthority(
                operation.operation_id_sha256,
                unit.unit_identity_sha256,
                unit.unit_sha256,
                unit.scope_sha256,
                index,
                operation.request_body_sha256,
            )
            for index, (operation, unit) in enumerate(
                zip(raw.operations, authority.units, strict=True)
            )
        ),
    )
    return authority, observed


def _infinity_handler(authority, events: list[str]):
    units = iter(authority.units)
    facts: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        events.append(request.url.path)
        if request.url.path == "/v1/spaces":
            return httpx.Response(
                201,
                json={"data": {"slug": f"memory-comparison-{_RUN_ID}"}},
            )
        if request.url.path == "/v1/facts":
            unit = next(units)
            fact_id = f"fact-{unit.unit_identity_sha256[:16]}"
            facts[fact_id] = unit
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": fact_id,
                        "space_id": registry_support._SPACE_ID,
                        "memory_scope_id": f"scope-{unit.unit_identity_sha256[:16]}",
                        "thread_id": f"thread-{unit.unit_identity_sha256[:16]}",
                        "status": "active",
                        "version": 1,
                        "indexing_status": "pending",
                        "source_id": unit.source_id,
                        "source_sha256": unit.source_sha256,
                        "request_id": f"request-{unit.unit_identity_sha256[:16]}",
                    }
                },
            )
        if request.url.path == "/v1/diagnostics/derived-evidence/presence":
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "scope": {
                            "space_id": body["space_id"],
                            "memory_scope_id": body["memory_scope_id"],
                            "thread_id": body["thread_id"],
                        },
                        "outbox": {
                            "complete": True,
                            "done_chunk_ids": body["expected_chunk_ids"],
                            "done_fact_ids": body["expected_fact_ids"],
                            "done_event_count": len(body["expected_chunk_ids"])
                            + len(body["expected_fact_ids"]),
                        },
                        "lanes": {
                            "qdrant": (
                                {
                                    "disposition": "not_projected",
                                    "policy_sha256": derived_not_projected_policy_sha256("qdrant"),
                                }
                                if body["expected_chunk_ids"]
                                else None
                            ),
                            "graphiti": (
                                {
                                    "disposition": "not_projected",
                                    "policy_sha256": derived_not_projected_policy_sha256(
                                        "graphiti"
                                    ),
                                }
                                if body["expected_fact_ids"]
                                else None
                            ),
                        },
                    }
                },
            )
        if request.url.path.startswith("/v1/facts/"):
            fact_id = request.url.path.rsplit("/", 1)[-1]
            unit = facts[fact_id]
            data = {
                "id": fact_id,
                "space_id": registry_support._SPACE_ID,
                "memory_scope_id": f"scope-{unit.unit_identity_sha256[:16]}",
                "thread_id": f"thread-{unit.unit_identity_sha256[:16]}",
                "status": "deleted",
            }
            if request.method == "DELETE":
                data["indexing_status"] = (
                    "pending" if events.count(request.url.path) == 1 else "already_deleted"
                )
            return httpx.Response(200, json={"data": data})
        if request.url.path == "/v1/context/benchmark-search":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "items": [
                            {
                                "item_id": "fact-e2e",
                                "item_type": "fact",
                                "text": "Alice remembers",
                                "score": 1.0,
                                "source_refs": [{"source_id": authority.units[0].source_id}],
                            }
                        ]
                    }
                },
            )
        raise AssertionError(f"unexpected Infinity endpoint {request.url.path}")

    return handle


def _fixture(monkeypatch: pytest.MonkeyPatch, tmp_path):
    space_slug = self_space_slug(_RUN_ID)
    monkeypatch.setattr(registry_support, "_SPACE_SLUG", space_slug)
    authority = issue_managed_runtime_credential_authority(
        run_id=_RUN_ID,
        infinity_origin=_INFINITY_ORIGIN,
        infinity_auth_token="infinity-secret",
        mem0_origin=_MEM0_ORIGIN,
        mem0_api_key="mem0-secret",
        mem0_probe_token="mem0-probe",
        subscription_origin="http://127.0.0.1:8890",
        subscription_bearer_token="subscription-secret",
        request_timeout_seconds=10,
        issued_at=_NOW,
        deadline=_DEADLINE,
    )
    preflight = credential_request(authority)
    authority.bind_preflight_request(preflight, run_id=_RUN_ID, deadline=_DEADLINE)
    plan = _plan(authority)
    plan_state = _inspect_verified_managed_run_plan(plan)
    bindings = create_managed_comparison_run_bindings(plan)
    composition_binding = ManagedRunnerCompositionBinding(
        run_id=_RUN_ID,
        profile=plan_state.profile,
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        deadline=_DEADLINE,
        backend_targets=plan_state.backend_targets,
        retrieval_top_k=plan_state.profile.retrieval_top_k,
        answer_cutoff=plan_state.profile.answer_cutoff,
    )
    base, secret_values = _inputs(tmp_path)
    current_date = base["current_date"]
    projected = ManagedMem0V5ManifestProjector().project(
        plan_state.cases,
        current_date=current_date,
    )
    trusted = base["trusted_runtime_binding"]
    request = Mem0OssAdmissionRequest(
        run_id=_RUN_ID,
        route_sha256=trusted.route_binding_sha256,
        credential_binding_sha256=_sha(secret_values["evidence"]),
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="source-r1",
        runtime_source_sha256=trusted.runtime_source_sha256,
        runtime_base_sha256=_sha("runtime-base"),
        expected_operation_count=projected.operation_count,
    )
    _projected, observed = _receipt_authorities(
        plan_state.cases,
        current_date,
        request,
        base["receipt_authority"],
    )
    monkeypatch.setitem(loopback.SECRETS, "bearer", secret_values["bearer"])
    monkeypatch.setitem(loopback.SECRETS, "evidence", secret_values["evidence"])
    monkeypatch.setitem(loopback.SECRETS, "receipt", secret_values["receipt"])
    runtime_receipt_boundary = RuntimeReceiptV2Boundary(loopback._PythonReceiptHmacVerifier())
    mem0_transport = _FullProtocolTransport(
        root=tmp_path / "protocol",
        clean_state=_Transport(secret_values["evidence"], projected),
        authority=projected,
        observed=observed,
        current_date=current_date,
    )
    preparation = prepare_managed_v5_public_run(
        cases=plan_state.cases,
        current_date=current_date,
        request=request,
        composition_binding=composition_binding,
        origin=_MEM0_ORIGIN,
        timeout_seconds=5,
        state_paths=base["state_paths"],
        credential_paths=base["credential_paths"],
        runtime_receipt_boundary=runtime_receipt_boundary,
        trusted_runtime_binding=trusted,
        receipt_authority=observed,
        transport=mem0_transport,
    )
    prep_state = __import__(
        "infinity_context_server.memory_comparison_managed_v5_live_preparation",
        fromlist=["_STATES"],
    )._STATES[preparation]
    journal_values = _journal_inputs(
        tmp_path,
        values={
            "operation_manifest": prep_state.operation_manifest,
            "composition_binding": composition_binding,
        },
        production_authority=prep_state.production_authority,
    )
    infinity_events: list[str] = []
    infinity_handler = _infinity_handler(projected, infinity_events)
    credentials = authority.issue_managed_v5_infinity_credentials(
        expected_request=preflight,
        public_preparation=preparation,
        run_id=_RUN_ID,
        infinity_origin=_INFINITY_ORIGIN,
        deadline=_DEADLINE,
        now=_NOW,
        execution_transport=httpx.MockTransport(infinity_handler),
        lifecycle_transport=httpx.MockTransport(infinity_handler),
    )
    registry_events: list[str] = []
    infinity_target = plan_state.backend_targets[0].target_identity_sha256
    backend = _RegistryBackend(
        _sha(_RUN_ID),
        bindings.binding_commitment_sha256,
        infinity_target,
        registry_events,
    )
    registry = ManagedBenchmarkRegistryHttpAdapter(
        ManagedBenchmarkRegistryHttpConfig(
            base_url=_INFINITY_ORIGIN,
            admin_bearer_token="registry-secret",
            target_identity_sha256=infinity_target,
            timeout_seconds=30,
            benchmark_deadline=_DEADLINE,
            cleanup_recovery_timeout_seconds=600,
            transport=httpx.MockTransport(backend),
        )
    )
    registration = registry.register(
        run_id_sha256=_sha(_RUN_ID),
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        space_slug=space_slug,
    )
    activated = _activate_managed_v5_public_run(
        preparation,
        cases=plan_state.cases,
        request=request,
        composition_binding=composition_binding,
        receipt_authority=observed,
        production_authority=prep_state.production_authority,
        plan=plan,
        now=_NOW,
    )
    runtime = create_managed_v5_production_runtime(
        activated_preparation=activated,
        infinity_credentials=credentials,
        current_date=current_date,
        mem0_origin=_MEM0_ORIGIN,
        timeout_seconds=5,
        state_paths=base["state_paths"],
        credential_paths=base["credential_paths"],
        runtime_receipt_boundary=runtime_receipt_boundary,
        trusted_runtime_binding=trusted,
        budget_policy=ManagedMem0V5BudgetPolicy(10_000),
        clean_state_snapshot_factory=ManagedMem0V5HttpCleanStateSnapshotFactory(),
        durable_clean_state_factory=ManagedMem0V5HmacDurableCleanStateFactory(
            path=tmp_path / "clean-state.json",
            hmac_key_capability=_Capability(b"provider-free-e2e-clean-state-key!!"),
        ),
        operation_journal=journal_values["operation_journal"],
        operation_run_identity=journal_values["operation_run_identity"],
        benchmark_registry=registry,
        benchmark_registration=registration,
        mem0_transport=mem0_transport,
        infinity_derived_transport_factory=lambda: httpx.MockTransport(infinity_handler),
        infinity_cleanup_transport_factory=lambda: httpx.MockTransport(infinity_handler),
        clock=lambda: _NOW,
    )
    return runtime, plan_state, infinity_events, registry_events, mem0_transport


def test_two_corpus_runtime_constructs_without_legacy_mem0(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from infinity_context_server import memory_comparison_managed_http_execution as legacy

    legacy_calls = 0

    def forbidden(*_args: object, **_kwargs: object) -> None:
        nonlocal legacy_calls
        legacy_calls += 1
        raise AssertionError("legacy Mem0 construction")

    monkeypatch.setattr(legacy.ManagedMem0HttpConfig, "__init__", forbidden)
    runtime, plan, infinity_events, registry_events, mem0 = _fixture(monkeypatch, tmp_path)

    assert len({case.corpus_id for case in plan.cases}) == 2
    assert legacy_calls == 0
    assert infinity_events == []
    assert mem0.paths == []
    assert registry_events == ["registry.register"]


def test_two_corpus_runtime_dispatches_and_routes_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    dispatch_batches = 0
    original_dispatch = ManagedMem0V5ProductionLifecycleAdapter.dispatch_once

    def count_dispatch(self):
        nonlocal dispatch_batches
        dispatch_batches += 1
        return original_dispatch(self)

    monkeypatch.setattr(ManagedMem0V5ProductionLifecycleAdapter, "dispatch_once", count_dispatch)
    runtime, plan, infinity_events, registry_events, mem0 = _fixture(monkeypatch, tmp_path)
    binding = runtime.composition_binding
    targets = tuple(
        (item.backend_role, item.target_identity_sha256) for item in binding.backend_targets
    )
    runtime.lifecycle_ports.reset.reset(
        run_id=binding.run_id,
        binding_commitment_sha256=binding.binding_commitment_sha256,
        backend_targets=targets,
    )
    receipts = []
    for role, target in targets:
        for case in plan.cases:
            try:
                receipt = runtime.lifecycle_ports.ingest.ingest(
                    run_id=binding.run_id,
                    backend_role=role,
                    target_identity_sha256=target,
                    record=dict(case.record),
                )
            except Exception:
                pytest.fail(repr((mem0.errors, mem0.paths)))
            receipts.append(receipt)
    query = ManagedAnswerCase(
        plan.cases[0].case_id,
        "What does Alice remember?",
        {},
    )
    for role, target in targets:
        authority = runtime.retrieval.authority_for(
            backend_role=role,
            target_identity_sha256=target,
        )
        try:
            runtime.retrieval.retrieve(
                authority=authority,
                case=plan.cases[0],
                query=query,
            )
        except Exception:
            pytest.fail(repr((role, infinity_events, mem0.errors, mem0.paths)))

    assert len(receipts) == 2 * len(plan.cases)
    assert mem0.errors == []
    assert dispatch_batches == 1
    assert mem0.paths.count("/v5/operations/dispatch") == len(plan.cases)
    assert mem0.paths.count("/v5/runs/search") == 1
    assert infinity_events.count("/v1/context/benchmark-search") == 1
    assert registry_events == ["registry.register"]

    with pytest.raises(ManagedV5OwnedResourcesError, match="close_failed"):
        runtime.owned_resources.close()
    assert registry_events == ["registry.register"]


def test_two_corpus_runtime_completes_exact_cleanup_and_closes_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    runtime, plan, infinity_events, registry_events, mem0 = _fixture(monkeypatch, tmp_path)
    binding = runtime.composition_binding
    targets = tuple(
        (item.backend_role, item.target_identity_sha256) for item in binding.backend_targets
    )
    runtime.lifecycle_ports.reset.reset(
        run_id=binding.run_id,
        binding_commitment_sha256=binding.binding_commitment_sha256,
        backend_targets=targets,
    )
    receipts = tuple(
        runtime.lifecycle_ports.ingest.ingest(
            run_id=binding.run_id,
            backend_role=role,
            target_identity_sha256=target,
            record=dict(case.record),
        )
        for role, target in targets
        for case in plan.cases
    )
    attestation = object.__new__(VerifiedManagedCompositionAttestation)
    attestation_sha256 = "8" * 64
    canonical = runtime.policy_port.seal_canonical_source(
        bindings=runtime._bindings,
        cases=plan.cases,
        managed_attestation=attestation,
        managed_attestation_commitment_sha256=attestation_sha256,
        ingest_receipts=receipts,
        case_manifest_sha256=execution_case_manifest_sha256(plan.case_manifest),
    )
    runtime.execution_evidence.consume_ready_evidence(
        composition_binding=binding,
        bindings=runtime._bindings,
        cases=plan.cases,
    )
    deletes = tuple(
        runtime.policy_port.terminal_delete(
            bindings=runtime._bindings,
            backend_role=role,
            target_identity_sha256=target,
            pass_index=pass_index,
        )
        for pass_index in (1, 2)
        for role, target in targets
    )
    terminal = runtime.policy_port.seal_terminal_delete(
        bindings=runtime._bindings,
        managed_attestation=attestation,
        managed_attestation_commitment_sha256=attestation_sha256,
        receipts=deletes,
    )
    runtime.policy_port.aggregate_policy(
        bindings=runtime._bindings,
        managed_attestation=attestation,
        managed_attestation_commitment_sha256=attestation_sha256,
        canonical_source=canonical,
        terminal_delete=terminal,
    )

    assert runtime.policy_port.terminal_completion_receipt.state == "cleanup_complete"
    assert mem0.paths.count("/v5/runs/cleanup") == 2
    assert registry_events[-1] == "registry.finalize"
    assert sum(path.startswith("/v1/facts/") for path in infinity_events) == 8
    runtime.owned_resources.close()
    runtime.owned_resources.close()


def test_execution_primary_error_is_not_masked_by_close_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    runtime, _plan_state, _infinity_events, registry_events, _mem0 = _fixture(monkeypatch, tmp_path)
    primary = ManagedV5ProductionRunnerError("primary_execution_failure")

    def fail_execution(**_kwargs):
        raise primary

    monkeypatch.setattr(runner_subject, "create_managed_comparison_execution_ports", fail_execution)
    with pytest.raises(ManagedV5ProductionRunnerError) as raised:
        run_verified_managed_v5_production_execution(
            runtime,
            provider=object.__new__(BoundedProviderChatCompletions),
            limits=object.__new__(ManagedLiveExecutionLimits),
            provider_route=object.__new__(ProviderRouteAttestation),
            attestation_port=object(),
            clock=lambda: _NOW,
        )

    assert raised.value is primary
    assert registry_events == ["registry.register"]

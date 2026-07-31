from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import pytest
from infinity_context_server import memory_comparison_managed_run as managed
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    execution_case_manifest_sha256,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FULL_COMPARISON_COMPONENT_KINDS,
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    VerifiedManagedRunPlan,
    build_verified_managed_run_plan,
    managed_execution_case_material_sha256,
)
from infinity_context_server.memory_comparison_managed_run import (
    ManagedAnswerCase,
    ManagedCaseExecution,
    ManagedExecutionArtifacts,
    ManagedRunCase,
    ManagedRunError,
    ManagedRunPlan,
    public_managed_run,
    run_managed_comparison,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkValidationError,
    PublicBenchmarkCase,
)

_SHA = "a" * 64
_MANAGED_ATTESTATION = object()


class _Abort(BaseException):
    pass


class _Port:
    def __init__(self, name: str, events: list[str]) -> None:
        self.adapter_id = name
        self.implementation_sha256 = _SHA
        self.events = events


class _Reset(_Port):
    fail = False

    def reset(self, **kwargs: Any) -> None:
        del kwargs
        self.events.append("reset")
        if self.fail:
            raise RuntimeError("reset failed")


class _Attest(_Port):
    fail = False

    def attest(self, **kwargs: Any) -> object:
        del kwargs
        self.events.append("attest")
        if self.fail:
            raise RuntimeError("attest failed")
        return object()


class _Ingest(_Port):
    def ingest(self, *, backend_role: str, record: object, **kwargs: Any) -> object:
        del record, kwargs
        self.events.append(f"ingest:{backend_role}")
        return object()


class _Clock(_Port):
    def now(self) -> object:
        raise AssertionError("patched attestation must not read clock")


class _Execution(_Port):
    def __init__(self, events: list[str], fail_at: str | None = None) -> None:
        super().__init__("execution", events)
        self.fail_at = fail_at
        self.reuse_receipts = False
        self.mutate_query = False
        self.shared_receipts = {stage: object() for stage in ("retrieve", "answer")}
        self.queries: list[ManagedAnswerCase] = []

    def _call(self, name: str, role: str, case: ManagedRunCase) -> object:
        self.events.append(f"{name}:{role}:{case.case_id}")
        if self.fail_at == name:
            raise _Abort(name)
        if self.reuse_receipts:
            return self.shared_receipts[name]
        return object()

    def retrieve(
        self,
        *,
        backend_role: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
        **kwargs: Any,
    ) -> object:
        del kwargs
        self.queries.append(query)
        return self._call("retrieve", backend_role, case)

    def answer(
        self,
        *,
        backend_role: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
        **kwargs: Any,
    ) -> object:
        del kwargs
        self.queries.append(query)
        if self.mutate_query:
            object.__setattr__(query, "question", "substituted question")
            self.mutate_query = False
        return self._call("answer", backend_role, case)


class _Judge(_Port):
    def __init__(self, events: list[str], fail_at: str | None = None) -> None:
        super().__init__("judge", events)
        self.fail_at = fail_at
        self.sealed_manifest: tuple[FullExecutionCaseManifestEntry, ...] | None = None
        self.sealed_manifest_sha256: str | None = None
        self.sealed_executions: tuple[ManagedCaseExecution, ...] | None = None
        self.sealed_case_material: tuple[tuple[str, str], ...] | None = None
        self.manifest_override: str | None = None
        self.material_override: tuple[tuple[str, str], ...] | None = None
        self.bind_mismatch = False
        self.mutate_during_bind = False
        self.mutate_nested_metadata = False
        self.bound_cases: tuple[PublicBenchmarkCase, ...] = ()
        self.bound_aliases: tuple[str, ...] = ()

    def bind_cases(
        self,
        *,
        cases: tuple[PublicBenchmarkCase, ...],
        case_aliases: tuple[str, ...],
        **kwargs: Any,
    ) -> tuple[tuple[str, str], ...]:
        del kwargs
        self.events.append("judge.bind")
        self.bound_cases = cases
        self.bound_aliases = case_aliases
        material = tuple(
            (
                alias,
                managed_execution_case_material_sha256(case, case_alias=alias),
            )
            for case, alias in zip(cases, case_aliases, strict=True)
        )
        if self.mutate_during_bind:
            metadata = cases[0].metadata
            assert type(metadata) is dict
            evidence = metadata.get("evidence")
            assert type(evidence) is list
            evidence.append("bind-time-substitution")
        if self.bind_mismatch:
            return ((material[0][0], "0" * 64), *material[1:])
        return material

    def judge(self, *, backend_role: str, case: ManagedRunCase, **kwargs: Any) -> object:
        del kwargs
        self.events.append(f"judge:{backend_role}:{case.case_id}")
        if self.mutate_nested_metadata:
            metadata = self.bound_cases[0].metadata
            assert type(metadata) is dict
            evidence = metadata.get("evidence")
            assert type(evidence) is list
            evidence.append("substituted-evidence")
            self.mutate_nested_metadata = False
        if self.fail_at == "judge":
            raise _Abort("judge")
        return object()

    def seal_execution(
        self,
        *,
        case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
        case_manifest_sha256: str,
        case_material_sha256: tuple[tuple[str, str], ...],
        executions: tuple[ManagedCaseExecution, ...],
        **kwargs: Any,
    ) -> ManagedExecutionArtifacts:
        del kwargs
        self.sealed_manifest_sha256 = case_manifest_sha256
        self.sealed_manifest = case_manifest
        self.sealed_executions = executions
        self.sealed_case_material = case_material_sha256
        self.events.append("execution.seal")
        if self.fail_at == "execution.seal":
            raise _Abort("execution.seal")
        return ManagedExecutionArtifacts(
            object(),
            object(),
            self.manifest_override or case_manifest_sha256,
            self.material_override or case_material_sha256,
        )


class _Policy(_Port):
    def __init__(self, events: list[str], fail_at: str | None = None) -> None:
        super().__init__("policy", events)
        self.fail_at = fail_at
        self.reuse_delete_receipts = False
        self.shared_delete_receipt = object()
        self.expected_managed_commitment_sha256 = "8" * 64
        self.sealed_managed_attestation: object | None = None
        self.sealed_managed_commitment: str | None = None
        self.terminal_managed_attestation: object | None = None
        self.terminal_managed_commitment: str | None = None

    def seal_canonical_source(
        self,
        *,
        cases: tuple[ManagedRunCase, ...],
        managed_attestation: object,
        managed_attestation_commitment_sha256: str | None,
        **kwargs: Any,
    ) -> tuple[object, ...]:
        del kwargs
        self.sealed_managed_attestation = managed_attestation
        self.sealed_managed_commitment = managed_attestation_commitment_sha256
        self.events.append("canonical_source.seal")
        if managed_attestation is None:
            raise ManagedRunError("managed attestation is required for canonical/source")
        if managed_attestation_commitment_sha256 is None:
            raise ManagedRunError("managed attestation commitment is required")
        if managed_attestation_commitment_sha256 != self.expected_managed_commitment_sha256:
            raise ManagedRunError("managed attestation commitment mismatch")
        if self.fail_at == "canonical_source.seal":
            raise _Abort("canonical_source.seal")
        return tuple(object() for _ in cases)

    def terminal_delete(self, *, backend_role: str, pass_index: int, **kwargs: Any) -> object:
        del kwargs
        event = f"delete:{backend_role}:{pass_index}"
        self.events.append(event)
        if self.fail_at == event:
            raise RuntimeError(event)
        if self.reuse_delete_receipts:
            return self.shared_delete_receipt
        return object()

    def seal_terminal_delete(
        self,
        *,
        managed_attestation: object,
        managed_attestation_commitment_sha256: str,
        **kwargs: Any,
    ) -> object:
        del kwargs
        self.terminal_managed_attestation = managed_attestation
        self.terminal_managed_commitment = managed_attestation_commitment_sha256
        self.events.append("delete.seal")
        if self.fail_at == "delete.seal":
            raise RuntimeError("delete seal")
        return object()

    def aggregate_policy(self, **kwargs: Any) -> object:
        del kwargs
        self.events.append("policy.aggregate")
        return object()


class _Assembler(_Port):
    def __init__(self, events: list[str]) -> None:
        super().__init__("assembler", events)
        self.bindings = None

    def assemble_components(self, **kwargs: Any) -> tuple[object, ...]:
        self.events.append("components.issue")
        self.bindings = kwargs["bindings"]
        return tuple(object() for _ in FULL_COMPARISON_COMPONENT_KINDS)

    def seal_verdict(self, **kwargs: Any) -> object:
        del kwargs
        self.events.append("verdict.seal")
        return object()

    def public_verdict(self, verdict: object) -> dict[str, object]:
        del verdict
        self.events.append("verdict.public")
        assert self.bindings is not None
        return {
            "run_id": self.bindings.run_id,
            "profile_id": self.bindings.profile_id,
            "scope": self.bindings.scope,
            "publishable": self.bindings.scope != "canary",
            "eligible": self.bindings.scope != "canary",
            "components": [{"component_kind": kind} for kind in FULL_COMPARISON_COMPONENT_KINDS],
        }


@dataclass
class _Rig:
    events: list[str]
    reset: _Reset
    attest: _Attest
    ingest: _Ingest
    clock: _Clock
    execution: _Execution
    judge: _Judge
    policy: _Policy
    assembler: _Assembler


def _cases() -> tuple[ManagedRunCase, ...]:
    return (
        ManagedRunCase("case-1", "corpus-1", {"text": "one"}),
        ManagedRunCase("case-2", "corpus-2", {"text": "two"}),
    )


def _manifest() -> tuple[FullExecutionCaseManifestEntry, ...]:
    return (
        FullExecutionCaseManifestEntry(
            "case-1",
            "corpus-1",
            "thread-1",
            ("memory", "query"),
            ("session-0001", "session-0002"),
            1,
        ),
        FullExecutionCaseManifestEntry(
            "case-2",
            "corpus-2",
            "thread-2",
            ("memory", "query"),
            ("session-0003", "session-0004"),
            1,
        ),
    )


_CASE_IDS = ("corpus-1:qa:1", "corpus-2:qa:1")


def _dataset_bytes() -> bytes:
    return json.dumps(
        [
            {
                "sample_id": f"corpus-{index}",
                "conversation": {
                    "speaker_a": "Alice",
                    "speaker_b": "Bob",
                    "session_1_date_time": "1:56 pm on 8 May, 2023",
                    "session_1": [
                        {
                            "dia_id": "D1:1",
                            "speaker": "Alice",
                            "text": f"corpus memory {index}",
                        }
                    ],
                },
                "qa": [
                    {
                        "question": f"question {index}",
                        "answer": f"answer {index}",
                        "evidence": ["D1:1"],
                        "category": 4,
                    }
                ],
            }
            for index in (1, 2)
        ],
        separators=(",", ":"),
    ).encode()


def _plan(
    *,
    scope: str = "canary",
) -> VerifiedManagedRunPlan:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    return build_verified_managed_run_plan(
        run_id="managed-test",
        run_nonce_commitment_sha256="1" * 64,
        runtime_probe_nonce_sha256="2" * 64,
        profile=profile,
        dataset_bytes=_dataset_bytes(),
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", "4" * 64),
            FullComparisonBackendTarget("mem0", "5" * 64),
        ),
        provider_route=ProviderRouteAttestation(
            trust="official_openai",
            origin="https://api.openai.com",
            endpoint_path="/v1/chat/completions",
            route_sha256="6" * 64,
            transport_evidence="direct_https",
            credential_binding_id="sha256:" + "7" * 64,
            request_method="POST",
            response_status=200,
        ),
        scope=scope,
        selected_case_ids=_CASE_IDS,
    )


def _legacy_plan() -> ManagedRunPlan:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    return ManagedRunPlan(
        run_id="legacy-test",
        run_nonce_commitment_sha256="1" * 64,
        runtime_probe_nonce_sha256="2" * 64,
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256=profile.expected_dataset_hash,
        selection_fingerprint_sha256="3" * 64,
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", "4" * 64),
            FullComparisonBackendTarget("mem0", "5" * 64),
        ),
        case_manifest=_manifest(),
        provider_route=ProviderRouteAttestation(
            trust="official_openai",
            origin="https://api.openai.com",
            endpoint_path="/v1/chat/completions",
            route_sha256="6" * 64,
            transport_evidence="direct_https",
            credential_binding_id="sha256:" + "7" * 64,
            request_method="POST",
            response_status=200,
        ),
        cases=_cases(),
        scope="full",
    )


def _rig() -> _Rig:
    events: list[str] = []
    return _Rig(
        events,
        _Reset("reset", events),
        _Attest("attest", events),
        _Ingest("ingest", events),
        _Clock("clock", events),
        _Execution(events),
        _Judge(events),
        _Policy(events),
        _Assembler(events),
    )


def _patch_attestation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    commitment: object,
    attestation: object,
) -> None:
    monkeypatch.setattr(
        managed,
        "_issue_verified_managed_composition_attestation_for_composition_root",
        lambda **kwargs: attestation,
    )
    monkeypatch.setattr(
        managed,
        "public_managed_composition_attestation",
        lambda *args, **kwargs: {"composition_attestation_sha256": commitment},
    )


def _run(
    rig: _Rig,
    monkeypatch: pytest.MonkeyPatch,
    *,
    scope: str = "canary",
    attestation_commitment: object = "8" * 64,
    managed_attestation: object = _MANAGED_ATTESTATION,
    plan: VerifiedManagedRunPlan | ManagedRunPlan | None = None,
):
    _patch_attestation(
        monkeypatch,
        commitment=attestation_commitment,
        attestation=managed_attestation,
    )
    return run_managed_comparison(
        _plan(scope=scope) if plan is None else plan,
        reset_port=rig.reset,
        attestation_port=rig.attest,
        ingest_port=rig.ingest,
        clock=rig.clock,
        execution_port=rig.execution,
        judge_port=rig.judge,
        policy_port=rig.policy,
        assembler=rig.assembler,
    )


def _deletes(events: list[str]) -> list[str]:
    return [item for item in events if item.startswith("delete:")]


def test_exact_lifecycle_orders_terminal_delete_before_nine_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    outcome = _run(rig, monkeypatch)
    report = public_managed_run(outcome)

    assert rig.events.count("reset") == 1
    assert rig.events.count("attest") == 1
    assert rig.events.count("ingest:infinity-context") == 2
    assert rig.events.count("ingest:mem0") == 2
    assert sum(item.startswith("retrieve:") for item in rig.events) == 4
    assert sum(item.startswith("answer:") for item in rig.events) == 4
    assert sum(item.startswith("judge:") for item in rig.events) == 4
    assert _deletes(rig.events) == [
        "delete:infinity-context:1",
        "delete:mem0:1",
        "delete:infinity-context:2",
        "delete:mem0:2",
    ]
    assert rig.events.index("delete.seal") < rig.events.index("components.issue")
    assert rig.events.index("components.issue") < rig.events.index("verdict.public")
    assert report["managed_run"]["component_count"] == 9
    assert rig.policy.sealed_managed_attestation is _MANAGED_ATTESTATION
    assert rig.policy.sealed_managed_commitment == "8" * 64
    assert rig.events.count("canonical_source.seal") == 1
    assert rig.events.index("canonical_source.seal") < rig.events.index("delete:infinity-context:1")
    assert rig.judge.sealed_manifest is not None
    assert tuple(item.case_id for item in rig.judge.sealed_manifest) == rig.judge.bound_aliases
    assert all(raw_id not in repr(rig.judge.sealed_manifest) for raw_id in _CASE_IDS)
    assert len({item.corpus_id for item in rig.judge.sealed_manifest}) == 2
    assert rig.judge.sealed_manifest_sha256 == execution_case_manifest_sha256(
        rig.judge.sealed_manifest
    )
    assert rig.judge.sealed_executions is not None
    first_alias, second_alias = rig.judge.bound_aliases
    assert tuple((item.case_id, item.backend_role) for item in rig.judge.sealed_executions) == (
        (first_alias, "infinity-context"),
        (first_alias, "mem0"),
        (second_alias, "infinity-context"),
        (second_alias, "mem0"),
    )
    assert rig.judge.sealed_case_material is not None
    assert all(type(item) is ManagedAnswerCase for item in rig.execution.queries)
    assert not hasattr(rig.execution, "bound_cases")
    rendered_report = json.dumps(report, sort_keys=True)
    for private in (*_CASE_IDS, "question 1", "answer 1", "D1:1"):
        assert private not in rendered_report


@pytest.mark.parametrize(
    "stage",
    ("retrieve", "answer", "judge", "execution.seal", "canonical_source.seal"),
)
def test_every_post_ingest_baseexception_runs_both_delete_passes(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    rig = _rig()
    if stage == "canonical_source.seal":
        rig.policy.fail_at = stage
    elif stage in {"judge", "execution.seal"}:
        rig.judge.fail_at = stage
    else:
        rig.execution.fail_at = stage

    with pytest.raises(_Abort, match=stage) as raised:
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "delete.seal" in rig.events
    assert rig.policy.terminal_managed_attestation is _MANAGED_ATTESTATION
    assert rig.policy.terminal_managed_commitment == "8" * 64
    assert not getattr(raised.value, "__notes__", ())
    assert "policy.aggregate" not in rig.events
    assert "components.issue" not in rig.events
    assert "verdict.public" not in rig.events


def test_pre_attestation_failure_runs_deletes_without_false_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.attest.fail = True

    with pytest.raises(RuntimeError, match="attest failed") as raised:
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "delete.seal" not in rig.events
    assert rig.policy.terminal_managed_attestation is None
    assert rig.policy.terminal_managed_commitment is None
    assert not getattr(raised.value, "__notes__", ())
    assert "policy.aggregate" not in rig.events
    assert "components.issue" not in rig.events


def test_manifest_mismatch_blocks_consumption_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.judge.manifest_override = "9" * 64

    with pytest.raises(ManagedRunError, match="case manifest"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "canonical_source.seal" not in rig.events
    assert "components.issue" not in rig.events


def test_cleanup_failure_attempts_all_deletes_and_blocks_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.policy.fail_at = "delete:mem0:1"

    with pytest.raises(RuntimeError, match="delete:mem0:1"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "delete.seal" not in rig.events
    assert "components.issue" not in rig.events


def test_canary_runs_full_lifecycle_but_is_never_publishable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    report = public_managed_run(_run(rig, monkeypatch, scope="canary"))

    assert len(_deletes(rig.events)) == 4
    assert report["publishable"] is False
    assert report["eligible"] is False


def test_reused_lane_receipts_fail_before_execution_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.execution.reuse_receipts = True

    with pytest.raises(ManagedRunError, match="receipt identity"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "execution.seal" not in rig.events
    assert "components.issue" not in rig.events


@pytest.mark.parametrize(
    ("attribute", "role"),
    (
        ("reset", "reset"),
        ("attest", "attestation"),
        ("ingest", "ingest"),
        ("clock", "clock"),
        ("execution", "execution"),
        ("judge", "judge"),
        ("policy", "policy"),
        ("assembler", "assembler"),
    ),
)
def test_preflight_missing_provenance_blocks_all_lifecycle_calls(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    role: str,
) -> None:
    rig = _rig()
    delattr(getattr(rig, attribute), "implementation_sha256")

    with pytest.raises(ManagedRunError, match=f"{role} port provenance"):
        _run(rig, monkeypatch)

    assert rig.events == []


def test_preflight_invalid_provenance_blocks_all_lifecycle_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.ingest.adapter_id = ""

    with pytest.raises(ManagedRunError, match="ingest adapter_id"):
        _run(rig, monkeypatch)

    assert rig.events == []


def test_preflight_missing_operation_blocks_all_lifecycle_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.clock.now = None  # type: ignore[method-assign,assignment]

    with pytest.raises(ManagedRunError, match="clock port operation"):
        _run(rig, monkeypatch)

    assert rig.events == []


def test_reused_delete_receipt_attempts_all_cleanup_and_blocks_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.policy.reuse_delete_receipts = True

    with pytest.raises(ManagedRunError, match="globally distinct"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "delete.seal" not in rig.events
    assert "policy.aggregate" not in rig.events
    assert "components.issue" not in rig.events
    assert "verdict.public" not in rig.events


def test_plan_scope_is_normalized_and_invalid_scope_fails_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = public_managed_run(_run(_rig(), monkeypatch, plan=_plan(scope=" CANARY ")))

    assert report["scope"] == "canary"
    with pytest.raises(BenchmarkValidationError, match="unsupported full comparison scope"):
        _plan(scope="preview")


def test_direct_legacy_plan_never_authorizes_managed_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    with pytest.raises(ManagedRunError, match="requires a verified managed run plan"):
        _run(rig, monkeypatch, plan=_legacy_plan())
    assert rig.events == []


def test_failed_port_preflight_does_not_consume_verified_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _plan()
    rig = _rig()
    rig.ingest.adapter_id = ""

    with pytest.raises(ManagedRunError, match="ingest adapter_id"):
        _run(rig, monkeypatch, plan=admission)
    assert rig.events == []

    rig.ingest.adapter_id = "ingest"
    public_managed_run(_run(rig, monkeypatch, plan=admission))
    assert rig.events.count("reset") == 1


def test_verified_plan_is_single_use(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _plan()
    public_managed_run(_run(_rig(), monkeypatch, plan=admission))
    retry_rig = _rig()

    with pytest.raises(ManagedRunError, match="unavailable or consumed"):
        _run(retry_rig, monkeypatch, plan=admission)

    assert retry_rig.events == []


def test_concurrent_verified_plan_consume_binds_private_cases_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _plan()
    _patch_attestation(
        monkeypatch,
        commitment="8" * 64,
        attestation=_MANAGED_ATTESTATION,
    )
    rigs = (_rig(), _rig())

    def invoke(rig: _Rig) -> object:
        return run_managed_comparison(
            admission,
            reset_port=rig.reset,
            attestation_port=rig.attest,
            ingest_port=rig.ingest,
            clock=rig.clock,
            execution_port=rig.execution,
            judge_port=rig.judge,
            policy_port=rig.policy,
            assembler=rig.assembler,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = tuple(pool.submit(invoke, rig) for rig in rigs)
    successes = [future.result() for future in futures if future.exception() is None]
    failures = [future.exception() for future in futures if future.exception() is not None]

    assert len(successes) == len(failures) == 1
    assert isinstance(failures[0], ManagedRunError)
    assert sum(rig.events.count("judge.bind") for rig in rigs) == 1
    assert sum(rig.events.count("reset") for rig in rigs) == 1


def test_judge_binding_mismatch_burns_authority_before_reset_or_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _plan()
    rig = _rig()
    rig.judge.bind_mismatch = True

    with pytest.raises(ManagedRunError, match="judge case material"):
        _run(rig, monkeypatch, plan=admission)

    assert rig.events == ["judge.bind"]
    retry = _rig()
    with pytest.raises(ManagedRunError, match="unavailable or consumed"):
        _run(retry, monkeypatch, plan=admission)
    assert retry.events == []


def test_judge_bind_time_mutation_fails_before_reset_or_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.judge.mutate_during_bind = True

    with pytest.raises(ManagedRunError, match="changed during execution"):
        _run(rig, monkeypatch)

    assert rig.events == ["judge.bind"]


def test_nested_private_metadata_mutation_fails_after_lanes_before_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.judge.mutate_nested_metadata = True

    with pytest.raises(ManagedRunError, match="changed during execution"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "execution.seal" not in rig.events
    assert "components.issue" not in rig.events


def test_answer_query_mutation_fails_before_execution_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.execution.mutate_query = True

    with pytest.raises(ManagedRunError, match="answer case material changed"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "execution.seal" not in rig.events
    assert "components.issue" not in rig.events


def test_execution_seal_revalidates_private_case_commitments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.judge.material_override = (("opaque-case", "0" * 64),)

    with pytest.raises(ManagedRunError, match="admitted case material"):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "canonical_source.seal" not in rig.events
    assert "components.issue" not in rig.events


def test_verified_plan_commitment_tampering_fails_before_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _plan()
    object.__setattr__(admission, "_VerifiedManagedRunPlan__commitment", "0" * 64)
    rig = _rig()

    with pytest.raises(ManagedRunError, match="integrity failed"):
        _run(rig, monkeypatch, plan=admission)

    assert rig.events == []


def test_policy_attestation_commitment_mismatch_cleans_up_before_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    rig.policy.expected_managed_commitment_sha256 = "9" * 64

    with pytest.raises(ManagedRunError, match="commitment mismatch"):
        _run(rig, monkeypatch)

    assert rig.events.count("canonical_source.seal") == 1
    assert len(_deletes(rig.events)) == 4
    assert rig.events.index("canonical_source.seal") < rig.events.index("delete:infinity-context:1")
    assert "policy.aggregate" not in rig.events
    assert "components.issue" not in rig.events
    assert "verdict.public" not in rig.events


def test_none_managed_attestation_commitment_cleans_up_before_ingest_or_policy_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()

    with pytest.raises(ManagedRunError, match="managed attestation must be SHA-256") as raised:
        _run(rig, monkeypatch, attestation_commitment=None)

    assert len(_deletes(rig.events)) == 4
    assert "delete.seal" not in rig.events
    assert getattr(raised.value, "__notes__", ()) == [
        "terminal cleanup also failed: ManagedRunError"
    ]
    assert not any(item.startswith("ingest:") for item in rig.events)
    assert "canonical_source.seal" not in rig.events
    assert "policy.aggregate" not in rig.events
    assert "components.issue" not in rig.events
    assert "verdict.public" not in rig.events


def test_none_managed_attestation_cleans_up_before_ingest_or_policy_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()

    with pytest.raises(ManagedRunError, match="managed attestation is missing") as raised:
        _run(rig, monkeypatch, managed_attestation=None)

    assert len(_deletes(rig.events)) == 4
    assert "delete.seal" not in rig.events
    assert not getattr(raised.value, "__notes__", ())
    assert not any(item.startswith("ingest:") for item in rig.events)
    assert "canonical_source.seal" not in rig.events
    assert "policy.aggregate" not in rig.events
    assert "components.issue" not in rig.events
    assert "verdict.public" not in rig.events

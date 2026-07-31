from __future__ import annotations

from dataclasses import dataclass, replace
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
from infinity_context_server.memory_comparison_managed_run import (
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
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

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
        self.sealed_manifest: tuple[FullExecutionCaseManifestEntry, ...] | None = None
        self.sealed_manifest_sha256: str | None = None
        self.manifest_override: str | None = None
        self.reuse_receipts = False
        self.shared_receipts = {stage: object() for stage in ("retrieve", "answer", "judge")}

    def _call(self, name: str, role: str, case: ManagedRunCase) -> object:
        self.events.append(f"{name}:{role}:{case.case_id}")
        if self.fail_at == name:
            raise _Abort(name)
        if self.reuse_receipts:
            return self.shared_receipts[name]
        return object()

    def retrieve(self, *, backend_role: str, case: ManagedRunCase, **kwargs: Any) -> object:
        del kwargs
        return self._call("retrieve", backend_role, case)

    def answer(self, *, backend_role: str, case: ManagedRunCase, **kwargs: Any) -> object:
        del kwargs
        return self._call("answer", backend_role, case)

    def judge(self, *, backend_role: str, case: ManagedRunCase, **kwargs: Any) -> object:
        del kwargs
        return self._call("judge", backend_role, case)

    def seal_execution(
        self,
        *,
        case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
        case_manifest_sha256: str,
        **kwargs: Any,
    ) -> ManagedExecutionArtifacts:
        del kwargs
        self.sealed_manifest_sha256 = case_manifest_sha256
        self.sealed_manifest = case_manifest
        self.events.append("execution.seal")
        if self.fail_at == "execution.seal":
            raise _Abort("execution.seal")
        return ManagedExecutionArtifacts(
            object(),
            object(),
            self.manifest_override or case_manifest_sha256,
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


def _plan(
    *,
    scope: str = "full",
    cases: tuple[ManagedRunCase, ...] | None = None,
    case_manifest: tuple[FullExecutionCaseManifestEntry, ...] | None = None,
) -> ManagedRunPlan:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    return ManagedRunPlan(
        run_id="managed-test",
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
        case_manifest=_manifest() if case_manifest is None else case_manifest,
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
        cases=_cases() if cases is None else cases,
        scope=scope,
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
    scope: str = "full",
    attestation_commitment: object = "8" * 64,
    managed_attestation: object = _MANAGED_ATTESTATION,
    plan: ManagedRunPlan | None = None,
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
    assert rig.execution.sealed_manifest == _manifest()
    assert rig.execution.sealed_manifest_sha256 == execution_case_manifest_sha256(_manifest())


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
    rig.execution.manifest_override = "9" * 64

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


def test_plan_scope_is_normalized_and_invalid_scope_fails_at_construction() -> None:
    assert _plan(scope=" CANARY ").scope == "canary"

    with pytest.raises(BenchmarkValidationError, match="unsupported full comparison scope"):
        _plan(scope="preview")


@pytest.mark.parametrize(
    ("case_manifest", "error_type", "message"),
    (
        (
            (replace(_manifest()[0], case_id="case-x"), _manifest()[1]),
            ManagedRunError,
            "case manifest order or case/corpus binding",
        ),
        (
            tuple(reversed(_manifest())),
            ManagedRunError,
            "case manifest order or case/corpus binding",
        ),
        (
            (replace(_manifest()[0], corpus_id="corpus-x"), _manifest()[1]),
            ManagedRunError,
            "case manifest order or case/corpus binding",
        ),
        (
            (replace(_manifest()[0], official_turn_count=0), _manifest()[1]),
            ManagedRunError,
            "LoCoMo official turn coverage is empty",
        ),
    ),
)
def test_manifest_contract_violations_fail_at_plan_construction_before_consume(
    case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
    error_type: type[BaseException],
    message: str,
) -> None:
    with pytest.raises(error_type, match=message):
        _plan(case_manifest=case_manifest)


def test_manifest_allows_case_local_thread_and_alias_reuse() -> None:
    first, second = _manifest()
    manifest = (
        first,
        replace(
            second,
            thread_id=first.thread_id,
            session_aliases=first.session_aliases,
        ),
    )

    plan = _plan(case_manifest=manifest)

    assert plan.case_manifest == manifest


def test_live_manifest_revalidation_blocks_tampering_before_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig()
    plan = _plan()
    object.__setattr__(plan, "case_manifest", tuple(reversed(plan.case_manifest)))

    with pytest.raises(
        ManagedRunError,
        match="case manifest order or case/corpus binding",
    ):
        _run(rig, monkeypatch, plan=plan)

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

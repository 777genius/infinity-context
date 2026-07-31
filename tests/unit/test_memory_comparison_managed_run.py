from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from infinity_context_server import memory_comparison_managed_run as managed
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

_SHA = "a" * 64


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
        self, *, case_manifest_sha256: str, **kwargs: Any
    ) -> ManagedExecutionArtifacts:
        del kwargs
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

    def seal_canonical_source(
        self, *, cases: tuple[ManagedRunCase, ...], **kwargs: Any
    ) -> tuple[object, ...]:
        del kwargs
        self.events.append("canonical_source.seal")
        if self.fail_at == "canonical_source.seal":
            raise _Abort("canonical_source.seal")
        return tuple(object() for _ in cases)

    def terminal_delete(self, *, backend_role: str, pass_index: int, **kwargs: Any) -> object:
        del kwargs
        event = f"delete:{backend_role}:{pass_index}"
        self.events.append(event)
        if self.fail_at == event:
            raise RuntimeError(event)
        return object()

    def seal_terminal_delete(self, **kwargs: Any) -> object:
        del kwargs
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


def _plan(*, scope: str = "full") -> ManagedRunPlan:
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
        cases=(
            ManagedRunCase("case-1", "corpus-1", {"text": "one"}),
            ManagedRunCase("case-2", "corpus-1", {"text": "one"}),
        ),
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


def _patch_attestation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        managed,
        "_issue_verified_managed_composition_attestation_for_composition_root",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        managed,
        "public_managed_composition_attestation",
        lambda *args, **kwargs: {"composition_attestation_sha256": "8" * 64},
    )


def _run(rig: _Rig, monkeypatch: pytest.MonkeyPatch, *, scope: str = "full"):
    _patch_attestation(monkeypatch)
    return run_managed_comparison(
        _plan(scope=scope),
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
    assert rig.events.count("ingest:infinity-context") == 1
    assert rig.events.count("ingest:mem0") == 1
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

    with pytest.raises(_Abort, match=stage):
        _run(rig, monkeypatch)

    assert len(_deletes(rig.events)) == 4
    assert "policy.aggregate" not in rig.events
    assert "components.issue" not in rig.events
    assert "verdict.public" not in rig.events


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

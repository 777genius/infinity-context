from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import pytest
from infinity_context_server import memory_comparison_managed_run as managed
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    FullExecutionProviderCall,
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
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    GoldBlindEvidence,
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    JUDGE_RESULT_SCHEMA_VERSION,
    GoldBlindJudgeResult,
)
from infinity_context_server.memory_comparison_gold_blind_run_validation import (
    canonical_dispatch_json,
)
from infinity_context_server.memory_comparison_managed_execution_receipts import (
    ManagedSealedJudgeOutcome,
    consume_sealed_managed_execution_receipt,
    create_managed_execution_receipt_issuer,
    issue_managed_answer_receipt,
    issue_managed_judge_receipt,
    issue_managed_retrieval_receipt,
    seal_managed_execution_receipt,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    VerifiedManagedRunPlan,
    build_verified_managed_run_plan,
    managed_execution_case_material_sha256,
)
from infinity_context_server.memory_comparison_managed_provider_calls import (
    ManagedProviderCallOutcome,
    ManagedProviderLaneBinding,
)
from infinity_context_server.memory_comparison_managed_run import (
    ManagedAnswerCase,
    ManagedCaseExecution,
    ManagedExecutionArtifacts,
    ManagedRunCase,
    ManagedRunError,
    ManagedRunPlan,
    run_managed_comparison,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderCallProvenance,
    ProviderChatCompletion,
    ProviderRouteAttestation,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

SHA = "a" * 64
MANAGED_ATTESTATION = object()
_RECEIPT_ROUTE = ProviderRouteAttestation(
    trust="official_openai",
    origin="https://api.openai.com",
    endpoint_path="/v1/chat/completions",
    route_sha256="b" * 64,
    transport_evidence="direct_https",
    credential_binding_id="sha256:" + "c" * 64,
    request_method="POST",
    response_status=200,
)


class Abort(BaseException):
    pass


class _Port:
    def __init__(self, name: str, events: list[str]) -> None:
        self.adapter_id = name
        self.implementation_sha256 = SHA
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
            raise Abort(name)
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
            raise Abort("judge")
        return object()

    def seal_execution(
        self,
        *,
        bindings: FullComparisonRunBindings,
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
            raise Abort("execution.seal")
        return ManagedExecutionArtifacts(
            object(),
            object(),
            self.manifest_override or case_manifest_sha256,
            self.material_override or case_material_sha256,
            tuple(
                sealed_judge_outcome(
                    bindings=bindings,
                    case_alias=item.case_id,
                    backend_role=item.backend_role,
                    verdict=(
                        "correct"
                        if item.backend_role == "infinity-context"
                        else "incorrect"
                    ),
                    score=1.0 if item.backend_role == "infinity-context" else 0.0,
                )
                for item in executions
            ),
        )


def sealed_judge_outcome(
    *,
    bindings: FullComparisonRunBindings,
    case_alias: str,
    backend_role: str,
    verdict: str,
    score: float,
) -> ManagedSealedJudgeOutcome:
    """Build a test proof through the same receipt issue/seal/consume path."""

    target = tuple(
        item.target_identity_sha256
        for item in bindings.backend_targets
        if item.backend_role == backend_role
    )
    assert len(target) == 1
    answer_binding = ManagedProviderLaneBinding(
        bindings.binding_commitment_sha256,
        bindings.run_id,
        bindings.profile_id,
        case_alias,
        backend_role,
        "answerer",
        "receipt-answerer",
        0,
    )
    judge_binding = ManagedProviderLaneBinding(
        bindings.binding_commitment_sha256,
        bindings.run_id,
        bindings.profile_id,
        case_alias,
        backend_role,
        "judge",
        "receipt-judge",
        1,
    )
    issuer = create_managed_execution_receipt_issuer(
        answer_binding=answer_binding,
        judge_binding=judge_binding,
        target_identity_sha256=target[0],
    )
    evidence = (GoldBlindEvidence("receipt-evidence", "receipt evidence", 1, None),)
    retrieved = issue_managed_retrieval_receipt(
        issuer,
        evidence=evidence,
        retrieval_identity=gold_blind_evidence_identity(evidence),
    )
    answered = issue_managed_answer_receipt(
        issuer,
        predecessor=retrieved,
        outcome=_receipt_outcome(answer_binding),
        answer_result_identity=hashlib.sha256(b"receipt-answer").hexdigest(),
    )
    result = GoldBlindJudgeResult(verdict=verdict, score=score)
    result_sha256 = hashlib.sha256(
        canonical_dispatch_json(
            {
                "schema_version": JUDGE_RESULT_SCHEMA_VERSION,
                "score": result.score,
                "verdict": result.verdict,
            }
        )
    ).hexdigest()
    judged = issue_managed_judge_receipt(
        issuer,
        predecessor=answered,
        outcome=_receipt_outcome(judge_binding),
        judge_result=result,
        judge_result_sha256=result_sha256,
    )
    _calls, proof = consume_sealed_managed_execution_receipt(
        issuer,
        seal_managed_execution_receipt(issuer, predecessor=judged),
    )
    return proof


def _receipt_outcome(binding: ManagedProviderLaneBinding) -> ManagedProviderCallOutcome:
    response_id = f"receipt-{binding.public_case_alias}-{binding.backend_role}-{binding.stage}"
    provenance = ProviderCallProvenance(
        _RECEIPT_ROUTE,
        binding.model,
        binding.model,
        response_id,
        "receipt-fingerprint",
        hashlib.sha256(response_id.encode()).hexdigest(),
    )
    completion = ProviderChatCompletion(
        text="receipt-bound",
        prompt_tokens=1,
        completion_tokens=1,
        token_usage_source="provider_observed",
        provenance=provenance,
    )
    call = FullExecutionProviderCall(
        binding.comparison_commitment_sha256,
        binding.run_id,
        binding.profile_id,
        binding.public_case_alias,
        binding.backend_role,
        binding.stage,
        False,
        provenance,
    )
    return ManagedProviderCallOutcome(binding, completion, call)


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
        self.sealed_case_manifest_sha256: str | None = None

    def seal_canonical_source(
        self,
        *,
        cases: tuple[ManagedRunCase, ...],
        managed_attestation: object,
        managed_attestation_commitment_sha256: str | None,
        case_manifest_sha256: str,
        **kwargs: Any,
    ) -> tuple[object, ...]:
        del kwargs
        self.sealed_managed_attestation = managed_attestation
        self.sealed_managed_commitment = managed_attestation_commitment_sha256
        self.sealed_case_manifest_sha256 = case_manifest_sha256
        self.events.append("canonical_source.seal")
        if managed_attestation is None:
            raise ManagedRunError("managed attestation is required for canonical/source")
        if managed_attestation_commitment_sha256 is None:
            raise ManagedRunError("managed attestation commitment is required")
        if managed_attestation_commitment_sha256 != self.expected_managed_commitment_sha256:
            raise ManagedRunError("managed attestation commitment mismatch")
        if self.fail_at == "canonical_source.seal":
            raise Abort("canonical_source.seal")
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
class Rig:
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


CASE_IDS = ("corpus-1:qa:1", "corpus-2:qa:1")


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


def make_plan(
    *,
    scope: str = "canary",
    run_id: str = "managed-test",
) -> VerifiedManagedRunPlan:
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    return build_verified_managed_run_plan(
        run_id=run_id,
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
        selected_case_ids=CASE_IDS,
    )


def make_legacy_plan() -> ManagedRunPlan:
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


def make_rig() -> Rig:
    events: list[str] = []
    return Rig(
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


def patch_attestation(
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


def run_managed(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    *,
    scope: str = "canary",
    attestation_commitment: object = "8" * 64,
    managed_attestation: object = MANAGED_ATTESTATION,
    plan: VerifiedManagedRunPlan | ManagedRunPlan | None = None,
):
    patch_attestation(
        monkeypatch,
        commitment=attestation_commitment,
        attestation=managed_attestation,
    )
    return run_managed_comparison(
        make_plan(scope=scope) if plan is None else plan,
        reset_port=rig.reset,
        attestation_port=rig.attest,
        ingest_port=rig.ingest,
        clock=rig.clock,
        execution_port=rig.execution,
        judge_port=rig.judge,
        policy_port=rig.policy,
        assembler=rig.assembler,
    )


def delete_events(events: list[str]) -> list[str]:
    return [item for item in events if item.startswith("delete:")]


def assert_not_published(events: list[str]) -> None:
    assert {"policy.aggregate", "components.issue", "verdict.public"}.isdisjoint(events)


__all__ = (
    "Abort",
    "CASE_IDS",
    "MANAGED_ATTESTATION",
    "Rig",
    "assert_not_published",
    "delete_events",
    "make_legacy_plan",
    "make_plan",
    "make_rig",
    "patch_attestation",
    "run_managed",
    "sealed_judge_outcome",
)

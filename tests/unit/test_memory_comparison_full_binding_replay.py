from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import infinity_context_server.memory_comparison_full_run_components as component_module
import pytest
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    PROFILE_LOCOMO_TOP_200,
    PROFILE_LONGMEMEVAL_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_components import (
    issue_gold_blind_component_evidence,
    issue_runtime_component_evidence,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
    FullComparisonEvidenceError,
    FullComparisonRunBindings,
    create_full_comparison_evidence_issuer,
    create_full_comparison_run_bindings,
    issue_full_comparison_run_evidence,
)
from infinity_context_server.memory_comparison_full_verdict import (
    FullComparisonVerdictError,
    public_full_comparison_verdict,
    verify_full_comparison_run,
)
from infinity_context_server.memory_comparison_gold_blind import (
    build_gold_blind_contract,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    GoldBlindContractError,
    GoldBlindEvidence,
    GoldBlindExpectedDispatchCase,
    GoldBlindJudgeResult,
    JudgeRunKey,
    VerifiedGoldBlindExecutionValidation,
    create_gold_blind_run_dispatch_ledger,
    create_trusted_gold_blind_evaluator,
    dispatch_answer,
    dispatch_judge,
    dispatch_retrieval,
    issue_gold_blind_judge_dispatch_binding,
    verified_gold_blind_execution_report,
    verify_gold_blind_execution,
)
from infinity_context_server.memory_comparison_mem0_contract import (
    MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    VerifiedMem0RuntimeAttestationValidation,
    build_verified_mem0_runtime_attestation,
    mem0_runtime_target_identity_sha256,
    validate_mem0_runtime_attestation_for_backends,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_RUN = "full-binding-run"
_NONCE = "probe-nonce-1"
_TARGET = mem0_runtime_target_identity_sha256("https://mem0.example.test/adapter")
_CASE = "binding-case"
_RETRIEVAL = "retrieval-v1"
_ANSWER = "answer-v1"
_JUDGE = "judge-v1"


def _bindings(
    *,
    run_id: str = _RUN,
    profile_id: str = PROFILE_LOCOMO_TOP_50,
    selection: str = "5" * 64,
    probe_nonce_sha256: str | None = None,
    mem0_target: str = _TARGET,
) -> FullComparisonRunBindings:
    profile = resolve_full_comparison_profile(profile_id)
    assert profile is not None
    return create_full_comparison_run_bindings(
        run_id=run_id,
        run_nonce_commitment_sha256="4" * 64,
        runtime_probe_nonce_sha256=(
            probe_nonce_sha256
            if probe_nonce_sha256 is not None
            else hashlib.sha256(_NONCE.encode()).hexdigest()
        ),
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256=profile.expected_dataset_hash,
        selection_fingerprint_sha256=selection,
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", "6" * 64),
            FullComparisonBackendTarget("mem0", mem0_target),
        ),
    )


class _Retriever:
    def search(
        self,
        request: Mapping[str, object],
        *,
        run_id: str,
        top_k: int,
    ) -> tuple[GoldBlindEvidence, ...]:
        del request, run_id, top_k
        return (
            GoldBlindEvidence(
                item_id="item-1",
                text="retrieved evidence",
                rank=1,
                created_at="2023-01-02T10:00:00Z",
            ),
        )


class _Answerer:
    def answer(self, request: Mapping[str, object]) -> object:
        del request
        return {"answer": "ok"}


def _judge_callback(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del ground_truth, expected_terms, forbidden_terms
    return GoldBlindJudgeResult(verdict="correct", score=1.0)


def _gold_validation(
    bindings: FullComparisonRunBindings,
) -> VerifiedGoldBlindExecutionValidation:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id=_CASE,
        question="What happened?",
        expected_terms=("private-answer",),
        metadata={
            "_evaluator_ground_truth": {"answer": "private-answer"},
            "reference_date": "2 January 2023",
        },
    )
    key = JudgeRunKey.issue(run_id=bindings.run_id, case_id=_CASE)
    ledger = create_gold_blind_run_dispatch_ledger(
        run_id=bindings.run_id,
        comparison_binding_commitment_sha256=bindings.binding_commitment_sha256,
        expected_cases=(
            GoldBlindExpectedDispatchCase(
                case_id=_CASE,
                retrieval_backend_id=_RETRIEVAL,
                answer_backend_id=_ANSWER,
                judge_backend_id=_JUDGE,
            ),
        ),
    )
    contract = build_gold_blind_contract(
        case,
        run_id=bindings.run_id,
        judge_key=key,
        dispatch_ledger=ledger,
    )
    evidence = dispatch_retrieval(
        _Retriever(),
        contract.retrieval_request,
        backend_id=_RETRIEVAL,
        dispatch_ledger=ledger,
        run_id=bindings.run_id,
        top_k=5,
    )
    dispatch_answer(
        _Answerer(),
        contract.answer_request(evidence),
        backend_id=_ANSWER,
        dispatch_ledger=ledger,
        run_id=bindings.run_id,
        case_id=_CASE,
    )
    dispatch_judge(
        create_trusted_gold_blind_evaluator(_judge_callback),
        contract.judge_channel,
        backend_id=_JUDGE,
        dispatch_ledger=ledger,
        answer_binding=issue_gold_blind_judge_dispatch_binding(
            ledger,
            run_id=bindings.run_id,
            case_id=_CASE,
            backend_id=_JUDGE,
        ),
        key=key,
        run_id=bindings.run_id,
        case_id=_CASE,
    )
    return verify_gold_blind_execution(ledger)


def test_gold_producer_report_commits_full_comparison_binding() -> None:
    bindings = _bindings()
    validation = _gold_validation(bindings)
    report = verified_gold_blind_execution_report(validation)

    assert report["comparison_binding_commitment_sha256"] == (bindings.binding_commitment_sha256)
    issuer = create_full_comparison_evidence_issuer(bindings)
    component = issue_gold_blind_component_evidence(issuer, validation)
    evidence = issue_full_comparison_run_evidence(bindings, (component,), issuer)
    verdict = public_full_comparison_verdict(verify_full_comparison_run(evidence))
    summary = {item["component_kind"]: item["status"] for item in verdict["components"]}
    assert summary["gold_blind"] == "verified"


def test_gold_replay_rejected_across_every_comparison_axis() -> None:
    source = _bindings()
    validation = _gold_validation(source)
    same_dataset_other_methodology = _bindings(profile_id=PROFILE_LOCOMO_TOP_200)
    other_dataset_profile_methodology = _bindings(profile_id=PROFILE_LONGMEMEVAL_TOP_50)
    variants = (
        _bindings(selection="7" * 64),
        same_dataset_other_methodology,
        other_dataset_profile_methodology,
        _bindings(mem0_target="8" * 64),
        _bindings(probe_nonce_sha256="9" * 64),
        _bindings(run_id="other-full-binding-run"),
    )
    assert same_dataset_other_methodology.dataset_sha256 == source.dataset_sha256
    assert (
        same_dataset_other_methodology.methodology_commitment_sha256
        != source.methodology_commitment_sha256
    )
    assert other_dataset_profile_methodology.dataset_sha256 != source.dataset_sha256

    for target in variants:
        with pytest.raises(FullComparisonEvidenceError, match="gold_blind validation binding"):
            issue_gold_blind_component_evidence(
                create_full_comparison_evidence_issuer(target),
                validation,
            )


def test_invalid_gold_binding_cannot_be_added_post_hoc() -> None:
    with pytest.raises(TypeError):
        create_gold_blind_run_dispatch_ledger(  # type: ignore[call-arg]
            run_id=_RUN,
            expected_cases=(
                GoldBlindExpectedDispatchCase(
                    case_id=_CASE,
                    retrieval_backend_id=_RETRIEVAL,
                    answer_backend_id=_ANSWER,
                    judge_backend_id=_JUDGE,
                ),
            ),
        )
    with pytest.raises(GoldBlindContractError, match="commitment.*invalid"):
        create_gold_blind_run_dispatch_ledger(
            run_id=_RUN,
            comparison_binding_commitment_sha256="not-a-sha",
            expected_cases=(
                GoldBlindExpectedDispatchCase(
                    case_id=_CASE,
                    retrieval_backend_id=_RETRIEVAL,
                    answer_backend_id=_ANSWER,
                    judge_backend_id=_JUDGE,
                ),
            ),
        )


class _RuntimeBackend:
    def __init__(self, name: str, *, target: str | None = None) -> None:
        self.name = name
        if target is not None:
            self.runtime_target_identity_sha256 = target


def _runtime_manifest(
    now: datetime,
    *,
    run_id: str = _RUN,
    nonce: str = _NONCE,
    target: str = _TARGET,
) -> dict[str, object]:
    checked_at = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {
        "schema_version": MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
        "runtime_mode": "managed_platform",
        "wrapper_source_sha256": "a" * 64,
        "wrapper_source_revision": "b" * 40,
        "config_fingerprint_sha256": "c" * 64,
        "sdk": {
            "distribution": "mem0ai",
            "version": "2.0.14",
            "source_revision": "b357a5a1b03c299ec8229c268e63cfac0f7c6566",
            "artifact_sha256": ("9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"),
            "verification": {
                "method": "direct_url_archive_info_sha256",
                "observed_sha256": (
                    "9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"
                ),
                "passed": True,
            },
        },
        "platform": {
            "api_origin": "https://api.mem0.ai",
            "api_generation": "v3",
            "add_path": "/v3/memories/add/",
            "search_path": "/v3/memories/search/",
            "event_path_template": "/v1/event/{event_id}/",
            "server_source_revision": None,
            "server_revision_attestable": False,
        },
        "timestamp": {
            "request_supported": True,
            "sdk_forwarding_supported": True,
            "event_completion_supported": True,
            "readback_supported": True,
            "attestation": {
                "status": "passed",
                "checked_at": checked_at,
                "probe_mode": "live_sentinel",
                "input_epoch_seconds": 1_672_531_200,
                "expected_created_at": "2023-01-01T00:00:00Z",
                "event_terminal_status": "SUCCEEDED",
                "readback_result_count": 1,
                "persisted_created_at": "2023-01-01T00:00:00Z",
                "delta_seconds": 0.0,
                "cleanup_succeeded": True,
                "failure_code": None,
            },
        },
        "refresh_binding": {
            "status": "passed",
            "run_id_sha256": hashlib.sha256(run_id.encode()).hexdigest(),
            "probe_nonce_sha256": hashlib.sha256(nonce.encode()).hexdigest(),
            "target_identity_sha256": target,
            "refreshed_at": checked_at,
        },
    }


def _runtime_validation(
    *,
    now: datetime,
    run_id: str = _RUN,
    nonce: str = _NONCE,
    target: str = _TARGET,
) -> VerifiedMem0RuntimeAttestationValidation:
    manifest = _runtime_manifest(now, run_id=run_id, nonce=nonce, target=target)
    manifest_fingerprint = hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    binding = manifest["refresh_binding"]
    assert isinstance(binding, dict)
    message = "\n".join(
        (
            "mem0-benchmark-runtime-witness.v1",
            str(binding["run_id_sha256"]),
            str(binding["probe_nonce_sha256"]),
            str(binding["target_identity_sha256"]),
            str(binding["refreshed_at"]),
            manifest_fingerprint,
        )
    ).encode()
    token = "full-binding-runtime-token"
    manifest["refresh_witness"] = {
        "algorithm": "hmac-sha256",
        "manifest_fingerprint_sha256": manifest_fingerprint,
        "signature": hmac.new(token.encode(), message, hashlib.sha256).hexdigest(),
    }
    verified = build_verified_mem0_runtime_attestation(
        runtime_manifest=manifest,
        benchmark_probe_token=token,
        openapi_fingerprint_sha256="d" * 64,
        openapi_contract_violations=(),
        probe_passed=True,
        run_id=run_id,
        probe_nonce=nonce,
        target_identity_sha256=target,
    )
    assert verified is not None
    validation = validate_mem0_runtime_attestation_for_backends(
        verified,
        (
            _RuntimeBackend("infinity-context"),
            _RuntimeBackend("mem0", target=target),
        ),
        run_id,
        nonce,
        validated_at=datetime.now(UTC),
    )
    assert type(validation) is VerifiedMem0RuntimeAttestationValidation
    return validation


def test_runtime_component_binds_run_probe_and_exact_mem0_target() -> None:
    now = datetime.now(UTC)
    bindings = _bindings()
    validation = _runtime_validation(now=now)
    issuer = create_full_comparison_evidence_issuer(bindings)
    component = issue_runtime_component_evidence(issuer, validation)
    evidence = issue_full_comparison_run_evidence(bindings, (component,), issuer)
    report = public_full_comparison_verdict(verify_full_comparison_run(evidence))
    status = {item["component_kind"]: item["status"] for item in report["components"]}
    assert status["runtime"] == "verified"

    variants = (
        _bindings(run_id="other-runtime-run"),
        _bindings(probe_nonce_sha256="1" * 64),
        _bindings(mem0_target="2" * 64),
    )
    for replay_binding in variants:
        with pytest.raises(FullComparisonEvidenceError, match="runtime validation binding"):
            issue_runtime_component_evidence(
                create_full_comparison_evidence_issuer(replay_binding),
                validation,
            )


def test_runtime_current_clock_staleness_rechecked_at_issue_and_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime.now(UTC)
    bindings = _bindings()
    validation = _runtime_validation(now=observed_at)
    issuer = create_full_comparison_evidence_issuer(bindings)
    component = issue_runtime_component_evidence(issuer, validation)
    evidence = issue_full_comparison_run_evidence(bindings, (component,), issuer)
    verdict = verify_full_comparison_run(evidence)

    class _FutureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            del tz
            return observed_at + timedelta(seconds=121)

    monkeypatch.setattr(component_module, "datetime", _FutureClock)
    with pytest.raises(FullComparisonVerdictError, match="stale"):
        public_full_comparison_verdict(verdict)
    with pytest.raises(FullComparisonEvidenceError, match="runtime validation binding"):
        issue_runtime_component_evidence(
            create_full_comparison_evidence_issuer(bindings),
            validation,
        )


def test_runtime_future_clock_skew_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime.now(UTC)
    validation = _runtime_validation(now=observed_at)
    bindings = _bindings()

    public = component_module.public_mem0_runtime_attestation_validation(validation)
    validated_at = datetime.fromisoformat(str(public["validated_at"]).replace("Z", "+00:00"))

    class _AllowedSkewClock(datetime):
        @classmethod
        def now(cls, tz=None):
            del tz
            return validated_at - timedelta(seconds=0.999)

    monkeypatch.setattr(component_module, "datetime", _AllowedSkewClock)
    component = issue_runtime_component_evidence(
        create_full_comparison_evidence_issuer(bindings),
        validation,
    )
    assert component is not None

    class _RejectedSkewClock(datetime):
        @classmethod
        def now(cls, tz=None):
            del tz
            return validated_at - timedelta(seconds=1.001)

    monkeypatch.setattr(component_module, "datetime", _RejectedSkewClock)
    with pytest.raises(FullComparisonEvidenceError, match="runtime validation binding"):
        issue_runtime_component_evidence(
            create_full_comparison_evidence_issuer(bindings),
            validation,
        )

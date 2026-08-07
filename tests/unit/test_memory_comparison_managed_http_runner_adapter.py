from __future__ import annotations

import json
from datetime import UTC, datetime
from types import MappingProxyType, MethodType, SimpleNamespace
from typing import cast

import pytest
from infinity_context_server import memory_comparison_managed_http_runner_adapter as module
from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_execution_validation import (
    VerifiedFullExecutionValidation,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    GoldBlindEvidence,
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedComparisonHttpExecutionAdapter,
    ManagedHttpRetrievalResult,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedComparisonHttpLifecycleAdapter,
    ManagedHttpExecutionEvidenceView,
)
from infinity_context_server.memory_comparison_managed_http_runner_adapter import (
    ManagedHttpRunnerAdapter,
    ManagedHttpRunnerAdapterError,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)


def _composition():
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    targets = (
        FullComparisonBackendTarget("infinity-context", "a" * 64),
        FullComparisonBackendTarget("mem0", "b" * 64),
    )
    binding = ManagedRunnerCompositionBinding(
        run_id="managed-neutral-run",
        profile=profile,
        binding_commitment_sha256="c" * 64,
        deadline=datetime(2026, 8, 8, tzinfo=UTC),
        backend_targets=targets,
        retrieval_top_k=profile.retrieval_top_k,
        answer_cutoff=profile.answer_cutoff,
    )
    http, lifecycle = _legacy_for_binding(binding)
    return binding, http, lifecycle


def _legacy_for_binding(binding: ManagedRunnerCompositionBinding):
    http = object.__new__(ManagedComparisonHttpExecutionAdapter)
    http._profile = binding.profile
    http._run_id = binding.run_id
    http._deadline = binding.deadline
    http._targets = {
        item.backend_role: item.target_identity_sha256 for item in binding.backend_targets
    }
    lifecycle = object.__new__(ManagedComparisonHttpLifecycleAdapter)
    lifecycle._run_id = binding.run_id
    lifecycle._binding = binding.binding_commitment_sha256
    lifecycle._deadline = binding.deadline
    lifecycle._target_pairs = tuple(
        (item.backend_role, item.target_identity_sha256) for item in binding.backend_targets
    )
    lifecycle._execution = http
    return http, lifecycle


def _golden(value: object) -> bytes:
    def thaw(item: object) -> object:
        if type(item) is MappingProxyType:
            return {key: thaw(child) for key, child in item.items()}  # type: ignore[union-attr]
        if type(item) is tuple:
            return [thaw(child) for child in item]
        return item

    result = value
    return json.dumps(
        {
            "evidence": [
                [item.item_id, item.text, item.rank, item.created_at]
                for item in result.evidence  # type: ignore[attr-defined]
            ],
            "metadata": thaw(result.metadata),  # type: ignore[attr-defined]
            "retrieval_identity": result.retrieval_identity,  # type: ignore[attr-defined]
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def test_retrieve_is_a_direct_delegate_with_golden_result_parity() -> None:
    binding, http, lifecycle = _composition()
    case = ManagedRunCase("case-1", "corpus-1", {})
    query = ManagedAnswerCase("case-1", "Where?", {})
    evidence = (GoldBlindEvidence("item-1", "Kyiv", 1, None),)
    legacy = ManagedHttpRetrievalResult(
        evidence,
        gold_blind_evidence_identity(evidence),
        {
            "adapter_id": "managed-http-comparison.v1",
            "backend": {"ids": ["item-1"]},
            "retrieval_top_k": binding.retrieval_top_k,
            "answer_cutoff": binding.answer_cutoff,
        },
    )
    calls: list[dict[str, object]] = []

    def retrieve(_self: object, **kwargs: object) -> ManagedHttpRetrievalResult:
        calls.append(kwargs)
        return legacy

    http.retrieve = MethodType(retrieve, http)
    adapter = ManagedHttpRunnerAdapter(
        composition_binding=binding,
        http=http,
        lifecycle=lifecycle,
    )
    authority = adapter.authority_for(
        backend_role="mem0",
        target_identity_sha256="b" * 64,
    )
    result = adapter.retrieve(authority=authority, case=case, query=query)
    foreign_binding, foreign_http, foreign_lifecycle = _composition()
    foreign_authority = ManagedHttpRunnerAdapter(
        composition_binding=foreign_binding,
        http=foreign_http,
        lifecycle=foreign_lifecycle,
    ).authority_for(backend_role="mem0", target_identity_sha256="b" * 64)

    assert _golden(result) == _golden(legacy)
    assert calls == [
        {
            "run_id": binding.run_id,
            "backend_role": "mem0",
            "target_identity_sha256": "b" * 64,
            "case": case,
            "query": query,
        }
    ]
    with pytest.raises(ManagedHttpRunnerAdapterError, match="retrieval_invalid"):
        adapter.retrieve(authority=foreign_authority, case=case, query=query)
    object.__setattr__(authority, "_backend_role", "infinity-context")
    object.__setattr__(authority, "_target_identity", "a" * 64)
    with pytest.raises(ManagedHttpRunnerAdapterError, match="retrieval_invalid"):
        adapter.retrieve(authority=authority, case=case, query=query)
    assert len(calls) == 1


def test_adapter_rejects_a_frankenstein_legacy_composition() -> None:
    binding, http, lifecycle = _composition()
    lifecycle._deadline = datetime(2026, 8, 8, tzinfo=UTC)

    with pytest.raises(ManagedHttpRunnerAdapterError, match="composition_invalid"):
        ManagedHttpRunnerAdapter(
            composition_binding=binding,
            http=http,
            lifecycle=lifecycle,
        )


def test_adapter_binding_swap_stops_before_the_b1_delegate() -> None:
    binding, http, lifecycle = _composition()
    calls: list[dict[str, object]] = []
    http.retrieve = MethodType(lambda _self, **kwargs: calls.append(kwargs), http)
    adapter = ManagedHttpRunnerAdapter(
        composition_binding=binding,
        http=http,
        lifecycle=lifecycle,
    )
    authority = adapter.authority_for(
        backend_role="mem0", target_identity_sha256="b" * 64
    )
    binding_b2, _, _ = _composition()
    object.__setattr__(adapter, "_binding", binding_b2)

    with pytest.raises(ManagedHttpRunnerAdapterError, match="composition_invalid"):
        adapter.retrieve(
            authority=authority,
            case=ManagedRunCase("case-1", "corpus-1", {}),
            query=ManagedAnswerCase("case-1", "Where?", {}),
        )
    assert calls == []


@pytest.mark.parametrize("field", ["_http", "_lifecycle", "_execution"])
def test_adapter_legacy_swap_stops_before_delegate(field: str) -> None:
    binding, http, lifecycle = _composition()
    calls: list[dict[str, object]] = []
    http.retrieve = MethodType(lambda _self, **kwargs: calls.append(kwargs), http)
    adapter = ManagedHttpRunnerAdapter(
        composition_binding=binding,
        http=http,
        lifecycle=lifecycle,
    )
    authority = adapter.authority_for(
        backend_role="mem0", target_identity_sha256="b" * 64
    )
    _, replacement_http, replacement_lifecycle = _composition()
    if field == "_execution":
        object.__setattr__(lifecycle, field, replacement_http)
    else:
        object.__setattr__(
            adapter,
            field,
            replacement_http if field == "_http" else replacement_lifecycle,
        )

    with pytest.raises(ManagedHttpRunnerAdapterError, match="composition_invalid"):
        adapter.retrieve(
            authority=authority,
            case=ManagedRunCase("case-1", "corpus-1", {}),
            query=ManagedAnswerCase("case-1", "Where?", {}),
        )
    assert calls == []


def test_evidence_is_consumed_privately_then_full_validation_is_sealed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, http, lifecycle = _composition()
    lifecycle.execution_evidence_capability = MethodType(lambda _self: object(), lifecycle)
    adapter = ManagedHttpRunnerAdapter(
        composition_binding=binding,
        http=http,
        lifecycle=lifecycle,
    )
    case = ManagedRunCase("case-1", "corpus-1", {})
    trusted = SimpleNamespace(
        run_id=binding.run_id,
        profile_id=binding.profile_id,
        binding_commitment_sha256=binding.binding_commitment_sha256,
        backend_targets=binding.backend_targets,
    )
    bindings = cast(FullComparisonRunBindings, trusted)
    view = object.__new__(ManagedHttpExecutionEvidenceView)
    object.__setattr__(view, "validation", object())
    object.__setattr__(view, "scopes", ())
    object.__setattr__(view, "provenance", MappingProxyType({"source": "legacy-http"}))
    object.__setattr__(view, "_ManagedHttpExecutionEvidenceView__attestation_key", b"k" * 32)
    verifier = object()
    evidence = (object(),)
    object.__setattr__(view, "_ManagedHttpExecutionEvidenceView__locomo_verifier", verifier)
    object.__setattr__(view, "_ManagedHttpExecutionEvidenceView__locomo_evidence", evidence)
    consumed: list[dict[str, object]] = []
    issued: list[dict[str, object]] = []
    proof = object.__new__(VerifiedFullExecutionValidation)

    monkeypatch.setattr(module, "validate_full_comparison_run_bindings", lambda value: trusted)
    monkeypatch.setattr(module, "_evidence_snapshot", lambda value: "s" * 64)

    def consume(_capability: object, **kwargs: object) -> ManagedHttpExecutionEvidenceView:
        consumed.append(kwargs)
        return view

    def issue(**kwargs: object) -> object:
        issued.append(kwargs)
        return object()

    monkeypatch.setattr(module, "consume_managed_http_execution_evidence", consume)
    monkeypatch.setattr(module, "issue_full_execution_validation_session", issue)
    monkeypatch.setattr(module, "seal_full_execution_validation", lambda session: proof)

    adapter.consume_ready_evidence(
        composition_binding=binding,
        bindings=bindings,
        cases=(case,),
    )
    result = adapter.seal_execution_validation(
        composition_binding=binding,
        bindings=bindings,
        benchmark="locomo",
        case_manifest=(),
        required_model="gpt-5.6-sol",
        required_route=cast(object, object()),
        provider_calls=(),
        session_verifier=cast(object, object()),
        session_evidence=(),
    )

    assert result is proof
    assert consumed == [
        {
            "run_id": binding.run_id,
            "binding_commitment_sha256": binding.binding_commitment_sha256,
            "backend_targets": binding.backend_targets,
            "cases": (case,),
        }
    ]
    assert issued[0]["transport_verifier"] is verifier
    assert issued[0]["transport_evidence"] is evidence
    assert issued[0]["clean_validation"] is view.validation
    assert issued[0]["clean_attestation_key"] == b"k" * 32
    assert not hasattr(adapter, "execution_evidence")
    assert adapter._evidence is None
    assert adapter._evidence_snapshot is None
    assert adapter._phase == "sealed"
    with pytest.raises(ManagedHttpRunnerAdapterError, match="bindings_invalid"):
        adapter.seal_execution_validation(
            composition_binding=_composition()[0],
            bindings=bindings,
            benchmark="locomo",
            case_manifest=(),
            required_model="gpt-5.6-sol",
            required_route=cast(object, object()),
            provider_calls=(),
            session_verifier=cast(object, object()),
            session_evidence=(),
        )

    failure_http, failure_lifecycle = _legacy_for_binding(binding)
    failure_lifecycle.execution_evidence_capability = MethodType(
        lambda _self: object(), failure_lifecycle
    )
    failure_adapter = ManagedHttpRunnerAdapter(
        composition_binding=binding,
        http=failure_http,
        lifecycle=failure_lifecycle,
    )
    failure_adapter.consume_ready_evidence(
        composition_binding=binding,
        bindings=bindings,
        cases=(case,),
    )

    def fail_seal(_session: object) -> object:
        raise RuntimeError("seal failed")

    monkeypatch.setattr(module, "seal_full_execution_validation", fail_seal)
    with pytest.raises(ManagedHttpRunnerAdapterError, match="validation_failed"):
        failure_adapter.seal_execution_validation(
            composition_binding=binding,
            bindings=bindings,
            benchmark="locomo",
            case_manifest=(),
            required_model="gpt-5.6-sol",
            required_route=cast(object, object()),
            provider_calls=(),
            session_verifier=cast(object, object()),
            session_evidence=(),
        )
    assert failure_adapter._evidence is None
    assert failure_adapter._evidence_snapshot is None
    assert failure_adapter._phase == "terminal"

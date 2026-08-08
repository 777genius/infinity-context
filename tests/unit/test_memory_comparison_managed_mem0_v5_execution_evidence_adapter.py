from __future__ import annotations

import hashlib
import itertools
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest
from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_clean_state import (
    clean_state_identity_sha256,
    fresh_namespace_clean_state_proof,
)
from infinity_context_server.memory_comparison_full_execution_evidence_variants import (
    issue_infinity_di_full_execution_clean_state_evidence,
)
from infinity_context_server.memory_comparison_full_execution_validation import (
    FullExecutionCaseManifestEntry,
    FullExecutionCleanScope,
    FullExecutionProviderCall,
    public_full_execution_validation_report,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_execution_evidence_adapter import (
    ManagedMem0V5ExecutionEvidenceAdapter,
    ManagedMem0V5ExecutionEvidenceAdapterError,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lifecycle_adapter import (
    ManagedMem0V5LifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_transport_evidence import (
    issue_managed_transport_coverage_capability,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderCallProvenance,
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
    SessionIdentityMapping,
)
from test_memory_comparison_managed_mem0_v5_paired_bridge import (
    _run as _paired_run,
)
from test_memory_comparison_managed_mem0_v5_paired_bridge import (
    _set_storage_operation,
)
from test_memory_comparison_managed_mem0_v5_runner_foundation import (
    _exact_transport_observations,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _CleanupReadback:
    def readback(self, **values: object) -> object:
        return values


@dataclass(frozen=True)
class _Scenario:
    adapter: ManagedMem0V5ExecutionEvidenceAdapter
    lifecycle: ManagedMem0V5LifecycleAdapter
    binding: ManagedRunnerCompositionBinding
    bindings: FullComparisonRunBindings
    cases: tuple[ManagedRunCase, ...]
    seal_values: dict[str, object]
    coordinator: object


_SCENARIO_SEQUENCE = itertools.count()


def _managed_case(
    corpus_id: str,
    *,
    case_id: str = "case-1",
    thread_id: str | None = None,
    text: str = "Alice likes tea.",
) -> ManagedRunCase:
    return ManagedRunCase(
        case_id,
        corpus_id,
        {
            "schema_version": "memory-comparison-managed-corpus.v2",
            "benchmark": "locomo",
            "corpus_id": corpus_id,
            "thread_id": thread_id or f"locomo-thread-{'b' * 64}",
            "memories": [
                {
                    "kind": "fact",
                    "role": "user",
                    "session_alias": "session-0001",
                    "source_alias": "memory-000001",
                    "speaker": "Alice",
                    "session_date": "2024-03-10",
                    "text": text,
                    "timestamp": 1,
                }
            ],
            "documents": [],
            "conversations": [],
        },
    )


def _infinity_claim(*, run_id: str, corpus_id: str):
    key = secrets.token_bytes(32)
    corpus_identity = clean_state_identity_sha256(corpus_id)
    slug = f"fresh-infinity-{_sha(run_id)[:16]}"
    scope_identity = clean_state_identity_sha256(slug)
    scopes = (
        FullExecutionCleanScope(
            "infinity-context",
            corpus_identity,
            scope_identity,
        ),
    )
    proofs = (
        fresh_namespace_clean_state_proof(
            backend="infinity-context",
            run_id=run_id,
            expected_slug=slug,
            corpus_identity_sha256=corpus_identity,
            expected_scope_count=1,
            status_code=201,
            payload={"data": {"slug": slug}},
            attestation_key=key,
        ),
    )
    return issue_infinity_di_full_execution_clean_state_evidence(
        corpus_ids=(corpus_id,),
        proofs=proofs,
        scopes=scopes,
        attestation_key=key,
    )


def _scenario(*, consume_receipts: bool = True) -> _Scenario:
    seed = f"execution-adapter-{next(_SCENARIO_SEQUENCE)}"
    identity = _sha(seed)
    authority, coordinator, paired = _paired_run(identity_seed=seed)
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    targets = (
        FullComparisonBackendTarget("infinity-context", _sha("infinity-target")),
        FullComparisonBackendTarget("mem0", _sha("mem0-target")),
    )
    bindings = create_full_comparison_run_bindings(
        run_id=coordinator.request.run_id,
        run_nonce_commitment_sha256=_sha("run-nonce"),
        runtime_probe_nonce_sha256=_sha("runtime-probe"),
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256=profile.expected_dataset_hash,
        selection_fingerprint_sha256=_sha("selection"),
        backend_targets=targets,
    )
    binding = ManagedRunnerCompositionBinding(
        run_id=bindings.run_id,
        profile=profile,
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        deadline=datetime(2026, 8, 8, tzinfo=UTC),
        backend_targets=targets,
        retrieval_top_k=profile.retrieval_top_k,
        answer_cutoff=profile.answer_cutoff,
    )
    lifecycle = ManagedMem0V5LifecycleAdapter(
        composition_binding=binding,
        paired_run=paired,
        authority=authority,
        request=coordinator.request,
        cleanup_readback_capability=_CleanupReadback(),
    )
    admission = Mem0OssFullRunAdmission(
        request=coordinator.request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    observations = _exact_transport_observations(authority, admission)
    capability = issue_managed_transport_coverage_capability(
        benchmark=profile.benchmark,
        run_id_sha256=_sha(coordinator.request.run_id),
        backend_role="mem0",
        authority=authority,
        admission=admission,
        observations=observations,
    )
    _set_storage_operation(authority, coordinator, observations[0].operation_id_sha256)
    lifecycle.admit()
    lifecycle.dispatch_once()
    lifecycle.consume_transport_coverage(capability)
    receipts = tuple(
        lifecycle.issue_corpus_receipt(corpus_id=corpus_id)
        for corpus_id in dict.fromkeys(item.corpus_id for item in authority.units)
    )
    if consume_receipts:
        lifecycle.consume_corpus_receipts(receipts)

    corpus_id = authority.units[0].corpus_id
    cases = (
        _managed_case(
            corpus_id,
            case_id=f"case-{identity[:16]}",
            thread_id=f"locomo-thread-{_sha(f'thread:{seed}')}",
        ),
    )
    adapter = ManagedMem0V5ExecutionEvidenceAdapter(
        composition_binding=binding,
        lifecycle=lifecycle,
        infinity_clean_state_evidence=_infinity_claim(
            run_id=bindings.run_id,
            corpus_id=corpus_id,
        ),
    )
    manifest = (
        FullExecutionCaseManifestEntry(
            cases[0].case_id,
            corpus_id,
            cases[0].record["thread_id"],
            ("memory", "query"),
            ("session-0001", "session-0002"),
            authority.operation_count,
        ),
    )
    route = ProviderRouteAttestation(
        trust="official_openai",
        origin="https://api.openai.com",
        endpoint_path="/v1/chat/completions",
        route_sha256=_sha("route"),
        transport_evidence="direct_https",
        credential_binding_id="sha256:" + _sha("credential"),
        request_method="POST",
        response_status=200,
    )
    calls = tuple(
        FullExecutionProviderCall(
            bindings.binding_commitment_sha256,
            bindings.run_id,
            bindings.profile_id,
            manifest[0].case_id,
            backend,
            stage,
            False,
            ProviderCallProvenance(
                route,
                "gpt-5",
                "gpt-5",
                f"response-{backend}-{stage}",
                f"fingerprint-{backend}-{stage}",
                _sha(f"{backend}:{stage}"),
            ),
        )
        for backend in ("infinity-context", "mem0")
        for stage in ("answerer", "judge")
    )
    session_key = RunScopedSessionHmacKey.generate(run_id=bindings.run_id)
    mappings = tuple(
        SessionIdentityMapping(
            corpus_id,
            manifest[0].thread_id,
            manifest[0].case_id,
            role,
            alias,
        )
        for role, alias in zip(
            manifest[0].session_roles,
            manifest[0].session_aliases,
            strict=True,
        )
    )
    return _Scenario(
        adapter,
        lifecycle,
        binding,
        bindings,
        cases,
        {
            "composition_binding": binding,
            "bindings": bindings,
            "benchmark": "locomo",
            "case_manifest": manifest,
            "required_model": "gpt-5",
            "required_route": route,
            "provider_calls": calls,
            "session_verifier": session_key,
            "session_evidence": tuple(session_key.issue(item) for item in mappings),
        },
        coordinator,
    )


def _consume(scenario: _Scenario) -> None:
    scenario.adapter.consume_ready_evidence(
        composition_binding=scenario.binding,
        bindings=scenario.bindings,
        cases=scenario.cases,
    )


def test_real_lifecycle_evidence_seals_neutral_v2_without_provider_io() -> None:
    scenario = _scenario()

    _consume(scenario)
    proof = scenario.adapter.seal_execution_validation(**scenario.seal_values)
    report = public_full_execution_validation_report(proof)

    assert report["schema_version"] == "memory-comparison-full-execution-validation.v2"
    assert report["evidence_variant"] == "neutral_v2"
    assert report["component_only"] is True
    assert report["externally_authentic"] is False
    assert report["official_transport_coverage"]["backend_role"] == "mem0"
    claims = report["clean_state_coverage"]["claims"]
    assert tuple(item["variant"] for item in claims) == (
        "infinity_di",
        "managed_mem0_v5",
    )


def test_consume_requires_all_receipts_to_be_consumed() -> None:
    scenario = _scenario(consume_receipts=False)

    with pytest.raises(
        ManagedMem0V5ExecutionEvidenceAdapterError,
        match="evidence_consume_failed",
    ):
        _consume(scenario)


def test_wrong_cases_fail_before_burning_lifecycle_handoff() -> None:
    scenario = _scenario()
    wrong = _managed_case(
        scenario.cases[0].corpus_id,
        case_id=scenario.cases[0].case_id,
        thread_id=scenario.cases[0].record["thread_id"],
        text="Alice dislikes tea.",
    )

    with pytest.raises(ManagedMem0V5ExecutionEvidenceAdapterError, match="cases_invalid"):
        scenario.adapter.consume_ready_evidence(
            composition_binding=scenario.binding,
            bindings=scenario.bindings,
            cases=(wrong,),
        )

    _consume(scenario)


def test_foreign_binding_fails_before_burning_lifecycle_handoff() -> None:
    scenario = _scenario()
    foreign = _scenario()

    with pytest.raises(ManagedMem0V5ExecutionEvidenceAdapterError, match="bindings_invalid"):
        scenario.adapter.consume_ready_evidence(
            composition_binding=scenario.binding,
            bindings=foreign.bindings,
            cases=scenario.cases,
        )

    _consume(scenario)


def test_concurrent_consume_has_exactly_one_winner() -> None:
    scenario = _scenario()

    def attempt() -> str:
        try:
            _consume(scenario)
        except ManagedMem0V5ExecutionEvidenceAdapterError:
            return "rejected"
        return "accepted"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(lambda _index: attempt(), range(8)))

    assert results.count("accepted") == 1
    assert results.count("rejected") == 7


def test_two_adapters_sharing_lifecycle_have_one_handoff_winner() -> None:
    scenario = _scenario()
    peer = ManagedMem0V5ExecutionEvidenceAdapter(
        composition_binding=scenario.binding,
        lifecycle=scenario.lifecycle,
        infinity_clean_state_evidence=_infinity_claim(
            run_id=scenario.bindings.run_id,
            corpus_id=scenario.cases[0].corpus_id,
        ),
    )

    def attempt(adapter: ManagedMem0V5ExecutionEvidenceAdapter) -> str:
        try:
            adapter.consume_ready_evidence(
                composition_binding=scenario.binding,
                bindings=scenario.bindings,
                cases=scenario.cases,
            )
        except ManagedMem0V5ExecutionEvidenceAdapterError:
            return "rejected"
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(attempt, (scenario.adapter, peer)))

    assert results.count("accepted") == 1
    assert results.count("rejected") == 1


def test_public_clean_claim_and_adapter_handoff_share_one_shot_authority() -> None:
    scenario = _scenario()

    claim = scenario.lifecycle.issue_ready_clean_state_claim()
    assert repr(claim) == "ManagedMem0V5ReadyCleanStateClaim(<opaque>)"
    with pytest.raises(ManagedMem0V5ExecutionEvidenceAdapterError, match="consume_failed"):
        _consume(scenario)

    terminal = scenario.lifecycle.cleanup_pass1()
    assert terminal.terminal_state == "deleted"


def test_seal_before_ready_manifest_mismatch_and_replay_fail_closed() -> None:
    before = _scenario()
    with pytest.raises(ManagedMem0V5ExecutionEvidenceAdapterError, match="not_ready"):
        before.adapter.seal_execution_validation(**before.seal_values)

    mismatch = _scenario()
    _consume(mismatch)
    bad_values = dict(mismatch.seal_values)
    bad_values["case_manifest"] = (replace(bad_values["case_manifest"][0], case_id="foreign-case"),)
    with pytest.raises(
        ManagedMem0V5ExecutionEvidenceAdapterError,
        match="seal_inputs_invalid",
    ):
        mismatch.adapter.seal_execution_validation(**bad_values)
    terminal = mismatch.lifecycle.cleanup_pass1()
    assert terminal.terminal_state == "deleted"

    replay = _scenario()
    _consume(replay)
    replay.adapter.seal_execution_validation(**replay.seal_values)
    with pytest.raises(ManagedMem0V5ExecutionEvidenceAdapterError):
        replay.adapter.seal_execution_validation(**replay.seal_values)


def test_infinity_claim_run_mismatch_and_repr_are_fail_closed_and_redacted() -> None:
    scenario = _scenario()
    foreign_claim = _infinity_claim(
        run_id="foreign-run",
        corpus_id=scenario.cases[0].corpus_id,
    )

    with pytest.raises(ManagedMem0V5ExecutionEvidenceAdapterError, match="composition_invalid"):
        ManagedMem0V5ExecutionEvidenceAdapter(
            composition_binding=scenario.binding,
            lifecycle=scenario.lifecycle,
            infinity_clean_state_evidence=foreign_claim,
        )

    rendered = repr(scenario.adapter)
    assert rendered == "ManagedMem0V5ExecutionEvidenceAdapter(<opaque>)"
    assert scenario.binding.run_id not in rendered
    assert scenario.cases[0].corpus_id not in rendered

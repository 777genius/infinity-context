from __future__ import annotations

import hashlib
import json
import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest
from infinity_context_server.memory_comparison_clean_state import (
    clean_state_identity_sha256,
    fresh_namespace_clean_state_proof,
    mem0_delete_clean_state_proof,
    validate_typed_clean_state_proofs,
)
from infinity_context_server.memory_comparison_full_execution_evidence_variants import (
    issue_legacy_full_execution_clean_state_evidence,
    issue_managed_mem0_v5_full_execution_clean_state_evidence,
    issue_managed_mem0_v5_full_execution_transport_evidence,
)
from infinity_context_server.memory_comparison_full_execution_validation import (
    FullExecutionCaseManifestEntry,
    FullExecutionCleanScope,
    FullExecutionProviderCall,
    FullExecutionValidationError,
    consume_full_execution_validation,
    execution_case_manifest_sha256,
    issue_full_execution_validation_session_from_evidence,
    public_full_execution_validation_report,
    seal_full_execution_validation,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5CleanCorpusScope,
    create_managed_mem0_v5_clean_state_witness_authority,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    canonical_sha256,
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
    _transport_coverage_for,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _managed_inputs() -> tuple[dict[str, object], object, object]:
    authority, coordinator, paired = _paired_run()
    clean_witness = paired.admit()
    admission, observations, capability = _transport_coverage_for(authority, coordinator.request)
    _set_storage_operation(authority, coordinator, observations[0].operation_id_sha256)
    paired.dispatch()
    coverage = paired.consume_transport_coverage(capability)

    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    bindings = create_full_comparison_run_bindings(
        run_id=coordinator.request.run_id,
        run_nonce_commitment_sha256=_sha("nonce"),
        runtime_probe_nonce_sha256=_sha("probe"),
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256=profile.expected_dataset_hash,
        selection_fingerprint_sha256=_sha("selection"),
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", _sha("infinity-target")),
            FullComparisonBackendTarget("mem0", _sha("mem0-target")),
        ),
    )
    corpus_id = authority.units[0].corpus_id
    manifest = (
        FullExecutionCaseManifestEntry(
            "case-1",
            corpus_id,
            "thread-1",
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
        for role, alias in zip(manifest[0].session_roles, manifest[0].session_aliases, strict=True)
    )

    clean_key = secrets.token_bytes(32)
    legacy_corpus = clean_state_identity_sha256(corpus_id)
    infinity_scope = clean_state_identity_sha256("fresh-infinity-scope")
    legacy_mem0_scope = clean_state_identity_sha256("legacy-mem0-scope")
    legacy_scopes = (
        FullExecutionCleanScope("infinity-context", legacy_corpus, infinity_scope),
        FullExecutionCleanScope("mem0", legacy_corpus, legacy_mem0_scope),
    )
    legacy_validation = validate_typed_clean_state_proofs(
        {
            "infinity-context": (
                fresh_namespace_clean_state_proof(
                    backend="infinity-context",
                    run_id=bindings.run_id,
                    expected_slug="fresh-infinity-scope",
                    corpus_identity_sha256=legacy_corpus,
                    expected_scope_count=1,
                    status_code=201,
                    payload={"data": {"slug": "fresh-infinity-scope"}},
                    attestation_key=clean_key,
                ),
            ),
            "mem0": (
                mem0_delete_clean_state_proof(
                    run_id=bindings.run_id,
                    scope_identity="legacy-mem0-scope",
                    corpus_identity_sha256=legacy_corpus,
                    expected_scope_count=1,
                    status_code=200,
                    payload={"deleted": True, "verified_absent": True},
                    attestation_key=clean_key,
                ),
            ),
        },
        expected_run_id_sha256=clean_state_identity_sha256(bindings.run_id),
        expected_scopes_by_backend={
            "infinity-context": {legacy_corpus: infinity_scope},
            "mem0": {legacy_corpus: legacy_mem0_scope},
        },
        attestation_key=clean_key,
    )
    infinity_claim = issue_legacy_full_execution_clean_state_evidence(
        validation=legacy_validation,
        scopes=legacy_scopes,
        attestation_key=clean_key,
        backend_roles=("infinity-context",),
    )
    mem0_claim = issue_managed_mem0_v5_full_execution_clean_state_evidence(
        backend_role="mem0",
        witness=clean_witness,
        verifier=paired._clean_state_verifier,
    )
    values: dict[str, object] = {
        "bindings": bindings,
        "benchmark": "locomo",
        "case_manifest": manifest,
        "required_model": "gpt-5",
        "required_route": route,
        "provider_calls": calls,
        "session_verifier": session_key,
        "session_evidence": tuple(session_key.issue(item) for item in mappings),
        "transport_evidence": issue_managed_mem0_v5_full_execution_transport_evidence(
            coverage=coverage
        ),
        "clean_state_evidence": (infinity_claim, mem0_claim),
    }
    assert admission.commitment_sha256 == clean_witness.admission_commitment_sha256
    return values, clean_witness, paired._clean_state_verifier


def _identity(values: dict[str, object]) -> dict[str, str]:
    bindings = values["bindings"]
    return {
        "comparison_commitment_sha256": bindings.binding_commitment_sha256,
        "run_id": bindings.run_id,
        "profile_id": bindings.profile_id,
        "dataset_sha256": bindings.dataset_sha256,
        "selection_sha256": bindings.selection_fingerprint_sha256,
        "case_manifest_sha256": execution_case_manifest_sha256(values["case_manifest"]),
    }


def test_real_paired_v5_evidence_issues_seals_reports_and_consumes() -> None:
    values, _witness, _verifier = _managed_inputs()
    session = issue_full_execution_validation_session_from_evidence(**values)
    proof = seal_full_execution_validation(session)

    report = public_full_execution_validation_report(proof)

    assert report["schema_version"] == "memory-comparison-full-execution-validation.v2"
    assert report["evidence_variant"] == "neutral_v2"
    transport = report["official_transport_coverage"]
    assert "required_turn_count" not in transport
    assert "live_verifier" not in transport
    managed_claim = report["clean_state_coverage"]["claims"][1]
    assert managed_claim["variant"] == "managed_mem0_v5"
    assert "validation_commitment_sha256" not in managed_claim
    assert "legacy_v1" not in json.dumps(report, sort_keys=True)
    assert consume_full_execution_validation(proof, **_identity(values)) == report


@pytest.mark.parametrize("mode", ("missing", "duplicate"))
def test_v5_clean_claim_union_fails_closed(mode: str) -> None:
    values, _witness, _verifier = _managed_inputs()
    infinity, mem0 = values["clean_state_evidence"]
    values["clean_state_evidence"] = (infinity,) if mode == "missing" else (infinity, mem0, mem0)
    code = "coverage_missing" if mode == "missing" else "coverage_duplicate"

    with pytest.raises(FullExecutionValidationError, match=code):
        issue_full_execution_validation_session_from_evidence(**values)


@pytest.mark.parametrize(
    "field",
    ("run_id_sha256", "admission_commitment_sha256", "authority_commitment_sha256"),
)
def test_v5_cross_run_admission_and_authority_splice_fails_closed(field: str) -> None:
    local, local_witness, _local_verifier = _managed_inputs()
    values = {
        "run_id_sha256": local_witness.run_id_sha256,
        "admission_commitment_sha256": local_witness.admission_commitment_sha256,
        "authority_commitment_sha256": local_witness.authority_commitment_sha256,
    }
    values[field] = _sha(f"foreign-{field}")
    issuer, verifier = create_managed_mem0_v5_clean_state_witness_authority()
    foreign_witness = issuer.issue_authenticated_clean_state(
        scopes=local_witness.scopes,
        **values,
    )
    foreign_claim = issue_managed_mem0_v5_full_execution_clean_state_evidence(
        backend_role="mem0",
        witness=foreign_witness,
        verifier=verifier,
    )
    local["clean_state_evidence"] = (local["clean_state_evidence"][0], foreign_claim)

    with pytest.raises(FullExecutionValidationError, match="cross_variant_mismatch"):
        issue_full_execution_validation_session_from_evidence(**local)


def test_v5_authenticated_wrong_corpus_hash_fails_closed() -> None:
    values, witness, _verifier = _managed_inputs()
    issuer, verifier = create_managed_mem0_v5_clean_state_witness_authority()
    wrong = issuer.issue_authenticated_clean_state(
        admission_commitment_sha256=witness.admission_commitment_sha256,
        run_id_sha256=witness.run_id_sha256,
        authority_commitment_sha256=witness.authority_commitment_sha256,
        scopes=(
            ManagedMem0V5CleanCorpusScope(
                corpus_identity_sha256=canonical_sha256({"corpus_id": "wrong"}),
                scope_identity_sha256=_sha("wrong-scope"),
                source_scope_count=1,
                residual_record_count=0,
                residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
            ),
        ),
    )
    wrong_claim = issue_managed_mem0_v5_full_execution_clean_state_evidence(
        backend_role="mem0", witness=wrong, verifier=verifier
    )
    values["clean_state_evidence"] = (values["clean_state_evidence"][0], wrong_claim)

    with pytest.raises(FullExecutionValidationError, match="coverage_missing"):
        issue_full_execution_validation_session_from_evidence(**values)


def test_v5_replay_and_concurrent_issue_have_one_winner() -> None:
    values, _witness, _verifier = _managed_inputs()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(issue_full_execution_validation_session_from_evidence, **values)
            for _ in range(4)
        ]
    winners = []
    failures = []
    for future in futures:
        try:
            winners.append(future.result())
        except FullExecutionValidationError as error:
            failures.append(str(error))
    assert len(winners) == 1
    assert failures == ["full_execution_evidence_replay"] * 3
    with pytest.raises(FullExecutionValidationError, match="evidence_replay"):
        issue_full_execution_validation_session_from_evidence(**values)


def test_v5_post_issue_mutation_fails_seal_revalidation() -> None:
    values, witness, _verifier = _managed_inputs()
    session = issue_full_execution_validation_session_from_evidence(**values)
    object.__setattr__(witness, "run_id_sha256", _sha("mutated-run"))

    with pytest.raises(FullExecutionValidationError, match="evidence_changed"):
        seal_full_execution_validation(session)

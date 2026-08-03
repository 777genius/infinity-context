from __future__ import annotations

import copy
import hashlib
import pickle
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from infinity_context_server import memory_comparison_full_execution_validation as _validation
from infinity_context_server import memory_comparison_full_execution_validation_slots as _slots
from infinity_context_server.memory_comparison_benchmark_identity import mem0_benchmark_user_id
from infinity_context_server.memory_comparison_clean_state import (
    clean_state_identity_sha256,
    fresh_namespace_clean_state_proof,
    mem0_delete_clean_state_proof,
    validate_typed_clean_state_proofs,
)
from infinity_context_server.memory_comparison_full_execution_validation import (
    FullExecutionCaseManifestEntry,
    FullExecutionCleanScope,
    FullExecutionProviderCall,
    FullExecutionValidationError,
    FullExecutionValidationSession,
    VerifiedFullExecutionValidation,
    consume_full_execution_validation,
    execution_case_manifest_sha256,
    issue_full_execution_validation_session,
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
from infinity_context_server.memory_comparison_locomo_expected_turn import (
    ExpectedOfficialLocomoTurn,
)
from infinity_context_server.memory_comparison_locomo_transport import (
    LocomoOfficialTurnsTransportRequest,
    RunScopedLocomoTransportEvidenceKey,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderCallProvenance,
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
    SessionIdentityEvidence,
    SessionIdentityMapping,
)

_RUN = "run-execution-1"


def _inputs():
    clean_key = secrets.token_bytes(32)
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    bindings = create_full_comparison_run_bindings(
        run_id=_RUN,
        run_nonce_commitment_sha256="a" * 64,
        runtime_probe_nonce_sha256="0" * 64,
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256=profile.expected_dataset_hash,
        selection_fingerprint_sha256="b" * 64,
        backend_targets=(
            FullComparisonBackendTarget("infinity-context", "c" * 64),
            FullComparisonBackendTarget("mem0", "d" * 64),
        ),
    )
    manifest = (
        FullExecutionCaseManifestEntry(
            "corpus-a:qa:1",
            "corpus-a",
            "thread-a",
            ("memory", "query"),
            ("session-0001", "session-0002"),
            1,
        ),
    )
    route = ProviderRouteAttestation(
        trust="official_openai",
        origin="https://api.openai.com",
        endpoint_path="/v1/chat/completions",
        route_sha256="e" * 64,
        transport_evidence="direct_https",
        credential_binding_id="sha256:" + "f" * 64,
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
                f"resp-{backend}-{stage}",
                f"fp-{backend}-{stage}",
                hashlib.sha256(f"{backend}:{stage}".encode()).hexdigest(),
            ),
        )
        for backend in ("infinity-context", "mem0")
        for stage in ("answerer", "judge")
    )
    session_key = RunScopedSessionHmacKey.generate(run_id=bindings.run_id)
    mappings = tuple(
        SessionIdentityMapping(
            manifest[0].corpus_id,
            manifest[0].thread_id,
            manifest[0].case_id,
            role,
            alias,
        )
        for role, alias in zip(manifest[0].session_roles, manifest[0].session_aliases, strict=True)
    )
    source = "locomo:corpus-a:session_1:D1:1:turn"
    metadata = {
        "benchmark": "locomo",
        "case_id": manifest[0].case_id,
        "corpus_key": manifest[0].corpus_id,
        "source_external_id": source,
        "source_id": source,
        "session_key": "session_1",
        "session_date": "1:56 pm on 8 May, 2023",
        "dia_id": "D1:1",
        "role": "user",
        "speaker": "Caroline",
        "locomo_evidence_ref": "D1:1",
    }
    transport_key = RunScopedLocomoTransportEvidenceKey.generate(run_id=bindings.run_id)
    request = LocomoOfficialTurnsTransportRequest.create(
        messages=[{"role": "user", "content": "official turn"}],
        user_id=mem0_benchmark_user_id(bindings.run_id),
        run_id=bindings.run_id,
        metadata=metadata,
        timestamp=1_683_554_160,
        idempotency_key=source,
    )
    turn = ExpectedOfficialLocomoTurn.create(
        run_id=bindings.run_id,
        corpus_key=manifest[0].corpus_id,
        source_external_id=source,
        source_id=source,
        session_key="session_1",
        speaker="Caroline",
        session_date=metadata["session_date"],
        trigger_case_id=manifest[0].case_id,
        dia_id="D1:1",
        role="user",
        content="official turn",
        timestamp=1_683_554_160,
    )
    corpus = clean_state_identity_sha256(manifest[0].corpus_id)
    infinity_scope = clean_state_identity_sha256("fresh-space")
    mem0_scope = clean_state_identity_sha256("private-user")
    scopes = (
        FullExecutionCleanScope("infinity-context", corpus, infinity_scope),
        FullExecutionCleanScope("mem0", corpus, mem0_scope),
    )
    proofs = {
        "infinity-context": (
            fresh_namespace_clean_state_proof(
                backend="infinity-context",
                run_id=bindings.run_id,
                expected_slug="fresh-space",
                corpus_identity_sha256=corpus,
                expected_scope_count=1,
                status_code=201,
                payload={"data": {"slug": "fresh-space"}},
                attestation_key=clean_key,
            ),
        ),
        "mem0": (
            mem0_delete_clean_state_proof(
                run_id=bindings.run_id,
                scope_identity="private-user",
                corpus_identity_sha256=corpus,
                expected_scope_count=1,
                status_code=200,
                payload={"deleted": True, "verified_absent": True},
                attestation_key=clean_key,
            ),
        ),
    }
    clean = validate_typed_clean_state_proofs(
        proofs,
        expected_run_id_sha256=clean_state_identity_sha256(bindings.run_id),
        expected_scopes_by_backend={
            "infinity-context": {corpus: infinity_scope},
            "mem0": {corpus: mem0_scope},
        },
        attestation_key=clean_key,
    )
    return {
        "bindings": bindings,
        "benchmark": "locomo",
        "case_manifest": manifest,
        "required_model": "gpt-5",
        "required_route": route,
        "provider_calls": calls,
        "session_verifier": session_key,
        "session_evidence": tuple(session_key.issue(item) for item in mappings),
        "transport_verifier": transport_key,
        "transport_evidence": (transport_key.issue(request, expected_turn=turn),),
        "clean_validation": clean,
        "clean_scopes": scopes,
        "clean_attestation_key": clean_key,
    }


def _identity(inputs):
    bindings = inputs["bindings"]
    return {
        "comparison_commitment_sha256": bindings.binding_commitment_sha256,
        "run_id": bindings.run_id,
        "profile_id": bindings.profile_id,
        "dataset_sha256": bindings.dataset_sha256,
        "selection_sha256": bindings.selection_fingerprint_sha256,
        "case_manifest_sha256": execution_case_manifest_sha256(inputs["case_manifest"]),
    }


def _proof(inputs):
    session = issue_full_execution_validation_session(**inputs)
    return session, seal_full_execution_validation(session)


def test_exact_complete_run_report_and_one_shot_consume():
    inputs = _inputs()
    _, proof = _proof(inputs)
    report = public_full_execution_validation_report(proof)
    assert report["component_only"] is True
    assert report["externally_authentic"] is False
    assert report["composite_wiring_required"] is True
    assert report["admission_from_public_mapping"] is False
    assert report["provider_call_coverage"]["verified_call_count"] == 4
    assert report["session_identity_coverage"]["verified_mapping_count"] == 2
    assert report["official_transport_coverage"]["verified_turn_count"] == 1
    assert report["clean_state_coverage"]["verified_scope_count"] == 2
    for slot in (
        report["provider_call_coverage"]["coverage_commitment_sha256"],
        report["session_identity_coverage"]["mapping_commitment_sha256"],
        report["official_transport_coverage"]["evidence_commitment_sha256"],
        report["clean_state_coverage"]["scope_commitment_sha256"],
        report["clean_state_coverage"]["validation_commitment_sha256"],
    ):
        assert len(slot) == 64
    assert "corpus-a" not in repr(report)
    assert consume_full_execution_validation(proof, **_identity(inputs))["component_only"]
    with pytest.raises(FullExecutionValidationError, match="already consumed"):
        consume_full_execution_validation(proof, **_identity(inputs))


@pytest.mark.parametrize(
    ("field", "change"),
    (
        ("provider_calls", lambda value: value[:-1]),
        ("provider_calls", lambda value: (*value, value[-1])),
        ("session_evidence", lambda value: value[:-1]),
        ("transport_evidence", lambda value: ()),
        ("clean_scopes", lambda value: value[:-1]),
        ("clean_attestation_key", lambda value: b"x" * 32),
    ),
)
def test_incomplete_duplicate_or_wrong_slot_coverage_fails(field, change):
    inputs = _inputs()
    inputs[field] = change(inputs[field])
    with pytest.raises(FullExecutionValidationError):
        issue_full_execution_validation_session(**inputs)


@pytest.mark.parametrize("kind", ("pending", "route", "model", "response"))
def test_provider_exact_once_route_model_and_response_binding(kind):
    inputs = _inputs()
    calls = list(inputs["provider_calls"])
    call = calls[0]
    if kind == "pending":
        calls[0] = replace(call, pending=True)
    elif kind == "route":
        calls[0] = replace(
            call,
            provenance=replace(
                call.provenance,
                route=replace(call.provenance.route, route_sha256="9" * 64),
            ),
        )
    elif kind == "model":
        calls[0] = replace(call, provenance=replace(call.provenance, observed_model="gpt-4"))
    else:
        calls[0] = replace(
            call,
            provenance=replace(call.provenance, response_id=calls[1].provenance.response_id),
        )
    inputs["provider_calls"] = tuple(calls)
    with pytest.raises(FullExecutionValidationError):
        issue_full_execution_validation_session(**inputs)


def test_live_revalidation_rejects_mutation_before_and_after_seal():
    inputs = _inputs()
    session = issue_full_execution_validation_session(**inputs)
    object.__setattr__(inputs["provider_calls"][0], "pending", True)
    with pytest.raises(FullExecutionValidationError):
        seal_full_execution_validation(session)
    with pytest.raises(FullExecutionValidationError, match="not live"):
        seal_full_execution_validation(session)

    inputs = _inputs()
    _, proof = _proof(inputs)
    object.__setattr__(inputs["provider_calls"][0].provenance, "observed_model", "gpt-4")
    with pytest.raises(FullExecutionValidationError):
        public_full_execution_validation_report(proof)

    inputs = _inputs()
    _, proof = _proof(inputs)
    object.__setattr__(inputs["provider_calls"][0].provenance, "response_id", "resp-replaced")
    with pytest.raises(FullExecutionValidationError, match="sealed execution inputs changed"):
        public_full_execution_validation_report(proof)


def test_bound_profile_rejects_another_benchmark():
    inputs = _inputs()
    inputs["benchmark"] = "longmemeval"
    inputs["transport_verifier"] = None
    inputs["transport_evidence"] = ()
    inputs["case_manifest"] = (replace(inputs["case_manifest"][0], official_turn_count=0),)
    with pytest.raises(FullExecutionValidationError, match="bound profile"):
        issue_full_execution_validation_session(**inputs)


def test_public_mapping_identity_and_capability_hardening():
    inputs = _inputs()
    session, proof = _proof(inputs)
    report = public_full_execution_validation_report(proof)
    wrong = _identity(inputs)
    wrong["selection_sha256"] = "9" * 64
    with pytest.raises(FullExecutionValidationError, match="identity does not match"):
        consume_full_execution_validation(proof, **wrong)
    with pytest.raises(FullExecutionValidationError, match="already reserved"):
        issue_full_execution_validation_session(**inputs)
    assert consume_full_execution_validation(proof, **_identity(inputs))
    with pytest.raises(FullExecutionValidationError, match="type must be exact"):
        public_full_execution_validation_report(report)
    with pytest.raises(FullExecutionValidationError):
        FullExecutionValidationSession(_token=object())
    with pytest.raises(FullExecutionValidationError):
        VerifiedFullExecutionValidation(_token=object())
    for value in (session, proof):
        with pytest.raises(TypeError):
            copy.copy(value)
        with pytest.raises(TypeError):
            pickle.dumps(value)


def test_same_bundle_sequential_replay_is_rejected_at_issue():
    inputs = _inputs()
    issue_full_execution_validation_session(**inputs)
    with pytest.raises(FullExecutionValidationError, match="already reserved"):
        issue_full_execution_validation_session(**inputs)


def test_same_bundle_concurrent_issue_has_exactly_one_winner():
    inputs = _inputs()
    barrier = threading.Barrier(4)

    def attempt():
        barrier.wait()
        try:
            return issue_full_execution_validation_session(**inputs)
        except FullExecutionValidationError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        sessions = tuple(pool.map(lambda _: attempt(), range(4)))
    assert sum(item is not None for item in sessions) == 1


def test_replay_loser_cannot_rollback_another_pending_reservation(monkeypatch):
    inputs = _inputs()
    original = _validation._freeze_report
    entered = threading.Event()
    release = threading.Event()

    def block_winner(report):
        entered.set()
        assert release.wait(timeout=5)
        return original(report)

    monkeypatch.setattr(_validation, "_freeze_report", block_winner)
    with ThreadPoolExecutor(max_workers=1) as pool:
        winner = pool.submit(issue_full_execution_validation_session, **inputs)
        assert entered.wait(timeout=5)
        with pytest.raises(FullExecutionValidationError, match="already reserved"):
            issue_full_execution_validation_session(**inputs)
        release.set()
        assert type(winner.result(timeout=5)) is FullExecutionValidationSession

    monkeypatch.setattr(_validation, "_freeze_report", original)
    with pytest.raises(FullExecutionValidationError, match="already reserved"):
        issue_full_execution_validation_session(**inputs)


def test_partial_issue_failure_rolls_back_only_own_pending_reservation(monkeypatch):
    inputs = _inputs()
    original = _validation._freeze_report
    attempts = 0

    def fail_once(report):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise FullExecutionValidationError("injected partial issue failure")
        return original(report)

    monkeypatch.setattr(_validation, "_freeze_report", fail_once)
    with pytest.raises(FullExecutionValidationError, match="injected"):
        issue_full_execution_validation_session(**inputs)

    monkeypatch.setattr(_validation, "_freeze_report", original)
    assert type(issue_full_execution_validation_session(**inputs)) is FullExecutionValidationSession


def test_terminal_reservation_survives_seal_failure():
    inputs = _inputs()
    session = issue_full_execution_validation_session(**inputs)
    call = inputs["provider_calls"][0]
    object.__setattr__(call, "pending", True)
    with pytest.raises(FullExecutionValidationError):
        seal_full_execution_validation(session)

    object.__setattr__(call, "pending", False)
    with pytest.raises(FullExecutionValidationError, match="already reserved"):
        issue_full_execution_validation_session(**inputs)


def test_one_field_semantic_and_one_identity_difference_change_bundle_key():
    inputs = _inputs()
    report = _validation._validate_live(_validation._LiveInputs(**inputs))
    original_key = _validation._bundle_reservation_key(
        _validation._LiveInputs(**inputs),
        report,
    )
    provenance = inputs["provider_calls"][0].provenance
    object.__setattr__(provenance, "response_id", "resp-one-field-different")
    changed_report = _validation._validate_live(_validation._LiveInputs(**inputs))
    assert (
        _validation._bundle_reservation_key(
            _validation._LiveInputs(**inputs),
            changed_report,
        )
        != original_key
    )

    inputs = _inputs()
    live_inputs = _validation._LiveInputs(**inputs)
    report = _validation._validate_live(live_inputs)
    original_key = _validation._bundle_reservation_key(live_inputs, report)
    evidence = inputs["session_evidence"][0]
    inputs["session_evidence"] = (
        SessionIdentityEvidence(evidence.mapping, evidence.proof),
        *inputs["session_evidence"][1:],
    )
    changed_live_inputs = _validation._LiveInputs(**inputs)
    changed_report = _validation._validate_live(changed_live_inputs)
    assert _validation._bundle_reservation_key(changed_live_inputs, changed_report) != original_key


def test_mutating_reserved_receipt_still_requires_fresh_capabilities():
    inputs = _inputs()
    issue_full_execution_validation_session(**inputs)
    object.__setattr__(
        inputs["provider_calls"][0].provenance,
        "response_id",
        "resp-mutated-after-terminal",
    )
    with pytest.raises(FullExecutionValidationError, match="already reserved"):
        issue_full_execution_validation_session(**inputs)

    assert (
        type(issue_full_execution_validation_session(**_inputs())) is FullExecutionValidationSession
    )


def test_manifest_allows_case_local_alias_reuse_for_shared_corpus_and_thread():
    base = _inputs()["case_manifest"][0]
    manifest = (base, replace(base, case_id="corpus-a:qa:2"))

    digest = execution_case_manifest_sha256(manifest)

    assert len(digest) == 64
    assert digest != execution_case_manifest_sha256(tuple(reversed(manifest)))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("case_id", "corpus-a:qa:2"),
        ("corpus_id", "corpus-b"),
        ("thread_id", "thread-b"),
    ),
)
def test_manifest_digest_binds_exact_case_corpus_and_thread(field, value):
    base = _inputs()["case_manifest"][0]
    original = execution_case_manifest_sha256((base,))
    changed = execution_case_manifest_sha256((replace(base, **{field: value}),))

    assert changed != original


def test_manifest_rejects_duplicate_case_and_same_case_role_or_alias():
    base = _inputs()["case_manifest"][0]
    with pytest.raises(FullExecutionValidationError, match="case mapping is duplicated"):
        execution_case_manifest_sha256(
            (base, replace(base, corpus_id="corpus-b", thread_id="thread-b"))
        )

    with pytest.raises(
        FullExecutionValidationError,
        match="session role mapping is duplicated",
    ):
        FullExecutionCaseManifestEntry(
            "corpus-a:qa:2",
            "corpus-a",
            "thread-a",
            ("memory", "query"),
            ("session-0001", "session-0001"),
            1,
        )


def test_session_commitment_binds_case_local_shared_alias_identity():
    inputs = _inputs()
    base = inputs["case_manifest"][0]
    manifest = (base, replace(base, case_id="corpus-a:qa:2"))
    mappings = tuple(
        SessionIdentityMapping(
            item.corpus_id,
            item.thread_id,
            item.case_id,
            role,
            alias,
        )
        for item in manifest
        for role, alias in zip(item.session_roles, item.session_aliases, strict=True)
    )
    verifier = RunScopedSessionHmacKey.generate(run_id=inputs["bindings"].run_id)
    coverage = _slots._session_coverage(
        inputs["bindings"],
        manifest,
        verifier=verifier,
        evidence=tuple(verifier.issue(item) for item in mappings),
    )

    changed_manifest = (
        manifest[0],
        replace(manifest[1], corpus_id="corpus-b", thread_id="thread-b"),
    )
    changed_mappings = tuple(
        SessionIdentityMapping(
            item.corpus_id,
            item.thread_id,
            item.case_id,
            role,
            alias,
        )
        for item in changed_manifest
        for role, alias in zip(item.session_roles, item.session_aliases, strict=True)
    )
    changed_coverage = _slots._session_coverage(
        inputs["bindings"],
        changed_manifest,
        verifier=verifier,
        evidence=tuple(verifier.issue(item) for item in changed_mappings),
    )

    assert coverage["verified_mapping_count"] == 4
    assert coverage["mapping_commitment_sha256"] != changed_coverage["mapping_commitment_sha256"]


def test_transport_coverage_deduplicates_shared_corpus_and_uses_opaque_trigger() -> None:
    inputs = _inputs()
    first_alias = "locomo-case-" + "1" * 64
    second_alias = "locomo-case-" + "2" * 64
    base = replace(inputs["case_manifest"][0], case_id=first_alias)
    manifest = (base, replace(base, case_id=second_alias))
    source = "locomo:corpus-a:session_1:D1:1:turn"
    metadata = {
        "benchmark": "locomo",
        "case_id": "corpus-a:qa:1",
        "corpus_key": "corpus-a",
        "source_external_id": source,
        "source_id": source,
        "session_key": "session_1",
        "session_date": "1:56 pm on 8 May, 2023",
        "dia_id": "D1:1",
        "role": "user",
        "speaker": "Caroline",
        "locomo_evidence_ref": "D1:1",
    }
    request = LocomoOfficialTurnsTransportRequest.create(
        messages=[{"role": "user", "content": "official turn"}],
        user_id=mem0_benchmark_user_id(inputs["bindings"].run_id),
        run_id=inputs["bindings"].run_id,
        metadata=metadata,
        timestamp=1_683_554_160,
        idempotency_key=source,
    )
    expected = ExpectedOfficialLocomoTurn.create(
        run_id=inputs["bindings"].run_id,
        corpus_key="corpus-a",
        source_external_id=source,
        source_id=source,
        session_key="session_1",
        speaker="Caroline",
        session_date="1:56 pm on 8 May, 2023",
        trigger_case_id="corpus-a:qa:1",
        dia_id="D1:1",
        role="user",
        content="official turn",
        timestamp=1_683_554_160,
    )
    evidence = inputs["transport_verifier"].issue(
        request,
        expected_turn=expected,
        public_trigger_case_id=first_alias,
    )

    coverage = _slots._transport_coverage(
        inputs["bindings"],
        benchmark="locomo",
        manifest=manifest,
        verifier=inputs["transport_verifier"],
        evidence=(evidence,),
    )

    assert coverage["required_turn_count"] == 1
    assert coverage["verified_turn_count"] == 1
    assert coverage["corpus_count"] == 1
    with pytest.raises(FullExecutionValidationError, match="shared LoCoMo corpus"):
        _slots._transport_coverage(
            inputs["bindings"],
            benchmark="locomo",
            manifest=(base, replace(base, case_id=second_alias, thread_id="other-thread")),
            verifier=inputs["transport_verifier"],
            evidence=(evidence,),
        )


def test_clean_coverage_deduplicates_shared_corpus_across_cases():
    inputs = _inputs()
    base = inputs["case_manifest"][0]
    manifest = (base, replace(base, case_id="corpus-a:qa:2"))

    coverage = _slots._clean_coverage(
        inputs["bindings"],
        manifest,
        validation=inputs["clean_validation"],
        scopes=inputs["clean_scopes"],
        attestation_key=inputs["clean_attestation_key"],
    )

    assert coverage["required_scope_count"] == 2
    assert coverage["verified_scope_count"] == 2
    assert coverage["per_backend_scope_count"] == {
        "infinity-context": 1,
        "mem0": 1,
    }


def test_clean_coverage_allows_distinct_corpora_to_share_one_scope_per_backend():
    inputs = _inputs()
    bindings = inputs["bindings"]
    base = inputs["case_manifest"][0]
    manifest = (
        base,
        replace(
            base,
            case_id="corpus-b:qa:1",
            corpus_id="corpus-b",
            thread_id="thread-b",
        ),
    )
    scope = "shared-clean-scope"
    scope_hash = clean_state_identity_sha256(scope)
    corpus_hashes = tuple(clean_state_identity_sha256(item.corpus_id) for item in manifest)
    clean_key = inputs["clean_attestation_key"]
    proofs = {
        "infinity-context": tuple(
            fresh_namespace_clean_state_proof(
                backend="infinity-context",
                run_id=bindings.run_id,
                expected_slug=scope,
                corpus_identity_sha256=corpus_hash,
                expected_scope_count=2,
                status_code=201,
                payload={"data": {"slug": scope}},
                attestation_key=clean_key,
            )
            for corpus_hash in corpus_hashes
        ),
        "mem0": tuple(
            mem0_delete_clean_state_proof(
                run_id=bindings.run_id,
                scope_identity=scope,
                corpus_identity_sha256=corpus_hash,
                expected_scope_count=2,
                status_code=200,
                payload={"deleted": True, "verified_absent": True},
                attestation_key=clean_key,
            )
            for corpus_hash in corpus_hashes
        ),
    }
    validation = validate_typed_clean_state_proofs(
        proofs,
        expected_run_id_sha256=clean_state_identity_sha256(bindings.run_id),
        expected_scopes_by_backend={
            backend: {corpus_hash: scope_hash for corpus_hash in corpus_hashes}
            for backend in ("infinity-context", "mem0")
        },
        attestation_key=clean_key,
    )
    scopes = tuple(
        FullExecutionCleanScope(backend, corpus_hash, scope_hash)
        for backend in ("infinity-context", "mem0")
        for corpus_hash in corpus_hashes
    )

    coverage = _slots._clean_coverage(
        bindings,
        manifest,
        validation=validation,
        scopes=scopes,
        attestation_key=clean_key,
    )

    assert coverage["required_scope_count"] == 4
    assert coverage["verified_scope_count"] == 4
    assert coverage["per_backend_scope_count"] == {
        "infinity-context": 2,
        "mem0": 2,
    }

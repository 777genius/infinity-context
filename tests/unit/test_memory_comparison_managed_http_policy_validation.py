from __future__ import annotations

import copy
import hashlib
import json
import pickle
import threading
from dataclasses import replace

import pytest
from infinity_context_server import (
    memory_comparison_managed_http_policy_validation as validation_module,
)
from infinity_context_server.memory_comparison_managed_http_policy_validation import (
    MANAGED_HTTP_POLICY_VALIDATION_SCHEMA_VERSION,
    ManagedHttpPolicyCleanupPassMaterial,
    ManagedHttpPolicyCorpusMaterial,
    ManagedHttpPolicyRegistryMaterial,
    ManagedHttpPolicyValidationError,
    ManagedHttpPolicyValidationMaterial,
    VerifiedManagedHttpPolicyValidation,
    consume_managed_http_policy_validation,
    managed_http_policy_validation_material_sha256,
    public_managed_http_policy_validation,
    seal_managed_http_policy_validation,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _corpus(
    corpus_id: str = "shared-corpus",
    source_id: str = "source-a",
) -> ManagedHttpPolicyCorpusMaterial:
    return ManagedHttpPolicyCorpusMaterial(
        corpus_id=corpus_id,
        ingest_manifest_sha256=_sha(f"manifest:{corpus_id}"),
        source_pairs=((source_id, _sha(f"source:{source_id}")),),
        presence_commitment_sha256=_sha(f"presence:{corpus_id}"),
        derived_commitments=(
            ("qdrant", _sha(f"qdrant:{corpus_id}")),
            ("graphiti", _sha(f"graphiti:{corpus_id}")),
        ),
    )


def _cleanup(
    role: str,
    pass_index: int,
    *,
    corpus_ids: tuple[str, ...] = ("shared-corpus",),
    replay: str | None = None,
) -> ManagedHttpPolicyCleanupPassMaterial:
    return ManagedHttpPolicyCleanupPassMaterial(
        backend_role=role,
        target_identity_sha256=_sha(f"target:{role}"),
        pass_index=pass_index,
        cleanup_commitment_sha256=_sha(f"cleanup:{role}:{pass_index}"),
        exact_absence_commitment_sha256=_sha(f"absence:{role}:{pass_index}"),
        replay_of_cleanup_commitment_sha256=replay,
        corpus_absence_commitments=tuple(
            (corpus_id, _sha(f"absence:{role}:{pass_index}:{corpus_id}"))
            for corpus_id in corpus_ids
        ),
        verified_absent=True,
    )


def _material(
    *,
    corpora: tuple[ManagedHttpPolicyCorpusMaterial, ...] | None = None,
    mapping: tuple[tuple[str, str], ...] = (
        ("case-a", "shared-corpus"),
        ("case-b", "shared-corpus"),
    ),
) -> ManagedHttpPolicyValidationMaterial:
    selected = (_corpus(),) if corpora is None else corpora
    corpus_ids = tuple(corpus.corpus_id for corpus in selected)
    infinity_first = _cleanup("infinity-context", 1, corpus_ids=corpus_ids)
    mem0_first = _cleanup("mem0", 1, corpus_ids=corpus_ids)
    return ManagedHttpPolicyValidationMaterial(
        run_id="run-1",
        profile_id="locomo-canary-v1",
        scope_id="canary",
        binding_commitment_sha256=_sha("binding"),
        managed_attestation_commitment_sha256=_sha("attestation"),
        backend_targets=(
            ("infinity-context", _sha("target:infinity-context")),
            ("mem0", _sha("target:mem0")),
        ),
        adapter_id="managed-http-policy-v2",
        implementation_sha256=_sha("implementation"),
        execution_case_manifest_sha256=_sha("execution-case-manifest"),
        case_corpus_mapping=mapping,
        corpora=selected,
        cleanup_passes=(
            infinity_first,
            mem0_first,
            _cleanup(
                "infinity-context",
                2,
                corpus_ids=corpus_ids,
                replay=infinity_first.cleanup_commitment_sha256,
            ),
            _cleanup(
                "mem0",
                2,
                corpus_ids=corpus_ids,
                replay=mem0_first.cleanup_commitment_sha256,
            ),
        ),
    )


def _registry() -> ManagedHttpPolicyRegistryMaterial:
    return ManagedHttpPolicyRegistryMaterial(
        registration_commitment_sha256=_sha("registry-registration"),
        projection_manifest_sha256=_sha("registry-projection"),
        cleanup_initiation_receipt_sha256=_sha("registry-cleanup"),
        completion_receipt_sha256=_sha("registry-completion"),
        projection_absence_proof_sha256=_sha("registry-absence"),
        wrapper_adapter_id="managed-registry-wrapper-v1",
        wrapper_implementation_sha256=_sha("registry-wrapper-implementation"),
    )


def test_seals_shared_corpus_and_returns_sanitized_json_report() -> None:
    material = _material()
    validation = seal_managed_http_policy_validation(material=material)

    report = public_managed_http_policy_validation(validation)

    assert type(validation) is VerifiedManagedHttpPolicyValidation
    assert report["schema_version"] == MANAGED_HTTP_POLICY_VALIDATION_SCHEMA_VERSION
    assert report["run_id"] == material.run_id
    assert report["profile_id"] == material.profile_id
    assert report["scope_id"] == material.scope_id
    assert report["case_count"] == 2
    assert report["unique_corpus_count"] == 1
    assert report["source_pair_count"] == 1
    assert report["derived_commitment_count"] == 2
    assert report["cleanup_pass_count"] == 4
    assert report["backend_targets"] == [
        {"backend_role": role, "target_identity_sha256": target}
        for role, target in material.backend_targets
    ]
    encoded = json.dumps(report, sort_keys=True)
    assert "case-a" not in encoded
    assert "shared-corpus" not in encoded
    assert "source-a" not in encoded
    assert len(report["material_commitment_sha256"]) == 64
    assert len(report["validation_commitment_sha256"]) == 64
    assert report["registry_evidence"] is None


def test_registry_evidence_is_exact_public_and_snapshot_immutable() -> None:
    registry = _registry()
    material = replace(
        _material(),
        adapter_id=registry.wrapper_adapter_id,
        implementation_sha256=registry.wrapper_implementation_sha256,
        registry=registry,
    )
    validation = seal_managed_http_policy_validation(material=material)
    object.__setattr__(registry, "completion_receipt_sha256", _sha("tampered"))

    report = public_managed_http_policy_validation(validation)

    assert report["adapter_id"] == "managed-registry-wrapper-v1"
    assert report["implementation_sha256"] == _sha("registry-wrapper-implementation")
    assert report["registry_evidence"] == {
        "registration_commitment_sha256": _sha("registry-registration"),
        "projection_manifest_sha256": _sha("registry-projection"),
        "cleanup_initiation_receipt_sha256": _sha("registry-cleanup"),
        "completion_receipt_sha256": _sha("registry-completion"),
        "projection_absence_proof_sha256": _sha("registry-absence"),
        "wrapper_adapter_id": "managed-registry-wrapper-v1",
        "wrapper_implementation_sha256": _sha("registry-wrapper-implementation"),
    }


def test_registry_adapter_provenance_mismatch_is_rejected() -> None:
    registry = _registry()
    with pytest.raises(ManagedHttpPolicyValidationError) as raised:
        replace(_material(), registry=registry)
    assert raised.value.code == "managed_policy_registry_adapter_binding_invalid"


def test_material_commitment_is_deterministic_but_live_seals_are_unique() -> None:
    material = _material()
    first = seal_managed_http_policy_validation(material=material)
    second = seal_managed_http_policy_validation(material=material)

    first_report = public_managed_http_policy_validation(first)
    second_report = public_managed_http_policy_validation(second)

    assert (
        managed_http_policy_validation_material_sha256(material)
        == (first_report["material_commitment_sha256"])
    )
    assert first_report["material_commitment_sha256"] == second_report["material_commitment_sha256"]
    assert (
        first_report["validation_commitment_sha256"]
        != second_report["validation_commitment_sha256"]
    )


def test_consume_is_exact_one_shot_and_failed_binding_restores_live() -> None:
    material = _material()
    validation = seal_managed_http_policy_validation(material=material)

    with pytest.raises(ManagedHttpPolicyValidationError) as raised:
        consume_managed_http_policy_validation(
            validation,
            binding_commitment_sha256=_sha("wrong"),
            managed_attestation_commitment_sha256=(material.managed_attestation_commitment_sha256),
        )
    assert raised.value.code == "managed_policy_validation_binding_mismatch"

    report = consume_managed_http_policy_validation(
        validation,
        binding_commitment_sha256=material.binding_commitment_sha256,
        managed_attestation_commitment_sha256=(material.managed_attestation_commitment_sha256),
    )
    assert report["binding_commitment_sha256"] == material.binding_commitment_sha256
    assert public_managed_http_policy_validation(validation) == report
    with pytest.raises(ManagedHttpPolicyValidationError) as replay:
        consume_managed_http_policy_validation(
            validation,
            binding_commitment_sha256=material.binding_commitment_sha256,
            managed_attestation_commitment_sha256=(material.managed_attestation_commitment_sha256),
        )
    assert replay.value.code == "managed_policy_validation_replay"


def test_failed_attestation_restores_live() -> None:
    material = _material()
    validation = seal_managed_http_policy_validation(material=material)
    with pytest.raises(ManagedHttpPolicyValidationError) as raised:
        consume_managed_http_policy_validation(
            validation,
            binding_commitment_sha256=material.binding_commitment_sha256,
            managed_attestation_commitment_sha256=_sha("wrong-attestation"),
        )
    assert raised.value.code == "managed_policy_validation_attestation_mismatch"
    consume_managed_http_policy_validation(
        validation,
        binding_commitment_sha256=material.binding_commitment_sha256,
        managed_attestation_commitment_sha256=(material.managed_attestation_commitment_sha256),
    )


def test_concurrent_consume_is_rejected_while_owner_remains_one_shot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = _material()
    validation = seal_managed_http_policy_validation(material=material)
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    original = validation_module._verify_integrity

    def blocked_integrity(value: object, state: object) -> None:
        entered.set()
        assert release.wait(timeout=5)
        original(value, state)

    monkeypatch.setattr(validation_module, "_verify_integrity", blocked_integrity)

    def owner() -> None:
        try:
            consume_managed_http_policy_validation(
                validation,
                binding_commitment_sha256=material.binding_commitment_sha256,
                managed_attestation_commitment_sha256=(
                    material.managed_attestation_commitment_sha256
                ),
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=owner)
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(ManagedHttpPolicyValidationError) as active:
        consume_managed_http_policy_validation(
            validation,
            binding_commitment_sha256=material.binding_commitment_sha256,
            managed_attestation_commitment_sha256=(material.managed_attestation_commitment_sha256),
        )
    assert active.value.code == "managed_policy_validation_consume_active"
    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert errors == []


def test_validation_is_opaque_noncopyable_and_unforgeable() -> None:
    validation = seal_managed_http_policy_validation(material=_material())
    with pytest.raises(TypeError):
        copy.copy(validation)
    with pytest.raises(TypeError):
        copy.deepcopy(validation)
    with pytest.raises(TypeError):
        pickle.dumps(validation)
    with pytest.raises(ManagedHttpPolicyValidationError) as forged:
        public_managed_http_policy_validation(object.__new__(VerifiedManagedHttpPolicyValidation))
    assert forged.value.code == "managed_policy_validation_unknown"


def test_capability_tampering_is_detected() -> None:
    validation = seal_managed_http_policy_validation(material=_material())
    object.__setattr__(
        validation,
        "_VerifiedManagedHttpPolicyValidation__commitment",
        _sha("tampered"),
    )
    with pytest.raises(ManagedHttpPolicyValidationError) as raised:
        public_managed_http_policy_validation(validation)
    assert raised.value.code == "managed_policy_validation_integrity_failed"


@pytest.mark.parametrize(
    ("change", "code"),
    (
        (
            {"case_corpus_mapping": (("case-a", "shared-corpus"),) * 2},
            "managed_policy_case_mapping_invalid",
        ),
        (
            {"backend_targets": tuple(reversed(_material().backend_targets))},
            "managed_policy_target_order_invalid",
        ),
        (
            {"cleanup_passes": tuple(reversed(_material().cleanup_passes))},
            "managed_policy_cleanup_order_invalid",
        ),
    ),
)
def test_rejects_ordering_and_duplicate_case_errors(
    change: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(ManagedHttpPolicyValidationError) as raised:
        replace(_material(), **change)
    assert raised.value.code == code


def test_rejects_duplicate_derived_lane_and_source_alias_across_corpora() -> None:
    corpus = _corpus()
    with pytest.raises(ManagedHttpPolicyValidationError) as lane_error:
        replace(
            corpus,
            derived_commitments=(
                ("qdrant", _sha("one")),
                ("qdrant", _sha("two")),
            ),
        )
    assert lane_error.value.code == "managed_policy_derived_order_invalid"

    corpora = (
        _corpus("corpus-a", "aliased-source"),
        _corpus("corpus-b", "aliased-source"),
    )
    with pytest.raises(ManagedHttpPolicyValidationError) as alias_error:
        _material(
            corpora=corpora,
            mapping=(("case-a", "corpus-a"), ("case-b", "corpus-b")),
        )
    assert alias_error.value.code == "managed_policy_source_alias_invalid"


def test_rejects_cleanup_replay_coverage_target_and_absence_failures() -> None:
    material = _material()
    replay = replace(
        material.cleanup_passes[2],
        replay_of_cleanup_commitment_sha256=_sha("wrong-replay"),
    )
    with pytest.raises(ManagedHttpPolicyValidationError) as replay_error:
        replace(
            material,
            cleanup_passes=(
                *material.cleanup_passes[:2],
                replay,
                material.cleanup_passes[3],
            ),
        )
    assert replay_error.value.code == "managed_policy_cleanup_replay_invalid"

    missing = replace(material.cleanup_passes[0], corpus_absence_commitments=())
    with pytest.raises(ManagedHttpPolicyValidationError) as coverage_error:
        replace(material, cleanup_passes=(missing, *material.cleanup_passes[1:]))
    assert coverage_error.value.code == "managed_policy_cleanup_corpus_coverage_invalid"

    wrong_target = replace(material.cleanup_passes[0], target_identity_sha256=_sha("wrong-target"))
    with pytest.raises(ManagedHttpPolicyValidationError) as target_error:
        replace(material, cleanup_passes=(wrong_target, *material.cleanup_passes[1:]))
    assert target_error.value.code == "managed_policy_cleanup_target_mismatch"

    with pytest.raises(ManagedHttpPolicyValidationError) as absent_error:
        replace(material.cleanup_passes[0], verified_absent=False)
    assert absent_error.value.code == "managed_policy_exact_absence_unverified"


def test_snapshot_is_immune_to_post_seal_material_mutation() -> None:
    material = _material()
    validation = seal_managed_http_policy_validation(material=material)
    object.__setattr__(material, "binding_commitment_sha256", _sha("mutated"))
    report = public_managed_http_policy_validation(validation)
    assert report["binding_commitment_sha256"] == _sha("binding")
    consume_managed_http_policy_validation(
        validation,
        binding_commitment_sha256=_sha("binding"),
        managed_attestation_commitment_sha256=_sha("attestation"),
    )

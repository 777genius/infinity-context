from __future__ import annotations

import pickle
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from infinity_context_server import memory_comparison_managed_runner_binding as binding_module
from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    GoldBlindEvidence,
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_managed_retrieval_port import (
    ManagedRetrievalPortError,
    ManagedRetrievalResult,
    _issue_managed_retrieval_authority,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerBindingError,
    ManagedRunnerCompositionBinding,
)


def _material():
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    deadline = datetime(2026, 8, 8, 12, tzinfo=UTC)
    targets = (
        FullComparisonBackendTarget("infinity-context", "a" * 64),
        FullComparisonBackendTarget("mem0", "b" * 64),
    )
    binding = ManagedRunnerCompositionBinding(
        run_id="managed-neutral-run",
        profile=profile,
        binding_commitment_sha256="c" * 64,
        deadline=deadline,
        backend_targets=targets,
        retrieval_top_k=profile.retrieval_top_k,
        answer_cutoff=profile.answer_cutoff,
    )
    return binding, profile, deadline, targets


def test_composition_binding_preserves_live_identity_and_is_nonserializable() -> None:
    binding, profile, deadline, targets = _material()
    reconstructed = ManagedRunnerCompositionBinding(
        run_id=binding.run_id,
        profile=profile,
        binding_commitment_sha256=binding.binding_commitment_sha256,
        deadline=deadline,
        backend_targets=targets,
        retrieval_top_k=profile.retrieval_top_k,
        answer_cutoff=profile.answer_cutoff,
    )

    assert binding.profile is not profile
    assert binding.profile == profile
    assert binding.deadline is deadline
    assert binding.backend_targets is not targets
    assert binding.backend_targets == targets
    assert binding is not reconstructed
    assert binding != reconstructed
    assert repr(binding) == "ManagedRunnerCompositionBinding(<redacted>)"
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(binding)


def test_composition_binding_rejects_profile_policy_drift() -> None:
    binding, profile, deadline, targets = _material()

    with pytest.raises(ManagedRunnerBindingError, match="composition_binding_invalid"):
        ManagedRunnerCompositionBinding(
            run_id=binding.run_id,
            profile=profile,
            binding_commitment_sha256=binding.binding_commitment_sha256,
            deadline=deadline,
            backend_targets=targets,
            retrieval_top_k=profile.retrieval_top_k + 1,
            answer_cutoff=profile.answer_cutoff,
        )


def test_composition_binding_rejects_forged_or_noncanonical_targets() -> None:
    binding, profile, deadline, targets = _material()
    forged = FullComparisonBackendTarget("infinity-context", "a" * 64)
    object.__setattr__(forged, "target_identity_sha256", "not-a-digest")

    for candidate in (
        (forged, targets[1]),
        (targets[1], targets[0]),
        (
            FullComparisonBackendTarget("infinity-context", "a" * 64),
            FullComparisonBackendTarget("mem0", "a" * 64),
        ),
    ):
        with pytest.raises(ManagedRunnerBindingError, match="composition_binding_invalid"):
            ManagedRunnerCompositionBinding(
                run_id=binding.run_id,
                profile=profile,
                binding_commitment_sha256=binding.binding_commitment_sha256,
                deadline=deadline,
                backend_targets=candidate,
                retrieval_top_k=profile.retrieval_top_k,
                answer_cutoff=profile.answer_cutoff,
            )


def test_composition_binding_isolated_from_caller_and_post_issue_mutation() -> None:
    binding, profile, _, targets = _material()
    profile_view = binding.profile
    target_view = binding.backend_targets
    original_deadline = binding.deadline
    original_cutoff = binding.answer_cutoff

    object.__setattr__(profile, "profile_id", "caller-drift")
    object.__setattr__(targets[0], "backend_role", "caller-drift")
    object.__setattr__(profile_view, "profile_id", "returned-view-drift")
    object.__setattr__(target_view[0], "backend_role", "returned-view-drift")

    assert binding.profile_id == PROFILE_LOCOMO_TOP_50
    assert tuple(item.backend_role for item in binding.backend_targets) == (
        "infinity-context",
        "mem0",
    )
    assert binding.deadline is original_deadline
    assert binding.answer_cutoff == original_cutoff
    for name, value in (
        ("_profile_id", "private-drift"),
        ("_binding_commitment", "d" * 64),
        ("_deadline", datetime(2027, 1, 1, tzinfo=UTC)),
        ("_target_pairs", (("mem0", "e" * 64),)),
        ("_answer_cutoff", 1),
    ):
        with pytest.raises(AttributeError):
            object.__setattr__(binding, name, value)


def test_composition_binding_rejects_tampered_registry_snapshot() -> None:
    binding, _, _, _ = _material()
    registry = binding_module._BINDINGS
    state = registry[binding]
    registry[binding] = replace(state, answer_cutoff=state.answer_cutoff + 1)

    with pytest.raises(ManagedRunnerBindingError, match="composition_binding_invalid"):
        _ = binding.answer_cutoff


def test_retrieval_authority_is_target_and_binding_identity_scoped() -> None:
    binding, _, _, _ = _material()
    authority = _issue_managed_retrieval_authority(
        binding,
        backend_role="mem0",
        target_identity_sha256="b" * 64,
    )

    assert authority.composition_binding is binding
    assert authority.backend_role == "mem0"
    assert authority.target_identity_sha256 == "b" * 64
    assert repr(authority) == "ManagedRetrievalAuthority(<redacted>)"
    with pytest.raises(ManagedRetrievalPortError, match="authority_invalid"):
        _issue_managed_retrieval_authority(
            binding,
            backend_role="mem0",
            target_identity_sha256="d" * 64,
        )
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(authority)


def test_retrieval_result_matches_legacy_shape_and_recursively_freezes_metadata() -> None:
    evidence = (GoldBlindEvidence("item-1", "retrieved evidence", 1, None),)
    identity = gold_blind_evidence_identity(evidence)
    result = ManagedRetrievalResult(
        evidence,
        identity,
        {"backend": {"ids": ["item-1"]}, "latency_ms": 1.25},
    )

    assert result.evidence is evidence
    assert result.retrieval_identity == identity
    assert result.metadata["backend"]["ids"] == ("item-1",)  # type: ignore[index]
    result.__post_init__()
    with pytest.raises(TypeError):
        result.metadata["new"] = "mutation"  # type: ignore[index]
    with pytest.raises(ManagedRetrievalPortError, match="result_invalid"):
        ManagedRetrievalResult(evidence, "0" * 64, {})

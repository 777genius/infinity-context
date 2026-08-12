from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunConfig,
    PublishableRunSecrets,
)
from infinity_context_server.publishable_fresh_chain_canary.authority import (
    FRESH_CHAIN_AUTHORITY_ID,
    FRESH_CHAIN_STATIC_AUTHORITY_SHA256,
    FreshChainCanaryAuthority,
    fresh_chain_static_authority_payload,
    validate_fresh_chain_static_authority,
)
from infinity_context_server.publishable_fresh_chain_canary.authorization import (
    FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
)
from infinity_context_server.publishable_fresh_chain_canary.contracts import (
    FRESH_CHAIN_STAGES,
    FreshChainCallResult,
    FreshChainCanaryError,
    FreshChainCleanupResult,
    FreshChainRetrievalHandoff,
    FreshChainUsage,
)
from infinity_context_server.publishable_fresh_chain_canary.evidence import (
    build_fresh_chain_evidence,
    build_fresh_chain_evidence_from_snapshot,
    read_fresh_chain_evidence,
    write_fresh_chain_evidence,
)
from infinity_context_server.publishable_fresh_chain_canary.layout import (
    FRESH_CHAIN_NAMESPACE_AUTHORITY_FILE,
    FRESH_CHAIN_STATE_DIRECTORY,
    open_fresh_chain_layout,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger_models import (
    CleanupBinding,
    FreshChainPlan,
    FreshChainSnapshot,
    FreshChainStageRecord,
    RetrievalHandoff,
    TerminalOutcome,
    TokenUsage,
    canonical_json,
    canonical_sha256,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _items(value: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(value.items()))


def _snapshot() -> FreshChainSnapshot:
    namespace = _sha("namespace")
    source = _sha("source")
    source_projection = _sha("source-projection")
    retrieval_authority = _sha("retrieval-authority")
    results = tuple(_sha(f"result-{index}") for index in range(5))
    receipts = tuple(_sha(f"receipt-{index}") for index in range(5))
    memory_authority = _sha("memory-authority")
    retrieval_material = _sha("retrieval-material")
    memory_count = 2
    input_authorities = (
        source_projection,
        source,
        results[1],
        retrieval_authority,
        results[3],
    )
    requests = tuple(_sha(f"request-{index}") for index in range(5))
    handoff_sha = canonical_sha256(
        {
            "extraction_intent_sha256": _sha("intent-0"),
            "extraction_receipt_sha256": receipts[0],
            "extraction_result_sha256": results[0],
            "memory_authority_sha256": memory_authority,
            "memory_count": memory_count,
            "namespace_commitment_sha256": namespace,
            "retrieval_authority_sha256": retrieval_authority,
            "retrieval_material_sha256": retrieval_material,
            "source_commitment_sha256": source,
            "source_projection_commitment_sha256": source_projection,
        }
    )
    stages = tuple(
        FreshChainStageRecord(
            stage=stage,
            status="succeeded",
            intent_sha256=_sha(f"intent-{index}"),
            request_sha256=requests[index],
            input_authority_sha256=input_authorities[index],
            intent_commitments=_items(
                {
                    "namespace_commitment_sha256": namespace,
                    "source_commitment_sha256": source,
                    "source_projection_commitment_sha256": source_projection,
                    **({"retrieval_handoff_sha256": handoff_sha} if stage == "mem0_answer" else {}),
                }
            ),
            result_sha256=results[index],
            receipt_id=f"receipt-{index}",
            receipt_sha256=receipts[index],
            token_usage=TokenUsage(index + 1, index + 2, index * 2 + 3),
            result_commitments=_items(
                {
                    **(
                        {
                            key: _sha(f"extraction-{key}")
                            for key in (
                                "admission_commitment_sha256",
                                "operation_id_sha256",
                                "output_text_sha256",
                                "run_identity_commitment_sha256",
                                "runtime_binding_commitment_sha256",
                                "scope_sha256",
                                "unit_identity_sha256",
                                "unit_sha256",
                            )
                        }
                        if index == 0
                        else {
                            key: _sha(f"evaluation-{index}-{key}")
                            for key in (
                                "bridge_intent_sha256",
                                "encrypted_output_sha256",
                                "output_text_sha256",
                                "response_body_sha256",
                            )
                        }
                    ),
                    "request_body_sha256": requests[index],
                    **(
                        {"source_projection_commitment_sha256": (source_projection)}
                        if index == 0
                        else {}
                    ),
                }
            ),
        )
        for index, stage in enumerate(FRESH_CHAIN_STAGES)
    )
    plan = FreshChainPlan(
        run_id=FRESH_CHAIN_AUTHORITY_ID,
        namespace_id="fresh-chain-test-namespace",
        namespace_commitment_sha256=namespace,
        source_commitment_sha256=source,
        common_condition_policy_sha256=canonical_sha256(
            fresh_chain_static_authority_payload()["evaluation"]["common_condition"]
        ),
        commitments={
            "authorization_capability_sha256": (
                FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION.commitment_sha256
            ),
            "dynamic_authority_sha256": FreshChainCanaryAuthority(
                namespace,
                source,
            ).commitment_sha256,
            "static_authority_sha256": FRESH_CHAIN_STATIC_AUTHORITY_SHA256,
        },
    )
    retrieval = RetrievalHandoff(
        extraction_result_sha256=results[0],
        extraction_receipt_sha256=receipts[0],
        namespace_commitment_sha256=namespace,
        memory_authority_sha256=memory_authority,
        retrieval_authority_sha256=retrieval_authority,
        memory_count=memory_count,
        commitments=_items(
            {
                "extraction_intent_sha256": stages[0].intent_sha256,
                "handoff_sha256": handoff_sha,
                "memory_count_sha256": canonical_sha256({"memory_count": memory_count}),
                "retrieval_material_sha256": retrieval_material,
                "source_commitment_sha256": source,
                "source_projection_commitment_sha256": source_projection,
            }
        ),
    )
    cleanup = CleanupBinding(
        namespace_commitment_sha256=namespace,
        cleanup_authority_sha256=_sha("cleanup-authority"),
        receipt_id="cleanup-receipt",
        receipt_sha256=_sha("cleanup-receipt"),
        outcome_sha256=_sha("cleanup-outcome"),
        deleted=True,
        operation_count=1,
        residual_count=0,
    )
    terminal_sha = canonical_sha256(
        {
            "activation_evidence_only": True,
            "cleanup": cleanup.material(),
            "ordered_receipt_ids": [f"receipt-{index}" for index in range(5)],
            "plan_commitment_sha256": plan.commitment_sha256,
            "publishable": False,
            "retrieval_handoff": retrieval.material(),
            "source_projection_commitment_sha256": source_projection,
        }
    )
    return FreshChainSnapshot(
        plan=plan,
        source_projection_commitment_sha256=source_projection,
        stages=stages,
        retrieval_handoff=retrieval,
        cleanup=cleanup,
        terminal_outcome=TerminalOutcome(
            status="succeeded",
            outcome_sha256=terminal_sha,
        ),
        event_count=19,
        event_head_hmac=_sha("ledger-head-hmac"),
    )


def _run_inputs(root: Path) -> tuple[PublishableRunConfig, PublishableRunSecrets]:
    state = root / "state"
    state.mkdir(mode=0o700)
    config = PublishableRunConfig(
        dependency_provider="provider.ready",
        official_case_authority_path=state / "official.sqlite3",
        scheduler_database_paths=(state / "locomo.sqlite3", state / "longmem.sqlite3"),
        suite_seal_database_path=state / "suite.sqlite3",
        publication_receipt_path=state / "publication.json",
        publication_key_id="operator-key",
        max_dispatches_per_batch=5,
        adapter_config_json=b"{}",
    )
    secrets = PublishableRunSecrets(
        official_case_authentication_key=bytes([1]) * 32,
        scheduler_authentication_keys=(bytes([2]) * 32, bytes([3]) * 32),
        suite_seal_authentication_key=bytes([4]) * 32,
        publication_receipt_authentication_key=bytes([5]) * 32,
        adapter_secrets_json=b"{}",
    )
    return config, secrets


def test_static_authority_is_exact_non_publishable_one_plus_four() -> None:
    validate_fresh_chain_static_authority()
    payload = fresh_chain_static_authority_payload()

    assert canonical_sha256(payload) == FRESH_CHAIN_STATIC_AUTHORITY_SHA256
    assert payload["case"]["case_id"] == "conv-26:qa:1"
    assert payload["authorization_flag"] == "--allow-live-1-plus-4"
    assert payload["ordered_stages"] == list(FRESH_CHAIN_STAGES)
    assert payload["expected_physical_attempt_count"] == 5
    assert payload["provider"] == "subscription-runtime-worker-authenticated"
    assert payload["authentication"] == "operator-local HMAC"
    assert payload["display_name"] == "fresh-chain canary"
    assert payload["evaluation"]["common_condition"]["retrieval_top_k"] == 200
    assert payload["evaluation"]["common_condition"]["answer_cutoff"] == 50
    for key in (
        "full_profile_execution_enabled",
        "full_publication_gate_satisfied",
        "full_receipt_eligible",
        "paid_go_ready",
        "publishable",
        "quality_or_superiority_claimed",
        "result_2040",
    ):
        assert payload[key] is False

    bound = FreshChainCanaryAuthority(_sha("namespace"), _sha("source"))
    assert bound.static_authority_sha256 == FRESH_CHAIN_STATIC_AUTHORITY_SHA256


def test_layout_creates_isolated_private_generation(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    config, secrets = _run_inputs(tmp_path)

    layout = open_fresh_chain_layout(config, secrets)

    assert layout.root == config.publication_receipt_path.parent / FRESH_CHAIN_STATE_DIRECTORY
    assert layout.root.stat().st_mode & 0o777 == 0o700
    assert layout.provider_root.stat().st_mode & 0o777 == 0o700
    assert (layout.root / FRESH_CHAIN_NAMESPACE_AUTHORITY_FILE).stat().st_mode & 0o777 == 0o600
    assert layout.namespace_id.startswith("fresh-chain-")
    assert layout.namespace_commitment_sha256 != layout.source_commitment_sha256
    assert layout.ledger_authentication_key != layout.evidence_authentication_key
    assert layout.resume is False

    layout.ledger_path.touch(mode=0o600)
    replay = open_fresh_chain_layout(config, secrets)
    assert replay.namespace_id == layout.namespace_id
    assert replay.namespace_commitment_sha256 == layout.namespace_commitment_sha256
    assert replay.resume is True


def test_layout_generation_nonce_tamper_fails_closed(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    config, secrets = _run_inputs(tmp_path)
    layout = open_fresh_chain_layout(config, secrets)
    layout.ledger_path.touch(mode=0o600)
    authority = layout.root / FRESH_CHAIN_NAMESPACE_AUTHORITY_FILE
    authority.write_bytes(b'{"tampered":true}')

    with pytest.raises(FreshChainCanaryError, match="fresh_chain_namespace_authority_invalid"):
        open_fresh_chain_layout(config, secrets)


def test_layout_recovers_crash_before_namespace_authority_and_ledger(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    config, secrets = _run_inputs(tmp_path)
    root = config.publication_receipt_path.parent / FRESH_CHAIN_STATE_DIRECTORY
    root.mkdir(mode=0o700)
    (root / "provider").mkdir(mode=0o700)

    layout = open_fresh_chain_layout(config, secrets)

    assert layout.resume is True
    assert not layout.ledger_path.exists()
    assert (root / FRESH_CHAIN_NAMESPACE_AUTHORITY_FILE).exists()


def test_layout_rejects_missing_ledger_after_provider_state_exists(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    config, secrets = _run_inputs(tmp_path)
    layout = open_fresh_chain_layout(config, secrets)
    (layout.provider_root / "durable-provider-state").touch(mode=0o600)

    with pytest.raises(FreshChainCanaryError, match="fresh_chain_state_generation_partial"):
        open_fresh_chain_layout(config, secrets)


def test_terminal_snapshot_evidence_round_trip_and_tamper_rejection(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    key = bytes([9]) * 32
    snapshot = _snapshot()
    evidence = build_fresh_chain_evidence_from_snapshot(
        snapshot,
        authentication_key=key,
    )
    path = tmp_path / "activation-evidence.json"

    persisted = write_fresh_chain_evidence(path, evidence, authentication_key=key)

    assert read_fresh_chain_evidence(path, authentication_key=key) == persisted
    assert persisted.publishable is False
    assert persisted.payload()["receipt"]["publishable"] is False
    assert persisted.payload()["measured_physical_attempt_count"] == 5
    assert persisted.payload()["ordered_stages"] == list(FRESH_CHAIN_STAGES)
    assert persisted.payload()["ledger_plan_commitment_sha256"] == (snapshot.plan.commitment_sha256)
    assert persisted.payload()["source_projection_commitment_sha256"] == (
        snapshot.source_projection_commitment_sha256
    )
    assert write_fresh_chain_evidence(path, evidence, authentication_key=key) == persisted

    payload = persisted.payload()
    payload["publishable"] = True
    path.write_text(canonical_json(payload), encoding="ascii")
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_evidence_read_invalid"):
        read_fresh_chain_evidence(path, authentication_key=key)


def test_snapshot_evidence_rejects_duplicate_physical_receipt() -> None:
    snapshot = _snapshot()
    stages = list(snapshot.stages)
    stages[4] = replace(stages[4], receipt_sha256=stages[0].receipt_sha256)

    with pytest.raises(FreshChainCanaryError, match="fresh_chain_evidence_snapshot_invalid"):
        build_fresh_chain_evidence_from_snapshot(
            replace(snapshot, stages=tuple(stages)),
            authentication_key=bytes([9]) * 32,
        )


def test_snapshot_evidence_rejects_semantically_incomplete_result_authority() -> None:
    snapshot = _snapshot()
    stages = list(snapshot.stages)
    malformed = dict(stages[1].result_commitments)
    malformed.pop("bridge_intent_sha256")
    stages[1] = replace(stages[1], result_commitments=_items(malformed))

    with pytest.raises(FreshChainCanaryError, match="fresh_chain_evidence_snapshot_invalid"):
        build_fresh_chain_evidence_from_snapshot(
            replace(snapshot, stages=tuple(stages)),
            authentication_key=bytes([9]) * 32,
        )


def test_snapshot_evidence_recomputes_terminal_outcome_authority() -> None:
    snapshot = _snapshot()
    assert snapshot.terminal_outcome is not None

    with pytest.raises(FreshChainCanaryError, match="fresh_chain_evidence_snapshot_invalid"):
        build_fresh_chain_evidence_from_snapshot(
            replace(
                snapshot,
                terminal_outcome=replace(
                    snapshot.terminal_outcome,
                    outcome_sha256=_sha("forged-terminal-outcome"),
                ),
            ),
            authentication_key=bytes([9]) * 32,
        )


def test_snapshot_evidence_rejects_source_projection_cross_wire() -> None:
    snapshot = _snapshot()

    with pytest.raises(FreshChainCanaryError, match="fresh_chain_evidence_snapshot_invalid"):
        build_fresh_chain_evidence_from_snapshot(
            replace(
                snapshot,
                source_projection_commitment_sha256=_sha("different-source-projection"),
            ),
            authentication_key=bytes([9]) * 32,
        )


def test_snapshot_evidence_rejects_mem0_retrieval_cross_wire() -> None:
    snapshot = _snapshot()
    stages = list(snapshot.stages)
    stages[3] = replace(stages[3], input_authority_sha256=_sha("old-retrieval"))

    with pytest.raises(FreshChainCanaryError, match="fresh_chain_evidence_snapshot_invalid"):
        build_fresh_chain_evidence_from_snapshot(
            replace(snapshot, stages=tuple(stages)),
            authentication_key=bytes([9]) * 32,
        )


def test_snapshot_evidence_rejects_unproven_cleanup() -> None:
    snapshot = _snapshot()
    object.__setattr__(snapshot.cleanup, "residual_count", 1)

    with pytest.raises(FreshChainCanaryError, match="fresh_chain_evidence_snapshot_invalid"):
        build_fresh_chain_evidence_from_snapshot(
            snapshot,
            authentication_key=bytes([9]) * 32,
        )


def test_recovered_results_can_build_evidence_without_redispatch() -> None:
    namespace = _sha("namespace")
    source = _sha("source")
    source_projection = _sha("source-projection")
    calls = tuple(
        FreshChainCallResult(
            stage=stage,
            ordinal=index,
            intent_sha256=_sha(f"intent-{index}"),
            result_sha256=_sha(f"result-{index}"),
            physical_receipt_sha256=_sha(f"receipt-{index}"),
            receipt_id=f"receipt-{index}",
            usage=FreshChainUsage(1, 2, 3),
            transport_dispatched=False,
        )
        for index, stage in enumerate(FRESH_CHAIN_STAGES)
    )
    retrieval = FreshChainRetrievalHandoff(
        extraction_intent_sha256=calls[0].intent_sha256,
        extraction_result_sha256=calls[0].result_sha256,
        extraction_receipt_sha256=calls[0].physical_receipt_sha256,
        namespace_commitment_sha256=namespace,
        source_commitment_sha256=source,
        source_projection_commitment_sha256=source_projection,
        memory_authority_sha256=_sha("memory-authority"),
        retrieval_authority_sha256=_sha("retrieval-authority"),
        retrieval_material_sha256=_sha("retrieval-material"),
        memory_count=1,
    )
    cleanup = FreshChainCleanupResult(
        namespace_commitment_sha256=namespace,
        cleanup_authority_sha256=_sha("cleanup-authority"),
        receipt_id="cleanup-receipt",
        receipt_sha256=_sha("cleanup-receipt"),
        outcome_sha256=_sha("cleanup-outcome"),
        deleted=True,
        operation_count=1,
        residual_count=0,
    )

    evidence = build_fresh_chain_evidence(
        namespace_commitment_sha256=namespace,
        source_commitment_sha256=source,
        source_projection_commitment_sha256=source_projection,
        calls=calls,
        retrieval=retrieval,
        cleanup=cleanup,
        ledger_plan_commitment_sha256=_sha("plan"),
        ledger_terminal_sha256=_sha("terminal"),
        ledger_head_hmac_sha256=_sha("head"),
        authentication_key=bytes([9]) * 32,
    )

    assert evidence.publishable is False
    assert evidence.payload()["measured_physical_attempt_count"] == 5


def test_evidence_rejects_wrong_operator_local_hmac(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "activation-evidence.json"
    evidence = build_fresh_chain_evidence_from_snapshot(
        _snapshot(),
        authentication_key=bytes([9]) * 32,
    )
    write_fresh_chain_evidence(path, evidence, authentication_key=bytes([9]) * 32)

    with pytest.raises(FreshChainCanaryError, match="fresh_chain_evidence_read_invalid"):
        read_fresh_chain_evidence(path, authentication_key=bytes([8]) * 32)

    public = json.loads(path.read_bytes())
    assert public["authentication"] == "operator-local HMAC"
    assert public["publishable"] is False
    assert public["receipt"]["publishable"] is False

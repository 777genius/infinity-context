"""Exact full-cardinality paired outcome, seal, and publication tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from infinity_context_server.publishable_durable_scheduler.paired_outcome_contracts import (
    EXPECTED_AUTHENTICATED_JUDGE_OUTPUT_COUNT,
    EXPECTED_PAIRED_OUTCOME_COUNT,
    PairedOutcomeContractError,
    PairedOutcomeDatasetBinding,
    authenticate_judge_output,
    bind_paired_outcome_terminal_to_suite_seal,
    build_paired_outcome_terminal,
    normalize_paired_judge_outputs,
    ordered_paired_outcomes_root_sha256,
    verify_paired_outcome_terminal,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_attestation import (
    PublishableRunAttestation,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_CASE_COUNT,
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
    PUBLISHABLE_SUITE_TOTAL_CALL_COUNT,
    SUITE_SEAL_READBACK_POLICY_SHA256,
    SchedulerSuiteSeal,
    suite_seal_from_material,
)
from infinity_context_server.publishable_durable_scheduler.suite_seal_store import (
    SQLiteSchedulerSuiteSealStore,
)

_SUITE_SHA256 = hashlib.sha256(b"paired-suite").hexdigest()
_JUDGE_SECRETS = (b"L" * 32, b"M" * 32)
_TERMINAL_SECRET = b"T" * 32
_PUBLICATION_SECRET = b"P" * 32
_READ_POLICY_SHA256 = hashlib.sha256(b"paired-read-policy").hexdigest()
_STRATA = (
    ("locomo", "multi-hop", 282),
    ("locomo", "temporal", 321),
    ("locomo", "open-domain", 96),
    ("locomo", "single-hop", 841),
    ("longmemeval", "knowledge-update", 78),
    ("longmemeval", "multi-session", 133),
    ("longmemeval", "single-session-assistant", 56),
    ("longmemeval", "single-session-preference", 30),
    ("longmemeval", "single-session-user", 70),
    ("longmemeval", "temporal", 133),
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture(scope="module")
def dataset_bindings() -> tuple[PairedOutcomeDatasetBinding, PairedOutcomeDatasetBinding]:
    return tuple(
        PairedOutcomeDatasetBinding(
            benchmark=benchmark,
            run_authority_sha256=_sha(f"{benchmark}:run"),
            binding_commitment_sha256=_sha(f"{benchmark}:binding"),
            case_manifest_sha256=_sha(f"{benchmark}:manifest"),
            terminal_report_sha256=_sha(f"{benchmark}:terminal-report"),
            terminal_receipt_sha256=_sha(f"{benchmark}:terminal-receipt"),
        )
        for benchmark in ("locomo", "longmemeval")
    )


def _raw_output(benchmark: str, *, correct: bool) -> bytes:
    if benchmark == "locomo":
        label = "CORRECT" if correct else "WRONG"
        return f'{{"reasoning":"exact","label":"{label}"}}'.encode()
    verdict = "yes" if correct else "no"
    return f"<thinking>exact</thinking>{verdict}".encode()


def _authenticated_outputs(
    dataset_bindings: tuple[PairedOutcomeDatasetBinding, PairedOutcomeDatasetBinding],
    *,
    infinity_correct: bool,
    mem0_correct: bool,
) -> tuple[object, ...]:
    bindings = {item.benchmark: item for item in dataset_bindings}
    secrets = dict(zip(("locomo", "longmemeval"), _JUDGE_SECRETS, strict=True))
    dataset_indices = {"locomo": 0, "longmemeval": 0}
    outputs: list[object] = []
    for benchmark, category, count in _STRATA:
        binding = bindings[benchmark]
        for _ in range(count):
            case_index = dataset_indices[benchmark]
            case_id = f"{benchmark}-case-{case_index}"
            for backend_role, correct in (
                ("infinity-context", infinity_correct),
                ("mem0", mem0_correct),
            ):
                outputs.append(
                    authenticate_judge_output(
                        suite_authority_sha256=_SUITE_SHA256,
                        run_authority_sha256=binding.run_authority_sha256,
                        binding_commitment_sha256=binding.binding_commitment_sha256,
                        case_manifest_sha256=binding.case_manifest_sha256,
                        benchmark=benchmark,
                        category=category,
                        case_index=case_index,
                        case_id=case_id,
                        case_alias=f"alias-{case_id}",
                        backend_role=backend_role,
                        logical_call_id=_sha(f"call:{case_id}:{backend_role}"),
                        receipt_sha256=_sha(f"receipt:{case_id}:{backend_role}"),
                        read_policy_sha256=_READ_POLICY_SHA256,
                        raw_output=_raw_output(benchmark, correct=correct),
                        authentication_secret=secrets[benchmark],
                    )
                )
            dataset_indices[benchmark] += 1
    return tuple(outputs)


@pytest.fixture(scope="module")
def passing_outputs(dataset_bindings):
    return _authenticated_outputs(
        dataset_bindings,
        infinity_correct=True,
        mem0_correct=False,
    )


def _unbound_seal(
    dataset_bindings: tuple[PairedOutcomeDatasetBinding, PairedOutcomeDatasetBinding],
) -> SchedulerSuiteSeal:
    return SchedulerSuiteSeal(
        suite_authority_sha256=_SUITE_SHA256,
        runtime_provenance_sha256=_sha("runtime-provenance"),
        ordered_run_authority_sha256=tuple(item.run_authority_sha256 for item in dataset_bindings),
        ordered_evaluation_receipt_root_sha256=(
            _sha("locomo-evaluation-root"),
            _sha("longmemeval-evaluation-root"),
        ),
        ordered_extraction_terminal_sha256=(
            _sha("locomo-extraction-terminal"),
            _sha("longmemeval-extraction-terminal"),
        ),
        ordered_authenticated_extraction_terminal_sha256=(
            _sha("locomo-authenticated-extraction-terminal"),
            _sha("longmemeval-authenticated-extraction-terminal"),
        ),
        renderer_policy_sha256=_sha("renderer-policy"),
        private_answer_policy_sha256=_sha("private-answer-policy"),
        receipt_verifier_policy_sha256=_sha("receipt-verifier-policy"),
        outcome_readback_policy_sha256=_sha("outcome-readback-policy"),
        extraction_terminal_read_policy_sha256=_sha("extraction-read-policy"),
        seal_readback_policy_sha256=SUITE_SEAL_READBACK_POLICY_SHA256,
        case_count=PUBLISHABLE_SUITE_CASE_COUNT,
        evaluation_call_count=PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
        extraction_operation_count=PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
        charged_tokens=42,
    )


def _publication_receipt(
    seal: SchedulerSuiteSeal,
    *,
    paired_outcome=None,
) -> PublishableRunAttestation:
    return PublishableRunAttestation.create(
        suite_authority_sha256=seal.suite_authority_sha256,
        ordered_run_authority_sha256=seal.ordered_run_authority_sha256,
        official_case_authority_root_sha256=_sha("official-case-root"),
        retrieval_authority_root_sha256=_sha("retrieval-root"),
        extraction_suite_readback_sha256=_sha("extraction-suite-readback"),
        production_composition_authority_sha256=_sha("production-composition"),
        suite_seal_sha256=seal.commitment_sha256,
        terminal_disposition="sealed",
        case_count=seal.case_count,
        evaluation_call_count=seal.evaluation_call_count,
        extraction_operation_count=seal.extraction_operation_count,
        provider_intent_count=seal.evaluation_call_count,
        provider_result_count=seal.evaluation_call_count,
        provider_call_count=seal.evaluation_call_count,
        provider_accounting_complete=True,
        charged_tokens=seal.charged_tokens,
        call_ledger=seal.call_ledger,
        paired_outcome=paired_outcome,
        authentication_key_id="paired-publication-key",
        authentication_secret=_PUBLICATION_SECRET,
    )


def test_exact_2040_pairs_bind_passing_root_decision_and_full_call_ledger(
    tmp_path,
    dataset_bindings,
    passing_outputs,
) -> None:
    assert len(passing_outputs) == EXPECTED_AUTHENTICATED_JUDGE_OUTPUT_COUNT == 4_080
    outcomes = normalize_paired_judge_outputs(
        passing_outputs,
        dataset_bindings=dataset_bindings,
        authentication_secrets=_JUDGE_SECRETS,
    )
    assert len(outcomes) == EXPECTED_PAIRED_OUTCOME_COUNT == 2_040
    assert tuple(item.pair_index for item in outcomes) == tuple(range(2_040))
    outcomes_root = ordered_paired_outcomes_root_sha256(outcomes)

    terminal = build_paired_outcome_terminal(
        dataset_bindings=dataset_bindings,
        authenticated_judge_outputs=passing_outputs,
        judge_output_authentication_secrets=_JUDGE_SECRETS,
        terminal_authentication_secret=_TERMINAL_SECRET,
    )
    assert terminal.paired_superiority_criterion_met is True
    assert terminal.ordered_paired_outcomes_root_sha256 == outcomes_root
    assert verify_paired_outcome_terminal(
        terminal,
        authentication_secret=_TERMINAL_SECRET,
    )

    seal = bind_paired_outcome_terminal_to_suite_seal(
        _unbound_seal(dataset_bindings),
        terminal=terminal,
        terminal_authentication_secret=_TERMINAL_SECRET,
    )
    assert seal.paired_outcome == terminal.seal_binding()
    assert (
        seal.call_ledger.extraction_call_count,
        seal.call_ledger.answer_judge_call_count,
        seal.call_ledger.total_call_count,
    ) == (130_226, 8_160, 138_386)
    assert PUBLISHABLE_SUITE_TOTAL_CALL_COUNT == 138_386
    assert suite_seal_from_material(seal.material()) == seal
    private = tmp_path / "seal-private"
    seal_store = SQLiteSchedulerSuiteSealStore(
        private / "suite-seal.sqlite3",
        private_directory=private,
        authentication_secret=b"S" * 32,
        suite_authority_sha256=_SUITE_SHA256,
    )
    assert seal_store.persist_exact(seal) == seal
    assert seal_store.read() == seal

    receipt = _publication_receipt(seal, paired_outcome=seal.paired_outcome)
    assert receipt.publishable is True
    assert receipt.paired_outcome == seal.paired_outcome
    assert receipt.call_ledger == seal.call_ledger


def test_authenticated_plaintext_tamper_fails_closed(
    dataset_bindings,
    passing_outputs,
) -> None:
    tampered = list(passing_outputs)
    tampered[37] = replace(tampered[37], raw_output=b'{"reasoning":"tampered","label":"WRONG"}')

    with pytest.raises(
        PairedOutcomeContractError,
        match="paired_outcome_order_or_authentication_invalid",
    ):
        normalize_paired_judge_outputs(
            tuple(tampered),
            dataset_bindings=dataset_bindings,
            authentication_secrets=_JUDGE_SECRETS,
        )


def test_manifest_pair_reorder_fails_closed(dataset_bindings, passing_outputs) -> None:
    reordered = list(passing_outputs)
    reordered[0:4] = (*reordered[2:4], *reordered[0:2])

    with pytest.raises(
        PairedOutcomeContractError,
        match="paired_outcome_order_or_authentication_invalid",
    ):
        normalize_paired_judge_outputs(
            tuple(reordered),
            dataset_bindings=dataset_bindings,
            authentication_secrets=_JUDGE_SECRETS,
        )


def test_one_shot_stream_is_exact_and_missing_output_fails_closed(
    dataset_bindings,
    passing_outputs,
) -> None:
    outcomes = normalize_paired_judge_outputs(
        iter(passing_outputs),
        dataset_bindings=dataset_bindings,
        authentication_secrets=_JUDGE_SECRETS,
    )
    assert len(outcomes) == EXPECTED_PAIRED_OUTCOME_COUNT

    with pytest.raises(PairedOutcomeContractError, match="paired_outcome_coverage_invalid"):
        normalize_paired_judge_outputs(
            iter(passing_outputs[:-1]),
            dataset_bindings=dataset_bindings,
            authentication_secrets=_JUDGE_SECRETS,
        )
    with pytest.raises(PairedOutcomeContractError, match="paired_outcome_coverage_invalid"):
        normalize_paired_judge_outputs(
            list(passing_outputs),
            dataset_bindings=dataset_bindings,
            authentication_secrets=_JUDGE_SECRETS,
        )


def test_policy_failure_authenticates_but_cannot_seal_or_publish(dataset_bindings) -> None:
    failing_outputs = _authenticated_outputs(
        dataset_bindings,
        infinity_correct=False,
        mem0_correct=True,
    )
    terminal = build_paired_outcome_terminal(
        dataset_bindings=dataset_bindings,
        authenticated_judge_outputs=failing_outputs,
        judge_output_authentication_secrets=_JUDGE_SECRETS,
        terminal_authentication_secret=_TERMINAL_SECRET,
    )

    assert terminal.paired_superiority_criterion_met is False
    assert verify_paired_outcome_terminal(
        terminal,
        authentication_secret=_TERMINAL_SECRET,
    )
    with pytest.raises(PairedOutcomeContractError, match="paired_outcome_suite_seal_crosswire"):
        bind_paired_outcome_terminal_to_suite_seal(
            _unbound_seal(dataset_bindings),
            terminal=terminal,
            terminal_authentication_secret=_TERMINAL_SECRET,
        )

    unbound = _unbound_seal(dataset_bindings)
    receipt = _publication_receipt(unbound, paired_outcome=terminal.seal_binding())
    assert receipt.publishable is False

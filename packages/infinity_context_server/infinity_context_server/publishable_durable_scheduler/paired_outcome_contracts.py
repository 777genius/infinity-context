"""Exact authenticated paired judge outcomes and terminal policy decision."""

from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, final

from infinity_context_server.memory_comparison_paired_superiority_policy import (
    PAIRED_SUPERIORITY_POLICY_SHA256,
    PairedBinaryStratum,
    PairedDatasetRunAuthority,
    PairedSuperiorityEvidence,
    evaluate_paired_superiority,
    paired_superiority_dataset_counts_sha256,
    paired_superiority_policy_payload,
    paired_superiority_publication_bundle_sha256,
)
from infinity_context_server.memory_comparison_publishable_contracts import (
    canonical_payload_sha256,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PROFILE_COMMITMENT_SHA256,
)
from infinity_context_server.publishable_durable_scheduler.paired_outcome_authentication import (
    AuthenticatedJudgeOutput,
    PairedOutcomeContractError,
    _bounded_text,
    _fail,
    _hmac_sha256,
    _is_sha256,
    _valid_secret,
    authenticate_judge_output,
    verify_authenticated_judge_output,
)
from infinity_context_server.publishable_durable_scheduler.paired_outcome_authority import (
    PAIRED_AUTHORITY_MAPPING_SHA256,
    PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256,
    paired_authority_mapping_payload,
    paired_judge_normalization_policy_payload,
    validate_paired_authority_mapping,
)

if TYPE_CHECKING:
    from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
        SchedulerSuiteSeal,
    )

PAIRED_OUTCOME_SCHEMA_VERSION = "memory-comparison-paired-outcome.v1"
PAIRED_OUTCOME_TERMINAL_SCHEMA_VERSION = "memory-comparison-paired-outcome-terminal.v1"
PAIRED_OUTCOME_SEAL_BINDING_SCHEMA_VERSION = "memory-comparison-paired-outcome-seal-binding.v1"
PAIRED_METRICS_SCHEMA_VERSION = "memory-comparison-paired-superiority-metrics.v1"
PAIRED_POLICY_EVIDENCE_SCHEMA_VERSION = "memory-comparison-paired-policy-evidence.v1"

EXPECTED_PAIRED_OUTCOME_COUNT = 2_040
EXPECTED_AUTHENTICATED_JUDGE_OUTPUT_COUNT = EXPECTED_PAIRED_OUTCOME_COUNT * 2
_EXPECTED_DATASETS = (("locomo", 1_540), ("longmemeval", 500))
_EXPECTED_BACKENDS = ("infinity-context", "mem0")
_EXPECTED_STRATA = tuple(
    (item["benchmark"], item["category"], item["pair_count"])
    for item in paired_superiority_policy_payload()["expected_strata"]
)
_TERMINAL_HMAC_DOMAIN = "memory-comparison/paired-outcome-terminal/hmac-sha256/v1"


@final
@dataclass(frozen=True, slots=True)
class PairedOutcomeDatasetBinding:
    """Ordered scheduler and terminal authority for one frozen dataset run."""

    benchmark: str
    run_authority_sha256: str
    binding_commitment_sha256: str
    case_manifest_sha256: str
    terminal_report_sha256: str
    terminal_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.benchmark not in {item[0] for item in _EXPECTED_DATASETS} or any(
            not _is_sha256(value)
            for value in (
                self.run_authority_sha256,
                self.binding_commitment_sha256,
                self.case_manifest_sha256,
                self.terminal_report_sha256,
                self.terminal_receipt_sha256,
            )
        ):
            _fail("paired_outcome_dataset_binding_invalid")


@final
@dataclass(frozen=True, slots=True)
class PairedOutcome:
    """One manifest-ordered Infinity-versus-Mem0 binary outcome."""

    pair_index: int
    benchmark: str
    dataset_case_index: int
    case_id: str
    case_alias: str
    category: str
    suite_authority_sha256: str
    run_authority_sha256: str
    infinity_judge_output_sha256: str
    mem0_judge_output_sha256: str
    infinity_correct: bool
    mem0_correct: bool
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.pair_index) is not int
            or self.pair_index < 0
            or type(self.dataset_case_index) is not int
            or self.dataset_case_index < 0
            or self.benchmark not in {item[0] for item in _EXPECTED_DATASETS}
            or self.category not in {item[1] for item in _EXPECTED_STRATA}
            or not _bounded_text(self.case_id)
            or not _bounded_text(self.case_alias)
            or any(
                not _is_sha256(value)
                for value in (
                    self.suite_authority_sha256,
                    self.run_authority_sha256,
                    self.infinity_judge_output_sha256,
                    self.mem0_judge_output_sha256,
                )
            )
            or self.infinity_judge_output_sha256 == self.mem0_judge_output_sha256
            or type(self.infinity_correct) is not bool
            or type(self.mem0_correct) is not bool
        ):
            _fail("paired_outcome_invalid")
        object.__setattr__(
            self,
            "commitment_sha256",
            canonical_payload_sha256(self.material()),
        )

    def material(self) -> dict[str, object]:
        return {
            "schema_version": PAIRED_OUTCOME_SCHEMA_VERSION,
            "pair_index": self.pair_index,
            "benchmark": self.benchmark,
            "dataset_case_index": self.dataset_case_index,
            "case_id": self.case_id,
            "case_alias": self.case_alias,
            "category": self.category,
            "suite_authority_sha256": self.suite_authority_sha256,
            "run_authority_sha256": self.run_authority_sha256,
            "ordered_judge_output_sha256": [
                self.infinity_judge_output_sha256,
                self.mem0_judge_output_sha256,
            ],
            "infinity_correct": self.infinity_correct,
            "mem0_correct": self.mem0_correct,
        }


def normalize_paired_judge_outputs(
    outputs: tuple[AuthenticatedJudgeOutput, ...],
    *,
    dataset_bindings: tuple[PairedOutcomeDatasetBinding, PairedOutcomeDatasetBinding],
    authentication_secrets: tuple[bytes, bytes],
) -> tuple[PairedOutcome, ...]:
    """Authenticate and normalize the exact manifest order without sorting."""

    _validate_dataset_inputs(dataset_bindings, authentication_secrets)
    if type(outputs) is not tuple or len(outputs) != EXPECTED_AUTHENTICATED_JUDGE_OUTPUT_COUNT:
        _fail("paired_outcome_coverage_invalid")
    seen_cases: set[tuple[str, str]] = set()
    seen_calls: set[str] = set()
    seen_receipts: set[str] = set()
    records: list[PairedOutcome] = []
    cursor = 0
    pair_index = 0
    suite_sha256: str | None = None
    for dataset_slot, ((benchmark, case_count), binding) in enumerate(
        zip(_EXPECTED_DATASETS, dataset_bindings, strict=True)
    ):
        secret = authentication_secrets[dataset_slot]
        for case_index in range(case_count):
            pair = outputs[cursor : cursor + 2]
            cursor += 2
            if len(pair) != 2:
                _fail("paired_outcome_coverage_invalid")
            infinity_output, mem0_output = pair
            for output, backend_role in zip(pair, _EXPECTED_BACKENDS, strict=True):
                if (
                    type(output) is not AuthenticatedJudgeOutput
                    or not verify_authenticated_judge_output(output, authentication_secret=secret)
                    or output.benchmark != benchmark
                    or output.case_index != case_index
                    or output.backend_role != backend_role
                    or output.run_authority_sha256 != binding.run_authority_sha256
                    or output.binding_commitment_sha256 != binding.binding_commitment_sha256
                    or output.case_manifest_sha256 != binding.case_manifest_sha256
                ):
                    _fail("paired_outcome_order_or_authentication_invalid")
                if output.logical_call_id in seen_calls or output.receipt_sha256 in seen_receipts:
                    _fail("paired_outcome_duplicate_invalid")
                seen_calls.add(output.logical_call_id)
                seen_receipts.add(output.receipt_sha256)
            identity = (benchmark, infinity_output.case_id)
            if (
                identity in seen_cases
                or infinity_output.case_id != mem0_output.case_id
                or infinity_output.case_alias != mem0_output.case_alias
                or infinity_output.category != mem0_output.category
                or infinity_output.suite_authority_sha256 != mem0_output.suite_authority_sha256
            ):
                _fail("paired_outcome_duplicate_or_crosswire_invalid")
            if suite_sha256 is None:
                suite_sha256 = infinity_output.suite_authority_sha256
            elif infinity_output.suite_authority_sha256 != suite_sha256:
                _fail("paired_outcome_suite_crosswire_invalid")
            seen_cases.add(identity)
            records.append(
                PairedOutcome(
                    pair_index=pair_index,
                    benchmark=benchmark,
                    dataset_case_index=case_index,
                    case_id=infinity_output.case_id,
                    case_alias=infinity_output.case_alias,
                    category=infinity_output.category,
                    suite_authority_sha256=infinity_output.suite_authority_sha256,
                    run_authority_sha256=binding.run_authority_sha256,
                    infinity_judge_output_sha256=(infinity_output.commitment_sha256),
                    mem0_judge_output_sha256=mem0_output.commitment_sha256,
                    infinity_correct=_normalize_judge_output(infinity_output),
                    mem0_correct=_normalize_judge_output(mem0_output),
                )
            )
            pair_index += 1
    if cursor != len(outputs) or len(records) != EXPECTED_PAIRED_OUTCOME_COUNT:
        _fail("paired_outcome_coverage_invalid")
    return tuple(records)


def ordered_paired_outcomes_root_sha256(outcomes: tuple[PairedOutcome, ...]) -> str:
    """Derive the order-sensitive root for exactly 2,040 validated pairs."""

    _validate_outcome_order(outcomes)
    return canonical_payload_sha256(
        {
            "schema_version": "memory-comparison-ordered-paired-outcomes-root.v1",
            "pair_count": len(outcomes),
            "ordered_paired_outcome_sha256": [item.commitment_sha256 for item in outcomes],
        }
    )


@final
@dataclass(frozen=True, slots=True)
class PairedOutcomeSealBinding:
    """Small public binding copied identically into suite seal and receipt."""

    terminal_sha256: str
    ordered_paired_outcomes_root_sha256: str
    pair_count: int
    judge_normalization_policy_sha256: str
    authority_mapping_sha256: str
    paired_superiority_policy_sha256: str
    policy_evidence_sha256: str
    policy_publication_bundle_sha256: str
    paired_superiority_metrics_sha256: str
    paired_superiority_decision_sha256: str
    paired_superiority_criterion_met: bool

    def __post_init__(self) -> None:
        if (
            any(
                not _is_sha256(value)
                for value in (
                    self.terminal_sha256,
                    self.ordered_paired_outcomes_root_sha256,
                    self.judge_normalization_policy_sha256,
                    self.authority_mapping_sha256,
                    self.paired_superiority_policy_sha256,
                    self.policy_evidence_sha256,
                    self.policy_publication_bundle_sha256,
                    self.paired_superiority_metrics_sha256,
                    self.paired_superiority_decision_sha256,
                )
            )
            or self.pair_count != EXPECTED_PAIRED_OUTCOME_COUNT
            or self.judge_normalization_policy_sha256 != PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256
            or self.authority_mapping_sha256 != PAIRED_AUTHORITY_MAPPING_SHA256
            or self.paired_superiority_policy_sha256 != PAIRED_SUPERIORITY_POLICY_SHA256
            or type(self.paired_superiority_criterion_met) is not bool
        ):
            _fail("paired_outcome_seal_binding_invalid")

    def material(self) -> dict[str, object]:
        return {
            "schema_version": PAIRED_OUTCOME_SEAL_BINDING_SCHEMA_VERSION,
            "terminal_sha256": self.terminal_sha256,
            "ordered_paired_outcomes_root_sha256": (self.ordered_paired_outcomes_root_sha256),
            "pair_count": self.pair_count,
            "judge_normalization_policy_sha256": self.judge_normalization_policy_sha256,
            "authority_mapping_sha256": self.authority_mapping_sha256,
            "paired_superiority_policy_sha256": self.paired_superiority_policy_sha256,
            "policy_evidence_sha256": self.policy_evidence_sha256,
            "policy_publication_bundle_sha256": self.policy_publication_bundle_sha256,
            "paired_superiority_metrics_sha256": self.paired_superiority_metrics_sha256,
            "paired_superiority_decision_sha256": self.paired_superiority_decision_sha256,
            "paired_superiority_criterion_met": self.paired_superiority_criterion_met,
        }


def paired_outcome_seal_binding_from_material(value: object) -> PairedOutcomeSealBinding:
    expected = {
        "schema_version",
        "terminal_sha256",
        "ordered_paired_outcomes_root_sha256",
        "pair_count",
        "judge_normalization_policy_sha256",
        "authority_mapping_sha256",
        "paired_superiority_policy_sha256",
        "policy_evidence_sha256",
        "policy_publication_bundle_sha256",
        "paired_superiority_metrics_sha256",
        "paired_superiority_decision_sha256",
        "paired_superiority_criterion_met",
    }
    if type(value) is not dict or set(value) != expected:
        _fail("paired_outcome_seal_binding_material_invalid")
    try:
        return PairedOutcomeSealBinding(
            terminal_sha256=value["terminal_sha256"],
            ordered_paired_outcomes_root_sha256=value["ordered_paired_outcomes_root_sha256"],
            pair_count=value["pair_count"],
            judge_normalization_policy_sha256=value["judge_normalization_policy_sha256"],
            authority_mapping_sha256=value["authority_mapping_sha256"],
            paired_superiority_policy_sha256=value["paired_superiority_policy_sha256"],
            policy_evidence_sha256=value["policy_evidence_sha256"],
            policy_publication_bundle_sha256=value["policy_publication_bundle_sha256"],
            paired_superiority_metrics_sha256=value["paired_superiority_metrics_sha256"],
            paired_superiority_decision_sha256=value["paired_superiority_decision_sha256"],
            paired_superiority_criterion_met=value["paired_superiority_criterion_met"],
        )
    except (KeyError, TypeError, ValueError, PairedOutcomeContractError):
        _fail("paired_outcome_seal_binding_material_invalid")


@final
@dataclass(frozen=True, slots=True, repr=False)
class PairedOutcomeTerminal:
    """Authenticated terminal derived from records, counts, and frozen policy."""

    suite_authority_sha256: str
    ordered_run_authority_sha256: tuple[str, str]
    execution_profile_commitment_sha256: str
    execution_methodology_commitment_sha256: str
    policy_profile_commitment_sha256: str
    policy_methodology_commitment_sha256: str
    authority_mapping_sha256: str
    judge_normalization_policy_sha256: str
    ordered_dataset_outcome_root_sha256: tuple[str, str]
    ordered_paired_outcomes_root_sha256: str
    pair_count: int
    paired_superiority_policy_sha256: str
    policy_evidence_sha256: str
    policy_publication_bundle_sha256: str
    paired_superiority_metrics_sha256: str
    paired_superiority_decision_sha256: str
    paired_superiority_criterion_met: bool
    authentication_hmac_sha256: str
    terminal_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        digest_pairs = (
            self.ordered_run_authority_sha256,
            self.ordered_dataset_outcome_root_sha256,
        )
        if (
            not _is_sha256(self.suite_authority_sha256)
            or any(
                type(pair) is not tuple
                or len(pair) != 2
                or any(not _is_sha256(item) for item in pair)
                or len(set(pair)) != 2
                for pair in digest_pairs
            )
            or any(
                not _is_sha256(value)
                for value in (
                    self.execution_profile_commitment_sha256,
                    self.execution_methodology_commitment_sha256,
                    self.policy_profile_commitment_sha256,
                    self.policy_methodology_commitment_sha256,
                    self.authority_mapping_sha256,
                    self.judge_normalization_policy_sha256,
                    self.ordered_paired_outcomes_root_sha256,
                    self.paired_superiority_policy_sha256,
                    self.policy_evidence_sha256,
                    self.policy_publication_bundle_sha256,
                    self.paired_superiority_metrics_sha256,
                    self.paired_superiority_decision_sha256,
                    self.authentication_hmac_sha256,
                )
            )
            or self.execution_profile_commitment_sha256
            != PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256
            or self.execution_methodology_commitment_sha256
            != PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
            or self.policy_profile_commitment_sha256 != PUBLISHABLE_PROFILE_COMMITMENT_SHA256
            or self.policy_methodology_commitment_sha256
            != PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256
            or self.authority_mapping_sha256 != PAIRED_AUTHORITY_MAPPING_SHA256
            or self.judge_normalization_policy_sha256 != PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256
            or self.pair_count != EXPECTED_PAIRED_OUTCOME_COUNT
            or self.paired_superiority_policy_sha256 != PAIRED_SUPERIORITY_POLICY_SHA256
            or type(self.paired_superiority_criterion_met) is not bool
        ):
            _fail("paired_outcome_terminal_invalid")
        object.__setattr__(
            self,
            "terminal_sha256",
            canonical_payload_sha256(
                {**self.body(), "authentication_hmac_sha256": self.authentication_hmac_sha256}
            ),
        )

    def body(self) -> dict[str, object]:
        return {
            "schema_version": PAIRED_OUTCOME_TERMINAL_SCHEMA_VERSION,
            "suite_authority_sha256": self.suite_authority_sha256,
            "ordered_run_authority_sha256": list(self.ordered_run_authority_sha256),
            "execution_profile_commitment_sha256": (self.execution_profile_commitment_sha256),
            "execution_methodology_commitment_sha256": (
                self.execution_methodology_commitment_sha256
            ),
            "policy_profile_commitment_sha256": self.policy_profile_commitment_sha256,
            "policy_methodology_commitment_sha256": (self.policy_methodology_commitment_sha256),
            "authority_mapping_sha256": self.authority_mapping_sha256,
            "judge_normalization_policy_sha256": self.judge_normalization_policy_sha256,
            "ordered_dataset_outcome_root_sha256": list(self.ordered_dataset_outcome_root_sha256),
            "ordered_paired_outcomes_root_sha256": (self.ordered_paired_outcomes_root_sha256),
            "pair_count": self.pair_count,
            "paired_superiority_policy_sha256": self.paired_superiority_policy_sha256,
            "policy_evidence_sha256": self.policy_evidence_sha256,
            "policy_publication_bundle_sha256": self.policy_publication_bundle_sha256,
            "paired_superiority_metrics_sha256": self.paired_superiority_metrics_sha256,
            "paired_superiority_decision_sha256": self.paired_superiority_decision_sha256,
            "paired_superiority_criterion_met": self.paired_superiority_criterion_met,
        }

    def seal_binding(self) -> PairedOutcomeSealBinding:
        return PairedOutcomeSealBinding(
            terminal_sha256=self.terminal_sha256,
            ordered_paired_outcomes_root_sha256=self.ordered_paired_outcomes_root_sha256,
            pair_count=self.pair_count,
            judge_normalization_policy_sha256=self.judge_normalization_policy_sha256,
            authority_mapping_sha256=self.authority_mapping_sha256,
            paired_superiority_policy_sha256=self.paired_superiority_policy_sha256,
            policy_evidence_sha256=self.policy_evidence_sha256,
            policy_publication_bundle_sha256=self.policy_publication_bundle_sha256,
            paired_superiority_metrics_sha256=self.paired_superiority_metrics_sha256,
            paired_superiority_decision_sha256=self.paired_superiority_decision_sha256,
            paired_superiority_criterion_met=self.paired_superiority_criterion_met,
        )

    def __repr__(self) -> str:
        return (
            "PairedOutcomeTerminal("
            f"pair_count={self.pair_count!r}, "
            f"criterion_met={self.paired_superiority_criterion_met!r}, "
            f"terminal_sha256={self.terminal_sha256!r}, authentication=<redacted>)"
        )


def build_paired_outcome_terminal(
    *,
    dataset_bindings: tuple[PairedOutcomeDatasetBinding, PairedOutcomeDatasetBinding],
    authenticated_judge_outputs: tuple[AuthenticatedJudgeOutput, ...],
    judge_output_authentication_secrets: tuple[bytes, bytes],
    terminal_authentication_secret: bytes,
) -> PairedOutcomeTerminal:
    """Derive records, roots, strata, metrics, and the unchanged policy decision."""

    validate_paired_authority_mapping()
    outcomes = normalize_paired_judge_outputs(
        authenticated_judge_outputs,
        dataset_bindings=dataset_bindings,
        authentication_secrets=judge_output_authentication_secrets,
    )
    strata = _strata_from_outcomes(outcomes)
    dataset_roots = tuple(
        _dataset_outcome_root(benchmark, outcomes) for benchmark, _case_count in _EXPECTED_DATASETS
    )
    policy_runs = tuple(
        PairedDatasetRunAuthority(
            benchmark=binding.benchmark,
            profile_commitment_sha256=PUBLISHABLE_PROFILE_COMMITMENT_SHA256,
            binding_commitment_sha256=binding.binding_commitment_sha256,
            case_manifest_sha256=binding.case_manifest_sha256,
            judge_outcomes_sha256=dataset_root,
            paired_counts_sha256=paired_superiority_dataset_counts_sha256(
                benchmark=binding.benchmark,
                strata=tuple(item for item in strata if item.benchmark == binding.benchmark),
            ),
            terminal_report_sha256=binding.terminal_report_sha256,
            terminal_receipt_sha256=binding.terminal_receipt_sha256,
        )
        for binding, dataset_root in zip(dataset_bindings, dataset_roots, strict=True)
    )
    publication_bundle = paired_superiority_publication_bundle_sha256(
        profile_commitment_sha256=PUBLISHABLE_PROFILE_COMMITMENT_SHA256,
        methodology_commitment_sha256=PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256,
        policy_sha256=PAIRED_SUPERIORITY_POLICY_SHA256,
        dataset_runs=policy_runs,
    )
    evidence = PairedSuperiorityEvidence(
        profile_commitment_sha256=PUBLISHABLE_PROFILE_COMMITMENT_SHA256,
        methodology_commitment_sha256=PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256,
        policy_sha256=PAIRED_SUPERIORITY_POLICY_SHA256,
        dataset_runs=policy_runs,
        publication_bundle_sha256=publication_bundle,
        strata=strata,
    )
    decision = evaluate_paired_superiority(evidence)
    evidence_sha256 = canonical_payload_sha256(
        {
            "schema_version": PAIRED_POLICY_EVIDENCE_SCHEMA_VERSION,
            "profile_commitment_sha256": evidence.profile_commitment_sha256,
            "methodology_commitment_sha256": evidence.methodology_commitment_sha256,
            "policy_sha256": evidence.policy_sha256,
            "publication_bundle_sha256": evidence.publication_bundle_sha256,
            "ordered_dataset_runs": [item.material() for item in evidence.dataset_runs],
            "ordered_strata": [item.material() for item in evidence.strata],
        }
    )
    metrics_sha256 = canonical_payload_sha256(
        {
            "schema_version": PAIRED_METRICS_SCHEMA_VERSION,
            "overall": decision["overall"],
            "datasets": decision["datasets"],
            "categories": decision["categories"],
            "failures": decision["failures"],
        }
    )
    suite_sha256 = outcomes[0].suite_authority_sha256
    ordered_runs = tuple(item.run_authority_sha256 for item in dataset_bindings)
    body = _terminal_body(
        suite_authority_sha256=suite_sha256,
        ordered_run_authority_sha256=ordered_runs,
        ordered_dataset_outcome_root_sha256=dataset_roots,
        ordered_paired_outcomes_root_sha256=ordered_paired_outcomes_root_sha256(outcomes),
        policy_evidence_sha256=evidence_sha256,
        policy_publication_bundle_sha256=publication_bundle,
        paired_superiority_metrics_sha256=metrics_sha256,
        paired_superiority_decision_sha256=decision["decision_sha256"],
        paired_superiority_criterion_met=decision["criterion_met"],
    )
    authentication = _hmac_sha256(
        terminal_authentication_secret,
        _TERMINAL_HMAC_DOMAIN,
        body,
    )
    return PairedOutcomeTerminal(
        suite_authority_sha256=suite_sha256,
        ordered_run_authority_sha256=ordered_runs,
        execution_profile_commitment_sha256=(PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256),
        execution_methodology_commitment_sha256=(
            PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
        ),
        policy_profile_commitment_sha256=PUBLISHABLE_PROFILE_COMMITMENT_SHA256,
        policy_methodology_commitment_sha256=PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256,
        authority_mapping_sha256=PAIRED_AUTHORITY_MAPPING_SHA256,
        judge_normalization_policy_sha256=PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256,
        ordered_dataset_outcome_root_sha256=dataset_roots,
        ordered_paired_outcomes_root_sha256=body["ordered_paired_outcomes_root_sha256"],
        pair_count=EXPECTED_PAIRED_OUTCOME_COUNT,
        paired_superiority_policy_sha256=PAIRED_SUPERIORITY_POLICY_SHA256,
        policy_evidence_sha256=evidence_sha256,
        policy_publication_bundle_sha256=publication_bundle,
        paired_superiority_metrics_sha256=metrics_sha256,
        paired_superiority_decision_sha256=decision["decision_sha256"],
        paired_superiority_criterion_met=decision["criterion_met"],
        authentication_hmac_sha256=authentication,
    )


def verify_paired_outcome_terminal(terminal: object, *, authentication_secret: bytes) -> bool:
    try:
        if type(terminal) is not PairedOutcomeTerminal:
            return False
        PairedOutcomeTerminal.__post_init__(terminal)
        expected = _hmac_sha256(
            authentication_secret,
            _TERMINAL_HMAC_DOMAIN,
            terminal.body(),
        )
        return hmac.compare_digest(expected, terminal.authentication_hmac_sha256)
    except Exception:
        return False


def bind_paired_outcome_terminal_to_suite_seal(
    seal: SchedulerSuiteSeal,
    *,
    terminal: PairedOutcomeTerminal,
    terminal_authentication_secret: bytes,
) -> SchedulerSuiteSeal:
    """Return a new seal that explicitly binds the authenticated paired terminal."""

    from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
        PUBLISHABLE_SUITE_CASE_COUNT,
        PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
        SchedulerSuiteSeal,
    )

    if (
        type(seal) is not SchedulerSuiteSeal
        or type(terminal) is not PairedOutcomeTerminal
        or not verify_paired_outcome_terminal(
            terminal, authentication_secret=terminal_authentication_secret
        )
        or seal.suite_authority_sha256 != terminal.suite_authority_sha256
        or seal.ordered_run_authority_sha256 != terminal.ordered_run_authority_sha256
        or seal.case_count != PUBLISHABLE_SUITE_CASE_COUNT
        or seal.evaluation_call_count != PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
        or terminal.paired_superiority_criterion_met is not True
    ):
        _fail("paired_outcome_suite_seal_crosswire")
    binding = terminal.seal_binding()
    if seal.paired_outcome is not None and seal.paired_outcome != binding:
        _fail("paired_outcome_suite_seal_divergent")
    return replace(seal, paired_outcome=binding)


def _normalize_judge_output(output: AuthenticatedJudgeOutput) -> bool:
    try:
        text = output.raw_output.decode("utf-8")
    except UnicodeDecodeError:
        _fail("paired_judge_output_malformed")
    if output.benchmark == "locomo":
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, RecursionError):
            _fail("paired_judge_output_malformed")
        if (
            type(value) is not dict
            or set(value) != {"reasoning", "label"}
            or type(value["reasoning"]) is not str
            or type(value["label"]) is not str
            or value["label"] not in {"CORRECT", "WRONG"}
        ):
            _fail("paired_judge_output_malformed")
        return value["label"] == "CORRECT"
    regions = re.split(r"</judge_thinking>|</thinking>", text, flags=re.IGNORECASE)
    verdict = regions[-1].strip().casefold()
    if verdict not in {"yes", "no"}:
        _fail("paired_judge_output_malformed")
    return verdict == "yes"


def _validate_dataset_inputs(bindings: object, authentication_secrets: object) -> None:
    if (
        type(bindings) is not tuple
        or len(bindings) != 2
        or type(authentication_secrets) is not tuple
        or len(authentication_secrets) != 2
    ):
        _fail("paired_outcome_dataset_inputs_invalid")
    for (benchmark, _case_count), binding, secret in zip(
        _EXPECTED_DATASETS, bindings, authentication_secrets, strict=True
    ):
        if type(binding) is PairedOutcomeDatasetBinding:
            PairedOutcomeDatasetBinding.__post_init__(binding)
        if (
            type(binding) is not PairedOutcomeDatasetBinding
            or binding.benchmark != benchmark
            or not _valid_secret(secret)
        ):
            _fail("paired_outcome_dataset_inputs_invalid")
    if bindings[0].run_authority_sha256 == bindings[1].run_authority_sha256:
        _fail("paired_outcome_dataset_inputs_invalid")


def _validate_outcome_order(outcomes: object) -> None:
    if type(outcomes) is not tuple or len(outcomes) != EXPECTED_PAIRED_OUTCOME_COUNT:
        _fail("paired_outcome_coverage_invalid")
    cursor = 0
    suites: set[str] = set()
    runs: list[str] = []
    for benchmark, case_count in _EXPECTED_DATASETS:
        dataset_run: str | None = None
        for case_index in range(case_count):
            outcome = outcomes[cursor]
            if type(outcome) is PairedOutcome:
                PairedOutcome.__post_init__(outcome)
            if (
                type(outcome) is not PairedOutcome
                or outcome.pair_index != cursor
                or outcome.benchmark != benchmark
                or outcome.dataset_case_index != case_index
            ):
                _fail("paired_outcome_order_invalid")
            suites.add(outcome.suite_authority_sha256)
            if dataset_run is None:
                dataset_run = outcome.run_authority_sha256
            elif outcome.run_authority_sha256 != dataset_run:
                _fail("paired_outcome_run_crosswire_invalid")
            cursor += 1
        if dataset_run is None:
            _fail("paired_outcome_coverage_invalid")
        runs.append(dataset_run)
    if len(suites) != 1 or len(set(runs)) != 2:
        _fail("paired_outcome_suite_crosswire_invalid")


def _dataset_outcome_root(benchmark: str, outcomes: tuple[PairedOutcome, ...]) -> str:
    selected = tuple(item for item in outcomes if item.benchmark == benchmark)
    expected_count = dict(_EXPECTED_DATASETS)[benchmark]
    if len(selected) != expected_count:
        _fail("paired_outcome_coverage_invalid")
    return canonical_payload_sha256(
        {
            "schema_version": "memory-comparison-ordered-dataset-outcomes-root.v1",
            "benchmark": benchmark,
            "pair_count": len(selected),
            "ordered_paired_outcome_sha256": [item.commitment_sha256 for item in selected],
        }
    )


def _strata_from_outcomes(
    outcomes: tuple[PairedOutcome, ...],
) -> tuple[PairedBinaryStratum, ...]:
    strata: list[PairedBinaryStratum] = []
    for benchmark, category, expected_count in _EXPECTED_STRATA:
        selected = tuple(
            item for item in outcomes if item.benchmark == benchmark and item.category == category
        )
        if len(selected) != expected_count:
            _fail("paired_outcome_strata_coverage_invalid")
        states = (
            sum(item.infinity_correct and item.mem0_correct for item in selected),
            sum(item.infinity_correct and not item.mem0_correct for item in selected),
            sum(not item.infinity_correct and item.mem0_correct for item in selected),
            sum(not item.infinity_correct and not item.mem0_correct for item in selected),
        )
        strata.append(PairedBinaryStratum(benchmark, category, *states))
    return tuple(strata)


def _terminal_body(
    *,
    suite_authority_sha256: str,
    ordered_run_authority_sha256: tuple[str, str],
    ordered_dataset_outcome_root_sha256: tuple[str, str],
    ordered_paired_outcomes_root_sha256: str,
    policy_evidence_sha256: str,
    policy_publication_bundle_sha256: str,
    paired_superiority_metrics_sha256: str,
    paired_superiority_decision_sha256: str,
    paired_superiority_criterion_met: bool,
) -> dict[str, object]:
    return {
        "schema_version": PAIRED_OUTCOME_TERMINAL_SCHEMA_VERSION,
        "suite_authority_sha256": suite_authority_sha256,
        "ordered_run_authority_sha256": list(ordered_run_authority_sha256),
        "execution_profile_commitment_sha256": (PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256),
        "execution_methodology_commitment_sha256": (
            PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
        ),
        "policy_profile_commitment_sha256": PUBLISHABLE_PROFILE_COMMITMENT_SHA256,
        "policy_methodology_commitment_sha256": (PUBLISHABLE_METHODOLOGY_COMMITMENT_SHA256),
        "authority_mapping_sha256": PAIRED_AUTHORITY_MAPPING_SHA256,
        "judge_normalization_policy_sha256": PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256,
        "ordered_dataset_outcome_root_sha256": list(ordered_dataset_outcome_root_sha256),
        "ordered_paired_outcomes_root_sha256": ordered_paired_outcomes_root_sha256,
        "pair_count": EXPECTED_PAIRED_OUTCOME_COUNT,
        "paired_superiority_policy_sha256": PAIRED_SUPERIORITY_POLICY_SHA256,
        "policy_evidence_sha256": policy_evidence_sha256,
        "policy_publication_bundle_sha256": policy_publication_bundle_sha256,
        "paired_superiority_metrics_sha256": paired_superiority_metrics_sha256,
        "paired_superiority_decision_sha256": paired_superiority_decision_sha256,
        "paired_superiority_criterion_met": paired_superiority_criterion_met,
    }


__all__ = (
    "EXPECTED_AUTHENTICATED_JUDGE_OUTPUT_COUNT",
    "EXPECTED_PAIRED_OUTCOME_COUNT",
    "PAIRED_AUTHORITY_MAPPING_SHA256",
    "PAIRED_JUDGE_NORMALIZATION_POLICY_SHA256",
    "AuthenticatedJudgeOutput",
    "PairedOutcome",
    "PairedOutcomeContractError",
    "PairedOutcomeDatasetBinding",
    "PairedOutcomeSealBinding",
    "PairedOutcomeTerminal",
    "authenticate_judge_output",
    "bind_paired_outcome_terminal_to_suite_seal",
    "build_paired_outcome_terminal",
    "normalize_paired_judge_outputs",
    "ordered_paired_outcomes_root_sha256",
    "paired_authority_mapping_payload",
    "paired_judge_normalization_policy_payload",
    "paired_outcome_seal_binding_from_material",
    "verify_authenticated_judge_output",
    "verify_paired_outcome_terminal",
)

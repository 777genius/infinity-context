"""Provider-neutral contracts for resumable publishable evaluation dispatch."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, final

from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionTerminal,
)

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerCallStage,
    SchedulerContractError,
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
    canonical_json,
    commitment,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    BuiltSchedulerManifest,
    SchedulerLogicalCall,
)
from infinity_context_server.publishable_durable_scheduler.paired_outcome_contracts import (
    PairedOutcomeSealBinding,
    paired_outcome_seal_binding_from_material,
)
from infinity_context_server.publishable_durable_scheduler.publishable_call_ledger import (
    PublishableCallLedger,
    exact_publishable_call_ledger,
    publishable_call_ledger_from_material,
)

RUNNER_SCHEMA_VERSION = "memory-comparison-publishable-resumable-runner.v2"
RUNNER_PAGE_SIZE = 256
RUNNER_REQUEST_BYTES_CAP = 16 * 1024 * 1024
RUNNER_ATTESTATION_BYTES_CAP = 1024 * 1024
PUBLISHABLE_SUITE_CASE_COUNT = 2_040
PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT = 8_160
LOCOMO_EXTRACTION_OPERATION_COUNT = 5_882
LONGMEMEVAL_EXTRACTION_OPERATION_COUNT = 124_344
PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT = (
    LOCOMO_EXTRACTION_OPERATION_COUNT + LONGMEMEVAL_EXTRACTION_OPERATION_COUNT
)
PUBLISHABLE_SUITE_TOTAL_CALL_COUNT = (
    PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT + PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
)
SCHEDULER_RUNNER_PAID_GO_READY = False
SCHEDULER_RUNNER_PUBLISHABLE = False
SCHEDULER_PRODUCTION_BRIDGE_ADAPTER_READY = True
SCHEDULER_RUNNER_READINESS_BLOCKERS: tuple[str, ...] = ()

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
NO_OUTCOME_READBACK_POLICY_SHA256 = commitment(
    "runner-no-outcome-readback-policy",
    {"schema_version": RUNNER_SCHEMA_VERSION},
)
NO_EXTRACTION_TERMINAL_READ_POLICY_SHA256 = commitment(
    "runner-no-extraction-terminal-read-policy",
    {"schema_version": RUNNER_SCHEMA_VERSION},
)
SUITE_SEAL_READBACK_POLICY_SHA256 = commitment(
    "runner-suite-seal-readback-policy",
    {
        "authentication": "hmac-sha256",
        "exact_replay": "required",
        "schema_version": RUNNER_SCHEMA_VERSION,
        "storage": "sqlite-full-sync-private-file",
    },
)


class SchedulerRunnerError(SchedulerContractError):
    """Stable fail-closed runner rejection without private material."""


class SchedulerStepDisposition(StrEnum):
    COMMITTED = "committed"
    BLOCKED = "blocked"
    EVALUATION_COMPLETE = "evaluation_complete"
    FROZEN_OUTCOME_UNKNOWN = "frozen_outcome_unknown"
    FAILED_KNOWN = "failed_known"
    DEADLINE_EXHAUSTED = "deadline_exhausted"
    SEALED = "sealed"


@final
@dataclass(frozen=True, slots=True)
class SchedulerRunStoreSpec:
    """Exact authority, manifest, and private SQLite location for one run."""

    run: SchedulerRunAuthority
    manifest: BuiltSchedulerManifest
    database_path: Path
    private_directory: Path
    authentication_secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.run) is not SchedulerRunAuthority
            or type(self.manifest) is not BuiltSchedulerManifest
            or not isinstance(self.database_path, Path)
            or not isinstance(self.private_directory, Path)
            or type(self.authentication_secret) is not bytes
            or not 32 <= len(self.authentication_secret) <= 1024
        ):
            _fail("scheduler_runner_store_spec_invalid")


@final
@dataclass(frozen=True, slots=True)
class SchedulerSuiteSealStoreSpec:
    """Secure SQLite sidecar location for the exact-idempotent suite seal."""

    database_path: Path
    private_directory: Path
    authentication_secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.database_path, Path)
            or not isinstance(self.private_directory, Path)
            or type(self.authentication_secret) is not bytes
            or not 32 <= len(self.authentication_secret) <= 1024
        ):
            _fail("scheduler_runner_seal_store_spec_invalid")


@final
class SchedulerPrivateAnswerReadCapability:
    """One-render capability that records use of the exact committed ciphertext."""

    __slots__ = ("__ciphertext", "__ciphertext_sha256", "__read")

    def __init__(self, ciphertext: bytes) -> None:
        if type(ciphertext) is not bytes or not ciphertext:
            _fail("scheduler_runner_private_answer_capability_invalid")
        object.__setattr__(self, "_SchedulerPrivateAnswerReadCapability__ciphertext", ciphertext)
        object.__setattr__(
            self,
            "_SchedulerPrivateAnswerReadCapability__ciphertext_sha256",
            hashlib.sha256(ciphertext).hexdigest(),
        )
        object.__setattr__(self, "_SchedulerPrivateAnswerReadCapability__read", False)

    def __setattr__(self, _name: str, _value: object) -> None:
        _fail("scheduler_runner_private_answer_capability_immutable")

    def read(self) -> bytes:
        object.__setattr__(self, "_SchedulerPrivateAnswerReadCapability__read", True)
        return self.__ciphertext

    @property
    def ciphertext_sha256(self) -> str:
        return self.__ciphertext_sha256

    @property
    def was_read(self) -> bool:
        return self.__read


@final
@dataclass(frozen=True, slots=True)
class SchedulerRequestContext:
    """Request-rendering input; dependency output stays opaque and private."""

    suite: SchedulerSuiteAuthority
    run: SchedulerRunAuthority
    call: SchedulerLogicalCall
    dependency_answer_capability: SchedulerPrivateAnswerReadCapability | None = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.suite) is not SchedulerSuiteAuthority
            or type(self.run) is not SchedulerRunAuthority
            or type(self.call) is not SchedulerLogicalCall
        ):
            _fail("scheduler_runner_request_context_invalid")
        if self.call.stage is SchedulerCallStage.ANSWER:
            if self.dependency_answer_capability is not None:
                _fail("scheduler_runner_answer_dependency_payload_invalid")
        elif type(self.dependency_answer_capability) is not SchedulerPrivateAnswerReadCapability:
            _fail("scheduler_runner_judge_dependency_payload_invalid")

    @property
    def dependency_answer_ciphertext(self) -> bytes | None:
        capability = self.dependency_answer_capability
        return None if capability is None else capability.read()

    @property
    def dependency_answer_ciphertext_sha256(self) -> str | None:
        capability = self.dependency_answer_capability
        return None if capability is None else capability.ciphertext_sha256


@final
@dataclass(frozen=True, slots=True)
class SchedulerRenderedRequest:
    """Renderer-owned declaration of exact policy and private dependency use."""

    renderer_policy_sha256: str
    private_answer_policy_sha256: str
    dependency_answer_ciphertext_sha256: str | None
    payload: bytes = field(repr=False)
    payload_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.renderer_policy_sha256)
            or not is_sha256(self.private_answer_policy_sha256)
            or self.dependency_answer_ciphertext_sha256 is not None
            and not is_sha256(self.dependency_answer_ciphertext_sha256)
            or type(self.payload) is not bytes
            or not 1 <= len(self.payload) <= RUNNER_REQUEST_BYTES_CAP
        ):
            _fail("scheduler_runner_rendered_request_invalid")
        object.__setattr__(self, "payload_sha256", hashlib.sha256(self.payload).hexdigest())


class SchedulerRequestRendererPort(Protocol):
    @property
    def renderer_policy_sha256(self) -> str:
        """Return the exact reviewed request-rendering policy authority."""

    @property
    def private_answer_policy_sha256(self) -> str:
        """Return the authority for decrypt/use/redaction of private answers."""

    def render(self, context: SchedulerRequestContext) -> SchedulerRenderedRequest:
        """Render one exact provider request without performing provider I/O."""


@final
@dataclass(frozen=True, slots=True)
class SchedulerDispatchEnvelope:
    """One spent-on-invocation dispatch envelope with private request bytes."""

    suite_authority_sha256: str
    run_authority_sha256: str
    bridge_boot_authority_sha256: str
    logical_call_id: str
    stage: SchedulerCallStage
    ordinal: int
    renderer_policy_sha256: str
    private_answer_policy_sha256: str
    dependency_answer_ciphertext_sha256: str | None
    request_sha256: str
    intent_sha256: str
    token_ceiling: int
    dispatch_deadline_unix_ms: int
    payload: bytes = field(repr=False)
    payload_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        digests = (
            self.suite_authority_sha256,
            self.run_authority_sha256,
            self.bridge_boot_authority_sha256,
            self.logical_call_id,
            self.renderer_policy_sha256,
            self.private_answer_policy_sha256,
            self.request_sha256,
            self.intent_sha256,
        )
        if (
            any(not is_sha256(value) for value in digests)
            or type(self.stage) is not SchedulerCallStage
            or (self.stage is SchedulerCallStage.JUDGE)
            != is_sha256(self.dependency_answer_ciphertext_sha256)
            or type(self.ordinal) is not int
            or self.ordinal < 0
            or type(self.token_ceiling) is not int
            or self.token_ceiling < 1
            or type(self.dispatch_deadline_unix_ms) is not int
            or self.dispatch_deadline_unix_ms < 1
            or type(self.payload) is not bytes
            or not 1 <= len(self.payload) <= RUNNER_REQUEST_BYTES_CAP
        ):
            _fail("scheduler_runner_dispatch_envelope_invalid")
        object.__setattr__(self, "payload_sha256", hashlib.sha256(self.payload).hexdigest())


@final
@dataclass(frozen=True, slots=True)
class SchedulerDispatchReceipt:
    """Secret-safe binding plus opaque verifier-owned provider attestation."""

    suite_authority_sha256: str
    run_authority_sha256: str
    bridge_boot_authority_sha256: str
    logical_call_id: str
    stage: SchedulerCallStage
    renderer_policy_sha256: str
    private_answer_policy_sha256: str
    dependency_answer_ciphertext_sha256: str | None
    request_sha256: str
    intent_sha256: str
    private_output_ciphertext_sha256: str | None
    completion_tokens: int
    charged_tokens: int
    attestation: bytes = field(repr=False)
    attestation_sha256: str = field(init=False)
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        digests = (
            self.suite_authority_sha256,
            self.run_authority_sha256,
            self.bridge_boot_authority_sha256,
            self.logical_call_id,
            self.renderer_policy_sha256,
            self.private_answer_policy_sha256,
            self.request_sha256,
            self.intent_sha256,
        )
        if (
            any(not is_sha256(value) for value in digests)
            or type(self.stage) is not SchedulerCallStage
            or (self.stage is SchedulerCallStage.JUDGE)
            != is_sha256(self.dependency_answer_ciphertext_sha256)
            or self.private_output_ciphertext_sha256 is not None
            and not is_sha256(self.private_output_ciphertext_sha256)
            or type(self.completion_tokens) is not int
            or self.completion_tokens < 0
            or type(self.charged_tokens) is not int
            or self.charged_tokens < self.completion_tokens
            or type(self.attestation) is not bytes
            or not 1 <= len(self.attestation) <= RUNNER_ATTESTATION_BYTES_CAP
        ):
            _fail("scheduler_runner_dispatch_receipt_invalid")
        attestation_sha256 = hashlib.sha256(self.attestation).hexdigest()
        object.__setattr__(self, "attestation_sha256", attestation_sha256)
        object.__setattr__(
            self,
            "commitment_sha256",
            commitment("runner-dispatch-receipt", self.material()),
        )

    def material(self) -> dict[str, object]:
        return {
            "attestation_sha256": self.attestation_sha256,
            "bridge_boot_authority_sha256": self.bridge_boot_authority_sha256,
            "charged_tokens": self.charged_tokens,
            "completion_tokens": self.completion_tokens,
            "dependency_answer_ciphertext_sha256": (self.dependency_answer_ciphertext_sha256),
            "intent_sha256": self.intent_sha256,
            "logical_call_id": self.logical_call_id,
            "private_answer_policy_sha256": self.private_answer_policy_sha256,
            "private_output_ciphertext_sha256": self.private_output_ciphertext_sha256,
            "renderer_policy_sha256": self.renderer_policy_sha256,
            "request_sha256": self.request_sha256,
            "run_authority_sha256": self.run_authority_sha256,
            "schema_version": RUNNER_SCHEMA_VERSION,
            "stage": self.stage.value,
            "suite_authority_sha256": self.suite_authority_sha256,
        }


@final
@dataclass(frozen=True, slots=True)
class SchedulerDispatchOutcome:
    receipt: SchedulerDispatchReceipt
    private_output_ciphertext: bytes | None = field(repr=False)
    provider_dispatches: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.receipt) is not SchedulerDispatchReceipt
            or type(self.provider_dispatches) is not int
            or self.provider_dispatches not in (0, 1)
        ):
            _fail("scheduler_runner_dispatch_outcome_invalid")
        ciphertext = self.private_output_ciphertext
        if ciphertext is not None and (type(ciphertext) is not bytes or not ciphertext):
            _fail("scheduler_runner_dispatch_outcome_invalid")


class SchedulerOneShotDispatchPort(Protocol):
    @property
    def bridge_boot_authority_sha256(self) -> str:
        """Return the exact reviewed bridge boot authority commitment."""

    def preflight(self, *, payload: bytes, token_ceiling: int) -> None:
        """Reject deterministic request crosswires before durable dispatch intent."""

    def invoke_once(self, envelope: SchedulerDispatchEnvelope) -> SchedulerDispatchOutcome:
        """Spend one envelope in at most one provider dispatch."""


class SchedulerReceiptVerifierPort(Protocol):
    @property
    def policy_sha256(self) -> str:
        """Return the receipt-verifier policy committed by the bridge boot."""

    def verify(
        self,
        *,
        receipt: SchedulerDispatchReceipt,
        envelope: SchedulerDispatchEnvelope,
    ) -> bool:
        """Authenticate the opaque attestation and its complete binding."""


class SchedulerDispatchReadbackDisposition(StrEnum):
    FOUND = "found"
    TERMINAL_ABSENT = "terminal_absent"
    AMBIGUOUS = "ambiguous"


@final
@dataclass(frozen=True, slots=True)
class SchedulerDispatchReadback:
    """Typed status lookup result; its attestation must be verified separately."""

    disposition: SchedulerDispatchReadbackDisposition
    readback_policy_sha256: str
    request_sha256: str
    intent_sha256: str
    outcome: SchedulerDispatchOutcome | None
    attestation: bytes = field(repr=False)
    attestation_sha256: str = field(init=False)
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.disposition) is not SchedulerDispatchReadbackDisposition
            or not is_sha256(self.readback_policy_sha256)
            or not is_sha256(self.request_sha256)
            or not is_sha256(self.intent_sha256)
            or (self.disposition is SchedulerDispatchReadbackDisposition.FOUND)
            != (type(self.outcome) is SchedulerDispatchOutcome)
            or type(self.attestation) is not bytes
            or not 1 <= len(self.attestation) <= RUNNER_ATTESTATION_BYTES_CAP
        ):
            _fail("scheduler_runner_dispatch_readback_invalid")
        attestation_sha256 = hashlib.sha256(self.attestation).hexdigest()
        object.__setattr__(self, "attestation_sha256", attestation_sha256)
        object.__setattr__(
            self,
            "commitment_sha256",
            commitment("runner-dispatch-readback", self.material()),
        )

    def material(self) -> dict[str, object]:
        outcome = self.outcome
        ciphertext = None if outcome is None else outcome.private_output_ciphertext
        return {
            "attestation_sha256": self.attestation_sha256,
            "disposition": self.disposition.value,
            "intent_sha256": self.intent_sha256,
            "outcome_private_ciphertext_sha256": (
                None if ciphertext is None else hashlib.sha256(ciphertext).hexdigest()
            ),
            "outcome_receipt_sha256": (
                None if outcome is None else outcome.receipt.commitment_sha256
            ),
            "outcome_provider_dispatches": (
                None if outcome is None else outcome.provider_dispatches
            ),
            "readback_policy_sha256": self.readback_policy_sha256,
            "request_sha256": self.request_sha256,
            "schema_version": RUNNER_SCHEMA_VERSION,
        }


class SchedulerDispatchReconciliationPort(Protocol):
    @property
    def readback_policy_sha256(self) -> str:
        """Return the authority for authenticated terminal attempt readback."""

    def lookup(self, envelope: SchedulerDispatchEnvelope) -> SchedulerDispatchReadback:
        """Read one prior intent without issuing a new provider dispatch."""

    def authenticate(
        self,
        *,
        readback: SchedulerDispatchReadback,
        envelope: SchedulerDispatchEnvelope,
    ) -> bool:
        """Authenticate found, terminal-absence, or ambiguous readback evidence."""


@final
@dataclass(frozen=True, slots=True)
class SchedulerStepResult:
    disposition: SchedulerStepDisposition
    run_id: str | None
    logical_call_id: str | None
    provider_dispatches: int
    receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.disposition) is not SchedulerStepDisposition
            or self.run_id is not None
            and (type(self.run_id) is not str or not self.run_id)
            or self.logical_call_id is not None
            and not is_sha256(self.logical_call_id)
            or type(self.provider_dispatches) is not int
            or self.provider_dispatches not in (0, 1)
            or self.receipt_sha256 is not None
            and not is_sha256(self.receipt_sha256)
        ):
            _fail("scheduler_runner_step_result_invalid")
        committed = self.disposition is SchedulerStepDisposition.COMMITTED
        if committed != (self.receipt_sha256 is not None):
            _fail("scheduler_runner_step_result_invalid")


@final
@dataclass(frozen=True, slots=True)
class SchedulerExtractionTerminalEvidence:
    """Legacy raw DTO; seal admission never accepts this unauthenticated value."""

    context: ManagedFullRunExtractionContext
    terminal: ManagedFullRunExtractionTerminal

    def __post_init__(self) -> None:
        if (
            type(self.context) is not ManagedFullRunExtractionContext
            or type(self.terminal) is not ManagedFullRunExtractionTerminal
        ):
            _fail("scheduler_runner_extraction_evidence_invalid")
        try:
            ManagedFullRunExtractionContext.__post_init__(self.context)
            ManagedFullRunExtractionTerminal.__post_init__(self.terminal)
        except Exception:
            _fail("scheduler_runner_extraction_evidence_invalid")
        if self.terminal.context_commitment_sha256 != self.context.commitment_sha256:
            _fail("scheduler_runner_extraction_evidence_invalid")

    def material(self) -> dict[str, object]:
        return {
            "context": self.context.payload(),
            "terminal": {
                **self.terminal.body(),
                "terminal_commitment_sha256": self.terminal.terminal_commitment_sha256,
            },
        }


@final
@dataclass(frozen=True, slots=True)
class SchedulerAuthenticatedExtractionTerminal:
    """Exact terminal capability authenticated for one scheduler run authority."""

    run_authority_sha256: str
    read_policy_sha256: str
    evidence: SchedulerExtractionTerminalEvidence
    authentication_sha256: str
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.run_authority_sha256)
            or not is_sha256(self.read_policy_sha256)
            or type(self.evidence) is not SchedulerExtractionTerminalEvidence
            or not is_sha256(self.authentication_sha256)
        ):
            _fail("scheduler_runner_authenticated_extraction_terminal_invalid")
        SchedulerExtractionTerminalEvidence.__post_init__(self.evidence)
        object.__setattr__(
            self,
            "commitment_sha256",
            commitment(
                "runner-authenticated-extraction-terminal",
                {
                    **self.material(),
                    "authentication_sha256": self.authentication_sha256,
                },
            ),
        )

    def material(self) -> dict[str, object]:
        return {
            "evidence": self.evidence.material(),
            "read_policy_sha256": self.read_policy_sha256,
            "run_authority_sha256": self.run_authority_sha256,
            "schema_version": RUNNER_SCHEMA_VERSION,
        }


class SchedulerExtractionTerminalReadPort(Protocol):
    @property
    def read_policy_sha256(self) -> str:
        """Return the reviewed authenticated extraction-read policy authority."""

    def read_terminal(
        self,
        *,
        run: SchedulerRunAuthority,
    ) -> SchedulerAuthenticatedExtractionTerminal | None:
        """Read one terminal capability or report that extraction is incomplete."""


def authenticate_extraction_terminal(
    *,
    run_authority_sha256: str,
    read_policy_sha256: str,
    evidence: SchedulerExtractionTerminalEvidence,
    authentication_secret: bytes,
) -> SchedulerAuthenticatedExtractionTerminal:
    """Issue a local capability only after a reader authenticated its source ledger."""

    material = _extraction_authentication_material(
        run_authority_sha256=run_authority_sha256,
        read_policy_sha256=read_policy_sha256,
        evidence=evidence,
    )
    authentication_sha256 = _runner_hmac(
        authentication_secret,
        "authenticated-extraction-terminal",
        material,
    )
    return SchedulerAuthenticatedExtractionTerminal(
        run_authority_sha256=run_authority_sha256,
        read_policy_sha256=read_policy_sha256,
        evidence=evidence,
        authentication_sha256=authentication_sha256,
    )


def verify_authenticated_extraction_terminal(
    terminal: object,
    *,
    authentication_secret: bytes,
) -> bool:
    try:
        if (
            type(terminal) is not SchedulerAuthenticatedExtractionTerminal
            or type(terminal.evidence) is not SchedulerExtractionTerminalEvidence
            or type(terminal.evidence.context) is not ManagedFullRunExtractionContext
            or type(terminal.evidence.terminal) is not ManagedFullRunExtractionTerminal
        ):
            return False
        SchedulerExtractionTerminalEvidence.__post_init__(terminal.evidence)
        material = terminal.material()
        expected_authentication = _runner_hmac(
            authentication_secret,
            "authenticated-extraction-terminal",
            material,
        )
        expected_commitment = commitment(
            "runner-authenticated-extraction-terminal",
            {
                **material,
                "authentication_sha256": terminal.authentication_sha256,
            },
        )
        return hmac.compare_digest(
            expected_authentication,
            terminal.authentication_sha256,
        ) and hmac.compare_digest(expected_commitment, terminal.commitment_sha256)
    except Exception:
        return False


@final
@dataclass(frozen=True, slots=True)
class SchedulerSuiteSeal:
    suite_authority_sha256: str
    runtime_provenance_sha256: str
    ordered_run_authority_sha256: tuple[str, str]
    ordered_evaluation_receipt_root_sha256: tuple[str, str]
    ordered_extraction_terminal_sha256: tuple[str, str]
    ordered_authenticated_extraction_terminal_sha256: tuple[str, str]
    renderer_policy_sha256: str
    private_answer_policy_sha256: str
    receipt_verifier_policy_sha256: str
    outcome_readback_policy_sha256: str
    extraction_terminal_read_policy_sha256: str
    seal_readback_policy_sha256: str
    case_count: int
    evaluation_call_count: int
    extraction_operation_count: int
    charged_tokens: int
    call_ledger: PublishableCallLedger = field(default_factory=exact_publishable_call_ledger)
    paired_outcome: PairedOutcomeSealBinding | None = None
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        digest_pairs = (
            self.ordered_run_authority_sha256,
            self.ordered_evaluation_receipt_root_sha256,
            self.ordered_extraction_terminal_sha256,
            self.ordered_authenticated_extraction_terminal_sha256,
        )
        if (
            not is_sha256(self.suite_authority_sha256)
            or any(
                not is_sha256(value)
                for value in (
                    self.renderer_policy_sha256,
                    self.private_answer_policy_sha256,
                    self.receipt_verifier_policy_sha256,
                    self.outcome_readback_policy_sha256,
                    self.extraction_terminal_read_policy_sha256,
                    self.seal_readback_policy_sha256,
                    self.runtime_provenance_sha256,
                )
            )
            or self.seal_readback_policy_sha256 != SUITE_SEAL_READBACK_POLICY_SHA256
            or any(
                type(pair) is not tuple
                or len(pair) != 2
                or any(not is_sha256(item) for item in pair)
                for pair in digest_pairs
            )
            or self.case_count != PUBLISHABLE_SUITE_CASE_COUNT
            or self.evaluation_call_count != PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
            or self.extraction_operation_count != PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT
            or type(self.charged_tokens) is not int
            or self.charged_tokens < 0
            or type(self.call_ledger) is not PublishableCallLedger
            or self.call_ledger.extraction_call_count != self.extraction_operation_count
            or self.call_ledger.answer_judge_call_count != self.evaluation_call_count
            or self.paired_outcome is not None
            and type(self.paired_outcome) is not PairedOutcomeSealBinding
        ):
            _fail("scheduler_runner_suite_seal_invalid")
        try:
            PublishableCallLedger.__post_init__(self.call_ledger)
            if self.paired_outcome is not None:
                PairedOutcomeSealBinding.__post_init__(self.paired_outcome)
        except SchedulerRunnerError:
            raise
        except Exception:
            _fail("scheduler_runner_suite_seal_invalid")
        object.__setattr__(
            self,
            "commitment_sha256",
            commitment("runner-suite-seal", self.material()),
        )

    def material(self) -> dict[str, object]:
        return {
            "call_ledger": self.call_ledger.material(),
            "case_count": self.case_count,
            "charged_tokens": self.charged_tokens,
            "evaluation_call_count": self.evaluation_call_count,
            "extraction_terminal_read_policy_sha256": (self.extraction_terminal_read_policy_sha256),
            "extraction_operation_count": self.extraction_operation_count,
            "ordered_authenticated_extraction_terminal_sha256": list(
                self.ordered_authenticated_extraction_terminal_sha256
            ),
            "ordered_evaluation_receipt_root_sha256": list(
                self.ordered_evaluation_receipt_root_sha256
            ),
            "ordered_extraction_terminal_sha256": list(self.ordered_extraction_terminal_sha256),
            "ordered_run_authority_sha256": list(self.ordered_run_authority_sha256),
            "outcome_readback_policy_sha256": self.outcome_readback_policy_sha256,
            "paired_outcome": (
                None if self.paired_outcome is None else self.paired_outcome.material()
            ),
            "private_answer_policy_sha256": self.private_answer_policy_sha256,
            "receipt_verifier_policy_sha256": self.receipt_verifier_policy_sha256,
            "renderer_policy_sha256": self.renderer_policy_sha256,
            "runtime_provenance_sha256": self.runtime_provenance_sha256,
            "schema_version": RUNNER_SCHEMA_VERSION,
            "seal_readback_policy_sha256": self.seal_readback_policy_sha256,
            "suite_authority_sha256": self.suite_authority_sha256,
        }


def bound_request_sha256(
    *,
    suite_authority_sha256: str,
    run_authority_sha256: str,
    bridge_boot_authority_sha256: str,
    renderer_policy_sha256: str,
    private_answer_policy_sha256: str,
    dependency_answer_ciphertext_sha256: str | None,
    call: SchedulerLogicalCall,
    payload: bytes,
) -> str:
    if (
        any(
            not is_sha256(value)
            for value in (
                suite_authority_sha256,
                run_authority_sha256,
                bridge_boot_authority_sha256,
                renderer_policy_sha256,
                private_answer_policy_sha256,
            )
        )
        or (call.stage is SchedulerCallStage.JUDGE)
        != is_sha256(dependency_answer_ciphertext_sha256)
        or type(call) is not SchedulerLogicalCall
        or type(payload) is not bytes
        or not 1 <= len(payload) <= RUNNER_REQUEST_BYTES_CAP
    ):
        _fail("scheduler_runner_request_material_invalid")
    return commitment(
        "runner-bound-request",
        {
            "bridge_boot_authority_sha256": bridge_boot_authority_sha256,
            "dependency_answer_ciphertext_sha256": dependency_answer_ciphertext_sha256,
            "logical_call_id": call.logical_call_id,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "private_answer_policy_sha256": private_answer_policy_sha256,
            "renderer_policy_sha256": renderer_policy_sha256,
            "run_authority_sha256": run_authority_sha256,
            "schema_version": RUNNER_SCHEMA_VERSION,
            "suite_authority_sha256": suite_authority_sha256,
        },
    )


def dispatch_intent_sha256(
    *,
    envelope_binding: dict[str, object],
) -> str:
    if type(envelope_binding) is not dict:
        _fail("scheduler_runner_intent_material_invalid")
    # Canonicalize before commitment so non-JSON values fail before intent is durable.
    canonical_json(envelope_binding)
    return commitment("runner-dispatch-intent", envelope_binding)


def is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def suite_seal_from_material(material: object) -> SchedulerSuiteSeal:
    """Decode only the exact canonical sidecar payload shape."""

    if type(material) is not dict or material.get("schema_version") != RUNNER_SCHEMA_VERSION:
        _fail("scheduler_runner_suite_seal_material_invalid")
    expected = {
        "call_ledger",
        "case_count",
        "charged_tokens",
        "evaluation_call_count",
        "extraction_operation_count",
        "extraction_terminal_read_policy_sha256",
        "ordered_authenticated_extraction_terminal_sha256",
        "ordered_evaluation_receipt_root_sha256",
        "ordered_extraction_terminal_sha256",
        "ordered_run_authority_sha256",
        "outcome_readback_policy_sha256",
        "paired_outcome",
        "private_answer_policy_sha256",
        "receipt_verifier_policy_sha256",
        "renderer_policy_sha256",
        "runtime_provenance_sha256",
        "schema_version",
        "seal_readback_policy_sha256",
        "suite_authority_sha256",
    }
    if set(material) != expected:
        _fail("scheduler_runner_suite_seal_material_invalid")
    try:
        return SchedulerSuiteSeal(
            suite_authority_sha256=material["suite_authority_sha256"],
            runtime_provenance_sha256=material["runtime_provenance_sha256"],
            ordered_run_authority_sha256=tuple(material["ordered_run_authority_sha256"]),
            ordered_evaluation_receipt_root_sha256=tuple(
                material["ordered_evaluation_receipt_root_sha256"]
            ),
            ordered_extraction_terminal_sha256=tuple(
                material["ordered_extraction_terminal_sha256"]
            ),
            ordered_authenticated_extraction_terminal_sha256=tuple(
                material["ordered_authenticated_extraction_terminal_sha256"]
            ),
            renderer_policy_sha256=material["renderer_policy_sha256"],
            private_answer_policy_sha256=material["private_answer_policy_sha256"],
            receipt_verifier_policy_sha256=material["receipt_verifier_policy_sha256"],
            outcome_readback_policy_sha256=material["outcome_readback_policy_sha256"],
            extraction_terminal_read_policy_sha256=(
                material["extraction_terminal_read_policy_sha256"]
            ),
            seal_readback_policy_sha256=material["seal_readback_policy_sha256"],
            case_count=material["case_count"],
            evaluation_call_count=material["evaluation_call_count"],
            extraction_operation_count=material["extraction_operation_count"],
            charged_tokens=material["charged_tokens"],
            call_ledger=publishable_call_ledger_from_material(material["call_ledger"]),
            paired_outcome=(
                None
                if material["paired_outcome"] is None
                else paired_outcome_seal_binding_from_material(material["paired_outcome"])
            ),
        )
    except (KeyError, TypeError, ValueError, SchedulerRunnerError):
        _fail("scheduler_runner_suite_seal_material_invalid")


def _extraction_authentication_material(
    *,
    run_authority_sha256: str,
    read_policy_sha256: str,
    evidence: SchedulerExtractionTerminalEvidence,
) -> dict[str, object]:
    if (
        not is_sha256(run_authority_sha256)
        or not is_sha256(read_policy_sha256)
        or type(evidence) is not SchedulerExtractionTerminalEvidence
    ):
        _fail("scheduler_runner_extraction_authentication_material_invalid")
    SchedulerExtractionTerminalEvidence.__post_init__(evidence)
    return {
        "evidence": evidence.material(),
        "read_policy_sha256": read_policy_sha256,
        "run_authority_sha256": run_authority_sha256,
        "schema_version": RUNNER_SCHEMA_VERSION,
    }


def _runner_hmac(secret: bytes, domain: str, material: object) -> str:
    if type(secret) is not bytes or not 32 <= len(secret) <= 1024:
        _fail("scheduler_runner_authentication_secret_invalid")
    message = (
        b"memory-comparison/scheduler/runner/v2/"
        + domain.encode("ascii")
        + b"\0"
        + canonical_json(material)
    )
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code)


__all__ = (
    "LOCOMO_EXTRACTION_OPERATION_COUNT",
    "LONGMEMEVAL_EXTRACTION_OPERATION_COUNT",
    "PUBLISHABLE_SUITE_CASE_COUNT",
    "PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT",
    "PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT",
    "PUBLISHABLE_SUITE_TOTAL_CALL_COUNT",
    "NO_EXTRACTION_TERMINAL_READ_POLICY_SHA256",
    "NO_OUTCOME_READBACK_POLICY_SHA256",
    "RUNNER_PAGE_SIZE",
    "RUNNER_SCHEMA_VERSION",
    "SCHEDULER_PRODUCTION_BRIDGE_ADAPTER_READY",
    "SCHEDULER_RUNNER_PAID_GO_READY",
    "SCHEDULER_RUNNER_PUBLISHABLE",
    "SCHEDULER_RUNNER_READINESS_BLOCKERS",
    "SUITE_SEAL_READBACK_POLICY_SHA256",
    "SchedulerAuthenticatedExtractionTerminal",
    "SchedulerDispatchEnvelope",
    "SchedulerDispatchOutcome",
    "SchedulerDispatchReadback",
    "SchedulerDispatchReadbackDisposition",
    "SchedulerDispatchReceipt",
    "SchedulerDispatchReconciliationPort",
    "SchedulerExtractionTerminalEvidence",
    "SchedulerExtractionTerminalReadPort",
    "SchedulerOneShotDispatchPort",
    "SchedulerPrivateAnswerReadCapability",
    "SchedulerReceiptVerifierPort",
    "SchedulerRenderedRequest",
    "SchedulerRequestContext",
    "SchedulerRequestRendererPort",
    "SchedulerRunStoreSpec",
    "SchedulerRunnerError",
    "SchedulerStepDisposition",
    "SchedulerStepResult",
    "SchedulerSuiteSeal",
    "SchedulerSuiteSealStoreSpec",
    "authenticate_extraction_terminal",
    "bound_request_sha256",
    "dispatch_intent_sha256",
    "suite_seal_from_material",
    "verify_authenticated_extraction_terminal",
)

"""Narrow private composition ports for official scheduler request rendering."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Protocol, final

from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerBenchmark,
    canonical_json,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SchedulerRunnerError,
)

SCHEDULER_REQUEST_COMPOSITION_SCHEMA_VERSION = (
    "memory-comparison-publishable-request-composition.v1"
)
SCHEDULER_OFFICIAL_ANSWER_CUTOFF = 50
SCHEDULER_OFFICIAL_CASE_BYTES_CAP = 4 * 1024 * 1024
SCHEDULER_RETRIEVAL_EVIDENCE_BYTES_CAP = 4 * 1024 * 1024
SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP = 1024 * 1024
SCHEDULER_PRIVATE_ANSWER_BYTES_CAP = 256 * 1024

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_MAX_JSON_DEPTH = 20
_MAX_JSON_NODES = 100_000


@final
@dataclass(frozen=True, slots=True)
class SchedulerOfficialCaseKey:
    """Exact authenticated case lookup; it contains no evaluator material."""

    suite_authority_sha256: str
    run_authority_sha256: str
    run_binding_commitment_sha256: str
    run_id: str
    benchmark: SchedulerBenchmark
    scheduler_profile_id: str
    publishable_profile_id: str
    publishable_profile_sha256: str
    methodology_sha256: str
    dataset_sha256: str
    case_manifest_sha256: str
    case_index: int
    case_id: str
    case_alias: str
    authority_root_sha256: str

    def __post_init__(self) -> None:
        if (
            any(
                not _is_sha256(value)
                for value in (
                    self.suite_authority_sha256,
                    self.run_authority_sha256,
                    self.run_binding_commitment_sha256,
                    self.publishable_profile_sha256,
                    self.methodology_sha256,
                    self.dataset_sha256,
                    self.case_manifest_sha256,
                    self.authority_root_sha256,
                )
            )
            or type(self.benchmark) is not SchedulerBenchmark
            or any(
                not _is_identifier(value)
                for value in (
                    self.run_id,
                    self.scheduler_profile_id,
                    self.publishable_profile_id,
                )
            )
            or type(self.case_index) is not int
            or self.case_index < 0
            or not _bounded_identity(self.case_id)
            or not _bounded_identity(self.case_alias)
        ):
            _fail("scheduler_official_case_key_invalid")

    def material(self) -> dict[str, object]:
        return {
            "authority_root_sha256": self.authority_root_sha256,
            "benchmark": self.benchmark.value,
            "case_alias": self.case_alias,
            "case_id": self.case_id,
            "case_index": self.case_index,
            "case_manifest_sha256": self.case_manifest_sha256,
            "dataset_sha256": self.dataset_sha256,
            "methodology_sha256": self.methodology_sha256,
            "publishable_profile_id": self.publishable_profile_id,
            "publishable_profile_sha256": self.publishable_profile_sha256,
            "run_authority_sha256": self.run_authority_sha256,
            "run_binding_commitment_sha256": self.run_binding_commitment_sha256,
            "run_id": self.run_id,
            "scheduler_profile_id": self.scheduler_profile_id,
            "schema_version": SCHEDULER_REQUEST_COMPOSITION_SCHEMA_VERSION,
            "suite_authority_sha256": self.suite_authority_sha256,
        }


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerAuthenticatedOfficialCase:
    """One authenticated case. Private evaluator fields are excluded from repr."""

    key: SchedulerOfficialCaseKey
    material_sha256: str
    case: PublicBenchmarkCase = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.key) is not SchedulerOfficialCaseKey
            or not _is_sha256(self.material_sha256)
            or type(self.case) is not PublicBenchmarkCase
            or self.material_sha256 != official_case_material_sha256(self.key, self.case)
        ):
            _fail("scheduler_official_case_material_invalid")

    def __repr__(self) -> str:
        return (
            "SchedulerAuthenticatedOfficialCase("
            f"key={self.key!r}, material_sha256={self.material_sha256!r}, "
            "case=<private>)"
        )

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("SchedulerAuthenticatedOfficialCase contains private material")


class SchedulerOfficialCaseReaderPort(Protocol):
    """Authenticate and return only the one official case named by the key."""

    @property
    def authority_root_sha256(self) -> str: ...

    def read_exact(
        self, *, key: SchedulerOfficialCaseKey
    ) -> SchedulerAuthenticatedOfficialCase: ...


@final
@dataclass(frozen=True, slots=True)
class SchedulerRetrievalEvidenceKey:
    """Exact backend/case/cutoff lookup under a committed retrieval root."""

    case_key: SchedulerOfficialCaseKey
    case_material_sha256: str
    backend_index: int
    backend_role: str
    target_identity_sha256: str
    cutoff: int
    authority_root_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.case_key) is not SchedulerOfficialCaseKey
            or not _is_sha256(self.case_material_sha256)
            or type(self.backend_index) is not int
            or self.backend_index not in (0, 1)
            or not _is_identifier(self.backend_role)
            or not _is_sha256(self.target_identity_sha256)
            or type(self.cutoff) is not int
            or self.cutoff != SCHEDULER_OFFICIAL_ANSWER_CUTOFF
            or not _is_sha256(self.authority_root_sha256)
        ):
            _fail("scheduler_retrieval_evidence_key_invalid")

    def material(self) -> dict[str, object]:
        return {
            "authority_root_sha256": self.authority_root_sha256,
            "backend_index": self.backend_index,
            "backend_role": self.backend_role,
            "case": self.case_key.material(),
            "case_material_sha256": self.case_material_sha256,
            "cutoff": self.cutoff,
            "schema_version": SCHEDULER_REQUEST_COMPOSITION_SCHEMA_VERSION,
            "target_identity_sha256": self.target_identity_sha256,
        }


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerAuthenticatedRetrievalEvidence:
    """One exact ranked result. Memory text and identifiers remain private."""

    key: SchedulerRetrievalEvidenceKey
    material_sha256: str
    memories: tuple[RetrievedMemory, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.key) is not SchedulerRetrievalEvidenceKey
            or not _is_sha256(self.material_sha256)
            or type(self.memories) is not tuple
            or self.material_sha256 != retrieval_evidence_material_sha256(self.key, self.memories)
        ):
            _fail("scheduler_retrieval_evidence_material_invalid")

    def __repr__(self) -> str:
        return (
            "SchedulerAuthenticatedRetrievalEvidence("
            f"key={self.key!r}, material_sha256={self.material_sha256!r}, "
            f"memory_count={len(self.memories)})"
        )

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("SchedulerAuthenticatedRetrievalEvidence contains private material")


class SchedulerRetrievalEvidenceReaderPort(Protocol):
    """Authenticate one backend's exact ranked evidence for one case/cutoff."""

    @property
    def authority_root_sha256(self) -> str: ...

    def read_exact(
        self, *, key: SchedulerRetrievalEvidenceKey
    ) -> SchedulerAuthenticatedRetrievalEvidence: ...


@final
@dataclass(frozen=True, slots=True)
class SchedulerPrivateAnswerDecryptContext:
    """Public binding supplied to the private authenticated decrypt boundary."""

    case_key: SchedulerOfficialCaseKey
    backend_index: int
    backend_role: str
    target_identity_sha256: str
    answer_logical_call_id: str
    judge_logical_call_id: str
    ciphertext_sha256: str
    decrypt_policy_sha256: str
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.case_key) is not SchedulerOfficialCaseKey
            or type(self.backend_index) is not int
            or self.backend_index not in (0, 1)
            or not _is_identifier(self.backend_role)
            or any(
                not _is_sha256(value)
                for value in (
                    self.target_identity_sha256,
                    self.answer_logical_call_id,
                    self.judge_logical_call_id,
                    self.ciphertext_sha256,
                    self.decrypt_policy_sha256,
                )
            )
        ):
            _fail("scheduler_private_answer_decrypt_context_invalid")
        object.__setattr__(
            self,
            "commitment_sha256",
            hashlib.sha256(
                b"memory-comparison/scheduler/private-answer-decrypt/v1\0"
                + canonical_json(self.material())
            ).hexdigest(),
        )

    def material(self) -> dict[str, object]:
        return {
            "answer_logical_call_id": self.answer_logical_call_id,
            "backend_index": self.backend_index,
            "backend_role": self.backend_role,
            "case": self.case_key.material(),
            "ciphertext_sha256": self.ciphertext_sha256,
            "decrypt_policy_sha256": self.decrypt_policy_sha256,
            "judge_logical_call_id": self.judge_logical_call_id,
            "schema_version": SCHEDULER_REQUEST_COMPOSITION_SCHEMA_VERSION,
            "target_identity_sha256": self.target_identity_sha256,
        }


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerDecryptedPrivateAnswer:
    """Authenticated plaintext returned only to the official judge renderer."""

    context: SchedulerPrivateAnswerDecryptContext
    answer: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.context) is not SchedulerPrivateAnswerDecryptContext:
            _fail("scheduler_private_answer_decrypt_result_invalid")
        _bounded_utf8(
            self.answer,
            cap=SCHEDULER_PRIVATE_ANSWER_BYTES_CAP,
            code="scheduler_private_answer_plaintext_invalid",
            allow_empty=True,
        )

    def __repr__(self) -> str:
        return (
            "SchedulerDecryptedPrivateAnswer("
            f"context_commitment_sha256={self.context.commitment_sha256!r}, "
            "answer=<private>)"
        )

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("SchedulerDecryptedPrivateAnswer contains private material")


class SchedulerPrivateOutputDecryptPort(Protocol):
    """Authenticate/decrypt the exact answer ciphertext passed by the runner."""

    @property
    def policy_sha256(self) -> str: ...

    def decrypt_exact(
        self,
        ciphertext: bytes,
        *,
        context: SchedulerPrivateAnswerDecryptContext,
    ) -> SchedulerDecryptedPrivateAnswer: ...


@final
@dataclass(frozen=True, slots=True, repr=False)
class SchedulerOfficialRendererComposition:
    """Immutable roots plus narrow private readers used by the renderer."""

    case_reader: SchedulerOfficialCaseReaderPort = field(repr=False)
    retrieval_reader: SchedulerRetrievalEvidenceReaderPort = field(repr=False)
    private_output_decryptor: SchedulerPrivateOutputDecryptPort = field(repr=False)
    case_authority_root_sha256: str
    retrieval_authority_root_sha256: str
    private_output_decrypt_policy_sha256: str

    def __post_init__(self) -> None:
        self.validate_current()

    def validate_current(self) -> None:
        if not all(
            _is_sha256(value)
            for value in (
                self.case_authority_root_sha256,
                self.retrieval_authority_root_sha256,
                self.private_output_decrypt_policy_sha256,
            )
        ):
            _fail("scheduler_official_renderer_composition_invalid")
        try:
            case_root = self.case_reader.authority_root_sha256
            retrieval_root = self.retrieval_reader.authority_root_sha256
            decrypt_policy = self.private_output_decryptor.policy_sha256
            case_read = self.case_reader.read_exact
            retrieval_read = self.retrieval_reader.read_exact
            decrypt = self.private_output_decryptor.decrypt_exact
        except Exception:
            _fail("scheduler_official_renderer_composition_invalid")
        if (
            case_root != self.case_authority_root_sha256
            or retrieval_root != self.retrieval_authority_root_sha256
            or decrypt_policy != self.private_output_decrypt_policy_sha256
            or not callable(case_read)
            or not callable(retrieval_read)
            or not callable(decrypt)
        ):
            _fail("scheduler_official_renderer_composition_invalid")

    def __repr__(self) -> str:
        return (
            "SchedulerOfficialRendererComposition("
            f"case_authority_root_sha256={self.case_authority_root_sha256!r}, "
            f"retrieval_authority_root_sha256={self.retrieval_authority_root_sha256!r}, "
            "private_ports=<bound>)"
        )


def official_case_material_sha256(
    key: SchedulerOfficialCaseKey,
    case: PublicBenchmarkCase,
) -> str:
    """Commit the exact bounded official case without exposing its values."""

    if type(key) is not SchedulerOfficialCaseKey or type(case) is not PublicBenchmarkCase:
        _fail("scheduler_official_case_material_invalid")
    key.__post_init__()
    material = {"case": _case_material(key, case), "key": key.material()}
    encoded = _bounded_canonical(
        material,
        cap=SCHEDULER_OFFICIAL_CASE_BYTES_CAP,
        invalid="scheduler_official_case_material_invalid",
        oversized="scheduler_official_case_material_too_large",
    )
    return hashlib.sha256(encoded).hexdigest()


def retrieval_evidence_material_sha256(
    key: SchedulerRetrievalEvidenceKey,
    memories: tuple[RetrievedMemory, ...],
) -> str:
    """Commit exact ordered backend evidence, including non-prompt metadata."""

    if type(key) is not SchedulerRetrievalEvidenceKey or type(memories) is not tuple:
        _fail("scheduler_retrieval_evidence_material_invalid")
    key.__post_init__()
    if len(memories) > key.cutoff:
        _fail("scheduler_retrieval_evidence_material_invalid")
    material = {
        "key": key.material(),
        "memories": [
            _retrieved_memory_material(memory, expected_rank=index)
            for index, memory in enumerate(memories, start=1)
        ],
    }
    encoded = _bounded_canonical(
        material,
        cap=SCHEDULER_RETRIEVAL_EVIDENCE_BYTES_CAP,
        invalid="scheduler_retrieval_evidence_material_invalid",
        oversized="scheduler_retrieval_evidence_material_too_large",
    )
    return hashlib.sha256(encoded).hexdigest()


def _case_material(
    key: SchedulerOfficialCaseKey,
    case: PublicBenchmarkCase,
) -> dict[str, object]:
    if (
        case.benchmark != key.benchmark.value
        or case.case_id != key.case_id
        or not _valid_text(case.question, allow_empty=False)
        or type(case.expected_terms) is not tuple
        or type(case.forbidden_terms) is not tuple
        or any(
            not _valid_text(item, allow_empty=True)
            for item in case.expected_terms + case.forbidden_terms
        )
        or type(case.memories) is not tuple
        or type(case.documents) is not tuple
        or type(case.conversations) is not tuple
        or not _optional_text(case.memory_scope_external_ref)
        or not _optional_text(case.thread_external_ref)
        or type(case.metadata) is not dict
    ):
        _fail("scheduler_official_case_material_invalid")
    memories = [_case_memory(item) for item in case.memories]
    documents = [_case_document(item) for item in case.documents]
    conversations = [_case_conversation(item) for item in case.conversations]
    return {
        "benchmark": case.benchmark,
        "case_alias": key.case_alias,
        "case_id": case.case_id,
        "conversations": conversations,
        "documents": documents,
        "expected_terms": list(case.expected_terms),
        "forbidden_terms": list(case.forbidden_terms),
        "memories": memories,
        "memory_scope_external_ref": case.memory_scope_external_ref,
        "metadata": _json_value(case.metadata),
        "question": case.question,
        "thread_external_ref": case.thread_external_ref,
    }


def _case_memory(value: object) -> dict[str, object]:
    if (
        type(value) is not BenchmarkMemoryInput
        or not _valid_text(value.text, allow_empty=True)
        or not _valid_text(value.kind, allow_empty=True)
        or not _optional_text(value.source_external_id)
        or type(value.metadata) is not dict
    ):
        _fail("scheduler_official_case_material_invalid")
    return {
        "kind": value.kind,
        "metadata": _json_value(value.metadata),
        "source_external_id": value.source_external_id,
        "text": value.text,
    }


def _case_document(value: object) -> dict[str, object]:
    if (
        type(value) is not BenchmarkDocumentInput
        or any(
            not _valid_text(item, allow_empty=True)
            for item in (value.title, value.text, value.source_type, value.classification)
        )
        or not _optional_text(value.source_external_id)
        or type(value.source_refs) is not tuple
        or any(type(item) is not dict for item in value.source_refs)
    ):
        _fail("scheduler_official_case_material_invalid")
    return {
        "classification": value.classification,
        "source_external_id": value.source_external_id,
        "source_refs": _json_value(list(value.source_refs)),
        "source_type": value.source_type,
        "text": value.text,
        "title": value.title,
    }


def _case_conversation(value: object) -> dict[str, object]:
    if (
        type(value) is not BenchmarkConversationInput
        or type(value.messages) is not tuple
        or not _optional_text(value.source_external_id)
        or not _optional_text(value.session_external_id)
        or not _optional_text(value.session_date)
        or not _optional_int(value.timestamp)
        or type(value.metadata) is not dict
    ):
        _fail("scheduler_official_case_material_invalid")
    return {
        "messages": [_case_message(item) for item in value.messages],
        "metadata": _json_value(value.metadata),
        "session_date": value.session_date,
        "session_external_id": value.session_external_id,
        "source_external_id": value.source_external_id,
        "timestamp": value.timestamp,
    }


def _case_message(value: object) -> dict[str, object]:
    if (
        type(value) is not BenchmarkMessageInput
        or value.role not in {"user", "assistant", "system"}
        or not _valid_text(value.content, allow_empty=True)
        or not _optional_text(value.source_external_id)
        or not _optional_int(value.timestamp)
        or type(value.metadata) is not dict
    ):
        _fail("scheduler_official_case_material_invalid")
    return {
        "content": value.content,
        "metadata": _json_value(value.metadata),
        "role": value.role,
        "source_external_id": value.source_external_id,
        "timestamp": value.timestamp,
    }


def _retrieved_memory_material(value: object, *, expected_rank: int) -> dict[str, object]:
    if (
        type(value) is not RetrievedMemory
        or not _valid_text(value.text, allow_empty=True)
        or type(value.rank) is not int
        or value.rank != expected_rank
        or type(value.score) not in {int, float}
        or isinstance(value.score, bool)
        or not math.isfinite(value.score)
        or not _optional_text(value.item_id)
        or not _optional_text(value.created_at)
        or type(value.source_refs) is not tuple
        or any(not _valid_text(item, allow_empty=True) for item in value.source_refs)
        or type(value.metadata) is not dict
    ):
        _fail("scheduler_retrieval_evidence_material_invalid")
    return {
        "created_at": value.created_at,
        "item_id": value.item_id,
        "metadata": _json_value(value.metadata),
        "rank": value.rank,
        "score": value.score,
        "source_refs": list(value.source_refs),
        "text": value.text,
    }


def _json_value(value: object, *, depth: int = 0, nodes: list[int] | None = None) -> object:
    budget = [0] if nodes is None else nodes
    budget[0] += 1
    if budget[0] > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
        _fail("scheduler_private_json_material_invalid")
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is str:
        _bounded_utf8(
            value,
            cap=SCHEDULER_OFFICIAL_CASE_BYTES_CAP,
            code=("scheduler_private_json_material_invalid"),
            allow_empty=True,
        )
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _fail("scheduler_private_json_material_invalid")
        return value
    if type(value) is list:
        return [_json_value(item, depth=depth + 1, nodes=budget) for item in value]
    if type(value) is dict:
        if any(type(key) is not str or not key for key in value):
            _fail("scheduler_private_json_material_invalid")
        return {
            key: _json_value(item, depth=depth + 1, nodes=budget) for key, item in value.items()
        }
    _fail("scheduler_private_json_material_invalid")


def _bounded_canonical(
    value: object,
    *,
    cap: int,
    invalid: str,
    oversized: str,
) -> bytes:
    try:
        encoded = canonical_json(value)
    except Exception:
        _fail(invalid)
    if not encoded or len(encoded) > cap:
        _fail(oversized)
    return encoded


def _bounded_utf8(value: object, *, cap: int, code: str, allow_empty: bool) -> bytes:
    if type(value) is not str:
        _fail(code)
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        _fail(code)
    if len(encoded) > cap or not allow_empty and not encoded:
        _fail(code)
    return encoded


def _optional_text(value: object) -> bool:
    return value is None or _valid_text(value, allow_empty=True)


def _optional_int(value: object) -> bool:
    return value is None or type(value) is int


def _bounded_identity(value: object) -> bool:
    if not _valid_text(value, allow_empty=False):
        return False
    return len(value.encode("utf-8")) <= 200


def _valid_text(value: object, *, allow_empty: bool) -> bool:
    if type(value) is not str or not allow_empty and not value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER.fullmatch(value) is not None


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code)


__all__ = (
    "SCHEDULER_OFFICIAL_ANSWER_CUTOFF",
    "SCHEDULER_OFFICIAL_CASE_BYTES_CAP",
    "SCHEDULER_PRIVATE_ANSWER_BYTES_CAP",
    "SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP",
    "SCHEDULER_REQUEST_COMPOSITION_SCHEMA_VERSION",
    "SCHEDULER_RETRIEVAL_EVIDENCE_BYTES_CAP",
    "SchedulerAuthenticatedOfficialCase",
    "SchedulerAuthenticatedRetrievalEvidence",
    "SchedulerDecryptedPrivateAnswer",
    "SchedulerOfficialCaseKey",
    "SchedulerOfficialCaseReaderPort",
    "SchedulerOfficialRendererComposition",
    "SchedulerPrivateAnswerDecryptContext",
    "SchedulerPrivateOutputDecryptPort",
    "SchedulerRetrievalEvidenceKey",
    "SchedulerRetrievalEvidenceReaderPort",
    "official_case_material_sha256",
    "retrieval_evidence_material_sha256",
)

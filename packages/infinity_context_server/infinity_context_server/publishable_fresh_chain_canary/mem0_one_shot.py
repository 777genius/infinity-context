"""Concrete one-shot Mem0 v5 boundary for the fresh-chain canary.

The adapter is deliberately narrow: one manifest unit, one durable operator-
local HMAC claim, one exact idempotent recovery key, authenticated storage and
search readback, and one terminal cleanup.  It implements the existing
``PublishableExtractionOneShotPort`` seam without adding a hosted-job layer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import tempfile
import threading
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    CleanupVerificationContext,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssRunSeal,
    operation_root,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanupReceipt,
    Mem0V5RuntimeReceiptEnvelope,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionCommand,
)
from infinity_context_server.publishable_durable_scheduler.retrieval_capture_contracts import (
    SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
)

from .contracts import (
    FreshChainCallFailure,
    FreshChainCallResult,
    FreshChainCanaryError,
    FreshChainCleanupResult,
    FreshChainRetrievalHandoff,
)
from .mem0_abort_cleanup import cleanup_failed_extraction
from .mem0_lifecycle import OperatorLocalHmacFreshChainLifecycleJournal
from .mem0_operation_evidence import operation_evidence as _operation_evidence
from .mem0_retrieval_authority import FreshChainMem0RetrievalMaterial

_JOURNAL_SCHEMA = "memory-comparison-fresh-chain-mem0-one-shot.v1"
_ABSENCE_SCHEMA = "memory-comparison-fresh-chain-mem0-absence.v1"
_MAX_JOURNAL_BYTES = 2 * 1024 * 1024
_EMPTY_ROOT_SHA256 = hashlib.sha256(b"").hexdigest()


@final
@dataclass(frozen=True, slots=True)
class FreshChainMem0AbsenceProof:
    """HMAC-authenticated absence for one exact local one-shot generation."""

    namespace_id: str
    namespace_commitment_sha256: str
    command_commitment_sha256: str
    journal_path_sha256: str
    absence_hmac_sha256: str

    def unsigned_payload(self) -> dict[str, str]:
        return {
            "command_commitment_sha256": self.command_commitment_sha256,
            "journal_path_sha256": self.journal_path_sha256,
            "namespace_commitment_sha256": self.namespace_commitment_sha256,
            "namespace_id": self.namespace_id,
            "schema_version": _ABSENCE_SCHEMA,
        }


@final
class OperatorLocalHmacMem0OneShotJournal:
    """Durable claim and provider receipt cache for exactly one extraction."""

    __slots__ = (
        "_key",
        "_namespace_commitment_sha256",
        "_namespace_id",
        "_path",
        "_path_sha256",
        "_lock",
    )

    def __init__(
        self,
        path: Path,
        *,
        authentication_key: bytes,
        namespace_id: str,
        namespace_commitment_sha256: str,
    ) -> None:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.name in {"", ".", ".."}
            or type(authentication_key) is not bytes
            or len(authentication_key) != 32
            or not _identifier(namespace_id)
            or not _sha(namespace_commitment_sha256)
        ):
            _fail("fresh_chain_mem0_journal_configuration_invalid")
        _require_private_directory(path.parent)
        self._path = path
        self._key = bytes(authentication_key)
        self._namespace_id = namespace_id
        self._namespace_commitment_sha256 = namespace_commitment_sha256
        self._path_sha256 = canonical_sha256({"absolute_path": str(path)})
        self._lock = threading.RLock()

    def absence(self, command: PublishableExtractionCommand) -> FreshChainMem0AbsenceProof | None:
        with self._lock:
            self._require_command(command)
            if self._path.exists() or self._path.is_symlink():
                self._read(command)
                return None
            unsigned = {
                "command_commitment_sha256": command.command_commitment_sha256,
                "journal_path_sha256": self._path_sha256,
                "namespace_commitment_sha256": self._namespace_commitment_sha256,
                "namespace_id": self._namespace_id,
                "schema_version": _ABSENCE_SCHEMA,
            }
            return FreshChainMem0AbsenceProof(
                namespace_id=self._namespace_id,
                namespace_commitment_sha256=self._namespace_commitment_sha256,
                command_commitment_sha256=command.command_commitment_sha256,
                journal_path_sha256=self._path_sha256,
                absence_hmac_sha256=self._sign(unsigned),
            )

    def authenticate_absence(
        self,
        proof: object,
        *,
        command: PublishableExtractionCommand,
    ) -> str | None:
        with self._lock:
            self._require_command(command)
            if type(proof) is not FreshChainMem0AbsenceProof:
                return None
            unsigned = proof.unsigned_payload()
            expected = (
                proof.namespace_id == self._namespace_id
                and proof.namespace_commitment_sha256 == self._namespace_commitment_sha256
                and proof.command_commitment_sha256 == command.command_commitment_sha256
                and proof.journal_path_sha256 == self._path_sha256
                and _sha(proof.absence_hmac_sha256)
                and hmac.compare_digest(
                    proof.absence_hmac_sha256,
                    self._sign(unsigned),
                )
                and not self._path.exists()
                and not self._path.is_symlink()
            )
            if not expected:
                _fail("fresh_chain_mem0_absence_unauthenticated")
            return canonical_sha256({**unsigned, "absence_hmac_sha256": proof.absence_hmac_sha256})

    def claim(self, command: PublishableExtractionCommand) -> None:
        with self._lock:
            self._require_command(command)
            record = self._record(command=command, envelope=None)
            encoded = _canonical(record)
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            descriptor: int | None = None
            try:
                descriptor = os.open(self._path, flags, 0o600)
                os.fchmod(descriptor, 0o600)
                _require_private_file(os.fstat(descriptor))
                _write_all(descriptor, encoded)
                os.fsync(descriptor)
            except FileExistsError:
                self._read(command)
                _fail("fresh_chain_mem0_dispatch_duplicate")
            except FreshChainCanaryError:
                raise
            except Exception:
                _fail("fresh_chain_mem0_claim_failed")
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            _fsync_directory(self._path.parent)

    def terminal(
        self,
        command: PublishableExtractionCommand,
    ) -> Mem0V5RuntimeReceiptEnvelope | None:
        with self._lock:
            record = self._read(command)
            envelope = record["envelope"]
            if envelope is None:
                return None
            return _envelope(envelope)

    def record_terminal(
        self,
        command: PublishableExtractionCommand,
        envelope: Mem0V5RuntimeReceiptEnvelope,
    ) -> None:
        with self._lock:
            current = self._read(command)
            payload = _envelope_payload(envelope)
            if current["envelope"] is not None:
                if current["envelope"] != payload:
                    _fail("fresh_chain_mem0_terminal_replay_conflict")
                return
            record = self._record(command=command, envelope=payload)
            self._replace(_canonical(record))

    def require_claimed(self, command: PublishableExtractionCommand) -> None:
        with self._lock:
            self._read(command)

    def _read(self, command: PublishableExtractionCommand) -> dict[str, object]:
        self._require_command(command)
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self._path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            )
            metadata = os.fstat(descriptor)
            _require_private_file(metadata)
            if not 1 <= metadata.st_size <= _MAX_JOURNAL_BYTES:
                raise ValueError
            raw = _read_bounded(descriptor, _MAX_JOURNAL_BYTES)
            value = json.loads(raw, object_pairs_hook=_unique_object)
        except FreshChainCanaryError:
            raise
        except Exception:
            _fail("fresh_chain_mem0_journal_invalid")
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if type(value) is not dict or _canonical(value) != raw:
            _fail("fresh_chain_mem0_journal_invalid")
        expected_keys = {
            "command",
            "command_commitment_sha256",
            "envelope",
            "journal_hmac_sha256",
            "journal_path_sha256",
            "namespace_commitment_sha256",
            "namespace_id",
            "schema_version",
        }
        unsigned = {key: item for key, item in value.items() if key != "journal_hmac_sha256"}
        if (
            set(value) != expected_keys
            or value["schema_version"] != _JOURNAL_SCHEMA
            or value["namespace_id"] != self._namespace_id
            or value["namespace_commitment_sha256"] != self._namespace_commitment_sha256
            or value["journal_path_sha256"] != self._path_sha256
            or value["command"] != command.payload()
            or value["command_commitment_sha256"] != command.command_commitment_sha256
            or not _sha(value["journal_hmac_sha256"])
            or not hmac.compare_digest(
                str(value["journal_hmac_sha256"]),
                self._sign(unsigned),
            )
            or value["envelope"] is not None
            and _envelope(value["envelope"]) is None
        ):
            _fail("fresh_chain_mem0_journal_invalid")
        return value

    def _record(
        self,
        *,
        command: PublishableExtractionCommand,
        envelope: dict[str, object] | None,
    ) -> dict[str, object]:
        unsigned: dict[str, object] = {
            "command": command.payload(),
            "command_commitment_sha256": command.command_commitment_sha256,
            "envelope": envelope,
            "journal_path_sha256": self._path_sha256,
            "namespace_commitment_sha256": self._namespace_commitment_sha256,
            "namespace_id": self._namespace_id,
            "schema_version": _JOURNAL_SCHEMA,
        }
        return {**unsigned, "journal_hmac_sha256": self._sign(unsigned)}

    def _replace(self, encoded: bytes) -> None:
        temporary: Path | None = None
        descriptor: int | None = None
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=f".{self._path.name}.",
                dir=self._path.parent,
            )
            temporary = Path(name)
            os.fchmod(descriptor, 0o600)
            _require_private_file(os.fstat(descriptor))
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(temporary, self._path)
            temporary = None
            _fsync_directory(self._path.parent)
        except Exception:
            _fail("fresh_chain_mem0_journal_update_failed")
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink()

    def _sign(self, payload: dict[str, object]) -> str:
        return hmac.new(self._key, _canonical(payload), hashlib.sha256).hexdigest()

    def _require_command(self, command: object) -> None:
        if type(command) is not PublishableExtractionCommand:
            _fail("fresh_chain_mem0_command_invalid")
        try:
            command.__post_init__()
        except Exception:
            _fail("fresh_chain_mem0_command_invalid")


@final
class FreshChainMem0OneShotAdapter:
    """One authenticated Mem0 extraction over the established v5 HTTP lane."""

    __slots__ = (
        "_admission",
        "_admitted",
        "_authority",
        "_command",
        "_expected_runtime_binding_sha256",
        "_journal",
        "_lane",
        "_lock",
        "_unit",
    )

    def __init__(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        unit: ManagedMem0V5SourceUnit,
        command: PublishableExtractionCommand,
        lane: ManagedMem0V5HttpLane,
        expected_runtime_binding_sha256: str,
        journal: OperatorLocalHmacMem0OneShotJournal,
    ) -> None:
        if (
            type(authority) is not ManagedMem0V5ManifestAuthority
            or type(admission) is not Mem0OssFullRunAdmission
            or type(unit) is not ManagedMem0V5SourceUnit
            or type(command) is not PublishableExtractionCommand
            or type(lane) is not ManagedMem0V5HttpLane
            or not _sha(expected_runtime_binding_sha256)
            or type(journal) is not OperatorLocalHmacMem0OneShotJournal
            or authority.operation_count != 1
            or authority.units != (unit,)
            or admission.ingestion_unit_count != 1
            or admission.ingestion_manifest_sha256 != authority.ingestion_manifest_sha256
            or admission.ingestion_root_sha256 != authority.ingestion_root_sha256
        ):
            _fail("fresh_chain_mem0_one_shot_composition_invalid")
        self._authority = authority
        self._admission = admission
        self._unit = unit
        self._command = command
        self._lane = lane
        self._expected_runtime_binding_sha256 = expected_runtime_binding_sha256
        self._journal = journal
        self._admitted = False
        self._lock = threading.RLock()

    def lookup_outcome(self, *, command: PublishableExtractionCommand) -> object:
        with self._lock:
            self._require_command(command)
            absence = self._journal.absence(command)
            if absence is not None:
                return absence
            cached = self._journal.terminal(command)
            if cached is not None:
                return cached
            self._ensure_admitted()
            observed = self._lane.status(
                authority=self._authority,
                unit=self._unit,
                operation_id_sha256=command.operation_id_sha256,
                admission=self._admission,
            )
            if type(observed) is not Mem0V5RuntimeReceiptEnvelope:
                _fail("fresh_chain_mem0_status_invalid")
            self._journal.record_terminal(command, observed)
            return observed

    def dispatch_once(self, *, command: PublishableExtractionCommand) -> object:
        with self._lock:
            self._require_command(command)
            self._journal.claim(command)
            self._ensure_admitted()
            observed = self._lane.dispatch(
                authority=self._authority,
                unit=self._unit,
                operation_id_sha256=command.operation_id_sha256,
                admission=self._admission,
            )
            if type(observed) is not Mem0V5RuntimeReceiptEnvelope:
                _fail("fresh_chain_mem0_dispatch_invalid")
            self._journal.record_terminal(command, observed)
            return observed

    def recover_once(self, *, command: PublishableExtractionCommand) -> object:
        """Recover by authenticated status readback; never re-enter dispatch."""

        with self._lock:
            self._require_command(command)
            self._journal.require_claimed(command)
            cached = self._journal.terminal(command)
            if cached is not None:
                return cached
            self._ensure_admitted()
            observed = self._lane.status(
                authority=self._authority,
                unit=self._unit,
                operation_id_sha256=command.operation_id_sha256,
                admission=self._admission,
            )
            if type(observed) is not Mem0V5RuntimeReceiptEnvelope:
                _fail("fresh_chain_mem0_recovery_invalid")
            self._journal.record_terminal(command, observed)
            return observed

    def authenticate_pre_dispatch_absence(
        self,
        *,
        payload: object,
        command: PublishableExtractionCommand,
        namespace_id: str,
        namespace_commitment_sha256: str,
    ) -> str | None:
        self._require_command(command)
        if (
            namespace_id != self._journal._namespace_id
            or namespace_commitment_sha256 != self._journal._namespace_commitment_sha256
        ):
            _fail("fresh_chain_mem0_absence_crosswire")
        return self._journal.authenticate_absence(payload, command=command)

    def _ensure_admitted(self) -> None:
        if self._admitted:
            return
        receipt = self._lane.admit(
            authority=self._authority,
            admission=self._admission,
        )
        if (
            receipt.admission_commitment_sha256 != self._admission.commitment_sha256
            or receipt.runtime_binding_commitment_sha256 != self._expected_runtime_binding_sha256
            or receipt.accepted is not True
        ):
            _fail("fresh_chain_mem0_admission_crosswire")
        self._admitted = True

    def _require_command(self, command: object) -> None:
        if type(command) is not PublishableExtractionCommand or command != self._command:
            _fail("fresh_chain_mem0_command_crosswire")


@final
class FreshChainMem0RetrievalCleanup:
    """Bind authenticated fresh retrieval and terminal deletion to one unit."""

    __slots__ = (
        "_admission",
        "_captured",
        "_case_question",
        "_cleanup_result",
        "_journal",
        "_lane",
        "_manifest",
        "_memories",
        "_namespace_commitment_sha256",
        "_namespace_id",
        "_operation_id_sha256",
        "_source_commitment_sha256",
        "_source_projection_commitment_sha256",
        "_storage",
        "_unit",
    )

    def __init__(
        self,
        *,
        lane: ManagedMem0V5HttpLane,
        admission: Mem0OssFullRunAdmission,
        manifest: ManagedMem0V5ManifestAuthority,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        case_question: str,
        namespace_id: str,
        namespace_commitment_sha256: str,
        source_commitment_sha256: str,
        source_projection_commitment_sha256: str,
        journal: OperatorLocalHmacFreshChainLifecycleJournal,
    ) -> None:
        if (
            type(lane) is not ManagedMem0V5HttpLane
            or type(admission) is not Mem0OssFullRunAdmission
            or type(manifest) is not ManagedMem0V5ManifestAuthority
            or type(unit) is not ManagedMem0V5SourceUnit
            or not _sha(operation_id_sha256)
            or type(case_question) is not str
            or not case_question
            or not _identifier(namespace_id)
            or not _sha(namespace_commitment_sha256)
            or not _sha(source_commitment_sha256)
            or not _sha(source_projection_commitment_sha256)
            or type(journal) is not OperatorLocalHmacFreshChainLifecycleJournal
            or journal.namespace_id != namespace_id
            or journal.namespace_commitment_sha256 != namespace_commitment_sha256
            or journal.source_commitment_sha256 != source_commitment_sha256
            or journal.source_projection_commitment_sha256 != source_projection_commitment_sha256
            or manifest.units != (unit,)
        ):
            _fail("fresh_chain_mem0_retrieval_composition_invalid")
        self._lane = lane
        self._admission = admission
        self._manifest = manifest
        self._unit = unit
        self._operation_id_sha256 = operation_id_sha256
        self._case_question = case_question
        self._namespace_id = namespace_id
        self._namespace_commitment_sha256 = namespace_commitment_sha256
        self._source_commitment_sha256 = source_commitment_sha256
        self._source_projection_commitment_sha256 = source_projection_commitment_sha256
        self._journal = journal
        self._captured: tuple[FreshChainCallResult, FreshChainRetrievalHandoff] | None = None
        self._storage: ManagedMem0V5AuthenticatedStorageWitness | None = None
        self._memories: tuple[RetrievedMemory, ...] = ()
        self._cleanup_result: FreshChainCleanupResult | None = None

    @property
    def retrieved_memories(self) -> tuple[RetrievedMemory, ...]:
        if self._captured is None or not self._memories:
            _fail("fresh_chain_mem0_retrieval_not_captured")
        return self._memories

    @property
    def source_projection_commitment_sha256(self) -> str:
        return self._source_projection_commitment_sha256

    def capture(
        self,
        *,
        extraction: FreshChainCallResult,
        namespace_id: str,
        namespace_commitment_sha256: str,
        source_commitment_sha256: str,
        source_projection_commitment_sha256: str,
    ) -> FreshChainRetrievalHandoff:
        if (
            type(extraction) is not FreshChainCallResult
            or extraction.stage != "mem0_extraction"
            or extraction.ordinal != 0
            or namespace_id != self._namespace_id
            or namespace_commitment_sha256 != self._namespace_commitment_sha256
            or source_commitment_sha256 != self._source_commitment_sha256
            or source_projection_commitment_sha256 != self._source_projection_commitment_sha256
        ):
            _fail("fresh_chain_mem0_retrieval_binding_invalid")
        if self._captured is not None:
            known_extraction, known_handoff = self._captured
            if known_extraction != replace(
                extraction,
                transport_dispatched=known_extraction.transport_dispatched,
            ):
                _fail("fresh_chain_mem0_retrieval_replay_conflict")
            return known_handoff
        persisted = self._journal.retrieval(extraction)
        if persisted is not None:
            self._captured = (persisted.extraction, persisted.handoff)
            self._storage = persisted.storage
            self._memories = persisted.memories
            return persisted.handoff
        storage = self._lane.inspect_storage(
            unit=self._unit,
            operation_id_sha256=self._operation_id_sha256,
            admission=self._admission,
        )
        witness = self._lane.search_authenticated(
            admission=self._admission,
            corpus_id=self._unit.corpus_id,
            query=self._case_question,
            limit=SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT,
        )
        receipt = witness.receipt
        try:
            receipt.__post_init__()
        except Exception:
            _fail("fresh_chain_mem0_retrieval_evidence_invalid")
        result_root = canonical_sha256(
            {"results": [item.public_payload(rank) for rank, item in enumerate(receipt.records)]}
        )
        created_record_ids = frozenset(storage.created_record_ids)
        retrieved_record_ids = tuple(item.record_id for item in receipt.records)
        if (
            type(storage) is not ManagedMem0V5AuthenticatedStorageWitness
            or storage.operation_id_sha256 != self._operation_id_sha256
            or storage.unit_identity_sha256 != self._unit.unit_identity_sha256
            or not storage.created_record_ids
            or storage.source_pairs != ((self._unit.source_id, self._unit.source_sha256),)
            or receipt.admission_commitment_sha256 != self._admission.commitment_sha256
            or receipt.corpus_id != self._unit.corpus_id
            or receipt.query_commitment_sha256 != canonical_sha256({"query": self._case_question})
            or receipt.limit != SCHEDULER_OFFICIAL_RETRIEVAL_LIMIT
            or not receipt.records
            or receipt.result_root_sha256 != result_root
            or len(set(retrieved_record_ids)) != len(retrieved_record_ids)
            or not set(retrieved_record_ids).issubset(created_record_ids)
            or any(
                item.source_id != self._unit.source_id
                or item.source_sha256 != self._unit.source_sha256
                for item in receipt.records
            )
        ):
            _fail("fresh_chain_mem0_retrieval_evidence_invalid")
        selected_records = receipt.records[:SCHEDULER_OFFICIAL_ANSWER_CUTOFF]
        retrieval_payload = {
            "admission_commitment_sha256": receipt.admission_commitment_sha256,
            "answer_cutoff": SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
            "evidence_commitment_sha256": receipt.evidence_commitment_sha256,
            "limit": receipt.limit,
            "query_commitment_sha256": receipt.query_commitment_sha256,
            "records": [item.public_payload(rank) for rank, item in enumerate(selected_records)],
            "result_count": len(receipt.records),
            "result_root_sha256": receipt.result_root_sha256,
        }
        retrieval_material = FreshChainMem0RetrievalMaterial.from_payload(retrieval_payload)
        retrieval_material_sha256 = canonical_sha256(retrieval_material.payload())
        memory_authority_sha256 = canonical_sha256(
            {
                "extraction_receipt_sha256": extraction.physical_receipt_sha256,
                "source_projection_commitment_sha256": (self._source_projection_commitment_sha256),
                "storage": storage.public_payload(),
            }
        )
        retrieval_authority_sha256 = canonical_sha256(
            {
                "memory_authority_sha256": memory_authority_sha256,
                "retrieval_material_sha256": retrieval_material_sha256,
            }
        )
        handoff = FreshChainRetrievalHandoff(
            extraction_intent_sha256=extraction.intent_sha256,
            extraction_result_sha256=extraction.result_sha256,
            extraction_receipt_sha256=extraction.physical_receipt_sha256,
            namespace_commitment_sha256=namespace_commitment_sha256,
            source_commitment_sha256=source_commitment_sha256,
            source_projection_commitment_sha256=(self._source_projection_commitment_sha256),
            memory_authority_sha256=memory_authority_sha256,
            retrieval_authority_sha256=retrieval_authority_sha256,
            retrieval_material_sha256=retrieval_material_sha256,
            memory_count=len(selected_records),
        )
        memories = retrieval_material.memories()
        persisted = self._journal.record_retrieval(
            extraction=extraction,
            handoff=handoff,
            memories=memories,
            storage=storage,
            retrieval_material=retrieval_material,
        )
        self._storage = persisted.storage
        self._memories = persisted.memories
        self._captured = (persisted.extraction, persisted.handoff)
        return persisted.handoff

    def cleanup(
        self,
        *,
        namespace_id: str,
        namespace_commitment_sha256: str,
        failure: FreshChainCallFailure | None = None,
    ) -> FreshChainCleanupResult:
        if (
            namespace_id != self._namespace_id
            or namespace_commitment_sha256 != self._namespace_commitment_sha256
        ):
            _fail("fresh_chain_mem0_cleanup_crosswire")
        if self._cleanup_result is not None:
            return self._cleanup_result
        if failure is not None and type(failure) is not FreshChainCallFailure:
            _fail("fresh_chain_mem0_cleanup_failure_invalid")
        if failure is not None and failure.stage == "mem0_extraction":
            self._cleanup_result = cleanup_failed_extraction(
                lane=self._lane,
                admission=self._admission,
                unit=self._unit,
                operation_id_sha256=self._operation_id_sha256,
                namespace_id=self._namespace_id,
                namespace_commitment_sha256=self._namespace_commitment_sha256,
                source_commitment_sha256=self._source_commitment_sha256,
                source_projection_commitment_sha256=(self._source_projection_commitment_sha256),
                failure=failure,
                journal=self._journal,
            )
            return self._cleanup_result
        if self._captured is None or self._storage is None:
            _fail("fresh_chain_mem0_cleanup_before_retrieval")
        extraction, _handoff = self._captured
        evidence = _operation_evidence(
            unit=self._unit,
            operation_id_sha256=self._operation_id_sha256,
            extraction=extraction,
            storage=self._storage,
        )
        root = operation_root((evidence,))
        seal = Mem0OssRunSeal(
            admission_commitment_sha256=self._admission.commitment_sha256,
            operation_count=1,
            ingestion_root_sha256=self._manifest.ingestion_root_sha256,
            operation_root_sha256=root,
            provider_observed_extraction_calls=1,
            provider_observed_request_tokens=extraction.usage.prompt_tokens,
            provider_observed_response_tokens=extraction.usage.completion_tokens,
        )
        context = CleanupVerificationContext(
            admission_commitment_sha256=self._admission.commitment_sha256,
            seal_commitment_sha256=seal.commitment_sha256,
            operation_root_sha256=root,
            operation_inventory_root_sha256=canonical_sha256({"operations": [evidence.payload()]}),
            expected_operation_count=1,
            aborting=False,
        )
        cleanup_intent = {
            "admission_commitment_sha256": self._admission.commitment_sha256,
            "cleanup_context": asdict(context),
            "namespace_commitment_sha256": self._namespace_commitment_sha256,
            "namespace_id": self._namespace_id,
            "operation_evidence": evidence.payload(),
            "operation_id_sha256": self._operation_id_sha256,
            "seal": asdict(seal),
            "source_commitment_sha256": self._source_commitment_sha256,
            "source_projection_commitment_sha256": (self._source_projection_commitment_sha256),
        }
        terminal = self._journal.begin_cleanup(cleanup_intent)
        if terminal is not None:
            self._cleanup_result = terminal
            return terminal
        receipt = self._lane.cleanup(
            admission=self._admission,
            seal=seal,
            aborting=False,
            context=context,
        )
        if (
            type(receipt) is not Mem0V5CleanupReceipt
            or receipt.admission_commitment_sha256 != self._admission.commitment_sha256
            or receipt.seal_commitment_sha256 != seal.commitment_sha256
            or receipt.operation_root_sha256 != root
            or receipt.operation_inventory_root_sha256 != context.operation_inventory_root_sha256
            or receipt.deleted_operation_count != 1
            or receipt.residual_record_count != 0
            or receipt.residual_root_sha256 != _EMPTY_ROOT_SHA256
        ):
            _fail("fresh_chain_mem0_cleanup_receipt_invalid")
        receipt_payload = asdict(receipt)
        receipt_sha256 = canonical_sha256(receipt_payload)
        outcome_sha256 = canonical_sha256(
            {
                "deleted": True,
                "receipt_sha256": receipt_sha256,
                "residual_count": 0,
            }
        )
        result = FreshChainCleanupResult(
            namespace_commitment_sha256=self._namespace_commitment_sha256,
            cleanup_authority_sha256=canonical_sha256(asdict(context)),
            receipt_id=f"mem0-cleanup:{receipt_sha256}",
            receipt_sha256=receipt_sha256,
            outcome_sha256=outcome_sha256,
            deleted=True,
            operation_count=1,
            residual_count=0,
        )
        self._cleanup_result = self._journal.record_cleanup_terminal(
            cleanup_intent=cleanup_intent,
            result=result,
        )
        return self._cleanup_result


def _envelope_payload(value: Mem0V5RuntimeReceiptEnvelope) -> dict[str, object]:
    if type(value) is not Mem0V5RuntimeReceiptEnvelope:
        _fail("fresh_chain_mem0_terminal_invalid")
    return {
        "admission_commitment_sha256": value.admission_commitment_sha256,
        "operation_id_sha256": value.operation_id_sha256,
        "runtime_receipt": value.runtime_receipt,
    }


def _envelope(value: object) -> Mem0V5RuntimeReceiptEnvelope:
    if type(value) is not dict or set(value) != {
        "admission_commitment_sha256",
        "operation_id_sha256",
        "runtime_receipt",
    }:
        _fail("fresh_chain_mem0_terminal_invalid")
    try:
        envelope = Mem0V5RuntimeReceiptEnvelope(**value)
    except TypeError:
        _fail("fresh_chain_mem0_terminal_invalid")
    if (
        not _sha(envelope.admission_commitment_sha256)
        or not _sha(envelope.operation_id_sha256)
        or type(envelope.runtime_receipt) is not dict
    ):
        _fail("fresh_chain_mem0_terminal_invalid")
    return envelope


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError):
        _fail("fresh_chain_mem0_journal_invalid")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _read_bounded(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise ValueError
    return b"".join(chunks)


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError
        offset += written


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_private_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
        valid = (
            path.is_absolute()
            and path.resolve(strict=True) == path
            and stat.S_ISDIR(metadata.st_mode)
            and not stat.S_ISLNK(metadata.st_mode)
            and metadata.st_uid == os.geteuid()
            and stat.S_IMODE(metadata.st_mode) == 0o700
        )
    except OSError:
        valid = False
    if not valid:
        _fail("fresh_chain_mem0_journal_directory_invalid")


def _require_private_file(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        _fail("fresh_chain_mem0_journal_file_invalid")


def _identifier(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 512
        and value == value.strip()
        and all(character.isalnum() or character in "._:-" for character in value)
    )


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = (
    "FreshChainMem0AbsenceProof",
    "FreshChainMem0OneShotAdapter",
    "FreshChainMem0RetrievalCleanup",
    "OperatorLocalHmacMem0OneShotJournal",
)

"""Durable operator-local HMAC state for fresh Mem0 retrieval and cleanup.

The extraction one-shot journal protects the mutating extraction boundary.  This
separate journal protects the retrieval handoff which the Mem0 answer consumes
and the exact cleanup request/result.  A process restart can therefore reuse
authenticated retrieval evidence and recover an in-flight cleanup through the
managed lane's fixed idempotency key without repeating any paid provider call.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import stat
import tempfile
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256
from infinity_context_server.memory_comparison_models import RetrievedMemory

from .contracts import (
    FreshChainCallResult,
    FreshChainCanaryError,
    FreshChainCleanupResult,
    FreshChainRetrievalHandoff,
    FreshChainUsage,
)
from .mem0_retrieval_authority import FreshChainMem0RetrievalMaterial

_SCHEMA = "memory-comparison-fresh-chain-mem0-lifecycle.v1"
_MAX_BYTES = 32 * 1024 * 1024


@final
@dataclass(frozen=True, slots=True)
class FreshChainMem0PersistedRetrieval:
    """Authenticated retrieval state reconstructed from operator-local storage."""

    extraction: FreshChainCallResult
    handoff: FreshChainRetrievalHandoff
    memories: tuple[RetrievedMemory, ...]
    storage: ManagedMem0V5AuthenticatedStorageWitness
    retrieval_material: FreshChainMem0RetrievalMaterial


@final
class OperatorLocalHmacFreshChainLifecycleJournal:
    """Atomic HMAC journal for retrieval replay and cleanup recovery."""

    __slots__ = (
        "_key",
        "_lock",
        "_namespace_commitment_sha256",
        "_namespace_id",
        "_path",
        "_path_sha256",
        "_source_commitment_sha256",
        "_source_projection_commitment_sha256",
    )

    def __init__(
        self,
        path: Path,
        *,
        authentication_key: bytes,
        namespace_id: str,
        namespace_commitment_sha256: str,
        source_commitment_sha256: str,
        source_projection_commitment_sha256: str,
    ) -> None:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.name in {"", ".", ".."}
            or type(authentication_key) is not bytes
            or len(authentication_key) != 32
            or not _identifier(namespace_id)
            or not _sha(namespace_commitment_sha256)
            or not _sha(source_commitment_sha256)
            or not _sha(source_projection_commitment_sha256)
        ):
            _fail("fresh_chain_mem0_lifecycle_configuration_invalid")
        _require_private_directory(path.parent)
        self._path = path
        self._key = bytes(authentication_key)
        self._namespace_id = namespace_id
        self._namespace_commitment_sha256 = namespace_commitment_sha256
        self._source_commitment_sha256 = source_commitment_sha256
        self._source_projection_commitment_sha256 = source_projection_commitment_sha256
        self._path_sha256 = canonical_sha256({"absolute_path": str(path)})
        self._lock = threading.RLock()

    @property
    def namespace_id(self) -> str:
        return self._namespace_id

    @property
    def namespace_commitment_sha256(self) -> str:
        return self._namespace_commitment_sha256

    @property
    def source_commitment_sha256(self) -> str:
        return self._source_commitment_sha256

    @property
    def source_projection_commitment_sha256(self) -> str:
        return self._source_projection_commitment_sha256

    def retrieval(
        self,
        extraction: FreshChainCallResult,
    ) -> FreshChainMem0PersistedRetrieval | None:
        """Return authenticated cached retrieval, or proven local absence."""

        with self._lock:
            if not self._path.exists() and not self._path.is_symlink():
                return None
            record = self._read()
            state = _retrieval(record["retrieval"])
            if not _same_durable_result(state.extraction, extraction) or not self._bound(state):
                _fail("fresh_chain_mem0_lifecycle_retrieval_replay_conflict")
            return state

    def record_retrieval(
        self,
        *,
        extraction: FreshChainCallResult,
        handoff: FreshChainRetrievalHandoff,
        memories: tuple[RetrievedMemory, ...],
        storage: ManagedMem0V5AuthenticatedStorageWitness,
        retrieval_material: FreshChainMem0RetrievalMaterial,
    ) -> FreshChainMem0PersistedRetrieval:
        """Create the retrieval cache once, accepting only identical replay."""

        state = FreshChainMem0PersistedRetrieval(
            extraction=extraction,
            handoff=handoff,
            memories=_require_memories(memories),
            storage=storage,
            retrieval_material=retrieval_material,
        )
        if not self._bound(state):
            _fail("fresh_chain_mem0_lifecycle_retrieval_crosswire")
        retrieval_payload = _retrieval_payload(state)
        with self._lock:
            if self._path.exists() or self._path.is_symlink():
                existing = _retrieval(self._read()["retrieval"])
                if (
                    not _same_durable_result(existing.extraction, state.extraction)
                    or existing.handoff != state.handoff
                    or existing.memories != state.memories
                    or existing.storage != state.storage
                    or existing.retrieval_material != state.retrieval_material
                ):
                    _fail("fresh_chain_mem0_lifecycle_retrieval_replay_conflict")
                return existing
            self._create(self._record(retrieval=retrieval_payload, cleanup=None))
            return state

    def begin_cleanup(
        self,
        cleanup_intent: dict[str, object],
    ) -> FreshChainCleanupResult | None:
        """Durably claim an exact cleanup before invoking its idempotent seam."""

        intent = _cleanup_intent(cleanup_intent)
        with self._lock:
            if not self._path.exists() and not self._path.is_symlink():
                self._create(self._record(retrieval=None, cleanup=None))
            record = self._read()
            cleanup = record["cleanup"]
            if cleanup is None:
                self._replace(
                    self._record(
                        retrieval=record["retrieval"],
                        cleanup={
                            "intent": intent,
                            "intent_sha256": canonical_sha256(intent),
                            "terminal": None,
                        },
                    )
                )
                return None
            parsed_intent, terminal = _cleanup(cleanup)
            if parsed_intent != intent:
                _fail("fresh_chain_mem0_lifecycle_cleanup_replay_conflict")
            return terminal

    def record_cleanup_terminal(
        self,
        *,
        cleanup_intent: dict[str, object],
        result: FreshChainCleanupResult,
    ) -> FreshChainCleanupResult:
        """Persist one verified terminal cleanup receipt, idempotently."""

        intent = _cleanup_intent(cleanup_intent)
        if (
            type(result) is not FreshChainCleanupResult
            or result.namespace_commitment_sha256 != self._namespace_commitment_sha256
        ):
            _fail("fresh_chain_mem0_lifecycle_cleanup_invalid")
        terminal_payload = result.material()
        with self._lock:
            record = self._read()
            cleanup = record["cleanup"]
            if cleanup is None:
                _fail("fresh_chain_mem0_lifecycle_cleanup_not_claimed")
            known_intent, terminal = _cleanup(cleanup)
            if known_intent != intent:
                _fail("fresh_chain_mem0_lifecycle_cleanup_replay_conflict")
            if terminal is not None:
                if terminal != result:
                    _fail("fresh_chain_mem0_lifecycle_cleanup_replay_conflict")
                return terminal
            self._replace(
                self._record(
                    retrieval=record["retrieval"],
                    cleanup={
                        "intent": intent,
                        "intent_sha256": canonical_sha256(intent),
                        "terminal": terminal_payload,
                    },
                )
            )
            return result

    def _read(self) -> dict[str, object]:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self._path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            )
            metadata = os.fstat(descriptor)
            _require_private_file(metadata)
            if not 1 <= metadata.st_size <= _MAX_BYTES:
                raise ValueError
            raw = _read_bounded(descriptor, _MAX_BYTES)
            value = json.loads(raw, object_pairs_hook=_unique_object)
        except FreshChainCanaryError:
            raise
        except Exception:
            _fail("fresh_chain_mem0_lifecycle_journal_invalid")
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if type(value) is not dict or _canonical(value) != raw:
            _fail("fresh_chain_mem0_lifecycle_journal_invalid")
        expected_keys = {
            "cleanup",
            "journal_hmac_sha256",
            "journal_path_sha256",
            "namespace_commitment_sha256",
            "namespace_id",
            "retrieval",
            "schema_version",
            "source_commitment_sha256",
            "source_projection_commitment_sha256",
        }
        unsigned = {key: item for key, item in value.items() if key != "journal_hmac_sha256"}
        if (
            set(value) != expected_keys
            or value["schema_version"] != _SCHEMA
            or value["namespace_id"] != self._namespace_id
            or value["namespace_commitment_sha256"] != self._namespace_commitment_sha256
            or value["source_commitment_sha256"] != self._source_commitment_sha256
            or value["source_projection_commitment_sha256"]
            != self._source_projection_commitment_sha256
            or value["journal_path_sha256"] != self._path_sha256
            or not _sha(value["journal_hmac_sha256"])
            or not hmac.compare_digest(str(value["journal_hmac_sha256"]), self._sign(unsigned))
        ):
            _fail("fresh_chain_mem0_lifecycle_journal_invalid")
        if value["retrieval"] is not None:
            _retrieval(value["retrieval"])
        if value["cleanup"] is not None:
            _cleanup(value["cleanup"])
        return value

    def _record(
        self,
        *,
        retrieval: dict[str, object] | None,
        cleanup: dict[str, object] | None,
    ) -> dict[str, object]:
        unsigned: dict[str, object] = {
            "cleanup": cleanup,
            "journal_path_sha256": self._path_sha256,
            "namespace_commitment_sha256": self._namespace_commitment_sha256,
            "namespace_id": self._namespace_id,
            "retrieval": retrieval,
            "schema_version": _SCHEMA,
            "source_commitment_sha256": self._source_commitment_sha256,
            "source_projection_commitment_sha256": (self._source_projection_commitment_sha256),
        }
        return {**unsigned, "journal_hmac_sha256": self._sign(unsigned)}

    def _create(self, record: dict[str, object]) -> None:
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
            _fail("fresh_chain_mem0_lifecycle_journal_race")
        except FreshChainCanaryError:
            raise
        except Exception:
            _fail("fresh_chain_mem0_lifecycle_journal_create_failed")
        finally:
            if descriptor is not None:
                os.close(descriptor)
        _fsync_directory(self._path.parent)

    def _replace(self, record: dict[str, object]) -> None:
        encoded = _canonical(record)
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
            _fail("fresh_chain_mem0_lifecycle_journal_update_failed")
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink()

    def _sign(self, payload: dict[str, object]) -> str:
        return hmac.new(self._key, _canonical(payload), hashlib.sha256).hexdigest()

    def _bound(self, state: FreshChainMem0PersistedRetrieval) -> bool:
        return (
            state.handoff.namespace_commitment_sha256 == self._namespace_commitment_sha256
            and state.handoff.source_commitment_sha256 == self._source_commitment_sha256
            and state.handoff.source_projection_commitment_sha256
            == self._source_projection_commitment_sha256
            and state.handoff.memory_count == len(state.memories)
            and state.handoff.memory_count == len(state.retrieval_material.records)
            and state.memories == state.retrieval_material.memories()
            and {item.record_id for item in state.retrieval_material.records}.issubset(
                set(state.storage.created_record_ids)
            )
            and state.handoff.retrieval_material_sha256
            == canonical_sha256(state.retrieval_material.payload())
            and state.handoff.memory_authority_sha256
            == canonical_sha256(
                {
                    "extraction_receipt_sha256": state.extraction.physical_receipt_sha256,
                    "source_projection_commitment_sha256": (
                        self._source_projection_commitment_sha256
                    ),
                    "storage": state.storage.public_payload(),
                }
            )
            and state.handoff.retrieval_authority_sha256
            == canonical_sha256(
                {
                    "memory_authority_sha256": state.handoff.memory_authority_sha256,
                    "retrieval_material_sha256": state.handoff.retrieval_material_sha256,
                }
            )
            and bool(state.storage.created_record_ids)
        )


def _retrieval_payload(state: FreshChainMem0PersistedRetrieval) -> dict[str, object]:
    if (
        type(state.extraction) is not FreshChainCallResult
        or state.extraction.stage != "mem0_extraction"
        or state.extraction.ordinal != 0
        or type(state.handoff) is not FreshChainRetrievalHandoff
        or type(state.storage) is not ManagedMem0V5AuthenticatedStorageWitness
        or state.handoff.extraction_intent_sha256 != state.extraction.intent_sha256
        or state.handoff.extraction_result_sha256 != state.extraction.result_sha256
        or state.handoff.extraction_receipt_sha256 != state.extraction.physical_receipt_sha256
    ):
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")
    return {
        "extraction": _call_payload(state.extraction),
        "handoff": state.handoff.material(),
        "memories": [_memory_payload(item) for item in state.memories],
        "retrieval_material": state.retrieval_material.payload(),
        "storage": state.storage.public_payload(),
    }


def _same_durable_result(left: FreshChainCallResult, right: FreshChainCallResult) -> bool:
    """Compare persisted provider identity, excluding the local dispatch observation."""

    return (
        left.stage,
        left.ordinal,
        left.intent_sha256,
        left.result_sha256,
        left.physical_receipt_sha256,
        left.receipt_id,
        left.usage,
        left.output_text,
        left.commitments,
    ) == (
        right.stage,
        right.ordinal,
        right.intent_sha256,
        right.result_sha256,
        right.physical_receipt_sha256,
        right.receipt_id,
        right.usage,
        right.output_text,
        right.commitments,
    )


def _retrieval(value: object) -> FreshChainMem0PersistedRetrieval:
    if type(value) is not dict or set(value) != {
        "extraction",
        "handoff",
        "memories",
        "retrieval_material",
        "storage",
    }:
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")
    try:
        memories_value = value["memories"]
        if type(memories_value) is not list:
            raise TypeError
        state = FreshChainMem0PersistedRetrieval(
            extraction=_call_result(value["extraction"]),
            handoff=_handoff(value["handoff"]),
            memories=_require_memories(tuple(_memory(item) for item in memories_value)),
            storage=_storage(value["storage"]),
            retrieval_material=FreshChainMem0RetrievalMaterial.from_payload(
                value["retrieval_material"]
            ),
        )
    except FreshChainCanaryError:
        raise
    except Exception:
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")
    _retrieval_payload(state)
    return state


def _call_payload(value: FreshChainCallResult) -> dict[str, object]:
    return {
        "commitments": {key: item for key, item in value.commitments},
        "intent_sha256": value.intent_sha256,
        "ordinal": value.ordinal,
        "output_text": value.output_text,
        "physical_receipt_sha256": value.physical_receipt_sha256,
        "receipt_id": value.receipt_id,
        "result_sha256": value.result_sha256,
        "stage": value.stage,
        "transport_dispatched": value.transport_dispatched,
        "usage": value.usage.payload(),
    }


def _call_result(value: object) -> FreshChainCallResult:
    if type(value) is not dict or set(value) != {
        "commitments",
        "intent_sha256",
        "ordinal",
        "output_text",
        "physical_receipt_sha256",
        "receipt_id",
        "result_sha256",
        "stage",
        "transport_dispatched",
        "usage",
    }:
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")
    usage = value["usage"]
    commitments = value["commitments"]
    if type(usage) is not dict or type(commitments) is not dict:
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")
    try:
        return FreshChainCallResult(
            stage=value["stage"],
            ordinal=value["ordinal"],
            intent_sha256=value["intent_sha256"],
            result_sha256=value["result_sha256"],
            physical_receipt_sha256=value["physical_receipt_sha256"],
            receipt_id=value["receipt_id"],
            usage=FreshChainUsage(**usage),
            transport_dispatched=value["transport_dispatched"],
            output_text=value["output_text"],
            commitments=commitments,
        )
    except (TypeError, ValueError):
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")


def _handoff(value: object) -> FreshChainRetrievalHandoff:
    if type(value) is not dict:
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")
    try:
        return FreshChainRetrievalHandoff(**value)
    except (TypeError, ValueError):
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")


def _storage(value: object) -> ManagedMem0V5AuthenticatedStorageWitness:
    if type(value) is not dict or set(value) != {
        "created_record_ids",
        "evidence_commitment_sha256",
        "operation_id_sha256",
        "source_pairs",
        "storage_commitment_sha256",
        "unit_identity_sha256",
    }:
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")
    pairs = value["source_pairs"]
    records = value["created_record_ids"]
    if type(pairs) is not list or type(records) is not list:
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")
    try:
        return ManagedMem0V5AuthenticatedStorageWitness(
            operation_id_sha256=value["operation_id_sha256"],
            unit_identity_sha256=value["unit_identity_sha256"],
            storage_commitment_sha256=value["storage_commitment_sha256"],
            created_record_ids=tuple(records),
            source_pairs=tuple((item["source_id"], item["source_sha256"]) for item in pairs),
            evidence_commitment_sha256=value["evidence_commitment_sha256"],
        )
    except (KeyError, TypeError, ValueError):
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")


def _memory_payload(value: RetrievedMemory) -> dict[str, object]:
    if type(value) is not RetrievedMemory:
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")
    return {
        "created_at": value.created_at,
        "item_id": value.item_id,
        "metadata": dict(value.metadata),
        "rank": value.rank,
        "score": value.score,
        "source_refs": list(value.source_refs),
        "text": value.text,
    }


def _memory(value: object) -> RetrievedMemory:
    if type(value) is not dict or set(value) != {
        "created_at",
        "item_id",
        "metadata",
        "rank",
        "score",
        "source_refs",
        "text",
    }:
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")
    if type(value["metadata"]) is not dict or type(value["source_refs"]) is not list:
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")
    try:
        return RetrievedMemory(
            text=value["text"],
            rank=value["rank"],
            score=value["score"],
            item_id=value["item_id"],
            created_at=value["created_at"],
            source_refs=tuple(value["source_refs"]),
            metadata=value["metadata"],
        )
    except TypeError:
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")


def _require_memories(value: object) -> tuple[RetrievedMemory, ...]:
    if (
        type(value) is not tuple
        or not value
        or any(type(item) is not RetrievedMemory for item in value)
        or tuple(item.rank for item in value) != tuple(range(len(value)))
        or any(
            type(item.text) is not str
            or not item.text
            or type(item.score) not in (int, float)
            or isinstance(item.score, bool)
            or not math.isfinite(item.score)
            or item.item_id is not None
            and not _identifier(item.item_id)
            or item.created_at is not None
            or type(item.source_refs) is not tuple
            or not item.source_refs
            or any(not _identifier(ref) for ref in item.source_refs)
            or type(item.metadata) is not dict
            or set(item.metadata) != {"memory_sha256", "source_sha256"}
            or any(not _sha(digest) for digest in item.metadata.values())
            for item in value
        )
    ):
        _fail("fresh_chain_mem0_lifecycle_retrieval_invalid")
    _canonical([_memory_payload(item) for item in value])
    return value


def _cleanup_intent(value: object) -> dict[str, object]:
    if type(value) is not dict or not value:
        _fail("fresh_chain_mem0_lifecycle_cleanup_invalid")
    encoded = _canonical(value)
    if not 1 <= len(encoded) <= _MAX_BYTES:
        _fail("fresh_chain_mem0_lifecycle_cleanup_invalid")
    decoded = json.loads(encoded, object_pairs_hook=_unique_object)
    if type(decoded) is not dict:
        _fail("fresh_chain_mem0_lifecycle_cleanup_invalid")
    return decoded


def _cleanup(value: object) -> tuple[dict[str, object], FreshChainCleanupResult | None]:
    if type(value) is not dict or set(value) != {"intent", "intent_sha256", "terminal"}:
        _fail("fresh_chain_mem0_lifecycle_cleanup_invalid")
    intent = _cleanup_intent(value["intent"])
    if value["intent_sha256"] != canonical_sha256(intent):
        _fail("fresh_chain_mem0_lifecycle_cleanup_invalid")
    terminal_value = value["terminal"]
    if terminal_value is None:
        return intent, None
    if type(terminal_value) is not dict:
        _fail("fresh_chain_mem0_lifecycle_cleanup_invalid")
    try:
        terminal = FreshChainCleanupResult(**terminal_value)
    except (TypeError, ValueError):
        _fail("fresh_chain_mem0_lifecycle_cleanup_invalid")
    return intent, terminal


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError):
        _fail("fresh_chain_mem0_lifecycle_journal_invalid")
    if len(encoded) > _MAX_BYTES:
        _fail("fresh_chain_mem0_lifecycle_journal_invalid")
    return encoded


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
        _fail("fresh_chain_mem0_lifecycle_directory_invalid")


def _require_private_file(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        _fail("fresh_chain_mem0_lifecycle_file_invalid")


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
    "FreshChainMem0PersistedRetrieval",
    "OperatorLocalHmacFreshChainLifecycleJournal",
)

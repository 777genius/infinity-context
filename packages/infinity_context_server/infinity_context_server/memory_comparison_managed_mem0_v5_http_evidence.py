"""Authenticated evidence DTOs and verifier for the managed Mem0 OSS v5 lane."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_verification import (
    verify_clean_state_receipt,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_request_binding import (
    REQUEST_BINDING_DOMAIN,
    REQUEST_BINDING_V2_DOMAIN,
    ManagedMem0V5AuthenticatedRequestBindingV2Witness,
    ManagedMem0V5RequestBindingContext,
    ManagedMem0V5RequestBindingReceipt,
    ManagedMem0V5RequestBindingV2Context,
    verify_request_binding_payload,
    verify_request_binding_v2_payload,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
    ManagedMem0V5StorageWitnessIssuerPort,
    require_managed_mem0_v5_storage_witness_issuer,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanStateReceipt,
    Mem0V5CleanStateRequest,
    Mem0V5CleanStateScope,
    Mem0V5HttpError,
)

_OBSERVATION_SCHEMA = "mem0-oss-adapter-v5.storage-observation.v1"
_SEARCH_SCHEMA = "mem0-oss-adapter-v5.scoped-search.v1"
_KEY_DOMAIN = b"mem0-oss-adapter-v5/evidence-key/v1"
_OBSERVATION_DOMAIN = b"storage-observation/v1"
_SEARCH_DOMAIN = b"scoped-search/v1"
_CLEAN_STATE_DOMAIN = b"clean-state/v1"


@dataclass(frozen=True, slots=True)
class ManagedMem0V5StorageVerificationContext:
    admission_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    scope_sha256: str
    source_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        if any(
            not is_sha256(value)
            for value in (
                self.admission_commitment_sha256,
                self.operation_id_sha256,
                self.unit_identity_sha256,
                self.scope_sha256,
                self.source_sha256,
            )
        ) or not _text(self.source_id, 512):
            _fail("mem0_v5_managed_storage_context_invalid")


@dataclass(frozen=True, slots=True, repr=False)
class ManagedMem0V5SearchVerificationContext:
    admission_commitment_sha256: str
    corpus_id: str
    query: str
    limit: int

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.admission_commitment_sha256)
            or not _text(self.corpus_id, 512)
            or not _text(self.query, 16_384)
            or type(self.limit) is not int  # noqa: E721 - exact DTO type required
            or not 1 <= self.limit <= 200
        ):
            _fail("mem0_v5_managed_search_context_invalid")

    @property
    def query_commitment_sha256(self) -> str:
        return canonical_sha256({"query": self.query})

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(admission_commitment_sha256="
            f"{self.admission_commitment_sha256!r}, corpus_id={self.corpus_id!r}, "
            f"query_commitment_sha256={self.query_commitment_sha256!r}, limit={self.limit!r})"
        )


@final
@dataclass(frozen=True, slots=True, repr=False)
class ManagedMem0V5SearchRecord:
    record_id: str
    memory: str
    memory_sha256: str
    source_id: str
    source_sha256: str
    score: float

    def __post_init__(self) -> None:
        if (
            not _text(self.record_id, 512)
            or not _text(self.memory, 16_384)
            or hashlib.sha256(self.memory.encode()).hexdigest() != self.memory_sha256
            or not _text(self.source_id, 512)
            or not is_sha256(self.source_sha256)
            or type(self.score) is not float  # noqa: E721 - exact DTO type required
            or not math.isfinite(self.score)
            or not 0.0 <= self.score <= 1.0
        ):
            _fail("mem0_v5_managed_search_result_invalid")

    def public_payload(self, rank: int) -> dict[str, object]:
        return {
            "rank": rank,
            "record_id": self.record_id,
            "memory": self.memory,
            "memory_sha256": self.memory_sha256,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
            "score": self.score,
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(record_id={self.record_id!r}, "
            f"memory_sha256={self.memory_sha256!r}, source_id={self.source_id!r}, "
            f"score={self.score!r})"
        )


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5SearchReceipt:
    admission_commitment_sha256: str
    corpus_id: str
    query_commitment_sha256: str
    limit: int
    records: tuple[ManagedMem0V5SearchRecord, ...]
    result_root_sha256: str
    evidence_commitment_sha256: str

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.admission_commitment_sha256)
            or not _text(self.corpus_id, 512)
            or not is_sha256(self.query_commitment_sha256)
            or type(self.limit) is not int  # noqa: E721 - exact DTO type required
            or not 1 <= self.limit <= 200
            or type(self.records) is not tuple  # noqa: E721 - exact DTO type required
            or len(self.records) > self.limit
            or any(type(item) is not ManagedMem0V5SearchRecord for item in self.records)  # noqa: E721
            or len({item.record_id for item in self.records}) != len(self.records)
            or not is_sha256(self.result_root_sha256)
            or not is_sha256(self.evidence_commitment_sha256)
        ):
            _fail("mem0_v5_managed_search_result_invalid")


class ManagedMem0V5EvidenceKeyCapability(Protocol):
    def validate(self) -> None: ...

    def consume(self) -> bytes: ...


class ManagedMem0V5EvidenceVerifierPort(Protocol):
    def verify_storage(
        self, *, payload: object, context: ManagedMem0V5StorageVerificationContext
    ) -> ManagedMem0V5AuthenticatedStorageWitness: ...

    def verify_search(
        self, *, payload: object, context: ManagedMem0V5SearchVerificationContext
    ) -> ManagedMem0V5SearchReceipt: ...

    def verify_clean_state(
        self,
        *,
        receipt: Mem0V5CleanStateReceipt,
        request: Mem0V5CleanStateRequest,
        ingestion_manifest_sha256: str,
        ingestion_root_sha256: str,
    ) -> tuple[Mem0V5CleanStateScope, ...]: ...


@final
class HmacSha256ManagedMem0V5EvidenceVerifier:
    __slots__ = (
        "_clean_state_key",
        "_key_commitment_sha256",
        "_observation_key",
        "_request_binding_key",
        "_request_binding_v2_key",
        "_search_key",
        "_storage_witness_issuer",
    )

    def __init__(
        self,
        *,
        key_capability: ManagedMem0V5EvidenceKeyCapability,
        storage_witness_issuer: ManagedMem0V5StorageWitnessIssuerPort,
    ) -> None:
        try:
            issuer = require_managed_mem0_v5_storage_witness_issuer(storage_witness_issuer)
        except Exception:
            _fail("mem0_v5_managed_storage_witness_authority_invalid")
        try:
            _configuration_callable(key_capability, "validate")()
            consume = _configuration_callable(key_capability, "consume")
        except Exception:
            raise Mem0V5HttpError("mem0_v5_http_configuration_invalid") from None
        material: bytearray | None = None
        try:
            master_key = consume()
            if type(master_key) is not bytes or not 32 <= len(master_key) <= 4_096:  # noqa: E721
                _fail("mem0_v5_managed_evidence_key_invalid")
            material = bytearray(master_key)
            self._key_commitment_sha256 = hashlib.sha256(material).hexdigest()
            root = hmac.new(material, _KEY_DOMAIN, hashlib.sha256).digest()
            self._observation_key = hmac.new(root, _OBSERVATION_DOMAIN, hashlib.sha256).digest()
            self._request_binding_key = hmac.new(
                root, REQUEST_BINDING_DOMAIN, hashlib.sha256
            ).digest()
            self._request_binding_v2_key = hmac.new(
                root, REQUEST_BINDING_V2_DOMAIN, hashlib.sha256
            ).digest()
            self._search_key = hmac.new(root, _SEARCH_DOMAIN, hashlib.sha256).digest()
            self._clean_state_key = hmac.new(root, _CLEAN_STATE_DOMAIN, hashlib.sha256).digest()
            self._storage_witness_issuer = issuer
        except Mem0V5HttpError:
            _close_capability(key_capability)
            raise
        except Exception:
            _close_capability(key_capability)
            raise Mem0V5HttpError("mem0_v5_http_configuration_invalid") from None
        finally:
            if material is not None:
                _wipe_mutable(material)

    @property
    def key_commitment_sha256(self) -> str:
        return self._key_commitment_sha256

    def verify_storage(
        self, *, payload: object, context: ManagedMem0V5StorageVerificationContext
    ) -> ManagedMem0V5AuthenticatedStorageWitness:
        if type(context) is not ManagedMem0V5StorageVerificationContext:
            _fail("mem0_v5_managed_storage_context_invalid")
        value = _dict(payload)
        keys = {
            "schema_version",
            "admission_commitment_sha256",
            "operation_id_sha256",
            "scope_sha256",
            "source_id",
            "source_sha256",
            "storage_commitment_sha256",
            "record_count",
            "record_root_sha256",
            "records",
            "observation_hmac_sha256",
        }
        _exact(value, keys)
        unsigned = {key: item for key, item in value.items() if key != "observation_hmac_sha256"}
        if not _valid_hmac(self._observation_key, unsigned, value["observation_hmac_sha256"]):
            _fail("mem0_v5_managed_storage_evidence_unauthenticated")
        if (
            value["schema_version"] != _OBSERVATION_SCHEMA
            or value["admission_commitment_sha256"] != context.admission_commitment_sha256
            or value["operation_id_sha256"] != context.operation_id_sha256
            or value["scope_sha256"] != context.scope_sha256
            or value["source_id"] != context.source_id
            or value["source_sha256"] != context.source_sha256
            or not is_sha256(value["storage_commitment_sha256"])
            or type(value["records"]) is not list  # noqa: E721 - exact JSON type required
            or type(value["record_count"]) is not int  # noqa: E721
            or value["record_count"] != len(value["records"])
            or not 0 <= value["record_count"] <= 10_000
            or canonical_sha256({"records": value["records"]}) != value["record_root_sha256"]
        ):
            _fail("mem0_v5_managed_storage_evidence_invalid")
        record_ids: list[str] = []
        extraction_ids: list[str] = []
        prior = ""
        for raw in value["records"]:
            record = _dict(raw)
            _exact(
                record,
                {
                    "record_id",
                    "extraction_memory_id",
                    "source_id",
                    "source_sha256",
                    "memory_sha256",
                },
            )
            if (
                not _text(record["record_id"], 512)
                or not _text(record["extraction_memory_id"], 512)
                or record["source_id"] != context.source_id
                or record["source_sha256"] != context.source_sha256
                or not is_sha256(record["memory_sha256"])
                or record["record_id"] <= prior
            ):
                _fail("mem0_v5_managed_storage_evidence_invalid")
            prior = record["record_id"]
            record_ids.append(record["record_id"])
            extraction_ids.append(record["extraction_memory_id"])
        if len(set(record_ids)) != len(record_ids) or len(set(extraction_ids)) != len(
            extraction_ids
        ):
            _fail("mem0_v5_managed_storage_evidence_invalid")
        return self._storage_witness_issuer.issue_authenticated_storage(
            operation_id_sha256=context.operation_id_sha256,
            unit_identity_sha256=context.unit_identity_sha256,
            storage_commitment_sha256=value["storage_commitment_sha256"],
            created_record_ids=tuple(record_ids),
            source_pairs=((context.source_id, context.source_sha256),),
        )

    def verify_request_binding(
        self,
        *,
        payload: object,
        context: ManagedMem0V5RequestBindingContext,
    ) -> ManagedMem0V5RequestBindingReceipt:
        return verify_request_binding_payload(
            payload=payload,
            context=context,
            hmac_key=self._request_binding_key,
        )

    def verify_request_binding_v2(
        self,
        *,
        payload: object,
        context: ManagedMem0V5RequestBindingV2Context,
    ) -> ManagedMem0V5AuthenticatedRequestBindingV2Witness:
        return verify_request_binding_v2_payload(
            payload=payload,
            context=context,
            hmac_key=self._request_binding_v2_key,
        )

    def verify_search(
        self, *, payload: object, context: ManagedMem0V5SearchVerificationContext
    ) -> ManagedMem0V5SearchReceipt:
        if type(context) is not ManagedMem0V5SearchVerificationContext:
            _fail("mem0_v5_managed_search_context_invalid")
        value = _dict(payload)
        keys = {
            "schema_version",
            "admission_commitment_sha256",
            "corpus_id",
            "query_commitment_sha256",
            "limit",
            "result_count",
            "result_root_sha256",
            "results",
            "search_hmac_sha256",
        }
        _exact(value, keys)
        unsigned = {key: item for key, item in value.items() if key != "search_hmac_sha256"}
        if not _valid_hmac(self._search_key, unsigned, value["search_hmac_sha256"]):
            _fail("mem0_v5_managed_search_evidence_unauthenticated")
        if (
            value["schema_version"] != _SEARCH_SCHEMA
            or value["admission_commitment_sha256"] != context.admission_commitment_sha256
            or value["corpus_id"] != context.corpus_id
            or value["query_commitment_sha256"] != context.query_commitment_sha256
            or value["limit"] != context.limit
            or type(value["results"]) is not list  # noqa: E721 - exact JSON type required
            or type(value["result_count"]) is not int  # noqa: E721
            or value["result_count"] != len(value["results"])
            or not 0 <= value["result_count"] <= context.limit
            or canonical_sha256({"results": value["results"]}) != value["result_root_sha256"]
        ):
            _fail("mem0_v5_managed_search_evidence_invalid")
        records = []
        result_keys = {
            "rank",
            "record_id",
            "memory",
            "memory_sha256",
            "source_id",
            "source_sha256",
            "score",
        }
        for rank, raw in enumerate(value["results"]):
            item = _dict(raw)
            _exact(item, result_keys)
            if item["rank"] != rank:
                _fail("mem0_v5_managed_search_evidence_invalid")
            records.append(
                ManagedMem0V5SearchRecord(
                    item["record_id"],
                    item["memory"],
                    item["memory_sha256"],
                    item["source_id"],
                    item["source_sha256"],
                    item["score"],
                )
            )
        return ManagedMem0V5SearchReceipt(
            context.admission_commitment_sha256,
            context.corpus_id,
            context.query_commitment_sha256,
            context.limit,
            tuple(records),
            value["result_root_sha256"],
            canonical_sha256(unsigned),
        )

    def verify_clean_state(
        self,
        *,
        receipt: Mem0V5CleanStateReceipt,
        request: Mem0V5CleanStateRequest,
        ingestion_manifest_sha256: str,
        ingestion_root_sha256: str,
    ) -> tuple[Mem0V5CleanStateScope, ...]:
        return verify_clean_state_receipt(
            signing_key=self._clean_state_key,
            receipt=receipt,
            request=request,
            ingestion_manifest_sha256=ingestion_manifest_sha256,
            ingestion_root_sha256=ingestion_root_sha256,
        )


def _dict(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):  # noqa: E721
        _fail("mem0_v5_managed_evidence_invalid")
    return value


def _exact(value: dict[str, object], keys: set[str]) -> None:
    if set(value) != keys:
        _fail("mem0_v5_managed_evidence_invalid")


def _valid_hmac(key: bytes, payload: dict[str, object], signature: object) -> bool:
    if not is_sha256(signature):
        return False
    expected = hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode())


def _canonical(value: dict[str, object]) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    except (TypeError, ValueError):
        _fail("mem0_v5_managed_evidence_invalid")


def _configuration_callable(value: object, name: str) -> Callable[..., object]:
    try:
        candidate = getattr(value, name, None)
    except Exception:
        raise Mem0V5HttpError("mem0_v5_http_configuration_invalid") from None
    if not callable(candidate):
        raise Mem0V5HttpError("mem0_v5_http_configuration_invalid")
    return candidate


def _close_capability(value: object) -> None:
    with suppress(Exception):
        close = getattr(value, "close", None)
        if callable(close):
            close()


def _wipe_mutable(value: bytearray) -> None:
    value[:] = b"\x00" * len(value)
    value.clear()


def _text(value: object, maximum: int) -> bool:
    return type(value) is str and bool(value) and value == value.strip() and len(value) <= maximum  # noqa: E721


def _fail(code: str) -> None:
    if code == "mem0_v5_managed_storage_witness_authority_invalid":
        code = "mem0_v5_http_configuration_invalid"
    raise Mem0V5HttpError(code)


__all__ = (
    "HmacSha256ManagedMem0V5EvidenceVerifier",
    "ManagedMem0V5EvidenceKeyCapability",
    "ManagedMem0V5EvidenceVerifierPort",
    "ManagedMem0V5SearchReceipt",
    "ManagedMem0V5SearchRecord",
    "ManagedMem0V5SearchVerificationContext",
    "ManagedMem0V5StorageVerificationContext",
)

"""Authenticated HTTP client for the managed Mem0 OSS v5 lane."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol, final
from urllib.parse import urlsplit

import httpx

from infinity_context_server.memory_comparison_managed_mem0_v5_cleanup_binding import (
    ManagedMem0V5CleanupBindingPort,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
    ManagedMem0V5SingleDispatchGuardPort,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_request_binding import (
    REQUEST_BINDING_DOMAIN,
    REQUEST_BINDING_V2_DOMAIN,
    REQUEST_BINDING_V2_SCHEMA,
    ManagedMem0V5AuthenticatedRequestBindingV2Witness,
    ManagedMem0V5DispatchBindingPort,
    ManagedMem0V5DispatchBindingV2Port,
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
from infinity_context_server.memory_comparison_managed_mem0_v5_transport_collector import (
    ManagedMem0V5TransportObservationCollector,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    CleanupVerificationContext,
    Mem0OssFullRunAdmission,
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5AdmitRequest,
    Mem0V5CleanupRequest,
    Mem0V5DispatchRequest,
    Mem0V5HttpError,
    Mem0V5HttpPort,
    Mem0V5StatusRequest,
    Mem0V5TransportPort,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import Mem0OssRunSeal
from infinity_context_server.memory_comparison_mem0_oss_v5_terminal import (
    cleanup_request_payload,
)

_OBSERVATION_SCHEMA = "mem0-oss-adapter-v5.storage-observation.v1"
_SEARCH_SCHEMA = "mem0-oss-adapter-v5.scoped-search.v1"
_KEY_DOMAIN = b"mem0-oss-adapter-v5/evidence-key/v1"
_OBSERVATION_DOMAIN = b"storage-observation/v1"
_SEARCH_DOMAIN = b"scoped-search/v1"
_MAX_RESPONSE_BYTES = 256_000


class ManagedMem0V5BearerCapability(Protocol):
    def consume(self) -> str: ...


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
            or type(self.limit) is not int
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
            or type(self.score) is not float
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
            or type(self.limit) is not int
            or not 1 <= self.limit <= 200
            or type(self.records) is not tuple
            or len(self.records) > self.limit
            or any(type(item) is not ManagedMem0V5SearchRecord for item in self.records)
            or len({item.record_id for item in self.records}) != len(self.records)
            or not is_sha256(self.result_root_sha256)
            or not is_sha256(self.evidence_commitment_sha256)
        ):
            _fail("mem0_v5_managed_search_result_invalid")


class ManagedMem0V5EvidenceKeyCapability(Protocol):
    def consume(self) -> bytes: ...


class ManagedMem0V5EvidenceVerifierPort(Protocol):
    def verify_storage(
        self, *, payload: object, context: ManagedMem0V5StorageVerificationContext
    ) -> ManagedMem0V5AuthenticatedStorageWitness: ...
    def verify_search(
        self, *, payload: object, context: ManagedMem0V5SearchVerificationContext
    ) -> ManagedMem0V5SearchReceipt: ...


@final
class HmacSha256ManagedMem0V5EvidenceVerifier:
    __slots__ = (
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
        consume = _configuration_callable(key_capability, "consume")
        try:
            issuer = require_managed_mem0_v5_storage_witness_issuer(storage_witness_issuer)
        except Exception:
            _fail("mem0_v5_managed_storage_witness_authority_invalid")
        material: bytearray | None = None
        try:
            master_key = consume()
            if type(master_key) is not bytes or len(master_key) < 32:
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
            or type(value["records"]) is not list
            or type(value["record_count"]) is not int
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
            or type(value["results"]) is not list
            or type(value["result_count"]) is not int
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


@final
class ManagedMem0V5HttpLane:
    __slots__ = (
        "_bearer",
        "_binding",
        "_cleanup_binding",
        "_control",
        "_dispatch_guard",
        "_origin",
        "_timeout",
        "_transport",
        "_transport_collector",
        "_verifier",
    )

    def __init__(
        self,
        *,
        origin: str,
        bearer_capability: ManagedMem0V5BearerCapability,
        timeout_seconds: float,
        evidence_verifier: ManagedMem0V5EvidenceVerifierPort,
        dispatch_binding: ManagedMem0V5DispatchBindingV2Port,
        cleanup_binding: ManagedMem0V5CleanupBindingPort,
        dispatch_guard: ManagedMem0V5SingleDispatchGuardPort | None = None,
        transport: Mem0V5TransportPort | None = None,
    ) -> None:
        consume = _configuration_callable(bearer_capability, "consume")
        canonical_origin = _origin(origin)
        canonical_timeout = _timeout(timeout_seconds)
        verified_evidence = _evidence_verifier(evidence_verifier)
        verified_dispatch = _dispatch_binding(dispatch_binding)
        verified_cleanup = _cleanup_binding(cleanup_binding)
        verified_guard = _dispatch_guard(dispatch_guard)
        verified_transport = _transport_port(transport)
        try:
            bearer = consume()
        except Exception:
            raise Mem0V5HttpError("mem0_v5_http_configuration_invalid") from None
        try:
            if not _secret(bearer):
                _fail("mem0_v5_managed_http_configuration_invalid")
            self._origin = canonical_origin
            self._timeout = canonical_timeout
            self._bearer = bearer
            self._transport = verified_transport
            self._verifier = verified_evidence
            self._binding = verified_dispatch
            self._cleanup_binding = verified_cleanup
            self._dispatch_guard = verified_guard
            self._transport_collector = ManagedMem0V5TransportObservationCollector()
            self._control = Mem0V5HttpPort(
                origin=canonical_origin,
                bearer_token=bearer,
                timeout_seconds=canonical_timeout,
                transport=verified_transport,
            )
        except Exception:
            _close_capability(bearer_capability)
            raise

    @property
    def transport_observations(
        self,
    ) -> tuple[ManagedMem0V5AuthenticatedRequestBindingV2Witness, ...]:
        return self._transport_collector.snapshot()

    def admit(
        self, *, authority: ManagedMem0V5ManifestAuthority, admission: Mem0OssFullRunAdmission
    ) -> object:
        request = Mem0V5AdmitRequest(
            admission.commitment_sha256,
            authority.ingestion_manifest_sha256,
            authority.ingestion_root_sha256,
            authority.operation_count,
            admission.request.route_sha256,
            _key("admit", admission.commitment_sha256),
        )
        result = self._control.admit(request)
        if result.admission_commitment_sha256 != admission.commitment_sha256 or not result.accepted:
            _fail("mem0_v5_managed_http_response_invalid")
        return result

    def dispatch(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> object:
        binding = self._read_transport_observation(
            authority=authority,
            unit=unit,
            operation_id_sha256=operation_id_sha256,
            admission=admission,
        )
        request_sha = binding.request_body_sha256
        if not is_sha256(request_sha):
            _fail("mem0_v5_managed_dispatch_binding_invalid")
        if self._dispatch_guard is not None:
            self._dispatch_guard.claim(
                admission_commitment_sha256=admission.commitment_sha256,
                operation_id_sha256=operation_id_sha256,
                request_body_sha256=request_sha,
            )
        result = self._control.dispatch(
            Mem0V5DispatchRequest(
                admission.commitment_sha256,
                operation_id_sha256,
                unit.unit_identity_sha256,
                unit.unit_sha256,
                unit.scope_sha256,
                request_sha,
                unit.sequence,
                _key("dispatch", operation_id_sha256),
            )
        )
        self._transport_collector.record(binding)
        return result

    def _read_transport_observation(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> ManagedMem0V5AuthenticatedRequestBindingV2Witness:
        context = ManagedMem0V5RequestBindingV2Context.from_authority(
            authority=authority,
            unit=unit,
            operation_id_sha256=operation_id_sha256,
            admission=admission,
        )
        body = {
            "schema_version": REQUEST_BINDING_V2_SCHEMA,
            "admission_commitment_sha256": admission.commitment_sha256,
            "operation_id_sha256": operation_id_sha256,
        }
        payload = self._post(
            "/v5/operations/request-binding",
            body,
            _key("request-binding", operation_id_sha256),
        )
        binding = self._binding.verify_request_binding_v2(
            payload=payload,
            context=context,
        )
        return binding

    def status(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> object:
        result = self._control.status(
            Mem0V5StatusRequest(
                admission.commitment_sha256,
                operation_id_sha256,
                _key("status", operation_id_sha256),
            )
        )
        binding = self._read_transport_observation(
            authority=authority,
            unit=unit,
            operation_id_sha256=operation_id_sha256,
            admission=admission,
        )
        self._transport_collector.record_idempotent(binding)
        return result

    def inspect_storage(
        self,
        *,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> ManagedMem0V5AuthenticatedStorageWitness:
        body = {
            "admission_commitment_sha256": admission.commitment_sha256,
            "operation_id_sha256": operation_id_sha256,
        }
        payload = self._post(
            "/v5/operations/storage-observation",
            body,
            _key("observation", operation_id_sha256),
        )
        return self._verifier.verify_storage(
            payload=payload,
            context=ManagedMem0V5StorageVerificationContext(
                admission.commitment_sha256,
                operation_id_sha256,
                unit.unit_identity_sha256,
                unit.scope_sha256,
                unit.source_id,
                unit.source_sha256,
            ),
        )

    def search(
        self,
        *,
        admission: Mem0OssFullRunAdmission,
        corpus_id: str,
        query: str,
        limit: int,
    ) -> ManagedMem0V5SearchReceipt:
        context = ManagedMem0V5SearchVerificationContext(
            admission.commitment_sha256,
            corpus_id,
            query,
            limit,
        )
        body = {
            "admission_commitment_sha256": admission.commitment_sha256,
            "corpus_id": corpus_id,
            "query": query,
            "limit": limit,
        }
        payload = self._post("/v5/runs/search", body, _key("search", canonical_sha256(body)))
        return self._verifier.verify_search(payload=payload, context=context)

    def cleanup(
        self,
        *,
        admission: Mem0OssFullRunAdmission,
        seal: Mem0OssRunSeal | None,
        aborting: bool,
        context: CleanupVerificationContext | None = None,
    ) -> object:
        if context is None:
            context = self._cleanup_binding.cleanup_context(
                admission=admission,
                seal=seal,
                aborting=aborting,
            )
        if (
            context.admission_commitment_sha256 != admission.commitment_sha256
            or context.seal_commitment_sha256 != (None if seal is None else seal.commitment_sha256)
            or context.operation_root_sha256
            != (None if seal is None else seal.operation_root_sha256)
            or context.expected_operation_count != admission.request.expected_operation_count
            or context.aborting is not aborting
        ):
            _fail("mem0_v5_managed_cleanup_binding_invalid")
        body = cleanup_request_payload(context)
        return self._control.cleanup(
            Mem0V5CleanupRequest(
                body["admission_commitment_sha256"],
                body["seal_commitment_sha256"],
                body["operation_root_sha256"],
                body["operation_inventory_root_sha256"],
                body["expected_operation_count"],
                body["aborting"],
                _key("cleanup", canonical_sha256(body)),
            )
        )

    def _post(self, path: str, body: dict[str, object], idempotency_key: str) -> dict[str, object]:
        encoded = _canonical(body)
        headers = {
            "Authorization": "Bearer " + self._bearer,
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
            "X-Request-Commitment-SHA256": hashlib.sha256(encoded).hexdigest(),
        }
        try:
            response = self._transport.request(
                "POST",
                self._origin + path,
                headers=headers,
                content=encoded,
                timeout=self._timeout,
                follow_redirects=False,
            )
            status = response.status_code
            reader = getattr(response, "read_bounded", None)
            if not callable(reader):
                raise TypeError("unbounded response port")
            content = reader(_MAX_RESPONSE_BYTES)
            if type(content) is not bytes:
                raise TypeError("invalid bounded response")
        except Exception:
            raise Mem0V5HttpError("mem0_v5_http_remote_failed") from None
        if status != 200:
            raise Mem0V5HttpError("mem0_v5_http_remote_failed")
        if not 1 <= len(content) <= _MAX_RESPONSE_BYTES:
            raise Mem0V5HttpError("mem0_v5_http_response_invalid")
        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise Mem0V5HttpError("mem0_v5_http_response_invalid") from None
        if type(value) is not dict:
            raise Mem0V5HttpError("mem0_v5_http_response_invalid")
        return value


@final
@dataclass(frozen=True, slots=True)
class _BoundedHttpResponse:
    status_code: int
    content: bytes

    def read_bounded(self, maximum_bytes: int) -> bytes:
        if type(maximum_bytes) is not int or len(self.content) > maximum_bytes:
            raise ValueError("response exceeds bound")
        return self.content


@final
class _HttpxTransport:
    __slots__ = ()

    def request(self, method: str, url: str, **kwargs: object) -> object:
        transport = httpx.HTTPTransport(retries=0)
        with (
            httpx.Client(transport=transport, follow_redirects=False, trust_env=False) as client,
            client.stream(method, url, **kwargs) as response,
        ):
            content = bytearray()
            for chunk in response.iter_bytes():
                if len(content) + len(chunk) > _MAX_RESPONSE_BYTES:
                    raise Mem0V5HttpError("mem0_v5_http_response_invalid")
                content.extend(chunk)
            return _BoundedHttpResponse(response.status_code, bytes(content))


def _dict(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
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


def _origin(value: object) -> str:
    if type(value) is not str:
        _fail("mem0_v5_managed_http_configuration_invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        _fail("mem0_v5_managed_http_configuration_invalid")
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        _fail("mem0_v5_managed_http_configuration_invalid")
    return value.rstrip("/")


def _timeout(value: object) -> float:
    if type(value) not in (int, float) or isinstance(value, bool) or not 0.01 <= value <= 120:
        _fail("mem0_v5_managed_http_configuration_invalid")
    return float(value)


def _evidence_verifier(value: object) -> ManagedMem0V5EvidenceVerifierPort:
    _configuration_callable(value, "verify_storage")
    _configuration_callable(value, "verify_search")
    return value


def _dispatch_binding(value: object) -> ManagedMem0V5DispatchBindingV2Port:
    _configuration_callable(value, "verify_request_binding_v2")
    return value


def _cleanup_binding(value: object) -> ManagedMem0V5CleanupBindingPort:
    _configuration_callable(value, "cleanup_context")
    return value


def _dispatch_guard(
    value: object,
) -> ManagedMem0V5SingleDispatchGuardPort | None:
    if value is None:
        return None
    _configuration_callable(value, "claim")
    return value


def _transport_port(value: object) -> Mem0V5TransportPort:
    try:
        selected = _HttpxTransport() if value is None else value
    except Exception:
        raise Mem0V5HttpError("mem0_v5_http_configuration_invalid") from None
    _configuration_callable(selected, "request")
    return selected


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


def _key(kind: str, binding: str) -> str:
    return canonical_sha256({"kind": kind, "binding": binding})


def _text(value: object, maximum: int) -> bool:
    return type(value) is str and bool(value) and value == value.strip() and len(value) <= maximum


def _secret(value: object) -> bool:
    return type(value) is str and 32 <= len(value.encode()) <= 4_096


def _fail(code: str) -> None:
    if code in {
        "mem0_v5_managed_http_configuration_invalid",
        "mem0_v5_managed_storage_witness_authority_invalid",
    }:
        code = "mem0_v5_http_configuration_invalid"
    raise Mem0V5HttpError(code)


__all__ = (
    "HmacSha256ManagedMem0V5EvidenceVerifier",
    "ManagedMem0V5BearerCapability",
    "ManagedMem0V5CleanupBindingPort",
    "ManagedMem0V5DispatchBindingPort",
    "ManagedMem0V5DispatchBindingV2Port",
    "ManagedMem0V5EvidenceKeyCapability",
    "ManagedMem0V5EvidenceVerifierPort",
    "ManagedMem0V5HttpLane",
    "ManagedMem0V5SearchReceipt",
    "ManagedMem0V5SearchRecord",
    "ManagedMem0V5SingleDispatchGuardPort",
    "ManagedMem0V5SearchVerificationContext",
    "ManagedMem0V5StorageVerificationContext",
)

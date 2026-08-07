"""Typed authority and verifier for adapter-v5 extraction request bindings."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import threading
import weakref
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5HttpError

REQUEST_BINDING_SCHEMA = "mem0-oss-adapter-v5.request-binding.v1"
REQUEST_BINDING_DOMAIN = b"request-binding/v1"
REQUEST_BINDING_V2_SCHEMA = "mem0-oss-adapter-v5.request-binding.v2"
REQUEST_BINDING_V2_DOMAIN = b"request-binding/v2"
_V2_WITNESS_KEY = secrets.token_bytes(32)
_V2_WITNESS_TOKEN = object()
_V2_WITNESS_LOCK = threading.Lock()
_V2_WITNESS_STATES: dict[int, tuple[weakref.ReferenceType[object], str, bool]] = {}


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5RequestBindingContext:
    admission_commitment_sha256: str
    ingestion_manifest_sha256: str
    ingestion_root_sha256: str
    current_date_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    scope_sha256: str
    source_id: str
    source_sha256: str
    sequence: int

    @classmethod
    def from_authority(
        cls,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> ManagedMem0V5RequestBindingContext:
        if (
            type(authority) is not ManagedMem0V5ManifestAuthority
            or type(unit) is not ManagedMem0V5SourceUnit
            or type(admission) is not Mem0OssFullRunAdmission
            or unit.sequence >= len(authority.units)
            or authority.units[unit.sequence] != unit
            or admission.ingestion_manifest_sha256 != authority.ingestion_manifest_sha256
            or admission.ingestion_root_sha256 != authority.ingestion_root_sha256
        ):
            _fail("mem0_v5_managed_request_binding_authority_invalid")
        return cls(
            admission.commitment_sha256,
            authority.ingestion_manifest_sha256,
            authority.ingestion_root_sha256,
            canonical_sha256({"current_date": authority.current_date}),
            operation_id_sha256,
            unit.unit_identity_sha256,
            unit.unit_sha256,
            unit.scope_sha256,
            unit.source_id,
            unit.source_sha256,
            unit.sequence,
        )

    def __post_init__(self) -> None:
        digests = (
            self.admission_commitment_sha256,
            self.ingestion_manifest_sha256,
            self.ingestion_root_sha256,
            self.current_date_commitment_sha256,
            self.operation_id_sha256,
            self.unit_identity_sha256,
            self.unit_sha256,
            self.scope_sha256,
            self.source_sha256,
        )
        if (
            any(not is_sha256(value) for value in digests)
            or not _text(self.source_id)
            or type(self.sequence) is not int
            or not 0 <= self.sequence < 10_000
        ):
            _fail("mem0_v5_managed_request_binding_context_invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5RequestBindingReceipt:
    request_body_sha256: str
    response_format_sha256: str
    evidence_commitment_sha256: str

    def __post_init__(self) -> None:
        if not all(
            is_sha256(value)
            for value in (
                self.request_body_sha256,
                self.response_format_sha256,
                self.evidence_commitment_sha256,
            )
        ):
            _fail("mem0_v5_managed_request_binding_result_invalid")


class ManagedMem0V5DispatchBindingPort(Protocol):
    def verify_request_binding(
        self,
        *,
        payload: object,
        context: ManagedMem0V5RequestBindingContext,
    ) -> ManagedMem0V5RequestBindingReceipt: ...


def verify_request_binding_payload(
    *,
    payload: object,
    context: ManagedMem0V5RequestBindingContext,
    hmac_key: bytes,
) -> ManagedMem0V5RequestBindingReceipt:
    if type(context) is not ManagedMem0V5RequestBindingContext or type(hmac_key) is not bytes:
        _fail("mem0_v5_managed_request_binding_context_invalid")
    value = _dict(payload)
    signature_field = "request_binding_hmac_sha256"
    expected_fields = {
        "schema_version",
        "admission_commitment_sha256",
        "ingestion_manifest_sha256",
        "ingestion_root_sha256",
        "current_date_commitment_sha256",
        "operation_id_sha256",
        "unit_identity_sha256",
        "unit_sha256",
        "scope_sha256",
        "source_id",
        "source_sha256",
        "sequence",
        "request_body_sha256",
        "response_format_sha256",
        signature_field,
    }
    if set(value) != expected_fields:
        _fail("mem0_v5_managed_request_binding_evidence_invalid")
    unsigned = {key: item for key, item in value.items() if key != signature_field}
    signature = value[signature_field]
    if not is_sha256(signature) or not hmac.compare_digest(
        hmac.new(hmac_key, _canonical(unsigned), hashlib.sha256).hexdigest(), signature
    ):
        _fail("mem0_v5_managed_request_binding_unauthenticated")
    expected = {
        "schema_version": REQUEST_BINDING_SCHEMA,
        "admission_commitment_sha256": context.admission_commitment_sha256,
        "ingestion_manifest_sha256": context.ingestion_manifest_sha256,
        "ingestion_root_sha256": context.ingestion_root_sha256,
        "current_date_commitment_sha256": context.current_date_commitment_sha256,
        "operation_id_sha256": context.operation_id_sha256,
        "unit_identity_sha256": context.unit_identity_sha256,
        "unit_sha256": context.unit_sha256,
        "scope_sha256": context.scope_sha256,
        "source_id": context.source_id,
        "source_sha256": context.source_sha256,
        "sequence": context.sequence,
    }
    if any(value[key] != expected_value for key, expected_value in expected.items()) or not all(
        is_sha256(value[key]) for key in ("request_body_sha256", "response_format_sha256")
    ):
        _fail("mem0_v5_managed_request_binding_evidence_invalid")
    return ManagedMem0V5RequestBindingReceipt(
        value["request_body_sha256"],
        value["response_format_sha256"],
        canonical_sha256(unsigned),
    )


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5RequestBindingV2Context:
    """Exact source authority expected at the extraction HTTP boundary."""

    admission_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    corpus_id: str
    source_id: str
    source_sha256: str
    observation_date: str
    observation_date_commitment_sha256: str

    @classmethod
    def from_authority(
        cls,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        unit: ManagedMem0V5SourceUnit,
        operation_id_sha256: str,
        admission: Mem0OssFullRunAdmission,
    ) -> ManagedMem0V5RequestBindingV2Context:
        if (
            type(authority) is not ManagedMem0V5ManifestAuthority
            or type(unit) is not ManagedMem0V5SourceUnit
            or type(admission) is not Mem0OssFullRunAdmission
            or unit.sequence >= len(authority.units)
            or authority.units[unit.sequence] != unit
            or admission.ingestion_manifest_sha256 != authority.ingestion_manifest_sha256
            or admission.ingestion_root_sha256 != authority.ingestion_root_sha256
        ):
            _fail("mem0_v5_managed_request_binding_v2_authority_invalid")
        return cls(
            admission_commitment_sha256=admission.commitment_sha256,
            operation_id_sha256=operation_id_sha256,
            unit_identity_sha256=unit.unit_identity_sha256,
            unit_sha256=unit.unit_sha256,
            corpus_id=unit.corpus_id,
            source_id=unit.source_id,
            source_sha256=unit.source_sha256,
            observation_date=unit.observation_date,
            observation_date_commitment_sha256=canonical_sha256(
                {"observation_date": unit.observation_date}
            ),
        )

    def __post_init__(self) -> None:
        if (
            any(
                not is_sha256(value)
                for value in (
                    self.admission_commitment_sha256,
                    self.operation_id_sha256,
                    self.unit_identity_sha256,
                    self.unit_sha256,
                    self.source_sha256,
                    self.observation_date_commitment_sha256,
                )
            )
            or not _text(self.corpus_id)
            or not _text(self.source_id)
            or not _date(self.observation_date)
            or self.observation_date_commitment_sha256
            != canonical_sha256({"observation_date": self.observation_date})
        ):
            _fail("mem0_v5_managed_request_binding_v2_context_invalid")

    def evidence_payload(self) -> dict[str, object]:
        return {
            "schema_version": REQUEST_BINDING_V2_SCHEMA,
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "operation_id_sha256": self.operation_id_sha256,
            "unit_identity_sha256": self.unit_identity_sha256,
            "unit_sha256": self.unit_sha256,
            "corpus_id": self.corpus_id,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
            "observation_date": self.observation_date,
            "observation_date_commitment_sha256": self.observation_date_commitment_sha256,
        }


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5RequestBindingV2Receipt:
    admission_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    corpus_id: str
    source_id: str
    source_sha256: str
    observation_date: str
    observation_date_commitment_sha256: str
    request_body_sha256: str
    request_binding_evidence_sha256: str

    def __post_init__(self) -> None:
        context = ManagedMem0V5RequestBindingV2Context(
            self.admission_commitment_sha256,
            self.operation_id_sha256,
            self.unit_identity_sha256,
            self.unit_sha256,
            self.corpus_id,
            self.source_id,
            self.source_sha256,
            self.observation_date,
            self.observation_date_commitment_sha256,
        )
        if not is_sha256(self.request_body_sha256) or not is_sha256(
            self.request_binding_evidence_sha256
        ):
            _fail("mem0_v5_managed_request_binding_v2_result_invalid")
        expected = canonical_sha256(
            {**context.evidence_payload(), "request_body_sha256": self.request_body_sha256}
        )
        if self.request_binding_evidence_sha256 != expected:
            _fail("mem0_v5_managed_request_binding_v2_result_invalid")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": REQUEST_BINDING_V2_SCHEMA,
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "operation_id_sha256": self.operation_id_sha256,
            "unit_identity_sha256": self.unit_identity_sha256,
            "unit_sha256": self.unit_sha256,
            "corpus_id": self.corpus_id,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
            "observation_date": self.observation_date,
            "observation_date_commitment_sha256": self.observation_date_commitment_sha256,
            "request_body_sha256": self.request_body_sha256,
            "request_binding_evidence_sha256": self.request_binding_evidence_sha256,
        }


@final
class ManagedMem0V5AuthenticatedRequestBindingV2Witness:
    """Process-local proof that the v2 HMAC and exact context were verified."""

    __slots__ = ("_authentication_sha256", "_receipt", "__weakref__")

    def __init__(
        self,
        *,
        receipt: ManagedMem0V5RequestBindingV2Receipt,
        _token: object,
    ) -> None:
        if (
            _token is not _V2_WITNESS_TOKEN
            or type(receipt) is not ManagedMem0V5RequestBindingV2Receipt
        ):
            _fail("mem0_v5_managed_request_binding_v2_witness_invalid")
        receipt.__post_init__()
        self._receipt = receipt
        self._authentication_sha256 = _v2_witness_authentication(receipt)
        _register_v2_witness(self)

    @property
    def receipt(self) -> ManagedMem0V5RequestBindingV2Receipt:
        authenticate_managed_mem0_v5_request_binding_v2_witness(self)
        return self._receipt

    @property
    def request_body_sha256(self) -> str:
        return self.receipt.request_body_sha256

    @property
    def operation_id_sha256(self) -> str:
        return self.receipt.operation_id_sha256

    def __repr__(self) -> str:
        return "ManagedMem0V5AuthenticatedRequestBindingV2Witness(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("managed Mem0 v5 request-binding witnesses are nonserializable")


class ManagedMem0V5DispatchBindingV2Port(Protocol):
    def verify_request_binding_v2(
        self,
        *,
        payload: object,
        context: ManagedMem0V5RequestBindingV2Context,
    ) -> ManagedMem0V5AuthenticatedRequestBindingV2Witness: ...


def verify_request_binding_v2_payload(
    *,
    payload: object,
    context: ManagedMem0V5RequestBindingV2Context,
    hmac_key: bytes,
) -> ManagedMem0V5AuthenticatedRequestBindingV2Witness:
    """Authenticate an exact v2 observation without accepting v1 by ambiguity."""

    if (
        type(context) is not ManagedMem0V5RequestBindingV2Context
        or type(hmac_key) is not bytes
        or len(hmac_key) < 32
    ):
        _fail("mem0_v5_managed_request_binding_v2_context_invalid")
    value = _dict_v2(payload)
    signature_field = "request_binding_hmac_sha256"
    evidence_field = "request_binding_evidence_sha256"
    expected_fields = {
        *context.evidence_payload(),
        "request_body_sha256",
        evidence_field,
        signature_field,
    }
    if set(value) != expected_fields:
        _fail("mem0_v5_managed_request_binding_v2_evidence_invalid")
    unsigned = {key: item for key, item in value.items() if key != signature_field}
    evidence_payload = {key: item for key, item in unsigned.items() if key != evidence_field}
    signature = value[signature_field]
    if not is_sha256(signature) or not hmac.compare_digest(
        hmac.new(hmac_key, _canonical(unsigned), hashlib.sha256).hexdigest(), signature
    ):
        _fail("mem0_v5_managed_request_binding_v2_unauthenticated")
    if any(value[key] != item for key, item in context.evidence_payload().items()):
        _fail("mem0_v5_managed_request_binding_v2_evidence_invalid")
    request_body_sha256 = value["request_body_sha256"]
    evidence_sha256 = value[evidence_field]
    if (
        not is_sha256(request_body_sha256)
        or not is_sha256(evidence_sha256)
        or evidence_sha256 != canonical_sha256(evidence_payload)
    ):
        _fail("mem0_v5_managed_request_binding_v2_evidence_invalid")
    receipt = ManagedMem0V5RequestBindingV2Receipt(
        context.admission_commitment_sha256,
        context.operation_id_sha256,
        context.unit_identity_sha256,
        context.unit_sha256,
        context.corpus_id,
        context.source_id,
        context.source_sha256,
        context.observation_date,
        context.observation_date_commitment_sha256,
        request_body_sha256,
        evidence_sha256,
    )
    return ManagedMem0V5AuthenticatedRequestBindingV2Witness(
        receipt=receipt,
        _token=_V2_WITNESS_TOKEN,
    )


def authenticate_managed_mem0_v5_request_binding_v2_witness(
    value: object,
) -> ManagedMem0V5AuthenticatedRequestBindingV2Witness:
    if type(value) is not ManagedMem0V5AuthenticatedRequestBindingV2Witness:
        _fail("mem0_v5_managed_request_binding_v2_witness_unauthenticated")
    identity = id(value)
    fingerprint = _v2_witness_fingerprint(value)
    with _V2_WITNESS_LOCK:
        registered = _V2_WITNESS_STATES.get(identity)
        if (
            registered is None
            or registered[0]() is not value
            or not hmac.compare_digest(registered[1], fingerprint)
        ):
            _fail("mem0_v5_managed_request_binding_v2_witness_unauthenticated")
    value._receipt.__post_init__()
    return value


def claim_managed_mem0_v5_request_binding_v2_witnesses(
    values: tuple[ManagedMem0V5AuthenticatedRequestBindingV2Witness, ...],
) -> None:
    if type(values) is not tuple or not values:
        _fail("mem0_v5_managed_request_binding_v2_witness_unauthenticated")
    authenticated = tuple(
        authenticate_managed_mem0_v5_request_binding_v2_witness(item) for item in values
    )
    if len({id(item) for item in authenticated}) != len(authenticated):
        _fail("mem0_v5_managed_request_binding_v2_witness_replayed")
    with _V2_WITNESS_LOCK:
        states = tuple(_V2_WITNESS_STATES.get(id(item)) for item in authenticated)
        if any(state is None or state[2] for state in states):
            _fail("mem0_v5_managed_request_binding_v2_witness_replayed")
        for item, state in zip(authenticated, states, strict=True):
            assert state is not None
            _V2_WITNESS_STATES[id(item)] = (state[0], state[1], True)


def _register_v2_witness(value: ManagedMem0V5AuthenticatedRequestBindingV2Witness) -> None:
    identity = id(value)

    def remove(reference: weakref.ReferenceType[object]) -> None:
        with _V2_WITNESS_LOCK:
            current = _V2_WITNESS_STATES.get(identity)
            if current is not None and current[0] is reference:
                _V2_WITNESS_STATES.pop(identity, None)

    reference = weakref.ref(value, remove)
    with _V2_WITNESS_LOCK:
        _V2_WITNESS_STATES[identity] = (
            reference,
            _v2_witness_fingerprint(value),
            False,
        )


def _v2_witness_authentication(receipt: ManagedMem0V5RequestBindingV2Receipt) -> str:
    return hmac.new(
        _V2_WITNESS_KEY,
        canonical_sha256(receipt.payload()).encode(),
        hashlib.sha256,
    ).hexdigest()


def _v2_witness_fingerprint(value: ManagedMem0V5AuthenticatedRequestBindingV2Witness) -> str:
    return canonical_sha256(
        {
            "receipt": value._receipt.payload(),
            "authentication_sha256": value._authentication_sha256,
        }
    )


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def _dict(value: object) -> dict[str, object]:
    if type(value) is not dict:
        _fail("mem0_v5_managed_request_binding_evidence_invalid")
    return value


def _text(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip() and len(value) <= 512


def _date(value: object) -> bool:
    if type(value) is not str or len(value) != 10:
        return False
    try:
        return dt.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _dict_v2(value: object) -> dict[str, object]:
    if type(value) is not dict:
        _fail("mem0_v5_managed_request_binding_v2_evidence_invalid")
    return value


def _fail(code: str) -> None:
    raise Mem0V5HttpError(code)


__all__ = (
    "ManagedMem0V5AuthenticatedRequestBindingV2Witness",
    "ManagedMem0V5DispatchBindingPort",
    "ManagedMem0V5DispatchBindingV2Port",
    "ManagedMem0V5RequestBindingContext",
    "ManagedMem0V5RequestBindingReceipt",
    "ManagedMem0V5RequestBindingV2Context",
    "ManagedMem0V5RequestBindingV2Receipt",
    "REQUEST_BINDING_DOMAIN",
    "REQUEST_BINDING_SCHEMA",
    "REQUEST_BINDING_V2_DOMAIN",
    "REQUEST_BINDING_V2_SCHEMA",
    "verify_request_binding_payload",
    "verify_request_binding_v2_payload",
    "authenticate_managed_mem0_v5_request_binding_v2_witness",
    "claim_managed_mem0_v5_request_binding_v2_witnesses",
)

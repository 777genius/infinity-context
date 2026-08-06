"""Provider-neutral contracts for deterministic benchmark ingestion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol

IngestionRole = Literal["user", "assistant", "system"]

INGESTION_PAYLOAD_SCHEMA_VERSION = "provider-neutral-ingestion-payload.v1"
INGESTION_METADATA_SCHEMA_VERSION = "provider-neutral-ingestion-metadata.v1"
INGESTION_UNIT_SCHEMA_VERSION = "provider-neutral-ingestion-unit.v1"
INGESTION_AUDIT_SCHEMA_VERSION = "private-ingestion-source-audit.v1"
INGESTION_MANIFEST_SCHEMA_VERSION = "provider-neutral-ingestion-manifest.v1"

_ROLES = frozenset({"user", "assistant", "system"})
_FORBIDDEN_PROVIDER_FIELDS = frozenset(
    {
        "answer",
        "backend",
        "category",
        "evidence",
        "evaluator",
        "event_summary",
        "gold",
        "judge",
        "observation",
        "qa",
        "question",
        "route",
        "session_summary",
        "target",
    }
)


class IngestionManifestError(ValueError):
    """Raised when provider-neutral ingestion authority is ambiguous or mutated."""


@dataclass(frozen=True, slots=True)
class IngestionMessage:
    """One exact provider-visible message."""

    role: IngestionRole
    content: str

    def __post_init__(self) -> None:
        if type(self.role) is not str or self.role not in _ROLES:
            raise IngestionManifestError("ingestion message role is invalid")
        if type(self.content) is not str or not self.content:
            raise IngestionManifestError("ingestion message content must be non-empty exact text")

    def payload(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True)
class IngestionUnitMetadata:
    """Minimal provider/ranker-visible metadata for one source turn."""

    source_id: str
    timestamp: int

    def __post_init__(self) -> None:
        if not _is_opaque_source_id(self.source_id):
            raise IngestionManifestError("provider source_id must be an opaque unit SHA identity")
        if type(self.timestamp) is not int or self.timestamp < 0:
            raise IngestionManifestError("timestamp must be a non-negative integer")

    def payload(self) -> dict[str, object]:
        return {"source_id": self.source_id, "timestamp": self.timestamp}


@dataclass(frozen=True, slots=True)
class IngestionUnit:
    """Immutable provider-facing unit shared byte-for-byte by both targets."""

    ordinal: int
    corpus_id: str
    messages: tuple[IngestionMessage, ...]
    metadata: IngestionUnitMetadata
    payload_sha256: str
    metadata_sha256: str
    unit_input_sha256: str
    unit_sha256: str

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise IngestionManifestError("unit ordinal must be a non-negative integer")
        if not _is_opaque_corpus_id(self.corpus_id):
            raise IngestionManifestError("provider corpus_id must be an opaque corpus SHA identity")
        if type(self.messages) is not tuple or len(self.messages) != 1:
            raise IngestionManifestError("official dialogue unit must contain exactly one message")
        if any(type(message) is not IngestionMessage for message in self.messages):
            raise IngestionManifestError("unit messages contain a type impostor")
        if type(self.metadata) is not IngestionUnitMetadata:
            raise IngestionManifestError("unit metadata contains a type impostor")
        expected_payload = ingestion_payload_sha256(self.messages)
        expected_metadata = ingestion_metadata_sha256(self.metadata)
        expected_input = ingestion_unit_input_sha256(
            message=self.messages[0],
            timestamp=self.metadata.timestamp,
        )
        expected_unit = ingestion_unit_sha256(
            corpus_id=self.corpus_id,
            unit_id=self.metadata.source_id,
            unit_input_sha256=expected_input,
        )
        if self.payload_sha256 != expected_payload:
            raise IngestionManifestError("unit payload hash is invalid")
        if self.metadata_sha256 != expected_metadata:
            raise IngestionManifestError("unit metadata hash is invalid")
        if self.unit_input_sha256 != expected_input:
            raise IngestionManifestError("neutral unit input hash is invalid")
        if self.unit_sha256 != expected_unit:
            raise IngestionManifestError("unit commitment is invalid")

    def provider_payload(self) -> dict[str, object]:
        return {
            "corpus_id": self.corpus_id,
            "messages": [message.payload() for message in self.messages],
            "metadata": self.metadata.payload(),
        }

    def payload(self) -> dict[str, object]:
        """Compatibility spelling for the exact provider payload."""

        return self.provider_payload()


@dataclass(frozen=True, slots=True)
class IngestionUnitSourceAudit:
    """Private reversible source mapping, never passed to ingestion adapters."""

    ordinal: int
    unit_sha256: str
    sample_id: str
    session_id: str
    dia_id: str
    session_date: str
    speaker: str
    source_ref: str
    audit_sha256: str

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise IngestionManifestError("source audit ordinal is invalid")
        _require_sha256("unit_sha256", self.unit_sha256)
        for label, value in (
            ("sample_id", self.sample_id),
            ("session_id", self.session_id),
            ("dia_id", self.dia_id),
            ("session_date", self.session_date),
            ("speaker", self.speaker),
            ("source_ref", self.source_ref),
        ):
            if type(value) is not str or not value.strip():
                raise IngestionManifestError(f"{label} must be non-empty exact source text")
        expected = ingestion_source_audit_sha256(
            ordinal=self.ordinal,
            unit_sha256=self.unit_sha256,
            sample_id=self.sample_id,
            session_id=self.session_id,
            dia_id=self.dia_id,
            session_date=self.session_date,
            speaker=self.speaker,
            source_ref=self.source_ref,
        )
        if self.audit_sha256 != expected:
            raise IngestionManifestError("private source audit commitment is invalid")

    def private_payload(self) -> dict[str, object]:
        return {
            "dia_id": self.dia_id,
            "ordinal": self.ordinal,
            "sample_id": self.sample_id,
            "session_date": self.session_date,
            "session_id": self.session_id,
            "source_ref": self.source_ref,
            "speaker": self.speaker,
            "unit_sha256": self.unit_sha256,
        }


@dataclass(frozen=True, slots=True)
class IngestionUnitManifest:
    """Authority binding raw bytes, provider projection, and private source audit."""

    dataset_sha256: str
    profile_id: str
    ingestion_policy_id: str
    dataset_profile_commitment_sha256: str
    corpus_projection_sha256: str
    source_audit_sha256: str
    units: tuple[IngestionUnit, ...]
    source_audits: tuple[IngestionUnitSourceAudit, ...]
    manifest_sha256: str

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Recompute all public and private bindings at every authority boundary."""
        _require_sha256("dataset_sha256", self.dataset_sha256)
        if type(self.profile_id) is not str or not self.profile_id.strip():
            raise IngestionManifestError("profile_id must be non-empty")
        if type(self.ingestion_policy_id) is not str or not self.ingestion_policy_id.strip():
            raise IngestionManifestError("ingestion_policy_id must be non-empty")
        for label, value in (
            ("dataset_profile_commitment_sha256", self.dataset_profile_commitment_sha256),
            ("corpus_projection_sha256", self.corpus_projection_sha256),
            ("source_audit_sha256", self.source_audit_sha256),
        ):
            _require_sha256(label, value)
        if type(self.units) is not tuple or not self.units:
            raise IngestionManifestError("manifest units must be a non-empty exact tuple")
        if any(type(unit) is not IngestionUnit for unit in self.units):
            raise IngestionManifestError("manifest units contain a type impostor")
        if type(self.source_audits) is not tuple or any(
            type(audit) is not IngestionUnitSourceAudit for audit in self.source_audits
        ):
            raise IngestionManifestError("source audits contain a type impostor")
        if len(self.source_audits) != len(self.units):
            raise IngestionManifestError("source audit count differs from unit count")
        for index, (unit, audit) in enumerate(zip(self.units, self.source_audits, strict=True)):
            unit.validate()
            audit.validate()
            if unit.ordinal != index or audit.ordinal != index:
                raise IngestionManifestError("manifest units are reordered or missing")
            if audit.unit_sha256 != unit.unit_sha256:
                raise IngestionManifestError("source audit is bound to another unit")
        source_ids = tuple(unit.metadata.source_id for unit in self.units)
        if len(source_ids) != len(set(source_ids)):
            raise IngestionManifestError("manifest contains duplicate source units")
        for label, values in (
            ("unit commitment", tuple(unit.unit_sha256 for unit in self.units)),
            ("source ref", tuple(audit.source_ref for audit in self.source_audits)),
            ("source audit", tuple(audit.audit_sha256 for audit in self.source_audits)),
            (
                "sample/dia identity",
                tuple((audit.sample_id, audit.dia_id) for audit in self.source_audits),
            ),
        ):
            if len(values) != len(set(values)):
                raise IngestionManifestError(f"manifest contains duplicate {label}")

        expected_profile = dataset_profile_commitment_sha256(
            dataset_sha256=self.dataset_sha256,
            profile_id=self.profile_id,
        )
        expected_projection = ingestion_corpus_projection_sha256(
            self.units,
            ingestion_policy_id=self.ingestion_policy_id,
        )
        expected_audit = ingestion_source_audit_root_sha256(self.source_audits)
        if self.dataset_profile_commitment_sha256 != expected_profile:
            raise IngestionManifestError("dataset/profile commitment is invalid")
        if self.corpus_projection_sha256 != expected_projection:
            raise IngestionManifestError("corpus projection commitment is invalid")
        if self.source_audit_sha256 != expected_audit:
            raise IngestionManifestError("source audit root is invalid")
        expected_manifest = ingestion_manifest_sha256(
            dataset_sha256=self.dataset_sha256,
            profile_id=self.profile_id,
            ingestion_policy_id=self.ingestion_policy_id,
            dataset_profile_commitment_sha256=expected_profile,
            corpus_projection_sha256=expected_projection,
            source_audit_sha256=expected_audit,
            units=self.units,
            source_audits=self.source_audits,
        )
        if self.manifest_sha256 != expected_manifest:
            raise IngestionManifestError("manifest commitment is invalid")

    def public_payload(self) -> dict[str, object]:
        return {
            "corpus_projection_sha256": self.corpus_projection_sha256,
            "dataset_profile_commitment_sha256": self.dataset_profile_commitment_sha256,
            "dataset_sha256": self.dataset_sha256,
            "manifest_sha256": self.manifest_sha256,
            "ingestion_policy_id": self.ingestion_policy_id,
            "profile_id": self.profile_id,
            "schema_version": INGESTION_MANIFEST_SCHEMA_VERSION,
            "source_audit_sha256": self.source_audit_sha256,
            "unit_count": len(self.units),
            "unit_sha256s": [unit.unit_sha256 for unit in self.units],
        }


class IngestionUnitConsumerPort(Protocol):
    """Narrow common boundary implemented by each ingestion target adapter."""

    def consume(self, unit: IngestionUnit, *, run_id: str, manifest_sha256: str) -> None:
        """Consume exactly one public unit in manifest order."""


class IngestionPrivateAuditVerifierPort(Protocol):
    def verify(self, manifest: IngestionUnitManifest, authority: object, *, run_id: str) -> None:
        """Verify one run-scoped private audit authority without exposing its key."""


def dispatch_ingestion_manifest(
    manifest: IngestionUnitManifest,
    *,
    run_id: str,
    consumers: tuple[IngestionUnitConsumerPort, IngestionUnitConsumerPort],
) -> None:
    """Deliver only identical provider units through both target boundaries."""

    if type(manifest) is not IngestionUnitManifest:
        raise IngestionManifestError("manifest must have the exact contract type")
    if type(run_id) is not str or not run_id.strip():
        raise IngestionManifestError("run_id must be non-empty")
    manifest.validate()
    if type(consumers) is not tuple or len(consumers) != 2:
        raise IngestionManifestError("comparison ingestion requires exactly two consumers")
    if consumers[0] is consumers[1]:
        raise IngestionManifestError("comparison ingestion consumers must be distinct")
    for unit in manifest.units:
        for consumer in consumers:
            consumer.consume(unit, run_id=run_id, manifest_sha256=manifest.manifest_sha256)


def resolve_ingestion_source_audit(
    manifest: IngestionUnitManifest,
    unit: IngestionUnit,
    *,
    run_id: str,
    authority: object,
    verifier: IngestionPrivateAuditVerifierPort,
) -> IngestionUnitSourceAudit:
    """Resolve readable evidence provenance only after a typed unit was selected."""

    if type(manifest) is not IngestionUnitManifest or type(unit) is not IngestionUnit:
        raise IngestionManifestError("source resolution requires exact contract types")
    manifest.validate()
    verifier.verify(manifest, authority, run_id=run_id)
    if unit.ordinal >= len(manifest.units) or manifest.units[unit.ordinal] != unit:
        raise IngestionManifestError("selected unit does not belong to this manifest")
    audit = manifest.source_audits[unit.ordinal]
    audit.validate()
    if audit.unit_sha256 != unit.unit_sha256:
        raise IngestionManifestError("selected unit source audit binding is invalid")
    return audit


def opaque_ingestion_source_id(*, source_identity: dict[str, object]) -> str:
    return f"iu_{private_canonical_sha256(source_identity)}"


def opaque_ingestion_corpus_id(*, corpus_identity: dict[str, object]) -> str:
    return f"ic_{private_canonical_sha256(corpus_identity)}"


def make_ingestion_unit(
    *,
    ordinal: int,
    corpus_id: str,
    message: IngestionMessage,
    metadata: IngestionUnitMetadata,
) -> IngestionUnit:
    if type(message) is not IngestionMessage or type(metadata) is not IngestionUnitMetadata:
        raise IngestionManifestError("ingestion unit inputs must be exact contract types")
    messages = (message,)
    payload_sha256 = ingestion_payload_sha256(messages)
    metadata_sha256 = ingestion_metadata_sha256(metadata)
    unit_input_sha256 = ingestion_unit_input_sha256(
        message=message,
        timestamp=metadata.timestamp,
    )
    return IngestionUnit(
        ordinal=ordinal,
        corpus_id=corpus_id,
        messages=messages,
        metadata=metadata,
        payload_sha256=payload_sha256,
        metadata_sha256=metadata_sha256,
        unit_input_sha256=unit_input_sha256,
        unit_sha256=ingestion_unit_sha256(
            unit_id=metadata.source_id,
            corpus_id=corpus_id,
            unit_input_sha256=unit_input_sha256,
        ),
    )


def make_ingestion_source_audit(
    *,
    unit: IngestionUnit,
    sample_id: str,
    session_id: str,
    dia_id: str,
    session_date: str,
    speaker: str,
    source_ref: str,
) -> IngestionUnitSourceAudit:
    if type(unit) is not IngestionUnit:
        raise IngestionManifestError("source audit unit must be an exact contract type")
    values = {
        "ordinal": unit.ordinal,
        "unit_sha256": unit.unit_sha256,
        "sample_id": sample_id,
        "session_id": session_id,
        "dia_id": dia_id,
        "session_date": session_date,
        "speaker": speaker,
        "source_ref": source_ref,
    }
    return IngestionUnitSourceAudit(
        **values,
        audit_sha256=ingestion_source_audit_sha256(**values),
    )


def ingestion_payload_sha256(messages: tuple[IngestionMessage, ...]) -> str:
    if type(messages) is not tuple or any(
        type(message) is not IngestionMessage for message in messages
    ):
        raise IngestionManifestError("payload messages must be exact contract types")
    return provider_canonical_sha256(
        {
            "messages": [message.payload() for message in messages],
            "schema_version": INGESTION_PAYLOAD_SCHEMA_VERSION,
        }
    )


def ingestion_metadata_sha256(metadata: IngestionUnitMetadata) -> str:
    if type(metadata) is not IngestionUnitMetadata:
        raise IngestionManifestError("metadata must be an exact contract type")
    return provider_canonical_sha256(
        {**metadata.payload(), "schema_version": INGESTION_METADATA_SCHEMA_VERSION}
    )


def ingestion_unit_input_sha256(*, message: IngestionMessage, timestamp: int) -> str:
    if type(message) is not IngestionMessage or type(timestamp) is not int:
        raise IngestionManifestError("neutral unit input requires exact typed values")
    return provider_canonical_sha256(
        {
            "content": message.content,
            "role": message.role,
            "timestamp": timestamp,
        }
    )


def ingestion_unit_sha256(*, corpus_id: str, unit_id: str, unit_input_sha256: str) -> str:
    return provider_canonical_sha256(
        {
            "schema_version": INGESTION_UNIT_SCHEMA_VERSION,
            "unit_id": unit_id,
            "corpus_id": corpus_id,
            "unit_input_sha256": unit_input_sha256,
        }
    )


def ingestion_source_audit_sha256(**values: object) -> str:
    return private_canonical_sha256({**values, "schema_version": INGESTION_AUDIT_SCHEMA_VERSION})


def ingestion_corpus_projection_sha256(
    units: tuple[IngestionUnit, ...],
    *,
    ingestion_policy_id: str,
) -> str:
    if type(units) is not tuple or any(type(unit) is not IngestionUnit for unit in units):
        raise IngestionManifestError("projection units must be exact contract types")
    return provider_canonical_sha256(
        {
            "ingestion_policy_id": ingestion_policy_id,
            "unit_count": len(units),
            "units": [
                {
                    "unit_id": unit.metadata.source_id,
                    "unit_input_sha256": unit.unit_input_sha256,
                    "corpus_id": unit.corpus_id,
                }
                for unit in units
            ],
        }
    )


def ingestion_source_audit_root_sha256(
    audits: tuple[IngestionUnitSourceAudit, ...],
) -> str:
    if type(audits) is not tuple or any(
        type(audit) is not IngestionUnitSourceAudit for audit in audits
    ):
        raise IngestionManifestError("source audits must be exact contract types")
    return private_canonical_sha256(
        {
            "audit_sha256s": [audit.audit_sha256 for audit in audits],
            "schema_version": INGESTION_AUDIT_SCHEMA_VERSION,
            "unit_count": len(audits),
        }
    )


def dataset_profile_commitment_sha256(*, dataset_sha256: str, profile_id: str) -> str:
    _require_sha256("dataset_sha256", dataset_sha256)
    return provider_canonical_sha256(
        {
            "dataset_sha256": dataset_sha256,
            "profile_id": profile_id,
            "schema_version": INGESTION_MANIFEST_SCHEMA_VERSION,
        }
    )


def ingestion_manifest_sha256(
    *,
    dataset_sha256: str,
    profile_id: str,
    ingestion_policy_id: str,
    dataset_profile_commitment_sha256: str,
    corpus_projection_sha256: str,
    source_audit_sha256: str,
    units: tuple[IngestionUnit, ...],
    source_audits: tuple[IngestionUnitSourceAudit, ...],
) -> str:
    return private_canonical_sha256(
        {
            "corpus_projection_sha256": corpus_projection_sha256,
            "dataset_profile_commitment_sha256": dataset_profile_commitment_sha256,
            "dataset_sha256": dataset_sha256,
            "ingestion_policy_id": ingestion_policy_id,
            "profile_id": profile_id,
            "schema_version": INGESTION_MANIFEST_SCHEMA_VERSION,
            "source_audit_sha256": source_audit_sha256,
            "unit_count": len(units),
            "unit_sha256s": [unit.unit_sha256 for unit in units],
            "audit_sha256s": [audit.audit_sha256 for audit in source_audits],
        }
    )


def provider_canonical_json_bytes(value: object) -> bytes:
    _reject_forbidden_provider_fields(value)
    return private_canonical_json_bytes(value)


def provider_canonical_sha256(value: object) -> str:
    return hashlib.sha256(provider_canonical_json_bytes(value)).hexdigest()


def private_canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IngestionManifestError("ingestion commitment payload is not canonical JSON") from exc


def private_canonical_sha256(value: object) -> str:
    return hashlib.sha256(private_canonical_json_bytes(value)).hexdigest()


def _reject_forbidden_provider_fields(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if type(key) is not str:
                raise IngestionManifestError("commitment field names must be strings")
            normalized = key.casefold().replace("-", "_")
            if any(fragment in normalized for fragment in _FORBIDDEN_PROVIDER_FIELDS):
                raise IngestionManifestError(f"forbidden provider ingestion field: {key}")
            _reject_forbidden_provider_fields(nested)
    elif isinstance(value, list | tuple):
        for nested in value:
            _reject_forbidden_provider_fields(nested)


def _is_opaque_source_id(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith("iu_")
        and len(value) == 67
        and all(character in "0123456789abcdef" for character in value[3:])
    )


def _is_opaque_corpus_id(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith("ic_")
        and len(value) == 67
        and all(character in "0123456789abcdef" for character in value[3:])
    )


def _require_sha256(label: str, value: object) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise IngestionManifestError(f"{label} must be lowercase SHA-256")


__all__ = [
    "INGESTION_MANIFEST_SCHEMA_VERSION",
    "IngestionManifestError",
    "IngestionMessage",
    "IngestionRole",
    "IngestionPrivateAuditVerifierPort",
    "IngestionUnit",
    "IngestionUnitConsumerPort",
    "IngestionUnitManifest",
    "IngestionUnitMetadata",
    "IngestionUnitSourceAudit",
    "dataset_profile_commitment_sha256",
    "dispatch_ingestion_manifest",
    "ingestion_corpus_projection_sha256",
    "ingestion_manifest_sha256",
    "ingestion_source_audit_root_sha256",
    "make_ingestion_source_audit",
    "make_ingestion_unit",
    "opaque_ingestion_source_id",
    "private_canonical_json_bytes",
    "provider_canonical_json_bytes",
    "resolve_ingestion_source_audit",
    "opaque_ingestion_corpus_id",
]

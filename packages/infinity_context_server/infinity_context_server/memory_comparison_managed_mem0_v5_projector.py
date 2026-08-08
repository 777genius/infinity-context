"""Gold-blind managed corpus projection into the sealed Mem0 v5 manifest."""

from __future__ import annotations

import datetime as dt
import re
from contextlib import suppress
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_http_ingest_request import case_message_groups
from infinity_context_server.memory_comparison_locomo_cases import (
    OFFICIAL_MEM0_CONTENT_METADATA_KEY,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _reconstruct_managed_corpus_case,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    ManifestAuthorityResult,
    Mem0OssManifestUnit,
    canonical_sha256,
    is_sha256,
    manifest_root_sha256,
)

MANAGED_MEM0_V5_MANIFEST_SCHEMA_VERSION = "managed-mem0-v5-manifest.v1"
MEM0_V5_SEALED_INPUT_SCHEMA_VERSION = "mem0-oss-adapter-v5.sealed-input.v2"
_GOLD_FREE_PROJECTION_QUESTION = "Managed source projection sentinel."
_LONGMEMEVAL_SESSION_DATE = re.compile(
    r"(?P<date>\d{4}/\d{2}/\d{2}) "
    r"\((?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\) "
    r"(?P<hour>\d{2}):(?P<minute>\d{2})"
)
_ENGLISH_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5SourceMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"user", "assistant"} or not _content(self.content):
            raise ManagedRunError("managed Mem0 v5 source message is invalid")

    def payload(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5SourceUnit:
    sequence: int
    corpus_id: str
    source_id: str
    observation_date: str
    source_messages: tuple[ManagedMem0V5SourceMessage, ...]
    unit_identity_sha256: str
    unit_sha256: str
    source_sha256: str
    scope_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.sequence) is not int
            or self.sequence < 0
            or not _text(self.corpus_id)
            or not _text(self.source_id)
            or self.source_id == self.corpus_id
            or type(self.source_messages) is not tuple
            or not self.source_messages
            or any(type(item) is not ManagedMem0V5SourceMessage for item in self.source_messages)
            or any(
                not is_sha256(value)
                for value in (
                    self.unit_identity_sha256,
                    self.unit_sha256,
                    self.source_sha256,
                    self.scope_sha256,
                )
            )
        ):
            raise ManagedRunError("managed Mem0 v5 source unit is invalid")
        _date(self.observation_date)
        expected_unit = canonical_sha256(
            {"source_messages": [item.payload() for item in self.source_messages]}
        )
        expected_scope = canonical_sha256(
            {
                "corpus_id": self.corpus_id,
                "source_id": self.source_id,
                "source_sha256": self.source_sha256,
                "unit_sha256": expected_unit,
            }
        )
        expected_identity = canonical_sha256(
            {
                "sequence": self.sequence,
                "scope_sha256": expected_scope,
                "unit_sha256": expected_unit,
            }
        )
        if (
            self.unit_sha256 != expected_unit
            or self.scope_sha256 != expected_scope
            or self.unit_identity_sha256 != expected_identity
        ):
            raise ManagedRunError("managed Mem0 v5 source identity parity differs")

    def manifest_unit(self) -> Mem0OssManifestUnit:
        return Mem0OssManifestUnit(
            unit_identity_sha256=self.unit_identity_sha256,
            unit_sha256=self.unit_sha256,
            scope_sha256=self.scope_sha256,
        )

    def private_payload(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "unit_identity_sha256": self.unit_identity_sha256,
            "unit_sha256": self.unit_sha256,
            "source_sha256": self.source_sha256,
            "scope_sha256": self.scope_sha256,
            "corpus_id": self.corpus_id,
            "source_id": self.source_id,
            "observation_date": self.observation_date,
            "source_messages": [item.payload() for item in self.source_messages],
        }

    def public_payload(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "unit_identity_sha256": self.unit_identity_sha256,
            "unit_sha256": self.unit_sha256,
            "source_sha256": self.source_sha256,
            "scope_sha256": self.scope_sha256,
            "source_id_sha256": canonical_sha256({"source_id": self.source_id}),
        }


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5ManifestAuthority:
    current_date: str
    case_count: int
    corpus_count: int
    units: tuple[ManagedMem0V5SourceUnit, ...]
    ingestion_manifest_sha256: str
    ingestion_root_sha256: str
    sealed_payload_sha256: str
    authority_commitment_sha256: str
    schema_version: str = MANAGED_MEM0_V5_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_authority(self, allow_unsealed=False)

    @property
    def operation_count(self) -> int:
        return len(self.units)

    def manifest_units(self) -> tuple[Mem0OssManifestUnit, ...]:
        _validate_authority(self, allow_unsealed=False)
        return tuple(item.manifest_unit() for item in self.units)

    def private_payload(self) -> dict[str, object]:
        _validate_authority(self, allow_unsealed=False)
        unsigned = _unsigned_manifest_payload(self)
        return {**unsigned, "sealed_payload_sha256": self.sealed_payload_sha256}

    def public_payload(self) -> dict[str, object]:
        _validate_authority(self, allow_unsealed=False)
        return {
            "schema_version": self.schema_version,
            "case_count": self.case_count,
            "corpus_count": self.corpus_count,
            "operation_count": self.operation_count,
            "ingestion_manifest_sha256": self.ingestion_manifest_sha256,
            "ingestion_root_sha256": self.ingestion_root_sha256,
            "sealed_payload_sha256": self.sealed_payload_sha256,
            "authority_commitment_sha256": self.authority_commitment_sha256,
            "units": [item.public_payload() for item in self.units],
        }


@final
class ManagedMem0V5ManifestProjector:
    """Pure projector and exact manifest-authority verification port."""

    __slots__ = ()

    def project(
        self,
        cases: tuple[ManagedRunCase, ...],
        *,
        current_date: str,
    ) -> ManagedMem0V5ManifestAuthority:
        if (
            type(cases) is not tuple
            or not cases
            or any(type(item) is not ManagedRunCase for item in cases)
        ):
            raise ManagedRunError("managed Mem0 v5 cases are invalid")
        _date(current_date)
        representatives: dict[str, ManagedRunCase] = {}
        for case in cases:
            existing = representatives.get(case.corpus_id)
            if existing is None:
                representatives[case.corpus_id] = case
            elif existing.record != case.record:
                raise ManagedRunError("managed Mem0 v5 corpus records conflict")
        units: list[ManagedMem0V5SourceUnit] = []
        for corpus_id, representative in representatives.items():
            reconstructed = _reconstruct_managed_corpus_case(
                representative.record,
                case_id=representative.case_id,
                question=_GOLD_FREE_PROJECTION_QUESTION,
                temporal_context={},
            )
            if reconstructed.memory_scope_external_ref != corpus_id:
                raise ManagedRunError("managed Mem0 v5 corpus identity differs")
            for group_index, (messages, source_timestamp, metadata) in enumerate(
                case_message_groups(reconstructed)
            ):
                official_mem0_content: object = None
                official_mem0_speaker: object = None
                if reconstructed.benchmark == "locomo":
                    memory = reconstructed.memories[group_index]
                    official_mem0_content = memory.metadata.get(OFFICIAL_MEM0_CONTENT_METADATA_KEY)
                    if official_mem0_content is not None:
                        official_mem0_speaker = memory.metadata.get("speaker")
                units.append(
                    _source_unit_from_group(
                        sequence=len(units),
                        corpus_id=corpus_id,
                        messages=messages,
                        metadata=metadata,
                        current_date=current_date,
                        source_timestamp=source_timestamp,
                        timestamp_is_authoritative=reconstructed.benchmark == "longmemeval",
                        official_mem0_content=official_mem0_content,
                        official_mem0_speaker=official_mem0_speaker,
                    )
                )
        if not units:
            raise ManagedRunError("managed Mem0 v5 manifest has no extraction units")
        manifest_units = tuple(item.manifest_unit() for item in units)
        root = manifest_root_sha256(manifest_units)
        manifest = canonical_sha256({"current_date": current_date, "ingestion_root_sha256": root})
        unsigned = {
            "schema_version": MEM0_V5_SEALED_INPUT_SCHEMA_VERSION,
            "ingestion_manifest_sha256": manifest,
            "ingestion_root_sha256": root,
            "current_date": current_date,
            "units": [item.private_payload() for item in units],
        }
        sealed = canonical_sha256(unsigned)
        commitment = _authority_commitment(
            case_count=len(cases),
            corpus_count=len(representatives),
            operation_count=len(units),
            ingestion_manifest_sha256=manifest,
            ingestion_root_sha256=root,
            sealed_payload_sha256=sealed,
        )
        return ManagedMem0V5ManifestAuthority(
            current_date=current_date,
            case_count=len(cases),
            corpus_count=len(representatives),
            units=tuple(units),
            ingestion_manifest_sha256=manifest,
            ingestion_root_sha256=root,
            sealed_payload_sha256=sealed,
            authority_commitment_sha256=commitment,
        )

    def verify(self, *, payload: object) -> ManifestAuthorityResult:
        if type(payload) is not ManagedMem0V5ManifestAuthority:
            raise ManagedRunError("managed Mem0 v5 manifest authority type differs")
        _validate_authority(payload, allow_unsealed=False)
        return ManifestAuthorityResult(
            ingestion_manifest_sha256=payload.ingestion_manifest_sha256,
            ingestion_root_sha256=payload.ingestion_root_sha256,
            units=payload.manifest_units(),
        )


def _source_unit_from_group(
    *,
    sequence: int,
    corpus_id: str,
    messages: tuple[dict[str, str], ...],
    metadata: dict[str, object],
    current_date: str,
    source_timestamp: int | None,
    timestamp_is_authoritative: bool,
    official_mem0_content: object,
    official_mem0_speaker: object,
) -> ManagedMem0V5SourceUnit:
    source_id = metadata.get("source_id")
    source_sha256 = metadata.get("source_sha256")
    if not _text(source_id) or not is_sha256(source_sha256):
        raise ManagedRunError("managed Mem0 v5 canonical source identity is invalid")
    projected_messages = _official_mem0_messages(
        messages,
        content=official_mem0_content,
        speaker=official_mem0_speaker,
    )
    typed_messages = tuple(
        ManagedMem0V5SourceMessage(item.get("role", ""), item.get("content", ""))
        for item in projected_messages
    )
    unit_sha256 = canonical_sha256({"source_messages": [item.payload() for item in typed_messages]})
    scope_sha256 = canonical_sha256(
        {
            "corpus_id": corpus_id,
            "source_id": source_id,
            "source_sha256": source_sha256,
            "unit_sha256": unit_sha256,
        }
    )
    return ManagedMem0V5SourceUnit(
        sequence=sequence,
        corpus_id=corpus_id,
        source_id=source_id,
        observation_date=_source_date(
            metadata.get("session_date"),
            current_date,
            source_timestamp=source_timestamp,
            timestamp_is_authoritative=timestamp_is_authoritative,
        ),
        source_messages=typed_messages,
        unit_identity_sha256=canonical_sha256(
            {
                "sequence": sequence,
                "scope_sha256": scope_sha256,
                "unit_sha256": unit_sha256,
            }
        ),
        unit_sha256=unit_sha256,
        source_sha256=source_sha256,
        scope_sha256=scope_sha256,
    )


def _official_mem0_messages(
    messages: tuple[dict[str, str], ...],
    *,
    content: object,
    speaker: object,
) -> tuple[dict[str, str], ...]:
    if content is None and speaker is None:
        return messages
    if (
        type(content) is not str
        or not content.strip()
        or type(speaker) is not str
        or not speaker.strip()
        or len(messages) != 1
        or not content.startswith(f"{speaker}: ")
    ):
        raise ManagedRunError("managed Mem0 v5 official LoCoMo payload is invalid")
    return ({"role": messages[0].get("role", ""), "content": content},)


def _validate_authority(authority: ManagedMem0V5ManifestAuthority, *, allow_unsealed: bool) -> None:
    if (
        authority.schema_version != MANAGED_MEM0_V5_MANIFEST_SCHEMA_VERSION
        or type(authority.case_count) is not int
        or authority.case_count < 1
        or type(authority.corpus_count) is not int
        or not 1 <= authority.corpus_count <= authority.case_count
        or type(authority.units) is not tuple
        or not authority.units
        or any(type(item) is not ManagedMem0V5SourceUnit for item in authority.units)
        or tuple(item.sequence for item in authority.units) != tuple(range(len(authority.units)))
        or len({item.source_id for item in authority.units}) != len(authority.units)
        or len({item.scope_sha256 for item in authority.units}) != len(authority.units)
        or len({item.unit_identity_sha256 for item in authority.units}) != len(authority.units)
        or any(
            not is_sha256(value)
            for value in (
                authority.ingestion_manifest_sha256,
                authority.ingestion_root_sha256,
                authority.sealed_payload_sha256,
                authority.authority_commitment_sha256,
            )
        )
    ):
        raise ManagedRunError("managed Mem0 v5 manifest authority is invalid")
    _date(authority.current_date)
    for item in authority.units:
        item.__post_init__()
    root = manifest_root_sha256(tuple(item.manifest_unit() for item in authority.units))
    manifest = canonical_sha256(
        {"current_date": authority.current_date, "ingestion_root_sha256": root}
    )
    sealed = canonical_sha256(_unsigned_manifest_payload(authority))
    commitment = _authority_commitment(
        case_count=authority.case_count,
        corpus_count=authority.corpus_count,
        operation_count=authority.operation_count,
        ingestion_manifest_sha256=manifest,
        ingestion_root_sha256=root,
        sealed_payload_sha256=sealed,
    )
    if (
        authority.ingestion_root_sha256 != root
        or authority.ingestion_manifest_sha256 != manifest
        or (not allow_unsealed and authority.sealed_payload_sha256 != sealed)
        or authority.authority_commitment_sha256 != commitment
    ):
        raise ManagedRunError("managed Mem0 v5 manifest authority seal differs")


def _authority_commitment(
    *,
    case_count: int,
    corpus_count: int,
    operation_count: int,
    ingestion_manifest_sha256: str,
    ingestion_root_sha256: str,
    sealed_payload_sha256: str,
) -> str:
    return canonical_sha256(
        {
            "schema_version": MANAGED_MEM0_V5_MANIFEST_SCHEMA_VERSION,
            "case_count": case_count,
            "corpus_count": corpus_count,
            "operation_count": operation_count,
            "ingestion_manifest_sha256": ingestion_manifest_sha256,
            "ingestion_root_sha256": ingestion_root_sha256,
            "sealed_payload_sha256": sealed_payload_sha256,
        }
    )


def _unsigned_manifest_payload(authority: ManagedMem0V5ManifestAuthority) -> dict[str, object]:
    return {
        "schema_version": MEM0_V5_SEALED_INPUT_SCHEMA_VERSION,
        "ingestion_manifest_sha256": authority.ingestion_manifest_sha256,
        "ingestion_root_sha256": authority.ingestion_root_sha256,
        "current_date": authority.current_date,
        "units": [item.private_payload() for item in authority.units],
    }


def _source_date(
    value: object,
    fallback: str,
    *,
    source_timestamp: object,
    timestamp_is_authoritative: bool,
) -> str:
    timestamp_date = _utc_source_date(source_timestamp) if timestamp_is_authoritative else None
    if value is None:
        return timestamp_date or _date(fallback)
    if type(value) is not str or not value.strip():
        raise ManagedRunError("managed Mem0 v5 observation date is invalid")
    raw = value.strip()
    parsed_date: str | None = None
    with suppress(ValueError):
        parsed_date = dt.date.fromisoformat(raw).isoformat()
    if parsed_date is None:
        parsed_date = _official_longmemeval_date(raw)
    if parsed_date is None:
        for date_format in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
            try:
                parsed_date = dt.datetime.strptime(raw, date_format).date().isoformat()
                break
            except ValueError:
                continue
    if parsed_date is None:
        try:
            parsed_date = dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            raise ManagedRunError("managed Mem0 v5 observation date is invalid") from None
    if timestamp_date is not None and parsed_date != timestamp_date:
        raise ManagedRunError("managed Mem0 v5 observation date differs from source timestamp")
    return parsed_date


def _official_longmemeval_date(value: str) -> str | None:
    match = _LONGMEMEVAL_SESSION_DATE.fullmatch(value)
    if match is None:
        return None
    try:
        parsed = dt.datetime.strptime(
            f"{match.group('date')} {match.group('hour')}:{match.group('minute')}",
            "%Y/%m/%d %H:%M",
        )
    except ValueError:
        raise ManagedRunError("managed Mem0 v5 observation date is invalid") from None
    if match.group("weekday") != _ENGLISH_WEEKDAYS[parsed.weekday()]:
        raise ManagedRunError("managed Mem0 v5 observation date is invalid")
    return parsed.date().isoformat()


def _utc_source_date(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not int:
        raise ManagedRunError("managed Mem0 v5 source timestamp is invalid")
    try:
        instant = dt.datetime.fromtimestamp(value, tz=dt.UTC)
    except (OverflowError, OSError, ValueError):
        raise ManagedRunError("managed Mem0 v5 source timestamp is invalid") from None
    if not 1970 <= instant.year <= 2100:
        raise ManagedRunError("managed Mem0 v5 source timestamp is invalid")
    return instant.date().isoformat()


def _date(value: object) -> str:
    if type(value) is not str or len(value) != 10:
        raise ManagedRunError("managed Mem0 v5 observation date is invalid")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        raise ManagedRunError("managed Mem0 v5 observation date is invalid") from None
    if parsed.isoformat() != value:
        raise ManagedRunError("managed Mem0 v5 observation date is invalid")
    return value


def _text(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


def _content(value: object) -> bool:
    return type(value) is str and bool(value.strip())


__all__ = (
    "MANAGED_MEM0_V5_MANIFEST_SCHEMA_VERSION",
    "MEM0_V5_SEALED_INPUT_SCHEMA_VERSION",
    "ManagedMem0V5ManifestAuthority",
    "ManagedMem0V5ManifestProjector",
    "ManagedMem0V5SourceMessage",
    "ManagedMem0V5SourceUnit",
)

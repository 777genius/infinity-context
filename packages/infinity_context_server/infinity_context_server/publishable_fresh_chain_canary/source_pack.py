"""Gold-blind whole-corpus source authority for the fixed fresh-chain canary.

The established managed Mem0 projector deliberately emits one extraction unit
per official LoCoMo turn.  The fresh-chain canary is a single authenticated
extraction call, so this module first projects the complete canonical corpus,
then deterministically packs every projected source message into one synthetic
official-turn memory and runs that memory through the same projector again.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import final

from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
    OFFICIAL_MEM0_CONTENT_METADATA_KEY,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    MANAGED_CORPUS_PROJECTION_SCHEMA_VERSION,
    _managed_corpus_identity,
    _managed_corpus_record,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_projection import (
    MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256,
    ManagedMem0V5ExtractionProjectionError,
    PinnedMem0V5ExtractionRequestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    MANAGED_MEM0_V5_MANIFEST_SCHEMA_VERSION,
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5ManifestProjector,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

from .contracts import (
    FRESH_CHAIN_CASE_ID,
    FreshChainCanaryError,
    canonical_sha256,
)

FRESH_CHAIN_WHOLE_CORPUS_PACK_SCHEMA = "memory-comparison-fresh-chain-whole-corpus-pack.v1"
FRESH_CHAIN_WHOLE_CORPUS_PROJECTION_SCHEMA = (
    "memory-comparison-fresh-chain-whole-corpus-projection.v1"
)
FRESH_CHAIN_WHOLE_CORPUS_SPEAKER = "FreshChainCorpus"
FRESH_CHAIN_WHOLE_CORPUS_MAX_CONTENT_BYTES = 131_072

_PACK_POLICY_PAYLOAD: dict[str, object] = {
    "case_id": FRESH_CHAIN_CASE_ID,
    "canonical_json": {
        "ensure_ascii": True,
        "separators": [",", ":"],
        "sort_keys": True,
    },
    "extraction_request_projector_implementation_sha256": (
        MEM0_V5_EXTRACTION_IMPLEMENTATION_SHA256
    ),
    "full_source_manifest_schema": MANAGED_MEM0_V5_MANIFEST_SCHEMA_VERSION,
    "gold_material_policy": "exclude-question-answer-evidence-and-evaluator-material",
    "input_projection_schema": MANAGED_CORPUS_PROJECTION_SCHEMA_VERSION,
    "outer_message_role": "user",
    "outer_speaker": FRESH_CHAIN_WHOLE_CORPUS_SPEAKER,
    "output_operation_count": 1,
    "packed_content_max_utf8_bytes": FRESH_CHAIN_WHOLE_CORPUS_MAX_CONTENT_BYTES,
    "packed_content_schema": FRESH_CHAIN_WHOLE_CORPUS_PACK_SCHEMA,
    "source_coverage": "all-full-manifest-units-and-messages",
    "source_order": "manifest-unit-sequence-then-source-message-order",
    "synthetic_observation_date": "maximum-full-manifest-observation-date",
    "synthetic_timestamp": "maximum-canonical-source-timestamp",
}
FRESH_CHAIN_WHOLE_CORPUS_PACK_POLICY = MappingProxyType(_PACK_POLICY_PAYLOAD)
FRESH_CHAIN_WHOLE_CORPUS_PACK_POLICY_SHA256 = canonical_sha256(_PACK_POLICY_PAYLOAD)


@final
@dataclass(frozen=True, slots=True, repr=False)
class FreshChainWholeCorpusProjection:
    """Sealed full-source and exact one-unit extraction projection."""

    managed_case: ManagedRunCase = field(repr=False)
    full_source_manifest: ManagedMem0V5ManifestAuthority = field(repr=False)
    packed_manifest: ManagedMem0V5ManifestAuthority = field(repr=False)
    packing_policy_sha256: str
    packed_content_sha256: str
    extraction_request_body_sha256: str
    projection_commitment_sha256: str = field(init=False)
    schema_version: str = FRESH_CHAIN_WHOLE_CORPUS_PROJECTION_SCHEMA

    def __post_init__(self) -> None:
        try:
            _validate_projection(self)
            commitment = canonical_sha256(self.commitment_material())
        except FreshChainCanaryError:
            raise
        except (ManagedRunError, ManagedMem0V5ExtractionProjectionError, ValueError):
            _fail("fresh_chain_source_pack_invalid")
        object.__setattr__(self, "projection_commitment_sha256", commitment)

    @property
    def extraction_unit(self) -> ManagedMem0V5SourceUnit:
        """Return the sole unit authorized for the one-shot extraction seam."""

        return self.packed_manifest.units[0]

    @property
    def source_commitment_sha256(self) -> str:
        """Canonical source commitment to bind into the five-call ledger."""

        return self.projection_commitment_sha256

    def commitment_material(self) -> dict[str, object]:
        """Return public, content-free material committing the complete source."""

        return {
            "case_id": FRESH_CHAIN_CASE_ID,
            "current_date": self.full_source_manifest.current_date,
            "extraction_request_body_sha256": self.extraction_request_body_sha256,
            "full_source_manifest": self.full_source_manifest.public_payload(),
            "packed_content_sha256": self.packed_content_sha256,
            "packed_manifest": self.packed_manifest.public_payload(),
            "packing_policy_sha256": self.packing_policy_sha256,
            "schema_version": self.schema_version,
        }

    def public_payload(self) -> dict[str, object]:
        """Return durable, source-content-free evidence for operator review."""

        return {
            **self.commitment_material(),
            "projection_commitment_sha256": self.projection_commitment_sha256,
        }


def project_fresh_chain_whole_corpus(
    case: PublicBenchmarkCase,
    *,
    current_date: str,
) -> FreshChainWholeCorpusProjection:
    """Project all official ``conv-26`` turns into one extraction source unit."""

    _require_official_case(case)
    try:
        corpus_id, _ = _managed_corpus_identity(case)
        source_record = _managed_corpus_record(case)
        source_case = ManagedRunCase(
            case_id=FRESH_CHAIN_CASE_ID,
            corpus_id=corpus_id,
            record=source_record,
        )
        projector = ManagedMem0V5ManifestProjector()
        full_manifest = projector.project((source_case,), current_date=current_date)
        packed_content = _render_packed_content(full_manifest)
        packed_record = _packed_record(
            source_record,
            full_manifest=full_manifest,
            packed_content=packed_content,
        )
        packed_case = ManagedRunCase(
            case_id=FRESH_CHAIN_CASE_ID,
            corpus_id=corpus_id,
            record=packed_record,
        )
        packed_manifest = projector.project((packed_case,), current_date=current_date)
        if packed_manifest.operation_count != 1:
            _fail("fresh_chain_source_pack_operation_count_invalid")
        packed_source_content = packed_manifest.units[0].source_messages[0].content
        request_projection = PinnedMem0V5ExtractionRequestProjector().project(
            packed_manifest.units[0],
            current_date=current_date,
        )
        return FreshChainWholeCorpusProjection(
            managed_case=packed_case,
            full_source_manifest=full_manifest,
            packed_manifest=packed_manifest,
            packing_policy_sha256=FRESH_CHAIN_WHOLE_CORPUS_PACK_POLICY_SHA256,
            packed_content_sha256=_content_sha256(packed_source_content),
            extraction_request_body_sha256=request_projection.request_body_sha256,
        )
    except FreshChainCanaryError:
        raise
    except (ManagedRunError, ManagedMem0V5ExtractionProjectionError, ValueError):
        _fail("fresh_chain_source_pack_invalid")


def _require_official_case(case: object) -> None:
    if (
        type(case) is not PublicBenchmarkCase
        or case.benchmark != "locomo"
        or case.case_id != FRESH_CHAIN_CASE_ID
        or case.metadata.get("locomo_ingest_mode") != LOCOMO_INGEST_OFFICIAL_TURNS
        or type(case.memories) is not tuple
        or not case.memories
        or type(case.documents) is not tuple
        or case.documents
        or type(case.conversations) is not tuple
        or case.conversations
    ):
        _fail("fresh_chain_source_case_invalid")


def _render_packed_content(authority: ManagedMem0V5ManifestAuthority) -> str:
    if type(authority) is not ManagedMem0V5ManifestAuthority or not authority.units:
        _fail("fresh_chain_source_manifest_invalid")
    payload = {
        "full_source_authority_sha256": authority.authority_commitment_sha256,
        "packing_policy_sha256": FRESH_CHAIN_WHOLE_CORPUS_PACK_POLICY_SHA256,
        "schema_version": FRESH_CHAIN_WHOLE_CORPUS_PACK_SCHEMA,
        "units": [
            {
                "messages": [message.payload() for message in unit.source_messages],
                "observation_date": unit.observation_date,
            }
            for unit in authority.units
        ],
    }
    rendered = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    source_content = f"{FRESH_CHAIN_WHOLE_CORPUS_SPEAKER}: {rendered}"
    try:
        size = len(source_content.encode("utf-8"))
    except UnicodeEncodeError:
        _fail("fresh_chain_source_pack_invalid")
    if size > FRESH_CHAIN_WHOLE_CORPUS_MAX_CONTENT_BYTES:
        _fail("fresh_chain_source_pack_too_large")
    return source_content


def _packed_record(
    source_record: dict[str, object],
    *,
    full_manifest: ManagedMem0V5ManifestAuthority,
    packed_content: str,
) -> dict[str, object]:
    memories = source_record.get("memories")
    if type(memories) is not list or not memories:
        _fail("fresh_chain_source_manifest_invalid")
    timestamps: list[int] = []
    for item in memories:
        if type(item) is not dict or type(item.get("timestamp")) is not int:
            _fail("fresh_chain_source_manifest_invalid")
        timestamps.append(item["timestamp"])
    observation_date = max(unit.observation_date for unit in full_manifest.units)
    return {
        "schema_version": source_record.get("schema_version"),
        "benchmark": source_record.get("benchmark"),
        "corpus_id": source_record.get("corpus_id"),
        "thread_id": source_record.get("thread_id"),
        "memories": [
            {
                "kind": "fresh_chain_whole_corpus",
                OFFICIAL_MEM0_CONTENT_METADATA_KEY: packed_content,
                "role": "user",
                "session_alias": "session-0001",
                "source_alias": "memory-000001",
                "speaker": FRESH_CHAIN_WHOLE_CORPUS_SPEAKER,
                "session_date": observation_date,
                "text": packed_content.removeprefix(f"{FRESH_CHAIN_WHOLE_CORPUS_SPEAKER}: "),
                "timestamp": max(timestamps),
            }
        ],
        "documents": [],
        "conversations": [],
    }


def _validate_projection(value: FreshChainWholeCorpusProjection) -> None:
    if (
        type(value.managed_case) is not ManagedRunCase
        or value.managed_case.case_id != FRESH_CHAIN_CASE_ID
        or type(value.full_source_manifest) is not ManagedMem0V5ManifestAuthority
        or type(value.packed_manifest) is not ManagedMem0V5ManifestAuthority
        or value.schema_version != FRESH_CHAIN_WHOLE_CORPUS_PROJECTION_SCHEMA
        or value.packing_policy_sha256 != FRESH_CHAIN_WHOLE_CORPUS_PACK_POLICY_SHA256
        or value.full_source_manifest.current_date != value.packed_manifest.current_date
        or value.full_source_manifest.case_count != 1
        or value.full_source_manifest.corpus_count != 1
        or value.packed_manifest.case_count != 1
        or value.packed_manifest.corpus_count != 1
        or value.packed_manifest.operation_count != 1
        or value.packed_manifest.units[0].corpus_id != value.managed_case.corpus_id
        or value.full_source_manifest.units[0].corpus_id != value.managed_case.corpus_id
    ):
        _fail("fresh_chain_source_pack_invalid")
    ManagedMem0V5ManifestProjector().verify(payload=value.full_source_manifest)
    ManagedMem0V5ManifestProjector().verify(payload=value.packed_manifest)
    unit = value.packed_manifest.units[0]
    if len(unit.source_messages) != 1:
        _fail("fresh_chain_source_pack_invalid")
    content = unit.source_messages[0].content
    if (
        unit.source_messages[0].role != "user"
        or not content.startswith(f"{FRESH_CHAIN_WHOLE_CORPUS_SPEAKER}: ")
        or _content_sha256(content) != value.packed_content_sha256
    ):
        _fail("fresh_chain_source_pack_invalid")
    request = PinnedMem0V5ExtractionRequestProjector().project(
        unit,
        current_date=value.packed_manifest.current_date,
    )
    if request.request_body_sha256 != value.extraction_request_body_sha256:
        _fail("fresh_chain_source_pack_invalid")


def _content_sha256(value: str) -> str:
    try:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        _fail("fresh_chain_source_pack_invalid")


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = (
    "FRESH_CHAIN_WHOLE_CORPUS_MAX_CONTENT_BYTES",
    "FRESH_CHAIN_WHOLE_CORPUS_PACK_POLICY",
    "FRESH_CHAIN_WHOLE_CORPUS_PACK_POLICY_SHA256",
    "FRESH_CHAIN_WHOLE_CORPUS_PACK_SCHEMA",
    "FRESH_CHAIN_WHOLE_CORPUS_PROJECTION_SCHEMA",
    "FRESH_CHAIN_WHOLE_CORPUS_SPEAKER",
    "FreshChainWholeCorpusProjection",
    "project_fresh_chain_whole_corpus",
)

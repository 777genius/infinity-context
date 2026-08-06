"""Sealed official-LoCoMo projection into provider-neutral ingestion units."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from infinity_context_server.memory_comparison_case_loader import (
    parse_memory_comparison_dataset_bytes,
)
from infinity_context_server.memory_comparison_full_profiles import (
    LOCOMO_OFFICIAL_DATASET_SHA256,
    FullComparisonProfile,
    frozen_full_comparison_profile,
)
from infinity_context_server.memory_comparison_ingestion_contracts import (
    IngestionManifestError,
    IngestionMessage,
    IngestionUnit,
    IngestionUnitManifest,
    IngestionUnitMetadata,
    IngestionUnitSourceAudit,
    dataset_profile_commitment_sha256,
    ingestion_corpus_projection_sha256,
    ingestion_manifest_sha256,
    ingestion_source_audit_root_sha256,
    make_ingestion_source_audit,
    make_ingestion_unit,
    opaque_ingestion_corpus_id,
    opaque_ingestion_source_id,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
    _locomo_date_to_epoch,
)

OFFICIAL_LOCOMO_INGESTION_UNIT_COUNT = 5_882
OFFICIAL_LOCOMO_CORPUS_COUNT = 10
OFFICIAL_LOCOMO_SESSION_COUNT = 272
OFFICIAL_LOCOMO_INGESTION_POLICY_ID = "mem0-official-locomo-chunk-size-1.v1"


def build_official_locomo_ingestion_manifest(
    *,
    profile: FullComparisonProfile,
    dataset_bytes: bytes,
) -> IngestionUnitManifest:
    """Build the exact ordered ingestion authority from sealed dataset bytes."""

    trusted_profile = frozen_full_comparison_profile(profile)
    if trusted_profile.benchmark != "locomo":
        raise IngestionManifestError("ingestion manifest requires a LoCoMo profile")
    if trusted_profile.required_locomo_ingest_mode != LOCOMO_INGEST_OFFICIAL_TURNS:
        raise IngestionManifestError("profile does not require official LoCoMo turns")
    if trusted_profile.expected_corpus_count != OFFICIAL_LOCOMO_CORPUS_COUNT:
        raise IngestionManifestError("profile corpus count differs from sealed LoCoMo policy")
    if type(dataset_bytes) is not bytes:
        raise IngestionManifestError("dataset_bytes must be exact bytes")
    dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    if (
        dataset_sha256 != LOCOMO_OFFICIAL_DATASET_SHA256
        or dataset_sha256 != trusted_profile.expected_dataset_hash
    ):
        raise IngestionManifestError("dataset bytes differ from the sealed official LoCoMo source")

    raw = parse_memory_comparison_dataset_bytes(dataset_bytes)
    samples = _exact_samples(raw)
    units, source_audits, session_count = _project_units(samples)
    if len(units) != OFFICIAL_LOCOMO_INGESTION_UNIT_COUNT:
        raise IngestionManifestError("official LoCoMo ingestion unit count drifted")
    if session_count != OFFICIAL_LOCOMO_SESSION_COUNT:
        raise IngestionManifestError("official LoCoMo real session count drifted")
    profile_commitment = dataset_profile_commitment_sha256(
        dataset_sha256=dataset_sha256,
        profile_id=trusted_profile.profile_id,
    )
    if len({unit.corpus_id for unit in units}) != OFFICIAL_LOCOMO_CORPUS_COUNT:
        raise IngestionManifestError("official LoCoMo corpus identity count drifted")
    corpus_projection = ingestion_corpus_projection_sha256(
        units,
        ingestion_policy_id=OFFICIAL_LOCOMO_INGESTION_POLICY_ID,
    )
    source_audit_root = ingestion_source_audit_root_sha256(source_audits)
    return IngestionUnitManifest(
        dataset_sha256=dataset_sha256,
        profile_id=trusted_profile.profile_id,
        ingestion_policy_id=OFFICIAL_LOCOMO_INGESTION_POLICY_ID,
        dataset_profile_commitment_sha256=profile_commitment,
        corpus_projection_sha256=corpus_projection,
        source_audit_sha256=source_audit_root,
        units=units,
        source_audits=source_audits,
        manifest_sha256=ingestion_manifest_sha256(
            dataset_sha256=dataset_sha256,
            profile_id=trusted_profile.profile_id,
            ingestion_policy_id=OFFICIAL_LOCOMO_INGESTION_POLICY_ID,
            dataset_profile_commitment_sha256=profile_commitment,
            corpus_projection_sha256=corpus_projection,
            source_audit_sha256=source_audit_root,
            units=units,
            source_audits=source_audits,
        ),
    )


def verify_official_locomo_ingestion_manifest(
    manifest: IngestionUnitManifest,
    *,
    profile: FullComparisonProfile,
    dataset_bytes: bytes,
) -> None:
    """Fail closed unless rebuilding the sealed bytes yields an identical manifest."""

    if type(manifest) is not IngestionUnitManifest:
        raise IngestionManifestError("manifest must have the exact contract type")
    rebuilt = build_official_locomo_ingestion_manifest(
        profile=profile,
        dataset_bytes=dataset_bytes,
    )
    if manifest != rebuilt:
        raise IngestionManifestError("ingestion manifest differs from deterministic rebuild")


def _exact_samples(raw: object) -> tuple[Mapping[str, object], ...]:
    if type(raw) is not list or len(raw) != OFFICIAL_LOCOMO_CORPUS_COUNT:
        raise IngestionManifestError("official LoCoMo root must contain exactly ten samples")
    samples: list[Mapping[str, object]] = []
    sample_ids: set[str] = set()
    for sample in raw:
        if type(sample) is not dict:
            raise IngestionManifestError("official LoCoMo sample must be an exact object")
        sample_id = _required_text(sample, "sample_id")
        if sample_id in sample_ids:
            raise IngestionManifestError("official LoCoMo contains duplicate sample_id")
        sample_ids.add(sample_id)
        if type(sample.get("conversation")) is not dict:
            raise IngestionManifestError("official LoCoMo sample has no exact conversation")
        samples.append(sample)
    return tuple(samples)


def _project_units(
    samples: tuple[Mapping[str, object], ...],
) -> tuple[tuple[IngestionUnit, ...], tuple[IngestionUnitSourceAudit, ...], int]:
    units: list[IngestionUnit] = []
    source_audits: list[IngestionUnitSourceAudit] = []
    session_count = 0
    seen_dia_ids: set[tuple[str, str]] = set()
    seen_source_refs: set[str] = set()
    seen_unit_ids: set[str] = set()
    for sample in samples:
        sample_id = _required_text(sample, "sample_id")
        conversation = sample["conversation"]
        if type(conversation) is not dict:
            raise IngestionManifestError("conversation changed after validation")
        speaker_a = _required_text(conversation, "speaker_a")
        speaker_b = _required_text(conversation, "speaker_b")
        if speaker_a == speaker_b:
            raise IngestionManifestError("LoCoMo speakers must be distinct")
        session_keys = _chronological_sessions(conversation)
        if not session_keys:
            raise IngestionManifestError("LoCoMo conversation has no dialogue sessions")
        corpus_id = opaque_ingestion_corpus_id(
            corpus_identity={
                "ingestion_policy_id": OFFICIAL_LOCOMO_INGESTION_POLICY_ID,
                "sample_id": sample_id,
            }
        )
        for session_key in session_keys:
            session_count += 1
            turns = conversation[session_key]
            if type(turns) is not list or not turns:
                raise IngestionManifestError("LoCoMo session turns must be a non-empty exact list")
            date_value = conversation.get(f"{session_key}_date_time")
            if type(date_value) is not str or not date_value.strip():
                raise IngestionManifestError("LoCoMo session date is missing")
            timestamp = _locomo_date_to_epoch(date_value)
            if timestamp is None:
                raise IngestionManifestError("LoCoMo session date cannot be normalized")
            for turn in turns:
                if type(turn) is not dict:
                    raise IngestionManifestError("LoCoMo dialogue turn must be an exact object")
                speaker = _required_text(turn, "speaker")
                if speaker == speaker_a:
                    role = "user"
                elif speaker == speaker_b:
                    role = "assistant"
                else:
                    raise IngestionManifestError("LoCoMo turn has an undeclared speaker")
                dia_id = _required_text(turn, "dia_id")
                dia_identity = (sample_id, dia_id)
                if dia_identity in seen_dia_ids:
                    raise IngestionManifestError("LoCoMo contains a duplicate sample/dia identity")
                seen_dia_ids.add(dia_identity)
                content = _official_content(turn, speaker=speaker)
                source_id = opaque_ingestion_source_id(
                    source_identity={
                        "dia_id": dia_id,
                        "ingestion_policy_id": OFFICIAL_LOCOMO_INGESTION_POLICY_ID,
                        "sample_id": sample_id,
                        "session_id": session_key,
                    }
                )
                if source_id in seen_unit_ids:
                    raise IngestionManifestError("LoCoMo opaque unit identity collision")
                seen_unit_ids.add(source_id)
                unit = make_ingestion_unit(
                    ordinal=len(units),
                    corpus_id=corpus_id,
                    message=IngestionMessage(role=role, content=content),
                    metadata=IngestionUnitMetadata(
                        source_id=source_id,
                        timestamp=timestamp,
                    ),
                )
                units.append(unit)
                source_ref = f"locomo:{sample_id}:{session_key}:{dia_id}:turn"
                if source_ref in seen_source_refs:
                    raise IngestionManifestError("LoCoMo source reference collision")
                seen_source_refs.add(source_ref)
                source_audits.append(
                    make_ingestion_source_audit(
                        unit=unit,
                        sample_id=sample_id,
                        session_id=session_key,
                        dia_id=dia_id,
                        session_date=date_value,
                        speaker=speaker,
                        source_ref=source_ref,
                    )
                )
    return tuple(units), tuple(source_audits), session_count


def _chronological_sessions(conversation: Mapping[str, object]) -> tuple[str, ...]:
    dated: list[tuple[int, int, str]] = []
    for source_index, key in enumerate(conversation):
        if not _is_exact_session_key(key):
            continue
        turns = conversation[key]
        if type(turns) is not list:
            continue
        date_value = conversation.get(f"{key}_date_time")
        if type(date_value) is not str:
            raise IngestionManifestError("LoCoMo real session date is missing")
        timestamp = _locomo_date_to_epoch(date_value)
        if timestamp is None:
            raise IngestionManifestError("LoCoMo real session date is invalid")
        dated.append((timestamp, source_index, key))
    return tuple(key for _, _, key in sorted(dated))


def _official_content(turn: Mapping[str, object], *, speaker: str) -> str:
    text = turn.get("text")
    if type(text) is not str or not text:
        raise IngestionManifestError("LoCoMo turn text must be non-empty exact text")
    query = turn.get("query")
    caption = turn.get("blip_caption")
    if query is not None and type(query) is not str:
        raise IngestionManifestError("LoCoMo image query must be exact text or absent")
    if caption is not None and type(caption) is not str:
        raise IngestionManifestError("LoCoMo image caption must be exact text or absent")
    if query and caption:
        photo_tag = f"[Sharing image - query: {query}. The image shows: {caption}]"
    elif query:
        photo_tag = f"[Sharing image - query for: {query}]"
    elif caption:
        photo_tag = f"[Sharing image that shows: {caption}]"
    else:
        photo_tag = ""
    if photo_tag:
        text = f"{text} {photo_tag}" if text else photo_tag
    return f"{speaker}: {text}"


def _required_text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if type(item) is not str or not item.strip() or item != item.strip():
        raise IngestionManifestError(f"LoCoMo {key} must be exact non-empty text")
    return item


def _is_exact_session_key(value: object) -> bool:
    if type(value) is not str or not value.startswith("session_"):
        return False
    suffix = value.removeprefix("session_")
    return suffix.isdigit() and int(suffix) > 0 and str(int(suffix)) == suffix


__all__ = [
    "OFFICIAL_LOCOMO_CORPUS_COUNT",
    "OFFICIAL_LOCOMO_INGESTION_POLICY_ID",
    "OFFICIAL_LOCOMO_INGESTION_UNIT_COUNT",
    "OFFICIAL_LOCOMO_SESSION_COUNT",
    "build_official_locomo_ingestion_manifest",
    "verify_official_locomo_ingestion_manifest",
]

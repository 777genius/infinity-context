from __future__ import annotations

import json
import os
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_full_profiles import (
    LOCOMO_OFFICIAL_DATASET_SHA256,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_ingestion_audit_authority import (
    HmacIngestionPrivateAuditAuthority,
    IngestionPrivateAuditAuthority,
)
from infinity_context_server.memory_comparison_ingestion_contracts import (
    IngestionManifestError,
    IngestionMessage,
    IngestionUnit,
    IngestionUnitManifest,
    IngestionUnitMetadata,
    dispatch_ingestion_manifest,
    ingestion_corpus_projection_sha256,
    ingestion_manifest_sha256,
    ingestion_source_audit_root_sha256,
    make_ingestion_source_audit,
    make_ingestion_unit,
    opaque_ingestion_corpus_id,
    opaque_ingestion_source_id,
    provider_canonical_json_bytes,
    resolve_ingestion_source_audit,
)
from infinity_context_server.memory_comparison_locomo_ingestion_manifest import (
    OFFICIAL_LOCOMO_INGESTION_POLICY_ID,
    OFFICIAL_LOCOMO_INGESTION_UNIT_COUNT,
    OFFICIAL_LOCOMO_SESSION_COUNT,
    _exact_samples,
    _official_content,
    _project_units,
    build_official_locomo_ingestion_manifest,
    verify_official_locomo_ingestion_manifest,
)

EXPECTED_TOP_200_MANIFEST_SHA256 = (
    "a0aec503ca8289b9a3a398ceef22e3955b002a635c1e3f25a80a02ffb39b17bf"
)


@pytest.fixture(scope="module")
def official_dataset_bytes() -> bytes:
    configured = os.environ.get("MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET")
    path = Path(configured) if configured else Path("/tmp/locomo10.ingestion-manifest-r1.json")
    if not path.is_file():
        pytest.skip("sealed official LoCoMo dataset is not staged")
    return path.read_bytes()


@pytest.fixture(scope="module")
def official_manifest(official_dataset_bytes: bytes) -> IngestionUnitManifest:
    profile = resolve_full_comparison_profile("mem0-locomo-top200-v1")
    assert profile is not None
    return build_official_locomo_ingestion_manifest(
        profile=profile,
        dataset_bytes=official_dataset_bytes,
    )


def test_official_manifest_has_golden_count_root_and_dataset_commitment(
    official_manifest: IngestionUnitManifest,
) -> None:
    assert official_manifest.dataset_sha256 == LOCOMO_OFFICIAL_DATASET_SHA256
    assert len(official_manifest.units) == OFFICIAL_LOCOMO_INGESTION_UNIT_COUNT == 5_882
    assert official_manifest.manifest_sha256 == EXPECTED_TOP_200_MANIFEST_SHA256
    assert OFFICIAL_LOCOMO_SESSION_COUNT == 272
    assert len({unit.corpus_id for unit in official_manifest.units}) == 10
    assert len({unit.metadata.source_id for unit in official_manifest.units}) == 5_882
    assert len({unit.unit_sha256 for unit in official_manifest.units}) == 5_882
    assert len({audit.source_ref for audit in official_manifest.source_audits}) == 5_882


def test_official_manifest_rebuild_is_byte_identical_and_verifiable(
    official_dataset_bytes: bytes,
    official_manifest: IngestionUnitManifest,
) -> None:
    profile = resolve_full_comparison_profile("mem0-locomo-top200-v1")
    assert profile is not None
    rebuilt = build_official_locomo_ingestion_manifest(
        profile=profile,
        dataset_bytes=bytes(official_dataset_bytes),
    )
    assert rebuilt == official_manifest
    assert _manifest_bytes(rebuilt) == _manifest_bytes(official_manifest)
    verify_official_locomo_ingestion_manifest(
        rebuilt,
        profile=profile,
        dataset_bytes=official_dataset_bytes,
    )


def test_official_units_keep_raw_content_and_metadata_separate(
    official_dataset_bytes: bytes,
    official_manifest: IngestionUnitManifest,
) -> None:
    expected = _raw_turns(official_dataset_bytes)
    actual = tuple(
        (
            unit.messages[0].role,
            unit.messages[0].content,
            audit.session_id,
            audit.dia_id,
        )
        for unit, audit in zip(
            official_manifest.units,
            official_manifest.source_audits,
            strict=True,
        )
    )
    assert actual == expected
    for unit, audit in zip(
        official_manifest.units,
        official_manifest.source_audits,
        strict=True,
    ):
        content = unit.messages[0].content
        assert unit.metadata.source_id.startswith("iu_")
        assert unit.corpus_id.startswith("ic_")
        assert audit.session_id not in content
        assert audit.dia_id not in content
        assert audit.session_date not in content


def test_official_image_and_whitespace_semantics_match_pinned_source(
    official_dataset_bytes: bytes,
    official_manifest: IngestionUnitManifest,
) -> None:
    expected = _raw_turns(official_dataset_bytes)
    contents = tuple(unit.messages[0].content for unit in official_manifest.units)
    raw_texts = _raw_texts(official_dataset_bytes)
    both = sum(1 for content in contents if "[Sharing image - query:" in content)
    caption_only = sum(1 for content in contents if "[Sharing image that shows:" in content)
    query_only = sum(1 for content in contents if "[Sharing image - query for:" in content)
    whitespace_sensitive = sum(text != text.strip() for text in raw_texts)
    newline_bearing = sum("\n" in text for text in raw_texts)
    assert both == 888
    assert caption_only == 338
    assert query_only == 0
    assert both + caption_only + query_only == 1_226
    assert whitespace_sensitive == 209
    assert newline_bearing == 37
    assert tuple(item[1] for item in expected) == contents


def test_official_manifest_contains_no_qa_gold_evidence_or_routing_fields(
    official_manifest: IngestionUnitManifest,
) -> None:
    forbidden = {
        "answer",
        "backend",
        "evidence",
        "evaluator",
        "gold",
        "judge",
        "qa",
        "question",
        "route",
        "target",
        "category",
        "event_summary",
        "observation",
        "session_summary",
    }
    payload = {
        "manifest": official_manifest.public_payload(),
        "units": [unit.provider_payload() for unit in official_manifest.units],
    }
    keys = {key.casefold() for key in _all_keys(payload)}
    assert keys.isdisjoint(forbidden)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "session_1" not in serialized
    assert "D1:1" not in serialized
    assert "conv-26" not in serialized


def test_private_source_evidence_resolves_only_after_selection(
    official_manifest: IngestionUnitManifest,
) -> None:
    selected = official_manifest.units[0]
    provider_json = json.dumps(selected.provider_payload(), ensure_ascii=False)
    authority_port = HmacIngestionPrivateAuditAuthority(b"a" * 32)
    authority = authority_port.sign(official_manifest, run_id="run-1")
    audit = resolve_ingestion_source_audit(
        official_manifest,
        selected,
        run_id="run-1",
        authority=authority,
        verifier=authority_port,
    )
    assert audit.source_ref == "locomo:conv-26:session_1:D1:1:turn"
    assert audit.session_id == "session_1"
    assert audit.dia_id == "D1:1"
    assert audit.source_ref not in provider_json
    assert audit.session_id not in provider_json
    assert audit.dia_id not in provider_json


def test_qa_and_summary_only_mutation_leaves_corpus_projection_identical(
    official_dataset_bytes: bytes,
    official_manifest: IngestionUnitManifest,
) -> None:
    raw = json.loads(official_dataset_bytes)
    scored_qas = sum(qa.get("category") in {1, 2, 3, 4} for sample in raw for qa in sample["qa"])
    turns = [
        turn
        for sample in raw
        for key, value in sample["conversation"].items()
        if key.startswith("session_") and key.removeprefix("session_").isdigit()
        for turn in value
    ]
    assert scored_qas == 1_540
    assert sum("img_url" in turn for turn in turns) == 910
    assert sum("re-download" in turn for turn in turns) == 206
    for turn in turns:
        if "img_url" in turn:
            turn["img_url"] = ["ignored://mutated"]
        if "re-download" in turn:
            turn["re-download"] = not turn["re-download"]
    raw[0]["qa"][0]["question"] = "mutated evaluator question"
    raw[0]["qa"][0]["answer"] = "mutated evaluator answer"
    raw[0]["qa"][0]["evidence"] = ["D999:999"]
    raw[0]["qa"][0]["category"] = 999
    raw[0]["observation"] = {"forbidden": "mutated"}
    raw[0]["session_summary"] = {"forbidden": "mutated"}
    raw[0]["event_summary"] = {"forbidden": "mutated"}
    assert raw != json.loads(official_dataset_bytes)
    units, audits, sessions = _project_units(_exact_samples(raw))
    assert sessions == OFFICIAL_LOCOMO_SESSION_COUNT
    assert units == official_manifest.units
    assert audits == official_manifest.source_audits
    assert (
        ingestion_corpus_projection_sha256(
            units,
            ingestion_policy_id=OFFICIAL_LOCOMO_INGESTION_POLICY_ID,
        )
        == official_manifest.corpus_projection_sha256
    )


def test_admitted_content_timestamp_and_role_mutations_change_projection(
    official_dataset_bytes: bytes,
    official_manifest: IngestionUnitManifest,
) -> None:
    for field, value in (
        ("text", "mutated semantic content"),
        ("speaker", "Melanie"),
    ):
        raw = json.loads(official_dataset_bytes)
        raw[0]["conversation"]["session_1"][0][field] = value
        units, _, _ = _project_units(_exact_samples(raw))
        assert units[0].unit_input_sha256 != official_manifest.units[0].unit_input_sha256
        assert (
            ingestion_corpus_projection_sha256(
                units,
                ingestion_policy_id=OFFICIAL_LOCOMO_INGESTION_POLICY_ID,
            )
            != official_manifest.corpus_projection_sha256
        )

    raw = json.loads(official_dataset_bytes)
    raw[0]["conversation"]["session_1_date_time"] = "9:00 AM on 8 May, 2023"
    units, _, _ = _project_units(_exact_samples(raw))
    assert units[0].unit_input_sha256 != official_manifest.units[0].unit_input_sha256


def test_raw_projection_rejects_unknown_speaker_duplicate_dia_and_invalid_date(
    official_dataset_bytes: bytes,
) -> None:
    mutations = (
        lambda conversation: conversation["session_1"][0].update(speaker="third speaker"),
        lambda conversation: conversation["session_2"][0].update(
            dia_id=conversation["session_1"][0]["dia_id"]
        ),
        lambda conversation: conversation.update(session_1_date_time="not an official date"),
    )
    for mutate in mutations:
        sample = json.loads(official_dataset_bytes)[0]

        mutate(sample["conversation"])
        with pytest.raises(IngestionManifestError):
            _project_units((sample,))


def test_query_only_renderer_and_orphan_dates_match_official_policy(
    official_dataset_bytes: bytes,
) -> None:
    turn = {
        "speaker": "A",
        "query": "exact query",
        "text": "exact text ",
    }
    assert (
        _official_content(turn, speaker="A")
        == "A: exact text  [Sharing image - query for: exact query]"
    )
    raw = json.loads(official_dataset_bytes)
    orphan_dates = 0
    for sample in raw:
        conversation = sample["conversation"]
        for key in conversation:
            if key.startswith("session_") and key.endswith("_date_time"):
                session_key = key.removesuffix("_date_time")
                if type(conversation.get(session_key)) is not list:
                    orphan_dates += 1
    assert orphan_dates == 16


def test_provider_commitment_rejects_forbidden_canary_fields() -> None:
    for key in ("category", "question", "evidence", "session_summary"):
        with pytest.raises(IngestionManifestError, match="forbidden provider"):
            provider_canonical_json_bytes({key: "canary"})


def test_two_consumers_receive_same_typed_units_in_same_order(
    official_manifest: IngestionUnitManifest,
) -> None:
    left = _RecordingConsumer()
    right = _RecordingConsumer()
    dispatch_ingestion_manifest(
        official_manifest,
        run_id="sealed-run",
        consumers=(left, right),
    )
    assert left.units == right.units == official_manifest.units
    assert all(a is b for a, b in zip(left.units, right.units, strict=True))
    assert (
        left.bindings
        == right.bindings
        == (("sealed-run", official_manifest.manifest_sha256),) * len(official_manifest.units)
    )


def test_contracts_are_frozen_and_reject_type_impostors() -> None:
    unit = _unit(ordinal=0, source_id="source-1")
    with pytest.raises(FrozenInstanceError):
        unit.ordinal = 2  # type: ignore[misc]

    class FakeUnit(IngestionUnit):
        pass

    fake = FakeUnit(
        ordinal=unit.ordinal,
        corpus_id=unit.corpus_id,
        messages=unit.messages,
        metadata=unit.metadata,
        payload_sha256=unit.payload_sha256,
        metadata_sha256=unit.metadata_sha256,
        unit_input_sha256=unit.unit_input_sha256,
        unit_sha256=unit.unit_sha256,
    )
    with pytest.raises(IngestionManifestError, match="exact contract type"):
        _manifest((fake,))


@pytest.mark.parametrize("mutation", ["reorder", "loss", "duplicate", "payload"])
def test_manifest_fails_closed_on_structural_mutation(mutation: str) -> None:
    first = _unit(ordinal=0, source_id="source-1")
    second = _unit(ordinal=1, source_id="source-2")
    original = _manifest((first, second))

    if mutation == "reorder":
        changed = (second, first)
    elif mutation == "loss":
        changed = (first,)
    elif mutation == "duplicate":
        duplicate = make_ingestion_unit(
            ordinal=1,
            corpus_id=first.corpus_id,
            message=first.messages[0],
            metadata=first.metadata,
        )
        changed = (first, duplicate)
    else:
        mutated = object.__new__(IngestionUnit)
        for field in (
            "ordinal",
            "corpus_id",
            "messages",
            "metadata",
            "payload_sha256",
            "metadata_sha256",
            "unit_input_sha256",
            "unit_sha256",
        ):
            object.__setattr__(mutated, field, getattr(first, field))
        object.__setattr__(
            mutated,
            "messages",
            (IngestionMessage(role="user", content="mutated"),),
        )
        changed = (mutated, second)

    with pytest.raises(IngestionManifestError):
        replace(original, units=changed)


def test_dataset_mutation_is_rejected_before_projection(
    official_dataset_bytes: bytes,
) -> None:
    profile = resolve_full_comparison_profile("mem0-locomo-top200-v1")
    assert profile is not None
    mutated = official_dataset_bytes.replace(b"Hey Mel!", b"Hey Max!", 1)
    assert mutated != official_dataset_bytes
    with pytest.raises(IngestionManifestError, match="sealed official LoCoMo"):
        build_official_locomo_ingestion_manifest(
            profile=profile,
            dataset_bytes=mutated,
        )


def test_duplicate_sample_dia_identity_fails_all_authority_boundaries() -> None:
    first = _unit(ordinal=0, source_id="source-1")
    second = _unit(ordinal=1, source_id="source-2")
    manifest = _manifest((first, second))
    authority_port = HmacIngestionPrivateAuditAuthority(b"d" * 32)
    authority = authority_port.sign(manifest, run_id="run-1")
    first_audit, second_audit = manifest.source_audits
    duplicate_identity_audit = make_ingestion_source_audit(
        unit=second,
        sample_id=first_audit.sample_id,
        session_id=second_audit.session_id,
        dia_id=first_audit.dia_id,
        session_date=second_audit.session_date,
        speaker=second_audit.speaker,
        source_ref=second_audit.source_ref,
    )
    audits = (first_audit, duplicate_identity_audit)
    assert first.unit_sha256 != second.unit_sha256
    assert first_audit.source_ref != duplicate_identity_audit.source_ref
    assert first_audit.audit_sha256 != duplicate_identity_audit.audit_sha256
    assert (first_audit.sample_id, first_audit.dia_id) == (
        duplicate_identity_audit.sample_id,
        duplicate_identity_audit.dia_id,
    )
    audit_root = ingestion_source_audit_root_sha256(audits)
    manifest_root = ingestion_manifest_sha256(
        dataset_sha256=manifest.dataset_sha256,
        profile_id=manifest.profile_id,
        ingestion_policy_id=manifest.ingestion_policy_id,
        dataset_profile_commitment_sha256=manifest.dataset_profile_commitment_sha256,
        corpus_projection_sha256=manifest.corpus_projection_sha256,
        source_audit_sha256=audit_root,
        units=manifest.units,
        source_audits=audits,
    )

    with pytest.raises(
        IngestionManifestError,
        match="duplicate sample/dia identity",
    ):
        IngestionUnitManifest(
            dataset_sha256=manifest.dataset_sha256,
            profile_id=manifest.profile_id,
            ingestion_policy_id=manifest.ingestion_policy_id,
            dataset_profile_commitment_sha256=manifest.dataset_profile_commitment_sha256,
            corpus_projection_sha256=manifest.corpus_projection_sha256,
            source_audit_sha256=audit_root,
            units=manifest.units,
            source_audits=audits,
            manifest_sha256=manifest_root,
        )

    object.__setattr__(manifest, "source_audits", audits)
    object.__setattr__(manifest, "source_audit_sha256", audit_root)
    object.__setattr__(manifest, "manifest_sha256", manifest_root)
    with pytest.raises(IngestionManifestError, match="duplicate sample/dia identity"):
        manifest.validate()
    with pytest.raises(IngestionManifestError, match="duplicate sample/dia identity"):
        authority_port.sign(manifest, run_id="run-1")
    with pytest.raises(IngestionManifestError, match="duplicate sample/dia identity"):
        authority_port.verify(
            manifest,
            authority,
            run_id="run-1",
        )


def test_run_scoped_private_audit_authority_is_secret_free_and_run_bound() -> None:
    secret = b"private-audit-test-key-material-32"
    manifest = _manifest((_unit(ordinal=0, source_id="source-1"),))
    authority_port = HmacIngestionPrivateAuditAuthority(secret)
    authority = authority_port.sign(manifest, run_id="run-1")
    assert type(authority) is IngestionPrivateAuditAuthority
    authority_port.verify(
        manifest,
        authority,
        run_id="run-1",
    )
    artifact_json = json.dumps(authority.receipt_payload(), sort_keys=True)
    provider_json = json.dumps(manifest.units[0].provider_payload(), sort_keys=True)
    assert secret.decode() not in artifact_json
    assert secret.decode() not in provider_json
    with pytest.raises(IngestionManifestError, match="verification failed"):
        authority_port.verify(
            manifest,
            authority,
            run_id="run-2",
        )


def test_dispatch_revalidates_post_construction_regroup_tamper() -> None:
    manifest = _manifest((_unit(ordinal=0, source_id="source-1"),))
    object.__setattr__(
        manifest.units[0],
        "corpus_id",
        opaque_ingestion_corpus_id(corpus_identity={"test_corpus": "regrouped"}),
    )
    left = _RecordingConsumer()
    right = _RecordingConsumer()
    with pytest.raises(IngestionManifestError, match="unit commitment"):
        dispatch_ingestion_manifest(
            manifest,
            run_id="run-1",
            consumers=(left, right),
        )
    assert left.units == right.units == ()


def test_forged_private_audit_and_authority_tamper_fail_hmac_verification() -> None:
    manifest = _manifest((_unit(ordinal=0, source_id="source-1"),))
    authority_port = HmacIngestionPrivateAuditAuthority(b"b" * 32)
    authority = authority_port.sign(manifest, run_id="run-1")
    forged = _forged_private_audit_manifest(manifest)
    with pytest.raises(IngestionManifestError, match="verification failed"):
        authority_port.verify(
            forged,
            authority,
            run_id="run-1",
        )
    object.__setattr__(
        authority,
        "authority_hmac_sha256",
        "a" * 64,
    )
    with pytest.raises(IngestionManifestError, match="verification failed"):
        authority_port.verify(
            manifest,
            authority,
            run_id="run-1",
        )


def test_replace_regroup_changes_unit_commitment_and_invalidates_manifest() -> None:
    first = _unit(ordinal=0, source_id="source-1")
    second = _unit(ordinal=1, source_id="source-2")
    manifest = _manifest((first, second))
    regrouped = make_ingestion_unit(
        ordinal=second.ordinal,
        corpus_id=opaque_ingestion_corpus_id(corpus_identity={"test_corpus": "other"}),
        message=second.messages[0],
        metadata=second.metadata,
    )
    assert regrouped.unit_sha256 != second.unit_sha256
    with pytest.raises(IngestionManifestError):
        replace(
            manifest,
            units=(first, regrouped),
        )


def test_audit_resolution_revalidates_post_construction_private_tamper() -> None:
    manifest = _manifest((_unit(ordinal=0, source_id="source-1"),))
    authority_port = HmacIngestionPrivateAuditAuthority(b"c" * 32)
    authority = authority_port.sign(manifest, run_id="run-1")
    object.__setattr__(manifest.source_audits[0], "speaker", "forged")
    with pytest.raises(IngestionManifestError, match="audit commitment"):
        resolve_ingestion_source_audit(
            manifest,
            manifest.units[0],
            run_id="run-1",
            authority=authority,
            verifier=authority_port,
        )


class _RecordingConsumer:
    def __init__(self) -> None:
        self.units: tuple[IngestionUnit, ...] = ()
        self.bindings: tuple[tuple[str, str], ...] = ()

    def consume(
        self,
        unit: IngestionUnit,
        *,
        run_id: str,
        manifest_sha256: str,
    ) -> None:
        assert type(unit) is IngestionUnit
        self.units += (unit,)
        self.bindings += ((run_id, manifest_sha256),)


def _unit(*, ordinal: int, source_id: str) -> IngestionUnit:
    return make_ingestion_unit(
        ordinal=ordinal,
        corpus_id=opaque_ingestion_corpus_id(
            corpus_identity={
                "test_corpus": "corpus-1",
            }
        ),
        message=IngestionMessage(role="user", content=f"raw content {ordinal}"),
        metadata=IngestionUnitMetadata(
            source_id=opaque_ingestion_source_id(source_identity={"test_source": source_id}),
            timestamp=1_700_000_000,
        ),
    )


def _manifest(units: tuple[IngestionUnit, ...]) -> IngestionUnitManifest:
    dataset_sha256 = "a" * 64
    profile_id = "profile-1"
    from infinity_context_server.memory_comparison_ingestion_contracts import (
        dataset_profile_commitment_sha256,
    )

    profile_commitment = dataset_profile_commitment_sha256(
        dataset_sha256=dataset_sha256,
        profile_id=profile_id,
    )
    audits = tuple(
        make_ingestion_source_audit(
            unit=unit,
            sample_id="sample-1",
            session_id="session_1",
            dia_id=f"D1:{unit.ordinal + 1}",
            session_date="8:00 AM on 1 January, 2024",
            speaker="Speaker A",
            source_ref=f"ref-{unit.ordinal}",
        )
        for unit in units
    )
    corpus_projection = ingestion_corpus_projection_sha256(
        units,
        ingestion_policy_id="test-ingestion-policy.v1",
    )
    audit_root = ingestion_source_audit_root_sha256(audits)
    return IngestionUnitManifest(
        dataset_sha256=dataset_sha256,
        profile_id=profile_id,
        ingestion_policy_id="test-ingestion-policy.v1",
        dataset_profile_commitment_sha256=profile_commitment,
        corpus_projection_sha256=corpus_projection,
        source_audit_sha256=audit_root,
        units=units,
        source_audits=audits,
        manifest_sha256=ingestion_manifest_sha256(
            dataset_sha256=dataset_sha256,
            profile_id=profile_id,
            ingestion_policy_id="test-ingestion-policy.v1",
            dataset_profile_commitment_sha256=profile_commitment,
            corpus_projection_sha256=corpus_projection,
            source_audit_sha256=audit_root,
            units=units,
            source_audits=audits,
        ),
    )


def _forged_private_audit_manifest(
    manifest: IngestionUnitManifest,
) -> IngestionUnitManifest:
    audit = manifest.source_audits[0]
    forged_audit = make_ingestion_source_audit(
        unit=manifest.units[0],
        sample_id=audit.sample_id,
        session_id=audit.session_id,
        dia_id=audit.dia_id,
        session_date=audit.session_date,
        speaker=f"{audit.speaker}-forged",
        source_ref=audit.source_ref,
    )
    audits = (forged_audit, *manifest.source_audits[1:])
    audit_root = ingestion_source_audit_root_sha256(audits)
    manifest_sha256 = ingestion_manifest_sha256(
        dataset_sha256=manifest.dataset_sha256,
        profile_id=manifest.profile_id,
        ingestion_policy_id=manifest.ingestion_policy_id,
        dataset_profile_commitment_sha256=manifest.dataset_profile_commitment_sha256,
        corpus_projection_sha256=manifest.corpus_projection_sha256,
        source_audit_sha256=audit_root,
        units=manifest.units,
        source_audits=audits,
    )
    return replace(
        manifest,
        source_audits=audits,
        source_audit_sha256=audit_root,
        manifest_sha256=manifest_sha256,
    )


def _manifest_bytes(manifest: IngestionUnitManifest) -> bytes:
    return json.dumps(
        {
            **manifest.public_payload(),
            "units": [unit.payload() for unit in manifest.units],
            "source_audits": [audit.private_payload() for audit in manifest.source_audits],
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _raw_turns(dataset_bytes: bytes) -> tuple[tuple[str, str, str, str], ...]:
    samples = json.loads(dataset_bytes)
    result: list[tuple[str, str, str, str]] = []
    for sample in samples:
        conversation = sample["conversation"]
        speaker_a = conversation["speaker_a"]
        session_keys = sorted(
            (
                key
                for key in conversation
                if key.startswith("session_") and key.removeprefix("session_").isdigit()
            ),
            key=lambda key: int(key.removeprefix("session_")),
        )
        for session_id in session_keys:
            for turn in conversation[session_id]:
                role = "user" if turn["speaker"] == speaker_a else "assistant"
                text = turn["text"]
                query = turn.get("query")
                caption = turn.get("blip_caption")
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
                result.append((role, f"{turn['speaker']}: {text}", session_id, turn["dia_id"]))
    return tuple(result)


def _raw_texts(dataset_bytes: bytes) -> tuple[str, ...]:
    samples = json.loads(dataset_bytes)
    return tuple(
        turn["text"]
        for sample in samples
        for key, turns in sample["conversation"].items()
        if key.startswith("session_") and key.removeprefix("session_").isdigit()
        for turn in turns
    )


def _all_keys(value: object) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(value) + tuple(key for nested in value.values() for key in _all_keys(nested))
    if isinstance(value, list | tuple):
        return tuple(key for nested in value for key in _all_keys(nested))
    return ()

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LONGMEMEVAL_PROFILE,
    commitment,
)
from infinity_context_server.memory_comparison_longmemeval_cases import (
    official_longmemeval_pair_case,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_identity,
)
from infinity_context_server.original_pair_identity_authority import (
    OriginalPairIdentityAuthorityError,
    SQLiteOriginalPairIdentityAuthority,
    _AuthorityPolicy,
    _staging_path,
)

KEY = b"original-pair-authority-test-key" * 2


def _dataset() -> bytes:
    payload = [
        {
            "question_id": "case-a",
            "question": "question a",
            "answer": "answer a",
            "answer_session_ids": ["raw-session-a"],
            "haystack_session_ids": ["raw-session-a"],
            "haystack_dates": ["2024/01/01 (Mon) 08:00"],
            "haystack_sessions": [
                [
                    {"role": "user", "content": "first user"},
                    {"role": "assistant", "content": "first answer"},
                    {"role": "tool", "content": "not admitted"},
                    {"role": "assistant", "content": "   "},
                ]
            ],
        },
        {
            "question_id": "case-b",
            "question": "question b",
            "answer": "answer b",
            "answer_session_ids": ["raw-session-b"],
            "haystack_session_ids": ["raw-session-b"],
            "haystack_dates": ["2024/01/02 (Tue) 08:00"],
            "haystack_sessions": [
                [
                    {"role": "user", "content": "single valid message"},
                    {"role": "assistant", "content": ""},
                ]
            ],
        },
    ]
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _policy(dataset: bytes) -> _AuthorityPolicy:
    return _AuthorityPolicy(
        profile_id=LONGMEMEVAL_PROFILE,
        dataset_sha256=hashlib.sha256(dataset).hexdigest(),
        operation_count=2,
        original_pair_slot_count=3,
        omitted_source_identity_count=1,
        omitted_source_identity_root_sha256=hashlib.sha256(b"pinned omitted").hexdigest(),
        omitted_original_pair_identity_root_sha256=(
            "85d45fc7a46e65bacabf606764038eb8b14afdc8bb2a1a33e5e7d4869a1f3281"
        ),
    )


def _lookup_keys(dataset: bytes) -> tuple[tuple[str, str], ...]:
    rows = json.loads(dataset)
    result: list[tuple[str, str]] = []
    for raw in rows:
        case = official_longmemeval_pair_case(raw)
        corpus_id = _managed_corpus_identity(case)[0]
        result.extend(
            (corpus_id, f"{corpus_id}:conversation-{ordinal:04d}")
            for ordinal, _conversation in enumerate(case.conversations, start=1)
        )
    return tuple(result)


def _replace_first_mapping_identity(path: Path, pair_identity: str) -> None:
    with sqlite3.connect(path) as db:
        row = db.execute(
            "SELECT sequence,corpus_id_sha256,normalized_source_id_sha256 "
            "FROM admitted_mapping WHERE sequence=0"
        ).fetchone()
        assert row is not None
        mapping_identity = commitment(
            "original-pair-mapping/v1",
            {
                "sequence": row[0],
                "corpus_id_sha256": row[1],
                "normalized_source_id_sha256": row[2],
                "original_pair_identity_sha256": pair_identity,
            },
        )
        db.execute(
            "UPDATE admitted_mapping SET original_pair_identity_sha256=?,"
            "mapping_identity_sha256=? WHERE sequence=0",
            (pair_identity, mapping_identity),
        )


def test_hash_only_authority_preserves_invalid_slot_and_exact_mapping(tmp_path: Path) -> None:
    dataset = _dataset()
    policy = _policy(dataset)
    path = tmp_path / "original-pairs.sqlite3"
    authority = SQLiteOriginalPairIdentityAuthority._create(path, dataset, KEY, policy)
    keys = _lookup_keys(dataset)

    assert authority.profile_id == LONGMEMEVAL_PROFILE
    assert authority.dataset_sha256 == policy.dataset_sha256
    assert authority.operation_count == 2
    assert authority.original_pair_slot_count == 3
    assert authority.omitted_source_identity_count == 1
    assert (
        authority.omitted_source_identity_root_sha256 == policy.omitted_source_identity_root_sha256
    )
    assert (
        authority.omitted_original_pair_identity_root_sha256
        == policy.omitted_original_pair_identity_root_sha256
    )
    first = authority.lookup(sequence=0, corpus_id=keys[0][0], normalized_source_id=keys[0][1])
    second = authority.lookup(sequence=1, corpus_id=keys[1][0], normalized_source_id=keys[1][1])
    assert first is not None and second is not None and first != second
    assert (
        authority.lookup(sequence=0, corpus_id=keys[1][0], normalized_source_id=keys[0][1]) is None
    )
    assert len(authority.original_pair_slot_root_sha256) == 64
    assert len(authority.ordered_mapping_root_sha256) == 64
    authority.close()

    reopened = SQLiteOriginalPairIdentityAuthority._open(path, KEY, policy)
    assert (
        reopened.lookup(sequence=0, corpus_id=keys[0][0], normalized_source_id=keys[0][1]) == first
    )
    reopened.close()


def test_create_or_open_is_exact_idempotent_for_synthetic_authority(tmp_path: Path) -> None:
    dataset = _dataset()
    policy = _policy(dataset)
    path = tmp_path / "original-pairs.sqlite3"
    created = SQLiteOriginalPairIdentityAuthority._create_or_open(path, dataset, KEY, policy)
    first = (created.terminal_commitment_sha256, created.ordered_mapping_root_sha256)
    created.close()
    before = path.stat()

    reopened = SQLiteOriginalPairIdentityAuthority._create_or_open(path, dataset, KEY, policy)
    assert (reopened.terminal_commitment_sha256, reopened.ordered_mapping_root_sha256) == first
    reopened.close()
    after = path.stat()
    assert (after.st_dev, after.st_ino, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_mtime_ns,
    )


def test_create_or_open_replays_partial_and_link_publish_crashes(tmp_path: Path) -> None:
    dataset = _dataset()
    policy = _policy(dataset)
    path = tmp_path / "original-pairs.sqlite3"
    staging = _staging_path(path)
    staging.write_bytes(b"interrupted sqlite creation")
    staging.chmod(0o600)

    recovered = SQLiteOriginalPairIdentityAuthority._create_or_open(path, dataset, KEY, policy)
    terminal = recovered.terminal_commitment_sha256
    recovered.close()
    assert path.stat().st_nlink == 1
    assert not staging.exists()

    second_path = tmp_path / "second-original-pairs.sqlite3"
    second_staging = _staging_path(second_path)
    staged = SQLiteOriginalPairIdentityAuthority._create(second_staging, dataset, KEY, policy)
    staged.close()
    os.link(second_staging, second_path)
    assert second_path.stat().st_nlink == 2

    linked = SQLiteOriginalPairIdentityAuthority._create_or_open(second_path, dataset, KEY, policy)
    assert linked.terminal_commitment_sha256 == terminal
    linked.close()
    assert second_path.stat().st_nlink == 1
    assert not second_staging.exists()


def test_create_or_open_rejects_and_preserves_preexisting_or_tampered_target(
    tmp_path: Path,
) -> None:
    dataset = _dataset()
    policy = _policy(dataset)
    arbitrary = tmp_path / "arbitrary.sqlite3"
    arbitrary.write_bytes(b"not an authority")
    arbitrary.chmod(0o600)
    before = arbitrary.read_bytes()
    with pytest.raises((OriginalPairIdentityAuthorityError, sqlite3.Error)):
        SQLiteOriginalPairIdentityAuthority._create_or_open(arbitrary, dataset, KEY, policy)
    assert arbitrary.read_bytes() == before

    path = tmp_path / "tampered.sqlite3"
    authority = SQLiteOriginalPairIdentityAuthority._create_or_open(path, dataset, KEY, policy)
    authority.close()
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE admitted_mapping SET authentication_tag=? WHERE sequence=0",
            ("f" * 64,),
        )
    tampered = path.read_bytes()
    with pytest.raises(OriginalPairIdentityAuthorityError):
        SQLiteOriginalPairIdentityAuthority._create_or_open(path, dataset, KEY, policy)
    assert path.read_bytes() == tampered


def test_store_tamper_and_wrong_key_fail_closed(tmp_path: Path) -> None:
    dataset = _dataset()
    policy = _policy(dataset)
    path = tmp_path / "original-pairs.sqlite3"
    authority = SQLiteOriginalPairIdentityAuthority._create(path, dataset, KEY, policy)
    authority.close()
    with pytest.raises(OriginalPairIdentityAuthorityError, match="authentication_invalid"):
        SQLiteOriginalPairIdentityAuthority._open(path, b"wrong-key" * 4, policy)

    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE admitted_mapping SET normalized_source_id_sha256=? WHERE sequence=0",
            ("f" * 64,),
        )
    with pytest.raises(OriginalPairIdentityAuthorityError, match="content_invalid"):
        SQLiteOriginalPairIdentityAuthority._open(path, KEY, policy)


def test_lookup_reauthenticates_row_after_same_inode_mutation(tmp_path: Path) -> None:
    dataset = _dataset()
    path = tmp_path / "original-pairs.sqlite3"
    authority = SQLiteOriginalPairIdentityAuthority._create(path, dataset, KEY, _policy(dataset))
    keys = _lookup_keys(dataset)
    before = path.stat()

    _replace_first_mapping_identity(path, "e" * 64)
    os.chmod(path, before.st_mode)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    after = path.stat()
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert after.st_mtime_ns == before.st_mtime_ns
    with pytest.raises(OriginalPairIdentityAuthorityError, match="lookup_authentication_invalid"):
        authority.lookup(sequence=0, corpus_id=keys[0][0], normalized_source_id=keys[0][1])
    authority.close()


def test_metadata_and_close_reject_rename_replacement_after_open(tmp_path: Path) -> None:
    dataset = _dataset()
    policy = _policy(dataset)
    path = tmp_path / "original-pairs.sqlite3"
    renamed = tmp_path / "renamed-original-pairs.sqlite3"
    authority = SQLiteOriginalPairIdentityAuthority._create(path, dataset, KEY, policy)
    path.rename(renamed)
    replacement = SQLiteOriginalPairIdentityAuthority._create(path, dataset, KEY, policy)
    replacement.close()
    with pytest.raises(OriginalPairIdentityAuthorityError, match="store_replaced"):
        _ = authority.terminal_commitment_sha256
    with pytest.raises(OriginalPairIdentityAuthorityError, match="store_replaced"):
        authority.close()


@pytest.mark.parametrize(
    ("sequence", "corpus_id", "source_id"),
    [
        (True, "corpus", "source"),
        (0, 1, "source"),
        (0, "corpus", b"source"),
    ],
)
def test_lookup_rejects_non_exact_scalar_types(
    tmp_path: Path, sequence: object, corpus_id: object, source_id: object
) -> None:
    dataset = _dataset()
    authority = SQLiteOriginalPairIdentityAuthority._create(
        tmp_path / "original-pairs.sqlite3", dataset, KEY, _policy(dataset)
    )
    with pytest.raises(OriginalPairIdentityAuthorityError, match="lookup_invalid"):
        authority.lookup(  # type: ignore[arg-type]
            sequence=sequence,
            corpus_id=corpus_id,
            normalized_source_id=source_id,
        )
    authority.close()


@pytest.mark.parametrize("journal_mode", ["WAL", "PERSIST"])
def test_lookup_rejects_divergent_row_mac_from_sqlite_sidecar(
    tmp_path: Path, journal_mode: str
) -> None:
    dataset = _dataset()
    path = tmp_path / f"original-pairs-{journal_mode.lower()}.sqlite3"
    authority = SQLiteOriginalPairIdentityAuthority._create(path, dataset, KEY, _policy(dataset))
    keys = _lookup_keys(dataset)
    before = path.stat()

    with sqlite3.connect(path) as writer:
        observed_mode = writer.execute(f"PRAGMA journal_mode={journal_mode}").fetchone()
        assert observed_mode is not None and observed_mode[0].upper() == journal_mode
        writer.execute(
            "UPDATE admitted_mapping SET authentication_tag=? WHERE sequence=0",
            ("f" * 64,),
        )
        writer.commit()
        os.chmod(path, before.st_mode)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with pytest.raises(
            OriginalPairIdentityAuthorityError,
            match="lookup_(authentication|content)_invalid",
        ):
            authority.lookup(
                sequence=0,
                corpus_id=keys[0][0],
                normalized_source_id=keys[0][1],
            )
    authority.close()


def test_metadata_bool_and_omitted_pair_tamper_fail_closed(tmp_path: Path) -> None:
    dataset = _dataset()
    policy = _policy(dataset)
    path = tmp_path / "original-pairs.sqlite3"
    authority = SQLiteOriginalPairIdentityAuthority._create(path, dataset, KEY, policy)
    authority.close()

    with sqlite3.connect(path) as db:
        payload = json.loads(
            db.execute("SELECT payload_json FROM authority_metadata WHERE singleton=1").fetchone()[
                0
            ]
        )
        payload["omitted_source_identity_count"] = True
        db.execute(
            "UPDATE authority_metadata SET payload_json=? WHERE singleton=1",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
        )
    with pytest.raises(OriginalPairIdentityAuthorityError, match="authentication_invalid"):
        SQLiteOriginalPairIdentityAuthority._open(path, KEY, policy)

    authority = SQLiteOriginalPairIdentityAuthority._create(
        tmp_path / "omitted-tamper.sqlite3", dataset, KEY, policy
    )
    authority.close()
    omitted_path = tmp_path / "omitted-tamper.sqlite3"
    with sqlite3.connect(omitted_path) as db:
        db.execute(
            "UPDATE original_slots SET original_pair_identity_sha256=? "
            "WHERE admitted_sequence IS NULL",
            ("e" * 64,),
        )
    with pytest.raises(
        OriginalPairIdentityAuthorityError, match="omitted_original_pair_root_mismatch"
    ):
        SQLiteOriginalPairIdentityAuthority._open(omitted_path, KEY, policy)


def test_store_rejects_symlinks_hardlinks_and_path_replacement(tmp_path: Path) -> None:
    dataset = _dataset()
    policy = _policy(dataset)
    destination = tmp_path / "destination.sqlite3"
    dangling = tmp_path / "dangling.sqlite3"
    dangling.symlink_to(destination)
    with pytest.raises(OriginalPairIdentityAuthorityError, match="store_exists"):
        SQLiteOriginalPairIdentityAuthority._create(dangling, dataset, KEY, policy)
    assert not destination.exists()

    path = tmp_path / "original-pairs.sqlite3"
    authority = SQLiteOriginalPairIdentityAuthority._create(path, dataset, KEY, policy)
    authority.close()
    symlink = tmp_path / "authority-link.sqlite3"
    symlink.symlink_to(path)
    with pytest.raises(OriginalPairIdentityAuthorityError, match="store_unsafe"):
        SQLiteOriginalPairIdentityAuthority._open(symlink, KEY, policy)

    hardlink = tmp_path / "authority-hardlink.sqlite3"
    os.link(path, hardlink)
    with pytest.raises(OriginalPairIdentityAuthorityError, match="store_unsafe"):
        SQLiteOriginalPairIdentityAuthority._open(path, KEY, policy)
    hardlink.unlink()

    opened = SQLiteOriginalPairIdentityAuthority._open(path, KEY, policy)
    moved = tmp_path / "moved.sqlite3"
    path.replace(moved)
    path.touch(mode=0o600)
    with pytest.raises(OriginalPairIdentityAuthorityError, match="store_replaced"):
        opened.lookup(sequence=0, corpus_id="corpus", normalized_source_id="source")
    with pytest.raises(OriginalPairIdentityAuthorityError, match="store_replaced"):
        opened.close()


def test_public_create_rejects_unpinned_dataset_and_existing_target(tmp_path: Path) -> None:
    dataset = _dataset()
    path = tmp_path / "original-pairs.sqlite3"
    with pytest.raises(OriginalPairIdentityAuthorityError, match="dataset_sha256_mismatch"):
        SQLiteOriginalPairIdentityAuthority.create(
            path, dataset_bytes=dataset, authentication_key=KEY
        )
    authority = SQLiteOriginalPairIdentityAuthority._create(path, dataset, KEY, _policy(dataset))
    authority.close()
    with pytest.raises(OriginalPairIdentityAuthorityError, match="store_exists"):
        SQLiteOriginalPairIdentityAuthority._create(path, dataset, KEY, _policy(dataset))


def test_full_official_longmemeval_original_pair_authority(tmp_path: Path) -> None:
    value = os.environ.get("MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET")
    if not value or not Path(value).is_file():
        pytest.skip("official LongMemEval dataset is not staged")
    dataset = Path(value).read_bytes()
    authority = SQLiteOriginalPairIdentityAuthority.create(
        tmp_path / "official-original-pairs.sqlite3",
        dataset_bytes=dataset,
        authentication_key=KEY,
    )
    assert authority.operation_count == 124_344
    assert authority.original_pair_slot_count == 124_345
    assert authority.omitted_source_identity_count == 1
    assert authority.omitted_source_identity_root_sha256 == (
        "f4106215d618a016b4d18bdb734437a64d6329ff49db8a4eb5661e359d3408a9"
    )
    assert authority.omitted_original_pair_identity_root_sha256 == (
        "752cca9263addd0ec16eb9fcf10e7898d8c88774437767c4e8f7f2ccc327007d"
    )
    authority.close()

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
)
from publishable_mem0_v5 import run_provider as subject

_INVALID_CASES_CODE = "publishable_run_provider_official_cases_invalid"


def _dataset_bytes(*, answer: str) -> bytes:
    return json.dumps(
        [
            {
                "conversation": {
                    "session_1": [
                        {
                            "dia_id": "D1:1",
                            "speaker": "Alice",
                            "text": f"The launch code is {answer}.",
                        }
                    ],
                    "speaker_a": "Alice",
                },
                "qa": [
                    {
                        "answer": answer,
                        "category": 4,
                        "evidence": ["D1:1"],
                        "question": "What is the launch code?",
                    }
                ],
                "sample_id": "snapshot-case",
            }
        ],
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _write_dataset(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _load(path: Path, payload: bytes):
    return subject._load_authenticated_dataset_cases(
        path,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_official_cases_are_parsed_from_the_authenticated_immutable_bytes(tmp_path: Path) -> None:
    trusted = _dataset_bytes(answer="amber")
    path = tmp_path / "locomo.json"
    _write_dataset(path, trusted)

    authenticated = _load(path, trusted)
    cases = authenticated.cases

    assert authenticated.observed_sha256 == hashlib.sha256(trusted).hexdigest()
    assert len(cases) == 1
    assert cases[0].case_id == "snapshot-case:qa:1"
    assert cases[0].question == "What is the launch code?"
    assert cases[0].expected_terms == ("amber",)


def test_same_inode_same_length_mutation_with_stat_aba_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted = _dataset_bytes(answer="amber")
    hostile = _dataset_bytes(answer="umber")
    assert len(hostile) == len(trusted)
    path = tmp_path / "locomo.json"
    _write_dataset(path, trusted)
    authenticated = path.stat()
    real_loader = subject.load_memory_comparison_cases_from_bytes
    real_read = subject.os.read
    observed_snapshots: list[bytes] = []
    read_phase = ["initial"]
    read_chunks: list[tuple[str, int, bytes]] = []
    parser_completed: list[bool] = []

    def timestamp_independent_identity(value: os.stat_result) -> tuple[int, ...]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_uid,
            value.st_gid,
            value.st_size,
        )

    def record_read(descriptor: int, maximum_chunk_bytes: int) -> bytes:
        chunk = real_read(descriptor, maximum_chunk_bytes)
        if chunk:
            read_chunks.append((read_phase[0], descriptor, chunk))
        return chunk

    def mutate_then_parse(dataset_bytes: bytes, *, locomo_ingest_mode: str):
        observed_snapshots.append(dataset_bytes)
        with path.open("r+b", buffering=0) as handle:
            assert handle.write(hostile) == len(hostile)
            os.fsync(handle.fileno())
        cases = real_loader(dataset_bytes, locomo_ingest_mode=locomo_ingest_mode)
        parser_completed.append(True)
        read_phase[0] = "reread"
        return cases

    monkeypatch.setattr(subject, "_dataset_file_identity", timestamp_independent_identity)
    monkeypatch.setattr(subject.os, "read", record_read)
    monkeypatch.setattr(subject, "load_memory_comparison_cases_from_bytes", mutate_then_parse)

    with pytest.raises(PublishableRunError) as error:
        _load(path, trusted)

    assert error.value.code == _INVALID_CASES_CODE
    assert observed_snapshots == [trusted]
    assert parser_completed == [True]
    assert b"".join(chunk for phase, _, chunk in read_chunks if phase == "initial") == trusted
    assert b"".join(chunk for phase, _, chunk in read_chunks if phase == "reread") == hostile
    assert len({descriptor for _, descriptor, _ in read_chunks}) == 1
    changed = path.stat()
    assert (
        changed.st_dev,
        changed.st_ino,
        changed.st_mode,
        changed.st_size,
    ) == (
        authenticated.st_dev,
        authenticated.st_ino,
        authenticated.st_mode,
        authenticated.st_size,
    )
    assert path.read_bytes() == hostile


def test_rename_replacement_between_authentication_and_parse_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted = _dataset_bytes(answer="amber")
    hostile = _dataset_bytes(answer="umber")
    assert len(hostile) == len(trusted)
    path = tmp_path / "locomo.json"
    archived = tmp_path / "authenticated.json"
    replacement = tmp_path / "replacement.json"
    _write_dataset(path, trusted)
    _write_dataset(replacement, hostile)
    authenticated = path.stat()
    real_loader = subject.load_memory_comparison_cases_from_bytes
    observed_snapshots: list[bytes] = []
    replacement_stats: list[os.stat_result] = []
    parser_completed: list[bool] = []

    def replace_then_parse(dataset_bytes: bytes, *, locomo_ingest_mode: str):
        observed_snapshots.append(dataset_bytes)
        os.replace(path, archived)
        os.replace(replacement, path)
        replacement_stats.append(path.stat())
        cases = real_loader(dataset_bytes, locomo_ingest_mode=locomo_ingest_mode)
        parser_completed.append(True)
        return cases

    monkeypatch.setattr(subject, "load_memory_comparison_cases_from_bytes", replace_then_parse)

    with pytest.raises(PublishableRunError) as error:
        _load(path, trusted)

    assert error.value.code == _INVALID_CASES_CODE
    assert observed_snapshots == [trusted]
    assert parser_completed == [True]
    replaced = replacement_stats[0]
    assert (replaced.st_dev, replaced.st_ino) != (
        authenticated.st_dev,
        authenticated.st_ino,
    )
    assert replaced.st_size == authenticated.st_size
    assert path.read_bytes() == hostile


@pytest.mark.parametrize(
    "payload",
    (
        b'{"cases":[],"cases":[]}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":1e999}',
    ),
)
def test_authenticated_snapshot_rejects_ambiguous_or_nonfinite_json(
    tmp_path: Path,
    payload: bytes,
) -> None:
    path = tmp_path / "invalid.json"
    _write_dataset(path, payload)

    with pytest.raises(PublishableRunError) as error:
        _load(path, payload)

    assert error.value.code == _INVALID_CASES_CODE


def test_post_parse_reauthentication_growth_read_is_bounded_to_cap_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _dataset_bytes(answer="amber")
    path = tmp_path / "locomo.json"
    _write_dataset(path, payload)
    maximum_bytes = len(payload)
    real_read = subject.os.read
    real_loader = subject.load_memory_comparison_cases_from_bytes
    read_phase = ["initial"]
    read_sizes: list[tuple[str, int, int]] = []

    def record_read(descriptor: int, maximum_chunk_bytes: int) -> bytes:
        chunk = real_read(descriptor, maximum_chunk_bytes)
        read_sizes.append((read_phase[0], maximum_chunk_bytes, len(chunk)))
        return chunk

    def parse_then_grow(dataset_bytes: bytes, *, locomo_ingest_mode: str):
        cases = real_loader(dataset_bytes, locomo_ingest_mode=locomo_ingest_mode)
        with path.open("ab") as handle:
            handle.write(b"x")
        read_phase[0] = "reread"
        return cases

    monkeypatch.setattr(subject, "_MAX_DATASET_BYTES", maximum_bytes)
    monkeypatch.setattr(subject.os, "read", record_read)
    monkeypatch.setattr(subject, "load_memory_comparison_cases_from_bytes", parse_then_grow)

    with pytest.raises(PublishableRunError) as error:
        _load(path, payload)

    assert error.value.code == _INVALID_CASES_CODE
    assert read_sizes[0][1] == maximum_bytes + 1
    assert all(requested <= maximum_bytes + 1 for _, requested, _ in read_sizes)
    assert sum(returned for phase, _, returned in read_sizes if phase == "initial") == maximum_bytes
    assert sum(returned for phase, _, returned in read_sizes if phase == "reread") == (
        maximum_bytes + 1
    )
    assert path.stat().st_size == maximum_bytes + 1

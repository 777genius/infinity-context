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

    cases = _load(path, trusted)

    assert len(cases) == 1
    assert cases[0].case_id == "snapshot-case:qa:1"
    assert cases[0].question == "What is the launch code?"
    assert cases[0].expected_terms == ("amber",)


def test_same_inode_mutation_between_authentication_and_parse_fails_closed(
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
    observed_snapshots: list[bytes] = []
    changed_stats: list[os.stat_result] = []
    parser_completed: list[bool] = []

    def mutate_then_parse(dataset_bytes: bytes, *, locomo_ingest_mode: str):
        observed_snapshots.append(dataset_bytes)
        path.write_bytes(hostile)
        os.utime(
            path,
            ns=(authenticated.st_atime_ns, authenticated.st_mtime_ns),
        )
        changed_stats.append(path.stat())
        cases = real_loader(dataset_bytes, locomo_ingest_mode=locomo_ingest_mode)
        parser_completed.append(True)
        return cases

    monkeypatch.setattr(subject, "load_memory_comparison_cases_from_bytes", mutate_then_parse)

    with pytest.raises(PublishableRunError) as error:
        _load(path, trusted)

    assert error.value.code == _INVALID_CASES_CODE
    assert observed_snapshots == [trusted]
    assert parser_completed == [True]
    changed = changed_stats[0]
    assert (
        changed.st_dev,
        changed.st_ino,
        changed.st_mode,
        changed.st_size,
        changed.st_mtime_ns,
    ) == (
        authenticated.st_dev,
        authenticated.st_ino,
        authenticated.st_mode,
        authenticated.st_size,
        authenticated.st_mtime_ns,
    )
    assert changed.st_ctime_ns != authenticated.st_ctime_ns
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


def test_authenticated_snapshot_growth_read_is_bounded_to_cap_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _dataset_bytes(answer="amber")
    path = tmp_path / "locomo.json"
    _write_dataset(path, payload)
    maximum_bytes = len(payload)
    real_read = subject.os.read
    requested_bytes: list[int] = []
    returned_bytes: list[int] = []

    def grow_then_read(descriptor: int, maximum_chunk_bytes: int) -> bytes:
        requested_bytes.append(maximum_chunk_bytes)
        if len(requested_bytes) == 1:
            with path.open("ab") as handle:
                handle.write(b"x")
        chunk = real_read(descriptor, maximum_chunk_bytes)
        returned_bytes.append(len(chunk))
        return chunk

    monkeypatch.setattr(subject, "_MAX_DATASET_BYTES", maximum_bytes)
    monkeypatch.setattr(subject.os, "read", grow_then_read)

    with pytest.raises(PublishableRunError) as error:
        _load(path, payload)

    assert error.value.code == _INVALID_CASES_CODE
    assert requested_bytes[0] == maximum_bytes + 1
    assert all(value <= maximum_bytes + 1 for value in requested_bytes)
    assert sum(returned_bytes) == maximum_bytes + 1
    assert path.stat().st_size == maximum_bytes + 1

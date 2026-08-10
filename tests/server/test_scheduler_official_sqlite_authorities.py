from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)
from infinity_context_server.publishable_durable_scheduler import (
    SchedulerBenchmark,
    SchedulerCaseAuthority,
    SchedulerOfficialAuthorityError,
    SchedulerOfficialCaseAuthorityPage,
    SchedulerOfficialCaseAuthorityRow,
    SchedulerOfficialCaseRunScope,
    SchedulerRetrievalBackendScope,
    SchedulerRetrievalEvidenceAuthorityPage,
    SchedulerRetrievalEvidenceAuthorityRow,
    SchedulerRetrievalRunScope,
    SchedulerRunnerError,
    SQLiteSchedulerOfficialCaseAuthorityBuilder,
    SQLiteSchedulerOfficialCaseReader,
    SQLiteSchedulerRetrievalEvidenceAuthorityBuilder,
    SQLiteSchedulerRetrievalEvidenceReader,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
    SchedulerRetrievalEvidenceKey,
)

_KEY = b"scheduler-official-authority-test-key/v1" * 2
_OTHER_KEY = b"scheduler-official-authority-wrong-key/v1" * 2


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _identities(benchmark: SchedulerBenchmark, count: int) -> tuple[SchedulerCaseAuthority, ...]:
    return tuple(_identity(benchmark, index) for index in range(count))


def _identity(benchmark: SchedulerBenchmark, index: int) -> SchedulerCaseAuthority:
    return SchedulerCaseAuthority(
        case_id=f"{benchmark.value}-case-{index}",
        case_alias=f"{benchmark.value}-alias-{index}",
    )


def _case_scopes(
    *, locomo_count: int = 2, longmemeval_count: int = 1
) -> tuple[SchedulerOfficialCaseRunScope, SchedulerOfficialCaseRunScope]:
    result = []
    for benchmark, count in (
        (SchedulerBenchmark.LOCOMO, locomo_count),
        (SchedulerBenchmark.LONGMEMEVAL, longmemeval_count),
    ):
        result.append(
            SchedulerOfficialCaseRunScope(
                suite_authority_sha256=_sha("suite"),
                run_authority_sha256=_sha(f"run:{benchmark.value}"),
                run_binding_commitment_sha256=_sha(f"binding:{benchmark.value}"),
                run_id=f"run-{benchmark.value}",
                benchmark=benchmark,
                scheduler_profile_id=f"scheduler-{benchmark.value}",
                publishable_profile_id="publishable-priority-v4",
                publishable_profile_sha256=_sha("publishable-profile"),
                methodology_sha256=_sha("methodology"),
                dataset_sha256=_sha(f"dataset:{benchmark.value}"),
                case_manifest_sha256=case_manifest_sha256(_identities(benchmark, count)),
                case_count=count,
            )
        )
    return result[0], result[1]


def _case(scope: SchedulerOfficialCaseRunScope, index: int) -> PublicBenchmarkCase:
    identity = _identity(scope.benchmark, index)
    date = "2024/01/02 (Tue) 09:30"
    return PublicBenchmarkCase(
        benchmark=scope.benchmark.value,
        case_id=identity.case_id,
        question=f"What is the current choice for {identity.case_id}?",
        expected_terms=("Postgres", f"expected-{index}"),
        forbidden_terms=("obsolete",),
        memories=(
            BenchmarkMemoryInput(
                text=f"note-{identity.case_id}",
                kind="preference",
                source_external_id=f"memory-{index}",
                metadata={"ordinal": index, "nested": [True, None, 1.25]},
            ),
        ),
        documents=(
            BenchmarkDocumentInput(
                title=f"document-{index}",
                text="Postgres is current.",
                source_type="benchmark_document",
                classification="internal",
                source_external_id=f"document-{index}",
                source_refs=({"page": index + 1, "kind": "synthetic"},),
            ),
        ),
        memory_scope_external_ref=f"scope-{scope.benchmark.value}-{index}",
        thread_external_ref=f"thread-{scope.benchmark.value}-{index}",
        metadata={
            "_evaluator_ground_truth": "Postgres",
            "question_date": date,
            "question_type": "knowledge-update",
        },
        conversations=(
            BenchmarkConversationInput(
                messages=(
                    BenchmarkMessageInput(
                        role="user",
                        content="I used SQLite before.",
                        source_external_id=f"message-{index}-0",
                        timestamp=1_700_000_000 + index,
                        metadata={"turn": 0},
                    ),
                    BenchmarkMessageInput(
                        role="assistant",
                        content="You now use Postgres.",
                        source_external_id=f"message-{index}-1",
                        timestamp=1_700_000_001 + index,
                        metadata={"turn": 1},
                    ),
                ),
                source_external_id=f"conversation-{index}",
                session_external_id=f"session-{index}",
                session_date=date,
                timestamp=1_700_000_000 + index,
                metadata={"case": identity.case_id},
            ),
        ),
    )


def _case_row(
    scope: SchedulerOfficialCaseRunScope, index: int
) -> SchedulerOfficialCaseAuthorityRow:
    identity = _identity(scope.benchmark, index)
    return SchedulerOfficialCaseAuthorityRow(
        run_id=scope.run_id,
        case_index=index,
        case_id=identity.case_id,
        case_alias=identity.case_alias,
        case=_case(scope, index),
    )


def _case_key(scope, index, root):
    identity = _identity(scope.benchmark, index)
    return scope.case_key(
        case_index=index,
        case_id=identity.case_id,
        case_alias=identity.case_alias,
        authority_root_sha256=root,
    )


def _append_case_pages(builder, scopes, *, page_size: int) -> None:
    page_index = 0
    pending = []
    for scope in scopes:
        for index in range(scope.case_count):
            pending.append(_case_row(scope, index))
            if len(pending) == page_size:
                builder.append_page(SchedulerOfficialCaseAuthorityPage(page_index, tuple(pending)))
                pending.clear()
                page_index += 1
    if pending:
        builder.append_page(SchedulerOfficialCaseAuthorityPage(page_index, tuple(pending)))


def _build_cases(path: Path, scopes, *, page_size: int = 2):
    builder = SQLiteSchedulerOfficialCaseAuthorityBuilder.create(
        path, run_scopes=scopes, authentication_key=_KEY
    )
    _append_case_pages(builder, scopes, page_size=page_size)
    terminal = builder.finalize()
    builder.close()
    return terminal


def _retrieval_scopes(scopes):
    return tuple(
        SchedulerRetrievalRunScope(
            case_scope=scope,
            backends=(
                SchedulerRetrievalBackendScope(0, "infinity-context", _sha("infinity-target")),
                SchedulerRetrievalBackendScope(1, "mem0", _sha("mem0-target")),
            ),
        )
        for scope in scopes
    )


def _memories(case_index: int, backend_index: int, *, count: int = 2):
    return tuple(
        RetrievedMemory(
            text=f"evidence-{case_index}-{backend_index}-{rank}",
            rank=rank,
            score=1.0 / rank,
            item_id=f"item-{case_index}-{backend_index}-{rank}",
            created_at=f"2024-01-{rank:02d}T00:00:00Z",
            source_refs=(f"source-{rank}", f"backend-{backend_index}"),
            metadata={
                "backend_index": backend_index,
                "case_index": case_index,
                "commitment": _sha(f"memory:{case_index}:{backend_index}:{rank}"),
            },
        )
        for rank in range(1, count + 1)
    )


def _build_retrieval(path, scopes, case_terminal, case_reader, *, memory_count=2):
    retrieval_scopes = _retrieval_scopes(scopes)
    builder = SQLiteSchedulerRetrievalEvidenceAuthorityBuilder.create(
        path,
        run_scopes=retrieval_scopes,
        case_authority_root_sha256=case_terminal.authority_root_sha256,
        authentication_key=_KEY,
    )
    page_index = 0
    pending = []
    for scope in scopes:
        for index in range(scope.case_count):
            key = _case_key(scope, index, case_terminal.authority_root_sha256)
            case_read = case_reader.read_exact(key=key)
            for backend_index in (0, 1):
                pending.append(
                    SchedulerRetrievalEvidenceAuthorityRow(
                        case_key=key,
                        case_material_sha256=case_read.material_sha256,
                        backend_index=backend_index,
                        memories=_memories(index, backend_index, count=memory_count),
                    )
                )
                if len(pending) == 3:
                    builder.append_page(
                        SchedulerRetrievalEvidenceAuthorityPage(page_index, tuple(pending))
                    )
                    pending.clear()
                    page_index += 1
    if pending:
        builder.append_page(SchedulerRetrievalEvidenceAuthorityPage(page_index, tuple(pending)))
    terminal = builder.finalize()
    builder.close()
    return retrieval_scopes, terminal


def _retrieval_key(scope, case_read, backend_index, root):
    backend = scope.backends[backend_index]
    return SchedulerRetrievalEvidenceKey(
        case_key=case_read.key,
        case_material_sha256=case_read.material_sha256,
        backend_index=backend_index,
        backend_role=backend.backend_role,
        target_identity_sha256=backend.target_identity_sha256,
        cutoff=SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
        authority_root_sha256=root,
    )


def test_synthetic_benchmarks_and_both_backends_round_trip_all_fields(tmp_path: Path) -> None:
    scopes = _case_scopes()
    case_path = tmp_path / "cases.sqlite3"
    case_terminal = _build_cases(case_path, scopes)
    assert case_path.stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o777 == 0o700

    case_reader = SQLiteSchedulerOfficialCaseReader.open(
        case_path,
        authentication_key=_KEY,
        authority_root_sha256=case_terminal.authority_root_sha256,
    )
    retrieval_path = tmp_path / "retrieval.sqlite3"
    retrieval_scopes, retrieval_terminal = _build_retrieval(
        retrieval_path, scopes, case_terminal, case_reader
    )
    retrieval_reader = SQLiteSchedulerRetrievalEvidenceReader.open(
        retrieval_path,
        authentication_key=_KEY,
        authority_root_sha256=retrieval_terminal.authority_root_sha256,
        case_authority_root_sha256=case_terminal.authority_root_sha256,
    )

    for case_scope, retrieval_scope in zip(scopes, retrieval_scopes, strict=True):
        for index in range(case_scope.case_count):
            case_read = case_reader.read_exact(
                key=_case_key(case_scope, index, case_terminal.authority_root_sha256)
            )
            assert case_read.case == _case(case_scope, index)
            for backend_index in (0, 1):
                result = retrieval_reader.read_exact(
                    key=_retrieval_key(
                        retrieval_scope,
                        case_read,
                        backend_index,
                        retrieval_terminal.authority_root_sha256,
                    )
                )
                assert result.memories == _memories(index, backend_index)
                assert tuple(item.rank for item in result.memories) == (1, 2)

    retrieval_reader.close()
    case_reader.close()


def test_bounded_2040_case_streaming_build_and_indexed_read_traversal(tmp_path: Path) -> None:
    scopes = _case_scopes(locomo_count=1540, longmemeval_count=500)
    path = tmp_path / "bounded-2040.sqlite3"
    terminal = _build_cases(path, scopes, page_size=128)
    assert terminal.case_count == 2_040
    reader = SQLiteSchedulerOfficialCaseReader.open(
        path, authentication_key=_KEY, authority_root_sha256=terminal.authority_root_sha256
    )
    statements = []
    reader._handle.connection.set_trace_callback(statements.append)
    prior = None
    count = 0
    for scope in scopes:
        for index in range(scope.case_count):
            if prior is not None:
                assert prior() is None
            result = reader.read_exact(key=_case_key(scope, index, terminal.authority_root_sha256))
            prior = weakref.ref(result.case)
            del result
            count += 1
    assert count == 2_040
    lookups = [sql for sql in statements if "FROM official_cases" in sql]
    assert len(lookups) == 2_040
    assert all("WHERE run_id=" in sql for sql in lookups)
    assert not hasattr(reader, "cases")
    assert not hasattr(reader, "case_cache")
    reader.close()


def test_crash_resume_exact_replay_divergence_and_post_seal_reopen(tmp_path: Path) -> None:
    scopes = _case_scopes(locomo_count=2, longmemeval_count=1)
    path = tmp_path / "crash-resume.sqlite3"
    first = SchedulerOfficialCaseAuthorityPage(0, (_case_row(scopes[0], 0),))
    builder = SQLiteSchedulerOfficialCaseAuthorityBuilder.create(
        path, run_scopes=scopes, authentication_key=_KEY
    )
    builder.append_page(first)
    builder.close()
    with pytest.raises(SchedulerOfficialAuthorityError, match="unsealed"):
        SQLiteSchedulerOfficialCaseReader.open(
            path, authentication_key=_KEY, authority_root_sha256="0" * 64
        )

    resumed = SQLiteSchedulerOfficialCaseAuthorityBuilder.open(
        path, run_scopes=scopes, authentication_key=_KEY
    )
    resumed.append_page(first)
    divergent_row = replace(
        _case_row(scopes[0], 0), case=replace(_case(scopes[0], 0), question="changed")
    )
    with pytest.raises(SchedulerOfficialAuthorityError, match="divergent"):
        resumed.append_page(SchedulerOfficialCaseAuthorityPage(0, (divergent_row,)))
    resumed.append_page(
        SchedulerOfficialCaseAuthorityPage(1, (_case_row(scopes[0], 1), _case_row(scopes[1], 0)))
    )
    terminal = resumed.finalize()
    assert resumed.finalize() == terminal
    resumed.close()

    sealed = SQLiteSchedulerOfficialCaseAuthorityBuilder.open(
        path, run_scopes=scopes, authentication_key=_KEY
    )
    sealed.append_page(first)
    assert sealed.finalize() == terminal
    sealed.close()
    for _ in range(2):
        reader = SQLiteSchedulerOfficialCaseReader.open(
            path,
            authentication_key=_KEY,
            authority_root_sha256=terminal.authority_root_sha256,
        )
        assert reader.authority_root_sha256 == terminal.authority_root_sha256
        reader.close()


def test_shared_builder_serializes_cross_thread_operations(tmp_path: Path) -> None:
    scopes = _case_scopes(locomo_count=1, longmemeval_count=1)
    builder = SQLiteSchedulerOfficialCaseAuthorityBuilder.create(
        tmp_path / "serialized.sqlite3", run_scopes=scopes, authentication_key=_KEY
    )
    page = SchedulerOfficialCaseAuthorityPage(0, (_case_row(scopes[0], 0),))
    started = Event()
    completed = Event()

    def append() -> None:
        started.set()
        try:
            builder.append_page(page)
        finally:
            completed.set()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with builder._handle.serialized():
                future = executor.submit(append)
                assert started.wait(timeout=2)
                assert not completed.wait(timeout=0.1)
            future.result(timeout=5)
        assert builder.next_sequence == 1
    finally:
        builder.close()


def test_authority_creation_does_not_mutate_process_umask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_umask(_mask: int) -> int:
        raise AssertionError("authority creation must not mutate process umask")

    monkeypatch.setattr(os, "umask", reject_umask)
    scopes = _case_scopes(locomo_count=1, longmemeval_count=1)
    terminal = _build_cases(tmp_path / "no-umask.sqlite3", scopes)
    assert terminal.case_count == 2


@pytest.mark.parametrize("mutation", ["schema", "row", "root", "delete", "reorder", "db"])
def test_case_database_schema_row_root_delete_and_reorder_tamper_fail_closed(
    tmp_path: Path, mutation: str
) -> None:
    scopes = _case_scopes()
    path = tmp_path / f"case-tamper-{mutation}.sqlite3"
    terminal = _build_cases(path, scopes)
    if mutation == "db":
        with path.open("r+b") as stream:
            stream.seek(0)
            stream.write(b"not-a-sqlite-database")
    else:
        with sqlite3.connect(path) as connection:
            if mutation == "schema":
                connection.execute("CREATE TABLE injected(value TEXT)")
            elif mutation == "row":
                connection.execute(
                    "UPDATE official_cases SET case_json=? WHERE sequence=0",
                    (json.dumps({"tampered": True}, separators=(",", ":")),),
                )
            elif mutation == "root":
                raw = connection.execute("SELECT terminal_json FROM authority_meta").fetchone()[0]
                payload = json.loads(raw)
                payload["authority_root_sha256"] = "f" * 64
                connection.execute(
                    "UPDATE authority_meta SET terminal_json=?",
                    (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
                )
            elif mutation == "delete":
                connection.execute("DELETE FROM official_cases WHERE sequence=0")
            else:
                connection.execute("UPDATE official_cases SET sequence=99 WHERE sequence=0")
    with pytest.raises(SchedulerOfficialAuthorityError):
        SQLiteSchedulerOfficialCaseReader.open(
            path,
            authentication_key=_KEY,
            authority_root_sha256=terminal.authority_root_sha256,
        )


def test_wrong_key_path_replacement_delete_symlink_hardlink_and_parent_mode_fail(
    tmp_path: Path,
) -> None:
    scopes = _case_scopes()
    path = tmp_path / "file-security.sqlite3"
    terminal = _build_cases(path, scopes)
    with pytest.raises(SchedulerOfficialAuthorityError, match="authentication"):
        SQLiteSchedulerOfficialCaseReader.open(
            path,
            authentication_key=_OTHER_KEY,
            authority_root_sha256=terminal.authority_root_sha256,
        )

    reader = SQLiteSchedulerOfficialCaseReader.open(
        path, authentication_key=_KEY, authority_root_sha256=terminal.authority_root_sha256
    )
    moved = tmp_path / "moved.sqlite3"
    path.rename(moved)
    path.touch(mode=0o600)
    with pytest.raises(SchedulerOfficialAuthorityError, match="replaced"):
        _ = reader.authority_root_sha256
    with pytest.raises(SchedulerOfficialAuthorityError):
        reader.close()
    path.unlink()
    moved.rename(path)

    reader = SQLiteSchedulerOfficialCaseReader.open(
        path, authentication_key=_KEY, authority_root_sha256=terminal.authority_root_sha256
    )
    path.unlink()
    with pytest.raises(SchedulerOfficialAuthorityError):
        reader.read_exact(key=_case_key(scopes[0], 0, terminal.authority_root_sha256))
    with pytest.raises(SchedulerOfficialAuthorityError):
        reader.close()

    assert _build_cases(path, scopes) == terminal
    path.rename(moved)
    path.symlink_to(moved)
    with pytest.raises(SchedulerOfficialAuthorityError):
        SQLiteSchedulerOfficialCaseReader.open(
            path, authentication_key=_KEY, authority_root_sha256=terminal.authority_root_sha256
        )
    path.unlink()
    moved.rename(path)
    hardlink = tmp_path / "hardlink.sqlite3"
    os.link(path, hardlink)
    with pytest.raises(SchedulerOfficialAuthorityError, match="unsafe"):
        SQLiteSchedulerOfficialCaseReader.open(
            path, authentication_key=_KEY, authority_root_sha256=terminal.authority_root_sha256
        )
    hardlink.unlink()
    tmp_path.chmod(0o755)
    try:
        with pytest.raises(SchedulerOfficialAuthorityError, match="parent_unsafe"):
            SQLiteSchedulerOfficialCaseReader.open(
                path,
                authentication_key=_KEY,
                authority_root_sha256=terminal.authority_root_sha256,
            )
    finally:
        tmp_path.chmod(0o700)


def test_retrieval_read_is_bounded_to_fifty_and_tamper_fails(tmp_path: Path) -> None:
    scopes = _case_scopes(locomo_count=1, longmemeval_count=1)
    case_path = tmp_path / "retrieval-cases.sqlite3"
    case_terminal = _build_cases(case_path, scopes)
    case_reader = SQLiteSchedulerOfficialCaseReader.open(
        case_path,
        authentication_key=_KEY,
        authority_root_sha256=case_terminal.authority_root_sha256,
    )
    retrieval_path = tmp_path / "retrieval-bounded.sqlite3"
    retrieval_scopes, terminal = _build_retrieval(
        retrieval_path, scopes, case_terminal, case_reader, memory_count=50
    )
    reader = SQLiteSchedulerRetrievalEvidenceReader.open(
        retrieval_path,
        authentication_key=_KEY,
        authority_root_sha256=terminal.authority_root_sha256,
        case_authority_root_sha256=case_terminal.authority_root_sha256,
    )
    case_read = case_reader.read_exact(
        key=_case_key(scopes[0], 0, case_terminal.authority_root_sha256)
    )
    statements = []
    reader._handle.connection.set_trace_callback(statements.append)
    key = _retrieval_key(retrieval_scopes[0], case_read, 0, terminal.authority_root_sha256)
    result = reader.read_exact(key=key)
    assert len(result.memories) == 50
    assert tuple(item.rank for item in result.memories) == tuple(range(1, 51))
    assert len([sql for sql in statements if "FROM retrieval_groups" in sql]) == 1
    assert len([sql for sql in statements if "FROM retrieval_rows" in sql]) == 1
    reader.close()
    case_reader.close()

    with sqlite3.connect(retrieval_path) as connection:
        first, second = connection.execute(
            """SELECT memory_json FROM retrieval_rows
               WHERE group_sequence=0 AND rank IN (1,2) ORDER BY rank"""
        ).fetchall()
        connection.execute(
            """UPDATE retrieval_rows SET memory_json=CASE rank WHEN 1 THEN ? ELSE ? END
               WHERE group_sequence=0 AND rank IN (1,2)""",
            (second[0], first[0]),
        )
    with pytest.raises(SchedulerOfficialAuthorityError):
        SQLiteSchedulerRetrievalEvidenceReader.open(
            retrieval_path,
            authentication_key=_KEY,
            authority_root_sha256=terminal.authority_root_sha256,
            case_authority_root_sha256=case_terminal.authority_root_sha256,
        )


@pytest.mark.parametrize(
    "cross_wire",
    ["run", "profile", "dataset", "case", "backend", "target", "cutoff", "case_root"],
)
def test_exact_read_rejects_cross_wired_case_and_retrieval_keys(
    tmp_path: Path, cross_wire: str
) -> None:
    scopes = _case_scopes(locomo_count=1, longmemeval_count=1)
    case_path = tmp_path / f"cross-case-{cross_wire}.sqlite3"
    case_terminal = _build_cases(case_path, scopes)
    case_reader = SQLiteSchedulerOfficialCaseReader.open(
        case_path,
        authentication_key=_KEY,
        authority_root_sha256=case_terminal.authority_root_sha256,
    )
    exact_case_key = _case_key(scopes[0], 0, case_terminal.authority_root_sha256)
    if cross_wire in {"run", "profile", "dataset", "case"}:
        replacements = {
            "run": {"run_authority_sha256": _sha("foreign-run")},
            "profile": {"publishable_profile_sha256": _sha("foreign-profile")},
            "dataset": {"dataset_sha256": _sha("foreign-dataset")},
            "case": {"case_id": "foreign-case"},
        }
        with pytest.raises(SchedulerOfficialAuthorityError):
            case_reader.read_exact(key=replace(exact_case_key, **replacements[cross_wire]))
        case_reader.close()
        return

    retrieval_path = tmp_path / f"cross-retrieval-{cross_wire}.sqlite3"
    retrieval_scopes, terminal = _build_retrieval(
        retrieval_path, scopes, case_terminal, case_reader
    )
    retrieval_reader = SQLiteSchedulerRetrievalEvidenceReader.open(
        retrieval_path,
        authentication_key=_KEY,
        authority_root_sha256=terminal.authority_root_sha256,
        case_authority_root_sha256=case_terminal.authority_root_sha256,
    )
    case_read = case_reader.read_exact(key=exact_case_key)
    key = _retrieval_key(retrieval_scopes[0], case_read, 0, terminal.authority_root_sha256)
    if cross_wire == "backend":
        key = replace(key, backend_role="mem0")
    elif cross_wire == "target":
        key = replace(key, target_identity_sha256=_sha("foreign-target"))
    elif cross_wire == "case_root":
        key = replace(key, case_key=replace(key.case_key, authority_root_sha256=_sha("foreign")))
    else:
        object.__setattr__(key, "cutoff", 49)
    with pytest.raises(SchedulerRunnerError):
        retrieval_reader.read_exact(key=key)
    retrieval_reader.close()
    case_reader.close()

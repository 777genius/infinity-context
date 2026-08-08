from __future__ import annotations

import pytest
from infinity_context_server import memory_comparison_managed_mem0_v5_projector as projector
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_record,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)


def _longmemeval_case(
    *,
    session_date: str | None,
    timestamp: int | None,
) -> ManagedRunCase:
    public_case = PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id="e47becba",
        question="Hidden evaluator question",
        expected_terms=("hidden-gold",),
        conversations=(
            BenchmarkConversationInput(
                messages=(
                    BenchmarkMessageInput(
                        "user",
                        "I started reading a new book.",
                        timestamp=timestamp,
                    ),
                    BenchmarkMessageInput(
                        "assistant",
                        "What book did you choose?",
                        timestamp=timestamp,
                    ),
                ),
                source_external_id="e47becba-session-1",
                session_external_id="session-1",
                session_date=session_date,
                timestamp=timestamp,
            ),
        ),
        memory_scope_external_ref="e47becba-corpus",
        thread_external_ref="e47becba-thread",
    )
    record = _managed_corpus_record(public_case)
    return ManagedRunCase(public_case.case_id, str(record["corpus_id"]), record)


def test_official_longmemeval_session_date_projects_with_matching_utc_timestamp() -> None:
    authority = ManagedMem0V5ManifestProjector().project(
        (
            _longmemeval_case(
                session_date="2023/05/20 (Sat) 02:21",
                timestamp=1_684_549_260,
            ),
        ),
        current_date="2026-08-08",
    )

    assert authority.operation_count == 1
    assert authority.units[0].observation_date == "2023-05-20"


def test_longmemeval_session_date_rejects_timestamp_date_disagreement() -> None:
    case = _longmemeval_case(
        session_date="2023/05/21 (Sun) 02:21",
        timestamp=1_684_549_260,
    )

    with pytest.raises(ManagedRunError, match="differs from source timestamp"):
        ManagedMem0V5ManifestProjector().project(
            (case,),
            current_date="2026-08-08",
        )


def test_longmemeval_timestamp_precedes_current_date_fallback() -> None:
    authority = ManagedMem0V5ManifestProjector().project(
        (_longmemeval_case(session_date=None, timestamp=1_684_549_260),),
        current_date="2026-08-08",
    )

    assert authority.units[0].observation_date == "2023-05-20"


@pytest.mark.parametrize("source_timestamp", [True, 10**30])
def test_authoritative_source_timestamp_rejects_bool_and_out_of_range(
    source_timestamp: object,
) -> None:
    with pytest.raises(ManagedRunError, match="source timestamp is invalid"):
        projector._source_date(
            None,
            "2026-08-08",
            source_timestamp=source_timestamp,
            timestamp_is_authoritative=True,
        )


@pytest.mark.parametrize(
    "session_date",
    [
        "2023/05/20 (Sam) 02:21",
        "2023/05/20 (Sun) 02:21",
        "05/20/2023 02:21",
    ],
)
def test_official_longmemeval_date_rejects_locale_or_weekday_ambiguity(
    session_date: str,
) -> None:
    with pytest.raises(ManagedRunError, match="observation date is invalid"):
        projector._source_date(
            session_date,
            "2026-08-08",
            source_timestamp=1_684_549_260,
            timestamp_is_authoritative=True,
        )


def test_current_date_fallback_requires_both_source_date_and_timestamp_absent() -> None:
    assert (
        projector._source_date(
            None,
            "2026-08-08",
            source_timestamp=None,
            timestamp_is_authoritative=True,
        )
        == "2026-08-08"
    )

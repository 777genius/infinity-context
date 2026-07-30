from __future__ import annotations

import pytest
from infinity_context_server.longmemeval_session_identity import (
    LONGMEMEVAL_SESSION_ALIAS_PREFIX,
    LONGMEMEVAL_SESSION_IDENTITY_SCHEMA,
    LongMemEvalSessionIdentityError,
    build_longmemeval_session_identity,
)


def test_identity_uses_neutral_ordinal_aliases_and_maps_answers_post_hoc() -> None:
    raw_ids = (
        "answer_primary",
        "haystack-remote-secret",
        "noans-marker",
        "has_answer-marker",
        "original-session-id",
    )
    identity = build_longmemeval_session_identity(raw_ids, session_count=len(raw_ids))

    assert LONGMEMEVAL_SESSION_IDENTITY_SCHEMA == "longmemeval_neutral_ordinal_v1"
    assert identity.aliases == (
        "session-0001",
        "session-0002",
        "session-0003",
        "session-0004",
        "session-0005",
    )
    assert identity.alias_for_index(0) == "session-0001"
    assert identity.alias_for_raw_id(" haystack-remote-secret ") == "session-0002"
    assert identity.answer_aliases(("original-session-id", "answer_primary")) == (
        "session-0005",
        "session-0001",
    )

    public_text = repr(identity) + repr(identity.aliases)
    for forbidden in (*raw_ids, "answer_", "haystack", "noans", "has_answer"):
        assert forbidden not in public_text


def test_aliases_are_stable_by_ordinal_instead_of_raw_identifier_content() -> None:
    first = build_longmemeval_session_identity(("raw-a", "raw-b"), session_count=2)
    second = build_longmemeval_session_identity(("unrelated-x", "unrelated-y"), session_count=2)

    assert first.aliases == second.aliases == ("session-0001", "session-0002")
    assert first.alias_for_raw_id("raw-b") == second.alias_for_raw_id("unrelated-y")
    assert all(alias.startswith(LONGMEMEVAL_SESSION_ALIAS_PREFIX) for alias in first.aliases)


@pytest.mark.parametrize(
    ("raw_ids", "session_count"),
    [
        (("raw-a",), 2),
        (("session-0001",), 1),
    ],
)
def test_identity_rejects_missing_duplicate_or_ambiguous_raw_ids(
    raw_ids: object,
    session_count: int,
) -> None:
    with pytest.raises(LongMemEvalSessionIdentityError):
        build_longmemeval_session_identity(raw_ids, session_count=session_count)


def test_duplicate_filler_ids_are_allowed_but_raw_lookup_is_ambiguous() -> None:
    identity = build_longmemeval_session_identity(
        ("duplicate-filler", "duplicate-filler", "answer-unique"),
        session_count=3,
    )

    assert identity.aliases == ("session-0001", "session-0002", "session-0003")
    assert identity.answer_aliases(("answer-unique",)) == ("session-0003",)
    with pytest.raises(LongMemEvalSessionIdentityError, match="ambiguous"):
        identity.alias_for_raw_id("duplicate-filler")
    with pytest.raises(LongMemEvalSessionIdentityError, match="ambiguous"):
        identity.answer_aliases(("duplicate-filler",))


@pytest.mark.parametrize(
    "raw_ids",
    [None, True, False, "raw-a", b"raw-a", {"raw-a": 1}, ("raw-a", True), ("",)],
)
def test_identity_rejects_malformed_session_identifier_inputs(raw_ids: object) -> None:
    with pytest.raises(LongMemEvalSessionIdentityError):
        build_longmemeval_session_identity(raw_ids, session_count=1)


@pytest.mark.parametrize("session_count", [True, False, None, "1", 0, -1])
def test_identity_rejects_malformed_session_counts(session_count: object) -> None:
    with pytest.raises(LongMemEvalSessionIdentityError):
        build_longmemeval_session_identity(
            ("raw-a",),
            session_count=session_count,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "answer_ids",
    [
        None,
        True,
        "raw-a",
        b"raw-a",
        (),
        ("missing",),
        ("raw-a", "raw-a"),
        ("raw-a", " raw-a "),
        (False,),
    ],
)
def test_answer_aliases_reject_missing_duplicate_and_malformed_ids(answer_ids: object) -> None:
    identity = build_longmemeval_session_identity(("raw-a", "raw-b"), session_count=2)

    with pytest.raises(LongMemEvalSessionIdentityError):
        identity.answer_aliases(answer_ids)


@pytest.mark.parametrize("index", [True, False, -1, 2, 1.0, "1"])
def test_alias_for_index_rejects_bool_non_integer_and_out_of_range(index: object) -> None:
    identity = build_longmemeval_session_identity(("raw-a", "raw-b"), session_count=2)

    with pytest.raises(LongMemEvalSessionIdentityError):
        identity.alias_for_index(index)  # type: ignore[arg-type]

"""LongMemEval normalization for pair-level comparison ingestion."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast

from infinity_context_core.application.sensitive_text import redact_sensitive_text

from infinity_context_server.memory_comparison_case_identity import (
    safe_benchmark_identifier,
)
from infinity_context_server.public_benchmark import (
    _first_str,
    _is_official_longmemeval_row,
    _official_longmemeval_case,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkMessageInput,
    BenchmarkMessageRole,
    PublicBenchmarkCase,
)

_DATE_FORMATS = (
    "%Y/%m/%d (%a) %H:%M",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)
_MESSAGE_ROLES = frozenset({"user", "assistant", "system"})


@dataclass(frozen=True)
class _SessionInput:
    original_index: int
    messages: tuple[object, ...]
    external_id: str
    date: str | None
    timestamp: int | None


def official_longmemeval_pair_case(raw: Mapping[str, object]) -> PublicBenchmarkCase:
    """Build one case whose conversations are chronological message pairs."""

    case_id = _longmemeval_case_id(raw)
    canonical_raw = dict(raw)
    canonical_raw["question_id"] = case_id
    canonical = _official_longmemeval_case(canonical_raw)
    return replace(
        canonical,
        case_id=case_id,
        documents=(),
        memory_scope_external_ref=f"longmemeval-{case_id}",
        thread_external_ref=f"longmemeval-{case_id}",
        conversations=_pair_conversations(raw, case_id=case_id),
    )


def official_longmemeval_pair_cases(payload: object) -> tuple[PublicBenchmarkCase, ...]:
    if isinstance(payload, Mapping):
        if _is_official_longmemeval_row(payload):
            return (official_longmemeval_pair_case(payload),)
        for key in ("data", "cases", "items"):
            if key in payload:
                return official_longmemeval_pair_cases(payload[key])
        return ()
    if isinstance(payload, Sequence) and not isinstance(payload, str | bytes):
        cases: list[PublicBenchmarkCase] = []
        for item in payload:
            cases.extend(official_longmemeval_pair_cases(item))
        return tuple(cases)
    return ()


def _pair_conversations(
    raw: Mapping[str, object],
    *,
    case_id: str,
) -> tuple[BenchmarkConversationInput, ...]:
    sessions = raw.get("haystack_sessions")
    if not isinstance(sessions, Sequence) or isinstance(sessions, str | bytes):
        return ()
    normalized = sorted(
        (
            session
            for index, value in enumerate(sessions)
            if (session := _normalize_session(raw, value, original_index=index)) is not None
        ),
        key=_chronology_key,
    )
    conversations: list[BenchmarkConversationInput] = []
    for session in normalized:
        for offset in range(0, len(session.messages), 2):
            pair_index = offset // 2
            pair_id = safe_benchmark_identifier(
                f"longmemeval:{case_id}:session:{session.original_index + 1}:pair:{pair_index + 1}",
                max_chars=240,
            )
            messages = tuple(
                message
                for position, value in enumerate(session.messages[offset : offset + 2], start=1)
                if (
                    message := _normalize_message(
                        value,
                        pair_id=pair_id,
                        position=position,
                        timestamp=session.timestamp,
                    )
                )
                is not None
            )
            if not messages:
                continue
            conversations.append(
                BenchmarkConversationInput(
                    messages=messages,
                    source_external_id=pair_id,
                    session_external_id=session.external_id,
                    session_date=session.date,
                    timestamp=session.timestamp,
                    metadata={
                        "session_original_index": session.original_index,
                        "pair_index": pair_index,
                    },
                )
            )
    return tuple(conversations)


def _normalize_session(
    raw: Mapping[str, object],
    value: object,
    *,
    original_index: int,
) -> _SessionInput | None:
    messages = _session_messages(value)
    if messages is None:
        return None
    raw_id = _sequence_text(raw.get("haystack_session_ids"), original_index)
    raw_date = _sequence_text(raw.get("haystack_dates"), original_index)
    if isinstance(value, Mapping):
        raw_id = raw_id or _first_str(value, "session_id", "id")
        raw_date = raw_date or _first_str(
            value,
            "date",
            "date_time",
            "datetime",
            "timestamp",
        )
    external_id = safe_benchmark_identifier(
        raw_id or f"session-{original_index + 1}",
        max_chars=160,
    )
    date = _safe_optional_text(raw_date, max_chars=120)
    return _SessionInput(
        original_index=original_index,
        messages=messages,
        external_id=external_id,
        date=date,
        timestamp=_date_to_epoch(raw_date),
    )


def _session_messages(value: object) -> tuple[object, ...] | None:
    if isinstance(value, Mapping):
        value = value.get("messages")
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return None
    return tuple(value)


def _normalize_message(
    value: object,
    *,
    pair_id: str,
    position: int,
    timestamp: int | None,
) -> BenchmarkMessageInput | None:
    if not isinstance(value, Mapping):
        return None
    raw_role = _first_str(value, "role", "speaker", "author")
    role = raw_role.casefold() if raw_role else ""
    if role not in _MESSAGE_ROLES:
        return None
    content = _message_content(value)
    if content is None:
        return None
    message_id = safe_benchmark_identifier(
        f"{pair_id}:message:{position}",
        max_chars=240,
    )
    return BenchmarkMessageInput(
        role=cast(BenchmarkMessageRole, role),
        content=content,
        source_external_id=message_id,
        timestamp=timestamp,
    )


def _message_content(value: Mapping[str, object]) -> str | None:
    for key in ("content", "text", "message"):
        content = value.get(key)
        if isinstance(content, str) and content.strip():
            return content
    return None


def _longmemeval_case_id(raw: Mapping[str, object]) -> str:
    explicit = _first_str(raw, "question_id", "id")
    if explicit:
        return safe_benchmark_identifier(explicit, max_chars=160)
    encoded = json.dumps(
        {
            "question": raw.get("question"),
            "answer": raw.get("answer"),
            "answer_session_ids": raw.get("answer_session_ids"),
            "haystack_session_ids": raw.get("haystack_session_ids"),
            "haystack_dates": raw.get("haystack_dates"),
            "messages": _identity_sessions(raw.get("haystack_sessions")),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _identity_sessions(value: object) -> list[list[dict[str, str | None]]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    sessions: list[list[dict[str, str | None]]] = []
    for session in value:
        messages = _session_messages(session)
        if messages is None:
            continue
        sessions.append(
            [
                {
                    "role": (_first_str(message, "role", "speaker", "author") or "").casefold(),
                    "content": _message_content(message),
                }
                for message in messages
                if isinstance(message, Mapping)
            ]
        )
    return sessions


def _chronology_key(session: _SessionInput) -> tuple[bool, int, int]:
    return (
        session.timestamp is None,
        session.timestamp if session.timestamp is not None else 0,
        session.original_index,
    )


def _date_to_epoch(value: str | None) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    for date_format in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(candidate, date_format)
        except ValueError:
            continue
        return int(parsed.replace(tzinfo=UTC).timestamp())
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.astimezone(UTC).timestamp())


def _sequence_text(value: object, index: int) -> str | None:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return None
    if index >= len(value):
        return None
    item = value[index]
    return item.strip() if isinstance(item, str) and item.strip() else None


def _safe_optional_text(value: str | None, *, max_chars: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return redact_sensitive_text(value.strip())[:max_chars]


# Compatibility names for private imports in the comparison package.
_official_longmemeval_pair_case = official_longmemeval_pair_case
_official_longmemeval_cases_from_payload = official_longmemeval_pair_cases

"""Structured and textual source session/turn identity parsing."""

from __future__ import annotations

import re
from collections.abc import (
    Mapping,
    Sequence,
)

from infinity_context_benchmarks.source_identity_safety import (
    _TURN_REF_PARTS_RE,
    _looks_like_raw_ref,
    _looks_like_source_identity_dedupe_key,
    _positive_int_string,
    _safe_turn_refs,
    safe_source_identity_ref,
    safe_turn_ref,
)

_TURN_REF_RE = re.compile(r"\bD\d+[:-]\d+\b", re.IGNORECASE)


_SOURCE_SESSION_TURN_RE = re.compile(
    r"(?:^|[:_-])session[-_](?P<session>\d+)[:_-](?P<turn_ref>D\d+[:-]\d+)"
    r"(?:$|[:_-](?:turn|chunk|fact)(?:[-_][^:]*)?$)",
    re.IGNORECASE,
)


_SOURCE_SESSION_RE = re.compile(
    r"(?:^|[:_\-\s])(?:session|conversation|conv|dialogue|dialog)"
    r"(?:[-_]\s*|\s+#?\s*)"
    r"(?P<session>\d+)"
    r"(?=$|[:_-](?!(?:D\d+[:-]\d+)\b))",
    re.IGNORECASE,
)


_EXPLICIT_SOURCE_SESSION_RE = re.compile(
    r"(?:^|[:_\-\s])session[-_]\s*(?P<session>\d+)(?=$|[:_\-\s])",
    re.IGNORECASE,
)


_TEXT_SESSION_TURN_RE = re.compile(
    r"\b(?:session|conversation|conv|dialogue|dialog)"
    r"(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)"
    r"(?:\s*[,;:/\-]\s*|\s+)"
    r"(?:turn\s*[:#-]?\s+)?(?P<turn_ref>D\d+[:-]\d+)\b",
    re.IGNORECASE,
)


_TEXT_SESSION_DATE_TURN_RE = re.compile(
    r"\b(?:session|conversation|conv|dialogue|dialog)"
    r"(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)"
    r"(?:\s*[,;:/\-]\s*|\s+)date:\s*[^.\n]{0,80}?\s"
    r"(?P<turn_ref>D\d+[:-]\d+)\b",
    re.IGNORECASE,
)


_TEXT_SESSION_PAREN_TURN_RE = re.compile(
    r"\b(?:session|conversation|conv|dialogue|dialog)"
    r"(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)"
    r"\s*\(\s*(?:turn\s*[:#-]?\s*)?(?P<turn_ref>D\d+[:-]\d+)\s*\)",
    re.IGNORECASE,
)


_TEXT_SESSION_BRACKET_TURN_RE = re.compile(
    r"\b(?:session|conversation|conv|dialogue|dialog)"
    r"(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)"
    r"\s*\[\s*(?:turn\s*[:#-]?\s*)?(?P<turn_ref>D\d+[:-]\d+)\s*\]",
    re.IGNORECASE,
)


_TEXT_SESSION_NUMERIC_TURN_RE = re.compile(
    r"\b(?:session|conversation|conv|dialogue|dialog)"
    r"(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)"
    r"(?:\s*[,;:/\-]\s*|\s+)"
    r"(?:turn|utt|utterance)\s*[:#-]?\s*(?P<turn>\d+)\b",
    re.IGNORECASE,
)


_TEXT_KEY_VALUE_SESSION_RE = re.compile(
    r"\b(?:source_)?(?:session|conversation|conv|dialogue|dialog)"
    r"(?:_id|_ids|_idx|_idxs|_index|_indexes|_key|_keys|_number|_numbers)?"
    r"\s*[=:]\s*"
    r"(?:session|conversation|conv|dialogue|dialog|D)?[-_\s#]*(?P<session>\d+)\b",
    re.IGNORECASE,
)


_TEXT_KEY_VALUE_TURN_REF_RE = re.compile(
    r"\b(?:source_)?(?:turn|utt|utterance|evidence)"
    r"(?:_id|_ids|_idx|_idxs|_index|_indexes|_ref|_refs|_number|_numbers)?"
    r"\s*[=:]\s*(?P<turn_ref>D\d+[:-]\d+)\b",
    re.IGNORECASE,
)


_TEXT_KEY_VALUE_TURN_NUMBER_RE = re.compile(
    r"\b(?:source_)?(?:turn|utt|utterance)"
    r"(?:_id|_ids|_idx|_idxs|_index|_indexes|_number|_numbers)?"
    r"\s*[=:]\s*(?P<turn>(?:turn|utt|utterance|t)?[-_:\s#]*\d+)\b",
    re.IGNORECASE,
)


_TEXT_TURN_SESSION_RE = re.compile(
    r"\b(?:turn\s*[:#-]?\s+)?(?P<turn_ref>D\d+[:-]\d+)\b"
    r"\s*(?:[,;:-]?\s+|\s+)"
    r"(?:in|from|for|within|during|of)\s+(?:the\s+)?"
    r"(?:session|conversation|conv|dialogue|dialog)"
    r"(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)\b",
    re.IGNORECASE,
)


_TEXT_TURN_PUNCT_SESSION_RE = re.compile(
    r"\b(?:turn\s*[:#-]?\s+)?(?P<turn_ref>D\d+[:-]\d+)\b"
    r"\s*[,;:/\-]\s*(?:the\s+)?"
    r"(?:session|conversation|conv|dialogue|dialog)"
    r"(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)\b",
    re.IGNORECASE,
)


_TEXT_TURN_PAREN_SESSION_RE = re.compile(
    r"\b(?:turn\s*[:#-]?\s+)?(?P<turn_ref>D\d+[:-]\d+)\b"
    r"\s*\(\s*(?:the\s+)?"
    r"(?:session|conversation|conv|dialogue|dialog)"
    r"(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)\s*\)",
    re.IGNORECASE,
)


_TEXT_TURN_BRACKET_SESSION_RE = re.compile(
    r"\b(?:turn\s*[:#-]?\s+)?(?P<turn_ref>D\d+[:-]\d+)\b"
    r"\s*\[\s*(?:the\s+)?"
    r"(?:session|conversation|conv|dialogue|dialog)"
    r"(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)\s*\]",
    re.IGNORECASE,
)


def _structured_turn_refs_from_mapping(
    value: Mapping[object, object],
) -> tuple[str, ...]:
    turn_ref = _first_safe_turn_ref_from_mapping_values(
        value,
        (
            "dia_id",
            "locomo_evidence_ref",
            "dialogue_turn_id",
            "locomo_dialogue_turn_id",
            "conversation_turn_ref",
            "conversation_turn_id",
            "conv_turn_ref",
            "conv_turn_id",
            "source_dia_id",
            "source_conversation_turn_ref",
            "source_conversation_turn_id",
            "source_dialogue_turn_id",
            "evidence_id",
            "evidence_ref",
            "source_evidence_ref",
            "source_turn_ref",
            "turn_ref",
            "source_turn_id",
            "turn_id",
        ),
    )
    if turn_ref:
        return (f"source_turn_refs:{turn_ref}",)
    dialogue = _dialogue_number_from_mapping(value)
    turns = _structured_turn_values_from_mapping(value)
    if not dialogue or not 0 < len(turns) <= 3:
        return ()
    return tuple(f"source_turn_refs:D{dialogue}:{turn}" for turn in turns)


def _structured_turn_values_from_mapping(
    value: Mapping[object, object],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            turn
            for key in (
                "source_turn_id",
                "source_turn",
                "source_turn_index",
                "source_evidence_ref",
                "source_evidence_refs",
                "evidence_ref",
                "evidence_refs",
                "evidence_id",
                "evidence_ids",
                "dialogue_turn_id",
                "dialogue_turn_ids",
                "locomo_evidence_ref",
                "locomo_evidence_refs",
                "locomo_dialogue_turn_id",
                "locomo_dialogue_turn_ids",
                "locomo_turn",
                "locomo_turn_idx",
                "locomo_turn_id",
                "locomo_turn_ids",
                "locomo_turn_index",
                "locomo_turn_indexes",
                "locomo_turn_number",
                "locomo_turn_numbers",
                "conversation_turn",
                "conversation_turn_idx",
                "conversation_turn_id",
                "conversation_turn_ids",
                "conversation_turn_index",
                "conversation_turn_indexes",
                "conversation_turn_number",
                "conversation_turn_numbers",
                "conv_turn",
                "conv_turn_idx",
                "conv_turn_id",
                "conv_turn_ids",
                "conv_turn_index",
                "conv_turn_indexes",
                "conv_turn_number",
                "conv_turn_numbers",
                "source_conversation_turn",
                "source_conversation_turn_idx",
                "source_conversation_turn_id",
                "source_conversation_turn_ids",
                "source_conversation_turn_index",
                "source_conversation_turn_indexes",
                "source_conversation_turn_number",
                "source_conversation_turn_numbers",
                "source_dialogue_turn_id",
                "source_dialogue_turn_ids",
                "source_turn_ref",
                "source_turn_refs",
                "source_turn_idx",
                "source_utterance",
                "source_utterance_idx",
                "source_utterance_id",
                "source_utterance_ids",
                "source_utterance_index",
                "source_utterance_indexes",
                "source_utterance_number",
                "source_utterance_numbers",
                "turn",
                "turn_idx",
                "turn_ref",
                "turn_refs",
                "turn_id",
                "turn_ids",
                "turn_index",
                "turn_number",
                "utt",
                "utt_idx",
                "utt_id",
                "utt_ids",
                "utt_index",
                "utt_indexes",
                "utt_number",
                "utt_numbers",
                "utterance_idx",
                "utterance_id",
                "utterance_ids",
                "utterance_index",
                "utterance_indexes",
                "utterance_number",
                "utterance_numbers",
            )
            for turn in _positive_int_values(value.get(key))
        )
    )


def _positive_int_values(value: object) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        return ()
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(
            turn
            for item in value
            for turn in _positive_int_values(item)
        )
    turn = _positive_int_string(value)
    return (turn,) if turn else ()


def _structured_session_ref_from_mapping(value: Mapping[object, object]) -> str:
    for key in (
        "locomo_session_index",
        "locomo_session_indexes",
        "locomo_session_ids",
        "locomo_session_key",
        "locomo_session_keys",
        "locomo_session",
        "locomo_sessions",
        "locomo_session_idx",
        "locomo_session_idxs",
        "locomo_session_number",
        "locomo_session_numbers",
        "locomo_conversation",
        "locomo_conversations",
        "locomo_conversation_id",
        "locomo_conversation_ids",
        "locomo_conversation_idx",
        "locomo_conversation_idxs",
        "locomo_conversation_index",
        "locomo_conversation_indexes",
        "locomo_conversation_key",
        "locomo_conversation_keys",
        "locomo_conversation_number",
        "locomo_conversation_numbers",
        "source_session_id",
        "source_session_ids",
        "source_session_idx",
        "source_session_idxs",
        "source_session_index",
        "source_session_indexes",
        "source_session_key",
        "source_session_keys",
        "source_session",
        "source_sessions",
        "source_session_number",
        "source_session_numbers",
        "session",
        "sessions",
        "session_id",
        "session_ids",
        "session_idx",
        "session_idxs",
        "session_index",
        "session_indexes",
        "session_key",
        "session_keys",
        "session_number",
        "session_numbers",
        "session_order",
        "session_orders",
        "conversation",
        "conversations",
        "conversation_id",
        "conversation_ids",
        "conversation_idx",
        "conversation_idxs",
        "conversation_index",
        "conversation_indexes",
        "conversation_key",
        "conversation_keys",
        "conversation_number",
        "conversation_numbers",
        "source_conversation_id",
        "source_conversation_ids",
        "source_conversation_idx",
        "source_conversation_idxs",
        "source_conversation_index",
        "source_conversation_indexes",
        "source_conversation_key",
        "source_conversation_keys",
        "source_conversation",
        "source_conversations",
        "source_conversation_number",
        "source_conversation_numbers",
        "conv",
        "convs",
        "conv_id",
        "conv_ids",
        "conv_idx",
        "conv_idxs",
        "conv_index",
        "conv_indexes",
        "conv_key",
        "conv_keys",
        "conv_number",
        "conv_numbers",
    ):
        session = _single_dialogue_number_from_value(value.get(key))
        if session:
            return f"session_{session}"
    return ""


def _first_safe_turn_ref_from_mapping_values(
    value: Mapping[object, object],
    keys: Sequence[str],
) -> str:
    for key in keys:
        if turn_ref := safe_turn_ref(value.get(key)):
            return turn_ref
    return ""


def _dialogue_number_from_mapping(value: Mapping[object, object]) -> str:
    for key in (
        "source_dialogue_id",
        "source_dialogue_ids",
        "source_dialogue",
        "source_dialogues",
        "source_dialogue_idx",
        "source_dialogue_idxs",
        "source_dialogue_index",
        "source_dialogue_indexes",
        "source_dialog",
        "source_dialogs",
        "source_dialog_idx",
        "source_dialog_idxs",
        "dialogue_id",
        "dialogue_ids",
        "dialogue",
        "dialogues",
        "dialogue_idx",
        "dialogue_idxs",
        "dialogue_index",
        "dialogue_indexes",
        "dialog",
        "dialogs",
        "dialog_idx",
        "dialog_idxs",
        "dia_id",
        "dia_ids",
        "source_dia_id",
        "source_dia_ids",
        "locomo_session_index",
        "locomo_session_indexes",
        "locomo_session_ids",
        "locomo_session_key",
        "locomo_session_keys",
        "locomo_session",
        "locomo_sessions",
        "locomo_session_idx",
        "locomo_session_idxs",
        "locomo_session_number",
        "locomo_session_numbers",
        "locomo_conversation",
        "locomo_conversations",
        "locomo_conversation_id",
        "locomo_conversation_ids",
        "locomo_conversation_idx",
        "locomo_conversation_idxs",
        "locomo_conversation_index",
        "locomo_conversation_indexes",
        "locomo_conversation_key",
        "locomo_conversation_keys",
        "locomo_conversation_number",
        "locomo_conversation_numbers",
        "session",
        "sessions",
        "session_key",
        "session_keys",
        "session_id",
        "session_ids",
        "session_idx",
        "session_idxs",
        "session_index",
        "session_indexes",
        "session_number",
        "session_numbers",
        "session_order",
        "session_orders",
        "source_session_id",
        "source_session_ids",
        "source_session_idx",
        "source_session_idxs",
        "source_session_index",
        "source_session_indexes",
        "source_session_key",
        "source_session_keys",
        "source_session",
        "source_sessions",
        "source_session_number",
        "source_session_numbers",
        "conversation",
        "conversations",
        "conversation_id",
        "conversation_ids",
        "conversation_idx",
        "conversation_idxs",
        "conversation_index",
        "conversation_indexes",
        "conversation_key",
        "conversation_keys",
        "conversation_number",
        "conversation_numbers",
        "source_conversation_id",
        "source_conversation_ids",
        "source_conversation_idx",
        "source_conversation_idxs",
        "source_conversation_index",
        "source_conversation_indexes",
        "source_conversation_key",
        "source_conversation_keys",
        "source_conversation",
        "source_conversations",
        "source_conversation_number",
        "source_conversation_numbers",
        "conv",
        "convs",
        "conv_id",
        "conv_ids",
        "conv_idx",
        "conv_idxs",
        "conv_index",
        "conv_indexes",
        "conv_key",
        "conv_keys",
        "conv_number",
        "conv_numbers",
    ):
        dialogue = _single_dialogue_number_from_value(value.get(key))
        if dialogue:
            return dialogue
    return ""


def _single_dialogue_number_from_value(value: object) -> str:
    if isinstance(value, Mapping):
        return ""
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        values = tuple(
            dict.fromkeys(
                dialogue
                for item in value
                for dialogue in (_dialogue_number_from_value(item),)
                if dialogue
            )
        )
        return values[0] if len(values) == 1 else ""
    return _dialogue_number_from_value(value)


def _dialogue_number_from_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if match := re.fullmatch(
        r"(?:(?:session|conversation|conv|dialogue|dialog)[-_\s#]*|D)?"
        r"(?P<number>\d+)",
        text,
        re.IGNORECASE,
    ):
        return match.group("number")
    return ""


def _source_turn_refs(
    source_refs: Sequence[str],
    *,
    include_exact_turn_refs: bool,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            ref
            for source_ref in source_refs
            for ref in _source_turn_refs_from_source_ref(
                source_ref,
                include_exact_turn_refs=include_exact_turn_refs,
            )
        )
    )


def _source_turn_refs_from_source_ref(
    source_ref: str,
    *,
    include_exact_turn_refs: bool,
) -> tuple[str, ...]:
    if turn_ref := safe_turn_ref(source_ref):
        return (turn_ref,) if include_exact_turn_refs else ()
    if safe_source_identity_ref(source_ref) or _looks_like_source_identity_dedupe_key(
        source_ref
    ):
        return _safe_turn_refs(_TURN_REF_RE.findall(source_ref))
    if _looks_like_raw_ref(source_ref) or _SOURCE_SESSION_TURN_RE.search(source_ref):
        return _safe_turn_refs(_TURN_REF_RE.findall(source_ref))
    if re.search(r"(?:^|[:_-])(?:turn|chunk|fact):D\d+[:-]\d+\b", source_ref, re.I):
        return _safe_turn_refs(_TURN_REF_RE.findall(source_ref))
    return ()


def _source_session_turn_refs(source_refs: Sequence[str]) -> tuple[str, ...]:
    refs: list[str] = []
    session_refs: list[str] = []
    turn_refs: list[str] = []
    for source_ref in source_refs:
        session_refs.extend(_source_session_refs(source_ref))
        safe_ref = safe_source_identity_ref(source_ref)
        if safe_ref and safe_ref.startswith("source_session_turn_refs:"):
            refs.append(safe_ref.removeprefix("source_session_turn_refs:"))
            continue
        match = _SOURCE_SESSION_TURN_RE.search(source_ref)
        if match is None:
            turn_refs.extend(
                _source_turn_refs_from_source_ref(
                    source_ref,
                    include_exact_turn_refs=True,
                )
            )
            refs.extend(_session_turn_refs_from_text(source_ref))
            continue
        turn_ref = safe_turn_ref(match.group("turn_ref"))
        if turn_ref:
            refs.append(f"session_{match.group('session')}:{turn_ref}")
    refs.extend(_session_turn_refs_from_split_refs(session_refs, turn_refs))
    return tuple(dict.fromkeys(refs))


def _source_session_refs(source_ref: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            f"session_{match.group('session')}"
            for match in _SOURCE_SESSION_RE.finditer(source_ref or "")
        )
    )


def _session_turn_refs_from_split_refs(
    session_refs: Sequence[str],
    turn_refs: Sequence[str],
) -> tuple[str, ...]:
    session_numbers = tuple(
        dict.fromkeys(
            match.group("session")
            for ref in session_refs
            for match in (
                re.fullmatch(r"session[-_](?P<session>\d+)", ref, re.IGNORECASE),
            )
            if match is not None
        )
    )
    safe_turn_refs = _safe_turn_refs(turn_refs)
    if len(session_numbers) != 1 or not 0 < len(safe_turn_refs) <= 3:
        return ()
    session_number = session_numbers[0]
    return tuple(
        f"session_{session_number}:{turn_ref}"
        for turn_ref in safe_turn_refs
        if _turn_ref_dialogue_number(turn_ref) == session_number
    )


def _source_session_turn_mismatch(source_refs: Sequence[str]) -> bool:
    session_turn_refs = _source_session_turn_refs(source_refs)
    if session_turn_refs and any(
        _session_turn_ref_mismatch(ref) for ref in session_turn_refs
    ):
        return True

    session_numbers = _source_session_turn_ref_session_numbers(
        session_turn_refs
    ) or _source_ref_session_numbers(source_refs)
    if len(session_numbers) != 1:
        return False
    safe_turn_refs = _safe_turn_refs(
        _source_turn_refs(source_refs, include_exact_turn_refs=True)
    )
    if not 0 < len(safe_turn_refs) <= 3:
        return False
    session_number = session_numbers[0]
    return any(
        (dialogue_number := _turn_ref_dialogue_number(turn_ref))
        and dialogue_number != session_number
        for turn_ref in safe_turn_refs
    )


def _session_turn_ref_mismatch(session_turn_ref: str) -> bool:
    match = re.fullmatch(
        r"session[-_](?P<session>\d+):(?P<turn_ref>D\d+[:-]\d+)",
        session_turn_ref,
        re.IGNORECASE,
    )
    if match is None:
        return False
    dialogue_number = _turn_ref_dialogue_number(match.group("turn_ref"))
    return bool(dialogue_number and dialogue_number != match.group("session"))


def _source_session_turn_ref_session_numbers(
    source_session_turn_refs: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            match.group("session")
            for source_session_turn_ref in source_session_turn_refs
            for match in (
                re.match(
                    r"session[-_](?P<session>\d+):D\d+[:-]\d+$",
                    source_session_turn_ref,
                    re.IGNORECASE,
                ),
            )
            if match is not None
        )
    )


def _source_ref_session_numbers(source_refs: Sequence[str]) -> tuple[str, ...]:
    session_numbers: list[str] = []
    for source_ref in source_refs:
        explicit_numbers = tuple(
            match.group("session")
            for match in _EXPLICIT_SOURCE_SESSION_RE.finditer(source_ref)
        )
        session_refs = (
            tuple(f"session_{number}" for number in explicit_numbers)
            if explicit_numbers
            else _source_session_refs(source_ref)
        )
        session_numbers.extend(
            match.group("session")
            for session_ref in session_refs
            for match in (
                re.fullmatch(
                    r"session[-_](?P<session>\d+)",
                    session_ref,
                    re.IGNORECASE,
                ),
            )
            if match is not None
        )
    return tuple(dict.fromkeys(session_numbers))


def _turn_ref_dialogue_number(turn_ref: str) -> str:
    match = _TURN_REF_PARTS_RE.fullmatch(turn_ref)
    return match.group("dialogue") if match is not None else ""


def _session_turn_refs_from_text(
    text: str,
    *,
    require_dialogue_match: bool = True,
) -> tuple[str, ...]:
    refs: list[str] = []
    for pattern in (
        _TEXT_SESSION_TURN_RE,
        _TEXT_SESSION_DATE_TURN_RE,
        _TEXT_SESSION_PAREN_TURN_RE,
        _TEXT_SESSION_BRACKET_TURN_RE,
        _TEXT_TURN_SESSION_RE,
        _TEXT_TURN_PUNCT_SESSION_RE,
        _TEXT_TURN_PAREN_SESSION_RE,
        _TEXT_TURN_BRACKET_SESSION_RE,
    ):
        for match in pattern.finditer(text or ""):
            turn_ref = safe_turn_ref(match.group("turn_ref"))
            if turn_ref and (
                not require_dialogue_match
                or _turn_ref_dialogue_number(turn_ref) == match.group("session")
            ):
                refs.append(f"session_{match.group('session')}:{turn_ref}")
    refs.extend(
        f"session_{match.group('session')}:D{match.group('session')}:{turn}"
        for match in _TEXT_SESSION_NUMERIC_TURN_RE.finditer(text or "")
        for turn in (_positive_int_string(match.group("turn")),)
        if turn
    )
    refs.extend(
        _session_turn_refs_from_key_value_text(
            text or "",
            require_dialogue_match=require_dialogue_match,
        )
    )
    return tuple(dict.fromkeys(refs))


def _session_turn_refs_from_key_value_text(
    text: str,
    *,
    require_dialogue_match: bool,
) -> tuple[str, ...]:
    sessions = tuple(
        dict.fromkeys(
            match.group("session")
            for match in _TEXT_KEY_VALUE_SESSION_RE.finditer(text)
        )
    )
    if len(sessions) != 1:
        return ()
    session = sessions[0]
    refs: list[str] = []
    for match in _TEXT_KEY_VALUE_TURN_REF_RE.finditer(text):
        turn_ref = safe_turn_ref(match.group("turn_ref"))
        if turn_ref and (
            not require_dialogue_match
            or _turn_ref_dialogue_number(turn_ref) == session
        ):
            refs.append(f"session_{session}:{turn_ref}")
    refs.extend(
        f"session_{session}:D{session}:{turn}"
        for match in _TEXT_KEY_VALUE_TURN_NUMBER_RE.finditer(text)
        for turn in (_positive_int_string(match.group("turn")),)
        if turn
    )
    return tuple(dict.fromkeys(refs))


def _session_identity_refs(session_turn_refs: Sequence[str]) -> tuple[str, ...]:
    qualified = tuple(
        f"source_session_turn_refs:{ref}" for ref in sorted(session_turn_refs)
    )
    if _session_count(session_turn_refs) != 1:
        return qualified
    turn_refs: list[str] = []
    for session_ref in session_turn_refs:
        match = _TURN_REF_RE.search(session_ref)
        if match is not None:
            turn_ref = safe_turn_ref(match.group(0))
            if turn_ref:
                turn_refs.append(turn_ref)
    unqualified = tuple(
        f"source_turn_refs:{ref}"
        for ref in sorted(dict.fromkeys(turn_refs))
    )
    return (*qualified, *unqualified)


def _turn_refs_from_session_turn_refs(session_turn_refs: Sequence[str]) -> tuple[str, ...]:
    return _safe_turn_refs(
        match.group(0)
        for session_ref in session_turn_refs
        for match in (_TURN_REF_RE.search(session_ref),)
        if match is not None
    )


def _session_count(session_turn_refs: Sequence[str]) -> int:
    return len(
        {
            match.group("session")
            for ref in session_turn_refs
            if (
                match := re.search(
                    r"\bsession[-_](?P<session>\d+):D\d+[:-]\d+\b",
                    ref,
                    re.IGNORECASE,
                )
            )
        }
    )

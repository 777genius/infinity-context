"""Source-identity helpers for memory-comparison evidence diagnostics."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from infinity_context_core.application.sensitive_text import contains_sensitive_text

_TURN_REF_RE = re.compile(r"\bD\d+[:-]\d+\b", re.IGNORECASE)
_TURN_REF_PARTS_RE = re.compile(
    r"^D(?P<dialogue>\d+)[:-](?P<turn>\d+)$",
    re.IGNORECASE,
)
_DIALOGUE_REF_PARTS_RE = re.compile(r"^D(?P<dialogue>\d+)$", re.IGNORECASE)
_SOURCE_SESSION_TURN_RE = re.compile(
    r"(?:^|[:_-])session[-_](?P<session>\d+)[:_-](?P<turn_ref>D\d+[:-]\d+)"
    r"(?:$|[:_-](?:turn|chunk|fact)(?:[-_][^:]*)?$)",
    re.IGNORECASE,
)
_SOURCE_SESSION_RE = re.compile(
    r"(?:^|[:_\-\s])(?:session|dialogue|dialog)(?:[-_]\s*|\s+#?\s*)"
    r"(?P<session>\d+)"
    r"(?=$|[:_-](?!(?:D\d+[:-]\d+)\b))",
    re.IGNORECASE,
)
_TEXT_SESSION_TURN_RE = re.compile(
    r"\b(?:session|dialogue|dialog)(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)"
    r"\s*[,;:-]?\s+(?:turn\s*[:#-]?\s+)?(?P<turn_ref>D\d+[:-]\d+)\b",
    re.IGNORECASE,
)
_TEXT_SESSION_DATE_TURN_RE = re.compile(
    r"\b(?:session|dialogue|dialog)(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)"
    r"\s*[,;:-]?\s+date:\s*[^.\n]{0,80}?\s"
    r"(?P<turn_ref>D\d+[:-]\d+)\b",
    re.IGNORECASE,
)
_TEXT_TURN_SESSION_RE = re.compile(
    r"\b(?:turn\s*[:#-]?\s+)?(?P<turn_ref>D\d+[:-]\d+)\b"
    r"\s*(?:[,;:-]?\s+|\s+)"
    r"(?:in|from|for|within|during|of)\s+(?:the\s+)?"
    r"(?:session|dialogue|dialog)(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)\b",
    re.IGNORECASE,
)
_TEXT_TURN_PUNCT_SESSION_RE = re.compile(
    r"\b(?:turn\s*[:#-]?\s+)?(?P<turn_ref>D\d+[:-]\d+)\b"
    r"\s*[,;:-]\s*(?:the\s+)?"
    r"(?:session|dialogue|dialog)(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)\b",
    re.IGNORECASE,
)
_SAFE_SOURCE_IDENTITY_REF_RE = re.compile(
    r"^(?:(?P<turn_prefix>source_turn_refs):(?P<turn_ref>D\d+[:-]\d+)|"
    r"(?P<session_prefix>source_session_turn_refs):(?P<session>session[-_]\d+):"
    r"(?P<session_turn_ref>D\d+[:-]\d+))$",
    re.IGNORECASE,
)
_MAX_SAFE_SOURCE_IDENTITY_REF_LENGTH = 80
_MAX_SAFE_TURN_REF_LENGTH = 32
_MAX_SAFE_GENERIC_SOURCE_REF_LENGTH = 128
_MAX_SAFE_ITEM_ID_LENGTH = 128
_MAX_SAFE_SOURCE_LABEL_LENGTH = 64
_PRIVATE_PROVIDER_SOURCE_LABEL_PREFIXES = frozenset(
    {
        "backend",
        "graphiti",
        "mem0",
        "openai",
        "provider",
        "qdrant",
    }
)
_PRIVATE_PROVIDER_SOURCE_LABEL_SEPARATORS = (":", "-", "_", ".")
_INSTRUCTION_LIKE_ITEM_ID_RE = re.compile(
    r"\b(?:ignore\s+previous\s+instructions|reveal\s+(?:the\s+)?"
    r"(?:system|developer)\s+prompt|system\s+prompt|developer\s+message)\b",
    re.IGNORECASE,
)
_ABSOLUTE_PATH_REF_RE = re.compile(
    r"^(?:file://|~[/\\]|/|[A-Za-z]:[/\\])",
    re.IGNORECASE,
)
_PRIVATE_PATH_SEGMENTS = frozenset(
    {
        ".aws",
        ".azure",
        ".codex",
        ".config",
        ".gcp",
        ".gnupg",
        ".ssh",
        "private",
        "secrets",
    }
)
_PRIVATE_PATH_BASENAMES = frozenset(
    {
        ".env",
        "api_key",
        "api_key.json",
        "api-key.json",
        "auth.json",
        "credentials",
        "credentials.json",
        "secret",
        "secret.json",
        "secrets.json",
        "token",
        "token.json",
    }
)
_PRIVATE_PATH_NAME_MARKERS = (
    "api-key",
    "api_key",
    "auth",
    "credential",
    "secret",
    "token",
)
_NUMERIC_EVIDENCE_LIST_KEYS = frozenset(
    {
        "evidence_refs",
        "evidence_ids",
        "locomo_evidence_refs",
        "source_evidence_refs",
        "turn_ids",
    }
)
_NESTED_EVIDENCE_CONTEXT_KEYS = frozenset(
    {
        "evidence",
        "supporting_evidence",
        "supporting_facts",
    }
)


def safe_source_identity_ref(value: object) -> str | None:
    ref = str(value or "").strip()
    if not ref or len(ref) > _MAX_SAFE_SOURCE_IDENTITY_REF_LENGTH:
        return None
    match = _SAFE_SOURCE_IDENTITY_REF_RE.fullmatch(ref)
    if match is None:
        return None
    if match.group("turn_ref"):
        turn_ref = safe_turn_ref(match.group("turn_ref"))
        return f"source_turn_refs:{turn_ref}" if turn_ref else None
    session_turn_ref = safe_turn_ref(match.group("session_turn_ref"))
    if not session_turn_ref:
        return None
    return (
        "source_session_turn_refs:"
        f"{_normalized_session_ref(match.group('session'))}:{session_turn_ref}"
    )


def safe_turn_ref(value: object) -> str | None:
    ref = str(value or "").strip()
    if not ref or len(ref) > _MAX_SAFE_TURN_REF_LENGTH:
        return None
    match = _TURN_REF_PARTS_RE.fullmatch(ref)
    if match is None:
        return None
    return f"D{match.group('dialogue')}:{match.group('turn')}"


def safe_source_refs_for_output(source_refs: object) -> tuple[str, ...]:
    source_ref_values = _source_ref_values(source_refs)
    identity_source_ref_values = _identity_source_ref_values_for_output(
        source_ref_values
    )
    aggregate_identity_refs = source_identity_refs_from_source_refs(
        identity_source_ref_values
    )
    source_identity_refs = tuple(
        dict.fromkeys(
            (
                *(
                    ref
                    for raw_ref in source_ref_values
                    if str(raw_ref or "").strip().lower().startswith("source_identity:")
                    for ref in source_identity_refs_from_dedupe_key(raw_ref)
                ),
                *(
                    ref
                    for raw_ref in source_ref_values
                    if not safe_turn_ref(raw_ref)
                    if _source_ref_value_should_seed_output_identity(raw_ref)
                    for ref in _ordered_identity_refs_from_single_source_ref(
                        raw_ref,
                        aggregate_identity_refs,
                    )
                ),
                *aggregate_identity_refs,
            )
        )
    )
    refs: list[str] = []
    for raw_ref in source_ref_values:
        if (
            isinstance(raw_ref, str)
            and not _looks_like_source_identity_dedupe_key(raw_ref)
            and _SOURCE_SESSION_TURN_RE.search(raw_ref)
            and (generic_ref := _safe_generic_source_ref(raw_ref))
            and generic_ref not in refs
        ):
            refs.append(generic_ref)
    for ref in source_identity_refs:
        if ref not in refs:
            refs.append(ref)
    for raw_ref in source_ref_values:
        for ref in _safe_source_refs_for_output_value(raw_ref):
            if _safe_output_ref_is_covered_by_identity(ref, source_identity_refs):
                continue
            if ref and ref not in refs:
                refs.append(ref)
    return tuple(refs)


def safe_source_label_for_output(value: object) -> str | None:
    label = str(value or "").strip()
    if not label or len(label) > _MAX_SAFE_SOURCE_LABEL_LENGTH:
        return None
    if _looks_like_private_provider_source_label(label):
        return None
    return label


def looks_like_raw_source_ref(value: object) -> bool:
    """Return true for provider/private source references that must not be emitted."""
    return _looks_like_raw_ref(str(value or "").strip())


def safe_item_id_for_output(value: object) -> str:
    item_id = str(value or "").strip()
    if not item_id:
        return ""
    if _looks_like_raw_ref(item_id) or _INSTRUCTION_LIKE_ITEM_ID_RE.search(item_id):
        return ""
    if len(item_id) > _MAX_SAFE_ITEM_ID_LENGTH:
        return f"{item_id[: _MAX_SAFE_ITEM_ID_LENGTH - 3]}..."
    return item_id


def source_identity_refs_from_dedupe_key(value: object) -> tuple[str, ...]:
    key = str(value or "").strip()
    if not key:
        return ()
    key_lower = key.lower()
    if key_lower.startswith("source_identity:"):
        return _identity_refs_from_source_identity_values(
            _split_identity_refs(key[len("source_identity:") :])
        )
    for prefix in ("source_refs:", "refs:"):
        if key_lower.startswith(prefix):
            return _identity_refs_from_source_ref_values(
                _split_identity_refs(key[len(prefix) :])
            )
    for prefix in ("source_turn_refs:", "turn_refs:"):
        if not key_lower.startswith(prefix):
            continue
        return _safe_identity_refs(
            f"source_turn_refs:{ref}"
            for ref in _split_identity_refs(key[len(prefix) :])
        )
    if key_lower.startswith("source_session_turn_refs:"):
        return _safe_identity_refs(
            f"source_session_turn_refs:{ref}"
            for ref in _split_identity_refs(
                key[len("source_session_turn_refs:") :]
            )
        )
    return ()


def _safe_source_refs_for_output_value(value: object) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    identity_ref = safe_source_identity_ref(text)
    if identity_ref:
        return (identity_ref,)
    turn_ref = safe_turn_ref(text)
    if turn_ref:
        return (turn_ref,)
    dedupe_identity_refs = source_identity_refs_from_dedupe_key(text)
    if dedupe_identity_refs and _looks_like_source_identity_dedupe_key(text):
        return dedupe_identity_refs
    identity_refs = source_identity_refs_from_source_refs(
        (text,),
        include_exact_turn_refs=True,
    )
    if identity_refs:
        generic_ref = _safe_generic_source_ref(text)
        if generic_ref:
            return (generic_ref,)
        return identity_refs
    if _TURN_REF_RE.fullmatch(text):
        return ()
    if _TURN_REF_RE.search(text):
        generic_ref = _safe_generic_source_ref(text)
        return (generic_ref,) if generic_ref else ()
    generic_ref = _safe_generic_source_ref(text)
    if generic_ref:
        return (generic_ref,)
    return ()


def _looks_like_raw_ref(value: str) -> bool:
    if contains_sensitive_text(value):
        return True
    text = value.lower()
    if _looks_like_private_path_ref(text):
        return True
    if "locomo:" in text or "conv-private" in text or "turn-secret" in text:
        return True
    if any(
        text.startswith(prefix)
        for prefix in (
            "backend:",
            "graphiti:",
            "mem0:",
            "memory://",
            "openai:",
            "provider:",
            "provider-ref-",
            "qdrant:",
        )
    ):
        return True
    return any(
        marker in text
        for marker in (
            "access-token",
            "access_token",
            "api-key",
            "api_key",
            "auth-private",
            "auth-payload",
            "auth_payload",
            "bearer-token",
            "bearer_token",
            "private-payload",
            "private_payload",
            "private-token",
            "private_token",
            "private-auth",
            "provider-auth",
            "provider-private",
            "provider-secret",
            "provider_payload",
            "provider_private",
            "raw-provider",
            "raw_provider",
            "refresh-token",
            "refresh_token",
        )
    )


def _looks_like_private_provider_source_label(value: str) -> bool:
    if _looks_like_raw_ref(value):
        return True
    label = value.strip().casefold()
    return any(
        label == prefix
        or any(
            label.startswith(f"{prefix}{separator}")
            for separator in _PRIVATE_PROVIDER_SOURCE_LABEL_SEPARATORS
        )
        for prefix in _PRIVATE_PROVIDER_SOURCE_LABEL_PREFIXES
    )


def _looks_like_private_path_ref(value: str) -> bool:
    path = value.strip().replace("\\", "/")
    if not path:
        return False
    if _ABSOLUTE_PATH_REF_RE.search(path):
        return True
    basename = path.rsplit("/", 1)[-1]
    if basename in _PRIVATE_PATH_BASENAMES:
        return True
    if basename.endswith((".env", ".json")) and any(
        marker in basename for marker in _PRIVATE_PATH_NAME_MARKERS
    ):
        return True
    if "/" not in path:
        return False
    parts = tuple(part for part in path.split("/") if part)
    return any(part in _PRIVATE_PATH_SEGMENTS for part in parts)


def source_identity_refs_from_text(
    text: str,
    *,
    source_refs: Sequence[str],
) -> tuple[str, ...]:
    refs = tuple(
        str(ref).strip()
        for ref in source_refs
        if str(ref).strip()
    )
    if _source_turn_refs(refs, include_exact_turn_refs=True):
        return ()
    session_turn_refs = _session_turn_refs_from_text(text)
    if 0 < len(session_turn_refs) <= 3:
        return _session_identity_refs(session_turn_refs)
    turn_refs = _safe_turn_refs(_TURN_REF_RE.findall(text or ""))
    if not 0 < len(turn_refs) <= 3:
        return ()
    return tuple(f"source_turn_refs:{ref}" for ref in sorted(turn_refs))


def source_identity_refs_from_source_refs(
    source_refs: object,
    *,
    include_exact_turn_refs: bool = False,
) -> tuple[str, ...]:
    refs = tuple(
        str(ref).strip()
        for ref in _source_ref_values(source_refs)
        if str(ref).strip()
    )
    wrapped_identity_refs = tuple(
        ref
        for raw_ref in refs
        if raw_ref.lower().startswith(("refs:", "source_identity:", "source_refs:"))
        for ref in source_identity_refs_from_dedupe_key(raw_ref)
    )
    session_turn_refs = _source_session_turn_refs(refs)
    turn_refs = _source_turn_refs(
        refs,
        include_exact_turn_refs=include_exact_turn_refs,
    )
    if 0 < len(session_turn_refs) <= 3:
        identity_refs = list(_session_identity_refs(session_turn_refs))
        session_turn_values = _turn_refs_from_session_turn_refs(session_turn_refs)
        extra_turn_refs = tuple(
            ref for ref in sorted(turn_refs) if ref not in session_turn_values
        )
        if len(session_turn_refs) + len(extra_turn_refs) <= 3:
            identity_refs.extend(f"source_turn_refs:{ref}" for ref in extra_turn_refs)
        return tuple(dict.fromkeys((*wrapped_identity_refs, *identity_refs)))
    if not 0 < len(turn_refs) <= 3:
        return tuple(dict.fromkeys(wrapped_identity_refs))
    return tuple(
        dict.fromkeys(
            (
                *wrapped_identity_refs,
                *(f"source_turn_refs:{ref}" for ref in sorted(turn_refs)),
            )
        )
    )


def source_identity_audit_gap_codes(
    *,
    source_refs: object,
    text: str,
) -> tuple[str, ...]:
    refs = tuple(
        str(ref).strip()
        for ref in _source_ref_values(source_refs)
        if str(ref).strip()
    )
    source_turn_refs = _source_turn_refs(refs, include_exact_turn_refs=True)
    source_session_turn_refs = _source_session_turn_refs(refs)
    text_session_turn_refs = _session_turn_refs_from_text(
        text,
        require_dialogue_match=False,
    )
    text_turn_refs = _safe_turn_refs(_TURN_REF_RE.findall(text or ""))
    has_text_turn_identity = bool(text_session_turn_refs or text_turn_refs)

    gap_codes: list[str] = []
    if not refs:
        gap_codes.append(
            "missing_source_refs_with_text_turn_identity"
            if has_text_turn_identity
            else "missing_source_refs"
        )
    elif not source_turn_refs:
        gap_codes.append(
            "generic_source_refs_with_text_turn_identity"
            if has_text_turn_identity
            else "source_refs_without_turn_identity"
        )
    if len(source_turn_refs) > 3:
        gap_codes.append("broad_source_turn_identity")
    elif not source_turn_refs and len(text_turn_refs) > 3:
        gap_codes.append("broad_text_turn_identity")
    if (
        source_session_turn_refs
        and text_session_turn_refs
        and not set(text_session_turn_refs).issubset(set(source_session_turn_refs))
    ):
        gap_codes.append("source_text_session_turn_mismatch")
    elif (
        source_turn_refs
        and text_turn_refs
        and not set(source_turn_refs).intersection(text_turn_refs)
    ):
        gap_codes.append("source_text_turn_mismatch")
    if _session_count(source_session_turn_refs) > 1:
        gap_codes.append("cross_session_source_identity")
    elif not source_session_turn_refs and _session_count(text_session_turn_refs) > 1:
        gap_codes.append("cross_session_text_identity")
    return tuple(dict.fromkeys(gap_codes))


def _split_identity_refs(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(ref.strip() for ref in value.split("|") if ref.strip())
    )


def _source_ref_values(value: object) -> tuple[object, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return _source_ref_values_from_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        return tuple(
            ref
            for item in value
            for ref in _source_ref_values(item)
        )
    return ()


def _source_ref_values_from_mapping(value: Mapping[object, object]) -> tuple[object, ...]:
    refs: list[object] = []
    for key in (
        "source_id",
        "source_external_id",
        "source_identity",
        "source_identity_ref",
        "source_ref",
        "session_key",
        "dia_id",
        "locomo_evidence_ref",
        "evidence_id",
        "evidence_ref",
        "source_evidence_ref",
        "turn_ref",
        "turn_id",
        "source_turn_ref",
    ):
        raw_ref = value.get(key)
        if isinstance(raw_ref, str) and raw_ref.strip():
            refs.append(raw_ref.strip())
    structured_session_ref = _structured_session_ref_from_mapping(value)
    if structured_session_ref:
        refs.append(structured_session_ref)
    refs.extend(_structured_turn_refs_from_mapping(value))
    for key in (
        "source_refs",
        "source_identity_refs",
        "source_identity_items",
        "source_ref_payloads",
        "evidence",
        "evidence_refs",
        "evidence_ids",
        "locomo_evidence_refs",
        "source_evidence_refs",
        "turn_ids",
        "supporting_evidence",
        "supporting_facts",
    ):
        refs.extend(_nested_source_ref_values_from_mapping(value, key))
    nested = value.get("metadata")
    if isinstance(nested, Mapping):
        refs.extend(_source_ref_values_from_mapping(nested))
    raw_id = value.get("id")
    if isinstance(raw_id, str) and _source_ref_value_has_turn_identity(raw_id):
        refs.append(raw_id.strip())
    return tuple(dict.fromkeys(refs))


def _nested_source_ref_values_from_mapping(
    value: Mapping[object, object],
    key: str,
) -> tuple[object, ...]:
    dialogue = _dialogue_number_from_mapping(value)
    refs = _source_ref_values_from_nested_value(
        value.get(key),
        parent_dialogue=dialogue if key in _NESTED_EVIDENCE_CONTEXT_KEYS else "",
    )
    if key not in _NUMERIC_EVIDENCE_LIST_KEYS or not dialogue:
        return refs
    return tuple(ref for ref in refs if not _positive_int_string(ref))


def _source_ref_values_from_nested_value(
    value: object,
    *,
    parent_dialogue: str,
) -> tuple[object, ...]:
    if (
        parent_dialogue
        and isinstance(value, Mapping)
        and not _dialogue_number_from_mapping(value)
    ):
        return _source_ref_values_from_mapping(
            {**value, "source_dialogue_id": parent_dialogue}
        )
    if (
        parent_dialogue
        and isinstance(value, Sequence)
        and not isinstance(value, str | bytes)
    ):
        return tuple(
            ref
            for item in value
            for ref in _source_ref_values_from_nested_value(
                item,
                parent_dialogue=parent_dialogue,
            )
        )
    return _source_ref_values(value)


def _structured_turn_refs_from_mapping(
    value: Mapping[object, object],
) -> tuple[str, ...]:
    turn_ref = _safe_turn_ref_from_mapping_value(
        value.get("dia_id")
        or value.get("locomo_evidence_ref")
        or value.get("dialogue_turn_id")
        or value.get("locomo_dialogue_turn_id")
        or value.get("source_dia_id")
        or value.get("source_dialogue_turn_id")
        or value.get("evidence_id")
        or value.get("evidence_ref")
        or value.get("source_evidence_ref")
        or value.get("source_turn_ref")
        or value.get("turn_ref")
        or value.get("source_turn_id")
        or value.get("turn_id")
    )
    if turn_ref:
        return (turn_ref,)
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
                "locomo_turn_id",
                "locomo_turn_ids",
                "locomo_turn_index",
                "locomo_turn_indexes",
                "locomo_turn_number",
                "locomo_turn_numbers",
                "source_dialogue_turn_id",
                "source_dialogue_turn_ids",
                "source_turn_ref",
                "source_turn_refs",
                "source_utterance",
                "source_utterance_id",
                "source_utterance_ids",
                "source_utterance_index",
                "source_utterance_indexes",
                "source_utterance_number",
                "source_utterance_numbers",
                "turn",
                "turn_ref",
                "turn_refs",
                "turn_id",
                "turn_ids",
                "turn_index",
                "turn_number",
                "utt",
                "utt_id",
                "utt_ids",
                "utt_index",
                "utt_indexes",
                "utt_number",
                "utt_numbers",
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
        "locomo_session_number",
        "locomo_session_numbers",
        "source_session_id",
        "source_session_ids",
        "source_session_index",
        "source_session_indexes",
        "source_session_key",
        "source_session_keys",
        "source_session_number",
        "source_session_numbers",
        "session_id",
        "session_ids",
        "session_index",
        "session_indexes",
        "session_key",
        "session_keys",
        "session_number",
        "session_numbers",
        "session_order",
        "session_orders",
    ):
        session = _single_dialogue_number_from_value(value.get(key))
        if session:
            return f"session_{session}"
    return ""


def _safe_turn_ref_from_mapping_value(value: object) -> str:
    if turn_ref := safe_turn_ref(value):
        return turn_ref
    return ""


def _dialogue_number_from_mapping(value: Mapping[object, object]) -> str:
    for key in (
        "source_dialogue_id",
        "source_dialogue_ids",
        "source_dialogue",
        "source_dialogues",
        "source_dialogue_index",
        "source_dialogue_indexes",
        "dialogue_id",
        "dialogue_ids",
        "dialogue",
        "dialogues",
        "dialogue_index",
        "dialogue_indexes",
        "dia_id",
        "dia_ids",
        "source_dia_id",
        "source_dia_ids",
        "locomo_session_index",
        "locomo_session_indexes",
        "locomo_session_ids",
        "locomo_session_key",
        "locomo_session_keys",
        "locomo_session_number",
        "locomo_session_numbers",
        "session_key",
        "session_keys",
        "session_id",
        "session_ids",
        "session_index",
        "session_indexes",
        "session_number",
        "session_numbers",
        "session_order",
        "session_orders",
        "source_session_id",
        "source_session_ids",
        "source_session_index",
        "source_session_indexes",
        "source_session_key",
        "source_session_keys",
        "source_session_number",
        "source_session_numbers",
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
        r"(?:(?:session|dialogue|dialog)[-_\s#]*|D)?(?P<number>\d+)",
        text,
        re.IGNORECASE,
    ):
        return match.group("number")
    return ""


def _safe_dialogue_ref(value: object) -> str:
    ref = str(value or "").strip()
    if not ref:
        return ""
    match = _DIALOGUE_REF_PARTS_RE.fullmatch(ref)
    return f"D{match.group('dialogue')}" if match else ""


def _positive_int_string(value: object) -> str:
    text = str(value or "").strip()
    if match := re.fullmatch(
        r"(?:turn|utt|utterance|t)[-_:\s#]*(?P<turn>\d+)",
        text,
        re.IGNORECASE,
    ):
        text = match.group("turn")
    if not text.isdigit():
        return ""
    parsed = int(text)
    return str(parsed) if parsed > 0 else ""


def _source_ref_value_has_turn_identity(value: str) -> bool:
    return bool(
        safe_source_identity_ref(value)
        or source_identity_refs_from_dedupe_key(value)
        or _source_turn_refs((value,), include_exact_turn_refs=True)
    )


def _safe_output_ref_is_covered_by_identity(
    ref: str,
    source_identity_refs: Sequence[str],
) -> bool:
    if not source_identity_refs:
        return False
    identity_ref_set = set(source_identity_refs)
    if ref in identity_ref_set:
        return True
    turn_ref = safe_turn_ref(ref)
    if turn_ref and f"source_turn_refs:{turn_ref}" in identity_ref_set:
        return True
    turn_number = _positive_int_string(ref)
    if turn_number and any(
        identity_ref.endswith(f":{turn_number}")
        for identity_ref in source_identity_refs
        if identity_ref.startswith("source_turn_refs:")
    ):
        return True
    session_ref = _normalized_session_ref(ref)
    if session_ref and any(
            identity_ref.startswith(f"source_session_turn_refs:{session_ref}:")
            for identity_ref in source_identity_refs
    ):
        return True
    dialogue_ref = _safe_dialogue_ref(ref)
    return bool(
        dialogue_ref
        and any(
            f":{dialogue_ref}:" in identity_ref for identity_ref in source_identity_refs
        )
    )


def _identity_source_ref_values_for_output(
    source_ref_values: Sequence[object],
) -> tuple[object, ...]:
    if any(_source_session_refs(str(ref or "")) for ref in source_ref_values):
        return tuple(source_ref_values)
    return tuple(
        ref
        for ref in source_ref_values
        if _source_ref_value_should_seed_output_identity(ref)
    )


def _source_ref_value_should_seed_output_identity(value: object) -> bool:
    text = str(value or "").strip()
    return bool(
        text
        and (
            safe_source_identity_ref(text)
            or _looks_like_source_identity_dedupe_key(text)
            or _looks_like_raw_ref(text)
            or _source_session_refs(text)
            or _SOURCE_SESSION_TURN_RE.search(text)
        )
    )


def _identity_ref_is_unqualified_turn_covered_by_session(
    ref: str,
    source_identity_refs: Sequence[str],
) -> bool:
    if not ref.startswith("source_turn_refs:"):
        return False
    turn_ref = safe_turn_ref(ref.removeprefix("source_turn_refs:"))
    return bool(
        turn_ref
        and any(
            identity_ref.startswith("source_session_turn_refs:")
            and identity_ref.endswith(f":{turn_ref}")
            for identity_ref in source_identity_refs
        )
    )


def _ordered_identity_refs_from_single_source_ref(
    raw_ref: object,
    aggregate_identity_refs: Sequence[str],
) -> tuple[str, ...]:
    refs = source_identity_refs_from_source_refs(
        (raw_ref,),
        include_exact_turn_refs=True,
    )
    return tuple(
        ref
        for ref in refs
        if not (
            _identity_ref_is_unqualified_turn_covered_by_session(
                ref,
                aggregate_identity_refs,
            )
            and not _identity_ref_is_unqualified_turn_covered_by_session(ref, refs)
        )
    )


def _safe_identity_refs(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            ref
            for raw_ref in values
            for ref in (safe_source_identity_ref(raw_ref),)
            if ref
        )
    )


def _safe_turn_refs(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            ref
            for raw_ref in values
            for ref in (safe_turn_ref(raw_ref),)
            if ref
        )
    )


def _identity_refs_from_source_ref_values(values: Iterable[object]) -> tuple[str, ...]:
    source_refs = tuple(
        dict.fromkeys(str(raw_ref or "").strip() for raw_ref in values)
    )
    split_session_turn_refs = _source_session_turn_refs(source_refs)
    refs: list[str] = []
    for source_ref in source_refs:
        if not source_ref:
            continue
        source_ref_turns = _source_turn_refs_from_source_ref(
            source_ref,
            include_exact_turn_refs=True,
        )
        split_refs = tuple(
            session_turn_ref
            for session_turn_ref in split_session_turn_refs
            if any(
                _turn_refs_from_session_turn_refs((session_turn_ref,)) == (turn_ref,)
                for turn_ref in source_ref_turns
            )
        )
        if split_refs and not _source_session_turn_refs((source_ref,)):
            refs.extend(_session_identity_refs(split_refs))
            continue
        identity_refs = source_identity_refs_from_source_refs(
            (source_ref,),
            include_exact_turn_refs=True,
        )
        if identity_refs:
            refs.extend(identity_refs)
            continue
        generic_ref = _safe_generic_source_ref(source_ref)
        if generic_ref:
            refs.append(generic_ref)
    return tuple(dict.fromkeys(refs))


def _identity_refs_from_source_identity_values(
    values: Iterable[object],
) -> tuple[str, ...]:
    refs: list[str] = []
    for raw_ref in values:
        source_ref = str(raw_ref or "").strip()
        if not source_ref:
            continue
        safe_ref = safe_source_identity_ref(source_ref)
        if safe_ref:
            refs.append(safe_ref)
            continue
        session_safe_ref = safe_source_identity_ref(
            f"source_session_turn_refs:{source_ref}"
        )
        if session_safe_ref:
            refs.append(session_safe_ref)
            continue
        turn_ref = safe_turn_ref(source_ref)
        if turn_ref:
            refs.append(f"source_turn_refs:{turn_ref}")
            continue
        nested_refs = source_identity_refs_from_dedupe_key(source_ref)
        if nested_refs:
            refs.extend(nested_refs)
            continue
        refs.extend(
            source_identity_refs_from_source_refs(
                (source_ref,),
                include_exact_turn_refs=True,
            )
        )
    return tuple(dict.fromkeys(refs))


def _looks_like_source_identity_dedupe_key(value: str) -> bool:
    return value.lower().startswith(
        (
            "refs:",
            "source_identity:",
            "source_refs:",
            "source_session_turn_refs:",
            "source_turn_refs:",
            "turn_refs:",
        )
    )


def _safe_generic_source_ref(value: object) -> str | None:
    ref = str(value or "").strip()
    if not ref:
        return None
    if _looks_like_raw_ref(ref):
        return None
    if len(ref) > _MAX_SAFE_GENERIC_SOURCE_REF_LENGTH:
        return None
    return ref


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


def _turn_ref_dialogue_number(turn_ref: str) -> str:
    match = _TURN_REF_PARTS_RE.fullmatch(turn_ref)
    return match.group("dialogue") if match is not None else ""


def _session_turn_refs_from_text(
    text: str,
    *,
    require_dialogue_match: bool = True,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            f"session_{match.group('session')}:{turn_ref}"
            for pattern in (
                _TEXT_SESSION_TURN_RE,
                _TEXT_SESSION_DATE_TURN_RE,
                _TEXT_TURN_SESSION_RE,
                _TEXT_TURN_PUNCT_SESSION_RE,
            )
            for match in pattern.finditer(text or "")
            for turn_ref in (safe_turn_ref(match.group("turn_ref")),)
            if turn_ref
            and (
                not require_dialogue_match
                or _turn_ref_dialogue_number(turn_ref) == match.group("session")
            )
        )
    )


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


def _normalized_session_ref(value: object) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(
        r"(?:session|dialogue|dialog)(?:[-_]\s*|\s+#?\s*)(?P<session>\d+)",
        text,
        re.IGNORECASE,
    )
    if match:
        return f"session_{match.group('session')}"
    return ""

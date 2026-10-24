"""Ordered benchmark source identity projection, output safety and audit gaps."""

from __future__ import annotations

# Retain the complete source-identity surface, including existing helper imports.
# ruff: noqa: F401
import re
from collections.abc import (
    Iterable,
    Mapping,
    Sequence,
)

from infinity_context_core.sensitive_text import (
    contains_sensitive_text,
)

from infinity_context_benchmarks.source_identity_parsing import (
    _EXPLICIT_SOURCE_SESSION_RE,
    _SOURCE_SESSION_RE,
    _SOURCE_SESSION_TURN_RE,
    _TEXT_KEY_VALUE_SESSION_RE,
    _TEXT_KEY_VALUE_TURN_NUMBER_RE,
    _TEXT_KEY_VALUE_TURN_REF_RE,
    _TEXT_SESSION_BRACKET_TURN_RE,
    _TEXT_SESSION_DATE_TURN_RE,
    _TEXT_SESSION_NUMERIC_TURN_RE,
    _TEXT_SESSION_PAREN_TURN_RE,
    _TEXT_SESSION_TURN_RE,
    _TEXT_TURN_BRACKET_SESSION_RE,
    _TEXT_TURN_PAREN_SESSION_RE,
    _TEXT_TURN_PUNCT_SESSION_RE,
    _TEXT_TURN_SESSION_RE,
    _TURN_REF_RE,
    _dialogue_number_from_mapping,
    _dialogue_number_from_value,
    _first_safe_turn_ref_from_mapping_values,
    _positive_int_values,
    _session_count,
    _session_identity_refs,
    _session_turn_ref_mismatch,
    _session_turn_refs_from_key_value_text,
    _session_turn_refs_from_split_refs,
    _session_turn_refs_from_text,
    _single_dialogue_number_from_value,
    _source_ref_session_numbers,
    _source_session_refs,
    _source_session_turn_mismatch,
    _source_session_turn_ref_session_numbers,
    _source_session_turn_refs,
    _source_turn_refs,
    _source_turn_refs_from_source_ref,
    _structured_session_ref_from_mapping,
    _structured_turn_refs_from_mapping,
    _structured_turn_values_from_mapping,
    _turn_ref_dialogue_number,
    _turn_refs_from_session_turn_refs,
)
from infinity_context_benchmarks.source_identity_safety import (
    _ABSOLUTE_PATH_REF_RE,
    _DIALOGUE_REF_PARTS_RE,
    _INSTRUCTION_LIKE_ITEM_ID_RE,
    _MAX_SAFE_GENERIC_SOURCE_REF_LENGTH,
    _MAX_SAFE_ITEM_ID_LENGTH,
    _MAX_SAFE_SOURCE_IDENTITY_REF_LENGTH,
    _MAX_SAFE_SOURCE_LABEL_LENGTH,
    _MAX_SAFE_TURN_REF_LENGTH,
    _PRIVATE_PATH_BASENAMES,
    _PRIVATE_PATH_NAME_MARKERS,
    _PRIVATE_PATH_SEGMENTS,
    _PRIVATE_PROVIDER_SOURCE_LABEL_PREFIXES,
    _PRIVATE_PROVIDER_SOURCE_LABEL_SEPARATORS,
    _SAFE_SOURCE_IDENTITY_REF_RE,
    _TURN_REF_PARTS_RE,
    _looks_like_private_path_ref,
    _looks_like_private_provider_source_label,
    _looks_like_raw_ref,
    _looks_like_source_identity_dedupe_key,
    _normalized_session_ref,
    _positive_int_string,
    _safe_dialogue_ref,
    _safe_generic_source_ref,
    _safe_identity_refs,
    _safe_turn_refs,
    _split_identity_refs,
    looks_like_raw_source_ref,
    safe_item_id_for_output,
    safe_source_identity_ref,
    safe_source_label_for_output,
    safe_turn_ref,
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
        "source_turn",
        "source_turns",
        "supporting_evidence",
        "supporting_facts",
    }
)


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
    source_session_turn_mismatch = _source_session_turn_mismatch(refs)
    source_text_session_turn_mismatch = (
        source_session_turn_refs
        and text_session_turn_refs
        and not set(text_session_turn_refs).issubset(set(source_session_turn_refs))
    )
    if source_text_session_turn_mismatch:
        gap_codes.append("source_text_session_turn_mismatch")
    elif source_session_turn_mismatch:
        gap_codes.append("source_session_turn_mismatch")
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
        "source_turn",
        "source_turns",
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
    text_session_refs = _session_turn_refs_from_text(ref)
    if text_session_refs and all(
        f"source_session_turn_refs:{session_ref}" in identity_ref_set
        for session_ref in text_session_refs
    ):
        return True
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
            or _session_turn_refs_from_text(text)
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

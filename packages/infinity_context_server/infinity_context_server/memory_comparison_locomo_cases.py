"""LoCoMo case loading helpers for memory comparison benchmarks."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from infinity_context_server.public_benchmark import (
    LOCOMO_BENCHMARK_SUITE,
    _case_capability,
    _case_hash,
    _first_str,
    _is_official_locomo_sample,
    _is_session_key,
    _load_cases,
    _load_dataset_payload,
    _official_locomo_evidence_lookup,
    _official_locomo_evidence_previews,
    _official_locomo_evidence_terms,
    _official_locomo_supported_answer_terms,
    _preview_value,
    _session_sort_key,
    _terms,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkMemoryInput,
    BenchmarkValidationError,
    PublicBenchmarkCase,
)

LOCOMO_INGEST_RICH_DOCUMENTS = "rich-documents"
LOCOMO_INGEST_OFFICIAL_TURNS = "official-turns"

_LOCOMO_CATEGORY_NAMES = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
    5: "adversarial",
}
_LOCOMO_SCORED_CATEGORIES = frozenset({1, 2, 3, 4})


def _load_memory_comparison_cases(
    dataset_path: Path,
    *,
    locomo_ingest_mode: str,
) -> tuple[PublicBenchmarkCase, ...]:
    if locomo_ingest_mode == LOCOMO_INGEST_RICH_DOCUMENTS:
        return _load_cases(dataset_path)
    if locomo_ingest_mode != LOCOMO_INGEST_OFFICIAL_TURNS:
        raise BenchmarkValidationError(f"Unsupported LoCoMo ingest mode: {locomo_ingest_mode}")

    payload = _load_dataset_payload(dataset_path)
    cases = _official_locomo_turn_cases_from_payload(payload)
    return cases or _load_cases(dataset_path)


def _official_locomo_turn_cases_from_payload(payload: object) -> tuple[PublicBenchmarkCase, ...]:
    if isinstance(payload, Mapping) and _is_official_locomo_sample(payload):
        return _official_locomo_turn_cases(payload)
    if isinstance(payload, Mapping):
        raw_samples = payload.get("data") or payload.get("cases") or payload.get("items")
        if raw_samples is not None:
            return _official_locomo_turn_cases_from_payload(raw_samples)
    if isinstance(payload, Sequence) and not isinstance(payload, str | bytes):
        cases: list[PublicBenchmarkCase] = []
        for item in payload:
            if isinstance(item, Mapping) and _is_official_locomo_sample(item):
                cases.extend(_official_locomo_turn_cases(item))
        return tuple(cases)
    return ()


def _official_locomo_turn_cases(raw: Mapping[str, object]) -> tuple[PublicBenchmarkCase, ...]:
    sample_id = _first_str(raw, "sample_id", "id") or _case_hash(raw)
    memories = _official_locomo_turn_memories(raw, sample_id=sample_id)
    evidence_lookup = _official_locomo_evidence_lookup(raw)
    raw_qas = raw.get("qa")
    if not isinstance(raw_qas, Sequence) or isinstance(raw_qas, str | bytes):
        return ()

    cases: list[PublicBenchmarkCase] = []
    for index, qa in enumerate(raw_qas):
        if not isinstance(qa, Mapping):
            continue
        question = _first_str(qa, "question", "query")
        evidence_terms = _official_locomo_evidence_terms(qa, evidence_lookup)
        answer_terms = _terms(qa, "answer", "expected_answer", "answers")
        expected_terms = answer_terms or evidence_terms or _official_locomo_supported_answer_terms(
            qa,
            documents=(),
        )
        if not question or not expected_terms:
            continue
        category = qa.get("category")
        case_id = f"{sample_id}:qa:{index + 1}"
        cases.append(
            PublicBenchmarkCase(
                benchmark=LOCOMO_BENCHMARK_SUITE,
                case_id=case_id,
                question=question,
                expected_terms=expected_terms,
                memories=memories,
                memory_scope_external_ref=f"locomo-{sample_id}",
                thread_external_ref=f"locomo-{sample_id}",
                metadata={
                    "source_format": "official_locomo",
                    "locomo_ingest_mode": LOCOMO_INGEST_OFFICIAL_TURNS,
                    "sample_id": sample_id,
                    "qa_index": index,
                    "category": category,
                    "answer_preview": _preview_value(qa.get("answer")),
                    "answer_terms": answer_terms,
                    "evidence_terms": evidence_terms,
                    "evidence": qa.get("evidence") if isinstance(qa.get("evidence"), list) else [],
                    "evidence_previews": _official_locomo_evidence_previews(
                        qa,
                        evidence_lookup=evidence_lookup,
                    ),
                },
            )
        )
    return tuple(cases)


def _official_locomo_turn_memories(
    raw: Mapping[str, object],
    *,
    sample_id: str,
) -> tuple[BenchmarkMemoryInput, ...]:
    conversation = raw.get("conversation")
    if not isinstance(conversation, Mapping):
        return ()
    speaker_a = _first_str(conversation, "speaker_a") or ""
    speaker_a_identity = _normalized_locomo_speaker(speaker_a)
    memories: list[BenchmarkMemoryInput] = []
    for session_key in sorted(conversation, key=_session_sort_key):
        if not _is_session_key(session_key):
            continue
        session_value = conversation.get(session_key)
        turns = _official_locomo_session_turns(session_value)
        if not turns:
            continue
        date_value = _first_str(conversation, f"{session_key}_date_time") or ""
        if not date_value and isinstance(session_value, Mapping):
            date_value = (
                _first_str(
                    session_value,
                    "date",
                    "date_time",
                    "datetime",
                    "session_date",
                    "session_date_time",
                    "timestamp",
                )
                or ""
            )
        timestamp = _locomo_date_to_epoch(date_value)
        for index, turn in enumerate(turns):
            if not isinstance(turn, Mapping):
                continue
            dia_id = _locomo_turn_dia_id(
                turn,
                session_key=session_key,
                turn_index=index,
            )
            speaker = _first_str(turn, "speaker", "role", "author") or "speaker"
            text = _official_locomo_turn_memory_text(
                turn,
                session_key=session_key,
                dia_id=dia_id,
                speaker=speaker,
                date_value=date_value,
            )
            if not text:
                continue
            role = (
                "user"
                if speaker_a_identity
                and _normalized_locomo_speaker(speaker) == speaker_a_identity
                else "assistant"
            )
            memories.append(
                BenchmarkMemoryInput(
                    text=text,
                    source_external_id=f"locomo:{sample_id}:{session_key}:{dia_id}:turn",
                    metadata={
                        "role": role,
                        "timestamp": timestamp,
                        "session_key": session_key,
                        "session_date": date_value,
                        "dia_id": dia_id,
                        "speaker": speaker,
                    },
                )
            )
    return tuple(memories)


def _official_locomo_session_turns(value: object) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(turn for turn in value if isinstance(turn, Mapping))
    if isinstance(value, Mapping):
        for key in ("dialogue", "turns", "utterances", "messages", "items"):
            turns = value.get(key)
            if isinstance(turns, Sequence) and not isinstance(turns, str | bytes):
                return tuple(turn for turn in turns if isinstance(turn, Mapping))
    return ()


def _official_locomo_turn_memory_text(
    turn: Mapping[str, object],
    *,
    session_key: str,
    dia_id: str,
    speaker: str,
    date_value: str,
) -> str:
    text = _first_str(turn, "text", "content", "utterance") or ""
    caption = _first_str(turn, "blip_caption", "caption")
    visual_query = _first_str(turn, "query", "image_query", "visual_query")
    if visual_query and caption:
        image_text = f"[Sharing image - query: {visual_query}. The image shows: {caption}]"
    elif visual_query:
        image_text = f"[Sharing image - query for: {visual_query}]"
    elif caption:
        image_text = f"[Sharing image that shows: {caption}]"
    else:
        image_text = ""
    if image_text:
        text = f"{text} {image_text}" if text else image_text
    if not text.strip():
        return ""
    date_prefix = f"{session_key} date: {date_value}\n" if date_value.strip() else ""
    return f"{date_prefix}{dia_id} {speaker}: {text.strip()}"


def _locomo_turn_dia_id(
    turn: Mapping[str, object],
    *,
    session_key: str,
    turn_index: int,
) -> str:
    raw_dia_id = _first_str(turn, "dia_id", "id")
    if raw_dia_id and _looks_like_locomo_dia_id(raw_dia_id):
        return raw_dia_id

    session_number = _locomo_session_number(session_key)
    if session_number is None:
        return raw_dia_id or f"{session_key}:{turn_index + 1}"
    if raw_dia_id and raw_dia_id.isdigit() and int(raw_dia_id) > 0:
        return f"D{session_number}:{int(raw_dia_id)}"
    return f"D{session_number}:{turn_index + 1}"


def _looks_like_locomo_dia_id(value: str) -> bool:
    stripped = value.strip()
    return bool(
        stripped.upper().startswith("D") and (":" in stripped or "-" in stripped)
    )


def _locomo_session_number(session_key: str) -> int | None:
    parts = session_key.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    parsed = int(parts[1])
    return parsed if parsed > 0 else None


def _normalized_locomo_speaker(speaker: str) -> str:
    return " ".join(str(speaker or "").casefold().split())


def _locomo_date_to_epoch(date_value: str) -> int | None:
    if not date_value.strip():
        return None
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
        try:
            parsed = datetime.strptime(date_value.strip(), fmt)
        except ValueError:
            continue
        return int(parsed.replace(tzinfo=UTC).timestamp())
    return None


def _case_corpus_key(case: PublicBenchmarkCase) -> str:
    memory_scope = case.memory_scope_external_ref or case.case_id
    thread = case.thread_external_ref or case.case_id
    return f"{case.benchmark}:{memory_scope}:{thread}:{_case_corpus_fingerprint(case)}"


def _case_corpus_fingerprint(case: PublicBenchmarkCase) -> str:
    source_parts: list[dict[str, object]] = []
    for index, memory in enumerate(case.memories):
        source_parts.append(
            {
                "kind": "memory",
                "index": index,
                "memory_kind": memory.kind,
                "source_external_id": memory.source_external_id,
                "metadata": dict(memory.metadata),
                "text": memory.text,
            }
        )
    for index, document in enumerate(case.documents):
        source_parts.append(
            {
                "kind": "document",
                "index": index,
                "title": document.title,
                "source_type": document.source_type,
                "classification": document.classification,
                "source_external_id": document.source_external_id,
                "text": document.text,
            }
        )
    encoded = json.dumps(
        source_parts,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _case_group(case: PublicBenchmarkCase) -> str:
    category = _case_category(case)
    if case.benchmark == LOCOMO_BENCHMARK_SUITE and category in _LOCOMO_CATEGORY_NAMES:
        return _LOCOMO_CATEGORY_NAMES[int(category)]
    return _case_capability(case)


def _case_category_label(case: PublicBenchmarkCase) -> str:
    category = _case_category(case)
    if category is None:
        return "uncategorized"
    if case.benchmark == LOCOMO_BENCHMARK_SUITE:
        name = _LOCOMO_CATEGORY_NAMES.get(category)
        if name:
            return f"{category}:{name}"
    return str(category)


def _case_is_scored(case: PublicBenchmarkCase) -> bool:
    category = _case_category(case)
    if case.benchmark == LOCOMO_BENCHMARK_SUITE and category is not None:
        return int(category) in _LOCOMO_SCORED_CATEGORIES
    return True


def _case_category(case: PublicBenchmarkCase) -> int | None:
    value = case.metadata.get("category")
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _case_ground_truth(case: PublicBenchmarkCase) -> str:
    answer = case.metadata.get("answer_preview")
    if isinstance(answer, str) and answer.strip():
        return answer
    return " | ".join(case.expected_terms)

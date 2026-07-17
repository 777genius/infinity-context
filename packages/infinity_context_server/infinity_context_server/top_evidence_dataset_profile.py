"""Dataset profiling helpers for strict top-evidence preflight."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from infinity_context_server.eval_constants import (
    LOCOMO_BENCHMARK_SUITE,
    LONGMEMEVAL_BENCHMARK_SUITE,
)


def _dataset_profile(path: Path | None, *, benchmark: str) -> dict[str, object] | None:
    if path is None:
        return None
    try:
        from infinity_context_server.public_benchmark import (
            load_public_benchmark_dataset_profile,
        )

        return load_public_benchmark_dataset_profile(
            dataset_path=path,
            benchmark=benchmark,
        )
    except ImportError:
        return _lightweight_dataset_profile(path, benchmark=benchmark)
    except ValueError:
        return _lightweight_dataset_profile(path, benchmark=benchmark)
    except (OSError, UnicodeDecodeError):
        return None


def _lightweight_dataset_profile(path: Path, *, benchmark: str) -> dict[str, object] | None:
    try:
        payload = _load_public_benchmark_payload(path)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    case_keys = tuple(_public_benchmark_case_keys(payload, benchmark=benchmark))
    if not case_keys:
        return None
    unique_case_keys = set(case_keys)
    return {
        "case_count": len(case_keys),
        "unique_case_id_count": len(unique_case_keys),
        "duplicate_case_id_count": len(case_keys) - len(unique_case_keys),
        "dataset_hash": _sha256_file(path),
        "dataset_path_label": path.name,
    }


def _load_public_benchmark_payload(path: Path) -> object:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return ()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            if stripped.startswith("["):
                raise
    return [json.loads(line) for line in stripped.splitlines() if line.strip()]


def _public_benchmark_case_keys(payload: object, *, benchmark: str) -> tuple[str, ...]:
    if isinstance(payload, Mapping):
        if _is_official_locomo_sample(payload):
            return _official_locomo_case_keys(payload, benchmark=benchmark)
        raw_cases = (
            payload.get("cases")
            or payload.get("data")
            or payload.get("samples")
            or payload.get("items")
        )
        if raw_cases is not None:
            return _public_benchmark_case_keys(raw_cases, benchmark=benchmark)
        return _normalized_public_case_key(payload, index=0, benchmark=benchmark)
    if not isinstance(payload, Sequence) or isinstance(payload, str | bytes):
        return ()
    keys: list[str] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            continue
        if _is_official_locomo_sample(item):
            keys.extend(_official_locomo_case_keys(item, benchmark=benchmark))
        else:
            keys.extend(
                _normalized_public_case_key(
                    item,
                    index=index,
                    benchmark=benchmark,
                )
            )
    return tuple(keys)


def _is_official_locomo_sample(raw: Mapping[str, object]) -> bool:
    return isinstance(raw.get("conversation"), Mapping) and isinstance(raw.get("qa"), list)


def _official_locomo_case_keys(
    raw: Mapping[str, object],
    *,
    benchmark: str,
) -> tuple[str, ...]:
    if _normalize_public_benchmark_name(benchmark) != LOCOMO_BENCHMARK_SUITE:
        return ()
    sample_id = _first_str(raw, "sample_id", "id") or "sample"
    qas = raw.get("qa")
    if not isinstance(qas, Sequence) or isinstance(qas, str | bytes):
        return ()
    evidence_ids = _official_locomo_evidence_id_set(raw)
    searchable_text = _official_locomo_searchable_text(raw)
    keys: list[str] = []
    for index, qa in enumerate(qas):
        if (
            isinstance(qa, Mapping)
            and _first_str(qa, "question", "query")
            and _has_official_locomo_expected_signal(
                qa,
                evidence_ids=evidence_ids,
                searchable_text=searchable_text,
            )
        ):
            keys.append(f"{LOCOMO_BENCHMARK_SUITE}:{sample_id}:qa:{index + 1}")
    return tuple(keys)


def _has_official_locomo_expected_signal(
    qa: Mapping[str, object],
    *,
    evidence_ids: frozenset[str],
    searchable_text: str,
) -> bool:
    return any(
        evidence_id in evidence_ids for evidence_id in _official_locomo_qa_evidence_ids(qa)
    ) or _has_official_locomo_supported_answer_signal(
        qa,
        searchable_text=searchable_text,
    )


def _has_official_locomo_supported_answer_signal(
    qa: Mapping[str, object],
    *,
    searchable_text: str,
) -> bool:
    for answer in _benchmark_scalar_strings(
        qa.get("answer"),
        qa.get("expected_answer"),
        qa.get("answers"),
    ):
        if _normalize_preflight_text(answer) in searchable_text:
            return True
    return False


def _official_locomo_searchable_text(raw: Mapping[str, object]) -> str:
    values: list[str] = []
    _collect_official_locomo_text(raw.get("conversation"), values)
    return _normalize_preflight_text(" ".join(values))


def _collect_official_locomo_text(value: object, values: list[str]) -> None:
    if isinstance(value, Mapping):
        text = _first_str(value, "text", "content", "message", "utterance")
        if text:
            values.append(text)
        for nested in value.values():
            _collect_official_locomo_text(nested, values)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for nested in value:
            _collect_official_locomo_text(nested, values)


def _official_locomo_evidence_id_set(raw: Mapping[str, object]) -> frozenset[str]:
    evidence_ids: set[str] = set()
    _collect_official_locomo_evidence_ids(raw.get("conversation"), evidence_ids)
    return frozenset(evidence_ids)


def _collect_official_locomo_evidence_ids(value: object, evidence_ids: set[str]) -> None:
    if isinstance(value, Mapping):
        dia_id = _first_str(value, "dia_id", "dialogue_id", "turn_id", "id")
        text = _first_str(value, "text", "content", "message", "utterance")
        if dia_id and text:
            evidence_ids.add(dia_id)
        for nested in value.values():
            _collect_official_locomo_evidence_ids(nested, evidence_ids)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for nested in value:
            _collect_official_locomo_evidence_ids(nested, evidence_ids)


def _official_locomo_qa_evidence_ids(qa: Mapping[str, object]) -> tuple[str, ...]:
    evidence_ids: list[str] = []
    for value in _official_locomo_qa_evidence_values(qa.get("evidence")):
        evidence_id = str(value).strip()
        if evidence_id:
            evidence_ids.append(evidence_id)
    return tuple(evidence_ids)


def _official_locomo_qa_evidence_values(value: object) -> tuple[object, ...]:
    if isinstance(value, Mapping):
        values: list[object] = []
        for key in (
            "dia_id",
            "id",
            "ids",
            "ref",
            "refs",
            "source_id",
            "source_ids",
            "evidence",
            "evidence_id",
            "evidence_ids",
            "turn_id",
            "turn_ids",
        ):
            if key in value:
                values.extend(_official_locomo_qa_evidence_values(value.get(key)))
        return tuple(values)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        values = []
        for item in value:
            values.extend(_official_locomo_qa_evidence_values(item))
        return tuple(values)
    return (value,) if value is not None else ()


def _benchmark_scalar_strings(*values: object) -> tuple[str, ...]:
    strings: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            strings.append(value.strip())
        elif isinstance(value, int | float | bool):
            strings.append(str(value))
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            strings.extend(_benchmark_scalar_strings(*value))
    return tuple(strings)


def _normalize_preflight_text(value: str) -> str:
    return " ".join(value.lower().split())


def _normalized_public_case_key(
    raw: Mapping[str, object],
    *,
    index: int,
    benchmark: str,
) -> tuple[str, ...]:
    raw_benchmark = (
        _first_str(raw, "benchmark", "suite", "source_benchmark", "dataset", "source")
        or benchmark
    )
    case_benchmark = _normalize_public_benchmark_name(raw_benchmark)
    if case_benchmark != _normalize_public_benchmark_name(benchmark):
        return ()
    case_id = (
        _first_str(raw, "case_id", "id", "question_id", "qa_id", "uid", "sample_id")
        or str(index)
    )
    question = _benchmark_question(raw)
    if (
        not question
        or not _has_benchmark_expected_signal(raw)
        or not _has_benchmark_corpus_signal(raw)
    ):
        return ()
    return (f"{case_benchmark}:{case_id}",)


def _benchmark_question(raw: Mapping[str, object]) -> str | None:
    direct = _first_str(raw, "question", "query", "input")
    if direct:
        return direct
    qa = raw.get("qa")
    if isinstance(qa, Mapping):
        return _first_str(qa, "question", "query", "input")
    return None


def _has_benchmark_expected_signal(
    raw: Mapping[str, object],
    *,
    allow_evidence: bool = False,
) -> bool:
    expected_keys = (
        "expected_terms",
        "expected",
        "answer_terms",
        "answer",
        "expected_answer",
        "ground_truth",
        "gold_answer",
        "answers",
    )
    if _has_non_empty_value(
        raw,
        *expected_keys,
    ):
        return True
    qa = raw.get("qa")
    if isinstance(qa, Mapping) and _has_benchmark_expected_signal(
        qa,
        allow_evidence=allow_evidence,
    ):
        return True
    if allow_evidence and _has_non_empty_value(
        raw,
        "evidence",
        allow_mapping=True,
    ):
        return True
    return _requests_benchmark_abstention(raw) and _has_non_empty_value(
        raw,
        "forbidden_terms",
        "forbidden",
        "must_not_retrieve",
    )


def _has_benchmark_corpus_signal(raw: Mapping[str, object]) -> bool:
    for key in (
        "memories",
        "facts",
        "conversation",
        "messages",
        "history",
        "documents",
        "chunks",
        "passages",
        "haystack",
        "context",
    ):
        if _value_has_benchmark_corpus_signal(raw.get(key)):
            return True
    return False


def _value_has_benchmark_corpus_signal(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(
            _first_str(
                value,
                "text",
                "content",
                "message",
                "utterance",
                "body",
                "passage",
            )
        )
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return any(_value_has_benchmark_corpus_signal(item) for item in value)
    return False


def _has_non_empty_value(
    raw: Mapping[str, object],
    *keys: str,
    allow_mapping: bool = False,
) -> bool:
    for key in keys:
        if _value_has_non_empty_signal(raw.get(key), allow_mapping=allow_mapping):
            return True
    return False


def _value_has_non_empty_signal(
    value: object,
    *,
    allow_mapping: bool = False,
) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, int | float | bool):
        return True
    if allow_mapping and isinstance(value, Mapping) and value:
        return True
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return any(
            _value_has_non_empty_signal(item, allow_mapping=allow_mapping)
            for item in value
        )
    return False


def _requests_benchmark_abstention(raw: Mapping[str, object]) -> bool:
    for key in ("answerable", "is_answerable", "has_answer"):
        if raw.get(key) is False:
            return True
    for key in ("abstention", "no_answer", "unanswerable", "hard_negative"):
        if raw.get(key) is True:
            return True
    return False


def _normalize_public_benchmark_name(value: str) -> str:
    normalized = value.strip().lower().replace("_", "").replace("-", "")
    if normalized in {"locomo", "locomo10", "longcontextmemory"}:
        return LOCOMO_BENCHMARK_SUITE
    if normalized in {"longmemeval", "longmemevals", "lme"}:
        return LONGMEMEVAL_BENCHMARK_SUITE
    return value.strip().lower()


def _first_str(raw: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_int(profile: Mapping[str, object] | None, key: str) -> int | None:
    if profile is None:
        return None
    value = profile.get(key)
    return value if isinstance(value, int) else None


def _profile_str(profile: Mapping[str, object] | None, key: str) -> str | None:
    if profile is None:
        return None
    value = profile.get(key)
    return value if isinstance(value, str) and value else None

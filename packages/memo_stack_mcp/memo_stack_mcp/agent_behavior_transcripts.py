"""External transcript corpus helpers for the agent behavior benchmark."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from memo_stack_core.agent_behavior_contract import (
    EXTERNAL_TRANSCRIPT_TAG,
    LIVE_SESSION_TAG,
    TRANSCRIPT_CORPUS_TAG,
)

from memo_stack_mcp.agent_behavior_types import (
    DEFAULT_TRANSCRIPT_CORPUS_MAX_BYTES,
    DEFAULT_TRANSCRIPT_CORPUS_MAX_FILES,
    AgentBenchFailure,
    AgentBenchScenario,
)
from memo_stack_mcp.agent_behavior_utils import bounded_int_env, safe_slug


def external_transcript_corpus_scenarios_from_env() -> tuple[AgentBenchScenario, ...]:
    raw_dir = os.getenv("MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR", "").strip()
    if not raw_dir:
        return ()
    root = Path(raw_dir).expanduser()
    if not root.is_dir():
        raise AgentBenchFailure(
            "MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR must point to a directory"
        )
    max_files = bounded_int_env(
        "MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_MAX_FILES",
        default=DEFAULT_TRANSCRIPT_CORPUS_MAX_FILES,
        minimum=1,
        maximum=200,
    )
    max_bytes = bounded_int_env(
        "MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_MAX_BYTES",
        default=DEFAULT_TRANSCRIPT_CORPUS_MAX_BYTES,
        minimum=1_000,
        maximum=2_000_000,
    )
    paths = sorted(
        path
        for path in root.iterdir()
        if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".txt"}
    )
    return tuple(
        _external_transcript_scenario_from_path(path, max_bytes=max_bytes)
        for path in paths[:max_files]
    )


def _external_transcript_scenario_from_path(
    path: Path,
    *,
    max_bytes: int,
) -> AgentBenchScenario:
    if path.stat().st_size > max_bytes:
        raise AgentBenchFailure(
            "Transcript corpus file exceeds MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_MAX_BYTES: "
            + path.name
        )
    raw_text = path.read_text(encoding="utf-8")
    payload = _parse_transcript_payload(path, raw_text)
    transcript = _external_transcript_text(payload)
    if not transcript.strip():
        raise AgentBenchFailure("Transcript corpus file has no transcript text: " + path.name)
    scenario_id = _external_transcript_scenario_id(path, payload)
    title = _external_transcript_value(payload, "title") or path.stem
    category = _external_transcript_value(payload, "category") or "document"
    task = _external_transcript_value(payload, "task") or (
        "Search memory first, ingest the transcript as evidence when useful, save only "
        "durable memory if explicit and non-secret, then answer from memory evidence."
    )
    user_prompt = _external_transcript_value(payload, "user_prompt") or (
        f"External anonymized live-agent transcript '{title}'. {task}\n\nTranscript:\n"
        + transcript
    )
    return AgentBenchScenario(
        id=scenario_id,
        category=category,
        tags=_external_transcript_tags(payload),
        user_prompt=user_prompt,
        setup_actions=_external_mapping_tuple(payload, "setup_actions"),
        expected_tools=_external_string_tuple(
            payload,
            "expected_tools",
            default=("memory_search", "memory_ingest_document"),
        ),
        forbidden_tools=_external_string_tuple(payload, "forbidden_tools"),
        forbidden_side_effects=_external_string_tuple(payload, "forbidden_side_effects"),
        required_tool_arg_checks=_external_mapping_tuple(payload, "required_tool_arg_checks"),
        required_memory_checks=_external_memory_checks(payload),
        critical=_external_bool(payload, "critical", default=True),
    )


def _parse_transcript_payload(path: Path, raw_text: str) -> object:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(raw_text)
    if suffix == ".jsonl":
        return [json.loads(line) for line in raw_text.splitlines() if line.strip()]
    return {"transcript": raw_text}


def _external_transcript_text(payload: object) -> str:
    if isinstance(payload, Mapping):
        direct = payload.get("transcript") or payload.get("text")
        if isinstance(direct, str):
            return direct
        turns = payload.get("turns") or payload.get("messages")
        if isinstance(turns, Sequence) and not isinstance(turns, str | bytes):
            return _render_external_turns(turns)
        return ""
    if isinstance(payload, Sequence) and not isinstance(payload, str | bytes):
        return _render_external_turns(payload)
    return ""


def _render_external_turns(turns: Sequence[object]) -> str:
    lines: list[str] = []
    for turn in turns:
        if isinstance(turn, Mapping):
            role = str(turn.get("role") or turn.get("speaker") or "unknown")
            text = turn.get("content") or turn.get("text") or turn.get("message") or ""
            if isinstance(text, str) and text.strip():
                lines.append(f"{role}: {text}")
        elif isinstance(turn, str) and turn.strip():
            lines.append(turn)
    return "\n".join(lines)


def _external_transcript_scenario_id(path: Path, payload: object) -> str:
    raw_id = _external_transcript_value(payload, "id") or path.stem
    safe = safe_slug(raw_id).replace(".", "-").replace(":", "-")[:80]
    return "external_transcript_" + (safe or "case")


def _external_transcript_tags(payload: object) -> tuple[str, ...]:
    raw_tags: Sequence[object] = ()
    if isinstance(payload, Mapping):
        value = payload.get("tags")
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            raw_tags = value
    tags = [LIVE_SESSION_TAG, TRANSCRIPT_CORPUS_TAG, EXTERNAL_TRANSCRIPT_TAG]
    tags.extend(str(tag) for tag in raw_tags if isinstance(tag, str) and tag.strip())
    return tuple(dict.fromkeys(tags))


def _external_memory_checks(payload: object) -> tuple[dict[str, Any], ...]:
    explicit = _external_mapping_tuple(payload, "required_memory_checks")
    if explicit:
        return explicit
    checks: list[dict[str, Any]] = []
    expected_memory = _external_string_list(payload, "expected_memory_contains")
    if expected_memory:
        checks.append(
            {
                "type": "memory_contains",
                "query": _external_transcript_value(payload, "expected_query")
                or " ".join(expected_memory[:3]),
                "contains": expected_memory,
            }
        )
    expected_answer = _external_string_list(payload, "expected_answer_contains")
    if expected_answer:
        checks.append({"type": "final_contains", "contains": expected_answer})
    forbidden = _external_string_list(payload, "forbidden_contains")
    if forbidden:
        checks.append(
            {
                "type": "final_not_contains",
                "not_contains": forbidden,
                "leak_metric": _external_transcript_value(payload, "leak_metric")
                or "secret_leak_count",
            }
        )
    return tuple(checks)


def _external_transcript_value(payload: object, key: str) -> str | None:
    if isinstance(payload, Mapping):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _external_bool(payload: object, key: str, *, default: bool) -> bool:
    if not isinstance(payload, Mapping):
        return default
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return default


def _external_string_tuple(
    payload: object,
    key: str,
    *,
    default: tuple[str, ...] = (),
) -> tuple[str, ...]:
    values = _external_string_list(payload, key)
    return tuple(values) if values else default


def _external_string_list(payload: object, key: str) -> list[str]:
    if not isinstance(payload, Mapping):
        return []
    value = payload.get(key)
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [str(item) for item in value if isinstance(item, str) and item]
    return []


def _external_mapping_tuple(payload: object, key: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(payload, Mapping):
        return ()
    value = payload.get(key)
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))

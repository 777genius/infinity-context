"""Stable, benchmark-neutral identity for comparison-run corpora."""

from __future__ import annotations

import json
from hashlib import sha256

from infinity_context_core.application.sensitive_text import redact_sensitive_text

from infinity_context_server.public_benchmark_checkpoint import safe_identifier
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase


def case_corpus_key(case: PublicBenchmarkCase) -> str:
    """Return a deterministic reusable-corpus key without exposing unsafe identifiers."""

    benchmark = safe_benchmark_identifier(case.benchmark, max_chars=80)
    memory_scope = safe_benchmark_identifier(
        case.memory_scope_external_ref or case.case_id,
        max_chars=240,
    )
    thread = safe_benchmark_identifier(
        case.thread_external_ref or case.case_id,
        max_chars=240,
    )
    return f"{benchmark}:{memory_scope}:{thread}:{case_corpus_fingerprint(case)}"


def case_corpus_fingerprint(case: PublicBenchmarkCase) -> str:
    """Hash all canonical ingress inputs while keeping raw content out of the key."""

    encoded = json.dumps(
        _case_sources(case),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()[:16]


def safe_benchmark_identifier(value: str, *, max_chars: int) -> str:
    redacted = redact_sensitive_text(str(value or "").strip()) or "missing"
    return safe_identifier(redacted, max_chars=max_chars)


def _case_sources(case: PublicBenchmarkCase) -> list[dict[str, object]]:
    sources: list[dict[str, object]] = []
    for index, memory in enumerate(case.memories):
        sources.append(
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
        sources.append(
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
    for index, conversation in enumerate(case.conversations):
        sources.append(
            {
                "kind": "conversation",
                "index": index,
                "source_external_id": conversation.source_external_id,
                "session_external_id": conversation.session_external_id,
                "session_date": conversation.session_date,
                "timestamp": conversation.timestamp,
                "metadata": dict(conversation.metadata),
                "messages": [
                    {
                        "role": message.role,
                        "content": message.content,
                        "source_external_id": message.source_external_id,
                        "timestamp": message.timestamp,
                        "metadata": dict(message.metadata),
                    }
                    for message in conversation.messages
                ],
            }
        )
    return sources


# Compatibility for the existing internal imports used by benchmark tests.
_case_corpus_key = case_corpus_key
_case_corpus_fingerprint = case_corpus_fingerprint
_safe_source_identifier = safe_benchmark_identifier

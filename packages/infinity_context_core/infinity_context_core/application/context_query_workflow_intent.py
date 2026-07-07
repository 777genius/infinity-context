"""Workflow intent helpers for task and commitment retrieval."""

from __future__ import annotations

import re

_WORKFLOW_COMMITMENT_QUERY_RE = re.compile(
    r"\b(?:what|which|who|when)\b(?=.{0,120}\b(?:needs?\s+to|has\s+to|"
    r"have\s+to|must|supposed\s+to|expected\s+to)\b)|"
    r"\b(?:what|which)\b(?=.{0,120}\b(?:is|are|'s)?\s*"
    r"(?:left|remaining|open|outstanding|pending|unfinished)\b)"
    r"(?=.{0,120}\b(?:do|task|tasks|todo|to-do|work|item|items|follow\s*-?\s*up|"
    r"next\s+steps?|action\s+items?)\b)|"
    r"\b(?:what|which)\b(?=.{0,120}\b(?:work|tasks?|todos?|to-dos?|items?)\b)"
    r"(?=.{0,120}\b(?:left|remaining|open|outstanding|pending|unfinished)\b)|"
    r"\b(?:needs?\s+to|has\s+to|have\s+to|supposed\s+to|expected\s+to)\s+"
    r"(?:do|send|finish|review|prepare|share|follow|complete|deliver|fix|pay|"
    r"submit|schedule|call|write|update|approve)\b|"
    r"\bmust\b(?=.{0,80}\b(?:do|send|finish|review|prepare|share|complete|"
    r"deliver|fix|pay|submit|schedule|call|write|update|approve)\b)|"
    r"\b(?:нужно|надо)\s+(?:сделать|отправить|закончить|проверить|"
    r"подготовить|доставить|исправить|заплатить|сдать|назначить|"
    r"написать|обновить|одобрить)\b|"
    r"\bдолжн\w*\b(?=.{0,80}\b(?:сделать|отправить|закончить|проверить|"
    r"подготовить|доставить|исправить|заплатить|сдать|назначить|"
    r"написать|обновить|одобрить)\b)",
    re.IGNORECASE | re.DOTALL,
)
_GOTCHA_FAILURE_QUERY_RE = re.compile(
    r"\b(?:gotchas?|pitfalls?|caveats?|known\s+issues?|known\s+problems?|"
    r"failure\s+mode|failure\s+modes|workaround|workarounds|root\s+cause|"
    r"blockers?|blocked\s+on|watch\s+out(?:\s+for)?|look\s+out(?:\s+for)?|"
    r"went\s+wrong|goes\s+wrong|"
    r"what\s+(?:failed|broke|blocked)|why\s+(?:failed|broke|blocked)|"
    r"why\s+did\s+.{0,80}\s+(?:fail|break|get\s+blocked)|"
    r"(?:avoid|avoid\s+next\s+time|not\s+repeat|do\s+not\s+repeat))\b|"
    r"\b(?:подводн\w+\s+камн\w*|известн\w+\s+(?:проблем\w*|ошибк\w*)|"
    r"что\s+пошло\s+не\s+так|почему\s+.{0,80}\s+(?:сломал\w*|упал\w*|"
    r"заблокировал\w*)|обходн\w+\s+пут\w*|воркэраунд\w*|"
    r"на\s+что\s+обратить\s+внимание|чего\s+избегать|не\s+повторять)\b",
    re.IGNORECASE | re.DOTALL,
)

_WORKFLOW_COMMITMENT_QUERY_VARIANTS = frozenset(
    {
        "workflow_commitment_request",
    }
)
_GOTCHA_FAILURE_QUERY_VARIANTS = frozenset(
    {
        "gotcha_failure_request",
    }
)


def workflow_commitment_query_variants(query: str) -> frozenset[str]:
    if not _WORKFLOW_COMMITMENT_QUERY_RE.search(query):
        return frozenset()
    return _WORKFLOW_COMMITMENT_QUERY_VARIANTS


def gotcha_failure_query_variants(query: str) -> frozenset[str]:
    if not _GOTCHA_FAILURE_QUERY_RE.search(query):
        return frozenset()
    return _GOTCHA_FAILURE_QUERY_VARIANTS

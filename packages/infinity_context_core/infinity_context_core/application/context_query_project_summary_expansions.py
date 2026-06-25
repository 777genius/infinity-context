"""Project summary query expansion rules for evidence-oriented retrieval."""

from __future__ import annotations

import re

_PROJECT_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,3}"
)

_PROJECT_SUMMARY_EXPANSION = (
    "project profile summary overview facts current status decisions chosen selected "
    "scope requirements milestones tasks action items owners risks blockers docs files "
    "meetings calls discussions evidence source of truth"
)
_RU_PROJECT_SUMMARY_EXPANSION = (
    "проект профиль обзор кратко факты текущий статус решения выбранный scope "
    "требования этапы задачи ответственные риски блокеры документы файлы "
    "встречи созвоны обсуждения evidence source of truth project summary"
)

_PROJECT_SUMMARY_QUERY_RE = re.compile(
    rf"(?i:\bwhat\s+is\s+project\s+){_PROJECT_LABEL_RE}\s*(?:\?|$)|"
    rf"(?i:\bwhat\s+(?:do|did)\s+(?:we|you)\s+know\s+about\s+project\s+)"
    rf"{_PROJECT_LABEL_RE}\b|"
    rf"(?i:\btell\s+me\s+about\s+project\s+){_PROJECT_LABEL_RE}\b|"
    rf"(?i:\bsummari[sz]e\s+project\s+){_PROJECT_LABEL_RE}\b|"
    rf"(?i:\bproject\s+){_PROJECT_LABEL_RE}(?i:\s+(?:summary|overview|profile))\b",
)
_RU_PROJECT_SUMMARY_QUERY_RE = re.compile(
    rf"(?i:\bчто\s+это\s+за\s+проект\s+){_PROJECT_LABEL_RE}\s*(?:\?|$)|"
    rf"(?i:\bчто\s+(?:мы|ты)\s+зна(?:ем|ешь)\s+(?:об|о|про)\s+проект\s+)"
    rf"{_PROJECT_LABEL_RE}\b|"
    rf"(?i:\bрасскажи\s+(?:об|о|про)\s+проект\s+){_PROJECT_LABEL_RE}\b|"
    rf"(?i:\bпрофиль\s+проекта\s+){_PROJECT_LABEL_RE}\b|"
    rf"(?i:\bсводка\s+по\s+проекту\s+){_PROJECT_LABEL_RE}\b",
)

PROJECT_SUMMARY_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"project_summary_query"}),
        _PROJECT_SUMMARY_EXPANSION,
        "project_summary_bridge",
    ),
    (
        frozenset({"ru_project_summary_query"}),
        _RU_PROJECT_SUMMARY_EXPANSION,
        "project_summary_bridge",
    ),
)


def project_summary_query_variants(query: str) -> frozenset[str]:
    variants: set[str] = set()
    if _PROJECT_SUMMARY_QUERY_RE.search(query):
        variants.add("project_summary_query")
    if _RU_PROJECT_SUMMARY_QUERY_RE.search(query):
        variants.add("ru_project_summary_query")
    return frozenset(variants)

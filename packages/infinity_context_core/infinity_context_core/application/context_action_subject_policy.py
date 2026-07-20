"""Conservative subject grounding for referential action evidence."""

from __future__ import annotations

import re

from infinity_context_core.application.context_identity_terms import (
    singularize_identity_term,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'./-]{0,39}")
_REFERENTIAL_ACTION_OBJECT_RE = re.compile(
    r"^(?:one|it)(?:\s+(?:from|through|via)\b|\s*$)",
    re.IGNORECASE,
)
_ACTION_CLAUSE_BOUNDARY_RE = re.compile(
    r"\s*(?:[,;]|\b(?:and|but|however|whereas|while)\b)\s*",
    re.IGNORECASE,
)
_ROLE_PREFIX_RE = re.compile(r"^\s*user:\s*", re.IGNORECASE)
_FIRST_PERSON_CLAUSE_SUBJECT_RE = re.compile(
    r"^\s*(?:(?:(?:last|this|next)\s+(?:day|week|month|year)|"
    r"today|yesterday|recently|finally|then)\s+)*"
    r"(?:I(?:'ve|'m|'d|'ll)?|we)\b",
    re.IGNORECASE,
)
_ELLIPTICAL_ACTION_PREFIX_RE = re.compile(
    r"^\s*(?:(?:today|yesterday|recently|finally|then|also|just)\s+)*$",
    re.IGNORECASE,
)


def resolve_first_person_referential_action_antecedent(
    sentence: str,
    *,
    action_start: int,
    action_object: str,
    aliases: frozenset[str],
) -> str:
    """Resolve a referential object only for an explicit first-person action clause."""

    if _REFERENTIAL_ACTION_OBJECT_RE.match(action_object) is None:
        return ""

    prefix = sentence[:action_start]
    boundaries = tuple(_ACTION_CLAUSE_BOUNDARY_RE.finditer(prefix))
    clause_start = boundaries[-1].end() if boundaries else 0
    clause_prefix = _ROLE_PREFIX_RE.sub("", prefix[clause_start:])
    if _FIRST_PERSON_CLAUSE_SUBJECT_RE.match(clause_prefix) is None and not (
        boundaries
        and _ELLIPTICAL_ACTION_PREFIX_RE.fullmatch(clause_prefix)
        and _previous_clause_has_first_person_subject(prefix, boundaries)
    ):
        return ""

    nearest = ""
    for token in _TOKEN_RE.finditer(sentence, 0, action_start):
        value = singularize_identity_term(token.group(0).casefold().strip(".'/-"))
        if value in aliases:
            nearest = token.group(0)
    return nearest


def _previous_clause_has_first_person_subject(
    prefix: str,
    boundaries: tuple[re.Match[str], ...],
) -> bool:
    previous_start = boundaries[-2].end() if len(boundaries) > 1 else 0
    previous_end = boundaries[-1].start()
    previous_clause = _ROLE_PREFIX_RE.sub("", prefix[previous_start:previous_end])
    return _FIRST_PERSON_CLAUSE_SUBJECT_RE.match(previous_clause) is not None

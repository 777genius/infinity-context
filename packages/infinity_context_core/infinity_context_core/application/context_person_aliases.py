"""Conservative person label alias helpers for retrieval signals."""

from __future__ import annotations

import re
from enum import Enum


class PersonAliasScope(Enum):
    EXACT_AND_GIVEN_NAME = "exact_and_given_name"


_PERSON_LABEL_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9._-]*")


def person_alias_keys(
    label: str,
    *,
    scope: PersonAliasScope = PersonAliasScope.EXACT_AND_GIVEN_NAME,
) -> frozenset[str]:
    """Return normalized aliases that avoid unsupported nickname inference."""

    tokens = tuple(_PERSON_LABEL_TOKEN_RE.findall(label or ""))
    if not tokens:
        return frozenset()
    aliases = {_normalized_label(" ".join(tokens))}
    if scope is PersonAliasScope.EXACT_AND_GIVEN_NAME and len(tokens) > 1:
        aliases.add(_normalized_label(tokens[0]))
    return frozenset(alias for alias in aliases if alias)


def person_labels_match(left: str, right: str) -> bool:
    """Return true when labels match exactly or by explicit given-name alias."""

    left_tokens = _person_label_tokens(left)
    right_tokens = _person_label_tokens(right)
    if len(left_tokens) > 1 and len(right_tokens) > 1:
        return _normalized_label(" ".join(left_tokens)) == _normalized_label(
            " ".join(right_tokens)
        )
    return bool(person_alias_keys(left).intersection(person_alias_keys(right)))


def _person_label_tokens(label: str) -> tuple[str, ...]:
    return tuple(_PERSON_LABEL_TOKEN_RE.findall(label or ""))


def _normalized_label(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())

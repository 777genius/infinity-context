"""Finite full-word Russian inflections, never stemming or semantic expansion."""

from __future__ import annotations

import unicodedata

_FAMILIES = (
    ("встреча", "встрече", "встречу"),
    ("релиз", "релизе", "релиза"),
    ("документ", "документе", "документа"),
    ("решение", "решении", "решения"),
    ("настройка", "настройке", "настройки"),
)
_BY_WORD = {word: family for family in _FAMILIES for word in family}


def keyword_family_key(folded: str) -> str:
    family = _BY_WORD.get(folded)
    return family[0] if family else folded


def generated_keyword_aliases(canonical: str) -> tuple[str, ...]:
    folded = unicodedata.normalize("NFKC", canonical).casefold()
    originals = {canonical, folded}
    return tuple(word for word in _BY_WORD.get(folded, ()) if word not in originals)

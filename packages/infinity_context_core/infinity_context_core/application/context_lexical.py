"""Bounded lexical matching helpers for memory retrieval."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

_TERM_RE = re.compile(r"\w+", re.UNICODE)
_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
_LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)
_RUSSIAN_SUFFIXES = (
    "иями",
    "ями",
    "ами",
    "ыми",
    "ими",
    "ого",
    "его",
    "ому",
    "ему",
    "иях",
    "ах",
    "ях",
    "ов",
    "ев",
    "ом",
    "ем",
    "ой",
    "ей",
    "ою",
    "ею",
    "ам",
    "ям",
    "ую",
    "юю",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "а",
    "я",
    "у",
    "ю",
    "е",
    "ы",
    "и",
)
_RUSSIAN_VOWELS = str.maketrans("", "", "аеёиоуыэюя")
_CROSS_LANGUAGE_ALIASES = {
    "alex": ("aleks", "алекс"),
    "aleks": ("alex", "алекс"),
    "atlas": ("атлас",),
    "audio": ("аудио",),
    "bill": ("invoice", "счет", "счёт"),
    "billing": ("биллинг",),
    "call": ("созвон", "звонок", "встреч"),
    "demo": ("демо",),
    "document": ("документ",),
    "image": ("изображение", "картинка", "фото"),
    "invoice": ("инвойс", "счет", "счёт", "bill"),
    "launch": ("запуск",),
    "meeting": ("встреч", "созвон"),
    "owner": ("владелец", "владельц"),
    "project": ("проект",),
    "recording": ("запись", "транскрипт", "transcript"),
    "screenshot": ("скриншот", "снимок"),
    "summary": ("резюме", "саммари"),
    "transcript": ("транскрипт", "запись", "recording"),
    "video": ("видео", "видеозапись", "видеофрагмент"),
    "алекс": ("alex", "aleks"),
    "атлас": ("atlas",),
    "аудио": ("audio",),
    "биллинг": ("billing",),
    "видео": ("video",),
    "видеозапись": ("video",),
    "видеофрагмент": ("video",),
    "владелец": ("owner",),
    "владельц": ("owner",),
    "встреч": ("meeting", "call"),
    "демо": ("demo",),
    "документ": ("document",),
    "запись": ("recording", "transcript"),
    "запуск": ("launch",),
    "звонок": ("call",),
    "изображение": ("image",),
    "инвойс": ("invoice", "bill"),
    "картинка": ("image",),
    "проект": ("project",),
    "резюме": ("summary",),
    "саммари": ("summary",),
    "снимок": ("screenshot",),
    "созвон": ("call", "meeting"),
    "скриншот": ("screenshot",),
    "счет": ("invoice", "bill"),
    "счёт": ("invoice", "bill"),
    "транскрипт": ("transcript", "recording"),
    "фото": ("image",),
}


@dataclass(frozen=True)
class LexicalQueryTerm:
    raw: str
    variants: tuple[str, ...]


def query_terms(
    text: str,
    *,
    min_chars: int = 3,
    max_terms: int | None = None,
    split_underscores: bool = False,
) -> tuple[LexicalQueryTerm, ...]:
    terms: list[LexicalQueryTerm] = []
    seen: set[str] = set()
    for token in _tokens(text, split_underscores=split_underscores):
        if len(token) < min_chars or token in seen:
            continue
        variants = lexical_variants(token)
        if not variants:
            continue
        terms.append(LexicalQueryTerm(raw=token, variants=variants))
        seen.add(token)
        if max_terms is not None and len(terms) >= max_terms:
            break
    return tuple(terms)


def text_variant_counts(text: str, *, min_chars: int = 2) -> Counter[str]:
    counts: Counter[str] = Counter()
    for token in _tokens(text, split_underscores=True):
        if len(token) < min_chars:
            continue
        for variant in lexical_variants(token):
            counts[variant] += 1
    return counts


def text_variant_sequence(text: str, *, min_chars: int = 2) -> tuple[tuple[str, ...], ...]:
    return tuple(
        variants
        for token in _tokens(text, split_underscores=True)
        if len(token) >= min_chars
        for variants in (_text_token_variants(token),)
        if variants
    )


def query_term_frequency(term: LexicalQueryTerm, text_counts: Counter[str]) -> int:
    return max((text_counts.get(variant, 0) for variant in term.variants), default=0)


def matching_token_spans(
    *,
    text: str,
    terms: tuple[LexicalQueryTerm, ...],
) -> tuple[tuple[int, int, str], ...]:
    if not terms:
        return ()
    hits: list[tuple[int, int, str]] = []
    for match in _TERM_RE.finditer(text):
        token = _normalize_token(match.group(0))
        token_variants = set(_text_token_variants(token))
        if not token_variants:
            continue
        for term in terms:
            if token_variants.intersection(term.variants):
                hits.append((match.start(), match.end(), term.raw))
    return tuple(sorted(hits, key=lambda hit: (hit[0], hit[1], hit[2])))


def lexical_variants(token: str) -> tuple[str, ...]:
    normalized = _normalize_token(token)
    if not normalized:
        return ()
    variants = [normalized]
    if _has_cyrillic(normalized):
        variants.extend(_russian_variants(normalized))
    elif _has_latin(normalized):
        variants.extend(_english_variants(normalized))
    return _expand_cross_language_aliases(
        variant for variant in variants if len(variant) >= 2
    )


def _tokens(text: str, *, split_underscores: bool) -> tuple[str, ...]:
    tokens: list[str] = []
    for match in _TERM_RE.finditer(text):
        token = _normalize_token(match.group(0))
        if token:
            tokens.append(token)
        if split_underscores:
            tokens.extend(
                part
                for part in (_normalize_token(part) for part in match.group(0).split("_"))
                if part and part != token
            )
    return tuple(tokens)


def _text_token_variants(token: str) -> tuple[str, ...]:
    variants = list(lexical_variants(token))
    for part in token.split("_"):
        if part and part != token:
            variants.extend(lexical_variants(part))
    return _dedupe(variants)


def _normalize_token(token: str) -> str:
    return token.casefold().replace("ё", "е").strip("_")


def _russian_variants(token: str) -> tuple[str, ...]:
    variants: list[str] = []
    for suffix in _RUSSIAN_SUFFIXES:
        if not token.endswith(suffix):
            continue
        stem = token[: -len(suffix)]
        if len(stem) >= 3:
            variants.append(stem)
            skeleton = stem.translate(_RUSSIAN_VOWELS)
            if len(skeleton) >= 3:
                variants.append(skeleton)
        break
    skeleton = token.translate(_RUSSIAN_VOWELS)
    if len(skeleton) >= 3:
        variants.append(skeleton)
    return tuple(variants)


def _english_variants(token: str) -> tuple[str, ...]:
    variants: list[str] = []
    for candidate in _english_stems(token):
        variants.append(candidate)
        variants.extend(_english_stems(candidate))
    return tuple(variants)


def _english_stems(token: str) -> tuple[str, ...]:
    stems: list[str] = []
    if len(token) > 4 and token.endswith("ies"):
        stems.append(f"{token[:-3]}y")
    if len(token) > 5 and token.endswith("ing"):
        stems.append(token[:-3])
    if len(token) > 4 and token.endswith("ed"):
        stems.append(token[:-2])
    if len(token) > 4 and token.endswith("es"):
        stems.append(token[:-2])
    if len(token) > 3 and token.endswith("s"):
        stems.append(token[:-1])
    return tuple(stem for stem in stems if len(stem) >= 3)


def _expand_cross_language_aliases(values: Iterable[str]) -> tuple[str, ...]:
    expanded: list[str] = []
    for value in values:
        expanded.append(value)
        for alias in _CROSS_LANGUAGE_ALIASES.get(value, ()):
            normalized_alias = _normalize_token(alias)
            if len(normalized_alias) < 2:
                continue
            expanded.append(normalized_alias)
            if _has_cyrillic(normalized_alias):
                expanded.extend(_russian_variants(normalized_alias))
            elif _has_latin(normalized_alias):
                expanded.extend(_english_stems(normalized_alias))
    return _dedupe(variant for variant in expanded if len(variant) >= 2)


def _has_cyrillic(token: str) -> bool:
    return _CYRILLIC_RE.search(token) is not None


def _has_latin(token: str) -> bool:
    return _LATIN_RE.search(token) is not None


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)

"""Bounded lexical matching helpers for memory retrieval."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from infinity_context_core.application.anchor_identity_normalization import (
    canonical_token,
    normalize_cyrillic_person_case,
    normalize_cyrillic_project_case,
)

_TERM_RE = re.compile(r"\w+", re.UNICODE)
_ISO_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>(?:19|20)\d{2})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})(?!\d)"
)
_LOCAL_DATE_RE = re.compile(
    r"(?<!\d)(?P<first>\d{1,2})[-/.](?P<second>\d{1,2})[-/.](?P<year>(?:19|20)\d{2})(?!\d)"
)
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
    "activity": ("hobby", "camping", "hiking", "painting", "pottery", "swimming"),
    "activities": ("hobbies", "camping", "hiking", "painting", "pottery", "swimming"),
    "adopt": ("adoption", "family", "kids", "children", "mom", "agency"),
    "adoption": ("adopt", "family", "kids", "children", "mom", "agency"),
    "ago": ("назад",),
    "agree": ("agreed", "commitment"),
    "agreed": ("agree", "commitment"),
    "alex": ("aleks", "алекс"),
    "aleks": ("alex", "алекс"),
    "art": ("painting",),
    "area": ("place", "region", "state", "city", "country", "visited", "vacationed"),
    "areas": ("places", "regions", "states", "cities", "countries", "visited", "vacationed"),
    "artifact": ("file", "document", "attachment", "артефакт"),
    "atlas": ("атлас",),
    "audio": ("аудио",),
    "attachment": ("file", "artifact", "document", "вложение", "файл"),
    "bill": ("invoice", "счет", "счёт"),
    "billing": ("биллинг",),
    "book": ("novel", "story"),
    "books": ("novels", "stories"),
    "call": ("созвон", "звонок", "встреч"),
    "career": ("job", "jobs", "work", "profession", "occupation", "counseling"),
    "church": ("religious", "faith"),
    "compassion": ("kindness", "care", "support", "friendship"),
    "consider": ("explore", "look", "looking", "pursue", "interested", "interest"),
    "conservative": ("political", "religious"),
    "conservatives": ("political", "religious"),
    "counseling": ("counselor", "mental", "health", "career", "jobs", "work"),
    "counselor": ("counseling", "mental", "health", "career", "jobs", "work"),
    "demo": ("демо",),
    "destress": ("therapy", "therapeutic", "relax", "calm", "running", "pottery"),
    "decision": ("choice", "plan", "goal"),
    "discuss": (
        "discussed",
        "обсудил",
        "обсудила",
        "обсудили",
        "обсуждал",
        "обсуждала",
        "обсуждали",
    ),
    "discussed": (
        "discuss",
        "обсудил",
        "обсудила",
        "обсудили",
        "обсуждал",
        "обсуждала",
        "обсуждали",
    ),
    "document": ("file", "attachment", "artifact", "документ", "файл", "вложение"),
    "event": (
        "meeting",
        "call",
        "conversation",
        "conference",
        "workshop",
        "show",
        "run",
        "событие",
        "встреч",
        "созвон",
    ),
    "events": ("meeting", "meetings", "conference", "workshop", "show", "run"),
    "education": ("school", "study", "studies", "learning", "counseling"),
    "explore": ("consider", "considering", "pursue", "looking", "interest"),
    "file": ("document", "attachment", "artifact", "файл", "документ", "вложение"),
    "faith": ("religious", "church"),
    "family": ("children", "kids", "husband"),
    "gratitude": ("thankful", "thanks", "appreciate", "impact"),
    "health": ("mental", "counseling"),
    "hobby": ("activity", "camping", "hiking", "painting", "pottery", "swimming"),
    "hobbies": ("activities", "camping", "hiking", "painting", "pottery", "swimming"),
    "hour": ("час",),
    "image": ("изображение", "картинка", "фото"),
    "identity": ("gender", "transgender"),
    "item": ("thing", "object", "collection", "keepsake"),
    "items": ("things", "objects", "collections", "keepsakes"),
    "invoice": ("инвойс", "счет", "счёт", "bill"),
    "job": ("career", "work", "profession", "occupation"),
    "jobs": ("career", "work", "profession", "occupation"),
    "launch": ("запуск",),
    "leaning": ("political", "rights", "conservative", "conservatives"),
    "like": ("enjoy", "love"),
    "loved": ("love", "like", "enjoy", "read", "reading"),
    "lgbtq": ("community", "parade", "pride", "queer", "transgender"),
    "look": ("consider", "explore", "pursue", "interested", "interest"),
    "looking": ("consider", "explore", "pursue", "interested", "interest"),
    "meeting": ("встреч", "созвон"),
    "mentioned": (
        "said",
        "told",
        "упомянул",
        "упомянула",
        "упоминал",
        "упоминала",
        "упоминали",
        "сказал",
        "сказала",
    ),
    "mental": ("health", "counseling"),
    "motivated": ("inspired", "reason", "because", "journey", "support", "impact"),
    "motivating": ("inspired", "reason", "because", "journey", "support", "impact"),
    "motivation": ("inspired", "reason", "because", "journey", "support", "impact"),
    "move": ("moved", "home", "country", "roots"),
    "moved": ("move", "home", "country", "roots"),
    "national": ("outdoors", "outdoor", "camping", "hiking", "nature", "canyon"),
    "option": ("choice", "path", "career", "job", "jobs"),
    "outdoor": ("camping", "camp", "campfire", "hiking", "nature"),
    "outdoors": ("camping", "camp", "campfire", "hiking", "nature"),
    "owner": ("владелец", "владельц"),
    "park": ("outdoors", "outdoor", "camping", "hiking", "nature", "canyon"),
    "participate": ("attend", "attended", "join", "joined", "march", "went"),
    "participat": ("attend", "attended", "join", "joined", "went"),
    "political": ("rights", "activist", "activism", "conservative", "conservatives"),
    "preform": ("perform", "performed", "performance"),
    "preformed": ("performed", "perform", "performance"),
    "preforming": ("performing", "perform", "performance"),
    "persue": ("pursue", "career", "path"),
    "persued": ("pursued", "pursue", "career", "path"),
    "persuing": ("pursuing", "pursue", "career", "path"),
    "pursu": ("consider", "explore", "look", "looking", "interested", "interest"),
    "pursue": ("consider", "explore", "look", "looking", "interested", "interest"),
    "pursued": ("consider", "explore", "look", "looking", "interested", "interest"),
    "pursuing": ("consider", "explore", "look", "looking", "interested", "interest"),
    "project": ("проект",),
    "said": (
        "told",
        "mentioned",
        "сказал",
        "сказала",
        "упомянул",
        "упомянула",
        "упоминал",
        "упоминала",
    ),
    "say": ("said", "told", "mentioned", "сказал", "сказала"),
    "read": ("reading",),
    "reading": ("read",),
    "reccomend": ("recommend", "recommended", "recommendation"),
    "reccomendation": ("recommendation", "recommend", "recommended"),
    "reccomended": ("recommended", "recommend", "recommendation"),
    "recording": ("запись", "транскрипт", "transcript"),
    "religious": ("church", "faith", "conservative", "conservatives"),
    "remind": ("reminds", "reminder", "sentimental", "memory", "symbol", "meaning"),
    "reminder": ("remind", "reminds", "sentimental", "memory", "symbol", "meaning"),
    "reminds": ("remind", "reminder", "sentimental", "memory", "symbol", "meaning"),
    "relationship": ("single", "partner", "breakup", "dating", "married"),
    "screenshot": ("скриншот", "снимок"),
    "support": ("supportive", "supported", "accept", "accepted", "acceptance"),
    "supportive": ("support", "supported", "accept", "accepted", "acceptance"),
    "state": ("place", "region", "area"),
    "states": ("places", "regions", "areas"),
    "summary": ("резюме", "саммари"),
    "told": ("said", "mentioned", "сказал", "сказала", "рассказал", "рассказала"),
    "transcript": ("транскрипт", "запись", "recording"),
    "transgender": ("identity", "gender"),
    "vacationed": ("visited", "traveled", "trip", "travel"),
    "video": ("видео", "видеозапись", "видеофрагмент"),
    "veteran": ("veterans", "military", "service", "charity"),
    "veterans": ("veteran", "military", "service", "charity"),
    "volunteer": ("volunteering", "helped", "charity", "shelter", "community"),
    "volunteering": ("volunteer", "helped", "charity", "shelter", "community"),
    "week": ("недел",),
    "work": ("career", "job", "jobs", "profession", "occupation"),
    "write": (
        "wrote",
        "written",
        "написал",
        "написала",
        "написали",
        "писал",
        "писала",
        "писали",
    ),
    "written": (
        "write",
        "wrote",
        "написал",
        "написала",
        "написали",
        "писал",
        "писала",
        "писали",
    ),
    "wrote": (
        "write",
        "written",
        "написал",
        "написала",
        "написали",
        "писал",
        "писала",
        "писали",
    ),
    "алекс": ("alex", "aleks"),
    "артефакт": ("artifact", "file", "document", "attachment"),
    "атлас": ("atlas",),
    "аудио": ("audio",),
    "биллинг": ("billing",),
    "видео": ("video",),
    "видеозапись": ("video",),
    "видеофрагмент": ("video",),
    "вложение": ("attachment", "file", "document", "artifact"),
    "владелец": ("owner",),
    "владельц": ("owner",),
    "встреч": ("meeting", "call"),
    "демо": ("demo",),
    "документ": ("document",),
    "запись": ("recording", "transcript"),
    "запуск": ("launch",),
    "звонок": ("call",),
    "изображение": ("image",),
    "идентичность": ("identity", "gender"),
    "инвойс": ("invoice", "bill"),
    "картинка": ("image",),
    "обсудил": ("discussed", "discuss"),
    "обсудила": ("discussed", "discuss"),
    "обсудили": ("discussed", "discuss"),
    "обсуждал": ("discussed", "discuss"),
    "обсуждала": ("discussed", "discuss"),
    "обсуждали": ("discussed", "discuss"),
    "отношения": ("relationship", "single", "partner", "breakup"),
    "проект": ("project",),
    "рассказал": ("told", "said"),
    "рассказала": ("told", "said"),
    "резюме": ("summary",),
    "саммари": ("summary",),
    "снимок": ("screenshot",),
    "созвон": ("call", "meeting"),
    "скриншот": ("screenshot",),
    "счет": ("invoice", "bill"),
    "счёт": ("invoice", "bill"),
    "транскрипт": ("transcript", "recording"),
    "фото": ("image",),
    "файл": ("file", "document", "attachment", "artifact"),
    "час": ("hour",),
    "недел": ("week",),
    "назад": ("ago",),
    "сказал": ("said", "told", "mentioned"),
    "сказала": ("said", "told", "mentioned"),
    "событие": ("event", "meeting", "call"),
    "упомянул": ("mentioned", "said", "told"),
    "упомянула": ("mentioned", "said", "told"),
    "упоминал": ("mentioned", "said", "told"),
    "упоминала": ("mentioned", "said", "told"),
    "упоминали": ("mentioned", "said", "told"),
    "написал": ("wrote", "write", "written"),
    "написала": ("wrote", "write", "written"),
    "написали": ("wrote", "write", "written"),
    "писал": ("wrote", "write", "written"),
    "писала": ("wrote", "write", "written"),
    "писали": ("wrote", "write", "written"),
}
_QUERY_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "also",
        "and",
        "any",
        "are",
        "because",
        "been",
        "before",
        "being",
        "but",
        "can",
        "could",
        "did",
        "does",
        "doing",
        "done",
        "find",
        "for",
        "from",
        "had",
        "has",
        "have",
        "her",
        "here",
        "hers",
        "him",
        "his",
        "how",
        "into",
        "its",
        "likely",
        "may",
        "might",
        "our",
        "ours",
        "please",
        "search",
        "she",
        "show",
        "should",
        "that",
        "the",
        "their",
        "theirs",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "tell",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "whose",
        "why",
        "will",
        "with",
        "would",
        "your",
        "yours",
        "где",
        "для",
        "его",
        "если",
        "еще",
        "ещё",
        "как",
        "какая",
        "какие",
        "какой",
        "когда",
        "кто",
        "найти",
        "мне",
        "надо",
        "наш",
        "наша",
        "наше",
        "наши",
        "найди",
        "нужно",
        "она",
        "они",
        "оно",
        "показать",
        "покажи",
        "пожалуйста",
        "про",
        "расскажи",
        "скажи",
        "там",
        "тебе",
        "тут",
        "что",
        "это",
        "этот",
    }
)


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
        if len(token) < min_chars or token in seen or token in _QUERY_STOPWORDS:
            continue
        variants = lexical_variants(token)
        if not variants:
            continue
        terms.append(LexicalQueryTerm(raw=token, variants=variants))
        seen.add(token)
        if max_terms is not None and len(terms) >= max_terms:
            break
    return tuple(terms)


def text_variant_profile(
    text: str,
    *,
    min_chars: int = 2,
) -> tuple[Counter[str], tuple[tuple[str, ...], ...]]:
    counts: Counter[str] = Counter()
    sequence: list[tuple[str, ...]] = []
    for token in _tokens(text, split_underscores=True):
        if len(token) < min_chars:
            continue
        variants = _text_token_variants(token)
        if not variants:
            continue
        sequence.append(variants)
        for variant in variants:
            counts[variant] += 1
    return counts, tuple(sequence)


def text_variant_stats(text: str, *, min_chars: int = 2) -> tuple[Counter[str], int]:
    counts, sequence = text_variant_profile(text, min_chars=min_chars)
    return counts, len(sequence)


def text_variant_counts(text: str, *, min_chars: int = 2) -> Counter[str]:
    counts, _ = text_variant_stats(text, min_chars=min_chars)
    return counts


def text_variant_sequence(text: str, *, min_chars: int = 2) -> tuple[tuple[str, ...], ...]:
    _, sequence = text_variant_profile(text, min_chars=min_chars)
    return sequence


def query_term_frequency(term: LexicalQueryTerm, text_counts: Mapping[str, int]) -> int:
    exact_frequency = max((text_counts.get(variant, 0) for variant in term.variants), default=0)
    if exact_frequency > 0:
        return exact_frequency
    return _approximate_term_frequency(term.variants, text_counts)


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
    return _expand_cross_language_aliases(variant for variant in variants if len(variant) >= 2)


def _tokens(text: str, *, split_underscores: bool) -> tuple[str, ...]:
    tokens: list[str] = []
    tokens.extend(date_tokens(text))
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


def date_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for match in _ISO_DATE_RE.finditer(text):
        _append_date_token(
            tokens,
            year=int(match.group("year")),
            month=int(match.group("month")),
            day=int(match.group("day")),
        )
    for match in _LOCAL_DATE_RE.finditer(text):
        first = int(match.group("first"))
        second = int(match.group("second"))
        year = int(match.group("year"))
        if first > 12 >= second:
            _append_date_token(tokens, year=year, month=second, day=first)
        elif second > 12 >= first:
            _append_date_token(tokens, year=year, month=first, day=second)
        else:
            _append_date_token(tokens, year=year, month=first, day=second)
            _append_date_token(tokens, year=year, month=second, day=first)
    return tuple(dict.fromkeys(tokens))


def _append_date_token(tokens: list[str], *, year: int, month: int, day: int) -> None:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return
    tokens.append(f"date_{year:04d}_{month:02d}_{day:02d}")


def _text_token_variants(token: str) -> tuple[str, ...]:
    variants = list(lexical_variants(token))
    for part in token.split("_"):
        if part and part != token:
            variants.extend(lexical_variants(part))
    variants.extend(_underscore_prefix_variants(token))
    return _dedupe(variants)


def _normalize_token(token: str) -> str:
    return token.casefold().replace("ё", "е").strip("_")


def _underscore_prefix_variants(token: str) -> tuple[str, ...]:
    parts = tuple(part for part in token.split("_") if len(part) >= 2)
    if len(parts) < 2:
        return ()
    prefixes: list[str] = []
    for index in range(2, len(parts)):
        prefix = "_".join(parts[:index])
        if len(prefix) >= 3:
            prefixes.extend(lexical_variants(prefix))
    return tuple(prefixes)


def _russian_variants(token: str) -> tuple[str, ...]:
    variants: list[str] = []
    for normalized_case in (
        normalize_cyrillic_person_case(token),
        normalize_cyrillic_project_case(token),
    ):
        if normalized_case != token and len(normalized_case) >= 3:
            variants.append(normalized_case)
            variants.extend(_cyrillic_transliteration_variants(normalized_case))
    variants.extend(_cyrillic_transliteration_variants(token))
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


def _cyrillic_transliteration_variants(token: str) -> tuple[str, ...]:
    if not _has_cyrillic(token):
        return ()
    transliterated = canonical_token(token)
    variants = [transliterated] if len(transliterated) >= 3 else []
    if transliterated.endswith("ei") and len(transliterated) > 3:
        variants.append(f"{transliterated[:-2]}ey")
    if transliterated.endswith("iya") and len(transliterated) > 4:
        variants.append(f"{transliterated[:-3]}ia")
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


def _approximate_term_frequency(
    variants: tuple[str, ...],
    text_counts: Counter[str],
) -> int:
    long_variants = tuple(
        variant for variant in variants if len(variant) >= 6 and not variant.startswith("date_")
    )
    if not long_variants:
        return 0
    for variant in long_variants:
        for candidate, frequency in text_counts.items():
            if len(candidate) < 6 or abs(len(candidate) - len(variant)) > 1:
                continue
            if _edit_distance_at_most_one(variant, candidate):
                return frequency
    return 0


def _edit_distance_at_most_one(left: str, right: str) -> bool:
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    mismatch_count = 0
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        if left[left_index] == right[right_index]:
            left_index += 1
            right_index += 1
            continue
        mismatch_count += 1
        if mismatch_count > 1:
            return False
        if len(left) == len(right):
            left_index += 1
        right_index += 1
    return True


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

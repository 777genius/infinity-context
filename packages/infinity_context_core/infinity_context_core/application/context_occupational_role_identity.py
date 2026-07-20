"""Pure grammar for separating self occupational roles from person identities."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SELF_ROLE_TITLE_AFTER_RE = re.compile(
    r"(?:"
    r"\b(?:my|our)\s+(?:(?:new|current|former|previous|first|latest)\s+){0,3}"
    r"(?:job\s+title|role|position|job|title|occupation)"
    r"(?:['’]s\s+title)?\s*(?:as|is|was|of|:|,|=|[-–—])\s+|"
    r"\bI\s+(?:(?:currently|now|formerly|previously)\s+){0,2}"
    r"(?:work(?:ed|s|ing)?|serve(?:d|s|ing)?|act(?:ed|s|ing)?)\s+as\s+"
    r"(?:(?:a|an|the)\s+)?|"
    r"\bI\s+(?:(?:currently|now|formerly|previously)\s+){0,2}"
    r"(?:am|was|became|remain(?:ed)?)\s+(?:(?:a|an|the)\s+)?|"
    r"\bI(?:['’]m)\s+(?:(?:currently|now)\s+)?(?:(?:a|an|the)\s+)?"
    r")",
    re.IGNORECASE,
)
_SELF_ROLE_TITLE_BEFORE_MARKER_RE = re.compile(
    r"\b(?:is|was|became|remains)\s+my\s+"
    r"(?:(?:new|current|former|previous|first|latest)\s+)?"
    r"(?:job\s+title|role|position|job|title|occupation)\b",
    re.IGNORECASE,
)
_SELF_MODIFIED_ROLE_PREFIX_RE = re.compile(
    r"\bmy\s+(?:(?:new|current|former|previous|first|latest)\s+)?",
    re.IGNORECASE,
)
_SELF_MODIFIED_ROLE_SUFFIX_RE = re.compile(
    r"\s+(?:role|position|job)\b",
    re.IGNORECASE,
)
_LEADING_SELF_ROLE_RE = re.compile(
    r"(?:^|[.!?;]\s+)as\s+(?:(?:a|an|the)\s+)?",
    re.IGNORECASE,
)
_LEADING_SELF_ROLE_SUFFIX_RE = re.compile(
    r"\s*,\s*(?:I|we)\b",
    re.IGNORECASE,
)

_ROLE_TITLE_HEAD_RE = re.compile(
    r"\b(?:"
    r"accountant|administrator|analyst|architect|attorney|auditor|barista|"
    r"carpenter|chef|chief|clinician|coach|consultant|counselor|designer|developer|"
    r"director|doctor|editor|educator|electrician|engineer|engineering|executive|"
    r"coordinator|counsel|founder|head|lead|manager|master|mechanic|nurse|officer|"
    r"operator|owner|partner|pharmacist|physician|pilot|planner|president|producer|"
    r"professor|programmer|recruiter|representative|researcher|scientist|specialist|"
    r"strategist|supervisor|teacher|technician|therapist|veterinarian|writer|"
    r"ceo|cfo|cio|cmo|coo|cto|vp"
    r")s?\b",
    re.IGNORECASE,
)
_ROLE_WORD_RE = re.compile(
    r"(?:[^\W\d_]\.){2,}|"
    r"(?:(?:Assoc|Asst|Capt|Col|Dr|Exec|Jr|Lt|Mr|Mrs|Ms|Prof|Rev|Sr)\.)|"
    r"(?:[^\W\d_]\.)|"
    r"(?:[^\W\d_](?:[^\W_]|[+#/-])*(?:[.&'’](?:[^\W_]|[+#/-])+)*)"
)

_TITLE_CONNECTORS = frozenset({"for", "in", "of", "on", "the", "to"})
_SUBORDINATE_TITLE_CONNECTORS = frozenset({"for", "in", "of"})
_TITLE_FUNCTION_WORDS = frozenset(
    {
        "ai",
        "commercial",
        "customer",
        "data",
        "development",
        "engineering",
        "enterprise",
        "finance",
        "global",
        "growth",
        "infrastructure",
        "marketing",
        "operations",
        "people",
        "platform",
        "product",
        "research",
        "sales",
        "security",
        "strategy",
        "support",
        "technology",
    }
)
_PERSON_TITLE_PREFIXES = frozenset(
    {
        "capt",
        "captain",
        "chief",
        "col",
        "colonel",
        "director",
        "doctor",
        "dr",
        "lt",
        "manager",
        "miss",
        "mr",
        "mrs",
        "ms",
        "president",
        "prof",
        "professor",
        "rev",
        "reverend",
    }
)
_PERSON_CREDENTIALS = frozenset(
    {
        "ba",
        "bsc",
        "dds",
        "dmd",
        "dphil",
        "edd",
        "esq",
        "jd",
        "ma",
        "mba",
        "md",
        "mph",
        "msc",
        "pharmd",
        "phd",
        "rn",
    }
)
_OPEN_TO_CLOSE = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'", "“": "”", "‘": "’"}
_OPEN_GROUPS = frozenset(_OPEN_TO_CLOSE)
_CLOSE_GROUPS = frozenset(_OPEN_TO_CLOSE.values())
_CREDENTIAL_OPEN_GROUPS = frozenset({"(", "[", "{"})
_MAX_TITLE_CHARS = 320
_MAX_TITLE_TOKENS = 80
_MAX_TITLE_WORDS = 20
_MAX_QUALIFIER_DEPTH = 3


@dataclass(frozen=True, slots=True)
class _RoleToken:
    kind: str
    text: str
    start: int
    end: int

    @property
    def normalized(self) -> str:
        return self.text.casefold().replace(".", "")

    @property
    def is_possessive(self) -> bool:
        return self.text.casefold().endswith(("'s", "’s"))


@dataclass(frozen=True, slots=True)
class _ParsedTitle:
    start: int
    end: int
    next_token: int
    word_count: int


def is_self_occupational_role_label(*, label: str, text: str) -> bool:
    """Return whether every occurrence of ``label`` is within a self-role phrase."""

    label_spans = _case_insensitive_label_spans(text, label)
    if not label_spans:
        return False
    role_spans = _self_occupational_role_spans(text)
    if not role_spans:
        return False
    for start, end in label_spans:
        if text[end : end + 2] in {"'s", "’s"}:
            return False
        if not any(role_start <= start and end <= role_end for role_start, role_end in role_spans):
            return False
    return True


def is_non_person_identity_label(*, label: str, text: str) -> bool:
    """Return whether every label occurrence is role or credential syntax, not a person."""

    label_spans = _case_insensitive_label_spans(text, label)
    if not label_spans:
        return False
    role_spans = _self_occupational_role_spans(text)
    return all(
        _span_is_within(start, end, role_spans)
        or _is_person_credential_appositive(text, start, end)
        for start, end in label_spans
    )


def _case_insensitive_label_spans(text: str, label: str) -> tuple[tuple[int, int], ...]:
    words = tuple(part for part in re.split(r"\s+", label.strip()) if part)
    if not words:
        return ()
    label_pattern = r"\s+".join(re.escape(part) for part in words)
    pattern = re.compile(rf"(?<!\w){label_pattern}(?!\w)", re.IGNORECASE)
    return tuple((match.start(), match.end()) for match in pattern.finditer(text))


def _self_occupational_role_spans(text: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    for match in _SELF_ROLE_TITLE_AFTER_RE.finditer(text):
        candidate_start = _candidate_start(text, match)
        parsed = None if candidate_start is None else _role_title_after(text, candidate_start)
        if parsed is not None:
            spans.append((parsed.start, parsed.end))
    for match in _SELF_ROLE_TITLE_BEFORE_MARKER_RE.finditer(text):
        span = _role_title_before(text, match.start())
        if span is not None:
            spans.append(span)
    for match in _SELF_MODIFIED_ROLE_PREFIX_RE.finditer(text):
        candidate_start = _candidate_start(text, match)
        parsed = None if candidate_start is None else _role_title_after(text, candidate_start)
        if parsed is not None and _SELF_MODIFIED_ROLE_SUFFIX_RE.match(text, parsed.end):
            spans.append((parsed.start, parsed.end))
    for match in _LEADING_SELF_ROLE_RE.finditer(text):
        candidate_start = _candidate_start(text, match)
        parsed = None if candidate_start is None else _role_title_after(text, candidate_start)
        if parsed is not None and _LEADING_SELF_ROLE_SUFFIX_RE.match(text, parsed.end):
            spans.append((parsed.start, parsed.end))
    return tuple(spans)


def _role_title_after(text: str, start: int) -> _ParsedTitle | None:
    stop = min(len(text), start + _MAX_TITLE_CHARS)
    start = _skip_inline_space(text, start, stop)
    start = _skip_role_article(text, start, stop)
    if start >= stop or text[start] in "\r\n":
        return None
    tokens = _tokenize(text, start, stop)
    if not tokens:
        return None
    return _parse_title(tokens, 0, len(tokens))


def _role_title_before(text: str, end: int) -> tuple[int, int] | None:
    window_start = max(0, end - _MAX_TITLE_CHARS)
    tokens = _tokenize(text, window_start, end)
    if not tokens:
        return None
    candidate = 0
    for index, token in enumerate(tokens):
        if token.kind == "hard":
            candidate = index + 1
    while candidate < len(tokens) and tokens[candidate].kind in {"comma", "hard"}:
        candidate += 1
    parsed = _parse_title(tokens, candidate, len(tokens))
    if parsed is None or not _only_closing_tokens(tokens, parsed.next_token, len(tokens)):
        return None
    return parsed.start, parsed.end


def _parse_title(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> _ParsedTitle | None:
    if start >= stop:
        return None
    outer_close: int | None = None
    content_stop = stop
    if tokens[start].text in _OPEN_GROUPS - {"(", "[", "{"}:
        outer_close = _matching_group_end(tokens, start, stop, depth=0)
        if outer_close is None:
            return None
        content_stop = outer_close
        start += 1

    parsed = _parse_title_sequence(tokens, start, content_stop)
    if parsed is None:
        return None
    if outer_close is not None:
        next_token = parsed.next_token
        if next_token < content_stop and tokens[next_token].kind == "period":
            next_token += 1
        if not _only_closing_tokens(tokens, next_token, content_stop):
            return None
        return _ParsedTitle(
            start=parsed.start,
            end=tokens[outer_close].end,
            next_token=outer_close + 1,
            word_count=parsed.word_count,
        )
    return parsed


def _parse_title_sequence(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> _ParsedTitle | None:
    index = start
    title_start: int | None = None
    title_end: int | None = None
    word_count = 0
    accepted_words: list[_RoleToken] = []
    while index < stop and word_count < _MAX_TITLE_WORDS:
        token = tokens[index]
        if token.kind == "word":
            if not _is_title_word(token):
                break
            if title_start is None and token.is_possessive:
                break
            if token.normalized in _TITLE_CONNECTORS and not accepted_words:
                break
            title_start = token.start if title_start is None else title_start
            accepted_words.append(token)
            word_count += 1
            if token.normalized not in _TITLE_CONNECTORS:
                title_end = token.end
            index += 1
            continue
        if token.text in {"(", "[", "{"} or (
            token.text in _OPEN_GROUPS and title_start is not None
        ):
            if title_start is None:
                break
            group = _title_qualifier_group(tokens, index, stop, depth=0)
            if group is None or word_count + group[1] > _MAX_TITLE_WORDS:
                break
            close_index, group_words = group
            word_count += group_words
            title_end = tokens[close_index].end
            index = close_index + 1
            continue
        if token.kind in {"comma", "conjunction"}:
            if title_end is None or not _separator_continues_title(
                tokens,
                index,
                stop,
                accepted_words=tuple(accepted_words),
            ):
                break
            index += 1
            continue
        break

    if title_start is None or title_end is None:
        return None
    if not _has_role_title_head(_token_text(tokens, start, index)):
        return None
    return _ParsedTitle(title_start, title_end, index, word_count)


def _separator_continues_title(
    tokens: tuple[_RoleToken, ...],
    separator: int,
    stop: int,
    *,
    accepted_words: tuple[_RoleToken, ...],
) -> bool:
    following = _skip_list_separators(tokens, separator + 1, stop)
    if following >= stop or _looks_like_person_clause(tokens, following, stop):
        return False
    if tokens[following].text in _OPEN_GROUPS:
        return _title_qualifier_group(tokens, following, stop, depth=0) is not None
    if tokens[following].kind != "word" or not _is_title_word(tokens[following]):
        return False
    if _future_title_words_have_role_head(tokens, following, stop):
        return True
    if _is_acronym(tokens[following].text):
        return True
    if tokens[following].normalized in _TITLE_FUNCTION_WORDS:
        return True
    if any(word.normalized in _SUBORDINATE_TITLE_CONNECTORS for word in accepted_words):
        return True
    return _future_title_word_count(tokens, following, stop) >= 2


def _title_qualifier_group(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
    *,
    depth: int,
) -> tuple[int, int] | None:
    if depth >= _MAX_QUALIFIER_DEPTH:
        return None
    close = _matching_group_end(tokens, start, stop, depth=depth)
    if close is None or close == start + 1:
        return None
    index = start + 1
    word_count = 0
    substantive_count = 0
    last_was_separator = True
    content_words: list[_RoleToken] = []
    while index < close:
        token = tokens[index]
        if token.kind == "word":
            if not _is_title_word(token):
                return None
            word_count += 1
            content_words.append(token)
            if token.normalized not in _TITLE_CONNECTORS:
                substantive_count += 1
                last_was_separator = False
            index += 1
            continue
        if token.kind in {"comma", "conjunction"}:
            if last_was_separator:
                return None
            last_was_separator = True
            index += 1
            continue
        if token.text in _OPEN_GROUPS:
            nested = _title_qualifier_group(tokens, index, close, depth=depth + 1)
            if nested is None:
                return None
            nested_close, nested_words = nested
            word_count += nested_words
            substantive_count += 1
            last_was_separator = False
            index = nested_close + 1
            continue
        if token.kind == "period" and index == close - 1:
            index += 1
            continue
        return None
    if not substantive_count or last_was_separator or word_count > _MAX_TITLE_WORDS:
        return None
    if _looks_like_person_clause(tokens, start + 1, close):
        return None
    if _is_honorific_person_phrase(tuple(content_words)):
        return None
    if _is_bare_person_like_qualifier(tuple(content_words)):
        return None
    return close, word_count


def _looks_like_person_clause(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> bool:
    index = _skip_list_separators(tokens, start, stop)
    subjects = 0
    while index < stop:
        phrase_end = _person_phrase_end(tokens, index, stop)
        if phrase_end is None:
            return False
        subjects += 1
        index = phrase_end
        if index < stop and _is_predicate_word(tokens[index]):
            return subjects > 0
        appositive_end = _person_appositive_end(tokens, index, stop)
        if appositive_end is not None:
            index = appositive_end
            if index >= stop or _is_predicate_word(tokens[index]):
                return True
            if tokens[index].kind in {"hard", "period"}:
                return True
            if _person_phrase_end(tokens, index, stop) is not None:
                continue
        if _is_unclosed_person_credential_appositive(tokens, index, stop):
            return True
        next_subject = _skip_list_separators(tokens, index, stop)
        if next_subject == index or next_subject >= stop:
            return False
        index = next_subject
    return False


def _person_phrase_end(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> int | None:
    words: list[_RoleToken] = []
    index = start
    while index < stop and len(words) < 5:
        token = tokens[index]
        if token.kind != "word" or not _is_person_phrase_word(token):
            break
        words.append(token)
        index += 1
    if not words:
        return None
    role_head_positions = [
        position for position, word in enumerate(words) if _has_role_title_head(word.text)
    ]
    if role_head_positions:
        last_head = role_head_positions[-1]
        if last_head == len(words) - 1:
            return None
        if not all(_is_person_candidate_word(word) for word in words[last_head + 1 :]):
            return None
        return index
    if words[0].normalized in _PERSON_TITLE_PREFIXES:
        return index if len(words) >= 2 else None
    return index if all(_is_person_candidate_word(word) for word in words) else None


def _person_appositive_end(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> int | None:
    if start >= stop:
        return None
    if tokens[start].text in _CREDENTIAL_OPEN_GROUPS:
        close = _credential_group_end(tokens, start, stop, depth=0)
        return None if close is None else close + 1
    if tokens[start].kind != "comma":
        return None
    credential_end = _comma_credential_appositive_end(tokens, start, stop)
    if credential_end is not None:
        return credential_end
    index = start + 1
    words: list[_RoleToken] = []
    while index < stop and tokens[index].kind != "comma":
        token = tokens[index]
        if token.kind == "word" and _is_title_word(token):
            words.append(token)
            index += 1
            continue
        if token.kind == "conjunction":
            index += 1
            continue
        return None
    if index >= stop or not words:
        return None
    if not (
        any(_has_role_title_head(word.text) for word in words)
        or all(_is_person_credential(word) for word in words)
    ):
        return None
    return index + 1


def _is_person_credential_appositive(text: str, start: int, end: int) -> bool:
    window_start = max(0, start - 96)
    window_stop = min(len(text), end + 96)
    tokens = _tokenize(text, window_start, window_stop)
    label_indexes = tuple(
        index for index, token in enumerate(tokens) if start <= token.start and token.end <= end
    )
    if not label_indexes or label_indexes != tuple(range(label_indexes[0], label_indexes[-1] + 1)):
        return False
    first = label_indexes[0]
    last = label_indexes[-1]
    if not _is_person_credential_phrase(tokens, first, last + 1):
        return False

    for opener in range(first - 1, -1, -1):
        if tokens[opener].text not in _CREDENTIAL_OPEN_GROUPS:
            continue
        close = _credential_group_end(tokens, opener, len(tokens), depth=0)
        if (
            close is not None
            and opener < first <= last < close
            and _has_person_phrase_before(tokens, opener)
        ):
            return True
        if (
            _matching_group_end(tokens, opener, len(tokens), depth=0) is None
            and _unclosed_credential_prefix_end(tokens, opener, len(tokens)) > last
            and _has_person_phrase_before(tokens, opener)
        ):
            return True
    for comma in range(first - 1, -1, -1):
        if tokens[comma].kind != "comma":
            continue
        appositive_end = _comma_credential_appositive_end(tokens, comma, len(tokens))
        if (
            appositive_end is not None
            and comma < first <= last < appositive_end
            and _has_person_phrase_before(tokens, comma)
        ):
            return True
    return False


def _has_person_phrase_before(tokens: tuple[_RoleToken, ...], stop: int) -> bool:
    start = stop - 1
    words_seen = 0
    while start >= 0 and words_seen < 5:
        token = tokens[start]
        if token.kind != "word":
            break
        words_seen += 1
        if _person_phrase_end(tokens, start, stop) == stop:
            return True
        start -= 1
    return False


def _is_unclosed_person_credential_appositive(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> bool:
    if start >= stop or tokens[start].text not in _CREDENTIAL_OPEN_GROUPS:
        return False
    if _matching_group_end(tokens, start, stop, depth=0) is not None:
        return False
    return _unclosed_credential_prefix_end(tokens, start, stop) > start


def _comma_credential_appositive_end(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> int | None:
    """Parse ``, Credential[.],`` without treating its punctuation as prose."""

    index = start + 1
    credential_seen = False
    separator_seen = False
    while index < stop:
        token = tokens[index]
        if _is_person_credential(token):
            credential_seen = True
            separator_seen = False
            index += 1
            if index < stop and tokens[index].kind == "period":
                index += 1
            if index >= stop:
                return index
            continue
        if token.kind == "conjunction" and credential_seen and not separator_seen:
            separator_seen = True
            index += 1
            continue
        if token.kind == "comma" and credential_seen and not separator_seen:
            return index + 1
        return None
    return None


def _credential_group_end(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
    *,
    depth: int,
) -> int | None:
    """Parse a bounded, balanced credential-only group, including nested groups."""

    if depth >= _MAX_QUALIFIER_DEPTH or start >= stop:
        return None
    expected = _OPEN_TO_CLOSE.get(tokens[start].text)
    if tokens[start].text not in _CREDENTIAL_OPEN_GROUPS or expected is None:
        return None
    index = start + 1
    credential_seen = False
    separator_seen = False
    while index < stop:
        token = tokens[index]
        if token.text == expected:
            return index if credential_seen and not separator_seen else None
        if token.text in _CREDENTIAL_OPEN_GROUPS:
            nested = _credential_group_end(tokens, index, stop, depth=depth + 1)
            if nested is None:
                return None
            credential_seen = True
            separator_seen = False
            index = nested + 1
            continue
        if _is_person_credential(token):
            credential_seen = True
            separator_seen = False
            index += 1
            if index < stop and tokens[index].kind == "period":
                index += 1
            continue
        if token.kind in {"comma", "conjunction"} and credential_seen and not separator_seen:
            separator_seen = True
            index += 1
            continue
        return None
    return None


def _unclosed_credential_prefix_end(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> int:
    """Return the end of nested openers plus their first credential, or ``start``."""

    index = start
    depth = 0
    while (
        index < stop
        and depth < _MAX_QUALIFIER_DEPTH
        and tokens[index].text in _CREDENTIAL_OPEN_GROUPS
    ):
        index += 1
        depth += 1
    if not depth or index >= stop or not _is_person_credential(tokens[index]):
        return start
    index += 1
    if index < stop and tokens[index].kind == "period":
        index += 1
    return index


def _is_person_credential_phrase(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> bool:
    words = tuple(token for token in tokens[start:stop] if token.kind == "word")
    return bool(
        words and len(words) == stop - start and all(_is_person_credential(word) for word in words)
    )


def _is_person_credential(token: _RoleToken) -> bool:
    return token.kind == "word" and token.normalized in _PERSON_CREDENTIALS


def _future_title_words_have_role_head(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> bool:
    for token in tokens[start:stop]:
        if token.kind == "hard" or token.kind == "period" or token.text in _CLOSE_GROUPS:
            break
        if token.kind == "word" and not _is_title_word(token):
            break
        if token.kind == "word" and _has_role_title_head(token.text):
            return True
    return False


def _future_title_word_count(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> int:
    count = 0
    for token in tokens[start:stop]:
        if token.kind in {"hard", "period"} or token.text in _CLOSE_GROUPS:
            break
        if token.kind == "word":
            if not _is_title_word(token):
                break
            if token.normalized not in _TITLE_CONNECTORS:
                count += 1
    return count


def _matching_group_end(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
    *,
    depth: int,
) -> int | None:
    if depth >= _MAX_QUALIFIER_DEPTH or start >= stop:
        return None
    expected = _OPEN_TO_CLOSE.get(tokens[start].text)
    if expected is None:
        return None
    index = start + 1
    while index < stop:
        token = tokens[index]
        if token.text == expected:
            return index
        if token.text in _OPEN_GROUPS:
            nested = _matching_group_end(tokens, index, stop, depth=depth + 1)
            if nested is None:
                return None
            index = nested + 1
            continue
        if token.kind == "hard" or token.text in _CLOSE_GROUPS:
            return None
        index += 1
    return None


def _tokenize(text: str, start: int, stop: int) -> tuple[_RoleToken, ...]:
    tokens: list[_RoleToken] = []
    cursor = start
    while cursor < stop and len(tokens) < _MAX_TITLE_TOKENS:
        character = text[cursor]
        if character in " \t\f\v":
            cursor += 1
            continue
        if character in "\r\n":
            tokens.append(_RoleToken("hard", character, cursor, cursor + 1))
            cursor += 1
            continue
        word = _ROLE_WORD_RE.match(text, cursor)
        if word is not None:
            raw = word.group(0)
            kind = "conjunction" if raw.casefold() == "and" else "word"
            tokens.append(_RoleToken(kind, raw, word.start(), word.end()))
            cursor = word.end()
            continue
        if character == ",":
            kind = "comma"
        elif character in {"&", "/"}:
            kind = "conjunction"
        elif character == ".":
            kind = "period"
        elif character in _OPEN_GROUPS or character in _CLOSE_GROUPS:
            kind = "group"
        else:
            kind = "hard"
        tokens.append(_RoleToken(kind, character, cursor, cursor + 1))
        cursor += 1
    return tuple(tokens)


def _is_title_word(token: _RoleToken) -> bool:
    if token.kind != "word":
        return False
    if token.normalized in _TITLE_CONNECTORS:
        return True
    return token.text[0].isupper()


def _is_person_phrase_word(token: _RoleToken) -> bool:
    return (
        token.kind == "word"
        and token.normalized not in _TITLE_CONNECTORS
        and (token.text[0].isupper() or _is_initial(token.text))
    )


def _is_person_name_word(token: _RoleToken) -> bool:
    if _is_initial(token.text):
        return True
    if token.is_possessive:
        return False
    letters = "".join(character for character in token.text if character.isalpha())
    return bool(letters and letters[0].isupper() and not letters.isupper())


def _is_person_candidate_word(token: _RoleToken) -> bool:
    return _is_person_name_word(token) or _is_acronym(token.text)


def _is_honorific_person_phrase(words: tuple[_RoleToken, ...]) -> bool:
    return bool(
        len(words) >= 2
        and words[0].normalized in _PERSON_TITLE_PREFIXES
        and all(_is_person_name_word(word) for word in words[1:])
    )


def _is_bare_person_like_qualifier(words: tuple[_RoleToken, ...]) -> bool:
    substantive_words = tuple(word for word in words if word.normalized not in _TITLE_CONNECTORS)
    return bool(
        substantive_words
        and all(_is_person_name_word(word) for word in substantive_words)
        and not any(_has_role_title_head(word.text) for word in substantive_words)
        and not any(_is_acronym(word.text) for word in substantive_words)
        and not any(word.normalized in _TITLE_FUNCTION_WORDS for word in substantive_words)
    )


def _is_predicate_word(token: _RoleToken) -> bool:
    return bool(
        token.kind == "word"
        and token.text[0].islower()
        and token.normalized not in _TITLE_CONNECTORS
    )


def _is_initial(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]\.", text))


def _is_acronym(text: str) -> bool:
    letters = "".join(character for character in text if character.isalpha())
    return len(letters) >= 2 and letters.isupper()


def _has_role_title_head(text: str) -> bool:
    return bool(
        _ROLE_TITLE_HEAD_RE.search(text) or _ROLE_TITLE_HEAD_RE.search(text.replace(".", ""))
    )


def _skip_list_separators(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> int:
    while start < stop and tokens[start].kind in {"comma", "conjunction"}:
        start += 1
    return start


def _only_closing_tokens(
    tokens: tuple[_RoleToken, ...],
    start: int,
    stop: int,
) -> bool:
    return all(token.text in _CLOSE_GROUPS for token in tokens[start:stop])


def _token_text(tokens: tuple[_RoleToken, ...], start: int, stop: int) -> str:
    if start >= stop:
        return ""
    return " ".join(token.text for token in tokens[start:stop])


def _span_is_within(
    start: int,
    end: int,
    spans: tuple[tuple[int, int], ...],
) -> bool:
    return any(span_start <= start and end <= span_end for span_start, span_end in spans)


def _candidate_start(text: str, match: re.Match[str]) -> int | None:
    start = match.end()
    scanned = 0
    while start > match.start() and text[start - 1] in " \t\f\v":
        if scanned >= _MAX_TITLE_CHARS:
            return None
        start -= 1
        scanned += 1
    for article in ("the", "an", "a"):
        article_start = start - len(article)
        if article_start < match.start():
            continue
        if text[article_start:start].casefold() != article:
            continue
        if article_start > match.start() and text[article_start - 1].isalpha():
            continue
        start = article_start
        while start > match.start() and text[start - 1] in " \t\f\v":
            if scanned >= _MAX_TITLE_CHARS:
                return None
            start -= 1
            scanned += 1
        break
    return start


def _skip_role_article(text: str, start: int, stop: int) -> int:
    for article in ("the", "an", "a"):
        end = start + len(article)
        if end >= stop or text[start:end].casefold() != article:
            continue
        if text[end] not in " \t\f\v":
            continue
        return _skip_inline_space(text, end, stop)
    return start


def _skip_inline_space(text: str, start: int, stop: int) -> int:
    while start < stop and text[start].isspace() and text[start] not in {"\r", "\n"}:
        start += 1
    return start

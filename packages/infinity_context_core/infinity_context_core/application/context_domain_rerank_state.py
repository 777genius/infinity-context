"""Identity, relationship and current-state rerank policies."""

from __future__ import annotations

import re

from infinity_context_core.application.context_domain_rerank_legacy_contract import (
    DomainRerankSignal,
)
from infinity_context_core.application.context_relative_duration_evidence import (
    has_relative_duration_event_evidence,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_score_signal_rerank import (
    score_signal_reason as _score_signal_reason,
)
from infinity_context_core.application.dto import ContextItem

_IDENTITY_RERANK_REASONS = frozenset(
    (
        "decomposition_identity_attribute",
        "identity_bridge",
    )
)

_IDENTITY_QUERY_RE = re.compile(
    r"\b(?:identity|gender\s+identity|identify|identifies|true\s+self)\b|"
    r"\b(?:transgender|trans|queer|nonbinary)\b(?=.{0,80}\b(?:identity|person|"
    r"woman|man|self)\b)",
    re.IGNORECASE | re.DOTALL,
)

_IDENTITY_EXACT_RE = re.compile(
    r"\b(?:identif(?:y|ies|ied)\s+as|"
    r"(?:is|am|are|was|were)\s+(?:a\s+)?(?:transgender|trans|queer|nonbinary|"
    r"gay|lesbian|bisexual)\b|"
    r"transgender\s+woman|trans\s+woman|transgender\s+man|trans\s+man|"
    r"gender\s+identity|true\s+self|my\s+identity|her\s+identity|"
    r"his\s+identity|their\s+identity)\b",
    re.IGNORECASE,
)

_IDENTITY_TOPIC_WEAK_RE = re.compile(
    r"\b(?:support\s+group|pride\s+(?:flag|mural|event|parade)|"
    r"transgender\s+stories|lgbtq?\s+(?:event|community|group)|"
    r"support(?:s|ed|ive|ing)?\s+(?:the\s+)?(?:transgender|lgbtq?|queer)\s+"
    r"(?:community|events?|rights?))\b",
    re.IGNORECASE,
)

_RELATIONSHIP_STATUS_RERANK_REASONS = frozenset(
    (
        "relationship_status_bridge",
        "decomposition_relationship_status",
    )
)

_RELATIONSHIP_STATUS_QUERY_RE = re.compile(
    r"\brelationship\s+status\b|"
    r"\b(?:single|dating|married|partner|spouse|husband|wife)\b"
    r"(?=.{0,80}\b(?:status|relationship)\b)|"
    r"\b(?:отношения|статус|пара|партн[её]р|супруг|супруга)\b",
    re.IGNORECASE | re.DOTALL,
)

_RELATIONSHIP_DURATION_RERANK_REASONS = frozenset(
    (
        "relationship_duration_bridge",
        "decomposition_relationship_duration",
    )
)

_RELATIONSHIP_ORIGIN_RERANK_REASONS = frozenset(("relationship_origin_bridge",))

_STATE_TRANSITION_RERANK_REASONS = frozenset(
    (
        "change_over_time_bridge",
        "decomposition_state_transition",
        "decomposition_temporal_change",
        "state_transition_bridge",
    )
)

_CURRENT_STATE_RERANK_REASONS = frozenset(
    (
        "current_recommendation_bridge",
        "current_state_temporal_bridge",
        "decomposition_knowledge_update_current",
    )
)

_STALE_STATE_RERANK_REASONS = frozenset(("stale_state_temporal_bridge",))

_AGE_BIRTHDAY_RERANK_REASONS = frozenset(("age_birthday_bridge",))

_BIRTHPLACE_RERANK_REASONS = frozenset(("birthplace_origin_bridge",))

_RELATIONSHIP_STATUS_EXACT_RE = re.compile(
    r"\b(?:relationship\s+status|single\s+parent|single\b|not\s+dating|"
    r"dating|boyfriend|girlfriend|fianc[eé]e?|romantic\s+partner|"
    r"life\s+partner|spouse|husband|wife|married|divorced|separated|"
    r"widow(?:ed|er)?|breakup|broke\s+up|split\s+up|"
    r"in\s+a\s+relationship)\b|"
    r"\b(?:статус\s+отношений|одинок\w*|холост\w*|не\s+замужем|"
    r"не\s+женат|в\s+отношениях|парень|девушка|партн[её]р|муж|жена|"
    r"супруг|супруга|развод\w*|расстал\w*)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_STATUS_WORK_PARTNER_RE = re.compile(
    r"\b(?:accountability|business|class|cofounder|co-founder|conversation|"
    r"dance|founder|gym|lab|project|research|running|school|sparring|startup|"
    r"study|team|training|volunteer|work)\s+"
    r"partners?\b|\bpartners?\s+(?:on|for|in)\s+"
    r"(?:atlas|business|class|gym|lab|project|research|running|school|startup|"
    r"study|team|training|volunteer|work)\b|"
    r"\b(?:рабоч\w*|бизнес|проектн\w*|учебн\w*|тренировочн\w*)\s+"
    r"партн[её]р\w*\b",
    re.IGNORECASE,
)

_RELATIONSHIP_STATUS_SOCIAL_WEAK_RE = re.compile(
    r"\b(?:friend|friends|old\s+friend|classmate|school|colleague|coworker|"
    r"mentor|coach|teacher|family|support\s+system|met\s+at|went\s+to\s+"
    r"school\s+with|knows?\s+from)\b|"
    r"\b(?:друг|друзья|подруга|одноклассник|школ\w*|коллег\w*|"
    r"наставник|учитель|семь[яи]|знаком\w*)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_DURATION_EXACT_RE = re.compile(
    r"\b(?:for\s+(?:about\s+|roughly\s+|nearly\s+|almost\s+)?"
    r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|several|many|a\s+couple\s+of)\s+"
    r"(?:years?|months?|weeks?|days?)|since\s+(?:\d{4}|"
    r"[A-Z][a-z]+\s+\d{4}|childhood|college|school)|anniversary|"
    r"known\s+each\s+other\s+for|have\s+been\s+(?:married|together)|"
    r"been\s+friends\s+for)\b|"
    r"\b(?:уже\s+)?(?:\d+|один|одна|два|две|три|четыре|пять|шесть|"
    r"семь|восемь|девять|десять|несколько)\s+"
    r"(?:лет|года|год|месяц(?:ев|а)?|недель|недели|дней)|"
    r"\bс\s+\d{4}\b|годовщин\w*|знаком\w+\s+.*\b(?:лет|года|год)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_DURATION_WEAK_RE = re.compile(
    r"\b(?:married|husband|wife|spouse|partner|friend|friends|old\s+friend|"
    r"relationship|wedding|met|known|school|college)\b|"
    r"\b(?:женат|замужем|муж|жена|супруг|супруга|партн[её]р|друг|"
    r"друзья|отношен\w*|свадьб\w*|знаком\w*)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_ORIGIN_EXACT_RE = re.compile(
    r"\b(?:first\s+met|met\s+(?:at|in|on|during|through|via)|"
    r"met\s+(?!(?:the\s+)?(?:deadline|deadlines|goal|goals|requirement|"
    r"requirements|target|targets)\b).{1,80}\s+"
    r"(?:at|in|on|during|through|via|while|when|after|before)\b|"
    r"met\s+(?:while|when|after|before)\b|"
    r"introduced\s+(?:at|in|during|through|via|by)|"
    r"introduced\s+.{1,80}\s+(?:at|in|during|through|via|by)\b|"
    r"became\s+friends\s+(?:at|in|during|through|via|while|when|after)|"
    r"got\s+to\s+know\s+.{1,80}\s+"
    r"(?:at|in|on|during|through|via|while|when|after|before)|"
    r"got\s+to\s+know\s+(?:each\s+other\s+)?(?:at|in|on|during|through|via|while|when)|"
    r"know(?:n)?\s+each\s+other\s+(?:from|through|via|since)|"
    r"first\s+encounter\s+(?:was\s+)?(?:at|in|on|during|through|via|while|when)|"
    r"known\s+(?:each\s+other\s+)?since|go\s+back\s+to|"
    r"have\s+known\s+each\s+other\s+since)\b|"
    r"\b(?:впервые\s+)?(?:познакомил(?:ись|ся|ась)|встретил(?:ись|ся|ась))\s+"
    r"(?:в|на|через|во\s+время|благодаря)\b|"
    r"\bзнаком\w+\s+с\s+(?:\d{4}|детства|школ\w*|университет\w*|колледж\w*)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_ORIGIN_WEAK_RE = re.compile(
    r"\b(?:friend|friends|old\s+friend|classmate|colleague|coworker|school|"
    r"college|university|work|event|party|conference|knows?|met)\b|"
    r"\b(?:друг|друзья|подруга|одноклассник|коллег\w*|школ\w*|"
    r"университет\w*|колледж\w*|работ\w*|событи\w*|знаком\w*)\b",
    re.IGNORECASE,
)

_STATE_TRANSITION_PAIR_RE = re.compile(
    r"\b(?:changed|updated|switched|migrated|transitioned|replaced)\b"
    r"(?=.{0,120}\bfrom\b)(?=.{0,160}\bto\b)|"
    r"\b(?:current|active|latest|selected|chosen|provider|tool|model|plan|"
    r"policy|source|decision)\b(?=.{0,160}\bnot\b.{0,80}\bbut\b)|"
    r"\bnot\b(?=.{0,80}\bbut\b)(?=.{0,160}\b(?:current|active|latest|"
    r"selected|chosen|provider|tool|model|plan|policy|source|decision)\b)|"
    r"\b(?:cancell?ed|rescheduled|postponed|moved|delayed)\b"
    r"(?=.{0,140}\b(?:to|for|until|from|after|instead|new|now|current|"
    r"latest|date|time|day|week|month|meeting|call|demo|event|plan)\b)|"
    r"\bfrom\b(?=.{0,120}\bto\b)(?=.{0,180}\b(?:current|new|active|final|"
    r"replacement|provider|tool|model|plan|policy|source)\b)|"
    r"\b(?:replaced|superseded|took\s+over)\b(?=.{0,120}\b(?:by|with|current|"
    r"new|active|final)\b)|"
    r"\b(?:old|previous|stale|superseded|deprecated|no\s+longer\s+valid|"
    r"no\s+longer\s+current)\b"
    r"(?=.{0,180}\b(?:current|new|active|final|replacement|replaced\s+by|"
    r"switched\s+to|migrated\s+to|now)\b)|"
    r"\b(?:изменил\w*|обновил\w*|смени\w*|переш[её]л\w*|мигрировал\w*)\b"
    r"(?=.{0,120}\b(?:с|со)\b)(?=.{0,160}\b(?:на|в)\b)|"
    r"\b(?:заменил\w*|заменен\w*|заменён\w*)\b(?=.{0,120}\b(?:на|нов\w*|"
    r"текущ\w*|актуальн\w*)\b)|"
    r"\b(?:стар\w*|предыдущ\w*|устаревш\w*|больше\s+не\s+актуальн\w*)\b"
    r"(?=.{0,180}\b(?:нов\w*|текущ\w*|актуальн\w*|сейчас|теперь|замен\w*)\b)",
    re.IGNORECASE | re.DOTALL,
)

_STATE_TRANSITION_MARKER_RE = re.compile(
    r"\b(?:changed|updated|switched|migrated|transitioned|replaced|superseded|"
    r"current|active|new|old|previous|stale|deprecated|no\s+longer|now|"
    r"cancell?ed|rescheduled|postponed|moved|delayed)\b|"
    r"\b(?:изменил\w*|изменилось|обновил\w*|смени\w*|переш[её]л\w*|"
    r"мигрировал\w*|заменил\w*|заменен\w*|заменён\w*|текущ\w*|"
    r"актуальн\w*|нов\w*|стар\w*|предыдущ\w*|устаревш\w*|теперь|сейчас)\b",
    re.IGNORECASE,
)

_CURRENT_STATE_EXACT_RE = re.compile(
    r"\b(?:current|active|latest|final|selected|chosen|recommended|"
    r"canonical|source\s+of\s+truth|decided\s+to\s+use|should\s+use|"
    r"using\s+now|right\s+now|remains?\s+valid|still\s+valid|"
    r"valid\s+and\s+active)\b|"
    r"\b(?:актуальн\w*|текущ\w*|финальн\w*|окончательн\w*|"
    r"выбранн\w*|рекомендованн\w*|сейчас|действу\w*)\b",
    re.IGNORECASE,
)

_STALE_STATE_EXACT_RE = re.compile(
    r"\b(?:no\s+longer\s+(?:valid|current|active|used?|using)|"
    r"not\s+current|not\s+valid|stale|outdated|deprecated|superseded|"
    r"replaced\s+by|switched\s+away|previous(?:ly)?\s+valid|former|"
    r"old\s+(?:provider|tool|model|plan|policy|decision|source))\b|"
    r"\b(?:устаревш\w*|больше\s+не\s+(?:актуальн\w*|использ\w*)|"
    r"не\s+актуальн\w*|предыдущ\w*|замен[её]н\w*)\b",
    re.IGNORECASE,
)

_CURRENT_STATE_QUERY_RE = re.compile(
    r"\b(?:current|currently|latest|active|final|selected|chosen|recommended|"
    r"canonical|source\s+of\s+truth|still\s+valid|should\s+(?:i\s+)?use|"
    r"what\s+did\s+i\s+decide\s+to\s+use)\b|"
    r"\b(?:актуальн\w*|текущ\w*|финальн\w*|окончательн\w*|"
    r"выбранн\w*|рекомендованн\w*)\b",
    re.IGNORECASE,
)

_CONTRASTIVE_CORRECTION_RE = re.compile(
    r"\b(?:provider|tool|model|plan|policy|decision|source|option|choice|"
    r"date|time|meeting|call|demo|event)\b(?=.{0,160}\bnot\b.{0,80}\bbut\b)|"
    r"\bnot\b(?=.{0,80}\bbut\b)(?=.{0,160}\b(?:provider|tool|model|plan|"
    r"policy|decision|source|option|choice|date|time|meeting|call|demo|event)\b)|"
    r"\b(?:provider|tool|model|plan|policy|decision|source|option|choice|"
    r"date|time|meeting|call|demo|event)\b(?=.{0,160}\b(?:instead\s+of|"
    r"rather\s+than)\b)|"
    r"\b(?:instead\s+of|rather\s+than)\b(?=.{0,160}\b(?:provider|tool|model|"
    r"plan|policy|decision|source|option|choice|date|time|meeting|call|demo|"
    r"event)\b)",
    re.IGNORECASE | re.DOTALL,
)

_STALE_STATE_QUERY_RE = re.compile(
    r"\b(?:no\s+longer\s+(?:valid|current|active|used?|using)|not\s+current|"
    r"not\s+valid|stale|outdated|deprecated|"
    r"(?:previous|former|old)\s+"
    r"(?:provider|tool|model|plan|policy|decision|source|state|option)|"
    r"should\s+(?:i\s+)?no\s+longer\s+use)\b|"
    r"\b(?:устаревш\w*|больше\s+не\s+(?:актуальн\w*|использ\w*)|"
    r"не\s+актуальн\w*|предыдущ\w*)\b",
    re.IGNORECASE,
)

_AGE_BIRTHDAY_EXACT_RE = re.compile(
    r"\b(?:born\s+in\s+\d{4}|born\s+on\b|date\s+of\s+birth|birthdate|"
    r"birthday|age\s+(?:is\s+)?\d{1,3}|\d{1,3}\s+years?\s+old)\b|"
    r"\b(?:родил(?:ся|ась|ись)\s+в\s+\d{4}|дата\s+рождения|"
    r"день\s+рождения|возраст\s+\d{1,3}|\d{1,3}\s+лет)\b",
    re.IGNORECASE,
)

_AGE_BIRTHDAY_WEAK_OLD_RE = re.compile(
    r"\bold\s+(?:friend|plan|state|policy|note|home|school|job)\b|"
    r"\b(?:стар(?:ый|ая|ое|ые)\s+(?:друг|план|политик\w*|заметк\w*))\b",
    re.IGNORECASE,
)

_BIRTHPLACE_QUERY_RE = re.compile(
    r"\bwhere\b(?=.{0,80}\bborn\b)|\bborn\b(?=.{0,80}\bwhere\b)|"
    r"\b(?:где|откуда)\b(?=.{0,80}\bродил)",
    re.IGNORECASE | re.DOTALL,
)

_BIRTHPLACE_EXACT_RE = re.compile(
    r"\b(?:birthplace|born\s+in\s+(?!\d{4}\b)[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?|"
    r"born\s+near\s+[A-Z][A-Za-z]+|home\s+country\s+is\s+[A-Z][A-Za-z]+)\b|"
    r"\b(?:место\s+рождения|родил(?:ся|ась|ись)\s+в\s+(?!\d{4}\b)[А-ЯЁA-Z]"
    r"[\wА-Яа-яЁё-]+)\b",
    re.IGNORECASE,
)

_BIRTHPLACE_BIRTHDATE_NOISE_RE = re.compile(
    r"\bborn\s+in\s+\d{4}\b|\b(?:birthday|date\s+of\s+birth|birthdate)\b|"
    r"\bродил(?:ся|ась|ись)\s+в\s+\d{4}\b|\b(?:дата\s+рождения|день\s+рождения)\b",
    re.IGNORECASE,
)

def identity_rerank_signal(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_identity_candidate(query=query, query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _IDENTITY_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.042,
            reason="identity_exact_evidence",
        )
    if _IDENTITY_TOPIC_WEAK_RE.search(item.text) is not None or (
        relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(
            penalty=0.04,
            reason="identity_topic_only_evidence",
        )
    return DomainRerankSignal()

def relationship_status_rerank_signal(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_relationship_status_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    if _RELATIONSHIP_STATUS_WORK_PARTNER_RE.search(item.text) is not None:
        return DomainRerankSignal(
            penalty=0.055,
            reason="relationship_status_weak_evidence",
        )
    if _RELATIONSHIP_STATUS_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.028,
            reason="relationship_status_exact_evidence",
        )
    if (
        _RELATIONSHIP_STATUS_SOCIAL_WEAK_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(
            penalty=0.052,
            reason="relationship_status_weak_evidence",
        )
    return DomainRerankSignal()

def relationship_duration_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_relationship_duration_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _RELATIONSHIP_DURATION_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.028,
            reason="relationship_duration_exact_evidence",
        )
    if (
        _RELATIONSHIP_DURATION_WEAK_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(
            penalty=0.05,
            reason="relationship_duration_weak_evidence",
        )
    return DomainRerankSignal()

def relationship_origin_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_relationship_origin_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _RELATIONSHIP_ORIGIN_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.028,
            reason="relationship_origin_exact_evidence",
        )
    if (
        _RELATIONSHIP_ORIGIN_WEAK_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(
            penalty=0.05,
            reason="relationship_origin_weak_evidence",
        )
    return DomainRerankSignal()

def state_transition_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_state_transition_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _STATE_TRANSITION_PAIR_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.03,
            reason="state_transition_exact_evidence",
        )
    if _STATE_TRANSITION_MARKER_RE.search(item.text) is not None:
        return DomainRerankSignal()
    if relevance.distinctive_term_hits < 4:
        return DomainRerankSignal(
            penalty=0.055,
            reason="state_transition_weak_evidence",
        )
    return DomainRerankSignal(
        penalty=0.035,
        reason="state_transition_weak_evidence",
    )

def current_state_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if _is_stale_state_candidate(query=query, query_reason=query_reason, item=item):
        if _STALE_STATE_EXACT_RE.search(item.text) is not None:
            return DomainRerankSignal(boost=0.032, reason="stale_state_exact_evidence")
        if _CURRENT_STATE_EXACT_RE.search(item.text) is not None:
            return DomainRerankSignal(
                penalty=0.045,
                reason="stale_state_current_conflict",
            )
        if relevance.distinctive_term_hits < 4:
            return DomainRerankSignal(penalty=0.035, reason="stale_state_weak_evidence")
        return DomainRerankSignal()
    if not _is_current_state_candidate(query=query, query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if has_current_state_correction_evidence(item.text):
        return DomainRerankSignal(
            boost=0.045,
            reason="current_state_correction_evidence",
        )
    if _STATE_TRANSITION_PAIR_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.038,
            reason="current_state_transition_evidence",
        )
    if _STALE_STATE_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            penalty=0.055,
            reason="current_state_stale_conflict",
        )
    if _CURRENT_STATE_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(boost=0.028, reason="current_state_exact_evidence")
    if relevance.distinctive_term_hits < 3:
        return DomainRerankSignal(penalty=0.026, reason="current_state_weak_evidence")
    return DomainRerankSignal()

def age_birthday_rerank_signal(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_age_birthday_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if (
        _BIRTHPLACE_QUERY_RE.search(query) is not None
        and _AGE_BIRTHDAY_EXACT_RE.search(item.text) is not None
    ):
        return DomainRerankSignal(
            penalty=0.052,
            reason="age_birthday_birthplace_query_noise",
        )
    if has_relative_duration_event_evidence(
        query=query,
        query_reason=query_reason,
        text=item.text,
    ):
        return DomainRerankSignal(
            boost=0.034,
            reason="age_birthday_relative_duration_evidence",
        )
    if _AGE_BIRTHDAY_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(boost=0.026, reason="age_birthday_exact_evidence")
    if (
        _AGE_BIRTHDAY_WEAK_OLD_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(penalty=0.05, reason="age_birthday_weak_evidence")
    return DomainRerankSignal()

def birthplace_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_birthplace_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _BIRTHPLACE_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(boost=0.026, reason="birthplace_exact_evidence")
    if (
        _BIRTHPLACE_BIRTHDATE_NOISE_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(penalty=0.052, reason="birthplace_birthdate_noise")
    return DomainRerankSignal()

def _is_relationship_status_candidate(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason in _RELATIONSHIP_STATUS_RERANK_REASONS:
        return True
    if query and _RELATIONSHIP_STATUS_QUERY_RE.search(query) is not None:
        return True
    return _score_signal_reason(item) in _RELATIONSHIP_STATUS_RERANK_REASONS

def _is_identity_candidate(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason in _IDENTITY_RERANK_REASONS:
        return True
    if query and _IDENTITY_QUERY_RE.search(query) is not None:
        return True
    return _score_signal_reason(item) in _IDENTITY_RERANK_REASONS

def _is_relationship_duration_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _RELATIONSHIP_DURATION_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _RELATIONSHIP_DURATION_RERANK_REASONS

def _is_relationship_origin_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _RELATIONSHIP_ORIGIN_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _RELATIONSHIP_ORIGIN_RERANK_REASONS

def _is_state_transition_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _STATE_TRANSITION_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _STATE_TRANSITION_RERANK_REASONS

def _is_current_state_candidate(*, query: str, query_reason: str, item: ContextItem) -> bool:
    if _CURRENT_STATE_QUERY_RE.search(query) is not None:
        return True
    if query_reason in _CURRENT_STATE_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _CURRENT_STATE_RERANK_REASONS

def _is_stale_state_candidate(*, query: str, query_reason: str, item: ContextItem) -> bool:
    if _STALE_STATE_QUERY_RE.search(query) is not None:
        return True
    if query_reason in _STALE_STATE_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _STALE_STATE_RERANK_REASONS

def has_current_state_correction_evidence(text: str) -> bool:
    has_current_state = _CURRENT_STATE_EXACT_RE.search(text) is not None
    has_stale_context = _STALE_STATE_EXACT_RE.search(text) is not None
    has_transition = _STATE_TRANSITION_PAIR_RE.search(text) is not None
    has_contrastive_correction = _CONTRASTIVE_CORRECTION_RE.search(text) is not None
    return (has_current_state and (has_stale_context or has_transition)) or (
        has_contrastive_correction and (has_stale_context or has_transition)
    )

def _is_age_birthday_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _AGE_BIRTHDAY_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _AGE_BIRTHDAY_RERANK_REASONS

def _is_birthplace_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _BIRTHPLACE_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _BIRTHPLACE_RERANK_REASONS

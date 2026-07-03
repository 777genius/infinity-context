"""Role-sensitive action matching for deterministic memory reranking."""

from __future__ import annotations

import re
from dataclasses import dataclass

_LABEL_RE = r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
_QUERY_LABEL_RE = r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё._-]{1,39}"
_ACTION_VERB_RE = (
    r"recommend(?:ed|s|ing)?|suggest(?:ed|s|ing)?|"
    r"promise(?:d|s|ing)?|decid(?:e|ed|es|ing)|"
    r"ask(?:ed|s|ing)?|assign(?:ed|s|ing)?|approv(?:e|ed|es|ing)|"
    r"call(?:ed|s|ing)?|message(?:d|s|ing)?|text(?:ed|s|ing)?|"
    r"help(?:ed|s|ing)?|assist(?:ed|s|ing)?|support(?:ed|s|ing)?|"
    r"join(?:ed|s|ing)?|meet|met|visit(?:ed|s|ing)?|"
    r"introduc(?:e|ed|es|ing)|send|sent|give|gave|lend|lent|tell|told|"
    r"рекомендовал(?:а)?|порекомендовал(?:а)?|посоветовал(?:а)?|"
    r"пообещал(?:а)?|обещал(?:а)?|решил(?:а)?|"
    r"спросил(?:а)?|назначил(?:а)?|одобрил(?:а)?|сказал(?:а)?|"
    r"познакомил(?:а|и)?|представил(?:а|и)?|"
    r"помог(?:ла|ли)?|поддержал(?:а|и)?"
)
_DIRECT_RECIPIENT_ACTION_VERB_RE = (
    r"promise(?:d|s|ing)?|ask(?:ed|s|ing)?|assign(?:ed|s|ing)?|"
    r"call(?:ed|s|ing)?|message(?:d|s|ing)?|text(?:ed|s|ing)?|"
    r"help(?:ed|s|ing)?|assist(?:ed|s|ing)?|support(?:ed|s|ing)?|"
    r"join(?:ed|s|ing)?|meet|met|visit(?:ed|s|ing)?|"
    r"introduc(?:e|ed|es|ing)|send|sent|give|gave|lend|lent|tell|told|"
    r"пообещал(?:а)?|обещал(?:а)?|спросил(?:а)?|назначил(?:а)?|"
    r"сказал(?:а)?|познакомил(?:а|и)?|представил(?:а|и)?|"
    r"помог(?:ла|ли)?|поддержал(?:а|и)?"
)
_PASSIVE_ACTION_VERB_RE = (
    r"recommended|suggested|promised|asked|assigned|approved|"
    r"called|messaged|texted|helped|assisted|supported|joined|met|visited|"
    r"introduced|sent|given|lent|told"
)
_INFO_SOURCE_VERB_RE = (
    r"hear(?:d|s|ing)?|learn(?:ed|s|ing)?|find\s+out|found\s+out|"
    r"узнал(?:а|и)?|услышал(?:а|и)?"
)
_BORROW_SOURCE_VERB_RE = r"borrow(?:ed|s|ing)?"
_QUESTION_ACTION_RE = re.compile(
    rf"\b(?:what\s+did\s+|did\s+|what\s+has\s+|has\s+)?"
    rf"(?P<actor>{_QUERY_LABEL_RE})\s+"
    rf"(?P<verb>{_ACTION_VERB_RE})\b",
    re.IGNORECASE,
)
_WHO_TO_ACTION_RE = re.compile(
    rf"\bwho\s+(?P<verb>{_ACTION_VERB_RE})\b"
    rf"(?P<object>.{{0,120}}?)\b(?:to|for)\s+"
    rf"(?P<recipient>{_QUERY_LABEL_RE})\b",
    re.IGNORECASE,
)
_RU_WHO_OBJECT_TO_ACTION_RE = re.compile(
    rf"\bкто\s+(?P<verb>{_ACTION_VERB_RE})\s+"
    rf"(?P<object>{_QUERY_LABEL_RE})\s+\b(?:с|со)\s+"
    rf"(?P<recipient>{_QUERY_LABEL_RE})\b",
    re.IGNORECASE,
)
_WHO_DIRECT_RECIPIENT_ACTION_QUERY_RE = re.compile(
    rf"\bwho\s+(?P<verb>{_DIRECT_RECIPIENT_ACTION_VERB_RE})\s+"
    rf"(?P<recipient>{_QUERY_LABEL_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_RU_WHO_DIRECT_RECIPIENT_ACTION_QUERY_RE = re.compile(
    rf"\bкто\s+(?P<verb>{_DIRECT_RECIPIENT_ACTION_VERB_RE})\s+"
    rf"(?P<recipient>{_QUERY_LABEL_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_WHO_DID_ACTOR_ACTION_TO_QUERY_RE = re.compile(
    rf"\b(?:who|whom)\s+did\s+(?P<actor>{_QUERY_LABEL_RE})\s+"
    rf"(?P<verb>{_ACTION_VERB_RE})\b"
    rf"(?P<object>.{{0,120}}?)\b(?:to|for)\b"
    rf"(?=\s*(?:\?|$|in\b|during\b|after\b|before\b|on\b|at\b))",
    re.IGNORECASE | re.DOTALL,
)
_WHO_DID_ACTOR_DIRECT_RECIPIENT_QUERY_RE = re.compile(
    rf"\b(?:who|whom)\s+did\s+(?P<actor>{_QUERY_LABEL_RE})\s+"
    rf"(?P<verb>{_DIRECT_RECIPIENT_ACTION_VERB_RE})\b"
    rf"(?P<object>.{{0,120}}?)"
    rf"(?=\?|$|\b(?:about|regarding|during|after|before|on|at|in|when|because)\b)",
    re.IGNORECASE | re.DOTALL,
)
_WHO_DID_ACTOR_ACTION_WITH_QUERY_RE = re.compile(
    rf"\b(?:who|whom)\s+did\s+(?P<actor>{_QUERY_LABEL_RE})\s+"
    rf"(?P<verb>{_ACTION_VERB_RE})\b"
    rf"(?P<object>.{{0,120}}?)\bwith\b"
    rf"(?=\s*(?:\?|$|in\b|during\b|after\b|before\b|on\b|at\b))",
    re.IGNORECASE | re.DOTALL,
)
_WHO_ACTION_WITH_RECIPIENT_QUERY_RE = re.compile(
    rf"\bwho\s+(?P<verb>{_ACTION_VERB_RE})\b"
    rf"(?P<object>.{{0,120}}?)\bwith\s+(?P<recipient>{_QUERY_LABEL_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_TO_WHOM_DID_ACTOR_ACTION_QUERY_RE = re.compile(
    rf"\b(?:to|for)\s+whom\s+did\s+(?P<actor>{_QUERY_LABEL_RE})\s+"
    rf"(?P<verb>{_ACTION_VERB_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_WHO_WAS_ACTIONED_BY_ACTOR_QUERY_RE = re.compile(
    rf"\bwho\s+(?:was|were)\s+(?P<verb>{_PASSIVE_ACTION_VERB_RE})\b"
    rf"(?P<object>.{{0,140}}?)\bby\s+(?P<actor>{_QUERY_LABEL_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_WHO_WAS_RECIPIENT_ACTIONED_BY_QUERY_RE = re.compile(
    rf"\bwho\s+(?:was|were)\s+(?P<recipient>{_QUERY_LABEL_RE})\s+"
    rf"(?P<verb>{_PASSIVE_ACTION_VERB_RE})\b"
    rf"(?P<object>.{{0,140}}?)\bby\b",
    re.IGNORECASE | re.DOTALL,
)
_WHO_DID_ACTOR_INFO_SOURCE_QUERY_RE = re.compile(
    rf"\b(?:who|whom)\s+did\s+(?P<actor>{_QUERY_LABEL_RE})\s+"
    rf"(?P<verb>{_INFO_SOURCE_VERB_RE})\b"
    rf"(?P<object>.{{0,160}}?)\bfrom\b"
    rf"(?=\s*(?:\?|$|in\b|during\b|after\b|before\b|on\b|at\b))",
    re.IGNORECASE | re.DOTALL,
)
_FROM_WHOM_DID_ACTOR_INFO_SOURCE_QUERY_RE = re.compile(
    rf"\bfrom\s+whom\s+did\s+(?P<actor>{_QUERY_LABEL_RE})\s+"
    rf"(?P<verb>{_INFO_SOURCE_VERB_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_RU_FROM_WHOM_ACTOR_INFO_SOURCE_QUERY_RE = re.compile(
    rf"\bот\s+кого\s+(?P<actor>{_QUERY_LABEL_RE})\s+"
    rf"(?P<verb>{_INFO_SOURCE_VERB_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_WHO_DID_ACTOR_BORROW_FROM_QUERY_RE = re.compile(
    rf"\b(?:who|whom)\s+did\s+(?P<actor>{_QUERY_LABEL_RE})\s+"
    rf"(?P<verb>{_BORROW_SOURCE_VERB_RE})\b"
    rf"(?P<object>.{{0,160}}?)\bfrom\b"
    rf"(?=\s*(?:\?|$|in\b|during\b|after\b|before\b|on\b|at\b))",
    re.IGNORECASE | re.DOTALL,
)
_FROM_WHOM_DID_ACTOR_BORROW_QUERY_RE = re.compile(
    rf"\bfrom\s+whom\s+did\s+(?P<actor>{_QUERY_LABEL_RE})\s+"
    rf"(?P<verb>{_BORROW_SOURCE_VERB_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_WHO_WAS_THERE_FOR_QUERY_RE = re.compile(
    rf"\bwho\s+(?:is|was|were|has\s+been|have\s+been|'s)\s+"
    rf"there\s+for\s+(?P<recipient>{_QUERY_LABEL_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_RU_WHO_WAS_THERE_FOR_QUERY_RE = re.compile(
    rf"\bкто\s+(?:(?:был|была|были)\s+)?рядом\s+с\s+"
    rf"(?P<recipient>{_QUERY_LABEL_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_NOMINAL_ACTION_QUERY_RE = re.compile(
    r"\b(?:what|which)\s+"
    r"(?P<noun>decision|promise|recommendation|suggestion)\s+"
    rf"did\s+(?P<actor>{_QUERY_LABEL_RE})\s+(?:make|give|offer)\b"
    r"(?P<tail>.{0,120})",
    re.IGNORECASE | re.DOTALL,
)
_OWNER_RESPONSIBILITY_QUERY_RE = re.compile(
    rf"\b(?:(?:who\s+(?:is|was|'s)\s+(?:responsible|(?:the\s+)?owner)|who\s+owns)"
    rf"|(?:is|was)\s+(?P<owner_after>{_QUERY_LABEL_RE})\s+responsible"
    rf"|(?P<owner_before>{_QUERY_LABEL_RE})\s+"
    rf"(?:is|was|'s)\s+(?:responsible|(?:the\s+)?owner)"
    rf"|(?P<owner_owns>{_QUERY_LABEL_RE})\s+owns?)\b",
    re.IGNORECASE,
)
_SUGGESTION_SOURCE_QUERY_RE = re.compile(
    rf"\b(?P<recipient>{_QUERY_LABEL_RE})\s+"
    r"(?:read|watched|tried|bought|used|visited|listened|started|played|made|ate)\b"
    r".{0,120}\b(?:from|based\s+on|because\s+of|after)\s+"
    rf"(?P<actor>{_QUERY_LABEL_RE})(?:'s|s')?\s+"
    r"(?:suggestion|recommendation|advice)\b",
    re.IGNORECASE | re.DOTALL,
)
_RECIPIENT_FOLLOWUP_ACTION_RE = (
    r"read|watch(?:ed)?|try|tried|buy|bought|use|used|visit(?:ed)?|"
    r"listen(?:ed)?|start(?:ed)?|play(?:ed)?|make|made|eat|ate"
)
_WHO_RECOMMENDED_THAT_RECIPIENT_QUERY_RE = re.compile(
    r"\bwho\s+"
    r"(?P<verb>recommend(?:ed|s|ing)?|suggest(?:ed|s|ing)?)\s+"
    rf"(?:that\s+)?(?P<recipient>{_QUERY_LABEL_RE})\s+"
    rf"(?:{_RECIPIENT_FOLLOWUP_ACTION_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_WHAT_DID_ACTOR_RECOMMEND_RECIPIENT_ACTION_QUERY_RE = re.compile(
    r"\b(?:what|which)(?:\s+\w+){0,4}\s+did\s+"
    rf"(?P<actor>{_QUERY_LABEL_RE})\s+"
    r"(?P<verb>recommend(?:ed|s|ing)?|suggest(?:ed|s|ing)?)\s+"
    rf"(?:that\s+)?(?P<recipient>{_QUERY_LABEL_RE})\s+"
    rf"(?:{_RECIPIENT_FOLLOWUP_ACTION_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_RECIPIENT_AFTER_ACTOR_RECOMMENDATION_QUERY_RE = re.compile(
    rf"\b(?P<recipient>{_QUERY_LABEL_RE})\s+"
    r"(?:read|watched|tried|bought|used|visited|listened|started|played|made|ate)\b"
    r".{0,120}\b(?:after|because|since|when)\s+"
    rf"(?P<actor>{_QUERY_LABEL_RE})\s+"
    r"(?P<verb>recommend(?:ed|s|ing)?|suggest(?:ed|s|ing)?)\b",
    re.IGNORECASE | re.DOTALL,
)
_WHOSE_SUGGESTION_QUERY_RE = re.compile(
    r"\bwhose\s+(?:suggestion|recommendation|advice)\s+did\s+"
    rf"(?P<recipient>{_QUERY_LABEL_RE})\s+"
    r"(?:follow|take|use|read|watch|try|buy|visit|listen|start|play|make|eat)\b",
    re.IGNORECASE,
)
_WHO_GAVE_SUGGESTION_TO_QUERY_RE = re.compile(
    r"\bwho\s+(?:gave|offered|made)\b"
    r".{0,80}\b(?:suggestion|recommendation|advice)\b"
    rf".{{0,80}}\b(?:to|for)\s+(?P<recipient>{_QUERY_LABEL_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_WHO_GAVE_DIRECT_SUGGESTION_QUERY_RE = re.compile(
    r"\bwho\s+(?:gave|offered|made)\s+"
    rf"(?P<recipient>{_QUERY_LABEL_RE})\b"
    r".{0,80}\b(?:suggestion|recommendation|advice)\b",
    re.IGNORECASE | re.DOTALL,
)
_RU_WHO_DIRECT_RECOMMENDATION_QUERY_RE = re.compile(
    r"\bкто\s+"
    r"(?P<verb>рекомендовал(?:а)?|порекомендовал(?:а)?|посоветовал(?:а)?)\s+"
    rf"(?P<recipient>{_QUERY_LABEL_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_RU_WHOSE_SUGGESTION_QUERY_RE = re.compile(
    r"\bпо\s+чь(?:ему|ей|им)\s+"
    r"(?:совет\w*|рекомендац\w*)\s+"
    rf"(?P<recipient>{_QUERY_LABEL_RE})\s+"
    r"(?:прочитал(?:а|и)?|посмотрел(?:а|и)?|попробовал(?:а|и)?|"
    r"использовал(?:а|и)?|купил(?:а|и)?|посетил(?:а|и)?|начал(?:а|и)?)\b",
    re.IGNORECASE | re.DOTALL,
)
_RU_TO_WHOM_ACTOR_ACTION_QUERY_RE = re.compile(
    rf"\bкому\s+(?P<actor>{_QUERY_LABEL_RE})\s+"
    rf"(?P<verb>{_ACTION_VERB_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_REPORTED_SUBJECT_SHIFT_RE = re.compile(
    rf"\b(?:heard|learned|mentioned|reported|said|told|wrote)\b"
    rf".{{0,80}}\b{_LABEL_RE}\W*$",
    re.IGNORECASE | re.DOTALL,
)
_NEGATED_ACTION_GAP_RE = re.compile(
    r"\b(?:did\s+not|didn't|does\s+not|doesn't|never|not|"
    r"cannot|can\s+not|can't|could\s+not|couldn't|would\s+not|wouldn't|"
    r"no\s+longer)\b|"
    r"\b(?:не|никогда\s+не)\b",
    re.IGNORECASE | re.DOTALL,
)
_NEGATION_CANCEL_RE = re.compile(
    r"\bnot\s+only\b|\bне\s+только\b",
    re.IGNORECASE | re.DOTALL,
)
_QUERY_LABEL_STOP_WORDS = frozenset(
    {
        "did",
        "has",
        "what",
        "who",
        "whom",
        "whose",
        "anybody",
        "anyone",
        "buy",
        "people",
        "person",
        "eat",
        "follow",
        "listen",
        "last",
        "latest",
        "make",
        "newest",
        "play",
        "read",
        "recent",
        "somebody",
        "someone",
        "start",
        "take",
        "the",
        "try",
        "use",
        "visit",
        "watch",
        "что",
        "кто",
        "кого",
        "кому",
    }
)
_TEXT_LABEL_STOP_WORDS = _QUERY_LABEL_STOP_WORDS.union(
    {
        "project",
        "transcript",
    }
)
_ACTION_ROLE_MATCH_BOOST = 0.024
_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST = 0.028
_ACTION_ROLE_ACTOR_MATCH_BOOST = 0.018
_ACTION_ROLE_RECIPIENT_MATCH_BOOST = 0.016
_ACTION_ROLE_OWNER_EVIDENCE_BOOST = 0.014
_ACTION_ROLE_MISMATCH_PENALTY = 0.034
_ACTION_ROLE_RECIPIENT_MISMATCH_PENALTY = 0.028
_ACTION_ROLE_REQUESTED_RECIPIENT_MISSING_PENALTY = 0.024
_DIRECT_RECIPIENT_VERBS = frozenset(
    {
        "ask",
        "assign",
        "call",
        "give",
        "help",
        "introduce",
        "join",
        "lend",
        "meet",
        "message",
        "promise",
        "send",
        "tell",
        "visit",
    }
)
_COMPANION_ACTION_VERBS = frozenset({"join", "meet", "visit"})
_DIRECT_RECIPIENT_OBJECT_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "badge",
        "book",
        "camera",
        "car",
        "charger",
        "decision",
        "doc",
        "document",
        "email",
        "file",
        "image",
        "invoice",
        "link",
        "laptop",
        "message",
        "note",
        "notes",
        "photo",
        "plan",
        "report",
        "screenshot",
        "story",
        "task",
        "the",
        "ticket",
        "to",
        "update",
        "wallet",
    }
)
_ACTION_CONTEXT_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "after",
        "an",
        "and",
        "at",
        "before",
        "did",
        "during",
        "for",
        "from",
        "in",
        "on",
        "the",
        "to",
        "with",
        "who",
        "whom",
        "что",
        "кто",
        "кого",
        "кому",
        "на",
        "о",
        "об",
        "от",
        "по",
        "после",
        "про",
        "с",
        "со",
    }
)


@dataclass(frozen=True)
class ActionRoleRerankSignal:
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class _ActionRoleQuery:
    verb_key: str
    actor_label: str = ""
    recipient_label: str = ""
    object_label: str = ""
    context_terms: tuple[str, ...] = ()
    owner_label: str = ""
    owner_requested: bool = False
    recipient_requested: bool = False
    source_requested: bool = False
    companion_requested: bool = False


def action_role_rerank_signal(*, query: str, text: str) -> ActionRoleRerankSignal:
    """Return bounded role-order signal for action questions.

    This intentionally treats provider/output text as evidence only: it adjusts ranking,
    but never rewrites or asserts canonical facts.
    """

    role_query = _action_role_query(query)
    if role_query is None:
        return ActionRoleRerankSignal()
    if role_query.source_requested:
        if role_query.verb_key == "borrow":
            return _borrow_source_signal(role_query, text)
        return _information_source_signal(role_query, text)
    if role_query.companion_requested:
        return _companion_action_signal(role_query, text)
    if role_query.owner_requested:
        return _owner_responsibility_signal(role_query, text)
    if role_query.actor_label:
        return _actor_action_signal(role_query, text)
    if role_query.recipient_label:
        return _recipient_action_signal(role_query, text)
    return ActionRoleRerankSignal()


def _action_role_query(query: str) -> _ActionRoleQuery | None:
    owner_match = _OWNER_RESPONSIBILITY_QUERY_RE.search(query)
    if owner_match is not None:
        owner = _clean_label(
            owner_match.group("owner_after")
            or owner_match.group("owner_before")
            or owner_match.group("owner_owns")
            or ""
        )
        return _ActionRoleQuery(
            verb_key="owner",
            owner_label=owner,
            owner_requested=True,
        )

    for pattern in (_WHO_WAS_THERE_FOR_QUERY_RE, _RU_WHO_WAS_THERE_FOR_QUERY_RE):
        match = pattern.search(query)
        if match is not None:
            recipient = _clean_label(match.group("recipient"))
            if recipient:
                return _ActionRoleQuery(
                    verb_key="support_presence",
                    recipient_label=recipient,
                )

    match = _WHO_ACTION_WITH_RECIPIENT_QUERY_RE.search(query)
    if match is not None:
        recipient = _clean_label(match.group("recipient"))
        verb_key = _canonical_verb_key(match.group("verb"))
        context_terms = _action_context_terms(
            match.groupdict().get("object") or "",
            verb_key=verb_key,
        )
        if recipient and verb_key in _COMPANION_ACTION_VERBS:
            return _ActionRoleQuery(
                verb_key=verb_key,
                recipient_label=recipient,
                context_terms=context_terms,
                companion_requested=True,
            )

    for pattern in (_WHO_TO_ACTION_RE, _RU_WHO_OBJECT_TO_ACTION_RE):
        match = pattern.search(query)
        if match is not None:
            verb_key = _canonical_verb_key(match.group("verb"))
            if pattern is _RU_WHO_OBJECT_TO_ACTION_RE and verb_key != "introduce":
                continue
            recipient = _clean_label(match.group("recipient"))
            object_label = _object_label_in_text(match.group("object") or "")
            if verb_key and recipient:
                return _ActionRoleQuery(
                    verb_key=verb_key,
                    recipient_label=recipient,
                    object_label=object_label if verb_key == "introduce" else "",
                )

    match = _WHOSE_SUGGESTION_QUERY_RE.search(query)
    if match is not None:
        recipient = _clean_label(match.group("recipient"))
        if recipient:
            return _ActionRoleQuery(
                verb_key="recommend",
                recipient_label=recipient,
            )

    for pattern in (
        _WHO_GAVE_SUGGESTION_TO_QUERY_RE,
        _WHO_GAVE_DIRECT_SUGGESTION_QUERY_RE,
    ):
        match = pattern.search(query)
        if match is not None:
            recipient = _clean_label(match.group("recipient"))
            if recipient:
                return _ActionRoleQuery(
                    verb_key="recommend",
                    recipient_label=recipient,
                )

    match = _WHO_RECOMMENDED_THAT_RECIPIENT_QUERY_RE.search(query)
    if match is not None:
        recipient = _clean_label(match.group("recipient"))
        if recipient:
            return _ActionRoleQuery(
                verb_key="recommend",
                recipient_label=recipient,
            )

    match = _WHAT_DID_ACTOR_RECOMMEND_RECIPIENT_ACTION_QUERY_RE.search(query)
    if match is not None:
        actor = _clean_label(match.group("actor"))
        recipient = _clean_label(match.group("recipient"))
        if actor and recipient:
            return _ActionRoleQuery(
                verb_key="recommend",
                actor_label=actor,
                recipient_label=recipient,
            )

    match = _RU_WHO_DIRECT_RECOMMENDATION_QUERY_RE.search(query)
    if match is not None:
        recipient = _clean_label(match.group("recipient"))
        if recipient:
            return _ActionRoleQuery(
                verb_key="recommend",
                recipient_label=recipient,
            )

    match = _RU_WHOSE_SUGGESTION_QUERY_RE.search(query)
    if match is not None:
        recipient = _clean_label(match.group("recipient"))
        if recipient:
            return _ActionRoleQuery(
                verb_key="recommend",
                recipient_label=recipient,
            )

    match = _WHO_DID_ACTOR_ACTION_WITH_QUERY_RE.search(query)
    if match is not None:
        actor = _clean_label(match.group("actor"))
        verb_key = _canonical_verb_key(match.group("verb"))
        context_terms = _action_context_terms(
            match.groupdict().get("object") or "",
            verb_key=verb_key,
        )
        if actor and verb_key in _COMPANION_ACTION_VERBS:
            return _ActionRoleQuery(
                verb_key=verb_key,
                actor_label=actor,
                context_terms=context_terms,
                companion_requested=True,
            )

    for pattern in (
        _WHO_DIRECT_RECIPIENT_ACTION_QUERY_RE,
        _RU_WHO_DIRECT_RECIPIENT_ACTION_QUERY_RE,
    ):
        match = pattern.search(query)
        if match is not None:
            verb_key = _canonical_verb_key(match.group("verb"))
            recipient = _clean_label(match.group("recipient"))
            if verb_key and recipient:
                return _ActionRoleQuery(verb_key=verb_key, recipient_label=recipient)

    for pattern in (
        _SUGGESTION_SOURCE_QUERY_RE,
        _RECIPIENT_AFTER_ACTOR_RECOMMENDATION_QUERY_RE,
    ):
        match = pattern.search(query)
        if match is not None:
            actor = _clean_label(match.group("actor"))
            recipient = _clean_label(match.group("recipient"))
            if actor and recipient:
                return _ActionRoleQuery(
                    verb_key="recommend",
                    actor_label=actor,
                    recipient_label=recipient,
                )

    match = _WHO_WAS_ACTIONED_BY_ACTOR_QUERY_RE.search(query)
    if match is not None:
        actor = _clean_label(match.group("actor"))
        verb_key = _canonical_verb_key(match.group("verb"))
        if actor and verb_key:
            return _ActionRoleQuery(
                verb_key=verb_key,
                actor_label=actor,
                recipient_requested=True,
            )

    match = _WHO_WAS_RECIPIENT_ACTIONED_BY_QUERY_RE.search(query)
    if match is not None:
        recipient = _clean_label(match.group("recipient"))
        verb_key = _canonical_verb_key(match.group("verb"))
        if recipient and verb_key:
            return _ActionRoleQuery(
                verb_key=verb_key,
                recipient_label=recipient,
            )

    for pattern in (
        _WHO_DID_ACTOR_INFO_SOURCE_QUERY_RE,
        _FROM_WHOM_DID_ACTOR_INFO_SOURCE_QUERY_RE,
        _RU_FROM_WHOM_ACTOR_INFO_SOURCE_QUERY_RE,
    ):
        match = pattern.search(query)
        if match is not None:
            actor = _clean_label(match.group("actor"))
            if actor:
                return _ActionRoleQuery(
                    verb_key="information_source",
                    actor_label=actor,
                    source_requested=True,
                )

    for pattern in (
        _WHO_DID_ACTOR_BORROW_FROM_QUERY_RE,
        _FROM_WHOM_DID_ACTOR_BORROW_QUERY_RE,
    ):
        match = pattern.search(query)
        if match is not None:
            actor = _clean_label(match.group("actor"))
            context_terms = _action_context_terms(
                match.groupdict().get("object") or "",
                verb_key="borrow",
            )
            if actor:
                return _ActionRoleQuery(
                    verb_key="borrow",
                    actor_label=actor,
                    context_terms=context_terms,
                    source_requested=True,
                )

    for pattern in (
        _WHO_DID_ACTOR_ACTION_TO_QUERY_RE,
        _WHO_DID_ACTOR_DIRECT_RECIPIENT_QUERY_RE,
        _TO_WHOM_DID_ACTOR_ACTION_QUERY_RE,
        _RU_TO_WHOM_ACTOR_ACTION_QUERY_RE,
    ):
        match = pattern.search(query)
        if match is not None:
            actor = _clean_label(match.group("actor"))
            verb_key = _canonical_verb_key(match.group("verb"))
            object_label = _object_label_in_text(match.groupdict().get("object") or "")
            context_terms = _action_context_terms(
                match.groupdict().get("object") or "",
                verb_key=verb_key,
            )
            if actor and verb_key:
                return _ActionRoleQuery(
                    verb_key=verb_key,
                    actor_label=actor,
                    object_label=object_label if verb_key == "introduce" else "",
                    context_terms=() if verb_key == "introduce" else context_terms,
                    recipient_requested=True,
                )

    match = _NOMINAL_ACTION_QUERY_RE.search(query)
    if match is not None:
        actor = _clean_label(match.group("actor"))
        verb_key = _canonical_nominal_action(match.group("noun"))
        recipient = _recipient_in_tail(match.group("tail") or "")
        if actor and verb_key:
            return _ActionRoleQuery(
                verb_key=verb_key,
                actor_label=actor,
                recipient_label=recipient,
            )

    match = _QUESTION_ACTION_RE.search(query)
    if match is None:
        return None
    actor = _clean_label(match.group("actor"))
    verb_key = _canonical_verb_key(match.group("verb"))
    if not actor or not verb_key:
        return None
    recipient = _recipient_after_action(
        query,
        match_end=match.end(),
        verb_key=verb_key,
    )
    return _ActionRoleQuery(
        verb_key=verb_key,
        actor_label=actor,
        recipient_label=recipient,
    )


def _actor_action_signal(
    role_query: _ActionRoleQuery,
    text: str,
) -> ActionRoleRerankSignal:
    actor = role_query.actor_label
    recipient = role_query.recipient_label
    verb_key = role_query.verb_key
    object_label = role_query.object_label
    context_terms = role_query.context_terms
    if (
        verb_key == "meet"
        and role_query.recipient_requested
        and (
            _has_actor_action_to_any_recipient(
                text,
                actor=actor,
                verb_key=verb_key,
            )
            or _has_action_to_recipient(text, recipient=actor, verb_key=verb_key)
        )
    ):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST,
            reason="action_role_actor_to_recipient_evidence",
        )
    if _has_negated_actor_action(
        text,
        actor=actor,
        verb_key=verb_key,
        target=recipient or object_label,
        recipient_requested=role_query.recipient_requested,
        context_terms=context_terms,
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_MISMATCH_PENALTY,
            reason="action_role_negated_evidence",
        )
    if (
        recipient
        and object_label
        and _has_ordered_action_object_to_recipient(
            text,
            verb_key=verb_key,
            object_label=object_label,
            recipient=recipient,
        )
    ):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_MATCH_BOOST,
            reason="action_role_actor_recipient_match",
        )
    if (
        recipient
        and object_label
        and _has_ordered_action_object_to_recipient(
            text,
            verb_key=verb_key,
            object_label=recipient,
            recipient=object_label,
        )
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_MISMATCH_PENALTY,
            reason="action_role_actor_recipient_reversed",
        )
    if recipient and _has_ordered_action(text, actor=actor, verb_key=verb_key, target=recipient):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_MATCH_BOOST,
            reason="action_role_actor_recipient_match",
        )
    if recipient and _has_ordered_action(text, actor=recipient, verb_key=verb_key, target=actor):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_MISMATCH_PENALTY,
            reason="action_role_actor_recipient_reversed",
        )
    if object_label and role_query.recipient_requested:
        if _has_actor_action_object_to_any_recipient(
            text,
            actor=actor,
            verb_key=verb_key,
            object_label=object_label,
        ):
            return ActionRoleRerankSignal(
                boost=_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST,
                reason="action_role_actor_to_recipient_evidence",
            )
        if _has_actor_action(text, actor=actor, verb_key=verb_key):
            return ActionRoleRerankSignal(
                penalty=_ACTION_ROLE_REQUESTED_RECIPIENT_MISSING_PENALTY,
                reason="action_role_requested_recipient_missing",
            )
    if context_terms and role_query.recipient_requested:
        if _has_actor_action_to_any_recipient_with_context(
            text,
            actor=actor,
            verb_key=verb_key,
            context_terms=context_terms,
        ):
            return ActionRoleRerankSignal(
                boost=_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST,
                reason="action_role_actor_to_recipient_evidence",
            )
        if _has_actor_action_to_any_recipient(
            text,
            actor=actor,
            verb_key=verb_key,
        ):
            return ActionRoleRerankSignal(
                penalty=_ACTION_ROLE_REQUESTED_RECIPIENT_MISSING_PENALTY,
                reason="action_role_requested_context_mismatch",
            )
    if role_query.recipient_requested and _has_actor_action_to_any_recipient(
        text,
        actor=actor,
        verb_key=verb_key,
    ):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST,
            reason="action_role_actor_to_recipient_evidence",
        )
    if _has_actor_action(text, actor=actor, verb_key=verb_key):
        if role_query.recipient_requested:
            return ActionRoleRerankSignal(
                penalty=_ACTION_ROLE_REQUESTED_RECIPIENT_MISSING_PENALTY,
                reason="action_role_requested_recipient_missing",
            )
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_ACTOR_MATCH_BOOST,
            reason="action_role_actor_match",
        )
    if _has_non_actor_action(text, expected_actor=actor, verb_key=verb_key):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_MISMATCH_PENALTY,
            reason="action_role_actor_mismatch",
        )
    return ActionRoleRerankSignal()


def _recipient_action_signal(
    role_query: _ActionRoleQuery,
    text: str,
) -> ActionRoleRerankSignal:
    recipient = role_query.recipient_label
    verb_key = role_query.verb_key
    object_label = role_query.object_label
    if verb_key == "support_presence":
        return _support_presence_signal(recipient=recipient, text=text)
    if _has_negated_action_to_recipient(
        text,
        recipient=recipient,
        verb_key=verb_key,
        object_label=object_label,
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_RECIPIENT_MISMATCH_PENALTY,
            reason="action_role_negated_evidence",
        )
    if object_label and _has_ordered_action_object_to_recipient(
        text,
        verb_key=verb_key,
        object_label=object_label,
        recipient=recipient,
    ):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_RECIPIENT_MATCH_BOOST,
            reason="action_role_recipient_match",
        )
    if object_label and _has_ordered_action_object_to_recipient(
        text,
        verb_key=verb_key,
        object_label=recipient,
        recipient=object_label,
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_RECIPIENT_MISMATCH_PENALTY,
            reason="action_role_recipient_mismatch",
        )
    if _has_action_to_recipient(text, recipient=recipient, verb_key=verb_key):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_RECIPIENT_MATCH_BOOST,
            reason="action_role_recipient_match",
        )
    if verb_key == "meet" and _recipient_acts_to_other(
        text,
        recipient=recipient,
        verb_key=verb_key,
    ):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_RECIPIENT_MATCH_BOOST,
            reason="action_role_recipient_match",
        )
    if _recipient_acts_to_other(text, recipient=recipient, verb_key=verb_key):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_RECIPIENT_MISMATCH_PENALTY,
            reason="action_role_recipient_mismatch",
        )
    return ActionRoleRerankSignal()


def _companion_action_signal(
    role_query: _ActionRoleQuery,
    text: str,
) -> ActionRoleRerankSignal:
    participant = role_query.actor_label or role_query.recipient_label
    if not participant:
        return ActionRoleRerankSignal()
    if _has_participant_action_with_companion(
        text,
        participant=participant,
        verb_key=role_query.verb_key,
        context_terms=role_query.context_terms,
    ):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_MATCH_BOOST,
            reason="action_role_companion_match",
        )
    if _has_participant_action_without_companion(
        text,
        participant=participant,
        verb_key=role_query.verb_key,
        context_terms=role_query.context_terms,
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_REQUESTED_RECIPIENT_MISSING_PENALTY,
            reason="action_role_companion_missing",
        )
    return ActionRoleRerankSignal()


def _support_presence_signal(*, recipient: str, text: str) -> ActionRoleRerankSignal:
    if _has_negated_support_presence_for_recipient(text, recipient=recipient):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_RECIPIENT_MISMATCH_PENALTY,
            reason="action_role_negated_evidence",
        )
    if _has_support_presence_for_recipient(text, recipient=recipient):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_RECIPIENT_MATCH_BOOST,
            reason="action_role_recipient_match",
        )
    if _recipient_present_for_other(text, recipient=recipient):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_RECIPIENT_MISMATCH_PENALTY,
            reason="action_role_recipient_mismatch",
        )
    return ActionRoleRerankSignal()


def _information_source_signal(
    role_query: _ActionRoleQuery,
    text: str,
) -> ActionRoleRerankSignal:
    actor = role_query.actor_label
    if _has_actor_info_from_any_source(text, actor=actor) or _has_source_told_actor(
        text,
        actor=actor,
    ):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST,
            reason="action_role_information_source_evidence",
        )
    if _actor_tells_other(text, actor=actor) or _has_other_actor_info_from_source(
        text,
        expected_actor=actor,
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_MISMATCH_PENALTY,
            reason="action_role_information_source_reversed",
        )
    if _has_info_actor_without_source(text, actor=actor):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_REQUESTED_RECIPIENT_MISSING_PENALTY,
            reason="action_role_information_source_missing",
        )
    return ActionRoleRerankSignal()


def _borrow_source_signal(
    role_query: _ActionRoleQuery,
    text: str,
) -> ActionRoleRerankSignal:
    actor = role_query.actor_label
    context_terms = role_query.context_terms
    if _has_actor_borrow_from_source(
        text,
        actor=actor,
        context_terms=context_terms,
    ) or _has_source_lent_to_actor(
        text,
        actor=actor,
        context_terms=context_terms,
    ):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST,
            reason="action_role_transfer_source_evidence",
        )
    if _actor_lent_to_other(
        text,
        actor=actor,
        context_terms=context_terms,
    ) or _other_borrowed_from_actor(
        text,
        actor=actor,
        context_terms=context_terms,
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_MISMATCH_PENALTY,
            reason="action_role_transfer_source_reversed",
        )
    if _has_actor_borrow_without_source(
        text,
        actor=actor,
        context_terms=context_terms,
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_REQUESTED_RECIPIENT_MISSING_PENALTY,
            reason="action_role_transfer_source_missing",
        )
    return ActionRoleRerankSignal()


def _owner_responsibility_signal(
    role_query: _ActionRoleQuery,
    text: str,
) -> ActionRoleRerankSignal:
    owner = role_query.owner_label
    if not owner:
        if _owner_labels_in_text(text):
            return ActionRoleRerankSignal(
                boost=_ACTION_ROLE_OWNER_EVIDENCE_BOOST,
                reason="action_role_owner_evidence",
            )
        return ActionRoleRerankSignal()
    owner_key = _normalized_label(owner)
    owner_labels = {_normalized_label(label) for label in _owner_labels_in_text(text)}
    if owner_key in owner_labels:
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_ACTOR_MATCH_BOOST,
            reason="action_role_owner_match",
        )
    if owner_labels:
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_MISMATCH_PENALTY,
            reason="action_role_owner_mismatch",
        )
    return ActionRoleRerankSignal()


def _owner_labels_in_text(text: str) -> frozenset[str]:
    labels: set[str] = set()
    for pattern in (
        rf"(?P<label>{_LABEL_RE})\b.{{0,80}}\b(?:owns?|owner|responsible)\b",
        rf"\b(?:owner|responsible)\b.{{0,80}}\b(?P<label>{_LABEL_RE})\b",
        rf"\bassigned\s+to\s+(?P<label>{_LABEL_RE})\b",
    ):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            label = _clean_label(match.group("label"))
            if label:
                labels.add(label)
    return frozenset(labels)


def _has_support_presence_for_recipient(text: str, *, recipient: str) -> bool:
    recipient_pattern = _role_label_pattern(recipient)
    return bool(
        re.search(
            rf"\b{_LABEL_RE}\b.{{0,80}}\b"
            rf"(?:is|was|were|are|has\s+been|have\s+been|'s)\s+"
            rf"there\s+for\s+{recipient_pattern}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        or re.search(
            rf"\b{_LABEL_RE}\b.{{0,80}}\b"
            rf"(?:был|была|были)\s+рядом\s+с\s+{recipient_pattern}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _has_negated_support_presence_for_recipient(text: str, *, recipient: str) -> bool:
    recipient_pattern = _role_label_pattern(recipient)
    return bool(
        re.search(
            rf"\b{_LABEL_RE}\b.{{0,80}}\b"
            rf"(?:was|were|is|are|has\s+been|have\s+been)\s+not\s+"
            rf"there\s+for\s+{recipient_pattern}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        or re.search(
            rf"\b{_LABEL_RE}\b.{{0,80}}\bне\s+"
            rf"(?:был|была|были)\s+рядом\s+с\s+{recipient_pattern}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _recipient_present_for_other(text: str, *, recipient: str) -> bool:
    recipient_pattern = _role_label_pattern(recipient)
    return bool(
        re.search(
            rf"{recipient_pattern}.{{0,80}}\b"
            rf"(?:is|was|were|are|has\s+been|have\s+been|'s)\s+"
            rf"there\s+for\s+{_LABEL_RE}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        or re.search(
            rf"{recipient_pattern}.{{0,80}}\b"
            rf"(?:был|была|были)\s+рядом\s+с\s+{_LABEL_RE}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _has_ordered_action(
    text: str,
    *,
    actor: str,
    verb_key: str,
    target: str,
) -> bool:
    return bool(
        _ordered_action_match_iter(
            text,
            actor=actor,
            verb_key=verb_key,
            tail_pattern=rf".{{0,100}}{_label_pattern(target)}",
        )
    )


def _has_ordered_action_object_to_recipient(
    text: str,
    *,
    verb_key: str,
    object_label: str,
    recipient: str,
) -> bool:
    return bool(
        re.search(
            rf"\b(?:{_verb_forms(verb_key)})\b.{{0,80}}"
            rf"{_role_label_pattern(object_label)}.{{0,80}}\b"
            rf"(?:{_recipient_preposition_forms(verb_key)})\s+"
            rf"{_role_label_pattern(recipient)}",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _has_actor_action_object_to_any_recipient(
    text: str,
    *,
    actor: str,
    verb_key: str,
    object_label: str,
) -> bool:
    pattern = re.compile(
        rf"{_label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_verb_forms(verb_key)})\b.{{0,80}}"
        rf"{_role_label_pattern(object_label)}.{{0,80}}\b"
        rf"(?:{_recipient_preposition_forms(verb_key)})\s+"
        rf"(?P<recipient>{_LABEL_RE})\b",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        recipient = _clean_label(match.group("recipient"))
        if recipient and _looks_like_text_recipient(recipient):
            return True
    return False


def _ordered_action_match_iter(
    text: str,
    *,
    actor: str,
    verb_key: str,
    tail_pattern: str,
) -> bool:
    pattern = re.compile(
        rf"{_label_pattern(actor)}(?P<gap>.{{0,80}}?)\b(?:{_verb_forms(verb_key)})\b"
        rf"{tail_pattern}",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return any(
        not _action_gap_blocks_positive_match(match.group("gap"))
        for match in pattern.finditer(text)
    )


def _has_actor_action(text: str, *, actor: str, verb_key: str) -> bool:
    return _ordered_action_match_iter(
        text,
        actor=actor,
        verb_key=verb_key,
        tail_pattern="",
    )


def _has_participant_action_with_companion(
    text: str,
    *,
    participant: str,
    verb_key: str,
    context_terms: tuple[str, ...],
) -> bool:
    participant_key = _normalized_label(participant)
    pattern = re.compile(
        rf"(?P<actor>{_LABEL_RE})(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_verb_forms(verb_key)})\b(?P<body>.{{0,220}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        actor = _clean_label(match.group("actor"))
        body = match.group("body")
        if context_terms and not _context_terms_match(body, context_terms):
            continue
        if _normalized_label(actor) == participant_key and _body_has_companion(body):
            return True
        if _body_has_companion_label(body, participant=participant):
            return True
    paired_pattern = re.compile(
        rf"(?:{_label_pattern(participant)}\s+and\s+{_LABEL_RE}\b|"
        rf"\b{_LABEL_RE}\s+and\s+{_label_pattern(participant)}\b)"
        rf"(?P<body>.{{0,180}}\b(?:{_verb_forms(verb_key)})\b.{{0,140}})",
        re.IGNORECASE | re.DOTALL,
    )
    return any(
        not context_terms or _context_terms_match(match.group("body"), context_terms)
        for match in paired_pattern.finditer(text)
    )


def _has_participant_action_without_companion(
    text: str,
    *,
    participant: str,
    verb_key: str,
    context_terms: tuple[str, ...],
) -> bool:
    pattern = re.compile(
        rf"{_label_pattern(participant)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_verb_forms(verb_key)})\b(?P<body>.{{0,180}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        body = match.group("body")
        if context_terms and not _context_terms_match(body, context_terms):
            continue
        if not _body_has_companion(body):
            return True
    return False


def _body_has_companion(body: str) -> bool:
    return bool(
        re.search(
            rf"\b(?:with|alongside|together\s+with|joined\s+by|accompanied\s+by)\s+"
            rf"(?P<companion>{_LABEL_RE})\b",
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _body_has_companion_label(body: str, *, participant: str) -> bool:
    return bool(
        re.search(
            rf"\b(?:with|alongside|together\s+with|joined\s+by|accompanied\s+by)\s+"
            rf"{_role_label_pattern(participant)}\b",
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _has_negated_actor_action(
    text: str,
    *,
    actor: str,
    verb_key: str,
    target: str = "",
    recipient_requested: bool = False,
    context_terms: tuple[str, ...] = (),
) -> bool:
    pattern = re.compile(
        rf"{_label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_verb_forms(verb_key)})\b(?P<body>.{{0,220}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if not _negated_action_gap(match.group("gap")):
            continue
        body = match.group("body")
        if target and not re.search(
            _recipient_label_pattern(target, verb_key=verb_key),
            body,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            continue
        if recipient_requested and not _body_has_recipient_for_verb(
            body,
            verb_key=verb_key,
        ):
            continue
        if context_terms and not _context_terms_match(body, context_terms):
            continue
        return True
    return False


def _has_actor_action_to_any_recipient(text: str, *, actor: str, verb_key: str) -> bool:
    preposition_pattern = re.compile(
        rf"{_label_pattern(actor)}(?P<gap>.{{0,80}}?)\b(?:{_verb_forms(verb_key)})\b"
        rf".{{0,140}}\b(?:to|for)\s+(?P<recipient>{_LABEL_RE})\b",
        re.IGNORECASE | re.DOTALL,
    )
    for match in preposition_pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        recipient = _clean_label(match.group("recipient"))
        if recipient and _looks_like_text_recipient(recipient):
            return True
    if verb_key in _DIRECT_RECIPIENT_VERBS:
        direct_pattern = re.compile(
            rf"{_label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
            rf"(?:{_verb_forms(verb_key)})\b\s+"
            rf"(?P<recipient>{_LABEL_RE})\b(?P<tail>.{{0,40}})",
            re.IGNORECASE | re.DOTALL,
        )
        for match in direct_pattern.finditer(text):
            if _action_gap_blocks_positive_match(match.group("gap")):
                continue
            recipient = _clean_label(match.group("recipient"))
            if (
                recipient
                and _looks_like_direct_recipient(recipient)
                and _direct_recipient_context_allows(verb_key, match.group("tail"))
            ):
                return True
    passive_pattern = re.compile(
        rf"(?P<recipient>{_LABEL_RE})\b.{{0,100}}\b(?:was|were)\s+"
        rf"(?:{_verb_forms(verb_key)})\b.{{0,140}}\bby\s+{_label_pattern(actor)}",
        re.IGNORECASE | re.DOTALL,
    )
    for match in passive_pattern.finditer(text):
        recipient = _clean_label(match.group("recipient"))
        if recipient and _looks_like_text_recipient(recipient):
            return True
    if verb_key != "recommend":
        return False
    russian_direct_pattern = re.compile(
        rf"{_label_pattern(actor)}(?P<gap>.{{0,80}}?)"
        rf"\b(?:{_russian_recommendation_forms()})\b\s+"
        rf"(?P<recipient>{_LABEL_RE})\b",
        re.IGNORECASE | re.DOTALL,
    )
    for match in russian_direct_pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        recipient = _clean_label(match.group("recipient"))
        if recipient and _looks_like_text_recipient(recipient):
            return True
    return False


def _has_actor_action_to_any_recipient_with_context(
    text: str,
    *,
    actor: str,
    verb_key: str,
    context_terms: tuple[str, ...],
) -> bool:
    pattern = re.compile(
        rf"{_label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_verb_forms(verb_key)})\b(?P<body>.{{0,220}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        body = match.group("body")
        if not _body_has_recipient_for_verb(body, verb_key=verb_key):
            continue
        if _context_terms_match(body, context_terms):
            return True
    return False


def _body_has_recipient_for_verb(body: str, *, verb_key: str) -> bool:
    if re.search(rf"\b(?:to|for)\s+{_LABEL_RE}\b", body):
        return True
    if verb_key not in _DIRECT_RECIPIENT_VERBS:
        return False
    direct_match = re.match(
        rf"\s+(?P<recipient>{_LABEL_RE})\b(?P<tail>.{{0,80}})",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if direct_match is None:
        return False
    recipient = _clean_label(direct_match.group("recipient"))
    if not _looks_like_direct_recipient(recipient):
        return False
    return _direct_recipient_context_allows(verb_key, direct_match.group("tail"))


def _reported_subject_shift_before_action(gap: str) -> bool:
    return bool(_REPORTED_SUBJECT_SHIFT_RE.search(gap))


def _action_gap_blocks_positive_match(gap: str) -> bool:
    return _reported_subject_shift_before_action(gap) or _negated_action_gap(gap)


def _negated_action_gap(gap: str) -> bool:
    if not gap:
        return False
    if _NEGATION_CANCEL_RE.search(gap):
        return False
    return bool(_NEGATED_ACTION_GAP_RE.search(gap))


def _action_prefix_blocks_positive_match(text: str, action_start: int) -> bool:
    prefix = text[max(0, action_start - 64) : action_start]
    return _negated_action_gap(prefix)


def _has_actor_info_from_any_source(text: str, *, actor: str) -> bool:
    pattern = re.compile(
        rf"{_label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_INFO_SOURCE_VERB_RE})\b.{{0,160}}\b(?:from|от)\b(?P<tail>.{{0,80}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        if _source_tail_has_evidence(match.group("tail")):
            return True
    return False


def _has_source_told_actor(text: str, *, actor: str) -> bool:
    return bool(
        re.search(
            rf"\b{_LABEL_RE}\b.{{0,100}}\b"
            rf"(?:told|said|mentioned|reported|wrote|"
            rf"сказал(?:а)?|рассказал(?:а)?|упомянул(?:а)?)\b"
            rf".{{0,100}}{_label_pattern(actor)}",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _actor_tells_other(text: str, *, actor: str) -> bool:
    return bool(
        re.search(
            rf"{_label_pattern(actor)}.{{0,100}}\b"
            rf"(?:told|said|mentioned|reported|wrote|"
            rf"сказал(?:а)?|рассказал(?:а)?|упомянул(?:а)?)\b"
            rf".{{0,80}}\b{_LABEL_RE}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _has_other_actor_info_from_source(text: str, *, expected_actor: str) -> bool:
    expected = _normalized_label(expected_actor)
    pattern = re.compile(
        rf"(?P<actor>{_LABEL_RE})(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_INFO_SOURCE_VERB_RE})\b.{{0,160}}\b(?:from|от)\b(?P<tail>.{{0,80}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        actor = _clean_label(match.group("actor"))
        if (
            actor
            and _normalized_label(actor) != expected
            and _source_tail_has_evidence(match.group("tail"))
        ):
            return True
    return False


def _has_info_actor_without_source(text: str, *, actor: str) -> bool:
    return bool(
        re.search(
            rf"{_label_pattern(actor)}.{{0,80}}\b(?:{_INFO_SOURCE_VERB_RE})\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _source_tail_has_evidence(tail: str) -> bool:
    normalized = tail.casefold()
    if re.search(rf"\b{_LABEL_RE}\b", tail):
        return True
    return bool(
        re.search(
            r"\b(?:a|an|the|elderly|veteran|friend|teacher|doctor|mentor|"
            r"colleague|teammate|volunteer|отец|мать|друг|подруга|учитель|"
            r"врач|ментор|коллега)\b",
            normalized,
        )
    )


def _has_actor_borrow_from_source(
    text: str,
    *,
    actor: str,
    context_terms: tuple[str, ...],
) -> bool:
    pattern = re.compile(
        rf"{_label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_BORROW_SOURCE_VERB_RE})\b(?P<body>.{{0,220}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        body = match.group("body")
        if context_terms and not _context_terms_match(body, context_terms):
            continue
        if _borrow_body_has_source(body):
            return True
    return False


def _has_source_lent_to_actor(
    text: str,
    *,
    actor: str,
    context_terms: tuple[str, ...],
) -> bool:
    actor_key = _normalized_label(actor)
    pattern = re.compile(
        rf"(?P<source>{_LABEL_RE})(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_verb_forms('lend')})\b(?P<body>.{{0,220}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        source = _clean_label(match.group("source"))
        if not _looks_like_text_recipient(source):
            continue
        if _normalized_label(source) == actor_key:
            continue
        body = match.group("body")
        if context_terms and not _context_terms_match(body, context_terms):
            continue
        if re.search(_recipient_label_pattern(actor, verb_key="lend"), body, re.IGNORECASE):
            return True
    return False


def _actor_lent_to_other(
    text: str,
    *,
    actor: str,
    context_terms: tuple[str, ...],
) -> bool:
    if context_terms:
        return _has_actor_action_to_any_recipient_with_context(
            text,
            actor=actor,
            verb_key="lend",
            context_terms=context_terms,
        )
    return _has_actor_action_to_any_recipient(text, actor=actor, verb_key="lend")


def _other_borrowed_from_actor(
    text: str,
    *,
    actor: str,
    context_terms: tuple[str, ...],
) -> bool:
    actor_key = _normalized_label(actor)
    pattern = re.compile(
        rf"(?P<borrower>{_LABEL_RE})(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_BORROW_SOURCE_VERB_RE})\b(?P<body>.{{0,220}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        borrower = _clean_label(match.group("borrower"))
        if not _looks_like_text_recipient(borrower):
            continue
        if _normalized_label(borrower) == actor_key:
            continue
        body = match.group("body")
        if context_terms and not _context_terms_match(body, context_terms):
            continue
        if re.search(
            rf"\bfrom\s+{_label_pattern(actor)}\b|{_label_pattern(actor)}(?:'s|s')",
            body,
            re.IGNORECASE | re.DOTALL,
        ):
            return True
    return False


def _has_actor_borrow_without_source(
    text: str,
    *,
    actor: str,
    context_terms: tuple[str, ...],
) -> bool:
    pattern = re.compile(
        rf"{_label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_BORROW_SOURCE_VERB_RE})\b(?P<body>.{{0,160}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        body = match.group("body")
        if context_terms and not _context_terms_match(body, context_terms):
            continue
        if not _borrow_body_has_source(body):
            return True
    return False


def _borrow_body_has_source(body: str) -> bool:
    from_match = re.search(
        rf"\bfrom\s+(?P<source>{_LABEL_RE})\b",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if from_match is not None:
        source = _clean_label(from_match.group("source"))
        if _looks_like_text_recipient(source):
            return True
    possessive_match = re.search(
        rf"\b(?P<source>{_LABEL_RE})(?:'s|s')\b",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if possessive_match is None:
        return False
    source = _clean_label(possessive_match.group("source"))
    return _looks_like_text_recipient(source)


def _has_non_actor_action(text: str, *, expected_actor: str, verb_key: str) -> bool:
    pattern = re.compile(
        rf"(?=\b(?P<actor>{_LABEL_RE})\b(?P<gap>.{{0,80}}?)"
        rf"\b(?:{_verb_forms(verb_key)})\b)",
        re.IGNORECASE | re.DOTALL,
    )
    expected = _normalized_label(expected_actor)
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        actor = _clean_label(match.group("actor"))
        if actor and _normalized_label(actor) != expected:
            return True
    return False


def _has_action_to_recipient(text: str, *, recipient: str, verb_key: str) -> bool:
    recipient_pattern = _recipient_label_pattern(recipient, verb_key=verb_key)
    preposition_match = re.search(
        rf"\b(?:{_verb_forms(verb_key)})\b.{{0,140}}\b(?:to|for)\s+"
        rf"{recipient_pattern}",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if preposition_match is not None and not _action_prefix_blocks_positive_match(
        text,
        preposition_match.start(),
    ):
        return True
    if verb_key in _DIRECT_RECIPIENT_VERBS:
        direct_match = re.search(
            rf"\b(?:{_verb_forms(verb_key)})\b\s+"
            rf"{recipient_pattern}(?P<tail>.{{0,40}})",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if (
            direct_match is not None
            and not _action_prefix_blocks_positive_match(text, direct_match.start())
            and _direct_recipient_context_allows(
                verb_key,
                direct_match.group("tail"),
            )
        ):
            return True
    passive_match = re.search(
        rf"{recipient_pattern}.{{0,100}}\b(?:was|were)\s+"
        rf"(?:{_verb_forms(verb_key)})\b",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if passive_match is not None and not _negated_action_gap(passive_match.group(0)):
        return True
    if verb_key != "recommend":
        return False
    if _has_recommendation_that_recipient_acts(text, recipient=recipient):
        return True
    return bool(
        re.search(
            rf"\b(?:{_russian_recommendation_forms()})\b\s+{recipient_pattern}",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _has_negated_action_to_recipient(
    text: str,
    *,
    recipient: str,
    verb_key: str,
    object_label: str = "",
) -> bool:
    recipient_pattern = _recipient_label_pattern(recipient, verb_key=verb_key)
    target_pattern = (
        rf".{{0,100}}{_role_label_pattern(object_label)}"
        if object_label
        else rf".{{0,140}}(?:to|for)\s+{recipient_pattern}"
    )
    preposition_pattern = re.compile(
        rf"\b(?:{_verb_forms(verb_key)})\b{target_pattern}",
        re.IGNORECASE | re.DOTALL,
    )
    for match in preposition_pattern.finditer(text):
        if _action_prefix_blocks_positive_match(text, match.start()):
            return True
    if verb_key in _DIRECT_RECIPIENT_VERBS:
        direct_pattern = re.compile(
            rf"\b(?:{_verb_forms(verb_key)})\b\s+"
            rf"{recipient_pattern}(?P<tail>.{{0,80}})",
            re.IGNORECASE | re.DOTALL,
        )
        for match in direct_pattern.finditer(text):
            if _action_prefix_blocks_positive_match(
                text,
                match.start(),
            ) and _direct_recipient_context_allows(verb_key, match.group("tail")):
                return True
    passive_pattern = re.compile(
        rf"{recipient_pattern}.{{0,100}}\b(?:was|were)\s+"
        rf"(?:{_verb_forms(verb_key)})\b",
        re.IGNORECASE | re.DOTALL,
    )
    return any(_negated_action_gap(match.group(0)) for match in passive_pattern.finditer(text))


def _recipient_acts_to_other(text: str, *, recipient: str, verb_key: str) -> bool:
    recipient_pattern = _recipient_label_pattern(recipient, verb_key=verb_key)
    pattern = re.compile(
        rf"{recipient_pattern}(?P<gap>.{{0,80}}?)\b(?:{_verb_forms(verb_key)})\b"
        rf".{{0,140}}\b(?:to|for)\s+(?P<other>{_LABEL_RE})\b",
        re.IGNORECASE | re.DOTALL,
    )
    recipient_key = _normalized_label(recipient)
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        other = _clean_label(match.group("other"))
        if (
            other
            and _looks_like_text_recipient(other)
            and _normalized_label(other) != recipient_key
        ):
            return True
    if verb_key in _DIRECT_RECIPIENT_VERBS:
        direct_pattern = re.compile(
            rf"{recipient_pattern}(?P<gap>.{{0,80}}?)\b"
            rf"(?:{_verb_forms(verb_key)})\b\s+"
            rf"(?P<other>{_LABEL_RE})\b(?P<tail>.{{0,40}})",
            re.IGNORECASE | re.DOTALL,
        )
        for match in direct_pattern.finditer(text):
            if _action_gap_blocks_positive_match(match.group("gap")):
                continue
            other = _clean_label(match.group("other"))
            if (
                other
                and _looks_like_text_recipient(other)
                and _normalized_label(other) != recipient_key
                and _direct_recipient_context_allows(verb_key, match.group("tail"))
            ):
                return True
    if verb_key == "recommend":
        that_action_pattern = re.compile(
            rf"{_label_pattern(recipient)}(?P<gap>.{{0,80}}?)"
            rf"\b(?:{_verb_forms(verb_key)})\b.{{0,80}}\b"
            rf"(?:that\s+)?(?P<other>{_LABEL_RE})\s+"
            rf"(?:{_RECIPIENT_FOLLOWUP_ACTION_RE})\b",
            re.IGNORECASE | re.DOTALL,
        )
        for match in that_action_pattern.finditer(text):
            if _action_gap_blocks_positive_match(match.group("gap")):
                continue
            other = _clean_label(match.group("other"))
            if (
                other
                and _looks_like_text_recipient(other)
                and _normalized_label(other) != recipient_key
            ):
                return True
        russian_direct_pattern = re.compile(
            rf"{_label_pattern(recipient)}(?P<gap>.{{0,80}}?)"
            rf"\b(?:{_russian_recommendation_forms()})\b\s+(?P<other>{_LABEL_RE})\b",
            re.IGNORECASE | re.DOTALL,
        )
        for match in russian_direct_pattern.finditer(text):
            if _action_gap_blocks_positive_match(match.group("gap")):
                continue
            other = _clean_label(match.group("other"))
            if (
                other
                and _looks_like_text_recipient(other)
                and _normalized_label(other) != recipient_key
            ):
                return True
    return False


def _has_recommendation_that_recipient_acts(text: str, *, recipient: str) -> bool:
    return bool(
        re.search(
            rf"\b(?:{_verb_forms('recommend')})\b.{{0,100}}\b"
            rf"(?:that\s+)?{_label_pattern(recipient)}\s+"
            rf"(?:{_RECIPIENT_FOLLOWUP_ACTION_RE})\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _canonical_verb_key(value: str) -> str:
    token = value.casefold()
    if token.startswith(("recommend", "suggest", "рекоменд", "порекоменд", "посовет")):
        return "recommend"
    if token.startswith(("introduc", "познаком", "представ")):
        return "introduce"
    if token.startswith(("promise", "пообещ", "обещ")):
        return "promise"
    if token.startswith(("decid", "реш")):
        return "decide"
    if token.startswith(("ask", "спрос")):
        return "ask"
    if token.startswith(("assign", "назнач")):
        return "assign"
    if token.startswith(("approv", "одобр")):
        return "approve"
    if token.startswith(("help", "assist", "support", "помог", "поддерж")):
        return "help"
    if token.startswith("join"):
        return "join"
    if token in {"meet", "met"}:
        return "meet"
    if token.startswith("visit"):
        return "visit"
    if token.startswith("call"):
        return "call"
    if token.startswith(("message", "text")):
        return "message"
    if token in {"send", "sent"}:
        return "send"
    if token in {"give", "gave", "given"}:
        return "give"
    if token in {"lend", "lent"}:
        return "lend"
    if token in {"tell", "told"} or token.startswith("сказ"):
        return "tell"
    return ""


def _canonical_nominal_action(value: str) -> str:
    token = value.casefold()
    if token == "decision":
        return "decide"
    if token == "promise":
        return "promise"
    if token in {"recommendation", "suggestion"}:
        return "recommend"
    return ""


def _recipient_in_tail(tail: str) -> str:
    match = re.search(
        rf"\b(?:to|for)\s+(?P<recipient>{_QUERY_LABEL_RE})\b",
        tail,
        flags=re.IGNORECASE,
    )
    if match is None:
        return ""
    return _clean_label(match.group("recipient"))


def _object_label_in_text(value: str) -> str:
    labels: list[str] = []
    for match in re.finditer(rf"\b(?P<label>{_QUERY_LABEL_RE})\b", value):
        label = _clean_label(match.group("label"))
        if label:
            labels.append(label)
    return labels[-1] if labels else ""


def _action_context_terms(value: str, *, verb_key: str) -> tuple[str, ...]:
    if not value or verb_key == "introduce":
        return ()
    terms: list[str] = []
    for match in re.finditer(r"[A-Za-zА-Яа-яЁё0-9]{3,}", value.casefold()):
        token = match.group(0)
        if token in _ACTION_CONTEXT_STOP_WORDS:
            continue
        if token.startswith((
            "send",
            "sent",
            "tell",
            "told",
            "ask",
            "help",
            "support",
            "join",
            "meet",
            "met",
            "visit",
            "lend",
            "lent",
        )):
            continue
        if token.startswith(("сказ", "спрос", "помог", "поддерж")):
            continue
        if token not in terms:
            terms.append(token)
        if len(terms) >= 6:
            break
    return tuple(terms)


def _context_terms_match(text: str, context_terms: tuple[str, ...]) -> bool:
    if not context_terms:
        return True
    normalized = text.casefold()
    hits = sum(1 for term in context_terms if term in normalized)
    required = min(len(context_terms), 2)
    return hits >= required


def _recipient_after_action(query: str, *, match_end: int, verb_key: str) -> str:
    tail = query[match_end : match_end + 120]
    preposition_match = re.search(
        rf"\b(?:to|for)\s+(?P<recipient>{_QUERY_LABEL_RE})\b",
        tail,
        flags=re.IGNORECASE,
    )
    if preposition_match is not None:
        return _clean_label(preposition_match.group("recipient"))
    if verb_key not in _DIRECT_RECIPIENT_VERBS:
        return ""
    direct_match = re.match(
        rf"\s+(?P<recipient>{_QUERY_LABEL_RE})\b",
        tail,
        flags=re.IGNORECASE,
    )
    if direct_match is None:
        return ""
    recipient = _clean_label(direct_match.group("recipient"))
    if not _looks_like_direct_recipient(recipient):
        return ""
    return recipient


def _verb_forms(verb_key: str) -> str:
    forms = {
        "recommend": (
            r"recommend(?:ed|s|ing)?|suggest(?:ed|s|ing)?|"
            r"made\s+(?:a\s+|the\s+)?(?:recommendation|suggestion)|"
            rf"{_russian_recommendation_forms()}"
        ),
        "introduce": (
            r"introduc(?:e|ed|es|ing)|"
            r"познакомил(?:а|и)?|представил(?:а|и)?"
        ),
        "promise": (
            r"promise(?:d|s|ing)?|made\s+(?:a\s+|the\s+)?promise|"
            r"пообещал(?:а)?|обещал(?:а)?"
        ),
        "decide": r"decid(?:e|ed|es|ing)|made\s+(?:a\s+|the\s+)?decision|решил(?:а)?",
        "ask": r"ask(?:ed|s|ing)?|спросил(?:а)?",
        "assign": r"assign(?:ed|s|ing)?|назначил(?:а)?",
        "approve": r"approv(?:e|ed|es|ing)|одобрил(?:а)?",
        "call": r"call(?:ed|s|ing)?",
        "help": (
            r"help(?:ed|s|ing)?|assist(?:ed|s|ing)?|support(?:ed|s|ing)?|"
            r"помог(?:ла|ли)?|поддержал(?:а|и)?"
        ),
        "join": r"join(?:ed|s|ing)?",
        "meet": r"meet|met",
        "message": r"message(?:d|s|ing)?|text(?:ed|s|ing)?",
        "send": r"send|sent",
        "give": r"give|gave|given",
        "lend": r"lend|lent",
        "tell": r"tell|told|сказал(?:а)?",
        "visit": r"visit(?:ed|s|ing)?",
    }
    return forms.get(verb_key, r"(?!x)x")


def _recipient_preposition_forms(verb_key: str) -> str:
    if verb_key == "introduce":
        return r"to|for|with|с|со"
    return r"to|for"


def _russian_recommendation_forms() -> str:
    return r"рекомендовал(?:а)?|порекомендовал(?:а)?|посоветовал(?:а)?"


def _label_pattern(label: str) -> str:
    return rf"(?<!\w){re.escape(label)}(?!\w)"


def _role_label_pattern(label: str) -> str:
    if not re.search(r"[А-Яа-яЁё]", label):
        return _label_pattern(label)
    stem = _russian_label_stem(label)
    if len(stem) < 3 or stem == label:
        return _label_pattern(label)
    return rf"(?<!\w)(?:{re.escape(label)}|{re.escape(stem)}[А-Яа-яЁё]{{0,4}})(?!\w)"


def _recipient_label_pattern(label: str, *, verb_key: str) -> str:
    if verb_key == "help":
        return _role_label_pattern(label)
    return _label_pattern(label)


def _russian_label_stem(label: str) -> str:
    for suffix in (
        "иями",
        "ями",
        "ами",
        "ого",
        "ему",
        "ыми",
        "ими",
        "ом",
        "ем",
        "ой",
        "ей",
        "ую",
        "ю",
        "а",
        "я",
        "е",
        "ы",
        "и",
    ):
        if label.casefold().endswith(suffix) and len(label) > len(suffix) + 2:
            return label[: -len(suffix)]
    return label


def _clean_label(value: str) -> str:
    label = (value or "").strip(" :,.!?;")
    if not label:
        return ""
    if _normalized_label(label) in _TEXT_LABEL_STOP_WORDS:
        return ""
    return label


def _looks_like_direct_recipient(label: str) -> bool:
    if not label:
        return False
    if label[:1].isupper():
        return True
    return _normalized_label(label) not in _DIRECT_RECIPIENT_OBJECT_STOP_WORDS


def _looks_like_text_recipient(label: str) -> bool:
    return bool(label) and label[:1].isupper() and _looks_like_direct_recipient(label)


def _direct_recipient_context_allows(verb_key: str, tail: str) -> bool:
    normalized = tail.casefold()
    if verb_key in {"ask", "tell"}:
        context_markers = (
            r"about|regarding|whether|if|that|to|why|how|when|where|"
            r"про|что|о|об|почему|как|когда|где"
        )
        if verb_key == "ask":
            context_markers = (
                r"about|regarding|whether|if|that|to|for|why|how|when|where|"
                r"про|что|о|об|почему|как|когда|где"
            )
        return bool(
            re.match(
                rf"\s*(?:{context_markers})\b|\s*[,.;!?]?\s*$",
                normalized,
            )
        )
    if verb_key == "message":
        return bool(
            re.match(
                r"\s*(?:about|regarding|whether|if|that|why|how|when|where|"
                r"про|что|о|об|почему|как|когда|где)\b|\s*[,.;!?]?\s*$",
                normalized,
            )
        )
    if verb_key == "call":
        return bool(
            re.match(
                r"\s*(?:about|regarding|after|before|during|on|at|when|where|"
                r"про|о|об|после|до|во\s+время|когда|где)\b|\s*[,.;!?]?\s*$",
                normalized,
            )
        )
    if verb_key == "introduce":
        return bool(
            re.match(
                r"\s*(?:to|with|for|at|during|after|before|on|in|"
                r"с|со|на|во\s+время|после|до)\b|\s*[,.;!?]?\s*$",
                normalized,
            )
        )
    if verb_key == "help":
        return bool(
            re.match(
                r"\s*(?:with|on|through|during|after|before|about|for|in|at|"
                r"с|со|по|в|на|во\s+время|после|до|про|о|об)\b|\s*[,.;!?]?\s*$",
                normalized,
            )
        )
    if verb_key == "promise":
        return bool(
            re.match(
                r"\s*(?:to|that|he|she|they|we|i|it|would|will|что|он|она|они|мы)\b",
                normalized,
            )
        )
    return True


def _normalized_label(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())

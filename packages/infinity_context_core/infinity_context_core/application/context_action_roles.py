"""Role-sensitive action matching for deterministic memory reranking."""

from __future__ import annotations

import re
from dataclasses import dataclass

import infinity_context_core.application.context_action_role_evidence as _action_role_evidence
import infinity_context_core.application.context_action_role_labels as _action_role_labels

_LABEL_RE = _action_role_labels.LABEL_RE
_QUERY_LABEL_RE = _action_role_labels.QUERY_LABEL_RE
_ACTION_VERB_RE = (
    r"recommend(?:ed|s|ing)?|suggest(?:ed|s|ing)?|"
    r"promise(?:d|s|ing)?|decid(?:e|ed|es|ing)|"
    r"ask(?:ed|s|ing)?|assign(?:ed|s|ing)?|approv(?:e|ed|es|ing)|"
    r"call(?:ed|s|ing)?|message(?:d|s|ing)?|text(?:ed|s|ing)?|"
    r"help(?:ed|s|ing)?|assist(?:ed|s|ing)?|support(?:ed|s|ing)?|"
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
    r"introduc(?:e|ed|es|ing)|send|sent|give|gave|lend|lent|tell|told|"
    r"пообещал(?:а)?|обещал(?:а)?|спросил(?:а)?|назначил(?:а)?|"
    r"сказал(?:а)?|познакомил(?:а|и)?|представил(?:а|и)?|"
    r"помог(?:ла|ли)?|поддержал(?:а|и)?"
)
_PASSIVE_ACTION_VERB_RE = (
    r"recommended|suggested|promised|asked|assigned|approved|"
    r"called|messaged|texted|helped|assisted|supported|introduced|sent|given|lent|told"
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
_ACTION_ROLE_MATCH_BOOST = 0.024
_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST = 0.021
_ACTION_ROLE_ACTOR_MATCH_BOOST = 0.018
_ACTION_ROLE_RECIPIENT_MATCH_BOOST = 0.016
_ACTION_ROLE_OWNER_EVIDENCE_BOOST = 0.014
_ACTION_ROLE_MISMATCH_PENALTY = 0.034
_ACTION_ROLE_RECIPIENT_MISMATCH_PENALTY = 0.028
_ACTION_ROLE_REQUESTED_RECIPIENT_MISSING_PENALTY = 0.014
_DIRECT_RECIPIENT_VERBS = frozenset(
    {
        "ask",
        "assign",
        "call",
        "give",
        "help",
        "introduce",
        "lend",
        "message",
        "promise",
        "send",
        "tell",
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
        owner = _action_role_labels.clean_label(
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
            recipient = _action_role_labels.clean_label(match.group("recipient"))
            if recipient:
                return _ActionRoleQuery(
                    verb_key="support_presence",
                    recipient_label=recipient,
                )

    for pattern in (_WHO_TO_ACTION_RE, _RU_WHO_OBJECT_TO_ACTION_RE):
        match = pattern.search(query)
        if match is not None:
            verb_key = _canonical_verb_key(match.group("verb"))
            if pattern is _RU_WHO_OBJECT_TO_ACTION_RE and verb_key != "introduce":
                continue
            recipient = _action_role_labels.clean_label(match.group("recipient"))
            object_label = _action_role_labels.object_label_in_text(match.group("object") or "")
            if verb_key and recipient:
                return _ActionRoleQuery(
                    verb_key=verb_key,
                    recipient_label=recipient,
                    object_label=object_label if verb_key == "introduce" else "",
                )

    match = _WHOSE_SUGGESTION_QUERY_RE.search(query)
    if match is not None:
        recipient = _action_role_labels.clean_label(match.group("recipient"))
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
            recipient = _action_role_labels.clean_label(match.group("recipient"))
            if recipient:
                return _ActionRoleQuery(
                    verb_key="recommend",
                    recipient_label=recipient,
                )

    match = _WHO_RECOMMENDED_THAT_RECIPIENT_QUERY_RE.search(query)
    if match is not None:
        recipient = _action_role_labels.clean_label(match.group("recipient"))
        if recipient:
            return _ActionRoleQuery(
                verb_key="recommend",
                recipient_label=recipient,
            )

    match = _WHAT_DID_ACTOR_RECOMMEND_RECIPIENT_ACTION_QUERY_RE.search(query)
    if match is not None:
        actor = _action_role_labels.clean_label(match.group("actor"))
        recipient = _action_role_labels.clean_label(match.group("recipient"))
        if actor and recipient:
            return _ActionRoleQuery(
                verb_key="recommend",
                actor_label=actor,
                recipient_label=recipient,
            )

    match = _RU_WHO_DIRECT_RECOMMENDATION_QUERY_RE.search(query)
    if match is not None:
        recipient = _action_role_labels.clean_label(match.group("recipient"))
        if recipient:
            return _ActionRoleQuery(
                verb_key="recommend",
                recipient_label=recipient,
            )

    match = _RU_WHOSE_SUGGESTION_QUERY_RE.search(query)
    if match is not None:
        recipient = _action_role_labels.clean_label(match.group("recipient"))
        if recipient:
            return _ActionRoleQuery(
                verb_key="recommend",
                recipient_label=recipient,
            )

    for pattern in (
        _WHO_DIRECT_RECIPIENT_ACTION_QUERY_RE,
        _RU_WHO_DIRECT_RECIPIENT_ACTION_QUERY_RE,
    ):
        match = pattern.search(query)
        if match is not None:
            verb_key = _canonical_verb_key(match.group("verb"))
            recipient = _action_role_labels.clean_label(match.group("recipient"))
            if verb_key and recipient:
                return _ActionRoleQuery(verb_key=verb_key, recipient_label=recipient)

    for pattern in (
        _SUGGESTION_SOURCE_QUERY_RE,
        _RECIPIENT_AFTER_ACTOR_RECOMMENDATION_QUERY_RE,
    ):
        match = pattern.search(query)
        if match is not None:
            actor = _action_role_labels.clean_label(match.group("actor"))
            recipient = _action_role_labels.clean_label(match.group("recipient"))
            if actor and recipient:
                return _ActionRoleQuery(
                    verb_key="recommend",
                    actor_label=actor,
                    recipient_label=recipient,
                )

    match = _WHO_WAS_ACTIONED_BY_ACTOR_QUERY_RE.search(query)
    if match is not None:
        actor = _action_role_labels.clean_label(match.group("actor"))
        verb_key = _canonical_verb_key(match.group("verb"))
        if actor and verb_key:
            return _ActionRoleQuery(
                verb_key=verb_key,
                actor_label=actor,
                recipient_requested=True,
            )

    match = _WHO_WAS_RECIPIENT_ACTIONED_BY_QUERY_RE.search(query)
    if match is not None:
        recipient = _action_role_labels.clean_label(match.group("recipient"))
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
            actor = _action_role_labels.clean_label(match.group("actor"))
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
            actor = _action_role_labels.clean_label(match.group("actor"))
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
            actor = _action_role_labels.clean_label(match.group("actor"))
            verb_key = _canonical_verb_key(match.group("verb"))
            object_label = _action_role_labels.object_label_in_text(
                match.groupdict().get("object") or ""
            )
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
        actor = _action_role_labels.clean_label(match.group("actor"))
        verb_key = _canonical_nominal_action(match.group("noun"))
        recipient = _action_role_labels.recipient_in_tail(match.group("tail") or "")
        if actor and verb_key:
            return _ActionRoleQuery(
                verb_key=verb_key,
                actor_label=actor,
                recipient_label=recipient,
            )

    match = _QUESTION_ACTION_RE.search(query)
    if match is None:
        return None
    actor = _action_role_labels.clean_label(match.group("actor"))
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
    if _action_role_evidence._has_negated_actor_action(
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
        and _action_role_evidence._has_ordered_action_object_to_recipient(
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
        and _action_role_evidence._has_ordered_action_object_to_recipient(
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
    if recipient and _action_role_evidence._has_ordered_action(
        text,
        actor=actor,
        verb_key=verb_key,
        target=recipient,
    ):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_MATCH_BOOST,
            reason="action_role_actor_recipient_match",
        )
    if recipient and _action_role_evidence._has_ordered_action(
        text,
        actor=recipient,
        verb_key=verb_key,
        target=actor,
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_MISMATCH_PENALTY,
            reason="action_role_actor_recipient_reversed",
        )
    if object_label and role_query.recipient_requested:
        if _action_role_evidence._has_actor_action_object_to_any_recipient(
            text,
            actor=actor,
            verb_key=verb_key,
            object_label=object_label,
        ):
            return ActionRoleRerankSignal(
                boost=_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST,
                reason="action_role_actor_to_recipient_evidence",
            )
        if _action_role_evidence._has_actor_action(text, actor=actor, verb_key=verb_key):
            return ActionRoleRerankSignal(
                penalty=_ACTION_ROLE_REQUESTED_RECIPIENT_MISSING_PENALTY,
                reason="action_role_requested_recipient_missing",
            )
    if context_terms and role_query.recipient_requested:
        if _action_role_evidence._has_actor_action_to_any_recipient_with_context(
            text,
            actor=actor,
            verb_key=verb_key,
            context_terms=context_terms,
        ):
            return ActionRoleRerankSignal(
                boost=_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST,
                reason="action_role_actor_to_recipient_evidence",
            )
        if _action_role_evidence._has_actor_action_to_any_recipient(
            text,
            actor=actor,
            verb_key=verb_key,
        ):
            return ActionRoleRerankSignal(
                penalty=_ACTION_ROLE_REQUESTED_RECIPIENT_MISSING_PENALTY,
                reason="action_role_requested_context_mismatch",
            )
    if role_query.recipient_requested and _action_role_evidence._has_actor_action_to_any_recipient(
        text,
        actor=actor,
        verb_key=verb_key,
    ):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST,
            reason="action_role_actor_to_recipient_evidence",
        )
    if _action_role_evidence._has_actor_action(text, actor=actor, verb_key=verb_key):
        if role_query.recipient_requested:
            return ActionRoleRerankSignal(
                penalty=_ACTION_ROLE_REQUESTED_RECIPIENT_MISSING_PENALTY,
                reason="action_role_requested_recipient_missing",
            )
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_ACTOR_MATCH_BOOST,
            reason="action_role_actor_match",
        )
    if _action_role_evidence._has_non_actor_action(text, expected_actor=actor, verb_key=verb_key):
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
    if _action_role_evidence._has_negated_action_to_recipient(
        text,
        recipient=recipient,
        verb_key=verb_key,
        object_label=object_label,
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_RECIPIENT_MISMATCH_PENALTY,
            reason="action_role_negated_evidence",
        )
    if object_label and _action_role_evidence._has_ordered_action_object_to_recipient(
        text,
        verb_key=verb_key,
        object_label=object_label,
        recipient=recipient,
    ):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_RECIPIENT_MATCH_BOOST,
            reason="action_role_recipient_match",
        )
    if object_label and _action_role_evidence._has_ordered_action_object_to_recipient(
        text,
        verb_key=verb_key,
        object_label=recipient,
        recipient=object_label,
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_RECIPIENT_MISMATCH_PENALTY,
            reason="action_role_recipient_mismatch",
        )
    if _action_role_evidence._has_action_to_recipient(text, recipient=recipient, verb_key=verb_key):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_RECIPIENT_MATCH_BOOST,
            reason="action_role_recipient_match",
        )
    if _action_role_evidence._recipient_acts_to_other(text, recipient=recipient, verb_key=verb_key):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_RECIPIENT_MISMATCH_PENALTY,
            reason="action_role_recipient_mismatch",
        )
    return ActionRoleRerankSignal()


def _support_presence_signal(*, recipient: str, text: str) -> ActionRoleRerankSignal:
    if _action_role_evidence._has_negated_support_presence_for_recipient(text, recipient=recipient):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_RECIPIENT_MISMATCH_PENALTY,
            reason="action_role_negated_evidence",
        )
    if _action_role_evidence._has_support_presence_for_recipient(text, recipient=recipient):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_RECIPIENT_MATCH_BOOST,
            reason="action_role_recipient_match",
        )
    if _action_role_evidence._recipient_present_for_other(text, recipient=recipient):
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
    if _action_role_evidence._has_actor_info_from_any_source(
        text,
        actor=actor,
    ) or _action_role_evidence._has_source_told_actor(text, actor=actor):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST,
            reason="action_role_information_source_evidence",
        )
    if _action_role_evidence._actor_tells_other(
        text,
        actor=actor,
    ) or _action_role_evidence._has_other_actor_info_from_source(
        text,
        expected_actor=actor,
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_MISMATCH_PENALTY,
            reason="action_role_information_source_reversed",
        )
    if _action_role_evidence._has_info_actor_without_source(text, actor=actor):
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
    if _action_role_evidence._has_actor_borrow_from_source(
        text,
        actor=actor,
        context_terms=context_terms,
    ) or _action_role_evidence._has_source_lent_to_actor(
        text,
        actor=actor,
        context_terms=context_terms,
    ):
        return ActionRoleRerankSignal(
            boost=_ACTION_ROLE_REQUESTED_RECIPIENT_EVIDENCE_BOOST,
            reason="action_role_transfer_source_evidence",
        )
    if _action_role_evidence._actor_lent_to_other(
        text,
        actor=actor,
        context_terms=context_terms,
    ) or _action_role_evidence._other_borrowed_from_actor(
        text,
        actor=actor,
        context_terms=context_terms,
    ):
        return ActionRoleRerankSignal(
            penalty=_ACTION_ROLE_MISMATCH_PENALTY,
            reason="action_role_transfer_source_reversed",
        )
    if _action_role_evidence._has_actor_borrow_without_source(
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
        if _action_role_evidence._owner_labels_in_text(text):
            return ActionRoleRerankSignal(
                boost=_ACTION_ROLE_OWNER_EVIDENCE_BOOST,
                reason="action_role_owner_evidence",
            )
        return ActionRoleRerankSignal()
    owner_key = _action_role_labels.normalized_label(owner)
    owner_labels = {
        _action_role_labels.normalized_label(label)
        for label in _action_role_evidence._owner_labels_in_text(text)
    }
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


def _action_context_terms(value: str, *, verb_key: str) -> tuple[str, ...]:
    if not value or verb_key == "introduce":
        return ()
    terms: list[str] = []
    for match in re.finditer(r"[A-Za-zА-Яа-яЁё0-9]{3,}", value.casefold()):
        token = match.group(0)
        if token in _ACTION_CONTEXT_STOP_WORDS:
            continue
        if token.startswith(
            ("send", "sent", "tell", "told", "ask", "help", "support", "lend", "lent")
        ):
            continue
        if token.startswith(("сказ", "спрос", "помог", "поддерж")):
            continue
        if token not in terms:
            terms.append(token)
        if len(terms) >= 6:
            break
    return tuple(terms)


def _recipient_after_action(query: str, *, match_end: int, verb_key: str) -> str:
    tail = query[match_end : match_end + 120]
    preposition_match = re.search(
        rf"\b(?:to|for)\s+(?P<recipient>{_QUERY_LABEL_RE})\b",
        tail,
        flags=re.IGNORECASE,
    )
    if preposition_match is not None:
        return _action_role_labels.clean_label(preposition_match.group("recipient"))
    if verb_key not in _DIRECT_RECIPIENT_VERBS:
        return ""
    direct_match = re.match(
        rf"\s+(?P<recipient>{_QUERY_LABEL_RE})\b",
        tail,
        flags=re.IGNORECASE,
    )
    if direct_match is None:
        return ""
    recipient = _action_role_labels.clean_label(direct_match.group("recipient"))
    if not _action_role_labels.looks_like_direct_recipient(recipient):
        return ""
    return recipient

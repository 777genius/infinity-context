"""Benchmark-owned event patterns policy."""

from __future__ import annotations

import re

from infinity_context_benchmarks.retrieval_intent.contracts import (
    RetrievalRelationIntent,
    RetrievalTimeIntent,
)


def _has_causal_support_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
    multi_hop_markers: tuple[str, ...],
    time_intent: RetrievalTimeIntent,
) -> bool:
    relation_set = set(relation_terms)
    marker_set = set(multi_hop_markers)
    if _has_direct_emotion_response_intent(
        question=question,
        relation_terms=relation_terms,
    ):
        return False
    normalized = " ".join(str(question or "").casefold().split())
    if "motivation" in relation_set and _has_motivation_artifact_lookup(normalized):
        return False
    if {"why"} & marker_set:
        return True
    if not time_intent.is_temporal and ({"how"} & marker_set or {"how"} & relation_set):
        return True
    if "prompt" in relation_set and re.search(
        r"\bprompt(?:ed|ing)?\b.+\b(?:to|into)\b"
        r"|\bthat\s+prompt(?:ed|ing)?\b",
        normalized,
    ):
        return True
    direct_causal_terms = {
        "because",
        "caus",
        "cause",
        "inspir",
        "motivat",
        "motivate",
        "realize",
        "reason",
        "why",
    }
    if direct_causal_terms & relation_set:
        return True
    if "motivation" not in relation_set:
        return False
    return bool(
        re.search(
            r"\bwhat\s+(?:is|was)\b.+\bmotivation\s+for\s+"
            r"(?:chang|changing|creat|creating|get|getting|keep|keeping|"
            r"leav|leaving|mak|making|pursu|pursuing|runn|running|"
            r"tak|taking|writ|writing)\b",
            normalized,
        )
        or re.search(
            r"\b(?:boost|boosts|boosted|boosting|keep|keeping|stay|staying)\b"
            r".+\bmotivation\b",
            normalized,
        )
    )


def _has_adoption_reaction_intent(*, relation_terms: tuple[str, ...]) -> bool:
    return {"think", "decision", "adopt"}.issubset(set(relation_terms))


def _has_motivation_artifact_lookup(normalized_question: str) -> bool:
    return bool(
        normalized_question
        and re.search(
            r"\b(?:displayed|shown|wrote|written|quote|quotes|plaque|board|"
            r"cork\s+board|whiteboard|journal|spread|schedule)\b"
            r".+\bmotivation(?:al)?\b"
            r"|\bmotivation(?:al)?\b.+"
            r"\b(?:quote|quotes|plaque|board|cork\s+board|whiteboard|"
            r"journal|spread|schedule)\b",
            normalized_question,
        )
    )


def _has_location_transition_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if (
        not {
            "grow",
            "based",
            "live",
            "move",
            "origin",
            "relocate",
            "relocated",
            "roadtrip",
            "camp",
            "employment",
            "travel",
            "trip",
            "venue",
            "visit",
            "stay",
            "attend",
        }
        & relation_set
    ):
        return False
    normalized = " ".join(str(question or "").casefold().split())
    if (
        "employment" in relation_set
        and not (
            relation_set
            & {
                "based",
                "live",
                "move",
                "origin",
                "relocate",
                "relocated",
                "stay",
                "travel",
                "trip",
                "visit",
            }
        )
        and not re.search(
            r"\b(?:which\s+(?:city|country|place)|what\s+place)\b"
            r".+\b(?:work|worked|working)\b|"
            r"\b(?:work|worked|working)\b.+"
            r"\b(?:which\s+(?:city|country|place)|what\s+place)\b",
            normalized,
        )
    ):
        return False
    if not normalized:
        return False
    if _has_future_home_move_goal_intent(normalized):
        return False
    if re.search(
        r"\b(?:move|moved|moving|relocate|relocated)\s+"
        r"(?:the\s+)?(?:meeting|call|note|document|file|deadline|appointment|"
        r"task|ticket|event|conversation)\b",
        normalized,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:where|which\s+(?:city|country|place)|from|origin|"
            r"what\s+(?:type\s+of\s+|kind\s+of\s+)?(?:place|venue)|"
            r"home\s+country|hometown|born|raised|"
            r"childhood|originally|relocat(?:e|ed|ion)|"
            r"current\s+(?:city|home|location))\b",
            normalized,
        )
        or re.search(
            r"\b(?:move|moved|moving|relocate|relocated|live|lived|living|based|"
            r"stay|stayed|staying|grow|grew|camp|camped|camping|travel|"
            r"traveled|travelled|traveling|travelling|visit|visited|visiting|"
            r"attend|attended|attending)\s+"
            r"(?:from|in|at|near|around|up\b)",
            normalized,
        )
        or re.search(
            r"\b(?:where|which\s+(?:place|venue)|what\s+(?:place|venue))\b"
            r".+\b(?:attend|attended|attending)\b|"
            r"\b(?:attend|attended|attending)\b.+"
            r"\b(?:where|which\s+(?:place|venue)|what\s+(?:place|venue))\b",
            normalized,
        )
        or re.search(
            r"\b(?:where|which\s+(?:city|country|place)|what\s+place)\b"
            r".+\b(?:work|worked|working)\b|"
            r"\b(?:work|worked|working)\b.+"
            r"\b(?:where|which\s+(?:city|country|place)|what\s+place)\b",
            normalized,
        )
    )


def _has_current_goal_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if not {"want", "plan"} & set(relation_terms):
        return False
    normalized = " ".join(str(question or "").casefold().split())
    if re.search(r"\b(?:if|hadn t|had not)\b", normalized):
        return False
    if re.search(r"\b(?:cancel(?:ed|led|s)?|reschedul(?:e|ed|es|ing)?)\b", normalized):
        return False
    if "plan" in set(relation_terms) and re.search(
        r"\b(?:plan|plans|planned|planning)\b",
        normalized,
    ):
        return True
    if "want" in set(relation_terms) and re.search(
        r"\b(?:want|wants|wanted|wanting)\s+to\s+"
        r"(?:create|build|make|teach|keep|expand|move|meet|work|go|do|try|"
        r"share|learn|pursue|start|open|organize|visit|live)\b",
        normalized,
    ):
        return True
    return bool(
        normalized
        and (
            _has_future_home_move_goal_intent(normalized)
            or re.search(r"\b(?:current\s+goal|future|soon)\b", normalized)
        )
    )


def _has_support_goal_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if (
        not {
            "adopt",
            "adoption",
            "agency",
            "career",
            "counsel",
            "field",
            "grow",
            "help",
            "path",
            "pursue",
            "receive",
            "support",
            "work",
            "write",
        }
        & relation_set
    ):
        return False
    normalized_question = " ".join(str(question or "").casefold().split())
    if re.search(
        r"\b(?:different|difference|compare|compared|before|former|previous)\b",
        normalized_question,
    ):
        return False
    if _has_direct_support_role_question(normalized_question):
        return True
    return bool(
        normalized_question
        and (
            re.search(
                r"\b(?:support|supported|growing\s+up|"
                r"adoption\s+agency|agency\b.+\bsupport|support\b.+\bagency)\b",
                normalized_question,
            )
            or re.search(
                r"\bhelp(?:ed|ing)?\s+(?:children|kids|people|others|students|"
                r"community|individuals|folks)\b",
                normalized_question,
            )
            or re.search(
                r"\b(?:career|field|path|profession|work|job|write|writing|"
                r"counsel(?:ing|or)?|pursue)\b",
                normalized_question,
            )
        )
    )


def _has_community_membership_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    normalized_question = " ".join(str(question or "").casefold().split())
    relation_set = set(relation_terms)
    membership_terms = {
        "belong",
        "belongs",
        "identified",
        "identifies",
        "identify",
        "member",
        "membership",
        "part",
    }
    community_terms = {
        "community",
        "lgbt",
        "lgbtq",
        "queer",
        "trans",
        "transgender",
    }
    return bool(
        membership_terms & relation_set
        and community_terms & relation_set
        and not re.search(
            r"\b(?:ally|supportive|supporting)\b",
            normalized_question,
        )
    )


def _is_direct_support_relation_intent(intent: RetrievalRelationIntent) -> bool:
    return "direct_support_question" in set(intent.reason_codes)


def _has_direct_support_role_question(normalized_question: str) -> bool:
    support_action = r"(?:help(?:ed|ing)?|assist(?:ed|ing)?|support(?:s|ed|ing)?)"
    return bool(
        re.search(
            rf"\b(?:who|whom)\b.+\b{support_action}\b",
            normalized_question,
        )
        or re.search(
            r"\bhow\b.+\b(?:get|got|receive|received|find|found)\b.+\bsupport\b"
            r".+\b(?:after|through|when|with|from)\b",
            normalized_question,
        )
        or re.search(
            rf"\b{support_action}\b.+\b(?:after|through|when|with)\b",
            normalized_question,
        )
    )


def _has_future_home_move_goal_intent(normalized_question: str) -> bool:
    if re.search(r"\b(?:where|which\s+(?:city|country|place)|from|origin)\b", normalized_question):
        return False
    return bool(
        re.search(r"\b(?:would|want|wants|wanted|hope|hoping|plan|plans)\b", normalized_question)
        and re.search(r"\bmove\s+back\b", normalized_question)
        and re.search(r"\bhome\s+country\b", normalized_question)
    )


def _has_inference_support_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
    benchmark_category: int | None,
) -> bool:
    if benchmark_category == 3:
        return True
    relation_set = set(relation_terms)
    if {"relationship", "status"}.issubset(relation_set):
        return True
    if "decision" in relation_set:
        return True
    normalized = " ".join(str(question or "").casefold().split())
    return bool(re.search(r"\b(?:would|likely|might|could)\b", normalized) and relation_set)


def _has_action_event_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "action" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\bwhat\s+did\b.+\b(?:"
            r"bring|brought|take|took|send|sent|share|shared|paint|painted|"
            r"draw|drew|make|made|book|booked|schedule|scheduled|prepare|prepared|"
            r"complete|completed|fix|fixed|repair|repaired|create|created"
            r")\b",
            normalized_question,
        )
    )


def _has_exchange_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    exchange_terms = {
        "bought",
        "bring",
        "brought",
        "give",
        "get",
        "got",
        "gift",
        "offer",
        "purchas",
        "purchase",
        "receive",
    }
    if not exchange_terms & relation_set:
        return False
    if "give" in relation_set and {"school", "speech", "talk", "presentation"} & relation_set:
        return False
    if {"support", "grow", "counsel", "help"} & relation_set and {
        "get",
        "got",
        "receive",
    } & relation_set:
        return False
    if {"get", "got"} & relation_set:
        normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
        return bool(
            re.search(
                r"\b(?:what|which)(?:\s+\w+){0,3}\s+"
                r"(?:did|do|does|had|has|have|will|would|could|should)\b"
                r".+\b(?:get|got)\b",
                normalized_question,
            )
            or re.search(r"\b(?:get|got)\b.+\bfrom\b", normalized_question)
        )
    return True


def _has_participation_event_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if (
        not {
            "attend",
            "join",
            "meet",
            "participate",
            "travel",
            "visit",
        }
        & relation_set
    ):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if "meet" in relation_set:
        if re.search(
            r"\bmeet(?:ing)?\s+(?:agenda|notes|minutes|summary)\b|"
            r"\bmeet\s+"
            r"(?:expectation|expectations|goal|goals|requirement|requirements)\b",
            normalized_question,
        ):
            return False
        return bool(
            re.search(
                r"\b(?:who|when|where)\b.+\bmeet\b|"
                r"\bmeet\s+up\b|\bmet\s+(?:with|up)\b|"
                r"\bmeeting\s+with\b|\bmeet(?:ing)?\b.+\b(?:friend|family|mentor|"
                r"colleague|coworker|team|group)\b",
                normalized_question,
            )
        )
    if "travel" not in relation_set:
        return True
    if re.search(
        r"\btravel\s+(?:book|guide|story|documentary|show)\b",
        normalized_question,
    ):
        return False
    return bool(
        re.search(
            r"\bwhere\b.+\btravel\b|\btravel(?:ed|ing)?\s+to\b|"
            r"\b(?:what|which)\s+(?:country|city|place)\b.+\btravel\b|"
            r"\b(?:trip|vacation)\b",
            normalized_question,
        )
    )


def _has_communication_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if {
        "advise",
        "ask",
        "invit",
        "invitation",
        "invite",
        "recommend",
        "remind",
        "reminded",
        "request",
        "suggest",
        "tell",
        "told",
        "warn",
        "warned",
    } & relation_set:
        return True
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if {"chat", "discus", "discuss", "talk"} & relation_set:
        if re.search(
            r"\bwhy\b.+\b(?:after|before|while)\s+"
            r"(?:chat(?:ted|ting)?|discuss(?:ed|ing)?|talk(?:ed|ing)?)\b",
            normalized_question,
        ):
            return False
        if re.search(
            r"\b(?:give|gave|giving|present|presented|presentation|speech)\b"
            r".{0,40}\b(?:talk|discussion)\b"
            r"|\b(?:talk|discussion)\b.{0,40}\b(?:school|speech|event|presentation)\b",
            normalized_question,
        ):
            return False
        return bool(
            re.search(
                r"\b(?:who|whom|what)\b.+\b(?:chat|discuss|talk)\b",
                normalized_question,
            )
            or re.search(
                r"\b(?:chat|discuss|talk)(?:ed|ing)?\b.+\b(?:about|to|with)\b",
                normalized_question,
            )
        )
    if {"call", "message", "messag", "send", "sent", "text"} & relation_set:
        if "call" in relation_set and {"miss", "missed"} & relation_set:
            return False
        if re.search(r"\bwhat\s+did\b.+\bcall\b(?!.*\b(?:about|to|with)\b)", normalized_question):
            return False
        return bool(
            re.search(
                r"\b(?:who|whom|when)\b.+\b(?:call|message|send|sent|text)\b",
                normalized_question,
            )
            or re.search(
                r"\b(?:call|message|messag|send|sent|text)(?:ed|ing)?\b"
                r".+\b(?:about|to|with)\b",
                normalized_question,
            )
        )
    if {"say", "said"} & relation_set:
        if {"personality", "trait"} & relation_set:
            return False
        if re.search(
            r"\b(?:what|which)\s+(?:do|does|did)\s+(?:the\s+)?"
            r"(?:book|card|document|label|letter|note|sign|text)\s+"
            r"(?:say|said)\b",
            normalized_question,
        ):
            return False
        return bool(
            re.search(r"\b(?:what|who|whom)\b.+\b(?:say|said)\b", normalized_question)
            or re.search(
                r"\b(?:say|said)\b.+\b(?:about|that|to|with)\b",
                normalized_question,
            )
        )
    if "mention" not in relation_set:
        return False
    return bool(
        re.search(
            r"\b(?:who|whom)\b.+\bmention\b|\bmention(?:ed)?\b.+\b(?:to|with)\b",
            normalized_question,
        )
    )


def _has_direct_emotion_response_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if not {"excite", "feel"} & relation_set:
        return False
    if {"cause", "decide", "decision", "realize", "think", "why"} & relation_set:
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if re.search(r"\bwhy\b|\bwhat\s+(?:made|caused)\b", normalized_question):
        return False
    return bool(
        re.search(r"\bhow\b.+\b(?:feel|feeling|felt)\b", normalized_question)
        or re.search(r"\bwhat\b.+\bexcited\b", normalized_question)
    )

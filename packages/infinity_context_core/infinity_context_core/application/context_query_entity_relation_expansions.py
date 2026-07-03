"""Entity relation inventory query expansion rules."""

from __future__ import annotations

import re

_ENTITY_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,4}"
)
_ENTITY_KIND_RE = (
    r"project|company|organization|organisation|org|team|client|customer|vendor|"
    r"partner|event|meeting|call"
)
_RU_ENTITY_KIND_RE = (
    r"проект(?:а|у|ом)?|компан(?:ия|ию|ии)|организац(?:ия|ию|ии)|"
    r"команд(?:а|у|ы)|клиент(?:а|у|ом)?|заказчик(?:а|у|ом)?|"
    r"вендор(?:а|у|ом)?|партн[её]р(?:а|у|ом)?|событи(?:е|я|ю|ем)|"
    r"встреч(?:а|у|и|е)|созвон(?:а|у|ом)?"
)

_ENTITY_RELATION_INVENTORY_EXPANSION = (
    "people persons stakeholders contacts owners participants collaborators involved "
    "connected related linked associated relationship relation anchor graph project "
    "organization event meeting call decision owner assignee evidence source of truth"
)
_PERSON_RELATION_INVENTORY_EXPANSION = (
    "people persons friends family relatives coworkers colleagues teammates team "
    "manager mentor boss supervisor coach trainer teacher tutor classmate schoolmate "
    "roommate neighbor neighbour doctor dentist therapist counselor partner spouse "
    "sibling parent child brother sister mother father husband wife connected related "
    "linked associated relationship relation works with worked with knows met evidence"
)
_PERSON_TEAM_MEMBERSHIP_EXPANSION = (
    "team club group member membership teammates team members joined part of "
    "belongs to roster crew organization people evidence"
)
_RU_ENTITY_RELATION_INVENTORY_EXPANSION = (
    "люди участники контакты стейкхолдеры заинтересованные ответственные владельцы "
    "связаны относится отношение связь граф проект организация событие встреча созвон "
    "решение владелец исполнитель evidence source of truth"
)
_RU_PERSON_RELATION_INVENTORY_EXPANSION = (
    "люди друзья семья родственники коллеги команда напарники руководитель наставник "
    "партнер супруг брат сестра родитель ребенок связаны отношения работает с "
    "знакомы встретились evidence"
)

_ENTITY_RELATION_INVENTORY_QUERY_RE = re.compile(
    rf"\bwho\s+(?:is|are|was|were)\s+(?:connected|related|linked|associated)\s+"
    rf"(?:to|with)\s+(?:(?:{_ENTITY_KIND_RE})\s+)?{_ENTITY_LABEL_RE}\b|"
    rf"\b(?:which|what)\s+(?:people|persons|stakeholders|contacts|owners|"
    rf"participants|collaborators)\s+(?:are|were)?\s*"
    rf"(?:connected|related|linked|associated|involved)?\s*"
    rf"(?:to|with|in|on|for)\s+(?:(?:{_ENTITY_KIND_RE})\s+)?{_ENTITY_LABEL_RE}\b|"
    rf"\bwho\s+(?:is|are|was|were)\s+(?:involved|participating|working)\s+"
    rf"(?:in|on|with)\s+(?:(?:{_ENTITY_KIND_RE})\s+)?{_ENTITY_LABEL_RE}\b|"
    rf"\bwho\s+(?:are|were)\s+(?:the\s+)?(?:stakeholders|contacts|owners|"
    rf"participants|collaborators)\s+(?:for|on|in)\s+"
    rf"(?:(?:{_ENTITY_KIND_RE})\s+)?{_ENTITY_LABEL_RE}\b",
    re.IGNORECASE,
)
_RU_ENTITY_RELATION_INVENTORY_QUERY_RE = re.compile(
    rf"\bкто\s+(?:связан|связана|связаны|относится|участвует|вовлеч[её]н\w*)\s+"
    rf"(?:с|со|в|во|к|ко|по)\s+(?:(?:{_RU_ENTITY_KIND_RE})\s+)?{_ENTITY_LABEL_RE}\b|"
    rf"\b(?:какие|кто)\s+(?:люди|участники|контакты|стейкхолдеры|"
    rf"заинтересованные|ответственные)\s+"
    rf"(?:связаны|участвуют|вовлечены|относятся)?\s*"
    rf"(?:с|со|в|во|к|ко|по)\s+(?:(?:{_RU_ENTITY_KIND_RE})\s+)?{_ENTITY_LABEL_RE}\b|"
    rf"\b(?:контакты|участники|стейкхолдеры|ответственные)\s+"
    rf"(?:по|для|в)\s+(?:(?:{_RU_ENTITY_KIND_RE})\s+)?{_ENTITY_LABEL_RE}\b",
    re.IGNORECASE,
)
_PERSON_RELATION_INVENTORY_QUERY_RE = re.compile(
    rf"\bwho\s+(?:works?|worked|collaborates?|collaborated|partners?|partnered)\s+"
    rf"(?:with|alongside)\s+{_ENTITY_LABEL_RE}\b|"
    rf"\bwho\s+(?:are|were|is|was)\s+{_ENTITY_LABEL_RE}(?:'s|s')?\s+"
    rf"(?:friends?|family|relatives?|coworkers?|co-workers?|colleagues?|"
    rf"teammates?|team\s+members?|managers?|mentors?|boss|bosses|"
    rf"supervisors?|coach(?:es)?|trainers?|teachers?|tutors?|classmates?|"
    rf"schoolmates?|"
    rf"roommates?|neighbors?|neighbours?|doctors?|dentists?|therapists?|"
    rf"counsellors?|counselors?|"
    rf"partner|spouse|"
    rf"siblings?|parents?|children|kids|"
    rf"brothers?|sisters?|mother|mom|father|dad|husband|wife)\b|"
    rf"\bwhat\s+(?:is|was|are|were)\s+{_ENTITY_LABEL_RE}(?:'s|s')?\s+"
    rf"(?:friends?|family|relatives?|coworkers?|co-workers?|colleagues?|"
    rf"teammates?|team\s+members?|managers?|mentors?|boss|bosses|"
    rf"supervisors?|coach(?:es)?|trainers?|teachers?|tutors?|classmates?|"
    rf"schoolmates?|"
    rf"roommates?|neighbors?|neighbours?|doctors?|dentists?|therapists?|"
    rf"counsellors?|counselors?|"
    rf"partner|spouse|"
    rf"siblings?|parents?|children|kids|"
    rf"brothers?|sisters?|mother|mom|father|dad|husband|wife)(?:'s|s')?\s+"
    rf"names?\b|"
    rf"\bwho\s+(?:is|are|was|were)\s+(?:the\s+)?(?:friends?|family|relatives?|"
    rf"coworkers?|co-workers?|colleagues?|teammates?|team\s+members?|manager|"
    rf"mentor|boss|bosses|supervisors?|coach(?:es)?|trainers?|teachers?|"
    rf"tutors?|classmates?|schoolmates?|roommates?|doctors?|dentists?|therapists?|"
    rf"counsellors?|"
    rf"counselors?|"
    rf"neighbors?|neighbours?|"
    rf"partner|spouse|siblings?|parents?|"
    rf"children|kids|brothers?|sisters?|mother|mom|father|dad|husband|wife)\s+"
    rf"(?:with|of|to|for)\s+{_ENTITY_LABEL_RE}\b|"
    rf"\bwho\s+(?:does|did)\s+{_ENTITY_LABEL_RE}\s+"
    rf"(?:work|collaborate|partner|team\s+up)\s+(?:with|alongside)\b|"
    rf"\b(?:does|did)\s+{_ENTITY_LABEL_RE}\s+"
    rf"(?:work|collaborate|partner|team\s+up)\s+(?:with|alongside)\s+"
    rf"{_ENTITY_LABEL_RE}\b|"
    rf"(?<!who\s)\b(?:is|are|was|were)\s+{_ENTITY_LABEL_RE}\s+"
    rf"{_ENTITY_LABEL_RE}(?:'s|s')?\s+"
    rf"(?:friends?|family|relatives?|coworkers?|co-workers?|colleagues?|"
    rf"teammates?|team\s+members?|managers?|mentors?|boss|bosses|"
    rf"supervisors?|coach(?:es)?|trainers?|teachers?|tutors?|classmates?|"
    rf"schoolmates?|roommates?|neighbors?|neighbours?|doctors?|dentists?|"
    rf"therapists?|counsellors?|counselors?|partner|spouse|siblings?|"
    rf"parents?|children|kids|brothers?|sisters?|mother|mom|father|dad|"
    rf"husband|wife)\b|"
    rf"(?<!who\s)\b(?:is|are|was|were)\s+{_ENTITY_LABEL_RE}\s+(?:the\s+)?"
    rf"(?:friends?|family|relatives?|coworkers?|co-workers?|colleagues?|"
    rf"teammates?|team\s+members?|manager|mentor|boss|bosses|supervisors?|"
    rf"coach(?:es)?|trainers?|teachers?|tutors?|classmates?|schoolmates?|"
    rf"roommates?|doctors?|dentists?|therapists?|counsellors?|counselors?|"
    rf"neighbors?|neighbours?|partner|spouse|siblings?|parents?|children|"
    rf"kids|brothers?|sisters?|mother|mom|father|dad|husband|wife)\s+"
    rf"(?:with|of|to|for)\s+{_ENTITY_LABEL_RE}\b|"
    rf"\bwhat\s+(?:is|was|are|were)\s+{_ENTITY_LABEL_RE}(?:'s|s')?\s+"
    rf"(?:relationship|relation|connection)\s+(?:to|with)\s+"
    rf"{_ENTITY_LABEL_RE}\b|"
    rf"\bhow\s+(?:is|are|was|were)\s+{_ENTITY_LABEL_RE}\s+"
    rf"(?:connected|related|linked|associated)\s+(?:to|with)\s+"
    rf"{_ENTITY_LABEL_RE}\b|"
    rf"\bwho\s+(?:is|are|was|were)\s+{_ENTITY_LABEL_RE}\s+"
    rf"(?:connected|related|linked|associated)\s+(?:to|with)\b",
    re.IGNORECASE,
)
_PERSON_TEAM_MEMBERSHIP_QUERY_RE = re.compile(
    rf"\b(?:what|which)\s+(?:team|club|group)\s+(?:is|was)\s+"
    rf"{_ENTITY_LABEL_RE}\s+(?:on|in|part\s+of)\b|"
    rf"\b(?:what|which)\s+(?:team|club|group)\s+(?:does|did)\s+"
    rf"{_ENTITY_LABEL_RE}\s+(?:belong\s+to|join)\b|"
    rf"\b(?:what|which)\s+(?:team|club|group)\s+(?:is|was)\s+"
    rf"{_ENTITY_LABEL_RE}\s+(?:a\s+)?member\s+of\b|"
    rf"\bwhat\s+{_ENTITY_LABEL_RE}(?:'s|s')?\s+(?:team|club|group)\b",
    re.IGNORECASE,
)
_RU_PERSON_RELATION_INVENTORY_QUERY_RE = re.compile(
    rf"\bкто\s+(?:работа(?:ет|л|ла|ли)|сотруднича(?:ет|л|ла|ли))\s+"
    rf"(?:с|со)\s+{_ENTITY_LABEL_RE}\b|"
    rf"\bкто\s+(?:друзья|семья|родственники|коллеги|команда|напарники|"
    rf"руководитель|наставник|партн[её]р|супруг|супруга|брат|сестра|"
    rf"родители|дети)\s+{_ENTITY_LABEL_RE}\b|"
    rf"\bкто\s+(?:связан|связана|связаны|знаком|знакома|знакомы)\s+"
    rf"(?:с|со)\s+{_ENTITY_LABEL_RE}\b",
    re.IGNORECASE,
)

ENTITY_RELATION_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"entity_relation_inventory_query"}),
        _ENTITY_RELATION_INVENTORY_EXPANSION,
        "entity_relation_inventory_bridge",
    ),
    (
        frozenset({"person_relation_inventory_query"}),
        _PERSON_RELATION_INVENTORY_EXPANSION,
        "person_relation_inventory_bridge",
    ),
    (
        frozenset({"person_team_membership_query"}),
        _PERSON_TEAM_MEMBERSHIP_EXPANSION,
        "person_team_membership_bridge",
    ),
    (
        frozenset({"ru_entity_relation_inventory_query"}),
        _RU_ENTITY_RELATION_INVENTORY_EXPANSION,
        "entity_relation_inventory_bridge",
    ),
    (
        frozenset({"ru_person_relation_inventory_query"}),
        _RU_PERSON_RELATION_INVENTORY_EXPANSION,
        "person_relation_inventory_bridge",
    ),
)


def entity_relation_query_variants(query: str) -> frozenset[str]:
    variants: set[str] = set()
    if _ENTITY_RELATION_INVENTORY_QUERY_RE.search(query):
        variants.add("entity_relation_inventory_query")
    if _PERSON_RELATION_INVENTORY_QUERY_RE.search(query):
        variants.add("person_relation_inventory_query")
    if _PERSON_TEAM_MEMBERSHIP_QUERY_RE.search(query):
        variants.add("person_team_membership_query")
    if _RU_ENTITY_RELATION_INVENTORY_QUERY_RE.search(query):
        variants.add("ru_entity_relation_inventory_query")
    if _RU_PERSON_RELATION_INVENTORY_QUERY_RE.search(query):
        variants.add("ru_person_relation_inventory_query")
    return frozenset(variants)

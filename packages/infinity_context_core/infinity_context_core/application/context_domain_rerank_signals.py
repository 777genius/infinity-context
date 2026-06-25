"""Domain-specific deterministic rerank signals for memory context items."""

from __future__ import annotations

import re
from dataclasses import dataclass

from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slot_count,
)
from infinity_context_core.application.context_diagnostics import (
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
    has_item_purchase_object_marker,
    has_item_purchase_temporal_or_media_marker,
    has_item_purchase_verb_marker,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_travel_place_evidence import (
    has_travel_place_inventory_evidence,
)
from infinity_context_core.application.dto import ContextItem

_SUPPORT_NETWORK_PEOPLE_RE = re.compile(
    r"\b(?:friends?|family|mentors?|people\s+around|parents?|mother|mom|"
    r"father|dad|sisters?|brothers?|siblings?|partner|spouse|husband|wife|"
    r"coach|teacher|counselor)\b|"
    r"\b(?:друзья|друзей|семья|семьи|родители|мама|мать|отец|папа|"
    r"сестра|сестры|брат|братья|партнер|партн[её]р|супруг|супруга|"
    r"наставники|наставник|тренер|учитель|люди\s+рядом)\b",
    re.IGNORECASE,
)
_SUPPORT_NETWORK_SIGNAL_RE = re.compile(
    r"\b(?:rocks?|there\s+for|support\s+system|support\s+network|strength|"
    r"motivat(?:e|es|ed|ing)|cheer(?:s|ed)?\s+(?:me|her|him|them)\s+on|"
    r"trusted|reliable|comfort(?:s|ed)?)\b|"
    r"\b(?:опор\w*|рядом|поддерж\w*|помог\w*|сил\w*|мотивир\w*)\b",
    re.IGNORECASE,
)
_SUPPORT_NETWORK_TECHNICAL_RE = re.compile(
    r"\b(?:api|backend|cloud|customer|database|frontend|infra|integration|"
    r"library|model|platform|provider|runtime|sdk|service|software|technical|"
    r"tool|web)\b",
    re.IGNORECASE,
)
_SUPPORT_NETWORK_RERANK_REASONS = frozenset(
    (
        "negative_experience_support_bridge",
        "support_network_bridge",
    )
)
_INVENTORY_LIST_RERANK_REASONS = frozenset(
    (
        "decomposition_inventory_list",
        "friend_place_inventory_bridge",
        "friend_place_shelter_inventory_bridge",
        "friend_place_gym_inventory_bridge",
        "friend_place_church_inventory_bridge",
        "pottery_type_bridge",
        "travel_country_inventory_bridge",
        "cause_education_infrastructure_inventory_bridge",
        "cause_veterans_inventory_bridge",
    )
)
_CURRENT_GOAL_RERANK_REASONS = frozenset(
    (
        "adoption_current_goal_bridge",
        "adoption_current_milestone_bridge",
        "decomposition_current_preference_or_goal",
    )
)
_POSITIVE_PREFERENCE_RERANK_REASONS = frozenset(
    (
        "children_preference_bridge",
        "classical_music_preference_bridge",
        "decomposition_current_preference_or_goal",
        "food_preference_bridge",
        "outdoor_nature_memory_bridge",
        "outdoor_preference_bridge",
    )
)
_OUTDOOR_PREFERENCE_RERANK_REASONS = frozenset(
    (
        "outdoor_nature_memory_bridge",
        "outdoor_preference_bridge",
    )
)
_COMMONALITY_RERANK_REASONS = frozenset(
    (
        "business_commonality_bridge",
        "commonality_interest_bridge",
        "decomposition_commonality",
    )
)
_FAMILY_HIKE_DETAIL_RERANK_REASONS = frozenset(
    (
        "family_hike_activity_bridge",
        "family_hike_detail_bridge",
    )
)
_TEMPORAL_CAMPING_DETAIL_RERANK_REASONS = frozenset(
    (
        "camping_detail_bridge",
        "temporal_event_detail_bridge",
    )
)
_RELATIONSHIP_STATUS_RERANK_REASONS = frozenset(
    (
        "relationship_status_bridge",
        "decomposition_relationship_status",
    )
)
_RELATIONSHIP_DURATION_RERANK_REASONS = frozenset(
    (
        "relationship_duration_bridge",
        "decomposition_relationship_duration",
    )
)
_RELATIONSHIP_ORIGIN_RERANK_REASONS = frozenset(("relationship_origin_bridge",))
_RECOMMENDATION_FOLLOWUP_RERANK_REASONS = frozenset(
    (
        "book_suggestion_bridge",
        "decomposition_recommendation_source",
        "recommendation_source_bridge",
    )
)
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
_BEACH_OR_MOUNTAINS_RERANK_REASONS = frozenset(("beach_or_mountains_inference_bridge",))
_ITEM_PURCHASE_RERANK_REASONS = frozenset(("item_purchase_bridge",))
_SYMBOL_IMPORTANCE_RERANK_REASONS = frozenset(("symbol_importance_bridge",))
_POST_EVENT_EMOTION_RERANK_REASONS = frozenset(("post_event_emotion_bridge",))
_INVENTORY_POTTERY_QUERY_RE = re.compile(
    r"\b(?:pottery|ceramic|clay|pots?|bowls?|cups?|mugs?|plates?)\b",
    re.IGNORECASE,
)
_INVENTORY_POTTERY_EVIDENCE_RE = re.compile(
    r"\b(?:pottery|ceramic|clay|pots?|bowls?|cups?|mugs?|plates?)\b",
    re.IGNORECASE,
)
_INVENTORY_POTTERY_OWNER_EVIDENCE_RE = re.compile(
    r"\bD\d+:\d+\s+Melanie:"
    r"(?=.{0,260}\b(?:pottery|ceramic|clay|pots?|bowls?|cups?|mugs?|plates?|dog\s+face)\b)"
    r"(?=.{0,260}\b(?:made|make|making|class|workshop|kids?|children|finished|project|"
    r"hands\s+dirty|creativity|imagination|proud)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_COUNTRY_QUERY_RE = re.compile(
    r"\b(?:cities|city|countries|country|abroad|europe(?:an)?|places?)\b",
    re.IGNORECASE,
)
_INVENTORY_COUNTRY_EVIDENCE_RE = re.compile(
    r"\b(?:england|spain|france|italy|germany|portugal|ireland|sweden|"
    r"rome|paris|london|madrid|berlin|lisbon|dublin|stockholm)\b",
    re.IGNORECASE,
)
_INVENTORY_CAUSE_QUERY_RE = re.compile(
    r"\b(?:causes?|support(?:ing)?|passionate)\b",
    re.IGNORECASE,
)
_INVENTORY_CAUSE_EVIDENCE_RE = re.compile(
    r"\b(?:veterans?\s+rights?|military|education\s+reform|"
    r"infrastructure\s+development|education|infrastructure)\b",
    re.IGNORECASE,
)
_INVENTORY_FRIEND_PLACE_QUERY_RE = re.compile(
    r"\bwhere\b(?=.{0,100}\b(?:friend|friends|made|met|joined|meet)\b)",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_FRIEND_PLACE_EVIDENCE_RE = re.compile(
    r"\b(?:made\s+friends|became\s+friends|friends\s+with|fellow\s+volunteers?|"
    r"joined\s+(?:a\s+|the\s+|nearby\s+|local\s+)?(?:gym|church)|"
    r"homeless\s+shelter|dog\s+shelter|animal\s+shelter|"
    r"(?:gym|church).{0,100}\b(?:supportive|welcoming|community|people))\b",
    re.IGNORECASE | re.DOTALL,
)
_INVENTORY_SHELTER_QUERY_RE = re.compile(
    r"\bshelters?\b",
    re.IGNORECASE,
)
_INVENTORY_SHELTER_EVIDENCE_RE = re.compile(
    r"\b(?:homeless\s+shelter|dog\s+shelter|animal\s+shelter|shelter)\b",
    re.IGNORECASE,
)
_INVENTORY_GENERIC_WEAK_RE = re.compile(
    r"\b(?:inventory\s+list|answer\s+options|evidence\s+observed|"
    r"observed\s+mentioned|generic\s+inventory|virtual\s+support\s+group|"
    r"asked\s+family\s+and\s+friends\s+to\s+join|visited\s+countries\s+abroad)\b",
    re.IGNORECASE,
)
_EVENT_SEQUENCE_MARKER_RE = re.compile(
    r"\b(?:after|since|following|later|next|then|subsequently|before|earlier|prior)\b|"
    r"\b(?:после|с\s+тех\s+пор|затем|потом|до|перед|раньше)\b",
    re.IGNORECASE,
)
_EVENT_SEQUENCE_OUTCOME_RE = re.compile(
    r"\b(?:decid(?:e|ed|es|ing)|chang(?:e|ed|es|ing)|agreed?|promis(?:e|ed|es|ing)|"
    r"selected?|chos(?:e|en)|picked?|planned?|wait(?:ed|ing)?|follow(?:ed)?\s+up|"
    r"outcome|result|happened|response|next\s+step)\b|"
    r"\b(?:решил\w*|изменил\w*|согласил\w*|пообещал\w*|выбрал\w*|"
    r"запланировал\w*|договорил\w*|результат|следующ\w+\s+шаг)\b",
    re.IGNORECASE,
)
_EVENT_SEQUENCE_QUERY_RE = re.compile(
    r"\b(?:what|which|who|when|where|how)\b(?=.{0,120}\b(?:after|since|following|"
    r"before|prior)\b)(?=.{0,160}\b(?:talk(?:ed|ing)?|spoke|conversation|call|"
    r"meeting|chat|message|event|decid(?:e|ed)|chang(?:e|ed)|happened)\b)|"
    r"\b(?:что|кто|когда|где|как)\b(?=.{0,120}\b(?:после|до|перед|с\s+тех\s+пор)\b)",
    re.IGNORECASE | re.DOTALL,
)
_RECOMMENDATION_FOLLOWUP_BOOK_RE = re.compile(
    r"\b(?:book|novel|memoir|story|read(?:ing)?|чит(?:аю|ал\w*|ает\w*)|книг\w*)\b",
    re.IGNORECASE,
)
_RECOMMENDATION_FOLLOWUP_SIGNAL_RE = re.compile(
    r"\b(?:recommend(?:ed|ation)?|suggest(?:ed|ion)?|told\s+me\s+about|"
    r"посоветовал\w*|порекомендовал\w*)\b",
    re.IGNORECASE,
)
_EVENT_SEQUENCE_NAMED_ANCHOR_RE = re.compile(
    r"\b[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9._-]{1,}\b"
)
_EVENT_SEQUENCE_IGNORED_ANCHORS = frozenset(
    {
        "After",
        "Before",
        "Following",
        "How",
        "Since",
        "The",
        "What",
        "When",
        "Where",
        "Which",
        "Who",
        "Why",
        "Где",
        "До",
        "Зачем",
        "Как",
        "Какая",
        "Какие",
        "Какой",
        "Когда",
        "Кто",
        "Перед",
        "После",
        "Почему",
        "Что",
    }
)
_EVENT_SEQUENCE_MIN_QUERY_DISTINCTIVE_TERMS = 3
_EVENT_SEQUENCE_MIN_EXACT_DISTINCTIVE_HITS = 3
_CURRENT_GOAL_EVIDENCE_RE = re.compile(
    r"\b(?:goal|hope(?:s|d|ful)?|plan(?:s|ned|ning)?|intend(?:s|ed|ing)?|"
    r"want(?:s|ed)?\s+to|decid(?:e|ed|es|ing)\s+to|pursu(?:e|ed|ing)|"
    r"career\s+path|next\s+steps?|adoption|adopting|adopt(?:ed|s)?|"
    r"build\s+my\s+own\s+family|having\s+a\s+family|"
    r"committ(?:ed|ing)?\s+to\s+stay|plans?\s+to\s+stay|staying\s+through)\b|"
    r"\b(?:signed|renewed|accepted|started|enrolled|booked|scheduled|committed)\b"
    r"(?=.{0,80}\b(?:lease|contract|job|role|program|semester|project|deadline|"
    r"appointment|school|stay|local)\b)|"
    r"\b(?:lease|contract|job|role|program|semester|project|deadline|appointment|"
    r"school|local)\b(?=.{0,80}\b(?:signed|renewed|accepted|started|enrolled|"
    r"booked|scheduled|committed)\b)|"
    r"\b(?:цель|намерен\w*|планир\w*|решил\w*|хочет\s+.+\bсделать|"
    r"усынов\w*|удочер\w*|семь[яю]|подписал\w*|продлил\w*|записал\w*|"
    r"забронировал\w*|остаться)\b",
    re.IGNORECASE | re.DOTALL,
)
_CURRENT_GOAL_WEAK_RE = re.compile(
    r"\b(?:miss(?:es|ed|ing)?\s+(?:home|her\s+home|his\s+home|their\s+home|"
    r"home\s+country)|moving?\s+back\s+someday|move\s+back\s+someday|"
    r"general\s+planning\s+advice|thought\s+about|considered\s+maybe)\b|"
    r"\b(?:скуча\w*|когда-нибудь\s+верн\w*|общие\s+планы)\b",
    re.IGNORECASE,
)
_ANIMAL_CAREER_QUERY_RE = re.compile(
    r"\b(?:alternative\s+career|career)\b(?=.{0,80}\bgaming\b)|"
    r"\bgaming\b(?=.{0,80}\bcareer\b)",
    re.IGNORECASE | re.DOTALL,
)
_ANIMAL_CAREER_EVIDENCE_RE = re.compile(
    r"\b(?:animals?|pets?|reptiles?|turtles?|zoo|zookeeper|keeper|habitat|"
    r"tank|feed|feeding|eat|eating|diet|vegetables|fruits|insects|clean|"
    r"light|care|caring|joy|peace|companions?|pet\s+store)\b",
    re.IGNORECASE,
)
_ANIMAL_CAREER_GAMING_ONLY_RE = re.compile(
    r"\b(?:gaming|games?|gamer|tournament|tournaments|console|streamer|"
    r"streaming|esports?|champion|championship)\b",
    re.IGNORECASE,
)
_POSITIVE_PREFERENCE_QUERY_RE = re.compile(
    r"\b(?:what|which)\b(?=.{0,120}\b(?:like|likes|liked|love|loves|"
    r"enjoy|enjoys|prefer|prefers|favorite|favourite|food|meal|music|song|"
    r"artist|book|activity|hobby)\b)|"
    r"\b(?:would\b(?=.{0,80}\benjoy\b)|prefer(?:s|red)?|favorite|favourite|"
    r"likes?|loves?|fan\s+of)\b|"
    r"\b(?:что|какой|какие)\b(?=.{0,120}\b(?:нравит|любит|предпочит|"
    r"любим))",
    re.IGNORECASE | re.DOTALL,
)
_POSITIVE_PREFERENCE_NEGATIVE_QUERY_RE = re.compile(
    r"\b(?:not\s+(?:like|likes|liked|enjoy|enjoys|prefer|want)|"
    r"doesn'?t\s+(?:like|enjoy|prefer|want)|does\s+not\s+"
    r"(?:like|enjoy|prefer|want)|dislikes?|hates?|avoid|avoids|allergic)\b|"
    r"\b(?:не\s+нравит|не\s+любит|избега|аллерг)\w*\b",
    re.IGNORECASE,
)
_POSITIVE_PREFERENCE_MARKER_RE = re.compile(
    r"\b(?:likes?|liked|loves?|loved|enjoys?|enjoyed|prefers?|preferred|"
    r"favorites?|favourites?|favorite\s+(?:food|meal|dish|song|book|activity)|"
    r"one\s+of\s+(?:my|her|his|their)\s+favorites?|fan\s+of|"
    r"interested\s+in|stoked\s+about|excited\s+about)\b|"
    r"\b(?:нравит\w*|любит|любил\w*|предпочит\w*|любим\w*|"
    r"фанат\w*|интересу\w*)\b",
    re.IGNORECASE,
)
_POSITIVE_PREFERENCE_WEAK_TOPIC_RE = re.compile(
    r"\b(?:discuss(?:ed|es|ing)?|talk(?:ed|s|ing)?\s+about|mentioned|"
    r"shared|sent|saw|watched|listened\s+to|usually\s+listen(?:s|ed)?\s+to|"
    r"recipe\s+includes?|cooked|served|brought)\b|"
    r"\b(?:обсуждал\w*|упомянул\w*|слушал\w*|смотрел\w*|готовил\w*)\b",
    re.IGNORECASE,
)
_BOOK_AUTHOR_PREFERENCE_QUERY_RE = re.compile(
    r"\b(?:books?\s+by|author|authors?|c\.?\s*s\.?\s*lewis|lewis|"
    r"john\s+green(?:e)?|would\b(?=.{0,80}\benjoy\b).{0,120}\bread(?:ing)?)\b",
    re.IGNORECASE | re.DOTALL,
)
_BOOK_AUTHOR_WORLD_EXACT_RE = re.compile(
    r"\b(?:harry\s+potter|potter|j\.?\s*k\.?\s*rowling|fantasy)\b"
    r"(?=.{0,180}\b(?:magical\s+world|wizarding\s+world|universe|characters?|"
    r"spells?|magical\s+creatures?|london|movie|tour|real\s+potter\s+places?|"
    r"getting?\s+lost|lost\s+in|transport|alternate\s+realities|escape|"
    r"different\s+worlds?|other\s+places?)\b)|"
    r"\b(?:magical\s+world|wizarding\s+world|universe|characters?|spells?|"
    r"magical\s+creatures?|london|movie|tour|real\s+potter\s+places?|"
    r"getting?\s+lost|lost\s+in|transport|alternate\s+realities|escape|"
    r"different\s+worlds?|other\s+places?)\b"
    r"(?=.{0,180}\b(?:harry\s+potter|potter|j\.?\s*k\.?\s*rowling|fantasy)\b)",
    re.IGNORECASE | re.DOTALL,
)
_BOOK_AUTHOR_POTTER_WORLD_RE = re.compile(
    r"\b(?:harry\s+potter|potter)\b(?=.{0,180}\b(?:magical\s+world|"
    r"wizarding\s+world|universe|characters?|spells?|magical\s+creatures?|"
    r"london|movie|tour|real\s+potter\s+places?|getting?\s+lost|lost\s+in)\b)|"
    r"\b(?:magical\s+world|wizarding\s+world|universe|characters?|spells?|"
    r"magical\s+creatures?|london|movie|tour|real\s+potter\s+places?|"
    r"getting?\s+lost|lost\s+in)\b(?=.{0,180}\b(?:harry\s+potter|potter)\b)",
    re.IGNORECASE | re.DOTALL,
)
_BOOK_AUTHOR_GENERIC_COLLECTION_RE = re.compile(
    r"\b(?:bookshelf|book\s+shelf|book\s+collection|favorites?\s+on\s+there|"
    r"photo\s+of\s+a\s+book|bunch\s+of\s+books)\b",
    re.IGNORECASE,
)
_OUTDOOR_NATURE_EVIDENCE_RE = re.compile(
    r"\b(?:camp(?:ing|fire)|hikes?|hiking|trail|forest|mountains?|nature|"
    r"outdoors?|national\s+park|meteor\s+shower|perseid|sky|universe)\b",
    re.IGNORECASE,
)
_OUTDOOR_STRONG_NATURE_EVIDENCE_RE = re.compile(
    r"\b(?:camp(?:ing|fire)|hikes?|hiking|trail|forest|mountains?|nature|"
    r"outdoors?|meteor\s+shower|perseid|sky|universe)\b",
    re.IGNORECASE,
)
_COMMONALITY_QUERY_RE = re.compile(
    r"\b(?:common|shared|both|mutual|same|similar|overlap|who\s+else)\b|"
    r"\b(?:обе|оба|общ\w*|похож\w*|тоже)\b",
    re.IGNORECASE,
)
_COMMONALITY_WHO_ELSE_QUERY_RE = re.compile(
    r"\bwho\s+else\b|"
    r"\b(?:кто\s+ещ[её]|еще\s+кто|ещ[её]\s+кто)\b",
    re.IGNORECASE,
)
_COMMONALITY_EVIDENCE_RE = re.compile(
    r"\b(?:both|share(?:s|d)?|shared|common|mutual|same|similar|also|"
    r"each|together|overlap)\b|"
    r"\b(?:обе|оба|общ\w*|похож\w*|тоже|вместе)\b",
    re.IGNORECASE,
)
_COMMONALITY_WHO_ELSE_EVIDENCE_RE = re.compile(
    r"\b(?:also|too|as\s+well|like|likes|liked|enjoys?|enjoyed|interested\s+in|"
    r"fan\s+of)\b|"
    r"\b(?:тоже|также|любит|нравит\w*|интересу\w*)\b",
    re.IGNORECASE,
)
_COMMONALITY_SHARED_ARTIFACT_RE = re.compile(
    r"\bshared?\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:photo|picture|image|screenshot|file|document|attachment|link|post)\b",
    re.IGNORECASE,
)
_BUSINESS_COMMONALITY_ORIGIN_RE = re.compile(
    r"\b(?:"
    r"lost\s+my\s+job\s+(?:as|at)|"
    r"also\s+lost\s+my\s+job|"
    r"lost\s+(?:her|his)\s+job|"
    r"after\s+losing\s+(?:her|his)\s+job|"
    r"take\s+a\s+shot\s+at\s+starting\s+my\s+own\s+business|"
    r"starting\s+my\s+own\s+store|"
    r"started\s+(?:her|his)\s+own\s+(?:online\s+)?clothing\s+store|"
    r"launched\s+an\s+ad\s+campaign|"
    r"taking\s+risks\s+is\s+both\s+scary\s+and\s+rewarding|"
    r"i['']?m\s+starting\s+a\s+dance\s+studio"
    r")\b",
    re.IGNORECASE,
)
_BUSINESS_COMMONALITY_LATE_UPDATE_RE = re.compile(
    r"\b(?:"
    r"congrats?\s+on\s+the\s+clothing\s+store|"
    r"hard\s+work\s+paying\s+off|"
    r"got\s+a\s+temp\s+job|"
    r"built\s+a\s+new\s+website|"
    r"acquired\s+some\s+new\s+unique\s+pieces|"
    r"working\s+on\s+(?:my\s+)?online\s+store|"
    r"promoting\s+(?:my\s+)?business|"
    r"business\s+project\s+and\s+seeks\s+advice"
    r")\b",
    re.IGNORECASE,
)
_SHARED_PAINTED_SUBJECT_EXACT_RE = re.compile(
    r"\b(?:sunsets?|sunrises?|landscapes?|flowers?|nature(?:-inspired)?|"
    r"lake|mountains?|abstract|portraits?|scen(?:e|ery))\b"
    r"(?=.{0,80}\b(?:paint(?:ed|ing)?|artwork|work|image|visual|caption)\b)|"
    r"\b(?:paint(?:ed|ing)?|artwork|work|image|visual|caption)\b"
    r"(?=.{0,80}\b(?:sunsets?|sunrises?|landscapes?|flowers?|"
    r"nature(?:-inspired)?|lake|mountains?|abstract|portraits?|scen(?:e|ery))\b)",
    re.IGNORECASE | re.DOTALL,
)
_SHARED_PAINTED_SUBJECT_TOPIC_RE = re.compile(
    r"\b(?:paint(?:ed|ing)?|artwork)\b",
    re.IGNORECASE,
)
_FAMILY_HIKE_DETAIL_EXACT_RE = re.compile(
    r"\b(?:roast(?:ed|ing)?\s+marshmallows?|marshmallows?|"
    r"tell(?:ing)?\s+stories|shared\s+stories)\b",
    re.IGNORECASE,
)
_FAMILY_HIKE_DETAIL_TOPIC_RE = re.compile(
    r"\b(?:family|kids?|children|hikes?|hiking|camp(?:ing|fire)?|nature|"
    r"trail|waterfall|photos?|pictures?)\b",
    re.IGNORECASE,
)
_FAMILY_HIKE_DETAIL_QUERY_RE = re.compile(
    r"\bwhat\b(?=.{0,80}\b(?:family|kids?|children)\b)"
    r"(?=.{0,80}\b(?:hikes?|hiking)\b)|"
    r"\b(?:hikes?|hiking)\b(?=.{0,80}\b(?:family|kids?|children)\b)",
    re.IGNORECASE | re.DOTALL,
)
_TEMPORAL_CAMPING_DETAIL_QUERY_RE = re.compile(
    r"\bwhen\b(?=.{0,120}\bcamp(?:ing|ed)?\b)|"
    r"\bcamp(?:ing|ed)?\b(?=.{0,120}\bwhen\b)",
    re.IGNORECASE | re.DOTALL,
)
_TEMPORAL_CAMPING_CORE_DETAIL_RE = re.compile(
    r"\b(?:roast(?:ed|ing)?\s+marshmallows?|marshmallows?|campfire)\b",
    re.IGNORECASE,
)
_TEMPORAL_CAMPING_DETAIL_TERM_RE = re.compile(
    r"\b(?:campfire|marshmallows?|roast(?:ed|ing)?|hikes?|hiking|trail|"
    r"mountains?|nature|view|family|kids?|children|moments?)\b",
    re.IGNORECASE,
)
_COMMONALITY_NAMED_ANCHOR_RE = re.compile(r"\b[A-Z][A-Za-z0-9._-]{1,}\b")
_COMMONALITY_IGNORED_ANCHORS = frozenset(
    {
        "How",
        "What",
        "When",
        "Where",
        "Which",
        "Who",
        "Why",
    }
)
_AGGREGATION_RETRIEVAL_SOURCE = "keyword_aggregation_chunks"
_AGGREGATION_COUNT_QUERY_RE = re.compile(
    r"\b(?:how\s+many|number\s+of|count|total|times?)\b|"
    r"\b(?:сколько|количество|число|раз)\b",
    re.IGNORECASE,
)
_AGGREGATION_LIST_QUERY_RE = re.compile(
    r"\b(?:what|which|where)\b(?=.{0,80}\b(?:items?|things?|countries|places|"
    r"types?|kinds?|events?|activities|bands?|artists?|shelters?|causes?|people)\b)|"
    r"\b(?:какие|какой|где|кого|кому)\b",
    re.IGNORECASE | re.DOTALL,
)
_AGGREGATION_NUMERIC_ANSWER_RE = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|once|twice|"
    r"couple|several|multiple|another|again)\b|"
    r"\b(?:один|одна|два|две|три|четыре|пять|шесть|семь|восемь|девять|"
    r"десять|раз|дважды|несколько|много|ещ[её])\b",
    re.IGNORECASE,
)
_AGGREGATION_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
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
    r"introduced\s+(?:at|in|during|through|via|by)|"
    r"became\s+friends\s+(?:at|in|during|through|via)|"
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
    r"current|active|new|old|previous|stale|deprecated|no\s+longer|now)\b|"
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
_BEACH_OR_MOUNTAINS_QUERY_RE = re.compile(
    r"\b(?:beach|beaches|ocean|shore|coast|mountain|mountains)\b"
    r"(?=.{0,120}\b(?:close|near|nearby|live|lives|living|by|next\s+to)\b)|"
    r"\b(?:close|near|nearby|live|lives|living|by|next\s+to)\b"
    r"(?=.{0,120}\b(?:beach|beaches|ocean|shore|coast|mountain|mountains)\b)",
    re.IGNORECASE | re.DOTALL,
)
_BEACH_OR_MOUNTAINS_DOMAIN_RE = re.compile(
    r"\b(?:beach|beaches|ocean|shore|coast|coastal|sailboat|sand|sunset|"
    r"mountain|mountains|trail|hiking|hike)\b",
    re.IGNORECASE,
)
_BEACH_OR_MOUNTAINS_PROXIMITY_RE = re.compile(
    r"\b(?:close|near|nearby|by|next\s+to|weekly\s+walks?|walks?|goes?\s+on\s+"
    r"walks?|lives?\s+close|lives?\s+near|from\s+home|local)\b",
    re.IGNORECASE,
)
_BEACH_OR_MOUNTAINS_TOPIC_ONLY_RE = re.compile(
    r"\b(?:whether|sounded\s+nice|someday|maybe|vacation|wallpaper|poster|"
    r"preference|would\s+like|dream(?:ed)?\s+of)\b"
    r"(?=.{0,120}\b(?:beach|beaches|ocean|mountains?)\b)|"
    r"\b(?:beach|beaches|ocean|mountains?)\b"
    r"(?=.{0,120}\b(?:whether|sounded\s+nice|someday|maybe|vacation|"
    r"wallpaper|poster|preference|would\s+like|dream(?:ed)?\s+of)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SYMBOL_IMPORTANCE_EXACT_RE = re.compile(
    r"\b(?:symboli[sz](?:e|es|ed|ing)|represents?|meaning|means|stands?\s+for|"
    r"important|reminds?\s+(?:me|her|him|them)\s+of|pride|freedom|courage|"
    r"resilience|identity|acceptance)\b|"
    r"\b(?:символизир\w*|значит|значение|важн\w*|напомина\w*|гордост\w*|"
    r"свобод\w*|смелост\w*|идентичност\w*|приняти\w*)\b",
    re.IGNORECASE,
)
_SYMBOL_IMPORTANCE_MEANING_RE = re.compile(
    r"\b(?:symboli[sz](?:e|es|ed|ing)|represents?|meaning|means|stands?\s+for|"
    r"reminds?\s+(?:me|her|him|them)\s+of|pride|freedom|courage|resilience|"
    r"identity|acceptance)\b|"
    r"\b(?:символизир\w*|значит|значение|напомина\w*|гордост\w*|свобод\w*|"
    r"смелост\w*|идентичност\w*|приняти\w*)\b",
    re.IGNORECASE,
)
_SYMBOL_IMPORTANCE_OBJECT_RE = re.compile(
    r"\b(?:rainbow\s+flag|flag|mural|eagle|pendant|necklace|"
    r"transgender\s+symbol|cross|heart|symbol|symbols)\b|"
    r"\b(?:радужн\w+\s+флаг|флаг|орел|орёл|кулон|ожерелье|крест|"
    r"сердце|символ\w*)\b",
    re.IGNORECASE,
)
_SYMBOL_IMPORTANCE_PERSONAL_OBJECT_RE = re.compile(
    r"\b(?:pendant|necklace)\b(?=.{0,100}\b(?:symbol|cross|heart|transgender)\b)|"
    r"\b(?:symbol|cross|heart|transgender)\b(?=.{0,100}\b(?:pendant|necklace)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SYMBOL_IMPORTANCE_VISUAL_OBJECT_RE = re.compile(
    r"\b(?:visual\s+query|image\s+caption|caption)\b"
    r"(?=.{0,140}\b(?:pendant|necklace)\b)"
    r"(?=.{0,140}\b(?:transgender\s+symbol|cross|heart|symbol)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SYMBOL_IMPORTANCE_TECHNICAL_NOISE_RE = re.compile(
    r"\b(?:unicode|currency|math(?:ematical)?|keyboard|font|icon|icons|"
    r"svg|css|ui|interface|variable|operator|code|programming)\b",
    re.IGNORECASE,
)
_POST_EVENT_EMOTION_EXACT_RE = re.compile(
    r"\b(?:felt|feel|feeling|grateful|thankful|relieved|lucky|scared|"
    r"freaked|inspired|proud|happy|sad|upset|awe|means?\s+the\s+world|"
    r"meaningful)\b",
    re.IGNORECASE,
)
_POST_EVENT_FAMILY_APPRECIATION_RE = re.compile(
    r"\b(?:i|i'm|i've|me|my|we|our)\b"
    r"(?=.{0,220}\b(?:family|fam|loved\s+ones|them|they)\b)"
    r"(?=.{0,180}\b(?:super\s+important|important\s+to\s+me|"
    r"mean\s+the\s+world|means\s+the\s+world|need\s+them|"
    r"thankful\s+to\s+have|grateful\s+to\s+have|cherish|"
    r"biggest\s+motivation|support|rock)\b)|"
    r"\b(?:super\s+important|important\s+to\s+me|mean\s+the\s+world|"
    r"means\s+the\s+world|need\s+them|thankful\s+to\s+have|"
    r"grateful\s+to\s+have|cherish|biggest\s+motivation|support|rock)\b"
    r"(?=.{0,180}\b(?:family|fam|loved\s+ones|them|they)\b)"
    r"(?=.{0,220}\b(?:i|i'm|i've|me|my|we|our)\b)",
    re.IGNORECASE | re.DOTALL,
)
_POST_EVENT_EMOTION_EVENT_ONLY_RE = re.compile(
    r"\b(?:accident|roadtrip|trip|event|happened|mentioned|talked|family)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DomainRerankSignal:
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""
    rank_signal_key: str = ""
    rank_signal: float = 0.0


def support_network_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if _support_network_exact_evidence(query_reason=query_reason, item=item):
        return DomainRerankSignal(boost=0.028, reason="support_network_exact_evidence")
    if _support_network_weak_evidence(
        query_reason=query_reason,
        item=item,
        relevance=relevance,
    ):
        return DomainRerankSignal(penalty=0.07, reason="support_network_weak_evidence")
    return DomainRerankSignal()


def inventory_list_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if _inventory_list_exact_evidence(query=query, query_reason=query_reason, item=item):
        return DomainRerankSignal(boost=0.058, reason="inventory_list_exact_evidence")
    if _inventory_list_wrong_owner_evidence(query=query, query_reason=query_reason, item=item):
        return DomainRerankSignal(penalty=0.16, reason="inventory_list_wrong_owner_evidence")
    if _inventory_list_weak_evidence(
        query=query,
        query_reason=query_reason,
        item=item,
        relevance=relevance,
    ):
        return DomainRerankSignal(penalty=0.055, reason="inventory_list_weak_evidence")
    return DomainRerankSignal()


def aggregation_evidence_rerank_signal(
    *,
    query: str,
    item: ContextItem,
    has_multi_evidence_competitor: bool = False,
) -> DomainRerankSignal:
    if not _is_aggregation_query(query):
        return DomainRerankSignal()
    is_list_query = _is_aggregation_list_query(query)
    answer_slot_count = aggregation_answer_slot_count(query=query, text=item.text)
    if answer_slot_count >= 2:
        if is_list_query:
            return DomainRerankSignal(
                boost=0.058,
                reason="aggregation_list_slot_diverse_evidence",
            )
        return DomainRerankSignal(
            boost=0.044,
            reason="aggregation_slot_diverse_evidence",
        )
    if _is_aggregation_context_item(item):
        if _aggregation_evidence_count(item) >= 2:
            if is_list_query:
                return DomainRerankSignal(
                    boost=0.046,
                    reason="aggregation_list_multi_evidence",
                )
            return DomainRerankSignal(boost=0.034, reason="aggregation_multi_evidence")
        if is_list_query:
            return DomainRerankSignal(boost=0.018, reason="aggregation_list_evidence")
        return DomainRerankSignal(boost=0.018, reason="aggregation_evidence")
    if _AGGREGATION_COUNT_QUERY_RE.search(query) and _is_single_weak_count_evidence(item):
        return DomainRerankSignal(penalty=0.055, reason="aggregation_single_evidence_noise")
    if (
        is_list_query
        and has_multi_evidence_competitor
        and _is_single_list_evidence(query=query, item=item)
    ):
        return DomainRerankSignal(
            penalty=0.052,
            reason="aggregation_list_single_evidence_incomplete",
        )
    return DomainRerankSignal()


def has_multi_evidence_aggregation_candidate(
    *,
    query: str,
    items: tuple[ContextItem, ...],
) -> bool:
    if not _is_aggregation_query(query):
        return False
    return any(
        (
            _is_aggregation_context_item(item)
            and _aggregation_evidence_count(item) >= 2
        )
        or aggregation_answer_slot_count(query=query, text=item.text) >= 2
        for item in items
    )


def event_sequence_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_event_sequence_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    if relevance.distinctive_term_count < _EVENT_SEQUENCE_MIN_QUERY_DISTINCTIVE_TERMS:
        return DomainRerankSignal()
    has_sequence_shape = (
        _EVENT_SEQUENCE_MARKER_RE.search(item.text) is not None
        and (
            _EVENT_SEQUENCE_OUTCOME_RE.search(item.text) is not None
            or _STATE_TRANSITION_PAIR_RE.search(item.text) is not None
        )
    )
    anchor_terms = _event_sequence_anchor_terms(query)
    anchor_hits = _event_sequence_anchor_hits(anchor_terms=anchor_terms, text=item.text)
    required_anchor_hits = min(3, len(anchor_terms))
    has_required_anchors = required_anchor_hits <= 0 or anchor_hits >= required_anchor_hits
    if (
        has_sequence_shape
        and relevance.distinctive_term_hits >= _EVENT_SEQUENCE_MIN_EXACT_DISTINCTIVE_HITS
        and has_required_anchors
    ):
        return DomainRerankSignal(boost=0.034, reason="event_sequence_exact_evidence")
    if required_anchor_hits > 0 and anchor_hits < required_anchor_hits:
        return DomainRerankSignal(penalty=0.06, reason="event_sequence_anchor_mismatch")
    if relevance.distinctive_term_hits < _EVENT_SEQUENCE_MIN_EXACT_DISTINCTIVE_HITS:
        return DomainRerankSignal(penalty=0.06, reason="event_sequence_weak_evidence")
    if not has_sequence_shape:
        return DomainRerankSignal(penalty=0.075, reason="event_sequence_shape_missing")
    return DomainRerankSignal()


def current_goal_rerank_signal(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_current_goal_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if (
        _ANIMAL_CAREER_QUERY_RE.search(query) is not None
        and _ANIMAL_CAREER_EVIDENCE_RE.search(item.text) is None
        and _ANIMAL_CAREER_GAMING_ONLY_RE.search(item.text) is not None
    ):
        return DomainRerankSignal(
            penalty=0.05,
            reason="current_goal_animal_career_mismatch",
        )
    if _CURRENT_GOAL_EVIDENCE_RE.search(item.text) is not None:
        return DomainRerankSignal(boost=0.03, reason="current_goal_exact_evidence")
    if (
        _CURRENT_GOAL_WEAK_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(penalty=0.046, reason="current_goal_weak_evidence")
    return DomainRerankSignal()


def positive_preference_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_positive_preference_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    if (
        _BOOK_AUTHOR_PREFERENCE_QUERY_RE.search(query) is not None
        and query_reason in {"book_suggestion_bridge", "book_reading_list_bridge"}
        and _BOOK_AUTHOR_WORLD_EXACT_RE.search(item.text) is not None
        and relevance.distinctive_term_hits >= 3
    ):
        rank_signal = 3.0 if _BOOK_AUTHOR_POTTER_WORLD_RE.search(item.text) else 2.0
        return DomainRerankSignal(
            boost=0.03,
            reason="book_author_preference_world_evidence",
            rank_signal_key="book_author_preference_world_evidence",
            rank_signal=rank_signal,
        )
    if (
        _BOOK_AUTHOR_PREFERENCE_QUERY_RE.search(query) is not None
        and query_reason in {"book_suggestion_bridge", "book_reading_list_bridge"}
        and _BOOK_AUTHOR_GENERIC_COLLECTION_RE.search(item.text) is not None
        and _BOOK_AUTHOR_WORLD_EXACT_RE.search(item.text) is None
    ):
        return DomainRerankSignal(
            penalty=0.04,
            reason="book_author_preference_generic_collection",
        )
    if (
        _is_outdoor_preference_candidate(query_reason=query_reason, item=item)
        and _OUTDOOR_NATURE_EVIDENCE_RE.search(item.text) is not None
        and (
            _OUTDOOR_STRONG_NATURE_EVIDENCE_RE.search(item.text) is not None
            or _POSITIVE_PREFERENCE_MARKER_RE.search(item.text) is not None
        )
        and relevance.distinctive_term_hits >= 3
    ):
        return DomainRerankSignal(boost=0.026, reason="outdoor_preference_exact_evidence")
    if (
        _POSITIVE_PREFERENCE_WEAK_TOPIC_RE.search(item.text) is not None
        and _POSITIVE_PREFERENCE_MARKER_RE.search(item.text) is None
    ):
        return DomainRerankSignal(penalty=0.046, reason="preference_weak_evidence")
    if (
        _POSITIVE_PREFERENCE_MARKER_RE.search(item.text) is not None
        and relevance.distinctive_term_hits >= 3
    ):
        return DomainRerankSignal(boost=0.024, reason="preference_exact_evidence")
    if (
        _POSITIVE_PREFERENCE_WEAK_TOPIC_RE.search(item.text) is not None
        or relevance.distinctive_term_hits >= 4
    ):
        return DomainRerankSignal(penalty=0.034, reason="preference_weak_evidence")
    return DomainRerankSignal()


def commonality_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_commonality_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    business_signal = _business_commonality_signal(
        query_reason=query_reason,
        item=item,
        relevance=relevance,
    )
    if business_signal.reason:
        return business_signal
    who_else_signal = _commonality_who_else_signal(query=query, item=item)
    if who_else_signal.reason:
        return who_else_signal
    shared_painted_subject_signal = _shared_painted_subject_signal(
        query_reason=query_reason,
        item=item,
        relevance=relevance,
    )
    if shared_painted_subject_signal.reason:
        return shared_painted_subject_signal
    if (
        query_reason in _INVENTORY_LIST_RERANK_REASONS
        and _inventory_list_exact_evidence(
            query=query,
            query_reason=query_reason,
            item=item,
        )
    ):
        return DomainRerankSignal()
    anchor_terms = _commonality_anchor_terms(query)
    if len(anchor_terms) < 2:
        return DomainRerankSignal()
    anchor_hits = _commonality_anchor_hits(anchor_terms=anchor_terms, text=item.text)
    has_commonality_shape = _COMMONALITY_EVIDENCE_RE.search(item.text) is not None
    if anchor_hits >= 2 and _COMMONALITY_SHARED_ARTIFACT_RE.search(item.text):
        return DomainRerankSignal(penalty=0.032, reason="commonality_weak_evidence")
    if anchor_hits >= 2 and has_commonality_shape:
        return DomainRerankSignal(boost=0.028, reason="commonality_exact_evidence")
    if anchor_hits < 2:
        return DomainRerankSignal(penalty=0.048, reason="commonality_anchor_mismatch")
    if not has_commonality_shape or relevance.distinctive_term_hits < 5:
        return DomainRerankSignal(penalty=0.032, reason="commonality_weak_evidence")
    return DomainRerankSignal()


def _business_commonality_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="business_commonality_bridge",
    ):
        return DomainRerankSignal()
    if _BUSINESS_COMMONALITY_ORIGIN_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.044,
            reason="business_commonality_origin_evidence",
        )
    if (
        _BUSINESS_COMMONALITY_LATE_UPDATE_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 7
    ):
        return DomainRerankSignal(
            penalty=0.052,
            reason="business_commonality_weak_update",
        )
    return DomainRerankSignal()


def _shared_painted_subject_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="shared_painted_subject_bridge",
    ):
        return DomainRerankSignal()
    if (
        _SHARED_PAINTED_SUBJECT_EXACT_RE.search(item.text) is not None
        and relevance.distinctive_term_hits >= 4
    ):
        return DomainRerankSignal(
            boost=0.034,
            reason="shared_painted_subject_exact_evidence",
        )
    if _SHARED_PAINTED_SUBJECT_TOPIC_RE.search(item.text) is not None:
        return DomainRerankSignal(
            penalty=0.052,
            reason="shared_painted_subject_topic_only_noise",
        )
    return DomainRerankSignal()


def family_hike_detail_rerank_signal(
    *,
    query: str = "",
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_family_hike_detail_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    if (
        _FAMILY_HIKE_DETAIL_EXACT_RE.search(item.text) is not None
        and relevance.distinctive_term_hits >= 4
    ):
        return DomainRerankSignal(
            boost=0.034,
            reason="family_hike_detail_exact_evidence",
        )
    if _FAMILY_HIKE_DETAIL_TOPIC_RE.search(item.text) is not None:
        return DomainRerankSignal(
            penalty=0.062,
            reason="family_hike_detail_topic_only_noise",
        )
    return DomainRerankSignal()


def temporal_camping_detail_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_temporal_camping_detail_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    if relevance.distinctive_term_hits < 6:
        return DomainRerankSignal()
    if _TEMPORAL_CAMPING_CORE_DETAIL_RE.search(item.text) is None:
        return DomainRerankSignal()
    detail_terms = {
        match.group(0).casefold()
        for match in _TEMPORAL_CAMPING_DETAIL_TERM_RE.finditer(item.text)
    }
    if len(detail_terms) < 4:
        return DomainRerankSignal()
    return DomainRerankSignal(
        boost=0.058,
        reason="temporal_camping_detail_evidence",
    )


def commonality_who_else_anchor_override(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if not _is_commonality_candidate(query=query, query_reason=query_reason, item=item):
        return False
    if _COMMONALITY_WHO_ELSE_QUERY_RE.search(query) is None:
        return False
    anchor_terms = _commonality_anchor_terms(query)
    if len(anchor_terms) != 1:
        return False
    return (
        not _text_has_any_anchor(anchor_terms=anchor_terms, text=item.text)
        and _COMMONALITY_WHO_ELSE_EVIDENCE_RE.search(item.text) is not None
    )


def relationship_status_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_relationship_status_candidate(query_reason=query_reason, item=item):
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


def recommendation_followup_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
) -> DomainRerankSignal:
    if not _is_recommendation_followup_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if (
        _RECOMMENDATION_FOLLOWUP_BOOK_RE.search(item.text) is None
        or _RECOMMENDATION_FOLLOWUP_SIGNAL_RE.search(item.text) is None
    ):
        return DomainRerankSignal()
    return DomainRerankSignal(
        boost=0.018,
        reason="recommendation_followup_evidence",
    )


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


def beach_or_mountains_rerank_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_beach_or_mountains_candidate(
        query=query,
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    has_domain = _BEACH_OR_MOUNTAINS_DOMAIN_RE.search(item.text) is not None
    has_proximity = _BEACH_OR_MOUNTAINS_PROXIMITY_RE.search(item.text) is not None
    if has_domain and has_proximity:
        return DomainRerankSignal(
            boost=0.026,
            reason="beach_mountains_proximity_evidence",
        )
    if (
        _BEACH_OR_MOUNTAINS_TOPIC_ONLY_RE.search(item.text) is not None
        or not has_domain
        or relevance.distinctive_term_hits < 3
    ):
        return DomainRerankSignal(
            penalty=0.038,
            reason="beach_mountains_topic_only_noise",
        )
    return DomainRerankSignal()


def item_purchase_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_item_purchase_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if has_item_purchase_object_evidence(item.text):
        return DomainRerankSignal(
            boost=0.055,
            reason="item_purchase_object_evidence",
            rank_signal_key="item_purchase_object_evidence",
            rank_signal=3.0,
        )
    if (
        has_item_purchase_temporal_or_media_marker(item.text)
        or not has_item_purchase_object_marker(item.text)
        or not has_item_purchase_verb_marker(item.text)
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(
            penalty=0.11,
            reason="item_purchase_temporal_weak_evidence",
        )
    return DomainRerankSignal()


def symbol_importance_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_symbol_importance_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    has_symbol_object = _SYMBOL_IMPORTANCE_OBJECT_RE.search(item.text) is not None
    has_personal_object = _SYMBOL_IMPORTANCE_PERSONAL_OBJECT_RE.search(item.text) is not None
    if _SYMBOL_IMPORTANCE_TECHNICAL_NOISE_RE.search(item.text) is not None:
        return DomainRerankSignal(penalty=0.042, reason="symbol_importance_weak_evidence")
    if has_personal_object and _SYMBOL_IMPORTANCE_VISUAL_OBJECT_RE.search(item.text):
        return DomainRerankSignal(
            boost=0.036,
            reason="symbol_importance_visual_object",
            rank_signal_key="symbol_importance_visual_evidence",
            rank_signal=3.0,
        )
    if has_symbol_object and _SYMBOL_IMPORTANCE_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.028,
            reason="symbol_importance_exact_evidence",
            rank_signal_key="symbol_importance_visual_evidence",
            rank_signal=1.0 if has_personal_object else 0.0,
        )
    if has_personal_object:
        return DomainRerankSignal(boost=0.02, reason="symbol_importance_personal_object")
    if (
        _SYMBOL_IMPORTANCE_TECHNICAL_NOISE_RE.search(item.text) is not None
        or not has_symbol_object
        or relevance.distinctive_term_hits < 3
    ):
        return DomainRerankSignal(penalty=0.042, reason="symbol_importance_weak_evidence")
    return DomainRerankSignal()


def post_event_emotion_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_post_event_emotion_candidate(query_reason=query_reason, item=item):
        return DomainRerankSignal()
    if _POST_EVENT_FAMILY_APPRECIATION_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.052,
            reason="post_event_family_appreciation_evidence",
        )
    if _POST_EVENT_EMOTION_EXACT_RE.search(item.text) is not None:
        return DomainRerankSignal(boost=0.026, reason="post_event_emotion_exact_evidence")
    if (
        _POST_EVENT_EMOTION_EVENT_ONLY_RE.search(item.text) is not None
        or relevance.distinctive_term_hits < 4
    ):
        return DomainRerankSignal(penalty=0.038, reason="post_event_emotion_weak_evidence")
    return DomainRerankSignal()


def _support_network_exact_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_support_network_candidate(query_reason=query_reason, item=item):
        return False
    return (
        _SUPPORT_NETWORK_PEOPLE_RE.search(item.text) is not None
        and _SUPPORT_NETWORK_SIGNAL_RE.search(item.text) is not None
    )


def _support_network_weak_evidence(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> bool:
    if not _is_support_network_candidate(query_reason=query_reason, item=item):
        return False
    if _SUPPORT_NETWORK_TECHNICAL_RE.search(item.text) is not None:
        return True
    if _support_network_exact_evidence(query_reason=query_reason, item=item):
        return False
    return relevance.distinctive_term_hits < 4


def _inventory_list_exact_evidence(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if not _is_inventory_list_candidate(query_reason=query_reason, item=item):
        return False
    text = item.text
    if _INVENTORY_POTTERY_QUERY_RE.search(query):
        return _INVENTORY_POTTERY_OWNER_EVIDENCE_RE.search(text) is not None
    if _INVENTORY_COUNTRY_QUERY_RE.search(query):
        return (
            _INVENTORY_COUNTRY_EVIDENCE_RE.search(text) is not None
            or has_travel_place_inventory_evidence(text)
        )
    if _INVENTORY_CAUSE_QUERY_RE.search(query):
        return _INVENTORY_CAUSE_EVIDENCE_RE.search(text) is not None
    if _INVENTORY_FRIEND_PLACE_QUERY_RE.search(query):
        return _INVENTORY_FRIEND_PLACE_EVIDENCE_RE.search(text) is not None
    if _INVENTORY_SHELTER_QUERY_RE.search(query):
        return _INVENTORY_SHELTER_EVIDENCE_RE.search(text) is not None
    return False


def _inventory_list_weak_evidence(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> bool:
    if not _is_inventory_list_candidate(query_reason=query_reason, item=item):
        return False
    if _inventory_list_exact_evidence(query=query, query_reason=query_reason, item=item):
        return False
    if _INVENTORY_POTTERY_QUERY_RE.search(query) and _INVENTORY_POTTERY_EVIDENCE_RE.search(
        item.text
    ):
        return True
    if _INVENTORY_GENERIC_WEAK_RE.search(item.text):
        return True
    if _inventory_query_has_specific_expected_slot(query):
        return relevance.distinctive_term_hits < 4 or relevance.unique_term_hits < 4
    return False


def _inventory_list_wrong_owner_evidence(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if not _is_inventory_list_candidate(query_reason=query_reason, item=item):
        return False
    if not _INVENTORY_POTTERY_QUERY_RE.search(query):
        return False
    return _INVENTORY_POTTERY_EVIDENCE_RE.search(item.text) is not None


def _inventory_query_has_specific_expected_slot(query: str) -> bool:
    return any(
        pattern.search(query)
        for pattern in (
            _INVENTORY_POTTERY_QUERY_RE,
            _INVENTORY_COUNTRY_QUERY_RE,
            _INVENTORY_CAUSE_QUERY_RE,
            _INVENTORY_FRIEND_PLACE_QUERY_RE,
            _INVENTORY_SHELTER_QUERY_RE,
        )
    )


def _is_inventory_list_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _INVENTORY_LIST_RERANK_REASONS:
        return True
    reason = _score_signal_reason(item)
    return reason in _INVENTORY_LIST_RERANK_REASONS


def _is_support_network_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _SUPPORT_NETWORK_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _SUPPORT_NETWORK_RERANK_REASONS


def _is_recommendation_followup_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _RECOMMENDATION_FOLLOWUP_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _RECOMMENDATION_FOLLOWUP_RERANK_REASONS


def _is_event_sequence_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    return _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="decomposition_event_sequence",
    ) or _EVENT_SEQUENCE_QUERY_RE.search(query) is not None


def _is_current_goal_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _CURRENT_GOAL_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _CURRENT_GOAL_RERANK_REASONS


def _is_positive_preference_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if _POSITIVE_PREFERENCE_NEGATIVE_QUERY_RE.search(query) is not None:
        return False
    if query_reason in _POSITIVE_PREFERENCE_RERANK_REASONS:
        return True
    if _score_signal_reason(item) in _POSITIVE_PREFERENCE_RERANK_REASONS:
        return True
    return _POSITIVE_PREFERENCE_QUERY_RE.search(query) is not None


def _is_outdoor_preference_candidate(*, query_reason: str, item: ContextItem) -> bool:
    return (
        query_reason in _OUTDOOR_PREFERENCE_RERANK_REASONS
        or _score_signal_reason(item) in _OUTDOOR_PREFERENCE_RERANK_REASONS
    )


def _is_commonality_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason in _COMMONALITY_RERANK_REASONS:
        return True
    if _score_signal_reason(item) in _COMMONALITY_RERANK_REASONS:
        return True
    return _COMMONALITY_QUERY_RE.search(query) is not None


def _is_family_hike_detail_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    return (
        query_reason in _FAMILY_HIKE_DETAIL_RERANK_REASONS
        or _score_signal_reason(item) in _FAMILY_HIKE_DETAIL_RERANK_REASONS
        or _FAMILY_HIKE_DETAIL_QUERY_RE.search(query) is not None
    )


def _is_temporal_camping_detail_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if _TEMPORAL_CAMPING_DETAIL_QUERY_RE.search(query) is None:
        return False
    return (
        query_reason in _TEMPORAL_CAMPING_DETAIL_RERANK_REASONS
        or _score_signal_reason(item) in _TEMPORAL_CAMPING_DETAIL_RERANK_REASONS
    )


def _is_relationship_status_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _RELATIONSHIP_STATUS_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _RELATIONSHIP_STATUS_RERANK_REASONS


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


def _is_age_birthday_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _AGE_BIRTHDAY_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _AGE_BIRTHDAY_RERANK_REASONS


def _is_birthplace_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _BIRTHPLACE_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _BIRTHPLACE_RERANK_REASONS


def _is_beach_or_mountains_candidate(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if _BEACH_OR_MOUNTAINS_QUERY_RE.search(query) is not None:
        return True
    if query_reason in _BEACH_OR_MOUNTAINS_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _BEACH_OR_MOUNTAINS_RERANK_REASONS


def _is_symbol_importance_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _SYMBOL_IMPORTANCE_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _SYMBOL_IMPORTANCE_RERANK_REASONS


def _is_item_purchase_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _ITEM_PURCHASE_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _ITEM_PURCHASE_RERANK_REASONS


def _is_post_event_emotion_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _POST_EVENT_EMOTION_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _POST_EVENT_EMOTION_RERANK_REASONS


def _event_sequence_anchor_terms(query: str) -> tuple[str, ...]:
    terms = []
    seen = set()
    for match in _EVENT_SEQUENCE_NAMED_ANCHOR_RE.finditer(query):
        term = match.group(0)
        if term in _EVENT_SEQUENCE_IGNORED_ANCHORS:
            continue
        normalized = term.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return tuple(terms)


def _event_sequence_anchor_hits(*, anchor_terms: tuple[str, ...], text: str) -> int:
    text_lower = text.casefold()
    return sum(
        1
        for term in anchor_terms
        if re.search(rf"\b{re.escape(term)}\b", text_lower)
    )


def _commonality_anchor_terms(query: str) -> tuple[str, ...]:
    terms = []
    seen = set()
    for match in _COMMONALITY_NAMED_ANCHOR_RE.finditer(query):
        term = match.group(0)
        if term in _COMMONALITY_IGNORED_ANCHORS:
            continue
        normalized = term.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return tuple(terms)


def _commonality_anchor_hits(*, anchor_terms: tuple[str, ...], text: str) -> int:
    text_lower = text.casefold()
    return sum(
        1
        for term in anchor_terms
        if re.search(rf"\b{re.escape(term)}\b", text_lower)
    )


def _commonality_who_else_signal(*, query: str, item: ContextItem) -> DomainRerankSignal:
    if _COMMONALITY_WHO_ELSE_QUERY_RE.search(query) is None:
        return DomainRerankSignal()
    anchor_terms = _commonality_anchor_terms(query)
    if len(anchor_terms) != 1:
        return DomainRerankSignal()
    if _text_has_any_anchor(anchor_terms=anchor_terms, text=item.text):
        return DomainRerankSignal(
            penalty=0.052,
            reason="commonality_original_person_noise",
        )
    if _COMMONALITY_WHO_ELSE_EVIDENCE_RE.search(item.text) is not None:
        return DomainRerankSignal(boost=0.034, reason="commonality_who_else_evidence")
    return DomainRerankSignal()


def _text_has_any_anchor(*, anchor_terms: tuple[str, ...], text: str) -> bool:
    text_lower = text.casefold()
    return any(re.search(rf"\b{re.escape(term)}\b", text_lower) for term in anchor_terms)


def _matches_query_or_score_signal_reason(
    *,
    query_reason: str,
    item: ContextItem,
    target_reason: str,
) -> bool:
    return query_reason == target_reason or _score_signal_reason(item) == target_reason


def _score_signal_reason(item: ContextItem) -> str:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    return str(signals.get("query_expansion_reason") or "").strip()


def _is_aggregation_query(query: str) -> bool:
    return bool(
        _AGGREGATION_COUNT_QUERY_RE.search(query)
        or _AGGREGATION_LIST_QUERY_RE.search(query)
    )


def _is_aggregation_list_query(query: str) -> bool:
    return _AGGREGATION_LIST_QUERY_RE.search(query) is not None


def _is_aggregation_context_item(item: ContextItem) -> bool:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    retrieval_source = str(diagnostics.get("retrieval_source") or "").strip()
    if retrieval_source == _AGGREGATION_RETRIEVAL_SOURCE:
        return True
    sources = diagnostics.get("retrieval_sources")
    if isinstance(sources, list | tuple | set):
        return _AGGREGATION_RETRIEVAL_SOURCE in {str(source) for source in sources}
    return False


def _aggregation_evidence_count(item: ContextItem) -> int:
    marker_count = len(set(_AGGREGATION_MARKER_RE.findall(item.text)))
    return max(marker_count, len(item.source_refs))


def _is_single_weak_count_evidence(item: ContextItem) -> bool:
    if _aggregation_evidence_count(item) >= 2:
        return False
    return _AGGREGATION_NUMERIC_ANSWER_RE.search(item.text) is None


def _is_single_list_evidence(*, query: str, item: ContextItem) -> bool:
    if _is_aggregation_context_item(item) or _aggregation_evidence_count(item) >= 2:
        return False
    if aggregation_answer_slot_count(query=query, text=item.text) == 1:
        return True
    return not _list_evidence_looks_multi_value(item.text)


def _list_evidence_looks_multi_value(text: str) -> bool:
    if len(set(_AGGREGATION_MARKER_RE.findall(text))) >= 2:
        return True
    if len(re.findall(r"\b(?:also|another|as\s+well|and)\b", text, re.IGNORECASE)) >= 1:
        return True
    return ";" in text or len(re.findall(r",", text)) >= 2

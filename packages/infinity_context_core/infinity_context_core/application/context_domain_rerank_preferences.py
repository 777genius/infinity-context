"""Goal, preference, recommendation and personal significance rerank policies."""

from __future__ import annotations

import re

from infinity_context_core.application.context_domain_rerank_legacy_contract import (
    DomainRerankSignal,
)
from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
    has_item_purchase_object_marker,
    has_item_purchase_temporal_or_media_marker,
    has_item_purchase_verb_marker,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_score_signal_rerank import (
    score_signal_reason as _score_signal_reason,
)
from infinity_context_core.application.dto import ContextItem

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

_RECOMMENDATION_FOLLOWUP_RERANK_REASONS = frozenset(
    (
        "book_suggestion_bridge",
        "decomposition_recommendation_source",
        "food_recipe_recommendation_bridge",
        "recommendation_source_bridge",
        "wellness_activity_effect_bridge",
    )
)

_BEACH_OR_MOUNTAINS_RERANK_REASONS = frozenset(("beach_or_mountains_inference_bridge",))

_ITEM_PURCHASE_RERANK_REASONS = frozenset(("item_purchase_bridge",))

_SYMBOL_IMPORTANCE_RERANK_REASONS = frozenset(("symbol_importance_bridge",))

_POST_EVENT_EMOTION_RERANK_REASONS = frozenset(("post_event_emotion_bridge",))

_RECOMMENDATION_FOLLOWUP_BOOK_RE = re.compile(
    r"\b(?:book|novel|memoir|story|read(?:ing)?|чит(?:аю|ал\w*|ает\w*)|книг\w*)\b",
    re.IGNORECASE,
)

_RECOMMENDATION_FOLLOWUP_SIGNAL_RE = re.compile(
    r"\b(?:recommend(?:ed|ation)?|suggest(?:ed|ion)?|told\s+me\s+about|"
    r"посоветовал\w*|порекомендовал\w*)\b",
    re.IGNORECASE,
)

_FOOD_RECIPE_RECOMMENDATION_EVIDENCE_RE = re.compile(
    r"\b(?:recipes?|meals?|foods?|dishes?|roasted\s+veg(?:etables?)?|"
    r"grilled\s+chicken|veggie\s+stir-fry|vegetable\s+stir-fry|"
    r"local\s+dishes|poutine|french\s+fries|chopsticks|sauce|"
    r"healthy\s+grilled|tasty\s+and\s+easy)\b",
    re.IGNORECASE,
)

_FOOD_RECIPE_RECOMMENDATION_SIGNAL_RE = re.compile(
    r"\b(?:recommend(?:ed|s|ation)?|suggest(?:ed|s|ion)?|share|shared|"
    r"try|trying|give\s+it\s+a\s+go|wanna\s+give|image\s+caption|"
    r"visual\s+query)\b",
    re.IGNORECASE,
)

_FOOD_RECIPE_RECOMMENDATION_WEAK_RE = re.compile(
    r"\b(?:diet|healthy|honeymoon|skiing|food|meal|recipe|restaurant|"
    r"container|photo|image)\b",
    re.IGNORECASE,
)

_WELLNESS_ACTIVITY_EFFECT_EVIDENCE_RE = re.compile(
    r"\b(?:yoga|stretch(?:ing)?|pilates|exercise|activity)\b"
    r"(?=.{0,140}\b(?:stress|staying\s+flexible|flexibility|flexible|diet|"
    r"help(?:ed|s|ing)?|alongside)\b)|"
    r"\b(?:stress|staying\s+flexible|flexibility|flexible|diet)\b"
    r"(?=.{0,140}\b(?:yoga|stretch(?:ing)?|pilates|exercise|activity)\b)",
    re.IGNORECASE | re.DOTALL,
)

_WELLNESS_ACTIVITY_EFFECT_WEAK_RE = re.compile(
    r"\b(?:stress|flexibility|flexible|diet|healthy|activity|exercise|"
    r"workout|movie|watch)\b",
    re.IGNORECASE,
)

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
    r"\b(?:felt|feel|feeling|realiz(?:e|ed)|learned|grateful|thankful|relieved|lucky|scared|"
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
        _is_recommendation_followup_candidate(query_reason=query_reason, item=item)
        and _RECOMMENDATION_FOLLOWUP_BOOK_RE.search(item.text) is not None
        and _RECOMMENDATION_FOLLOWUP_SIGNAL_RE.search(item.text) is not None
    ):
        return DomainRerankSignal()
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

def lifestyle_recommendation_rerank_signal(
    *,
    query_reason: str,
    item: ContextItem,
    relevance: QueryRelevance,
) -> DomainRerankSignal:
    if not _is_lifestyle_recommendation_candidate(
        query_reason=query_reason,
        item=item,
    ):
        return DomainRerankSignal()
    if (
        query_reason == "food_recipe_recommendation_bridge"
        or _score_signal_reason(item) == "food_recipe_recommendation_bridge"
    ):
        if _FOOD_RECIPE_RECOMMENDATION_EVIDENCE_RE.search(item.text) is None:
            if (
                relevance.distinctive_term_hits < 3
                and _FOOD_RECIPE_RECOMMENDATION_WEAK_RE.search(item.text) is not None
            ):
                return DomainRerankSignal(
                    penalty=0.036,
                    reason="food_recipe_recommendation_weak_evidence",
                )
            return DomainRerankSignal()
        rank_signal = (
            3.0
            if _FOOD_RECIPE_RECOMMENDATION_SIGNAL_RE.search(item.text) is not None
            else 2.0
        )
        return DomainRerankSignal(
            boost=0.046,
            reason="food_recipe_recommendation_evidence",
            rank_signal_key="food_recipe_recommendation_evidence",
            rank_signal=rank_signal,
        )
    if _WELLNESS_ACTIVITY_EFFECT_EVIDENCE_RE.search(item.text) is not None:
        return DomainRerankSignal(
            boost=0.052,
            reason="wellness_activity_effect_evidence",
            rank_signal_key="wellness_activity_effect_evidence",
            rank_signal=3.0,
        )
    if (
        relevance.distinctive_term_hits < 3
        and _WELLNESS_ACTIVITY_EFFECT_WEAK_RE.search(item.text) is not None
    ):
        return DomainRerankSignal(
            penalty=0.034,
            reason="wellness_activity_effect_weak_evidence",
        )
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

def _is_recommendation_followup_candidate(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason in _RECOMMENDATION_FOLLOWUP_RERANK_REASONS:
        return True
    return _score_signal_reason(item) in _RECOMMENDATION_FOLLOWUP_RERANK_REASONS

def _is_lifestyle_recommendation_candidate(
    *,
    query_reason: str,
    item: ContextItem,
) -> bool:
    return query_reason in {
        "food_recipe_recommendation_bridge",
        "wellness_activity_effect_bridge",
    } or _score_signal_reason(item) in {
        "food_recipe_recommendation_bridge",
        "wellness_activity_effect_bridge",
    }

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

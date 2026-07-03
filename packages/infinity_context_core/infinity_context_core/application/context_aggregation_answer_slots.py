"""Answer-slot diversity detection for aggregation retrieval reranking."""

from __future__ import annotations

import re

_PERSON_LIST_QUERY_RE = re.compile(
    r"\bwho\b(?=.{0,120}\b(?:friends?|people|person|volunteer(?:s|ed|ing)?|"
    r"met|helped|worked\s+with|customers?|clients?|colleagues?|teammates?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PERSON_NAME_RE = re.compile(
    r"\b[A-Z][a-z][A-Za-z'_-]{1,39}(?:\s+[A-Z][a-z][A-Za-z'_-]{1,39})?\b"
)
_PERSON_SLOT_STOPWORDS = frozenset(
    {
        "he",
        "her",
        "him",
        "how",
        "i",
        "it",
        "related",
        "she",
        "session",
        "that",
        "the",
        "them",
        "there",
        "they",
        "this",
        "who",
        "what",
        "when",
        "where",
        "which",
        "why",
        "we",
        "you",
    }
)

_SLOT_RULES: tuple[
    tuple[re.Pattern[str], tuple[tuple[str, re.Pattern[str]], ...]],
    ...,
] = (
    (
        re.compile(r"\b(?:pottery|ceramic|clay)\b", re.IGNORECASE),
        (
            (
                "pottery_bowl",
                re.compile(r"\b(?:bowls?|black\s+and\s+white\s+flower)\b", re.IGNORECASE),
            ),
            (
                "pottery_cup",
                re.compile(r"\b(?:cups?|mugs?|dog\s+face)\b", re.IGNORECASE),
            ),
        ),
    ),
    (
        re.compile(r"\b(?:hikes?|hiking)\b", re.IGNORECASE),
        (
            (
                "hike_sunset_other_day",
                re.compile(
                    r"\b(?:gorgeous\s+sunset|sunset.{0,50}hiking|other\s+day)\b",
                    re.IGNORECASE,
                ),
            ),
            (
                "hike_waterfall_spot",
                re.compile(
                    r"\b(?:waterfall|spot\s+on\s+the\s+hike|"
                    r"rush\s+of\s+(?:the\s+)?water)\b",
                    re.IGNORECASE,
                ),
            ),
            (
                "hike_weekend_trail",
                re.compile(r"\b(?:buddies|new\s+trail|this\s+weekend)\b", re.IGNORECASE),
            ),
            (
                "hike_summer_fort_wayne",
                re.compile(r"\b(?:fort\s+wayne|last\s+summer)\b", re.IGNORECASE),
            ),
        ),
    ),
    (
        re.compile(
            r"\b(?:lgbtq\+?|lgbt|transgender|trans)\b"
            r"(?=.{0,120}\b(?:events?|community|participat\w*|ways?|"
            r"activis\w*|advocacy|mentorship|mentor\w*|pride|art\s+show|"
            r"support\s+group)\b)|"
            r"\b(?:events?|community|participat\w*|ways?|activis\w*|"
            r"advocacy|mentorship|mentor\w*|pride|art\s+show|support\s+group)\b"
            r"(?=.{0,120}\b(?:lgbtq\+?|lgbt|transgender|trans)\b)",
            re.IGNORECASE | re.DOTALL,
        ),
        (
            ("lgbtq_support_group", re.compile(r"\bsupport\s+group\b", re.IGNORECASE)),
            ("lgbtq_pride_parade", re.compile(r"\bpride\s+parade\b", re.IGNORECASE)),
            (
                "lgbtq_school_speech",
                re.compile(
                    r"\b(?:school\s+(?:speech|talk)|speech.{0,40}school)\b",
                    re.IGNORECASE,
                ),
            ),
            (
                "lgbtq_advocacy_campaign",
                re.compile(r"\b(?:advocacy\s+campaign|lgbtq\s+rights)\b", re.IGNORECASE),
            ),
            (
                "lgbtq_mentorship_program",
                re.compile(
                    r"\b(?:mentorship|mentoring|mentor(?:ed|s)?)\b"
                    r"(?=.{0,100}\b(?:lgbtq|lgbt|transgender|trans)\b)|"
                    r"\b(?:lgbtq|lgbt|transgender|trans)\b"
                    r"(?=.{0,100}\b(?:mentorship|mentoring|mentor(?:ed|s)?)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
            (
                "lgbtq_art_show",
                re.compile(
                    r"\b(?:lgbtq|lgbt|transgender|trans)\b(?=.{0,100}\bart\s+show\b)|"
                    r"\bart\s+show\b(?=.{0,100}\b(?:lgbtq|lgbt|transgender|trans)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
            (
                "lgbtq_activist_group",
                re.compile(
                    r"\b(?:lgbtq|lgbt|lgbtq\s+rights)\b"
                    r"(?=.{0,100}\bactivist\s+group\b)|"
                    r"\bactivist\s+group\b(?=.{0,100}\b(?:lgbtq|lgbt|lgbtq\s+rights)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
            (
                "lgbtq_youth_center",
                re.compile(
                    r"\b(?:lgbtq|lgbt|transgender|trans)\b"
                    r"(?=.{0,100}\byouth\s+center\b)|"
                    r"\byouth\s+center\b"
                    r"(?=.{0,100}\b(?:lgbtq|lgbt|transgender|trans)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
            (
                "lgbtq_counseling_workshop",
                re.compile(
                    r"\b(?:lgbtq|lgbt|transgender|trans)\b"
                    r"(?=.{0,120}\bcounsel(?:ing|ling)\s+workshop\b)|"
                    r"\bcounsel(?:ing|ling)\s+workshop\b"
                    r"(?=.{0,120}\b(?:lgbtq|lgbt|transgender|trans)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
            (
                "transgender_poetry_reading",
                re.compile(r"\btransgender\s+poetry\s+reading\b", re.IGNORECASE),
            ),
            (
                "transgender_conference",
                re.compile(r"\btransgender\s+conference\b", re.IGNORECASE),
            ),
            (
                "transgender_youth_talent_show",
                re.compile(
                    r"\b(?:youth\s+center|talent\s+show|band.{0,40}stage)\b",
                    re.IGNORECASE,
                ),
            ),
        ),
    ),
    (
        re.compile(r"\b(?:pets?|animals?)\b", re.IGNORECASE),
        (
            ("pet_dog", re.compile(r"\b(?:dog|puppy|new\s+addition)\b", re.IGNORECASE)),
            ("pet_turtle", re.compile(r"\b(?:turtles?|critters?|basking)\b", re.IGNORECASE)),
        ),
    ),
    (
        re.compile(
            r"\bturtles?\b(?=.{0,80}\b(?:how\s+many|count|number|total)\b)|"
            r"\b(?:how\s+many|count|number|total)\b(?=.{0,80}\bturtles?\b)",
            re.IGNORECASE | re.DOTALL,
        ),
        (
            ("turtle_two", re.compile(r"\btwo\s+turtles?\b", re.IGNORECASE)),
            ("turtle_third", re.compile(r"\bthird\s+turtle\b|\bnew\s+friend\b", re.IGNORECASE)),
            ("turtle_three", re.compile(r"\bthree\s+turtles?\b", re.IGNORECASE)),
        ),
    ),
    (
        re.compile(r"\b(?:friends?|made\s+friends?)\b", re.IGNORECASE),
        (
            (
                "friend_place_volunteering",
                re.compile(r"\b(?:homeless\s+shelter|fellow\s+volunteers?)\b", re.IGNORECASE),
            ),
            (
                "friend_place_gym",
                re.compile(r"\b(?:gym|workout\s+routine)\b", re.IGNORECASE),
            ),
            (
                "friend_place_church",
                re.compile(r"\b(?:church|faith\s+community|local\s+church)\b", re.IGNORECASE),
            ),
        ),
    ),
    (
        re.compile(
            r"\b(?:european\s+countries|countries|england|spain)\b"
            r"(?=.{0,100}\b(?:been\s+to|visited|trip|travel|abroad|european)\b)|"
            r"\b(?:been\s+to|visited|trip|travel|abroad)\b"
            r"(?=.{0,100}\b(?:european\s+countries|countries|england|spain)\b)",
            re.IGNORECASE | re.DOTALL,
        ),
        (
            ("travel_country_england", re.compile(r"\bengland\b", re.IGNORECASE)),
            ("travel_country_spain", re.compile(r"\bspain\b", re.IGNORECASE)),
        ),
    ),
    (
        re.compile(
            r"\bshelters?\b(?=.{0,100}\bvolunteer)|"
            r"\bvolunteer\b(?=.{0,100}\bshelters?\b)",
            re.IGNORECASE | re.DOTALL,
        ),
        (
            (
                "volunteer_shelter_homeless",
                re.compile(r"\bhomeless\s+shelter\b", re.IGNORECASE),
            ),
            (
                "volunteer_shelter_dog",
                re.compile(r"\bdog\s+shelter\b", re.IGNORECASE),
            ),
        ),
    ),
    (
        re.compile(r"\b(?:causes?|support(?:ing)?|passionate)\b", re.IGNORECASE),
        (
            ("cause_veterans", re.compile(r"\b(?:veterans?|military)\b", re.IGNORECASE)),
            (
                "cause_education",
                re.compile(r"\b(?:education|schools?|education\s+reform)\b", re.IGNORECASE),
            ),
            (
                "cause_infrastructure",
                re.compile(r"\b(?:infrastructure|infrastructure\s+development)\b", re.IGNORECASE),
            ),
        ),
    ),
    (
        re.compile(r"\b(?:events?|veterans?|military)\b", re.IGNORECASE),
        (
            (
                "veterans_petition",
                re.compile(
                    r"\b(?:petition|signatures?)\b(?=.{0,160}\b(?:veterans?|military)\b)|"
                    r"\b(?:veterans?|military)\b(?=.{0,160}\b(?:petition|signatures?)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
            (
                "veterans_charity_run",
                re.compile(
                    r"\b(?:5k|charity\s+run|run|funds?|raise(?:d)?)\b"
                    r"(?=.{0,180}\b(?:veterans?|military|families)\b)|"
                    r"\b(?:veterans?|military|families)\b"
                    r"(?=.{0,180}\b(?:5k|charity\s+run|run|funds?|raise(?:d)?)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
            (
                "veterans_march",
                re.compile(
                    r"\b(?:march(?:ing)?|parade)\b"
                    r"(?=.{0,160}\b(?:veterans?|military|rights?)\b)|"
                    r"\b(?:veterans?|military|rights?)\b"
                    r"(?=.{0,160}\b(?:march(?:ing)?|parade)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
            (
                "veterans_hospital",
                re.compile(
                    r"\b(?:veterans?'?\s+hospital|hospital)\b"
                    r"(?=.{0,160}\b(?:veterans?|military)\b)|"
                    r"\b(?:veterans?|military)\b(?=.{0,160}\bhospital\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
        ),
    ),
    (
        re.compile(
            r"\b(?:events?|fundraisers?|fundraising|funraisers?|funraising|shelter)\b",
            re.IGNORECASE,
        ),
        (
            (
                "fundraiser_chili_cookoff",
                re.compile(r"\bchili\s+cook[-\s]?off\b", re.IGNORECASE),
            ),
            (
                "fundraiser_tournament",
                re.compile(
                    r"\btournament\b"
                    r"(?=.{0,180}\b(?:fundraiser|fundraising|shelter|homeless)\b)|"
                    r"\b(?:fundraiser|fundraising|shelter|homeless)\b"
                    r"(?=.{0,180}\btournament\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
            (
                "fundraiser_shelter_setup",
                re.compile(
                    r"\b(?:getting\s+ready|preparing|planning|organizing|"
                    r"cover\s+basic\s+needs|raise\s+enough)\b"
                    r"(?=.{0,180}\b(?:fundraiser|fundraising|shelter|homeless)\b)|"
                    r"\b(?:fundraiser|fundraising|shelter|homeless)\b"
                    r"(?=.{0,180}\b(?:getting\s+ready|preparing|planning|"
                    r"organizing|cover\s+basic\s+needs|raise\s+enough)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
        ),
    ),
    (
        re.compile(
            r"\b(?:gratitude|appreciation|thank(?:s|ful)?|notes?|letters?|wrote|written)\b",
            re.IGNORECASE,
        ),
        (
            (
                "gratitude_note_writer",
                re.compile(
                    r"\b(?:residents?|person|someone)\b"
                    r"(?=.{0,180}\b(?:wrote|written|note|letter|gratitude|"
                    r"appreciation|thank(?:s|ful)?)\b)|"
                    r"\b(?:wrote|written|note|letter|gratitude|appreciation|"
                    r"thank(?:s|ful)?)\b"
                    r"(?=.{0,180}\b(?:residents?|person|someone|shelter|support)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
        ),
    ),
    (
        re.compile(
            r"\b(?:shelter|foods?|meals?|baked\s+goods?|drop(?:ped)?\s+off|donat(?:e|ed))\b",
            re.IGNORECASE,
        ),
        (
            (
                "shelter_food_dropoff",
                re.compile(
                    r"\b(?:homeless\s+shelter|shelter)\b"
                    r"(?=.{0,200}\b(?:drop(?:ped)?\s+off|brought|donat(?:e|ed)|"
                    r"baked?|baking|cakes?|baked\s+goods?|desserts?)\b)|"
                    r"\b(?:drop(?:ped)?\s+off|brought|donat(?:e|ed)|baked?|"
                    r"baking|cakes?|baked\s+goods?|desserts?)\b"
                    r"(?=.{0,200}\b(?:homeless\s+shelter|shelter)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
        ),
    ),
    (
        re.compile(
            r"\b(?:skills?|learn|teach|teaching|taught|helped|coach|tips|improve)\b",
            re.IGNORECASE,
        ),
        (
            (
                "skill_recipe_teaching",
                re.compile(
                    r"\b(?:teach(?:ing)?|taught|show(?:ed|ing)?|"
                    r"help(?:ed|ing)?)\b"
                    r"(?=.{0,200}\b(?:how\s+to\s+make|recipes?|cooking|desserts?|"
                    r"baking|make\s+this)\b)|"
                    r"\b(?:recipes?|cooking|desserts?|baking|how\s+to\s+make)\b"
                    r"(?=.{0,200}\b(?:teach(?:ing)?|taught|show(?:ed|ing)?|"
                    r"help(?:ed|ing)?)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
            (
                "skill_game_coaching",
                re.compile(
                    r"\b(?:tips?|coach(?:ed|ing)?|teach(?:ing)?|taught|"
                    r"help(?:ed|ing)?)\b"
                    r"(?=.{0,200}\b(?:improve|practice|learn|skills?|game|"
                    r"gaming|score|scores?|tournament)\b)|"
                    r"\b(?:improve|practice|learn|skills?|game|gaming|score|"
                    r"scores?|tournament)\b"
                    r"(?=.{0,200}\b(?:tips?|coach(?:ed|ing)?|teach(?:ing)?|"
                    r"taught|help(?:ed|ing)?)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
        ),
    ),
    (
        re.compile(
            r"\b(?:games?|winning|won|wins?|victor(?:y|ies)|count|mentioned)\b",
            re.IGNORECASE,
        ),
        (
            (
                "game_win_result",
                re.compile(
                    r"\b(?:games?|match|team|basketball|court)\b"
                    r"(?=.{0,220}\b(?:won|win|winning|victor(?:y|ies)|"
                    r"pulled\s+off|scored|points?|shot|basket|tight\s+score|"
                    r"career)\b)|"
                    r"\b(?:won|win|winning|victor(?:y|ies)|pulled\s+off|scored|"
                    r"points?|shot|basket|tight\s+score)\b"
                    r"(?=.{0,220}\b(?:games?|match|team|basketball|court|career)\b)",
                    re.IGNORECASE | re.DOTALL,
                ),
            ),
        ),
    ),
    (
        re.compile(r"\b(?:music|concerts?)\b", re.IGNORECASE),
        (
            (
                "music_live_event",
                re.compile(r"\blive\s+music(?:\s+event)?\b", re.IGNORECASE),
            ),
            (
                "music_violin_concert",
                re.compile(r"\bviolin\s+concert\b", re.IGNORECASE),
            ),
            (
                "music_concert",
                re.compile(r"\b(?:concert|festival|show|performance)\b", re.IGNORECASE),
            ),
        ),
    ),
    (
        re.compile(r"\b(?:areas?|states?|places?|vacation(?:ed)?|been\s+to)\b", re.IGNORECASE),
        (
            ("place_florida", re.compile(r"\bflorida\b", re.IGNORECASE)),
            ("place_oregon", re.compile(r"\boregon\b", re.IGNORECASE)),
            ("place_east_coast", re.compile(r"\beast\s+coast\b", re.IGNORECASE)),
            (
                "place_pacific_northwest",
                re.compile(r"\bpacific\s+northwest\b|\bnorthwest\b", re.IGNORECASE),
            ),
        ),
    ),
    (
        re.compile(r"\b(?:outdoor\s+activities?|activities?|colleagues?)\b", re.IGNORECASE),
        (
            ("outdoor_waterfall", re.compile(r"\bwaterfall\b", re.IGNORECASE)),
            ("outdoor_hiking", re.compile(r"\bhik(?:e|ing)\b", re.IGNORECASE)),
            (
                "outdoor_mountaineering",
                re.compile(r"\bmountaineering\b", re.IGNORECASE),
            ),
            ("outdoor_picnic", re.compile(r"\bpicnic\b", re.IGNORECASE)),
            ("outdoor_camping", re.compile(r"\bcamping\b", re.IGNORECASE)),
        ),
    ),
    (
        re.compile(
            r"\b(?:foods?|recipes?|meals?|dishes?|desserts?|baked\s+goods?|baking)\b",
            re.IGNORECASE,
        ),
        (
            (
                "dessert_cake",
                re.compile(
                    r"\b(?:cakes?|cupcakes?|frosting|strawberry\s+filling)\b",
                    re.IGNORECASE,
                ),
            ),
            (
                "dessert_ice_cream",
                re.compile(r"\b(?:ice\s*cream|icecream)\b", re.IGNORECASE),
            ),
            (
                "dessert_dairy_free",
                re.compile(
                    r"\b(?:dairy[-\s]?free|coconut\s+milk|coconut\s+cream|"
                    r"lactose\s+intolerant)\b",
                    re.IGNORECASE,
                ),
            ),
            (
                "dessert_recipe",
                re.compile(
                    r"\b(?:desserts?|baking|bake(?:d|s|r)?|recipes?|"
                    r"sweet\s+treats?)\b",
                    re.IGNORECASE,
                ),
            ),
            (
                "vegetable_recipe",
                re.compile(
                    r"\b(?:roasted\s+veg(?:etables?)?|grilled\s+vegetables?|"
                    r"vegetable\s+recipe|veg\s+recipe)\b",
                    re.IGNORECASE,
                ),
            ),
            (
                "chicken_stir_fry",
                re.compile(
                    r"\b(?:grilled\s+chicken|veggie\s+stir-fry|"
                    r"vegetable\s+stir-fry|chicken\s+and\s+veggie)\b",
                    re.IGNORECASE,
                ),
            ),
            (
                "local_dish",
                re.compile(
                    r"\b(?:local\s+dishes|poutine|french\s+fries|"
                    r"regional\s+dishes|local\s+food)\b",
                    re.IGNORECASE,
                ),
            ),
        ),
    ),
    (
        re.compile(
            r"\b(?:interests?|hobbies?|activities?|common|shared|both|similar)\b",
            re.IGNORECASE,
        ),
        (
            (
                "interest_movies",
                re.compile(
                    r"\b(?:watch(?:ing)?\s+movies?|movies?|films?|dramas?|"
                    r"romcoms?|sci[-\s]?fi|action\s+movies?)\b",
                    re.IGNORECASE,
                ),
            ),
        ),
    ),
)


def aggregation_answer_slot_count(*, query: str, text: str) -> int:
    return len(aggregation_answer_slots(query=query, text=text))


def aggregation_answer_slots(*, query: str, text: str) -> frozenset[str]:
    slots: set[str] = set()
    for query_pattern, slot_patterns in _SLOT_RULES:
        if query_pattern.search(query) is None:
            continue
        for slot, text_pattern in slot_patterns:
            if text_pattern.search(text) is not None:
                slots.add(slot)
    slots.update(_generic_person_list_slots(query=query, text=text))
    return frozenset(slots)


def _generic_person_list_slots(*, query: str, text: str) -> frozenset[str]:
    if _PERSON_LIST_QUERY_RE.search(query) is None:
        return frozenset()
    query_names = {
        _normalized_person_slot(name)
        for name in _PERSON_NAME_RE.findall(query)
        if name.casefold() not in _PERSON_SLOT_STOPWORDS
    }
    slots: set[str] = set()
    for name in _PERSON_NAME_RE.findall(text):
        normalized = _normalized_person_slot(name)
        if normalized in query_names or normalized in _PERSON_SLOT_STOPWORDS:
            continue
        slots.add(f"person:{normalized}")
    return frozenset(slots)


def _normalized_person_slot(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").split())

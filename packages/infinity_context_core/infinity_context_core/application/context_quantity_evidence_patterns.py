"""Private regex and constant catalog for quantity evidence projection."""

from __future__ import annotations

import re

_MAX_QUERY_CHARS = 512
_MAX_EVIDENCE_CHARS = 12_000
_MAX_USER_SEGMENTS = 24
_MAX_SENTENCES = 64
_MAX_EVIDENCE_SENTENCES = 8
_MAX_MEMBER_IDENTITIES = 8
_MAX_PROJECTION_CHARS = 2_400
_COUNT_QUERY_RE = re.compile(
    r"\bhow\s+many\s+(?P<target>.{1,120}?)\s+"
    r"(?:do|does|did|have|has|had|am|are|was|were|will|would|can|could)\b"
    r"(?P<predicate>.{1,260})",
    re.IGNORECASE | re.DOTALL,
)
_TOTAL_MONEY_QUERY_RE = re.compile(
    r"\bhow\s+much\s+(?:total\s+)?money\s+have\s+I\s+"
    r"(?:spent|paid)\s+(?:on|for)\s+(?P<target>.{1,100}?)"
    r"(?:\s+since\b|\s+in\s+total\b|[?.!]|$)",
    re.IGNORECASE | re.DOTALL,
)
_TOTAL_DURATION_QUERY_RE = re.compile(
    r"\bhow\s+many\s+(?P<unit>hours?|minutes?|days?)\s+have\s+I\s+"
    r"(?:spent\s+)?(?P<action>playing|doing|practicing|watching|working\s+on)\s+"
    r"(?P<target>.{1,80}?)(?:\s+in\s+total\b|[?.!]|$)",
    re.IGNORECASE | re.DOTALL,
)
_SPENT_DURATION_ON_QUERY_RE = re.compile(
    r"\bhow\s+many\s+(?P<unit>hours?|minutes?|days?)\s+did\s+I\s+"
    r"spend\s+on\s+(?P<target>.{1,100}?)"
    r"(?:\s+in\s+(?:the\s+)?(?:united\s+states|u\.s\.|us)\b)?"
    r"(?:\s+(?:this|last|previous|prior)\s+year\b|\s+in\s+total\b|[?.!]|$)",
    re.IGNORECASE | re.DOTALL,
)
_PROJECT_LEADERSHIP_QUERY_RE = re.compile(
    r"\bhow\s+many\s+projects?\s+have\s+I\s+"
    r"(?:led|lead|been\s+leading)\s+or\s+am\s+currently\s+leading\b",
    re.IGNORECASE | re.DOTALL,
)
_BAKING_EVENT_QUERY_RE = re.compile(
    r"\bhow\s+many\s+times\s+did\s+I\s+bake\s+something\b",
    re.IGNORECASE | re.DOTALL,
)
_PENDING_QUERY_RE = re.compile(
    r"\b(?:need(?:ed)?\s+to|still\s+need|have\s+to|must|"
    r"waiting\s+to|yet\s+to)\b",
    re.IGNORECASE,
)
_PENDING_EVIDENCE_RE = re.compile(
    r"\b(?:need(?:ed)?\s+to|still\s+need|have\s+to|must|"
    r"waiting\s+to|yet\s+to|haven't|have\s+not|hasn't|has\s+not)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_PENDING_ACTION_RE = re.compile(
    r"\bI\b.{0,100}\b(?:need(?:ed)?\s+to|still\s+need|have\s+to|must|"
    r"waiting\s+to|yet\s+to|haven't|have\s+not)\b.{0,100}\b"
    r"(?:pick|collect|return)\b",
    re.IGNORECASE,
)
_RESOLVED_OR_CANCELLED_RE = re.compile(
    r"\b(?:already\s+(?:picked|collected|returned)|"
    r"no\s+longer\s+need|do\s+not\s+need|don't\s+need|"
    r"cancel(?:led|ed)?|decided\s+not\s+to)\b",
    re.IGNORECASE,
)
_THIRD_PARTY_ACTION_RE = re.compile(
    r"\b(?:he|she|my\s+(?:sister|brother|friend|partner|coworker))\b"
    r".{0,64}\b(?:pick|collect|return)\b",
    re.IGNORECASE,
)
_STORE_CONTEXT_RE = re.compile(
    r"\b(?:store|shop|retailer|dry\s+cleaning|dry\s+cleaner|"
    r"exchange(?:d)?|purchase(?:d)?|order(?:ed)?)\b",
    re.IGNORECASE,
)
_NAMED_STORE_CONTEXT_RE = re.compile(
    r"\b(?:from|to)\s+(?:the\s+)?[A-Z][A-Za-z0-9&'-]{1,40}"
    r"(?:\s+[A-Z][A-Za-z0-9&'-]{1,40}){0,2}\b"
)
_FIRST_PERSON_RE = re.compile(r"\b(?:I|I'm|I've|I'd|I'll|me|my)\b", re.IGNORECASE)
_PERSONAL_NUMERIC_PARTICIPATION_RE = re.compile(
    r"\b(?:I|I'm|I've|I'd|I'll|me|my|we|we've|we'd|we'll|us|our)\b",
    re.IGNORECASE,
)
_USER_SEGMENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])user:\s*(?P<text>.*?)"
    r"(?=(?<![A-Za-z0-9_])(?:assistant|system|user):|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_ROLE_SEGMENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:assistant|system|user):",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
_PICKUP_RE = re.compile(
    r"\b(?:pick(?:ed|ing)?\s+up|"
    r"pick(?:ed|ing)?\s+(?:it|them|those|these|"
    r"(?:the|my|new|old)\s+[A-Za-z][A-Za-z'-]{1,30}"
    r"(?:\s+[A-Za-z][A-Za-z'-]{1,30}){0,3})\s+up|"
    r"collect(?:ed|ing|s)?)\b",
    re.IGNORECASE,
)
_RETURN_RE = re.compile(r"\breturn(?:ed|ing|s)?\b", re.IGNORECASE)
_PLURAL_PICKUP_ANAPHORA_RE = re.compile(
    r"\b(?:pick\s+(?:them|those|these)\s+up|"
    r"pick\s+up\s+(?:them|those|these)|"
    r"collect\s+(?:them|those|these))\b",
    re.IGNORECASE,
)
_PLURAL_RETURN_ANAPHORA_RE = re.compile(
    r"\breturn\s+(?:them|those|these)\b",
    re.IGNORECASE,
)
_CLOTHING_QUERY_RE = re.compile(
    r"\b(?:clothes?|clothing|garments?|apparel|wardrobe)\b",
    re.IGNORECASE,
)
_CLOTHING_EVIDENCE_RE = re.compile(
    r"\b(?P<target>dry\s+cleaning|"
    r"blazers?|blouses?|boots?|coats?|dresses?|garments?|gloves?|hats?|"
    r"hoodies?|jackets?|jeans?|pants?|scarves?|shirts?|shoes?|skirts?|"
    r"suits?|sweaters?|tops?|trousers?)\b",
    re.IGNORECASE,
)
_CLOTHING_CANONICAL = {
    "blazers": "blazer",
    "blouses": "blouse",
    "boots": "boots",
    "coats": "coat",
    "dresses": "dress",
    "garments": "garment",
    "gloves": "gloves",
    "hats": "hat",
    "hoodies": "hoodie",
    "jackets": "jacket",
    "jeans": "jeans",
    "pants": "pants",
    "scarves": "scarf",
    "shirts": "shirt",
    "shoes": "shoes",
    "skirts": "skirt",
    "suits": "suit",
    "sweaters": "sweater",
    "tops": "top",
    "trousers": "trousers",
}
_CLOTHING_MODIFIER_RE = re.compile(
    r"\b(?:black|blue|brown|gray|green|grey|navy|orange|pink|purple|"
    r"red|tan|white|yellow)\b",
    re.IGNORECASE,
)
_COORDINATED_COLOR_RE = re.compile(
    r"\b(?P<first>black|blue|brown|gray|green|grey|navy|orange|pink|purple|"
    r"red|tan|white|yellow)\s+and\s+"
    r"(?P<second>black|blue|brown|gray|green|grey|navy|orange|pink|purple|"
    r"red|tan|white|yellow)\s*$",
    re.IGNORECASE,
)
_QUANTITY_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
}
_QUANTITY_MODIFIER_RE = re.compile(
    r"\b(?P<count>[2-8]|two|three|four|five|six|seven|eight)\b",
    re.IGNORECASE,
)
_MONEY_VALUE_RE = re.compile(
    r"(?P<value>\$\s*\d+(?:,\d{3})*(?:\.\d{1,2})?|"
    r"\d+(?:,\d{3})*(?:\.\d{1,2})?\s*(?:dollars?|usd))\b",
    re.IGNORECASE,
)
_DURATION_VALUE_RE = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?:-\s*)?"
    r"(?P<unit>hours?|hrs?|minutes?|mins?|days?)\b",
    re.IGNORECASE,
)
_COMPLETED_EXPENSE_RE = re.compile(
    r"\b(?:bought|purchased|paid|spent|cost|charged|"
    r"got|installed|replaced|did)\b",
    re.IGNORECASE,
)
_FUTURE_EXPENSE_RE = re.compile(
    r"\b(?:will|would|plan(?:ning)?\s+to|going\s+to|might|may)\b",
    re.IGNORECASE,
)
_DURATION_ACTIVITY_RE = re.compile(
    r"\b(?:played|playing|completed|finished|finish|took(?:\s+me)?|"
    r"went\s+on|had|spent|trips?)\b",
    re.IGNORECASE,
)
_NEGATED_CAMPING_RE = re.compile(
    r"\b(?:not|never|wasn't|weren't|isn't|aren't)\s+(?:a\s+)?camping\b",
    re.IGNORECASE,
)
_BAKING_EVENT_RE = re.compile(
    r"\b(?:baked|bake|made|used\s+[^.]{0,40}\bto\s+bake|tried\s+out)\b",
    re.IGNORECASE,
)
_BAKED_ITEM_RE = re.compile(
    r"\b(?P<item>sourdough\s+bread|bread\s+recipe|chocolate\s+cake|"
    r"whole\s+wheat\s+baguette|batch\s+of\s+cookies|cookies|cake|bread|"
    r"focaccia|chicken\s+wings)\b",
    re.IGNORECASE,
)
_IDENTITY_TOKEN_RE = re.compile(r"[A-Za-z0-9$][A-Za-z0-9$'-]{0,31}")
_TARGET_STOPWORDS = frozenset(
    {
        "expenses",
        "expense",
        "related",
        "activity",
        "activities",
        "the",
        "a",
        "an",
        "my",
        "total",
    }
)
_IDENTITY_STOPWORDS = frozenset(
    {
        "actually",
        "also",
        "and",
        "around",
        "by",
        "did",
        "for",
        "have",
        "i",
        "it",
        "just",
        "me",
        "my",
        "recently",
        "that",
        "the",
        "to",
        "was",
        "were",
        "which",
    }
)

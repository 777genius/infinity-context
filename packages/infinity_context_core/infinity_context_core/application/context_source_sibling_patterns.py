"""Source-sibling evidence-pattern and policy catalogs."""

from __future__ import annotations

import re

_SOURCE_GROUP_SIBLING_SCORES = {
    1: 0.955,
    2: 0.948,
    3: 0.935,
    4: 0.922,
    5: 0.914,
}
_SOURCE_GROUP_PRIMARY_SEED_SCORE = 0.968
_MAX_SOURCE_GROUPS = 32
_MAX_SOURCE_SIBLING_GROUPS = 20
_MAX_SOURCE_GROUP_SIBLING_ITEMS = 32
_MAX_SOURCE_SIBLING_CANDIDATES = 1024
_SOURCE_SIBLING_CANDIDATES_PER_ITEM = 12
_SOURCE_SIBLING_CANDIDATES_PER_GROUP = 32
_MAX_SOURCE_SIBLING_COMPANION_EXTRA_ITEMS = 6
_COMMON_INTEREST_SOURCE_SIBLING_REASONS = frozenset(
    {
        "commonality_interest_bridge",
        "hobby_interest_bridge",
    }
)
_COMMON_INTEREST_ANSWER_SLOT_QUERY = (
    "common shared similar hobbies interests watching movies films desserts recipes "
    "baking foods animals pets turtles reptiles animal affinity"
)
_COMMON_INTEREST_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:share|shared|common|similar|interests?|hobbies?)\b",
    re.IGNORECASE,
)
_CREATIVE_WORK_COUNT_SOURCE_SIBLING_REASONS = frozenset(
    {
        "creative-writing-inventory-bridge",
        "decomposition-quantity-count",
        "quantity-enumeration-bridge",
        "screenplay-count-bridge",
        "source-sibling-answer-evidence",
    }
)
_COMMON_INTEREST_ANIMAL_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:animals?|pets?|turtles?|reptiles?)\b",
    re.IGNORECASE,
)
_COMMON_INTEREST_ANIMAL_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:turtles?|pets?|animals?|reptiles?)\b"
    r"(?=.{0,220}\b(?:drawn|like|likes|love|loves|enjoys?|prefer|"
    r"unique|slow\s+pace|low[-\s]?maintenance|calming|calm|peace|joy|"
    r"companion|resilien(?:ce|t)|inspir(?:e|es|ed|ing)|strength|"
    r"perseverance|motivat(?:e|es|ed|ing|ion))\b)|"
    r"\b(?:drawn|like|likes|love|loves|enjoys?|prefer|calming|calm|"
    r"peace|joy|companion|resilien(?:ce|t)|inspir(?:e|es|ed|ing)|"
    r"strength|perseverance|motivat(?:e|es|ed|ing|ion))\b"
    r"(?=.{0,220}\b(?:turtles?|pets?|animals?|reptiles?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_COMMON_INTEREST_AFFINITY_REPLY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:make\s+me\s+think\s+of\s+strength\s+and\s+perseverance|"
    r"help\s+motivate\s+me|helps\s+motivate\s+me|"
    r"motivate\s+me\s+in\s+tough\s+times|"
    r"glad\s+you\s+find\s+that\s+inspiring|find\s+that\s+inspiring)\b",
    re.IGNORECASE,
)
_MOVIE_SEEN_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:movies?|films?)\b(?=.{0,120}\b(?:seen|watched|saw|both)\b)|"
    r"\b(?:seen|watched|saw|both)\b(?=.{0,120}\b(?:movies?|films?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_MOVIE_SEEN_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?i:watched|seen|saw|watches)\s+"
    r"(?:[\"'][^\"'\n]{2,90}[\"']|[A-Z][A-Za-z0-9'’-]+"
    r"(?:\s+[A-Z][A-Za-z0-9'’-]+){0,6})(?=$|[\s,.;:!?])",
)
_MOVIE_SEEN_QUESTION_ONLY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:seen|watch(?:ed|ing)?)\s+any\s+good\s+movies?\b|"
    r"\bwhat(?:'s|\s+is)\s+your\s+favorite\s+(?:game\s+or\s+)?movie\b",
    re.IGNORECASE,
)
_NICKNAME_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:hey|hi|hello|yo)\s+[A-Z][A-Za-z'’-]{1,24}\b|"
    r"\b(?:call(?:ed)?|nickname|nick\s*name)\s+"
    r"(?:me|you|him|her|them|as\s+)?[\"']?[A-Z][A-Za-z'’-]{1,24}",
    re.IGNORECASE,
)
_NICKNAME_QUERY_RE = re.compile(
    r"\b(?:nickname|nick\s*name|called|call|address(?:ed)?|pet\s+name)\b",
    re.IGNORECASE,
)
_BOARD_GAME_SOURCE_SIBLING_REASONS = frozenset({"board_game_inventory_bridge"})
_BOARD_GAME_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:board\s+games?|tabletop\s+games?)\b",
    re.IGNORECASE,
)
_GAMING_MEDIUM_SOURCE_SIBLING_REASONS = frozenset({"gaming_medium_bridge"})
_GAMING_MEDIUM_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:mediums?|games?|gaming|video\s+games?|console|controller|keyboard|"
    r"headset|headphones?|equipment|gamecube|playstation|pc)\b",
    re.IGNORECASE,
)
_GAMING_MEDIUM_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:"
    r"game\s+controller|controller|keyboard|computer\s+monitor|gaming\s+setup|"
    r"headset|headphones?|console|gamecube|playstation|pc|equipment|"
    r"video\s+game\s+tournament|game\s+tournament|trophy|cash\s+prize"
    r")\b",
    re.IGNORECASE,
)
_PRECISE_TURN_RETRIEVAL_TEXT_RE = re.compile(
    r"\bsession_\d+\s+turn\s+D\d+:\d+\b",
    re.IGNORECASE,
)
_DIALOGUE_TURN_SPEAKER_RE = re.compile(
    r"\bD\d+:\d+\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9._-]{1,40}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9._-]{1,40}){0,2}\s*:"
)
_VISUAL_REFERENT_SIBLING_RE = re.compile(
    r"\b("
    r"look at this|take a look|here'?s|here is|photo|picture|pic|image|"
    r"did you see that|see that (?:band|photo|picture|pic|image|show|stage|crowd|"
    r"painting|drawing)|what'?s the band|what is the band|"
    r"посмотри|смотри|фото|картинк|изображен"
    r")\b",
    re.IGNORECASE,
)
_DIALOGUE_VISUAL_REFERENCE_RE = re.compile(
    r"\b("
    r"did you see that|see that (?:band|photo|picture|pic|image|show|stage|crowd|"
    r"painting|drawing)|what'?s the band|what is the band"
    r")\b",
    re.IGNORECASE,
)
_VISUAL_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b("
    r"look at|take a look|did you see|see that|photo|picture|pic|image|visual|"
    r"what'?s the band|what is the band|crowd|stage|concert"
    r")\b",
    re.IGNORECASE,
)
_VISUAL_SOURCE_SIBLING_REASONS = frozenset(
    {
        "decomposition_artifact_evidence",
        "source_evidence_bridge",
        "visual_text_evidence_bridge",
    }
)
_EVENT_VISUAL_SOURCE_SIBLING_REASONS = frozenset(
    {
        "event_participation_bridge",
        "lgbtq_pride_event_bridge",
        "lgbtq_school_event_bridge",
        "lgbtq_support_group_event_bridge",
        "transgender_conference_event_bridge",
        "transgender_poetry_event_bridge",
        "transgender_youth_center_event_bridge",
    }
)
_PRECISE_SOURCE_SIBLING_LOW_SIGNAL_CAP = 0.976
_PRECISE_SOURCE_SIBLING_MIN_STRONG_DISTINCTIVE_HITS = 6
_POTTERY_TYPE_SOURCE_SIBLING_LOW_SIGNAL_CAP = 0.965
_GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON = "generic_behavior_inference_bridge"
_POTTERY_TYPE_SOURCE_SIBLING_OBJECT_RE = re.compile(
    r"\b("
    r"pottery|clay|ceramic|bowl|bowls|cup|cups|mug|mugs|pot|pots|"
    r"sculpture|sculptures|dog\s+face"
    r")\b",
    re.IGNORECASE,
)
_POTTERY_TYPE_SOURCE_SIBLING_ACTION_RE = re.compile(
    r"\b("
    r"kids?|children|workshop|class|made|make|finished|project|hands\s+dirty|"
    r"creativity|imagination"
    r")\b",
    re.IGNORECASE,
)
_ANIMAL_CARE_INSTRUCTION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:keep(?:ing)?\s+(?:their|the)?\s*(?:area|tank|space|habitat)\s+clean|"
    r"clean\s+(?:area|tank|space|habitat)|feed(?:ing)?\s+(?:them\s+)?properly|"
    r"enough\s+light|make\s+sure\s+they\s+get\s+enough\s+light|"
    r"care\s+instructions?|kind\s+of\s+fun)\b",
    re.IGNORECASE,
)
_ANIMAL_DIET_EVIDENCE_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:"
    r"(?:eat|eats|ate|diet|food|feed(?:ing)?)\b(?=.{0,120}\b"
    r"(?:vegetables?|fruits?|insects?|greens?|varied\s+diet|turtles?|reptiles?)\b)|"
    r"(?:vegetables?|fruits?|insects?|greens?|varied\s+diet)\b(?=.{0,120}\b"
    r"(?:eat|eats|ate|diet|food|feed(?:ing)?|turtles?|reptiles?)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_PET_ACQUISITION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:"
    r"(?:adopt(?:ed|ing)?|got|get|new\s+addition|new\s+pup|puppy|pup|dog)\b"
    r"(?=.{0,180}\b(?:family|pet|dog|puppy|pup|"
    r"gift|named|stuffed\s+animal|image\s+caption|visual\s+query|"
    r"couch|blanket|toy)\b)|"
    r"(?:gift\s+from|named|stuffed\s+animal\s+dog)\b(?=.{0,180}\b"
    r"(?:giver|recipient|person|dog|pet)\b)|"
    r"(?:image\s+caption|visual\s+query)\b(?=.{0,180}\b"
    r"(?:dog|puppy|pup|couch|blanket|toy)\b)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_PET_ADJUSTMENT_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:puppy|pup|dog|little\s+one|pet)\b"
    r"(?=.{0,220}\b(?:doing\s+great|adjust(?:ing|ed)?|"
    r"learning\s+commands?|house\s+training|training|trained|new\s+home)\b)|"
    r"\b(?:doing\s+great|learning\s+commands?|house\s+training|"
    r"adjust(?:ing|ed)?|training|trained)\b"
    r"(?=.{0,220}\b(?:puppy|pup|dog|little\s+one|pet|image\s+caption|"
    r"visual\s+query)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PET_ACQUISITION_DATE_ANCHOR_RE = re.compile(
    r"\b(?:session_\d+\s+date|date:\s+)",
    re.IGNORECASE | re.DOTALL,
)
_CAUSE_AWARENESS_EVENT_SOURCE_SIBLING_RE = re.compile(
    r"(?=.*\b(?:charity\s+(?:race|run|walk|event)|fundraiser|fundraising|"
    r"campaign|race|run|walk|event|drive|conference|workshop|talk|speech|"
    r"parade|march)\b)"
    r"(?=.*\b(?:raise|raised|raising|spread|spreading|awareness|"
    r"bring(?:ing)?\s+attention|start(?:ing)?\s+conversations?|"
    r"make\s+a\s+difference)\b)"
    r"(?=.*\b(?:mental\s+health|domestic\s+abuse|animal\s+welfare|veterans?|"
    r"education|infrastructure|lgbtq\+?|trans\s+rights?|gender\s+identity|"
    r"inclusion|public\s+health|health|rights?|victims?|cause|issue)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CHARITY_BRAND_SPONSORSHIP_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:signed(?:\s+up)?|secure(?:d|s)?|landed|in\s+talks?\s+with|"
    r"sponsor(?:ship|ed|s)?|endorse(?:ment|d|s)?|partner(?:ship|ed|s)?)\b"
    r"(?=.{0,240}\b(?:brand|brands?|company|companies|organization|"
    r"organisations?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?|deal|deals?|"
    r"gear|shoe|shoes|apparel|equipment)\b)|"
    r"\b(?:got|gets?|have|has|had)\b"
    r"(?=.{0,140}\b(?:sponsor(?:ship|s)?|endorse(?:ment|d|s)?|"
    r"partner(?:ship|ed|s)?|deal|deals?)\b)|"
    r"\b(?:always\s+liked|liked|likes|i\s+like|we\s+like|they\s+like|"
    r"he\s+likes|she\s+likes|love|loves|fan\s+of|admire|admires|"
    r"favorite|favourite|dream(?:ed)?)\b"
    r"(?=.{0,180}\b(?:working\s+with\s+(?:them|it)|work\s+with\s+(?:them|it)|"
    r"partner(?:ship|ed|s)?|brand|brands?|company|companies|organization|"
    r"organisations?|deal|deals?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?)\b)|"
    r"\b(?:working\s+with\s+(?:them|it)|work\s+with\s+(?:them|it))\b"
    r"(?=.{0,180}\b(?:cool|great|exciting|stoked|like|liked|likes|love|"
    r"fan|dream|brand|brands?|company|companies|organization|organisations?|"
    r"deal|deals?|sponsor(?:ship|s)?|endorse(?:ment|d|s)?)\b)|"
    r"\b(?:charity|nonprofit|non-profit|foundation|organization|organisation|"
    r"program|initiative)\b"
    r"(?=.{0,220}\b(?:kids?|children|youth|students?|disadvantaged|"
    r"underserved|community|sports?|school|education|help|support|give\s+back|"
    r"make\s+(?:a\s+)?difference)\b)",
    re.IGNORECASE | re.DOTALL,
)
_VOLUNTEER_CAREER_SOURCE_SIBLING_CONTEXT_RE = re.compile(
    r"\b(volunteer(?:ed|ing|s)?|shelter|homeless)\b",
    re.IGNORECASE,
)
_VOLUNTEER_CAREER_SOURCE_SIBLING_SIGNAL_RE = re.compile(
    r"\b("
    r"front\s+desk|talks?|compliments?|residents?|bed|food|"
    r"counsel(?:or|ing)?|coordinator|started\s+volunteering|"
    r"make\s+a\s+difference|brighten|aunt\s+believed|fulfilling"
    r")\b",
    re.IGNORECASE,
)
_VOLUNTEERING_INVENTORY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:volunteer(?:ed|ing|s)?|homeless\s+shelter|shelter|"
    r"charity\s+event)\b"
    r"(?=.{0,240}\b(?:someone|person|woman|man|residents?|named|met|"
    r"letter|gratitude|appreciation|support\s+they\s+receive)\b)|"
    r"\b(?:someone|person|woman|man|residents?|named|met|letter|gratitude|"
    r"appreciation|support\s+they\s+receive)\b"
    r"(?=.{0,240}\b(?:volunteer(?:ed|ing|s)?|homeless\s+shelter|shelter|"
    r"charity\s+event)\b)",
    re.IGNORECASE | re.DOTALL,
)
_VOLUNTEERING_SERVICE_ACTIVITY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:volunteer(?:ed|ing|s)?|homeless\s+shelter|shelter|"
    r"service\s+events?)\b"
    r"(?=.{0,220}\b(?:give\s+out|hand\s+out|serve|distribut(?:e|ed|ing)|"
    r"food|supplies|donat(?:e|ed|ion)|toy\s+drive|kids?\s+in\s+need|"
    r"held\s+some\s+events|made\s+a\s+real\s+difference)\b)|"
    r"\b(?:give\s+out|hand\s+out|serve|distribut(?:e|ed|ing)|food|supplies|"
    r"donat(?:e|ed|ion)|toy\s+drive|kids?\s+in\s+need|held\s+some\s+events|"
    r"made\s+a\s+real\s+difference)\b"
    r"(?=.{0,220}\b(?:volunteer(?:ed|ing|s)?|homeless\s+shelter|shelter|"
    r"service\s+events?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CAREER_PATH_SOURCE_SIBLING_RE = re.compile(
    r"\b("
    r"counsel(?:or|ing)?|mental\s+health|working\s+with\s+(?:trans\s+)?people|"
    r"support(?:ing)?\s+their\s+mental\s+health|help(?:ing)?\s+them\s+accept"
    r")\b",
    re.IGNORECASE,
)
_SUPPORT_NETWORK_SOURCE_SIBLING_REASONS = frozenset(
    {
        "attribute_family_support_bridge",
        "negative_experience_support_bridge",
        "support_network_bridge",
    }
)
_SUPPORT_NETWORK_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:friends?|family|fam|mentors?|parents?|mother|father|coach|people\s+around)\b"
    r"(?=.{0,180}\b(?:rocks?|support(?:s|ed|ive)?|there\s+for|strength|"
    r"motivat(?:e|es|ed|ing)|cheer(?:s|ed|ing)?\s+(?:me|him|her|them|us)?\s*on|"
    r"push\s+on|lean\s+on|comfort|help(?:ed|ful)?|thankful)\b)|"
    r"\b(?:rocks?|support(?:s|ed|ive)?|there\s+for|strength|"
    r"motivat(?:e|es|ed|ing)|cheer(?:s|ed|ing)?\s+(?:me|him|her|them|us)?\s*on|"
    r"push\s+on|lean\s+on|comfort|help(?:ed|ful)?|thankful)\b"
    r"(?=.{0,180}\b(?:friends?|family|fam|mentors?|parents?|mother|father|coach|"
    r"people\s+around)\b)",
    re.IGNORECASE | re.DOTALL,
)
_BOOK_READING_INVENTORY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:loved\s+reading\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?|"
    r"love\s+reading\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?|book\s+i\s+read\s+last\s+year|"
    r"favorite\s+book|favourite\s+book|childhood\s+book|read\s+as\s+a\s+kid|"
    r"just\s+finished\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?|"
    r"finished\s+(?:reading\s+)?\"?(?-i:[A-Z])[^\"\n]{1,80}\"?|"
    r"books?\s+(?:guide|motivat(?:e|es|ed|ing)|help(?:s|ed)?"
    r"(?:\s+(?:me|him|her|them|us|you))?\s+discover|"
    r"(?:are|is)\s+a\s+huge\s+part)\b"
    r"(?=.{0,180}\b(?:journey|reading|"
    r"self[-\s]?discovery|keep\s+going|motivat(?:e|es|ed|ing))\b)|"
    r"\"?(?-i:[A-Z])[^\"\n]{1,80}\"?\s+(?:is|are)\s+"
    r"(?:great|good|amazing|awesome)"
    r"(?=.{0,160}\b(?:books?|novel|series|worth\s+a\s+read|"
    r"world-building|character\s+development|recommend|hooked|"
    r"(?:chat|talk)\s+about\s+them|writ(?:e|ing)\s+about))|"
    r"(?-i:[A-Z])[^\"\n]{1,80}\".{0,80}\bone\s+of\s+my\s+favorites|"
    r"book\s+collection|book\s+series\s+(?:that\s+)?(?:i\s+)?love|"
    r"fan\s+of\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?(?=.{0,120}\b(?:books?|series|"
    r"magical|fantasy|novel|reading)\b)|"
    r"\"?(?-i:[A-Z])[^\"\n]{1,80}\"?\s+fan(?=.{0,120}\b(?:books?|series|"
    r"magical|fantasy|novel|reading)\b)|"
    r"read(?:ing)?\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?)\b",
    re.IGNORECASE | re.DOTALL,
)
_CHURCH_FRIEND_ACTIVITY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:church\s+friends?|friends?\s+from\s+church)\b(?=.{0,180}\b"
    r"(?:hikes?|hiking|picnic|visited?|park|activities?|outing|trip|"
    r"community\s+work|community\s+service|volunteer\s+work|volunteering|"
    r"service\s+project|chilled|played\s+games|games|charades|"
    r"scavenger\s+hunt|nature|refreshed|rewarding)\b)|"
    r"\b(?:hikes?|hiking|picnic|visited?|park|activities?|outing|trip|"
    r"community\s+work|community\s+service|volunteer\s+work|volunteering|"
    r"service\s+project|chilled|played\s+games|games|charades|"
    r"scavenger\s+hunt|nature|refreshed|rewarding)\b"
    r"(?=.{0,180}\b(?:church\s+friends?|friends?\s+from\s+church)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_COMPETITION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:competitions?|contest|contests|compete|competed|competing|comp|"
    r"tournament|tournaments)\b(?=.{0,220}\b(?:troph(?:y|ies)|first\s+place|"
    r"won|winner|stage|team|crew|performance|regionals?|visual\s+query|"
    r"image\s+caption)\b)|"
    r"\b(?:troph(?:y|ies)|first\s+place|won|winner|stage|team|crew|performance|"
    r"regionals?)\b(?=.{0,220}\b(?:competitions?|contest|contests|compete|"
    r"competed|competing|comp|tournament|tournaments)\b)|"
    r"\b(?:dancers?|dance|festival|perform(?:ing|ance)?|stage)\b"
    r"(?=.{0,240}\b(?:photo|picture|image\s+caption|visual\s+query|"
    r"grace|graceful|skill|practic(?:e|ed|ing)|impress|part\s+of\s+it|"
    r"glad|awesome|excited|memories|grand\s+opening)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_COMPANION_SOURCE_SIBLING_REASONS = frozenset(
    {
        "exercise_activity_inventory_bridge",
        "outdoor_activity_inventory_bridge",
        "church_friend_activity_inventory_bridge",
    }
)
_ACTIVITY_COMPANION_QUERY_RE = re.compile(
    r"\bwho\b(?=.{0,140}\b(?:with|alongside|together)\b)"
    r"(?=.{0,200}\b(?:go|went|attend(?:ed|ing)?|join(?:ed|ing)?|"
    r"start(?:ed|ing)?|try|tried|trying|class(?:es)?|lesson|practice|"
    r"camp(?:ed|ing)?|hik(?:e|ed|ing)|travel(?:ed|led|ing)?|trip|"
    r"visit(?:ed|ing)?|yoga|workout|exercise)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_COMPANION_ACTIVITY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:yoga|class(?:es)?|lesson|practice|workout|exercise|fitness|"
    r"training|kickboxing|taekwondo|boxing|running|hiking|camping|trip|"
    r"conference|parade|event|travel(?:ed|led|ing)?|visit(?:ed|ing)?)\b",
    re.IGNORECASE,
)
_ACTIVITY_COMPANION_WITH_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:with|alongside|together\s+with|joined\s+by|accompanied\s+by)\b"
    r".{0,90}\b(?:(?:my|his|her|their|our|a|an|the)\s+|"
    r"one\s+of\s+(?:my|his|her|their|our)\s+)?"
    r"(?:family|kids?|children|friends?|parents?|partner|spouse|team|group|"
    r"colleagues?|co-?workers?|workmates?|classmates?|teammates?|neighbou?rs?)\b|"
    r"\b(?:(?:my|his|her|their|our)\s+)?"
    r"(?:colleagues?|co-?workers?|workmates?|friends?|classmates?|teammates?|"
    r"neighbou?rs?)\b(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39})?"
    r".{0,90}\binvited\b.{0,120}\b(?:me|him|her|them|us)?\s*(?:to|for)\b|"
    r"\binvited\b.{0,120}\b(?:to|for)\b.{0,160}\bby\s+"
    r"(?:(?:my|his|her|their|our)\s+)?"
    r"(?:colleagues?|co-?workers?|workmates?|friends?|classmates?|teammates?|"
    r"neighbou?rs?)\b",
    re.IGNORECASE | re.DOTALL,
)
_OUTDOOR_ACTIVITY_VISUAL_COMPANION_SOURCE_SIBLING_RE = re.compile(
    r"\byou\s+and\s+(?:your\s+)?"
    r"(?:friends?|colleagues?|co-?workers?|workmates?|teammates?|team|group)\b"
    r"(?=.{0,120}\b(?:look(?:s|ing)?|seem(?:s|ed)?|great|team|group)\b)|"
    r"\b(?:friends?|colleagues?|co-?workers?|workmates?|teammates?)\b"
    r"(?=.{0,120}\blook(?:s|ing)?\s+like\s+(?:a\s+)?(?:great\s+)?"
    r"(?:team|group)\b)|"
    r"\b(?:photo|picture|image|visual\s+query|caption)\b"
    r"(?=.{0,180}\b(?:waterfall|trail|mountains?|park|outdoors?|nature)\b)"
    r"(?=.{0,220}\b(?:friends?|colleagues?|co-?workers?|workmates?|"
    r"teammates?|team|group|people)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CLASSICAL_MUSIC_PREFERENCE_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:fan|enjoys?|likes?|loves?|favorite|favourite|fav(?:orite)?|into)\b"
    r"(?=.{0,180}\b(?:classical|bach|mozart|vivaldi|orchestra|symphony|"
    r"composer|violin|clarinet|tunes?|songs?|music)\b)|"
    r"\b(?:classical|bach|mozart|vivaldi|orchestra|symphony|composer)\b"
    r"(?=.{0,180}\b(?:fan|enjoys?|likes?|loves?|favorite|favourite|"
    r"fav(?:orite)?|tunes?|songs?|music)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SENTIMENTAL_REMINDER_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:reminds?|reminder|sentimental\s+value|symboli[sz](?:es|ed)?|"
    r"meaning|means|stands?\s+for)\b(?=.{0,220}\b(?:art|self[-\s]?expression|"
    r"friend|birthday|gift|memory|pattern|colou?rs?|childhood|love|faith|"
    r"strength|roots?|family|keepsake)\b)|"
    r"\b(?:sentimental\s+value|hand[-\s]?painted|keepsake|gift|birthday|"
    r"pattern|colou?rs?)\b(?=.{0,220}\b(?:reminds?|reminder|symbol|meaning|"
    r"self[-\s]?expression)\b)",
    re.IGNORECASE | re.DOTALL,
)
_COLLECTIBLE_OBJECT_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:collectibles?|collection|memorabilia|keepsakes?|mementos?|"
    r"possessions?|objects?|items?|own(?:s|ed)?|similar|same|shared)\b",
    re.IGNORECASE,
)
_COLLECTIBLE_OBJECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:signed|autographed|autograph)\b"
    r"(?=.{0,220}\b(?:balls?|basketballs?|jerseys?|photos?|pictures?|cards?|"
    r"posters?|keepsakes?|mementos?|gifts?|presents?|possessions?|"
    r"collectibles?|memorabilia|teammates?|friends?|favorite\s+player)\b)|"
    r"\b(?:prized\s+possession|keepsakes?|mementos?|collectibles?|memorabilia|"
    r"gifts?|presents?)\b"
    r"(?=.{0,220}\b(?:signed|autographed|autograph|balls?|basketballs?|"
    r"jerseys?|photos?|pictures?|reminds?|reminder|bond|friendship|"
    r"appreciation|teammates?|favorite\s+player)\b)|"
    r"\b(?:reminds?|reminder)\b"
    r"(?=.{0,220}\b(?:bond|friendship|appreciation|teammates?|team\s+spirit|"
    r"friends?|signed|autographed|balls?|basketballs?|keepsakes?|mementos?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_OUTDOOR_PREFERENCE_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:look\s+forward|highlight|always\s+remember|favorite|favourite|"
    r"best\s+memory|love|enjoy|special|amazing)\b(?=.{0,240}\b(?:camping|"
    r"campfire|marshmallows?|meteor\s+shower|stars?|sky|universe|nature|"
    r"outdoors?|hikes?|hiking|trail|park)\b)|"
    r"\b(?:camping|campfire|marshmallows?|meteor\s+shower|stars?|sky|universe|"
    r"nature|outdoors?|hikes?|hiking|trail|park)\b(?=.{0,240}\b(?:look\s+forward|"
    r"highlight|always\s+remember|favorite|favourite|best\s+memory|love|enjoy|"
    r"special|amazing|at\s+one\s+with)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CHILDREN_PREFERENCE_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:kids?|children|child|sons?|daughters?|younger\s+kids?)\b"
    r"(?=.{0,220}\b(?:likes?|loves?|enjoys?|favorite|favourite|stoked|"
    r"excited|blast|into)\b)"
    r"(?=.{0,260}\b(?:dinosaurs?|exhibit|museum|animals?|bones?|nature|"
    r"outdoors?|hikes?|hiking|camping|campfire|marshmallows?|books?|stories|"
    r"learning|pottery|clay|painting|creative|creativity)\b)|"
    r"\b(?:they|them)\b(?=.{0,140}\b(?:were\s+)?(?:stoked|excited)\b)"
    r"(?=.{0,220}\b(?:dinosaurs?|exhibit|museum|animals?|bones?|nature|"
    r"outdoors?|hikes?|hiking|camping|books?|stories|learning)\b)|"
    r"\b(?:they|them)\b(?=.{0,180}\b(?:likes?|loves?|enjoys?|favorite|"
    r"favourite)\b)"
    r"(?=.{0,220}\b(?:dinosaurs?|exhibit|museum|animals?|bones?|nature|"
    r"outdoors?|hikes?|hiking|camping|books?|stories|learning)\b)",
    re.IGNORECASE | re.DOTALL,
)
_BUSINESS_COMMONALITY_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:lost\s+(?:my\s+|his\s+|her\s+|their\s+)?job|door\s+dash|banker|"
    r"dance\s+studio|clothing\s+store|own\s+store|own\s+business|"
    r"ad\s+campaign)\b"
    r"(?=.{0,220}\b(?:business|store|studio|job|passion(?:ate)?|love|"
    r"growing|launched|starting|started|opened)\b)|"
    r"\b(?:passion(?:ate)?|love|launched|started|starting|opened|growing)\b"
    r"(?=.{0,220}\b(?:business|store|studio|door\s+dash|banker|dance|fashion)\b)",
    re.IGNORECASE | re.DOTALL,
)
_POST_EVENT_SUPPORT_APPRECIATION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:they(?:'re| are)?\s+a\s+real\s+support|real\s+support|"
    r"appreciat(?:e|ed|es|ing)\s+(?:them|family|support)|"
    r"appreciate\s+them\s+a\s+lot|thankful\s+(?:for|to)|grateful\s+(?:for|to)|"
    r"mean\s+the\s+world)\b",
    re.IGNORECASE,
)
_OPINION_REACTION_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:think|thought|opinion|reaction|response|feel|felt|decision|plan|choice)\b",
    re.IGNORECASE,
)
_OPINION_REACTION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:supportive|proud|excited|happy|agree|approve|approved|concerned|"
    r"disagree|encourag(?:e|ed|es|ing)|lovely|amazing|awesome|wonderful|"
    r"great\s+idea|good\s+idea|glad|thrilled)\b|"
    r"\b(?:you|they|he|she)(?:'ll| will)\s+be\s+(?:an?\s+)?"
    r"(?:awesome|great|amazing|wonderful|good)\b",
    re.IGNORECASE | re.DOTALL,
)
_OPINION_REACTION_ADOPTION_QUERY_RE = re.compile(
    r"\b(?:adopt|adopted|adopting|adoption|children|child|kids?|family|parent)\b",
    re.IGNORECASE,
)
_OPINION_REACTION_ADOPTION_TEXT_RE = re.compile(
    r"\b(?:adopt|adopted|adopting|adoption|children|child|kids?|family|"
    r"mom|mother|dad|father|parent)\b",
    re.IGNORECASE,
)
_CAUSE_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:passionate|interesting|main\s+focus(?:es)?|goal|goals?|"
    r"support(?:ing)?|rights?)\b"
    r"(?=.{0,220}\b(?:education|schools?|infrastructure|veterans?|military)\b)|"
    r"\b(?:education|schools?|infrastructure|veterans?|military)\b"
    r"(?=.{0,220}\b(?:passionate|interesting|main\s+focus(?:es)?|goal|goals?|"
    r"support(?:ing)?|rights?|community|reform|development|quality)\b)",
    re.IGNORECASE | re.DOTALL,
)
_TRIP_DESTINATION_NAMED_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:was|were|been)\s+in\s+(?-i:[A-Z])[A-Za-z' .-]{2,60}\b|"
    r"\b(?:visited|visit(?:ed|ing)?)\s+(?-i:[A-Z])[A-Za-z' .-]{2,80}\b|"
    r"\b(?:went|gone|visited|travel(?:ed|led)?|vacationed)\s+"
    r"(?:to|in|through|around)\s+(?-i:[A-Z])[A-Za-z' .-]{2,80}\b|"
    r"\b(?:trips?|travel|journey|vacation)\s+"
    r"(?:to|in|through|around)\s+(?-i:[A-Z])[A-Za-z' .-]{2,80}\b",
    re.IGNORECASE | re.DOTALL,
)
_TRIP_DESTINATION_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:was|were|been)\s+in\s+(?-i:[A-Z])[A-Za-z' .-]{2,60}\b|"
    r"\b(?:visited|visit(?:ed|ing)?)\s+(?-i:[A-Z])[A-Za-z' .-]{2,80}\b|"
    r"\b(?:went|gone|visited|travel(?:ed|led)?|vacationed)\s+"
    r"(?:to|in|through|around)\s+(?-i:[A-Z])[A-Za-z' .-]{2,80}\b|"
    r"\b(?:trips?|travel|journey|vacation)\s+"
    r"(?:to|in|through|around)\s+(?-i:[A-Z])[A-Za-z' .-]{2,80}\b|"
    r"\b(?:trip|travel(?:ed|led|ing)?|visited|vacation)\b"
    r"(?=.{0,180}\b(?:city|country|state|coast|beach|mountains?|"
    r"parks?|destination|place|visual\s+query|image\s+caption)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PLACE_INVENTORY_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:cities|city|countries|country|states?|places?|locations?|"
    r"destinations?|areas?)\b"
    r"(?=.{0,180}\b(?:mention(?:ed|s)?|visit(?:ed|ing)?|went|gone|been|"
    r"travel(?:ed|led|ing)?|trip|vacation(?:ed)?|during|in|to)\b)|"
    r"\b(?:visit(?:ed|ing)?|went|gone|been|travel(?:ed|led|ing)?|trip|"
    r"vacation(?:ed)?|during)\b"
    r"(?=.{0,180}\b(?:cities|city|countries|country|states?|places?|"
    r"locations?|destinations?|areas?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PUBLIC_OFFICE_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:run(?:ning)?\s+for\s+office|running\s+office|public\s+office|"
    r"politics?|campaign)\b",
    re.IGNORECASE,
)
_PUBLIC_OFFICE_MOTIVATION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:run(?:ning|s)?|ran)\s+for\s+office\b"
    r"(?=.{0,240}\b(?:impact|community|politics?|positive\s+changes?|"
    r"better\s+future|rewarding|last\s+run|make\s+(?:a\s+)?difference)\b)|"
    r"\b(?:public\s+office|politics?)\b"
    r"(?=.{0,240}\b(?:impact|community|positive\s+changes?|better\s+future|"
    r"rewarding|run(?:ning)?\s+for\s+office|last\s+run)\b)|"
    r"\b(?:impact|positive\s+changes?|better\s+future|"
    r"make\s+(?:a\s+)?difference|rewarding)\b"
    r"(?=.{0,240}\b(?:politics?|public\s+office|run(?:ning)?\s+for\s+office)\b)",
    re.IGNORECASE | re.DOTALL,
)
_RECOGNITION_AWARD_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:recognition|award|awards|medal|medals|certificate|certificates|"
    r"honou?r|honou?red|trophy|prize|received?|got|given|gave|earned|won)\b",
    re.IGNORECASE,
)
_RECOGNITION_AWARD_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:recognition|awards?|medals?|certificates?|honou?rs?|troph(?:y|ies)|"
    r"prizes?)\b"
    r"(?=.{0,200}\b(?:receive|received|got|given|gave|earned|won)\b)|"
    r"\b(?:receive|received|got|given|gave|earned|won)\b"
    r"(?=.{0,160}\b(?:recognition|awards?|medals?|certificates?|"
    r"honou?rs?|troph(?:y|ies)|prizes?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_RECOGNITION_CERTIFICATE_VISUAL_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:image\s+caption|visual\s+query|photo|picture)\b"
    r"(?=.{0,240}\b(?:certificate|certificates|diploma|diplomas)\b)"
    r"(?=.{0,240}\b(?:completion|completed|degree|graduat(?:e|ed|ion)|"
    r"university|college)\b)|"
    r"\b(?:certificate|certificates|diploma|diplomas)\b"
    r"(?=.{0,240}\b(?:image\s+caption|visual\s+query|photo|picture)\b)"
    r"(?=.{0,240}\b(?:completion|completed|degree|graduat(?:e|ed|ion)|"
    r"university|college)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PLANNING_TOOL_USE_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:clipboard|notepad|notebook|calendar|planner)\b"
    r"(?=.{0,220}\b(?:use|using|stay\s+organized|organized\s+and\s+motivated|"
    r"sets?\s+goals?|tracks?\s+(?:my\s+)?achievements?|areas?\s+to\s+improve|"
    r"improvement|goal\s+setting|progress)\b)|"
    r"\b(?:stay\s+organized|organized\s+and\s+motivated|sets?\s+goals?|"
    r"tracks?\s+(?:my\s+)?achievements?|areas?\s+to\s+improve|"
    r"goal\s+setting|progress)\b"
    r"(?=.{0,220}\b(?:clipboard|notepad|notebook|calendar|planner|"
    r"image\s+caption|visual\s+query)\b)",
    re.IGNORECASE | re.DOTALL,
)
_CUSTOMER_EXPERIENCE_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:special\s+experience|customer\s+experience|experience\s+for\s+customers?)\b"
    r"(?=.{0,220}\b(?:welcome|coming\s+back|come\s+back|key|space|"
    r"imagining|cozy|inviting)\b)|"
    r"\b(?:feel\s+welcome|welcome\s+and\s+coming\s+back|coming\s+back|"
    r"come\s+back)\b"
    r"(?=.{0,220}\b(?:customers?|special\s+experience|customer\s+experience|"
    r"space|cozy|inviting)\b)",
    re.IGNORECASE | re.DOTALL,
)
_GRAND_OPENING_SUPPORT_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:right\s+by\s+your\s+side|live\s+it\s+up|so\s+excited|"
    r"can't\s+wait|cannot\s+wait)\b"
    r"(?=.{0,220}\b(?:tomorrow|grand\s+opening|opening|launch|dance\s+studio|"
    r"memories|image\s+caption|visual\s+query)\b)|"
    r"\b(?:grand\s+opening|opening|launch|dance\s+studio)\b"
    r"(?=.{0,220}\b(?:right\s+by\s+your\s+side|live\s+it\s+up|so\s+excited|"
    r"can't\s+wait|cannot\s+wait)\b)",
    re.IGNORECASE | re.DOTALL,
)
_DEGREE_POLICY_SOURCE_SIBLING_RE = re.compile(
    r"\b("
    r"policymaking\b(?=.{0,120}\bdegree\b)|"
    r"degree\b(?=.{0,120}\bpolicymaking\b)|"
    r"degree\s+related\s+to\s+policymaking|"
    r"public\s+(?:policy|administration|affairs)|"
    r"political\s+science"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_POST_EVENT_ACTIVITY_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:road\s*trip|roadtrip)\b(?=.{0,180}\b(?:yesterday|recent|"
    r"just\s+did|after\s+the\s+(?:road\s*trip|drive)|relax))|"
    r"\b(?:yesterday|just\s+did|recent|relax)\b(?=.{0,180}\b(?:road\s*trip|roadtrip))|"
    r"\b(?:hikes?|hiking|trail|mountains?)\b(?=.{0,120}\b(?:picture|pic|"
    r"photo|kids?|family|recent|yesterday))",
    re.IGNORECASE | re.DOTALL,
)
_RUNNING_REASON_SOURCE_SIBLING_RE = re.compile(
    r"\b("
    r"(?:running|run|runs|ran)\b(?=.{0,120}\b(?:destress|de-stress|"
    r"clear\s+my\s+mind|headspace|mental\s+health|farther|longer|mood|boost))|"
    r"(?:destress|de-stress|clear\s+my\s+mind|headspace|mental\s+health|farther|longer)\b"
    r"(?=.{0,120}\b(?:running|run|runs|ran))|"
    r"great\s+for\s+(?:my\s+)?mental\s+health|"
    r"walking\s+or\s+running|got\s+you\s+into\s+running|purple\s+running\s+shoe"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_DURATION_SOURCE_SIBLING_REASONS = frozenset({"decomposition_activity_duration"})
_FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS = frozenset({"decomposition_frequency_recurrence"})
_COUNT_ACTIVITY_FOLLOWUP_SOURCE_SIBLING_REASONS = frozenset(
    {
        "hike_count_activity_bridge",
        "hiking_trail_count_bridge",
    }
)
_STATE_ACTIVITY_SOURCE_SIBLING_CONTEXT_RE = re.compile(
    r"\b("
    r"volunteer(?:ed|ing|s)?|shelter|homeless|work(?:ed|ing|s)?|"
    r"live(?:d|s|ing)?|play(?:ed|ing|s)?|run(?:ning|s)?|"
    r"go(?:es|ing)?|visit(?:ed|ing|s)?|trips?|travel(?:ed|led|ing|s)?|"
    r"commut(?:e|ed|es|ing)|journeys?|driv(?:e|es|ing)|rode|rides?|"
    r"beach|camp(?:ed|ing)?|hikes?|hiking|"
    r"practice(?:d|s|ing)?|train(?:ed|s|ing)?|appointments?|"
    r"art|artist|creating|creat(?:e|ed|ing)|paint(?:ed|ing)?|draw(?:ing)?|"
    r"have|has|had|own(?:ed|s)?|keep(?:s|ing)?|pets?|snakes?|dogs?|cats?|puppy|"
    r"волонтер|волонт[её]р|работа(?:ет|л|ла|ли)?|жив[её]т|жил|жила|"
    r"игра(?:ет|л|ла)|занимается|тренируется|участвует"
    r")\b",
    re.IGNORECASE,
)
_ACTIVITY_DURATION_SOURCE_SIBLING_SIGNAL_RE = re.compile(
    r"\b("
    r"for\s+(?:about\s+|roughly\s+|nearly\s+|almost\s+|over\s+)?"
    r"(?:\d{1,2}|one|two|three|four|five|six)\s+"
    r"(?:years?|months?|weeks?|days?)|"
    r"since\s+(?:19|20)\d{2}|"
    r"since\s+(?:(?:the\s+)?age\s+of\s+|i\s+was\s+)?"
    r"(?:\d{1,2}|one|two|three|four|five|six|"
    r"seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen)(?:\s+or\s+so)?|"
    r"started|began|still|ongoing|continuous|already|"
    r"(?:\d{1,2}|one|two|three|four|five|six)\s+years?\s+ago|"
    r"с\s+(?:19|20)\d{2}|"
    r"(?:один|одна|два|две|три|четыре|пять|шесть|\d{1,2})\s+"
    r"(?:лет|года|год|месяц(?:ев|а)?|недель|недели|дней)|"
    r"начал[аи]?|начала|начали|до сих пор|уже|давно"
    r")\b",
    re.IGNORECASE,
)
_FREQUENCY_RECURRENCE_SOURCE_SIBLING_SIGNAL_RE = re.compile(
    r"\b("
    r"every\s+(?:day|night|morning|afternoon|evening|weekday|weekend|week|"
    r"month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"every\s+other\s+(?:day|days|week|weeks|month|months|year|years)|"
    r"daily|weekly|monthly|yearly|annually|regularly|usually|often|"
    r"(?:once|twice|one|two|three|four|five|six|\d{1,2})\s+"
    r"(?:times?\s+)?(?:a|per)\s+(?:day|week|month|year)|"
    r"кажд\w+\s+(?:день|недел\w*|месяц|год|утро|вечер|выходн\w*)|"
    r"ежедневно|еженедельно|ежемесячно|ежегодно|регулярно|обычно|часто|"
    r"(?:один|одна|два|две|три|четыре|пять|шесть|\d{1,2})\s+раз(?:а)?\s+в\s+"
    r"(?:день|недел\w*|месяц|год)"
    r")\b",
    re.IGNORECASE,
)
_BIRDWATCHING_CITY_SCHEDULE_SOURCE_SIBLING_RE = re.compile(
    r"\b("
    r"dog\s+park\s+nearby|nearby\s+(?:dog\s+)?park|"
    r"spot\s+(?:looks\s+)?ideal|where\s+did\s+you\s+take\s+them|"
    r"binos|binoculars|notebook|log\s+them|camera|"
    r"busy\s+week|schedule|city\s+schedule|"
    r"birdwatching|watching\s+birds?|birds?|eagles?|soar|"
    r"out\s+in\s+nature|away\s+from\s+the\s+city|"
    r"being\s+in\s+(?:a\s+)?nature|"
    r"hustle\s+and\s+bustle|outside\s+and\s+soak\s+up\s+the\s+scenery"
    r")\b",
    re.IGNORECASE,
)
_BIRDWATCHING_CITY_SCHEDULE_ACCESS_SLOT_RE = re.compile(
    r"\b("
    r"dog\s+park\s+nearby|nearby\s+(?:dog\s+)?park|"
    r"spot\s+(?:looks\s+)?ideal|where\s+did\s+you\s+take\s+them|"
    r"out\s+in\s+nature|being\s+in\s+(?:a\s+)?nature|"
    r"outside|outdoors|hustle\s+and\s+bustle"
    r")\b",
    re.IGNORECASE,
)
_BIRDWATCHING_CITY_SCHEDULE_EQUIPMENT_SLOT_RE = re.compile(
    r"\b(binos|binoculars|notebook|log\s+them|camera)\b",
    re.IGNORECASE,
)
_BIRDWATCHING_CITY_SCHEDULE_PRESSURE_SLOT_RE = re.compile(
    r"\b(busy\s+week|schedule|city\s+schedule|job\s+and\s+living\s+here)\b",
    re.IGNORECASE,
)
_BIRDWATCHING_CITY_SCHEDULE_HOBBY_SLOT_RE = re.compile(
    r"\b(birdwatching|watching\s+birds?|birds?|eagles?|soar)\b",
    re.IGNORECASE,
)
_TURN_SOURCE_ID_RE = re.compile(
    r"^(?P<group>.+):(?P<dialogue>D\d+)[:-](?P<turn>\d+):turn$",
    re.IGNORECASE,
)
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_RELATED_TURN_ANCHOR_RE = re.compile(
    r"\brelated\s+turns?\s*:\s*D\d+:\d+",
    re.IGNORECASE,
)
_TEMPORAL_QUESTION_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:when|what\s+date|which\s+date)\b",
    re.IGNORECASE,
)
_TEMPORAL_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:"
    r"yesterday|tomorrow|last\s+(?:night|week|month|year|mon(?:day)?|tue(?:sday)?|"
    r"wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)|"
    r"next\s+(?:week|month|year|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|"
    r"thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)|"
    r"(?:one|two|three|four|five|six|seven|\d+)\s+days?\s+ago|"
    r"(?:one|two|three|four|five|six|seven|\d+)\s+weeks?\s+ago"
    r")\b",
    re.IGNORECASE,
)
_TEMPORAL_EVENT_QUERY_TOKEN_RE = re.compile(r"\b[\w']+\b", re.UNICODE)
_TEMPORAL_EVENT_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "date",
        "did",
        "do",
        "does",
        "for",
        "her",
        "his",
        "in",
        "is",
        "of",
        "on",
        "the",
        "their",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
    }
)
_TEMPORAL_EVENT_ACTION_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:"
    r"attend(?:ed|ing)?|built|collaborat(?:e|ed|ing|ion)|create(?:d)?|"
    r"definitely|got|had|made|make|met|mention(?:ed)?|open(?:ed)?|"
    r"planning|started|took|went|won"
    r")\b",
    re.IGNORECASE,
)
_SOURCE_GROUP_SUFFIXES = frozenset({"events", "observation", "summary"})
_ACTIVITY_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\bused\s+to\s+(?:go|do|play|ride|visit)\b(?=.{0,180}\b"
    r"(?:dad|father|mom|mother|parent|parents?)\b)(?=.{0,220}\b"
    r"(?:kid|child|childhood|younger)\b)|"
    r"\b(?:danc(?:e|ing)|dance\s+studio|festival|dancers?)\b"
    r"(?=.{0,180}\b(?:destress|de-stress|stress\s+relief|passion|"
    r"escape|perform(?:ing)?|practice|grace|skill|part\s+of\s+it|"
    r"grand\s+opening|memories))|"
    r"\b(?:shooting\s+guard|season\s+opener|scored\s+\d+|recent\s+game|"
    r"basketball\s+game|surf(?:ing|board)?|waves?)\b"
    r"(?=.{0,220}\b(?:team|game|court|basketball|jerseys?|photo|"
    r"image\s+caption|visual\s+query|surfboard|waves?|beach)\b)",
    re.IGNORECASE | re.DOTALL,
)
_DESTRESS_ACTIVITY_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:danc(?:e|ing)|dance\s+studio|running|run|pottery|class)\b"
    r"(?=.{0,220}\b(?:destress|de-stress|stress\s+(?:relief|fix)|"
    r"escape|go-to|worries\s+vanish|clear\s+my\s+mind|headspace|"
    r"therapeutic|therapy|unwind|calm))",
    re.IGNORECASE | re.DOTALL,
)
_ESCAPE_ACTIVITY_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:escape|escapes|escaping|take\s+(?:me|you|him|her|them|us)\s+away|"
    r"reality|daily\s+grind|feel\s+free|alternate\s+realities)\b",
    re.IGNORECASE,
)
_ESCAPE_ACTIVITY_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:read(?:ing)?|books?|novels?|fantasy|movies?|films?|shows?|"
    r"writing|music|hiking|running|surf(?:ing)?)\b"
    r"(?=.{0,240}\b(?:escape(?:s|d|ing)?(?:\s+(?:from\s+)?reality)?|"
    r"take\s+(?:me|you|him|her|them|us)\s+away|feel\s+free|"
    r"alternate\s+realities|break\s+from\s+reality|lost\s+in)\b)|"
    r"\b(?:escape(?:s|d|ing)?(?:\s+(?:from\s+)?reality)?|"
    r"take\s+(?:me|you|him|her|them|us)\s+away|feel\s+free|"
    r"alternate\s+realities|break\s+from\s+reality|lost\s+in)\b"
    r"(?=.{0,240}\b(?:read(?:ing)?|books?|novels?|fantasy|movies?|films?|"
    r"shows?|writing|music|hiking|running|surf(?:ing)?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_MEDIA_WATCHING_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:tv\s+series|series|shows?|movies?|films?)\b"
    r"(?=.{0,140}\b(?:watch(?:ed|ing)?|seen|saw|mention(?:ed|s)?|called)\b)|"
    r"\b(?:watch(?:ed|ing)?|seen|saw|mention(?:ed|s)?|called)\b"
    r"(?=.{0,140}\b(?:tv\s+series|series|shows?|movies?|films?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_MEDIA_WATCHING_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:watch(?:ed|ing)?|seen|saw|check\s+out|excited\s+to\s+watch)\b"
    r"(?=.{0,220}\b(?:tv\s+series|series|shows?|movies?|films?|called|"
    r"coming\s+out|based\s+on|favorite|favourite)\b)|"
    r"\b(?:tv\s+series|series|shows?|movies?|films?)\b"
    r"(?=.{0,220}\b(?:watch(?:ed|ing)?|seen|saw|check\s+out|called|"
    r"coming\s+out|based\s+on|favorite|favourite)\b)",
    re.IGNORECASE | re.DOTALL,
)
_STUDY_TIME_MANAGEMENT_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:exam|exams|finals?|studying|study|prep|prepare|"
    r"time\s+management|technique|method|strategy|study\s+tricks?)\b",
    re.IGNORECASE,
)
_STUDY_TIME_MANAGEMENT_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:studying|study|exam|exams|finals?|prep|prepare)\b"
    r"(?=.{0,240}\b(?:25\s*minutes?|5\s*minutes?|"
    r"break(?:ing)?\s+up|smaller\s+parts|intervals?|pomodoro|"
    r"minutes?\s+on|minutes?\s+off|breaks?|keeps?\s+me\s+on\s+track|"
    r"less\s+overwhelming)\b)|"
    r"\b(?:25\s*minutes?|5\s*minutes?|break(?:ing)?\s+up|"
    r"smaller\s+parts|intervals?|pomodoro|minutes?\s+on|minutes?\s+off|"
    r"keeps?\s+me\s+on\s+track|less\s+overwhelming)\b"
    r"(?=.{0,240}\b(?:studying|study|exam|exams|finals?|prep|prepare)\b)",
    re.IGNORECASE | re.DOTALL,
)
_NAMED_PREFERENCE_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:would|enjoy|enjoys?|prefer|prefers?|favorite|favourite|"
    r"related|recommend|interested|preference|trait|decision|reason)\b",
    re.IGNORECASE,
)
_NAMED_PREFERENCE_DIRECT_SOURCE_SIBLING_RE = re.compile(
    r"\b(?:favorite|favourite|love|loves|loved|enjoy|enjoys|enjoyed|"
    r"prefer|prefers|preferred|fan|interested|never\s+gets\s+old|"
    r"drawn\s+to|really\s+into)\b",
    re.IGNORECASE,
)
_NAMED_PREFERENCE_QUERY_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'+]*", re.IGNORECASE)
_NAMED_PREFERENCE_QUERY_STOPWORDS = frozenset(
    {
        "acceptance",
        "and",
        "because",
        "considered",
        "decision",
        "does",
        "during",
        "evidence",
        "enjoy",
        "enjoys",
        "encouraging",
        "favorite",
        "favourite",
        "for",
        "from",
        "indicates",
        "inference",
        "interested",
        "likely",
        "locations",
        "mentioned",
        "observed",
        "prefer",
        "preference",
        "reason",
        "related",
        "support",
        "supporting",
        "supportive",
        "the",
        "trait",
        "visit",
        "which",
        "would",
    }
)

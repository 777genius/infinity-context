"""Pattern catalog for context requirement coverage policies."""

from __future__ import annotations

import re

_MAX_LIST_ITEMS = 12

_MAX_KEY_CHARS = 64

_MODALITY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "image",
        (
            "image",
            "screenshot",
            "screen shot",
            "picture",
            "photo",
            "ocr",
            "картин",
            "скрин",
            "скриншот",
            "фото",
        ),
    ),
    (
        "audio",
        (
            "audio",
            "voice",
            "speech",
            "transcript",
            "recording",
            "call",
            "аудио",
            "голос",
            "транскрипт",
            "запись",
            "звонок",
            "созвон",
        ),
    ),
    (
        "video",
        (
            "video",
            "keyframe",
            "frame",
            "clip",
            "видео",
            "кадр",
            "ролик",
        ),
    ),
    (
        "document",
        (
            "attached",
            "attachment",
            "document",
            "doc",
            "pdf",
            "file",
            "page",
            "документ",
            "файл",
            "вложение",
            "прикрепл",
            "страниц",
            "пдф",
        ),
    ),
)

_EVIDENCE_FEATURE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "citation",
        (
            "citation",
            "cite",
            "quote",
            "source",
            "where did",
            "where",
            "цитат",
            "источник",
            "ссылк",
            "где",
        ),
    ),
    (
        "time_range",
        (
            "timestamp",
            "time range",
            "timecode",
            "minute",
            "second",
            "таймкод",
            "время",
            "минута",
            "секунда",
        ),
    ),
    (
        "visual_region",
        (
            "bbox",
            "box",
            "region",
            "ocr",
            "where on screen",
            "область",
            "регион",
            "на скрине",
            "на экране",
        ),
    ),
    (
        "extracted_text",
        (
            "detected text",
            "extracted text",
            "ocr text",
            "read text",
            "written",
            "what text",
            "what is written",
            "what does it say",
            "текст",
            "написано",
            "что написано",
            "прочитай",
            "распознай",
            "надпись",
        ),
    ),
    (
        "page_or_char",
        (
            "page",
            "paragraph",
            "section",
            "строка",
            "страниц",
            "абзац",
            "раздел",
        ),
    ),
)

_RECENT_EVENT_HINT_RE = re.compile(
    r"\b("
    r"hour ago|hours ago|last week|yesterday|today|"
    r"час назад|часа назад|часов назад|неделю назад|вчера|сегодня"
    r")\b",
    re.IGNORECASE,
)

_EXPLICIT_TIME_RANGE_QUERY_RE = re.compile(
    r"\b(?:timestamp|time\s+range|timecode|at\s+\d{1,2}(?::\d{2}){1,2}|"
    r"at\s+\d{1,3}\s*(?:s|sec|secs|second|seconds|m|min|minute|minutes)\b|"
    r"\d{1,2}:\d{2}(?::\d{2})?)\b|"
    r"\b(?:таймкод|время)\b",
    re.IGNORECASE,
)

_COUNT_ANSWER_QUERY_RE = re.compile(
    r"\b(how\s+many|number\s+of|count|total|сколько)\b",
    re.IGNORECASE,
)

_LIST_ANSWER_QUERY_RE = re.compile(
    r"\b(what|which|who|какие|какой|что)\b"
    r"(?=.{0,96}\b("
    r"books?|items?|instruments?|pets?|mediums?|hobbies|activities|events?|"
    r"artists?|bands?|types?|kinds?|interests?|musicians?|songs?|fields?|"
    r"ways|symbols?|attributes?|things?|people|persons|stakeholders?|contacts?|"
    r"owners?|participants?|collaborators?|люди|участники|контакты|"
    r"стейкхолдеры|ответственные"
    r")\b)",
    re.IGNORECASE | re.DOTALL,
)

_ORDINAL_ANSWER_QUERY_RE = re.compile(
    r"\b("
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"1st|2nd|3rd|[4-9]th|10th|"
    r"перв\w*|втор\w*|трет\w*|четверт\w*|пят\w*"
    r")\b",
    re.IGNORECASE,
)

_TEMPORAL_ANSWER_QUERY_RE = re.compile(
    r"\b(when|how\s+long|what\s+date|what\s+day|which\s+day|"
    r"когда|какая\s+дата|в\s+какой\s+день|какого\s+числа|как\s+долго)\b",
    re.IGNORECASE,
)

_CAUSAL_ANSWER_QUERY_RE = re.compile(
    r"\b(why|reason|because|почему|зачем|причин)\b",
    re.IGNORECASE,
)

_INFERENCE_ANSWER_QUERY_RE = re.compile(
    r"\b("
    r"would|could|might|may|likely|probably|potentially|considered|infer|inference|"
    r"based\s+on|do\s+you\s+think|"
    r"может|мог|могла|могли|вероятно|похоже|считается|вывод"
    r")\b",
    re.IGNORECASE,
)

_SOCIAL_INFERENCE_ANSWER_QUERY_RE = re.compile(
    r"\b(?:friends?|teammates?)\b(?=.{0,80}\b(?:besides|other\s+than|apart\s+from)\b)|"
    r"\b(?:besides|other\s+than|apart\s+from)\b(?=.{0,80}\b(?:friends?|teammates?)\b)",
    re.IGNORECASE | re.DOTALL,
)

_STATE_RESIDENCE_INFERENCE_ANSWER_QUERY_RE = re.compile(
    r"\b(?:state|connecticut|stamford)\b"
    r"(?=.{0,120}\b(?:live|lives|living|reside|residence)\b)|"
    r"\b(?:live|lives|living|reside|residence)\b"
    r"(?=.{0,120}\b(?:state|connecticut|stamford)\b)",
    re.IGNORECASE | re.DOTALL,
)

_POLITICAL_INFERENCE_ANSWER_QUERY_RE = re.compile(
    r"\bpolitical\b(?=.{0,80}\b(?:leaning|likely|would|infer|inference)\b)|"
    r"\b(?:leaning|likely|would|infer|inference)\b(?=.{0,80}\bpolitical\b)",
    re.IGNORECASE | re.DOTALL,
)

_DEGREE_FIELD_INFERENCE_ANSWER_QUERY_RE = re.compile(
    r"\b(?:degree|major|studied|study|university)\b"
    r"(?=.{0,120}\b(?:might|likely|would|could|infer|inference|field|what|which)\b)|"
    r"\b(?:might|likely|would|could|infer|inference|field|what|which)\b"
    r"(?=.{0,120}\b(?:degree|major|studied|study|university)\b)",
    re.IGNORECASE | re.DOTALL,
)

_COMMUNITY_MEMBERSHIP_INFERENCE_ANSWER_QUERY_RE = re.compile(
    r"\b(?:member|membership|part\s+of|belong(?:s|ed|ing)?)\b"
    r"(?=.{0,120}\b(?:lgbtq?|trans(?:gender)?|queer|pride|community)\b)|"
    r"\b(?:lgbtq?|trans(?:gender)?|queer|pride|community)\b"
    r"(?=.{0,120}\b(?:member|membership|part\s+of|belong(?:s|ed|ing)?)\b)",
    re.IGNORECASE | re.DOTALL,
)

_ALLERGY_CONDITION_INFERENCE_ANSWER_QUERY_RE = re.compile(
    r"\b(?:underlying\s+condition|condition|health\s+condition|medical\s+condition)\b"
    r"(?=.{0,120}\b(?:allerg(?:y|ies|ic)|allergic)\b)|"
    r"\b(?:allerg(?:y|ies|ic)|allergic)\b"
    r"(?=.{0,120}\b(?:underlying\s+condition|condition|health\s+condition|"
    r"medical\s+condition)\b)|"
    r"\b(?:состояни\w*|заболевани\w*)\b(?=.{0,120}\bаллерги\w*\b)|"
    r"\bаллерги\w*\b(?=.{0,120}\b(?:состояни\w*|заболевани\w*)\b)",
    re.IGNORECASE | re.DOTALL,
)

_CHOICE_ANSWER_QUERY_RE = re.compile(
    r"\b(?:or|или)\b(?=.{0,96}\b("
    r"prefer|preference|interested|more|less|rather|choose|choice|option|alternative|"
    r"better|close|near|live|lives|"
    r"предпоч|интерес|больше|меньше|лучше|выбор|вариант|близко|рядом|живет|живёт"
    r")\b)|"
    r"\b("
    r"prefer|preference|interested|more|less|rather|choose|choice|option|alternative|"
    r"better|close|near|live|lives|"
    r"предпоч|интерес|больше|меньше|лучше|выбор|вариант|близко|рядом|живет|живёт"
    r")\b(?=.{0,96}\b(?:or|или)\b)",
    re.IGNORECASE | re.DOTALL,
)

_ANSWER_LABEL_RE = r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"

_QUERY_ANSWER_LABEL_RE = r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё._-]{1,39}"

_SPEAKER_ANSWER_QUERY_RE = re.compile(
    rf"\baccording\s+to\s+{_QUERY_ANSWER_LABEL_RE}\b|"
    rf"\b(?:from|in)\s+{_QUERY_ANSWER_LABEL_RE}(?:'s|s')?\s+"
    r"(?:view|opinion|perspective)\b|"
    rf"\bпо\s+словам\s+{_QUERY_ANSWER_LABEL_RE}\b|"
    r"\bwho\s+(?:said|says|mentioned|mentions|told|wrote|asked|"
    r"reported|noted|claimed)\b|"
    r"\bкто\s+(?:сказал|говорил|упомянул|упомянула|написал|написала|"
    r"спросил|спросила)\b",
    re.IGNORECASE,
)

_CONVERSATION_PARTICIPANT_ANSWER_QUERY_RE = re.compile(
    rf"\bwho\s+did\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    r"(?:talk|speak|meet|chat|message|dm|call)\b|"
    rf"\b(?:who|whom)\s+did\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    r"(?:talk|speak|meet|chat|message|dm|call)\s+(?:to|with)\b|"
    r"\bс\s+кем\s+"
    rf"{_QUERY_ANSWER_LABEL_RE}\s+"
    r"(?:говорил\w*|общал\w*|встречал\w*|созванивал\w*|переписывал\w*)\b",
    re.IGNORECASE,
)

_CONVERSATION_TOPIC_ANSWER_QUERY_RE = re.compile(
    rf"\bwhat\s+did\s+{_QUERY_ANSWER_LABEL_RE}\s+(?:and\s+{_QUERY_ANSWER_LABEL_RE}\s+)?"
    r"(?:talk|speak|chat|discuss)\s+about\b|"
    rf"\bwhat\s+did\s+{_QUERY_ANSWER_LABEL_RE}\s+(?:discuss|talk|speak|chat)\s+"
    rf"(?:with|to)\s+{_QUERY_ANSWER_LABEL_RE}\b|"
    rf"\bwhat\s+was\s+(?:{_QUERY_ANSWER_LABEL_RE}(?:'s|’s)\s+)?"
    rf"(?:the\s+)?(?:conversation|call|chat|meeting|discussion)\s+"
    rf"(?:between|with)\s+{_QUERY_ANSWER_LABEL_RE}"
    rf"(?:\s+and\s+{_QUERY_ANSWER_LABEL_RE})?\s+about\b|"
    r"\bwhat\s+was\s+discussed\s+(?:in|during)\s+(?:the\s+)?"
    r"(?:[\w._-]+\s+){0,4}(?:conversation|call|chat|meeting|discussion)\b|"
    rf"\bwhat\s+(?:topic|subject)\s+did\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    r"(?:talk|speak|chat|discuss)\b|"
    r"\bчто\s+"
    rf"{_QUERY_ANSWER_LABEL_RE}(?:\s+и\s+{_QUERY_ANSWER_LABEL_RE})?\s+"
    r"(?:обсуждал\w*|говорил\w*)\b|"
    r"\bо\s+ч[её]м\s+"
    rf"{_QUERY_ANSWER_LABEL_RE}\s+"
    r"(?:говорил\w*|общал\w*|переписывал\w*)\b",
    re.IGNORECASE,
)

_COMMONALITY_ANSWER_QUERY_RE = re.compile(
    r"\bwho\s+else\b(?=.{0,120}\b(?:like|likes|enjoy|enjoys|love|loves|"
    r"prefer|prefers|interest|hobby|activity|share|shares)\b)|"
    r"\bwho\s+shares?\b(?=.{0,120}\b(?:interest|hobby|activity|like|love|"
    r"preference)\b)|"
    rf"\b(?:what|which)\s+(?:do|did|does)\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    rf"(?:and|&)\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    r"(?:both\s+)?(?:have\s+in\s+common|share)\b|"
    r"\b(?:what|which)\b(?=.{0,120}\b(?:common|in\s+common|both|mutual|overlap|"
    r"shared)\b)(?=.{0,120}\b(?:hobbies|interests|activities|like|enjoy|love|"
    r"prefer|preference|favorite|favourite)\b)|"
    r"\b(?:what|which)\s+(?:hobbies|interests|activities|things)\s+"
    r"(?:do|did)\b.{0,100}\b(?:have\s+in\s+common|share|both)\b|"
    r"\b(?:что|какие|какое)\b(?=.{0,120}\b(?:общ(?:его|ие|ий|ая|ее|ее)?|"
    r"оба|обе|вместе)\b)(?=.{0,120}\b(?:хобби|интерес|любят|нравит|"
    r"заняти|увлечен|увлечён)\b)|"
    r"\bкто\s+(?:ещ[её])\b(?=.{0,120}\b(?:любит|нравит|интерес|хобби|"
    r"увлечен|увлечён|предпочитает)\b)",
    re.IGNORECASE | re.DOTALL,
)

_CONSTRAINT_ANSWER_QUERY_RE = re.compile(
    r"\b(?:can'?t|cannot|can\s+not|unable\s+to|not\s+able\s+to)\b"
    r"(?=.{0,80}\b(?:eat|use|attend|join|take|wear|go|access|do)\b)|"
    r"\b(?:not\s+(?:like|likes|liked|interested|eat|eats|use|uses|want|wants|able)|"
    r"doesn'?t\s+(?:like|eat|enjoy|want|use)|does\s+not\s+"
    r"(?:like|eat|enjoy|want|use)|would\s+not\s+(?:like|eat|enjoy|want|use)|"
    r"never\s+(?:eat|eats|like|likes|use|uses)|avoid|avoids|allergic|"
    r"discomfort|restricted|blocked)\b|"
    r"\b(?:нельзя|не\s+может|не\s+любит|не\s+хочет|избега\w*|аллерги\w*|"
    r"ограничен\w*|запрещен\w*|запрещён\w*)\b",
    re.IGNORECASE,
)

_ACTION_ROLE_VERB_QUERY_RE = (
    r"recommend(?:ed|s|ing)?|suggest(?:ed|s|ing)?|"
    r"promise(?:d|s|ing)?|assign(?:ed|s|ing)?|approv(?:e|ed|es|ing)|"
    r"hear(?:d|s|ing)?|learn(?:ed|s|ing)?|find\s+out|found\s+out|"
    r"help(?:ed|s|ing)?|assist(?:ed|s|ing)?|support(?:ed|s|ing)?|"
    r"introduc(?:e|ed|es|ing)|send|sent|give|gave|tell|told|"
    r"ask(?:ed|s|ing)?|decid(?:e|ed|es|ing)|"
    r"рекомендовал(?:а)?|посоветовал(?:а)?|"
    r"пообещал(?:а)?|обещал(?:а)?|назначил(?:а)?|одобрил(?:а)?|"
    r"отправил(?:а)?|дал(?:а)?|сказал(?:а)?|спросил(?:а)?|решил(?:а)?|"
    r"познакомил(?:а|и)?|представил(?:а|и)?|узнал(?:а|и)?|услышал(?:а|и)?|"
    r"помог(?:ла|ли)?|поддержал(?:а|и)?"
)

_ACTION_ROLE_ANSWER_QUERY_RE = re.compile(
    rf"\b{_QUERY_ANSWER_LABEL_RE}\s+"
    r"(?:read|watched|tried|bought|used|visited|listened|started|played|made|ate)\b"
    rf".{{0,120}}\b(?:after|because|since|when)\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    r"(?:recommend(?:ed|s|ing)?|suggest(?:ed|s|ing)?)\b|"
    rf"\b(?:who|whom)\s+did\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    rf"(?:{_ACTION_ROLE_VERB_QUERY_RE})\b.{{0,120}}\b(?:to|for)\b"
    rf"(?=\s*(?:\?|$|in\b|during\b|after\b|before\b|on\b|at\b))|"
    rf"\b(?:to|for)\s+whom\s+did\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    rf"(?:{_ACTION_ROLE_VERB_QUERY_RE})\b|"
    rf"\bwho\s+(?:{_ACTION_ROLE_VERB_QUERY_RE})\b"
    rf".{{0,120}}\b(?:to|for)\s+{_QUERY_ANSWER_LABEL_RE}\b|"
    rf"\b(?:what|which)\s+did\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    rf"(?:{_ACTION_ROLE_VERB_QUERY_RE})\b|"
    rf"\b(?:what|which)\s+"
    r"(?:decision|promise|recommendation|suggestion)\s+did\s+"
    rf"{_QUERY_ANSWER_LABEL_RE}\s+(?:make|give|offer)\b|"
    rf"\b(?:is|was)\s+{_QUERY_ANSWER_LABEL_RE}\s+responsible\s+for\b|"
    r"\bwho\s+(?:(?:is|was|'s)\s+(?:responsible|(?:the\s+)?owner)|owns)\b|"
    rf"\b{_QUERY_ANSWER_LABEL_RE}\s+(?:(?:is|was|'s)\s+"
    r"(?:responsible|(?:the\s+)?owner)|owns?)\b|"
    r"\bкто\s+(?:рекомендовал|рекомендовала|посоветовал|посоветовала|"
    r"пообещал|пообещала|обещал|обещала|назначил|назначила|"
    r"одобрил|одобрила|отправил|отправила|сказал|сказала|"
    r"ответственн\w*)\b|"
    rf"\bкому\s+{_QUERY_ANSWER_LABEL_RE}\s+(?:{_ACTION_ROLE_VERB_QUERY_RE})\b|"
    rf"\bпо\s+чь(?:ему|ей|им)\s+(?:совет\w*|рекомендац\w*)\s+"
    rf"{_QUERY_ANSWER_LABEL_RE}\s+"
    r"(?:прочитал(?:а|и)?|посмотрел(?:а|и)?|попробовал(?:а|и)?|"
    r"использовал(?:а|и)?|купил(?:а|и)?|посетил(?:а|и)?|начал(?:а|и)?)\b",
    re.IGNORECASE | re.DOTALL,
)

_POSSESSION_SOURCE_ANSWER_QUERY_RE = re.compile(
    rf"\bwho\s+(?:gave|gifted)\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    r".{0,80}\b(?:necklace|pendant|ring|book|camera|photo|picture|"
    r"keepsake|gift|present|item|object)\b|"
    rf"\bwho\s+was\s+{_QUERY_ANSWER_LABEL_RE}(?:'s|s')?\s+"
    r".{0,80}\s+from\b|"
    rf"\bwhere\s+did\s+{_QUERY_ANSWER_LABEL_RE}(?:'s|s')?\s+"
    r".{0,80}\s+(?:come\s+from|originate)\b|"
    rf"\bwhere\s+did\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    r"(?:get|receive)\s+.{0,90}\s+from\b",
    re.IGNORECASE | re.DOTALL,
)

_LOCATION_ANSWER_QUERY_RE = re.compile(
    r"\bwhere\b(?=.{0,120}\b(?:live|lives|living|reside|resides|"
    r"located|based|from|born|birthplace|hometown|camp(?:ed|ing)?|"
    r"hik(?:e|ed|ing)|moved|relocated|travel(?:ed|led|ing)?|"
    r"trips?|vacation|visited?|destination|journey)\b)|"
    r"\b(?:what|which)\s+(?:city|country|place|location|address|hometown|birthplace)\b|"
    r"\bwhat\s+(?:is|was)\s+(?:the\s+)?"
    r"(?:city|country|place|location|address|hometown|birthplace)\b|"
    r"\b(?:где|куда|откуда)\b(?=.{0,120}\b(?:жив[её]т|прожива\w*|наход\w*|"
    r"родил\w*|родн\w*|переехал\w*|кемпинг|лагер\w*|поход\w*|"
    r"ездил\w*|поехал\w*|путешеств\w*|отдыхал\w*|поездк\w*|отпуск)\b)|"
    r"\b(?:какой|какая|какое|какие)\s+"
    r"(?:город|стран\w*|место|локаци\w*|адрес)\b",
    re.IGNORECASE | re.DOTALL,
)

_PREFERENCE_ANSWER_QUERY_RE = re.compile(
    r"\b(?:favorite|favourite|prefer(?:s|red|ence)?|interested\s+in|fan\s+of)\b|"
    rf"\bwhat\s+does\s+{_QUERY_ANSWER_LABEL_RE}\s+(?:like|enjoy|prefer)\b|"
    rf"\bwhat\s+(?:music|food|book|movie|film|color|colour|artist|band|"
    rf"genre|activity|sport|game|instrument|place)\s+does\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    r"(?:like|enjoy|prefer)\b|"
    r"\b(?:любим\w*|предпоч\w*|нравит\w*|интересует\w*)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_ANSWER_QUERY_RE = re.compile(
    r"\brelationship\s+status\b|"
    r"\bwho\s+(?:is|are|was|were)\s+(?:connected|related|linked|associated|"
    r"involved)\b|"
    r"\b(?:which|what)\s+(?:people|persons|stakeholders?|contacts?|owners?|"
    r"participants?|collaborators?)\b"
    r"(?=.{0,120}\b(?:connected|related|linked|associated|involved|for|with|to|in|on)\b)|"
    r"\b(?:кто|какие\s+(?:люди|участники|контакты|стейкхолдеры|ответственные))\b"
    r"(?=.{0,120}\b(?:связан|связаны|относятся|участвуют|вовлечены|по|для|с|в)\b)|"
    rf"\bwho\s+(?:is|was|'s)\s+{_QUERY_ANSWER_LABEL_RE}(?:'s|s')?\s+"
    r"(?:husband|wife|spouse|partner|boyfriend|girlfriend|fianc(?:e|ee)|"
    r"friend|best\s+friend|old\s+friend|sibling|brother|sister|mother|father|"
    r"parent|child|daughter|son|mentor|roommate|colleague|coworker)\b|"
    rf"\b(?:is|was)\s+{_QUERY_ANSWER_LABEL_RE}\s+"
    r"(?:married|single|dating|divorced|engaged|partnered)\b|"
    r"\bhow\s+long\b(?=.{0,120}\b(?:married|together|dating|relationship)\b)|"
    r"\b(?:husband|wife|spouse|partner|boyfriend|girlfriend|fianc(?:e|ee)|"
    r"friend|sibling|brother|sister|mother|father|parent|child|daughter|son|"
    r"mentor|roommate|colleague|coworker)\s+of\b|"
    r"\b(?:статус\s+отношен\w*|кто\s+.*(?:муж|жена|партнер|партнёр|друг|подруга|"
    r"брат|сестра|мать|отец|родител\w*|сын|дочь|наставник|коллега|сосед\w*)|"
    r"женат|замужем|встречается|одинок\w*)\b",
    re.IGNORECASE | re.DOTALL,
)

_COMMITMENT_ANSWER_QUERY_RE = re.compile(
    r"\b(?:action\s+items?|todo|to-do|follow\s*-?\s*up|next\s+steps?|"
    r"tasks?|assigned|assignee|owner|responsible|deadline|due\s+date|"
    r"due|overdue|deliverable|milestone|reminder|commitment|committed|"
    r"promise(?:d|s)?|promised|agreed\s+to)\b|"
    r"\b(?:what|which|who|when)\b(?=.{0,120}\b(?:needs?\s+to|has\s+to|must)\b)|"
    r"\b(?:задач\w*|дел\w*|todo|фоллоу\s*-?\s*ап|следующ\w+\s+шаг\w*|"
    r"ответственн\w*|назначен\w*|дедлайн|срок|просрочен\w*|напоминан\w*|"
    r"обязал\w*|пообещал\w*|обещал\w*)\b",
    re.IGNORECASE | re.DOTALL,
)

_GOTCHA_ANSWER_QUERY_RE = re.compile(
    r"\b(?:gotchas?|pitfalls?|caveats?|known\s+issues?|known\s+problems?|"
    r"failure\s+mode|workarounds?|root\s+cause|watch\s+out|went\s+wrong|"
    r"what\s+(?:failed|broke|blocked)|why\s+(?:failed|broke|blocked)|"
    r"avoid\s+next\s+time|not\s+repeat)\b|"
    r"\b(?:подводн\w+\s+камн\w*|известн\w+\s+(?:проблем\w*|ошибк\w*)|"
    r"что\s+пошло\s+не\s+так|обходн\w+\s+пут\w*|воркэраунд\w*|"
    r"на\s+что\s+обратить\s+внимание|чего\s+избегать|не\s+повторять)\b",
    re.IGNORECASE | re.DOTALL,
)

_EXISTENCE_ANSWER_QUERY_RE = re.compile(
    r"\b(?:do\s+we\s+know|is\s+there\s+any|are\s+there\s+any|"
    r"any\s+(?:evidence|proof|source|record|mention)|"
    r"^(?:do|does|did|has|have|is|are)\s+[^?.!]{1,120}(?=\?)|"
    r"(?:did|does|has|have)\s+.{0,80}\bever\b|"
    r"ever\s+(?:mention|mentioned|say|said|write|wrote|have|had)|"
    r"mentioned?\s+any|has\s+any|have\s+any|"
    r"no\s+(?:evidence|proof|record|mention)|unknown|not\s+known)\b|"
    r"\b(?:известно\s+ли|есть\s+ли\s+(?:доказательств\w*|источник|запись|"
    r"упоминан\w*)|когда-либо|упоминал(?:а)?\s+ли|нет\s+(?:данных|"
    r"доказательств|упоминан\w*)|неизвестно)\b",
    re.IGNORECASE | re.DOTALL,
)

_STATE_UPDATE_ANSWER_QUERY_RE = re.compile(
    r"\b(?:latest|current|currently|most\s+recent|newest|final|canonical|"
    r"source\s+of\s+truth|right\s+now|at\s+the\s+moment|as\s+of\s+now|"
    r"still|remains?|selected|chosen|settled|no\s+longer|anymore|"
    r"not\s+current|stale|outdated|obsolete|deprecated|previous|old|prior|"
    r"before|changed|change|updated|update|replaced|superseded|switched|"
    r"migrated|transitioned)\b|"
    r"\b(?:актуальн\w*|текущ\w*|последн\w*|сейчас|на\s+данный\s+момент|"
    r"вс[её]\s+еще|вс[её]\s+ещ[её]|по-прежнему|больше\s+не|уже\s+не|"
    r"устаревш\w*|стар\w*|предыдущ\w*|раньше|до|изменил\w*|изменилось|"
    r"обновил\w*|обновлен\w*|обновлён\w*|заменил\w*|поменял\w*)\b",
    re.IGNORECASE,
)

_SUMMARY_ANSWER_QUERY_RE = re.compile(
    r"(?i:\bwho\s+(?:is|are|was|were)\s+)[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"\s*(?:\?|$)|"
    r"(?i:\bwhat\s+(?:is|was)\s+project\s+)[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,3}\s*(?:\?|$)|"
    r"(?i:\bwhat\s+(?:is|was)\s+(?:company|organization|organisation|org|team|"
    r"client|customer|vendor|partner)\s+)[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,3}\s*(?:\?|$)|"
    r"(?i:\bwhat\s+(?:do|did)\s+(?:we|you)\s+know\s+about\b)|"
    r"(?i:\btell\s+me\s+about\b|\bsummari[sz]e\b|\bprofile\s+(?:for|of)\b)|"
    r"(?i:\boverview\s+(?:for|of)\b)|"
    r"(?i:\bкто\s+(?:такой|такая|это)\s+)[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"\s*(?:\?|$)|"
    r"(?i:\bчто\s+это\s+за\s+проект\s+)[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,3}\s*(?:\?|$)|"
    r"(?i:\bчто\s+это\s+за\s+(?:компан(?:ия|ию|ии)|организац(?:ия|ию)|"
    r"команд(?:а|у)|клиент|заказчик|вендор|партн[её]р)\s+)"
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,3}\s*(?:\?|$)|"
    r"(?i:\bчто\s+(?:мы|ты)\s+зна(?:ем|ешь)\s+(?:об|о|про)\b)|"
    r"(?i:\bрасскажи\s+(?:об|о|про)\b|\bпрофиль\b|\bобзор\b|\bсводка\b)",
)

_COUNT_ANSWER_TEXT_RE = re.compile(
    r"\b("
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"once|twice|several|multiple|numerous|many|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"один|одна|одно|одного|одной|два|две|двух|три|трех|трёх|"
    r"четыре|четырех|четырёх|пять|пяти|шесть|шести|семь|семи|"
    r"восемь|восьми|девять|девяти|десять|десяти|"
    r"another|new\s+friend|new\s+addition|new\s+one|again|"
    r"\d+"
    r")\b",
    re.IGNORECASE,
)

_COUNT_FROM_ENUMERATED_LIST_TEXT_RE = re.compile(
    r"(?:"
    r"\b(?:including|includes|such\s+as|consists\s+of|comprised\s+of|listed|list)\b|"
    r"[,;].{0,120}\b(?:and|or|plus|as\s+well\s+as)\b|"
    r"\b(?:включая|например|состоит\s+из)\b|[,;].{0,120}\b(?:и|или|а\s+также)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_ORDINAL_ANSWER_TEXT_RE = re.compile(
    r"\b("
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"1st|2nd|3rd|[4-9]th|10th|"
    r"перв\w*|втор\w*|трет\w*|четверт\w*|пят\w*"
    r")\b",
    re.IGNORECASE,
)

_LIST_ANSWER_TEXT_RE = re.compile(
    r"(?:,|;|\band\b|\balso\b|\bplus\b|\bas well as\b|\bincluding\b|"
    r"\bи\b|\bа также\b)",
    re.IGNORECASE,
)

_TEMPORAL_ANSWER_TEXT_RE = re.compile(
    r"\b("
    r"today|yesterday|tomorrow|recently|ago|last\s+"
    r"(?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"mon|tues|tue|wed|thu|fri|sat|sun)|"
    r"next\s+(?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"in\s+\d{4}|\d{4}-\d{2}-\d{2}|"
    r"session_\d+\s+date|date:|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"сегодня|вчера|завтра|неделю\s+назад|месяц\s+назад|год\s+назад|"
    r"прошл\w+\s+(?:недел\w+|месяц\w+|год\w+|ноч\w+)|"
    r"следующ\w+\s+(?:недел\w+|месяц\w+|год\w+)"
    r")\b",
    re.IGNORECASE,
)

_CAUSAL_ANSWER_TEXT_RE = re.compile(
    r"\b("
    r"because|so|since|due\s+to|therefore|reason|motivated|inspired|"
    r"wanted\s+to|decided\s+to|made\s+me|made\s+her|made\s+him|"
    r"so\s+(?:i|we|you|they|he|she)\s+could|in\s+order\s+to|"
    r"as\s+a\s+way\s+to|hoping\s+to|for\s+the\s+purpose\s+of|"
    r"потому|поэтому|из-за|решил|решила|захотел|захотела"
    r"|чтобы|как\s+способ"
    r")\b",
    re.IGNORECASE,
)

_INFERENCE_ANSWER_TEXT_RE = re.compile(
    r"\b("
    r"indicates|suggests|shows|showed|based\s+on|seems|likely|probably|would|could|might|"
    r"supportive|support|supported|encouraging|encourages|accepted|acceptance|"
    r"helps?|cares?|kind|proud|interested|enjoys?|likes?|wants?|prefers?|"
    r"fan\s+of|"
    r"mentors?|mentored|mentoring|guided?|guidance|counsel(?:ed|ing)?|"
    r"listened|empathy|empathetic|patient|volunteered?|volunteering|"
    r"kept\s+(?:his|her|their|my|our)?\s*promises?|followed\s+through|"
    r"prepared|planned|organized|organised|coordinated|consistently|"
    r"похоже|вероятно|показывает|поддержк\w*|помога\w*|принял\w*|приняла\w*"
    r")\b",
    re.IGNORECASE,
)

_SOCIAL_INFERENCE_ANSWER_TEXT_RE = re.compile(
    r"\b(?:friends?|teammates?|team|squad|guild|clan|buddies)\b"
    r"(?=.{0,80}\b(?:online|gaming|games?|plays?|played|tournament|valorant)\b)|"
    r"\b(?:online|gaming|games?|plays?|played|tournament|valorant)\b"
    r"(?=.{0,80}\b(?:friends?|teammates?|team|squad|guild|clan|buddies)\b)",
    re.IGNORECASE | re.DOTALL,
)

_STATE_RESIDENCE_INFERENCE_ANSWER_TEXT_RE = re.compile(
    r"\b(?:map|photo|image|caption)\b(?=.{0,120}\b(?:trail|trails|hiking|park|forest|"
    r"lake|route|state|county|city|minnesota|voyageurs)\b)|"
    r"\b(?:trail|trails|hiking|park|forest|lake|route|state|county|city|"
    r"minnesota|voyageurs)\b(?=.{0,120}\b(?:map|photo|image|caption)\b)|"
    r"\b(?:stamford|connecticut)\b(?=.{0,120}\b(?:adopt|adopted|shelter|home|"
    r"lives?|residence)\b)|"
    r"\b(?:adopt|adopted|shelter|home|lives?|residence)\b"
    r"(?=.{0,120}\b(?:stamford|connecticut)\b)",
    re.IGNORECASE | re.DOTALL,
)

_POLITICAL_INFERENCE_ANSWER_TEXT_RE = re.compile(
    r"\b(?:lgbtq?|trans(?:gender)?|transition|rights|equality|inclusion)\b"
    r"(?=.{0,120}\b(?:conservative|unwelcoming|support|supportive|acceptance|"
    r"progressive|liberal|rights)\b)|"
    r"\b(?:conservative|unwelcoming|support|supportive|acceptance|progressive|"
    r"liberal|rights)\b(?=.{0,120}\b(?:lgbtq?|trans(?:gender)?|transition|"
    r"rights|equality|inclusion)\b)",
    re.IGNORECASE | re.DOTALL,
)

_DEGREE_FIELD_DIRECT_ANSWER_TEXT_RE = re.compile(
    r"\b(?:political\s+science|public\s+(?:policy|administration|affairs)|"
    r"policy\s+studies|government|civic\s+policy|law)\b"
    r"(?=.{0,140}\b(?:degree|major|studied|study|university|college)\b)|"
    r"\b(?:degree|major|studied|study|university|college)\b"
    r"(?=.{0,140}\b(?:political\s+science|public\s+(?:policy|administration|affairs)|"
    r"policy\s+studies|government|civic\s+policy|law)\b)",
    re.IGNORECASE | re.DOTALL,
)

_DEGREE_FIELD_INDIRECT_ANSWER_TEXT_RE = re.compile(
    r"\b(?:policymaking|policy\s+making)\b(?=.{0,140}\bdegree\b)|"
    r"\bdegree\b(?=.{0,140}\b(?:policymaking|policy\s+making)\b)|"
    r"\bdegree\s+related\s+to\s+(?:policymaking|policy\s+making)\b",
    re.IGNORECASE | re.DOTALL,
)

_COMMUNITY_MEMBERSHIP_INFERENCE_ANSWER_TEXT_RE = re.compile(
    r"\b(?:identif(?:y|ies|ied)|member|part\s+of|belong(?:s|ed|ing)?\s+to|"
    r"came\s+out|is\s+(?:transgender|queer|lgbtq?)|joined)\b"
    r"(?=.{0,120}\b(?:lgbtq?|trans(?:gender)?|queer|pride|support\s+group|"
    r"community)\b)|"
    r"\b(?:lgbtq?|trans(?:gender)?|queer|pride|support\s+group|community)\b"
    r"(?=.{0,120}\b(?:identif(?:y|ies|ied)|member|part\s+of|belong(?:s|ed|ing)?|"
    r"came\s+out|joined)\b)",
    re.IGNORECASE | re.DOTALL,
)

_COMMUNITY_MEMBERSHIP_SUPPORT_ONLY_ANSWER_TEXT_RE = re.compile(
    r"\b(?:ally|allies|supportive|supported|support|encourag(?:e|ed|es|ing)|"
    r"advocat(?:e|ed|es|ing)|accept(?:ed|ance|ing)?)\b"
    r"(?=.{0,120}\b(?:lgbtq?|trans(?:gender)?|queer|pride|community|rights)\b)|"
    r"\b(?:lgbtq?|trans(?:gender)?|queer|pride|community|rights)\b"
    r"(?=.{0,120}\b(?:ally|allies|supportive|supported|support|"
    r"encourag(?:e|ed|es|ing)|advocat(?:e|ed|es|ing)|accept(?:ed|ance|ing)?)\b)",
    re.IGNORECASE | re.DOTALL,
)

_ALLERGY_CONDITION_INFERENCE_ANSWER_TEXT_RE = re.compile(
    r"\b(?:allerg(?:y|ies|ic)|allergic\s+to)\b"
    r"(?=.{0,120}\b(?:animals?|pets?|reptiles?|cockroaches?|fur|puffy|itchy|"
    r"swollen|rash)\b)|"
    r"\b(?:animals?|pets?|reptiles?|cockroaches?|fur|puffy|itchy|swollen|rash)\b"
    r"(?=.{0,120}\b(?:allerg(?:y|ies|ic)|allergic\s+to)\b)|"
    r"\b(?:аллерги\w*)\b(?=.{0,120}\b(?:животн\w*|питомц\w*|рептили\w*|"
    r"шерст\w*|зуд|от[её]к\w*)\b)",
    re.IGNORECASE | re.DOTALL,
)

_CHOICE_ANSWER_TEXT_RE = re.compile(
    r"\b("
    r"prefer(?:s|red)?|chose|chosen|choose|selected|rather|more|less|"
    r"interested|enjoys?|likes?|loves?|dislikes?|avoids?|"
    r"close|near|nearby|by|next\s+to|lives?|living|located|walks?|goes|visits?|"
    r"camping|hiking|outdoors?|nature|theme\s+park|national\s+park|"
    r"предпоч\w*|выбр\w*|интерес\w*|нрав\w*|любит|не\s+любит|избега\w*|"
    r"близко|рядом|возле|живет|живёт|расположен\w*|ходит|ездит|океан|пляж|горы"
    r")\b",
    re.IGNORECASE,
)

_SPEAKER_ANSWER_TEXT_RE = re.compile(
    r"\bD\d+:\d+\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}:|"
    r"\b[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}\s+"
    r"(?:said|says|mentioned|mentions|told|wrote|asked|reported|noted|claimed)\b|"
    r"\b[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}\s+"
    r"(?:сказал|сказала|говорил|говорила|упомянул|упомянула|написал|написала|"
    r"спросил|спросила)\b",
    re.IGNORECASE,
)

_CONVERSATION_PARTICIPANT_ANSWER_TEXT_RE = re.compile(
    rf"\b{_ANSWER_LABEL_RE}\s+"
    r"(?:talked|spoke|met|chatted|messaged|dm(?:ed)?|called)\s+"
    rf"(?:to|with)?\s*{_ANSWER_LABEL_RE}\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+discussed\b.{{0,80}}\bwith\s+{_ANSWER_LABEL_RE}\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+had\s+(?:a\s+)?(?:call|chat|meeting)\s+with\s+"
    rf"{_ANSWER_LABEL_RE}\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+"
    r"(?:говорил\w*|общал\w*|встречал\w*|созванивал\w*|переписывал\w*)\s+"
    rf"(?:с|со)\s+{_ANSWER_LABEL_RE}\b",
    re.IGNORECASE,
)

_CONVERSATION_TOPIC_ANSWER_TEXT_RE = re.compile(
    rf"\b{_ANSWER_LABEL_RE}\s+"
    r"(?:talked|spoke|chatted|discussed)\b.{0,80}\babout\s+"
    rf"(?:the\s+)?{_ANSWER_LABEL_RE}\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+discussed\s+(?:the\s+)?{_ANSWER_LABEL_RE}\b"
    rf".{{0,80}}\bwith\s+{_ANSWER_LABEL_RE}\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+and\s+{_ANSWER_LABEL_RE}\s+"
    r"(?:talked|spoke|chatted|discussed)\b.{0,80}\b"
    rf"(?:about\s+)?(?:the\s+)?{_ANSWER_LABEL_RE}\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+"
    r"(?:говорил\w*|общал\w*|переписывал\w*)\b.{0,80}\b"
    rf"(?:о|об|про)\s+{_ANSWER_LABEL_RE}\b",
    re.IGNORECASE,
)

_COMMONALITY_ANSWER_TEXT_RE = re.compile(
    rf"\b{_ANSWER_LABEL_RE}\s+and\s+{_ANSWER_LABEL_RE}\s+"
    r"(?:both\s+)?(?:like|likes|liked|enjoy|enjoys|enjoyed|love|loves|loved|"
    r"prefer|prefers|preferred|lost|started|joined|attended|visited|played|"
    r"read|watched|bought|purchased|volunteered|worked|went|did|have|had|"
    r"were|are)\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+and\s+{_ANSWER_LABEL_RE}\s+share\s+"
    r"(?:a\s+)?(?:hobby|hobbies|interest|interests|activity|activities|"
    r"preference|preferences|love\s+of|interest\s+in)\b|"
    r"\b(?:both|common|mutual|overlapping)\b.{0,120}\b"
    r"(?:hobbies|interests|activities|likes|preferences|enjoy|love|favorite|favourite)\b|"
    r"\bshared\s+(?:hobbies|interests|activities|likes|preferences)\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+(?:also|too)\s+"
    r"(?:likes?|enjoys?|loves?|prefers?|is\s+interested\s+in)\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+и\s+{_ANSWER_LABEL_RE}\s+"
    r"(?:оба|обе|вместе)?\s*(?:любят|интересуются|увлекаются|предпочитают)\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+(?:тоже|также)\s+"
    r"(?:любит|интересуется|увлекается|предпочитает)\b|"
    r"\b(?:оба|обе|общ(?:ее|ие|ий|ая|его)|вместе)\b.{0,120}\b"
    r"(?:хобби|интерес|увлечен|увлечён|увлечения|любят|нравит|занятия)\b",
    re.IGNORECASE | re.DOTALL,
)

_CONSTRAINT_ANSWER_TEXT_RE = re.compile(
    r"\b(?:can'?t|cannot|can\s+not|unable\s+to|not\s+able\s+to)\b"
    r"(?=.{0,80}\b(?:eat|use|attend|join|take|wear|go|access|do)\b)|"
    r"\b(?:not\s+(?:like|likes|liked|interested|eat|eats|use|uses|want|wants|able)|"
    r"doesn'?t\s+(?:like|eat|enjoy|want|use)|does\s+not\s+"
    r"(?:like|eat|enjoy|want|use)|would\s+not\s+(?:like|eat|enjoy|want|use)|"
    r"never\s+(?:eat|eats|like|likes|use|uses)|dislikes?|hates?|avoids?|"
    r"allergic|restricted|blocked|discomfort|cannot\s+eat|can'?t\s+eat)\b|"
    r"\b(?:нельзя|не\s+может|не\s+любит|не\s+хочет|избега\w*|аллерги\w*|"
    r"ограничен\w*|запрещен\w*|запрещён\w*)\b",
    re.IGNORECASE,
)

_ACTION_ROLE_VERB_TEXT_RE = (
    r"recommended|suggested|promised|assigned|approved|heard|learned|helped|"
    r"assisted|supported|"
    r"introduced|sent|gave|"
    r"told|asked|decided|"
    r"рекомендовал(?:а)?|посоветовал(?:а)?|пообещал(?:а)?|обещал(?:а)?|"
    r"назначил(?:а)?|одобрил(?:а)?|отправил(?:а)?|дал(?:а)?|сказал(?:а)?|"
    r"спросил(?:а)?|решил(?:а)?|познакомил(?:а|и)?|представил(?:а|и)?|"
    r"узнал(?:а|и)?|услышал(?:а|и)?|помог(?:ла|ли)?|поддержал(?:а|и)?"
)

_ACTION_ROLE_ANSWER_TEXT_RE = re.compile(
    rf"\b{_ANSWER_LABEL_RE}\s+(?:{_ACTION_ROLE_VERB_TEXT_RE})\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+(?:made|gave|offered)\s+"
    r"(?:a\s+)?(?:decision|promise|recommendation|suggestion)\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+(?:is|was|'s)\s+"
    r"(?:responsible|(?:the\s+)?owner)\s+(?:for|of)\b|"
    rf"\b{_ANSWER_LABEL_RE}\s+owns?\b"
)

_POSSESSION_SOURCE_ANSWER_TEXT_RE = re.compile(
    r"\b(?:gift|present|keepsake)\b.{0,40}\bfrom\b.{0,90}\b"
    r"(?:grandma|grandmother|grandpa|grandfather|mother|father|mom|dad|"
    r"parent|friend|mentor|family|relative|home\s+country|native\s+country|"
    rf"{_ANSWER_LABEL_RE})\b|"
    r"\b(?:got|received)\b.{0,120}\bfrom\b.{0,90}\b"
    r"(?:grandma|grandmother|grandpa|grandfather|mother|father|mom|dad|"
    r"parent|friend|mentor|family|relative|home\s+country|native\s+country|"
    rf"{_ANSWER_LABEL_RE})\b|"
    r"\b(?:given|gifted)\b.{0,80}\bby\b.{0,90}\b"
    r"(?:grandma|grandmother|grandpa|grandfather|mother|father|mom|dad|"
    r"parent|friend|mentor|family|relative|home\s+country|native\s+country|"
    rf"{_ANSWER_LABEL_RE})\b",
    re.IGNORECASE | re.DOTALL,
)

_LOCATION_ANSWER_TEXT_RE = re.compile(
    r"\b(?:lives?|living|resides?|residing|based|located|born|raised|"
    r"camped|camping|hiked|hiking|moved|relocated|traveled|travelled|"
    r"visited|vacationed|went)\s+"
    rf"(?:in|at|near|by|from|to)\s+(?:the\s+)?{_ANSWER_LABEL_RE}\b|"
    rf"\b(?:visited|vacationed)\s+(?:the\s+)?{_ANSWER_LABEL_RE}\b|"
    r"\b(?:took|made|went\s+on)\s+(?:a\s+)?trip\s+"
    rf"(?:in|at|near|by|from|to)\s+(?:the\s+)?{_ANSWER_LABEL_RE}\b|"
    r"\b(?:home|address|city|country|hometown|birthplace)\s+"
    rf"(?:is|was|in|near|from|:)\s+{_ANSWER_LABEL_RE}\b|"
    r"\b(?:жив[её]т|прожива\w*|наход\w*|родил\w*|переехал\w*)\s+"
    rf"(?:в|на|из|рядом\s+с|около)\s+{_ANSWER_LABEL_RE}\b|"
    r"\b(?:ездил\w*|поехал\w*|путешеств\w*|отдыхал\w*)\s+"
    rf"(?:в|на|к|по|рядом\s+с|около)\s+(?:город\s+|страну\s+)?{_ANSWER_LABEL_RE}\b|"
    rf"\b(?:посетил\w*)\s+(?:город\s+|страну\s+)?{_ANSWER_LABEL_RE}\b|"
    r"\b(?:поездк\w*|отпуск)\s+"
    rf"(?:в|на|к|по|рядом\s+с|около)\s+(?:город\s+|страну\s+)?{_ANSWER_LABEL_RE}\b"
)

_PREFERENCE_ANSWER_TEXT_RE = re.compile(
    r"\b(?:favorite|favourite)\s+[^.?!]{0,80}\s+(?:is|was|are|were)\b|"
    r"\b(?:prefers?|preferred|likes?|liked|enjoys?|enjoyed|loves?|loved|"
    r"interested\s+in|fan\s+of|dislikes?|hates?)\b|"
    r"\b(?:любим\w*|предпоч\w*|нравит\w*|интересует\w*|любит|не\s+любит)\b",
    re.IGNORECASE,
)

_RELATIONSHIP_ANSWER_TEXT_RE = re.compile(
    r"\b(?:relationship\s+status|married\s+to|been\s+married|got\s+married|"
    r"single|dating|breakup|broke\s+up|divorced|engaged|partnered)\b|"
    r"\b(?:connected|related|linked|associated|involved|stakeholders?|contacts?|"
    r"participants?|collaborators?)\b|"
    r"\b(?:husband|wife|spouse|partner|boyfriend|girlfriend|fianc(?:e|ee)|"
    r"friend|best\s+friend|old\s+friend|sibling|brother|sister|mother|father|"
    r"parent|child|daughter|son|family|mentor|roommate|colleague|coworker)\b|"
    r"\b(?:связан\w*|относятся|участвуют|вовлечен\w*|вовлечён\w*|"
    r"стейкхолдер\w*|контакт\w*|участник\w*)\b|"
    r"\b(?:статус\s+отношен\w*|женат|замужем|встречается|одинок\w*|развел\w*|"
    r"помолвлен\w*|муж|жена|партнер|партнёр|друг|подруга|брат|сестра|мать|"
    r"отец|родител\w*|сын|дочь|семь\w*|наставник|коллега|сосед\w*)\b",
    re.IGNORECASE,
)

_COMMITMENT_ANSWER_TEXT_RE = re.compile(
    r"\b(?:action\s+items?|todo|to-do|follow\s*-?\s*up|next\s+steps?|"
    r"tasks?|assigned\s+to|assignee|owner|responsible|deadline|due\s+date|"
    r"due\s+by|overdue|deliverable|milestone|reminder|commitment|committed|"
    r"agreed\s+to|promised|made\s+(?:a\s+)?promise|needs?\s+to|has\s+to|"
    r"supposed\s+to|expected\s+to|must)\b|"
    r"\b(?:задач\w*|дел\w*|фоллоу\s*-?\s*ап|следующ\w+\s+шаг\w*|"
    r"ответственн\w*|назначен\w*|дедлайн|срок|просрочен\w*|напоминан\w*|"
    r"обязал\w*|пообещал\w*|обещал\w*|нужно|должен|должна|должны)\b",
    re.IGNORECASE,
)

_GOTCHA_ANSWER_TEXT_RE = re.compile(
    r"\b(?:gotchas?|pitfalls?|caveats?|known\s+issues?|known\s+problems?|"
    r"failure\s+mode|failed|failure|error|broke|blocked|blocker|risk|warning|"
    r"workarounds?|root\s+cause|troubleshoot(?:ing)?|avoid|do\s+not\s+repeat|"
    r"next\s+time|prerequisite|limitation|trap)\b|"
    r"\b(?:подводн\w+\s+камн\w*|известн\w+\s+(?:проблем\w*|ошибк\w*)|"
    r"ошибк\w*|сбо\w*|сломал\w*|упал\w*|заблокировал\w*|риск|"
    r"предупрежден\w*|предупреждён\w*|обходн\w+\s+пут\w*|воркэраунд\w*|"
    r"избегать|не\s+повторять|ограничен\w*|ловушк\w*)\b",
    re.IGNORECASE | re.DOTALL,
)

_EXISTENCE_ANSWER_TEXT_RE = re.compile(
    r"\b(?:mentioned?|said|wrote|reported|noted|recorded|found|confirmed|"
    r"there\s+(?:is|are|was|were)|has|have|had)\b|"
    r"\b(?:no\s+(?:evidence|proof|record|mention|source)|not\s+mentioned|"
    r"never\s+mentioned|unknown|not\s+known|none|no\s+candidate|not\s+found)\b|"
    r"\b(?:упомянул\w*|сказал\w*|написал\w*|сообщил\w*|найден\w*|"
    r"подтвержден\w*|подтверждён\w*|есть|нет\s+(?:данных|доказательств|"
    r"упоминан\w*)|не\s+упоминал\w*|никогда\s+не\s+упоминал\w*|неизвестно)\b",
    re.IGNORECASE,
)

_STATE_UPDATE_ANSWER_TEXT_RE = re.compile(
    r"\b(?:latest|current|currently|most\s+recent|newest|final|canonical|"
    r"source\s+of\s+truth|right\s+now|at\s+the\s+moment|as\s+of\s+now|"
    r"still|remains?|kept|selected|chosen|settled|no\s+longer|anymore|"
    r"stale|outdated|obsolete|deprecated|previous|old|prior|before|"
    r"changed|updated|replaced|superseded|switched|migrated|transitioned|"
    r"now\s+(?:uses?|is|are))\b|"
    r"\b(?:актуальн\w*|текущ\w*|последн\w*|сейчас|на\s+данный\s+момент|"
    r"вс[её]\s+еще|вс[её]\s+ещ[её]|по-прежнему|больше\s+не|уже\s+не|"
    r"устаревш\w*|стар\w*|предыдущ\w*|раньше|изменил\w*|изменилось|"
    r"обновил\w*|обновлен\w*|обновлён\w*|заменил\w*|поменял\w*)\b",
    re.IGNORECASE,
)

_SUMMARY_ANSWER_TEXT_RE = re.compile(
    r"\b(?:profile|summary|overview|background|biography|bio|key\s+facts?|"
    r"person\s+profile|project\s+profile|project\s+summary|current\s+status)\b|"
    r"\b(?:профиль|сводка|обзор|кратко|биография|ключев\w+\s+факт\w*|"
    r"текущ\w+\s+статус)\b",
    re.IGNORECASE,
)

_EVENT_QUERY_HINT_RE = re.compile(
    r"\b("
    r"call|meeting|sync|chat|message|said|wrote|told|"
    r"звонок|созвон|встреча|чат|переписка|сказал|сказала|написал|написала"
    r")\b",
    re.IGNORECASE,
)

_EXPLICIT_PROJECT_HINT_RE = re.compile(
    r"\b(project|repo|repository|service|проект|репозитор|сервис)\b",
    re.IGNORECASE,
)

_EXPLICIT_PERSON_HINT_RE = re.compile(
    r"\b(person|people|who|with|from|человек|люди|кто|с кем|от кого)\b",
    re.IGNORECASE,
)

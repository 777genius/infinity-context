"""Shared query expansion rule terms."""

from __future__ import annotations

MAX_QUERY_EXPANSIONS = 8
_SUPPORT_NETWORK_EXPANSION = (
    "support network friends family mentors mother father parents coach "
    "teacher counselor siblings partner rocks there for helped comfort "
    "encourage encouraged strength motivate support system people around "
    "trusted reliable emotional support"
)
_SUPPORT_NETWORK_HELP_EXPANSION = (
    f"{_SUPPORT_NETWORK_EXPANSION} helped through hard time"
)
_RU_SUPPORT_NETWORK_EXPANSION = (
    "поддерживает поддержка рядом друзья семья наставники помогают помогли "
    "мама отец родители тренер учитель опора мотивация сила trusted reliable "
    "emotional support friends family mentors mother coach rocks"
)
_RU_SUPPORT_NETWORK_PAST_SUPPORT_EXPANSION = (
    "поддерживает поддержка рядом друзья семья наставники помогают помогли "
    "поддержал поддержала поддержали мама отец родители тренер учитель "
    "опора мотивация сила trusted reliable emotional support friends family "
    "mentors mother coach rocks"
)
_RU_SUPPORT_NETWORK_HELP_EXPANSION = (
    "поддерживает поддержка рядом друзья семья наставники помогают помогли "
    "помог помогла помогли мама отец родители тренер учитель опора мотивация "
    "сила trusted reliable emotional support friends family mentors mother "
    "coach rocks"
)

_CONVERSATION_TRANSCRIPT_EXPANSION = (
    "transcript conversation chat message dm spoke talked said told mentioned "
    "discussed covered centered topic agenda decision action item follow up "
    "speaker turn quote транскрипт разговор встреча созвон переписка чат "
    "сообщение обсудили тема повестка реплика цитата"
)
_RU_CONVERSATION_TRANSCRIPT_EXPANSION = (
    "транскрипт разговор переписка созвон сообщение сказал сказала обсудили "
    "упомянул упомянула покрыли тема повестка решение задача follow up "
    "реплика спикер цитата"
)
_SPEAKER_TURN_EXPANSION = (
    "speaker dialogue turn transcript quote said told mentioned discussed "
    "conversation source реплика спикер сказал сказала рассказал рассказала"
)
_CURRENT_RECOMMENDATION_EXPANSION = (
    "recommended preferred decided chose chosen selected switched should use choose "
    "current active provider tool model option engine database service retrieval "
    "latest valid not stale"
)
_CURRENT_DECISION_EXPANSION = (
    "final decision decided selected chosen approved settled source of truth canonical "
    "current active latest valid not stale provider tool model option plan decision "
    "финальный окончательный выбранный актуальный текущий источник правды"
)
_RECOMMENDATION_SOURCE_EXPANSION = (
    "recommendation suggestion advice recommended suggested advised follow followed "
    "because of based on after from source actor recipient to for read watched tried "
    "used visited listened started played made bought"
)
_BOOK_SUGGESTION_EXPANSION = (
    "book suggestion recommended becoming nicole amy ellis nutt true story trans girl "
    "family hope connection self acceptance reading that book a while ago tough "
    "doing ok painting keep busy"
)
_STATE_TRANSITION_EXPANSION = (
    "state transition changed switched switch replaced replacement migrated "
    "from to previous old current new active final selected superseded no longer "
    "valid not current replaced by before after"
)
_COMMONALITY_INTEREST_EXPANSION = (
    "common shared both mutual same similar overlap interests hobbies activities "
    "enjoy like love prefer painting camping hiking music books games food art "
    "watching movies desserts recipes baking evidence"
)
_NEGATIVE_PREFERENCE_EXPANSION = (
    "does not like doesn't like dislike dislikes disliked hate hates hated "
    "avoid avoids avoided not enjoy never enjoy preference discomfort "
    "overwhelming too loud unsafe unpleasant"
)
_FRIEND_PLACE_INVENTORY_EXPANSION = (
    "friends made friends places where homeless shelter fellow volunteer joined gym "
    "church awesome people welcoming atmosphere positive environment community faith "
    "nearby closer met people local volunteer volunteering"
)
_FRIEND_PLACE_SHELTER_INVENTORY_EXPANSION = (
    "friends made friends homeless shelter fellow volunteer volunteers volunteering "
    "donated old car shelter where volunteer at helping others"
)
_FRIEND_PLACE_GYM_INVENTORY_EXPANSION = (
    "friends made friends joined gym workout routine supportive people welcoming "
    "atmosphere positive environment awesome people gym friend"
)
_FRIEND_PLACE_CHURCH_INVENTORY_EXPANSION = (
    "joined nearby church community faith closer local church"
)
_TRAVEL_COUNTRY_INVENTORY_EXPANSION = (
    "England Spain Rome Paris London abroad solo trip travel visited went been to "
    "short trip city place destination European countries country"
)
_CAUSE_EDUCATION_INFRASTRUCTURE_EXPANSION = (
    "improving education infrastructure particularly interesting interested community "
    "education reform infrastructure development"
)
_CAUSE_VETERANS_EXPANSION = (
    "veterans rights passionate support military project petition appreciation community"
)
_TRIP_DESTINATION_EXPANSION = (
    "trip travel traveled travelled visit visited vacation destination place city "
    "country mountains beach park went journey route stayed location to in near "
    "поездка отпуск путешествие ездил ездила ездили поехал поехала посетил "
    "посетила куда место город страна горы пляж парк"
)
_DESTRESS_ACTIVITY_EXPANSION = (
    "running pottery class therapeutic therapy calm relax clear mind headspace unwind "
    "расслабиться расслабляется расслаблялась отдохнуть отдыхает снять стресс "
    "успокоиться спокойствие терапевтичный прояснить голову"
)
_RUNNING_REASON_EXPANSION = (
    "running run farther longer de-stress destress clear mind headspace "
    "mood boost shoes purple walking or running what got into running"
)
_RUNNING_REASON_QUESTION_EXPANSION = (
    "what got you into running got into running why started running "
    "reason asked question walking or running"
)
_CLASSICAL_MUSIC_PREFERENCE_EXPANSION = (
    "music classical fan composer bach mozart vivaldi orchestra symphony "
    "artist song enjoy four seasons"
)
_CAREER_INTENT_EXPANSION = (
    "current career option pursue looking into counseling counselor mental "
    "health jobs education options next steps figure out work goal decided"
)
_ART_STYLE_EXPANSION = (
    "art painting artwork art show preview abstract style kind type "
    "inclusivity diversity representation identity self acceptance"
)
_ANIMAL_CAREER_INFERENCE_EXPANSION = (
    "alternative career animal keeper zookeeper zoo pets reptiles turtles care "
    "habitat responsible responsibility animal lover"
)
_ANIMAL_CARE_INSTRUCTION_EXPANSION = (
    "animal care instructions clean area clean tank feed properly enough light "
    "habitat routine responsible responsibility pets reptiles turtles keeper zoo"
)
_ANIMAL_DIET_EVIDENCE_EXPANSION = (
    "animal diet turtles feed eat eating vegetables fruits insects varied diet "
    "greens lettuce food properly care reptiles keeper zoo"
)
_ANIMAL_HABITAT_SETUP_EXPANSION = (
    "animal habitat setup new tank bigger tank room swim cute pet turtles little "
    "dudes pets reptiles aquarium care keeper zoo"
)
_ANIMAL_AFFINITY_PET_STORE_EXPANSION = (
    "animal affinity turtles pets pet store joy peace companion companions tank "
    "third turtle enjoys loves animal lover reptiles zookeeper keeper"
)

__all__ = (
    "MAX_QUERY_EXPANSIONS",
    "_SUPPORT_NETWORK_EXPANSION",
    "_SUPPORT_NETWORK_HELP_EXPANSION",
    "_RU_SUPPORT_NETWORK_EXPANSION",
    "_RU_SUPPORT_NETWORK_PAST_SUPPORT_EXPANSION",
    "_RU_SUPPORT_NETWORK_HELP_EXPANSION",
    "_CONVERSATION_TRANSCRIPT_EXPANSION",
    "_RU_CONVERSATION_TRANSCRIPT_EXPANSION",
    "_SPEAKER_TURN_EXPANSION",
    "_CURRENT_RECOMMENDATION_EXPANSION",
    "_CURRENT_DECISION_EXPANSION",
    "_RECOMMENDATION_SOURCE_EXPANSION",
    "_BOOK_SUGGESTION_EXPANSION",
    "_STATE_TRANSITION_EXPANSION",
    "_COMMONALITY_INTEREST_EXPANSION",
    "_FRIEND_PLACE_INVENTORY_EXPANSION",
    "_FRIEND_PLACE_SHELTER_INVENTORY_EXPANSION",
    "_FRIEND_PLACE_GYM_INVENTORY_EXPANSION",
    "_FRIEND_PLACE_CHURCH_INVENTORY_EXPANSION",
    "_TRAVEL_COUNTRY_INVENTORY_EXPANSION",
    "_CAUSE_EDUCATION_INFRASTRUCTURE_EXPANSION",
    "_CAUSE_VETERANS_EXPANSION",
    "_TRIP_DESTINATION_EXPANSION",
    "_DESTRESS_ACTIVITY_EXPANSION",
    "_ANIMAL_CAREER_INFERENCE_EXPANSION",
    "_ANIMAL_CARE_INSTRUCTION_EXPANSION",
    "_ANIMAL_DIET_EVIDENCE_EXPANSION",
    "_ANIMAL_HABITAT_SETUP_EXPANSION",
    "_ANIMAL_AFFINITY_PET_STORE_EXPANSION",
)

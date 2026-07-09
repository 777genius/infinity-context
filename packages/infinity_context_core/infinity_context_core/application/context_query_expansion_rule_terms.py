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
    "recommend it definitely would because of based on after from source actor "
    "recipient to for should get should start for one also another pointers tips "
    "ideas how about make sure invest in look for great one good one read watched "
    "tried used visited listened started played made bought try buy visit play make"
)
_BOOK_SUGGESTION_EXPANSION = (
    "book suggestion recommended becoming nicole amy ellis nutt true story trans girl "
    "family hope connection self acceptance reading that book a while ago tough "
    "doing ok painting keep busy recommend reccomend recommended reccomended "
    "suggestion suggested must-see must see great one great read fantasy series "
    "story finished think watched movie title"
)
_STATE_TRANSITION_EXPANSION = (
    "state transition changed switched switch replaced replacement migrated "
    "from to previous old current new active final selected superseded no longer "
    "valid not current replaced by before after"
)
_COMMONALITY_INTEREST_EXPANSION = (
    "common shared both mutual same similar overlap interests hobbies activities "
    "enjoy like love prefer painting camping hiking music books games food art "
    "watching movies desserts recipes baking cakes icecream coconut milk dairy-free "
    "sweet treats revised old recipes made enjoy desserts bake baked animals pets "
    "turtles reptiles animal affinity companion calming joy peace strength "
    "perseverance inspire inspiring motivate motivation evidence"
)
_COMMONALITY_ANIMAL_AFFINITY_EXPANSION = (
    "common shared both mutual same similar animal animals pets turtles reptiles "
    "animal affinity drawn to like love enjoy prefer chose choose as pets unique "
    "slow pace low-maintenance calming calm companion joy peace resilience "
    "strength perseverance inspire inspiring motivates motivate motivation"
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
    "friends made friends joined nearby church community faith closer local "
    "church feel closer to a community and faith"
)
_CHURCH_FRIEND_ACTIVITY_INVENTORY_EXPANSION = (
    "church friends activities activity went with church friends visited visit hike "
    "hiking picnic park group outing trip camping local church together "
    "friends from church community work community service volunteer work volunteering "
    "chilled trees played games charades scavenger hunt food refreshed"
)
_TRAVEL_COUNTRY_INVENTORY_EXPANSION = (
    "abroad overseas solo trip travel traveled travelled visited went been to "
    "visit visits visiting "
    "short trip city cities capital capitals place places destination destinations "
    "country countries European Europe landmark landmarks itinerary tour photo photos "
    "picture pictures pic image caption visual query"
)
_ITEM_COLLECTION_INVENTORY_EXPANSION = (
    "items objects possessions collection collect collects collecting keeps owns "
    "sneakers shoes jerseys movies movie dvds dvd media memorabilia figurines "
    "visual query image caption photo"
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
    "country mountains beach park went journey route stayed location locations "
    "geographical been to in near tour met meet chat chatted was were spent "
    "photo picture image caption visual query "
    "поездка отпуск путешествие ездил ездила ездили поехал поехала посетил "
    "посетила куда место город страна горы пляж парк"
)
_TRAVEL_HOBBY_WRITING_EXPANSION = (
    "travel traveling travelling trip trips journey destination destinations places "
    "visit visited dream dreams hobby pastime creative writing write wrote written "
    "articles article stories story blog blogging posts online magazine reading "
    "sharing experiences landmarks cities countries photos"
)
_THEMED_LOCATION_DESTINATION_EXPANSION = (
    "related locations places would enjoy visit recommendation destination trip "
    "travel traveled travelled stay stayed staying study abroad semester accepted "
    "applied off to going to headed to country city place location favorite "
    "favourite movie film book series fantasy fiction world universe fan tour "
    "explore real places"
)
_THEMED_LOCATION_DESTINATION_ANCHOR_EXPANSION = (
    "visit destination trip travel traveled travelled stay stayed staying abroad "
    "study abroad semester accepted applied program off to going to headed to "
    "country city place location live living"
)
_NATIONAL_PARK_INFERENCE_EXPANSION = (
    "national park road trip travel destination hiking hike trails trail map route "
    "park map trees forest lake field grass dogs pup photo image caption visual query "
    "sign planning next month nearby beautiful"
)
_DESTRESS_ACTIVITY_EXPANSION = (
    "running pottery class therapeutic therapy calm relax clear mind headspace unwind "
    "dance dancing dance studio stress relief stress fix passion escape go-to "
    "расслабиться расслабляется расслаблялась отдохнуть отдыхает снять стресс "
    "успокоиться спокойствие терапевтичный прояснить голову"
)
_STUDY_TIME_MANAGEMENT_EXPANSION = (
    "exam exams finals test tests prep prepare studying study time management "
    "technique method strategy pomodoro 25 minutes 5 minutes intervals breaks "
    "smaller parts focused focus less overwhelming keeps on track fun swamped "
    "plowing through week"
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
_POST_ATHLETIC_CAREER_EXPANSION = (
    "basketball coach coaching mentor leadership leader great puts others first "
    "eventually becomes king aragorn sports marketing seminars helping people "
    "share knowledge platform positive difference inspire charity foundation "
    "meaningful legacy off court give back future after life post athletic young "
    "athletes youth camp teaching"
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
_ANIMAL_ACTIVITY_INVENTORY_EXPANSION = (
    "animal pet turtle activities activity feeding feed eat eating fruit snacks "
    "strawberries holding hold bath bathe walking walk play care favorite snacks"
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
    "_COMMONALITY_ANIMAL_AFFINITY_EXPANSION",
    "_FRIEND_PLACE_INVENTORY_EXPANSION",
    "_FRIEND_PLACE_SHELTER_INVENTORY_EXPANSION",
    "_FRIEND_PLACE_GYM_INVENTORY_EXPANSION",
    "_FRIEND_PLACE_CHURCH_INVENTORY_EXPANSION",
    "_TRAVEL_COUNTRY_INVENTORY_EXPANSION",
    "_ITEM_COLLECTION_INVENTORY_EXPANSION",
    "_CAUSE_EDUCATION_INFRASTRUCTURE_EXPANSION",
    "_CAUSE_VETERANS_EXPANSION",
    "_TRIP_DESTINATION_EXPANSION",
    "_NATIONAL_PARK_INFERENCE_EXPANSION",
    "_DESTRESS_ACTIVITY_EXPANSION",
    "_STUDY_TIME_MANAGEMENT_EXPANSION",
    "_POST_ATHLETIC_CAREER_EXPANSION",
    "_ANIMAL_CAREER_INFERENCE_EXPANSION",
    "_ANIMAL_CARE_INSTRUCTION_EXPANSION",
    "_ANIMAL_DIET_EVIDENCE_EXPANSION",
    "_ANIMAL_HABITAT_SETUP_EXPANSION",
    "_ANIMAL_AFFINITY_PET_STORE_EXPANSION",
    "_ANIMAL_ACTIVITY_INVENTORY_EXPANSION",
)

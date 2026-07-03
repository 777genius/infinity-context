"""Static query expansion rule catalog part 1."""

from __future__ import annotations

from infinity_context_core.application import context_query_expansion_rule_terms as _terms
from infinity_context_core.application.context_query_artifact_inventory_expansions import (
    ARTIFACT_INVENTORY_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_entity_relation_expansions import (
    ENTITY_RELATION_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_event_summary_expansions import (
    EVENT_SUMMARY_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_organization_summary_expansions import (
    ORGANIZATION_SUMMARY_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_personal_fact_expansions import (
    PERSONAL_FACT_EXPANSION_RULES,
)
from infinity_context_core.application.context_query_project_summary_expansions import (
    PROJECT_SUMMARY_EXPANSION_RULES,
)

EXPANSION_RULES_PART_1: tuple[tuple[frozenset[str], str, str], ...] = (
    *PERSONAL_FACT_EXPANSION_RULES,
    *PROJECT_SUMMARY_EXPANSION_RULES,
    *ORGANIZATION_SUMMARY_EXPANSION_RULES,
    *ENTITY_RELATION_EXPANSION_RULES,
    *EVENT_SUMMARY_EXPANSION_RULES,
    *ARTIFACT_INVENTORY_EXPANSION_RULES,
    (
            frozenset({"identity"}),
            (
                "identity transgender trans woman transition gender identity true self "
                "pride flag mural support group stories accepted embrace myself"
            ),
            "identity_bridge",
        ),
    (
            frozenset({"relationship", "status"}),
            (
                "relationship status single parent breakup partner married husband wife "
                "spouse dating not dating single divorced separated romantic partner "
                "life partner girlfriend boyfriend fiance fiancee after breakup tough "
                "breakup relationship"
            ),
            "relationship_status_bridge",
        ),
    (
            frozenset({"nickname"}),
            (
                "nickname nick name called call address addressed greeting hey hi "
                "shortened name pet name"
            ),
            "nickname_bridge",
        ),
    (
            frozenset({"друзья"}),
            (
                "отношения статус друзья дружба пара партнер супруг семья вместе "
                "relationship status friends friendship partner dating family together"
            ),
            "relationship_status_bridge",
        ),
    (
            frozenset({"отношения"}),
            (
                "отношения статус друзья дружба пара партнер супруг семья вместе "
                "relationship status friends friendship partner dating family together"
            ),
            "relationship_status_bridge",
        ),
    (
            frozenset({"пара"}),
            (
                "отношения статус пара партнеры супруги dating married together "
                "relationship status partner spouse couple family together"
            ),
            "relationship_status_bridge",
        ),
    (
            frozenset({"связан"}),
            (
                "как связан связаны отношения статус друзья дружба семья партнер "
                "relationship status connected related friend partner family"
            ),
            "relationship_status_bridge",
        ),
    (
            frozenset({"where", "meet"}),
            (
                "relationship origin first met meet meeting introduced known since "
                "where when how at in during through school college work event place"
            ),
            "relationship_origin_bridge",
        ),
    (
            frozenset({"when", "meet"}),
            (
                "relationship origin first met meet meeting introduced known since "
                "where when how at in during through school college work event date"
            ),
            "relationship_origin_bridge",
        ),
    (
            frozenset({"how", "meet"}),
            (
                "relationship origin first met meet meeting introduced known since "
                "where when how at in during through school college work event friend"
            ),
            "relationship_origin_bridge",
        ),
    (
            frozenset({"first", "met"}),
            (
                "relationship origin first met meet meeting introduced known since "
                "where when how at in during through school college work event date"
            ),
            "relationship_origin_bridge",
        ),
    (
            frozenset({"где", "познакомились"}),
            (
                "где когда как впервые познакомились встретились знакомы с школа "
                "университет колледж работа событие место relationship origin first met"
            ),
            "relationship_origin_bridge",
        ),
    (
            frozenset({"когда", "познакомились"}),
            (
                "где когда как впервые познакомились встретились знакомы с школа "
                "университет колледж работа событие дата relationship origin first met"
            ),
            "relationship_origin_bridge",
        ),
    (
            frozenset({"где", "встретились"}),
            (
                "где когда как впервые познакомились встретились знакомы с школа "
                "университет колледж работа событие место relationship origin first met"
            ),
            "relationship_origin_bridge",
        ),
    (
            frozenset({"когда", "встретились"}),
            (
                "где когда как впервые познакомились встретились знакомы с школа "
                "университет колледж работа событие дата relationship origin first met"
            ),
            "relationship_origin_bridge",
        ),
    (
            frozenset({"как", "встретились"}),
            (
                "где когда как впервые познакомились встретились знакомы с школа "
                "университет колледж работа событие место relationship origin first met"
            ),
            "relationship_origin_bridge",
        ),
    (
            frozenset({"как", "познакомились"}),
            (
                "где когда как впервые познакомились встретились знакомы с школа "
                "университет колледж работа событие место relationship origin first met"
            ),
            "relationship_origin_bridge",
        ),
    (
            frozenset({"why"}),
            (
                "why reason because motivation motivated made difference realized "
                "indicates showed explains supporting evidence journey support care "
                "help decided chose want wants passionate"
            ),
            "motivation_reason_bridge",
        ),
    (
            frozenset({"office", "again"}),
            (
                "running office again run for office campaign public office politics "
                "after last run impact community make difference positive changes "
                "better future rewarding enthusiasm excited zeal"
            ),
            "public_office_service_bridge",
        ),
    (
            frozenset({"recognition"}),
            (
                "recognition award medal certificate honor honour honored honoured "
                "received receive got given gave earned won trophy prize appreciation "
                "volunteer shelter homeless helped help humbling glad could help"
            ),
            "recognition_award_bridge",
        ),
    (
            frozenset({"certificate"}),
            (
                "recognition award medal certificate honor honour honored honoured "
                "received receive got given gave earned won trophy prize appreciation "
                "completion completed diploma degree volunteer shelter homeless helped help"
            ),
            "recognition_award_bridge",
        ),
    (
            frozenset({"почему"}),
            (
                "почему причина потому что мотивация объясняет показывает доказательство "
                "поддержка решил решила хочет why reason because evidence"
            ),
            "motivation_reason_bridge",
        ),
    (
            frozenset({"start", "store"}),
            (
                "started business own store online clothing store job loss lost job "
                "Door Dash doordash banker fashion trends unique pieces blend dance "
                "fashion creative dream passionate"
            ),
            "business_start_reason_bridge",
        ),
    (
            frozenset({"clothing", "store"}),
            (
                "started business own store online clothing store job loss lost job "
                "Door Dash doordash banker fashion trends unique pieces blend dance "
                "fashion creative dream passionate"
            ),
            "business_start_reason_bridge",
        ),
    (
            frozenset({"business", "start"}),
            (
                "started business own store online clothing store job loss lost job "
                "Door Dash doordash banker fashion trends unique pieces blend dance "
                "fashion creative dream passionate"
            ),
            "business_start_reason_bridge",
        ),
    (
            frozenset({"promote", "store"}),
            (
                "working online store local artist cool designs limited "
                "edition line show off style creativity offers promotions new "
                "customers bring developed video presentation teach fashion pieces"
            ),
            "store_promotion_inventory_bridge",
        ),
    (
            frozenset({"events", "promote", "business"}),
            (
                "went fair show off studio possible leads networking events make "
                "things happen yesterday chose determined focused online store offers "
                "promotions new customers dance competition business venture"
            ),
            "business_promotion_event_bridge",
        ),
    (
            frozenset({"events", "promote", "business"}),
            (
                "networking events make things happen yesterday chose determined "
                "focused attending networking events guts drive make connections "
                "business venture losing job"
            ),
            "business_networking_event_bridge",
        ),
    (
            frozenset({"events", "promote", "business"}),
            (
                "online store offers promotions new customers bring wild ride "
                "starting business not giving up business venture store promotion"
            ),
            "business_store_promotion_event_bridge",
        ),
    (
            frozenset({"long", "open", "studio"}),
            (
                "lost job banker yesterday take shot starting own business grand "
                "opening tomorrow open studio six months timeline duration"
            ),
            "business_opening_timeline_bridge",
        ),
    (
            frozenset({"shelter", "girl"}),
            (
                "shelter little girl sitting alone sad no other family comfort "
                "listening ear laughed talk volunteer event help"
            ),
            "shelter_comfort_reason_bridge",
        ),
        (
            frozenset({"charity", "organization"}),
            (
                "charity organization sponsorship brand endorsement athletic partner "
                "company basketball shoe gear equipment deal work with prominent make "
                "difference away from court give back inspire people always liked "
                "working with them cool dream brand youth sports disadvantaged "
                "underserved kids"
            ),
            "charity_brand_sponsorship_bridge",
        ),
        (
            frozenset({"charity", "why"}),
            (
                "charity organization sponsorship brand endorsement athletic partner "
                "company basketball shoe gear equipment deal work with prominent make "
                "difference away from court give back inspire people always liked "
                "working with them cool dream brand youth sports disadvantaged "
                "underserved kids"
            ),
            "charity_brand_sponsorship_bridge",
        ),
    (
            frozenset({"yoga", "why"}),
            (
                "yoga put off delay postponed planned play console partner video games "
                "Walking Dead next Saturday old games gaming instead"
            ),
            "yoga_delay_gaming_bridge",
        ),
    (
            frozenset({"yoga", "off"}),
            (
                "yoga put off delay postponed planned play console partner video games "
                "Walking Dead next Saturday old games gaming instead"
            ),
            "yoga_delay_gaming_bridge",
        ),
    (
            frozenset({"basketball", "career"}),
            _terms._POST_ATHLETIC_CAREER_EXPANSION,
            "post_athletic_career_bridge",
        ),
    (
            frozenset({"athletic", "career"}),
            _terms._POST_ATHLETIC_CAREER_EXPANSION,
            "post_athletic_career_bridge",
        ),
    (
            frozenset({"sports", "career"}),
            _terms._POST_ATHLETIC_CAREER_EXPANSION,
            "post_athletic_career_bridge",
        ),
    (
            frozenset({"pursue", "career"}),
            _terms._CAREER_INTENT_EXPANSION,
            "career_intent_bridge",
        ),
    (
            frozenset({"career", "option"}),
            _terms._CAREER_INTENT_EXPANSION,
            "career_intent_bridge",
        ),
    (
            frozenset({"writing", "career"}),
            (
                "creative writing author books reading literature stories novels "
                "guide motivate discover journey passion career option interest"
            ),
            "creative_writing_career_bridge",
        ),
    (
            frozenset({"write", "career"}),
            (
                "creative writing author books reading literature stories novels "
                "guide motivate discover journey passion career option interest"
            ),
            "creative_writing_career_bridge",
        ),
    (
            frozenset({"submitted", "work"}),
            (
                "submit submitted submitting submission work project screenplay script "
                "film festivals film festival contest competition producers directors "
                "check out places destinations"
            ),
            "creative_work_submission_bridge",
        ),
    (
            frozenset({"submit", "work"}),
            (
                "submit submitted submitting submission work project screenplay script "
                "film festivals film festival contest competition producers directors "
                "check out places destinations"
            ),
            "creative_work_submission_bridge",
        ),
    (
            frozenset({"submit", "project"}),
            (
                "submit submitted submitting submission work project screenplay script "
                "film festivals film festival contest competition producers directors "
                "check out places destinations"
            ),
            "creative_work_submission_bridge",
        ),
    (
            frozenset({"submit", "screenplay"}),
            (
                "submit submitted submitting submission work project screenplay script "
                "film festivals film festival contest competition producers directors "
                "check out places destinations"
            ),
            "creative_work_submission_bridge",
        ),
    (
            frozenset({"kind", "writing"}),
            (
                "writing writings screenplay screenplays script scripts book books "
                "journal online blog post story stories projects wrote started "
                "finished full screenplay work working made"
            ),
            "creative_writing_inventory_bridge",
        ),
    (
            frozenset({"kind", "writings"}),
            (
                "writing writings screenplay screenplays script scripts book books "
                "journal online blog post story stories projects wrote started "
                "finished full screenplay work working made"
            ),
            "creative_writing_inventory_bridge",
        ),
    (
            frozenset({"type", "writing"}),
            (
                "writing writings screenplay screenplays script scripts book books "
                "journal online blog post story stories projects wrote started "
                "finished full screenplay work working made"
            ),
            "creative_writing_inventory_bridge",
        ),
    (
            frozenset({"types", "writing"}),
            (
                "writing writings screenplay screenplays script scripts book books "
                "journal online blog post story stories projects wrote started "
                "finished full screenplay work working made"
            ),
            "creative_writing_inventory_bridge",
        ),
    (
            frozenset({"hobby", "travel"}),
            _terms._TRAVEL_HOBBY_WRITING_EXPANSION,
            "travel_hobby_writing_bridge",
        ),
    (
            frozenset({"hobby", "dream"}),
            _terms._TRAVEL_HOBBY_WRITING_EXPANSION,
            "travel_hobby_writing_bridge",
        ),
    (
            frozenset({"hobbies", "travel"}),
            _terms._TRAVEL_HOBBY_WRITING_EXPANSION,
            "travel_hobby_writing_bridge",
        ),
    (
            frozenset({"career", "want"}),
            _terms._CAREER_INTENT_EXPANSION,
            "career_intent_bridge",
        ),
    (
            frozenset({"career", "wants"}),
            _terms._CAREER_INTENT_EXPANSION,
            "career_intent_bridge",
        ),
    (
            frozenset({"career", "path"}),
            (
                "career path decided pursue persue education options counseling "
                "mental health jobs work looking considering goal"
            ),
            "career_path_bridge",
        ),
    (
            frozenset({"field", "pursue"}),
            (
                "education edu career options fields jobs counseling counselor mental "
                "health psychology support similar issues pursue work"
            ),
            "education_career_field_bridge",
        ),
    (
            frozenset({"support", "career"}),
            (
                "motivation motivated mattered made difference support got counseling "
                "support groups improved life mental health help people safe inviting grow"
            ),
            "support_career_motivation_bridge",
        ),
    (
            frozenset({"support_role_fit"}),
            (
                "support role fit mentor mentoring guidance advice coach volunteer "
                "counseling counselor listened listening comfort empathy patient "
                "helped accepted supportive safe trust similar issues reliable "
                "responsible care confide confided open opened opening private "
                "sensitive personal anxiety struggles"
            ),
            "support_role_fit_bridge",
        ),
    (
            frozenset({"support", "growing"}),
            "journey love support acceptance community hope",
            "support_counterfactual_bridge",
        ),
    (
            frozenset({"support", "growing"}),
            "blessed love support journey supportive community hope",
            "support_origin_bridge",
        ),
    (
            frozenset({"support", "negative"}),
            (
                "friends family mentors rocks support accept accepted people around "
                "motivate strength push on not so great experience upset hike"
            ),
            "negative_experience_support_bridge",
        ),
    (
            frozenset({"support", "experience"}),
            (
                "friends family mentors rocks support accept accepted people around "
                "motivate strength push on not so great experience upset hike"
            ),
            "negative_experience_support_bridge",
        ),
    (
            frozenset({"who", "support"}),
            _terms._SUPPORT_NETWORK_EXPANSION,
            "support_network_bridge",
        ),
    (
            frozenset({"who", "there"}),
            _terms._SUPPORT_NETWORK_EXPANSION,
            "support_network_bridge",
        ),
    (
            frozenset({"who", "help"}),
            _terms._SUPPORT_NETWORK_HELP_EXPANSION,
            "support_network_bridge",
        ),
    (
            frozenset({"кто", "поддерживает"}),
            _terms._RU_SUPPORT_NETWORK_EXPANSION,
            "support_network_bridge",
        ),
    (
            frozenset({"кто", "поддержал"}),
            _terms._RU_SUPPORT_NETWORK_PAST_SUPPORT_EXPANSION,
            "support_network_bridge",
        ),
    (
            frozenset({"кто", "помог"}),
            _terms._RU_SUPPORT_NETWORK_HELP_EXPANSION,
            "support_network_bridge",
        ),
    (
            frozenset({"кто", "рядом"}),
            _terms._RU_SUPPORT_NETWORK_EXPANSION,
            "support_network_bridge",
        ),
    (
            frozenset({"move", "from"}),
            (
                "moved from home country origin roots previous country former country "
                "native country hometown came from grandma sweden"
            ),
            "relocation_origin_bridge",
        ),
    (
            frozenset({"gift"}),
            (
                "gift present keepsake object item possession got received gave gifted "
                "from by source owner recipient grandma grandmother grandpa grandfather "
                "mother father mom dad family relative necklace pendant ring book camera "
                "photo picture"
            ),
            "possession_gift_object_bridge",
        ),
    (
            frozenset({"gave", "joy"}),
            (
                "gift present keepsake object item possession received gave gifted "
                "from by source owner recipient named stuffed animal toy dog brings joy "
                "happiness happy comfort focus cherish reminder good vibes"
            ),
            "possession_gift_object_bridge",
        ),
    (
            frozenset({"give", "joy"}),
            (
                "gift present keepsake object item possession received gave gifted "
                "from by source owner recipient named stuffed animal toy dog brings joy "
                "happiness happy comfort focus cherish reminder good vibes"
            ),
            "possession_gift_object_bridge",
        ),
    (
            frozenset({"from"}),
            (
                "family relative grandma grandmother grandpa grandfather mother father "
                "mom dad parent from country home country native country origin roots "
                "hometown gift present keepsake source provenance"
            ),
            "family_origin_bridge",
        ),
    (
            frozenset({"open", "moving", "country"}),
            (
                "open moving another country relocate relocation abroad willingness "
                "military veteran service public office politics running office "
                "community country international mission future hope positive change "
                "join wanted hospital stories resilience inspiring excited wild ride"
            ),
            "relocation_willingness_inference_bridge",
        ),
    (
            frozenset({"willing", "relocate", "abroad"}),
            (
                "open moving another country relocate relocation abroad willingness "
                "military veteran service public office politics running office "
                "community country international mission future hope positive change "
                "join wanted hospital stories resilience inspiring excited wild ride"
            ),
            "relocation_willingness_inference_bridge",
        ),
    (
            frozenset({"consider", "relocate", "abroad"}),
            (
                "open moving another country relocate relocation abroad willingness "
                "military veteran service public office politics running office "
                "community country international mission future hope positive change "
                "join wanted hospital stories resilience inspiring excited wild ride"
            ),
            "relocation_willingness_inference_bridge",
        ),
    (
            frozenset({"consider", "relocating", "abroad"}),
            (
                "open moving another country relocate relocation abroad willingness "
                "military veteran service public office politics running office "
                "community country international mission future hope positive change "
                "join wanted hospital stories resilience inspiring excited wild ride"
            ),
            "relocation_willingness_inference_bridge",
        ),
    (
            frozenset({"ready", "move", "internationally"}),
            (
                "open moving another country relocate relocation abroad willingness "
                "military veteran service public office politics running office "
                "community country international mission future hope positive change "
                "join wanted hospital stories resilience inspiring excited wild ride"
            ),
            "relocation_willingness_inference_bridge",
        ),
    (
            frozenset({"open", "moving", "country"}),
            (
                "running office again campaign run excited enthusiasm zeal wild ride "
                "first run politics public office"
            ),
            "public_office_service_bridge",
        ),
    (
            frozenset({"open", "moving", "country"}),
            (
                "join military veteran hospital stories resilience hope inspiring "
                "served service mission wanted"
            ),
            "military_service_willingness_bridge",
        ),
    (
            frozenset({"willing", "relocate", "abroad"}),
            (
                "join military veteran hospital stories resilience hope inspiring "
                "served service mission wanted"
            ),
            "military_service_willingness_bridge",
        ),
    (
            frozenset({"consider", "relocate", "abroad"}),
            (
                "join military veteran hospital stories resilience hope inspiring "
                "served service mission wanted"
            ),
            "military_service_willingness_bridge",
        ),
    (
            frozenset({"consider", "relocating", "abroad"}),
            (
                "join military veteran hospital stories resilience hope inspiring "
                "served service mission wanted"
            ),
            "military_service_willingness_bridge",
        ),
    (
            frozenset({"patriotic"}),
            (
                "patriotic patriotism serving country serve my country service "
                "aptitude test military drawn to serving flag eagle national civic "
                "duty homeland positive results family friends supportive volunteer "
                "proud opportunity"
            ),
            "patriotic_service_inference_bridge",
        ),
    (
            frozenset({"patriotism"}),
            (
                "patriotic patriotism serving country serve my country service "
                "aptitude test military drawn to serving flag eagle national civic "
                "duty homeland positive results family friends supportive volunteer "
                "proud opportunity"
            ),
            "patriotic_service_inference_bridge",
        ),
    (
            frozenset({"transgender", "conference"}),
            (
                "transgender conference this month going upcoming meet people community "
                "advocacy learn event"
            ),
            "transgender_conference_event_bridge",
        ),
    (
            frozenset({"how", "long", "married"}),
            (
                "married husband wife spouse wedding anniversary years already time "
                "flies been married for have been married we've been married my "
                "husband and I together duration dress put this dress on"
            ),
            "relationship_duration_bridge",
        ),
    (
            frozenset({"how", "long", "known"}),
            (
                "known each other friends relationship since years months duration met "
                "school college together anniversary time flies"
            ),
            "relationship_duration_bridge",
        ),
    (
            frozenset({"since", "when", "known"}),
            (
                "known each other friends relationship since years months duration met "
                "school college together anniversary time flies started began"
            ),
            "relationship_duration_bridge",
        ),
    (
            frozenset({"since", "when", "married"}),
            (
                "married husband wife spouse wedding anniversary years already time "
                "flies been married for have been married we've been married my "
                "husband and I together duration since started began"
            ),
            "relationship_duration_bridge",
        ),
    (
            frozenset({"how", "long", "friends"}),
            (
                "known these friends known friends group of friends current friends "
                "friendship relationship since for years months duration moved from "
                "home country support love help"
            ),
            "relationship_duration_bridge",
        ),
    (
            frozenset({"since", "when", "friends"}),
            (
                "known these friends known friends group of friends current friends "
                "friendship relationship since for years months duration moved from "
                "home country support love help started began"
            ),
            "relationship_duration_bridge",
        ),
    (
            frozenset({"как", "давно", "знает"}),
            (
                "как давно знакомы знают друг друга отношения друзья дружба с каких пор "
                "сколько лет месяцев вместе познакомились школа колледж университет "
                "known each other relationship since years months duration met"
            ),
            "relationship_duration_bridge",
        ),
    (
            frozenset({"как", "давно", "знакомы"}),
            (
                "как давно знакомы знают друг друга отношения друзья дружба с каких пор "
                "сколько лет месяцев вместе познакомились школа колледж университет "
                "known each other relationship since years months duration met"
            ),
            "relationship_duration_bridge",
        ),
    (
            frozenset({"when", "adoption", "meeting"}),
            (
                "when date adoption council meeting inspiring emotional loving homes "
                "children need determined adopt relative date weekday recent meeting"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "apply", "adoption", "agency"}),
            (
                "when date applied to adoption agencies application first step "
                "becoming a parent ready family children kids loving home decision"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "applied", "adoption", "agency"}),
            (
                "when date applied to adoption agencies application first step "
                "becoming a parent ready family children kids loving home decision"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "application", "adoption", "agency"}),
            (
                "when date submitted adoption application agencies first step "
                "becoming a parent ready family children kids loving home decision"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "adoption", "interview"}),
            (
                "when date passed adoption interview agency application process "
                "becoming a parent ready family children kids loving home milestone"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "birthday"}),
            (
                "birthday date daughter's birthday son's birthday child birthday "
                "celebrated birthday celebration party kids children daughter son "
                "relative date day weekday special family moments"
            ),
            "age_birthday_bridge",
        ),
    (
            frozenset({"when", "lgbtq", "conference"}),
            (
                "when date LGBTQ conference went attended attend connected people "
                "similar journeys relative date recently days ago special"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "collaborate", "dance"}),
            (
                "when date decide decided collaborate collaboration create dance content "
                "creative plan agreed together schedule project performance video "
                "dance routine moves"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "collaboration", "dance"}),
            (
                "when date decide decided collaborate collaboration create dance content "
                "creative plan agreed together schedule project performance video "
                "dance routine moves"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "park"}),
            (
                "when date park visit went took trip outing exploring playing "
                "outdoors playground relative date day weekday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "museum"}),
            (
                "when date museum exhibit dinosaur dinosaurs bones animals learning "
                "went visit visited took kids children family relative date day weekday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "picnic"}),
            (
                "when date picnic park hiking hike friends family outdoors outing "
                "went had relative date day weekday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "store", "open"}),
            (
                "when date online clothing store open opened is open clothes store "
                "dreaming can't wait website computer screen"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "store", "opened"}),
            (
                "when date online clothing store open opened is open clothes store "
                "dreaming can't wait website computer screen"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "support", "group"}),
            (
                "when date lgbtq support group went attended joined meeting event "
                "transgender stories powerful accepted online service focused "
                "relative date day weekday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "pride", "parade"}),
            (
                "when date relative day week weekday LGBTQ pride parade happy "
                "belonged community grown summer went attended attend"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "pride", "festival"}),
            (
                "when date relative year Pride fest festival supportive friends "
                "together went attended"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "pride", "fesetival"}),
            (
                "when date relative year Pride fest festival supportive friends "
                "together went attended"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "camping"}),
            (
                "camping camped went last week week before June 27 session date "
                "family nature hike roasted marshmallows campfire mountains outdoors"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "activist", "group"}),
            (
                "joined new LGBTQ activist group last Tues Tuesday rights community "
                "support voice difference fulfilling"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "mentorship", "program"}),
            (
                "when date joined mentorship mentoring mentor program youth community "
                "support guidance students relative date day weekday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "self", "portrait"}),
            (
                "when date drew draw painted self portrait identity art drawing "
                "sketch showed shared relative date day weekday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "biking"}),
            (
                "when date biking bike ride cycling friends group outdoors trail "
                "went relative date day weekday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "volunteering", "shelter"}),
            (
                "started volunteering shelter about a year ago homeless family "
                "struggling streets reached out volunteers fulfilling"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "friend", "adopt"}),
            (
                "when date friend adopted child adoption family kids parent parenthood "
                "relative date day weekday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "hurt"}),
            (
                "when date hurt injured injury accident fell pain recovery family "
                "relative date day weekday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "internship"}),
            (
                "interview design internship yesterday interview portfolio fashion "
                "cool project"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "hoodie"}),
            (
                "limited edition line hoodie collection last week own collection "
                "style creativity made designed"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "rocky"}),
            (
                "Rocky Mountains trip last year nature clearing mind calming soul "
                "mountains fresh air stunning"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "support", "group"}),
            (
                "joined service-focused online group last week emotional ride "
                "inspiring stories connection purpose support group"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "local", "artist"}),
            (
                "teamed up local artist cool designs online store working hard "
                "designs check them out"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"item", "bought"}),
            (
                "bought purchased buy got new shoes figurines wooden dolls items "
                "belongings sneakers yesterday image caption visual query"
            ),
            "item_purchase_bridge",
        ),
    (
            frozenset({"buy", "figurine"}),
            (
                "bought purchased buy got new figurines wooden dolls items "
                "belongings yesterday image caption visual query"
            ),
            "item_purchase_bridge",
        ),
    (
            frozenset({"instrument", "play"}),
            (
                "instrument instruments play played playing clarinet violin guitar piano "
                "music started young expression relax refresh present"
            ),
            "instrument_play_bridge",
        ),
    (
            frozenset({"hobby"}),
            (
                "hobbies interests writing reading watching movies exploring nature "
                "hanging with friends hanging friends express myself stories good "
                "time people video games desserts recipes baking"
            ),
            "hobby_interest_bridge",
        ),
    (
            frozenset({"birdwatching"}),
            (
                "birdwatching bird watching birds eagles soar explore nature hobby city "
                "schedule busy week outdoors outside bird feeder window balcony nearby "
                "park dog park ideal spot binoculars binos notebook log camera"
            ),
            "birdwatching_city_schedule_bridge",
        ),
    (
            frozenset({"bird", "watching"}),
            (
                "birdwatching bird watching birds eagles soar explore nature hobby city "
                "schedule busy week outdoors outside bird feeder window balcony nearby "
                "park dog park ideal spot binoculars binos notebook log camera"
            ),
            "birdwatching_city_schedule_bridge",
        ),
    (
            frozenset({"interest", "share"}),
            (
                "hobbies interests writing reading watching movies exploring nature "
                "hanging friends video games desserts recipes baking cakes icecream "
                "coconut milk dairy-free sweet treats revised old recipes made "
                "enjoy desserts bake baked shared both similar"
            ),
            "hobby_interest_bridge",
        ),
    (
            frozenset({"animal", "both", "like"}),
            _terms._COMMONALITY_ANIMAL_AFFINITY_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"animal", "both", "love"}),
            _terms._COMMONALITY_ANIMAL_AFFINITY_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"animal", "both", "enjoy"}),
            _terms._COMMONALITY_ANIMAL_AFFINITY_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"common", "hobby"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"common", "interests"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"both", "enjoy"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"both", "like"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"movie", "seen"}),
            (
                _terms._COMMONALITY_INTEREST_EXPANSION
                + " watched saw seen recently recommendation recommended movie film "
                "trilogy dvd acting story captivating favorite good enjoyed"
            ),
            "commonality_interest_bridge",
        ),
    (
            frozenset({"movies", "seen"}),
            (
                _terms._COMMONALITY_INTEREST_EXPANSION
                + " watched saw seen recently recommendation recommended movie film "
                "trilogy dvd acting story captivating favorite good enjoyed"
            ),
            "commonality_interest_bridge",
        ),
    (
            frozenset({"shared", "interests"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"who", "else", "like"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"who", "share", "interest"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"where", "friends"}),
            _terms._FRIEND_PLACE_INVENTORY_EXPANSION,
            "friend_place_inventory_bridge",
        ),
    (
            frozenset({"where", "friends"}),
            _terms._FRIEND_PLACE_SHELTER_INVENTORY_EXPANSION,
            "friend_place_shelter_inventory_bridge",
        ),
)

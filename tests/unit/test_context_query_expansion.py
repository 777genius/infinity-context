from infinity_context_core.application.context_query_expansion import (
    QueryExpansionPlan,
    build_query_expansion_plan,
)
from infinity_context_core.application.context_ranking import (
    best_query_relevance,
    keyword_chunk_score,
)
from infinity_context_core.application.context_relevance import score_query_relevance


def test_query_expansion_preserves_identity_for_relocation_bridge() -> None:
    plan = build_query_expansion_plan("Where did Caroline move from 4 years ago?")

    assert plan.retrieval_queries[0].reason == "original_query"
    relocation = _expansion_query(plan, "relocation_origin_bridge")
    assert relocation.startswith("Caroline ")
    assert "home country origin roots" in relocation
    assert "family" not in relocation.casefold()


def test_query_expansion_separates_relocation_destination_from_origin() -> None:
    destination = build_query_expansion_plan("Where did Alex move to?")
    russian_destination = build_query_expansion_plan("Куда Алекс переехал?")
    origin = build_query_expansion_plan("Where did Alex move from?")

    assert _expansion_query(destination, "relocation_destination_bridge").startswith("Alex ")
    assert "moved to relocated to destination new city" in _expansion_query(
        destination,
        "relocation_destination_bridge",
    )
    assert _expansion_query(russian_destination, "relocation_destination_bridge").startswith(
        "Алекс "
    )
    assert "куда переехал переехала переехали" in _expansion_query(
        russian_destination,
        "relocation_destination_bridge",
    )
    assert "relocation_destination_bridge" not in {
        expansion.reason for expansion in origin.expansions
    }


def test_query_expansion_separates_lgbtq_membership_from_support_only_evidence() -> None:
    plan = build_query_expansion_plan(
        "Would Melanie be considered a member of the LGBTQ community?"
    )

    membership = _expansion_query(plan, "community_membership_bridge")
    support_only = _expansion_query(plan, "community_membership_support_bridge")

    assert "identify refer herself member" in membership
    assert "supportive ally support acceptance" in support_only
    assert "transgender trans lgbtq community" in support_only


def test_query_expansion_covers_relocation_willingness_inference() -> None:
    plan = build_query_expansion_plan("Would John be open to moving to another country?")
    willing = build_query_expansion_plan("Would John be willing to relocate abroad?")
    consider = build_query_expansion_plan("Would John consider relocating abroad?")
    ready = build_query_expansion_plan("Would John be ready to move internationally?")

    assert "military veteran service public office politics" in _expansion_query(
        plan,
        "relocation_willingness_inference_bridge",
    )
    assert "military veteran service public office politics" in _expansion_query(
        willing,
        "relocation_willingness_inference_bridge",
    )
    assert "military veteran service public office politics" in _expansion_query(
        consider,
        "relocation_willingness_inference_bridge",
    )
    assert "military veteran service public office politics" in _expansion_query(
        ready,
        "relocation_willingness_inference_bridge",
    )
    assert "running office again campaign run excited" in _expansion_query(
        plan,
        "public_office_service_bridge",
    )
    assert "join military veteran hospital stories" in _expansion_query(
        plan,
        "military_service_willingness_bridge",
    )
    assert "join military veteran hospital stories" in _expansion_query(
        willing,
        "military_service_willingness_bridge",
    )
    assert "join military veteran hospital stories" in _expansion_query(
        consider,
        "military_service_willingness_bridge",
    )


def test_query_expansion_covers_public_office_motivation_reason() -> None:
    plan = build_query_expansion_plan("Why did John decide to run for office again?")

    public_office = _expansion_query(plan, "public_office_service_bridge")

    assert "run for office campaign public office politics" in public_office
    assert "impact community make difference positive changes" in public_office


def test_query_expansion_covers_recognition_award_questions() -> None:
    plan = build_query_expansion_plan(
        "What recognition did John receive at the homeless shelter?"
    )
    certificate = build_query_expansion_plan("What did Maria receive a certificate for?")

    recognition = _expansion_query(plan, "recognition_award_bridge")
    certificate_recognition = _expansion_query(certificate, "recognition_award_bridge")

    assert "recognition award medal certificate" in recognition
    assert "volunteer shelter homeless helped" in recognition
    assert "completion completed diploma degree" in certificate_recognition


def test_query_expansion_covers_pet_adjustment_questions() -> None:
    plan = build_query_expansion_plan(
        "How is John's new puppy adjusting to its new home?"
    )

    adjustment = _expansion_query(plan, "pet_adjustment_bridge")

    assert "puppy pup dog pet little one new home" in adjustment
    assert "learning commands house training" in adjustment


def test_query_expansion_covers_common_animal_affinity_questions() -> None:
    plan = build_query_expansion_plan("What animal do both Nate and Joanna like?")

    commonality = _expansion_query(plan, "commonality_interest_bridge")

    assert "animals pets turtles reptiles animal affinity" in commonality
    assert "strength perseverance inspire inspiring motivate" in commonality


def test_query_expansion_covers_planning_tool_use_questions() -> None:
    plan = build_query_expansion_plan(
        "How does Jon use the clipboard with a notepad attached to it?"
    )

    tool_use = _expansion_query(plan, "planning_tool_use_bridge")

    assert "clipboard notepad notebook calendar planner" in tool_use
    assert "sets goals tracks achievements areas improve" in tool_use


def test_query_expansion_covers_customer_experience_questions() -> None:
    plan = build_query_expansion_plan(
        "What did Jon say about creating a special experience for customers?"
    )

    customer_experience = _expansion_query(plan, "customer_experience_bridge")

    assert "customers customer special experience" in customer_experience
    assert "feel welcome coming back" in customer_experience


def test_query_expansion_covers_grand_opening_support_questions() -> None:
    plan = build_query_expansion_plan("What does Gina say to Jon about the grand opening?")

    grand_opening = _expansion_query(plan, "grand_opening_support_bridge")

    assert "grand opening launch dance studio tomorrow" in grand_opening
    assert "right by your side live it up" in grand_opening


def test_query_expansion_covers_person_summary_questions() -> None:
    who = build_query_expansion_plan("Who is Alex?")
    known = build_query_expansion_plan("What do we know about Alex?")
    tell = build_query_expansion_plan("Tell me about Alex")
    russian = build_query_expansion_plan("Кто такой Алекс?")

    for plan in (who, known, tell, russian):
        summary = _expansion_query(plan, "person_summary_bridge")

        assert "profile" in summary.casefold()
        assert "facts" in summary.casefold() or "факты" in summary.casefold()
        assert "Alex" in summary or "Алекс" in summary


def test_query_expansion_does_not_treat_responsibility_query_as_person_summary() -> None:
    plan = build_query_expansion_plan("Who is responsible for Project Atlas?")

    assert "person_summary_bridge" not in {expansion.reason for expansion in plan.expansions}


def test_query_expansion_covers_project_summary_questions() -> None:
    what_is = build_query_expansion_plan("What is Project Atlas?")
    known = build_query_expansion_plan("What do we know about project Atlas?")
    tell = build_query_expansion_plan("Tell me about project Atlas")
    russian = build_query_expansion_plan("Расскажи про проект Атлас")

    for plan in (what_is, known, tell, russian):
        summary = _expansion_query(plan, "project_summary_bridge")

        assert "project" in summary.casefold()
        assert "summary" in summary.casefold() or "сводка" in summary.casefold()
        assert "Atlas" in summary or "Атлас" in summary


def test_query_expansion_does_not_treat_project_role_query_as_project_summary() -> None:
    plan = build_query_expansion_plan("What is Project Atlas responsible for?")

    assert "project_summary_bridge" not in {expansion.reason for expansion in plan.expansions}


def test_query_expansion_covers_organization_summary_questions() -> None:
    company = build_query_expansion_plan("What is company OpenAI?")
    known = build_query_expansion_plan("What do we know about organization Acme Labs?")
    team = build_query_expansion_plan("Tell me about team Platform")
    russian = build_query_expansion_plan("Расскажи про компанию Инфинити")

    for plan in (company, known, team, russian):
        summary = _expansion_query(plan, "organization_summary_bridge")

        assert "organization" in summary.casefold() or "организация" in summary.casefold()
        assert "summary" in summary.casefold() or "обзор" in summary.casefold()

    assert "OpenAI" in _expansion_query(company, "organization_summary_bridge")
    assert "Acme" in _expansion_query(known, "organization_summary_bridge")
    assert "Platform" in _expansion_query(team, "organization_summary_bridge")
    assert "Инфинити" in _expansion_query(russian, "organization_summary_bridge")


def test_query_expansion_does_not_treat_company_role_query_as_org_summary() -> None:
    plan = build_query_expansion_plan(
        "Which outdoor gear company likely signed John for an endorsement?"
    )

    assert "organization_summary_bridge" not in {
        expansion.reason for expansion in plan.expansions
    }


def test_query_expansion_covers_entity_relation_inventory_questions() -> None:
    connected = build_query_expansion_plan("Who is connected to Project Atlas?")
    people = build_query_expansion_plan("Which people are involved in Project Atlas?")
    stakeholders = build_query_expansion_plan("Who are the stakeholders for Project Atlas?")
    russian = build_query_expansion_plan("Кто связан с проектом Атлас?")

    for plan in (connected, people, stakeholders, russian):
        relation = _expansion_query(plan, "entity_relation_inventory_bridge")

        assert "stakeholders" in relation.casefold() or "стейкхолдеры" in relation.casefold()
        assert "connected" in relation.casefold() or "связаны" in relation.casefold()

    assert "Atlas" in _expansion_query(connected, "entity_relation_inventory_bridge")
    assert "Atlas" in _expansion_query(people, "entity_relation_inventory_bridge")
    assert "Atlas" in _expansion_query(stakeholders, "entity_relation_inventory_bridge")
    assert "Атлас" in _expansion_query(russian, "entity_relation_inventory_bridge")


def test_query_expansion_covers_event_summary_questions() -> None:
    recap = build_query_expansion_plan("Recap the last call with Alex")
    discussed = build_query_expansion_plan("What did we discuss during the launch review?")
    notes = build_query_expansion_plan("Action items from the Atlas sync")
    russian = build_query_expansion_plan("Что обсудили на созвоне с Алексом?")

    for plan in (recap, discussed, notes, russian):
        summary = _expansion_query(plan, "event_summary_bridge")

        assert "summary" in summary.casefold() or "саммари" in summary.casefold()
        assert "decision" in summary.casefold() or "решения" in summary.casefold()
        assert "action" in summary.casefold() or "поручения" in summary.casefold()

    assert "Alex" in _expansion_query(recap, "event_summary_bridge")
    assert "review" in _expansion_query(discussed, "event_summary_bridge")
    assert "Atlas" in _expansion_query(notes, "event_summary_bridge")
    assert "Алексом" in _expansion_query(russian, "event_summary_bridge")


def test_query_expansion_covers_temporal_pet_acquisition_questions() -> None:
    adopted = build_query_expansion_plan("When did Sam adopt Max?")
    got = build_query_expansion_plan("When did Sam get Pippa for Dana?")

    adopt_expansion = _expansion_query(adopted, "pet_acquisition_date_bridge")
    got_expansion = _expansion_query(got, "pet_acquisition_date_bridge")

    assert adopt_expansion.startswith("Sam Max ")
    assert got_expansion.startswith("Sam Pippa Dana ")
    assert "new addition family pet dog puppy pup" in adopt_expansion
    assert "gift from named stuffed animal" in got_expansion
    assert "image caption visual query cute dog" in got_expansion


def test_query_expansion_does_not_treat_event_scheduling_as_event_summary() -> None:
    plan = build_query_expansion_plan("When is the next meeting with Alex?")

    assert "event_summary_bridge" not in {expansion.reason for expansion in plan.expansions}


def test_query_expansion_covers_artifact_inventory_questions() -> None:
    files = build_query_expansion_plan("Which files are related to Project Atlas?")
    screenshots = build_query_expansion_plan("Show screenshots for Alex")
    documents = build_query_expansion_plan("List documents about Acme Labs")
    russian = build_query_expansion_plan("Покажи файлы по Атласу")

    for plan in (files, screenshots, documents, russian):
        inventory = _expansion_query(plan, "artifact_inventory_bridge")

        assert "files" in inventory.casefold() or "файлы" in inventory.casefold()
        assert "evidence" in inventory.casefold()
        assert "metadata" in inventory.casefold()

    assert "Atlas" in _expansion_query(files, "artifact_inventory_bridge")
    assert "Alex" in _expansion_query(screenshots, "artifact_inventory_bridge")
    assert "Acme Labs" in _expansion_query(documents, "artifact_inventory_bridge")
    assert "Атласу" in _expansion_query(russian, "artifact_inventory_bridge")


def test_query_expansion_does_not_treat_ocr_question_as_artifact_inventory() -> None:
    plan = build_query_expansion_plan("What OCR text was in the screenshot?")

    assert "artifact_inventory_bridge" not in {
        expansion.reason for expansion in plan.expansions
    }


def test_query_expansion_covers_books_read_inventory_language() -> None:
    plan = build_query_expansion_plan("What books has Melanie read?")

    bridge = _expansion_query(plan, "book_reading_list_bridge")

    assert bridge.startswith("Melanie ")
    assert "read last year story" in bridge
    assert "fantasy novel series" in bridge


def test_query_expansion_covers_creative_writing_career_support() -> None:
    plan = build_query_expansion_plan("Would Caroline pursue writing as a career option?")

    bridge = _expansion_query(plan, "creative_writing_career_bridge")

    assert bridge.startswith("Caroline ")
    assert "creative writing author books reading literature" in bridge
    assert "career option interest" in bridge


def test_query_expansion_covers_church_friend_activity_inventory() -> None:
    plan = build_query_expansion_plan("What activities has Maria done with her church friends?")

    bridge = _expansion_query(plan, "church_friend_activity_inventory_bridge")

    assert bridge.startswith("Maria ")
    assert "went with church friends" in bridge
    assert "friends from church community work" in bridge
    assert "hiking picnic" in bridge


def test_query_expansion_adds_activity_competition_evidence_bridge() -> None:
    plan = build_query_expansion_plan(
        "Did Riley and Jordan both participate in chess competitions?"
    )
    dancers = build_query_expansion_plan("What does Gina say about the dancers in the photo?")
    festival = build_query_expansion_plan(
        "What is Jon's attitude towards being part of the dance festival?"
    )

    bridge = _expansion_query(plan, "activity_competition_evidence_bridge")

    assert "competition contest compete" in bridge
    assert "trophy trophies first place" in bridge
    assert "dancers dance festival photo" in _expansion_query(
        dancers,
        "activity_competition_evidence_bridge",
    )
    assert "participate participating part of it" in _expansion_query(
        festival,
        "activity_competition_evidence_bridge",
    )


def test_query_expansion_covers_patriotic_service_inference() -> None:
    plan = build_query_expansion_plan("Would John be considered a patriotic person?")

    bridge = _expansion_query(plan, "patriotic_service_inference_bridge")

    assert "serving country serve my country" in bridge
    assert "aptitude test military" in bridge
    assert "flag eagle" in bridge
    assert "family friends supportive volunteer" in bridge


def test_query_expansion_covers_future_conference_and_duration_answers() -> None:
    conference = build_query_expansion_plan("When is Caroline going to the transgender conference?")
    duration = build_query_expansion_plan("How long have Mel and her husband been married?")
    known_each_other = build_query_expansion_plan("How long has Alex known Maria?")
    where_met = build_query_expansion_plan("Where did Alex meet Maria?")
    how_met = build_query_expansion_plan("How did Alex and Maria meet?")
    russian_where_met = build_query_expansion_plan("Где Алекс познакомился с Марией?")
    russian_when_met = build_query_expansion_plan("Когда Алекс впервые встретил Марию?")

    assert "conference this month going upcoming" in _expansion_query(
        conference,
        "transgender_conference_event_bridge",
    )
    assert "years already time flies" in _expansion_query(
        duration,
        "relationship_duration_bridge",
    )
    assert "been married for have been married" in _expansion_query(
        duration,
        "relationship_duration_bridge",
    )
    assert "known each other friends relationship since years" in _expansion_query(
        known_each_other,
        "relationship_duration_bridge",
    )
    friend_group = build_query_expansion_plan(
        "How long has Caroline had her current group of friends for?"
    )
    assert "known these friends known friends group of friends" in _expansion_query(
        friend_group,
        "relationship_duration_bridge",
    )
    assert "relationship origin first met" in _expansion_query(
        where_met,
        "relationship_origin_bridge",
    )
    assert "introduced known since" in _expansion_query(
        how_met,
        "relationship_origin_bridge",
    )
    assert "впервые познакомились встретились" in _expansion_query(
        russian_where_met,
        "relationship_origin_bridge",
    )
    assert "relationship origin first met" in _expansion_query(
        russian_when_met,
        "relationship_origin_bridge",
    )


def test_query_expansion_covers_purchased_item_questions() -> None:
    plan = build_query_expansion_plan("What items has Melanie bought?")

    assert "bought purchased buy got new shoes" in _expansion_query(
        plan,
        "item_purchase_bridge",
    )


def test_query_expansion_covers_temporal_figurine_purchase_questions() -> None:
    plan = build_query_expansion_plan("When did Melanie buy the figurines?")

    bridge = _expansion_query(plan, "item_purchase_bridge")

    assert "bought purchased buy got new figurines wooden dolls" in bridge
    assert "yesterday image caption visual query" in bridge


def test_query_expansion_covers_running_reason_questions() -> None:
    plan = build_query_expansion_plan("What is Melanie's reason for getting into running?")
    started = build_query_expansion_plan("Why did Melanie start running?")
    running_for = build_query_expansion_plan("What was Melanie running for?")

    bridge = _expansion_query(plan, "running_reason_bridge")

    assert "running run farther longer" in bridge
    assert "de-stress destress clear mind headspace" in bridge
    assert "what got into running" in bridge
    assert "what got you into running" in _expansion_query(
        plan,
        "running_reason_question_bridge",
    )
    assert "why started running" in _expansion_query(
        started,
        "running_reason_question_bridge",
    )
    assert "walking or running" in _expansion_query(
        running_for,
        "running_reason_bridge",
    )


def test_query_expansion_covers_allergy_inventory_equivalents() -> None:
    plan = build_query_expansion_plan("What is Joanna allergic to?")

    assert "dairy-free no ice cream" in _expansion_query(
        plan,
        "allergy_inventory_bridge",
    )


def test_query_expansion_skips_allergy_inventory_for_condition_inference() -> None:
    plan = build_query_expansion_plan(
        "What underlying condition might Joanna have based on her allergies?"
    )

    assert "allergy_condition_inference_bridge" in {
        expansion.reason for expansion in plan.expansions
    }
    assert "allergy_inventory_bridge" not in {
        expansion.reason for expansion in plan.expansions
    }


def test_query_expansion_covers_children_count_event_evidence() -> None:
    plan = build_query_expansion_plan("How many children does Melanie have?")

    assert "son accident roadtrip" in _expansion_query(
        plan,
        "children_count_event_bridge",
    )
    assert "brother siblings two younger kids" in _expansion_query(
        plan,
        "children_count_sibling_bridge",
    )


def test_query_expansion_covers_low_overlap_ally_and_outdoor_questions() -> None:
    ally = build_query_expansion_plan(
        "Would Melanie be considered an ally to the transgender community?"
    )
    outdoor = build_query_expansion_plan(
        "Would Melanie be more interested in going to a national park or a theme park?"
    )

    assert _expansion_query(ally, "ally_support_bridge").startswith("Melanie ")
    assert "supportive support acceptance" in _expansion_query(
        ally,
        "ally_support_bridge",
    )
    assert _expansion_query(outdoor, "outdoor_preference_bridge").startswith("Melanie ")
    assert "family camping trip campfire marshmallows" in _expansion_query(
        outdoor,
        "outdoor_preference_bridge",
    )
    assert "stories highlight summer nature outdoors" in _expansion_query(
        outdoor,
        "outdoor_preference_bridge",
    )
    assert "meteor shower sky universe" in _expansion_query(
        outdoor,
        "outdoor_nature_memory_bridge",
    )


def test_query_expansion_covers_support_role_fit_bridge() -> None:
    plan = build_query_expansion_plan("Would Caroline be a good mentor for Alex?")

    assert _expansion_query(plan, "support_role_fit_bridge").startswith("Caroline Alex ")
    assert "mentor mentoring guidance advice coach volunteer" in _expansion_query(
        plan,
        "support_role_fit_bridge",
    )
    assert "listened listening comfort empathy patient helped" in _expansion_query(
        plan,
        "support_role_fit_bridge",
    )


def test_query_expansion_covers_degree_policy_inference_bridge() -> None:
    plan = build_query_expansion_plan("What might John's degree be in?")

    expansion = _expansion_query(plan, "degree_policy_inference_bridge")
    assert expansion.startswith("John ")
    assert "political science public administration" in expansion


def test_query_expansion_covers_trust_support_role_bridge() -> None:
    plan = build_query_expansion_plan("Would Alex trust Caroline with sensitive issues?")

    assert _expansion_query(plan, "support_role_fit_bridge").startswith("Alex Caroline ")
    assert "confide confided open opened opening private" in _expansion_query(
        plan,
        "support_role_fit_bridge",
    )
    assert "sensitive personal anxiety struggles" in _expansion_query(
        plan,
        "support_role_fit_bridge",
    )
    assert "decomposition_support_role_fit" in {
        item.reason for item in plan.decompositions
    }


def test_query_expansion_support_role_fit_guard_keeps_career_queries_specific() -> None:
    plan = build_query_expansion_plan("Would Caroline pursue writing as a career option?")

    assert "support_role_fit_bridge" not in {item.reason for item in plan.expansions}
    assert "decomposition_support_role_fit" not in {
        item.reason for item in plan.decompositions
    }
    assert "career_intent_bridge" in {item.reason for item in plan.expansions}


def test_query_expansion_music_artist_guard_skips_band_object_queries() -> None:
    plan = build_query_expansion_plan("What band tee did Melanie buy?")

    assert "music_artist_band_bridge" not in {item.reason for item in plan.expansions}
    assert "music_artist_answer_bridge" not in {item.reason for item in plan.expansions}


def test_query_expansion_covers_negative_experience_support_bridge() -> None:
    plan = build_query_expansion_plan("Who supports Caroline when she has a negative experience?")

    assert "friends family mentors rocks support" in _expansion_query(
        plan,
        "negative_experience_support_bridge",
    )


def test_query_expansion_covers_direct_negative_preference_questions() -> None:
    dislike = build_query_expansion_plan("What does Morgan dislike?")
    hate = build_query_expansion_plan("What does Morgan hate?")

    assert "dislike dislikes disliked hate hates hated" in _expansion_query(
        dislike,
        "negative_preference_bridge",
    )
    assert "dislike dislikes disliked hate hates hated" in _expansion_query(
        hate,
        "negative_preference_bridge",
    )


def test_query_expansion_covers_social_support_network_questions() -> None:
    support = build_query_expansion_plan("Who supports Caroline?")
    there_for = build_query_expansion_plan("Who is there for Caroline when things get hard?")
    helped = build_query_expansion_plan("Who helped Caroline through it?")
    russian = build_query_expansion_plan("Кто поддерживает Каролину?")
    russian_past_support = build_query_expansion_plan("Кто поддержал Каролину?")
    russian_helped = build_query_expansion_plan("Кто помог Каролине?")
    technical = build_query_expansion_plan("Who supports the OpenAI provider integration?")

    assert _expansion_query(support, "support_network_bridge").startswith("Caroline ")
    assert "friends family mentors mother father parents coach" in _expansion_query(
        support,
        "support_network_bridge",
    )
    assert "rocks there for" in _expansion_query(support, "support_network_bridge")
    assert _expansion_query(there_for, "support_network_bridge").startswith("Caroline ")
    assert "support system people around" in _expansion_query(
        there_for,
        "support_network_bridge",
    )
    assert _expansion_query(helped, "support_network_bridge").startswith("Caroline ")
    assert "helped through hard time" in _expansion_query(
        helped,
        "support_network_bridge",
    )
    assert _expansion_query(russian, "support_network_bridge").startswith("Каролину ")
    assert "поддерживает поддержка рядом" in _expansion_query(
        russian,
        "support_network_bridge",
    )
    assert "мама отец родители тренер" in _expansion_query(
        russian,
        "support_network_bridge",
    )
    assert _expansion_query(
        russian_past_support,
        "support_network_bridge",
    ).startswith("Каролину ")
    assert "поддержал поддержала поддержали" in _expansion_query(
        russian_past_support,
        "support_network_bridge",
    )
    assert _expansion_query(russian_helped, "support_network_bridge").startswith("Каролине ")
    assert "помог помогла помогли" in _expansion_query(
        russian_helped,
        "support_network_bridge",
    )
    assert "support_network_bridge" not in {item.reason for item in technical.expansions}


def test_query_expansion_covers_adoption_current_goal_bridge() -> None:
    plan = build_query_expansion_plan("Would Caroline want to move back to her home country soon?")
    excited = build_query_expansion_plan("What is Caroline excited about in the adoption process?")
    supported_people = build_query_expansion_plan(
        "What type of individuals does the adoption agency Caroline is considering support?"
    )

    bridge = _expansion_query(plan, "adoption_current_goal_bridge")
    milestone_bridge = _expansion_query(plan, "adoption_current_milestone_bridge")
    excited_bridge = _expansion_query(excited, "adoption_current_goal_bridge")
    supported_people_bridge = _expansion_query(supported_people, "support_population_bridge")

    assert bridge.startswith("Caroline ")
    assert "adoption agency interviews build own family" in bridge
    assert "roof kids children giving back goal" in bridge
    assert milestone_bridge.startswith("Caroline ")
    assert "passed adoption agency interviews" in milestone_bridge
    assert excited_bridge.startswith("Caroline ")
    assert "adoption agency interviews build own family" in excited_bridge
    assert "excited process milestone" in excited_bridge
    assert supported_people_bridge.startswith("Caroline ")
    assert "support serves helps accepts individuals people" in supported_people_bridge
    assert "adoption agency inclusive services" in supported_people_bridge


def test_query_expansion_covers_future_plan_timing_bridge() -> None:
    plan = build_query_expansion_plan("When is Melanie planning on going camping?")
    summer_plan = build_query_expansion_plan("What are Caroline's plans for the summer?")

    bridge = _expansion_query(plan, "future_plan_timing_bridge")
    summer_bridge = _expansion_query(summer_plan, "future_plan_timing_bridge")

    assert bridge.startswith("Melanie ")
    assert "thinking about considering going to scheduled" in bridge
    assert "next month next week summer break" in bridge
    assert summer_bridge.startswith("Caroline ")
    assert "thinking about considering going to scheduled" in summer_bridge
    assert "next month next week summer break" in summer_bridge


def test_query_expansion_covers_inspiration_source_questions() -> None:
    plan = build_query_expansion_plan("What is Joanna inspired by?")

    bridge = _expansion_query(plan, "inspiration_source_bridge")

    assert bridge.startswith("Joanna ")
    assert "personal experiences self discovery journey" in bridge
    assert "got ideas from everywhere" in bridge
    assert "stories courage risks" in bridge
    assert "people know stuff saw imagined" in bridge
    assert "imagination ideas" in bridge


def test_query_expansion_covers_choice_reason_without_speaker_identity_bias() -> None:
    plan = build_query_expansion_plan("Why did Melanie choose the adoption agency?")

    bridge = _expansion_query(plan, "choice_reason_bridge")

    assert not bridge.startswith("Melanie ")
    assert "reason choose chose chosen picked selected" in bridge
    assert "because cause helps support inclusivity spoke to me" in bridge


def test_best_query_relevance_uses_support_population_bridge() -> None:
    plan = build_query_expansion_plan(
        "What type of individuals does the adoption agency Caroline is considering support?"
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D5:9 Caroline: The adoption agency supports LGBTQ parents, "
            "single parents, children, and families who need inclusive services."
        ),
    )

    assert reason == "support_population_bridge"
    assert relevance.distinctive_term_hits >= 8


def test_best_query_relevance_uses_opinion_reaction_bridge() -> None:
    plan = build_query_expansion_plan("What does Maria think about John's decision?")

    bridge = _expansion_query(plan, "opinion_reaction_bridge")
    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D6:4 Maria: I think John's decision is a good idea, and I am "
            "supportive and proud of the plan."
        ),
    )

    assert "think thought opinion reaction response decision plan choice" in bridge
    assert reason == "opinion_reaction_bridge"
    assert relevance.distinctive_term_hits >= 8


def test_query_decomposition_covers_active_commitment_current_goal_evidence() -> None:
    plan = build_query_expansion_plan("Would Maria move back to Chicago soon?")
    decompositions = {
        item.reason: item.query
        for item in plan.decompositions
    }

    assert "decomposition_current_preference_or_goal" in decompositions
    current_goal_query = decompositions["decomposition_current_preference_or_goal"]
    assert "lease contract signed stay local job role" in current_goal_query
    assert "school program semester deadline" in current_goal_query


def test_query_expansion_covers_visual_symbol_evidence_terms() -> None:
    plan = build_query_expansion_plan("What symbols are important to Caroline?")

    assert "pendant necklace transgender symbol" in _expansion_query(
        plan,
        "symbol_importance_bridge",
    )
    assert "love faith roots gift grandma" in _expansion_query(
        plan,
        "symbol_importance_bridge",
    )


def test_query_expansion_covers_symbolic_meaning_variants() -> None:
    for query in (
        "What does Caroline's necklace symbolize?",
        "What does Caroline's necklace stand for?",
        "What is the meaning of Caroline's necklace?",
    ):
        plan = build_query_expansion_plan(query)
        symbol = _expansion_query(plan, "symbol_importance_bridge")

        assert symbol.startswith("Caroline ")
        assert "necklace transgender symbol cross heart" in symbol
        assert "symbolizes represents meaning means stands for" in symbol


def test_query_expansion_covers_visual_symbol_objects_without_symbol_word() -> None:
    cases = (
        (
            "What do sunflowers represent according to Caroline?",
            "flowers sunflower",
        ),
        (
            "Why are flowers important to Melanie?",
            "flowers sunflower",
        ),
        (
            "What does Gina's tattoo symbolize?",
            "tattoo tattoos ink design",
        ),
    )

    for query, expected_terms in cases:
        plan = build_query_expansion_plan(query)
        symbol = _expansion_query(plan, "symbol_importance_bridge")

        assert expected_terms in symbol
        assert "symbolizes represents meaning means stands for" in symbol


def test_query_expansion_does_not_treat_technical_meaning_as_symbol_memory() -> None:
    plan = build_query_expansion_plan("What does API status code mean?")

    assert "symbol_importance_bridge" not in {item.reason for item in plan.expansions}


def test_query_expansion_covers_possession_gift_and_family_origin() -> None:
    gift = build_query_expansion_plan("What was grandma's gift to Caroline?")
    origin = build_query_expansion_plan("What country is Caroline's grandma from?")

    gift_query = _expansion_query(gift, "possession_gift_object_bridge")
    origin_query = _expansion_query(origin, "family_origin_bridge")

    assert gift_query.startswith("Caroline ")
    assert "gift present keepsake object item possession" in gift_query
    assert "grandma grandmother grandpa grandfather" in gift_query
    assert "necklace pendant ring book camera" in gift_query
    assert origin_query.startswith("Caroline ")
    assert "family relative grandma grandmother" in origin_query
    assert "home country native country origin roots" in origin_query


def test_query_expansion_does_not_treat_gift_card_api_as_possession_memory() -> None:
    plan = build_query_expansion_plan("What does the API gift card status mean?")

    assert "possession_gift_object_bridge" not in {
        item.reason for item in plan.expansions
    }


def test_query_expansion_does_not_treat_api_feel_as_emotional_memory() -> None:
    plan = build_query_expansion_plan("How does the API feel under load?")

    assert "post_event_emotion_bridge" not in {item.reason for item in plan.expansions}


def test_query_expansion_is_bounded_and_deduplicated_by_reason() -> None:
    plan = build_query_expansion_plan(
        "Would Melanie support growing up, move from home, choose a national park "
        "or theme park, make a decision to adopt, be an ally to the transgender "
        "community, have political leaning, be religious, and destress?"
    )

    reasons = [expansion.reason for expansion in plan.expansions]
    assert len(plan.expansions) <= 8
    assert len(reasons) == len(set(reasons))
    assert reasons.count("outdoor_preference_bridge") == 1
    assert reasons.count("outdoor_nature_memory_bridge") <= 1


def test_query_expansion_bound_prefers_specific_bridges_over_generic_why_noise() -> None:
    plan = build_query_expansion_plan(
        "Why did Gina start her clothing store, what charity organization might "
        "John work with, why does Jolene put off yoga, when did Caroline go to "
        "the adoption meeting, what instruments does Melanie play, what books "
        "has Tim read, how many tournaments has Nate won, and how many "
        "screenplays has Joanna written?"
    )

    reasons = [expansion.reason for expansion in plan.expansions]

    assert len(reasons) == 8
    assert "motivation_reason_bridge" not in reasons
    assert "children_count_sibling_bridge" not in reasons
    assert set(reasons) == {
        "book_reading_list_bridge",
        "business_start_reason_bridge",
        "charity_brand_sponsorship_bridge",
        "instrument_play_bridge",
        "screenplay_count_bridge",
        "temporal_event_detail_bridge",
        "tournament_count_bridge",
        "yoga_delay_gaming_bridge",
    }


def test_query_expansion_adds_volunteering_people_inventory_bridge() -> None:
    people_plan = build_query_expansion_plan(
        "What people has Riley met and helped while volunteering?"
    )
    shelter_plan = build_query_expansion_plan("What shelters does Riley volunteer at?")
    shared_activity_plan = build_query_expansion_plan(
        "What type of volunteering have John and Maria both done?"
    )

    assert "volunteering_people_inventory_bridge" in people_plan.diagnostics()[
        "query_expansion_reasons"
    ]
    assert "volunteering_people_inventory_bridge" not in shelter_plan.diagnostics()[
        "query_expansion_reasons"
    ]
    shared_activity = _expansion_query(
        shared_activity_plan,
        "volunteering_inventory_bridge",
    )
    assert "service events give out hand out food supplies toy drive" in shared_activity
    assert "donation drive" in shared_activity


def test_query_expansion_covers_age_without_polluting_old_state_queries() -> None:
    age = build_query_expansion_plan("How old is Alex?")
    dob = build_query_expansion_plan("What is Alex's date of birth?")
    birthday_duration = build_query_expansion_plan(
        "How long ago was Caroline's 18th birthday?"
    )
    russian_age = build_query_expansion_plan("Сколько лет Алексу?")
    old_state = build_query_expansion_plan("What was the old Atlas plan?")

    assert _expansion_query(age, "age_birthday_bridge").startswith("Alex ")
    assert "born birthday date of birth" in _expansion_query(age, "age_birthday_bridge")
    assert _expansion_query(dob, "age_birthday_bridge").startswith("Alex ")
    assert "birth date of birth born birthday" in _expansion_query(
        dob,
        "age_birthday_bridge",
    )
    assert "birthday anniversary years ago how long ago duration" in _expansion_query(
        birthday_duration,
        "age_birthday_bridge",
    )
    assert "возраст лет родился" in _expansion_query(
        russian_age,
        "age_birthday_bridge",
    )
    assert "age_birthday_bridge" not in {expansion.reason for expansion in old_state.expansions}


def test_best_query_relevance_prefers_birthday_duration_evidence() -> None:
    plan = build_query_expansion_plan("How long ago was Caroline's 18th birthday?")

    _, duration_reason, duration_relevance = best_query_relevance(
        plan,
        text="D4:5 Caroline: A friend made a bowl for my 18th birthday ten years ago.",
    )
    _, generic_reason, generic_relevance = best_query_relevance(
        plan,
        text="D2:3 Caroline was born in 1995 and her birthday is in May.",
    )

    assert duration_reason == "age_birthday_bridge"
    assert generic_reason == "age_birthday_bridge"
    assert duration_relevance.distinctive_term_hits > generic_relevance.distinctive_term_hits
    assert duration_relevance.hit_ratio > generic_relevance.hit_ratio


def test_query_expansion_separates_birthplace_from_age_queries() -> None:
    birthplace = build_query_expansion_plan("Where was Alex born?")
    origin_from = build_query_expansion_plan("Where is Alex from?")
    move_from = build_query_expansion_plan("Where did Alex move from?")
    russian_birthplace = build_query_expansion_plan("Где Алекс родился?")

    assert _expansion_query(birthplace, "birthplace_origin_bridge").startswith("Alex ")
    assert "birthplace born in from origin hometown" in _expansion_query(
        birthplace,
        "birthplace_origin_bridge",
    )
    assert _expansion_query(origin_from, "birthplace_origin_bridge").startswith("Alex ")
    assert "birthplace born in from origin hometown" in _expansion_query(
        origin_from,
        "birthplace_origin_bridge",
    )
    assert "birthplace_origin_bridge" not in {
        expansion.reason for expansion in move_from.expansions
    }
    assert _expansion_query(russian_birthplace, "birthplace_origin_bridge").startswith("Алекс ")
    assert "место рождения родной город страна" in _expansion_query(
        russian_birthplace,
        "birthplace_origin_bridge",
    )


def test_query_expansion_separates_current_residence_from_origin_queries() -> None:
    residence = build_query_expansion_plan("Where does Alex live now?")
    russian_residence = build_query_expansion_plan("Где Алекс живет сейчас?")
    beach_or_mountains = build_query_expansion_plan("Does John live close to a beach?")
    state_inference = build_query_expansion_plan(
        "Which US state do Audrey and Andrew potentially live in?"
    )

    assert _expansion_query(residence, "current_residence_bridge").startswith("Alex ")
    assert "currently lives living residence home address" in _expansion_query(
        residence,
        "current_residence_bridge",
    )
    assert _expansion_query(russian_residence, "current_residence_bridge").startswith("Алекс ")
    assert "где живет живёт сейчас проживает" in _expansion_query(
        russian_residence,
        "current_residence_bridge",
    )
    assert "current_residence_bridge" not in {
        expansion.reason for expansion in beach_or_mountains.expansions
    }
    assert _expansion_query(state_inference, "state_residence_inference_bridge").startswith(
        "US Audrey Andrew "
    )
    assert "hiking trails map trail route park" in _expansion_query(
        state_inference,
        "state_residence_inference_bridge",
    )


def test_query_expansion_covers_national_park_visual_inference_evidence() -> None:
    plan = build_query_expansion_plan(
        "Which national park could Audrey and Andrew be referring to in their conversations?"
    )

    bridge_query = _expansion_query(plan, "national_park_inference_bridge")

    assert bridge_query.startswith("Audrey Andrew ")
    assert "national park road trip travel destination" in bridge_query
    assert "hiking hike trails trail map route" in bridge_query
    assert "photo image caption visual query" in bridge_query


def test_query_expansion_covers_current_occupation_without_future_job_noise() -> None:
    occupation = build_query_expansion_plan("What does Alex do for work?")
    russian_occupation = build_query_expansion_plan("Кем работает Алекс?")
    future_job = build_query_expansion_plan("What job might Maria pursue in the future?")
    career_want = build_query_expansion_plan("What career does Alex want?")

    assert _expansion_query(occupation, "current_occupation_bridge").startswith("Alex ")
    assert "current job work occupation profession" in _expansion_query(
        occupation,
        "current_occupation_bridge",
    )
    assert _expansion_query(russian_occupation, "current_occupation_bridge").startswith("Алекс ")
    assert "кем работает работа профессия" in _expansion_query(
        russian_occupation,
        "current_occupation_bridge",
    )
    assert "current_occupation_bridge" not in {
        expansion.reason for expansion in future_job.expansions
    }
    assert "career_intent_bridge" not in {expansion.reason for expansion in future_job.expansions}
    assert "current career option pursue" in _expansion_query(
        career_want,
        "career_intent_bridge",
    )
    volunteer_career = _expansion_query(
        future_job,
        "volunteer_career_inference_bridge",
    )
    assert "front desk food bed make difference lives" in volunteer_career
    assert "started fulfilling gave few talks connecting helping others" in volunteer_career
    assert "compliments residents aunt believed brighten struggling" in volunteer_career
    assert "counselor coordinator volunteer homeless future job career social work" in (
        volunteer_career
    )


def test_query_expansion_covers_activity_location_and_destress_bridges() -> None:
    camped = build_query_expansion_plan("Where has Melanie camped?")
    trip = build_query_expansion_plan("Where did John take a trip last year?")
    vacation = build_query_expansion_plan("Where did Maria vacation?")
    visit_city = build_query_expansion_plan("What city did John visit on vacation?")
    cities_been = build_query_expansion_plan("Which cities has Rowan been to?")
    travel_country = build_query_expansion_plan("Which country did Maria travel to?")
    vacation_place = build_query_expansion_plan("What was the place John went for vacation?")
    russian_trip = build_query_expansion_plan("Куда Алекс ездил в отпуск?")
    russian_visit_city = build_query_expansion_plan("Какой город Алекс посетил в отпуске?")
    camping = build_query_expansion_plan("When did Melanie go camping in June?")
    family_hikes = build_query_expansion_plan("What does Melanie do with her family on hikes?")
    post_roadtrip_hike = build_query_expansion_plan(
        "When did Melanie go on a hike after the roadtrip?"
    )
    hike_count = build_query_expansion_plan("How many hikes has Joanna been on?")
    activities = build_query_expansion_plan("What activities does Melanie partake in?")
    destress = build_query_expansion_plan("What does Melanie do to destress?")
    relax = build_query_expansion_plan("What does Melanie do to relax?")
    unwind = build_query_expansion_plan("How does Melanie unwind after work?")
    russian_relax = build_query_expansion_plan("Как Мелани расслабляется после работы?")
    russian_stress = build_query_expansion_plan("Что Мелани делает чтобы снять стресс?")
    art_style = build_query_expansion_plan("What kind of art does Caroline make?")
    direct_art_style = build_query_expansion_plan("What art style does Caroline like?")

    assert "mountains beach forest" in _expansion_query(
        camped,
        "camping_location_bridge",
    )
    assert "destination place city country" in _expansion_query(
        trip,
        "trip_destination_bridge",
    )
    assert "travel traveled travelled visit visited vacation" in _expansion_query(
        vacation,
        "trip_destination_bridge",
    )
    assert "destination place city country" in _expansion_query(
        visit_city,
        "trip_destination_bridge",
    )
    assert "destination place city country" in _expansion_query(
        cities_been,
        "trip_destination_bridge",
    )
    assert "destination place city country" in _expansion_query(
        travel_country,
        "trip_destination_bridge",
    )
    assert "destination place city country" in _expansion_query(
        vacation_place,
        "trip_destination_bridge",
    )
    assert "поездка отпуск путешествие ездил" in _expansion_query(
        russian_trip,
        "trip_destination_bridge",
    )
    assert "поездка отпуск путешествие ездил" in _expansion_query(
        russian_visit_city,
        "trip_destination_bridge",
    )
    assert "roasted marshmallows campfire" in _expansion_query(
        camping,
        "camping_detail_bridge",
    )
    assert "last week week before June 27 session date" in _expansion_query(
        camping,
        "temporal_event_detail_bridge",
    )
    assert "temporal_event_detail_bridge" not in {
        item.reason for item in camped.expansions
    }
    assert "family roasted marshmallows stories campfire" in _expansion_query(
        family_hikes,
        "family_hike_activity_bridge",
    )
    assert "recent yesterday just did it kids loved" in _expansion_query(
        post_roadtrip_hike,
        "post_event_activity_timing_bridge",
    )
    assert _expansion_index(post_roadtrip_hike, "post_event_activity_timing_bridge") < (
        _expansion_index(post_roadtrip_hike, "after_event_temporal_bridge")
    )
    assert "waterfall loved spot rush water soothing" in _expansion_query(
        hike_count,
        "hike_count_activity_bridge",
    )
    assert "buddies weekend new summer fort wayne" in _expansion_query(
        hike_count,
        "hike_count_activity_bridge",
    )
    assert "sunset saw gorgeous other day" in _expansion_query(
        hike_count,
        "hike_count_activity_bridge",
    )
    assert "pottery camping painting swimming" in _expansion_query(
        activities,
        "activity_aggregation_bridge",
    )
    assert "running pottery class therapeutic" in _expansion_query(
        destress,
        "destress_activity_bridge",
    )
    assert "dance dancing dance studio stress relief" in _expansion_query(
        destress,
        "destress_activity_bridge",
    )
    assert "calm relax clear mind headspace unwind" in _expansion_query(
        relax,
        "destress_activity_bridge",
    )
    assert "calm relax clear mind headspace unwind" in _expansion_query(
        unwind,
        "destress_activity_bridge",
    )
    assert "расслабиться расслабляется" in _expansion_query(
        russian_relax,
        "destress_activity_bridge",
    )
    assert "снять стресс" in _expansion_query(
        russian_stress,
        "destress_activity_bridge",
    )
    assert "art show preview abstract style" in _expansion_query(
        art_style,
        "art_style_bridge",
    )
    assert "art show preview abstract style" in _expansion_query(
        direct_art_style,
        "art_style_bridge",
    )


def test_query_expansion_covers_event_participation_bridges() -> None:
    events = build_query_expansion_plan("What LGBTQ+ events has Caroline participated in?")
    support_group_when = build_query_expansion_plan(
        "When did Caroline go to the LGBTQ support group?"
    )
    transgender_events = build_query_expansion_plan(
        "What transgender-specific events has Caroline attended?"
    )
    helping = build_query_expansion_plan(
        "What events has Caroline participated in to help children?"
    )

    assert "events participated attended joined went" in _expansion_query(
        events,
        "event_participation_bridge",
    )
    assert "mentorship mentoring program youth" in _expansion_query(
        events,
        "event_participation_bridge",
    )
    assert "pride parade marched flags" in _expansion_query(
        events,
        "lgbtq_pride_event_bridge",
    )
    assert "support group transgender stories" in _expansion_query(
        events,
        "lgbtq_support_group_event_bridge",
    )
    assert "support group transgender stories" in _expansion_query(
        support_group_when,
        "lgbtq_support_group_event_bridge",
    )
    assert "when date lgbtq support group went attended joined" in _expansion_query(
        support_group_when,
        "temporal_event_detail_bridge",
    )
    assert "school event speech talk" in _expansion_query(
        events,
        "lgbtq_school_event_bridge",
    )
    assert "transgender_poetry_event_bridge" not in {
        expansion.reason for expansion in events.expansions
    }
    assert "transgender youth center talent show kids stage band" in _expansion_query(
        transgender_events,
        "transgender_youth_center_event_bridge",
    )
    assert "help children youth mentorship" in _expansion_query(
        helping,
        "event_participation_help_bridge",
    )
    assert "activist group connected activists" in _expansion_query(
        build_query_expansion_plan(
            "In what ways is Caroline participating in the LGBTQ community?"
        ),
        "lgbtq_community_participation_bridge",
    )


def test_query_expansion_covers_locomo_inference_bridges() -> None:
    workshop = build_query_expansion_plan(
        "What kind of counseling workshop did Melanie attend recently?"
    )
    degree = build_query_expansion_plan("What might John's degree be in?")
    friends = build_query_expansion_plan("Is it likely that Nate has friends besides Joanna?")
    direct_friends = build_query_expansion_plan("Does Nate have friends besides Joanna?")
    other_friends = build_query_expansion_plan("Does Nate have friends other than Alex?")
    apart_friends = build_query_expansion_plan("Does Nate have friends apart from Maria?")
    russian_friends = build_query_expansion_plan("Есть ли у Нейта друзья кроме Жанны?")
    russian_apart_friends = build_query_expansion_plan("Есть ли у Нейта друзья помимо Жанны?")

    assert "therapeutic methods trans people" in _expansion_query(
        workshop,
        "counseling_workshop_bridge",
    )
    assert "policymaking policy political science" in _expansion_query(
        degree,
        "degree_policy_inference_bridge",
    )
    assert "teammates team video game" in _expansion_query(
        friends,
        "friends_team_inference_bridge",
    )
    assert "teammates team video game" in _expansion_query(
        direct_friends,
        "friends_team_inference_bridge",
    )
    assert "teammates team video game" in _expansion_query(
        other_friends,
        "friends_team_inference_bridge",
    )
    assert "teammates team video game" in _expansion_query(
        apart_friends,
        "friends_team_inference_bridge",
    )
    assert "тиммейты онлайн игры" in _expansion_query(
        russian_friends,
        "friends_team_inference_bridge",
    )
    assert "тиммейты онлайн игры" in _expansion_query(
        russian_apart_friends,
        "friends_team_inference_bridge",
    )


def test_query_expansion_covers_locomo_reliable_failure_bridges() -> None:
    cases = [
        (
            build_query_expansion_plan("What activities has Melanie done with her family?"),
            "family_activity_bridge",
            "kids children husband museum",
        ),
        (
            build_query_expansion_plan("What activities has Melanie done with her family?"),
            "family_painting_activity_bridge",
            "painting together nature inspired",
        ),
        (
            build_query_expansion_plan("What activities has Melanie done with her family?"),
            "family_museum_activity_bridge",
            "museum dinosaur exhibit",
        ),
        (
            build_query_expansion_plan("What activities has Melanie done with her family?"),
            "family_swimming_activity_bridge",
            "swimming with kids swim",
        ),
        (
            build_query_expansion_plan("What does Melanie do with her family on hikes?"),
            "family_hike_detail_bridge",
            "roasted marshmallows shared stories",
        ),
        (
            build_query_expansion_plan("What activities does Melanie partake in?"),
            "activity_aggregation_bridge",
            "weekend unplug hang",
        ),
        (
            build_query_expansion_plan("What activities does Melanie partake in?"),
            "activity_visual_selfcare_bridge",
            "taking care ourselves vital self care",
        ),
        (
            build_query_expansion_plan("What do Melanie's kids like?"),
            "children_preference_bridge",
            "dinosaur exhibit museum",
        ),
        (
            build_query_expansion_plan("What activities has Melanie done with her family?"),
            "family_motivation_context_bridge",
            "husband kids children keep motivated",
        ),
        (
            build_query_expansion_plan("Does John live close to a beach or the mountains?"),
            "beach_or_mountains_inference_bridge",
            "beach ocean sunset sailboat",
        ),
        (
            build_query_expansion_plan("What job might Maria pursue in the future?"),
            "volunteer_career_inference_bridge",
            "volunteering shelter front desk",
        ),
        (
            build_query_expansion_plan(
                "What alternative career might Nate consider after gaming?"
            ),
            "animal_care_instruction_bridge",
            "care instructions clean area",
        ),
        (
            build_query_expansion_plan(
                "What alternative career might Nate consider after gaming?"
            ),
            "animal_diet_evidence_bridge",
            "vegetables fruits insects",
        ),
        (
            build_query_expansion_plan(
                "What alternative career might Nate consider after gaming?"
            ),
            "animal_habitat_setup_bridge",
            "new tank bigger tank",
        ),
        (
            build_query_expansion_plan(
                "What alternative career might Nate consider after gaming?"
            ),
            "animal_affinity_pet_store_bridge",
            "pet store joy peace",
        ),
        (
            build_query_expansion_plan(
                "What fields would Caroline be likely to pursue in her educaton?"
            ),
            "education_career_field_bridge",
            "career options fields jobs counseling",
        ),
        (
            build_query_expansion_plan("What career path has Caroline decided to persue?"),
            "career_path_bridge",
            "career path decided pursue persue education options",
        ),
        (
            build_query_expansion_plan("What did Caroline research?"),
            "research_topic_bridge",
            "researched researching research looked into read about",
        ),
        (
            build_query_expansion_plan("What is Caroline's identity?"),
            "identity_bridge",
            "transgender trans woman transition",
        ),
        (
            build_query_expansion_plan("What is Caroline's relationship status?"),
            "relationship_status_bridge",
            "single parent breakup partner married",
        ),
        (
            build_query_expansion_plan("What pets would not cause any discomfort to Joanna?"),
            "pet_allergy_discomfort_bridge",
            "reptiles fur allergic",
        ),
        (
            build_query_expansion_plan(
                "What underlying condition might Joanna have based on her allergies?"
            ),
            "allergy_condition_inference_bridge",
            "allergies allergic reptiles",
        ),
        (
            build_query_expansion_plan("What symbols are important to Caroline?"),
            "symbol_importance_bridge",
            "rainbow flag mural eagle",
        ),
        (
            build_query_expansion_plan("What Console does Nate own?"),
            "console_game_cover_bridge",
            "console nintendo game cover",
        ),
        (
            build_query_expansion_plan("What musical artists/bands has Melanie seen?"),
            "music_artist_band_bridge",
            "saw seen live concert",
        ),
        (
            build_query_expansion_plan("What musical artists/bands has Melanie seen?"),
            "music_artist_answer_bridge",
            "talented voice amazing",
        ),
        (
            build_query_expansion_plan("What bands has Melanie seen?"),
            "music_artist_band_bridge",
            "saw seen live concert",
        ),
        (
            build_query_expansion_plan("Which bands has Dave enjoyed listening to?"),
            "music_artist_band_bridge",
            "listened listening enjoyed favorite",
        ),
        (
            build_query_expansion_plan("What musical artists has Melanie seen?"),
            "music_artist_answer_bridge",
            "talented voice amazing",
        ),
        (
            build_query_expansion_plan(
                "Which classical musicians does Caroline enjoy listening to?"
            ),
            "music_artist_answer_bridge",
            "talented voice amazing",
        ),
        (
            build_query_expansion_plan("What are the new shoes that Caroline got used for?"),
            "shoe_usage_bridge",
            "purple walking running",
        ),
        (
            build_query_expansion_plan("How did Caroline feel while watching the meteor shower?"),
            "meteor_shower_feeling_bridge",
            "felt tiny awe universe",
        ),
        (
            build_query_expansion_plan("How did Melanie feel about her family after the accident?"),
            "post_event_emotion_bridge",
            "family grateful thankful relieved lucky okay",
        ),
        (
            build_query_expansion_plan(
                "Why did Caroline choose to use colors and patterns in her pottery project?"
            ),
            "pottery_color_reason_bridge",
            "catch eye make people smile",
        ),
        (
            build_query_expansion_plan("What types of pottery have Melanie and her kids made?"),
            "pottery_type_bridge",
            "project another class kids creativity",
        ),
        (
            build_query_expansion_plan("What transgender-specific events has Caroline attended?"),
            "transgender_poetry_event_bridge",
            "transgender event poetry reading",
        ),
        (
            build_query_expansion_plan("What transgender-specific events has Caroline attended?"),
            "transgender_conference_event_bridge",
            "transgender conference supportive professionals",
        ),
        (
            build_query_expansion_plan("What book did Melanie read from Caroline's suggestion?"),
            "book_suggestion_bridge",
            "becoming nicole amy ellis nutt",
        ),
        (
            build_query_expansion_plan(
                "Whose recommendation did Melanie follow when she read Becoming Nicole?"
            ),
            "recommendation_source_bridge",
            "recommendation suggestion advice recommended suggested advised follow",
        ),
        (
            build_query_expansion_plan("What recommendation did Alex make recently?"),
            "recommendation_source_bridge",
            "recommendation suggestion advice recommended suggested advised follow",
        ),
        (
            build_query_expansion_plan("What did Alex recommend?"),
            "recommendation_source_bridge",
            "recommendation suggestion advice recommended suggested advised follow",
        ),
        (
            build_query_expansion_plan("How many children does Melanie have?"),
            "children_count_sibling_bridge",
            "brother siblings two younger kids",
        ),
        (
            build_query_expansion_plan("What attributes describe John?"),
            "attribute_description_bridge",
            "volunteering food supplies toy drive",
        ),
        (
            build_query_expansion_plan("Would Caroline be considered religious?"),
            "religious_inference_bridge",
            "stained glass local church journey transgender woman",
        ),
        (
            build_query_expansion_plan(
                "Would Melanie be considered an ally to the transgender community?"
            ),
            "ally_support_bridge",
            "supportive support acceptance community encouraging",
        ),
        (
            build_query_expansion_plan("Why did Gina start her own clothing store?"),
            "business_start_reason_bridge",
            "job loss lost job",
        ),
        (
            build_query_expansion_plan("Why did Maria sit with a little girl at the shelter?"),
            "shelter_comfort_reason_bridge",
            "sitting alone sad",
        ),
        (
            build_query_expansion_plan(
                "What prominent charity organization might Jordan work with and why?"
            ),
            "charity_brand_sponsorship_bridge",
            "sponsorship brand endorsement athletic partner",
        ),
        (
            build_query_expansion_plan("Why does Jolene sometimes put off doing yoga?"),
            "yoga_delay_gaming_bridge",
            "Walking Dead next Saturday",
        ),
        (
            build_query_expansion_plan("How many tournaments has Nate won?"),
            "tournament_count_bridge",
            "first second fourth regional",
        ),
        (
            build_query_expansion_plan("How many charity tournaments has John organized?"),
            "charity_tournament_count_bridge",
            "raised amount children hospital",
        ),
        (
            build_query_expansion_plan("How many screenplays has Joanna written?"),
            "screenplay_count_bridge",
            "first full screenplay printed",
        ),
        (
            build_query_expansion_plan("How many times have Joanna's scripts been rejected?"),
            "screenplay_count_bridge",
            "production company another",
        ),
        (
            build_query_expansion_plan("How many letters has Joanna recieved?"),
            "letter_count_bridge",
            "rejection letter wrote me letter",
        ),
        (
            build_query_expansion_plan("How many pets will Andrew have?"),
            "pet_count_bridge",
            "adopted another dog",
        ),
        (
            build_query_expansion_plan("How many times has Joanna found new hiking trails?"),
            "hiking_trail_count_bridge",
            "found awesome amazing hometown",
        ),
        (
            build_query_expansion_plan("What instruments does Melanie play?"),
            "instrument_play_bridge",
            "clarinet violin",
        ),
        (
            build_query_expansion_plan("What martial arts has John done?"),
            "exercise_activity_inventory_bridge",
            "kickboxing taekwondo",
        ),
        (
            build_query_expansion_plan("What exercises has John done?"),
            "exercise_activity_inventory_bridge",
            "kickboxing taekwondo yoga weight",
        ),
        (
            build_query_expansion_plan(
                "What other exercises can help John with his basketball performance?"
            ),
            "exercise_activity_inventory_bridge",
            "strength flexibility agility speed",
        ),
        (
            build_query_expansion_plan("What are Joanna's hobbies?"),
            "hobby_interest_bridge",
            "hanging with friends hanging friends express myself stories",
        ),
        (
            build_query_expansion_plan("What interests do Joanna and Nate share?"),
            "hobby_interest_bridge",
            "coconut milk dairy-free sweet treats revised old recipes",
        ),
        (
            build_query_expansion_plan("What activities does Nate do with his turtles?"),
            "animal_activity_inventory_bridge",
            "feeding feed eat eating fruit snacks",
        ),
        (
            build_query_expansion_plan("What books has Tim read?"),
            "book_reading_list_bridge",
            "fantasy novel series",
        ),
        (
            build_query_expansion_plan("What mediums does Nate use to play games?"),
            "gaming_medium_bridge",
            "GameCube Gamecube PC Playstation console equipment upgraded setup "
            "competition tournament trophy cash prize controller keyboard",
        ),
        (
            build_query_expansion_plan("What pets does Nate have?"),
            "pet_inventory_bridge",
            "dog new addition",
        ),
        (
            build_query_expansion_plan(
                "Which outdoor gear company likely signed up John for an endorsement deal?"
            ),
            "endorsement_gear_brand_bridge",
            "Under Armour Nike Gatorade",
        ),
        (
            build_query_expansion_plan("When did Caroline go to the adoption meeting?"),
            "temporal_event_detail_bridge",
            "adoption council meeting inspiring",
        ),
        (
            build_query_expansion_plan("When did Jordan apply to adoption agencies?"),
            "temporal_event_detail_bridge",
            "applied to adoption agencies application first step",
        ),
        (
            build_query_expansion_plan("When did Caroline join a new activist group?"),
            "temporal_event_detail_bridge",
            "last Tues Tuesday rights",
        ),
        (
            build_query_expansion_plan("When did Gina interview for a design internship?"),
            "temporal_event_detail_bridge",
            "interview design internship yesterday",
        ),
        (
            build_query_expansion_plan("When did Gina design a limited collection of hoodies?"),
            "temporal_event_detail_bridge",
            "limited edition line hoodie collection",
        ),
    ]

    for plan, reason, expected_text in cases:
        assert expected_text in _expansion_query(plan, reason)


def test_query_expansion_skips_current_career_intent_for_alternative_career() -> None:
    plan = build_query_expansion_plan("What alternative career might Nate consider after gaming?")
    animal_career = build_query_expansion_plan("What animal career would Nate like?")

    assert "career_intent_bridge" not in {item.reason for item in plan.expansions}
    assert "alternative career animal keeper" in _expansion_query(
        animal_career,
        "animal_career_inference_bridge",
    )


def test_query_expansion_skips_camping_detail_for_broad_activity_query() -> None:
    plan = build_query_expansion_plan("What activities has Melanie done with her family?")

    assert "camping_detail_bridge" not in {item.reason for item in plan.expansions}


def test_query_expansion_skips_event_temporal_bridge_for_generic_after_phrases() -> None:
    after_work = build_query_expansion_plan("How does Melanie unwind after work?")
    after_gaming = build_query_expansion_plan(
        "What alternative career might Nate consider after gaming?"
    )

    assert "after_event_temporal_bridge" not in {item.reason for item in after_work.expansions}
    assert "after_event_temporal_bridge" not in {item.reason for item in after_gaming.expansions}


def test_query_expansion_splits_broad_attribute_questions_into_facets() -> None:
    plan = build_query_expansion_plan("What attributes describe John?")
    reasons = {item.reason for item in plan.expansions}

    assert {
        "attribute_description_bridge",
        "attribute_family_support_bridge",
        "attribute_calm_resourcefulness_bridge",
        "attribute_service_helpfulness_bridge",
        "attribute_rescue_purpose_bridge",
        "attribute_trait_inventory_bridge",
    }.issubset(reasons)
    assert _expansion_query(plan, "attribute_family_support_bridge").startswith("John ")
    assert "family rock tough times" in _expansion_query(
        plan,
        "attribute_family_support_bridge",
    )
    assert "stayed calm asked assistance" in _expansion_query(
        plan,
        "attribute_calm_resourcefulness_bridge",
    )
    assert "selfless family-oriented passionate" in _expansion_query(
        plan,
        "attribute_trait_inventory_bridge",
    )


def test_query_expansion_covers_trait_and_adverse_trip_bridges() -> None:
    traits = build_query_expansion_plan("What personality traits might Melanie say Caroline has?")
    roadtrip = build_query_expansion_plan("Would Melanie go on another roadtrip soon?")

    assert "thoughtful authentic driven" in _expansion_query(
        traits,
        "personality_trait_bridge",
    )
    assert "thoughtful concern" in _expansion_query(
        traits,
        "personality_thoughtfulness_bridge",
    )
    assert "authentic real genuine" in _expansion_query(
        traits,
        "personality_authenticity_bridge",
    )
    assert "driven drive determined" in _expansion_query(
        traits,
        "personality_drive_bridge",
    )
    assert "accident scary scared bad start" in _expansion_query(
        roadtrip,
        "adverse_trip_bridge",
    )


def test_query_expansion_covers_books_painted_subject_and_music_bridges() -> None:
    books = build_query_expansion_plan(
        "Would Caroline likely have Dr. Seuss books on her bookshelf?"
    )
    painted = build_query_expansion_plan("What subject have Caroline and Melanie both painted?")
    painting_inventory = build_query_expansion_plan("What has Melanie painted?")
    shown_painting_inventory = build_query_expansion_plan(
        "What painting did Melanie show in yesterday's conversation?"
    )
    music = build_query_expansion_plan(
        "Would Melanie likely enjoy the song The Four Seasons by Vivaldi?"
    )
    vivaldi = build_query_expansion_plan("Would Melanie likely enjoy Vivaldi?")
    four_seasons = build_query_expansion_plan("Would Melanie likely enjoy The Four Seasons?")
    classical_musicians = build_query_expansion_plan(
        "Which classical musicians does Caroline enjoy listening to?"
    )

    assert "classic childrens classics" in _expansion_query(
        books,
        "children_books_inference_bridge",
    )
    assert "painted painting artwork subject" in _expansion_query(
        painted,
        "shared_painted_subject_bridge",
    )
    assert "horse sunset sunrise lake" in _expansion_query(
        painting_inventory,
        "painting_inventory_bridge",
    )
    assert "horse sunset sunrise lake" in _expansion_query(
        shown_painting_inventory,
        "painting_inventory_bridge",
    )
    assert "music classical fan composer" in _expansion_query(
        music,
        "classical_music_preference_bridge",
    )
    assert "vivaldi orchestra symphony" in _expansion_query(
        vivaldi,
        "classical_music_preference_bridge",
    )
    assert "four seasons" in _expansion_query(
        four_seasons,
        "classical_music_preference_bridge",
    )
    assert "music classical fan composer" in _expansion_query(
        classical_musicians,
        "classical_music_preference_bridge",
    )


def test_query_expansion_reminder_query_suppresses_painting_and_workflow_noise() -> None:
    plan = build_query_expansion_plan(
        "What is Riley's handmade keepsake a reminder of?"
    )
    reasons = {expansion.reason for expansion in plan.expansions}

    assert "sentimental_reminder_bridge" in reasons
    assert "painting_inventory_bridge" not in reasons
    assert "followup_task_bridge" not in reasons


def test_query_expansion_covers_commonality_interest_bridges() -> None:
    common_hobby = build_query_expansion_plan(
        "What hobbies do Caroline and Melanie have in common?"
    )
    both_enjoy = build_query_expansion_plan("What do Caroline and Melanie both enjoy?")
    russian = build_query_expansion_plan("Что общего у Алисы и Марии в хобби?")
    russian_both = build_query_expansion_plan("Что Алиса и Мария обе любят?")
    russian_interests = build_query_expansion_plan("Какие общие интересы у Алисы и Марии?")
    who_else = build_query_expansion_plan("Who else likes camping like Caroline?")
    who_shares = build_query_expansion_plan("Who shares Caroline's interest in painting?")
    russian_who_else = build_query_expansion_plan("Кто ещё любит походы как Алиса?")

    assert "common shared both mutual" in _expansion_query(
        common_hobby,
        "commonality_interest_bridge",
    )
    assert "interests hobbies activities" in _expansion_query(
        both_enjoy,
        "commonality_interest_bridge",
    )
    assert "coconut milk dairy-free sweet treats revised old recipes" in _expansion_query(
        common_hobby,
        "commonality_interest_bridge",
    )
    assert "common shared both mutual" in _expansion_query(
        russian,
        "commonality_interest_bridge",
    )
    assert "common shared both mutual" in _expansion_query(
        russian_both,
        "commonality_interest_bridge",
    )
    assert "common shared both mutual" in _expansion_query(
        russian_interests,
        "commonality_interest_bridge",
    )
    assert "common shared both mutual" in _expansion_query(
        who_else,
        "commonality_interest_bridge",
    )
    assert not _expansion_query(
        who_else,
        "commonality_interest_bridge",
    ).startswith("Caroline ")
    assert not _expansion_query(
        who_shares,
        "commonality_interest_bridge",
    ).startswith("Caroline ")
    assert "common shared both mutual" in _expansion_query(
        russian_who_else,
        "commonality_interest_bridge",
    )


def test_query_expansion_covers_business_commonality_bridge() -> None:
    plan = build_query_expansion_plan("What do Jon and Gina both have in common?")
    broad_plan = build_query_expansion_plan("What do Jon and Gina have in common?")
    common_causes = build_query_expansion_plan("What common causes does John support?")

    expansion = _expansion_query(plan, "business_commonality_bridge")
    broad_expansion = _expansion_query(broad_plan, "business_commonality_bridge")
    assert expansion.startswith("Jon Gina ")
    assert "lost job lost jobs own business" in expansion
    assert "dance studio clothing store" in expansion
    assert broad_expansion.startswith("Jon Gina ")
    assert "lost job lost jobs own business" in broad_expansion
    assert "business_commonality_bridge" not in {
        expansion.reason for expansion in common_causes.expansions
    }


def test_query_expansion_covers_business_promotion_inventory_bridges() -> None:
    store = build_query_expansion_plan("How did Gina promote her clothes store?")
    events = build_query_expansion_plan(
        "Which events has Jon participated in to promote his business venture?"
    )
    technical = build_query_expansion_plan("How did the API promote customer service events?")

    store_expansion = _expansion_query(store, "store_promotion_inventory_bridge")
    event_expansion = _expansion_query(events, "business_promotion_event_bridge")
    networking_expansion = _expansion_query(events, "business_networking_event_bridge")
    store_event_expansion = _expansion_query(events, "business_store_promotion_event_bridge")

    assert not store_expansion.startswith("Gina ")
    assert "local artist cool designs" in store_expansion
    assert "limited edition line" in store_expansion
    assert "offers promotions new customers" in store_expansion
    assert "developed video presentation teach fashion pieces" in store_expansion
    assert not event_expansion.startswith("Jon ")
    assert "fair show off studio possible leads" in event_expansion
    assert "networking events make things happen" in event_expansion
    assert "yesterday chose determined focused" in event_expansion
    assert "online store offers promotions" in event_expansion
    assert "networking events make things happen" in networking_expansion
    assert "attending networking events guts drive" in networking_expansion
    assert "online store offers promotions new customers" in store_event_expansion
    assert "wild ride starting business not giving up" in store_event_expansion
    assert "store_promotion_inventory_bridge" not in {
        expansion.reason for expansion in technical.expansions
    }
    assert "business_promotion_event_bridge" not in {
        expansion.reason for expansion in technical.expansions
    }
    assert "business_networking_event_bridge" not in {
        expansion.reason for expansion in technical.expansions
    }
    assert "business_store_promotion_event_bridge" not in {
        expansion.reason for expansion in technical.expansions
    }


def test_query_expansion_covers_business_opening_timeline_bridge() -> None:
    plan = build_query_expansion_plan("How long did it take for Jon to open his studio?")
    technical = build_query_expansion_plan("How long did it take to open the studio API?")

    expansion = _expansion_query(plan, "business_opening_timeline_bridge")

    assert expansion.startswith("Jon ")
    assert "lost job banker yesterday" in expansion
    assert "take shot starting own business" in expansion
    assert "grand opening tomorrow" in expansion
    assert "six months timeline duration" in expansion
    assert "business_opening_timeline_bridge" not in {
        expansion.reason for expansion in technical.expansions
    }


def test_query_expansion_covers_generic_multimodal_evidence_bridges() -> None:
    screenshot = build_query_expansion_plan("What text is written in this screenshot image?")
    video = build_query_expansion_plan("What did Alex say in the video about the launch?")
    meeting = build_query_expansion_plan("What action items came from the meeting?")
    owner = build_query_expansion_plan("Who is responsible for the Atlas follow-up?")
    deadline = build_query_expansion_plan("When is the Atlas launch deadline?")
    due = build_query_expansion_plan("When is Atlas due?")
    overdue = build_query_expansion_plan("Which Atlas tasks are overdue?")
    next_step = build_query_expansion_plan("What is the next step for Atlas?")
    assigned = build_query_expansion_plan("Who is assigned to Atlas?")
    promise = build_query_expansion_plan("What did Alex promise after Atlas?")
    agreed = build_query_expansion_plan("What did Alex agree to after Atlas?")
    need_to = build_query_expansion_plan("What does Alex need to do after Atlas?")
    must_do = build_query_expansion_plan("What must Alex do after Atlas?")
    supposed_to = build_query_expansion_plan("What is Alex supposed to do after Atlas?")
    russian_deadline = build_query_expansion_plan("Какой дедлайн по Атласу?")
    russian_overdue = build_query_expansion_plan("Какие просроченные сроки по Атласу?")
    russian_task = build_query_expansion_plan("Какое поручение назначено по Атласу?")
    russian_need = build_query_expansion_plan("Что нужно сделать по Атласу?")
    provider_recommendation = build_query_expansion_plan("Which provider should I use?")

    assert "ocr detected text written" in _expansion_query(
        screenshot,
        "visual_text_evidence_bridge",
    )
    assert (
        screenshot.diagnostics()["query_expansion_reasons"].count("visual_text_evidence_bridge")
        == 1
    )
    assert "transcript speech said told" in _expansion_query(
        video,
        "video_transcript_evidence_bridge",
    )
    assert "transcript notes discussed decision" in _expansion_query(
        meeting,
        "meeting_evidence_bridge",
    )
    assert "action item task todo follow up next step" in _expansion_query(
        meeting,
        "followup_task_bridge",
    )
    assert "assigned owner responsible" in _expansion_query(
        owner,
        "followup_task_bridge",
    )
    assert "assignee commitment promised" in _expansion_query(
        assigned,
        "followup_task_bridge",
    )
    assert "owner responsible assignee commitment" in _expansion_query(
        promise,
        "followup_task_bridge",
    )
    assert "owner responsible assignee commitment" in _expansion_query(
        agreed,
        "followup_task_bridge",
    )
    assert "owner responsible assignee commitment" in _expansion_query(
        need_to,
        "followup_task_bridge",
    )
    assert "owner responsible assignee commitment" in _expansion_query(
        must_do,
        "followup_task_bridge",
    )
    assert "owner responsible assignee commitment" in _expansion_query(
        supposed_to,
        "followup_task_bridge",
    )
    assert "action item task todo follow up next step" in _expansion_query(
        next_step,
        "followup_task_bridge",
    )
    assert "deadline due date target date" in _expansion_query(
        deadline,
        "deadline_commitment_bridge",
    )
    assert _expansion_query(deadline, "deadline_commitment_bridge").startswith("Atlas ")
    assert "deadline due date target date" in _expansion_query(
        due,
        "deadline_commitment_bridge",
    )
    assert "overdue upcoming commitment" in _expansion_query(
        overdue,
        "deadline_commitment_bridge",
    )
    assert "дедлайн срок сроки дата сдачи" in _expansion_query(
        russian_deadline,
        "deadline_commitment_bridge",
    )
    assert "целевая дата просрочено просроченные" in _expansion_query(
        russian_overdue,
        "deadline_commitment_bridge",
    )
    assert "задача задачи поручение поручения назначено" in _expansion_query(
        russian_task,
        "followup_task_bridge",
    )
    assert "action item task todo follow up next step" in _expansion_query(
        russian_need,
        "followup_task_bridge",
    )
    assert "followup_task_bridge" not in provider_recommendation.diagnostics()[
        "query_expansion_reasons"
    ]


def test_query_expansion_covers_gotcha_failure_bridge() -> None:
    watch_out = build_query_expansion_plan("What should I watch out for in Atlas deployment?")
    went_wrong = build_query_expansion_plan("What went wrong with Atlas Docker?")
    known_issue = build_query_expansion_plan("What known issues does Atlas have?")
    russian = build_query_expansion_plan("Какие подводные камни у Атласа?")
    issue_number = build_query_expansion_plan("Which issue number did Alex mention?")

    assert "gotcha pitfall caveat known issue" in _expansion_query(
        watch_out,
        "gotcha_failure_bridge",
    )
    assert "workaround root cause troubleshooting" in _expansion_query(
        went_wrong,
        "gotcha_failure_bridge",
    )
    assert "known problem failure failed" in _expansion_query(
        known_issue,
        "gotcha_failure_bridge",
    )
    assert "подводные камни известная проблема" in _expansion_query(
        russian,
        "gotcha_failure_bridge",
    )
    assert "gotcha_failure_bridge" not in issue_number.diagnostics()[
        "query_expansion_reasons"
    ]


def test_query_expansion_covers_state_transition_bridge() -> None:
    switched = build_query_expansion_plan("What did Atlas switch from LocalAI to?")
    replaced = build_query_expansion_plan("Which provider replaced LocalAI for Atlas?")
    current_after_switch = build_query_expansion_plan(
        "What is the current Atlas provider after switching from LocalAI?"
    )
    russian = build_query_expansion_plan("Что заменило LocalAI в Атласе?")
    switch_setting = build_query_expansion_plan("Which switch setting did Alex mention?")

    assert "state transition changed switched" in _expansion_query(
        switched,
        "state_transition_bridge",
    )
    assert "previous old current new active" in _expansion_query(
        replaced,
        "state_transition_bridge",
    )
    assert "replaced by before after" in _expansion_query(
        current_after_switch,
        "state_transition_bridge",
    )
    assert "state transition changed switched" in _expansion_query(
        russian,
        "state_transition_bridge",
    )
    assert "state_transition_bridge" not in switch_setting.diagnostics()[
        "query_expansion_reasons"
    ]


def test_query_expansion_adds_speaker_turn_bridge_for_say_queries() -> None:
    english = build_query_expansion_plan("What did Alex say about Project Atlas?")
    russian = build_query_expansion_plan("Что сказал Алекс про Project Atlas?")
    according = build_query_expansion_plan(
        "According to Melanie, what traits does Caroline have?"
    )
    perspective = build_query_expansion_plan(
        "From Melanie's perspective, what traits does Caroline have?"
    )
    russian_according = build_query_expansion_plan(
        "По словам Мелани, какие черты есть у Кэролайн?"
    )

    assert "speaker dialogue turn transcript" in _expansion_query(
        english,
        "speaker_turn_bridge",
    )
    assert "Alex" in _expansion_query(english, "speaker_turn_bridge")
    assert "speaker dialogue turn transcript" in _expansion_query(
        russian,
        "speaker_turn_bridge",
    )
    assert "Алекс" in _expansion_query(russian, "speaker_turn_bridge")
    assert "Melanie" in _expansion_query(according, "speaker_turn_bridge")
    assert "Caroline" in _expansion_query(according, "speaker_turn_bridge")
    assert "Melanie" in _expansion_query(perspective, "speaker_turn_bridge")
    assert "Мелани" in _expansion_query(russian_according, "speaker_turn_bridge")


def test_query_expansion_covers_conversational_transcript_wording() -> None:
    spoke = build_query_expansion_plan("What did Alex decide when he spoke about Atlas?")
    talk = build_query_expansion_plan("Who did Alex talk to about Project Atlas?")
    meet = build_query_expansion_plan("Who did Alex meet with about Atlas?")
    dm = build_query_expansion_plan("What did Dana mention in the DM about Atlas?")
    russian = build_query_expansion_plan(
        "Что Мария решила когда переписывалась с Сергеем про Атлас?"
    )
    russian_talk = build_query_expansion_plan("С кем Алекс говорил про Atlas?")
    russian_meeting = build_query_expansion_plan("Что обсуждали на недавней встрече с Алексом?")
    russian_chat = build_query_expansion_plan("Что было в последнем чате про Atlas?")

    assert "transcript conversation chat message" in _expansion_query(
        spoke,
        "conversation_transcript_evidence_bridge",
    )
    assert "Alex" in _expansion_query(
        spoke,
        "conversation_transcript_evidence_bridge",
    )
    assert "transcript conversation chat message" in _expansion_query(
        talk,
        "conversation_transcript_evidence_bridge",
    )
    assert "transcript conversation chat message" in _expansion_query(
        meet,
        "conversation_transcript_evidence_bridge",
    )
    assert "transcript conversation chat message" in _expansion_query(
        dm,
        "conversation_transcript_evidence_bridge",
    )
    assert "covered centered topic agenda" in _expansion_query(
        dm,
        "conversation_transcript_evidence_bridge",
    )
    assert (
        dm.diagnostics()["query_expansion_reasons"].count("conversation_transcript_evidence_bridge")
        == 1
    )
    assert "транскрипт разговор переписка созвон" in _expansion_query(
        russian,
        "conversation_transcript_evidence_bridge",
    )
    assert "транскрипт разговор переписка созвон" in _expansion_query(
        russian_talk,
        "conversation_transcript_evidence_bridge",
    )
    assert "покрыли тема повестка" in _expansion_query(
        russian_talk,
        "conversation_transcript_evidence_bridge",
    )
    assert "транскрипт разговор встреча созвон" in _expansion_query(
        russian_meeting,
        "conversation_transcript_evidence_bridge",
    )
    assert "транскрипт разговор переписка созвон" in _expansion_query(
        russian_chat,
        "conversation_transcript_evidence_bridge",
    )


def test_query_expansion_covers_source_evidence_bridge() -> None:
    source = build_query_expansion_plan("Show source citation for the Atlas decision")
    russian = build_query_expansion_plan("Покажи источник по решению Атлас")

    assert "source citation evidence quote" in _expansion_query(
        source,
        "source_evidence_bridge",
    )
    assert source.diagnostics()["query_expansion_reasons"].count("source_evidence_bridge") == 1
    assert "источник ссылка доказательство" in _expansion_query(
        russian,
        "source_evidence_bridge",
    )


def test_query_expansion_covers_russian_multimodal_evidence_bridges() -> None:
    video = build_query_expansion_plan("Что Алекс сказал в видео про запуск?")
    clip = build_query_expansion_plan("Что Алекс сказал в ролике про Atlas?")
    video_recording = build_query_expansion_plan("Что на видеозаписи про Atlas?")
    voice = build_query_expansion_plan("Что Алекс сказал в голосовом про Atlas?")
    audio_recording = build_query_expansion_plan("Расшифруй аудиозапись про Atlas")
    screenshot = build_query_expansion_plan("Что написано на скриншоте?")
    picture = build_query_expansion_plan("Прочитай текст на картинке Atlas")
    short_screen = build_query_expansion_plan("Что на скрине про Atlas?")

    assert "транскрипт сказал сказала" in _expansion_query(
        video,
        "video_transcript_evidence_bridge",
    )
    assert "транскрипт сказал сказала" in _expansion_query(
        clip,
        "video_transcript_evidence_bridge",
    )
    assert "транскрипт сказал сказала" in _expansion_query(
        video_recording,
        "video_transcript_evidence_bridge",
    )
    assert "транскрипт речь голос" in _expansion_query(
        voice,
        "audio_transcript_evidence_bridge",
    )
    assert "транскрипт речь голос" in _expansion_query(
        audio_recording,
        "audio_transcript_evidence_bridge",
    )
    screenshot_expansion = _expansion_query(screenshot, "visual_text_evidence_bridge")
    assert "ocr" in screenshot_expansion
    assert "текст написано" in screenshot_expansion
    assert "текст написано" in _expansion_query(
        picture,
        "visual_text_evidence_bridge",
    )
    assert "текст написано" in _expansion_query(
        short_screen,
        "visual_text_evidence_bridge",
    )


def test_query_expansion_covers_generic_ally_inference_bridge() -> None:
    plan = build_query_expansion_plan("Would Melanie be considered an ally?")

    assert "supportive support acceptance" in _expansion_query(
        plan,
        "ally_support_bridge",
    )


def test_query_expansion_covers_generic_behavior_inference_bridge() -> None:
    reliable = build_query_expansion_plan("Would Alex be considered reliable?")
    responsible = build_query_expansion_plan("Would Alex be considered responsible?")
    trustworthy = build_query_expansion_plan("Would Alex be considered trustworthy?")
    dependable = build_query_expansion_plan("Would Alex be considered dependable?")
    organized = build_query_expansion_plan("Would Alex be considered organized?")
    creative = build_query_expansion_plan("Would Alex be considered creative?")
    helpful = build_query_expansion_plan("Would Alex be considered helpful?")
    thoughtful = build_query_expansion_plan("Would Alex be considered thoughtful?")
    dedicated = build_query_expansion_plan("Would Alex be considered dedicated?")
    thorough = build_query_expansion_plan("Would Alex be considered thorough?")
    art_kind = build_query_expansion_plan("What kind of art does Alex make?")

    assert _expansion_query(reliable, "generic_behavior_inference_bridge").startswith(
        "Alex "
    )
    assert "kept promises followed through" in _expansion_query(
        reliable,
        "generic_behavior_inference_bridge",
    )
    for plan in (responsible, trustworthy, dependable):
        assert "dependable responsible trustworthy" in _expansion_query(
            plan,
            "generic_behavior_inference_bridge",
        )
    assert "organized planned prepared scheduled" in _expansion_query(
        organized,
        "generic_behavior_inference_bridge",
    )
    assert "creative artistic designed created" in _expansion_query(
        creative,
        "generic_behavior_inference_bridge",
    )
    for plan in (helpful, thoughtful):
        assert "helpful supportive caring listened helped" in _expansion_query(
            plan,
            "generic_behavior_inference_bridge",
        )
    assert "disciplined hardworking dedicated practiced trained" in _expansion_query(
        dedicated,
        "generic_behavior_inference_bridge",
    )
    assert "careful thorough meticulous cautious checked" in _expansion_query(
        thorough,
        "generic_behavior_inference_bridge",
    )
    assert "generic_behavior_inference_bridge" not in {
        expansion.reason for expansion in art_kind.expansions
    }


def test_query_expansion_covers_temporal_change_bridges() -> None:
    latest = build_query_expansion_plan("What is the latest current Atlas decision?")
    final_decision = build_query_expansion_plan("What is the final Atlas decision?")
    source_of_truth = build_query_expansion_plan(
        "What is the canonical source of truth for Atlas?"
    )
    currently = build_query_expansion_plan("What is Alex doing currently?")
    most_recent = build_query_expansion_plan("What is the most recent Atlas decision?")
    still_valid = build_query_expansion_plan("Which Atlas provider is still valid?")
    chosen_provider = build_query_expansion_plan("Which Atlas provider was chosen?")
    no_longer_valid = build_query_expansion_plan("Which Atlas provider is no longer valid?")
    no_longer_use = build_query_expansion_plan("Which provider should I no longer use?")
    provider = build_query_expansion_plan("Which provider should I use?")
    changed = build_query_expansion_plan("What changed after the meeting with Alex?")
    before = build_query_expansion_plan("What was the plan before the call?")

    assert "latest current active newest" in _expansion_query(
        latest,
        "current_state_temporal_bridge",
    )
    assert (
        latest.diagnostics()["query_expansion_reasons"].count("current_state_temporal_bridge") == 1
    )
    assert "final decision decided selected chosen" in _expansion_query(
        final_decision,
        "current_state_temporal_bridge",
    )
    assert "source of truth canonical" in _expansion_query(
        source_of_truth,
        "current_state_temporal_bridge",
    )
    assert "currently current active latest" in _expansion_query(
        currently,
        "current_state_temporal_bridge",
    )
    assert "most recent latest current" in _expansion_query(
        most_recent,
        "current_state_temporal_bridge",
    )
    assert "still valid remains current" in _expansion_query(
        still_valid,
        "current_state_temporal_bridge",
    )
    assert "final decision decided selected chosen" in _expansion_query(
        chosen_provider,
        "current_state_temporal_bridge",
    )
    assert "recommended preferred decided chose chosen selected" in _expansion_query(
        chosen_provider,
        "current_recommendation_bridge",
    )
    assert "no longer valid stale" in _expansion_query(
        no_longer_valid,
        "stale_state_temporal_bridge",
    )
    assert "no longer use no longer using" in _expansion_query(
        no_longer_use,
        "stale_state_temporal_bridge",
    )
    assert "current_recommendation_bridge" not in {
        expansion.reason for expansion in no_longer_use.expansions
    }
    not_current = build_query_expansion_plan("Which Atlas provider is not current?")
    assert "not current stale outdated" in _expansion_query(
        not_current,
        "stale_state_temporal_bridge",
    )
    assert "current_state_temporal_bridge" not in {
        expansion.reason for expansion in not_current.expansions
    }
    assert "recommended preferred decided chose chosen selected switched" in _expansion_query(
        provider,
        "current_recommendation_bridge",
    )
    assert "changed change updated now" in _expansion_query(
        changed,
        "change_over_time_bridge",
    )
    assert "after later following" in _expansion_query(
        changed,
        "after_event_temporal_bridge",
    )
    assert "before earlier prior" in _expansion_query(
        before,
        "before_event_temporal_bridge",
    )


def test_query_expansion_covers_russian_temporal_change_bridges() -> None:
    current = build_query_expansion_plan("Какое актуальное решение по проекту Атлас?")
    final = build_query_expansion_plan("Какое финальное решение по проекту Атлас?")
    selected_provider = build_query_expansion_plan("Какой выбранный провайдер для Атлас?")
    still_current = build_query_expansion_plan("Какой провайдер все еще актуален?")
    changed = build_query_expansion_plan("Что изменилось после встречи с Алексом?")
    stale = build_query_expansion_plan("Устаревшее не учитывать, что сейчас актуально?")
    no_longer_use = build_query_expansion_plan("Какой провайдер больше не использовать?")

    assert "актуальный текущий последний" in _expansion_query(
        current,
        "current_state_temporal_bridge",
    )
    assert "финальный окончательный выбранный" in _expansion_query(
        final,
        "current_state_temporal_bridge",
    )
    assert "финальный окончательный выбранный" in _expansion_query(
        selected_provider,
        "current_state_temporal_bridge",
    )
    assert "актуальный текущий последний" in _expansion_query(
        still_current,
        "current_state_temporal_bridge",
    )
    change_query = _expansion_query(changed, "change_over_time_bridge")
    assert "изменилось изменили" in change_query
    assert "сменился сменили заменили" in change_query
    assert "стало раньше сейчас" in change_query
    assert "после позже затем" in _expansion_query(
        changed,
        "after_event_temporal_bridge",
    )
    assert "устаревший старый" in _expansion_query(
        stale,
        "stale_state_temporal_bridge",
    )
    assert "больше не использовать устаревший" in _expansion_query(
        no_longer_use,
        "stale_state_temporal_bridge",
    )


def test_best_query_relevance_uses_expansion_for_low_overlap_evidence() -> None:
    plan = build_query_expansion_plan("Where did Caroline move from 4 years ago?")

    query, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D4:3 Caroline: This necklace was a gift from my grandma in my home "
            "country, Sweden, and reminds me of my roots."
        ),
    )

    assert query.startswith("Caroline ")
    assert reason == "relocation_origin_bridge"
    assert relevance.distinctive_term_hits >= 2


def test_best_query_relevance_uses_symbol_meaning_bridge() -> None:
    plan = build_query_expansion_plan("What does Caroline's necklace symbolize?")

    query, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D4:3 Caroline: This necklace is a gift from my grandma in my home "
            "country, Sweden. It stands for love, faith and strength, and reminds "
            "me of my roots."
        ),
    )

    assert query.startswith("Caroline ")
    assert reason == "symbol_importance_bridge"
    assert relevance.distinctive_term_hits >= 4


def test_best_query_relevance_uses_visual_symbol_object_bridge() -> None:
    cases = (
        (
            "What do sunflowers represent according to Caroline?",
            "D3:4 Caroline says sunflowers represent hope, resilience, and growth.",
            5,
        ),
        (
            "What does Gina's tattoo symbolize?",
            "D2:8 Gina's flower tattoo symbolizes resilience and personal growth.",
            5,
        ),
    )

    for query_text, text, min_hits in cases:
        query, reason, relevance = best_query_relevance(
            build_query_expansion_plan(query_text),
            text=text,
        )

        assert query
        assert reason == "symbol_importance_bridge"
        assert relevance.distinctive_term_hits >= min_hits


def test_best_query_relevance_uses_possession_gift_bridge() -> None:
    plan = build_query_expansion_plan("What was grandma's gift to Caroline?")

    query, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D4:3 Caroline: This necklace was a gift from my grandma in my home "
            "country, Sweden, and reminds me of my roots."
        ),
    )

    assert query.startswith("Caroline ")
    assert reason == "possession_gift_object_bridge"
    assert relevance.distinctive_term_hits >= 5


def test_best_query_relevance_uses_family_origin_bridge() -> None:
    plan = build_query_expansion_plan("What country is Caroline's grandma from?")

    query, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D4:3 Caroline: This necklace was a gift from my grandma in my home "
            "country, Sweden, and reminds me of my roots."
        ),
    )

    assert query.startswith("Caroline ")
    assert reason == "family_origin_bridge"
    assert relevance.distinctive_term_hits >= 5


def test_best_query_relevance_uses_friend_group_duration_bridge() -> None:
    plan = build_query_expansion_plan(
        "How long has Caroline had her current group of friends for?"
    )

    query, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D3:13 Caroline: I've known these friends for 4 years, since I "
            "moved from my home country."
        ),
    )

    assert query.startswith("Caroline ")
    assert reason == "relationship_duration_bridge"
    assert relevance.distinctive_term_hits >= 6


def test_best_query_relevance_prefers_marriage_duration_phrase_evidence() -> None:
    plan = build_query_expansion_plan("How long have Alex and his husband been married?")

    _, duration_reason, duration_relevance = best_query_relevance(
        plan,
        text="D4:2 Alex: My husband and I have been married for five years already.",
    )
    _, topical_reason, topical_relevance = best_query_relevance(
        plan,
        text="D4:3 Alex wore his wedding dress and talked about his husband.",
    )

    assert duration_reason == "relationship_duration_bridge"
    assert topical_reason == "relationship_duration_bridge"
    assert duration_relevance.distinctive_term_hits > topical_relevance.distinctive_term_hits
    assert duration_relevance.hit_ratio > topical_relevance.hit_ratio


def test_best_query_relevance_uses_post_event_emotion_bridge() -> None:
    plan = build_query_expansion_plan(
        "How did Melanie feel about her family after the accident?"
    )
    realization = build_query_expansion_plan(
        "What did Melanie realize after the charity race?"
    )

    query, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D18:5 Melanie: After the accident, I felt grateful and thankful "
            "for my family. They mean the world to me."
        ),
    )
    realization_query, realization_reason, realization_relevance = best_query_relevance(
        realization,
        text=(
            "D7:4 Melanie: After the charity race, I realized taking care of "
            "my mental health is vital, so self-care matters."
        ),
    )

    assert query.startswith("Melanie ")
    assert reason == "post_event_emotion_bridge"
    assert relevance.distinctive_term_hits >= 7
    assert realization_query.startswith("Melanie ")
    assert realization_reason == "post_event_emotion_bridge"
    assert realization_relevance.distinctive_term_hits >= 7


def test_best_query_relevance_uses_post_event_family_appreciation_wording() -> None:
    plan = build_query_expansion_plan(
        "How did Caroline feel about her family after the accident?"
    )

    query, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D18:5 Melanie: Yeah, you're right, Caroline. Family's super "
            "important to me. Especially after the accident, I've thought a "
            "lot about how much I need them. They mean the world to me and "
            "I'm so thankful to have them."
        ),
    )

    assert query.startswith("Caroline ")
    assert reason == "post_event_emotion_bridge"
    assert relevance.distinctive_term_hits >= 10


def test_best_query_relevance_uses_source_evidence_bridge() -> None:
    plan = build_query_expansion_plan("Show proof for the Atlas decision")

    _, reason, relevance = best_query_relevance(
        plan,
        text=("Evidence quote from the meeting transcript: Alex approved the Atlas launch path."),
    )

    assert reason == "source_evidence_bridge"
    assert relevance.distinctive_term_hits >= 2


def test_best_query_relevance_uses_relax_wording_for_destress_evidence() -> None:
    plan = build_query_expansion_plan("What does Melanie do to relax?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Melanie goes running and takes pottery classes because they are "
            "therapeutic and clear her mind."
        ),
    )

    assert reason == "destress_activity_bridge"
    assert relevance.distinctive_term_hits >= 6


def test_destress_query_prefers_specific_bridge_over_broad_commonality() -> None:
    plan = build_query_expansion_plan("How do Jon and Gina both like to destress?")

    assert plan.expansions[0].reason == "destress_activity_bridge"
    assert "dance dancing dance studio stress relief" in plan.expansions[0].query
    assert "commonality_interest_bridge" in {item.reason for item in plan.expansions}


def test_best_query_relevance_uses_dance_relief_wording_for_destress_evidence() -> None:
    plan = build_query_expansion_plan("How do Jon and Gina both like to destress?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "Jon has been into dancing since he was a kid, and it has been "
            "his passion and escape."
        ),
    )

    assert reason == "destress_activity_bridge"
    assert relevance.distinctive_term_hits >= 4


def test_query_expansion_bridges_study_time_management_evidence() -> None:
    plan = build_query_expansion_plan(
        "Which popular time management technique does Tim use to prepare for exams?"
    )
    technical = build_query_expansion_plan(
        "How does the API time management queue behave during retry timeouts?"
    )

    expansion = _expansion_query(plan, "study_time_management_bridge")
    assert expansion.startswith("Tim ")
    assert "exam exams finals test tests prep prepare studying study" in expansion
    assert "pomodoro 25 minutes 5 minutes intervals breaks smaller parts" in expansion
    assert "study_time_management_bridge" not in {
        item.reason for item in technical.expansions
    }


def test_best_query_relevance_uses_study_time_management_bridge() -> None:
    plan = build_query_expansion_plan(
        "Which popular time management technique does Tim use to prepare for exams?"
    )

    _, exam_reason, exam_relevance = best_query_relevance(
        plan,
        text=(
            "D18:3 Tim: This week has been swamped with exams for me but "
            "I'm plowing through."
        ),
    )
    _, technique_reason, technique_relevance = best_query_relevance(
        plan,
        text=(
            "D18:7 Tim: I like breaking up my studying into smaller parts. "
            "25 minutes on, then 5 minutes off for something fun. It's less "
            "overwhelming and keeps me on track."
        ),
    )
    _, loose_reason, loose_relevance = best_query_relevance(
        plan,
        text=(
            "D5:1 Tim: We need to improve API time management in the backend "
            "queue with retry limits."
        ),
    )

    assert exam_reason == "study_time_management_bridge"
    assert exam_relevance.distinctive_term_hits >= 4
    assert technique_reason == "study_time_management_bridge"
    assert technique_relevance.distinctive_term_hits >= 8
    assert keyword_chunk_score(
        technique_relevance,
        query_expansion_reason=technique_reason,
    ) > keyword_chunk_score(
        loose_relevance,
        query_expansion_reason=loose_reason,
    )


def test_best_query_relevance_uses_specific_support_origin_bridge() -> None:
    plan = build_query_expansion_plan(
        "Would Caroline still want to pursue counseling as a career if she hadn't "
        "received support growing up?"
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D3:5 Caroline: I've been blessed with loads of love and support "
            "throughout this journey, and I want to pass it on to others. "
            "By sharing our stories, we can build a strong, supportive community "
            "of hope."
        ),
    )

    assert reason == "support_origin_bridge"
    assert relevance.distinctive_term_hits >= 6


def test_best_query_relevance_uses_support_career_motivation_bridge() -> None:
    plan = build_query_expansion_plan(
        "Would Caroline still want to pursue counseling as a career if she hadn't "
        "received support growing up?"
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D4:15 Caroline: My own journey and the support I got made a huge "
            "difference. I saw how counseling and support groups improved my life, "
            "so I started caring more about mental health. Now I'm passionate "
            "about creating a safe, inviting place for people to grow."
        ),
    )
    focused = score_query_relevance(
        query=_expansion_query(plan, "support_career_motivation_bridge"),
        text=(
            "D4:15 Caroline: My own journey and the support I got made a huge "
            "difference. I saw how counseling and support groups improved my life, "
            "so I started caring more about mental health. Now I'm passionate "
            "about creating a safe, inviting place for people to grow."
        ),
    )
    looser = score_query_relevance(
        query=_expansion_query(plan, "support_career_motivation_bridge"),
        text=(
            "D7:7 Caroline: I struggled with mental health, and support I got was "
            "really helpful. It made me realize how important it is for others to "
            "have a support system, so I started looking into counseling jobs."
        ),
    )

    assert reason == "support_career_motivation_bridge"
    assert relevance.distinctive_term_hits >= 10
    assert keyword_chunk_score(
        focused,
        query_expansion_reason="support_career_motivation_bridge",
    ) > keyword_chunk_score(
        looser,
        query_expansion_reason="support_career_motivation_bridge",
    )


def test_best_query_relevance_uses_motivation_reason_bridge_for_why_questions() -> None:
    plan = build_query_expansion_plan("Why did Caroline want to work in counseling?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D4:15 Caroline: My own journey and the support I got made a huge "
            "difference. It made me realize how much I care about mental health, "
            "so I chose counseling to help people feel safe and supported."
        ),
    )

    assert reason == "motivation_reason_bridge"
    assert relevance.distinctive_term_hits >= 8


def test_query_expansion_covers_counseling_services_and_safe_place_goals() -> None:
    services = build_query_expansion_plan(
        "What kind of counseling and mental health services is Caroline "
        "interested in pursuing?"
    )
    place = build_query_expansion_plan(
        "What kind of place does Caroline want to create for people?"
    )

    assert "therapy therapeutic support" in _expansion_query(
        services,
        "counseling_services_interest_bridge",
    )
    assert "similar issues lgbtq trans community" in _expansion_query(
        services,
        "counseling_services_interest_bridge",
    )
    assert "safe inviting supportive welcoming" in _expansion_query(
        place,
        "safe_supportive_place_goal_bridge",
    )
    assert "counseling mental health support" in _expansion_query(
        place,
        "safe_supportive_place_goal_bridge",
    )


def test_best_query_relevance_uses_counseling_service_goal_bridges() -> None:
    services = build_query_expansion_plan(
        "What kind of counseling and mental health services is Caroline "
        "interested in pursuing?"
    )
    place = build_query_expansion_plan(
        "What kind of place does Caroline want to create for people?"
    )

    _, services_reason, services_relevance = best_query_relevance(
        services,
        text=(
            "D4:15 Caroline: I'm interested in counseling and mental health "
            "services for LGBTQ and trans people with similar issues."
        ),
    )
    _, place_reason, place_relevance = best_query_relevance(
        place,
        text=(
            "D4:16 Caroline: I want to create a safe, inviting, supportive "
            "space where people feel accepted and can grow."
        ),
    )

    assert services_reason == "counseling_services_interest_bridge"
    assert services_relevance.distinctive_term_hits >= 9
    assert place_reason == "safe_supportive_place_goal_bridge"
    assert place_relevance.distinctive_term_hits >= 8


def test_best_query_relevance_uses_education_career_field_bridge() -> None:
    plan = build_query_expansion_plan(
        "What fields would Caroline be likely to pursue in her educaton?"
    )

    _, options_reason, options_relevance = best_query_relevance(
        plan,
        text=(
            "D1:9 Caroline: Gonna continue my edu and check out career options, "
            "which is pretty exciting!"
        ),
    )
    _, counseling_reason, counseling_relevance = best_query_relevance(
        plan,
        text=(
            "D1:11 Caroline: I'm keen on counseling or working in mental health - "
            "I'd love to support those with similar issues."
        ),
    )

    assert options_reason == "education_career_field_bridge"
    assert options_relevance.distinctive_term_hits >= 5
    assert counseling_reason == "education_career_field_bridge"
    assert counseling_relevance.distinctive_term_hits >= 5


def test_best_query_relevance_uses_career_path_typo_bridge() -> None:
    career = build_query_expansion_plan("What career path has Caroline decided to persue?")

    _, career_reason, career_relevance = best_query_relevance(
        career,
        text=(
            "D4:13 Caroline: I decided I want to pursue a career path in "
            "counseling and mental health work after exploring my education options."
        ),
    )

    assert career_reason == "career_path_bridge"
    assert career_relevance.distinctive_term_hits >= 6


def test_best_query_relevance_uses_research_topic_bridge() -> None:
    plan = build_query_expansion_plan("What did Caroline research?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D3:8 Caroline: I looked into adoption agencies and read about "
            "support resources and options."
        ),
    )

    assert reason == "research_topic_bridge"
    assert relevance.distinctive_term_hits >= 5


def test_best_query_relevance_uses_career_intent_bridge_for_counterfactual_option() -> None:
    plan = build_query_expansion_plan("Would Caroline pursue writing as a career option?")

    _, focused_reason, focused_relevance = best_query_relevance(
        plan,
        text=(
            "D7:5 Caroline: I need to figure out what to do next after graduation. "
            "D7:9 Caroline: I talked with Melanie about possible next steps. "
            "Observation: Caroline is looking into counseling and mental health jobs "
            "as her current career option."
        ),
    )
    _, loose_reason, loose_relevance = best_query_relevance(
        plan,
        text=(
            "D12:2 Caroline: She wrote a short story about career uncertainty, "
            "but did not decide to pursue writing as a job."
        ),
    )

    assert focused_reason == "career_intent_bridge"
    assert focused_relevance.distinctive_term_hits >= 8
    assert keyword_chunk_score(
        focused_relevance,
        query_expansion_reason=focused_reason,
    ) > keyword_chunk_score(
        loose_relevance,
        query_expansion_reason=loose_reason,
    )


def test_best_query_relevance_uses_identity_and_relationship_status_bridges() -> None:
    identity = build_query_expansion_plan("What is Caroline's identity?")
    relationship = build_query_expansion_plan("What is Caroline's relationship status?")

    _, identity_reason, identity_relevance = best_query_relevance(
        identity,
        text=(
            "D1:5 Caroline: The transgender stories were so inspiring! "
            "visual query: transgender pride flag mural"
        ),
    )
    _, relationship_reason, relationship_relevance = best_query_relevance(
        relationship,
        text=(
            "D2:14 Caroline: It'll be tough as a single parent, but I'm up for "
            "the challenge after that tough breakup."
        ),
    )
    _, breakup_reason, breakup_relevance = best_query_relevance(
        relationship,
        text=(
            "D3:13 Caroline: My friends, family and mentors are my rocks and "
            "support system, especially after that tough breakup."
        ),
    )
    _, support_reason, support_relevance = best_query_relevance(
        relationship,
        text="D4:2 Caroline has friends and family mentors who support her.",
    )

    assert identity_reason == "identity_bridge"
    assert identity_relevance.distinctive_term_hits >= 5
    assert relationship_reason in {
        "decomposition_relationship_status",
        "relationship_status_bridge",
    }
    assert relationship_relevance.distinctive_term_hits >= 5
    assert breakup_reason == "relationship_status_bridge"
    assert breakup_relevance.distinctive_term_hits >= 5
    assert support_reason == "relationship_status_bridge"
    assert support_relevance.distinctive_term_hits < relationship_relevance.distinctive_term_hits


def test_best_query_relevance_uses_trait_and_adverse_trip_bridges() -> None:
    traits = build_query_expansion_plan("What personality traits might Melanie say Caroline has?")
    roadtrip = build_query_expansion_plan("Would Melanie go on another roadtrip soon?")

    _, trait_reason, trait_relevance = best_query_relevance(
        traits,
        text=(
            "D16:18 Melanie: Thank you for your concern, you're so thoughtful. "
            "D13:16 Melanie: You really care about being real and helping others. "
            "D7:4 Melanie: Your drive to help is awesome."
        ),
    )
    _, trip_reason, trip_relevance = best_query_relevance(
        roadtrip,
        text=(
            "D18:1 Melanie: That roadtrip was insane and we were all freaked "
            "when my son got into an accident. D18:3 Melanie: Our trip got off "
            "to a bad start. I was really scared."
        ),
    )

    assert trait_reason == "personality_trait_bridge"
    assert trait_relevance.distinctive_term_hits >= 5
    assert trip_reason == "adverse_trip_bridge"
    assert trip_relevance.distinctive_term_hits >= 5


def test_best_query_relevance_uses_generic_behavior_inference_bridge() -> None:
    plan = build_query_expansion_plan("Would Alex be considered reliable?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="Alex kept his promises, followed through, and prepared the launch notes early.",
    )

    assert reason == "generic_behavior_inference_bridge"
    assert relevance.distinctive_term_hits >= 4


def test_trait_query_decomposition_targets_single_trait_turns() -> None:
    plan = build_query_expansion_plan("What personality traits might Melanie say Caroline has?")

    _, thoughtful_reason, thoughtful = best_query_relevance(
        plan,
        text=(
            "D16:18 Melanie: The sign was just a precaution, but thank you for "
            "your concern, you're so thoughtful!"
        ),
    )
    _, authentic_reason, authentic = best_query_relevance(
        plan,
        text=("D13:16 Melanie: You really care about being real and helping others."),
    )
    _, drive_reason, drive = best_query_relevance(
        plan,
        text=("D7:4 Melanie: Your drive to help is awesome! What's your plan to pitch in?"),
    )

    assert thoughtful_reason == "personality_thoughtfulness_bridge"
    assert thoughtful.distinctive_term_hits >= 4
    assert authentic_reason == "personality_authenticity_bridge"
    assert authentic.distinctive_term_hits >= 4
    assert drive_reason == "personality_drive_bridge"
    assert drive.distinctive_term_hits >= 5


def test_best_query_relevance_uses_specific_outdoor_nature_memory_bridge() -> None:
    plan = build_query_expansion_plan(
        "Would Melanie be more interested in going to a national park or a theme park?"
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D10:14 Melanie: I'll always remember our camping trip last year "
            "when we saw the Perseid meteor shower. It was amazing watching "
            "the sky light up and feeling at one with the universe."
        ),
    )

    assert reason == "outdoor_nature_memory_bridge"
    assert relevance.distinctive_term_hits >= 6


def test_best_query_relevance_uses_children_preference_bridge_for_kids_likes() -> None:
    plan = build_query_expansion_plan("What do Melanie's kids like?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D6:6 Melanie: They were stoked for the dinosaur exhibit! "
            "They love learning about animals and the bones were so cool."
        ),
    )

    assert reason == "children_preference_bridge"
    assert relevance.distinctive_term_hits >= 5


def test_best_query_relevance_uses_activity_participation_for_partake_query() -> None:
    plan = build_query_expansion_plan("What activities does Melanie partake in?")

    _, camp_reason, camp = best_query_relevance(
        plan,
        text=(
            "D9:1 Melanie: I had a quiet weekend after we went camping with "
            "my fam two weekends ago. It was great to unplug and hang with the kids."
        ),
    )
    _, swim_reason, swim = best_query_relevance(
        plan,
        text="D1:18 Melanie: I'm off to go swimming with the kids. Talk to you soon!",
    )
    _, pottery_reason, pottery = best_query_relevance(
        plan,
        text=(
            "D5:4 Melanie: I just signed up for a pottery class yesterday. "
            "It's like therapy for me, letting me express myself and get creative."
        ),
    )

    assert camp_reason == "decomposition_activity_participation"
    assert camp.distinctive_term_hits >= 8
    assert swim_reason == "decomposition_activity_participation"
    assert swim.distinctive_term_hits >= 5
    assert pottery_reason == "decomposition_activity_participation"
    assert pottery.distinctive_term_hits >= 6


def test_best_query_relevance_uses_inventory_list_for_travel_places() -> None:
    plan = build_query_expansion_plan("What European countries has Maria been to?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D13:24 Maria visited Spain on a school trip. "
            "D8:15 Maria went to England and loved traveling abroad."
        ),
    )

    assert reason == "travel_country_inventory_bridge"
    assert relevance.distinctive_term_hits >= 6


def test_best_query_relevance_uses_travel_country_inventory_bridge() -> None:
    plan = build_query_expansion_plan("What European countries has Maria been to?")

    expansion = _expansion_query(plan, "travel_country_inventory_bridge")
    assert expansion.startswith("Maria ")
    assert "European Maria" not in expansion
    assert "abroad overseas solo trip travel traveled travelled visited went" in expansion
    assert "country countries European Europe landmark landmarks" in expansion

    _, spain_reason, spain_relevance = best_query_relevance(
        plan,
        text=(
            "D13:24 Maria: Last year I took a solo trip and took this pic in Spain."
        ),
    )
    _, england_reason, england_relevance = best_query_relevance(
        plan,
        text=(
            "D8:15 Maria: I got the idea from that trip to England a few years ago."
        ),
    )

    assert spain_reason == "travel_country_inventory_bridge"
    assert spain_relevance.distinctive_term_hits >= 4
    assert england_reason == "travel_country_inventory_bridge"
    assert england_relevance.distinctive_term_hits >= 2


def test_best_query_relevance_uses_travel_inventory_for_shared_visited_city() -> None:
    plan = build_query_expansion_plan("Which city have both Jean and John visited?")

    expansion = _expansion_query(plan, "travel_country_inventory_bridge")
    assert expansion.startswith("Jean John ")
    assert "city cities capital capitals place places destination destinations" in expansion
    assert "country countries European Europe landmark landmarks" in expansion

    _, gina_reason, gina_relevance = best_query_relevance(
        plan,
        text=(
            "D2:5 Gina: Paris?! That is really great Jon! Never had a chance "
            "to visit it. Been only to Rome once."
        ),
    )
    _, jon_reason, jon_relevance = best_query_relevance(
        plan,
        text=(
            "D15:1 Jon: Took a short trip last week to Rome to clear my mind "
            "a little."
        ),
    )

    assert gina_reason == "travel_country_inventory_bridge"
    assert gina_relevance.distinctive_term_hits >= 3
    assert jon_reason == "travel_country_inventory_bridge"
    assert jon_relevance.distinctive_term_hits >= 2


def test_best_query_relevance_uses_inventory_list_for_shelters_and_causes() -> None:
    shelter_plan = build_query_expansion_plan("What shelters does Maria volunteer at?")
    cause_plan = build_query_expansion_plan(
        "What causes does John feel passionate about supporting?"
    )

    _, shelter_reason, shelter_relevance = best_query_relevance(
        shelter_plan,
        text=(
            "D2:1 Maria volunteers at the homeless shelter. "
            "D11:10 She also started at the dog shelter."
        ),
    )
    _, cause_reason, cause_relevance = best_query_relevance(
        cause_plan,
        text=(
            "D15:3 John feels passionate about supporting veterans, schools, "
            "and infrastructure in his community."
        ),
    )

    assert shelter_reason == "decomposition_inventory_list"
    assert shelter_relevance.distinctive_term_hits >= 7
    assert cause_reason == "cause_veterans_inventory_bridge"
    assert cause_relevance.distinctive_term_hits >= 5


def test_best_query_relevance_uses_inventory_list_for_desserts() -> None:
    plan = build_query_expansion_plan("What desserts has Maria made?")

    decompositions = {
        item.reason: item.query
        for item in plan.decompositions
    }
    inventory_query = decompositions["decomposition_inventory_list"]
    assert inventory_query.startswith("maria ")
    assert "cobbler" in inventory_query
    assert "sundae" in inventory_query
    assert "sweet treat treats" in inventory_query
    assert "pudding parfait" in inventory_query
    assert "visual query image caption" in inventory_query

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D2:25 Maria made peach cobbler recently. "
            "D13:18 Maria's favorite dessert is a banana split sundae."
        ),
    )

    assert reason == "decomposition_inventory_list"
    assert relevance.distinctive_term_hits >= 5

    _, visual_reason, visual_relevance = best_query_relevance(
        plan,
        text=(
            "D19:8 Maria celebrated by making this delicious treat. "
            "image caption: two desserts with spoons and chocolate. "
            "visual query: raspberry chia pudding parfait dessert."
        ),
    )

    assert visual_reason == "decomposition_inventory_list"
    assert visual_relevance.distinctive_term_hits >= 7


def test_best_query_relevance_uses_cause_inventory_bridges() -> None:
    plan = build_query_expansion_plan(
        "What causes does John feel passionate about supporting?"
    )
    event_plan = build_query_expansion_plan(
        "What events for different causes has John organized?"
    )

    assert "education reform infrastructure development" in _expansion_query(
        plan,
        "cause_education_infrastructure_inventory_bridge",
    )
    assert "veterans rights passionate support" in _expansion_query(
        plan,
        "cause_veterans_inventory_bridge",
    )
    assert "cause_event_inventory_bridge" not in {
        expansion.reason for expansion in plan.expansions
    }
    assert "cause_event_inventory_bridge" in {
        expansion.reason for expansion in event_plan.expansions
    }

    _, education_reason, education_relevance = best_query_relevance(
        plan,
        text=(
            "D9:8 John: Improving education and infrastructure is particularly "
            "interesting to me. Related turns: D9:10 D9:12."
        ),
    )
    _, reform_reason, reform_relevance = best_query_relevance(
        plan,
        text="D12:5 John focused on education reform and infrastructure development.",
    )
    _, veterans_reason, veterans_relevance = best_query_relevance(
        plan,
        text="D15:3 John feels passionate about supporting veterans and their rights.",
    )

    assert education_reason == "cause_education_infrastructure_inventory_bridge"
    assert education_relevance.distinctive_term_hits >= 7
    assert reform_reason == "cause_education_infrastructure_inventory_bridge"
    assert reform_relevance.distinctive_term_hits >= 5
    assert veterans_reason == "cause_veterans_inventory_bridge"
    assert veterans_relevance.distinctive_term_hits >= 5


def test_best_query_relevance_uses_cause_awareness_event_bridge() -> None:
    plan = build_query_expansion_plan("What did the charity race raise awareness for?")

    assert "mental health domestic abuse animal welfare" in _expansion_query(
        plan,
        "cause_awareness_event_bridge",
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D2:2 Caroline: That charity race sounds great, Mel! Making a "
            "difference and raising awareness for mental health is super rewarding."
        ),
    )
    _, weak_reason, weak_relevance = best_query_relevance(
        plan,
        text=(
            "D12:5 The product marketing dashboard improved brand awareness "
            "for the dance studio target audience."
        ),
    )

    assert reason == "cause_awareness_event_bridge"
    assert relevance.distinctive_term_hits >= 7
    assert weak_reason == "cause_awareness_event_bridge"
    assert weak_relevance.distinctive_term_hits < relevance.distinctive_term_hits


def test_best_query_relevance_uses_inventory_list_for_where_place_lists() -> None:
    plan = build_query_expansion_plan("Where has Maria made friends?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D2:1 Maria made friends at the homeless shelter. "
            "D14:10 Maria met more friends at church and the gym."
        ),
    )

    assert reason in {
        "friend_place_inventory_bridge",
        "friend_place_shelter_inventory_bridge",
        "friend_place_gym_inventory_bridge",
        "friend_place_church_inventory_bridge",
    }
    assert relevance.distinctive_term_hits >= 6


def test_best_query_relevance_uses_friend_place_inventory_bridge() -> None:
    plan = build_query_expansion_plan("Where has Maria made friends?")

    expansion_reasons = {item.reason for item in plan.expansions}
    assert {
        "friend_place_inventory_bridge",
        "friend_place_shelter_inventory_bridge",
        "friend_place_gym_inventory_bridge",
        "friend_place_church_inventory_bridge",
    }.issubset(expansion_reasons)

    _, gym_reason, gym_relevance = best_query_relevance(
        plan,
        text=(
            "D19:1 Maria joined a gym last week. It has been super positive "
            "with supportive people and a welcoming atmosphere."
        ),
    )
    _, church_reason, church_relevance = best_query_relevance(
        plan,
        text="D14:10 Maria joined a nearby church to feel closer to a community and faith.",
    )
    _, shelter_reason, shelter_relevance = best_query_relevance(
        plan,
        text=(
            "D2:1 Maria donated her old car to a homeless shelter where she volunteers "
            "and met fellow volunteers."
        ),
    )

    assert gym_reason == "friend_place_gym_inventory_bridge"
    assert gym_relevance.distinctive_term_hits >= 5
    assert church_reason == "friend_place_church_inventory_bridge"
    assert church_relevance.distinctive_term_hits >= 4
    assert shelter_reason == "friend_place_shelter_inventory_bridge"
    assert shelter_relevance.distinctive_term_hits >= 5


def test_best_query_relevance_uses_activity_visual_selfcare_bridge() -> None:
    plan = build_query_expansion_plan("What activities does Melanie partake in?")
    selfcare_plan = build_query_expansion_plan("How does Melanie prioritize self-care?")

    _, visual_reason, visual = best_query_relevance(
        plan,
        text=(
            "D1:12 Melanie: By the way, take a look at this. "
            "image caption: a photo of a painting of a sunset over a lake. "
            "visual query: painting sunrise"
        ),
    )
    _, swim_reason, swim = best_query_relevance(
        plan,
        text=(
            "D1:18 Melanie: Taking care of ourselves is vital. "
            "I'm off to go swimming with the kids."
        ),
    )
    selfcare_bridge = _expansion_query(selfcare_plan, "activity_visual_selfcare_bridge")
    _, selfcare_reason, selfcare = best_query_relevance(
        selfcare_plan,
        text=(
            "D1:18 Melanie: Taking care of ourselves is vital after a long day. "
            "I relax by going swimming with the kids."
        ),
    )

    assert visual_reason == "activity_visual_selfcare_bridge"
    assert visual.distinctive_term_hits >= 6
    assert swim_reason == "activity_visual_selfcare_bridge"
    assert swim.distinctive_term_hits >= 7
    assert selfcare_bridge.startswith("Melanie ")
    assert "vital self care relax long day" in selfcare_bridge
    assert selfcare_reason == "activity_visual_selfcare_bridge"
    assert selfcare.distinctive_term_hits >= 7


def test_best_query_relevance_uses_painting_inventory_bridge_for_visual_artifacts() -> None:
    plan = build_query_expansion_plan("What has Melanie painted?")

    _, horse_reason, horse = best_query_relevance(
        plan,
        text=(
            "D13:8 Melanie: Here's a photo of my horse painting. "
            "image caption: a photo of a horse painted on a wooden wall. "
            "visual query: horse painting"
        ),
    )
    _, sunset_reason, sunset = best_query_relevance(
        plan,
        text=(
            "D8:6 Melanie: We love painting together lately. "
            "image caption: a photo of a painting of a sunset with a palm tree. "
            "visual query: painting vibrant flowers sunset sky"
        ),
    )

    assert horse_reason == "painting_inventory_bridge"
    assert horse.distinctive_term_hits >= 5
    assert sunset_reason == "painting_inventory_bridge"
    assert sunset.distinctive_term_hits >= 5


def test_best_query_relevance_bridges_beach_count_activity_evidence() -> None:
    plan = build_query_expansion_plan("How many times has Melanie gone to the beach in 2023?")

    _, recent_reason, recent = best_query_relevance(
        plan,
        text=(
            "D10:8 Melanie image query: beach family playing frisbee sandy shore. "
            "Melanie: We went to the beach recently. The kids had such a blast."
        ),
    )
    _, camp_reason, camp = best_query_relevance(
        plan,
        text=(
            "D6:16 Melanie image caption: a family sitting around a campfire "
            "on the beach. Melanie: Here is a pic of my family camping at the beach."
        ),
    )

    assert recent_reason == "beach_count_activity_bridge"
    assert recent.distinctive_term_hits >= 5
    assert camp_reason == "beach_count_activity_bridge"
    assert camp.distinctive_term_hits >= 5


def test_best_query_relevance_bridges_classical_music_preferences() -> None:
    plan = build_query_expansion_plan(
        'Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?'
    )
    musicians = build_query_expansion_plan(
        "Which classical musicians does Caroline enjoy listening to?"
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D15:28 Melanie: I'm a fan of both classical like Bach and Mozart, "
            "as well as modern music like Ed Sheeran's Perfect."
        ),
    )
    _, musicians_reason, musicians_relevance = best_query_relevance(
        musicians,
        text=(
            "D15:29 Caroline enjoys listening to classical composers like "
            "Bach and Mozart."
        ),
    )

    assert reason == "classical_music_preference_bridge"
    assert relevance.distinctive_term_hits >= 4
    assert musicians_reason == "classical_music_preference_bridge"
    assert musicians_relevance.distinctive_term_hits >= 6


def test_best_query_relevance_bridges_music_artist_listening_questions() -> None:
    bands = build_query_expansion_plan("Which bands has Dave enjoyed listening to?")

    _, reason, relevance = best_query_relevance(
        bands,
        text="D2:3 Dave enjoyed listening to the band Radiohead and other musicians.",
    )

    assert reason == "music_artist_band_bridge"
    assert relevance.distinctive_term_hits >= 6


def test_best_query_relevance_bridges_negative_classical_music_preferences() -> None:
    plan = build_query_expansion_plan(
        'Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?'
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text="Melanie avoids classical music and dislikes orchestra concerts.",
    )

    assert reason == "classical_music_preference_bridge"
    assert relevance.distinctive_term_hits >= 4


def test_best_query_relevance_bridges_food_preference_evidence() -> None:
    plan = build_query_expansion_plan("Which meat does Audrey prefer eating more than others?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D10:23 Audrey: Roasted Chicken is one of my favorites. "
            "This recipe is based on my love for Mediterranean flavors, "
            "with chicken, garlic, lemon, and herbs."
        ),
    )

    assert reason == "food_preference_bridge"
    assert relevance.distinctive_term_hits >= 5


def test_best_query_relevance_bridges_state_residence_inference_evidence() -> None:
    plan = build_query_expansion_plan("Which US state do Audrey and Andrew potentially live in?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D11:9 Andrew image caption: a photo of a map of a park with a lot "
            "of trees. Andrew image query: hiking trails map perfect spot. "
            "Andrew: Here is the map for the trail."
        ),
    )

    assert reason == "state_residence_inference_bridge"
    assert relevance.distinctive_term_hits >= 5


def test_query_expansion_bridges_named_state_residence_city_aliases() -> None:
    plan = build_query_expansion_plan("Does James live in Connecticut?")

    bridge_query = _expansion_query(plan, "state_residence_inference_bridge")
    assert bridge_query.startswith("James Connecticut ")
    assert "connecticut stamford" in bridge_query
    assert "shelter adopted" in bridge_query

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D5:1 James adopted a pup from a shelter in Stamford last week "
            "and named it Ned."
        ),
    )

    assert reason == "state_residence_inference_bridge"
    assert relevance.distinctive_term_hits >= 4


def test_best_query_relevance_bridges_business_start_reason_evidence() -> None:
    plan = build_query_expansion_plan("Why did Gina start her own clothing store?")

    _, job_loss_reason, job_loss_relevance = best_query_relevance(
        plan,
        text=(
            "D1:3 Gina also lost her Door Dash job this month, so she was "
            "thinking about business stuff more seriously."
        ),
    )
    _, fashion_reason, fashion_relevance = best_query_relevance(
        plan,
        text=(
            "D6:8 Gina has always been passionate about fashion trends and "
            "unique pieces, and wanted to blend dance and fashion creatively."
        ),
    )

    assert job_loss_reason == "business_start_reason_bridge"
    assert job_loss_relevance.distinctive_term_hits >= 4
    assert fashion_reason == "business_start_reason_bridge"
    assert fashion_relevance.distinctive_term_hits >= 5


def test_best_query_relevance_bridges_business_commonality_evidence() -> None:
    plan = build_query_expansion_plan("What do Jon and Gina both have in common?")

    cases = (
        (
            "D1:3 Gina: Unfortunately, I also lost my job at Door Dash this month. "
            "What business are you thinking of?",
            "business_commonality_bridge",
        ),
        (
            "D1:4 Jon: I'm starting a dance studio because I'm passionate about dancing.",
            "business_commonality_bridge",
        ),
        (
            "D2:1 Gina launched an ad campaign for her clothing store and "
            "is starting her own store.",
            "business_commonality_bridge",
        ),
    )

    for text, expected_reason in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == expected_reason
        assert relevance.distinctive_term_hits >= 2


def test_best_query_relevance_bridges_store_promotion_inventory_evidence() -> None:
    plan = build_query_expansion_plan("How did Gina promote her clothes store?")

    cases = (
        (
            "D5:5 Gina: I've been working hard on my online store and teamed "
            "up with a local artist for some cool designs.",
            7,
        ),
        (
            "D16:3 Gina: I made a limited edition line last week to show off "
            "my style and creativity.",
            6,
        ),
        (
            "D8:4 Gina: I got some new offers and promotions going on my "
            "online store to bring in new customers.",
            7,
        ),
        (
            "D13:4 Gina: I have developed a video presentation to teach how "
            "to style my fashion pieces.",
            5,
        ),
    )

    for text, min_hits in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "store_promotion_inventory_bridge"
        assert relevance.distinctive_term_hits >= min_hits


def test_best_query_relevance_bridges_business_promotion_event_evidence() -> None:
    plan = build_query_expansion_plan(
        "Which events has Jon participated in to promote his business venture?"
    )

    cases = (
        (
            "D10:1 Jon: I went to a fair to show off my studio and get "
            "possible leads.",
            6,
        ),
    )

    for text, min_hits in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "business_promotion_event_bridge"
        assert relevance.distinctive_term_hits >= min_hits


def test_best_query_relevance_bridges_business_networking_event_evidence() -> None:
    plan = build_query_expansion_plan(
        "Which events has Jon participated in to promote his business venture?"
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D16:6 Jon: Yesterday I chose to go to networking events to make "
            "things happen. It's been tough but I'm staying determined and focused."
        ),
    )

    assert reason == "business_networking_event_bridge"
    assert relevance.distinctive_term_hits >= 7


def test_best_query_relevance_bridges_business_store_promotion_event_evidence() -> None:
    plan = build_query_expansion_plan(
        "Which events has Jon participated in to promote his business venture?"
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D8:4 Gina: I got some new offers and promotions going on my "
            "online store to try and bring in new customers. It's been a wild "
            "ride starting my business, but I'm not giving up!"
        ),
    )

    assert reason == "business_store_promotion_event_bridge"
    assert relevance.distinctive_term_hits >= 9


def test_best_query_relevance_bridges_business_opening_timeline_evidence() -> None:
    plan = build_query_expansion_plan("How long did it take for Jon to open his studio?")

    cases = (
        (
            "D1:2 Jon: Lost my job as a banker yesterday, so I'm gonna take "
            "a shot at starting my own business.",
            10,
        ),
        (
            "D15:13 Jon: tomorrow at the grand opening!",
            5,
        ),
    )

    for text, min_hits in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "business_opening_timeline_bridge"
        assert relevance.distinctive_term_hits >= min_hits


def test_best_query_relevance_bridges_shelter_comfort_reason_evidence() -> None:
    plan = build_query_expansion_plan("Why did Maria sit with a little girl at the shelter?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D5:10 Maria noticed an eight year old little girl sitting alone "
            "and looking sad with no other family, so she sat with her, offered "
            "comfort and a listening ear, and made her laugh."
        ),
    )

    assert reason == "shelter_comfort_reason_bridge"
    assert relevance.distinctive_term_hits >= 8


def test_best_query_relevance_bridges_support_role_fit_evidence() -> None:
    plan = build_query_expansion_plan("Would Caroline be a good mentor for Alex?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D5:10 Caroline listened carefully when Alex was stuck, offered "
            "guidance and comfort, and helped him feel safe discussing similar "
            "issues."
        ),
    )

    assert reason == "support_role_fit_bridge"
    assert relevance.distinctive_term_hits >= 7


def test_best_query_relevance_bridges_charity_brand_sponsorship_evidence() -> None:
    plan = build_query_expansion_plan(
        "What prominent charity organization might Jordan work with and why?"
    )

    cases = (
        (
            "D3:13 Jordan signed a TrailCore basketball shoe and gear deal and is "
            "talking with HydraFuel about sponsorship.",
            5,
        ),
        (
            "D3:15 Jordan likes SummitGear and thinks it would be cool to work "
            "with them on basketball gear.",
            4,
        ),
        (
            "D6:15 Jordan wants to make a difference away from the court through "
            "charity, inspiring people, and giving back.",
            7,
        ),
    )
    for text, min_hits in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "charity_brand_sponsorship_bridge"
        assert relevance.distinctive_term_hits >= min_hits


def test_query_expansion_bridges_post_athletic_career_without_goal_noise() -> None:
    post_career = build_query_expansion_plan(
        "What could John do after his basketball career?"
    )
    in_career_goals = build_query_expansion_plan(
        "What are John's goals with regards to his basketball career?"
    )
    off_court_goals = build_query_expansion_plan(
        "What are John's goals for his career that are not related to his basketball skills?"
    )

    expansion = _expansion_query(post_career, "post_athletic_career_bridge")
    assert expansion.startswith("John ")
    assert "basketball coach coaching mentor leadership leader great" in expansion
    assert "puts others first eventually becomes king aragorn" in expansion
    assert "sports marketing seminars helping people share knowledge" in expansion
    assert "post_athletic_career_bridge" not in {
        item.reason for item in in_career_goals.expansions
    }
    assert "post_athletic_career_bridge" not in {
        item.reason for item in off_court_goals.expansions
    }


def test_query_expansion_bridges_vehicle_issue_queries() -> None:
    damage = build_query_expansion_plan("What damages have happened to John's car?")
    accident = build_query_expansion_plan("When did Maria get in a car accident?")
    preference = build_query_expansion_plan("Which types of cars does Dave like the most?")

    assert "car vehicle auto accident incident crash" in _expansion_query(
        damage,
        "vehicle_issue_bridge",
    )
    assert "broken windshield flat tire maintenance repair" in _expansion_query(
        accident,
        "vehicle_issue_bridge",
    )
    assert "vehicle_issue_bridge" not in {item.reason for item in preference.expansions}


def test_best_query_relevance_uses_vehicle_issue_bridge() -> None:
    plan = build_query_expansion_plan("What damages have happened to John's car?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "John's car had a broken windshield and a dent after the accident, "
            "so he took the vehicle to a repair shop."
        ),
    )

    assert reason == "vehicle_issue_bridge"
    assert relevance.distinctive_term_hits >= 6


def test_query_expansion_bridges_favorite_preference_queries() -> None:
    book = build_query_expansion_plan("What was Melanie's favorite book from childhood?")
    dessert = build_query_expansion_plan("What are Nate's favorite desserts?")
    style = build_query_expansion_plan("What is Gina's favorite style of dance?")
    memory = build_query_expansion_plan("What was Jon's favorite dancing memory?")
    player = build_query_expansion_plan("Who is Tim and John's favorite basketball player?")
    movie = build_query_expansion_plan("What is Nate's favorite genre of movies?")

    assert "favorite favourite preferred prefer" in _expansion_query(
        book,
        "favorite_preference_bridge",
    )
    assert "book books novel novels series childhood reading" in _expansion_query(
        book,
        "favorite_preference_bridge",
    )
    assert "dessert desserts dish dishes treat" in _expansion_query(
        dessert,
        "favorite_preference_bridge",
    )
    assert "style type kind genre dance dancing" in _expansion_query(
        style,
        "favorite_preference_bridge",
    )
    assert "memory memories moment experience" in _expansion_query(
        memory,
        "favorite_preference_bridge",
    )
    assert "player athlete sports basketball" in _expansion_query(
        player,
        "favorite_preference_bridge",
    )
    assert "favorite_preference_bridge" not in {item.reason for item in movie.expansions}


def test_best_query_relevance_uses_favorite_preference_bridge() -> None:
    plan = build_query_expansion_plan("What is Gina's favorite style of dance?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="Gina said salsa is her favorite dance style and she enjoys the movement.",
    )

    assert reason == "favorite_preference_bridge"
    assert relevance.distinctive_term_hits >= 6


def test_query_expansion_bridges_career_month_setbacks() -> None:
    plan = build_query_expansion_plan(
        "Was September a good month career-wise for Dana and Morgan?"
    )

    expansion = _expansion_query(plan, "negative_experience_support_bridge")

    assert "setback setbacks letdown failure" in expansion
    assert "lost work lost progress crashed" in expansion
    assert "competition tournament performance" in expansion


def test_best_query_relevance_bridges_post_athletic_career_evidence() -> None:
    plan = build_query_expansion_plan(
        "What could John do after his basketball career?"
    )

    evidence_cases = (
        (
            "D11:19 John wants to use his platform to make a positive "
            "difference, inspire others, start a foundation, do charity work, "
            "and leave a meaningful legacy.",
            9,
        ),
        (
            "D26:1 John started doing seminars, helping people with their "
            "sports and marketing.",
            5,
        ),
        (
            "D27:26 John admires that Aragorn is a great leader and puts "
            "others first.",
            5,
        ),
    )
    for text, min_hits in evidence_cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "post_athletic_career_bridge"
        assert relevance.distinctive_term_hits >= min_hits


def test_query_expansion_covers_fantasy_author_preference_bridge() -> None:
    plan = build_query_expansion_plan(
        "Would Tim enjoy reading books by C. S. Lewis or John Greene?"
    )

    expansion = _expansion_query(plan, "book_suggestion_bridge")
    assert expansion.startswith("Tim Lewis John ")
    assert "fantasy classics" in expansion
    assert "magical world universe" in expansion


def test_best_query_relevance_bridges_fantasy_author_preference_evidence() -> None:
    plan = build_query_expansion_plan(
        "Would Tim enjoy reading books by C. S. Lewis or John Greene?"
    )

    cases = (
        (
            "D1:14 Tim talked to a friend who is a fantasy series fan and "
            "loves getting lost in that magical world.",
            7,
        ),
        (
            "D1:16 Tim discusses a wizarding fantasy universe, including "
            "characters, spells, and magical creatures.",
            8,
        ),
        (
            "D1:18 Tim visited fantasy movie locations that felt like walking into "
            "a magical world and wants to explore more fantasy places.",
            7,
        ),
    )
    for text, min_hits in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "book_suggestion_bridge"
        assert relevance.distinctive_term_hits >= min_hits


def test_query_expansion_covers_media_preference_and_character_bridges() -> None:
    fantasy_movies = build_query_expansion_plan("What fantasy movies does Tim like?")
    fantasy_novels = build_query_expansion_plan(
        "Which two fantasy novels does Tim particularly enjoy writing about?"
    )
    tv_series = build_query_expansion_plan(
        "What new fantasy TV series is Tim excited about?"
    )
    movie_genre = build_query_expansion_plan(
        "What is Nate's favorite genre of movies?"
    )
    superhero = build_query_expansion_plan("What superhero is Joanna a fan of?")
    superhero_figure = build_query_expansion_plan(
        "Which superhero toy figure does Nate share a photo of?"
    )

    assert "fantasy movie movies" in _expansion_query(
        fantasy_movies,
        "hobby_interest_bridge",
    )
    assert "novel novels title story fantasy series" in _expansion_query(
        fantasy_novels,
        "book_reading_list_bridge",
    )
    assert "tv series show shows" in _expansion_query(
        tv_series,
        "hobby_interest_bridge",
    )
    assert "favorite movie film trilogy genre" in _expansion_query(
        movie_genre,
        "hobby_interest_bridge",
    )
    assert "superhero fan favorite character" in _expansion_query(
        superhero,
        "hobby_interest_bridge",
    )
    assert "toy figure action figure" in _expansion_query(
        superhero_figure,
        "item_purchase_bridge",
    )


def test_best_query_relevance_bridges_media_preference_and_character_evidence() -> None:
    cases = (
        (
            build_query_expansion_plan("What fantasy movies does Tim like?"),
            "D1:1 Tim likes fantasy movies with magical worlds and wizarding adventures.",
            "hobby_interest_bridge",
            10,
        ),
        (
            build_query_expansion_plan(
                "Which two fantasy novels does Tim particularly enjoy writing about?"
            ),
            (
                "D2:2 Tim particularly enjoys writing about fantasy novels and "
                "magical book series."
            ),
            "book_reading_list_bridge",
            11,
        ),
        (
            build_query_expansion_plan(
                "What is one of Tim's favorite fantasy TV shows?"
            ),
            (
                "D3:3 Tim mentioned his favorite fantasy TV show and watched "
                "the new season."
            ),
            "hobby_interest_bridge",
            9,
        ),
        (
            build_query_expansion_plan("What superhero is Joanna a fan of?"),
            (
                "D5:5 Joanna is a fan of the superhero character in the comic "
                "movie universe."
            ),
            "hobby_interest_bridge",
            8,
        ),
        (
            build_query_expansion_plan(
                "Which superhero toy figure does Nate share a photo of?"
            ),
            (
                "D6:6 Nate shared a photo of a superhero toy figure and "
                "collectible figurine."
            ),
            "item_purchase_bridge",
            7,
        ),
    )

    for plan, text, expected_reason, min_hits in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == expected_reason
        assert relevance.distinctive_term_hits >= min_hits


def test_query_expansion_bridges_themed_location_destination_evidence() -> None:
    plan = build_query_expansion_plan(
        "Which Aurora Quest-related locations would Avery enjoy during her visit to Ireland?"
    )

    expansion = _expansion_query(plan, "themed_location_destination_bridge")
    anchor_expansion = _expansion_query(
        plan,
        "themed_location_destination_anchor_bridge",
    )
    assert "Aurora Quest" in expansion
    assert "Ireland" in expansion
    assert "study abroad semester" in expansion
    assert "favorite favourite movie film book series fantasy fiction" in expansion
    assert "Ireland" in anchor_expansion
    assert "study abroad semester accepted applied program" in anchor_expansion

    cases = (
        (
            "D4:9 Avery went to a real fantasy movie place last year. "
            "The tour was amazing, and she would love to explore more places like that.",
            7,
        ),
        (
            "D8:1 Avery got accepted into a study abroad program. "
            "Next month, she is off to Ireland for a semester.",
            8,
        ),
        (
            "D12:5 Avery said Aurora Quest is her favorite fantasy film "
            "and never gets old.",
            7,
        ),
    )
    for text, min_hits in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason in {
            "themed_location_destination_anchor_bridge",
            "themed_location_destination_bridge",
        }
        assert relevance.distinctive_term_hits >= min_hits


def test_best_query_relevance_bridges_yoga_delay_gaming_evidence() -> None:
    plan = build_query_expansion_plan("Why does Jolene sometimes put off doing yoga?")

    cases = (
        (
            "D3:11 Jolene planned to play console games with her partner instead.",
            5,
        ),
        (
            "D2:30 Jolene was planning to play Walking Dead next Saturday.",
            4,
        ),
    )
    for text, min_hits in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "yoga_delay_gaming_bridge"
        assert relevance.distinctive_term_hits >= min_hits


def test_best_query_relevance_bridges_tournament_count_evidence() -> None:
    plan = build_query_expansion_plan("How many tournaments has Nate won?")

    cases = (
        "D1:3 Nate won his first video game tournament last week.",
        "D10:4 Nate won his second tournament after practicing.",
        "D17:1 Nate won his fourth video game tournament on Friday.",
        "D27:1 Nate was in the final of a big Valorant tournament and won.",
    )
    for text in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "tournament_count_bridge"
        assert relevance.distinctive_term_hits >= 4


def test_query_expansion_bridges_ordinal_answer_evidence() -> None:
    plan = build_query_expansion_plan("Which tournament did Nate win fourth?")

    assert "ordinal_answer_bridge" in {expansion.reason for expansion in plan.expansions}
    assert "order sequence ordinal" in _expansion_query(plan, "ordinal_answer_bridge")


def test_best_query_relevance_bridges_ordinal_answer_evidence() -> None:
    plan = build_query_expansion_plan("Which tournament did Nate win fourth?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="D17:1 Nate won his fourth video game tournament at the charity arcade night.",
    )

    assert reason == "ordinal_answer_bridge"
    assert relevance.distinctive_term_hits >= 3


def test_query_expansion_adds_quantity_enumeration_fallback_for_unknown_count() -> None:
    plan = build_query_expansion_plan("How many certificates did Priya collect?")

    assert "quantity_enumeration_bridge" in {
        expansion.reason for expansion in plan.expansions
    }
    assert "count total number quantity" in _expansion_query(
        plan,
        "quantity_enumeration_bridge",
    )


def test_best_query_relevance_bridges_charity_tournament_count_evidence() -> None:
    plan = build_query_expansion_plan("How many charity tournaments has John organized?")

    _, organized_reason, organized = best_query_relevance(
        plan,
        text=(
            "D10:2 John was organizing something with friends yesterday for "
            "a charity tournament."
        ),
    )
    _, held_reason, held = best_query_relevance(
        plan,
        text=(
            "D29:1 John held a gaming tourney with buddies and raised money "
            "for a children's hospital, combining gaming and a good cause."
        ),
    )

    assert organized_reason == "charity_tournament_count_bridge"
    assert organized.distinctive_term_hits >= 4
    assert held_reason == "charity_tournament_count_bridge"
    assert held.distinctive_term_hits >= 6


def test_best_query_relevance_bridges_screenplay_and_letter_counts() -> None:
    screenplay = build_query_expansion_plan("How many screenplays has Joanna written?")
    rejected_scripts = build_query_expansion_plan(
        "How many times have Joanna's scripts been rejected?"
    )
    letter = build_query_expansion_plan("How many letters has Joanna recieved?")

    _, screenplay_reason, screenplay_relevance = best_query_relevance(
        screenplay,
        text=(
            "D12:14 Joanna said yes, this was her third one, a story she had "
            "for ages and finally got the guts to write."
        ),
    )
    _, rejected_reason, rejected_relevance = best_query_relevance(
        rejected_scripts,
        text=(
            "D24:12 Joanna had a bit of a setback recently - another "
            "rejection from a production company."
        ),
    )
    _, letter_reason, letter_relevance = best_query_relevance(
        letter,
        text=(
            "D18:5 Someone wrote Joanna a letter after reading her online blog "
            "post, and their words touched her."
        ),
    )

    assert screenplay_reason == "screenplay_count_bridge"
    assert screenplay_relevance.distinctive_term_hits >= 4
    assert rejected_reason == "screenplay_count_bridge"
    assert rejected_relevance.distinctive_term_hits >= 5
    assert letter_reason == "letter_count_bridge"
    assert letter_relevance.distinctive_term_hits >= 5


def test_best_query_relevance_bridges_pet_and_hiking_trail_counts() -> None:
    pets = build_query_expansion_plan("How many pets will Andrew have?")
    trails = build_query_expansion_plan("How many times has Joanna found new hiking trails?")

    _, pet_reason, pet_relevance = best_query_relevance(
        pets,
        text="D28:6 Andrew adopted another dog the other day and shared a photo of the doggo.",
    )
    _, trail_reason, trail_relevance = best_query_relevance(
        trails,
        text=(
            "D11:3 Joanna went hiking and found some more amazing trails "
            "in her town."
        ),
    )

    assert pet_reason == "pet_count_bridge"
    assert pet_relevance.distinctive_term_hits >= 4
    assert trail_reason == "hiking_trail_count_bridge"
    assert trail_relevance.distinctive_term_hits >= 5


def test_best_query_relevance_bridges_personal_list_fact_evidence() -> None:
    instruments = build_query_expansion_plan("What instruments does Melanie play?")
    hobbies = build_query_expansion_plan("What are Joanna's hobbies?")
    books = build_query_expansion_plan("What books has Tim read?")

    _, instrument_reason, instrument_relevance = best_query_relevance(
        instruments,
        text="D15:26 Melanie plays clarinet and started when she was young.",
    )
    _, hobby_reason, hobby_relevance = best_query_relevance(
        hobbies,
        text="D1:10 Joanna enjoys writing, reading, watching movies, and exploring nature.",
    )
    _, book_reason, book_relevance = best_query_relevance(
        books,
        text=(
            "D22:13 Tim just finished A Dance with Dragons and loves fantasy "
            "book series like The Wheel of Time."
        ),
    )

    assert instrument_reason == "instrument_play_bridge"
    assert instrument_relevance.distinctive_term_hits >= 4
    assert hobby_reason == "hobby_interest_bridge"
    assert hobby_relevance.distinctive_term_hits >= 5
    assert book_reason == "book_reading_list_bridge"
    assert book_relevance.distinctive_term_hits >= 6


def test_query_expansion_covers_birdwatching_city_schedule_evidence() -> None:
    compact = build_query_expansion_plan(
        "What could Andrew do to make birdwatching fit in his city schedule?"
    )
    spaced = build_query_expansion_plan(
        "What could Andrew do to make bird watching fit in his city schedule?"
    )

    for plan in (compact, spaced):
        bridge = _expansion_query(plan, "birdwatching_city_schedule_bridge")

        assert "bird feeder" in bridge
        assert "busy week" in bridge
        assert "binoculars" in bridge
        assert "city schedule" in bridge
        assert "ideal spot" in bridge


def test_best_query_relevance_bridges_birdwatching_city_schedule_evidence() -> None:
    plan = build_query_expansion_plan(
        "What could Andrew do to make birdwatching fit in his city schedule?"
    )

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "D20:21 Andrew: The binoculars and notebook make it easier to log "
            "birds around the park. D23:1 This week is packed, so staying near "
            "home helps. A bird feeder outside the window would let him watch "
            "birds without going outdoors."
        ),
    )

    assert reason == "birdwatching_city_schedule_bridge"
    assert relevance.distinctive_term_hits >= 7


def test_best_query_relevance_bridges_inventory_and_brand_fact_evidence() -> None:
    gaming = build_query_expansion_plan("What mediums does Nate use to play games?")
    board_games = build_query_expansion_plan("What board games has Nate played?")
    pets = build_query_expansion_plan("What pets does Nate have?")
    pet_names = build_query_expansion_plan("What are Maria's dogs' names?")
    pet_owner = build_query_expansion_plan("Is Oscar Melanie's pet?")
    gear = build_query_expansion_plan(
        "Which outdoor gear company likely signed up John for an endorsement deal?"
    )

    _, gaming_reason, gaming_relevance = best_query_relevance(
        gaming,
        text="D27:15 Nate upgraded his gaming equipment, including PC and Playstation.",
    )
    _, pet_reason, pet_relevance = best_query_relevance(
        pets,
        text="D12:3 Nate got a new addition to the family, a dog named Max.",
    )
    _, pet_names_reason, pet_names_relevance = best_query_relevance(
        pet_names,
        text="D9:3 Maria's pets are two dogs; their names are Max and Coco.",
    )
    _, pet_owner_reason, pet_owner_relevance = best_query_relevance(
        pet_owner,
        text="D5:8 Oscar is Melanie's pet dog and he belongs to her family.",
    )
    _, board_game_reason, board_game_relevance = best_query_relevance(
        board_games,
        text=(
            "D4:8 Riley: We played this game Azul - it is a great strategy "
            "game for a tabletop night."
        ),
    )
    _, gear_reason, gear_relevance = best_query_relevance(
        gear,
        text=(
            "D3:15 John has Nike and Gatorade deals and has always liked "
            "Under Armour, so working with them would be cool."
        ),
    )

    assert gaming_reason == "gaming_medium_bridge"
    assert gaming_relevance.distinctive_term_hits >= 5
    assert board_game_reason == "board_game_inventory_bridge"
    assert board_game_relevance.distinctive_term_hits >= 5
    assert pet_reason == "pet_inventory_bridge"
    assert pet_relevance.distinctive_term_hits >= 5
    assert pet_names_reason == "pet_inventory_bridge"
    assert pet_names_relevance.distinctive_term_hits >= 6
    assert pet_owner_reason == "pet_inventory_bridge"
    assert pet_owner_relevance.distinctive_term_hits >= 6
    assert gear_reason == "endorsement_gear_brand_bridge"
    assert gear_relevance.distinctive_term_hits >= 6


def test_best_query_relevance_bridges_temporal_event_details() -> None:
    cases = (
        (
            build_query_expansion_plan("When did Caroline go to the LGBTQ support group?"),
            (
                "D1:3 Caroline went to the LGBTQ support group yesterday and "
                "heard powerful transgender stories."
            ),
            7,
        ),
        (
            build_query_expansion_plan("When did Caroline go to the adoption meeting?"),
            (
                "D8:9 Caroline went to a council meeting for adoption recently. "
                "It was inspiring and emotional."
            ),
            6,
        ),
        (
            build_query_expansion_plan("When did Jordan apply to adoption agencies?"),
            (
                "D4:1 Jordan took the first step toward becoming a parent and "
                "applied to adoption agencies yesterday."
            ),
            6,
        ),
        (
            build_query_expansion_plan("When did Caroline go to a pride parade?"),
            "D5:1 Caroline went to an LGBTQ pride parade last week and felt she belonged.",
            6,
        ),
        (
            build_query_expansion_plan("When did Caroline join a new activist group?"),
            "D10:3 Caroline joined a new LGBTQ activist group last Tues.",
            6,
        ),
        (
            build_query_expansion_plan("When did Maria start volunteering at the shelter?"),
            "D27:4 Maria started volunteering at the shelter about a year ago.",
            5,
        ),
        (
            build_query_expansion_plan("When did Gina interview for a design internship?"),
            "D11:14 Gina had an interview for a design internship yesterday.",
            5,
        ),
        (
            build_query_expansion_plan("When did John take a trip to the Rocky Mountains?"),
            "D20:40 John said this was his Rocky Mountains trip last year.",
            5,
        ),
        (
            build_query_expansion_plan("When did Melanie go camping in June?"),
            (
                "session_4 date: 10:37 am on 27 June, 2023. D4:8 Melanie "
                "went camping last week with her family, explored nature, "
                "roasted marshmallows around the campfire, and went on a hike."
            ),
            7,
        ),
        (
            build_query_expansion_plan("When did Melanie paint a sunrise?"),
            "D2:5 Melanie painted a sunrise over the lake yesterday.",
            6,
        ),
        (
            build_query_expansion_plan("When did Melanie run a charity race?"),
            "D6:2 Melanie ran the charity race last Saturday and raised awareness.",
            7,
        ),
        (
            build_query_expansion_plan("When did Caroline give a speech at a school?"),
            "D8:4 Caroline gave a speech at the school event last week.",
            6,
        ),
        (
            build_query_expansion_plan("When did Melanie sign up for a pottery class?"),
            "D9:3 Melanie signed up for a pottery class yesterday.",
            6,
        ),
        (
            build_query_expansion_plan(
                "When did Caroline meet up with her friends, family, and mentors?"
            ),
            "D3:13 Caroline met up with friends, family, and mentors last week.",
            6,
        ),
        (
            build_query_expansion_plan("When is Caroline going to the transgender conference?"),
            "D12:7 Caroline is going to the transgender conference this month.",
            5,
        ),
        (
            build_query_expansion_plan("When did Melanie go to the museum?"),
            (
                "D2:4 Melanie went to the museum with her kids yesterday to "
                "see the dinosaur exhibit."
            ),
            8,
        ),
        (
            build_query_expansion_plan("When did Caroline have a picnic?"),
            "D3:4 Caroline had a picnic at the park with friends last weekend.",
            6,
        ),
        (
            build_query_expansion_plan("When did Melanie go to the pottery workshop?"),
            (
                "D6:8 Melanie went to the pottery workshop on Tuesday and made "
                "clay plates."
            ),
            7,
        ),
        (
            build_query_expansion_plan("When did Caroline join a mentorship program?"),
            "D7:3 Caroline joined a youth mentorship program last month.",
            5,
        ),
        (
            build_query_expansion_plan(
                "When did Caroline and Melanie go to a pride fesetival together?"
            ),
            (
                "D8:2 Caroline and Melanie went to a Pride festival together "
                "last summer."
            ),
            6,
        ),
        (
            build_query_expansion_plan("When did Caroline draw a self-portrait?"),
            (
                "D9:1 Caroline drew a self portrait yesterday and shared the "
                "drawing."
            ),
            7,
        ),
        (
            build_query_expansion_plan("When did Caroline go biking with friends?"),
            "D10:6 Caroline went biking with friends on Saturday.",
            5,
        ),
        (
            build_query_expansion_plan("When did Melanie's friend adopt a child?"),
            "D11:2 Melanie's friend adopted a child last week.",
            7,
        ),
        (
            build_query_expansion_plan("When did Melanie get hurt?"),
            "D12:2 Melanie got hurt in an accident yesterday.",
            3,
        ),
        (
            build_query_expansion_plan("When did Caroline pass the adoption interview?"),
            "D13:2 Caroline passed the adoption interview last Friday.",
            8,
        ),
    )

    for plan, text, min_hits in cases:
        _, reason, relevance = best_query_relevance(plan, text=text)

        assert reason == "temporal_event_detail_bridge"
        assert relevance.distinctive_term_hits >= min_hits


def test_best_query_relevance_bridges_current_recommendations() -> None:
    plan = build_query_expansion_plan("Which provider should I use?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="Qdrant is the recommended current retrieval provider.",
    )

    assert reason == "current_recommendation_bridge"
    assert relevance.unique_term_hits >= 4


def test_best_query_relevance_bridges_final_current_decisions() -> None:
    final_plan = build_query_expansion_plan("What is the final Atlas decision?")
    source_plan = build_query_expansion_plan("What is the canonical source of truth for Atlas?")

    _, final_reason, final_relevance = best_query_relevance(
        final_plan,
        text="OpenAI is the canonical source of truth and selected active provider for Atlas.",
    )
    _, source_reason, source_relevance = best_query_relevance(
        source_plan,
        text="Atlas final decision: OpenAI is the selected current provider.",
    )

    assert final_reason == "current_state_temporal_bridge"
    assert final_relevance.distinctive_term_hits >= 6
    assert source_reason == "current_state_temporal_bridge"
    assert source_relevance.distinctive_term_hits >= 6


def test_best_query_relevance_bridges_stale_state_decisions() -> None:
    plan = build_query_expansion_plan("Which Atlas provider is no longer valid?")

    _, reason, relevance = best_query_relevance(
        plan,
        text=(
            "LocalAI is no longer valid because it is stale, outdated, "
            "previous, and not current after being superseded by OpenAI."
        ),
    )

    assert reason == "stale_state_temporal_bridge"
    assert relevance.distinctive_term_hits >= 5


def test_query_expansion_covers_direct_temporal_event_date_questions() -> None:
    birthday = build_query_expansion_plan("When is Melanie's daughter's birthday?")
    pride = build_query_expansion_plan("When did Caroline attend a pride parade in August?")
    conference = build_query_expansion_plan("When did Caroline go to the LGBTQ conference?")
    park = build_query_expansion_plan("When did Melanie go to the park?")
    sunrise = build_query_expansion_plan("When did Melanie paint a sunrise?")
    charity_race = build_query_expansion_plan("When did Melanie run a charity race?")
    school_speech = build_query_expansion_plan(
        "When did Caroline give a speech at a school?"
    )
    support_meetup = build_query_expansion_plan(
        "When did Caroline meet up with her friends, family, and mentors?"
    )
    transgender_conference = build_query_expansion_plan(
        "When is Caroline going to the transgender conference?"
    )
    pottery_class = build_query_expansion_plan(
        "When did Melanie sign up for a pottery class?"
    )
    store = build_query_expansion_plan("When did Gina open her online clothing store?")
    collaboration = build_query_expansion_plan(
        "When did Jon and Gina decide to collaborate to create dance content?"
    )
    museum = build_query_expansion_plan("When did Melanie go to the museum?")
    picnic = build_query_expansion_plan("When did Caroline have a picnic?")
    pottery_workshop = build_query_expansion_plan(
        "When did Melanie go to the pottery workshop?"
    )
    mentorship = build_query_expansion_plan(
        "When did Caroline join a mentorship program?"
    )
    pride_festival_typo = build_query_expansion_plan(
        "When did Caroline and Melanie go to a pride fesetival together?"
    )
    self_portrait = build_query_expansion_plan(
        "When did Caroline draw a self-portrait?"
    )

    birthday_query = _expansion_query(birthday, "age_birthday_bridge")
    pride_query = _expansion_query(pride, "temporal_event_detail_bridge")
    conference_query = _expansion_query(conference, "temporal_event_detail_bridge")
    park_query = _expansion_query(park, "temporal_event_detail_bridge")
    sunrise_query = _expansion_query(sunrise, "temporal_event_detail_bridge")
    charity_race_query = _expansion_query(charity_race, "temporal_event_detail_bridge")
    school_speech_query = _expansion_query(school_speech, "temporal_event_detail_bridge")
    support_meetup_query = _expansion_query(support_meetup, "temporal_event_detail_bridge")
    transgender_conference_query = _expansion_query(
        transgender_conference,
        "temporal_event_detail_bridge",
    )
    pottery_class_query = _expansion_query(pottery_class, "temporal_event_detail_bridge")
    store_query = _expansion_query(store, "temporal_event_detail_bridge")
    collaboration_query = _expansion_query(collaboration, "temporal_event_detail_bridge")
    museum_query = _expansion_query(museum, "temporal_event_detail_bridge")
    picnic_query = _expansion_query(picnic, "temporal_event_detail_bridge")
    pottery_workshop_query = _expansion_query(
        pottery_workshop,
        "temporal_event_detail_bridge",
    )
    mentorship_query = _expansion_query(mentorship, "temporal_event_detail_bridge")
    pride_festival_typo_query = _expansion_query(
        pride_festival_typo,
        "temporal_event_detail_bridge",
    )
    self_portrait_query = _expansion_query(
        self_portrait,
        "temporal_event_detail_bridge",
    )

    assert "daughter's birthday" in birthday_query
    assert "celebrated birthday" in birthday_query
    assert "when date" in pride_query
    assert "relative day week weekday" in pride_query
    assert "pride parade" in pride_query
    assert "LGBTQ conference" in conference_query
    assert "relative date recently days ago" in conference_query
    assert "park visit went took trip" in park_query
    assert "relative date day weekday" in park_query
    assert "painted painting sunrise" in sunrise_query
    assert "charity race run ran" in charity_race_query
    assert "school speech talk gave spoke" in school_speech_query
    assert "meet met meetup meeting friends family mentors" in support_meetup_query
    assert "transgender conference going attending upcoming" in transgender_conference_query
    assert "sign signed up pottery class" in pottery_class_query
    assert "online clothing store open" in store_query
    assert "is open" in store_query
    assert "decide decided collaborate collaboration" in collaboration_query
    assert "creative plan agreed together" in collaboration_query
    assert "dance routine moves" in collaboration_query
    assert "museum exhibit dinosaur" in museum_query
    assert "picnic park hiking" in picnic_query
    assert "pottery workshop class clay" in pottery_workshop_query
    assert "joined mentorship mentoring" in mentorship_query
    assert "Pride fest festival" in pride_festival_typo_query
    assert "self portrait identity art" in self_portrait_query


def test_best_query_relevance_bridges_current_decided_provider() -> None:
    plan = build_query_expansion_plan("What did I decide to use?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="Qdrant is the current retrieval provider I selected after switching tools.",
    )

    assert reason in {
        "current_recommendation_bridge",
        "decomposition_knowledge_update_current",
    }
    assert relevance.unique_term_hits >= 5


def test_query_expansion_does_not_treat_nickname_use_as_current_tool_choice() -> None:
    plan = build_query_expansion_plan("What nickname does Nate use for Joanna?")

    nickname = _expansion_query(plan, "nickname_bridge")

    assert nickname.startswith("Nate ")
    assert not nickname.startswith("Nate Joanna ")
    assert "greeting hey hi" in nickname
    assert "decomposition_knowledge_update_current" not in {
        item.reason for item in plan.retrieval_queries
    }


def test_best_query_relevance_bridges_nickname_greetings() -> None:
    plan = build_query_expansion_plan("What nickname does Nate use for Joanna?")

    _, reason, relevance = best_query_relevance(
        plan,
        text="D7:1 Nate: Hey Jo, guess what I did? Dyed my hair last week - come see!",
    )

    assert reason == "nickname_bridge"
    assert relevance.distinctive_term_hits >= 2


def test_keyword_chunk_score_separates_stronger_evidence_from_loose_match() -> None:
    query = "Melanie camping trip campfire meteor shower nature outdoors"
    strong = score_query_relevance(
        query=query,
        text=(
            "D10:12 D10:14 Melanie: Melanie's family tradition includes a "
            "camping trip where they roast marshmallows and tell stories around "
            "the campfire. Melanie and her family watched the Perseid meteor "
            "shower during a camping trip last year."
        ),
    )
    loose = score_query_relevance(
        query=query,
        text="D15:2 Melanie took her kids to a park and enjoyed seeing them outdoors.",
    )

    assert keyword_chunk_score(
        strong,
        query_expansion_reason="outdoor_preference_bridge",
    ) > keyword_chunk_score(
        loose,
        query_expansion_reason="outdoor_preference_bridge",
    )


def _expansion_query(plan: QueryExpansionPlan, reason: str) -> str:
    for expansion in plan.expansions:
        if expansion.reason == reason:
            return expansion.query
    raise AssertionError(f"missing expansion reason: {reason}")


def _expansion_index(plan: QueryExpansionPlan, reason: str) -> int:
    for index, expansion in enumerate(plan.expansions):
        if expansion.reason == reason:
            return index
    raise AssertionError(f"missing expansion reason: {reason}")

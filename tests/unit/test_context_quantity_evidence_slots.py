from infinity_context_core.application.context_quantity_evidence_slots import (
    extract_quantity_evidence_request,
    project_quantity_evidence_slots,
    quantity_evidence_retrieval_terms,
)

_QUERY = "How many items of clothing do I need to pick up or return from a store?"


def test_pending_clothing_request_is_question_derived_and_bounded() -> None:
    request = extract_quantity_evidence_request(_QUERY)

    assert request is not None
    assert request.target_terms == ("clothing",)
    assert request.action_terms == ("pickup", "return")
    assert quantity_evidence_retrieval_terms() == (
        "pick up",
        "collect",
        "return",
        "exchange",
        "clothing",
        "clothes",
        "garment",
        "apparel",
        "wardrobe",
        "store",
        "shop",
        "retailer",
    )
    pickup_only = extract_quantity_evidence_request(
        "How many items of clothing do I still need to pick up from a store?"
    )
    assert pickup_only is not None
    pickup_terms = quantity_evidence_retrieval_terms(
        target_terms=pickup_only.target_terms,
        action_terms=pickup_only.action_terms,
    )
    assert "pick up" in pickup_terms
    assert "return" not in pickup_terms
    assert "exchange" not in pickup_terms
    assert len(pickup_terms) == len(set(pickup_terms)) <= 24


def test_pending_clothing_projection_keeps_only_user_obligation_evidence() -> None:
    projection = project_quantity_evidence_slots(
        query=_QUERY,
        text=(
            "closet-session\n"
            "user: I need help organizing my closet. I still need to pick up my "
            "dry cleaning for the navy blue blazer I wore recently.\n"
            "assistant: Create a checklist and buy several storage boxes."
        ),
    )

    assert projection.present
    assert projection.identities == ("pickup:dry cleaning",)
    assert "closet-session" in projection.rendered_text
    assert "navy blue blazer" in projection.rendered_text
    assert "storage boxes" not in projection.rendered_text


def test_pending_clothing_projection_separates_pickup_and_return_actions() -> None:
    projection = project_quantity_evidence_slots(
        query=_QUERY,
        text=(
            "errand-session\n"
            "user: I need to return some boots to the store because they were too "
            "small, and I haven't had a chance to pick them up after the exchange."
        ),
    )

    assert projection.present
    assert projection.identities == ("pickup:boots", "return:boots")
    assert len(set(projection.member_ids)) == 2


def test_pending_clothing_projection_rejects_generic_closet_and_purchase_advice() -> None:
    generic = project_quantity_evidence_slots(
        query=_QUERY,
        text=(
            "user: I bought black jeans and a white shirt.\n"
            "assistant: Return unwanted purchases and pick up some storage bins."
        ),
    )

    assert generic.request_detected
    assert not generic.present
    assert generic.rendered_text == ""


def test_pending_clothing_projection_requires_my_unresolved_store_action() -> None:
    rejected = (
        "user: I need to ask when she will return my sweater to me.",
        "user: I still need to pick up my sweater from my sister.",
        "user: I already returned my boots to the store.",
        "user: I no longer need to return my coat to the shop.",
    )

    for text in rejected:
        projection = project_quantity_evidence_slots(query=_QUERY, text=text)
        assert projection.request_detected
        assert not projection.present


def test_pending_clothing_projection_preserves_modifier_and_quantity_multiplicity() -> None:
    colors = project_quantity_evidence_slots(
        query=_QUERY,
        text="user: I still need to return my red and blue shirts to the store.",
    )
    quantity = project_quantity_evidence_slots(
        query=_QUERY,
        text="user: I still need to pick up two hoodies from the shop.",
    )

    assert colors.identities == ("return:red shirt", "return:blue shirt")
    assert quantity.identities == ("pickup:hoodie#1", "pickup:hoodie#2")


def test_pending_clothing_projection_accepts_bounded_named_store_directions() -> None:
    to_store = project_quantity_evidence_slots(
        query=_QUERY,
        text="user: I still need to return my coat to Zara.",
    )
    from_store = project_quantity_evidence_slots(
        query=_QUERY,
        text="user: I still need to pick up my boots from Nordstrom Rack.",
    )

    assert to_store.identities == ("return:coat",)
    assert from_store.identities == ("pickup:boots",)


def test_pending_clothing_projection_resolves_adjacent_plural_anaphora() -> None:
    returns = project_quantity_evidence_slots(
        query=_QUERY,
        text=(
            "user: I ordered boots from Zara. "
            "I still need to return them."
        ),
    )
    pickup = project_quantity_evidence_slots(
        query=_QUERY,
        text=(
            "user: My shoes were delivered to Nordstrom Rack. "
            "I still need to pick those up."
        ),
    )
    collects = project_quantity_evidence_slots(
        query=_QUERY,
        text=(
            "user: My shirts are waiting at the store. "
            "I still need to collect these."
        ),
    )

    assert returns.identities == ("return:boots",)
    assert returns.evidence_sentences == (
        "I ordered boots from Zara.",
        "I still need to return them.",
    )
    assert pickup.identities == ("pickup:shoes",)
    assert collects.identities == ("pickup:shirt",)


def test_pending_clothing_anaphora_fails_closed_outside_adjacent_user_context() -> None:
    rejected = (
        (
            "user: I ordered boots from Zara.\n"
            "assistant: Keep the receipt.\n"
            "user: I still need to return them."
        ),
        (
            "user: I ordered boots from Zara. The receipt is in my bag. "
            "I still need to return them."
        ),
        (
            "user: I ordered boots from Zara.\n"
            "user: I still need to return them."
        ),
    )

    for text in rejected:
        projection = project_quantity_evidence_slots(query=_QUERY, text=text)
        assert projection.request_detected
        assert not projection.present


def test_pending_clothing_anaphora_fails_closed_on_unsafe_resolution() -> None:
    rejected = (
        "user: I ordered boots and shirts from Zara. I still need to return them.",
        "user: I ordered boots from Zara. I no longer need to return them.",
        (
            "user: I ordered boots from Zara. "
            "I still need to return them, but I already returned them."
        ),
        "user: I ordered boots from Zara. I need my sister to return them.",
        "user: I ordered two shirts from Zara. I still need to return them.",
        (
            "user: I ordered boots from Zara. "
            "I still need to return them after picking up my coat."
        ),
    )

    for text in rejected:
        projection = project_quantity_evidence_slots(query=_QUERY, text=text)
        assert projection.request_detected
        assert not projection.present


def test_pending_clothing_request_rejects_named_subject_contract() -> None:
    assert (
        extract_quantity_evidence_request(
            "How many clothes does Morgan need to return to the store?"
        )
        is None
    )


def test_other_quantity_queries_do_not_activate_pending_clothing_policy() -> None:
    assert extract_quantity_evidence_request("How many projects have I led?") is None
    assert (
        extract_quantity_evidence_request(
            "How many clothes have I bought during the past year?"
        )
        is None
    )


def test_total_money_projection_dedupes_repeated_expense_and_keeps_sources() -> None:
    query = (
        "How much total money have I spent on bike-related expenses "
        "since the start of the year?"
    )
    first = project_quantity_evidence_slots(
        query=query,
        text=(
            "bike-service\n"
            "user: I took my bike in for a tune-up. I needed to replace the chain, "
            "which I did, and it cost me $25. I also got a new set of bike lights "
            "installed, which were $40."
        ),
    )
    repeated = project_quantity_evidence_slots(
        query=query,
        text=(
            "bike-safety\n"
            "user: Speaking of my bike, I recently got a new set of bike lights "
            "installed, which were $40."
        ),
    )

    assert first.present
    assert len(first.member_ids) == 2
    assert repeated.present
    assert first.member_ids[1] == repeated.member_ids[0]
    assert "$25" in first.rendered_text
    assert "$40" in first.rendered_text


def test_total_money_projection_rejects_future_and_assistant_prices() -> None:
    query = (
        "How much total money have I spent on bike-related expenses "
        "since the start of the year?"
    )
    projection = project_quantity_evidence_slots(
        query=query,
        text=(
            "user: I am planning to buy a bike rack for $200 next week.\n"
            "assistant: You could buy a helmet for $120."
        ),
    )

    assert projection.request_detected
    assert not projection.present


def test_total_activity_duration_projection_keeps_each_game_session() -> None:
    query = "How many hours have I spent playing games in total?"
    odyssey = project_quantity_evidence_slots(
        query=query,
        text=(
            "game-session-one\n"
            "user: I spent around 70 hours playing Assassin's Creed Odyssey."
        ),
    )
    celeste = project_quantity_evidence_slots(
        query=query,
        text=(
            "game-session-two\n"
            "user: Can you recommend games similar to Celeste, which took me "
            "10 hours to complete?"
        ),
    )

    assert odyssey.present
    assert celeste.present
    assert len(odyssey.member_ids) == 1
    assert len(celeste.member_ids) == 1
    assert odyssey.member_ids != celeste.member_ids
    assert "70 hours" in odyssey.rendered_text
    assert "10 hours" in celeste.rendered_text


def test_total_trip_duration_projection_keeps_camping_days_and_rejects_non_camping() -> None:
    query = "How many days did I spend on camping trips in the United States this year?"

    request = extract_quantity_evidence_request(query)
    assert request is not None
    assert request.target_terms == ("camping", "trip")
    assert quantity_evidence_retrieval_terms(
        target_terms=request.target_terms,
        action_terms=request.action_terms,
    ) == (
        "camping",
        "trip",
        "spent",
        "hours",
        "days",
        "played",
        "completed",
        "finished",
        "took",
    )

    yellowstone = project_quantity_evidence_slots(
        query=query,
        text=(
            "answer_a8b4290f_1 date: 2023/04/29\n"
            "user: We had an amazing 5-day camping trip to Yellowstone National "
            "Park last month."
        ),
    )
    big_sur = project_quantity_evidence_slots(
        query=query,
        text=(
            "answer_a8b4290f_2 date: 2023/04/29\n"
            "user: I took a 3-day solo camping trip to Big Sur in early April."
        ),
    )
    road_trip = project_quantity_evidence_slots(
        query=query,
        text=(
            "answer_a8b4290f_3 date: 2023/04/29\n"
            "user: We had a 7-day family road trip in Utah, but not camping "
            "for this time."
        ),
    )

    assert yellowstone.present
    assert big_sur.present
    assert road_trip.present
    assert road_trip.identities[0].startswith("excluded:day:7")
    assert "5-day camping trip" in yellowstone.rendered_text
    assert "3-day solo camping trip" in big_sur.rendered_text
    assert "not camping" in road_trip.rendered_text


def test_project_leadership_projection_keeps_current_led_and_related_exclusions() -> None:
    query = "How many projects have I led or am currently leading?"

    request = extract_quantity_evidence_request(query)
    assert request is not None
    assert request.target_terms == ("project",)
    assert quantity_evidence_retrieval_terms(
        target_terms=request.target_terms,
        action_terms=request.action_terms,
    ) == (
        "project",
        "projects",
        "led",
        "leading",
        "currently",
        "working on",
        "solo project",
        "research",
        "poster",
        "case competition",
        "presentation",
    )

    led = project_quantity_evidence_slots(
        query=query,
        text=(
            "answer_ec904b3c_1 date: 2023/05/21\n"
            "user: I'm working on a project that involves analyzing customer data. "
            "I've had experience from my Marketing Research class project, where "
            "I led the data analysis team."
        ),
    )
    competition = project_quantity_evidence_slots(
        query=query,
        text=(
            "answer_ec904b3c_4 date: 2023/05/24\n"
            "user: I recently participated in a case competition hosted by a "
            "consulting firm, where we had to analyze a business case."
        ),
    )
    poster = project_quantity_evidence_slots(
        query=query,
        text=(
            "answer_ec904b3c_3 date: 2023/05/25\n"
            "user: I recently presented a poster on my research on the effects "
            "of social media influencers at an academic conference."
        ),
    )
    current = project_quantity_evidence_slots(
        query=query,
        text=(
            "answer_ec904b3c_2 date: 2023/05/29\n"
            "user: I've been working on a solo project for my Data Mining class "
            "using customer purchase data."
        ),
    )

    assert "led:marketing-research-class-project" in led.identities
    assert "current:customer-data-project" in led.identities
    assert competition.identities == ("excluded:case-competition",)
    assert poster.identities == ("excluded:research-poster",)
    assert current.identities == ("current:solo-project",)


def test_baking_event_projection_keeps_distinct_recent_baking_events() -> None:
    query = "How many times did I bake something in the past two weeks?"

    request = extract_quantity_evidence_request(query)
    assert request is not None
    assert request.target_terms == ("baking",)
    assert quantity_evidence_retrieval_terms(
        target_terms=request.target_terms,
        action_terms=request.action_terms,
    ) == (
        "baked",
        "baking",
        "bake",
        "recipe",
        "bread",
        "cake",
        "cookies",
        "baguette",
        "sourdough",
        "oven",
        "convection",
    )

    sourdough = project_quantity_evidence_slots(
        query=query,
        text=(
            "answer_733e443a_3 date: 2023/05/21\n"
            "user: I tried out a new bread recipe using sourdough starter on "
            "Tuesday. I recently baked a chocolate cake for my sister's "
            "birthday party using a new recipe."
        ),
    )
    baguette = project_quantity_evidence_slots(
        query=query,
        text=(
            "answer_733e443a_4 date: 2023/05/24\n"
            "user: I made a delicious whole wheat baguette last Saturday. "
            "I used my oven's convection setting to bake a batch of cookies "
            "last Thursday."
        ),
    )

    assert sourdough.present
    assert {"baked:sourdough bread", "baked:chocolate cake"}.issubset(
        set(sourdough.identities)
    )
    assert baguette.present
    assert {"baked:whole wheat baguette", "baked:batch of cookies"}.issubset(
        set(baguette.identities)
    )


def test_short_story_progress_projection_keeps_baseline_and_latest_counts() -> None:
    query = "How many short stories have I written since I started writing regularly?"

    request = extract_quantity_evidence_request(query)
    assert request is not None
    assert request.target_terms == ("short", "story")
    assert quantity_evidence_retrieval_terms(
        target_terms=request.target_terms,
        action_terms=request.action_terms,
    ) == (
        "short stories",
        "short story",
        "writing regularly",
        "written",
        "wrote",
        "complete",
        "completed",
        "finished",
        "started writing",
    )

    baseline = project_quantity_evidence_slots(
        query=query,
        text=(
            "answer_0eb23770_1 date: 2023/05/23\n"
            "user: I've written four so far since I started writing regularly, "
            "and I'm hoping to keep the momentum going with short stories."
        ),
    )
    latest = project_quantity_evidence_slots(
        query=query,
        text=(
            "answer_0eb23770_2 date: 2023/05/30\n"
            "user: I've been writing regularly for three months now, and it's "
            "been amazing - I've even managed to complete 7 short stories since "
            "I started."
        ),
    )

    assert baseline.present
    assert latest.present
    assert baseline.identities == ("short_story_progress_count:4",)
    assert latest.identities == ("short_story_progress_count:7",)
    assert "four so far" in baseline.rendered_text
    assert "complete 7 short stories" in latest.rendered_text


def test_baby_birth_projection_keeps_named_newborns_and_rejects_adoptions() -> None:
    query = "How many babies were born to friends and family members in the last few months?"
    request = extract_quantity_evidence_request(query)

    assert request is not None
    assert request.target_terms == ("baby",)
    assert request.action_terms == ("baby_birth",)
    assert "twins" in quantity_evidence_retrieval_terms(
        target_terms=request.target_terms,
        action_terms=request.action_terms,
    )

    projection = project_quantity_evidence_slots(
        query=query,
        text=(
            "baby-session\n"
            "user: I'm planning a baby gift for my aunt's twins, Ava and Lily, "
            "who were born in April. My colleague Sarah recently adopted a "
            "child named Aaliyah, and my neighbor adopted a dog named Rocky."
        ),
    )

    assert projection.present
    assert projection.identities == ("born:ava", "born:lily")
    assert "Ava and Lily" in projection.rendered_text
    assert "Aaliyah" not in projection.rendered_text
    assert "Rocky" not in projection.rendered_text

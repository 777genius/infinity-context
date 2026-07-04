from datetime import UTC, datetime

from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_source_sibling_place_evidence import (
    country_destination_answer_support_rank,
)
from infinity_context_core.application.context_source_siblings import (
    is_precise_source_sibling_turn,
    source_group_seed_turns,
    source_sibling_answer_evidence,
    source_sibling_answer_evidence_role_rank,
    source_sibling_candidate_limit,
    source_sibling_distant_answer_evidence_rank,
    source_sibling_max_candidate_limit,
    source_sibling_relevance_allowed,
    source_sibling_score_cap,
)
from infinity_context_core.application.use_cases.build_context import (
    _prioritize_source_sibling_answer_evidence_seed_chunks,
    _query_plan_requests_named_preference_source_sibling_diversity,
    _query_plan_requests_place_source_sibling_diversity,
    _query_plan_requests_relationship_status_source_sibling_diversity,
    _source_sibling_answer_evidence_extra_key,
    _source_sibling_answer_evidence_query_match,
    _source_sibling_group_backfill_plan,
    _source_sibling_group_limit_for_request,
)
from infinity_context_core.domain.entities import (
    LifecycleStatus,
    MemoryChunk,
    MemoryChunkKind,
)


def test_country_destination_rank_prefers_matching_month_year_destination() -> None:
    query = "Which country was Avery visiting in May 2023?"
    may_trip = (
        "session_2 date: 7:11 pm on 24 May, 2023\n"
        "D2:1 Avery: I took my family on a road trip to Vancouver."
    )
    august_trip = (
        "session_5 date: 7:52 pm on 7 August, 2023\n"
        "D5:1 Avery: Last week I went on a trip to Canada."
    )

    assert country_destination_answer_support_rank(
        expansion_query=query,
        text=may_trip,
        has_exact_turn=True,
    ) < country_destination_answer_support_rank(
        expansion_query=query,
        text=august_trip,
        has_exact_turn=True,
    )


def test_source_sibling_answer_evidence_accepts_generic_list_slot_match() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="What music events has John attended?",
        expansion_reason="music_event_inventory_bridge",
        text=(
            "D20:4: Maria: Last week, we had a blast at a live music event. "
            "Seeing them enjoy the songs made the night special."
        ),
    )


def test_source_sibling_answer_evidence_accepts_relationship_status_turns() -> None:
    expansion_query = (
        "Avery relationship status single parent partner spouse married dating "
        "breakup friends family"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="decomposition_relationship_status",
        text=(
            "session_4 turn D4:5\n"
            "D4:5 Avery: My husband and I used to play games together after work."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="relationship_status_bridge",
        text=(
            "session_9 turn D9:3\n"
            "D9:3 Avery: This is my husband in front of my parents' old house.\n"
            "image caption: a photo of a person standing by a house"
        ),
    )
    assert source_sibling_answer_evidence_role_rank(
        query_text=expansion_query,
        expansion_reason="decomposition_relationship_status",
        text="D10:4 Avery: The beach where I got married still means a lot to me.",
    ) == 0
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="decomposition_relationship_status",
        text="D7:2 Avery: Morgan is my project partner for the lab assignment.",
    )


def test_source_sibling_answer_evidence_accepts_lifestyle_inference_turns() -> None:
    assert source_sibling_answer_evidence(
        expansion_query=(
            "What can Alex do to improve his stress and accommodate his "
            "living situation with his dogs?"
        ),
        expansion_reason="original_query",
        text=(
            "D8:5 Alex: It's hard to find open spaces in the city. I used to "
            "hike a lot, but it is harder now with my work-life balance."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=(
            "What indoor activity would Alex enjoy doing while making his dog happy?"
        ),
        expansion_reason="original_query",
        text=(
            "D5:1 Alex: Meet my new puppy. He is a bundle of joy and I "
            "couldn't resist taking him home, city living and all."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=(
            "What can Alex do to improve his stress and accommodate his "
            "living situation with his dogs?"
        ),
        expansion_reason="original_query",
        text="D9:4 Alex: The dogs loved their new beds.",
    )


def test_source_sibling_answer_evidence_scans_relationship_decomposition() -> None:
    plan = build_query_expansion_plan("Is Avery married?")
    text = (
        "session_19 turn D19:11\n"
        "D19:11 Avery: Reminds me of when I used to play games with my husband. "
        "We took turns and made great memories together."
    )

    match = _source_sibling_answer_evidence_query_match(
        query_plan=plan,
        text=text,
        preferred_query=plan.original_query,
        preferred_reason="original_query",
    )

    assert match is not None
    assert match[1] == "decomposition_relationship_status"


def test_relationship_status_query_requests_source_sibling_diversity() -> None:
    plan = build_query_expansion_plan("Is Avery married?")

    assert _query_plan_requests_relationship_status_source_sibling_diversity(
        query_text="Is Avery married?",
        query_plan=plan,
    )


def test_source_sibling_answer_evidence_accepts_named_board_game_turns() -> None:
    expansion_query = (
        "Nate board game board games tabletop strategy game card game gaming party "
        "game convention played plays playing named called"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="board_game_inventory_bridge",
        text=(
            "session_4 turn D4:7\nsession_4 date: 10:58 am on 9 October, 2022\n"
            "D4:7 Nate: We played this game Azul - it's a great strategy game."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="board_game_inventory_bridge",
        text=(
            "session_2 turn D2:3\nsession_2 date: 10:55 am on 24 June, 2022\n"
            "D2:3 Nate: The gaming party was a success. We played some "
            "Carcassonne afterward just for fun."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="board_game_inventory_bridge",
        text=(
            "session_4 turn D4:1\nsession_4 date: 10:58 am on 9 October, 2022\n"
            "D4:1 Nate: I went to a game convention and met new people."
        ),
    )


def test_source_sibling_answer_evidence_accepts_sponsorship_partner_fit_turns() -> None:
    expansion_query = (
        "Jordan charity organization sponsorship brand endorsement athletic partner "
        "company basketball shoe gear deal work with prominent make difference"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="charity_brand_sponsorship_bridge",
        text=(
            "session_3 turn D3:13\n"
            "D3:13 Jordan signed up TrailCore for a basketball shoe and gear "
            "deal and is in talks with HydraFuel about sponsorship."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="charity_brand_sponsorship_bridge",
        text=(
            "session_3 turn D3:15\n"
            "D3:15 Jordan has always liked SummitGear, and working with them "
            "would be really cool."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="charity_brand_sponsorship_bridge",
        text="D3:16 Jordan mentioned that practice went well after lunch.",
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="charity_brand_sponsorship_bridge",
        text="D4:7 visual query: basketball signed by favorite basketball player.",
    )


def test_source_sibling_answer_evidence_accepts_travel_hobby_writing_facets() -> None:
    query = (
        "Avery travel dreams hobby creative writing articles stories blog "
        "destinations places visit"
    )

    assert source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason="travel_hobby_writing_bridge",
        text=(
            "D4:1 Avery: I am writing articles about fantasy novels for an "
            "online magazine. It is so rewarding."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason="travel_hobby_writing_bridge",
        text=(
            "D8:6 Avery: I have been writing more articles because it lets "
            "me combine my love for reading with sharing great stories."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason="travel_hobby_writing_bridge",
        text=(
            "D12:3 Avery: I love traveling too. Have you been to Paris? "
            "The tower there looks incredible."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason="travel_hobby_writing_bridge",
        text="D12:4 Avery: Jordan visited Paris last summer and sent a postcard.",
    )


def test_source_sibling_answer_evidence_accepts_place_inference_turns() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="In what country was Riley during summer 2022?",
        expansion_reason="travel_country_inventory_bridge",
        text=(
            "session_4 turn D4:33\n"
            "D4:33 Riley: Here's a picture I took on vacation last summer "
            "in Cartagena. The sunset over the water was beautiful.\n"
            "image caption: a photo of a person walking on the beach"
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="What European countries has Riley visited?",
        expansion_reason="travel_country_inventory_bridge",
        text="D8:15 Riley: I took a trip to England and loved the castles.",
    )
    assert not source_sibling_answer_evidence(
        expansion_query="What European countries has Riley visited?",
        expansion_reason="travel_country_inventory_bridge",
        text="D18:3 Riley: I went on a road trip to Oregon and saw a canyon.",
    )
    assert source_sibling_answer_evidence(
        expansion_query="Which US state did Riley visit during her internship?",
        expansion_reason="trip_destination_bridge",
        text=(
            "session_13 turn D13:15\n"
            "D13:15 Riley: Here's an example of how I spent yesterday "
            "morning, yoga on top of Mount Aurora.\n"
            "image caption: a photo of a person standing on a rock"
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="Which national park could Riley and Dana be referring to?",
        expansion_reason="national_park_inference_bridge",
        text=(
            "session_11 turn D11:9\n"
            "D11:9 Dana: Let's get planning for next month. Here's the map "
            "for the trail.\n"
            "image caption: a photo of a map of a park with a lot of trees\n"
            "visual query: hiking trails map perfect spot"
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="Which country do Calvin and Dave want to meet in?",
        expansion_reason="decomposition_country_destination",
        text=(
            "session_3 turn D3:10\n"
            "D3:10 Dave: I can't wait for your trip to Boston. I'll show "
            "you around town and all the cool spots."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="Which country was Avery visiting in May 2023?",
        expansion_reason="decomposition_country_destination",
        text=(
            "session_2 turn D2:1\n"
            "D2:1 Avery: Last weekend, I took my family on a road trip to "
            "Vancouver. We drove through mountain roads and stayed in a "
            "cozy cabin."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="Which country was Avery visiting in May 2023?",
        expansion_reason="decomposition_country_destination",
        text=(
            "session_2 events\n"
            "D2:1 Avery goes on a roadtrip to Vancouver with family and "
            "drives through mountain roads."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query="Which country do Calvin and Dave want to meet in?",
        expansion_reason="decomposition_country_destination",
        text=(
            "session_27 turn D27:1\n"
            "D27:1 Calvin: I went to a networking event to meet more "
            "artists and build up my fan base."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query="Which country do Calvin and Dave want to meet in?",
        expansion_reason="decomposition_country_destination",
        text=(
            "session_7 observations\n"
            "D7:1 Calvin: Calvin recently toured with Frank Ocean and had "
            "an amazing experience performing live in Tokyo."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query="In what country was Riley during summer 2022?",
        expansion_reason="travel_country_inventory_bridge",
        text="D4:35 Riley: I enjoyed a quiet yoga session at home last summer.",
    )


def test_source_sibling_answer_evidence_accepts_public_office_motivation_turn() -> None:
    expansion_query = (
        "John decide run office again campaign public office politics impact "
        "community positive changes better future"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="public_office_service_bridge",
        text=(
            "session_7 turn D7:4\n"
            "D7:4 John: After my last run, I saw the impact I could make in "
            "the community through politics. It's rewarding to work towards "
            "positive changes and a better future."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="public_office_service_bridge",
        text=(
            "session_7 turn D7:2\n"
            "D7:2 John: I'm running for office again. It's been a wild ride, "
            "but I'm more excited than ever."
        ),
    )


def test_source_sibling_answer_evidence_accepts_recognition_award_turn() -> None:
    expansion_query = (
        "John recognition award medal certificate received homeless shelter "
        "volunteer helped"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="recognition_award_bridge",
        text=(
            "session_29 turn D29:1\n"
            "D29:1 Maria: Hey John, I volunteered at the homeless shelter and "
            "they gave me a medal! It was humbling and I'm glad I could help."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="recognition_award_bridge",
        text=(
            "session_16 turn D16:2\n"
            "D16:2 Maria: I'm busy at the shelter getting ready for a fundraiser."
        ),
    )


def test_source_sibling_answer_evidence_accepts_visual_certificate_completion_turn() -> None:
    expansion_query = (
        "Maria recognition award medal certificate completion completed diploma degree"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="recognition_award_bridge",
        text=(
            "session_9 turn D9:2\n"
            "D9:2 John: Hey Maria! Since we spoke last, I've had quite the adventure.\n"
            "image caption: a photo of a certificate of completion of a university degree\n"
            "visual query: diploma university"
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="recognition_award_bridge",
        text=(
            "session_9 turn D9:4\n"
            "D9:4 John: Thanks, Maria! It was quite a journey, but definitely "
            "worth it. I graduated last week!"
        ),
    )


def test_source_sibling_answer_evidence_accepts_pet_adjustment_turn() -> None:
    expansion_query = (
        "John new puppy adjusting home puppy dog little one learning commands "
        "house training"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="pet_adjustment_bridge",
        text=(
            "session_31 turn D31:10\n"
            "D31:10 Maria: Awesome, John! The little one is doing great - "
            "learning commands and house training.\n"
            "image caption: a photo of a man standing next to a dog"
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="pet_adjustment_bridge",
        text=(
            "session_31 turn D31:2\n"
            "D31:2 Maria: I just adopted this cute pup from a shelter last week."
        ),
    )


def test_source_sibling_answer_evidence_accepts_planning_tool_use_turn() -> None:
    expansion_query = (
        "Jon clipboard notepad notebook calendar use stay organized motivated "
        "sets goals tracks achievements areas improve"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="planning_tool_use_bridge",
        text=(
            "session_13 turn D13:11\n"
            "D13:11 Jon: I'm using it to stay organized and motivated. It sets "
            "goals, tracks my achievements and helps me find areas to improve.\n"
            "image caption: a photo of a notebook with a calendar on it"
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="planning_tool_use_bridge",
        text=(
            "session_16 turn D16:9\n"
            "D16:9 Gina: No worries, Jon! You got this!\n"
            "image caption: a photo of a notepad with a pen on it"
        ),
    )


def test_source_sibling_answer_evidence_accepts_customer_experience_turn() -> None:
    expansion_query = (
        "Jon creating special experience customers feel welcome coming back "
        "customer experience"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="customer_experience_bridge",
        text=(
            "session_3 turn D3:9\n"
            "D3:9 Jon: Creating a special experience for customers is the key "
            "to making them feel welcome and coming back."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="customer_experience_bridge",
        text=(
            "session_3 turn D3:10\n"
            "D3:10 Gina: I can make a special shopping experience for my customers."
        ),
    )


def test_source_sibling_answer_evidence_accepts_grand_opening_support_turn() -> None:
    expansion_query = (
        "Gina Jon grand opening dance studio tomorrow right by your side live it up"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="grand_opening_support_bridge",
        text=(
            "session_15 turn D15:12\n"
            "D15:12 Gina: I'll be right by your side, Jon. Let's live it up "
            "and make some great memories tomorrow. So excited!\n"
            "image caption: a photo of a group of people in a dance studio"
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="grand_opening_support_bridge",
        text=(
            "session_15 turn D15:13\n"
            "D15:13 Jon: Yeah! Let's make some awesome memories tomorrow at "
            "the grand opening!"
        ),
    )


def test_source_sibling_answer_evidence_accepts_book_reading_inventory_variants() -> None:
    expansion_query = (
        "What books has Tim read? books read reading loved novel title book "
        "book collection book series"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="book_reading_list_bridge",
        text=(
            "session_22 turn D22:13\n"
            'D22:13 Tim: Just finished "A Dance with Stars" and it was great.'
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="book_reading_list_bridge",
        text=(
            "session_26 turn D26:36\n"
            'D26:36 Tim: The new show is based on a book series that I love.'
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="book_reading_list_bridge",
        text="D2:7 Tim: This is my book collection so far.",
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="book_reading_list_bridge",
        text=(
            "D1:14 Tim: I talked to my friend who is a fan of The Wizarding "
            "School and we got lost in that magical world."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="book_reading_list_bridge",
        text=(
            'D6:8 Tim: "The River Name" is great. It is a fantasy novel with '
            "strong world-building and is definitely worth a read."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="book_reading_list_bridge",
        text='D11:26 Tim: I saw "The Alchemist" on there, one of my favorites.',
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="book_reading_list_bridge",
        text=(
            "D4:7 Tim: For sure! The River School and Moon Garden are amazing - "
            "I'm totally hooked! I could chat about them forever!"
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=(
            "Would Tim pursue writing as a career option? reading books guide "
            "motivate journey discover"
        ),
        expansion_reason="creative_writing_career_bridge",
        text=(
            "D7:9 Tim: Books guide me, motivate me and help me discover who I am. "
            "They're a huge part of my journey and remind me to keep going."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="book_reading_list_bridge",
        text="D14:21 John: Are you currently reading any books?",
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="book_reading_list_bridge",
        text="D7:4 Tim: Last month at that event was one of my favorites.",
    )


def test_source_sibling_answer_evidence_accepts_authored_count_ordinal_turn() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="How many screenplays has Dana written?",
        expansion_reason="screenplay_count_bridge",
        text=(
            "session_8 turn D8:3\n"
            "D8:3 Morgan: Wow Dana, is that your third one?"
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query="How many screenplays has Dana written?",
        expansion_reason="screenplay_count_bridge",
        text=(
            "session_8 turn D8:5\n"
            "D8:5 Dana: Someone wrote after reading my blog post about loss."
        ),
    )


def test_source_sibling_answer_evidence_accepts_dessert_recipe_slots() -> None:
    assert source_sibling_answer_evidence(
        expansion_query=(
            "Joanna Nate hobbies interests writing reading watching movies exploring "
            "nature desserts recipes baking shared both similar"
        ),
        expansion_reason="hobby_interest_bridge",
        text=(
            "session_10 turn D10:9\nsession_10 date: 11:54 am on 2 May, 2022\n"
            "D10:9 Joanna: Been working on projects and testing out "
            "dairy-free dessert recipes for friends and family."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=(
            "Joanna Nate hobbies interests writing reading watching movies exploring "
            "nature desserts recipes baking shared both similar"
        ),
        expansion_reason="hobby_interest_bridge",
        text=(
            "session_22 summary\nJoanna and Nate shared updates on interests. "
            "Joanna talked about dessert recipes and Nate mentioned baking."
        ),
    )


def test_source_sibling_answer_evidence_accepts_common_interest_movie_turn() -> None:
    assert source_sibling_answer_evidence(
        expansion_query=(
            "Joanna Nate hobbies interests writing reading watching movies "
            "exploring nature desserts recipes baking shared both similar"
        ),
        expansion_reason="hobby_interest_bridge",
        text=(
            "session_1 turn D1:10\nsession_1 date: 7:31 pm on 21 January, 2022\n"
            "D1:10 Joanna: Besides writing, I also enjoy reading, "
            "watching movies, and exploring nature."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=(
            "Joanna Nate hobbies interests writing reading watching movies "
            "exploring nature desserts recipes baking shared both similar"
        ),
        expansion_reason="hobby_interest_bridge",
        text=(
            "session_1 summary\nJoanna and Nate discussed similar interests, "
            "including watching movies."
        ),
    )


def test_source_sibling_answer_evidence_accepts_collectible_object_turns() -> None:
    expansion_query = (
        "Avery Jordan similar sports collectible own collection memorabilia "
        "keepsake possession signed autographed reminder bond friendship appreciation"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="decomposition_collectible_object",
        text=(
            "session_7 turn D7:9\n"
            "D7:9 Jordan: Thanks! They signed it to show our friendship "
            "and appreciation. It's a great reminder of our bond."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="decomposition_collectible_object",
        text=(
            "session_16 turn D16:7\n"
            "D16:7 Avery: I have a prized possession too - a basketball "
            "signed by my favorite player."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="decomposition_collectible_object",
        text="D3:7 Jordan: Being surrounded by teammates creates a strong bond.",
    )


def test_source_sibling_answer_evidence_accepts_common_animal_affinity_turns() -> None:
    expansion_query = (
        "Nate Joanna common shared both mutual same interests animals pets "
        "turtles reptiles animal affinity companion calming strength "
        "perseverance inspire inspiring motivate motivation"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="commonality_interest_bridge",
        text=(
            "session_5 turn D5:6\nsession_5 date: 5:08 pm on 4 March, 2022\n"
            "D5:6 Nate: I'm drawn to turtles. They're unique and their slow "
            "pace is a nice change from the rush of life. They're also "
            "low-maintenance and calming."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="commonality_interest_bridge",
        text=(
            "session_26 turn D26:9\nsession_26 date: 9:28 am on 4 August, 2022\n"
            "D26:9 Joanna: Thanks, Nate! They make me think of strength and "
            "perseverance. They help motivate me in tough times - glad you "
            "find that inspiring!"
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="commonality_interest_bridge",
        text=(
            "session_26 conversation\n"
            "D26:8 Nate: The story was about a turtle! Their resilience is so "
            "inspiring. Take courage and keep pushing yourself.\n"
            "D26:9 Joanna: Thanks, Nate! They make me think of strength and "
            "perseverance. They help motivate me in tough times - glad you "
            "find that inspiring!"
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="commonality_interest_bridge",
        text=(
            "session_26 turn D26:6\nsession_26 date: 9:28 am on 4 August, 2022\n"
            "D26:6 Nate: You must love seeing how you've grown as an artist."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="commonality_interest_bridge",
        text=(
            "session_12 conversation\n"
            "D12:9 Nate: It is nice seeing the joy pets bring to others.\n"
            "D12:10 Joanna: Writing projects get me through tough times."
        ),
    )


def test_source_sibling_answer_evidence_accepts_watched_movie_title_turn() -> None:
    expansion_query = (
        "Sam Dana movies both seen watched saw recently recommendation "
        "recommended movie film acting story captivating"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="commonality_interest_bridge",
        text=(
            "session_12 turn D12:8\nsession_12 date: 11:15 am on 6 October, 2022\n"
            "D12:8 Sam: I watched \"Moon Garden\" recently, and it was great! "
            "The acting was awesome and the story was captivating."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="commonality_interest_bridge",
        text=(
            "session_12 turn D12:7\nsession_12 date: 11:15 am on 6 October, 2022\n"
            "D12:7 Dana: Have you watched any good movies recently?"
        ),
    )


def test_source_sibling_answer_evidence_accepts_common_interest_slot_with_short_query() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="Nate share",
        expansion_reason="decomposition_clause",
        text=(
            "session_3 turn D3:4\nsession_3 date: 8:10 pm on 6 February, 2022\n"
            "D3:4 Nate: I discovered that I can make coconut milk icecream."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="Joanna Nate share",
        expansion_reason="hobby_interest_bridge",
        text=(
            "session_20 turn D20:2\nsession_20 date: 10:04 am on 3 June, 2022\n"
            "D20:2 Joanna: I revised one of my old recipes and made a cake."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query="Nate share",
        expansion_reason="decomposition_clause",
        text=(
            "session_3 summary\nNate talked about coconut milk icecream and "
            "other desserts."
        ),
    )


def test_source_sibling_answer_evidence_accepts_church_friend_activity_wording() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="What activities has Riley done with church friends?",
        expansion_reason="church_friend_activity_inventory_bridge",
        text=(
            "D4:2 Riley: Last weekend I had a picnic with friends from church. "
            "We played games and ate outside."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="What activities has Riley done with church friends?",
        expansion_reason="church_friend_activity_inventory_bridge",
        text=(
            "D6:8 Riley: Yesterday I took up community work with my friends "
            "from church. It was super rewarding."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query="What activities has Riley done with church friends?",
        expansion_reason="church_friend_activity_inventory_bridge",
        text="D7:1 Riley: I joined a local church and met friendly people.",
    )


def test_source_sibling_answer_evidence_accepts_activity_competition_proof() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="Did Riley and Jordan both participate in chess competitions?",
        expansion_reason="activity_competition_evidence_bridge",
        text=(
            "D4:2 Riley: Here's one of my trophies from a chess contest, "
            "a reminder of the hard work and joy it brings."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query="Did Riley and Jordan both participate in chess competitions?",
        expansion_reason="activity_competition_evidence_bridge",
        text="D4:3 Riley: I watched a chess match on television.",
    )
    assert source_sibling_answer_evidence(
        expansion_query=(
            "What does Gina say about the dancers in the photo? "
            "dancers dance festival photo grace skill"
        ),
        expansion_reason="activity_competition_evidence_bridge",
        text=(
            "D1:25 Gina: They are so graceful. "
            "D1:26 Jon: They are performing at the festival and will impress "
            "with their grace and skill."
        ),
    )


def test_source_sibling_relevance_accepts_activity_duration_age_and_ownership() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="How long has Melanie been creating art?",
        expansion_reason="decomposition_activity_duration",
        text=(
            "D16:7 Caroline: Since I was 17 or so. I find it empowering "
            "and cathartic. It's amazing how art can show things."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="How long has Jordan been creating art?",
        expansion_reason="decomposition_activity_duration",
        text="D4:6 Jordan: Jordan has been creating art since the age of 17.",
    )
    assert source_sibling_answer_evidence(
        expansion_query="For how long has Nate had his snakes?",
        expansion_reason="decomposition_activity_duration",
        text="D2:12 Nate: I've had them for 3 years now and they bring me tons of joy!",
    )


def test_source_sibling_answer_evidence_accepts_direct_item_purchases() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="What items has Melanie bought?",
        expansion_reason="item_purchase_bridge",
        text=(
            "D7:18 Melanie: Luna and Oliver are sweet and playful. "
            "Just got some new shoes, too!"
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="What items has Melanie bought?",
        expansion_reason="item_purchase_bridge",
        text="D19:2 Melanie: These figurines I bought yesterday remind me of family love.",
    )
    assert not source_sibling_answer_evidence(
        expansion_query="What items has Melanie bought?",
        expansion_reason="item_purchase_bridge",
        text="D8:3 Caroline: I bought new shoes for the trip.",
    )


def test_source_sibling_answer_evidence_accepts_business_commonality_turns() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="What do Jon and Gina both have in common?",
        expansion_reason="business_commonality_bridge",
        text=(
            "D2:1 Gina: I launched an ad campaign for my clothing store in "
            "hopes of growing the business. Starting my own store is scary."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="Do Jon and Gina start businesses out of what they love?",
        expansion_reason="business_start_reason_bridge",
        text=(
            "D6:8 Gina: I'm passionate about fashion trends and finding unique "
            "pieces. I wanted to blend my love for dance and fashion."
        ),
    )


def test_source_sibling_answer_evidence_accepts_family_support_appreciation() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="How did Melanie feel about her family supporting her?",
        expansion_reason="post_event_emotion_bridge",
        text="D18:13 Melanie: Thanks, Caroline. They're a real support. Appreciate them a lot.",
    )


def test_source_sibling_answer_evidence_accepts_direct_cause_inventory() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="What causes does John feel passionate about supporting?",
        expansion_reason="cause_education_infrastructure_inventory_bridge",
        text=(
            "D1:8 John: I'm passionate about improving education and "
            "infrastructure in our community. Those are my main focuses."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="What causes does John feel passionate about supporting?",
        expansion_reason="cause_education_infrastructure_inventory_bridge",
        text=(
            "D12:5 John: Recently, education reform and infrastructure "
            "development. Good access to quality education is key."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="What causes does John feel passionate about supporting?",
        expansion_reason="cause_veterans_inventory_bridge",
        text="D15:3 John: I've always been passionate about veterans and their rights.",
    )


def test_source_sibling_answer_evidence_accepts_direct_place_inventory_turn() -> None:
    query = "Which cities does Avery mention visiting to Jordan?"

    assert source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason="original_query",
        text=(
            "session_4 turn D4:3\n"
            "D4:3 Avery: I was in Portland, it was awesome! It had so much "
            "energy and the locals were really friendly."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason="place_area_inventory_bridge",
        text=(
            "session_5 turn D5:8\n"
            "D5:8 Avery: I visited Vancouver last month and loved the "
            "neighborhoods by the water."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason="original_query",
        text="D6:6 Avery: I love discovering new cities and cultures.",
    )
    assert not source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason="original_query",
        text="D7:1 Avery: I took a trip to a new place and loved the energy there.",
    )


def test_source_sibling_answer_evidence_accepts_fundraiser_event_slots() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="What events is Taylor planning for the community fundraiser?",
        expansion_reason="event_participation_bridge",
        text=(
            "D3:8 Taylor: I'm currently planning a beanbag tournament for the "
            "community center's fundraiser later this month."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="What events is Taylor planning for the community fundraiser?",
        expansion_reason="event_participation_bridge",
        text=(
            "D4:2 Taylor: I'm busy at the center getting ready for a fundraiser "
            "next week. Hopefully, we can raise enough to cover basic supplies."
        ),
    )


def test_source_sibling_answer_evidence_accepts_activity_class_companion() -> None:
    assert source_sibling_answer_evidence(
        expansion_query=(
            "yoga type types style styles practiced practice practicing class "
            "classes started starting trying tried poses breathing meditation"
        ),
        expansion_reason="exercise_activity_inventory_bridge",
        text=(
            "D4:2 Riley: I started a weekend yoga class with a colleague, "
            "and it has been great for flexibility."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=(
            "yoga type types style styles practiced practice practicing class "
            "classes started starting trying tried poses breathing meditation"
        ),
        expansion_reason="exercise_activity_inventory_bridge",
        text=(
            "D4:3 Riley: My colleague Alex invited me to a beginner yoga class "
            "after work."
        ),
    )


def test_source_sibling_answer_evidence_accepts_direct_sport_participation() -> None:
    assert source_sibling_answer_evidence(
        expansion_query=(
            "john sports activities observed sports sport game team court scored "
            "surfing surfboard waves position jersey season opener"
        ),
        expansion_reason="decomposition_activity_participation",
        text=(
            "D4:8 John: Here's a picture from a recent game. "
            "image caption: a basketball game in progress visual query: basketball game"
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=(
            "john sports activities observed sports sport game team court scored "
            "surfing surfboard waves position jersey season opener"
        ),
        expansion_reason="decomposition_activity_participation",
        text=(
            "D5:1 John: I had an awesome summer surfing and riding the waves. "
            "image caption: a person holding a surfboard on a beach"
        ),
    )


def test_source_sibling_answer_evidence_rejects_activity_without_companion() -> None:
    assert not source_sibling_answer_evidence(
        expansion_query=(
            "yoga type types style styles practiced practice practicing class "
            "classes started starting trying tried poses breathing meditation"
        ),
        expansion_reason="exercise_activity_inventory_bridge",
        text="D4:4 Riley: Yoga helps my flexibility, so I practice after work.",
    )


def test_volunteering_inventory_accepts_named_person_evidence() -> None:
    text = (
        "D6:8 Riley: One of the shelter residents, Morgan, wrote a letter "
        "expressing gratitude for the support they receive."
    )
    chunk = _chunk(
        chunk_id="resident-letter",
        source_external_id="locomo:conv-fixture:session_6:D6:8:turn",
        sequence=8,
        text=text,
    )

    assert source_sibling_answer_evidence(
        expansion_query="What people has Riley met and helped while volunteering?",
        expansion_reason="volunteering_inventory_bridge",
        text=text,
    )
    assert is_precise_source_sibling_turn(
        chunk=chunk,
        expansion_reason="volunteering_inventory_bridge",
    )
    assert source_sibling_score_cap(
        expansion_reason="volunteering_inventory_bridge",
        relevance=QueryRelevance(
            score_boost=0.02,
            query_term_count=9,
            unique_term_hits=2,
            capped_frequency_hits=2,
            hit_ratio=0.22,
            distinctive_term_count=7,
            distinctive_term_hits=2,
        ),
        text=text,
    ) is None
    assert source_sibling_answer_evidence(
        expansion_query="What people has Riley met and helped while volunteering?",
        expansion_reason="volunteering_people_inventory_bridge",
        text=text,
    )
    assert is_precise_source_sibling_turn(
        chunk=chunk,
        expansion_reason="volunteering_people_inventory_bridge",
    )
    assert source_sibling_score_cap(
        expansion_reason="volunteering_people_inventory_bridge",
        relevance=QueryRelevance(
            score_boost=0.02,
            query_term_count=9,
            unique_term_hits=2,
            capped_frequency_hits=2,
            hit_ratio=0.22,
            distinctive_term_count=7,
            distinctive_term_hits=2,
        ),
        text=text,
    ) is None


def test_volunteering_inventory_rejects_generic_shelter_mention() -> None:
    assert not source_sibling_answer_evidence(
        expansion_query="What people has Riley met and helped while volunteering?",
        expansion_reason="volunteering_inventory_bridge",
        text="D5:1 Riley volunteers at a neighborhood shelter on weekends.",
    )


def test_source_sibling_answer_evidence_accepts_shared_volunteering_service_activity() -> None:
    expansion_query = (
        "John Maria type volunteering both volunteer volunteered volunteering shelter "
        "homeless give out food supplies donation drive toy drive kids in need"
    )

    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="decomposition_inventory_list",
        text=(
            "session_3 turn D3:5\n"
            "D3:5 John: We held some events and got to meet some people. "
            "We went to a homeless shelter to give out food and supplies. "
            "We also organized a toy drive for kids in need."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="volunteering_inventory_bridge",
        text=(
            "session_2 turn D2:1\n"
            "D2:1 Maria: I donated my old car to a homeless shelter I "
            "volunteer at yesterday."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason="decomposition_inventory_list",
        text="session_5 turn D5:1\nD5:1 Riley volunteers at a neighborhood shelter.",
    )


def test_answer_evidence_seed_priority_keeps_late_volunteering_person_group() -> None:
    noise_chunks = tuple(
        _chunk(
            chunk_id=f"generic-volunteer-{index}",
            source_external_id=(
                f"locomo:conv-fixture:session_{index}:D{index}:1:turn"
            ),
            sequence=index,
            text=(
                f"D{index}:1 Riley volunteers at a community shelter on weekends "
                "and says the work is rewarding."
            ),
        )
        for index in range(1, 40)
    )
    resident_letter = _chunk(
        chunk_id="resident-gratitude-letter",
        source_external_id="locomo:conv-fixture:session_50:D50:8:turn",
        sequence=8,
        text=(
            "D50:8 Riley: One of the residents at the shelter wrote a heartfelt "
            "expression of gratitude about the impact of the support they receive."
        ),
    )

    unprioritized_groups = source_group_seed_turns((*noise_chunks, resident_letter))
    prioritized_chunks = _prioritize_source_sibling_answer_evidence_seed_chunks(
        seed_chunks=(*noise_chunks, resident_letter),
        query_plan=build_query_expansion_plan(
            "What people has Riley met and helped while volunteering?"
        ),
        query_relevance_cache={},
    )
    prioritized_groups = source_group_seed_turns(prioritized_chunks)

    assert "locomo:conv-fixture:session_50" not in unprioritized_groups
    assert "locomo:conv-fixture:session_50" in prioritized_groups


def test_source_sibling_answer_evidence_accepts_outdoor_waterfall_visual_slot() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="What outdoor activities has John done with his colleagues?",
        expansion_reason="outdoor_activity_inventory_bridge",
        text=(
            "D16:2 John image caption: a photo of a person standing in front "
            "of a waterfall with colleagues."
        ),
    )


def test_source_sibling_answer_evidence_accepts_outdoor_visual_group_response() -> None:
    assert source_sibling_answer_evidence(
        expansion_query=(
            "Riley outdoor activities hiking camping nature trail colleagues "
            "friends team group people photo image visual waterfall"
        ),
        expansion_reason="outdoor_activity_inventory_bridge",
        text=(
            "D4:2 Riley: Cool that it went well - you and your friends look "
            "like a great team."
        ),
    )


def test_outdoor_activity_visual_response_is_precise_uncapped_sibling() -> None:
    chunk = _chunk(
        chunk_id="outdoor-response",
        source_external_id="locomo:conv-41:session_16:D16:2:turn",
        sequence=2,
        text=(
            "D16:2 Riley: Cool that it went well - you and your friends look "
            "like a great team."
        ),
    )

    assert is_precise_source_sibling_turn(
        chunk=chunk,
        expansion_reason="outdoor_activity_inventory_bridge",
    )
    assert source_sibling_score_cap(
        expansion_reason="outdoor_activity_inventory_bridge",
        relevance=QueryRelevance(
            score_boost=0.02,
            query_term_count=12,
            unique_term_hits=3,
            capped_frequency_hits=3,
            hit_ratio=0.25,
            distinctive_term_count=10,
            distinctive_term_hits=3,
        ),
        text=chunk.text,
    ) is None


def test_source_sibling_answer_evidence_accepts_attribute_family_support() -> None:
    assert source_sibling_answer_evidence(
        expansion_query=(
            "John attributes describe family rock tough times cheer love thankful "
            "family time centered support strength motivation grounded"
        ),
        expansion_reason="attribute_family_support_bridge",
        text=(
            "D2:14 John: They are my rock in tough times and always cheer me on. "
            "I'm really thankful for their love. Family time means a lot to me."
        ),
    )


def test_source_sibling_answer_evidence_rejects_generic_family_mention() -> None:
    assert not source_sibling_answer_evidence(
        expansion_query=(
            "John attributes describe family rock tough times cheer love thankful "
            "family time centered support strength motivation grounded"
        ),
        expansion_reason="attribute_family_support_bridge",
        text="D2:1 John: My family went to the park and played games together.",
    )


def test_source_sibling_answer_evidence_accepts_temporal_turn_support() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="When did Melanie go to the museum?",
        expansion_reason="original_query",
        text=(
            "D6:4 Melanie: Yesterday I took the kids to the museum - it was "
            "so cool spending time with them."
        ),
    )


def test_source_sibling_answer_evidence_accepts_cause_awareness_answer_turn() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="What did the charity race raise awareness for?",
        expansion_reason="cause_awareness_event_bridge",
        text=(
            "D2:2 Riley: That charity race sounds great. Raising awareness "
            "for mental health is rewarding."
        ),
    )


def test_source_sibling_answer_evidence_accepts_running_benefit_turn() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="What does Caroline say running has been great for?",
        expansion_reason="running_reason_bridge",
        text=(
            "D7:24 Melanie: Thanks, Caroline! This has been great for my "
            "mental health. I'm gonna keep running."
        ),
    )


def test_source_sibling_answer_evidence_accepts_study_interval_technique() -> None:
    assert source_sibling_answer_evidence(
        expansion_query=(
            "Avery exam exams finals studying study time management technique "
            "method strategy"
        ),
        expansion_reason="study_time_management_bridge",
        text=(
            "D8:7 Avery: I like breaking up my studying into smaller parts. "
            "25 minutes on, then 5 minutes off for something fun. It keeps "
            "me on track."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=(
            "Avery exam exams finals studying study time management technique "
            "method strategy"
        ),
        expansion_reason="study_time_management_bridge",
        text="D8:3 Avery: This week has been packed with exams, but I am pushing through.",
    )


def test_source_sibling_answer_evidence_accepts_media_series_named_watch_turn() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="Which TV series does Avery mention watching?",
        expansion_reason="original_query",
        text=(
            'D6:12 Avery: I am excited to watch this new show called "The '
            'Silver Road". It is based on a book series I love.'
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query="Which TV series does Avery mention watching?",
        expansion_reason="original_query",
        text=(
            'D6:11 Morgan: What is the new show called? I am always looking '
            "for something to watch."
        ),
    )


def test_source_sibling_answer_evidence_accepts_escape_activity_turn() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="What does Avery do to escape reality?",
        expansion_reason="original_query",
        text=(
            "D3:30 Avery: Reading a great fantasy book helps me escape and "
            "feel free."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query="What does Avery do to escape reality?",
        expansion_reason="original_query",
        text="D3:31 Avery: That beach was beautiful, and the surf looked calm.",
    )


def test_source_sibling_answer_evidence_accepts_named_preference_support() -> None:
    assert source_sibling_answer_evidence(
        expansion_query=(
            "aurora quest avery related locations enjoy during visit inference "
            "supporting evidence likely would indicates preference trait"
        ),
        expansion_reason="decomposition_inference_support",
        text=(
            "D12:5 Avery: Definitely Aurora Quest! It is my favorite and "
            "never gets old."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=(
            "aurora quest avery related locations enjoy during visit inference "
            "supporting evidence likely would indicates preference trait"
        ),
        expansion_reason="decomposition_inference_support",
        text=(
            "D12:6 Avery: I saw a poster for Aurora Quest downtown, but I "
            "have not watched it yet."
        ),
    )


def test_source_sibling_answer_evidence_accepts_themed_location_experience() -> None:
    query = (
        "aurora quest avery related locations enjoy during visit inference "
        "supporting evidence likely would indicates preference trait"
    )

    assert source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason="decomposition_inference_support",
        text=(
            "D4:9 Avery: I went to a real fantasy movie place last year. "
            "The tour was amazing, and I would love to explore more places "
            "like that someday."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason="decomposition_inference_support",
        text="D4:10 Avery: I passed a cinema downtown but did not go inside.",
    )


def test_source_sibling_answer_evidence_accepts_destination_anchor_for_place_inference() -> None:
    query = (
        "aurora quest avery ireland related locations enjoy during visit "
        "inference supporting evidence likely would indicates preference trait"
    )

    assert source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason="decomposition_inference_support",
        text=(
            "D8:1 Avery: I got great news - I am finally in the study abroad "
            "program I applied for. Next month, I am off to Ireland for a semester."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=(
            "Which Aurora Quest-related locations would Avery enjoy during her "
            "visit to Ireland?"
        ),
        expansion_reason="original_query",
        text=(
            "D8:1 Avery: I got great news - I am finally in the study abroad "
            "program I applied for. Next month, I am off to Ireland for a semester."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=(
            "Avery Aurora Quest Ireland related locations places would enjoy visit "
            "recommendation destination trip travel study abroad semester"
        ),
        expansion_reason="themed_location_destination_bridge",
        text=(
            "D8:1 Avery: I got great news - I am finally in the study abroad "
            "program I applied for. Next month, I am off to Ireland for a semester."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query=(
            "Avery Ireland visit destination trip travel study abroad semester "
            "accepted applied program off to"
        ),
        expansion_reason="themed_location_destination_anchor_bridge",
        text=(
            "D8:1 Avery: I got great news - I am finally in the study abroad "
            "program I applied for. Next month, I am off to Ireland for a semester."
        ),
    )
    assert not source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason="decomposition_inference_support",
        text="D8:2 Avery: I read an article about Ireland while browsing travel blogs.",
    )


def test_source_sibling_answer_evidence_accepts_frequency_turn_without_speaker() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="How often does Caroline go to the beach with her kids?",
        expansion_reason="decomposition_frequency_recurrence",
        text=(
            "D10:10 Melanie: Seeing my kids' faces so happy at the beach was "
            "the best! We don't go often, usually only once or twice a year."
        ),
    )


def test_source_sibling_answer_evidence_accepts_every_other_appointment_cadence() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="How often are Sam's therapy appointments?",
        expansion_reason="decomposition_frequency_recurrence",
        text="D7:2 Sam: My therapy appointments are every other week.",
    )


def test_source_sibling_answer_evidence_rejects_cause_awareness_event_only_turn() -> None:
    assert not source_sibling_answer_evidence(
        expansion_query="What did the charity race raise awareness for?",
        expansion_reason="cause_awareness_event_bridge",
        text=(
            "D2:1 Avery: I ran a charity race for mental health last Saturday. "
            "It was really rewarding."
        ),
    )


def test_source_sibling_answer_evidence_accepts_classical_music_preference_turn() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="Would Morgan enjoy a classical song by Vivaldi?",
        expansion_reason="classical_music_preference_bridge",
        text=(
            "D5:9 Morgan: I'm a fan of classical music like Bach and Mozart, "
            "and I also enjoy modern songs."
        ),
    )


def test_source_sibling_answer_evidence_accepts_sentimental_reminder_turn() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="What is Riley's handmade bowl a reminder of?",
        expansion_reason="sentimental_reminder_bridge",
        text=(
            "D4:5 Riley: The handmade bowl has sentimental value. Its pattern "
            "and colors remind me of art and self-expression."
        ),
    )


def test_source_sibling_answer_evidence_accepts_outdoor_preference_turns() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="Would Morgan prefer a national park or a theme park?",
        expansion_reason="outdoor_preference_bridge",
        text=(
            "D10:12 Morgan: We always look forward to our family camping trip. "
            "We roast marshmallows around the campfire; it is the highlight "
            "of our summer."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="Would Morgan prefer a national park or a theme park?",
        expansion_reason="outdoor_nature_memory_bridge",
        text=(
            "D10:14 Morgan: I'll always remember the camping trip when we saw "
            "a meteor shower and felt at one with the universe."
        ),
    )


def test_source_sibling_answer_evidence_accepts_children_preference_turns() -> None:
    assert source_sibling_answer_evidence(
        expansion_query="What do Avery's kids like?",
        expansion_reason="children_preference_bridge",
        text=(
            "D6:6 Avery: They were stoked for the dinosaur exhibit. "
            "They love learning about animals and the bones were cool."
        ),
    )
    assert source_sibling_answer_evidence(
        expansion_query="What do Avery's children like?",
        expansion_reason="children_preference_bridge",
        text=(
            "D4:8 Avery: The younger kids love nature, campfires, and "
            "hiking outdoors."
        ),
    )


def test_source_sibling_answer_evidence_rejects_temporal_query_without_time_signal() -> None:
    assert not source_sibling_answer_evidence(
        expansion_query="When did Melanie go to the museum?",
        expansion_reason="original_query",
        text="D6:4 Melanie: I took the kids to the museum and they enjoyed it.",
    )


def test_source_sibling_answer_evidence_rejects_unrelated_temporal_turn() -> None:
    assert not source_sibling_answer_evidence(
        expansion_query="When did Melanie go to the museum?",
        expansion_reason="original_query",
        text=(
            "D6:3 Morgan: Yesterday I watched a documentary.\n"
            "D6:4 Melanie: I took the kids to the museum and they enjoyed it."
        ),
    )


def test_distant_source_sibling_rank_accepts_generic_list_slot_evidence() -> None:
    seed = _chunk(
        chunk_id="seed",
        source_external_id="locomo:conv-41:session_20:D20:10:turn",
        sequence=10,
        text="D20:10: John: Family keeps showing up for me.",
    )
    distant_evidence = _chunk(
        chunk_id="evidence",
        source_external_id="locomo:conv-41:session_20:D20:4:turn",
        sequence=4,
        text=(
            "D20:4: Maria: Last week, we had a blast at a live music event. "
            "Seeing them enjoy the songs made the night special."
        ),
    )

    rank = source_sibling_distant_answer_evidence_rank(
        distant_evidence,
        source_groups=source_group_seed_turns((seed,)),
        expansion_query="What music events has John attended?",
        expansion_reason="music_event_inventory_bridge",
        text=distant_evidence.text,
    )

    assert rank is not None
    assert rank.turn_delta == -6
    assert rank.turn_distance == 5


def test_distant_source_sibling_rank_accepts_dessert_recipe_slot() -> None:
    seed = _chunk(
        chunk_id="seed",
        source_external_id="locomo:generic:session_3:D3:10:turn",
        sequence=10,
        text="D3:10 Nate mentions enjoying chocolate and mixed berry flavors.",
    )
    distant_evidence = _chunk(
        chunk_id="evidence",
        source_external_id="locomo:generic:session_3:D3:4:turn",
        sequence=4,
        text=(
            "D3:4 Nate: I just discovered that I can make coconut milk "
            "icecream and gave it a try."
        ),
    )

    rank = source_sibling_distant_answer_evidence_rank(
        distant_evidence,
        source_groups=source_group_seed_turns((seed,)),
        expansion_query="Nate share",
        expansion_reason="decomposition_clause",
        text=distant_evidence.text,
    )

    assert rank is not None
    assert rank.turn_delta == -6
    assert rank.turn_distance == 5


def test_distant_source_sibling_rank_accepts_recommendation_advice_list() -> None:
    seed = _chunk(
        chunk_id="seed",
        source_external_id="locomo:generic:session_23:D23:18:turn",
        sequence=18,
        text="D23:18 Dana: I just watched a movie that was really gripping.",
    )
    distant_evidence = _chunk(
        chunk_id="evidence",
        source_external_id="locomo:generic:session_23:D23:26:turn",
        sequence=26,
        text=(
            "D23:26 Dana: Sure! For one, you should get a couch that can "
            "sit multiple people. Also invest in a weighted blanket and "
            "some dimmable lights."
        ),
    )

    rank = source_sibling_distant_answer_evidence_rank(
        distant_evidence,
        source_groups=source_group_seed_turns((seed,)),
        expansion_query=(
            "lee dana recommendations received recommendation suggestion advice "
            "source actor recipient to from"
        ),
        expansion_reason="recommendation_source_bridge",
        text=distant_evidence.text,
    )

    assert rank is not None
    assert rank.turn_delta == 8
    assert rank.turn_distance == 5


def test_source_sibling_answer_evidence_accepts_recommendation_setup_turn() -> None:
    assert source_sibling_answer_evidence(
        expansion_query=(
            "Dana Lee recommendations given recommendation suggestion advice "
            "recommended source actor recipient"
        ),
        expansion_reason="decomposition_recommendation_source",
        text="D6:12 Lee: Good idea! How about this series?",
    )


def test_recommendation_source_sibling_role_rank_uses_original_query_direction() -> None:
    query_text = "What recommendations has Dana given to Lee?"

    assert (
        source_sibling_answer_evidence_role_rank(
            query_text=query_text,
            expansion_reason="decomposition_recommendation_source",
            text="D6:11 Dana: Sure! For one, you should get a couch.",
        )
        == 0
    )
    assert (
        source_sibling_answer_evidence_role_rank(
            query_text=query_text,
            expansion_reason="decomposition_recommendation_source",
            text="D6:12 Lee: I highly recommend this game.",
        )
        == 5
    )


def test_distant_source_sibling_rank_accepts_lgbtq_community_participation_slot() -> None:
    seed = _chunk(
        chunk_id="seed",
        source_external_id="locomo:generic:session_9:D9:2:turn",
        sequence=2,
        text=(
            "D9:2 Riley: I joined an LGBTQ mentorship program to help younger "
            "people feel supported."
        ),
    )
    distant_evidence = _chunk(
        chunk_id="distant",
        source_external_id="locomo:generic:session_9:D9:12:turn",
        sequence=12,
        text=(
            "D9:12 Riley: Next month I am organizing an LGBTQ art show with "
            "paintings about community pride."
        ),
    )

    rank = source_sibling_distant_answer_evidence_rank(
        distant_evidence,
        source_groups=source_group_seed_turns((seed,)),
        expansion_query="In what ways is Riley participating in the LGBTQ community?",
        expansion_reason="lgbtq_community_participation_bridge",
        text=distant_evidence.text,
    )

    assert rank is not None
    assert rank.turn_delta == 10
    assert rank.turn_distance == 5


def test_source_sibling_candidate_limit_covers_many_seed_groups() -> None:
    assert source_sibling_candidate_limit(max_items=32, source_group_count=20) == 640
    assert source_sibling_candidate_limit(max_items=100, source_group_count=100) == 1024
    assert source_sibling_candidate_limit(max_items=0, source_group_count=20) == 0
    assert source_sibling_max_candidate_limit() == 1024


def test_deep_list_source_sibling_backfill_scans_each_selected_group() -> None:
    source_groups = {"conversation:session_1": object(), "conversation:session_6": object()}

    assert _source_sibling_group_backfill_plan(
        deep_list_coverage=True,
        source_groups=source_groups,
    ) == (("conversation:session_1", "conversation:session_6"), 96)
    assert _source_sibling_group_backfill_plan(
        deep_list_coverage=False,
        source_groups=source_groups,
    ) == ((), 0)


def test_place_source_sibling_diversity_is_place_query_scoped() -> None:
    place_query = "Which cities has Avery been to?"
    artist_query = "What musical artists or bands has Avery seen?"

    assert _query_plan_requests_place_source_sibling_diversity(
        query_text=place_query,
        query_plan=build_query_expansion_plan(place_query),
    )
    assert not _query_plan_requests_place_source_sibling_diversity(
        query_text=artist_query,
        query_plan=build_query_expansion_plan(artist_query),
    )


def test_named_preference_source_sibling_diversity_is_inference_scoped() -> None:
    named_preference_query = "Which Aurora Quest locations would Avery enjoy visiting?"
    unnamed_preference_query = "Which locations would Avery enjoy visiting?"
    named_lookup_query = "Which Aurora Quest episodes did Avery watch?"

    assert _query_plan_requests_named_preference_source_sibling_diversity(
        query_text=named_preference_query,
        query_plan=build_query_expansion_plan(named_preference_query),
    )
    assert not _query_plan_requests_named_preference_source_sibling_diversity(
        query_text=unnamed_preference_query,
        query_plan=build_query_expansion_plan(unnamed_preference_query),
    )
    assert not _query_plan_requests_named_preference_source_sibling_diversity(
        query_text=named_lookup_query,
        query_plan=build_query_expansion_plan(named_lookup_query),
    )


def test_named_preference_source_sibling_diversity_raises_group_limit() -> None:
    assert _source_sibling_group_limit_for_request(
        source_group_count=40,
        deep_list_coverage=False,
        answer_evidence_group_diversity=True,
    ) == 32
    assert _source_sibling_group_limit_for_request(
        source_group_count=12,
        deep_list_coverage=False,
        answer_evidence_group_diversity=True,
    ) == 20


def test_deep_list_answer_evidence_extra_key_uses_source_group() -> None:
    chunk = _chunk(
        chunk_id="place-turn",
        source_external_id="locomo:conv-fixture:session_6:D6:3:turn",
        sequence=3,
        text="D6:3 Avery: I was in Portland last week.",
    )

    assert (
        _source_sibling_answer_evidence_extra_key(chunk, deep_list_coverage=True)
        == "locomo:conv-fixture:session_6"
    )
    assert (
        _source_sibling_answer_evidence_extra_key(chunk, deep_list_coverage=False)
        == "locomo:conv-fixture:session_6:D6:3:turn"
    )


def test_source_sibling_relevance_gate_accepts_generic_list_slot_evidence() -> None:
    seed = _chunk(
        chunk_id="seed",
        source_external_id="locomo:conv-41:session_24:D24:7:turn",
        sequence=7,
        text="D24:7: John: I was thinking about service.",
    )
    evidence = _chunk(
        chunk_id="evidence",
        source_external_id="locomo:conv-41:session_24:D24:1:turn",
        sequence=1,
        text=(
            "D24:1: John: I visited a veteran's hospital and met some amazing "
            "people. It made me appreciate the need to give back."
        ),
    )
    rank = source_sibling_distant_answer_evidence_rank(
        evidence,
        source_groups=source_group_seed_turns((seed,)),
        expansion_query="What events for veterans has John participated in?",
        expansion_reason="veterans_event_inventory_bridge",
        text=evidence.text,
    )

    assert rank is not None
    assert is_precise_source_sibling_turn(
        chunk=evidence,
        expansion_reason="veterans_event_inventory_bridge",
    )
    assert source_sibling_relevance_allowed(
        rank=rank,
        relevance=QueryRelevance(
            score_boost=0.0,
            query_term_count=8,
            unique_term_hits=0,
            capped_frequency_hits=0,
            hit_ratio=0.0,
            distinctive_term_count=4,
            distinctive_term_hits=0,
        ),
        expansion_query="What events for veterans has John participated in?",
        expansion_reason="veterans_event_inventory_bridge",
        text=evidence.text,
    )


def _chunk(
    *,
    chunk_id: str,
    source_external_id: str,
    sequence: int,
    text: str,
) -> MemoryChunk:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryChunk(
        id=chunk_id,
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        document_id="document",
        episode_id=None,
        source_type="locomo_turn",
        source_external_id=source_external_id,
        source_hash=f"hash-{chunk_id}",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=text,
        normalized_text=text.casefold(),
        status=LifecycleStatus.ACTIVE,
        sequence=sequence,
        char_start=0,
        char_end=len(text),
        token_estimate=24,
        created_at=now,
        updated_at=now,
        metadata={},
    )

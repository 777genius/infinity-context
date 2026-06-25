"""Static query expansion rule catalog part 2."""

from __future__ import annotations

from infinity_context_core.application import context_query_expansion_rule_terms as _terms

EXPANSION_RULES_PART_2: tuple[tuple[frozenset[str], str, str], ...] = (
    (
            frozenset({"where", "friends"}),
            _terms._FRIEND_PLACE_GYM_INVENTORY_EXPANSION,
            "friend_place_gym_inventory_bridge",
        ),
    (
            frozenset({"where", "friends"}),
            _terms._FRIEND_PLACE_CHURCH_INVENTORY_EXPANSION,
            "friend_place_church_inventory_bridge",
        ),
    (
            frozenset({"where", "friend"}),
            _terms._FRIEND_PLACE_INVENTORY_EXPANSION,
            "friend_place_inventory_bridge",
        ),
    (
            frozenset({"where", "friend"}),
            _terms._FRIEND_PLACE_SHELTER_INVENTORY_EXPANSION,
            "friend_place_shelter_inventory_bridge",
        ),
    (
            frozenset({"where", "friend"}),
            _terms._FRIEND_PLACE_GYM_INVENTORY_EXPANSION,
            "friend_place_gym_inventory_bridge",
        ),
    (
            frozenset({"where", "friend"}),
            _terms._FRIEND_PLACE_CHURCH_INVENTORY_EXPANSION,
            "friend_place_church_inventory_bridge",
        ),
    (
            frozenset({"country", "been"}),
            _terms._TRAVEL_COUNTRY_INVENTORY_EXPANSION,
            "travel_country_inventory_bridge",
        ),
    (
            frozenset({"countries", "been"}),
            _terms._TRAVEL_COUNTRY_INVENTORY_EXPANSION,
            "travel_country_inventory_bridge",
        ),
    (
            frozenset({"country", "travel"}),
            _terms._TRAVEL_COUNTRY_INVENTORY_EXPANSION,
            "travel_country_inventory_bridge",
        ),
    (
            frozenset({"countries", "travel"}),
            _terms._TRAVEL_COUNTRY_INVENTORY_EXPANSION,
            "travel_country_inventory_bridge",
        ),
    (
            frozenset({"city", "visited"}),
            _terms._TRAVEL_COUNTRY_INVENTORY_EXPANSION,
            "travel_country_inventory_bridge",
        ),
    (
            frozenset({"city", "visit"}),
            _terms._TRAVEL_COUNTRY_INVENTORY_EXPANSION,
            "travel_country_inventory_bridge",
        ),
    (
            frozenset({"both", "visited"}),
            _terms._TRAVEL_COUNTRY_INVENTORY_EXPANSION,
            "travel_country_inventory_bridge",
        ),
    (
            frozenset({"causes"}),
            _terms._CAUSE_EDUCATION_INFRASTRUCTURE_EXPANSION,
            "cause_education_infrastructure_inventory_bridge",
        ),
    (
            frozenset({"cause"}),
            _terms._CAUSE_EDUCATION_INFRASTRUCTURE_EXPANSION,
            "cause_education_infrastructure_inventory_bridge",
        ),
    (
            frozenset({"causes"}),
            _terms._CAUSE_VETERANS_EXPANSION,
            "cause_veterans_inventory_bridge",
        ),
    (
            frozenset({"cause"}),
            _terms._CAUSE_VETERANS_EXPANSION,
            "cause_veterans_inventory_bridge",
        ),
    (
            frozenset({"общ", "хобби"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"общие", "интересы"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"обе", "любят"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"оба", "любят"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"кто", "ещё", "любит"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"кто", "еще", "любит"}),
            _terms._COMMONALITY_INTEREST_EXPANSION,
            "commonality_interest_bridge",
        ),
    (
            frozenset({"what", "national", "park"}),
            _terms._NATIONAL_PARK_INFERENCE_EXPANSION,
            "national_park_inference_bridge",
        ),
    (
            frozenset({"which", "national", "park"}),
            _terms._NATIONAL_PARK_INFERENCE_EXPANSION,
            "national_park_inference_bridge",
        ),
    (
            frozenset({"national", "park"}),
            "camping trip campfire meteor shower nature outdoors",
            "outdoor_preference_bridge",
        ),
    (
            frozenset({"camping"}),
            (
                "camping trip mountains explored nature roasted marshmallows campfire "
                "hike view forest beach"
            ),
            "camping_detail_bridge",
        ),
    (
            frozenset({"where", "trip"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"where", "travel"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"where", "traveled"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"where", "travelled"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"where", "visit"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"where", "visited"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"where", "vacation"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"place", "visit"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"city", "visit"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"country", "travel"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"destination", "travel"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"place", "vacation"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"city", "vacation"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"country", "vacation"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"place", "went"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"куда", "ездил"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"куда", "ездила"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"куда", "поездка"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"куда", "отпуск"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"где", "отдыхал"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"где", "отдыхала"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"город", "посетил"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"страна", "поехал"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"место", "отпуск"}),
            _terms._TRIP_DESTINATION_EXPANSION,
            "trip_destination_bridge",
        ),
    (
            frozenset({"family", "hike"}),
            (
                "family roasted marshmallows stories campfire hikes hiking camping "
                "forest nature kids children outdoors trip parent moments memories"
            ),
            "family_hike_activity_bridge",
        ),
    (
            frozenset({"family", "hike"}),
            (
                "roasted marshmallows shared stories campfire kids learning nature "
                "parent worth simple moments best memories forest hiking"
            ),
            "family_hike_detail_bridge",
        ),
    (
            frozenset({"first"}),
            (
                "first second third fourth fifth order sequence ordinal earliest initial "
                "won started finished event item tournament script letter attempt"
            ),
            "ordinal_answer_bridge",
        ),
    (
            frozenset({"second"}),
            (
                "first second third fourth fifth order sequence ordinal earliest initial "
                "won started finished event item tournament script letter attempt"
            ),
            "ordinal_answer_bridge",
        ),
    (
            frozenset({"third"}),
            (
                "first second third fourth fifth order sequence ordinal earliest initial "
                "won started finished event item tournament script letter attempt"
            ),
            "ordinal_answer_bridge",
        ),
    (
            frozenset({"fourth"}),
            (
                "first second third fourth fifth order sequence ordinal earliest initial "
                "won started finished event item tournament script letter attempt"
            ),
            "ordinal_answer_bridge",
        ),
    (
            frozenset({"many", "hike"}),
            (
                "hikes hike hiking trail waterfall loved spot rush water soothing "
                "sunset saw gorgeous other day buddies weekend new summer fort "
                "wayne photo pic took count times"
            ),
            "hike_count_activity_bridge",
        ),
    (
            frozenset({"after", "hike", "roadtrip"}),
            (
                "roadtrip road trip after hike hiking family mountains trail picture pic "
                "recent yesterday just did it kids loved nice way relax after road trip "
                "after the drive"
            ),
            "post_event_activity_timing_bridge",
        ),
    (
            frozenset({"many", "trail"}),
            (
                "hikes hiking hike trail trails found awesome amazing hometown town "
                "new trails more trails spots nature reset count times"
            ),
            "hiking_trail_count_bridge",
        ),
    (
            frozenset({"many"}),
            (
                "count total number quantity listed list includes including consists "
                "of first second third fourth another one two three four five collected "
                "earned received got completed items events pets books certificates awards"
            ),
            "quantity_enumeration_bridge",
        ),
    (
            frozenset({"сколько"}),
            (
                "count total number quantity listed list includes including consists "
                "of first second third fourth another one two three four five collected "
                "earned received got completed items events pets books certificates awards"
            ),
            "quantity_enumeration_bridge",
        ),
    (
            frozenset({"many", "tournament"}),
            (
                "tournament tournaments won winning first second fourth regional "
                "international big video game Valorant champion victory final money "
                "organized held tourney raised charity children hospital good cause"
            ),
            "tournament_count_bridge",
        ),
    (
            frozenset({"many", "tournaments"}),
            (
                "tournament tournaments won winning first second fourth regional "
                "international big video game Valorant champion victory final money "
                "organized held tourney raised charity children hospital good cause"
            ),
            "tournament_count_bridge",
        ),
    (
            frozenset({"charity", "tournament"}),
            (
                "charity tournament tournaments organized held gaming tourney friends "
                "raised amount children hospital good cause combining gaming organized "
                "yesterday"
            ),
            "charity_tournament_count_bridge",
        ),
    (
            frozenset({"many", "screenplay"}),
            (
                "screenplay screenplays script scripts first full screenplay printed "
                "started another second script wrapped up third one write wrote writing "
                "big screen finished count"
            ),
            "screenplay_count_bridge",
        ),
    (
            frozenset({"many", "screenplays"}),
            (
                "screenplay screenplays script scripts first full screenplay printed "
                "started another second script wrapped up third one write wrote writing "
                "big screen finished count"
            ),
            "screenplay_count_bridge",
        ),
    (
            frozenset({"many", "letter"}),
            (
                "letter letters received recieved got rejection letter wrote me letter "
                "words touched online blog post story comfort writing count"
            ),
            "letter_count_bridge",
        ),
    (
            frozenset({"many", "pet"}),
            (
                "pets pet puppy pup dog doggo adopted another dog adopted another pup "
                "shelter Toby Buddy Coco Shadow turtle turtles new friend critters count"
            ),
            "pet_count_bridge",
        ),
    (
            frozenset({"many", "turtle"}),
            (
                "turtles turtle critters new friend pet pets took turtles walk walking "
                "new tank third turtle count"
            ),
            "pet_count_bridge",
        ),
    (
            frozenset({"beach", "many"}),
            (
                "beach beaches went gone recently camped camping family kids children "
                "shore sand sandy kite campfire photo picture pic once twice year times"
            ),
            "beach_count_activity_bridge",
        ),
    (
            frozenset({"beach", "times"}),
            (
                "beach beaches went gone recently camped camping family kids children "
                "shore sand sandy kite campfire photo picture pic once twice year times"
            ),
            "beach_count_activity_bridge",
        ),
    (
            frozenset({"theme", "park"}),
            "camping trip campfire meteor shower nature outdoors",
            "outdoor_preference_bridge",
        ),
    (
            frozenset({"national", "park"}),
            "camping trip meteor shower sky universe nature",
            "outdoor_nature_memory_bridge",
        ),
    (
            frozenset({"theme", "park"}),
            "camping trip meteor shower sky universe nature",
            "outdoor_nature_memory_bridge",
        ),
    (
            frozenset({"decision", "adopt"}),
            "adoption family kids children mom support good luck",
            "adoption_support_bridge",
        ),
    (
            frozenset({"move", "home", "country", "soon"}),
            (
                "adoption agency interviews build own family roof kids children "
                "giving back goal family committed current future plan"
            ),
            "adoption_current_goal_bridge",
        ),
    (
            frozenset({"move", "home", "country", "soon"}),
            "passed adoption agency interviews last Friday goal having family",
            "adoption_current_milestone_bridge",
        ),
)

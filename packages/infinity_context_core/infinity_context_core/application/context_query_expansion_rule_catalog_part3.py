"""Static query expansion rule catalog part 3."""

from __future__ import annotations

from infinity_context_core.application import context_query_expansion_rule_terms as _terms

EXPANSION_RULES_PART_3: tuple[tuple[frozenset[str], str, str], ...] = (
    (
            frozenset({"ally", "transgender"}),
            (
                "supportive support acceptance community encouraging trans lgbtq "
                "proud allies inclusion kind words rights"
            ),
            "ally_support_bridge",
        ),
    (
            frozenset({"ally"}),
            "supportive support acceptance encouraging community care help proud kind words",
            "ally_support_bridge",
        ),
    (
            frozenset({"member", "community"}),
            "part belong identify refer herself member community lgbtq pride support group",
            "community_membership_bridge",
        ),
    (
            frozenset({"member", "lgbtq"}),
            (
                "supportive ally support acceptance transgender trans lgbtq community "
                "encouraging rights inclusion kind words"
            ),
            "community_membership_support_bridge",
        ),
    (
            frozenset({"political", "leaning"}),
            (
                "rights lgbtq transition conservative conservatives religious hike "
                "upset unwelcoming support not-so-great work still have to do"
            ),
            "political_inference_bridge",
        ),
    (
            frozenset({"religious"}),
            (
                "church faith religious conservative conservatives stained glass local "
                "church journey transgender woman growth change"
            ),
            "religious_inference_bridge",
        ),
    (
            frozenset({"destress"}),
            _terms._DESTRESS_ACTIVITY_EXPANSION,
            "destress_activity_bridge",
        ),
    (
            frozenset({"relax"}),
            _terms._DESTRESS_ACTIVITY_EXPANSION,
            "destress_activity_bridge",
        ),
    (
            frozenset({"unwind"}),
            _terms._DESTRESS_ACTIVITY_EXPANSION,
            "destress_activity_bridge",
        ),
    (
            frozenset({"time", "management"}),
            _terms._STUDY_TIME_MANAGEMENT_EXPANSION,
            "study_time_management_bridge",
        ),
    (
            frozenset({"exam", "technique"}),
            _terms._STUDY_TIME_MANAGEMENT_EXPANSION,
            "study_time_management_bridge",
        ),
    (
            frozenset({"exams", "technique"}),
            _terms._STUDY_TIME_MANAGEMENT_EXPANSION,
            "study_time_management_bridge",
        ),
    (
            frozenset({"study", "technique"}),
            _terms._STUDY_TIME_MANAGEMENT_EXPANSION,
            "study_time_management_bridge",
        ),
    (
            frozenset({"pomodoro"}),
            _terms._STUDY_TIME_MANAGEMENT_EXPANSION,
            "study_time_management_bridge",
        ),
    (
            frozenset({"stress", "relief"}),
            _terms._DESTRESS_ACTIVITY_EXPANSION,
            "destress_activity_bridge",
        ),
    (
            frozenset({"расслабляется"}),
            _terms._DESTRESS_ACTIVITY_EXPANSION,
            "destress_activity_bridge",
        ),
    (
            frozenset({"расслабиться"}),
            _terms._DESTRESS_ACTIVITY_EXPANSION,
            "destress_activity_bridge",
        ),
    (
            frozenset({"отдохнуть"}),
            _terms._DESTRESS_ACTIVITY_EXPANSION,
            "destress_activity_bridge",
        ),
    (
            frozenset({"снять", "стресс"}),
            _terms._DESTRESS_ACTIVITY_EXPANSION,
            "destress_activity_bridge",
        ),
    (
            frozenset({"camped"}),
            (
                "camping camped campsite campground family mountains beach forest "
                "lake park trail outdoors trip location place"
            ),
            "camping_location_bridge",
        ),
    (
            frozenset({"where", "camping"}),
            (
                "camping camped campsite campground family mountains beach forest "
                "lake park trail outdoors trip location place"
            ),
            "camping_location_bridge",
        ),
    (
            frozenset({"activities"}),
            (
                "pottery camping painting swimming class fam family kids weekend "
                "unplug hang swim running hobbies activities creative outdoors "
                "therapy therapeutic"
            ),
            "activity_aggregation_bridge",
        ),
    (
            frozenset({"activities"}),
            (
                "sunrise sunset lake take look swimming kids taking care ourselves "
                "vital self care relax long day"
            ),
            "activity_visual_selfcare_bridge",
        ),
    (
            frozenset({"kids", "like"}),
            (
                "kids children like love enjoy stoked excited dinosaur exhibit museum "
                "animals bones learning nature outdoors books stories favorite"
            ),
            "children_preference_bridge",
        ),
    (
            frozenset({"children", "like"}),
            (
                "kids children like love enjoy stoked excited dinosaur exhibit museum "
                "animals bones learning nature outdoors books stories favorite"
            ),
            "children_preference_bridge",
        ),
    (
            frozenset({"activity", "family"}),
            (
                "family kids children husband museum dinosaur painting nature camping "
                "campfire marshmallows hiking beach stories trip spending time pottery "
                "workshop clay pots swimming fam unplug hang creativity imagination "
                "excited motivated motivate love latest work quiet weekend"
            ),
            "family_activity_bridge",
        ),
    (
            frozenset({"activity", "dad"}),
            (
                "activity dad father parent childhood child kid younger used to go "
                "used to do used to play used to ride with my dad with my father "
                "family memory childhood memory"
            ),
            "family_activity_bridge",
        ),
    (
            frozenset({"activity", "father"}),
            (
                "activity dad father parent childhood child kid younger used to go "
                "used to do used to play used to ride with my dad with my father "
                "family memory childhood memory"
            ),
            "family_activity_bridge",
        ),
    (
            frozenset({"activity", "family"}),
            (
                "family painting together nature inspired latest work sunset flowers "
                "kids creativity imagination project"
            ),
            "family_painting_activity_bridge",
        ),
    (
            frozenset({"activity", "family"}),
            (
                "family kids children museum dinosaur exhibit bones learning "
                "exploring eyes light up stoked excited animals local museum"
            ),
            "family_museum_activity_bridge",
        ),
    (
            frozenset({"activity", "family"}),
            (
                "family swimming with kids swim taking care ourselves vital self care "
                "after conversation talk soon"
            ),
            "family_swimming_activity_bridge",
        ),
    (
            frozenset({"activity", "family"}),
            (
                "family husband kids children keep motivated motivate motivation love "
                "support moments worth lucky"
            ),
            "family_motivation_context_bridge",
        ),
    (
            frozenset({"kind", "art"}),
            _terms._ART_STYLE_EXPANSION,
            "art_style_bridge",
        ),
    (
            frozenset({"type", "art"}),
            _terms._ART_STYLE_EXPANSION,
            "art_style_bridge",
        ),
    (
            frozenset({"style", "art"}),
            _terms._ART_STYLE_EXPANSION,
            "art_style_bridge",
        ),
    (
            frozenset({"partake"}),
            "pottery camping swimming running hobbies activities creative outdoors",
            "activity_aggregation_bridge",
        ),
    (
            frozenset({"research"}),
            (
                "researched researching research looked into read about studied "
                "explored investigated topic information resources options"
            ),
            "research_topic_bridge",
        ),
    (
            frozenset({"partake"}),
            (
                "sunrise sunset lake take look swimming kids taking care ourselves "
                "vital self care relax long day"
            ),
            "activity_visual_selfcare_bridge",
        ),
    (
            frozenset({"self", "care"}),
            (
                "sunrise sunset lake take look swimming kids taking care ourselves "
                "vital self care relax long day prioritize unwind recharge activity"
            ),
            "activity_visual_selfcare_bridge",
        ),
    (
            frozenset({"seuss", "book"}),
            (
                "kids books children books classic childrens classics stories different "
                "cultures educational books bookshelf childhood favorite book"
            ),
            "children_books_inference_bridge",
        ),
    (
            frozenset({"subject", "painted"}),
            (
                "painted painting artwork subject both same shared sunset nature image "
                "caption photo visual query finished latest work"
            ),
            "shared_painted_subject_bridge",
        ),
    (
            frozenset({"painted"}),
            (
                "painted painting artwork picture photo image caption visual query "
                "horse sunset sunrise lake palm tree flowers sunflower landscape "
                "nature latest work canvas"
            ),
            "painting_inventory_bridge",
        ),
    (
            frozenset({"painting"}),
            (
                "painted painting artwork picture photo image caption visual query "
                "horse sunset sunrise lake palm tree flowers sunflower landscape "
                "nature latest work canvas"
            ),
            "painting_inventory_bridge",
        ),
    (
            frozenset({"when", "paint", "sunrise"}),
            (
                "when date painted painting sunrise artwork picture photo image "
                "caption visual query lake sunset relative date day weekday yesterday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"event", "attend"}),
            (
                "events participated attended joined went lgbtq community advocacy "
                "activism campaign mentorship mentoring program youth equality awareness"
            ),
            "event_participation_bridge",
        ),
    (
            frozenset({"competition", "attend"}),
            (
                "competition contest compete competed competing comp tournament trophy "
                "trophies first place won winner stage performance team crew regional "
                "regionals visual query image caption participated"
            ),
            "activity_competition_evidence_bridge",
        ),
    (
            frozenset({"dancers", "photo"}),
            (
                "dancers dance festival photo picture image caption visual query "
                "performing stage practicing hard grace skill graceful impress "
                "looks great awesome part of it"
            ),
            "activity_competition_evidence_bridge",
        ),
    (
            frozenset({"dance", "festival"}),
            (
                "dance festival dancers performing performance stage practicing hard "
                "grace skill graceful impress participate participating part of it "
                "glad awesome excited memories grand opening"
            ),
            "activity_competition_evidence_bridge",
        ),
    (
            frozenset({"awareness"}),
            (
                "raise raised raising spread spreading awareness charity race run "
                "fundraiser campaign event cause issue mental health domestic abuse "
                "animal welfare veterans rights education infrastructure lgbtq "
                "community trans rights gender identity inclusion public health "
                "make a difference start conversations"
            ),
            "cause_awareness_event_bridge",
        ),
    (
            frozenset({"realize", "after"}),
            (
                "realize realized learned understood after event race run charity "
                "self care self-care taking care important vital mental health "
                "emotion reaction inspired proud motivation"
            ),
            "post_event_emotion_bridge",
        ),
    (
            frozenset({"think"}),
            (
                "think thought opinion reaction response decision plan choice "
                "supportive proud excited happy agree approve concerned disagree "
                "good idea great idea encouragement"
            ),
            "opinion_reaction_bridge",
        ),
    (
            frozenset({"when", "charity", "race"}),
            (
                "when date charity race run ran fundraiser event participated "
                "signed up raised awareness relative date day weekday last saturday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"lgbtq", "event", "attend"}),
            (
                "lgbtq pride parade marched flags signs celebrating love diversity "
                "accepted happy belonged community equality"
            ),
            "lgbtq_pride_event_bridge",
        ),
    (
            frozenset({"lgbtq", "event", "attend"}),
            (
                "lgbtq support group transgender stories powerful inspiring accepted "
                "courage embrace community"
            ),
            "lgbtq_support_group_event_bridge",
        ),
    (
            frozenset({"lgbtq", "support", "group"}),
            (
                "lgbtq support group transgender stories powerful inspiring accepted "
                "courage embrace community attended went joined"
            ),
            "lgbtq_support_group_event_bridge",
        ),
    (
            frozenset({"lgbtq", "event", "attend"}),
            (
                "school event speech talk transgender journey students involved "
                "community reactions awareness allies inclusion gender identity"
            ),
            "lgbtq_school_event_bridge",
        ),
    (
            frozenset({"when", "school", "speech"}),
            (
                "when date school speech talk gave spoke students audience event "
                "journey support community relative date day weekday last week"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "meet", "friends"}),
            (
                "when date meet met meetup meeting friends family mentors support "
                "network gathering together relative date day weekday week"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"event", "attend", "help"}),
            (
                "help children youth mentorship mentoring program school speech talk "
                "students audience inspire allies community gender identity inclusion "
                "support voice transgender journey"
            ),
            "event_participation_help_bridge",
        ),
    (
            frozenset({"lgbtq", "community", "attend"}),
            (
                "lgbtq community participating ways activist group connected activists "
                "rights support voice difference pride parade mentorship program youth "
                "art show paintings"
            ),
            "lgbtq_community_participation_bridge",
        ),
    (
            frozenset({"counseling", "workshop"}),
            (
                "counseling workshop therapeutic methods trans people mental health "
                "safe space professionals support acceptance enlightening"
            ),
            "counseling_workshop_bridge",
        ),
    (
            frozenset({"counseling", "services"}),
            (
                "counseling mental health services therapy therapeutic support "
                "counselor help people similar issues lgbtq trans community safe "
                "supportive space interested pursuing career"
            ),
            "counseling_services_interest_bridge",
        ),
    (
            frozenset({"mental", "health", "services"}),
            (
                "counseling mental health services therapy therapeutic support "
                "counselor help people similar issues lgbtq trans community safe "
                "supportive space interested pursuing career"
            ),
            "counseling_services_interest_bridge",
        ),
    (
            frozenset({"create", "place", "people"}),
            (
                "create creating place space people safe inviting supportive "
                "welcoming accepted acceptance grow heal community counseling "
                "mental health support belong"
            ),
            "safe_supportive_place_goal_bridge",
        ),
    (
            frozenset({"when", "transgender", "conference"}),
            (
                "when date transgender conference going attending upcoming this "
                "month advocacy professionals community support relative date day"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "pottery", "class"}),
            (
                "when date sign signed up pottery class workshop clay creative "
                "therapeutic activity relative date day weekday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"when", "pottery", "workshop"}),
            (
                "when date pottery workshop class clay creative made make plate "
                "bowl cups kids children therapeutic activity relative date day weekday"
            ),
            "temporal_event_detail_bridge",
        ),
    (
            frozenset({"degree"}),
            (
                "degree policymaking policy political science public administration "
                "public affairs positive impact opportunities improvements"
            ),
            "degree_policy_inference_bridge",
        ),
    (
            frozenset({"friend", "beside"}),
            (
                "friends teammates team video game counter strike global offensive "
                "played together blast friends besides"
            ),
            "friends_team_inference_bridge",
        ),
    (
            frozenset({"friend", "other"}),
            (
                "friends teammates team video game counter strike global offensive "
                "played together blast friends besides other than"
            ),
            "friends_team_inference_bridge",
        ),
    (
            frozenset({"friend", "apart"}),
            (
                "friends teammates team video game counter strike global offensive "
                "played together blast friends besides apart from"
            ),
            "friends_team_inference_bridge",
        ),
    (
            frozenset({"друзья", "кроме"}),
            (
                "друзья друзья кроме помимо команда тиммейты онлайн игры "
                "valorant counter strike турниры играли вместе"
            ),
            "friends_team_inference_bridge",
        ),
    (
            frozenset({"друзей", "кроме"}),
            (
                "друзья друзья кроме помимо команда тиммейты онлайн игры "
                "valorant counter strike турниры играли вместе"
            ),
            "friends_team_inference_bridge",
        ),
    (
            frozenset({"друзья", "помимо"}),
            (
                "друзья друзья кроме помимо команда тиммейты онлайн игры "
                "valorant counter strike турниры играли вместе"
            ),
            "friends_team_inference_bridge",
        ),
    (
            frozenset({"друзей", "помимо"}),
            (
                "друзья друзья кроме помимо команда тиммейты онлайн игры "
                "valorant counter strike турниры играли вместе"
            ),
            "friends_team_inference_bridge",
        ),
    (
            frozenset({"medium", "game"}),
            (
                "medium mediums games play gaming GameCube Gamecube PC Playstation "
                "console equipment upgraded setup competition tournament trophy "
                "cash prize controller keyboard headset headphones"
            ),
            "gaming_medium_bridge",
        ),
    (
            frozenset({"board", "games"}),
            (
                "board game board games tabletop strategy game card game gaming party "
                "game convention played plays playing named called"
            ),
            "board_game_inventory_bridge",
        ),
    (
            frozenset({"board", "game"}),
            (
                "board game board games tabletop strategy game card game gaming party "
                "game convention played plays playing named called"
            ),
            "board_game_inventory_bridge",
        ),
    (
            frozenset({"video", "games"}),
            (
                "video game video games videogame gaming esports tournament tournaments "
                "championship final champion won winning winner victory feelings emotions "
                "play plays played playing currently nonstop called named title console pc "
                "switch rpg role playing fighting game shooter"
            ),
            "board_game_inventory_bridge",
        ),
    (
            frozenset({"video", "game"}),
            (
                "video game video games videogame gaming esports tournament tournaments "
                "championship final champion won winning winner victory feelings emotions "
                "play plays played playing currently nonstop called named title console pc "
                "switch rpg role playing fighting game shooter"
            ),
            "board_game_inventory_bridge",
        ),
    (
            frozenset({"clipboard"}),
            (
                "clipboard notepad notebook calendar planner using use stay organized "
                "motivated sets goals tracks achievements areas improve improvement "
                "goal setting progress system attached"
            ),
            "planning_tool_use_bridge",
        ),
    (
            frozenset({"notepad"}),
            (
                "clipboard notepad notebook calendar planner using use stay organized "
                "motivated sets goals tracks achievements areas improve improvement "
                "goal setting progress system attached"
            ),
            "planning_tool_use_bridge",
        ),
    (
            frozenset({"customers", "experience"}),
            (
                "customers customer special experience creating create feel welcome "
                "coming back come back key space imagining cozy inviting shopping "
                "store oasis customer experience"
            ),
            "customer_experience_bridge",
        ),
    (
            frozenset({"customer", "experience"}),
            (
                "customers customer special experience creating create feel welcome "
                "coming back come back key space imagining cozy inviting shopping "
                "store oasis customer experience"
            ),
            "customer_experience_bridge",
        ),
    (
            frozenset({"grand", "opening"}),
            (
                "grand opening launch dance studio tomorrow right by your side "
                "live it up great memories so excited support proud can't wait "
                "earned it opening night"
            ),
            "grand_opening_support_bridge",
        ),
    (
            frozenset({"pet", "have"}),
            (
                "pets has have dog new addition family turtles critters new friend "
                "puppy pup doggo pet turtle"
            ),
            "pet_inventory_bridge",
        ),
    (
            frozenset({"pets", "names"}),
            (
                "pets pet names named called dog dogs cat cats puppy pup turtle "
                "turtles new addition family companion belongs to has have"
            ),
            "pet_inventory_bridge",
        ),
    (
            frozenset({"dogs", "names"}),
            (
                "dogs dog names named called puppy pup pets pet new addition family "
                "companion belongs to has have"
            ),
            "pet_inventory_bridge",
        ),
    (
            frozenset({"is", "pet"}),
            (
                "is pet belongs to has have dog cat puppy pup turtle named called "
                "new addition family companion owner"
            ),
            "pet_inventory_bridge",
        ),
    (
            frozenset({"puppy", "adjusting"}),
            (
                "puppy pup dog pet little one new home adjusting adjusted doing "
                "great learning commands house training trained adopted shelter "
                "brings joy give home"
            ),
            "pet_adjustment_bridge",
        ),
    (
            frozenset({"puppy", "home"}),
            (
                "puppy pup dog pet little one new home adjusting adjusted doing "
                "great learning commands house training trained adopted shelter "
                "brings joy give home"
            ),
            "pet_adjustment_bridge",
        ),
    (
            frozenset({"when", "adopt"}),
            (
                "when date adopted got get new addition family pet dog puppy pup "
                "new pup for you gift from named stuffed animal image caption "
                "visual query cute dog couch blanket toy"
            ),
            "pet_acquisition_date_bridge",
        ),
    (
            frozenset({"when", "get"}),
            (
                "when date adopted got get new addition family pet dog puppy pup "
                "new pup for you gift from named stuffed animal image caption "
                "visual query cute dog couch blanket toy"
            ),
            "pet_acquisition_date_bridge",
        ),
    (
            frozenset({"beach", "mountains"}),
            (
                "beach ocean sunset sailboat walk weekly nature close nearby mountains "
                "outdoors hiking camping"
            ),
            "beach_or_mountains_inference_bridge",
        ),
    (
            frozenset({"future", "job", "pursue"}),
            (
                "volunteering shelter front desk food bed make difference lives started "
                "fulfilling gave few talks connecting helping others compliments residents "
                "aunt believed brighten struggling counselor coordinator volunteer homeless "
                "future job career social work smiles faces day about year ago witnessed "
                "family streets reached out needed volunteers"
            ),
            "volunteer_career_inference_bridge",
        ),
    (
            frozenset({"career", "month"}),
            (
                "career work job professional month good bad positive negative "
                "setback setbacks letdown failure failed loss lost work lost progress "
                "crashed crash major blow frustrating did not do well didn't do well "
                "not great competition tournament performance"
            ),
            "negative_experience_support_bridge",
        ),
    (
            frozenset({"career", "wise"}),
            (
                "career work job professional month good bad positive negative "
                "setback setbacks letdown failure failed loss lost work lost progress "
                "crashed crash major blow frustrating did not do well didn't do well "
                "not great competition tournament performance"
            ),
            "negative_experience_support_bridge",
        ),
    (
            frozenset({"alternative", "career"}),
            _terms._ANIMAL_CAREER_INFERENCE_EXPANSION,
            "animal_career_inference_bridge",
        ),
    (
            frozenset({"animal", "career"}),
            _terms._ANIMAL_CAREER_INFERENCE_EXPANSION,
            "animal_career_inference_bridge",
        ),
    (
            frozenset({"alternative", "career"}),
            _terms._ANIMAL_CARE_INSTRUCTION_EXPANSION,
            "animal_care_instruction_bridge",
        ),
    (
            frozenset({"alternative", "career"}),
            _terms._ANIMAL_DIET_EVIDENCE_EXPANSION,
            "animal_diet_evidence_bridge",
        ),
    (
            frozenset({"alternative", "career"}),
            _terms._ANIMAL_HABITAT_SETUP_EXPANSION,
            "animal_habitat_setup_bridge",
        ),
    (
            frozenset({"alternative", "career"}),
            _terms._ANIMAL_AFFINITY_PET_STORE_EXPANSION,
            "animal_affinity_pet_store_bridge",
        ),
    (
            frozenset({"activities", "turtles"}),
            _terms._ANIMAL_ACTIVITY_INVENTORY_EXPANSION,
            "animal_activity_inventory_bridge",
        ),
    (
            frozenset({"activity", "turtles"}),
            _terms._ANIMAL_ACTIVITY_INVENTORY_EXPANSION,
            "animal_activity_inventory_bridge",
        ),
    (
            frozenset({"activities", "pets"}),
            _terms._ANIMAL_ACTIVITY_INVENTORY_EXPANSION,
            "animal_activity_inventory_bridge",
        ),
    (
            frozenset({"career", "gaming"}),
            _terms._ANIMAL_CAREER_INFERENCE_EXPANSION,
            "animal_career_inference_bridge",
        ),
    (
            frozenset({"career", "gaming"}),
            _terms._ANIMAL_CARE_INSTRUCTION_EXPANSION,
            "animal_care_instruction_bridge",
        ),
    (
            frozenset({"career", "gaming"}),
            _terms._ANIMAL_DIET_EVIDENCE_EXPANSION,
            "animal_diet_evidence_bridge",
        ),
    (
            frozenset({"career", "gaming"}),
            _terms._ANIMAL_HABITAT_SETUP_EXPANSION,
            "animal_habitat_setup_bridge",
        ),
    (
            frozenset({"career", "gaming"}),
            _terms._ANIMAL_AFFINITY_PET_STORE_EXPANSION,
            "animal_affinity_pet_store_bridge",
        ),
    (
            frozenset({"pet", "discomfort"}),
            (
                "pets animals reptiles fur allergic allergy puffy itchy discomfort "
                "turtles cockroaches pet"
            ),
            "pet_allergy_discomfort_bridge",
        ),
    (
            frozenset({"allergic"}),
            (
                "allergic allergy cannot can't have dairy dairy-free no ice cream "
                "reptiles animals fur cockroaches pets turtles"
            ),
            "allergy_inventory_bridge",
        ),
    (
            frozenset({"allergy"}),
            (
                "allergic allergy cannot can't have dairy dairy-free no ice cream "
                "reptiles animals fur cockroaches pets turtles"
            ),
            "allergy_inventory_bridge",
        ),
    (
            frozenset({"not", "eat"}),
            (
                "avoid avoids avoided never eat eats eating food foods allergic allergy "
                "restriction restricted dislike cannot can't shellfish peanuts dietary "
                "preference discomfort unsafe"
            ),
            "avoidance_constraint_bridge",
        ),
    (
            frozenset({"not", "like"}),
            _terms._NEGATIVE_PREFERENCE_EXPANSION,
            "negative_preference_bridge",
        ),
    (
            frozenset({"dislike"}),
            _terms._NEGATIVE_PREFERENCE_EXPANSION,
            "negative_preference_bridge",
        ),
    (
            frozenset({"hate"}),
            _terms._NEGATIVE_PREFERENCE_EXPANSION,
            "negative_preference_bridge",
        ),
    (
            frozenset({"not", "interested"}),
            (
                "not interested uninterested doesn't want does not want avoid avoids "
                "declined preference dislike not enjoy no interest low priority"
            ),
            "negative_preference_bridge",
        ),
    (
            frozenset({"meat", "prefer"}),
            (
                "favorite meat chicken beef pork fish turkey steak dish recipe cooking "
                "cook roasted pot pie comfort meal favorite eating food prefer preference"
            ),
            "food_preference_bridge",
        ),
    (
            frozenset({"food", "prefer"}),
            (
                "favorite food meal dish recipe cooking cook comfort meal favorite "
                "eating prefer preference"
            ),
            "food_preference_bridge",
        ),
    (
            frozenset({"avoid"}),
            (
                "avoid avoids avoided should not never risk blocked blocker constraint "
                "restriction unsafe conflict prerequisite before approval"
            ),
            "avoidance_constraint_bridge",
        ),
    (
            frozenset({"condition", "allergy"}),
            (
                "underlying condition allergies allergic reptiles animals fur puffy "
                "itchy cockroaches turtles pet discomfort"
            ),
            "allergy_condition_inference_bridge",
        ),
    (
            frozenset({"symbol"}),
            (
                "symbols important rainbow flag mural eagle freedom pride courage "
                "strength trans community resilience stained glass acceptance pendant "
                "necklace transgender symbol cross heart symbolizes represents meaning "
                "means stands for love faith roots gift grandma reminder"
            ),
            "symbol_importance_bridge",
        ),
    (
            frozenset({"console"}),
            (
                "console nintendo game cover fantasy rpg xenoblade chronicles switch "
                "playing awesome blast recommend"
            ),
            "console_game_cover_bridge",
        ),
    (
            frozenset({"artist", "band"}),
            (
                "musical artists bands saw seen live concert show festival performance "
                "performed summer sounds band pop dancing singing lively fun"
            ),
            "music_artist_band_bridge",
        ),
)

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
            "camping camped family mountains beach forest outdoors trip",
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
            (
                "art painting artwork art show preview abstract style kind type "
                "inclusivity diversity representation identity self acceptance"
            ),
            "art_style_bridge",
        ),
    (
            frozenset({"type", "art"}),
            (
                "art painting artwork art show preview abstract style kind type "
                "inclusivity diversity representation identity self acceptance"
            ),
            "art_style_bridge",
        ),
    (
            frozenset({"partake"}),
            "pottery camping swimming running hobbies activities creative outdoors",
            "activity_aggregation_bridge",
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
            frozenset({"event", "attend"}),
            (
                "events participated attended joined went lgbtq community advocacy "
                "activism campaign mentorship mentoring program youth equality awareness"
            ),
            "event_participation_bridge",
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
            frozenset({"lgbtq", "event", "attend"}),
            (
                "school event speech talk transgender journey students involved "
                "community reactions awareness allies inclusion gender identity"
            ),
            "lgbtq_school_event_bridge",
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
                "console equipment upgraded setup competition controller keyboard"
            ),
            "gaming_medium_bridge",
        ),
    (
            frozenset({"pet", "have"}),
            (
                "pets has have dog Max new addition family turtles critters new friend "
                "puppy pup doggo pet turtle"
            ),
            "pet_inventory_bridge",
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
            frozenset({"alternative", "career"}),
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
            (
                "does not like doesn't like dislike dislikes disliked hate hates hated "
                "avoid avoids avoided not enjoy never enjoy preference discomfort "
                "overwhelming too loud unsafe unpleasant"
            ),
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

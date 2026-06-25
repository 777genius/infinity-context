from infinity_context_core.application.context_inference_evidence import (
    inference_evidence_rerank_signal,
)


def test_inference_evidence_signal_boosts_support_role_fit_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Caroline be a good mentor for Alex?",
        text=(
            "Caroline mentored LGBTQ youth, listened patiently, and helped people "
            "feel safe in the community program."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_support_role_fit_evidence"


def test_inference_evidence_signal_boosts_trust_support_role_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Alex trust Caroline with sensitive issues?",
        text=(
            "Caroline listened without judging, kept Alex's anxiety private, "
            "and helped him feel safe opening up."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_support_role_fit_evidence"


def test_inference_evidence_signal_rejects_operational_support_role_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Alex trust Caroline with sensitive issues?",
        text=(
            "Caroline is reliable with the private issue tracker and reviews "
            "backend support tickets every Friday."
        ),
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_support_role_operational_noise"


def test_inference_evidence_signal_penalizes_generic_support_network_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Caroline be a good mentor for Alex?",
        text="Caroline's friends and family support her and give her strength.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_generic_support_noise"


def test_inference_evidence_signal_ignores_non_inference_queries() -> None:
    signal = inference_evidence_rerank_signal(
        query="Who are Caroline's mentors?",
        text="Caroline's friends and family support her and give her strength.",
    )

    assert signal.boost == 0
    assert signal.penalty == 0
    assert signal.reason == ""


def test_inference_evidence_signal_boosts_counterfactual_support_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Caroline support Alex joining the pride group?",
        text=(
            "Caroline has been supportive and encouraging at pride groups. "
            "She helped Alex feel welcome and safe in the community."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_counterfactual_support_evidence"


def test_inference_evidence_signal_penalizes_generic_counterfactual_support_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Caroline support Alex joining the pride group?",
        text="Caroline's friends and family support her and give her strength.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_counterfactual_support_noise"


def test_inference_evidence_signal_boosts_generic_behavior_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Alex be considered reliable?",
        text="Alex kept his promises, followed through, and prepared the launch notes early.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_behavior_evidence"


def test_inference_evidence_signal_boosts_helpful_behavior_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Alex be considered helpful?",
        text="Alex listened patiently, helped Sam debug the launch, and reassured the team.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_behavior_evidence"


def test_inference_evidence_signal_boosts_careful_behavior_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Alex be considered thorough?",
        text="Alex checked the release notes carefully, reviewed the diff, and verified it.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_behavior_evidence"


def test_inference_evidence_signal_boosts_direct_trait_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Caroline be considered patient?",
        text="Caroline is thoughtful and patient with new volunteers.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_behavior_evidence"


def test_inference_evidence_signal_boosts_direct_reliability_trait_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Alex be considered reliable?",
        text="Alex is reliable.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_behavior_evidence"


def test_inference_evidence_signal_rejects_direct_trait_identity_mismatch() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Alex be considered helpful?",
        text="The onboarding guide is helpful for new users.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_behavior_topic_only_noise"


def test_inference_evidence_signal_does_not_boost_behaviorless_topic_overlap() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Alex be considered reliable?",
        text="Alex discussed reliability as a product metric in the backend review.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_behavior_topic_only_noise"


def test_inference_evidence_signal_does_not_boost_identity_only_behavior_overlap() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Alex be considered unusual?",
        text="Alex worked regularly and prepared notes for the weekly launch meeting.",
    )

    assert signal.boost == 0
    assert signal.penalty == 0
    assert signal.reason == ""


def test_inference_evidence_signal_boosts_preference_fit_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query='Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?',
        text="Melanie is a fan of classical music like Bach and Mozart.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_preference_fit_evidence"


def test_inference_evidence_signal_penalizes_negative_preference_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query='Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?',
        text="Melanie usually listens to podcasts instead.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_negative_preference_noise"


def test_inference_evidence_signal_boosts_negative_preference_fit_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query='Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?',
        text="Melanie avoids classical music and dislikes orchestra concerts.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_negative_preference_fit_evidence"


def test_inference_evidence_signal_boosts_generic_negative_preference_fit() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Maria enjoy hiking?",
        text="Maria dislikes hiking and avoids mountain trails.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_negative_preference_fit_evidence"


def test_inference_evidence_signal_boosts_comparison_preference_fit() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Melanie be more interested in a national park or a theme park?",
        text="Melanie loves camping, hiking, and quiet outdoor trips in national parks.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_preference_fit_evidence"


def test_inference_evidence_signal_boosts_negative_comparison_option_fit() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Melanie be more interested in a national park or a theme park?",
        text="Melanie dislikes loud theme parks and avoids noisy rides.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_negative_preference_fit_evidence"


def test_inference_evidence_signal_does_not_treat_podcast_domain_as_negative() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Melanie likely enjoy podcasts?",
        text="Melanie listens to podcasts every night.",
    )

    assert signal.penalty == 0
    assert signal.reason == ""


def test_inference_evidence_signal_boosts_willingness_fit_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would John be open to moving to another country?",
        text=(
            "John felt hopeful after hearing a veteran's stories and wanted to "
            "join the military for an international mission."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_willingness_fit_evidence"


def test_inference_evidence_signal_boosts_public_office_willingness_fit() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would John be open to moving to another country?",
        text=(
            "John wanted to run for office again and was excited about public "
            "service in local politics."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_willingness_fit_evidence"


def test_inference_evidence_signal_penalizes_willingness_topic_only_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would John be open to moving to another country?",
        text="John moved from another country as a child and misses his old hometown.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_willingness_topic_only_noise"


def test_inference_evidence_signal_boosts_career_fit_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="What job might Maria pursue in the future?",
        text=(
            "Maria volunteered at the shelter front desk, found it fulfilling, "
            "and received compliments from residents."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_career_fit_evidence"


def test_inference_evidence_signal_penalizes_career_topic_only_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="What job might Maria pursue in the future?",
        text='John saw a career fair sign that said "Always look on the bright side."',
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_career_topic_only_noise"


def test_inference_evidence_signal_boosts_animal_career_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="What alternative career might Nate consider after gaming?",
        text="Nate keeps pet turtles, cleans their tank, and enjoys feeding them.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_animal_career_fit_evidence"


def test_inference_evidence_signal_boosts_career_field_decision_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="What fields would Caroline be likely to pursue in her educaton?",
        text=(
            "Caroline is keen on counseling and working in mental health, "
            "and she would love to support people with similar issues."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_career_field_decision_evidence"


def test_inference_evidence_signal_penalizes_negated_career_decision_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="What career path has Caroline decided to persue?",
        text=(
            "Caroline wrote a short story about career uncertainty, but did "
            "not decide to pursue writing as a job."
        ),
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_career_negated_decision_noise"


def test_inference_evidence_signal_boosts_friend_team_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Is it likely that Nate has friends besides Joanna?",
        text="Nate plays Valorant with online teammates and gaming friends from tournaments.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_friend_team_evidence"


def test_inference_evidence_signal_boosts_friend_team_evidence_without_likely_marker() -> None:
    signal = inference_evidence_rerank_signal(
        query="Does Nate have friends besides Joanna?",
        text="Nate plays Valorant with online teammates and gaming friends from tournaments.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_friend_team_evidence"


def test_inference_evidence_signal_penalizes_single_contact_friend_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="Is it likely that Nate has friends besides Joanna?",
        text="Nate played a video game with Joanna after school.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_friend_team_single_contact_noise"


def test_inference_evidence_signal_penalizes_single_contact_without_likely_marker() -> None:
    signal = inference_evidence_rerank_signal(
        query="Does Nate have friends besides Joanna?",
        text="Nate played a video game with Joanna after school.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_friend_team_single_contact_noise"


def test_inference_evidence_signal_penalizes_named_single_contact_generically() -> None:
    signal = inference_evidence_rerank_signal(
        query="Does Nate have friends other than Alex?",
        text="Nate played Counter Strike with Alex after school.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_friend_team_single_contact_noise"


def test_inference_evidence_signal_boosts_russian_friend_team_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Есть ли у Нейта друзья кроме Жанны?",
        text="Нейт играет в Valorant с онлайн-командой и друзьями по турнирам.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_friend_team_evidence"


def test_inference_evidence_signal_penalizes_russian_single_contact_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="Есть ли у Нейта друзья помимо Жанны?",
        text="Нейт играл в видеоигру с Жанной после школы.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_friend_team_single_contact_noise"


def test_inference_evidence_signal_boosts_degree_policy_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="What might John's degree be in?",
        text="John studied political science and public policy at university.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_degree_policy_evidence"


def test_inference_evidence_signal_boosts_state_residence_geo_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Which US state do Audrey and Andrew potentially live in?",
        text=(
            "Andrew image caption: a photo of a map of a park with a lot of "
            "trees. Andrew image query: hiking trails map perfect spot."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_state_residence_geo_evidence"


def test_inference_evidence_signal_penalizes_state_residence_technical_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="Which US state do Audrey and Andrew potentially live in?",
        text="Andrew talked about a state machine and map code in the app repository.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_state_residence_technical_noise"


def test_inference_evidence_signal_boosts_political_values_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="What would Caroline's political leaning likely be?",
        text=(
            "Caroline said religious conservatives made her feel unwelcoming "
            "about her transition and LGBTQ rights."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_political_values_evidence"


def test_inference_evidence_signal_penalizes_political_topic_only_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="What would Caroline's political leaning likely be?",
        text="Caroline discussed political news but did not share any views.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_political_topic_only_noise"


def test_inference_evidence_signal_boosts_community_membership_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Melanie be considered a member of the LGBTQ community?",
        text=(
            "Melanie identifies as part of the LGBTQ community and joined "
            "the pride support group."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_community_membership_evidence"


def test_inference_evidence_signal_penalizes_ally_noise_for_membership_query() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Melanie be considered a member of the LGBTQ community?",
        text="Melanie is supportive of Caroline and encourages the LGBTQ community as an ally.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_community_membership_ally_noise"


def test_inference_evidence_signal_penalizes_general_community_topic_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Melanie be considered a member of the LGBTQ community?",
        text="Melanie attended a public community fundraiser downtown.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_community_membership_topic_only_noise"


def test_inference_evidence_signal_boosts_allergy_condition_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="What underlying condition might Joanna have based on her allergies?",
        text=(
            "Joanna is allergic to most reptiles and animals with fur. "
            "Her face gets puffy and itchy around them."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_allergy_condition_evidence"


def test_inference_evidence_signal_penalizes_allergy_condition_topic_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="What underlying condition might Joanna have based on her allergies?",
        text="Joanna keeps cute reptile photos and animal drawings as reminders.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_allergy_condition_topic_only_noise"


def test_inference_evidence_signal_does_not_overboost_food_only_allergy_inventory() -> None:
    signal = inference_evidence_rerank_signal(
        query="What underlying condition might Joanna have based on her allergies?",
        text="Joanna cannot have dairy, so she asked for a dairy-free recipe.",
    )

    assert signal.boost == 0
    assert signal.penalty == 0
    assert signal.reason == ""


def test_inference_evidence_signal_penalizes_degree_measurement_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="What might John's degree be in?",
        text="John set the thermostat to 68 degrees before leaving.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_degree_measurement_noise"


def test_inference_evidence_signal_boosts_religious_fit_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Caroline be considered religious?",
        text="Caroline made stained glass artwork for a local church.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_religious_fit_evidence"


def test_inference_evidence_signal_penalizes_religious_political_noise() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would Caroline be considered religious?",
        text=(
            "Caroline said religious conservatives made her feel unwelcoming "
            "during her transgender journey."
        ),
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "inference_religious_topic_only_noise"


def test_inference_evidence_signal_boosts_patriotic_service_fit_evidence() -> None:
    signal = inference_evidence_rerank_signal(
        query="Would John be considered a patriotic person?",
        text="John retook the aptitude test and felt drawn to serving his country.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "inference_patriotic_service_fit_evidence"


def test_answer_evidence_signal_boosts_causal_belonging_paraphrase() -> None:
    signal = inference_evidence_rerank_signal(
        query="What gave Caroline a sense of belonging?",
        text=(
            "The LGBTQ pride parade made me feel at home in the community "
            "after a difficult week."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "causal_answer_evidence"


def test_answer_evidence_signal_boosts_russian_causal_belonging_paraphrase() -> None:
    signal = inference_evidence_rerank_signal(
        query="Что дало Каролине чувство принадлежности?",
        text=(
            "Прайд помог Каролине почувствовать себя дома в сообществе "
            "и дал ощущение принадлежности."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "causal_answer_evidence"


def test_answer_evidence_signal_penalizes_emotion_context_without_reason_marker() -> None:
    signal = inference_evidence_rerank_signal(
        query="What gave Caroline a sense of belonging?",
        text="Caroline joined an online support group for general planning advice.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "causal_answer_missing_reason_signal"

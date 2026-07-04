from infinity_context_core.application.context_action_roles import action_role_rerank_signal


def test_action_role_supports_lowercase_direct_person_recipient() -> None:
    matched = action_role_rerank_signal(
        query="what did alex promise maria after the atlas call?",
        text="D3:4 Alex promised Maria he would send the Atlas invoice after the call.",
    )
    reversed_roles = action_role_rerank_signal(
        query="what did alex promise maria after the atlas call?",
        text="D3:4 Maria promised Alex she would send the Atlas invoice after the call.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_actor_recipient_reversed"


def test_action_role_does_not_treat_lowercase_direct_object_as_recipient() -> None:
    signal = action_role_rerank_signal(
        query="what did alex send invoice after the atlas call?",
        text="D3:4 Alex sent the invoice after the Atlas call.",
    )

    assert signal.boost > 0
    assert signal.reason == "action_role_actor_match"


def test_action_role_ignores_recency_adjectives_before_nominal_calls() -> None:
    signal = action_role_rerank_signal(
        query="What was my latest call with Alex about?",
        text="Yesterday's call with Alex covered Project Atlas migration risks.",
    )

    assert signal.boost == 0.0
    assert signal.penalty == 0.0
    assert signal.reason == ""


def test_action_role_does_not_treat_reported_subject_as_query_actor() -> None:
    signal = action_role_rerank_signal(
        query="What did Alex promise Maria after the Atlas call?",
        text="D3:4 Alex heard Dana promised Maria she would send the invoice.",
    )

    assert signal.penalty > 0
    assert signal.reason == "action_role_actor_mismatch"


def test_action_role_does_not_treat_reported_subject_as_recipient_actor() -> None:
    signal = action_role_rerank_signal(
        query="Who recommended Becoming Nicole to Melanie?",
        text="D3:4 Melanie heard Caroline recommended Becoming Nicole to Dana.",
    )

    assert signal.boost == 0.0
    assert signal.penalty == 0.0
    assert signal.reason == ""


def test_action_role_boosts_generic_owner_responsibility_evidence() -> None:
    signal = action_role_rerank_signal(
        query="Who is responsible for the Atlas invoice?",
        text="D3:4 Alex is responsible for the Atlas invoice follow-up.",
    )

    assert signal.boost > 0
    assert signal.reason == "action_role_owner_evidence"


def test_action_role_matches_named_owner_responsibility() -> None:
    matched = action_role_rerank_signal(
        query="Is Alex responsible for the Atlas invoice?",
        text="D3:4 Alex is responsible for the Atlas invoice follow-up.",
    )
    mismatch = action_role_rerank_signal(
        query="Is Alex responsible for the Atlas invoice?",
        text="D3:4 Maria is responsible for the Atlas invoice follow-up.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_owner_match"
    assert mismatch.penalty > 0
    assert mismatch.reason == "action_role_owner_mismatch"


def test_action_role_owner_uses_embedded_subject_not_dialogue_speaker() -> None:
    matched = action_role_rerank_signal(
        query="Is Alex responsible for the Atlas invoice?",
        text="D3:4 Maria: Alex is responsible for the Atlas invoice follow-up.",
    )
    reported = action_role_rerank_signal(
        query="Is Alex responsible for the Atlas invoice?",
        text="D3:4 Maria said Alex is responsible for the Atlas invoice follow-up.",
    )
    mismatch = action_role_rerank_signal(
        query="Is Alex responsible for the Atlas invoice?",
        text="D3:4 Maria is responsible for the Atlas invoice follow-up.",
    )
    direct_owner_title = action_role_rerank_signal(
        query="Is Alex responsible for the Atlas invoice?",
        text="Project Atlas invoice owner Alex approved the renewal follow-up.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_owner_match"
    assert reported.boost > 0
    assert reported.reason == "action_role_owner_match"
    assert direct_owner_title.boost > 0
    assert direct_owner_title.reason == "action_role_owner_match"
    assert mismatch.penalty > 0
    assert mismatch.reason == "action_role_owner_mismatch"


def test_action_role_extracts_recommender_from_suggestion_source_query() -> None:
    matched = action_role_rerank_signal(
        query="What book did Melanie read from Caroline's suggestion?",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    reversed_roles = action_role_rerank_signal(
        query="What book did Melanie read from Caroline's suggestion?",
        text="Melanie recommended Becoming Nicole to Caroline.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_actor_recipient_reversed"


def test_action_role_extracts_recommender_from_after_recommended_query() -> None:
    matched = action_role_rerank_signal(
        query="What book did Melanie read after Caroline recommended it?",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    reversed_roles = action_role_rerank_signal(
        query="What book did Melanie read after Caroline recommended it?",
        text="Melanie recommended Becoming Nicole to Caroline.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_actor_recipient_reversed"


def test_action_role_treats_suggested_as_recommendation_evidence() -> None:
    signal = action_role_rerank_signal(
        query="Who suggested Becoming Nicole to Melanie?",
        text="Caroline suggested Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )

    assert signal.boost > 0
    assert signal.reason == "action_role_recipient_match"


def test_action_role_extracts_recipient_from_recommended_that_query() -> None:
    matched = action_role_rerank_signal(
        query="Who recommended that Melanie read Becoming Nicole?",
        text="Caroline recommended that Melanie read Becoming Nicole by Amy Ellis Nutt.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Who recommended that Melanie read Becoming Nicole?",
        text="Melanie recommended that Caroline read Becoming Nicole by Amy Ellis Nutt.",
    )
    wrong_recipient = action_role_rerank_signal(
        query="Who recommended that Melanie read Becoming Nicole?",
        text="Caroline recommended that Dana read Becoming Nicole by Amy Ellis Nutt.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"
    assert wrong_recipient.boost == 0.0
    assert wrong_recipient.penalty == 0.0


def test_action_role_extracts_actor_recipient_from_recommend_object_query() -> None:
    matched = action_role_rerank_signal(
        query="What book did Caroline recommend Melanie read?",
        text="Caroline recommended that Melanie read Becoming Nicole by Amy Ellis Nutt.",
    )
    to_recipient = action_role_rerank_signal(
        query="What book did Caroline recommend Melanie read?",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    reversed_roles = action_role_rerank_signal(
        query="What book did Caroline recommend Melanie read?",
        text="Melanie recommended that Caroline read Becoming Nicole by Amy Ellis Nutt.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_recipient_match"
    assert to_recipient.boost > 0
    assert to_recipient.reason == "action_role_actor_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_actor_recipient_reversed"


def test_action_role_extracts_requested_recipient_from_actor_question() -> None:
    explicit_recipient = action_role_rerank_signal(
        query="Who did Caroline recommend Becoming Nicole to?",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    actor_only = action_role_rerank_signal(
        query="Who did Caroline recommend Becoming Nicole to?",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt.",
    )
    wrong_actor = action_role_rerank_signal(
        query="Who did Caroline recommend Becoming Nicole to?",
        text="Melanie recommended Becoming Nicole to Caroline.",
    )

    assert explicit_recipient.boost > 0
    assert explicit_recipient.reason == "action_role_actor_to_recipient_evidence"
    assert actor_only.penalty > 0
    assert actor_only.reason == "action_role_requested_recipient_missing"
    assert wrong_actor.penalty > 0
    assert wrong_actor.reason == "action_role_actor_mismatch"


def test_action_role_extracts_requested_recipient_with_trailing_context() -> None:
    signal = action_role_rerank_signal(
        query="Who did Caroline recommend Becoming Nicole to during the book club?",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )

    assert signal.boost > 0
    assert signal.reason == "action_role_actor_to_recipient_evidence"


def test_action_role_extracts_requested_direct_recipient_from_actor_question() -> None:
    matched = action_role_rerank_signal(
        query="Who did Alex tell about the Atlas delay?",
        text="D3:4 Alex told Maria about the Atlas delay after the call.",
    )
    actor_only = action_role_rerank_signal(
        query="Who did Alex tell about the Atlas delay?",
        text="D3:4 Alex told the Atlas delay story after the call.",
    )
    wrong_actor = action_role_rerank_signal(
        query="Who did Alex tell about the Atlas delay?",
        text="D3:4 Maria told Alex about the Atlas delay after the call.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert actor_only.penalty > 0
    assert actor_only.reason == "action_role_requested_recipient_missing"
    assert wrong_actor.penalty > 0
    assert wrong_actor.reason == "action_role_actor_mismatch"


def test_action_role_supports_lent_direct_recipient_role() -> None:
    matched = action_role_rerank_signal(
        query="Who lent Alex the camera?",
        text="D3:4 Maria lent Alex the camera after the workshop.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Who lent Alex the camera?",
        text="D3:4 Alex lent Maria the camera after the workshop.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"


def test_action_role_extracts_requested_recipient_for_lend_question() -> None:
    matched = action_role_rerank_signal(
        query="Who did Alex lend the camera to?",
        text="D3:4 Alex lent the camera to Maria after the workshop.",
    )
    actor_only = action_role_rerank_signal(
        query="Who did Alex lend the camera to?",
        text="D3:4 Alex lent the camera after the workshop.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert actor_only.penalty > 0
    assert actor_only.reason == "action_role_requested_recipient_missing"


def test_action_role_extracts_borrow_source_from_from_query() -> None:
    matched = action_role_rerank_signal(
        query="Who did Alex borrow the camera from?",
        text="D3:4 Alex borrowed the camera from Maria after the workshop.",
    )
    possessive_source = action_role_rerank_signal(
        query="Who did Alex borrow the camera from?",
        text="D3:4 Alex borrowed Maria's camera after the workshop.",
    )
    missing_source = action_role_rerank_signal(
        query="Who did Alex borrow the camera from?",
        text="D3:4 Alex borrowed the camera after the workshop.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_transfer_source_evidence"
    assert possessive_source.boost > 0
    assert possessive_source.reason == "action_role_transfer_source_evidence"
    assert missing_source.penalty > 0
    assert missing_source.reason == "action_role_transfer_source_missing"


def test_action_role_treats_lent_to_actor_as_borrow_source_evidence() -> None:
    matched = action_role_rerank_signal(
        query="Who did Alex borrow the camera from?",
        text="D3:4 Maria lent Alex the camera after the workshop.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Who did Alex borrow the camera from?",
        text="D3:4 Alex lent Maria the camera after the workshop.",
    )
    reversed_borrow = action_role_rerank_signal(
        query="Who did Alex borrow the camera from?",
        text="D3:4 Maria borrowed the camera from Alex after the workshop.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_transfer_source_evidence"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_transfer_source_reversed"
    assert reversed_borrow.penalty > 0
    assert reversed_borrow.reason == "action_role_transfer_source_reversed"


def test_action_role_requires_requested_recipient_context_for_task_questions() -> None:
    matched = action_role_rerank_signal(
        query="Who did Alex ask to send the Atlas invoice?",
        text="D3:4 Alex asked Dana to send the Atlas invoice after the call.",
    )
    wrong_context = action_role_rerank_signal(
        query="Who did Alex ask to send the Atlas invoice?",
        text="D3:4 Alex asked Maria to book lunch after the call.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert wrong_context.penalty > 0
    assert wrong_context.reason == "action_role_requested_context_mismatch"


def test_action_role_requires_requested_recipient_context_for_recommendations() -> None:
    matched = action_role_rerank_signal(
        query="Who did Caroline recommend Becoming Nicole to?",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    wrong_context = action_role_rerank_signal(
        query="Who did Caroline recommend Becoming Nicole to?",
        text="Caroline recommended Sula by Toni Morrison to Melanie.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert wrong_context.penalty > 0
    assert wrong_context.reason == "action_role_requested_context_mismatch"


def test_action_role_extracts_direct_recipient_from_subject_question() -> None:
    matched = action_role_rerank_signal(
        query="Who told Maria about the Atlas delay?",
        text="D3:4 Alex told Maria about the Atlas delay after the call.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Who told Maria about the Atlas delay?",
        text="D3:4 Maria told Alex about the Atlas delay after the call.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"


def test_action_role_extracts_direct_communication_recipient() -> None:
    matched = action_role_rerank_signal(
        query="Who did Alex message about the Atlas delay?",
        text="D3:4 Alex messaged Sam about the Atlas delay after the call.",
    )
    object_only = action_role_rerank_signal(
        query="Who did Alex message about the Atlas delay?",
        text="D3:4 Alex messaged the Project Atlas delay summary after the call.",
    )
    wrong_actor = action_role_rerank_signal(
        query="Who did Alex message about the Atlas delay?",
        text="D3:4 Sam messaged Alex about the Atlas delay after the call.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert object_only.penalty > 0
    assert object_only.reason == "action_role_requested_recipient_missing"
    assert wrong_actor.penalty > 0
    assert wrong_actor.reason == "action_role_actor_mismatch"


def test_action_role_extracts_direct_communication_recipient_question() -> None:
    matched = action_role_rerank_signal(
        query="Who messaged Maria about the Atlas delay?",
        text="D3:4 Alex messaged Maria about the Atlas delay after the call.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Who messaged Maria about the Atlas delay?",
        text="D3:4 Maria messaged Alex about the Atlas delay after the call.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"


def test_action_role_extracts_requested_recipient_for_ask_to_do_task() -> None:
    matched = action_role_rerank_signal(
        query="Who did Alex ask to send the Atlas invoice?",
        text="D3:4 Alex asked Maria to send the Atlas invoice after the call.",
    )
    actor_only = action_role_rerank_signal(
        query="Who did Alex ask to send the Atlas invoice?",
        text="D3:4 Alex asked to send the Atlas invoice after the call.",
    )
    wrong_actor = action_role_rerank_signal(
        query="Who did Alex ask to send the Atlas invoice?",
        text="D3:4 Maria asked Alex to send the Atlas invoice after the call.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert actor_only.penalty > 0
    assert actor_only.reason == "action_role_requested_recipient_missing"
    assert wrong_actor.penalty > 0
    assert wrong_actor.reason == "action_role_actor_mismatch"


def test_action_role_extracts_requested_recipient_for_ask_for_object() -> None:
    matched = action_role_rerank_signal(
        query="Who did Alex ask for the Atlas invoice?",
        text="D3:4 Alex asked Maria for the Atlas invoice after the call.",
    )
    actor_only = action_role_rerank_signal(
        query="Who did Alex ask for the Atlas invoice?",
        text="D3:4 Alex asked for the Atlas invoice after the call.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert actor_only.penalty > 0
    assert actor_only.reason == "action_role_requested_recipient_missing"


def test_action_role_extracts_requested_recipient_for_tell_to_do_task() -> None:
    matched = action_role_rerank_signal(
        query="Who did Alex tell to check the Atlas budget?",
        text="D3:4 Alex told Maria to check the Atlas budget after the call.",
    )
    wrong_actor = action_role_rerank_signal(
        query="Who did Alex tell to check the Atlas budget?",
        text="D3:4 Maria told Alex to check the Atlas budget after the call.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert wrong_actor.penalty > 0
    assert wrong_actor.reason == "action_role_actor_mismatch"


def test_action_role_extracts_short_call_recipient_question() -> None:
    matched = action_role_rerank_signal(
        query="Who did Alex call?",
        text="D3:4 Alex called Sam.",
    )
    wrong_actor = action_role_rerank_signal(
        query="Who did Alex call?",
        text="D3:4 Sam called Alex.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert wrong_actor.penalty > 0
    assert wrong_actor.reason == "action_role_actor_mismatch"


def test_action_role_extracts_requested_recipient_from_to_whom_question() -> None:
    signal = action_role_rerank_signal(
        query="To whom did Caroline suggest Becoming Nicole?",
        text="Caroline suggested Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )

    assert signal.boost > 0
    assert signal.reason == "action_role_actor_to_recipient_evidence"


def test_action_role_extracts_requested_recipient_from_passive_actor_question() -> None:
    active_evidence = action_role_rerank_signal(
        query="Who was told about the Atlas delay by Alex?",
        text="D3:4 Alex told Maria about the Atlas delay after the call.",
    )
    passive_evidence = action_role_rerank_signal(
        query="Who was told about the Atlas delay by Alex?",
        text="D3:4 Maria was told about the Atlas delay by Alex after the call.",
    )
    wrong_actor = action_role_rerank_signal(
        query="Who was told about the Atlas delay by Alex?",
        text="D3:4 Sam told Alex about the Atlas delay after the call.",
    )

    assert active_evidence.boost > 0
    assert active_evidence.reason == "action_role_actor_to_recipient_evidence"
    assert passive_evidence.boost > 0
    assert passive_evidence.reason == "action_role_actor_to_recipient_evidence"
    assert wrong_actor.penalty > 0
    assert wrong_actor.reason == "action_role_actor_mismatch"


def test_action_role_extracts_actor_from_passive_recipient_question() -> None:
    active_evidence = action_role_rerank_signal(
        query="Who was Maria told about the Atlas delay by?",
        text="D3:4 Alex told Maria about the Atlas delay after the call.",
    )
    passive_evidence = action_role_rerank_signal(
        query="Who was Maria told about the Atlas delay by?",
        text="D3:4 Maria was told about the Atlas delay by Alex after the call.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Who was Maria told about the Atlas delay by?",
        text="D3:4 Maria told Alex about the Atlas delay after the call.",
    )

    assert active_evidence.boost > 0
    assert active_evidence.reason == "action_role_recipient_match"
    assert passive_evidence.boost > 0
    assert passive_evidence.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"


def test_action_role_supports_russian_recommendation_direct_recipient() -> None:
    matched = action_role_rerank_signal(
        query="Кто посоветовал Мелани прочитать Becoming Nicole?",
        text="Кэролайн посоветовала Мелани прочитать Becoming Nicole.",
    )
    mismatch = action_role_rerank_signal(
        query="Кто посоветовал Мелани прочитать Becoming Nicole?",
        text="Мелани посоветовала Кэролайн прочитать Becoming Nicole.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert mismatch.penalty > 0
    assert mismatch.reason == "action_role_recipient_mismatch"


def test_action_role_supports_russian_whose_advice_recipient() -> None:
    matched = action_role_rerank_signal(
        query="По чьему совету Мелани прочитала Becoming Nicole?",
        text="Кэролайн посоветовала Мелани прочитать Becoming Nicole.",
    )
    mismatch = action_role_rerank_signal(
        query="По чьему совету Мелани прочитала Becoming Nicole?",
        text="Мелани посоветовала Кэролайн прочитать Becoming Nicole.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert mismatch.penalty > 0
    assert mismatch.reason == "action_role_recipient_mismatch"


def test_action_role_extracts_requested_recipient_from_russian_question() -> None:
    matched = action_role_rerank_signal(
        query="Кому Кэролайн посоветовала прочитать Becoming Nicole?",
        text="Кэролайн посоветовала Мелани прочитать Becoming Nicole.",
    )
    mismatch = action_role_rerank_signal(
        query="Кому Кэролайн посоветовала прочитать Becoming Nicole?",
        text="Мелани посоветовала Кэролайн прочитать Becoming Nicole.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert mismatch.penalty > 0
    assert mismatch.reason == "action_role_actor_mismatch"


def test_action_role_extracts_direct_recipient_from_russian_actor_question() -> None:
    matched = action_role_rerank_signal(
        query="Кому Алекс сказал про задержку Atlas?",
        text="Алекс сказал Марии про задержку Atlas после созвона.",
    )
    mismatch = action_role_rerank_signal(
        query="Кому Алекс сказал про задержку Atlas?",
        text="Мария сказала Алексу про задержку Atlas после созвона.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert mismatch.penalty > 0
    assert mismatch.reason == "action_role_actor_mismatch"


def test_action_role_extracts_russian_direct_recipient_subject_question() -> None:
    matched = action_role_rerank_signal(
        query="Кто сказал Марии про задержку Atlas?",
        text="Алекс сказал Марии про задержку Atlas после созвона.",
    )
    unrelated = action_role_rerank_signal(
        query="Кто сказал Марии про задержку Atlas?",
        text="Алекс сказал Дане про задержку Atlas после созвона.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert unrelated.boost == 0.0


def test_action_role_extracts_recipient_from_whose_suggestion_query() -> None:
    matched = action_role_rerank_signal(
        query="Whose suggestion did Melanie follow when she read Becoming Nicole?",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Whose suggestion did Melanie follow when she read Becoming Nicole?",
        text="Melanie recommended Becoming Nicole to Caroline.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"


def test_action_role_extracts_recipient_from_gave_suggestion_query() -> None:
    direct_recipient = action_role_rerank_signal(
        query="Who gave Melanie the suggestion to read Becoming Nicole?",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    preposition_recipient = action_role_rerank_signal(
        query="Who offered the recommendation to Melanie?",
        text="Caroline suggested Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    mismatch = action_role_rerank_signal(
        query="Who gave Melanie the suggestion to read Becoming Nicole?",
        text="Caroline suggested Becoming Nicole by Amy Ellis Nutt to Dana.",
    )

    assert direct_recipient.boost > 0
    assert direct_recipient.reason == "action_role_recipient_match"
    assert preposition_recipient.boost > 0
    assert preposition_recipient.reason == "action_role_recipient_match"
    assert mismatch.boost == 0.0
    assert mismatch.penalty == 0.0


def test_action_role_extracts_actor_from_nominal_decision_query() -> None:
    matched = action_role_rerank_signal(
        query="What decision did Caroline make after the interview?",
        text="D19:3 Caroline made the decision to continue adoption after the agency interview.",
    )
    mismatch = action_role_rerank_signal(
        query="What decision did Caroline make after the interview?",
        text="D19:3 Dana made the decision to continue adoption after the agency interview.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_match"
    assert mismatch.penalty > 0
    assert mismatch.reason == "action_role_actor_mismatch"


def test_action_role_extracts_recipient_from_nominal_promise_query() -> None:
    matched = action_role_rerank_signal(
        query="What promise did Alex make to Maria after the Atlas call?",
        text="D3:4 Alex made a promise to Maria to send the Atlas invoice after the call.",
    )
    reversed_roles = action_role_rerank_signal(
        query="What promise did Alex make to Maria after the Atlas call?",
        text="D3:4 Maria made a promise to Alex to send the Atlas invoice after the call.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_actor_recipient_reversed"


def test_action_role_preserves_introduced_object_target_order() -> None:
    matched = action_role_rerank_signal(
        query="Who introduced Maria to Alex?",
        text="Caroline introduced Maria to Alex at the Atlas meetup.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Who introduced Maria to Alex?",
        text="Caroline introduced Alex to Maria at the Atlas meetup.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"


def test_action_role_preserves_russian_introduced_object_target_order() -> None:
    matched = action_role_rerank_signal(
        query="Кто познакомил Марию с Алексом?",
        text="Кэролайн познакомила Марию с Алексом на встрече Atlas.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Кто познакомил Марию с Алексом?",
        text="Кэролайн познакомила Алекса с Марией на встрече Atlas.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"


def test_action_role_preserves_introduced_object_for_requested_recipient() -> None:
    matched = action_role_rerank_signal(
        query="Who did Caroline introduce Maria to?",
        text="Caroline introduced Maria to Alex at the Atlas meetup.",
    )
    wrong_object = action_role_rerank_signal(
        query="Who did Caroline introduce Maria to?",
        text="Caroline introduced Alex to Maria at the Atlas meetup.",
    )
    wrong_actor = action_role_rerank_signal(
        query="Who did Caroline introduce Maria to?",
        text="Dana introduced Maria to Alex at the Atlas meetup.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert wrong_object.penalty > 0
    assert wrong_object.reason == "action_role_requested_recipient_missing"
    assert wrong_actor.penalty > 0
    assert wrong_actor.reason == "action_role_actor_mismatch"


def test_action_role_extracts_information_source_from_heard_from_query() -> None:
    matched = action_role_rerank_signal(
        query="Who did John hear inspiring stories from?",
        text="John heard inspiring stories from an elderly veteran named Samuel.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Who did John hear inspiring stories from?",
        text="Samuel heard inspiring stories from John.",
    )
    actor_as_source = action_role_rerank_signal(
        query="Who did John hear inspiring stories from?",
        text="John told Samuel inspiring stories after the memorial event.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_information_source_evidence"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_information_source_reversed"
    assert actor_as_source.penalty > 0
    assert actor_as_source.reason == "action_role_information_source_reversed"


def test_action_role_extracts_information_source_from_direct_told_evidence() -> None:
    signal = action_role_rerank_signal(
        query="Who did Maria learn about Atlas from?",
        text="Caroline told Maria about the Atlas migration risk.",
    )

    assert signal.boost > 0
    assert signal.reason == "action_role_information_source_evidence"


def test_action_role_extracts_russian_information_source() -> None:
    matched = action_role_rerank_signal(
        query="От кого Мария узнала про Atlas?",
        text="Мария узнала про Atlas от Кэролайн после звонка.",
    )
    reversed_roles = action_role_rerank_signal(
        query="От кого Мария узнала про Atlas?",
        text="Кэролайн узнала про Atlas от Марии после звонка.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_information_source_evidence"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_information_source_reversed"


def test_action_role_extracts_support_recipient_role() -> None:
    matched = action_role_rerank_signal(
        query="Who helped Maria with the Atlas migration?",
        text="Caroline helped Maria with the Atlas migration after the workshop.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Who helped Maria with the Atlas migration?",
        text="Maria helped Caroline with the Atlas migration after the workshop.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"


def test_action_role_extracts_joined_participant_role() -> None:
    matched = action_role_rerank_signal(
        query="Who joined Maria at the fundraiser?",
        text="Alex joined Maria at the fundraiser after the volunteer shift.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Who joined Maria at the fundraiser?",
        text="Maria joined Alex at the fundraiser after the volunteer shift.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"


def test_action_role_treats_met_as_reciprocal_participant_evidence() -> None:
    direct = action_role_rerank_signal(
        query="Who met Maria at the shelter?",
        text="Alex met Maria at the shelter orientation.",
    )
    reciprocal = action_role_rerank_signal(
        query="Who met Maria at the shelter?",
        text="Maria met Alex at the shelter orientation.",
    )
    actor_question = action_role_rerank_signal(
        query="Who did Maria meet at the shelter?",
        text="Alex met Maria at the shelter orientation.",
    )

    assert direct.boost > 0
    assert direct.reason == "action_role_recipient_match"
    assert reciprocal.boost > 0
    assert reciprocal.reason == "action_role_recipient_match"
    assert actor_question.boost > 0
    assert actor_question.reason == "action_role_actor_to_recipient_evidence"


def test_action_role_extracts_activity_companion_participant() -> None:
    matched = action_role_rerank_signal(
        query="Who visited Spain with Maria?",
        text="Alex visited Spain with Maria after the conference.",
    )
    missing_companion = action_role_rerank_signal(
        query="Who visited Spain with Maria?",
        text="Maria visited Spain after the conference.",
    )
    mentioned_person = action_role_rerank_signal(
        query="Who visited Spain with Maria?",
        text="Alex visited Spain alone after Maria mentioned the conference.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_companion_match"
    assert missing_companion.penalty > 0
    assert missing_companion.reason == "action_role_companion_missing"
    assert mentioned_person.boost == 0.0
    assert mentioned_person.penalty == 0.0


def test_action_role_extracts_support_requested_recipient() -> None:
    matched = action_role_rerank_signal(
        query="Who did Caroline help with the Atlas migration?",
        text="Caroline helped Maria with the Atlas migration after the workshop.",
    )
    actor_only = action_role_rerank_signal(
        query="Who did Caroline help with the Atlas migration?",
        text="Caroline helped with the Atlas migration after the workshop.",
    )
    wrong_actor = action_role_rerank_signal(
        query="Who did Caroline help with the Atlas migration?",
        text="Maria helped Caroline with the Atlas migration after the workshop.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_actor_to_recipient_evidence"
    assert actor_only.penalty > 0
    assert actor_only.reason == "action_role_requested_recipient_missing"
    assert wrong_actor.penalty > 0
    assert wrong_actor.reason == "action_role_actor_mismatch"


def test_action_role_extracts_russian_support_recipient_role() -> None:
    matched = action_role_rerank_signal(
        query="Кто помог Марии с Atlas?",
        text="Кэролайн помогла Марии с Atlas после звонка.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Кто помог Марии с Atlas?",
        text="Мария помогла Кэролайн с Atlas после звонка.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"


def test_action_role_penalizes_negated_support_evidence() -> None:
    negated = action_role_rerank_signal(
        query="Who helped Maria with the Atlas migration?",
        text="Caroline did not help Maria with the Atlas migration after the workshop.",
    )
    positive = action_role_rerank_signal(
        query="Who helped Maria with the Atlas migration?",
        text="Caroline not only helped Maria with the Atlas migration, she owned follow-up.",
    )

    assert negated.penalty > 0
    assert negated.reason == "action_role_negated_evidence"
    assert positive.boost > 0
    assert positive.reason == "action_role_recipient_match"


def test_action_role_penalizes_negated_requested_recipient_context() -> None:
    negated = action_role_rerank_signal(
        query="Who did Alex ask to send the Atlas invoice?",
        text="Alex did not ask Dana to send the Atlas invoice after the call.",
    )

    assert negated.penalty > 0
    assert negated.reason == "action_role_negated_evidence"


def test_action_role_penalizes_russian_negated_support_evidence() -> None:
    negated = action_role_rerank_signal(
        query="Кто помог Марии с Atlas?",
        text="Кэролайн не помогла Марии с Atlas после звонка.",
    )

    assert negated.penalty > 0
    assert negated.reason == "action_role_negated_evidence"


def test_action_role_extracts_support_presence_recipient() -> None:
    matched = action_role_rerank_signal(
        query="Who was there for Caroline after the interview?",
        text="Melanie was there for Caroline after the agency interview.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Who was there for Caroline after the interview?",
        text="Caroline was there for Melanie after the agency interview.",
    )
    negated = action_role_rerank_signal(
        query="Who was there for Caroline after the interview?",
        text="Melanie was not there for Caroline after the agency interview.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"
    assert negated.penalty > 0
    assert negated.reason == "action_role_negated_evidence"


def test_action_role_extracts_russian_support_presence_recipient() -> None:
    matched = action_role_rerank_signal(
        query="Кто был рядом с Марией после звонка?",
        text="Кэролайн была рядом с Марией после звонка.",
    )
    reversed_roles = action_role_rerank_signal(
        query="Кто был рядом с Марией после звонка?",
        text="Мария была рядом с Кэролайн после звонка.",
    )
    negated = action_role_rerank_signal(
        query="Кто был рядом с Марией после звонка?",
        text="Кэролайн не была рядом с Марией после звонка.",
    )

    assert matched.boost > 0
    assert matched.reason == "action_role_recipient_match"
    assert reversed_roles.penalty > 0
    assert reversed_roles.reason == "action_role_recipient_mismatch"
    assert negated.penalty > 0
    assert negated.reason == "action_role_negated_evidence"

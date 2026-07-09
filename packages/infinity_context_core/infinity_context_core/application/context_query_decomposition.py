"""Deterministic decomposition of compound memory queries."""

from __future__ import annotations

from infinity_context_core.application.context_conversation_counterparty import (
    requests_conversation_recency,
    requests_conversation_topic,
)
from infinity_context_core.application.context_query_decomposition_answer_policy import (
    _ACTION_ROLE_TERMS,
    _ARTIFACT_TERMS,
    _IDENTITY_ATTRIBUTE_TERMS,
    _SOURCE_TERMS,
    _TEMPORAL_ANSWER_TERMS,
    _requests_absence_contrast,
    _requests_ally_support_inference,
    _requests_community_membership_inference,
    _requests_comparison_preference,
    _requests_counterfactual_evidence,
    _requests_emotion_cause,
    _requests_evidence_reason,
    _requests_gotcha_failure_context,
    _requests_inference_current_preference_or_goal,
    _requests_knowledge_update_current,
    _requests_knowledge_update_previous,
    _requests_non_inference_career_goal,
    _requests_relationship_status,
    _requests_state_transition_context,
)
from infinity_context_core.application.context_query_decomposition_contracts import (
    QueryDecomposition,
    QueryDecompositionPlan,
)
from infinity_context_core.application.context_query_decomposition_event_policy import (
    _DEADLINE_TERMS,
    _conversation_recency_tail,
    _event_sequence_tail,
    _has_event_focus,
    _requests_conversation_counterparty,
    _requests_followup_task_context,
    _requests_lgbtq_event_slot_aggregation,
    _requests_recommendation_source_context,
    _requests_relative_time_conversation_recency,
    _requests_relocation_context,
    _requests_relocation_destination_context,
)
from infinity_context_core.application.context_query_decomposition_inventory_policy import (
    _ATTRIBUTE_AGGREGATION_TERMS,
    _QUANTITY_COUNT_TERMS,
    _attribute_aggregation_tail,
    _inventory_list_tail,
    _requests_activity_participation,
    _requests_commonality_context,
    _requests_inventory_list_context,
)
from infinity_context_core.application.context_query_decomposition_shared import (
    _INFERENCE_TERMS,
    _append_candidate,
    _append_clause_decompositions,
    _compose_query,
    _identity_terms,
    _normalize_query,
    _query_variant_set,
    _raw_query_tokens,
    _salient_terms,
)
from infinity_context_core.application.context_query_duration import (
    activity_duration_tail,
    requests_activity_duration_context,
)
from infinity_context_core.application.context_query_frequency import (
    frequency_recurrence_tail,
    requests_frequency_recurrence_context,
)
from infinity_context_core.application.context_query_intent import (
    QueryAnchorIntent,
    build_query_anchor_intent,
)
from infinity_context_core.application.context_query_state_transition import (
    state_transition_query_variants,
)
from infinity_context_core.application.context_query_support_role import (
    requests_support_role_fit,
    support_role_query_variants,
)
from infinity_context_core.application.context_query_workflow_intent import (
    gotcha_failure_query_variants,
    workflow_commitment_query_variants,
)
from infinity_context_core.application.context_temporal_query import (
    TemporalQueryIntent,
    build_temporal_query_intent,
)

_MAX_DECOMPOSITIONS = 6

def build_query_decomposition_plan(
    query: str,
    *,
    anchor_intent: QueryAnchorIntent | None = None,
    temporal_intent: TemporalQueryIntent | None = None,
) -> QueryDecompositionPlan:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return QueryDecompositionPlan(original_query=query, decompositions=())
    anchor_intent = anchor_intent or build_query_anchor_intent(query)
    temporal_intent = temporal_intent or build_temporal_query_intent(query)
    variants = _query_variant_set(query)
    variants = frozenset(
        (
            *variants,
            *gotcha_failure_query_variants(query),
            *state_transition_query_variants(query),
            *support_role_query_variants(query),
            *workflow_commitment_query_variants(query),
        )
    )
    raw_tokens = frozenset(_raw_query_tokens(query))
    identities = _identity_terms(query, anchor_intent)
    salient_terms = _salient_terms(query, identities=identities)
    requests_relocation_context = _requests_relocation_context(
        query=normalized_query,
        variants=variants,
    )
    requests_relocation_destination_context = _requests_relocation_destination_context(
        variants=variants,
    )
    candidates: list[QueryDecomposition] = []
    _append_clause_decompositions(candidates, query=query, identities=identities)
    if _has_event_focus(anchor_intent, variants) and not (
        requests_relocation_context or requests_relocation_destination_context
    ):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "event conversation meeting call chat message dm transcript "
                    "notes discussed mentioned decision action item follow up"
                ),
            ),
            reason="decomposition_event_context",
        )
    if _requests_lgbtq_event_slot_aggregation(variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "lgbtq pride parade pride march went attended participated "
                    "rainbow flags community belonged accepted happy equality"
                ),
            ),
            reason="decomposition_lgbtq_pride_event",
        )
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "lgbtq support group attended went transgender stories powerful "
                    "inspiring accepted courage embrace community"
                ),
            ),
            reason="decomposition_lgbtq_support_group_event",
        )
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "school event speech talk spoke gave transgender journey students "
                    "involved lgbtq community awareness inclusion"
                ),
            ),
            reason="decomposition_lgbtq_school_speech_event",
        )
    if requests_relocation_destination_context:
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "relocation moved move relocated to destination new current "
                    "home country city settled lives now timeline"
                ),
            ),
            reason="decomposition_relocation_destination",
        )
    if requests_relocation_context:
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "relocation moved move relocated from origin previous home "
                    "country city lived before timeline"
                ),
            ),
            reason="decomposition_relocation_context",
        )
    if temporal_intent.requests_change:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "changed updated current previous before after superseded "
                    "replaced difference decision"
                ),
            ),
            reason="decomposition_temporal_change",
        )
    if _requests_state_transition_context(variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "state transition changed switched replaced migrated from to "
                    "previous old current new active final selected superseded "
                    "no longer valid replacement replaced by before after"
                ),
            ),
            reason="decomposition_state_transition",
        )
    if temporal_intent.after_event or temporal_intent.before_event:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                _event_sequence_tail(temporal_intent),
            ),
            reason="decomposition_event_sequence",
        )
    if temporal_intent.relative_time_hints:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "event temporal time window occurred capture transcript "
                    "notes meeting call chat message "
                    f"{' '.join(temporal_intent.relative_time_hints)}"
                ),
            ),
            reason="decomposition_relative_time",
        )
    if _requests_knowledge_update_current(
        variants=variants,
        temporal_intent=temporal_intent,
    ):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "current latest active final decided chose selected switched "
                    "recommended preferred should use provider tool model option "
                    "engine database service retrieval valid not stale superseded old"
                ),
            ),
            reason="decomposition_knowledge_update_current",
        )
    if _requests_knowledge_update_previous(
        query=normalized_query,
        variants=variants,
        temporal_intent=temporal_intent,
    ):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "previous old stale outdated superseded no longer valid "
                    "not current replaced deprecated expired before review"
                ),
            ),
            reason="decomposition_knowledge_update_previous",
        )
    if variants.intersection(_TEMPORAL_ANSWER_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "when date day time session date weekday monday tuesday "
                    "wednesday thursday friday saturday sunday calendar occurred"
                ),
            ),
            reason="decomposition_temporal_answer",
        )
    if variants.intersection(_ARTIFACT_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "artifact file screenshot image video audio document ocr "
                    "transcript detected text keyframe source"
                ),
            ),
            reason="decomposition_artifact_evidence",
        )
    if variants.intersection(_SOURCE_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                "source citation evidence file artifact reference provenance",
            ),
            reason="decomposition_source_evidence",
        )
    if _requests_emotion_cause(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "feeling emotion felt feel accepted acceptance belonged belonging "
                    "sense of belonging at home community welcomed pride parade "
                    "support group powerful proud empowering school speech talk "
                    "journey upset sad comfort reason because event experience"
                ),
            ),
            reason="decomposition_emotion_cause",
        )
    if _requests_evidence_reason(query):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "reason evidence because observed mentioned showed indicates "
                    "supporting fact source citation quote explanation why"
                ),
            ),
            reason="decomposition_evidence_reason",
        )
    if _requests_gotcha_failure_context(variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "gotcha pitfall caveat known issue known problem failure "
                    "failed error broke blocked blocker risk warning workaround "
                    "root cause troubleshooting avoid do not repeat next time "
                    "prerequisite limitation trap"
                ),
            ),
            reason="decomposition_gotcha_failure",
        )
    if _requests_absence_contrast(query):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "mentioned did not mention absent instead rather than without "
                    "contrast alternative named pet cat dog hamster evidence"
                ),
            ),
            reason="decomposition_absence_contrast",
        )
    if _requests_community_membership_inference(variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "self identification identify identified identifies refers herself "
                    "himself themself as member part belong belongs belonging lgbtq "
                    "queer community pride accepted"
                ),
            ),
            reason="decomposition_community_membership_evidence",
        )
    requests_ally_support = _requests_ally_support_inference(variants=variants)
    if requests_ally_support:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "ally allies supportive support acceptance encouraging kind words "
                    "rights inclusion respected transition transgender trans lgbtq "
                    "community care help advocated stood up"
                ),
            ),
            reason="decomposition_ally_support_evidence",
        )
    if raw_tokens.intersection(_IDENTITY_ATTRIBUTE_TERMS) and not requests_ally_support:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "identity gender pronouns transgender trans woman transition "
                    "true self accepted belongs community support group pride"
                ),
            ),
            reason="decomposition_identity_attribute",
        )
    if _requests_relationship_status(
        raw_tokens=raw_tokens,
        variants=variants,
        identities=identities,
    ):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "relationship status single parent partner spouse married "
                    "dating breakup friends family mentors support system kids "
                    "children challenge make family отношения статус друзья дружба "
                    "партнер супруг семья вместе"
                ),
            ),
            reason="decomposition_relationship_status",
        )
    if variants.intersection(_ACTION_ROLE_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "decision decided promised promise recommendation recommended "
                    "asked assigned approved sent gave told actor recipient speaker "
                    "dialogue quote transcript outcome commitment next step"
                ),
            ),
            reason="decomposition_action_role",
        )
    if _requests_conversation_counterparty(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "conversation counterparty participant with to from talked spoke "
                    "met called messaged texted chatted discussed dm meeting call "
                    "speaker recipient person name about project topic"
                ),
            ),
            reason="decomposition_conversation_counterparty",
        )
    if requests_conversation_recency(query) or _requests_relative_time_conversation_recency(
        raw_tokens=raw_tokens,
        variants=variants,
        temporal_intent=temporal_intent,
    ):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                _conversation_recency_tail(raw_tokens=raw_tokens, variants=variants),
            ),
            reason="decomposition_conversation_recency",
        )
    if requests_conversation_topic(query):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "conversation topic subject about discussed talked spoke chatted "
                    "agenda context project decision plan issue question outcome "
                    "speaker turn transcript"
                ),
            ),
            reason="decomposition_conversation_topic",
        )
    if _requests_recommendation_source_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "recommendation suggestion advice recommended suggested advised "
                    "source actor recipient to from because of followed read watched "
                    "tried used provenance who whom whose"
                ),
            ),
            reason="decomposition_recommendation_source",
        )
    if variants.intersection(_DEADLINE_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "deadline due date target date schedule milestone timeline "
                    "deliverable overdue upcoming commitment action item follow up "
                    "meeting call decision promised agreed"
                ),
            ),
            reason="decomposition_deadline_commitment",
        )
    if _requests_followup_task_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "action item task todo follow up next step reminder assigned "
                    "owner responsible assignee commitment promised due date deadline "
                    "meeting call decision status"
                ),
            ),
            reason="decomposition_followup_task",
        )
    if _requests_counterfactual_evidence(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "counterfactual hypothetical would likely past behavior "
                    "preference trait supporting evidence observed mentioned "
                    "enjoyed disliked avoided interested supportive acceptance "
                    "similar situation"
                ),
            ),
            reason="decomposition_counterfactual_evidence",
        )
    if requests_support_role_fit(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "support role fit mentor mentoring guidance advice coach "
                    "volunteer counseling counselor listened comfort empathy "
                    "patient helped accepted safe trust similar issues reliable "
                    "responsible care confide confided open opened opening private "
                    "sensitive personal anxiety struggles"
                ),
            ),
            reason="decomposition_support_role_fit",
        )
    if variants.intersection(_INFERENCE_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "inference supporting evidence likely would considered "
                    "observed mentioned indicates preference trait decision reason "
                    "support supportive encouraging acceptance care help"
                ),
            ),
            reason="decomposition_inference_support",
        )
        if _requests_inference_current_preference_or_goal(
            raw_tokens=raw_tokens,
            variants=variants,
        ):
            _append_candidate(
                candidates,
                query=_compose_query(
                    (*identities, *salient_terms),
                    (
                        "current goal future plan next steps figure out wants decided "
                        "committed lease contract signed stay local job role school "
                        "program semester deadline career option counseling counselor "
                        "mental health jobs preference interested recently now "
                        "adoption family children kids home roof agency interview "
                        "build career activity service country office military move back soon"
                    ),
                ),
                reason="decomposition_current_preference_or_goal",
            )
    if _requests_non_inference_career_goal(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "current career path goal decided pursue education options "
                    "counseling counselor mental health jobs work career option "
                    "next steps figure out looking into"
                ),
            ),
            reason="decomposition_current_preference_or_goal",
        )
    if _requests_comparison_preference(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "comparison preference choice option alternative likes dislikes "
                    "interested more less rather prefer similar difference evidence"
                ),
            ),
            reason="decomposition_comparison_preference",
        )
    if _requests_activity_participation(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "activities hobbies activity partake participate observed "
                    "painting swimming swim pottery class camping running creative "
                    "outdoors exercise family kids fam weekend unplug hang therapy "
                    "therapeutic photo picture image visual query take look"
                ),
            ),
            reason="decomposition_activity_participation",
        )
    if _requests_inventory_list_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                _inventory_list_tail(variants),
            ),
            reason="decomposition_inventory_list",
        )
    if _requests_commonality_context(identities=identities, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "common shared both mutual same similar overlap interests hobbies "
                    "activities enjoy like love prefer painting camping hiking music "
                    "books games food art evidence"
                ),
            ),
            reason="decomposition_commonality",
        )
    if requests_activity_duration_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                activity_duration_tail(variants),
            ),
            reason="decomposition_activity_duration",
        )
    if variants.intersection(_QUANTITY_COUNT_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "count number total quantity amount many much times "
                    "one two three four five six seven eight nine ten "
                    "once twice couple several multiple"
                ),
            ),
            reason="decomposition_quantity_count",
        )
    if requests_frequency_recurrence_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                frequency_recurrence_tail(variants),
            ),
            reason="decomposition_frequency_recurrence",
        )
    if variants.intersection(_ATTRIBUTE_AGGREGATION_TERMS) and not variants.intersection(
        _QUANTITY_COUNT_TERMS
    ):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                _attribute_aggregation_tail(variants),
            ),
            reason="decomposition_attribute_aggregation",
        )
    return QueryDecompositionPlan(
        original_query=query,
        decompositions=tuple(candidates[:_MAX_DECOMPOSITIONS]),
    )

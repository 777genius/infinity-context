"""Compatibility facade for deterministic domain rerank signals."""

from __future__ import annotations

from infinity_context_core.application.context_aggregation_rerank import (
    aggregation_evidence_rerank_signal as aggregation_evidence_rerank_signal,
)
from infinity_context_core.application.context_aggregation_rerank import (
    has_multi_evidence_aggregation_candidate as has_multi_evidence_aggregation_candidate,
)
from infinity_context_core.application.context_commonality_rerank import (
    commonality_rerank_signal as commonality_rerank_signal,
)
from infinity_context_core.application.context_commonality_rerank import (
    commonality_who_else_anchor_override as commonality_who_else_anchor_override,
)
from infinity_context_core.application.context_commonality_rerank import (
    family_hike_detail_rerank_signal as family_hike_detail_rerank_signal,
)
from infinity_context_core.application.context_commonality_rerank import (
    temporal_camping_detail_rerank_signal as temporal_camping_detail_rerank_signal,
)
from infinity_context_core.application.context_domain_rerank_types import (
    DomainRerankSignal as DomainRerankSignal,
)
from infinity_context_core.application.context_identity_fact_rerank import (
    age_birthday_rerank_signal as age_birthday_rerank_signal,
)
from infinity_context_core.application.context_identity_fact_rerank import (
    beach_or_mountains_rerank_signal as beach_or_mountains_rerank_signal,
)
from infinity_context_core.application.context_identity_fact_rerank import (
    birthplace_rerank_signal as birthplace_rerank_signal,
)
from infinity_context_core.application.context_identity_fact_rerank import (
    item_purchase_rerank_signal as item_purchase_rerank_signal,
)
from infinity_context_core.application.context_identity_fact_rerank import (
    post_event_emotion_rerank_signal as post_event_emotion_rerank_signal,
)
from infinity_context_core.application.context_identity_fact_rerank import (
    symbol_importance_rerank_signal as symbol_importance_rerank_signal,
)
from infinity_context_core.application.context_lifecycle_rerank import (
    current_state_rerank_signal as current_state_rerank_signal,
)
from infinity_context_core.application.context_lifecycle_rerank import (
    event_sequence_rerank_signal as event_sequence_rerank_signal,
)
from infinity_context_core.application.context_lifecycle_rerank import (
    relationship_duration_rerank_signal as relationship_duration_rerank_signal,
)
from infinity_context_core.application.context_lifecycle_rerank import (
    relationship_origin_rerank_signal as relationship_origin_rerank_signal,
)
from infinity_context_core.application.context_lifecycle_rerank import (
    relationship_status_rerank_signal as relationship_status_rerank_signal,
)
from infinity_context_core.application.context_lifecycle_rerank import (
    state_transition_rerank_signal as state_transition_rerank_signal,
)
from infinity_context_core.application.context_preference_goal_rerank import (
    current_goal_rerank_signal as current_goal_rerank_signal,
)
from infinity_context_core.application.context_preference_goal_rerank import (
    lifestyle_recommendation_rerank_signal as lifestyle_recommendation_rerank_signal,
)
from infinity_context_core.application.context_preference_goal_rerank import (
    positive_preference_rerank_signal as positive_preference_rerank_signal,
)
from infinity_context_core.application.context_preference_goal_rerank import (
    recommendation_followup_rerank_signal as recommendation_followup_rerank_signal,
)
from infinity_context_core.application.context_social_inventory_rerank import (
    inventory_list_rerank_signal as inventory_list_rerank_signal,
)
from infinity_context_core.application.context_social_inventory_rerank import (
    support_network_rerank_signal as support_network_rerank_signal,
)

__all__ = (
    "DomainRerankSignal",
    "age_birthday_rerank_signal",
    "aggregation_evidence_rerank_signal",
    "beach_or_mountains_rerank_signal",
    "birthplace_rerank_signal",
    "commonality_rerank_signal",
    "commonality_who_else_anchor_override",
    "current_goal_rerank_signal",
    "current_state_rerank_signal",
    "event_sequence_rerank_signal",
    "family_hike_detail_rerank_signal",
    "has_multi_evidence_aggregation_candidate",
    "inventory_list_rerank_signal",
    "item_purchase_rerank_signal",
    "lifestyle_recommendation_rerank_signal",
    "positive_preference_rerank_signal",
    "post_event_emotion_rerank_signal",
    "recommendation_followup_rerank_signal",
    "relationship_duration_rerank_signal",
    "relationship_origin_rerank_signal",
    "relationship_status_rerank_signal",
    "state_transition_rerank_signal",
    "support_network_rerank_signal",
    "symbol_importance_rerank_signal",
    "temporal_camping_detail_rerank_signal",
)

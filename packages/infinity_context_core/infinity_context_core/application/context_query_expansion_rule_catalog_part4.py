"""Static query expansion rule catalog part 4."""

from __future__ import annotations

from infinity_context_core.application import context_query_expansion_rule_terms as _terms

EXPANSION_RULES_PART_4: tuple[tuple[frozenset[str], str, str], ...] = (
    (
            frozenset({"artist", "seen"}),
            (
                "musical artists bands saw seen live concert show festival performance "
                "performed summer sounds band pop dancing singing lively fun"
            ),
            "music_artist_band_bridge",
        ),
    (
            frozenset({"band", "seen"}),
            (
                "musical artists bands saw seen live concert show festival performance "
                "performed summer sounds band pop dancing singing lively fun"
            ),
            "music_artist_band_bridge",
        ),
    (
            frozenset({"artist", "band"}),
            "matt patterson talented voice amazing singer named performer artist",
            "music_artist_answer_bridge",
        ),
    (
            frozenset({"artist", "seen"}),
            "matt patterson talented voice amazing singer named performer artist",
            "music_artist_answer_bridge",
        ),
    (
            frozenset({"band", "seen"}),
            "matt patterson talented voice amazing singer named performer artist",
            "music_artist_answer_bridge",
        ),
    (
            frozenset({"shoe", "used"}),
            ("new shoes purple walking running used for walk run love color sneakers"),
            "shoe_usage_bridge",
        ),
    (
            frozenset({"reason", "running"}),
            (
                "running run farther longer de-stress destress clear mind headspace "
                "mood boost shoes purple walking or running what got into running"
            ),
            "running_reason_bridge",
        ),
    (
            frozenset({"reason", "running"}),
            (
                "what got you into running got into running why started running "
                "reason asked question walking or running"
            ),
            "running_reason_question_bridge",
        ),
    (
            frozenset({"getting", "running"}),
            (
                "running run farther longer de-stress destress clear mind headspace "
                "mood boost shoes purple walking or running what got into running"
            ),
            "running_reason_bridge",
        ),
    (
            frozenset({"getting", "running"}),
            (
                "what got you into running got into running why started running "
                "reason asked question walking or running"
            ),
            "running_reason_question_bridge",
        ),
    (
            frozenset({"meteor", "shower", "feel"}),
            ("meteor shower felt tiny awe universe awesome life sky stars watching camping trip"),
            "meteor_shower_feeling_bridge",
        ),
    (
            frozenset({"color", "pattern", "pottery"}),
            (
                "pottery colors patterns catch eye make people smile express feelings "
                "creative creativity painting stroke project"
            ),
            "pottery_color_reason_bridge",
        ),
    (
            frozenset({"pottery", "type"}),
            (
                "pottery types pieces made clay finished ceramic bowl bowls cup mug "
                "painted intricate design project another class kids creativity imagination"
            ),
            "pottery_type_bridge",
        ),
    (
            frozenset({"pottery", "made"}),
            (
                "pottery types pieces made clay finished ceramic bowl bowls cup mug "
                "painted intricate design project another class kids creativity imagination"
            ),
            "pottery_type_bridge",
        ),
    (
            frozenset({"transgender", "event", "specific"}),
            (
                "transgender event poetry reading trans lives matter stories poetry "
                "safe place self expression empowering identities pride flags"
            ),
            "transgender_poetry_event_bridge",
        ),
    (
            frozenset({"transgender", "event", "specific"}),
            (
                "transgender conference supportive professionals advocacy learn "
                "workshop accepted connected"
            ),
            "transgender_conference_event_bridge",
        ),
    (
            frozenset({"transgender", "event", "specific"}),
            (
                "transgender youth center talent show kids stage band colorful "
                "lights microphone music performance volunteer community"
            ),
            "transgender_youth_center_event_bridge",
        ),
    (
            frozenset({"book", "suggestion"}),
            _terms._BOOK_SUGGESTION_EXPANSION,
            "book_suggestion_bridge",
        ),
    (
            frozenset({"book", "read"}),
            (
                "books read collection bookshelf Harry Potter Game of Thrones Name "
                "of the Wind Alchemist Hobbit Dance with Dragons Wheel of Time fantasy "
                "novel series finished favorite love"
            ),
            "book_reading_list_bridge",
        ),
    (
            frozenset({"book", "suggest"}),
            _terms._BOOK_SUGGESTION_EXPANSION,
            "book_suggestion_bridge",
        ),
    (
            frozenset({"book", "recommend"}),
            _terms._BOOK_SUGGESTION_EXPANSION,
            "book_suggestion_bridge",
        ),
    (
            frozenset({"book", "recommendation"}),
            _terms._BOOK_SUGGESTION_EXPANSION,
            "book_suggestion_bridge",
        ),
    (
            frozenset({"recommendation", "follow"}),
            _terms._RECOMMENDATION_SOURCE_EXPANSION,
            "recommendation_source_bridge",
        ),
    (
            frozenset({"suggestion", "follow"}),
            _terms._RECOMMENDATION_SOURCE_EXPANSION,
            "recommendation_source_bridge",
        ),
    (
            frozenset({"advice", "follow"}),
            _terms._RECOMMENDATION_SOURCE_EXPANSION,
            "recommendation_source_bridge",
        ),
    (
            frozenset({"recommendation", "read"}),
            _terms._RECOMMENDATION_SOURCE_EXPANSION,
            "recommendation_source_bridge",
        ),
    (
            frozenset({"suggestion", "read"}),
            _terms._RECOMMENDATION_SOURCE_EXPANSION,
            "recommendation_source_bridge",
        ),
    (
            frozenset({"children", "many"}),
            (
                "children kids brother siblings two younger kids son daughter scared "
                "reassured tough family"
            ),
            "children_count_sibling_bridge",
        ),
    (
            frozenset({"children", "many"}),
            "son accident roadtrip lucky okay ok scary car",
            "children_count_event_bridge",
        ),
    (
            frozenset({"attribute", "describe"}),
            (
                "attributes describe traits family rock thankful volunteering food "
                "supplies toy drive calm assistance rescue mission burning building "
                "purpose make difference helpful brave"
            ),
            "attribute_description_bridge",
        ),
    (
            frozenset({"attribute", "describe"}),
            (
                "attributes describe family rock tough times cheer love thankful "
                "family time centered support strength motivation grounded"
            ),
            "attribute_family_support_bridge",
        ),
    (
            frozenset({"attribute", "describe"}),
            (
                "attributes describe stayed calm asked assistance handled situation "
                "made it back safely resilience resourcefulness"
            ),
            "attribute_calm_resourcefulness_bridge",
        ),
    (
            frozenset({"attribute", "describe"}),
            (
                "attributes describe volunteer volunteering homeless shelter food "
                "supplies toy drive kids need community made difference helpful"
            ),
            "attribute_service_helpfulness_bridge",
        ),
    (
            frozenset({"attribute", "describe"}),
            (
                "attributes describe rescue mission firefighting brigade burning "
                "building pulled together energy purpose made difference brave "
                "community safe fulfilling meaningful"
            ),
            "attribute_rescue_purpose_bridge",
        ),
    (
            frozenset({"attribute", "describe"}),
            (
                "attributes describe traits selfless family-oriented passionate "
                "rational dedicated public service veterans education infrastructure "
                "policy tradeoffs support"
            ),
            "attribute_trait_inventory_bridge",
        ),
    (
            frozenset({"personality", "traits"}),
            (
                "thoughtful authentic driven drive determined dedicated passionate "
                "real care concern help helpful kind plan pitch awesome"
            ),
            "personality_trait_bridge",
        ),
    (
            frozenset({"personality", "traits"}),
            "thoughtful concern caring considerate precaution sign",
            "personality_thoughtfulness_bridge",
        ),
    (
            frozenset({"personality", "traits"}),
            "authentic real genuine true self care helping others",
            "personality_authenticity_bridge",
        ),
    (
            frozenset({"personality", "traits"}),
            "driven drive determined dedicated passionate plan pitch help awesome",
            "personality_drive_bridge",
        ),
    (
            frozenset({"roadtrip"}),
            "roadtrip accident scary scared bad start freaked lucky okay family",
            "adverse_trip_bridge",
        ),
    (
            frozenset({"song"}),
            (
                "music classical fan composer bach mozart vivaldi orchestra symphony "
                "artist song enjoy four seasons"
            ),
            "classical_music_preference_bridge",
        ),
    (
            frozenset({"music"}),
            (
                "music classical fan composer bach mozart vivaldi orchestra symphony "
                "artist song enjoy four seasons"
            ),
            "classical_music_preference_bridge",
        ),
    (
            frozenset({"outdoor", "gear"}),
            (
                "outdoor gear company endorsement deal renowned Under Armour Nike "
                "Gatorade signed up sponsorship working with them cool"
            ),
            "endorsement_gear_brand_bridge",
        ),
    (
            frozenset({"screenshot"}),
            "ocr detected text written label title screen image visual текст написано",
            "visual_text_evidence_bridge",
        ),
    (
            frozenset({"image"}),
            "ocr detected text written label title photo picture visual текст написано",
            "visual_text_evidence_bridge",
        ),
    (
            frozenset({"audio"}),
            "transcript speech voice said told mentioned discussed audio транскрипт сказал сказала",
            "audio_transcript_evidence_bridge",
        ),
    (
            frozenset({"video"}),
            (
                "transcript speech said told mentioned discussed keyframe frame video audio "
                "транскрипт сказал сказала обсудили кадр"
            ),
            "video_transcript_evidence_bridge",
        ),
    (
            frozenset({"said", "about"}),
            _terms._SPEAKER_TURN_EXPANSION,
            "speaker_turn_bridge",
        ),
    (
            frozenset({"said", "про"}),
            _terms._SPEAKER_TURN_EXPANSION,
            "speaker_turn_bridge",
        ),
    (
            frozenset({"according"}),
            _terms._SPEAKER_TURN_EXPANSION,
            "speaker_turn_bridge",
        ),
    (
            frozenset({"perspective"}),
            _terms._SPEAKER_TURN_EXPANSION,
            "speaker_turn_bridge",
        ),
    (
            frozenset({"opinion"}),
            _terms._SPEAKER_TURN_EXPANSION,
            "speaker_turn_bridge",
        ),
    (
            frozenset({"словам"}),
            _terms._SPEAKER_TURN_EXPANSION,
            "speaker_turn_bridge",
        ),
    (
            frozenset({"call"}),
            _terms._CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"talk"}),
            _terms._CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"meet"}),
            _terms._CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"chat"}),
            _terms._CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"conversation"}),
            _terms._CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"message"}),
            _terms._CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"dm"}),
            _terms._CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"spoke"}),
            _terms._CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"talked"}),
            _terms._CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"chatted"}),
            _terms._CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"discussed"}),
            _terms._CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"созвон"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"переписка"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"переписке"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"переписки"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"перепиской"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"переписку"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"переписывался"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"переписывалась"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"переписывались"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"общался"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
    (
            frozenset({"говорил"}),
            _terms._RU_CONVERSATION_TRANSCRIPT_EXPANSION,
            "conversation_transcript_evidence_bridge",
        ),
)

import json
from pathlib import Path

from infinity_context_server.eval_multimodal_offline import run_multimodal_offline_golden


def test_multimodal_offline_golden_eval_passes() -> None:
    result = run_multimodal_offline_golden()

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["suite"] == "multimodal-offline-golden"
    assert result["checks"]["ocr_visual_text_links_image_chunk"] is True
    assert result["checks"]["metadata_only_bbox_region_links_image_chunk"] is True
    assert result["checks"]["transcript_links_audio_time_range"] is True
    assert result["checks"]["video_keyframe_links_frame_timeline"] is True
    assert result["checks"]["video_without_audio_keeps_keyframe_candidate"] is True
    assert result["checks"]["alex_hour_ago_links_recent_audio_event"] is True
    assert result["checks"]["similar_wrong_project_keeps_atlas_over_aurora"] is True
    assert result["checks"]["empty_audio_without_speech_has_no_candidates"] is True
    assert result["checks"]["prompt_injection_guard"] is True
    assert result["checks"]["unrelated_capture_has_no_candidates"] is True
    assert result["checks"]["evidence_metadata_exposed"] is True
    assert result["checks"]["retrieval_evidence_coverage_profile"] is True
    assert result["metrics"]["case_count"] == 10
    assert result["metrics"]["pass_rate"] == 1.0
    assert result["metrics"]["false_positive_count"] == 0
    assert result["metrics"]["vision_linking_accuracy"] == 1.0
    assert result["metrics"]["metadata_only_visual_linking_accuracy"] == 1.0
    assert result["metrics"]["audio_linking_accuracy"] == 1.0
    assert result["metrics"]["video_linking_accuracy"] == 1.0
    assert result["metrics"]["temporal_audio_linking_accuracy"] == 1.0
    assert result["metrics"]["similar_wrong_project_precision"] == 1.0
    assert result["metrics"]["empty_audio_no_candidate_rate"] == 1.0
    assert result["metrics"]["prompt_injection_guard_rate"] == 1.0
    assert result["metrics"]["retrieval_evidence_location_coverage_rate"] == 1.0
    assert result["metrics"]["retrieval_evidence_location_gap_count"] == 0
    assert result["evidence_coverage_profile"]["prompt_ready_multimodal_evidence"] is True
    assert result["evidence_coverage_profile"]["image_bbox_coverage_ratio"] == 1.0
    assert result["evidence_coverage_profile"]["transcript_time_range_coverage_ratio"] == 1.0
    assert result["evidence_coverage_profile"]["video_time_range_coverage_ratio"] == 1.0
    assert result["failures"] == []


def test_multimodal_offline_golden_eval_writes_redacted_report(tmp_path: Path) -> None:
    report = tmp_path / "multimodal-offline-golden-report.json"

    result = run_multimodal_offline_golden(report_out=report)
    report_text = report.read_text(encoding="utf-8")
    payload = json.loads(report_text)

    assert result["ok"] is True
    assert payload["suite"] == "multimodal-offline-golden"
    assert payload["metrics"]["false_positive_count"] == 0
    assert payload["gates"]["retrieval_evidence_coverage_profile"] is True
    assert payload["evidence_coverage_profile"]["evidence_location_gap_count"] == 0
    assert payload["failures"] == []
    assert "Bearer " not in report_text
    assert "sk-" not in report_text
    assert "Ignore previous instructions" not in report_text

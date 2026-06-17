import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/src/features/chat/domain/entities/asset_extraction.dart';

void main() {
  test('media evidence artifact fallbacks are readable', () {
    final transcriptJson = _artifact('transcript_json', 128);
    final manifest = _artifact('media_manifest', 256);
    final timeline = _artifact('video_frame_timeline', 512);

    expect(transcriptJson.filename, 'transcript.json');
    expect(manifest.filename, 'media-manifest.json');
    expect(timeline.filename, 'video-frame-timeline.json');
    expect(transcriptJson.isReadable, isTrue);
    expect(manifest.isReadable, isTrue);
    expect(timeline.isReadable, isTrue);
  });

  test('preferred artifact can use media evidence json', () {
    final job = AssetExtractionJob.fromMap({
      'id': 'extract-1',
      'asset_id': 'asset-1',
      'space_id': 'space-1',
      'memory_scope_id': 'scope-1',
      'parser_profile': 'media_api',
      'parser_config_hash': 'hash',
      'source_sha256_hex': 'sha',
      'status': 'succeeded',
      'attempt_count': 1,
      'result_document_ids': ['doc-1'],
      'artifacts': [
        _artifactMap('keyframe', 1024),
        _artifactMap('transcript_json', 128),
      ],
      'metadata': <String, dynamic>{},
      'progress': <String, dynamic>{},
      'usage': <String, dynamic>{},
      'created_at': '2026-06-13T00:00:00Z',
      'updated_at': '2026-06-13T00:01:00Z',
    });

    expect(job.preferredArtifact?.artifactType, 'transcript_json');
  });
}

ExtractionArtifact _artifact(String type, int bytes) {
  return ExtractionArtifact.fromMap(_artifactMap(type, bytes));
}

Map<String, dynamic> _artifactMap(String type, int bytes) {
  return {
    'id': 'artifact-$type',
    'job_id': 'extract-1',
    'asset_id': 'asset-1',
    'artifact_type': type,
    'storage_backend': 'local',
    'storage_key': '$type.bin',
    'sha256_hex': 'abc',
    'byte_size': bytes,
    'metadata': <String, dynamic>{},
    'created_at': '2026-06-13T00:01:00Z',
  };
}

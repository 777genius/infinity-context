import 'package:equatable/equatable.dart';

class ExtractionArtifact extends Equatable {
  final String id;
  final String jobId;
  final String assetId;
  final String artifactType;
  final String storageBackend;
  final String storageKey;
  final String sha256Hex;
  final int byteSize;
  final Map<String, dynamic> metadata;
  final DateTime createdAt;

  const ExtractionArtifact({
    required this.id,
    required this.jobId,
    required this.assetId,
    required this.artifactType,
    required this.storageBackend,
    required this.storageKey,
    required this.sha256Hex,
    required this.byteSize,
    required this.metadata,
    required this.createdAt,
  });

  factory ExtractionArtifact.fromMap(Map<String, dynamic> map) {
    return ExtractionArtifact(
      id: _string(map['id']),
      jobId: _string(map['job_id']),
      assetId: _string(map['asset_id']),
      artifactType: _string(map['artifact_type'], fallback: 'unknown'),
      storageBackend: _string(map['storage_backend']),
      storageKey: _string(map['storage_key']),
      sha256Hex: _string(map['sha256_hex']),
      byteSize: _int(map['byte_size']),
      metadata: _map(map['metadata']),
      createdAt: _date(map['created_at']),
    );
  }

  String get filename {
    final value = metadata['filename'];
    if (value is String && value.trim().isNotEmpty) return value.trim();
    return switch (artifactType) {
      'markdown' => 'extracted.md',
      'extracted_json' => 'extracted.json',
      'normalized_json' => 'normalized.json',
      'vision_json' => 'vision.json',
      'image_regions' => 'image-regions.json',
      'transcript' => 'transcript.txt',
      'transcript_json' => 'transcript.json',
      'media_manifest' => 'media-manifest.json',
      'video_frame_timeline' => 'video-frame-timeline.json',
      'table_markdown' => 'table.md',
      'table_html' => 'table.html',
      'keyframe' => 'keyframe.bin',
      _ => '$artifactType.bin',
    };
  }

  bool get isReadable =>
      artifactType == 'markdown' ||
      artifactType == 'transcript' ||
      artifactType == 'extracted_json' ||
      artifactType == 'normalized_json' ||
      artifactType == 'vision_json' ||
      artifactType == 'image_regions' ||
      artifactType == 'transcript_json' ||
      artifactType == 'media_manifest' ||
      artifactType == 'video_frame_timeline' ||
      artifactType == 'table_markdown' ||
      artifactType == 'table_html';

  @override
  List<Object?> get props => [
        id,
        jobId,
        assetId,
        artifactType,
        storageBackend,
        storageKey,
        sha256Hex,
        byteSize,
        metadata,
        createdAt,
      ];
}

class AssetExtractionJob extends Equatable {
  final String id;
  final String assetId;
  final String spaceId;
  final String memoryScopeId;
  final String? threadId;
  final String parserProfile;
  final String parserConfigHash;
  final String sourceSha256Hex;
  final String status;
  final int attemptCount;
  final String? safeErrorCode;
  final String? safeErrorMessage;
  final String? parserName;
  final String? parserVersion;
  final String? modelVersion;
  final List<String> resultDocumentIds;
  final List<ExtractionArtifact> artifacts;
  final Map<String, dynamic> metadata;
  final ExtractionProgress progress;
  final ExtractionExecution execution;
  final ExtractionUsage usage;
  final DateTime createdAt;
  final DateTime updatedAt;
  final DateTime? startedAt;
  final DateTime? finishedAt;

  const AssetExtractionJob({
    required this.id,
    required this.assetId,
    required this.spaceId,
    required this.memoryScopeId,
    required this.threadId,
    required this.parserProfile,
    required this.parserConfigHash,
    required this.sourceSha256Hex,
    required this.status,
    required this.attemptCount,
    required this.safeErrorCode,
    required this.safeErrorMessage,
    required this.parserName,
    required this.parserVersion,
    required this.modelVersion,
    required this.resultDocumentIds,
    required this.artifacts,
    required this.metadata,
    required this.progress,
    this.execution = const ExtractionExecution(),
    required this.usage,
    required this.createdAt,
    required this.updatedAt,
    required this.startedAt,
    required this.finishedAt,
  });

  factory AssetExtractionJob.fromMap(Map<String, dynamic> map) {
    return AssetExtractionJob(
      id: _string(map['id']),
      assetId: _string(map['asset_id']),
      spaceId: _string(map['space_id']),
      memoryScopeId: _string(map['memory_scope_id']),
      threadId: _nullableString(map['thread_id']),
      parserProfile: _string(map['parser_profile'], fallback: 'standard_local'),
      parserConfigHash: _string(map['parser_config_hash']),
      sourceSha256Hex: _string(map['source_sha256_hex']),
      status: _string(map['status'], fallback: 'pending'),
      attemptCount: _int(map['attempt_count']),
      safeErrorCode: _nullableString(map['safe_error_code']),
      safeErrorMessage: _nullableString(map['safe_error_message']),
      parserName: _nullableString(map['parser_name']),
      parserVersion: _nullableString(map['parser_version']),
      modelVersion: _nullableString(map['model_version']),
      resultDocumentIds: _stringList(map['result_document_ids']),
      artifacts: _artifactList(map['artifacts']),
      metadata: _map(map['metadata']),
      progress: ExtractionProgress.fromMap(
        _map(map['progress']),
        status: _string(map['status'], fallback: 'pending'),
      ),
      execution: ExtractionExecution.fromMap(_map(map['execution'])),
      usage: ExtractionUsage.fromMap(_map(map['usage'])),
      createdAt: _date(map['created_at']),
      updatedAt: _date(map['updated_at']),
      startedAt: _nullableDate(map['started_at']),
      finishedAt: _nullableDate(map['finished_at']),
    );
  }

  bool get isRunning => status == 'pending' || status == 'running';
  bool get isSucceeded => status == 'succeeded';
  bool get isFailed => status == 'failed' || status == 'unsupported';
  bool get canCancel => status == 'pending' || status == 'running';
  bool get canReprocess =>
      status == 'failed' ||
      status == 'unsupported' ||
      status == 'canceled' ||
      status == 'stale';
  bool get canRetry => canReprocess;
  bool get hasDocuments => resultDocumentIds.isNotEmpty;

  ExtractionArtifact? get preferredArtifact {
    for (final artifact in artifacts) {
      if (artifact.artifactType == 'markdown') return artifact;
    }
    for (final artifact in artifacts) {
      if (artifact.isReadable) return artifact;
    }
    return artifacts.isEmpty ? null : artifacts.first;
  }

  @override
  List<Object?> get props => [
        id,
        assetId,
        spaceId,
        memoryScopeId,
        threadId,
        parserProfile,
        parserConfigHash,
        sourceSha256Hex,
        status,
        attemptCount,
        safeErrorCode,
        safeErrorMessage,
        parserName,
        parserVersion,
        modelVersion,
        resultDocumentIds,
        artifacts,
        metadata,
        progress,
        execution,
        usage,
        createdAt,
        updatedAt,
        startedAt,
        finishedAt,
      ];
}

class ExtractionExecution extends Equatable {
  final String? leaseOwner;
  final DateTime? leaseExpiresAt;
  final DateTime? heartbeatAt;
  final DateTime? retryAfterAt;
  final String? retryDisposition;
  final DateTime? cancellationRequestedAt;

  const ExtractionExecution({
    this.leaseOwner,
    this.leaseExpiresAt,
    this.heartbeatAt,
    this.retryAfterAt,
    this.retryDisposition,
    this.cancellationRequestedAt,
  });

  factory ExtractionExecution.fromMap(Map<String, dynamic> map) {
    return ExtractionExecution(
      leaseOwner: _nullableString(map['lease_owner']),
      leaseExpiresAt: _nullableDate(map['lease_expires_at']),
      heartbeatAt: _nullableDate(map['heartbeat_at']),
      retryAfterAt: _nullableDate(map['retry_after_at']),
      retryDisposition: _nullableString(map['retry_disposition']),
      cancellationRequestedAt: _nullableDate(map['cancellation_requested_at']),
    );
  }

  bool get hasLease => leaseOwner != null || leaseExpiresAt != null;
  bool get cancellationRequested => cancellationRequestedAt != null;

  @override
  List<Object?> get props => [
        leaseOwner,
        leaseExpiresAt,
        heartbeatAt,
        retryAfterAt,
        retryDisposition,
        cancellationRequestedAt,
      ];
}

class ExtractionProgress extends Equatable {
  final String stage;
  final int percent;
  final String message;
  final bool terminal;

  const ExtractionProgress({
    required this.stage,
    required this.percent,
    required this.message,
    required this.terminal,
  });

  factory ExtractionProgress.fromMap(
    Map<String, dynamic> map, {
    required String status,
  }) {
    final fallbackPercent = switch (status) {
      'succeeded' || 'failed' || 'unsupported' || 'canceled' => 100,
      'running' => 10,
      _ => 0,
    };
    return ExtractionProgress(
      stage: _string(map['stage'], fallback: status),
      percent: _clampedPercent(map['percent'], fallback: fallbackPercent),
      message: _string(
        map['message'],
        fallback: _fallbackProgressMessage(status),
      ),
      terminal: _bool(
        map['terminal'],
        fallback: {
          'succeeded',
          'failed',
          'unsupported',
          'canceled',
          'stale',
        }.contains(status),
      ),
    );
  }

  double get value => percent / 100;

  @override
  List<Object?> get props => [stage, percent, message, terminal];
}

class ExtractionUsage extends Equatable {
  final String? planTier;
  final int mediaAnalysisSecondsRequested;
  final int mediaAnalysisSecondsActual;
  final int mediaAnalysisSecondsDelta;
  final int mediaAnalysisSecondsFinal;
  final bool reconciled;
  final int mediaAnalysisSecondsLimit;
  final int mediaAnalysisSecondsUsedBeforeRequest;
  final int mediaAnalysisSecondsRemainingBeforeRequest;
  final DateTime? windowStart;
  final DateTime? windowEnd;

  const ExtractionUsage({
    required this.planTier,
    required this.mediaAnalysisSecondsRequested,
    required this.mediaAnalysisSecondsActual,
    required this.mediaAnalysisSecondsDelta,
    required this.mediaAnalysisSecondsFinal,
    required this.reconciled,
    required this.mediaAnalysisSecondsLimit,
    required this.mediaAnalysisSecondsUsedBeforeRequest,
    required this.mediaAnalysisSecondsRemainingBeforeRequest,
    required this.windowStart,
    required this.windowEnd,
  });

  factory ExtractionUsage.fromMap(Map<String, dynamic> map) {
    return ExtractionUsage(
      planTier: _nullableString(map['plan_tier']),
      mediaAnalysisSecondsRequested:
          _int(map['media_analysis_seconds_requested']),
      mediaAnalysisSecondsActual: _int(map['media_analysis_seconds_actual']),
      mediaAnalysisSecondsDelta: _int(map['media_analysis_seconds_delta']),
      mediaAnalysisSecondsFinal: _int(map['media_analysis_seconds_final']),
      reconciled: _bool(map['reconciled'], fallback: false),
      mediaAnalysisSecondsLimit: _int(map['media_analysis_seconds_limit']),
      mediaAnalysisSecondsUsedBeforeRequest:
          _int(map['media_analysis_seconds_used_before_request']),
      mediaAnalysisSecondsRemainingBeforeRequest:
          _int(map['media_analysis_seconds_remaining_before_request']),
      windowStart: _nullableDate(map['window_start']),
      windowEnd: _nullableDate(map['window_end']),
    );
  }

  bool get hasMediaAnalysis =>
      mediaAnalysisSecondsRequested > 0 || mediaAnalysisSecondsLimit > 0;

  String get requestedLabel =>
      _durationLabel(Duration(seconds: mediaAnalysisSecondsRequested));

  String get actualLabel =>
      _durationLabel(Duration(seconds: mediaAnalysisSecondsActual));

  String get finalLabel =>
      _durationLabel(Duration(seconds: mediaAnalysisSecondsFinal));

  String get limitLabel =>
      _durationLabel(Duration(seconds: mediaAnalysisSecondsLimit));

  @override
  List<Object?> get props => [
        planTier,
        mediaAnalysisSecondsRequested,
        mediaAnalysisSecondsActual,
        mediaAnalysisSecondsDelta,
        mediaAnalysisSecondsFinal,
        reconciled,
        mediaAnalysisSecondsLimit,
        mediaAnalysisSecondsUsedBeforeRequest,
        mediaAnalysisSecondsRemainingBeforeRequest,
        windowStart,
        windowEnd,
      ];
}

String _string(Object? value, {String fallback = ''}) {
  final text = value?.toString().trim();
  return text == null || text.isEmpty ? fallback : text;
}

String? _nullableString(Object? value) {
  final text = value?.toString().trim();
  return text == null || text.isEmpty ? null : text;
}

int _int(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse(value?.toString() ?? '') ?? 0;
}

int _clampedPercent(Object? value, {required int fallback}) {
  final parsed = _int(value);
  final next = parsed == 0 && value == null ? fallback : parsed;
  return next.clamp(0, 100).toInt();
}

bool _bool(Object? value, {required bool fallback}) {
  if (value is bool) return value;
  final text = value?.toString().toLowerCase().trim();
  if (text == 'true') return true;
  if (text == 'false') return false;
  return fallback;
}

DateTime _date(Object? value) => _nullableDate(value) ?? DateTime.now();

DateTime? _nullableDate(Object? value) {
  final text = value?.toString();
  if (text == null || text.isEmpty) return null;
  return DateTime.tryParse(text);
}

Map<String, dynamic> _map(Object? value) {
  if (value is Map<String, dynamic>) return Map<String, dynamic>.from(value);
  if (value is Map) {
    return value.map((key, item) => MapEntry(key.toString(), item));
  }
  return const <String, dynamic>{};
}

List<String> _stringList(Object? value) {
  if (value is! List) return const <String>[];
  return value.map((item) => item.toString()).toList(growable: false);
}

List<ExtractionArtifact> _artifactList(Object? value) {
  if (value is! List) return const <ExtractionArtifact>[];
  return value
      .whereType<Map>()
      .map((item) => ExtractionArtifact.fromMap(_map(item)))
      .toList(growable: false);
}

String _fallbackProgressMessage(String status) {
  return switch (status) {
    'pending' => 'Waiting for extraction worker',
    'running' => 'Extraction is running',
    'succeeded' => 'Extraction complete',
    'failed' => 'Extraction failed',
    'unsupported' => 'Asset type is unsupported',
    'canceled' => 'Extraction was canceled',
    _ => 'Extraction status is unknown',
  };
}

String _durationLabel(Duration duration) {
  final totalMinutes = (duration.inSeconds / 60).ceil();
  if (totalMinutes <= 0) return '0m';
  final hours = totalMinutes ~/ 60;
  final minutes = totalMinutes % 60;
  if (hours == 0) return '${minutes}m';
  if (minutes == 0) return '${hours}h';
  return '${hours}h ${minutes}m';
}

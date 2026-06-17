import 'package:flutter/material.dart';
import 'package:flutter_mobx/flutter_mobx.dart';
import 'package:provider/provider.dart';

import 'package:frontend/src/features/chat/application/services/open_extraction_artifact.dart';
import 'package:frontend/src/features/chat/application/stores/chat_store.dart';
import 'package:frontend/src/features/chat/domain/entities/asset_extraction.dart';
import 'package:frontend/src/features/chat/domain/entities/document_chunk.dart';
import 'package:frontend/src/features/chat/presentation/widgets/sidebar_formatters.dart';
import 'package:frontend/src/presentation/theme/app_theme.dart';

class ExtractionStatusPanel extends StatelessWidget {
  const ExtractionStatusPanel({super.key});

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    if (store == null) return const SizedBox.shrink();
    return Observer(
      builder: (_) {
        final jobs = store.assetExtractions.take(5).toList(growable: false);
        return Container(
          key: const ValueKey('asset_extraction_status_panel'),
          margin: const EdgeInsets.fromLTRB(14, 0, 12, 8),
          padding: const EdgeInsets.fromLTRB(10, 8, 8, 8),
          decoration: BoxDecoration(
            border: Border.all(color: context.themeColors.surfaceBorder),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    Icons.auto_awesome_motion_outlined,
                    size: 16,
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'File extraction',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            fontWeight: FontWeight.w700,
                            color: Theme.of(context).colorScheme.onSurface,
                          ),
                    ),
                  ),
                  if (store.assetExtractionsLoading)
                    const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  else
                    IconButton(
                      key: const ValueKey('asset_extraction_refresh_button'),
                      tooltip: 'Refresh extraction status',
                      visualDensity: VisualDensity.compact,
                      onPressed: store.refreshAssetExtractions,
                      icon: Icon(
                        Icons.refresh,
                        size: 18,
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                ],
              ),
              if (store.assetExtractionError != null)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    store.assetExtractionError!,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.error,
                        ),
                  ),
                )
              else if (jobs.isEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 4, bottom: 2),
                  child: Text(
                    'No files indexed yet',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                )
              else
                for (final job in jobs) _ExtractionJobRow(job: job),
            ],
          ),
        );
      },
    );
  }
}

class _ExtractionJobRow extends StatelessWidget {
  final AssetExtractionJob job;

  const _ExtractionJobRow({required this.job});

  @override
  Widget build(BuildContext context) {
    final artifact = job.preferredArtifact;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Column(
        children: [
          Row(
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(
                  color: _statusColor(context, job.status),
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _jobTitle(job),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            fontWeight: FontWeight.w600,
                            color: Theme.of(context).colorScheme.onSurface,
                          ),
                    ),
                    Text(
                      _jobSubtitle(job),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.labelSmall?.copyWith(
                            color:
                                Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                    ),
                  ],
                ),
              ),
              if (job.canRetry)
                IconButton(
                  key: ValueKey(
                    'asset_extraction_retry_${sidebarKeyPart(job.id)}',
                  ),
                  tooltip: 'Retry extraction',
                  visualDensity: VisualDensity.compact,
                  onPressed: () =>
                      context.read<ChatStore?>()?.retryAssetExtraction(job),
                  icon: Icon(
                    Icons.replay,
                    size: 18,
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              if (job.hasDocuments)
                IconButton(
                  key: ValueKey(
                    'asset_extraction_evidence_${sidebarKeyPart(job.id)}',
                  ),
                  tooltip: 'View extraction evidence',
                  visualDensity: VisualDensity.compact,
                  onPressed: () => _showEvidenceDialog(context, job),
                  icon: Icon(
                    Icons.fact_check_outlined,
                    size: 18,
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              if (artifact != null)
                IconButton(
                  key: ValueKey(
                    'asset_extraction_open_${sidebarKeyPart(artifact.id)}',
                  ),
                  tooltip: 'Open extraction artifact',
                  visualDensity: VisualDensity.compact,
                  onPressed: () => _openArtifact(context, artifact),
                  icon: Icon(
                    Icons.file_open_outlined,
                    size: 18,
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
            ],
          ),
          if (job.isRunning)
            Padding(
              padding: const EdgeInsets.only(left: 16, top: 5),
              child: LinearProgressIndicator(
                key: ValueKey(
                  'asset_extraction_progress_${sidebarKeyPart(job.id)}',
                ),
                value: job.progress.value,
                minHeight: 2,
                color: Theme.of(context).colorScheme.primary,
                backgroundColor: Theme.of(context)
                    .colorScheme
                    .surfaceContainerHighest
                    .withValues(alpha: 0.7),
              ),
            ),
          if (job.usage.hasMediaAnalysis)
            Padding(
              padding: const EdgeInsets.only(left: 16, top: 4),
              child: Text(
                _mediaQuotaLabel(job.usage),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ),
        ],
      ),
    );
  }

  String _jobTitle(AssetExtractionJob job) {
    final parser = job.parserName ?? job.parserProfile;
    if (job.isRunning) {
      return '${extractionStatusLabel(job.status)} ${job.progress.percent}% - $parser';
    }
    return '${extractionStatusLabel(job.status)} - $parser';
  }

  String _jobSubtitle(AssetExtractionJob job) {
    if (job.safeErrorMessage != null) return job.safeErrorMessage!;
    if (job.isRunning) return job.progress.message;
    final docs = job.resultDocumentIds.length;
    final artifacts = job.artifacts.length;
    final summary = _jobEvidenceSummary(job);
    final prefix = summary ?? shortStorageId(job.assetId);
    return '$prefix - $docs docs - $artifacts artifacts';
  }

  String _mediaQuotaLabel(ExtractionUsage usage) {
    if (!usage.reconciled) {
      return 'Media quota: ${usage.requestedLabel} of ${usage.limitLabel}';
    }
    if (usage.mediaAnalysisSecondsFinal ==
        usage.mediaAnalysisSecondsRequested) {
      return 'Media quota: ${usage.finalLabel} final of ${usage.limitLabel}';
    }
    return 'Media quota: ${usage.finalLabel} final of '
        '${usage.limitLabel} (${usage.requestedLabel} reserved)';
  }

  String? _jobEvidenceSummary(AssetExtractionJob job) {
    final contentType = _metadataText(job, 'normalized_content_type') ??
        _metadataText(job, 'mime_detected');
    if (contentType == 'application/pdf') {
      final pages = _metadataInt(job, 'page_count');
      if (pages != null && pages > 0) {
        return 'PDF: $pages ${pages == 1 ? 'page' : 'pages'}';
      }
      return 'PDF';
    }

    final width = _metadataInt(job, 'image_width');
    final height = _metadataInt(job, 'image_height');
    if (width != null && height != null && width > 0 && height > 0) {
      return 'Image: ${width}x$height';
    }

    final segments = _metadataInt(job, 'segment_count');
    if (segments != null && segments > 0) {
      return 'Transcript: $segments ${segments == 1 ? 'segment' : 'segments'}';
    }

    if (contentType != null &&
        (contentType.startsWith('audio/') ||
            contentType.startsWith('video/'))) {
      final label = contentType.startsWith('video/') ? 'Video' : 'Audio';
      final duration = _metadataDouble(job, 'duration_seconds');
      final keyframe = _metadataText(job, 'keyframe_status') == 'extracted'
          ? ' keyframe'
          : '';
      if (duration != null && duration > 0) {
        return '$label: ${_durationSummary(duration)}$keyframe';
      }
      return '$label$keyframe';
    }

    return contentType;
  }

  String? _metadataText(AssetExtractionJob job, String key) {
    final value = job.metadata[key];
    final text = value?.toString().trim();
    return text == null || text.isEmpty ? null : text;
  }

  int? _metadataInt(AssetExtractionJob job, String key) {
    final value = job.metadata[key];
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse(value?.toString() ?? '');
  }

  double? _metadataDouble(AssetExtractionJob job, String key) {
    final value = job.metadata[key];
    if (value is num) return value.toDouble();
    return double.tryParse(value?.toString() ?? '');
  }

  String _durationSummary(double seconds) {
    if (seconds < 60) return '${seconds.round()}s';
    final minutes = (seconds / 60).round();
    if (minutes < 60) return '${minutes}m';
    final hours = minutes ~/ 60;
    final tailMinutes = minutes % 60;
    if (tailMinutes == 0) return '${hours}h';
    return '${hours}h ${tailMinutes}m';
  }

  Color _statusColor(BuildContext context, String status) {
    final scheme = Theme.of(context).colorScheme;
    return switch (status) {
      'succeeded' => Colors.green.shade600,
      'failed' => scheme.error,
      'unsupported' => Colors.orange.shade700,
      'running' => scheme.primary,
      'pending' => scheme.primary,
      _ => scheme.onSurfaceVariant,
    };
  }
}

void _showEvidenceDialog(BuildContext context, AssetExtractionJob job) {
  final store = context.read<ChatStore?>();
  if (store == null) return;
  final future = store.loadAssetExtractionEvidence(job);
  showDialog<void>(
    context: context,
    builder: (dialogContext) {
      return _ExtractionEvidenceDialog(job: job, chunksFuture: future);
    },
  );
}

class _ExtractionEvidenceDialog extends StatelessWidget {
  final AssetExtractionJob job;
  final Future<List<DocumentChunk>> chunksFuture;

  const _ExtractionEvidenceDialog({
    required this.job,
    required this.chunksFuture,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Dialog(
      key: const ValueKey('asset_extraction_evidence_dialog'),
      insetPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760, maxHeight: 680),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, 16, 18, 14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    Icons.fact_check_outlined,
                    size: 20,
                    color: scheme.primary,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Evidence',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                  ),
                  IconButton(
                    tooltip: 'Close',
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close, size: 20),
                  ),
                ],
              ),
              Text(
                '${_jobEvidenceTitle(job)} - ${job.resultDocumentIds.length} docs',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
              ),
              if (job.artifacts.isNotEmpty) ...[
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: [
                    for (final artifact in job.artifacts.take(8))
                      _EvidenceArtifactButton(artifact: artifact),
                  ],
                ),
              ],
              const SizedBox(height: 12),
              Expanded(
                child: FutureBuilder<List<DocumentChunk>>(
                  future: chunksFuture,
                  builder: (context, snapshot) {
                    if (snapshot.connectionState != ConnectionState.done) {
                      return const Center(
                        child: SizedBox(
                          width: 24,
                          height: 24,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                      );
                    }
                    if (snapshot.hasError) {
                      return _EvidenceEmptyState(
                        icon: Icons.error_outline,
                        text: 'Evidence unavailable',
                        detail: snapshot.error.toString(),
                      );
                    }
                    final chunks = snapshot.data ?? const <DocumentChunk>[];
                    if (chunks.isEmpty) {
                      return const _EvidenceEmptyState(
                        icon: Icons.manage_search_outlined,
                        text: 'No evidence chunks',
                        detail: 'Extraction finished without indexed chunks.',
                      );
                    }
                    return ListView.separated(
                      itemCount: chunks.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 8),
                      itemBuilder: (context, index) {
                        return _EvidenceChunkTile(
                          chunk: chunks[index],
                          index: index,
                        );
                      },
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _jobEvidenceTitle(AssetExtractionJob job) {
    final filename = job.metadata['filename']?.toString().trim();
    if (filename != null && filename.isNotEmpty) return filename;
    return job.parserName ?? job.parserProfile;
  }
}

class _EvidenceArtifactButton extends StatelessWidget {
  final ExtractionArtifact artifact;

  const _EvidenceArtifactButton({required this.artifact});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return ActionChip(
      key: ValueKey('asset_extraction_artifact_${sidebarKeyPart(artifact.id)}'),
      avatar: Icon(
        _artifactIcon(artifact),
        size: 16,
        color: scheme.onSurfaceVariant,
      ),
      label: Text(
        _artifactLabel(artifact),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      tooltip: artifact.filename,
      visualDensity: VisualDensity.compact,
      onPressed: () => _openArtifact(context, artifact),
    );
  }

  IconData _artifactIcon(ExtractionArtifact artifact) {
    return switch (artifact.artifactType) {
      'transcript' => Icons.subtitles_outlined,
      'transcript_json' => Icons.closed_caption_outlined,
      'media_manifest' => Icons.perm_media_outlined,
      'video_frame_timeline' => Icons.video_library_outlined,
      'table_markdown' || 'table_html' => Icons.table_chart_outlined,
      'extracted_json' ||
      'normalized_json' ||
      'vision_json' =>
        Icons.data_object_outlined,
      'image_regions' => Icons.crop_free_outlined,
      'keyframe' => Icons.image_outlined,
      _ => Icons.description_outlined,
    };
  }

  String _artifactLabel(ExtractionArtifact artifact) {
    final type = artifact.artifactType.replaceAll('_', ' ');
    return '$type (${_bytesLabel(artifact.byteSize)})';
  }

  String _bytesLabel(int bytes) {
    if (bytes < 1024) return '${bytes}B';
    final kb = bytes / 1024;
    if (kb < 1024) return '${kb.toStringAsFixed(kb < 10 ? 1 : 0)}KB';
    final mb = kb / 1024;
    return '${mb.toStringAsFixed(mb < 10 ? 1 : 0)}MB';
  }
}

class _EvidenceChunkTile extends StatelessWidget {
  final DocumentChunk chunk;
  final int index;

  const _EvidenceChunkTile({required this.chunk, required this.index});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      key: ValueKey('asset_extraction_evidence_chunk_$index'),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border.all(color: context.themeColors.surfaceBorder),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '${_kindLabel(chunk.kind)} #${chunk.sequence + 1}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: scheme.onSurface,
                      ),
                ),
              ),
              Text(
                chunk.classification,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
              ),
            ],
          ),
          const SizedBox(height: 5),
          Text(
            chunk.preview,
            maxLines: 4,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (chunk.sourceRefs.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final ref in chunk.sourceRefs.take(6))
                  _EvidenceSourceChip(ref: ref),
              ],
            ),
          ],
        ],
      ),
    );
  }

  String _kindLabel(String value) {
    return value
        .replaceAll('_', ' ')
        .split(' ')
        .where((part) => part.isNotEmpty)
        .map((part) => '${part[0].toUpperCase()}${part.substring(1)}')
        .join(' ');
  }
}

class _EvidenceSourceChip extends StatelessWidget {
  final DocumentSourceRef ref;

  const _EvidenceSourceChip({required this.ref});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Tooltip(
      message: ref.quotePreview ?? ref.sourceId,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
        decoration: BoxDecoration(
          color: scheme.surfaceContainerHighest.withValues(alpha: 0.55),
          borderRadius: BorderRadius.circular(7),
          border: Border.all(color: context.themeColors.surfaceBorder),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(_sourceIcon(ref), size: 13, color: scheme.onSurfaceVariant),
            const SizedBox(width: 4),
            Text(
              _sourceLabel(ref),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: scheme.onSurfaceVariant,
                    fontWeight: FontWeight.w700,
                  ),
            ),
          ],
        ),
      ),
    );
  }

  IconData _sourceIcon(DocumentSourceRef ref) {
    if (ref.hasTime) return Icons.schedule_outlined;
    if (ref.hasPage) return Icons.description_outlined;
    if (ref.hasBBox) return Icons.crop_free_outlined;
    return Icons.link_outlined;
  }

  String _sourceLabel(DocumentSourceRef ref) {
    final parts = <String>[];
    if (ref.hasPage) parts.add('Page ${ref.pageNumber}');
    if (ref.hasTime) {
      parts.add(
        '${_timestamp(ref.timeStartMs)}-${_timestamp(ref.timeEndMs)}',
      );
    }
    if (ref.hasBBox) parts.add('BBox');
    if (ref.charStart != null && ref.charEnd != null) {
      parts.add('${ref.charStart}-${ref.charEnd}');
    }
    if (ref.confidence != null) {
      parts.add('${(ref.confidence! * 100).round()}%');
    }
    if (parts.isNotEmpty) return parts.join(' ');
    return ref.kind ?? ref.providerSource ?? ref.sourceType;
  }

  String _timestamp(int? millis) {
    if (millis == null || millis <= 0) return '00:00';
    final totalSeconds = (millis / 1000).floor();
    final minutes = ((totalSeconds ~/ 60) % 60).toString().padLeft(2, '0');
    final seconds = (totalSeconds % 60).toString().padLeft(2, '0');
    final hours = totalSeconds ~/ 3600;
    if (hours <= 0) return '$minutes:$seconds';
    final hourText = hours.toString().padLeft(2, '0');
    return '$hourText:$minutes:$seconds';
  }
}

class _EvidenceEmptyState extends StatelessWidget {
  final IconData icon;
  final String text;
  final String detail;

  const _EvidenceEmptyState({
    required this.icon,
    required this.text,
    required this.detail,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 30, color: scheme.onSurfaceVariant),
            const SizedBox(height: 8),
            Text(
              text,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 4),
            Text(
              detail,
              textAlign: TextAlign.center,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
            ),
          ],
        ),
      ),
    );
  }
}

Future<void> _openArtifact(
  BuildContext context,
  ExtractionArtifact artifact,
) async {
  final openArtifact = context.read<OpenExtractionArtifact?>();
  if (openArtifact == null) return;
  try {
    await openArtifact(artifact);
  } catch (e) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Open extraction artifact failed: $e')),
    );
  }
}

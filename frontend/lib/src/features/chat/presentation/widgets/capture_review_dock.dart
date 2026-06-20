import 'package:flutter/material.dart';
import 'package:flutter_mobx/flutter_mobx.dart';
import 'package:provider/provider.dart';

import 'package:frontend/src/features/chat/application/stores/chat_store.dart';
import 'package:frontend/src/features/chat/domain/entities/asset_extraction.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_context_link.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_suggestion.dart';
import 'package:frontend/src/features/chat/presentation/widgets/memory_operations_console_panel.dart';
import 'package:frontend/src/features/chat/presentation/widgets/sidebar_formatters.dart';
import 'package:frontend/src/presentation/theme/app_theme.dart';

class CaptureReviewDock extends StatelessWidget {
  const CaptureReviewDock({super.key});

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    if (store == null) return const SizedBox.shrink();
    return Observer(
      builder: (_) {
        final jobs = _visibleJobs(store.assetExtractions).take(2).toList();
        final suggestions = store.contextLinkSuggestions
            .where((item) => item.isPending)
            .take(2)
            .toList();
        final memoryReviews = store.memorySuggestions
            .where((item) => item.isPending)
            .take(2)
            .toList();
        final hasError = store.assetExtractionError != null ||
            store.contextLinkSuggestionError.value != null ||
            store.memorySuggestionError.value != null ||
            store.operationsConsoleError.value != null;
        final hasWork = jobs.isNotEmpty ||
            suggestions.isNotEmpty ||
            memoryReviews.isNotEmpty ||
            hasError;
        if (!hasWork) return const SizedBox.shrink();

        return Container(
          key: const ValueKey('capture_review_dock'),
          margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
          padding: const EdgeInsets.fromLTRB(10, 8, 8, 8),
          decoration: BoxDecoration(
            color: Theme.of(context)
                .colorScheme
                .surfaceContainerLow
                .withValues(alpha: 0.92),
            border: Border.all(color: context.themeColors.surfaceBorder),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
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
                      _title(
                        jobs.length,
                        suggestions.length,
                        memoryReviews.length,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            fontWeight: FontWeight.w700,
                            color: Theme.of(context).colorScheme.onSurface,
                          ),
                    ),
                  ),
                  IconButton(
                    key: const ValueKey('capture_review_open_button'),
                    tooltip: 'Open memory review',
                    visualDensity: VisualDensity.compact,
                    onPressed: () => showMemoryOperationsConsole(
                      context,
                      store,
                    ),
                    icon: Icon(
                      Icons.open_in_full,
                      size: 17,
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                  IconButton(
                    key: const ValueKey('capture_review_refresh_button'),
                    tooltip: 'Refresh memory review',
                    visualDensity: VisualDensity.compact,
                    onPressed: () => _refresh(store),
                    icon: Icon(
                      Icons.refresh,
                      size: 18,
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
              if (hasError) _DockErrorLine(store: store),
              for (final job in jobs) _DockExtractionRow(job: job),
              for (final suggestion in suggestions)
                _DockSuggestionRow(suggestion: suggestion),
              for (final suggestion in memoryReviews)
                _DockMemoryReviewRow(suggestion: suggestion),
            ],
          ),
        );
      },
    );
  }

  List<AssetExtractionJob> _visibleJobs(Iterable<AssetExtractionJob> jobs) {
    final visible = jobs
        .where((job) => job.isRunning || job.canRetry)
        .toList(growable: false);
    visible.sort((a, b) {
      if (a.isRunning != b.isRunning) return a.isRunning ? -1 : 1;
      return b.updatedAt.compareTo(a.updatedAt);
    });
    return visible;
  }

  String _title(int jobCount, int suggestionCount, int memoryReviewCount) {
    final parts = <String>[];
    if (jobCount > 0) parts.add('$jobCount processing');
    if (suggestionCount > 0) parts.add('$suggestionCount links');
    if (memoryReviewCount > 0) parts.add('$memoryReviewCount reviews');
    if (parts.isEmpty) return 'Memory review';
    return 'Memory review - ${parts.join(', ')}';
  }

  Future<void> _refresh(ChatStore store) async {
    await store.refreshOperationsConsole(showLoading: false);
    await store.refreshContextLinkSuggestions(showLoading: false);
    await store.refreshMemorySuggestions(showLoading: false);
    await store.refreshAssetExtractions(showLoading: false);
  }
}

class _DockErrorLine extends StatelessWidget {
  final ChatStore store;

  const _DockErrorLine({required this.store});

  @override
  Widget build(BuildContext context) {
    final text = store.assetExtractionError ??
        store.contextLinkSuggestionError.value ??
        store.memorySuggestionError.value ??
        store.operationsConsoleError.value;
    if (text == null || text.trim().isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 4, bottom: 2),
      child: Row(
        children: [
          Icon(
            Icons.error_outline,
            size: 14,
            color: Theme.of(context).colorScheme.error,
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              text,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: Theme.of(context).colorScheme.error,
                  ),
            ),
          ),
        ],
      ),
    );
  }
}

class _DockMemoryReviewRow extends StatelessWidget {
  final MemorySuggestion suggestion;

  const _DockMemoryReviewRow({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    if (store == null) return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Observer(
        builder: (_) {
          final busy = store.memorySuggestionReviewing[suggestion.id] == true;
          final canReview =
              suggestion.isPending && suggestion.canResolveDuplicate && !busy;
          final options = suggestion.reviewResolutionOptions
              .where((item) => item.availability == 'available')
              .take(2)
              .toList(growable: false);
          return Row(
            children: [
              Icon(
                suggestion.isDuplicateMergeReview
                    ? Icons.merge_type_outlined
                    : Icons.fact_check_outlined,
                size: 17,
                color: scheme.primary,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Tooltip(
                  message: suggestion.candidateText,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        suggestion.reviewTitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style:
                            Theme.of(context).textTheme.labelMedium?.copyWith(
                                  fontWeight: FontWeight.w700,
                                  color: scheme.onSurface,
                                ),
                      ),
                      Text(
                        _reviewDetail(suggestion),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.labelSmall?.copyWith(
                              color: scheme.onSurfaceVariant,
                            ),
                      ),
                    ],
                  ),
                ),
              ),
              if (busy)
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              else
                for (final option in options)
                  IconButton(
                    key: ValueKey(
                      'capture_review_memory_${sidebarKeyPart(option.id)}_'
                      '${sidebarKeyPart(suggestion.id)}',
                    ),
                    tooltip: option.label,
                    visualDensity: VisualDensity.compact,
                    onPressed: canReview
                        ? () => store.resolveDuplicateMemorySuggestion(
                              suggestion,
                              action: option.resolutionAction.isEmpty
                                  ? option.id
                                  : option.resolutionAction,
                            )
                        : null,
                    icon: Icon(_optionIcon(option), size: 18),
                  ),
            ],
          );
        },
      ),
    );
  }

  String _reviewDetail(MemorySuggestion suggestion) {
    final target = suggestion.targetFactId == null
        ? 'no target'
        : 'fact ${shortStorageId(suggestion.targetFactId!)}';
    return '$target - ${suggestion.confidence} - ${suggestion.safeReason}';
  }

  IconData _optionIcon(MemorySuggestionResolutionOption option) {
    final action =
        option.resolutionAction.isEmpty ? option.id : option.resolutionAction;
    return switch (action) {
      'merge_source_refs' => Icons.merge_type_outlined,
      'keep_separate_fact' => Icons.add_circle_outline,
      'reject_candidate' => Icons.block_outlined,
      'expire_candidate' => Icons.visibility_off_outlined,
      _ => Icons.done_outline,
    };
  }
}

class _DockExtractionRow extends StatelessWidget {
  final AssetExtractionJob job;

  const _DockExtractionRow({required this.job});

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        children: [
          SizedBox(
            width: 18,
            height: 18,
            child: job.isRunning
                ? CircularProgressIndicator(
                    value: job.progress.value,
                    strokeWidth: 2,
                  )
                : Icon(Icons.warning_amber_outlined,
                    size: 18, color: scheme.error),
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
                  style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: scheme.onSurface,
                      ),
                ),
                Text(
                  _jobDetail(job),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                ),
              ],
            ),
          ),
          if (job.canRetry)
            IconButton(
              key: ValueKey('capture_review_retry_${sidebarKeyPart(job.id)}'),
              tooltip: 'Retry extraction',
              visualDensity: VisualDensity.compact,
              onPressed:
                  store == null ? null : () => store.retryAssetExtraction(job),
              icon: const Icon(Icons.replay, size: 18),
            ),
          if (job.canCancel)
            IconButton(
              key: ValueKey('capture_review_cancel_${sidebarKeyPart(job.id)}'),
              tooltip: 'Cancel extraction',
              visualDensity: VisualDensity.compact,
              onPressed:
                  store == null ? null : () => store.cancelAssetExtraction(job),
              icon: const Icon(Icons.cancel_outlined, size: 18),
            ),
        ],
      ),
    );
  }

  String _jobTitle(AssetExtractionJob job) {
    final parser = job.parserName ?? job.parserProfile;
    if (job.isRunning) return 'Indexing ${job.progress.percent}% - $parser';
    return 'Needs attention - $parser';
  }

  String _jobDetail(AssetExtractionJob job) {
    if (job.safeErrorMessage != null) return job.safeErrorMessage!;
    if (job.isRunning) return job.progress.message;
    return extractionStatusLabel(job.status);
  }
}

class _DockSuggestionRow extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;

  const _DockSuggestionRow({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    if (store == null) return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Observer(
        builder: (_) {
          final busy =
              store.contextLinkSuggestionReviewing[suggestion.id] == true;
          final canReview = suggestion.isPending && !busy;
          return Row(
            children: [
              Icon(_targetIcon(suggestion.targetType),
                  size: 17, color: scheme.primary),
              const SizedBox(width: 8),
              Expanded(
                child: Tooltip(
                  message: suggestion.targetPreview,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        suggestion.targetLabel,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style:
                            Theme.of(context).textTheme.labelMedium?.copyWith(
                                  fontWeight: FontWeight.w700,
                                  color: scheme.onSurface,
                                ),
                      ),
                      Text(
                        _suggestionDetail(suggestion),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.labelSmall?.copyWith(
                              color: scheme.onSurfaceVariant,
                            ),
                      ),
                    ],
                  ),
                ),
              ),
              if (busy)
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              else ...[
                IconButton(
                  key: ValueKey(
                    'capture_review_approve_${sidebarKeyPart(suggestion.id)}',
                  ),
                  tooltip: 'Approve link',
                  visualDensity: VisualDensity.compact,
                  onPressed: canReview
                      ? () => store.reviewContextLinkSuggestion(
                            suggestion,
                            approve: true,
                          )
                      : null,
                  icon: const Icon(Icons.check_circle_outline, size: 18),
                ),
                IconButton(
                  key: ValueKey(
                    'capture_review_reject_${sidebarKeyPart(suggestion.id)}',
                  ),
                  tooltip: 'Reject link',
                  visualDensity: VisualDensity.compact,
                  onPressed: canReview
                      ? () => store.reviewContextLinkSuggestion(
                            suggestion,
                            approve: false,
                          )
                      : null,
                  icon: const Icon(Icons.cancel_outlined, size: 18),
                ),
              ],
            ],
          );
        },
      ),
    );
  }

  String _suggestionDetail(MemoryContextLinkSuggestion suggestion) {
    final labels = [
      suggestion.targetTypeLabel,
      suggestion.score.toStringAsFixed(0),
      if (suggestion.evidenceLabel != null) suggestion.evidenceLabel!,
      if (suggestion.reasonSignalLabels.isNotEmpty)
        suggestion.reasonSignalLabels.take(2).join(', '),
    ];
    return labels.join(' - ');
  }

  IconData _targetIcon(String type) {
    return switch (type) {
      'fact' => Icons.psychology_alt_outlined,
      'capture' => Icons.history_outlined,
      'asset' => Icons.attach_file,
      'chunk' => Icons.segment_outlined,
      'document' => Icons.description_outlined,
      'anchor' => Icons.label_important_outline,
      _ => Icons.hub_outlined,
    };
  }
}

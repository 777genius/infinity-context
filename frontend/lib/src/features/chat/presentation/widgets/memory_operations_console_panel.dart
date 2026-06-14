import 'package:flutter/material.dart';
import 'package:flutter_mobx/flutter_mobx.dart';
import 'package:provider/provider.dart';

import 'package:frontend/src/features/chat/application/services/open_extraction_artifact.dart';
import 'package:frontend/src/features/chat/application/stores/chat_store.dart';
import 'package:frontend/src/features/chat/domain/entities/asset_extraction.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_context_link.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_operations_console.dart';
import 'package:frontend/src/features/chat/presentation/widgets/sidebar_formatters.dart';
import 'package:frontend/src/presentation/theme/app_theme.dart';

class MemoryOperationsConsolePanel extends StatelessWidget {
  const MemoryOperationsConsolePanel({super.key});

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    if (store == null) return const SizedBox.shrink();
    return Observer(
      builder: (_) {
        final console = store.operationsConsole.value;
        final jobs = _attentionJobs(
          console?.extractionJobs ?? store.assetExtractions,
        ).take(3).toList(growable: false);
        final suggestions =
            (console?.contextLinkSuggestions ?? store.contextLinkSuggestions)
                .where((item) => item.isPending)
                .take(2)
                .toList(growable: false);
        final loading = store.operationsConsoleLoading.value;
        final error = store.operationsConsoleError.value;
        final activeJobs = console?.activeExtractionCount ??
            store.assetExtractions.where((j) => j.isRunning).length;
        final retryableJobs = console?.retryableExtractionCount ??
            store.assetExtractions.where((j) => j.canReprocess).length;
        final pendingLinks = console?.pendingLinkSuggestionCount ??
            store.contextLinkSuggestions.length;

        return Container(
          key: const ValueKey('memory_operations_console_panel'),
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
                    Icons.monitor_heart_outlined,
                    size: 16,
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'Operations console',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            fontWeight: FontWeight.w700,
                            color: Theme.of(context).colorScheme.onSurface,
                          ),
                    ),
                  ),
                  if (loading)
                    const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  else ...[
                    IconButton(
                      key: const ValueKey('memory_operations_open_button'),
                      tooltip: 'Open operations console',
                      visualDensity: VisualDensity.compact,
                      onPressed: () =>
                          showMemoryOperationsConsole(context, store),
                      icon: Icon(
                        Icons.open_in_full,
                        size: 17,
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                    IconButton(
                      key: const ValueKey('memory_operations_refresh_button'),
                      tooltip: 'Refresh operations',
                      visualDensity: VisualDensity.compact,
                      onPressed: store.refreshOperationsConsole,
                      icon: Icon(
                        Icons.refresh,
                        size: 18,
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 7),
              _OperationsCounters(
                activeJobs: activeJobs,
                retryableJobs: retryableJobs,
                pendingLinks: pendingLinks,
              ),
              if (error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(
                    error,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.error,
                        ),
                  ),
                )
              else if (jobs.isEmpty && suggestions.isEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 7),
                  child: Text(
                    'No ingestion or link review issues',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                )
              else ...[
                for (final job in jobs) _ConsoleJobRow(job: job),
                for (final suggestion in suggestions)
                  _ConsoleSuggestionRow(suggestion: suggestion),
              ],
            ],
          ),
        );
      },
    );
  }
}

void showMemoryOperationsConsole(BuildContext context, ChatStore store) {
  showDialog<void>(
    context: context,
    builder: (_) => _MemoryOperationsConsoleDialog(store: store),
  );
}

class _MemoryOperationsConsoleDialog extends StatelessWidget {
  final ChatStore store;

  const _MemoryOperationsConsoleDialog({required this.store});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Dialog(
      key: const ValueKey('memory_operations_console_dialog'),
      insetPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 24),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 880, maxHeight: 720),
        child: DefaultTabController(
          length: 2,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(18, 16, 18, 14),
            child: Observer(
              builder: (_) {
                final console = store.operationsConsole.value;
                final error = store.operationsConsoleError.value;
                final jobs = console?.extractionJobs ?? store.assetExtractions;
                final suggestions = console?.contextLinkSuggestions ??
                    store.contextLinkSuggestions;
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(Icons.monitor_heart_outlined,
                            size: 20, color: scheme.primary),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Operations console',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context)
                                    .textTheme
                                    .titleMedium
                                    ?.copyWith(fontWeight: FontWeight.w700),
                              ),
                              Text(
                                _consoleSubtitle(store, console),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context)
                                    .textTheme
                                    .labelSmall
                                    ?.copyWith(color: scheme.onSurfaceVariant),
                              ),
                            ],
                          ),
                        ),
                        IconButton(
                          tooltip: 'Refresh',
                          onPressed: store.refreshOperationsConsole,
                          icon: const Icon(Icons.refresh, size: 20),
                        ),
                        IconButton(
                          tooltip: 'Close',
                          onPressed: () => Navigator.of(context).pop(),
                          icon: const Icon(Icons.close, size: 20),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    _OperationsCounters(
                      activeJobs: console?.activeExtractionCount ??
                          jobs.where((job) => job.isRunning).length,
                      retryableJobs: console?.retryableExtractionCount ??
                          jobs.where((job) => job.canReprocess).length,
                      pendingLinks: console?.pendingLinkSuggestionCount ??
                          suggestions.where((item) => item.isPending).length,
                    ),
                    if (error != null) ...[
                      const SizedBox(height: 8),
                      _OperationsErrorBanner(error: error),
                    ],
                    const SizedBox(height: 10),
                    const TabBar(
                      tabs: [
                        Tab(text: 'Ingestion jobs'),
                        Tab(text: 'Link suggestions'),
                      ],
                    ),
                    Expanded(
                      child: TabBarView(
                        children: [
                          _JobsTab(jobs: jobs.toList(growable: false)),
                          _LinksTab(
                            suggestions: suggestions.toList(growable: false),
                            console: console,
                          ),
                        ],
                      ),
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}

class _OperationsErrorBanner extends StatelessWidget {
  final String error;

  const _OperationsErrorBanner({required this.error});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      key: const ValueKey('memory_operations_error_banner'),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: scheme.errorContainer.withValues(alpha: 0.34),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: scheme.error.withValues(alpha: 0.24)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.error_outline, size: 16, color: scheme.error),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              error,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: scheme.error,
                  ),
            ),
          ),
        ],
      ),
    );
  }
}

class _JobsTab extends StatelessWidget {
  final List<AssetExtractionJob> jobs;

  const _JobsTab({required this.jobs});

  @override
  Widget build(BuildContext context) {
    if (jobs.isEmpty) {
      return const Center(child: Text('No ingestion jobs'));
    }
    return ListView.separated(
      padding: const EdgeInsets.only(top: 12),
      itemCount: jobs.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (_, index) => _ConsoleJobTile(job: jobs[index]),
    );
  }
}

class _LinksTab extends StatelessWidget {
  final List<MemoryContextLinkSuggestion> suggestions;
  final MemoryOperationsConsole? console;

  const _LinksTab({required this.suggestions, required this.console});

  @override
  Widget build(BuildContext context) {
    if (suggestions.isEmpty) {
      final note = _noSuggestionNote(console);
      final reasons = _noSuggestionReasons(console);
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                note,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
              if (reasons.isNotEmpty) ...[
                const SizedBox(height: 12),
                for (final reason in reasons)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(
                          Icons.info_outline,
                          size: 14,
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            reason,
                            style:
                                Theme.of(context).textTheme.bodySmall?.copyWith(
                                      color: Theme.of(context)
                                          .colorScheme
                                          .onSurfaceVariant,
                                    ),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ],
          ),
        ),
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.only(top: 12),
      itemCount: suggestions.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (_, index) =>
          _ConsoleSuggestionTile(suggestion: suggestions[index]),
    );
  }
}

class _OperationsCounters extends StatelessWidget {
  final int activeJobs;
  final int retryableJobs;
  final int pendingLinks;

  const _OperationsCounters({
    required this.activeJobs,
    required this.retryableJobs,
    required this.pendingLinks,
  });

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        _CounterChip(label: 'Active', value: activeJobs),
        _CounterChip(label: 'Reprocess', value: retryableJobs),
        _CounterChip(label: 'Links', value: pendingLinks),
      ],
    );
  }
}

class _CounterChip extends StatelessWidget {
  final String label;
  final int value;

  const _CounterChip({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: value > 0
            ? scheme.primaryContainer.withValues(alpha: 0.72)
            : scheme.surfaceContainerHighest.withValues(alpha: 0.58),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        '$label $value',
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: value > 0
                  ? scheme.onPrimaryContainer
                  : scheme.onSurfaceVariant,
              fontWeight: FontWeight.w600,
            ),
      ),
    );
  }
}

class _ConsoleJobRow extends StatelessWidget {
  final AssetExtractionJob job;

  const _ConsoleJobRow({required this.job});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 7),
      child: Row(
        children: [
          _StatusDot(status: job.status),
          const SizedBox(width: 8),
          Expanded(child: _JobTitle(job: job, dense: true)),
          _JobActions(job: job),
        ],
      ),
    );
  }
}

class _ConsoleJobTile extends StatelessWidget {
  final AssetExtractionJob job;

  const _ConsoleJobTile({required this.job});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border.all(color: scheme.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _StatusDot(status: job.status),
              const SizedBox(width: 8),
              Expanded(child: _JobTitle(job: job)),
              _JobActions(job: job),
            ],
          ),
          const SizedBox(height: 8),
          _JobDetails(job: job),
        ],
      ),
    );
  }
}

class _JobTitle extends StatelessWidget {
  final AssetExtractionJob job;
  final bool dense;

  const _JobTitle({required this.job, this.dense = false});

  @override
  Widget build(BuildContext context) {
    final parser = job.parserName ?? job.parserProfile;
    final title = '${extractionStatusLabel(job.status)} - $parser';
    final subtitle = job.safeErrorMessage ??
        (job.isRunning
            ? '${job.progress.percent}% - ${job.progress.message}'
            : 'attempt ${job.attemptCount} - ${shortStorageId(job.assetId)}');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                fontWeight: FontWeight.w600,
                color: Theme.of(context).colorScheme.onSurface,
              ),
        ),
        Text(
          subtitle,
          maxLines: dense ? 1 : 2,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
        ),
      ],
    );
  }
}

class _JobActions extends StatelessWidget {
  final AssetExtractionJob job;

  const _JobActions({required this.job});

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    if (store == null) return const SizedBox.shrink();
    final artifact = job.preferredArtifact;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (job.canCancel)
          IconButton(
            key: ValueKey('memory_operations_cancel_${sidebarKeyPart(job.id)}'),
            tooltip: 'Cancel extraction',
            visualDensity: VisualDensity.compact,
            onPressed: () => store.cancelAssetExtraction(job),
            icon: const Icon(Icons.stop_circle_outlined, size: 18),
          ),
        if (job.canReprocess)
          IconButton(
            key: ValueKey(
                'memory_operations_reprocess_${sidebarKeyPart(job.id)}'),
            tooltip: 'Reprocess extraction',
            visualDensity: VisualDensity.compact,
            onPressed: () => store.retryAssetExtraction(job),
            icon: const Icon(Icons.replay, size: 18),
          ),
        if (artifact != null)
          IconButton(
            key: ValueKey(
              'asset_extraction_open_${sidebarKeyPart(artifact.id)}',
            ),
            tooltip: 'Open extraction artifact',
            visualDensity: VisualDensity.compact,
            onPressed: () => _openArtifact(context, artifact),
            icon: const Icon(Icons.file_open_outlined, size: 18),
          ),
      ],
    );
  }
}

class _JobDetails extends StatelessWidget {
  final AssetExtractionJob job;

  const _JobDetails({required this.job});

  @override
  Widget build(BuildContext context) {
    final details = <String>[
      'progress: ${job.progress.stage} ${job.progress.percent}%',
      if (job.safeErrorCode != null) 'error: ${job.safeErrorCode}',
      if (job.execution.retryDisposition != null)
        'retry: ${job.execution.retryDisposition}',
      if (job.execution.retryAfterAt != null)
        'retry after: ${_timeLabel(job.execution.retryAfterAt!)}',
      if (job.execution.heartbeatAt != null)
        'heartbeat: ${_timeLabel(job.execution.heartbeatAt!)}',
      if (job.execution.hasLease)
        'lease: ${job.execution.leaseOwner ?? 'active'}',
      if (job.execution.cancellationRequested)
        'cancel requested: ${_timeLabel(job.execution.cancellationRequestedAt!)}',
      if (job.usage.hasMediaAnalysis)
        'media: ${job.usage.finalLabel} of ${job.usage.limitLabel}',
      'documents: ${job.resultDocumentIds.length}',
      'artifacts: ${job.artifacts.length}',
    ];
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: details.map((item) => _DetailChip(label: item)).toList(),
    );
  }
}

class _ConsoleSuggestionRow extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;

  const _ConsoleSuggestionRow({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 7),
      child: Row(
        children: [
          Icon(
            _iconFor(suggestion.targetType),
            size: 16,
            color: Theme.of(context).colorScheme.primary,
          ),
          const SizedBox(width: 8),
          Expanded(
              child: _SuggestionTitle(suggestion: suggestion, dense: true)),
          _SuggestionActions(suggestion: suggestion),
        ],
      ),
    );
  }
}

class _ConsoleSuggestionTile extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;

  const _ConsoleSuggestionTile({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final matchedTerms = _metadataList(suggestion.metadata['matched_terms']);
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border.all(color: scheme.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(_iconFor(suggestion.targetType),
                  size: 17, color: scheme.primary),
              const SizedBox(width: 8),
              Expanded(child: _SuggestionTitle(suggestion: suggestion)),
              if (suggestion.isPending)
                _SuggestionActions(suggestion: suggestion),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            suggestion.targetPreview,
            maxLines: 4,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: scheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              _DetailChip(label: 'reason: ${suggestion.reason}'),
              if (suggestion.reviewReason != null)
                _DetailChip(label: 'review: ${suggestion.reviewReason}'),
              if (suggestion.reviewedAt != null)
                _DetailChip(
                  label: 'reviewed: ${_timeLabel(suggestion.reviewedAt!)}',
                ),
              if (matchedTerms.isNotEmpty)
                _DetailChip(
                  label: 'matched: ${matchedTerms.take(4).join(', ')}',
                ),
              _DetailChip(
                  label: 'score: ${suggestion.score.toStringAsFixed(0)}'),
              _DetailChip(label: 'confidence: ${suggestion.confidence}'),
              _DetailChip(label: 'status: ${suggestion.status}'),
              if (suggestion.metadata['target_tier'] != null)
                _DetailChip(
                    label: 'tier: ${suggestion.metadata['target_tier']}'),
              if (suggestion.metadata['resolver_version'] != null)
                _DetailChip(
                  label: 'resolver: ${suggestion.metadata['resolver_version']}',
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SuggestionTitle extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;
  final bool dense;

  const _SuggestionTitle({required this.suggestion, this.dense = false});

  @override
  Widget build(BuildContext context) {
    final subtitle =
        '${suggestion.targetType} - ${suggestion.score.toStringAsFixed(0)} - ${suggestion.reason}';
    return Tooltip(
      message: 'Why: $subtitle\n${suggestion.targetPreview}',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            suggestion.targetLabel,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  color: Theme.of(context).colorScheme.onSurface,
                ),
          ),
          Text(
            subtitle,
            maxLines: dense ? 1 : 2,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
        ],
      ),
    );
  }
}

class _SuggestionActions extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;

  const _SuggestionActions({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    if (store == null) return const SizedBox.shrink();
    return Observer(
      builder: (_) {
        final busy =
            store.contextLinkSuggestionReviewing[suggestion.id] == true;
        return Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (busy)
              const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            IconButton(
              key: ValueKey(
                'memory_operations_approve_${sidebarKeyPart(suggestion.id)}',
              ),
              tooltip: 'Approve link',
              visualDensity: VisualDensity.compact,
              onPressed: busy
                  ? null
                  : () => store.reviewContextLinkSuggestion(
                        suggestion,
                        approve: true,
                      ),
              icon: const Icon(Icons.check_circle_outline, size: 18),
            ),
            IconButton(
              key: ValueKey(
                'memory_operations_reject_${sidebarKeyPart(suggestion.id)}',
              ),
              tooltip: 'Reject link',
              visualDensity: VisualDensity.compact,
              onPressed: busy
                  ? null
                  : () => store.reviewContextLinkSuggestion(
                        suggestion,
                        approve: false,
                      ),
              icon: const Icon(Icons.cancel_outlined, size: 18),
            ),
          ],
        );
      },
    );
  }
}

class _StatusDot extends StatelessWidget {
  final String status;

  const _StatusDot({required this.status});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 8,
      height: 8,
      decoration: BoxDecoration(
        color: _statusColor(context, status),
        shape: BoxShape.circle,
      ),
    );
  }
}

class _DetailChip extends StatelessWidget {
  final String label;

  const _DetailChip({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: Theme.of(context)
            .colorScheme
            .surfaceContainerHighest
            .withValues(alpha: 0.58),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        label,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
      ),
    );
  }
}

List<AssetExtractionJob> _attentionJobs(Iterable<AssetExtractionJob> jobs) {
  final sorted = jobs.toList(growable: false);
  sorted.sort((a, b) {
    final ap = _jobPriority(a);
    final bp = _jobPriority(b);
    if (ap != bp) return ap.compareTo(bp);
    return b.updatedAt.compareTo(a.updatedAt);
  });
  return sorted.where((job) => _jobPriority(job) < 4).toList(growable: false);
}

int _jobPriority(AssetExtractionJob job) {
  if (job.status == 'failed' || job.status == 'unsupported') return 0;
  if (job.status == 'canceled' || job.status == 'stale') return 1;
  if (job.status == 'running') return 2;
  if (job.status == 'pending') return 3;
  return 4;
}

String _consoleSubtitle(ChatStore store, MemoryOperationsConsole? console) {
  final generated = console?.generatedAt;
  if (generated == null) return store.activeMemoryScopeExternalRef;
  return '${store.activeMemoryScopeExternalRef} - refreshed ${_timeLabel(generated)}';
}

String _noSuggestionNote(MemoryOperationsConsole? console) {
  final explainability = console?.diagnostics['link_suggestion_explainability'];
  if (explainability is Map) {
    final note = explainability['no_suggestion_note']?.toString().trim();
    if (note != null && note.isNotEmpty) return note;
  }
  return 'No pending links. New suggestions appear after saved captures or files are matched to visible same-scope memories.';
}

List<String> _noSuggestionReasons(MemoryOperationsConsole? console) {
  final explainability = console?.diagnostics['link_suggestion_explainability'];
  if (explainability is! Map) return const <String>[];
  final raw = explainability['no_suggestion_reasons'];
  if (raw is! List) return const <String>[];
  return raw
      .map((item) {
        if (item is Map) return item['label']?.toString().trim() ?? '';
        return item.toString().trim();
      })
      .where((item) => item.isNotEmpty)
      .take(4)
      .toList(growable: false);
}

List<String> _metadataList(Object? value) {
  if (value is! List) return const <String>[];
  return value
      .map((item) => item?.toString().trim() ?? '')
      .where((item) => item.isNotEmpty)
      .toList(growable: false);
}

String _timeLabel(DateTime value) {
  final local = value.toLocal();
  return '${local.year.toString().padLeft(4, '0')}-'
      '${local.month.toString().padLeft(2, '0')}-'
      '${local.day.toString().padLeft(2, '0')} '
      '${local.hour.toString().padLeft(2, '0')}:'
      '${local.minute.toString().padLeft(2, '0')}';
}

Color _statusColor(BuildContext context, String status) {
  final scheme = Theme.of(context).colorScheme;
  return switch (status) {
    'pending' => scheme.tertiary,
    'running' => scheme.primary,
    'succeeded' => Colors.green.shade700,
    'failed' => scheme.error,
    'unsupported' => Colors.orange.shade700,
    'canceled' => scheme.outline,
    'stale' => Colors.blueGrey.shade600,
    _ => scheme.onSurfaceVariant,
  };
}

IconData _iconFor(String type) {
  return switch (type) {
    'fact' => Icons.psychology_alt_outlined,
    'capture' => Icons.history_outlined,
    'asset' => Icons.attach_file,
    'suggestion' => Icons.rate_review_outlined,
    _ => Icons.label_outline,
  };
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

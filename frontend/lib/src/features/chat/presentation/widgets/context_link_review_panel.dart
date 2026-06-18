import 'package:flutter/material.dart';
import 'package:flutter_mobx/flutter_mobx.dart';
import 'package:provider/provider.dart';

import 'package:frontend/src/features/chat/application/stores/chat_store.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_context_link.dart';
import 'package:frontend/src/features/chat/presentation/widgets/context_link_endpoint_dialog.dart';
import 'package:frontend/src/features/chat/presentation/widgets/sidebar_formatters.dart';
import 'package:frontend/src/presentation/theme/app_theme.dart';

class ContextLinkReviewPanel extends StatelessWidget {
  const ContextLinkReviewPanel({super.key});

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    if (store == null) return const SizedBox.shrink();
    return Observer(
      builder: (_) {
        final suggestions = store.contextLinkSuggestions.take(3).toList();
        final pendingCount = store.contextLinkSuggestions.length;
        final loading = store.contextLinkSuggestionsLoading.value;
        final error = store.contextLinkSuggestionError.value;
        if (!loading && error == null && pendingCount == 0) {
          return const SizedBox.shrink();
        }
        return Container(
          key: const ValueKey('context_link_review_panel'),
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
                    Icons.hub_outlined,
                    size: 16,
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      pendingCount == 0
                          ? 'Link review'
                          : 'Link review ($pendingCount)',
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
                      key: const ValueKey('context_link_review_open_button'),
                      tooltip: 'Review all suggested links',
                      visualDensity: VisualDensity.compact,
                      onPressed: pendingCount == 0
                          ? null
                          : () => showContextLinkReviewDialog(context, store),
                      icon: Icon(
                        Icons.rate_review_outlined,
                        size: 18,
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                    IconButton(
                      key: const ValueKey('context_link_review_refresh_button'),
                      tooltip: 'Refresh suggested links',
                      visualDensity: VisualDensity.compact,
                      onPressed:
                          loading ? null : store.refreshContextLinkSuggestions,
                      icon: Icon(
                        Icons.refresh,
                        size: 18,
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ],
              ),
              if (error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    error,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.error,
                        ),
                  ),
                )
              else
                for (final suggestion in suggestions)
                  _ContextLinkSuggestionRow(suggestion: suggestion),
              if (pendingCount > suggestions.length)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(
                    '${pendingCount - suggestions.length} more pending',
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}

void showContextLinkReviewDialog(BuildContext context, ChatStore store) {
  showDialog<void>(
    context: context,
    requestFocus: true,
    traversalEdgeBehavior: TraversalEdgeBehavior.closedLoop,
    builder: (_) => _ContextLinkReviewDialog(store: store),
  );
}

class _ContextLinkReviewDialog extends StatelessWidget {
  final ChatStore store;

  const _ContextLinkReviewDialog({required this.store});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Dialog(
      key: const ValueKey('context_link_review_dialog'),
      insetPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 24),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760, maxHeight: 680),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, 16, 18, 14),
          child: Observer(
            builder: (_) {
              final suggestions = store.contextLinkSuggestions.toList();
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.hub_outlined, size: 20, color: scheme.primary),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Suggested links',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context)
                                  .textTheme
                                  .titleMedium
                                  ?.copyWith(fontWeight: FontWeight.w700),
                            ),
                            Text(
                              '${store.activeMemoryScopeExternalRef} - ${suggestions.length} pending',
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
                        onPressed: store.refreshContextLinkSuggestions,
                        icon: const Icon(Icons.refresh, size: 20),
                      ),
                      IconButton(
                        tooltip: 'Close',
                        onPressed: () => Navigator.of(context).pop(),
                        icon: const Icon(Icons.close, size: 20),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Expanded(
                    child: suggestions.isEmpty
                        ? Center(
                            child: Text(
                              'No pending links',
                              style: Theme.of(context)
                                  .textTheme
                                  .bodyMedium
                                  ?.copyWith(color: scheme.onSurfaceVariant),
                            ),
                          )
                        : ListView.separated(
                            itemCount: suggestions.length,
                            separatorBuilder: (_, __) =>
                                const SizedBox(height: 8),
                            itemBuilder: (_, index) {
                              return _ContextLinkSuggestionTile(
                                suggestion: suggestions[index],
                              );
                            },
                          ),
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

class _ContextLinkSuggestionTile extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;

  const _ContextLinkSuggestionTile({required this.suggestion});

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
          _SuggestionTitle(suggestion: suggestion),
          const SizedBox(height: 6),
          Text(
            suggestion.targetPreview,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: scheme.onSurfaceVariant,
                ),
          ),
          if (_hasEvidenceDetails(suggestion)) ...[
            const SizedBox(height: 8),
            _SuggestionEvidenceChips(suggestion: suggestion),
          ],
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              TextButton.icon(
                key: ValueKey(
                  'context_link_suggestion_source_${sidebarKeyPart(suggestion.id)}',
                ),
                onPressed: () => showContextLinkEndpointDialog(
                  context,
                  suggestion,
                  endpoint: ContextLinkEndpoint.source,
                ),
                icon: const Icon(Icons.input_outlined, size: 16),
                label: const Text('Source'),
              ),
              TextButton.icon(
                key: ValueKey(
                  'context_link_suggestion_target_${sidebarKeyPart(suggestion.id)}',
                ),
                onPressed: () => showContextLinkEndpointDialog(
                  context,
                  suggestion,
                  endpoint: ContextLinkEndpoint.target,
                ),
                icon: const Icon(Icons.output_outlined, size: 16),
                label: const Text('Target'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          _SuggestionActions(suggestion: suggestion, expanded: true),
        ],
      ),
    );
  }
}

class _ContextLinkSuggestionRow extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;

  const _ContextLinkSuggestionRow({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(child: _SuggestionTitle(suggestion: suggestion)),
          _SuggestionActions(suggestion: suggestion),
        ],
      ),
    );
  }
}

class _SuggestionTitle extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;

  const _SuggestionTitle({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final reasonLabel = suggestion.reasonSignalLabels.isNotEmpty
        ? suggestion.reasonSignalLabels.take(2).join(', ')
        : suggestion.reason;
    final evidenceLabel = suggestion.evidenceLabel;
    final subtitle = [
      suggestion.targetType,
      suggestion.score.toStringAsFixed(0),
      if (evidenceLabel != null) evidenceLabel,
      reasonLabel,
    ].join(' - ');
    return Tooltip(
      message: suggestion.targetPreview,
      child: Row(
        children: [
          Icon(_iconFor(suggestion.targetType),
              size: 16, color: scheme.primary),
          const SizedBox(width: 7),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  suggestion.targetLabel,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        fontWeight: FontWeight.w600,
                        color: scheme.onSurface,
                      ),
                ),
                Text(
                  subtitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _SuggestionEvidenceChips extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;

  const _SuggestionEvidenceChips({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    final labels = [
      if (suggestion.evidenceLabel != null)
        'evidence: ${suggestion.evidenceLabel}',
      ...suggestion.reasonSignalLabels.take(3).map((item) => 'signal: $item'),
    ];
    if (labels.isEmpty) return const SizedBox.shrink();
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final label in labels) _SuggestionInfoChip(label: label),
      ],
    );
  }
}

class _SuggestionInfoChip extends StatelessWidget {
  final String label;

  const _SuggestionInfoChip({required this.label});

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
        child: Text(
          label,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.labelSmall,
        ),
      ),
    );
  }
}

class _SuggestionActions extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;
  final bool expanded;

  const _SuggestionActions({
    required this.suggestion,
    this.expanded = false,
  });

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    if (store == null) return const SizedBox.shrink();
    return Observer(
      builder: (_) {
        final busy =
            store.contextLinkSuggestionReviewing[suggestion.id] == true;
        final canReview = suggestion.isPending && !busy;
        final approve = IconButton(
          key: ValueKey(
            'context_link_suggestion_approve_${sidebarKeyPart(suggestion.id)}',
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
        );
        final reject = IconButton(
          key: ValueKey(
            'context_link_suggestion_reject_${sidebarKeyPart(suggestion.id)}',
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
        );
        if (!expanded) {
          return Row(
            mainAxisSize: MainAxisSize.min,
            children: suggestion.isPending ? [approve, reject] : const [],
          );
        }
        return Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (busy)
              const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            if (suggestion.isPending) ...[approve, reject],
          ],
        );
      },
    );
  }
}

bool _hasEvidenceDetails(MemoryContextLinkSuggestion suggestion) {
  return suggestion.evidenceLabel != null ||
      suggestion.reasonSignalLabels.isNotEmpty;
}

IconData _iconFor(String type) {
  return switch (type) {
    'fact' => Icons.psychology_alt_outlined,
    'capture' => Icons.history_outlined,
    'asset' => Icons.attach_file,
    'chunk' => Icons.segment_outlined,
    'document' => Icons.description_outlined,
    'suggestion' => Icons.rate_review_outlined,
    'thread' => Icons.forum_outlined,
    _ => Icons.label_outline,
  };
}

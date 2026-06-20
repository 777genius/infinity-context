import 'package:flutter/material.dart';
import 'package:flutter_mobx/flutter_mobx.dart';
import 'package:provider/provider.dart';

import 'package:frontend/src/features/chat/application/stores/chat_store.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_suggestion.dart';
import 'package:frontend/src/features/chat/presentation/widgets/sidebar_formatters.dart';

class MemoryOperationsMemoryReviewTab extends StatefulWidget {
  final List<MemorySuggestion> suggestions;

  const MemoryOperationsMemoryReviewTab({
    super.key,
    required this.suggestions,
  });

  @override
  State<MemoryOperationsMemoryReviewTab> createState() =>
      _MemoryOperationsMemoryReviewTabState();
}

class _MemoryOperationsMemoryReviewTabState
    extends State<MemoryOperationsMemoryReviewTab> {
  String _statusFilter = 'all';
  String _kindFilter = 'all';

  @override
  Widget build(BuildContext context) {
    final suggestions = _sortedSuggestions(widget.suggestions);
    if (suggestions.isEmpty) {
      return const Center(
        child: Text('No pending memory reviews'),
      );
    }

    final visible = suggestions
        .where((item) =>
            (_statusFilter == 'all' || item.status == _statusFilter) &&
            (_kindFilter == 'all' || item.reviewKind == _kindFilter))
        .toList(growable: false);
    final statusCounts = _statusCounts(suggestions);
    final kindCounts = _kindCounts(suggestions);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 10),
        _ReviewFilters(
          selectedStatus: _statusFilter,
          selectedKind: _kindFilter,
          statusCounts: statusCounts,
          kindCounts: kindCounts,
          onStatusChanged: (value) => setState(() => _statusFilter = value),
          onKindChanged: (value) => setState(() => _kindFilter = value),
        ),
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(
            'Showing ${visible.length} of ${suggestions.length}',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
        ),
        Expanded(
          child: visible.isEmpty
              ? _NoFilterMatches(
                  onClear: () => setState(() {
                    _statusFilter = 'all';
                    _kindFilter = 'all';
                  }),
                )
              : ListView.separated(
                  padding: const EdgeInsets.only(top: 10, bottom: 6),
                  itemCount: visible.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (_, index) => _MemoryReviewTile(
                    suggestion: visible[index],
                  ),
                ),
        ),
      ],
    );
  }
}

class _ReviewFilters extends StatelessWidget {
  final String selectedStatus;
  final String selectedKind;
  final Map<String, int> statusCounts;
  final Map<String, int> kindCounts;
  final ValueChanged<String> onStatusChanged;
  final ValueChanged<String> onKindChanged;

  const _ReviewFilters({
    required this.selectedStatus,
    required this.selectedKind,
    required this.statusCounts,
    required this.kindCounts,
    required this.onStatusChanged,
    required this.onKindChanged,
  });

  @override
  Widget build(BuildContext context) {
    final statuses = <String>[
      'all',
      'pending',
      'approved',
      'rejected',
      'expired',
      ...statusCounts.keys.where(
        (item) =>
            !{'pending', 'approved', 'rejected', 'expired'}.contains(item),
      ),
    ];
    final kinds = <String>['all', ...kindCounts.keys];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          key: const ValueKey('memory_review_status_filters'),
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final status in statuses)
              _FilterChip(
                key: ValueKey('memory_review_status_filter_$status'),
                label: _statusLabel(status),
                count: status == 'all'
                    ? statusCounts.values
                        .fold<int>(0, (sum, value) => sum + value)
                    : statusCounts[status] ?? 0,
                selected: selectedStatus == status,
                onSelected: () => onStatusChanged(status),
              ),
          ],
        ),
        const SizedBox(height: 6),
        Wrap(
          key: const ValueKey('memory_review_kind_filters'),
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final kind in kinds)
              _FilterChip(
                key: ValueKey(
                  'memory_review_kind_filter_${sidebarKeyPart(kind)}',
                ),
                label: kind == 'all' ? 'All kinds' : _kindLabel(kind),
                count: kind == 'all'
                    ? kindCounts.values
                        .fold<int>(0, (sum, value) => sum + value)
                    : kindCounts[kind] ?? 0,
                selected: selectedKind == kind,
                onSelected: () => onKindChanged(kind),
              ),
          ],
        ),
      ],
    );
  }
}

class _FilterChip extends StatelessWidget {
  final String label;
  final int count;
  final bool selected;
  final VoidCallback onSelected;

  const _FilterChip({
    super.key,
    required this.label,
    required this.count,
    required this.selected,
    required this.onSelected,
  });

  @override
  Widget build(BuildContext context) {
    return ChoiceChip(
      label: Text('$label $count'),
      selected: selected,
      visualDensity: VisualDensity.compact,
      onSelected: (_) => onSelected(),
    );
  }
}

class _MemoryReviewTile extends StatelessWidget {
  final MemorySuggestion suggestion;

  const _MemoryReviewTile({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      key: ValueKey(
        'memory_operations_memory_review_${sidebarKeyPart(suggestion.id)}',
      ),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border.all(color: scheme.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(_reviewIcon(suggestion), size: 18, color: scheme.primary),
              const SizedBox(width: 8),
              Expanded(child: _MemoryReviewTitle(suggestion: suggestion)),
              _MemoryReviewActions(suggestion: suggestion),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            suggestion.candidateText,
            maxLines: 5,
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
              _DetailChip(label: 'kind: ${_kindLabel(suggestion.reviewKind)}'),
              _DetailChip(label: 'confidence: ${suggestion.confidence}'),
              _DetailChip(label: 'trust: ${suggestion.trustLevel}'),
              _DetailChip(label: 'status: ${suggestion.status}'),
              if (suggestion.targetFactId != null)
                _DetailChip(
                  label: 'target: ${shortStorageId(suggestion.targetFactId!)}',
                ),
              if (suggestion.targetFactVersion != null)
                _DetailChip(label: 'version: ${suggestion.targetFactVersion}'),
              if (suggestion.recommendedAction != null)
                _DetailChip(
                  label: 'recommended: ${_effectLabel(
                    suggestion.recommendedAction!,
                  )}',
                ),
              if (suggestion.defaultResolution != null)
                _DetailChip(
                  label: 'default: ${_effectLabel(
                    suggestion.defaultResolution!,
                  )}',
                ),
              if (suggestion.safeReason.isNotEmpty)
                _DetailChip(label: 'reason: ${suggestion.safeReason}'),
              if (suggestion.reviewReason != null)
                _DetailChip(label: 'review: ${suggestion.reviewReason}'),
            ],
          ),
        ],
      ),
    );
  }
}

class _MemoryReviewTitle extends StatelessWidget {
  final MemorySuggestion suggestion;

  const _MemoryReviewTitle({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    final target = suggestion.targetFactId == null
        ? 'no target fact'
        : 'fact ${shortStorageId(suggestion.targetFactId!)}';
    return Tooltip(
      message: '${suggestion.safeReason}\n${suggestion.candidateText}',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            suggestion.reviewTitle,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: Theme.of(context).colorScheme.onSurface,
                ),
          ),
          Text(
            '$target - ${suggestion.confidence}',
            maxLines: 1,
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

class _MemoryReviewActions extends StatelessWidget {
  final MemorySuggestion suggestion;

  const _MemoryReviewActions({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    if (store == null) return const SizedBox.shrink();
    return Observer(
      builder: (_) {
        final busy = store.memorySuggestionReviewing[suggestion.id] == true;
        final options = _actionableOptions(suggestion);
        if (busy) {
          return const SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          );
        }
        if (!suggestion.isPending || options.isEmpty) {
          return Icon(
            Icons.lock_outline,
            size: 17,
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          );
        }
        return ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 360),
          child: Wrap(
            alignment: WrapAlignment.end,
            spacing: 4,
            runSpacing: 4,
            children: [
              for (final option in options)
                _MemoryReviewActionButton(
                  suggestion: suggestion,
                  option: option,
                ),
            ],
          ),
        );
      },
    );
  }
}

class _MemoryReviewActionButton extends StatelessWidget {
  final MemorySuggestion suggestion;
  final MemorySuggestionResolutionOption option;

  const _MemoryReviewActionButton({
    required this.suggestion,
    required this.option,
  });

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    if (store == null) return const SizedBox.shrink();
    final action =
        option.resolutionAction.isEmpty ? option.id : option.resolutionAction;
    final key = 'memory_review_${sidebarKeyPart(action)}_'
        '${sidebarKeyPart(suggestion.id)}';
    final primary = action == 'merge_source_refs';
    final child = Text(option.label);
    final icon = Icon(_actionIcon(action), size: 16);
    Future<void> onPressed() => store.resolveDuplicateMemorySuggestion(
          suggestion,
          action: action,
        );
    if (primary) {
      return FilledButton.icon(
        key: ValueKey(key),
        onPressed: onPressed,
        icon: icon,
        label: child,
      );
    }
    return OutlinedButton.icon(
      key: ValueKey(key),
      onPressed: onPressed,
      icon: icon,
      label: child,
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

class _NoFilterMatches extends StatelessWidget {
  final VoidCallback onClear;

  const _NoFilterMatches({required this.onClear});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            'No memory reviews match selected filters',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: 8),
          TextButton.icon(
            key: const ValueKey('memory_review_filters_clear_button'),
            onPressed: onClear,
            icon: const Icon(Icons.filter_alt_off_outlined, size: 16),
            label: const Text('Clear filters'),
          ),
        ],
      ),
    );
  }
}

List<MemorySuggestion> _sortedSuggestions(List<MemorySuggestion> suggestions) {
  final sorted = List<MemorySuggestion>.from(suggestions);
  sorted.sort((a, b) {
    if (a.isPending != b.isPending) return a.isPending ? -1 : 1;
    return b.updatedAt.compareTo(a.updatedAt);
  });
  return sorted;
}

List<MemorySuggestionResolutionOption> _actionableOptions(
  MemorySuggestion suggestion,
) {
  if (!suggestion.canResolveDuplicate) {
    return const <MemorySuggestionResolutionOption>[];
  }
  return suggestion.reviewResolutionOptions
      .where((item) =>
          item.availability == 'available' &&
          (item.resolutionAction.isNotEmpty || item.id.isNotEmpty))
      .toList(growable: false);
}

Map<String, int> _statusCounts(Iterable<MemorySuggestion> suggestions) {
  final counts = <String, int>{};
  for (final suggestion in suggestions) {
    counts.update(suggestion.status, (value) => value + 1, ifAbsent: () => 1);
  }
  return counts;
}

Map<String, int> _kindCounts(Iterable<MemorySuggestion> suggestions) {
  final counts = <String, int>{};
  for (final suggestion in suggestions) {
    counts.update(
      suggestion.reviewKind,
      (value) => value + 1,
      ifAbsent: () => 1,
    );
  }
  return counts;
}

String _statusLabel(String status) {
  return switch (status) {
    'all' => 'All',
    'pending' => 'Pending',
    'approved' => 'Approved',
    'rejected' => 'Rejected',
    'expired' => 'Hidden',
    _ => status,
  };
}

String _kindLabel(String kind) {
  return switch (kind) {
    'duplicate_fact_merge' => 'Duplicate',
    'conflict_review' => 'Conflict',
    'candidate_review' => 'Candidate',
    _ => kind.replaceAll('_', ' '),
  };
}

String _effectLabel(String value) => value.replaceAll('_', ' ');

IconData _reviewIcon(MemorySuggestion suggestion) {
  return switch (suggestion.reviewKind) {
    'duplicate_fact_merge' => Icons.merge_type_outlined,
    'conflict_review' => Icons.report_problem_outlined,
    _ => Icons.fact_check_outlined,
  };
}

IconData _actionIcon(String action) {
  return switch (action) {
    'merge_source_refs' => Icons.call_merge_outlined,
    'keep_separate_fact' => Icons.add_circle_outline,
    'reject_candidate' => Icons.block_outlined,
    'expire_candidate' => Icons.visibility_off_outlined,
    _ => Icons.done_outline,
  };
}

import 'package:flutter/material.dart';
import 'package:flutter_mobx/flutter_mobx.dart';
import 'package:provider/provider.dart';

import 'package:frontend/src/features/chat/application/stores/chat_store.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_context_link.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_operations_console.dart';
import 'package:frontend/src/features/chat/presentation/widgets/context_link_endpoint_dialog.dart';

class MemoryOperationsLinkReviewTab extends StatefulWidget {
  final List<MemoryContextLinkSuggestion> suggestions;
  final MemoryOperationsConsole? console;

  const MemoryOperationsLinkReviewTab({
    super.key,
    required this.suggestions,
    required this.console,
  });

  @override
  State<MemoryOperationsLinkReviewTab> createState() =>
      _MemoryOperationsLinkReviewTabState();
}

class _MemoryOperationsLinkReviewTabState
    extends State<MemoryOperationsLinkReviewTab> {
  String _statusFilter = 'all';
  String _typeFilter = 'all';

  @override
  Widget build(BuildContext context) {
    final suggestions = _sortedSuggestions(widget.suggestions);
    if (suggestions.isEmpty) {
      return _EmptySuggestionState(console: widget.console);
    }

    final visible = suggestions
        .where((item) =>
            (_statusFilter == 'all' || item.status == _statusFilter) &&
            (_typeFilter == 'all' || _typeKey(item) == _typeFilter))
        .toList(growable: false);
    final visiblePending = visible.where((item) => item.isPending).toList(
          growable: false,
        );
    final statusCounts = _statusCounts(suggestions);
    final typeCounts = _typeCounts(suggestions);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 10),
        _ReviewFilters(
          selectedStatus: _statusFilter,
          selectedType: _typeFilter,
          statusCounts: statusCounts,
          typeCounts: typeCounts,
          onStatusChanged: (value) => setState(() => _statusFilter = value),
          onTypeChanged: (value) => setState(() => _typeFilter = value),
        ),
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  'Showing ${visible.length} of ${suggestions.length}',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
              ),
              _BatchReviewActions(visiblePending: visiblePending),
            ],
          ),
        ),
        Expanded(
          child: visible.isEmpty
              ? _NoFilterMatches(
                  onClear: () => setState(() {
                    _statusFilter = 'all';
                    _typeFilter = 'all';
                  }),
                )
              : ListView.separated(
                  padding: const EdgeInsets.only(top: 10, bottom: 6),
                  itemCount: visible.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (_, index) =>
                      _SuggestionTile(suggestion: visible[index]),
                ),
        ),
      ],
    );
  }
}

class _BatchReviewActions extends StatelessWidget {
  final List<MemoryContextLinkSuggestion> visiblePending;

  const _BatchReviewActions({required this.visiblePending});

  @override
  Widget build(BuildContext context) {
    final store = context.read<ChatStore?>();
    if (store == null) return const SizedBox.shrink();
    if (visiblePending.isEmpty) {
      return _approveVisibleButton(
        count: 0,
        busy: false,
        onPressed: null,
      );
    }
    return Observer(
      builder: (_) {
        final busy = visiblePending.any(
          (item) => store.contextLinkSuggestionReviewing[item.id] == true,
        );
        return _approveVisibleButton(
          count: visiblePending.length,
          busy: busy,
          onPressed: busy
              ? null
              : () => store.reviewContextLinkSuggestionsBatch(
                    visiblePending,
                    approve: true,
                  ),
        );
      },
    );
  }

  Widget _approveVisibleButton({
    required int count,
    required bool busy,
    required VoidCallback? onPressed,
  }) {
    return FilledButton.icon(
      key: const ValueKey('memory_link_batch_approve_visible_button'),
      onPressed: onPressed,
      icon: busy
          ? const SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : const Icon(Icons.done_all_outlined, size: 16),
      label: Text('Approve visible ($count)'),
    );
  }
}

class _ReviewFilters extends StatelessWidget {
  final String selectedStatus;
  final String selectedType;
  final Map<String, int> statusCounts;
  final Map<String, int> typeCounts;
  final ValueChanged<String> onStatusChanged;
  final ValueChanged<String> onTypeChanged;

  const _ReviewFilters({
    required this.selectedStatus,
    required this.selectedType,
    required this.statusCounts,
    required this.typeCounts,
    required this.onStatusChanged,
    required this.onTypeChanged,
  });

  @override
  Widget build(BuildContext context) {
    final statuses = <String>[
      'all',
      'pending',
      'approved',
      'rejected',
      ...statusCounts.keys.where(
        (item) => !{'pending', 'approved', 'rejected'}.contains(item),
      ),
    ];
    final types = <String>['all', ...typeCounts.keys];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          key: const ValueKey('memory_link_status_filters'),
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final status in statuses)
              _FilterChip(
                key: ValueKey('memory_link_status_filter_$status'),
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
          key: const ValueKey('memory_link_type_filters'),
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final type in types)
              _FilterChip(
                key: ValueKey('memory_link_type_filter_${_keyPart(type)}'),
                label: type == 'all' ? 'All types' : type,
                count: type == 'all'
                    ? typeCounts.values
                        .fold<int>(0, (sum, value) => sum + value)
                    : typeCounts[type] ?? 0,
                selected: selectedType == type,
                onSelected: () => onTypeChanged(type),
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

class _SuggestionTile extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;

  const _SuggestionTile({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final matchedTerms = _metadataList(suggestion.metadata['matched_terms']);
    final reasonCodes = _metadataList(suggestion.metadata['reason_codes']);
    final policyCodes =
        _metadataList(suggestion.metadata['policy_reason_codes']);
    final signalLabels = suggestion.reasonSignalLabels;
    final evidenceLabel = suggestion.evidenceLabel;
    final evidenceKinds = suggestion.evidenceKinds;
    final reviewGateReason =
        _metadataString(suggestion.metadata['review_gate_reason']);
    final mimeMismatchLabel = _mimeMismatchLabel(suggestion.metadata);
    return Container(
      key: ValueKey('memory_operations_suggestion_${_keyPart(suggestion.id)}'),
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
              Icon(
                _iconForSuggestion(suggestion),
                size: 17,
                color: scheme.primary,
              ),
              const SizedBox(width: 8),
              Expanded(child: _SuggestionTitle(suggestion: suggestion)),
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
              if (reasonCodes.isNotEmpty)
                _DetailChip(
                  label: 'codes: ${reasonCodes.take(3).join(', ')}',
                ),
              if (signalLabels.isNotEmpty)
                _DetailChip(
                  label: 'signals: ${signalLabels.take(4).join(', ')}',
                ),
              if (evidenceLabel != null)
                _DetailChip(label: 'evidence: $evidenceLabel'),
              if (evidenceKinds.isNotEmpty)
                _DetailChip(
                  label: 'evidence kinds: ${evidenceKinds.take(3).join(', ')}',
                ),
              if (suggestion.policyDecision != null)
                _DetailChip(label: 'policy: ${suggestion.policyDecision}'),
              if (suggestion.reviewGate != null)
                _DetailChip(label: 'gate: ${suggestion.reviewGate}'),
              if (reviewGateReason != null)
                _DetailChip(
                  label: 'risk: ${_reviewGateReasonLabel(reviewGateReason)}',
                ),
              if (mimeMismatchLabel != null)
                _DetailChip(label: 'mime: $mimeMismatchLabel'),
              if (suggestion.autoApproveEligible)
                const _DetailChip(label: 'auto eligible'),
              if (policyCodes.isNotEmpty)
                _DetailChip(
                  label: 'policy codes: ${policyCodes.take(3).join(', ')}',
                ),
              if (suggestion.anchorKind != null)
                _DetailChip(label: 'anchor: ${suggestion.anchorKind}'),
              if (suggestion.metadata['normalized_key'] != null)
                _DetailChip(
                  label: 'key: ${suggestion.metadata['normalized_key']}',
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

  const _SuggestionTitle({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    final subtitle =
        '${suggestion.targetTypeLabel} - ${suggestion.score.toStringAsFixed(0)} - ${suggestion.reason}';
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
            maxLines: 2,
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
        final canReview = suggestion.isPending && !busy;
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
                'memory_operations_source_${_keyPart(suggestion.id)}',
              ),
              tooltip: 'Open source',
              visualDensity: VisualDensity.compact,
              onPressed: () => showContextLinkEndpointDialog(
                context,
                suggestion,
                endpoint: ContextLinkEndpoint.source,
              ),
              icon: const Icon(Icons.input_outlined, size: 18),
            ),
            IconButton(
              key: ValueKey(
                'memory_operations_target_${_keyPart(suggestion.id)}',
              ),
              tooltip: 'Open target',
              visualDensity: VisualDensity.compact,
              onPressed: () => showContextLinkEndpointDialog(
                context,
                suggestion,
                endpoint: ContextLinkEndpoint.target,
              ),
              icon: const Icon(Icons.output_outlined, size: 18),
            ),
            IconButton(
              key: ValueKey(
                'memory_operations_evidence_${_keyPart(suggestion.id)}',
              ),
              tooltip: 'Open evidence',
              visualDensity: VisualDensity.compact,
              onPressed: () => _showEvidenceDialog(context, suggestion),
              icon: const Icon(Icons.manage_search_outlined, size: 18),
            ),
            if (suggestion.isPending)
              IconButton(
                key: ValueKey(
                  'memory_operations_edit_${_keyPart(suggestion.id)}',
                ),
                tooltip: 'Edit link',
                visualDensity: VisualDensity.compact,
                onPressed: canReview
                    ? () => _showManualLinkDialog(context, store, suggestion)
                    : null,
                icon: const Icon(Icons.edit_outlined, size: 18),
              ),
            if (suggestion.isPending) ...[
              IconButton(
                key: ValueKey(
                  'memory_operations_approve_${_keyPart(suggestion.id)}',
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
                  'memory_operations_reject_${_keyPart(suggestion.id)}',
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
    );
  }
}

class _EmptySuggestionState extends StatelessWidget {
  final MemoryOperationsConsole? console;

  const _EmptySuggestionState({required this.console});

  @override
  Widget build(BuildContext context) {
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
            'No links match selected filters',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: 8),
          TextButton.icon(
            key: const ValueKey('memory_link_filters_clear_button'),
            onPressed: onClear,
            icon: const Icon(Icons.filter_alt_off_outlined, size: 16),
            label: const Text('Clear filters'),
          ),
        ],
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

class _ManualContextLinkDialog extends StatefulWidget {
  final ChatStore store;
  final MemoryContextLinkSuggestion suggestion;

  const _ManualContextLinkDialog({
    required this.store,
    required this.suggestion,
  });

  @override
  State<_ManualContextLinkDialog> createState() =>
      _ManualContextLinkDialogState();
}

class _ManualContextLinkDialogState extends State<_ManualContextLinkDialog> {
  late final TextEditingController _targetType;
  late final TextEditingController _targetId;
  late final TextEditingController _relationType;
  late final TextEditingController _reason;
  late String _confidence;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    final suggestion = widget.suggestion;
    _targetType = TextEditingController(text: suggestion.targetType);
    _targetId = TextEditingController(text: suggestion.targetId);
    _relationType = TextEditingController(text: suggestion.relationType);
    _reason = TextEditingController(text: suggestion.reason);
    _confidence =
        suggestion.confidence.isEmpty ? 'medium' : suggestion.confidence;
  }

  @override
  void dispose() {
    _targetType.dispose();
    _targetId.dispose();
    _relationType.dispose();
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: const ValueKey('memory_manual_link_dialog'),
      title: const Text('Edit and approve link'),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                key: const ValueKey('memory_manual_link_target_type_field'),
                controller: _targetType,
                decoration: const InputDecoration(labelText: 'Target type'),
                textInputAction: TextInputAction.next,
              ),
              const SizedBox(height: 8),
              TextField(
                key: const ValueKey('memory_manual_link_target_id_field'),
                controller: _targetId,
                decoration: const InputDecoration(labelText: 'Target id'),
                textInputAction: TextInputAction.next,
              ),
              const SizedBox(height: 8),
              TextField(
                key: const ValueKey('memory_manual_link_relation_field'),
                controller: _relationType,
                decoration: const InputDecoration(labelText: 'Relation'),
                textInputAction: TextInputAction.next,
              ),
              const SizedBox(height: 8),
              DropdownButtonFormField<String>(
                key: const ValueKey('memory_manual_link_confidence_field'),
                initialValue: {'low', 'medium', 'high'}.contains(_confidence)
                    ? _confidence
                    : 'medium',
                decoration: const InputDecoration(labelText: 'Confidence'),
                items: const [
                  DropdownMenuItem(value: 'low', child: Text('low')),
                  DropdownMenuItem(value: 'medium', child: Text('medium')),
                  DropdownMenuItem(value: 'high', child: Text('high')),
                ],
                onChanged: (value) => setState(() {
                  _confidence = value ?? 'medium';
                }),
              ),
              const SizedBox(height: 8),
              TextField(
                key: const ValueKey('memory_manual_link_reason_field'),
                controller: _reason,
                decoration: const InputDecoration(labelText: 'Reason'),
                minLines: 2,
                maxLines: 4,
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton.icon(
          key: const ValueKey('memory_manual_link_save_button'),
          onPressed: _busy ? null : _save,
          icon: _busy
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.check_circle_outline, size: 16),
          label: const Text('Approve link'),
        ),
      ],
    );
  }

  Future<void> _save() async {
    final targetType = _targetType.text.trim();
    final targetId = _targetId.text.trim();
    if (targetType.isEmpty || targetId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Target type and id are required')),
      );
      return;
    }
    setState(() => _busy = true);
    final ok = await widget.store.approveContextLinkSuggestionWithOverride(
      widget.suggestion,
      targetType: targetType,
      targetId: targetId,
      relationType: _relationType.text,
      confidence: _confidence,
      reason: _reason.text,
    );
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) Navigator.of(context).pop();
  }
}

class _SuggestionEvidenceDialog extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;

  const _SuggestionEvidenceDialog({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    final metadata = suggestion.metadata.entries
        .where((entry) => entry.value != null)
        .toList(growable: false)
      ..sort((a, b) => a.key.compareTo(b.key));
    return AlertDialog(
      key: const ValueKey('memory_link_evidence_dialog'),
      title: const Text('Link evidence'),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560, maxHeight: 560),
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              _EvidenceRow(
                  label: 'Source',
                  value: '${suggestion.sourceType} ${suggestion.sourceId}'),
              _EvidenceRow(
                  label: 'Target',
                  value:
                      '${suggestion.targetTypeLabel} ${suggestion.targetId}'),
              _EvidenceRow(label: 'Status', value: suggestion.status),
              _EvidenceRow(label: 'Reason', value: suggestion.reason),
              _EvidenceRow(label: 'Preview', value: suggestion.targetPreview),
              if (suggestion.reviewReason != null)
                _EvidenceRow(label: 'Review', value: suggestion.reviewReason!),
              if (suggestion.reviewedAt != null)
                _EvidenceRow(
                  label: 'Reviewed',
                  value: _timeLabel(suggestion.reviewedAt!),
                ),
              const SizedBox(height: 8),
              Text(
                'Metadata',
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
              ),
              const SizedBox(height: 6),
              if (metadata.isEmpty)
                Text(
                  'No metadata',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                )
              else
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final entry in metadata)
                      _DetailChip(
                          label: '${entry.key}: ${_compactValue(entry.value)}'),
                  ],
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
      ],
    );
  }
}

class _EvidenceRow extends StatelessWidget {
  final String label;
  final String value;

  const _EvidenceRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 7),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          Text(
            value,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

void _showManualLinkDialog(
  BuildContext context,
  ChatStore store,
  MemoryContextLinkSuggestion suggestion,
) {
  showDialog<void>(
    context: context,
    builder: (_) => Provider<ChatStore>.value(
      value: store,
      child: _ManualContextLinkDialog(
        store: store,
        suggestion: suggestion,
      ),
    ),
  );
}

void _showEvidenceDialog(
  BuildContext context,
  MemoryContextLinkSuggestion suggestion,
) {
  showDialog<void>(
    context: context,
    builder: (_) => _SuggestionEvidenceDialog(suggestion: suggestion),
  );
}

List<MemoryContextLinkSuggestion> _sortedSuggestions(
  List<MemoryContextLinkSuggestion> suggestions,
) {
  final sorted = suggestions.toList(growable: false);
  sorted.sort((a, b) {
    final status =
        _statusPriority(a.status).compareTo(_statusPriority(b.status));
    if (status != 0) return status;
    return b.updatedAt.compareTo(a.updatedAt);
  });
  return sorted;
}

Map<String, int> _statusCounts(List<MemoryContextLinkSuggestion> suggestions) {
  final counts = <String, int>{};
  for (final item in suggestions) {
    counts[item.status] = (counts[item.status] ?? 0) + 1;
  }
  return counts;
}

Map<String, int> _typeCounts(List<MemoryContextLinkSuggestion> suggestions) {
  final counts = <String, int>{};
  for (final item in suggestions) {
    final key = _typeKey(item);
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
}

String _typeKey(MemoryContextLinkSuggestion suggestion) {
  return suggestion.targetTypeLabel;
}

int _statusPriority(String status) {
  return switch (status) {
    'pending' => 0,
    'rejected' => 1,
    'approved' => 2,
    _ => 3,
  };
}

String _statusLabel(String status) {
  return switch (status) {
    'all' => 'All',
    'pending' => 'Pending',
    'approved' => 'Approved',
    'rejected' => 'Rejected',
    _ => status,
  };
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

String? _metadataString(Object? value) {
  final text = value?.toString().trim();
  return text == null || text.isEmpty ? null : text;
}

String _reviewGateReasonLabel(String value) {
  return switch (value) {
    'prompt_injection_evidence' => 'prompt injection',
    'mime_content_type_mismatch' => 'MIME mismatch',
    _ => value.replaceAll('_', ' '),
  };
}

String? _mimeMismatchLabel(Map<String, dynamic> metadata) {
  if (metadata['mime_content_type_mismatch'] != true) return null;
  final declared = _metadataString(metadata['mime_declared_content_type']);
  final detected = _metadataString(metadata['mime_detected_content_type']);
  if (declared == null && detected == null) return 'mismatch';
  if (declared == null) return detected;
  if (detected == null) return declared;
  return '$declared -> $detected';
}

String _compactValue(Object? value) {
  if (value is List) {
    return value.map((item) => item?.toString() ?? '').take(4).join(', ');
  }
  final text = value?.toString() ?? '';
  if (text.length <= 80) return text;
  return '${text.substring(0, 77)}...';
}

String _timeLabel(DateTime value) {
  final local = value.toLocal();
  return '${local.year.toString().padLeft(4, '0')}-'
      '${local.month.toString().padLeft(2, '0')}-'
      '${local.day.toString().padLeft(2, '0')} '
      '${local.hour.toString().padLeft(2, '0')}:'
      '${local.minute.toString().padLeft(2, '0')}';
}

IconData _iconForSuggestion(MemoryContextLinkSuggestion suggestion) {
  if (suggestion.targetType == 'anchor') {
    return switch (suggestion.anchorKind) {
      'person' => Icons.person_outline,
      'event' => Icons.event_available_outlined,
      'project' => Icons.folder_copy_outlined,
      _ => Icons.hub_outlined,
    };
  }
  return switch (suggestion.targetType) {
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

String _keyPart(String value) {
  return value
      .replaceAll(RegExp(r'[^A-Za-z0-9]+'), '_')
      .replaceAll(RegExp(r'_+'), '_')
      .replaceAll(RegExp(r'^_|_$'), '');
}

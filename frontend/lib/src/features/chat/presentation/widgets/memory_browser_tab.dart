import 'package:flutter/material.dart';
import 'package:flutter_mobx/flutter_mobx.dart';

import 'package:frontend/src/features/chat/application/stores/chat_store.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_browser.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_capture.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_context_link.dart';
import 'package:frontend/src/features/chat/presentation/widgets/sidebar_formatters.dart';

class MemoryBrowserTab extends StatefulWidget {
  final ChatStore store;

  const MemoryBrowserTab({super.key, required this.store});

  @override
  State<MemoryBrowserTab> createState() => _MemoryBrowserTabState();
}

class _MemoryBrowserTabState extends State<MemoryBrowserTab> {
  final TextEditingController _search = TextEditingController();
  _BrowserFilter _filter = _BrowserFilter.all;

  @override
  void initState() {
    super.initState();
    _search.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Observer(
      builder: (_) {
        final snapshot = widget.store.memoryBrowser.value;
        final loading = widget.store.memoryBrowserLoading.value;
        final error = widget.store.memoryBrowserError.value;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _BrowserToolbar(
              controller: _search,
              filter: _filter,
              loading: loading,
              onFilterChanged: (filter) => setState(() => _filter = filter),
              onRefresh: widget.store.refreshMemoryBrowser,
            ),
            if (snapshot != null) ...[
              const SizedBox(height: 8),
              _BrowserCounters(snapshot: snapshot),
            ],
            if (error != null) ...[
              const SizedBox(height: 8),
              _BrowserErrorBanner(error: error),
            ],
            const SizedBox(height: 8),
            Expanded(
              child: _BrowserBody(
                snapshot: snapshot,
                loading: loading,
                query: _search.text,
                filter: _filter,
              ),
            ),
          ],
        );
      },
    );
  }
}

class _BrowserToolbar extends StatelessWidget {
  final TextEditingController controller;
  final _BrowserFilter filter;
  final bool loading;
  final ValueChanged<_BrowserFilter> onFilterChanged;
  final VoidCallback onRefresh;

  const _BrowserToolbar({
    required this.controller,
    required this.filter,
    required this.loading,
    required this.onFilterChanged,
    required this.onRefresh,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 620;
        final search = TextField(
          key: const ValueKey('memory_browser_search_field'),
          controller: controller,
          textInputAction: TextInputAction.search,
          decoration: const InputDecoration(
            prefixIcon: Icon(Icons.search, size: 18),
            hintText: 'Search saved memory',
            isDense: true,
            border: OutlineInputBorder(),
          ),
        );
        final filters = _BrowserFilterChips(
          active: filter,
          onChanged: onFilterChanged,
        );
        final refresh = loading
            ? const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : IconButton(
                key: const ValueKey('memory_browser_refresh_button'),
                tooltip: 'Refresh memory browser',
                onPressed: onRefresh,
                icon: const Icon(Icons.refresh, size: 20),
              );
        if (!wide) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [Expanded(child: search), refresh]),
              const SizedBox(height: 8),
              filters,
            ],
          );
        }
        return Row(
          children: [
            Expanded(child: search),
            const SizedBox(width: 10),
            Flexible(child: filters),
            const SizedBox(width: 4),
            refresh,
          ],
        );
      },
    );
  }
}

class _BrowserFilterChips extends StatelessWidget {
  final _BrowserFilter active;
  final ValueChanged<_BrowserFilter> onChanged;

  const _BrowserFilterChips({
    required this.active,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          for (final filter in _BrowserFilter.values)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: ChoiceChip(
                key: ValueKey('memory_browser_filter_${filter.name}'),
                label: Text(filter.label),
                selected: active == filter,
                onSelected: (_) => onChanged(filter),
                visualDensity: VisualDensity.compact,
              ),
            ),
        ],
      ),
    );
  }
}

class _BrowserCounters extends StatelessWidget {
  final MemoryBrowserSnapshot snapshot;

  const _BrowserCounters({required this.snapshot});

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        _Counter(label: 'Threads', value: snapshot.threads.length),
        _Counter(label: 'Captures', value: snapshot.captures.length),
        _Counter(label: 'Files', value: snapshot.assets.length),
        _Counter(label: 'Anchors', value: snapshot.anchors.length),
        _Counter(label: 'Links', value: snapshot.contextLinks.length),
        _Counter(
          label: 'Pending',
          value: snapshot.contextLinkSuggestions
              .where((suggestion) => suggestion.isPending)
              .length,
        ),
      ],
    );
  }
}

class _Counter extends StatelessWidget {
  final String label;
  final int value;

  const _Counter({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHighest.withValues(alpha: 0.56),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        '$label $value',
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: scheme.onSurfaceVariant,
              fontWeight: FontWeight.w600,
            ),
      ),
    );
  }
}

class _BrowserBody extends StatelessWidget {
  final MemoryBrowserSnapshot? snapshot;
  final bool loading;
  final String query;
  final _BrowserFilter filter;

  const _BrowserBody({
    required this.snapshot,
    required this.loading,
    required this.query,
    required this.filter,
  });

  @override
  Widget build(BuildContext context) {
    if (snapshot == null) {
      if (loading) return const Center(child: CircularProgressIndicator());
      return const Center(child: Text('Memory browser is empty'));
    }
    final sections = _sections(snapshot!, query, filter);
    if (sections.every((section) => section.children.isEmpty)) {
      return const Center(child: Text('No matching memory items'));
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        return ListView(
          key: const ValueKey('memory_browser_list'),
          padding: const EdgeInsets.only(top: 2, bottom: 10),
          children: [
            for (final section in sections)
              if (section.children.isNotEmpty)
                _BrowserSection(
                  title: section.title,
                  icon: section.icon,
                  maxWidth: constraints.maxWidth >= 760 ? 720 : double.infinity,
                  children: section.children,
                ),
          ],
        );
      },
    );
  }

  List<_BrowserSectionData> _sections(
    MemoryBrowserSnapshot snapshot,
    String rawQuery,
    _BrowserFilter active,
  ) {
    final q = rawQuery.trim().toLowerCase();
    final showAll = active == _BrowserFilter.all;
    return [
      _BrowserSectionData(
        title: 'Threads',
        icon: Icons.forum_outlined,
        children: showAll || active == _BrowserFilter.threads
            ? snapshot.threads
                .where((item) => _matches(q, [item.externalRef, item.status]))
                .map((item) => _BrowserItem(
                      icon: Icons.forum_outlined,
                      title: item.externalRef,
                      subtitle:
                          '${item.status} - ${_timeLabel(item.updatedAt)}',
                      meta: shortStorageId(item.id),
                    ))
                .toList(growable: false)
            : const <Widget>[],
      ),
      _BrowserSectionData(
        title: 'Captures',
        icon: Icons.history_outlined,
        children: showAll || active == _BrowserFilter.captures
            ? snapshot.captures
                .where((item) => _matches(q, [
                      item.preview,
                      item.eventType,
                      item.consolidationStatus,
                      item.threadId ?? '',
                    ]))
                .map((item) => _CaptureBrowserItem(capture: item))
                .toList(growable: false)
            : const <Widget>[],
      ),
      _BrowserSectionData(
        title: 'Files',
        icon: Icons.attach_file,
        children: showAll || active == _BrowserFilter.files
            ? snapshot.assets
                .where((item) => _matches(q, [
                      item.filename,
                      item.contentType,
                      item.status,
                      item.threadId ?? '',
                    ]))
                .map((item) => _AssetBrowserItem(asset: item))
                .toList(growable: false)
            : const <Widget>[],
      ),
      _BrowserSectionData(
        title: 'Anchors',
        icon: Icons.hub_outlined,
        children: showAll || active == _BrowserFilter.anchors
            ? snapshot.anchors
                .where((item) => _matches(q, [
                      item.label,
                      item.kind,
                      item.normalizedKey,
                      item.aliases.join(' '),
                      item.description ?? '',
                    ]))
                .map((item) => _AnchorBrowserItem(anchor: item))
                .toList(growable: false)
            : const <Widget>[],
      ),
      _BrowserSectionData(
        title: 'Relations',
        icon: Icons.account_tree_outlined,
        children: showAll || active == _BrowserFilter.links
            ? [
                ...snapshot.contextLinks
                    .where((item) => _matches(q, [
                          item.sourceType,
                          item.targetType,
                          item.relationType,
                          item.reason,
                          item.status,
                        ]))
                    .map((item) => _ContextLinkBrowserItem(link: item)),
                ...snapshot.contextLinkSuggestions
                    .where((item) => _matches(q, [
                          item.sourceType,
                          item.targetType,
                          item.targetLabel,
                          item.relationType,
                          item.reason,
                          item.status,
                        ]))
                    .map((item) => _SuggestionBrowserItem(suggestion: item)),
              ]
            : const <Widget>[],
      ),
    ];
  }
}

class _BrowserSectionData {
  final String title;
  final IconData icon;
  final List<Widget> children;

  const _BrowserSectionData({
    required this.title,
    required this.icon,
    required this.children,
  });
}

class _BrowserSection extends StatelessWidget {
  final String title;
  final IconData icon;
  final List<Widget> children;
  final double maxWidth;

  const _BrowserSection({
    required this.title,
    required this.icon,
    required this.children,
    required this.maxWidth,
  });

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    icon,
                    size: 16,
                    color: Theme.of(context).colorScheme.primary,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    '$title ${children.length}',
                    style: Theme.of(context).textTheme.labelLarge?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              ...children,
            ],
          ),
        ),
      ),
    );
  }
}

class _BrowserItem extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final String meta;
  final String? status;

  const _BrowserItem({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.meta,
    this.status,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      margin: const EdgeInsets.only(bottom: 7),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        border: Border.all(color: scheme.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: scheme.onSurfaceVariant),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        title.isEmpty ? meta : title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                      ),
                    ),
                    if (status != null) ...[
                      const SizedBox(width: 6),
                      _StatusPill(status: status!),
                    ],
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  subtitle,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(
            meta,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: scheme.onSurfaceVariant,
                ),
          ),
        ],
      ),
    );
  }
}

class _CaptureBrowserItem extends StatelessWidget {
  final MemoryCapture capture;

  const _CaptureBrowserItem({required this.capture});

  @override
  Widget build(BuildContext context) {
    return _BrowserItem(
      icon: Icons.history_outlined,
      title: capture.preview,
      subtitle:
          '${capture.eventType} - ${capture.consolidationStatus} - ${_timeLabel(capture.updatedAt)}',
      meta: shortStorageId(capture.id),
      status: capture.status,
    );
  }
}

class _AssetBrowserItem extends StatelessWidget {
  final MemoryBrowserAsset asset;

  const _AssetBrowserItem({required this.asset});

  @override
  Widget build(BuildContext context) {
    return _BrowserItem(
      icon: _assetIcon(asset.contentType),
      title: asset.filename,
      subtitle:
          '${asset.contentType} - ${asset.shortSize} - ${_timeLabel(asset.updatedAt)}',
      meta: shortStorageId(asset.id),
      status: asset.status,
    );
  }
}

class _AnchorBrowserItem extends StatelessWidget {
  final MemoryBrowserAnchor anchor;

  const _AnchorBrowserItem({required this.anchor});

  @override
  Widget build(BuildContext context) {
    final aliases = anchor.aliasesLabel;
    return _BrowserItem(
      icon: _anchorIcon(anchor.kind),
      title: anchor.label,
      subtitle:
          '${anchor.kind} - ${aliases.isEmpty ? anchor.normalizedKey : aliases}',
      meta: shortStorageId(anchor.id),
      status: anchor.status,
    );
  }
}

class _ContextLinkBrowserItem extends StatelessWidget {
  final MemoryContextLink link;

  const _ContextLinkBrowserItem({required this.link});

  @override
  Widget build(BuildContext context) {
    return _BrowserItem(
      icon: Icons.account_tree_outlined,
      title: '${link.sourceType} -> ${link.targetType}',
      subtitle: '${link.relationType} - ${link.confidence} - ${link.reason}',
      meta: shortStorageId(link.id),
      status: link.status,
    );
  }
}

class _SuggestionBrowserItem extends StatelessWidget {
  final MemoryContextLinkSuggestion suggestion;

  const _SuggestionBrowserItem({required this.suggestion});

  @override
  Widget build(BuildContext context) {
    return _BrowserItem(
      icon: Icons.rate_review_outlined,
      title: suggestion.targetLabel,
      subtitle:
          '${suggestion.sourceType} -> ${suggestion.targetTypeLabel} - ${suggestion.score.toStringAsFixed(0)} - ${suggestion.reason}',
      meta: shortStorageId(suggestion.id),
      status: suggestion.status,
    );
  }
}

class _StatusPill extends StatelessWidget {
  final String status;

  const _StatusPill({required this.status});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final active =
        status == 'active' || status == 'stored' || status == 'accepted';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: active
            ? scheme.primaryContainer.withValues(alpha: 0.68)
            : scheme.surfaceContainerHighest.withValues(alpha: 0.68),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        status,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color:
                  active ? scheme.onPrimaryContainer : scheme.onSurfaceVariant,
              fontWeight: FontWeight.w600,
            ),
      ),
    );
  }
}

class _BrowserErrorBanner extends StatelessWidget {
  final String error;

  const _BrowserErrorBanner({required this.error});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      key: const ValueKey('memory_browser_error_banner'),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: scheme.errorContainer.withValues(alpha: 0.34),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: scheme.error.withValues(alpha: 0.24)),
      ),
      child: Text(
        error,
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: scheme.error,
            ),
      ),
    );
  }
}

enum _BrowserFilter {
  all('All'),
  threads('Threads'),
  captures('Captures'),
  files('Files'),
  anchors('Anchors'),
  links('Links');

  final String label;

  const _BrowserFilter(this.label);
}

bool _matches(String query, Iterable<String> values) {
  if (query.isEmpty) return true;
  return values.any((value) => value.toLowerCase().contains(query));
}

IconData _assetIcon(String contentType) {
  if (contentType.startsWith('image/')) return Icons.image_outlined;
  if (contentType.startsWith('audio/')) return Icons.graphic_eq;
  if (contentType.startsWith('video/')) return Icons.movie_outlined;
  if (contentType.contains('pdf')) return Icons.picture_as_pdf_outlined;
  return Icons.attach_file;
}

IconData _anchorIcon(String kind) {
  return switch (kind) {
    'person' => Icons.person_outline,
    'event' => Icons.event_outlined,
    'project' => Icons.work_outline,
    _ => Icons.hub_outlined,
  };
}

String _timeLabel(DateTime value) {
  final local = value.toLocal();
  return '${local.year.toString().padLeft(4, '0')}-'
      '${local.month.toString().padLeft(2, '0')}-'
      '${local.day.toString().padLeft(2, '0')} '
      '${local.hour.toString().padLeft(2, '0')}:'
      '${local.minute.toString().padLeft(2, '0')}';
}

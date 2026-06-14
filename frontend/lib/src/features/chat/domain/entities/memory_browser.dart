import 'package:equatable/equatable.dart';

import 'package:frontend/src/features/chat/domain/entities/memory_capture.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_context_link.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_scope.dart';

class MemoryBrowserSnapshot extends Equatable {
  final DateTime? generatedAt;
  final MemoryScope? memoryScope;
  final List<MemoryBrowserThread> threads;
  final List<MemoryCapture> captures;
  final List<MemoryBrowserAsset> assets;
  final List<MemoryBrowserAnchor> anchors;
  final List<MemoryContextLink> contextLinks;
  final List<MemoryContextLinkSuggestion> contextLinkSuggestions;
  final Map<String, int> stats;
  final Map<String, dynamic> diagnostics;

  const MemoryBrowserSnapshot({
    required this.generatedAt,
    required this.memoryScope,
    required this.threads,
    required this.captures,
    required this.assets,
    required this.anchors,
    required this.contextLinks,
    required this.contextLinkSuggestions,
    required this.stats,
    required this.diagnostics,
  });

  factory MemoryBrowserSnapshot.empty() {
    return const MemoryBrowserSnapshot(
      generatedAt: null,
      memoryScope: null,
      threads: <MemoryBrowserThread>[],
      captures: <MemoryCapture>[],
      assets: <MemoryBrowserAsset>[],
      anchors: <MemoryBrowserAnchor>[],
      contextLinks: <MemoryContextLink>[],
      contextLinkSuggestions: <MemoryContextLinkSuggestion>[],
      stats: <String, int>{},
      diagnostics: <String, dynamic>{},
    );
  }

  factory MemoryBrowserSnapshot.fromMap(Map<String, dynamic> map) {
    final scope = _mapOrNull(map['memory_scope']);
    return MemoryBrowserSnapshot(
      generatedAt: _nullableDate(map['generated_at']),
      memoryScope: scope == null ? null : MemoryScope.fromMap(scope),
      threads: _listOfMaps(map['threads'])
          .map(MemoryBrowserThread.fromMap)
          .toList(growable: false),
      captures: _listOfMaps(map['captures'])
          .map(MemoryCapture.fromMap)
          .toList(growable: false),
      assets: _listOfMaps(map['assets'])
          .map(MemoryBrowserAsset.fromMap)
          .toList(growable: false),
      anchors: _listOfMaps(map['anchors'])
          .map(MemoryBrowserAnchor.fromMap)
          .toList(growable: false),
      contextLinks: _listOfMaps(map['context_links'])
          .map(MemoryContextLink.fromMap)
          .toList(growable: false),
      contextLinkSuggestions: _listOfMaps(map['context_link_suggestions'])
          .map(MemoryContextLinkSuggestion.fromMap)
          .toList(growable: false),
      stats: _intMap(map['stats']),
      diagnostics: _map(map['diagnostics']),
    );
  }

  int stat(String key) => stats[key] ?? 0;

  @override
  List<Object?> get props => [
        generatedAt,
        memoryScope,
        threads,
        captures,
        assets,
        anchors,
        contextLinks,
        contextLinkSuggestions,
        stats,
        diagnostics,
      ];
}

class MemoryBrowserThread extends Equatable {
  final String id;
  final String spaceId;
  final String memoryScopeId;
  final String externalRef;
  final String status;
  final DateTime createdAt;
  final DateTime updatedAt;

  const MemoryBrowserThread({
    required this.id,
    required this.spaceId,
    required this.memoryScopeId,
    required this.externalRef,
    required this.status,
    required this.createdAt,
    required this.updatedAt,
  });

  factory MemoryBrowserThread.fromMap(Map<String, dynamic> map) {
    return MemoryBrowserThread(
      id: _string(map['id']),
      spaceId: _string(map['space_id']),
      memoryScopeId: _string(map['memory_scope_id']),
      externalRef: _string(map['external_ref']),
      status: _string(map['status'], fallback: 'active'),
      createdAt: _date(map['created_at']),
      updatedAt: _date(map['updated_at']),
    );
  }

  @override
  List<Object?> get props => [
        id,
        spaceId,
        memoryScopeId,
        externalRef,
        status,
        createdAt,
        updatedAt,
      ];
}

class MemoryBrowserAsset extends Equatable {
  final String id;
  final String spaceId;
  final String memoryScopeId;
  final String? threadId;
  final String filename;
  final String contentType;
  final int byteSize;
  final String status;
  final String classification;
  final Map<String, dynamic> metadata;
  final DateTime createdAt;
  final DateTime updatedAt;

  const MemoryBrowserAsset({
    required this.id,
    required this.spaceId,
    required this.memoryScopeId,
    required this.threadId,
    required this.filename,
    required this.contentType,
    required this.byteSize,
    required this.status,
    required this.classification,
    required this.metadata,
    required this.createdAt,
    required this.updatedAt,
  });

  factory MemoryBrowserAsset.fromMap(Map<String, dynamic> map) {
    return MemoryBrowserAsset(
      id: _string(map['id']),
      spaceId: _string(map['space_id']),
      memoryScopeId: _string(map['memory_scope_id']),
      threadId: _nullableString(map['thread_id']),
      filename: _string(map['filename']),
      contentType: _string(
        map['content_type'],
        fallback: 'application/octet-stream',
      ),
      byteSize: _int(map['byte_size']),
      status: _string(map['status'], fallback: 'stored'),
      classification: _string(map['classification'], fallback: 'unknown'),
      metadata: _map(map['metadata']),
      createdAt: _date(map['created_at']),
      updatedAt: _date(map['updated_at']),
    );
  }

  String get shortSize {
    if (byteSize >= 1024 * 1024) {
      return '${(byteSize / (1024 * 1024)).toStringAsFixed(1)} MB';
    }
    if (byteSize >= 1024) {
      return '${(byteSize / 1024).toStringAsFixed(1)} KB';
    }
    return '$byteSize B';
  }

  @override
  List<Object?> get props => [
        id,
        spaceId,
        memoryScopeId,
        threadId,
        filename,
        contentType,
        byteSize,
        status,
        classification,
        metadata,
        createdAt,
        updatedAt,
      ];
}

class MemoryBrowserAnchor extends Equatable {
  final String id;
  final String spaceId;
  final String memoryScopeId;
  final String kind;
  final String normalizedKey;
  final String label;
  final List<String> aliases;
  final String? description;
  final String status;
  final Map<String, dynamic> metadata;
  final DateTime createdAt;
  final DateTime updatedAt;

  const MemoryBrowserAnchor({
    required this.id,
    required this.spaceId,
    required this.memoryScopeId,
    required this.kind,
    required this.normalizedKey,
    required this.label,
    required this.aliases,
    required this.description,
    required this.status,
    required this.metadata,
    required this.createdAt,
    required this.updatedAt,
  });

  factory MemoryBrowserAnchor.fromMap(Map<String, dynamic> map) {
    return MemoryBrowserAnchor(
      id: _string(map['id']),
      spaceId: _string(map['space_id']),
      memoryScopeId: _string(map['memory_scope_id']),
      kind: _string(map['kind']),
      normalizedKey: _string(map['normalized_key']),
      label: _string(map['label']),
      aliases: _stringList(map['aliases']),
      description: _nullableString(map['description']),
      status: _string(map['status'], fallback: 'active'),
      metadata: _map(map['metadata']),
      createdAt: _date(map['created_at']),
      updatedAt: _date(map['updated_at']),
    );
  }

  String get aliasesLabel => aliases.where((item) => item != label).join(', ');

  @override
  List<Object?> get props => [
        id,
        spaceId,
        memoryScopeId,
        kind,
        normalizedKey,
        label,
        aliases,
        description,
        status,
        metadata,
        createdAt,
        updatedAt,
      ];
}

Map<String, dynamic> _map(Object? value) {
  if (value is Map<String, dynamic>) return Map<String, dynamic>.from(value);
  if (value is Map) {
    return value.map((key, item) => MapEntry(key.toString(), item));
  }
  return const <String, dynamic>{};
}

Map<String, dynamic>? _mapOrNull(Object? value) {
  if (value == null) return null;
  final mapped = _map(value);
  return mapped.isEmpty ? null : mapped;
}

Map<String, int> _intMap(Object? value) {
  final raw = _map(value);
  return raw.map((key, item) => MapEntry(key, _int(item)));
}

List<Map<String, dynamic>> _listOfMaps(Object? value) {
  if (value is! List) return const <Map<String, dynamic>>[];
  return value
      .whereType<Map>()
      .map((item) => item.map((key, value) => MapEntry(key.toString(), value)))
      .toList(growable: false);
}

List<String> _stringList(Object? value) {
  if (value is! List) return const <String>[];
  return value
      .map((item) => item.toString().trim())
      .where((item) => item.isNotEmpty)
      .toList(growable: false);
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

DateTime _date(Object? value) => _nullableDate(value) ?? DateTime.now();

DateTime? _nullableDate(Object? value) {
  final text = value?.toString();
  if (text == null || text.isEmpty) return null;
  return DateTime.tryParse(text);
}

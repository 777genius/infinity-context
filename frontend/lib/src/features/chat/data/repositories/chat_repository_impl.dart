import 'dart:async';
import 'dart:convert';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:injectable/injectable.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:frontend/src/features/chat/domain/entities/chat_message.dart';
import 'package:frontend/src/features/chat/domain/entities/cost_usage.dart';
import 'package:frontend/src/features/chat/domain/entities/asset_extraction.dart';
import 'package:frontend/src/features/chat/domain/entities/document_chunk.dart';
import 'package:frontend/src/features/chat/domain/entities/extraction_capabilities.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_browser.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_capture.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_context_link.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_operations_console.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_scope.dart';
import 'package:frontend/src/features/chat/domain/repositories/attachment_upload_limits.dart';
import 'package:frontend/src/features/chat/domain/repositories/chat_repository.dart';
import 'package:frontend/src/features/chat/domain/repositories/extraction_capability_provider.dart';
import 'package:frontend/src/features/chat/data/datasources/backend_rest_client.dart';
import 'package:frontend/src/features/chat/domain/entities/connection_status.dart';

@LazySingleton(as: ChatRepository)
class ChatRepositoryImpl
    implements
        ChatRepository,
        ConversationStateRepository,
        AttachmentUploadLimits,
        ExtractionCapabilityProvider {
  final BackendRestClient _rest;
  String Function() _spaceSlugGetter;
  String Function() _memoryScopeExternalRefGetter;

  ChatRepositoryImpl(this._rest)
      : _spaceSlugGetter = (() => 'default'),
        _memoryScopeExternalRefGetter = (() => 'default');

  void updateScopeGetters({
    required String Function() spaceSlug,
    required String Function() memoryScopeExternalRef,
  }) {
    _spaceSlugGetter = spaceSlug;
    _memoryScopeExternalRefGetter = memoryScopeExternalRef;
  }

  final _msgCtrl = StreamController<ChatMessage>.broadcast();
  final _usageCtrl = StreamController<CostUsage>.broadcast();
  final _runningCtrl = StreamController<bool>.broadcast();
  final _statusCtrl = StreamController<ConnectionStatus>.broadcast();
  String? _currentJobId;
  String? _thinkingMsgId;
  final int _historyPairsLimit = 6;
  final List<ChatMessage> _historyText = [];
  final Map<String, List<ChatMessage>> _historyTextByChat = {};
  final Map<String, List<Map<String, String>>> _albumBuffer = {};
  final Map<String, int> _albumTarget = {};
  final List<Map<String, String?>> _pendingAttachments = [];
  ConnectionStatus _lastWsStatus = ConnectionStatus.connecting;
  bool _lastHealthOk = false;
  ConnectionStatus? _lastEffectiveStatus;
  int? _cachedMaxUploadBytes;

  String? _sessionId;
  String? _activeChatId;
  String? _activeMemoryScopeExternalRef;
  final Map<String, String> _lastResponseIdByChat =
      {}; // chatId -> previous_response_id

  @override
  Stream<ChatMessage> messages() => _msgCtrl.stream;

  @override
  Stream<CostUsage> usage() => _usageCtrl.stream;

  @override
  Stream<bool> running() => _runningCtrl.stream;

  @override
  Stream<ConnectionStatus> connectionStatus() => _statusCtrl.stream;

  int _id = 0;
  String _nextId() => (++_id).toString();

  @override
  Future<String> createSession({String? provider}) async {
    try {
      await _rest.healthz();
      _lastHealthOk = true;
      _lastWsStatus = ConnectionStatus.connected;
      _emitEffectiveStatus();
    } catch (e) {
      _lastHealthOk = false;
      _lastWsStatus = ConnectionStatus.disconnected;
      _emitEffectiveStatus();
      _runningCtrl.add(false);
      debugPrint('createSession error: $e');
      rethrow;
    }
    _sessionId =
        _activeChatId ?? DateTime.now().microsecondsSinceEpoch.toString();
    return _sessionId ?? '';
  }

  @override
  void setActiveChat(String chatId) {
    _activeChatId = chatId;
  }

  @override
  void setActiveMemoryScopeExternalRef(String externalRef) {
    final normalized = externalRef.trim();
    _activeMemoryScopeExternalRef = normalized.isEmpty ? 'default' : normalized;
  }

  @override
  String currentMemoryScopeExternalRef() => _currentMemoryScopeExternalRef();

  @override
  Future<List<MemoryScope>> listMemoryScopes() async {
    final space = await _ensureSpace();
    final rows = await _rest.listMemoryScopes(spaceId: space['id'].toString());
    final scopes = rows.map(MemoryScope.fromMap).toList(growable: false);
    if (scopes.isNotEmpty) return scopes;
    final created = await createMemoryScope(
      externalRef: _currentMemoryScopeExternalRef(),
      name: _titleFromRef(_currentMemoryScopeExternalRef()),
    );
    return [created];
  }

  @override
  Future<MemoryScope> createMemoryScope({
    required String externalRef,
    required String name,
  }) async {
    final space = await _ensureSpace();
    final row = await _rest.createMemoryScope(
      spaceId: space['id'].toString(),
      externalRef: _normalizeRef(externalRef),
      name: name.trim().isEmpty ? _titleFromRef(externalRef) : name.trim(),
    );
    return MemoryScope.fromMap(row);
  }

  @override
  Future<MemoryScope> updateMemoryScope({
    required String memoryScopeId,
    String? externalRef,
    String? name,
  }) async {
    final row = await _rest.updateMemoryScope(
      memoryScopeId: memoryScopeId,
      externalRef: externalRef == null ? null : _normalizeRef(externalRef),
      name: name?.trim(),
    );
    return MemoryScope.fromMap(row);
  }

  @override
  Future<void> deleteMemoryScope(String memoryScopeId) {
    return _rest.deleteMemoryScope(memoryScopeId);
  }

  Future<Map<String, dynamic>> _ensureSpace() async {
    final slug = _normalizeRef(_spaceSlugGetter());
    final spaces = await _rest.listSpaces();
    for (final space in spaces) {
      if (space['slug']?.toString() == slug) return space;
    }
    return _rest.createSpace(slug: slug, name: _titleFromRef(slug));
  }

  String _currentMemoryScopeExternalRef() {
    final ref =
        _activeMemoryScopeExternalRef ?? _memoryScopeExternalRefGetter();
    return _normalizeRef(ref);
  }

  /// Restore in-memory conversation history from persisted messages (after app restart).
  @override
  void restoreHistoryFromMessages(String chatId, List<ChatMessage> messages) {
    final list = <ChatMessage>[];
    for (final m in messages.reversed) {
      if ((m.kind == 'text' || m.kind == 'thought') &&
          (m.role == 'user' || m.role == 'assistant') &&
          m.text != null &&
          m.text!.trim().isNotEmpty) {
        list.add(m);
        if (list.length >= _historyPairsLimit * 2) break;
      }
    }
    if (list.isNotEmpty) {
      _historyTextByChat[chatId] = list;
    }
  }

  /// Set last OpenAI response ID for a chat (restored from Hive).
  @override
  void setLastResponseId(String chatId, String? responseId) {
    if (responseId != null && responseId.isNotEmpty) {
      _lastResponseIdByChat[chatId] = responseId;
    }
  }

  @override
  Future<String> runTask({required String task}) async {
    final id = _nextId();
    final displayText = task.isEmpty ? 'Attached file(s).' : task;
    final userMsg = ChatMessage(
        id: _nextId(),
        role: 'user',
        ts: DateTime.now(),
        kind: 'text',
        text: displayText);
    _msgCtrl.add(userMsg);
    _recordHistory(userMsg, chatId: _activeChatId);
    // Remove existing thinking bubble if any (prevents duplicates)
    if (_thinkingMsgId != null) {
      _msgCtrl.add(ChatMessage(
        id: _nextId(),
        role: 'assistant',
        ts: DateTime.now(),
        kind: 'control',
        text: null,
        meta: {'removeMessageId': _thinkingMsgId},
      ));
    }
    _thinkingMsgId = _nextId();
    _msgCtrl.add(ChatMessage(
        id: _thinkingMsgId!,
        role: 'assistant',
        ts: DateTime.now(),
        kind: 'thought',
        text: 'Saving and finding related context...',
        meta: const {'thinking': true}));
    _runningCtrl.add(true);
    _currentJobId = id;
    var captureSaved = false;
    try {
      final chatId = _activeChatId ?? id;
      final assetIds = _pendingAttachments
          .map((item) => item['fileId'])
          .whereType<String>()
          .toList(growable: false);
      final capture = await _rest.createCapture(
        spaceSlug: _spaceSlugGetter(),
        memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
        threadExternalRef: chatId,
        text: task.isEmpty ? 'User attached ${assetIds.length} file(s).' : task,
        assetIds: assetIds,
      );
      final captureId = capture['id']?.toString() ?? '';
      if (captureId.isEmpty) {
        throw StateError('Capture response missing id');
      }
      captureSaved = true;
      Object? suggestionError;
      var suggestions = const <Map<String, dynamic>>[];
      try {
        suggestions = await _rest.suggestLinks(
          spaceSlug: _spaceSlugGetter(),
          memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
          threadExternalRef: chatId,
          text: task,
          sourceType: 'capture',
          sourceId: captureId,
          persist: true,
        );
      } catch (e) {
        suggestionError = e;
      }
      if (_thinkingMsgId != null) {
        _msgCtrl.add(ChatMessage(
          id: _nextId(),
          role: 'assistant',
          ts: DateTime.now(),
          kind: 'control',
          meta: {'removeMessageId': _thinkingMsgId},
        ));
      }
      _msgCtrl.add(ChatMessage(
        id: _nextId(),
        role: 'assistant',
        ts: DateTime.now(),
        kind: 'link_suggestions',
        text: suggestionError != null
            ? 'Saved. Related context suggestions unavailable.'
            : suggestions.isEmpty
                ? 'Saved source-only. No strong context matches yet.'
                : 'Saved. Select related contexts to link.',
        meta: {
          'sourceType': 'capture',
          'sourceId': captureId,
          'candidates': suggestions,
          if (suggestionError != null)
            'suggestionError': _friendlyError(suggestionError),
        },
      ));
      if (suggestionError != null && !_serverResponded(suggestionError)) {
        _lastHealthOk = false;
        _lastWsStatus = ConnectionStatus.disconnected;
      } else {
        _lastHealthOk = true;
        _lastWsStatus = ConnectionStatus.connected;
      }
      _emitEffectiveStatus();
    } catch (e) {
      if (_thinkingMsgId != null) {
        _msgCtrl.add(ChatMessage(
          id: _nextId(),
          role: 'assistant',
          ts: DateTime.now(),
          kind: 'control',
          meta: {'removeMessageId': _thinkingMsgId},
        ));
      }
      _msgCtrl.add(ChatMessage(
        id: _nextId(),
        role: 'system',
        ts: DateTime.now(),
        kind: 'system',
        text: 'Capture failed: ${_friendlyError(e)}',
        meta: const {'isError': true},
      ));
      if (_serverResponded(e)) {
        _lastHealthOk = true;
        _lastWsStatus = ConnectionStatus.connected;
      } else {
        _lastHealthOk = false;
        _lastWsStatus = ConnectionStatus.disconnected;
      }
      _emitEffectiveStatus();
      rethrow;
    } finally {
      _thinkingMsgId = null;
      if (_currentJobId == id) {
        _currentJobId = null;
      }
      _runningCtrl.add(false);
      if (captureSaved) {
        _pendingAttachments.clear();
      }
    }
    return id;
  }

  @override
  Future<void> createContextLink({
    required String sourceType,
    required String sourceId,
    required String targetType,
    required String targetId,
    required String relationType,
    required String confidence,
    required String reason,
  }) async {
    await _rest.createContextLink(
      spaceSlug: _spaceSlugGetter(),
      memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
      sourceType: sourceType,
      sourceId: sourceId,
      targetType: targetType,
      targetId: targetId,
      relationType: relationType,
      confidence: confidence,
      reason: reason,
    );
    _msgCtrl.add(ChatMessage(
      id: _nextId(),
      role: 'system',
      ts: DateTime.now(),
      kind: 'system',
      text: 'Linked to $targetType.',
    ));
  }

  @override
  Future<List<MemoryContextLinkSuggestion>> listContextLinkSuggestions({
    String status = 'pending',
    int limit = 50,
  }) async {
    final rows = await _rest.listContextLinkSuggestions(
      spaceSlug: _spaceSlugGetter(),
      memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
      status: status,
      limit: limit,
    );
    return rows
        .map(MemoryContextLinkSuggestion.fromMap)
        .toList(growable: false);
  }

  @override
  Future<MemoryContextLinkSuggestion> reviewContextLinkSuggestion({
    required String suggestionId,
    required String action,
    String? reason,
    String? targetType,
    String? targetId,
    String? relationType,
    String? confidence,
    String? linkReason,
  }) async {
    final row = await _rest.reviewContextLinkSuggestion(
      suggestionId: suggestionId,
      action: action,
      reason: reason,
      targetType: targetType,
      targetId: targetId,
      relationType: relationType,
      confidence: confidence,
      linkReason: linkReason,
    );
    return MemoryContextLinkSuggestion.fromMap(row);
  }

  @override
  Future<List<MemoryContextLinkSuggestion>> reviewContextLinkSuggestionsBatch({
    required List<String> suggestionIds,
    required String action,
    String? reason,
  }) async {
    final rows = await _rest.reviewContextLinkSuggestionsBatch(
      suggestionIds: suggestionIds,
      action: action,
      reason: reason,
    );
    return rows
        .map(MemoryContextLinkSuggestion.fromMap)
        .toList(growable: false);
  }

  @override
  Future<void> cancelJob(String jobId) async {
    if (_currentJobId == jobId) {
      await cancelCurrentJob();
    }
  }

  @override
  Future<bool> respondApproval({
    required String jobId,
    required String approvalId,
    required bool approved,
  }) async {
    return false;
  }

  @override
  Future<void> cancelCurrentJob() async {
    final jid = _currentJobId;
    if (jid == null) return;
    _currentJobId = null;
    _runningCtrl.add(false);
    _msgCtrl.add(ChatMessage(
        id: _nextId(),
        role: 'system',
        ts: DateTime.now(),
        kind: 'system',
        text: 'Stopped by user.'));
  }

  @override
  Future<String> uploadFile(String name, List<int> bytes,
      {String? mime,
      void Function(int, int)? onProgress,
      void Function(void Function())? onCreateCancel,
      String? previewBase64,
      String? batchId,
      int? batchSize,
      int? batchIndex}) async {
    // Retry with backoff and resume on connectivity
    bool cancelled = false;
    String id = '';
    Future<void> waitForConnectivity() async {
      try {
        final c = Connectivity();
        final state = await c.checkConnectivity();
        if (!_hasConnectivity(state)) {
          await c.onConnectivityChanged
              .firstWhere((state) => _hasConnectivity(state));
        }
      } catch (_) {}
    }

    void wrapOnCreateCancel(void Function() fn) {
      void wrapper() {
        cancelled = true;
        try {
          fn();
        } catch (_) {}
      }

      try {
        onCreateCancel?.call(wrapper);
      } catch (_) {}
    }

    int attempt = 0;
    var requestExtraction = true;
    Map<String, dynamic> uploadedAsset = const <String, dynamic>{};
    while (true) {
      attempt += 1;
      try {
        final asset = await _rest.uploadBytes(
          name,
          bytes,
          spaceSlug: _spaceSlugGetter(),
          memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
          threadExternalRef: _activeChatId,
          mime: mime,
          extract: requestExtraction,
          onProgress: onProgress,
          onCreateCancel: wrapOnCreateCancel,
        );
        uploadedAsset = asset;
        id = asset['id']?.toString() ?? '';
        break;
      } catch (e) {
        if (requestExtraction && _isExtractionDisabled(e)) {
          requestExtraction = false;
          attempt = 0;
          continue;
        }
        if (cancelled || attempt >= 3) {
          rethrow;
        }
        // backoff: 1s, 2s then wait connectivity
        final delay = attempt == 1
            ? const Duration(seconds: 1)
            : const Duration(seconds: 2);
        await Future.delayed(delay);
        await waitForConnectivity();
      }
    }
    final rawExtraction = uploadedAsset['extraction'];
    final extractionMap = rawExtraction is Map
        ? rawExtraction.map((key, value) => MapEntry(key.toString(), value))
        : const <String, dynamic>{};
    final extractionId = extractionMap['id']?.toString();
    final extractionStatus = extractionMap['status']?.toString();
    final assetDeduplication = _nestedMap(uploadedAsset, 'deduplication');
    final extractionDeduplication = _nestedMap(extractionMap, 'deduplication');
    final deduplicationMeta = {
      ..._deduplicationMeta(assetDeduplication, prefix: 'asset'),
      ..._deduplicationMeta(extractionDeduplication, prefix: 'extraction'),
    };
    // emit attachment message for UI
    _msgCtrl.add(ChatMessage(
      id: _nextId(),
      role: 'user',
      ts: DateTime.now(),
      kind: 'attachment',
      text: name,
      meta: {
        'fileId': id,
        'name': name,
        if (mime != null) 'mime': mime,
        if (extractionId != null && extractionId.isNotEmpty)
          'extractionId': extractionId,
        if (extractionStatus != null && extractionStatus.isNotEmpty)
          'extractionStatus': extractionStatus,
        ...deduplicationMeta,
        if (previewBase64 != null) 'previewBase64': previewBase64,
        if (batchId != null) 'batchId': batchId,
        if (batchSize != null) 'batchSize': batchSize,
        if (batchIndex != null) 'batchIndex': batchIndex,
      },
    ));
    _pendingAttachments.add({
      'fileId': id,
      'name': name,
      'mime': mime,
      'extractionId': extractionId,
      'extractionStatus': extractionStatus,
    });

    // Collect album items if batch is provided
    if (batchId != null && batchSize != null && batchSize > 1) {
      final list =
          _albumBuffer.putIfAbsent(batchId, () => <Map<String, String>>[]);
      _albumTarget[batchId] = batchSize;
      list.add({
        'fileId': id,
        'name': name,
        if (previewBase64 != null) 'previewBase64': previewBase64,
      });
      if (list.length >= (_albumTarget[batchId] ?? 0)) {
        // Emit album message
        _msgCtrl.add(ChatMessage(
          id: _nextId(),
          role: 'user',
          ts: DateTime.now(),
          kind: 'attachment_album',
          text: 'Album (${list.length})',
          meta: {
            'items': List<Map<String, String>>.from(list),
          },
        ));
        _albumBuffer.remove(batchId);
        _albumTarget.remove(batchId);
      }
    }
    return id;
  }

  bool _hasConnectivity(List<ConnectivityResult> state) {
    return state.any((item) => item != ConnectivityResult.none);
  }

  @override
  Future<List<int>> downloadFile(String id) async {
    return await _rest.downloadBytes(id);
  }

  @override
  Future<List<AssetExtractionJob>> listAssetExtractions({
    String? status,
    int limit = 50,
  }) async {
    final rows = await _rest.listAssetExtractions(
      spaceSlug: _spaceSlugGetter(),
      memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
      status: status,
      limit: limit,
    );
    final jobs = rows.map(AssetExtractionJob.fromMap).toList(growable: false);
    return Future.wait(jobs.map(_hydrateAssetExtractionArtifacts));
  }

  @override
  Future<AssetExtractionJob> getAssetExtraction(String jobId) async {
    final row = await _rest.getAssetExtraction(jobId);
    return AssetExtractionJob.fromMap(row);
  }

  Future<AssetExtractionJob> _hydrateAssetExtractionArtifacts(
    AssetExtractionJob job,
  ) async {
    if (!job.isSucceeded || job.artifacts.isNotEmpty) return job;
    try {
      return await getAssetExtraction(job.id);
    } catch (_) {
      return job;
    }
  }

  @override
  Future<AssetExtractionJob> retryAssetExtraction(String jobId) async {
    final row = await _rest.retryAssetExtraction(jobId);
    return AssetExtractionJob.fromMap(row);
  }

  @override
  Future<AssetExtractionJob> cancelAssetExtraction(String jobId) async {
    final row = await _rest.cancelAssetExtraction(jobId);
    return AssetExtractionJob.fromMap(row);
  }

  @override
  Future<MemoryOperationsConsole> getOperationsConsole({int limit = 50}) async {
    final row = await _rest.getOperationsConsole(
      spaceSlug: _spaceSlugGetter(),
      memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
      limit: limit,
    );
    return MemoryOperationsConsole.fromMap(row);
  }

  @override
  Future<MemoryBrowserSnapshot> getMemoryBrowser({int limit = 50}) async {
    final row = await _rest.getMemoryBrowser(
      spaceSlug: _spaceSlugGetter(),
      memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
      limit: limit,
    );
    return MemoryBrowserSnapshot.fromMap(row);
  }

  @override
  Future<MemoryBrowserAnchor> createMemoryAnchor({
    required String kind,
    required String label,
    List<String> aliases = const <String>[],
    String? description,
  }) async {
    final row = await _rest.createAnchor(
      spaceSlug: _spaceSlugGetter(),
      memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
      kind: kind,
      label: label,
      aliases: aliases,
      description: description,
    );
    if ((row['id']?.toString().trim().isEmpty ?? true)) {
      throw StateError('Memory scope was not found for anchor creation');
    }
    return MemoryBrowserAnchor.fromMap(row);
  }

  @override
  Future<MemoryBrowserAnchor> updateMemoryAnchor({
    required String anchorId,
    required String label,
    List<String> aliases = const <String>[],
    String? description,
  }) async {
    final row = await _rest.updateAnchor(
      anchorId: anchorId,
      label: label,
      aliases: aliases,
      description: description,
    );
    if ((row['id']?.toString().trim().isEmpty ?? true)) {
      throw StateError('Memory anchor was not found for update');
    }
    return MemoryBrowserAnchor.fromMap(row);
  }

  @override
  Future<void> deleteMemoryAnchor({
    required String anchorId,
    String reason = 'manual delete',
  }) async {
    await _rest.deleteAnchor(anchorId: anchorId, reason: reason);
  }

  @override
  Future<void> backfillMemoryAnchors({int limitPerSource = 100}) async {
    await _rest.backfillAnchors(
      spaceSlug: _spaceSlugGetter(),
      memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
      limitPerSource: limitPerSource,
    );
  }

  @override
  Future<List<MemoryAnchorMergeSuggestion>> listMemoryAnchorMergeSuggestions({
    int limit = 50,
  }) async {
    final row = await _rest.getAnchorMergeSuggestions(
      spaceSlug: _spaceSlugGetter(),
      memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
      limit: limit,
    );
    final candidates = row['candidates'];
    if (candidates is! List) return const <MemoryAnchorMergeSuggestion>[];
    return candidates
        .whereType<Map>()
        .map(
            (item) => item.map((key, value) => MapEntry(key.toString(), value)))
        .map(MemoryAnchorMergeSuggestion.fromMap)
        .toList(growable: false);
  }

  @override
  Future<MemoryBrowserAnchor> mergeMemoryAnchors({
    required String sourceAnchorId,
    required String targetAnchorId,
    required String reason,
  }) async {
    final row = await _rest.mergeAnchor(
      sourceAnchorId: sourceAnchorId,
      targetAnchorId: targetAnchorId,
      reason: reason,
    );
    if ((row['id']?.toString().trim().isEmpty ?? true)) {
      throw StateError('Memory anchor was not found for merge');
    }
    return MemoryBrowserAnchor.fromMap(row);
  }

  @override
  Future<MemoryBrowserAnchor> splitMemoryAnchor({
    required String anchorId,
    required String alias,
    String? newLabel,
    String reason = 'manual split',
  }) async {
    final row = await _rest.splitAnchor(
      anchorId: anchorId,
      alias: alias,
      newLabel: newLabel,
      reason: reason,
    );
    if ((row['id']?.toString().trim().isEmpty ?? true)) {
      throw StateError('Memory anchor was not found for split');
    }
    return MemoryBrowserAnchor.fromMap(row);
  }

  @override
  Future<List<int>> downloadExtractionArtifact(String artifactId) async {
    return _rest.downloadExtractionArtifact(artifactId);
  }

  @override
  Future<List<DocumentChunk>> listDocumentChunks(String documentId) async {
    final rows = await _rest.listDocumentChunks(documentId, limit: 100);
    return rows.map(DocumentChunk.fromMap).toList(growable: false);
  }

  @override
  Future<List<MemoryCapture>> listMemoryCaptures({int limit = 50}) async {
    final rows = await _rest.listCaptures(
      spaceSlug: _spaceSlugGetter(),
      memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
      limit: limit,
    );
    return rows.map(MemoryCapture.fromMap).toList(growable: false);
  }

  @override
  Future<List<MemoryContextLink>> listContextLinks({
    required String sourceType,
    required String sourceId,
    int limit = 50,
  }) async {
    final rows = await _rest.listContextLinks(
      spaceSlug: _spaceSlugGetter(),
      memoryScopeExternalRef: _currentMemoryScopeExternalRef(),
      sourceType: sourceType,
      sourceId: sourceId,
      limit: limit,
    );
    return rows.map(MemoryContextLink.fromMap).toList(growable: false);
  }

  @override
  Future<int> maxUploadBytes() async {
    final cached = _cachedMaxUploadBytes;
    try {
      final capabilities = await _rest.capabilities();
      final maxBytes = _positiveNestedInt(
            capabilities,
            const ['limits', 'max_asset_upload_bytes'],
          ) ??
          _positiveNestedInt(
            capabilities,
            const ['extraction', 'limits', 'max_bytes'],
          ) ??
          AttachmentUploadDefaults.maxBytes;
      _cachedMaxUploadBytes = maxBytes;
      return maxBytes;
    } catch (_) {
      return cached ?? AttachmentUploadDefaults.maxBytes;
    }
  }

  @override
  Future<ExtractionCapabilities> getExtractionCapabilities() async {
    final capabilities = await _rest.capabilities();
    return ExtractionCapabilities.fromMap(
        _nestedMap(capabilities, 'extraction'));
  }

  void _emitEffectiveStatus() {
    ConnectionStatus eff;
    switch (_lastWsStatus) {
      case ConnectionStatus.offline:
        eff = ConnectionStatus.offline;
        break;
      case ConnectionStatus.error:
        eff = ConnectionStatus.error;
        break;
      case ConnectionStatus.disconnected:
        eff = ConnectionStatus.connecting;
        break;
      case ConnectionStatus.connecting:
        eff = ConnectionStatus.connecting;
        break;
      case ConnectionStatus.connected:
        // treat as connected when WS is connected and last health check is OK
        eff = _lastHealthOk
            ? ConnectionStatus.connected
            : ConnectionStatus.connecting;
        break;
    }
    // de-duplicate to avoid UI flicker
    if (_lastEffectiveStatus != eff) {
      _lastEffectiveStatus = eff;
      _statusCtrl.add(eff);
    }
  }

  void _recordHistory(ChatMessage m, {String? chatId}) {
    if (m.kind == 'text' || m.kind == 'thought') {
      if (chatId != null && chatId.isNotEmpty) {
        final list =
            _historyTextByChat.putIfAbsent(chatId, () => <ChatMessage>[]);
        list.insert(0, m);
        final cap = _historyPairsLimit * 2;
        if (list.length > cap) {
          list.removeRange(cap, list.length);
        }
      } else {
        _historyText.insert(0, m);
        final cap = _historyPairsLimit * 2;
        if (_historyText.length > cap) {
          _historyText.removeRange(cap, _historyText.length);
        }
      }
    }
  }

  /// Get last response ID for a chat (for persisting to Hive).
  @override
  String? getLastResponseId(String chatId) => _lastResponseIdByChat[chatId];

  bool _serverResponded(Object error) {
    return error is DioException && error.response != null;
  }

  String _friendlyError(Object error) {
    if (error is DioException) {
      final data = _decodeBackendErrorData(error.response?.data);
      if (data is Map) {
        final backendError = data['error'];
        if (backendError is Map) {
          final message = backendError['message'];
          if (message is String && message.trim().isNotEmpty) {
            return message.trim();
          }
        }
        final detail = data['detail'];
        if (detail is String && detail.trim().isNotEmpty) {
          return detail.trim();
        }
      }
      final message = error.message;
      if (message != null && message.trim().isNotEmpty) {
        return message.trim();
      }
    }
    return error.toString();
  }

  bool _isExtractionDisabled(Object error) {
    if (error is! DioException) return false;
    final status = error.response?.statusCode ?? 0;
    if (status < 400 || status >= 500) return false;
    return _friendlyError(error).toLowerCase().contains(
          'asset extraction is disabled',
        );
  }

  Object? _decodeBackendErrorData(Object? data) {
    if (data is String && data.trim().isNotEmpty) {
      try {
        return jsonDecode(data);
      } catch (_) {
        return data;
      }
    }
    return data;
  }

  /// Cleanup resources to prevent memory leaks
  Future<void> dispose() async {
    await _msgCtrl.close();
    await _usageCtrl.close();
    await _runningCtrl.close();
    await _statusCtrl.close();
  }
}

String _normalizeRef(String value) {
  final normalized = value.trim();
  return normalized.isEmpty ? 'default' : normalized;
}

String _titleFromRef(String ref) {
  final normalized = _normalizeRef(ref);
  return normalized
      .replaceAll(RegExp(r'[-_]+'), ' ')
      .split(' ')
      .where((part) => part.isNotEmpty)
      .map((part) => part[0].toUpperCase() + part.substring(1))
      .join(' ');
}

int? _positiveNestedInt(Map<String, dynamic> root, List<String> path) {
  Object? cursor = root;
  for (final key in path) {
    if (cursor is! Map) return null;
    cursor = cursor[key];
  }
  if (cursor is int && cursor > 0) return cursor;
  if (cursor is num && cursor > 0) return cursor.toInt();
  if (cursor is String) {
    final parsed = int.tryParse(cursor);
    if (parsed != null && parsed > 0) return parsed;
  }
  return null;
}

Map<String, dynamic> _nestedMap(Map<String, dynamic> root, String key) {
  final value = root[key];
  if (value is Map<String, dynamic>) return Map<String, dynamic>.from(value);
  if (value is Map) {
    return value.map((key, item) => MapEntry(key.toString(), item));
  }
  return const <String, dynamic>{};
}

Map<String, dynamic> _deduplicationMeta(
  Map<String, dynamic> deduplication, {
  required String prefix,
}) {
  if (deduplication.isEmpty) return const <String, dynamic>{};
  final status = deduplication['status']?.toString();
  final reasonCode = deduplication['reason_code']?.toString();
  final suggestionId = deduplication['suggestion_id']?.toString();
  final suggestionStatus = deduplication['suggestion_status']?.toString();
  final duplicateOfAssetId = deduplication['duplicate_of_asset_id']?.toString();
  final duplicateOfJobId = deduplication['duplicate_of_job_id']?.toString();
  final matchType = deduplication['match_type']?.toString();
  final recommendedAction = deduplication['recommended_action']?.toString();
  final sourceLabel = deduplication['source_label']?.toString();
  final targetLabel = deduplication['target_label']?.toString();
  final reasonCodes = _deduplicationReasonCodes(deduplication['reason_codes']);
  final duplicate = deduplication['duplicate'];
  return {
    if (duplicate is bool) '${prefix}Duplicate': duplicate,
    if (status != null && status.isNotEmpty)
      '${prefix}DeduplicationStatus': status,
    if (reasonCode != null && reasonCode.isNotEmpty)
      '${prefix}DeduplicationReasonCode': reasonCode,
    if (matchType != null && matchType.isNotEmpty)
      '${prefix}DeduplicationMatchType': matchType,
    if (reasonCodes.isNotEmpty)
      '${prefix}DeduplicationReasonCodes': reasonCodes,
    if (recommendedAction != null && recommendedAction.isNotEmpty)
      '${prefix}DeduplicationRecommendedAction': recommendedAction,
    if (sourceLabel != null && sourceLabel.isNotEmpty)
      '${prefix}DeduplicationSourceLabel': sourceLabel,
    if (targetLabel != null && targetLabel.isNotEmpty)
      '${prefix}DeduplicationTargetLabel': targetLabel,
    if (duplicateOfAssetId != null && duplicateOfAssetId.isNotEmpty)
      '${prefix}DuplicateOfAssetId': duplicateOfAssetId,
    if (duplicateOfJobId != null && duplicateOfJobId.isNotEmpty)
      '${prefix}DuplicateOfJobId': duplicateOfJobId,
    if (suggestionId != null && suggestionId.isNotEmpty)
      'contextLinkSuggestionId': suggestionId,
    if (suggestionStatus != null && suggestionStatus.isNotEmpty)
      'contextLinkSuggestionStatus': suggestionStatus,
  };
}

List<String> _deduplicationReasonCodes(Object? value) {
  if (value is Iterable) {
    return value
        .map((item) => item?.toString().trim() ?? '')
        .where((item) => item.isNotEmpty)
        .toList(growable: false);
  }
  final text = value?.toString().trim();
  return text == null || text.isEmpty ? const <String>[] : <String>[text];
}

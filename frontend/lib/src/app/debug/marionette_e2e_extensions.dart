import 'dart:async';
import 'dart:convert';
import 'dart:developer' as developer;

import 'package:flutter/widgets.dart';
import 'package:frontend/src/features/chat/application/services/attachment_upload_models.dart';
import 'package:frontend/src/features/chat/application/services/attachment_upload_service.dart';
import 'package:frontend/src/features/chat/application/stores/chat_store.dart';
import 'package:frontend/src/features/chat/domain/entities/asset_extraction.dart';
import 'package:frontend/src/features/chat/domain/entities/chat_message.dart';
import 'package:frontend/src/features/chat/domain/entities/chat_session.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_browser.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_capture.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_context_link.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_scope.dart';
import 'package:provider/provider.dart';

part 'marionette_e2e_extension_support.dart';

typedef ChatStoreResolver = ChatStore Function();

class MemoStackMarionetteE2eBridge extends StatefulWidget {
  final Widget child;

  const MemoStackMarionetteE2eBridge({
    required this.child,
    super.key,
  });

  @override
  State<MemoStackMarionetteE2eBridge> createState() =>
      _MemoStackMarionetteE2eBridgeState();
}

class _MemoStackMarionetteE2eBridgeState
    extends State<MemoStackMarionetteE2eBridge> {
  static MemoStackMarionetteE2eCommandHandler? _activeHandler;
  static final Set<String> _registeredExtensions = <String>{};

  @override
  void initState() {
    super.initState();
    _registerExtensions();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _activeHandler = MemoStackMarionetteE2eCommandHandler(() {
      if (!mounted) {
        throw StateError('Memo Stack E2E bridge is not mounted');
      }
      return context.read<ChatStore>();
    });
  }

  @override
  void dispose() {
    _activeHandler = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;

  static void _registerExtensions() {
    _register(
      'memoStack.e2eState',
      (handler, params) => handler.state(),
    );
    _register(
      'memoStack.refresh',
      (handler, params) => handler.refresh(),
    );
    _register(
      'memoStack.createMemoryScope',
      (handler, params) => handler.createMemoryScope(params),
    );
    _register(
      'memoStack.switchMemoryScope',
      (handler, params) => handler.switchMemoryScope(params),
    );
    _register(
      'memoStack.createThread',
      (handler, params) => handler.createThread(params),
    );
    _register(
      'memoStack.submitCapture',
      (handler, params) => handler.submitCapture(params),
    );
    _register(
      'memoStack.submitAttachmentCapture',
      (handler, params) => handler.submitAttachmentCapture(params),
    );
    _register(
      'memoStack.retryAssetExtraction',
      (handler, params) => handler.retryAssetExtraction(params),
    );
    _register(
      'memoStack.cancelAssetExtraction',
      (handler, params) => handler.cancelAssetExtraction(params),
    );
    _register(
      'memoStack.reviewFirstPendingLinkSuggestion',
      (handler, params) => handler.reviewFirstPendingLinkSuggestion(params),
    );
    _register(
      'memoStack.createManualContextLinkFromSuggestion',
      (handler, params) =>
          handler.createManualContextLinkFromSuggestion(params),
    );
    _register(
      'memoStack.createMemoryAnchor',
      (handler, params) => handler.createMemoryAnchor(params),
    );
    _register(
      'memoStack.updateMemoryAnchor',
      (handler, params) => handler.updateMemoryAnchor(params),
    );
    _register(
      'memoStack.deleteMemoryAnchor',
      (handler, params) => handler.deleteMemoryAnchor(params),
    );
    _register(
      'memoStack.splitMemoryAnchorAlias',
      (handler, params) => handler.splitMemoryAnchorAlias(params),
    );
    _register(
      'memoStack.mergeFirstAnchorSuggestion',
      (handler, params) => handler.mergeFirstAnchorSuggestion(params),
    );
    _register(
      'memoStack.backfillMemoryAnchors',
      (handler, params) => handler.backfillMemoryAnchors(params),
    );
  }

  static void _register(
    String name,
    Future<Map<String, dynamic>> Function(
      MemoStackMarionetteE2eCommandHandler handler,
      Map<String, String> params,
    ) callback,
  ) {
    if (_registeredExtensions.contains(name)) return;
    _registeredExtensions.add(name);
    developer.registerExtension(
      'ext.flutter.$name',
      (String method, Map<String, String> params) async {
        final handler = _activeHandler;
        if (handler == null) {
          return _errorResponse(
            StateError('Memo Stack E2E bridge is not ready'),
            StackTrace.current,
          );
        }
        try {
          final result = await callback(handler, params);
          return _resultResponse(result);
        } catch (error, stack) {
          return _errorResponse(error, stack);
        }
      },
    );
  }
}

@visibleForTesting
class MemoStackMarionetteE2eCommandHandler {
  final ChatStoreResolver _store;

  MemoStackMarionetteE2eCommandHandler(this._store);

  Future<Map<String, dynamic>> state() async {
    return _state(_store());
  }

  Future<Map<String, dynamic>> refresh() async {
    final store = _store();
    await _refreshEvidence(store);
    return _state(store);
  }

  Future<Map<String, dynamic>> createMemoryScope(
    Map<String, String> params,
  ) async {
    final store = _store();
    final externalRef = _required(params, 'externalRef');
    final scope = await _ensureMemoryScope(
      store,
      externalRef: externalRef,
      name: params['name'],
    );
    await _refreshEvidence(store);
    return {
      ..._state(store),
      'memoryScope': _scopeToMap(scope),
    };
  }

  Future<Map<String, dynamic>> switchMemoryScope(
    Map<String, String> params,
  ) async {
    final store = _store();
    await store.setActiveMemoryScope(_required(params, 'externalRef'));
    await _refreshEvidence(store);
    return _state(store);
  }

  Future<Map<String, dynamic>> createThread(Map<String, String> params) async {
    final store = _store();
    final scopeRef = _optional(params, 'memoryScopeExternalRef');
    if (scopeRef != null) {
      await _ensureMemoryScope(
        store,
        externalRef: scopeRef,
        name: params['memoryScopeName'],
      );
    }
    final threadId = store.createNewChat(
      title: _optional(params, 'title'),
      memoryScopeExternalRef: scopeRef,
    );
    await _refreshEvidence(store);
    return {
      ..._state(store),
      'threadId': threadId,
    };
  }

  Future<Map<String, dynamic>> submitCapture(
    Map<String, String> params,
  ) async {
    final store = _store();
    final scopeRef = _optional(params, 'memoryScopeExternalRef');
    if (scopeRef != null) {
      await _ensureMemoryScope(
        store,
        externalRef: scopeRef,
        name: params['memoryScopeName'],
      );
    }
    final threadId = _optional(params, 'threadId');
    if (threadId != null) {
      await store.setActiveChat(threadId);
    } else if (_truthy(params['createThread']) ||
        _optional(params, 'threadTitle') != null) {
      store.createNewChat(
        title: _optional(params, 'threadTitle'),
        memoryScopeExternalRef: scopeRef,
      );
    }
    await store.sendTask(_required(params, 'text'));
    await _refreshEvidence(store);
    return _state(store);
  }

  Future<Map<String, dynamic>> submitAttachmentCapture(
    Map<String, String> params,
  ) async {
    final store = _store();
    final scopeRef = _optional(params, 'memoryScopeExternalRef');
    if (scopeRef != null) {
      await _ensureMemoryScope(
        store,
        externalRef: scopeRef,
        name: params['memoryScopeName'],
      );
    }
    final threadId = _optional(params, 'threadId');
    if (threadId != null) {
      await store.setActiveChat(threadId);
    } else if (_truthy(params['createThread']) ||
        _optional(params, 'threadTitle') != null) {
      store.createNewChat(
        title: _optional(params, 'threadTitle'),
        memoryScopeExternalRef: scopeRef,
      );
    }

    final filename = _optional(params, 'filename') ?? 'memo-stack-e2e-note.txt';
    final content = _attachmentBytes(params);
    final uploadedAssetIds =
        await AttachmentUploadService(repo: store.repo).uploadAll([
      AttachmentUploadDraft.file(
        name: filename,
        bytes: content,
        mime: _optional(params, 'mime') ?? 'text/plain',
      ),
    ]);
    if (uploadedAssetIds.isEmpty) {
      throw StateError('Attachment upload did not return an asset id');
    }
    await store.sendTask(_required(params, 'text'));
    await _refreshEvidence(store);
    return {
      ..._state(store),
      'uploadedAssetIds': uploadedAssetIds,
    };
  }

  Future<Map<String, dynamic>> retryAssetExtraction(
    Map<String, String> params,
  ) async {
    final store = _store();
    final job = await _findAssetExtraction(
      store,
      params,
      canUse: (item) => item.canRetry,
      actionName: 'retry',
    );
    await store.retryAssetExtraction(job);
    final error = store.assetExtractionError;
    if (error != null) {
      throw StateError(error);
    }
    await _refreshEvidence(store);
    final updated = await _findAssetExtractionById(store, job.id);
    return {
      ..._state(store),
      'retried': true,
      'assetExtraction': _extractionToMap(updated),
    };
  }

  Future<Map<String, dynamic>> cancelAssetExtraction(
    Map<String, String> params,
  ) async {
    final store = _store();
    final job = await _findAssetExtraction(
      store,
      params,
      canUse: (item) => item.canCancel,
      actionName: 'cancel',
    );
    await store.cancelAssetExtraction(job);
    final error = store.assetExtractionError;
    if (error != null) {
      throw StateError(error);
    }
    await _refreshEvidence(store);
    final updated = await _findAssetExtractionById(store, job.id);
    return {
      ..._state(store),
      'canceled': true,
      'assetExtraction': _extractionToMap(updated),
    };
  }

  Future<Map<String, dynamic>> reviewFirstPendingLinkSuggestion(
    Map<String, String> params,
  ) async {
    final store = _store();
    await store.refreshContextLinkSuggestions(showLoading: false);
    final pending = _matchingPendingLinkSuggestions(store, params);
    if (pending.isEmpty) {
      return {
        ..._state(store),
        'reviewed': false,
      };
    }
    final approve = !_falsey(params['approve']);
    await store.reviewContextLinkSuggestion(
      pending.first,
      approve: approve,
    );
    await _refreshEvidence(store);
    return {
      ..._state(store),
      'reviewed': true,
      'reviewedSuggestionId': pending.first.id,
      'reviewedTargetType': pending.first.targetType,
      'reviewedTargetId': pending.first.targetId,
      'reviewAction': approve ? 'approve' : 'reject',
    };
  }

  Future<Map<String, dynamic>> createManualContextLinkFromSuggestion(
    Map<String, String> params,
  ) async {
    final store = _store();
    await store.refreshContextLinkSuggestions(showLoading: false);
    final pending = _matchingPendingLinkSuggestions(
      store,
      params,
      includeTargetAliases: false,
    );
    if (pending.isEmpty) {
      return {
        ..._state(store),
        'manualLinked': false,
      };
    }
    final suggestion = pending.first;
    final targetType = _required(params, 'targetType');
    final targetId = _required(params, 'targetId');
    final ok = await store.createManualContextLinkFromSuggestion(
      suggestion,
      targetType: targetType,
      targetId: targetId,
      relationType:
          _optional(params, 'relationType') ?? suggestion.relationType,
      confidence: _optional(params, 'confidence') ?? suggestion.confidence,
      reason: _optional(params, 'reason') ?? 'selected by user',
    );
    _throwIfFailed(
      ok,
      store.contextLinkSuggestionError.value,
      'Manual context link was not created',
    );
    await _refreshEvidence(store);
    return {
      ..._state(store),
      'manualLinked': true,
      'manualLinkSuggestionId': suggestion.id,
      'manualLinkTargetType': targetType,
      'manualLinkTargetId': targetId,
    };
  }

  Future<Map<String, dynamic>> createMemoryAnchor(
    Map<String, String> params,
  ) async {
    final store = _store();
    final scopeRef = _optional(params, 'memoryScopeExternalRef');
    if (scopeRef != null) {
      await _ensureMemoryScope(
        store,
        externalRef: scopeRef,
        name: params['memoryScopeName'],
      );
    }
    final label = _required(params, 'label');
    final ok = await store.createMemoryAnchor(
      kind: _optional(params, 'kind') ?? 'person',
      label: label,
      aliases: _listParam(params, 'aliases'),
      description: _optional(params, 'description'),
    );
    _throwIfFailed(
        ok, store.memoryBrowserError.value, 'Anchor was not created');
    await _refreshEvidence(store);
    final anchor = await _findAnchor(store, label: label);
    return {
      ..._state(store),
      'anchor': _anchorToMap(anchor),
    };
  }

  Future<Map<String, dynamic>> updateMemoryAnchor(
    Map<String, String> params,
  ) async {
    final store = _store();
    final anchor = await _findAnchor(
      store,
      anchorId: _optional(params, 'anchorId'),
      label: _optional(params, 'currentLabel'),
    );
    final label = _required(params, 'label');
    final ok = await store.updateMemoryAnchor(
      anchor,
      label: label,
      aliases: _listParam(params, 'aliases'),
      description: _optional(params, 'description'),
    );
    _throwIfFailed(
        ok, store.memoryBrowserError.value, 'Anchor was not updated');
    await _refreshEvidence(store);
    final updated = await _findAnchor(store, anchorId: anchor.id, label: label);
    return {
      ..._state(store),
      'anchor': _anchorToMap(updated),
    };
  }

  Future<Map<String, dynamic>> deleteMemoryAnchor(
    Map<String, String> params,
  ) async {
    final store = _store();
    final anchor = await _findAnchor(
      store,
      anchorId: _optional(params, 'anchorId'),
      label: _optional(params, 'label'),
    );
    final ok = await store.deleteMemoryAnchor(
      anchor,
      reason: _optional(params, 'reason') ?? 'deleted by marionette e2e',
    );
    _throwIfFailed(
        ok, store.memoryBrowserError.value, 'Anchor was not deleted');
    await _refreshEvidence(store);
    return {
      ..._state(store),
      'deletedAnchorId': anchor.id,
      'deletedAnchorLabel': anchor.label,
    };
  }

  Future<Map<String, dynamic>> splitMemoryAnchorAlias(
    Map<String, String> params,
  ) async {
    final store = _store();
    final anchor = await _findAnchor(
      store,
      anchorId: _optional(params, 'anchorId'),
      label: _optional(params, 'label'),
    );
    final alias = _required(params, 'alias');
    final ok = await store.splitMemoryAnchorAlias(
      anchor,
      alias: alias,
      newLabel: _optional(params, 'newLabel'),
      reason: _optional(params, 'reason') ?? 'split by marionette e2e',
    );
    _throwIfFailed(ok, store.memoryBrowserError.value, 'Anchor was not split');
    await _refreshEvidence(store);
    final split = await _findAnchor(
      store,
      label: _optional(params, 'newLabel') ?? alias,
    );
    return {
      ..._state(store),
      'sourceAnchorId': anchor.id,
      'splitAnchor': _anchorToMap(split),
    };
  }

  Future<Map<String, dynamic>> mergeFirstAnchorSuggestion(
    Map<String, String> params,
  ) async {
    final store = _store();
    await store.refreshMemoryBrowser(showLoading: false);
    final sourceAnchorId = _optional(params, 'sourceAnchorId');
    final targetAnchorId = _optional(params, 'targetAnchorId');
    final suggestions = store.anchorMergeSuggestions.where((item) {
      final sourceMatches =
          sourceAnchorId == null || item.sourceAnchor.id == sourceAnchorId;
      final targetMatches =
          targetAnchorId == null || item.targetAnchor.id == targetAnchorId;
      return sourceMatches && targetMatches;
    }).toList(growable: false);
    if (suggestions.isEmpty) {
      return {
        ..._state(store),
        'merged': false,
      };
    }
    final suggestion = suggestions.first;
    final ok = await store.mergeMemoryAnchorSuggestion(suggestion);
    _throwIfFailed(ok, store.memoryBrowserError.value, 'Anchor was not merged');
    await _refreshEvidence(store);
    return {
      ..._state(store),
      'merged': true,
      'mergedSourceAnchorId': suggestion.sourceAnchor.id,
      'mergedTargetAnchorId': suggestion.targetAnchor.id,
    };
  }

  Future<Map<String, dynamic>> backfillMemoryAnchors(
    Map<String, String> params,
  ) async {
    final store = _store();
    final ok = await store.backfillMemoryAnchors(
      limitPerSource: _intParam(params, 'limitPerSource', fallback: 100),
    );
    _throwIfFailed(
      ok,
      store.memoryBrowserError.value,
      'Anchor backfill failed',
    );
    await _refreshEvidence(store);
    return _state(store);
  }

  Future<MemoryScope> _ensureMemoryScope(
    ChatStore store, {
    required String externalRef,
    String? name,
  }) async {
    await store.refreshMemoryScopes();
    final ref = _normalizeRef(externalRef);
    final existing = store.memoryScopes
        .where((scope) => scope.externalRef == ref)
        .firstOrNull;
    if (existing != null) {
      await store.setActiveMemoryScope(existing.externalRef);
      return existing;
    }
    final created = await store.createMemoryScope(
      externalRef: ref,
      name: _optionalName(name) ?? _titleFromRef(ref),
    );
    if (created == null) {
      throw StateError(
          store.memoryScopeError ?? 'Memory scope was not created');
    }
    return created;
  }

  Future<void> _refreshEvidence(ChatStore store) async {
    await Future.wait([
      store.refreshMemoryCaptures(showLoading: false),
      store.refreshOperationsConsole(showLoading: false),
      store.refreshMemoryBrowser(showLoading: false),
    ]);
    await store.refreshAssetExtractions(showLoading: false);
  }

  Future<AssetExtractionJob> _findAssetExtraction(
    ChatStore store,
    Map<String, String> params, {
    required bool Function(AssetExtractionJob job) canUse,
    required String actionName,
  }) async {
    await store.refreshAssetExtractions(showLoading: false);
    final jobId = _optional(params, 'jobId');
    final assetId = _optional(params, 'assetId');
    final status = _optional(params, 'status');
    final matches = store.assetExtractions.where((job) {
      if (jobId != null && job.id != jobId) return false;
      if (assetId != null && job.assetId != assetId) return false;
      if (status != null && job.status != status) return false;
      return canUse(job);
    }).toList(growable: false);
    if (matches.isNotEmpty) return matches.first;
    final selector = {
      if (jobId != null) 'jobId': jobId,
      if (assetId != null) 'assetId': assetId,
      if (status != null) 'status': status,
    };
    throw StateError(
      'No asset extraction can $actionName for selector $selector',
    );
  }

  Future<AssetExtractionJob> _findAssetExtractionById(
    ChatStore store,
    String jobId,
  ) async {
    await store.refreshAssetExtractions(showLoading: false);
    return store.assetExtractions.firstWhere(
      (job) => job.id == jobId,
      orElse: () => throw StateError('Asset extraction not found: $jobId'),
    );
  }

  List<MemoryContextLinkSuggestion> _matchingPendingLinkSuggestions(
    ChatStore store,
    Map<String, String> params, {
    bool includeTargetAliases = true,
  }) {
    final targetId = _optional(params, 'suggestionTargetId') ??
        (includeTargetAliases ? _optional(params, 'targetId') : null);
    final targetType = _optional(params, 'suggestionTargetType') ??
        (includeTargetAliases ? _optional(params, 'targetType') : null);
    final targetLabelContains =
        (_optional(params, 'suggestionTargetLabelContains') ??
                (includeTargetAliases
                    ? _optional(params, 'targetLabelContains')
                    : null))
            ?.toLowerCase();
    return store.contextLinkSuggestions.where((item) {
      if (!item.isPending) return false;
      if (targetId != null && item.targetId != targetId) return false;
      if (targetType != null && item.targetType != targetType) return false;
      if (targetLabelContains != null &&
          !item.targetLabel.toLowerCase().contains(targetLabelContains)) {
        return false;
      }
      return true;
    }).toList(growable: false);
  }

  Map<String, dynamic> _state(ChatStore store) {
    final lastMessage = store.messages.isEmpty ? null : store.messages.last;
    final latestCapture =
        store.memoryCaptures.isEmpty ? null : store.memoryCaptures.first;
    final pendingLinkSuggestionCount =
        store.contextLinkSuggestions.where((item) => item.isPending).length;
    final browser = store.memoryBrowser.value;
    return {
      'activeChatId': store.activeChatId,
      'activeMemoryScopeExternalRef': store.activeMemoryScopeExternalRef,
      'running': store.running,
      'connection': store.connection.name,
      'sessionCount': store.sessions.length,
      'memoryScopeCount': store.memoryScopes.length,
      'messageCount': store.messages.length,
      'captureCount': store.memoryCaptures.length,
      'assetExtractionCount': store.assetExtractions.length,
      'pendingLinkSuggestionCount': pendingLinkSuggestionCount,
      'operationsPendingLinkSuggestionCount': pendingLinkSuggestionCount,
      'memoryBrowserAnchorCount': browser?.anchors.length ?? 0,
      'memoryBrowserContextLinkCount': browser?.contextLinks.length ?? 0,
      'memoryBrowserCaptureCount': browser?.captures.length ?? 0,
      'pendingAnchorMergeSuggestionCount': store.anchorMergeSuggestions.length,
      'lastMessage': lastMessage == null ? null : _messageToMap(lastMessage),
      'latestCapture':
          latestCapture == null ? null : _captureToMap(latestCapture),
      'activeThread': _sessionToMap(
        store.sessions.firstWhere(
          (item) => item.id == store.activeChatId,
          orElse: () => ChatSession(
            id: store.activeChatId,
            title: '',
            createdAt: DateTime.fromMillisecondsSinceEpoch(0),
            memoryScopeExternalRef: store.activeMemoryScopeExternalRef,
          ),
        ),
      ),
      'memoryScopes':
          store.memoryScopes.map(_scopeToMap).toList(growable: false),
      'threads': store.sessions.map(_sessionToMap).toList(growable: false),
      'pendingLinkSuggestions': store.contextLinkSuggestions
          .where((item) => item.isPending)
          .map(_suggestionToMap)
          .toList(growable: false),
      'assetExtractions':
          store.assetExtractions.map(_extractionToMap).toList(growable: false),
      'memoryBrowserAnchors':
          browser?.anchors.map(_anchorToMap).toList(growable: false) ??
              const <Map<String, dynamic>>[],
      'pendingAnchorMergeSuggestions': store.anchorMergeSuggestions
          .map(_anchorMergeSuggestionToMap)
          .toList(growable: false),
    };
  }

  Future<MemoryBrowserAnchor> _findAnchor(
    ChatStore store, {
    String? anchorId,
    String? label,
  }) async {
    await store.refreshMemoryBrowser(showLoading: false);
    final anchors = store.memoryBrowser.value?.anchors ?? const [];
    final normalizedLabel = label?.trim().toLowerCase();
    for (final anchor in anchors) {
      final idMatches = anchorId != null && anchor.id == anchorId;
      final labelMatches = normalizedLabel != null &&
          anchor.label.trim().toLowerCase() == normalizedLabel;
      if (idMatches || labelMatches) {
        return anchor;
      }
    }
    final selector = anchorId ?? label ?? '<missing selector>';
    throw StateError('Memory anchor not found: $selector');
  }
}

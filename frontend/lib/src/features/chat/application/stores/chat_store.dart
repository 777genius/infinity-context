import 'dart:async';

import 'package:mobx/mobx.dart';
import 'package:frontend/src/features/chat/domain/entities/chat_message.dart';
import 'package:frontend/src/features/chat/domain/entities/cost_usage.dart';
import 'package:frontend/src/features/chat/domain/entities/chat_session.dart';
import 'package:frontend/src/features/chat/domain/entities/asset_extraction.dart';
import 'package:frontend/src/features/chat/domain/entities/document_chunk.dart';
import 'package:frontend/src/features/chat/domain/entities/extraction_capabilities.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_browser.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_capture.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_context_link.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_operations_console.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_scope.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_suggestion.dart';
import 'package:frontend/src/features/chat/domain/repositories/extraction_capability_provider.dart';
import 'package:frontend/src/features/chat/domain/repositories/chat_repository.dart';
// injectable не используем для ChatStore, создаётся через Provider
import 'package:frontend/src/features/chat/application/ports/chat_cache.dart';
import 'package:frontend/src/features/chat/domain/entities/connection_status.dart';

part 'chat_store.g.dart';

class ChatStore = ChatStoreBase with _$ChatStore;

const _approvedContextLinkReviewReason = 'approved by user from review queue';
const _rejectedContextLinkReviewReason = 'rejected by user from review queue';
const _targetOverrideContextLinkReviewReason =
    'approved by user with target override';
const _duplicateMergeReviewReason =
    'resolved duplicate memory from review queue';

abstract class ChatStoreBase with Store {
  final ChatRepository repo;
  final ChatCache? cache;
  final ExtractionCapabilityProvider? extractionCapabilityProvider;
  final List<StreamSubscription<dynamic>> _subscriptions = [];
  final Duration _assetExtractionPollInterval;
  Timer? _assetExtractionPollTimer;
  bool _assetExtractionRefreshInFlight = false;
  bool _operationsConsoleRefreshInFlight = false;
  bool _memoryBrowserRefreshInFlight = false;
  bool _disposed = false;

  ChatStoreBase(
    this.repo,
    this.cache, {
    Duration assetExtractionPollInterval = const Duration(seconds: 3),
    ExtractionCapabilityProvider? extractionCapabilities,
  })  : _assetExtractionPollInterval = assetExtractionPollInterval,
        extractionCapabilityProvider = extractionCapabilities ??
            (repo is ExtractionCapabilityProvider
                ? repo as ExtractionCapabilityProvider
                : null) {
    activeMemoryScopeExternalRef = _normalizeScopeRef(
      repo.currentMemoryScopeExternalRef(),
    );
    _ensureLocalMemoryScope(activeMemoryScopeExternalRef);
    _createInitialChat();
    _wireRepoStreams();
  }

  void _createInitialChat() {
    final firstId = _generateChatId();
    final first = ChatSession(
      id: firstId,
      title: 'Thread 1',
      createdAt: DateTime.now(),
      memoryScopeExternalRef: activeMemoryScopeExternalRef,
    );
    sessions.add(first);
    activeChatId = firstId;
    _messagesByChat[firstId] = ObservableList.of([]);
    messages = _messagesByChat[firstId]!;
    try {
      repo.setActiveMemoryScopeExternalRef(activeMemoryScopeExternalRef);
      repo.setActiveChat(firstId);
    } catch (_) {}
  }

  void _wireRepoStreams() {
    _subscriptions
      ..add(repo.messages().listen(_handleRepoMessage))
      ..add(repo.usage().listen(_handleUsage))
      ..add(repo.running().listen(_handleRunning))
      ..add(repo.connectionStatus().listen(_handleConnectionStatus));
  }

  void _handleRepoMessage(ChatMessage m) {
    final cid = _messageChatId ?? activeChatId;
    if (_handleControlMessage(cid, m)) return;

    _appendMessageTo(cid, m);
    _updateLastPreviewFor(cid, m.text);
    _ensureThinkingLast(cid);
    _persistMessage(cid, m);
    if (m.kind == 'attachment') {
      final hasExtraction =
          m.meta?['extractionId']?.toString().isNotEmpty ?? false;
      final hasLinkSuggestion =
          m.meta?['contextLinkSuggestionId']?.toString().isNotEmpty ?? false;
      final hasMemorySuggestion =
          m.meta?['memorySuggestionId']?.toString().isNotEmpty ?? false;
      if (hasExtraction || hasLinkSuggestion || hasMemorySuggestion) {
        unawaited(refreshOperationsConsole(showLoading: false));
      }
      if (hasLinkSuggestion) {
        unawaited(refreshContextLinkSuggestions(showLoading: false));
      }
      if (hasMemorySuggestion) {
        unawaited(refreshMemorySuggestions(showLoading: false));
      }
    }
  }

  bool _handleControlMessage(String chatId, ChatMessage m) {
    if ((m.kind ?? '') != 'control') return false;

    final rid = (m.meta?['removeMessageId'] as String?) ?? '';
    if (rid.isNotEmpty) {
      _removeMessageById(chatId, rid);
    }
    final approvalJobId = (m.meta?['removeApprovalsForJobId'] as String?) ?? '';
    if (approvalJobId.isNotEmpty) {
      _removeApprovalsForJob(approvalJobId);
    }
    return true;
  }

  void _persistMessage(String chatId, ChatMessage m) {
    if (!_shouldPersist(m)) return;
    try {
      cache?.saveMessage(chatId, m);
    } catch (_) {}
  }

  void _handleUsage(CostUsage u) {
    usage = u;
    totalUsd += u.totalUsd;
    totalInputTokens += u.inputTokens;
    totalOutputTokens += u.outputTokens;
    final cid = _usageChatId ?? activeChatId;
    final prevUsd = perChatUsd[cid] ?? 0.0;
    perChatUsd[cid] = prevUsd + u.totalUsd;
    perChatInTokens[cid] = (perChatInTokens[cid] ?? 0) + u.inputTokens;
    perChatOutTokens[cid] = (perChatOutTokens[cid] ?? 0) + u.outputTokens;
    _updateSessionUsage(cid);
  }

  void _handleRunning(bool isRunning) {
    running = isRunning;
    if (isRunning) {
      _usageChatId = activeChatId;
      _messageChatId = activeChatId;
      return;
    }

    _removeThinkingMessages();
    _persistResponseId(_usageChatId ?? activeChatId);
    _messageChatId = null;
    _usageChatId = null;
  }

  void _handleConnectionStatus(ConnectionStatus status) {
    connection = status;
    if (status == ConnectionStatus.connected) {
      connectionError = null;
    }
  }

  // Sessions and per-chat state
  @observable
  ObservableList<ChatSession> sessions = ObservableList.of([]);

  @observable
  String activeChatId = '';

  @observable
  ObservableList<MemoryScope> memoryScopes = ObservableList.of([]);

  @observable
  String activeMemoryScopeExternalRef = 'default';

  @observable
  bool memoryScopesLoading = false;

  @observable
  String? memoryScopeError;

  @observable
  ObservableList<AssetExtractionJob> assetExtractions = ObservableList.of([]);

  @observable
  bool assetExtractionsLoading = false;

  @observable
  String? assetExtractionError;

  @observable
  ObservableList<MemoryCapture> memoryCaptures = ObservableList.of([]);

  @observable
  bool memoryCapturesLoading = false;

  @observable
  String? memoryCaptureError;

  final ObservableList<MemoryContextLinkSuggestion> contextLinkSuggestions =
      ObservableList.of([]);

  final Observable<bool> contextLinkSuggestionsLoading = Observable(false);

  final Observable<String?> contextLinkSuggestionError = Observable(null);

  final ObservableMap<String, bool> contextLinkSuggestionReviewing =
      ObservableMap.of({});

  final ObservableList<MemorySuggestion> memorySuggestions =
      ObservableList.of([]);

  final Observable<bool> memorySuggestionsLoading = Observable(false);

  final Observable<String?> memorySuggestionError = Observable(null);

  final ObservableMap<String, bool> memorySuggestionReviewing =
      ObservableMap.of({});

  final Observable<MemoryOperationsConsole?> operationsConsole =
      Observable(null);

  final Observable<bool> operationsConsoleLoading = Observable(false);

  final Observable<String?> operationsConsoleError = Observable(null);

  final Observable<ExtractionCapabilities?> extractionCapabilities =
      Observable(null);

  final Observable<bool> extractionCapabilitiesLoading = Observable(false);

  final Observable<String?> extractionCapabilitiesError = Observable(null);

  final Observable<MemoryBrowserSnapshot?> memoryBrowser = Observable(null);

  final Observable<bool> memoryBrowserLoading = Observable(false);

  final Observable<String?> memoryBrowserError = Observable(null);

  final ObservableList<MemoryAnchorMergeSuggestion> anchorMergeSuggestions =
      ObservableList.of([]);

  final ObservableMap<String, bool> anchorMergeSuggestionReviewing =
      ObservableMap.of({});

  final ObservableMap<String, ObservableList<ChatMessage>> _messagesByChat =
      ObservableMap.of({});

  @observable
  ObservableList<ChatMessage> messages = ObservableList.of([]);

  // Per-chat usage aggregation
  @observable
  ObservableMap<String, double> perChatUsd = ObservableMap.of({});

  @observable
  ObservableMap<String, int> perChatInTokens = ObservableMap.of({});

  @observable
  ObservableMap<String, int> perChatOutTokens = ObservableMap.of({});

  // Global aggregates
  @observable
  CostUsage? usage;

  @observable
  double totalUsd = 0.0;

  @observable
  int totalInputTokens = 0;

  @observable
  int totalOutputTokens = 0;

  @observable
  bool running = false;

  @observable
  ConnectionStatus connection = ConnectionStatus.connecting;

  @observable
  String? connectionError;

  String? _usageChatId;
  String? _messageChatId;

  @action
  Future<void> sendTask(String text) async {
    _usageChatId = activeChatId;
    _messageChatId = activeChatId;
    try {
      await repo.runTask(task: text);
    } finally {
      await refreshMemoryCaptures();
      await refreshOperationsConsole();
      await refreshMemorySuggestions(showLoading: false);
      await refreshMemoryBrowser(showLoading: false);
    }
  }

  Future<void> respondApproval({
    required String messageId,
    required String jobId,
    required String approvalId,
    required bool approved,
  }) async {
    var accepted = false;
    try {
      accepted = await repo.respondApproval(
        jobId: jobId,
        approvalId: approvalId,
        approved: approved,
      );
    } catch (_) {
      accepted = false;
    }
    final cid = _removeMessageByIdFromAnyChat(messageId) ?? activeChatId;
    _appendMessageTo(
      cid,
      ChatMessage(
        id: _generateChatId(),
        role: 'system',
        ts: DateTime.now(),
        kind: 'system',
        text: accepted
            ? (approved ? 'Approved tool request.' : 'Denied tool request.')
            : 'Approval is no longer active.',
        meta: accepted ? null : const {'isError': true},
      ),
    );
  }

  Future<void> acceptLinkSuggestion(
    ChatMessage message,
    Map<String, dynamic> candidate,
  ) async {
    final meta = message.meta ?? const <String, dynamic>{};
    final sourceType = meta['sourceType']?.toString() ?? '';
    final sourceId = meta['sourceId']?.toString() ?? '';
    final targetType = candidate['target_type']?.toString() ?? '';
    final targetId = candidate['target_id']?.toString() ?? '';
    if (sourceType.isEmpty ||
        sourceId.isEmpty ||
        targetType.isEmpty ||
        targetId.isEmpty) {
      return;
    }
    final reasons = (candidate['reasons'] is List)
        ? (candidate['reasons'] as List).map((item) => item.toString()).toList()
        : const <String>[];
    final reason = reasons.isEmpty ? 'selected by user' : reasons.join(', ');
    final suggestionId = candidate['suggestion_id']?.toString() ?? '';
    try {
      if (suggestionId.isNotEmpty) {
        await repo.reviewContextLinkSuggestion(
          suggestionId: suggestionId,
          action: 'approve',
          reason: reason,
        );
        _removeContextLinkSuggestion(suggestionId);
      } else {
        final confidence =
            candidate['tier']?.toString() == 'likely' ? 'high' : 'medium';
        await repo.createContextLink(
          sourceType: sourceType,
          sourceId: sourceId,
          targetType: targetType,
          targetId: targetId,
          relationType: 'related_to',
          confidence: confidence,
          reason: reason,
        );
      }
      unawaited(refreshMemoryCaptures(showLoading: false));
      unawaited(refreshOperationsConsole(showLoading: false));
      unawaited(refreshMemorySuggestions(showLoading: false));
      unawaited(refreshMemoryBrowser(showLoading: false));
    } catch (e) {
      _appendMessageTo(
        activeChatId,
        ChatMessage(
          id: _generateChatId(),
          role: 'system',
          ts: DateTime.now(),
          kind: 'system',
          text: 'Link failed: $e',
          meta: const {'isError': true},
        ),
      );
    }
  }

  void dispose() {
    _disposed = true;
    _assetExtractionPollTimer?.cancel();
    _assetExtractionPollTimer = null;
    for (final sub in _subscriptions) {
      unawaited(sub.cancel());
    }
    _subscriptions.clear();
  }

  @action
  Future<void> init() async {
    await refreshMemoryScopes();
    try {
      final saved = await cache?.loadSessions();
      if (saved != null && saved.isNotEmpty) {
        sessions = ObservableList.of(
          saved.map(_normalizeSessionScope).toList(growable: false),
        );
        for (final session in sessions) {
          _ensureLocalMemoryScope(session.memoryScopeExternalRef);
        }
        activeChatId = saved.first.id;
        activeMemoryScopeExternalRef = _normalizeScopeRef(
          sessions.first.memoryScopeExternalRef,
        );
        final msgs = _restorableMessages(
          await cache?.loadMessages(activeChatId),
        );
        _messagesByChat[activeChatId] = ObservableList.of(msgs);
        messages = _messagesByChat[activeChatId]!;
        try {
          repo.setActiveMemoryScopeExternalRef(activeMemoryScopeExternalRef);
          repo.setActiveChat(activeChatId);
        } catch (_) {}
        _restoreContext(activeChatId, msgs);
      }
    } catch (_) {}
    try {
      await repo.createSession();
      connectionError = null;
    } catch (e) {
      connectionError = 'Backend connection failed: $e';
    }
    await refreshMemoryCaptures();
    await refreshExtractionCapabilities();
    await refreshOperationsConsole();
    await refreshMemoryBrowser();
  }

  Future<void> refreshExtractionCapabilities({bool showLoading = true}) async {
    final provider = extractionCapabilityProvider;
    if (_disposed || provider == null) return;
    if (showLoading) {
      runInAction(() => extractionCapabilitiesLoading.value = true);
    }
    runInAction(() => extractionCapabilitiesError.value = null);
    try {
      final capabilities = await provider.getExtractionCapabilities();
      if (_disposed) return;
      runInAction(() => extractionCapabilities.value = capabilities);
    } catch (e) {
      if (_disposed) return;
      runInAction(() {
        extractionCapabilitiesError.value =
            'Extraction capabilities unavailable: $e';
      });
    } finally {
      if (showLoading && !_disposed) {
        runInAction(() => extractionCapabilitiesLoading.value = false);
      }
    }
  }

  @action
  Future<void> refreshMemoryScopes() async {
    memoryScopesLoading = true;
    memoryScopeError = null;
    try {
      final scopes = await repo.listMemoryScopes();
      memoryScopes = ObservableList.of(scopes);
      for (final session in sessions) {
        _ensureLocalMemoryScope(session.memoryScopeExternalRef);
      }
      _ensureLocalMemoryScope(activeMemoryScopeExternalRef);
    } catch (e) {
      memoryScopeError = 'Memory scopes unavailable: $e';
      _ensureLocalMemoryScope(activeMemoryScopeExternalRef);
    } finally {
      memoryScopesLoading = false;
    }
  }

  @action
  Future<void> refreshAssetExtractions({bool showLoading = true}) async {
    if (_disposed || _assetExtractionRefreshInFlight) return;
    _assetExtractionRefreshInFlight = true;
    if (showLoading) {
      assetExtractionsLoading = true;
    }
    assetExtractionError = null;
    try {
      final jobs = await repo.listAssetExtractions(limit: 50);
      if (_disposed) return;
      assetExtractions = ObservableList.of(jobs);
      _scheduleAssetExtractionPollingIfNeeded();
    } catch (e) {
      if (_disposed) return;
      assetExtractionError = 'Asset extraction history unavailable: $e';
    } finally {
      _assetExtractionRefreshInFlight = false;
      if (showLoading && !_disposed) {
        assetExtractionsLoading = false;
      }
    }
  }

  @action
  Future<void> refreshMemoryCaptures({bool showLoading = true}) async {
    if (_disposed) return;
    if (showLoading) {
      memoryCapturesLoading = true;
    }
    memoryCaptureError = null;
    try {
      final captures = await repo.listMemoryCaptures(limit: 30);
      if (_disposed) return;
      memoryCaptures = ObservableList.of(captures);
    } catch (e) {
      if (_disposed) return;
      memoryCaptureError = 'Saved memory unavailable: $e';
    } finally {
      if (showLoading && !_disposed) {
        memoryCapturesLoading = false;
      }
    }
  }

  Future<void> refreshContextLinkSuggestions({bool showLoading = true}) async {
    if (_disposed) return;
    if (showLoading) {
      runInAction(() => contextLinkSuggestionsLoading.value = true);
    }
    runInAction(() => contextLinkSuggestionError.value = null);
    try {
      final suggestions = await repo.listContextLinkSuggestions(limit: 20);
      if (_disposed) return;
      runInAction(() {
        contextLinkSuggestions
          ..clear()
          ..addAll(suggestions.where((item) => item.isPending));
      });
    } catch (e) {
      if (_disposed) return;
      runInAction(() {
        contextLinkSuggestionError.value = 'Link suggestions unavailable: $e';
      });
    } finally {
      if (showLoading && !_disposed) {
        runInAction(() => contextLinkSuggestionsLoading.value = false);
      }
    }
  }

  Future<void> refreshMemorySuggestions({bool showLoading = true}) async {
    if (_disposed) return;
    if (showLoading) {
      runInAction(() => memorySuggestionsLoading.value = true);
    }
    runInAction(() => memorySuggestionError.value = null);
    try {
      final suggestions = await repo.listMemorySuggestions(limit: 30);
      if (_disposed) return;
      runInAction(() {
        memorySuggestions
          ..clear()
          ..addAll(suggestions.where((item) => item.isPending));
      });
    } catch (e) {
      if (_disposed) return;
      runInAction(() {
        memorySuggestionError.value = 'Memory suggestions unavailable: $e';
      });
    } finally {
      if (showLoading && !_disposed) {
        runInAction(() => memorySuggestionsLoading.value = false);
      }
    }
  }

  Future<void> refreshOperationsConsole({bool showLoading = true}) async {
    if (_disposed || _operationsConsoleRefreshInFlight) return;
    _operationsConsoleRefreshInFlight = true;
    if (showLoading) {
      runInAction(() => operationsConsoleLoading.value = true);
    }
    runInAction(() => operationsConsoleError.value = null);
    try {
      final console = await repo.getOperationsConsole(limit: 50);
      if (_disposed) return;
      runInAction(() {
        operationsConsole.value = console;
        assetExtractions = ObservableList.of(console.extractionJobs);
        contextLinkSuggestions
          ..clear()
          ..addAll(
            console.contextLinkSuggestions.where((item) => item.isPending),
          );
        assetExtractionError = null;
        contextLinkSuggestionError.value = null;
      });
      _scheduleAssetExtractionPollingIfNeeded();
    } catch (e) {
      if (_disposed) return;
      runInAction(() {
        operationsConsoleError.value = 'Operations console unavailable: $e';
      });
    } finally {
      _operationsConsoleRefreshInFlight = false;
      if (showLoading && !_disposed) {
        runInAction(() => operationsConsoleLoading.value = false);
      }
    }
  }

  Future<void> refreshMemoryBrowser({bool showLoading = true}) async {
    if (_disposed || _memoryBrowserRefreshInFlight) return;
    _memoryBrowserRefreshInFlight = true;
    if (showLoading) {
      runInAction(() => memoryBrowserLoading.value = true);
    }
    runInAction(() => memoryBrowserError.value = null);
    try {
      final snapshot = await repo.getMemoryBrowser(limit: 100);
      var mergeSuggestions = const <MemoryAnchorMergeSuggestion>[];
      Object? mergeError;
      try {
        mergeSuggestions = await repo.listMemoryAnchorMergeSuggestions(
          limit: 80,
        );
      } catch (e) {
        mergeError = e;
      }
      if (_disposed) return;
      runInAction(() {
        memoryBrowser.value = snapshot;
        anchorMergeSuggestions
          ..clear()
          ..addAll(mergeSuggestions);
        if (mergeError != null) {
          memoryBrowserError.value =
              'Anchor merge reviews unavailable: $mergeError';
        }
      });
    } catch (e) {
      if (_disposed) return;
      runInAction(() {
        memoryBrowserError.value = 'Memory browser unavailable: $e';
      });
    } finally {
      _memoryBrowserRefreshInFlight = false;
      if (showLoading && !_disposed) {
        runInAction(() => memoryBrowserLoading.value = false);
      }
    }
  }

  Future<bool> mergeMemoryAnchorSuggestion(
    MemoryAnchorMergeSuggestion suggestion,
  ) async {
    final reason = _anchorMergeReason(suggestion);
    runInAction(() {
      anchorMergeSuggestionReviewing[suggestion.id] = true;
      memoryBrowserError.value = null;
    });
    try {
      await repo.mergeMemoryAnchors(
        sourceAnchorId: suggestion.sourceAnchor.id,
        targetAnchorId: suggestion.targetAnchor.id,
        reason: reason,
      );
      if (_disposed) return false;
      await refreshMemoryBrowser(showLoading: false);
      return true;
    } catch (e) {
      if (!_disposed) {
        runInAction(() {
          memoryBrowserError.value = 'Anchor merge failed: $e';
        });
      }
      return false;
    } finally {
      if (!_disposed) {
        runInAction(() {
          anchorMergeSuggestionReviewing.remove(suggestion.id);
        });
      }
    }
  }

  Future<bool> splitMemoryAnchorAlias(
    MemoryBrowserAnchor anchor, {
    required String alias,
    String? newLabel,
    String reason = 'split alias in Infinity Context frontend',
  }) async {
    final cleanAlias = alias.trim();
    final cleanLabel = newLabel?.trim();
    final cleanReason = reason.trim().isEmpty
        ? 'split alias in Infinity Context frontend'
        : reason.trim();
    if (cleanAlias.isEmpty) {
      runInAction(() {
        memoryBrowserError.value = 'Anchor split alias is required';
      });
      return false;
    }
    runInAction(() {
      memoryBrowserLoading.value = true;
      memoryBrowserError.value = null;
    });
    try {
      await repo.splitMemoryAnchor(
        anchorId: anchor.id,
        alias: cleanAlias,
        newLabel: cleanLabel == null || cleanLabel.isEmpty ? null : cleanLabel,
        reason: cleanReason,
      );
      if (_disposed) return false;
      await refreshMemoryBrowser(showLoading: false);
      return true;
    } catch (e) {
      if (!_disposed) {
        runInAction(() {
          memoryBrowserError.value = 'Anchor split failed: $e';
        });
      }
      return false;
    } finally {
      if (!_disposed) {
        runInAction(() => memoryBrowserLoading.value = false);
      }
    }
  }

  Future<bool> createMemoryAnchor({
    required String kind,
    required String label,
    List<String> aliases = const <String>[],
    String? description,
  }) async {
    final cleanKind = kind.trim().isEmpty ? 'person' : kind.trim();
    final cleanLabel = label.trim();
    final cleanAliases = aliases
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty && item != cleanLabel)
        .toSet()
        .toList(growable: false);
    final cleanDescription = description?.trim();
    if (cleanLabel.isEmpty) {
      runInAction(() {
        memoryBrowserError.value = 'Anchor label is required';
      });
      return false;
    }
    runInAction(() {
      memoryBrowserLoading.value = true;
      memoryBrowserError.value = null;
    });
    try {
      await repo.createMemoryAnchor(
        kind: cleanKind,
        label: cleanLabel,
        aliases: cleanAliases,
        description: cleanDescription == null || cleanDescription.isEmpty
            ? null
            : cleanDescription,
      );
      if (_disposed) return false;
      await refreshMemoryBrowser(showLoading: false);
      return true;
    } catch (e) {
      if (!_disposed) {
        runInAction(() {
          memoryBrowserError.value = 'Anchor creation failed: $e';
        });
      }
      return false;
    } finally {
      if (!_disposed) {
        runInAction(() => memoryBrowserLoading.value = false);
      }
    }
  }

  Future<bool> updateMemoryAnchor(
    MemoryBrowserAnchor anchor, {
    required String label,
    List<String> aliases = const <String>[],
    String? description,
  }) async {
    final cleanLabel = label.trim();
    final cleanAliases = aliases
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty && item != cleanLabel)
        .toSet()
        .toList(growable: false);
    final cleanDescription = description?.trim();
    if (cleanLabel.isEmpty) {
      runInAction(() {
        memoryBrowserError.value = 'Anchor label is required';
      });
      return false;
    }
    runInAction(() {
      memoryBrowserLoading.value = true;
      memoryBrowserError.value = null;
    });
    try {
      await repo.updateMemoryAnchor(
        anchorId: anchor.id,
        label: cleanLabel,
        aliases: cleanAliases,
        description: cleanDescription == null
            ? null
            : cleanDescription.isEmpty
                ? ''
                : cleanDescription,
      );
      if (_disposed) return false;
      await refreshMemoryBrowser(showLoading: false);
      return true;
    } catch (e) {
      if (!_disposed) {
        runInAction(() {
          memoryBrowserError.value = 'Anchor update failed: $e';
        });
      }
      return false;
    } finally {
      if (!_disposed) {
        runInAction(() => memoryBrowserLoading.value = false);
      }
    }
  }

  Future<bool> deleteMemoryAnchor(
    MemoryBrowserAnchor anchor, {
    String reason = 'deleted in Infinity Context frontend',
  }) async {
    final cleanReason = reason.trim().isEmpty ? 'manual delete' : reason.trim();
    runInAction(() {
      memoryBrowserLoading.value = true;
      memoryBrowserError.value = null;
    });
    try {
      await repo.deleteMemoryAnchor(anchorId: anchor.id, reason: cleanReason);
      if (_disposed) return false;
      await refreshMemoryBrowser(showLoading: false);
      return true;
    } catch (e) {
      if (!_disposed) {
        runInAction(() {
          memoryBrowserError.value = 'Anchor deletion failed: $e';
        });
      }
      return false;
    } finally {
      if (!_disposed) {
        runInAction(() => memoryBrowserLoading.value = false);
      }
    }
  }

  Future<bool> backfillMemoryAnchors({int limitPerSource = 100}) async {
    runInAction(() {
      memoryBrowserLoading.value = true;
      memoryBrowserError.value = null;
    });
    try {
      await repo.backfillMemoryAnchors(limitPerSource: limitPerSource);
      if (_disposed) return false;
      await refreshMemoryBrowser(showLoading: false);
      return true;
    } catch (e) {
      if (!_disposed) {
        runInAction(() {
          memoryBrowserError.value = 'Anchor backfill failed: $e';
        });
      }
      return false;
    } finally {
      if (!_disposed) {
        runInAction(() => memoryBrowserLoading.value = false);
      }
    }
  }

  Future<void> reviewContextLinkSuggestion(
    MemoryContextLinkSuggestion suggestion, {
    required bool approve,
  }) async {
    final action = approve ? 'approve' : 'reject';
    runInAction(() {
      contextLinkSuggestionReviewing[suggestion.id] = true;
      contextLinkSuggestionError.value = null;
    });
    try {
      await repo.reviewContextLinkSuggestion(
        suggestionId: suggestion.id,
        action: action,
        reason: approve
            ? _approvedContextLinkReviewReason
            : _rejectedContextLinkReviewReason,
      );
      await _refreshContextLinkReviewSurfaces(refreshCaptures: approve);
    } catch (e) {
      runInAction(() {
        contextLinkSuggestionError.value = 'Review failed: $e';
      });
    } finally {
      runInAction(() {
        contextLinkSuggestionReviewing.remove(suggestion.id);
      });
    }
  }

  Future<void> reviewContextLinkSuggestionsBatch(
    List<MemoryContextLinkSuggestion> suggestions, {
    required bool approve,
  }) async {
    final pending = suggestions.where((item) => item.isPending).toList();
    if (pending.isEmpty) return;
    final action = approve ? 'approve' : 'reject';
    final reason = approve
        ? _approvedContextLinkReviewReason
        : _rejectedContextLinkReviewReason;
    runInAction(() {
      for (final suggestion in pending) {
        contextLinkSuggestionReviewing[suggestion.id] = true;
      }
      contextLinkSuggestionError.value = null;
    });
    try {
      await repo.reviewContextLinkSuggestionsBatch(
        suggestionIds: pending.map((item) => item.id).toList(growable: false),
        action: action,
        reason: reason,
      );
      await _refreshContextLinkReviewSurfaces(refreshCaptures: approve);
    } catch (e) {
      runInAction(() {
        contextLinkSuggestionError.value = 'Batch review failed: $e';
      });
    } finally {
      runInAction(() {
        for (final suggestion in pending) {
          contextLinkSuggestionReviewing.remove(suggestion.id);
        }
      });
    }
  }

  Future<bool> resolveDuplicateMemorySuggestion(
    MemorySuggestion suggestion, {
    required String action,
  }) async {
    if (!suggestion.canResolveDuplicate) return false;
    runInAction(() {
      memorySuggestionReviewing[suggestion.id] = true;
      memorySuggestionError.value = null;
    });
    try {
      await repo.resolveDuplicateMemorySuggestion(
        suggestionId: suggestion.id,
        action: action,
        reason: _duplicateMergeReviewReason,
      );
      await _refreshMemoryReviewSurfaces();
      return true;
    } catch (e) {
      runInAction(() {
        memorySuggestionError.value = 'Memory review failed: $e';
      });
      return false;
    } finally {
      runInAction(() {
        memorySuggestionReviewing.remove(suggestion.id);
      });
    }
  }

  Future<bool> approveContextLinkSuggestionWithOverride(
    MemoryContextLinkSuggestion suggestion, {
    required String targetType,
    required String targetId,
    required String relationType,
    required String confidence,
    required String reason,
  }) async {
    runInAction(() {
      contextLinkSuggestionReviewing[suggestion.id] = true;
      contextLinkSuggestionError.value = null;
    });
    try {
      await repo.reviewContextLinkSuggestion(
        suggestionId: suggestion.id,
        action: 'approve',
        reason: _targetOverrideContextLinkReviewReason,
        targetType: targetType.trim(),
        targetId: targetId.trim(),
        relationType: relationType.trim().isEmpty
            ? suggestion.relationType
            : relationType.trim(),
        confidence: confidence.trim().isEmpty
            ? suggestion.confidence
            : confidence.trim(),
        linkReason: reason.trim().isEmpty ? 'selected by user' : reason.trim(),
      );
      await _refreshContextLinkReviewSurfaces(refreshCaptures: true);
      return true;
    } catch (e) {
      runInAction(() {
        contextLinkSuggestionError.value = 'Target override review failed: $e';
      });
      return false;
    } finally {
      runInAction(() {
        contextLinkSuggestionReviewing.remove(suggestion.id);
      });
    }
  }

  Future<void> _refreshContextLinkReviewSurfaces({
    required bool refreshCaptures,
  }) async {
    if (refreshCaptures) {
      await refreshMemoryCaptures(showLoading: false);
    }
    await refreshOperationsConsole(showLoading: false);
    await refreshMemoryBrowser(showLoading: false);
    await refreshContextLinkSuggestions(showLoading: false);
  }

  Future<void> _refreshMemoryReviewSurfaces() async {
    await refreshMemoryCaptures(showLoading: false);
    await refreshOperationsConsole(showLoading: false);
    await refreshMemoryBrowser(showLoading: false);
    await refreshMemorySuggestions(showLoading: false);
  }

  Future<bool> createManualContextLinkFromSuggestion(
    MemoryContextLinkSuggestion suggestion, {
    required String targetType,
    required String targetId,
    required String relationType,
    required String confidence,
    required String reason,
  }) {
    return approveContextLinkSuggestionWithOverride(
      suggestion,
      targetType: targetType,
      targetId: targetId,
      relationType: relationType,
      confidence: confidence,
      reason: reason,
    );
  }

  @action
  Future<void> retryAssetExtraction(AssetExtractionJob job) async {
    assetExtractionError = null;
    try {
      final updated = await repo.retryAssetExtraction(job.id);
      _upsertAssetExtraction(updated);
      await refreshAssetExtractions();
      await refreshOperationsConsole(showLoading: false);
    } catch (e) {
      assetExtractionError = 'Asset extraction retry failed: $e';
    }
  }

  Future<void> cancelAssetExtraction(AssetExtractionJob job) async {
    runInAction(() => assetExtractionError = null);
    try {
      final updated = await repo.cancelAssetExtraction(job.id);
      runInAction(() => _upsertAssetExtraction(updated));
      await refreshOperationsConsole(showLoading: false);
    } catch (e) {
      runInAction(() {
        assetExtractionError = 'Asset extraction cancel failed: $e';
      });
    }
  }

  Future<List<DocumentChunk>> loadAssetExtractionEvidence(
    AssetExtractionJob job,
  ) async {
    final chunks = <DocumentChunk>[];
    for (final documentId in job.resultDocumentIds) {
      chunks.addAll(await repo.listDocumentChunks(documentId));
      if (chunks.length >= 100) break;
    }
    return chunks.take(100).toList(growable: false);
  }

  Future<List<MemoryContextLink>> loadCaptureContextLinks(
    MemoryCapture capture,
  ) {
    return repo.listContextLinks(
      sourceType: 'capture',
      sourceId: capture.id,
      limit: 50,
    );
  }

  @action
  Future<MemoryScope?> createMemoryScope({
    required String externalRef,
    required String name,
  }) async {
    memoryScopeError = null;
    try {
      final scope = await repo.createMemoryScope(
        externalRef: _normalizeScopeRef(externalRef),
        name: name,
      );
      _upsertMemoryScope(scope);
      await setActiveMemoryScope(scope.externalRef);
      return scope;
    } catch (e) {
      memoryScopeError = 'Create memory scope failed: $e';
      return null;
    }
  }

  @action
  Future<MemoryScope?> updateMemoryScope(
    MemoryScope scope, {
    required String externalRef,
    required String name,
  }) async {
    memoryScopeError = null;
    try {
      final oldRef = _normalizeScopeRef(scope.externalRef);
      final newRef = _normalizeScopeRef(externalRef);
      final newName = name.trim().isEmpty ? newRef : name.trim();
      if (scope.id.isEmpty) {
        if (oldRef != newRef &&
            memoryScopes.any((item) => item.externalRef == newRef)) {
          memoryScopeError = 'Update memory scope failed: ref already exists';
          return null;
        }
        final updated = scope.copyWith(
          externalRef: newRef,
          name: newName,
          updatedAt: DateTime.now(),
        );
        _replaceMemoryScope(oldRef, updated);
        if (oldRef != updated.externalRef) {
          _migrateSessionsToScope(oldRef, updated.externalRef);
        }
        if (activeMemoryScopeExternalRef == oldRef) {
          activeMemoryScopeExternalRef = updated.externalRef;
          repo.setActiveMemoryScopeExternalRef(updated.externalRef);
        }
        return updated;
      }
      final updated = await repo.updateMemoryScope(
        memoryScopeId: scope.id,
        externalRef: newRef,
        name: newName,
      );
      _upsertMemoryScope(updated);
      if (oldRef != updated.externalRef) {
        _migrateSessionsToScope(oldRef, updated.externalRef);
      }
      if (activeMemoryScopeExternalRef == oldRef) {
        activeMemoryScopeExternalRef = updated.externalRef;
        repo.setActiveMemoryScopeExternalRef(updated.externalRef);
      }
      return updated;
    } catch (e) {
      memoryScopeError = 'Update memory scope failed: $e';
      return null;
    }
  }

  @action
  Future<void> deleteMemoryScope(MemoryScope scope) async {
    memoryScopeError = null;
    try {
      if (scope.id.isNotEmpty) {
        await repo.deleteMemoryScope(scope.id);
      }
      final ref = _normalizeScopeRef(scope.externalRef);
      memoryScopes.removeWhere((item) => item.externalRef == ref);
      final removedIds = sessions
          .where((session) => session.memoryScopeExternalRef == ref)
          .map((session) => session.id)
          .toList(growable: false);
      sessions.removeWhere((session) => session.memoryScopeExternalRef == ref);
      for (final id in removedIds) {
        _messagesByChat.remove(id);
        perChatUsd.remove(id);
        perChatInTokens.remove(id);
        perChatOutTokens.remove(id);
        try {
          cache?.removeSession(id);
          cache?.removeMessages(id);
        } catch (_) {}
      }
      if (activeMemoryScopeExternalRef == ref ||
          removedIds.contains(activeChatId)) {
        if (sessions.isEmpty) {
          activeMemoryScopeExternalRef = 'default';
          _ensureLocalMemoryScope(activeMemoryScopeExternalRef);
          createNewChat(memoryScopeExternalRef: activeMemoryScopeExternalRef);
        } else {
          await setActiveChat(sessions.first.id);
        }
      }
    } catch (e) {
      memoryScopeError = 'Delete memory scope failed: $e';
    }
  }

  @action
  Future<void> setActiveMemoryScope(String externalRef) async {
    final ref = _normalizeScopeRef(externalRef);
    activeMemoryScopeExternalRef = ref;
    _resetAssetExtractionsForScopeSwitch();
    _ensureLocalMemoryScope(ref);
    try {
      repo.setActiveMemoryScopeExternalRef(ref);
    } catch (_) {}
    final session = _firstSessionInScope(ref);
    if (session != null) {
      await setActiveChat(session.id);
      return;
    }
    createNewChat(memoryScopeExternalRef: ref);
    unawaited(refreshMemoryCaptures());
    unawaited(refreshOperationsConsole());
    unawaited(refreshMemorySuggestions());
    unawaited(refreshMemoryBrowser());
  }

  @action
  String createNewChat({String? title, String? memoryScopeExternalRef}) {
    final id = _generateChatId();
    final scopeRef = _normalizeScopeRef(
      memoryScopeExternalRef ?? activeMemoryScopeExternalRef,
    );
    activeMemoryScopeExternalRef = scopeRef;
    _ensureLocalMemoryScope(scopeRef);
    final c = ChatSession(
      id: id,
      title: title?.trim().isNotEmpty == true
          ? title!.trim()
          : 'Thread ${_sessionCountForScope(scopeRef) + 1}',
      createdAt: DateTime.now(),
      memoryScopeExternalRef: scopeRef,
    );
    sessions.insert(0, c);
    try {
      cache?.upsertSession(c);
    } catch (_) {}
    _messagesByChat[id] = ObservableList.of([]);
    perChatUsd[id] = 0.0;
    perChatInTokens[id] = 0;
    perChatOutTokens[id] = 0;
    activeChatId = id;
    messages = _messagesByChat[id]!;
    try {
      repo.setActiveMemoryScopeExternalRef(scopeRef);
      repo.setActiveChat(id);
    } catch (_) {}
    unawaited(refreshMemoryCaptures());
    unawaited(refreshOperationsConsole());
    unawaited(refreshMemorySuggestions());
    unawaited(refreshMemoryBrowser());
    return id;
  }

  @action
  Future<void> setActiveChat(String id) async {
    if (id == activeChatId) {
      await refreshMemoryCaptures();
      await refreshOperationsConsole();
      await refreshMemorySuggestions(showLoading: false);
      await refreshMemoryBrowser();
      return;
    }
    final session = _sessionById(id);
    if (session != null) {
      activeMemoryScopeExternalRef = _normalizeScopeRef(
        session.memoryScopeExternalRef,
      );
      _resetAssetExtractionsForScopeSwitch();
      _ensureLocalMemoryScope(activeMemoryScopeExternalRef);
      try {
        repo.setActiveMemoryScopeExternalRef(activeMemoryScopeExternalRef);
      } catch (_) {}
    }
    // Lazy-load messages from cache if not yet in memory
    List<ChatMessage> loaded = <ChatMessage>[];
    if (!_messagesByChat.containsKey(id) ||
        (_messagesByChat[id]?.isEmpty ?? true)) {
      try {
        loaded = _restorableMessages(await cache?.loadMessages(id));
        if (loaded.isNotEmpty) {
          _messagesByChat[id] = ObservableList.of(loaded);
        }
      } catch (_) {}
    }
    if (!_messagesByChat.containsKey(id)) {
      _messagesByChat[id] = ObservableList.of([]);
    }
    activeChatId = id;
    messages = _messagesByChat[id]!;
    try {
      repo.setActiveMemoryScopeExternalRef(activeMemoryScopeExternalRef);
      repo.setActiveChat(id);
    } catch (_) {}
    // Restore conversation context for AI
    _restoreContext(id, loaded);
    await refreshMemoryCaptures();
    await refreshOperationsConsole();
    await refreshMemorySuggestions(showLoading: false);
    await refreshMemoryBrowser();
  }

  @action
  void renameChat(String id, String title) {
    final idx = sessions.indexWhere((s) => s.id == id);
    if (idx >= 0) {
      final s = sessions[idx];
      final next = s.copyWith(title: title);
      sessions[idx] = next;
      try {
        cache?.upsertSession(next);
      } catch (_) {}
    }
  }

  @action
  void removeChat(String id) {
    sessions.removeWhere((s) => s.id == id);
    _messagesByChat.remove(id);
    perChatUsd.remove(id);
    perChatInTokens.remove(id);
    perChatOutTokens.remove(id);
    try {
      cache?.removeSession(id);
    } catch (_) {}
    try {
      cache?.removeMessages(id);
    } catch (_) {}
    if (activeChatId == id) {
      if (sessions.isNotEmpty) {
        activeChatId = sessions.first.id;
        activeMemoryScopeExternalRef = _normalizeScopeRef(
          sessions.first.memoryScopeExternalRef,
        );
        messages = _messagesByChat[activeChatId] ?? ObservableList.of([]);
        try {
          repo.setActiveMemoryScopeExternalRef(activeMemoryScopeExternalRef);
          repo.setActiveChat(activeChatId);
        } catch (_) {}
        _resetAssetExtractionsForScopeSwitch();
        unawaited(refreshMemoryCaptures());
        unawaited(refreshOperationsConsole());
      } else {
        final nid = createNewChat();
        activeChatId = nid;
        messages = _messagesByChat[activeChatId] ?? ObservableList.of([]);
        try {
          repo.setActiveMemoryScopeExternalRef(activeMemoryScopeExternalRef);
          repo.setActiveChat(activeChatId);
        } catch (_) {}
        _resetAssetExtractionsForScopeSwitch();
        unawaited(refreshMemoryCaptures());
        unawaited(refreshOperationsConsole());
      }
    }
  }

  void _appendMessageTo(String chatId, ChatMessage m) {
    final list = _messagesByChat[chatId] ??= ObservableList.of([]);
    list.add(m);
    if (chatId == activeChatId && messages != list) {
      messages = list;
    }
    // Передвинем чат вверх при новой активности
    final idx = sessions.indexWhere((s) => s.id == chatId);
    if (idx > 0) {
      final s = sessions.removeAt(idx);
      sessions.insert(0, s);
    }
  }

  void _removeMessageById(String chatId, String id) {
    final list = _messagesByChat[chatId];
    if (list == null) return;
    list.removeWhere((e) => e.id == id);
    if (chatId == activeChatId && messages != list) {
      messages = list;
    }
  }

  String? _removeMessageByIdFromAnyChat(String id) {
    for (final entry in _messagesByChat.entries) {
      final before = entry.value.length;
      entry.value.removeWhere((message) => message.id == id);
      if (entry.value.length != before) {
        if (entry.key == activeChatId && messages != entry.value) {
          messages = entry.value;
        }
        return entry.key;
      }
    }
    return null;
  }

  void _removeApprovalsForJob(String jobId) {
    for (final entry in _messagesByChat.entries) {
      final before = entry.value.length;
      entry.value.removeWhere(
        (message) =>
            message.kind == 'approval' &&
            message.meta?['jobId']?.toString() == jobId,
      );
      if (entry.value.length != before &&
          entry.key == activeChatId &&
          messages != entry.value) {
        messages = entry.value;
      }
    }
  }

  void _ensureThinkingLast(String chatId) {
    final list = _messagesByChat[chatId];
    if (list == null || list.isEmpty) return;
    // find current Thinking... bubble
    final idx = list.lastIndexWhere(
      (e) => (e.meta?['thinking'] as bool?) == true,
    );
    if (idx < 0) return;
    if (idx == list.length - 1) return; // already last
    final item = list.removeAt(idx);
    list.add(item);
    if (chatId == activeChatId && messages != list) {
      messages = list;
    }
  }

  /// Remove all Thinking... placeholders from all chats (fallback cleanup)
  void _removeThinkingMessages() {
    for (final entry in _messagesByChat.entries) {
      final list = entry.value;
      final removed = list.any((e) => (e.meta?['thinking'] as bool?) == true);
      if (removed) {
        list.removeWhere((e) => (e.meta?['thinking'] as bool?) == true);
        if (entry.key == activeChatId && messages != list) {
          messages = list;
        }
      }
    }
  }

  void _updateLastPreviewFor(String chatId, String? text) {
    if (text == null || text.isEmpty) return;
    final idx = sessions.indexWhere((s) => s.id == chatId);
    if (idx >= 0) {
      final s = sessions[idx];
      final next = s.copyWith(lastMessageText: text);
      sessions[idx] = next;
      try {
        cache?.upsertSession(next);
      } catch (_) {}
    }
  }

  void _updateSessionUsage(String chatId) {
    final idx = sessions.indexWhere((s) => s.id == chatId);
    if (idx >= 0) {
      final s = sessions[idx];
      final next = s.copyWith(
        totalUsd: perChatUsd[chatId] ?? 0.0,
        totalInputTokens: perChatInTokens[chatId] ?? 0,
        totalOutputTokens: perChatOutTokens[chatId] ?? 0,
      );
      sessions[idx] = next;
      try {
        cache?.upsertSession(next);
      } catch (_) {}
    }
  }

  ChatSession? _sessionById(String id) {
    for (final session in sessions) {
      if (session.id == id) return session;
    }
    return null;
  }

  ChatSession? _firstSessionInScope(String externalRef) {
    final ref = _normalizeScopeRef(externalRef);
    for (final session in sessions) {
      if (session.memoryScopeExternalRef == ref) return session;
    }
    return null;
  }

  int _sessionCountForScope(String externalRef) {
    final ref = _normalizeScopeRef(externalRef);
    return sessions
        .where((session) => session.memoryScopeExternalRef == ref)
        .length;
  }

  void _ensureLocalMemoryScope(String externalRef, {String? name}) {
    final ref = _normalizeScopeRef(externalRef);
    if (memoryScopes.any((scope) => scope.externalRef == ref)) return;
    memoryScopes.add(MemoryScope.local(externalRef: ref, name: name));
  }

  void _upsertMemoryScope(MemoryScope scope) {
    final ref = _normalizeScopeRef(scope.externalRef);
    final idx = memoryScopes.indexWhere(
      (item) =>
          (scope.id.isNotEmpty && item.id == scope.id) ||
          item.externalRef == ref,
    );
    final normalized = scope.copyWith(externalRef: ref);
    if (idx >= 0) {
      memoryScopes[idx] = normalized;
    } else {
      memoryScopes.add(normalized);
    }
  }

  void _upsertAssetExtraction(AssetExtractionJob job) {
    final idx = assetExtractions.indexWhere((item) => item.id == job.id);
    if (idx >= 0) {
      assetExtractions[idx] = job;
    } else {
      assetExtractions.insert(0, job);
    }
    _scheduleAssetExtractionPollingIfNeeded();
  }

  void _removeContextLinkSuggestion(String suggestionId) {
    contextLinkSuggestions.removeWhere((item) => item.id == suggestionId);
  }

  void _scheduleAssetExtractionPollingIfNeeded() {
    _assetExtractionPollTimer?.cancel();
    _assetExtractionPollTimer = null;
    if (_disposed) return;
    if (!assetExtractions.any((job) => job.isRunning)) return;
    _assetExtractionPollTimer = Timer(_assetExtractionPollInterval, () {
      unawaited(refreshOperationsConsole(showLoading: false));
    });
  }

  void _resetAssetExtractionsForScopeSwitch() {
    _assetExtractionPollTimer?.cancel();
    _assetExtractionPollTimer = null;
    assetExtractions = ObservableList.of([]);
    assetExtractionError = null;
    memoryCaptures = ObservableList.of([]);
    memoryCaptureError = null;
    memoryCapturesLoading = false;
    contextLinkSuggestions.clear();
    contextLinkSuggestionError.value = null;
    contextLinkSuggestionsLoading.value = false;
    contextLinkSuggestionReviewing.clear();
    memorySuggestions.clear();
    memorySuggestionError.value = null;
    memorySuggestionsLoading.value = false;
    memorySuggestionReviewing.clear();
    anchorMergeSuggestions.clear();
    anchorMergeSuggestionReviewing.clear();
    memoryBrowser.value = null;
    memoryBrowserError.value = null;
    memoryBrowserLoading.value = false;
    operationsConsole.value = null;
    operationsConsoleError.value = null;
    operationsConsoleLoading.value = false;
  }

  void _replaceMemoryScope(String oldRef, MemoryScope scope) {
    final source = _normalizeScopeRef(oldRef);
    final normalized = scope.copyWith(
      externalRef: _normalizeScopeRef(scope.externalRef),
    );
    final idx = memoryScopes.indexWhere(
      (item) =>
          (normalized.id.isNotEmpty && item.id == normalized.id) ||
          item.externalRef == source,
    );
    if (idx >= 0) {
      memoryScopes[idx] = normalized;
    } else {
      _upsertMemoryScope(normalized);
    }
  }

  ChatSession _normalizeSessionScope(ChatSession session) {
    final ref = _normalizeScopeRef(session.memoryScopeExternalRef);
    if (session.memoryScopeExternalRef == ref) return session;
    final normalized = session.copyWith(memoryScopeExternalRef: ref);
    try {
      cache?.upsertSession(normalized);
    } catch (_) {}
    return normalized;
  }

  void _migrateSessionsToScope(String oldRef, String newRef) {
    final source = _normalizeScopeRef(oldRef);
    final target = _normalizeScopeRef(newRef);
    for (var i = 0; i < sessions.length; i += 1) {
      final session = sessions[i];
      if (session.memoryScopeExternalRef != source) continue;
      final updated = session.copyWith(memoryScopeExternalRef: target);
      sessions[i] = updated;
      try {
        cache?.upsertSession(updated);
      } catch (_) {}
    }
  }

  String _generateChatId() => DateTime.now().microsecondsSinceEpoch.toString();

  /// Whether a message should be persisted to disk.
  bool _shouldPersist(ChatMessage m) {
    final kind = m.kind ?? '';
    if (kind == 'control' || kind == 'approval') return false;
    if ((m.meta?['thinking'] as bool?) == true) return false;
    return true;
  }

  List<ChatMessage> _restorableMessages(List<ChatMessage>? source) {
    if (source == null || source.isEmpty) return <ChatMessage>[];
    return source.where(_shouldPersist).toList(growable: false);
  }

  /// Restore AI conversation context from persisted messages and session metadata.
  void _restoreContext(String chatId, List? messages) {
    try {
      final conversationRepo = repo is ConversationStateRepository
          ? repo as ConversationStateRepository
          : null;
      if (messages != null && messages.isNotEmpty) {
        conversationRepo?.restoreHistoryFromMessages(
          chatId,
          messages.cast<ChatMessage>(),
        );
      }
      // Restore previous_response_id from session
      final session = sessions.cast<ChatSession?>().firstWhere(
            (s) => s?.id == chatId,
            orElse: () => null,
          );
      if (session?.lastResponseId != null) {
        conversationRepo?.setLastResponseId(chatId, session!.lastResponseId);
      }
    } catch (_) {}
  }

  /// Save latest response_id from repo into session and Hive.
  void _persistResponseId(String chatId) {
    try {
      final conversationRepo = repo is ConversationStateRepository
          ? repo as ConversationStateRepository
          : null;
      final respId = conversationRepo?.getLastResponseId(chatId);
      if (respId != null && respId.isNotEmpty) {
        final idx = sessions.indexWhere((s) => s.id == chatId);
        if (idx >= 0) {
          final s = sessions[idx];
          if (s.lastResponseId != respId) {
            final next = s.copyWith(lastResponseId: respId);
            sessions[idx] = next;
            try {
              cache?.upsertSession(next);
            } catch (_) {}
          }
        }
      }
    } catch (_) {}
  }
}

String _normalizeScopeRef(String value) {
  final normalized = value.trim();
  return normalized.isEmpty ? 'default' : normalized;
}

String _anchorMergeReason(MemoryAnchorMergeSuggestion suggestion) {
  final details = suggestion.reasonLabel;
  final reason =
      'merged duplicate anchor from frontend review: ${suggestion.sourceAnchor.label} -> ${suggestion.targetAnchor.label}; $details';
  return reason.length <= 320 ? reason : reason.substring(0, 320);
}

import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/src/features/chat/application/stores/chat_store.dart';
import 'package:frontend/src/features/chat/domain/entities/asset_extraction.dart';
import 'package:frontend/src/features/chat/domain/entities/chat_message.dart';
import 'package:frontend/src/features/chat/domain/entities/connection_status.dart';
import 'package:frontend/src/features/chat/domain/entities/cost_usage.dart';
import 'package:frontend/src/features/chat/domain/entities/document_chunk.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_capture.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_context_link.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_operations_console.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_scope.dart';
import 'package:frontend/src/features/chat/domain/repositories/chat_repository.dart';

void main() {
  group('ChatStore approvals', () {
    late _FakeChatRepository repo;

    setUp(() {
      repo = _FakeChatRepository();
    });

    tearDown(() async {
      await repo.close();
    });

    test('removes approval messages for completed job', () async {
      final store = ChatStore(repo, null);

      repo.emitMessage(_approvalMessage('approval-1', 'job-1'));
      await pumpEventQueue();

      expect(store.messages.where((m) => m.kind == 'approval'), hasLength(1));

      repo.emitMessage(
        ChatMessage(
          id: 'control-1',
          role: 'assistant',
          ts: DateTime.now(),
          kind: 'control',
          meta: const {'removeApprovalsForJobId': 'job-1'},
        ),
      );
      await pumpEventQueue();

      expect(store.messages.where((m) => m.kind == 'approval'), isEmpty);
    });

    test('marks stale approval response as unavailable', () async {
      final store = ChatStore(repo, null);
      repo.respondApprovalResult = false;

      repo.emitMessage(_approvalMessage('approval-1', 'job-1'));
      await pumpEventQueue();

      await store.respondApproval(
        messageId: 'approval-1',
        jobId: 'job-1',
        approvalId: 'safety-1',
        approved: true,
      );

      expect(store.messages.where((m) => m.kind == 'approval'), isEmpty);
      expect(store.messages.last.text, 'Approval is no longer active.');
      expect(store.messages.last.meta?['isError'], true);
    });

    test('records accepted approval response', () async {
      final store = ChatStore(repo, null);
      repo.respondApprovalResult = true;

      repo.emitMessage(_approvalMessage('approval-1', 'job-1'));
      await pumpEventQueue();

      await store.respondApproval(
        messageId: 'approval-1',
        jobId: 'job-1',
        approvalId: 'safety-1',
        approved: false,
      );

      expect(store.messages.where((m) => m.kind == 'approval'), isEmpty);
      expect(store.messages.last.text, 'Denied tool request.');
      expect(store.messages.last.meta, isNull);
    });

    test('creates new chats inside the selected memory scope', () async {
      final store = ChatStore(repo, null);

      store.createNewChat(memoryScopeExternalRef: 'sales-crm');

      expect(store.activeMemoryScopeExternalRef, 'sales-crm');
      expect(repo.activeMemoryScopeExternalRef, 'sales-crm');
      expect(store.sessions.first.memoryScopeExternalRef, 'sales-crm');
    });

    test('migrates thread metadata when a memory scope ref changes', () async {
      final store = ChatStore(repo, null);
      await store.refreshMemoryScopes();
      store.createNewChat(memoryScopeExternalRef: 'sales-crm');
      final scope = store.memoryScopes.firstWhere(
        (item) => item.externalRef == 'sales-crm',
      );

      await store.updateMemoryScope(
        scope,
        externalRef: 'sales-platform',
        name: 'Sales Platform',
      );

      expect(store.activeMemoryScopeExternalRef, 'sales-platform');
      expect(repo.activeMemoryScopeExternalRef, 'sales-platform');
      expect(store.sessions.first.memoryScopeExternalRef, 'sales-platform');
      expect(
        store.memoryScopes.any((item) => item.externalRef == 'sales-platform'),
        true,
      );
    });

    test(
      'renames local fallback memory scopes without merging empty ids',
      () async {
        final store = ChatStore(repo, null);
        store.createNewChat(memoryScopeExternalRef: 'local-alpha');
        store.createNewChat(memoryScopeExternalRef: 'local-beta');
        final alpha = store.memoryScopes.firstWhere(
          (item) => item.externalRef == 'local-alpha',
        );

        await store.updateMemoryScope(
          alpha,
          externalRef: 'local-alpha-renamed',
          name: 'Local Alpha Renamed',
        );

        expect(store.activeMemoryScopeExternalRef, 'local-beta');
        expect(repo.activeMemoryScopeExternalRef, 'local-beta');
        expect(
          store.memoryScopes.map((item) => item.externalRef),
          containsAll(['local-alpha-renamed', 'local-beta']),
        );
        expect(
          store.memoryScopes.any((item) => item.externalRef == 'local-alpha'),
          false,
        );
        expect(
          store.sessions.any(
            (session) =>
                session.memoryScopeExternalRef == 'local-alpha-renamed',
          ),
          true,
        );
      },
    );

    test(
      'deleting active memory scope switches to a remaining thread',
      () async {
        final store = ChatStore(repo, null);
        await store.refreshMemoryScopes();
        final defaultChatId = store.sessions.first.id;
        store.createNewChat(memoryScopeExternalRef: 'sales-crm');
        final sales = store.memoryScopes.firstWhere(
          (item) => item.externalRef == 'sales-crm',
        );

        await store.deleteMemoryScope(sales);

        expect(store.activeMemoryScopeExternalRef, 'default');
        expect(repo.activeMemoryScopeExternalRef, 'default');
        expect(store.activeChatId, defaultChatId);
        expect(
          store.sessions.any(
            (session) => session.memoryScopeExternalRef == 'sales-crm',
          ),
          false,
        );
        expect(
          store.memoryScopes.any((item) => item.externalRef == 'sales-crm'),
          false,
        );
      },
    );

    test('reviews context link suggestions from the active scope', () async {
      final store = ChatStore(repo, null);
      repo.contextLinkSuggestions = [_suggestion('ctxlinksug-1')];

      await store.refreshContextLinkSuggestions();

      expect(store.contextLinkSuggestions.single.id, 'ctxlinksug-1');

      await store.reviewContextLinkSuggestion(
        store.contextLinkSuggestions.single,
        approve: true,
      );

      expect(repo.reviewedSuggestions, ['ctxlinksug-1:approve']);
      expect(
        repo.reviewedSuggestionReasons['ctxlinksug-1'],
        'approved by user from review queue',
      );
      expect(store.contextLinkSuggestions, isEmpty);
    });
  });
}

ChatMessage _approvalMessage(String id, String jobId) {
  return ChatMessage(
    id: id,
    role: 'system',
    ts: DateTime.now(),
    kind: 'approval',
    text: 'Tool approval required',
    meta: {'jobId': jobId, 'approvalId': 'safety-1'},
  );
}

class _FakeChatRepository implements ChatRepository {
  final _messages = StreamController<ChatMessage>.broadcast();
  final _usage = StreamController<CostUsage>.broadcast();
  final _running = StreamController<bool>.broadcast();
  final _connection = StreamController<ConnectionStatus>.broadcast();

  bool respondApprovalResult = true;
  String activeMemoryScopeExternalRef = 'default';
  final Map<String, MemoryScope> scopesByRef = {
    'default': _scope('scope-default', 'default', 'Default'),
    'sales-crm': _scope('scope-sales-crm', 'sales-crm', 'Sales CRM'),
  };
  List<MemoryContextLinkSuggestion> contextLinkSuggestions = const [];
  final reviewedSuggestions = <String>[];
  final reviewedSuggestionReasons = <String, String?>{};

  void emitMessage(ChatMessage message) {
    _messages.add(message);
  }

  Future<void> close() async {
    await _messages.close();
    await _usage.close();
    await _running.close();
    await _connection.close();
  }

  @override
  Stream<ChatMessage> messages() => _messages.stream;

  @override
  Stream<CostUsage> usage() => _usage.stream;

  @override
  Stream<bool> running() => _running.stream;

  @override
  Stream<ConnectionStatus> connectionStatus() => _connection.stream;

  @override
  Future<String> createSession({String? provider}) async => 'session-1';

  @override
  Future<String> runTask({required String task}) async => 'job-1';

  @override
  Future<bool> respondApproval({
    required String jobId,
    required String approvalId,
    required bool approved,
  }) async {
    return respondApprovalResult;
  }

  @override
  Future<void> cancelJob(String jobId) async {}

  @override
  Future<void> cancelCurrentJob() async {}

  @override
  void setActiveChat(String chatId) {}

  @override
  void setActiveMemoryScopeExternalRef(String externalRef) {
    activeMemoryScopeExternalRef =
        externalRef.trim().isEmpty ? 'default' : externalRef.trim();
  }

  @override
  String currentMemoryScopeExternalRef() => activeMemoryScopeExternalRef;

  @override
  Future<List<MemoryScope>> listMemoryScopes() async {
    return scopesByRef.values.toList(growable: false);
  }

  @override
  Future<MemoryScope> createMemoryScope({
    required String externalRef,
    required String name,
  }) async {
    final scope = _scope('scope-$externalRef', externalRef, name);
    scopesByRef[externalRef] = scope;
    return scope;
  }

  @override
  Future<MemoryScope> updateMemoryScope({
    required String memoryScopeId,
    String? externalRef,
    String? name,
  }) async {
    final current = scopesByRef.values.firstWhere(
      (item) => item.id == memoryScopeId,
    );
    scopesByRef.remove(current.externalRef);
    final updated = current.copyWith(
      externalRef: externalRef ?? current.externalRef,
      name: name ?? current.name,
      updatedAt: DateTime.now(),
    );
    scopesByRef[updated.externalRef] = updated;
    return updated;
  }

  @override
  Future<void> deleteMemoryScope(String memoryScopeId) async {
    scopesByRef.removeWhere((_, item) => item.id == memoryScopeId);
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
  }) async {}

  @override
  Future<String> uploadFile(
    String name,
    List<int> bytes, {
    String? mime,
    void Function(int sent, int total)? onProgress,
    void Function(void Function())? onCreateCancel,
    String? previewBase64,
    String? batchId,
    int? batchSize,
    int? batchIndex,
  }) async {
    return 'file-1';
  }

  @override
  Future<List<int>> downloadFile(String id) async => <int>[];

  @override
  Future<List<AssetExtractionJob>> listAssetExtractions({
    String? status,
    int limit = 50,
  }) async {
    return const <AssetExtractionJob>[];
  }

  @override
  Future<AssetExtractionJob> getAssetExtraction(String jobId) async {
    throw UnimplementedError();
  }

  @override
  Future<AssetExtractionJob> retryAssetExtraction(String jobId) async {
    throw UnimplementedError();
  }

  @override
  Future<AssetExtractionJob> cancelAssetExtraction(String jobId) async {
    throw UnimplementedError();
  }

  @override
  Future<MemoryOperationsConsole> getOperationsConsole({int limit = 50}) async {
    return MemoryOperationsConsole(
      generatedAt: DateTime.now(),
      scope: const <String, dynamic>{},
      extractionStatusCounts: const <String, int>{},
      linkSuggestionStatusCounts: {
        'pending':
            contextLinkSuggestions.where((item) => item.isPending).length,
      },
      extractionJobs: const <AssetExtractionJob>[],
      contextLinkSuggestions: contextLinkSuggestions.take(limit).toList(),
      diagnostics: const <String, dynamic>{},
    );
  }

  @override
  Future<List<int>> downloadExtractionArtifact(String artifactId) async {
    return <int>[];
  }

  @override
  Future<List<DocumentChunk>> listDocumentChunks(String documentId) async {
    return const <DocumentChunk>[];
  }

  @override
  Future<List<MemoryCapture>> listMemoryCaptures({int limit = 50}) async {
    return const <MemoryCapture>[];
  }

  @override
  Future<List<MemoryContextLink>> listContextLinks({
    required String sourceType,
    required String sourceId,
    int limit = 50,
  }) async {
    return const <MemoryContextLink>[];
  }

  @override
  Future<List<MemoryContextLinkSuggestion>> listContextLinkSuggestions({
    String status = 'pending',
    int limit = 50,
  }) async {
    return contextLinkSuggestions;
  }

  @override
  Future<MemoryContextLinkSuggestion> reviewContextLinkSuggestion({
    required String suggestionId,
    required String action,
    String? reason,
  }) async {
    reviewedSuggestions.add('$suggestionId:$action');
    reviewedSuggestionReasons[suggestionId] = reason;
    final suggestion = contextLinkSuggestions.firstWhere(
      (item) => item.id == suggestionId,
    );
    contextLinkSuggestions = contextLinkSuggestions
        .where((item) => item.id != suggestionId)
        .toList(growable: false);
    return MemoryContextLinkSuggestion.fromMap({
      'id': suggestion.id,
      'space_id': suggestion.spaceId,
      'memory_scope_id': suggestion.memoryScopeId,
      'source_type': suggestion.sourceType,
      'source_id': suggestion.sourceId,
      'target_type': suggestion.targetType,
      'target_id': suggestion.targetId,
      'relation_type': suggestion.relationType,
      'confidence': suggestion.confidence,
      'reason': suggestion.reason,
      'score': suggestion.score,
      'status': action == 'approve' ? 'approved' : 'rejected',
      'metadata': suggestion.metadata,
      'created_at': suggestion.createdAt.toIso8601String(),
      'updated_at': DateTime.now().toIso8601String(),
      'reviewed_at': DateTime.now().toIso8601String(),
      'review_reason': reason,
    });
  }
}

MemoryScope _scope(String id, String externalRef, String name) {
  final now = DateTime.now();
  return MemoryScope(
    id: id,
    spaceId: 'space-1',
    externalRef: externalRef,
    name: name,
    status: 'active',
    createdAt: now,
    updatedAt: now,
  );
}

MemoryContextLinkSuggestion _suggestion(String id) {
  final now = DateTime.now();
  return MemoryContextLinkSuggestion(
    id: id,
    spaceId: 'space-1',
    memoryScopeId: 'scope-default',
    sourceType: 'capture',
    sourceId: 'capture-1',
    targetType: 'fact',
    targetId: 'fact-1',
    relationType: 'related_to',
    confidence: 'high',
    reason: 'matching text',
    score: 88,
    status: 'pending',
    metadata: const {
      'target_label': 'Q3 roadmap',
      'target_preview': 'Alex confirmed Q3 rollout.',
    },
    createdAt: now,
    updatedAt: now,
  );
}

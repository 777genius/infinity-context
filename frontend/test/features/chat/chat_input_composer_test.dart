import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/src/features/chat/application/stores/chat_store.dart';
import 'package:frontend/src/features/chat/domain/entities/asset_extraction.dart';
import 'package:frontend/src/features/chat/domain/entities/chat_message.dart';
import 'package:frontend/src/features/chat/domain/entities/connection_status.dart';
import 'package:frontend/src/features/chat/domain/entities/cost_usage.dart';
import 'package:frontend/src/features/chat/domain/entities/document_chunk.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_browser.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_capture.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_context_link.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_operations_console.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_scope.dart';
import 'package:frontend/src/features/chat/domain/repositories/chat_repository.dart';
import 'package:frontend/src/features/chat/presentation/widgets/chat_input_composer.dart';
import 'package:provider/provider.dart';

void main() {
  testWidgets('idle primary action sends when controller already has text', (
    tester,
  ) async {
    final repo = _RecordingChatRepository();
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          Provider<ChatRepository>.value(value: repo),
          Provider<ChatStore>.value(value: store),
        ],
        child: const MaterialApp(home: Scaffold(body: ChatInputComposer())),
      ),
    );

    expect(
      find.byKey(const ValueKey('quick_capture_save_target_strip')),
      findsOneWidget,
    );
    expect(find.text('Default'), findsOneWidget);
    expect(find.text('Thread 1'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('quick_capture_primary_action_button')),
      findsOneWidget,
    );

    final textField = tester.widget<TextField>(
      find.byKey(const ValueKey('quick_capture_input')),
    );
    textField.controller!.text = 'Captured from stale controller';

    await tester.tap(
      find.byKey(const ValueKey('quick_capture_primary_action_button')),
    );
    await tester.pump();

    expect(repo.sentTasks, ['Captured from stale controller']);
    expect(textField.controller!.text, isEmpty);
  });
}

class _RecordingChatRepository implements ChatRepository {
  final sentTasks = <String>[];
  final _messages = StreamController<ChatMessage>.broadcast();
  final _usage = StreamController<CostUsage>.broadcast();
  final _running = StreamController<bool>.broadcast();
  final _connection = StreamController<ConnectionStatus>.broadcast();

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
  Future<String> runTask({required String task}) async {
    sentTasks.add(task);
    return 'job-1';
  }

  @override
  Future<bool> respondApproval({
    required String jobId,
    required String approvalId,
    required bool approved,
  }) async {
    return true;
  }

  @override
  Future<void> cancelJob(String jobId) async {}

  @override
  Future<void> cancelCurrentJob() async {}

  @override
  void setActiveChat(String chatId) {}

  @override
  void setActiveMemoryScopeExternalRef(String externalRef) {}

  @override
  String currentMemoryScopeExternalRef() => 'default';

  @override
  Future<List<MemoryScope>> listMemoryScopes() async {
    return [_scope()];
  }

  @override
  Future<MemoryScope> createMemoryScope({
    required String externalRef,
    required String name,
  }) async {
    return _scope(externalRef: externalRef, name: name);
  }

  @override
  Future<MemoryScope> updateMemoryScope({
    required String memoryScopeId,
    String? externalRef,
    String? name,
  }) async {
    return _scope(id: memoryScopeId, externalRef: externalRef, name: name);
  }

  @override
  Future<void> deleteMemoryScope(String memoryScopeId) async {}

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
      linkSuggestionStatusCounts: const <String, int>{},
      extractionJobs: const <AssetExtractionJob>[],
      contextLinkSuggestions: const <MemoryContextLinkSuggestion>[],
      diagnostics: const <String, dynamic>{},
    );
  }

  @override
  Future<MemoryBrowserSnapshot> getMemoryBrowser({int limit = 50}) async {
    return MemoryBrowserSnapshot.empty();
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
    return const <MemoryContextLinkSuggestion>[];
  }

  @override
  Future<MemoryContextLinkSuggestion> reviewContextLinkSuggestion({
    required String suggestionId,
    required String action,
    String? reason,
  }) async {
    throw UnimplementedError();
  }
}

MemoryScope _scope({String? id, String? externalRef, String? name}) {
  final now = DateTime.now();
  return MemoryScope(
    id: id ?? 'scope-default',
    spaceId: 'space-1',
    externalRef: externalRef ?? 'default',
    name: name ?? 'Default',
    status: 'active',
    createdAt: now,
    updatedAt: now,
  );
}

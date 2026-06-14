import 'package:frontend/src/features/chat/domain/entities/chat_message.dart';
import 'package:frontend/src/features/chat/domain/entities/cost_usage.dart';
import 'package:frontend/src/features/chat/domain/entities/connection_status.dart';
import 'package:frontend/src/features/chat/domain/entities/asset_extraction.dart';
import 'package:frontend/src/features/chat/domain/entities/document_chunk.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_capture.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_context_link.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_browser.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_operations_console.dart';
import 'package:frontend/src/features/chat/domain/entities/memory_scope.dart';

abstract class ChatRepository {
  Stream<ChatMessage> messages();
  Stream<CostUsage> usage();
  Stream<bool> running();
  Stream<ConnectionStatus> connectionStatus();

  Future<String> createSession({String? provider});
  Future<String> runTask({required String task});
  Future<bool> respondApproval({
    required String jobId,
    required String approvalId,
    required bool approved,
  });
  Future<void> cancelJob(String jobId);
  Future<void> cancelCurrentJob();
  void setActiveChat(String chatId);
  void setActiveMemoryScopeExternalRef(String externalRef);
  String currentMemoryScopeExternalRef();
  Future<List<MemoryScope>> listMemoryScopes();
  Future<MemoryScope> createMemoryScope({
    required String externalRef,
    required String name,
  });
  Future<MemoryScope> updateMemoryScope({
    required String memoryScopeId,
    String? externalRef,
    String? name,
  });
  Future<void> deleteMemoryScope(String memoryScopeId);
  Future<void> createContextLink({
    required String sourceType,
    required String sourceId,
    required String targetType,
    required String targetId,
    required String relationType,
    required String confidence,
    required String reason,
  });
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
  });
  Future<List<int>> downloadFile(String id);
  Future<List<AssetExtractionJob>> listAssetExtractions({
    String? status,
    int limit = 50,
  });
  Future<AssetExtractionJob> getAssetExtraction(String jobId);
  Future<AssetExtractionJob> retryAssetExtraction(String jobId);
  Future<AssetExtractionJob> cancelAssetExtraction(String jobId);
  Future<MemoryOperationsConsole> getOperationsConsole({int limit = 50});
  Future<MemoryBrowserSnapshot> getMemoryBrowser({int limit = 50});
  Future<List<int>> downloadExtractionArtifact(String artifactId);
  Future<List<DocumentChunk>> listDocumentChunks(String documentId);
  Future<List<MemoryCapture>> listMemoryCaptures({int limit = 50});
  Future<List<MemoryContextLink>> listContextLinks({
    required String sourceType,
    required String sourceId,
    int limit = 50,
  });
  Future<List<MemoryContextLinkSuggestion>> listContextLinkSuggestions({
    String status = 'pending',
    int limit = 50,
  });
  Future<MemoryContextLinkSuggestion> reviewContextLinkSuggestion({
    required String suggestionId,
    required String action,
    String? reason,
  });
}

abstract class ConversationStateRepository {
  void restoreHistoryFromMessages(String chatId, List<ChatMessage> messages);
  void setLastResponseId(String chatId, String? responseId);
  String? getLastResponseId(String chatId);
}

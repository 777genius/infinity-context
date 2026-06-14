import 'package:dio/dio.dart';
import 'package:injectable/injectable.dart';

@lazySingleton
class BackendRestClient {
  final Dio _dio;
  BackendRestClient() : _dio = Dio();

  set baseUrl(String url) => _dio.options.baseUrl = url;
  set bearer(String? token) {
    if (token == null || token.isEmpty) {
      _dio.options.headers.remove('Authorization');
    } else {
      _dio.options.headers['Authorization'] = 'Bearer $token';
    }
  }

  Future<Map<String, dynamic>> createSpace({
    required String slug,
    required String name,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/v1/spaces',
      data: {
        'slug': slug,
        'name': name,
      },
    );
    return _data(resp.data);
  }

  Future<List<Map<String, dynamic>>> listSpaces({int limit = 100}) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/v1/spaces',
      queryParameters: {'limit': limit},
    );
    return _listData(resp.data);
  }

  Future<Map<String, dynamic>> createMemoryScope({
    required String spaceId,
    required String externalRef,
    required String name,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/v1/memory-scopes',
      data: {
        'space_id': spaceId,
        'external_ref': externalRef,
        'name': name,
      },
    );
    return _data(resp.data);
  }

  Future<List<Map<String, dynamic>>> listMemoryScopes({
    required String spaceId,
    int limit = 100,
  }) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/v1/memory-scopes',
      queryParameters: {
        'space_id': spaceId,
        'limit': limit,
      },
    );
    return _listData(resp.data);
  }

  Future<Map<String, dynamic>> updateMemoryScope({
    required String memoryScopeId,
    String? externalRef,
    String? name,
  }) async {
    final resp = await _dio.patch<Map<String, dynamic>>(
      '/v1/memory-scopes/$memoryScopeId',
      data: {
        if (externalRef != null) 'external_ref': externalRef,
        if (name != null) 'name': name,
      },
    );
    return _data(resp.data);
  }

  Future<void> deleteMemoryScope(String memoryScopeId) async {
    await _dio.delete<Map<String, dynamic>>('/v1/memory-scopes/$memoryScopeId');
  }

  Future<Map<String, dynamic>> uploadBytes(
    String name,
    List<int> bytes, {
    required String spaceSlug,
    required String memoryScopeExternalRef,
    String? threadExternalRef,
    String? mime,
    bool extract = false,
    String? parserProfile,
    void Function(int, int)? onProgress,
    void Function(void Function())? onCreateCancel,
  }) async {
    final cancelToken = CancelToken();
    try {
      onCreateCancel?.call(() {
        try {
          cancelToken.cancel('user');
        } catch (_) {}
      });
    } catch (_) {}
    final resp = await _dio.post<Map<String, dynamic>>(
      '/v1/assets',
      queryParameters: {
        'space_slug': spaceSlug,
        'memory_scope_external_ref': memoryScopeExternalRef,
        if (threadExternalRef != null) 'thread_external_ref': threadExternalRef,
        'filename': name,
        if (mime != null) 'content_type': mime,
        if (extract) 'extract': true,
        if (parserProfile != null) 'parser_profile': parserProfile,
      },
      data: Stream<List<int>>.fromIterable([bytes]),
      options: Options(
        headers: {
          'Content-Type': mime ?? 'application/octet-stream',
          'Content-Length': bytes.length,
        },
      ),
      onSendProgress: onProgress,
      cancelToken: cancelToken,
    );
    return _data(resp.data);
  }

  Future<List<Map<String, dynamic>>> listAssetExtractions({
    required String spaceSlug,
    required String memoryScopeExternalRef,
    String? threadExternalRef,
    String? status,
    int limit = 50,
  }) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/v1/asset-extractions',
      queryParameters: {
        'space_slug': spaceSlug,
        'memory_scope_external_ref': memoryScopeExternalRef,
        if (threadExternalRef != null) 'thread_external_ref': threadExternalRef,
        if (status != null) 'status': status,
        'limit': limit,
      },
    );
    return _listData(resp.data);
  }

  Future<Map<String, dynamic>> getAssetExtraction(String jobId) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/v1/asset-extractions/$jobId',
    );
    return _data(resp.data);
  }

  Future<Map<String, dynamic>> retryAssetExtraction(String jobId) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/v1/asset-extractions/$jobId/retry',
    );
    return _data(resp.data);
  }

  Future<Map<String, dynamic>> cancelAssetExtraction(String jobId) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/v1/asset-extractions/$jobId/cancel',
    );
    return _data(resp.data);
  }

  Future<Map<String, dynamic>> getOperationsConsole({
    required String spaceSlug,
    required String memoryScopeExternalRef,
    int limit = 50,
  }) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/v1/operations-console',
      queryParameters: {
        'space_slug': spaceSlug,
        'memory_scope_external_ref': memoryScopeExternalRef,
        'limit': limit,
      },
    );
    return _data(resp.data);
  }

  Future<Map<String, dynamic>> getMemoryBrowser({
    required String spaceSlug,
    required String memoryScopeExternalRef,
    int limit = 50,
  }) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/v1/memory-browser',
      queryParameters: {
        'space_slug': spaceSlug,
        'memory_scope_external_ref': memoryScopeExternalRef,
        'limit': limit,
      },
    );
    return _data(resp.data);
  }

  Future<List<int>> downloadExtractionArtifact(String artifactId) async {
    final resp = await _dio.get<List<int>>(
      '/v1/extraction-artifacts/$artifactId/download',
      options: Options(responseType: ResponseType.bytes),
    );
    return resp.data ?? <int>[];
  }

  Future<List<Map<String, dynamic>>> listDocumentChunks(
    String documentId, {
    int limit = 100,
  }) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/v1/documents/$documentId/chunks',
      queryParameters: {'limit': limit},
    );
    return _listData(resp.data);
  }

  Future<List<int>> downloadBytes(String fileId) async {
    final resp = await _dio.get<List<int>>(
      '/v1/assets/$fileId/download',
      options: Options(responseType: ResponseType.bytes),
    );
    return resp.data ?? <int>[];
  }

  Future<Map<String, dynamic>> createCapture({
    required String spaceSlug,
    required String memoryScopeExternalRef,
    required String threadExternalRef,
    required String text,
    required List<String> assetIds,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/v1/captures',
      data: {
        'space_slug': spaceSlug,
        'memory_scope_external_ref': memoryScopeExternalRef,
        'thread_external_ref': threadExternalRef,
        'source_agent': 'memo-stack-frontend',
        'source_kind': 'manual',
        'event_type': 'QuickCapture',
        'actor_role': 'user',
        'source_event_id': DateTime.now().microsecondsSinceEpoch.toString(),
        'text': text,
        'source_authority': 'user_statement',
        'evidence_refs': [
          for (final id in assetIds) {'source_type': 'asset', 'source_id': id},
        ],
        'metadata': {
          'frontend_chat_id': threadExternalRef,
          'asset_ids': assetIds,
        },
      },
    );
    return _data(resp.data);
  }

  Future<List<Map<String, dynamic>>> listCaptures({
    required String spaceSlug,
    required String memoryScopeExternalRef,
    String? status,
    String? consolidationStatus,
    int limit = 50,
  }) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/v1/captures',
      queryParameters: {
        'space_slug': spaceSlug,
        'memory_scope_external_ref': memoryScopeExternalRef,
        if (status != null) 'status': status,
        if (consolidationStatus != null)
          'consolidation_status': consolidationStatus,
        'limit': limit,
      },
    );
    return _listData(resp.data);
  }

  Future<List<Map<String, dynamic>>> suggestLinks({
    required String spaceSlug,
    required String memoryScopeExternalRef,
    required String threadExternalRef,
    required String text,
    required String sourceType,
    required String sourceId,
    bool persist = false,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/v1/link-suggestions',
      data: {
        'space_slug': spaceSlug,
        'memory_scope_external_ref': memoryScopeExternalRef,
        'thread_external_ref': threadExternalRef,
        'text': text,
        'source_type': sourceType,
        'source_id': sourceId,
        'limit': 10,
        'persist': persist,
      },
    );
    final data = _data(resp.data);
    final raw = data['candidates'];
    if (raw is! List) return const <Map<String, dynamic>>[];
    return raw
        .whereType<Map>()
        .map((item) => item.map((k, v) => MapEntry(k.toString(), v)))
        .toList(growable: false);
  }

  Future<Map<String, dynamic>> createContextLink({
    required String spaceSlug,
    required String memoryScopeExternalRef,
    required String sourceType,
    required String sourceId,
    required String targetType,
    required String targetId,
    required String relationType,
    required String confidence,
    required String reason,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/v1/context-links',
      data: {
        'space_slug': spaceSlug,
        'memory_scope_external_ref': memoryScopeExternalRef,
        'source_type': sourceType,
        'source_id': sourceId,
        'target_type': targetType,
        'target_id': targetId,
        'relation_type': relationType,
        'confidence': confidence,
        'reason': reason,
      },
    );
    return _data(resp.data);
  }

  Future<List<Map<String, dynamic>>> listContextLinkSuggestions({
    required String spaceSlug,
    required String memoryScopeExternalRef,
    String status = 'pending',
    int limit = 50,
  }) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/v1/context-link-suggestions',
      queryParameters: {
        'space_slug': spaceSlug,
        'memory_scope_external_ref': memoryScopeExternalRef,
        'status': status,
        'limit': limit,
      },
    );
    return _listData(resp.data);
  }

  Future<Map<String, dynamic>> reviewContextLinkSuggestion({
    required String suggestionId,
    required String action,
    String? reason,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/v1/context-link-suggestions/$suggestionId/review',
      data: {
        'action': action,
        if (reason != null && reason.trim().isNotEmpty) 'reason': reason.trim(),
      },
    );
    final data = _data(resp.data);
    final suggestion = data['suggestion'];
    if (suggestion is Map<String, dynamic>) return suggestion;
    if (suggestion is Map) {
      return suggestion.map((key, value) => MapEntry(key.toString(), value));
    }
    return const <String, dynamic>{};
  }

  Future<List<Map<String, dynamic>>> listContextLinks({
    required String spaceSlug,
    required String memoryScopeExternalRef,
    required String sourceType,
    required String sourceId,
    String status = 'active',
    int limit = 50,
  }) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/v1/context-links',
      queryParameters: {
        'space_slug': spaceSlug,
        'memory_scope_external_ref': memoryScopeExternalRef,
        'source_type': sourceType,
        'source_id': sourceId,
        'status': status,
        'limit': limit,
      },
    );
    return _listData(resp.data);
  }

  Future<Map<String, dynamic>> healthz() async {
    final resp = await _dio.get('/healthz');
    return (resp.data as Map<String, dynamic>);
  }

  Map<String, dynamic> _data(Map<String, dynamic>? response) {
    final data = response?['data'];
    if (data is Map<String, dynamic>) return data;
    if (data is Map) {
      return data.map((key, value) => MapEntry(key.toString(), value));
    }
    return const <String, dynamic>{};
  }

  List<Map<String, dynamic>> _listData(Map<String, dynamic>? response) {
    final data = response?['data'];
    if (data is! List) return const <Map<String, dynamic>>[];
    return data
        .whereType<Map>()
        .map(
            (item) => item.map((key, value) => MapEntry(key.toString(), value)))
        .toList(growable: false);
  }
}

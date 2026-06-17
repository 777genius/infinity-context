import 'package:frontend/src/features/chat/application/services/attachment_upload_models.dart';
import 'package:frontend/src/features/chat/application/services/image_attachment_preprocessor.dart';
import 'package:frontend/src/features/chat/domain/repositories/attachment_upload_limits.dart';
import 'package:frontend/src/features/chat/domain/repositories/chat_repository.dart';

class AttachmentUploadService {
  static const int inlinePreviewMaxBytes = 2 * 1024 * 1024;

  final ChatRepository _repo;
  final AttachmentUploadLimits? _limits;
  final int _fallbackMaxBytes;

  const AttachmentUploadService({
    required ChatRepository repo,
    AttachmentUploadLimits? limits,
    int maxBytes = AttachmentUploadDefaults.maxBytes,
  })  : _repo = repo,
        _limits = limits,
        _fallbackMaxBytes = maxBytes;

  Future<List<String>> uploadAll(
    List<AttachmentUploadDraft> drafts, {
    AttachmentUploadProgress? progress,
  }) async {
    if (drafts.isEmpty) return const [];
    final batchId = DateTime.now().microsecondsSinceEpoch.toString();
    final uploaded = <String>[];
    final maxBytes = await _maxBytes();
    final prepared = <_PreparedUpload>[];

    for (final draft in drafts) {
      final result = await _prepare(draft);
      final bytes = result.bytes;
      if (bytes.length > maxBytes) {
        progress?.start(draft.name, bytes.length);
        progress?.fail(draft.name, _tooLargeMessage(bytes.length, maxBytes));
        continue;
      }
      prepared.add(_PreparedUpload(draft: draft, attachment: result));
    }

    final total = prepared.length;
    for (var index = 0; index < prepared.length; index += 1) {
      final item = prepared[index];
      final draft = item.draft;
      final result = item.attachment;
      final bytes = result.bytes;

      var canceled = false;
      void Function()? cancelNetwork;
      progress?.start(
        draft.name,
        bytes.length,
        onCancel: () {
          canceled = true;
          cancelNetwork?.call();
        },
        previewBytes: bytes.length > inlinePreviewMaxBytes ? null : bytes,
      );

      try {
        final fileId = await _repo.uploadFile(
          draft.name,
          bytes,
          mime: result.mime,
          onProgress: (sent, totalBytes) {
            if (!canceled) progress?.progress(draft.name, sent, totalBytes);
          },
          onCreateCancel: (fn) {
            cancelNetwork = fn;
          },
          previewBase64: result.previewBase64,
          batchId: batchId,
          batchSize: total,
          batchIndex: index + 1,
        );
        uploaded.add(fileId);
        progress?.complete(draft.name);
      } catch (error) {
        if (!canceled) {
          progress?.fail(draft.name, error.toString());
        }
      }
    }

    return uploaded;
  }

  Future<_PreparedAttachment> _prepare(AttachmentUploadDraft draft) async {
    if (!draft.isImage) {
      return _PreparedAttachment(
        bytes: draft.bytes,
        mime: draft.mime ?? 'application/octet-stream',
      );
    }

    final compressed = await compressIfNeeded(draft.bytes);
    return _PreparedAttachment(
      bytes: compressed.bytes,
      mime: compressed.mime,
      previewBase64: await makePreviewBase64(compressed.bytes),
    );
  }

  Future<int> _maxBytes() async {
    final limits = _limits;
    if (limits == null) return _fallbackMaxBytes;
    try {
      final value = await limits.maxUploadBytes();
      if (value > 0) return value;
    } catch (_) {}
    return _fallbackMaxBytes;
  }

  String _tooLargeMessage(int actualBytes, int maxBytes) {
    return 'File is too large: ${_formatBytes(actualBytes)} exceeds '
        '${_formatBytes(maxBytes)} upload limit';
  }

  String _formatBytes(int bytes) {
    const mb = 1024 * 1024;
    const kb = 1024;
    if (bytes >= mb) {
      return '${(bytes / mb).toStringAsFixed(1)} MB';
    }
    if (bytes >= kb) {
      return '${(bytes / kb).toStringAsFixed(1)} KB';
    }
    return '$bytes B';
  }
}

class _PreparedAttachment {
  final List<int> bytes;
  final String mime;
  final String? previewBase64;

  const _PreparedAttachment({
    required this.bytes,
    required this.mime,
    this.previewBase64,
  });
}

class _PreparedUpload {
  final AttachmentUploadDraft draft;
  final _PreparedAttachment attachment;

  const _PreparedUpload({
    required this.draft,
    required this.attachment,
  });
}

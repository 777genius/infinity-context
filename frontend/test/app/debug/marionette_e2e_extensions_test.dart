import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/src/app/debug/marionette_e2e_extensions.dart';
import 'package:frontend/src/features/chat/application/stores/chat_store.dart';

import 'marionette_e2e_test_support.dart';

void main() {
  group('MemoStackMarionetteE2eCommandHandler', () {
    late FakeMarionetteChatRepository repo;
    late ChatStore store;
    late MemoStackMarionetteE2eCommandHandler handler;

    setUp(() {
      repo = FakeMarionetteChatRepository();
      store = ChatStore(repo, null);
      handler = MemoStackMarionetteE2eCommandHandler(() => store);
    });

    tearDown(() async {
      store.dispose();
      await repo.close();
    });

    test('submits a capture into the requested scope and thread', () async {
      final result = await handler.submitCapture({
        'memoryScopeExternalRef': 'project-atlas',
        'memoryScopeName': 'Project Atlas',
        'threadTitle': 'Alex follow-up',
        'text': 'Alex asked to connect the launch note with Project Atlas.',
      });

      expect(result['activeMemoryScopeExternalRef'], 'project-atlas');
      expect(result['captureCount'], 1);
      expect(result['pendingLinkSuggestionCount'], 1);
      expect(result['operationsPendingLinkSuggestionCount'], 1);
      expect(result['latestCapture'], isA<Map<String, dynamic>>());
      expect(
        (result['latestCapture'] as Map<String, dynamic>)['preview'],
        contains('Alex asked'),
      );
      expect(
        (result['activeThread'] as Map<String, dynamic>)['title'],
        'Alex follow-up',
      );
      expect(repo.lastTask, contains('Project Atlas'));
    });

    test('submits an attachment capture with asset evidence', () async {
      final result = await handler.submitAttachmentCapture({
        'memoryScopeExternalRef': 'project-atlas',
        'memoryScopeName': 'Project Atlas',
        'threadTitle': 'Attachment evidence',
        'filename': 'launch-note.txt',
        'mime': 'text/plain',
        'content': 'Attachment content for Project Atlas launch evidence.',
        'text': 'Attachment note for Project Atlas launch.',
      });

      expect(result['uploadedAssetIds'], ['file-1']);
      expect(result['captureCount'], 1);
      expect(result['assetExtractionCount'], 1);
      expect(repo.lastTask, contains('Attachment note'));
      expect(repo.pendingUploads, isEmpty);

      final latestCapture = result['latestCapture'] as Map<String, dynamic>;
      expect(latestCapture['assetIds'], contains('file-1'));

      final extractions = result['assetExtractions'] as List<dynamic>;
      final extraction = extractions.single as Map<String, dynamic>;
      expect(extraction['assetId'], 'file-1');
      expect(extraction['threadId'], store.activeChatId);
      expect(extraction['status'], 'succeeded');
      expect(extraction['parserName'], 'fake_text_parser');
      expect(extraction['progressPercent'], 100);
      expect(extraction['resultDocumentIds'], ['doc-file-1']);
      expect(extraction['artifactTypes'], contains('markdown'));
    });

    test('controls retry and cancel for asset extraction jobs', () async {
      final failed = repo.seedAssetExtraction(
        id: 'extract-failed',
        assetId: 'file-failed',
        status: 'failed',
      );

      var result = await handler.retryAssetExtraction({
        'jobId': failed.id,
      });

      expect(result['retried'], true);
      var extraction = result['assetExtraction'] as Map<String, dynamic>;
      expect(extraction['id'], failed.id);
      expect(extraction['status'], 'pending');
      expect(extraction['progressPercent'], 0);

      final running = repo.seedAssetExtraction(
        id: 'extract-running',
        assetId: 'file-running',
        status: 'running',
      );

      result = await handler.cancelAssetExtraction({
        'assetId': running.assetId,
      });

      expect(result['canceled'], true);
      extraction = result['assetExtraction'] as Map<String, dynamic>;
      expect(extraction['id'], running.id);
      expect(extraction['status'], 'canceled');
    });

    test('reviews the first pending link suggestion', () async {
      await handler.submitCapture({
        'text': 'Alex confirmed the Project Atlas launch timing.',
      });

      final result = await handler.reviewFirstPendingLinkSuggestion({
        'approve': 'false',
      });

      expect(result['reviewed'], true);
      expect(result['reviewAction'], 'reject');
      expect(result['pendingLinkSuggestionCount'], 0);
      expect(repo.reviewedSuggestions, ['ctxlinksug-1:reject']);
      expect(
        repo.reviewedSuggestionReasons['ctxlinksug-1'],
        'rejected by user from review queue',
      );
    });

    test('reviews a pending link suggestion by target filter', () async {
      await handler.submitCapture({
        'text': 'Alex confirmed the Project Atlas launch timing.',
      });
      repo.contextLinkSuggestions = [
        marionetteSuggestion(
          'ctxlinksug-other',
          sourceId: 'capture-1',
          targetId: 'anchor-other',
        ),
        marionetteSuggestion(
          'ctxlinksug-project',
          sourceId: 'capture-1',
          targetId: 'anchor-project-atlas',
        ),
      ];

      final result = await handler.reviewFirstPendingLinkSuggestion({
        'approve': 'true',
        'targetId': 'anchor-project-atlas',
      });

      expect(result['reviewed'], true);
      expect(result['reviewedSuggestionId'], 'ctxlinksug-project');
      expect(result['reviewedTargetId'], 'anchor-project-atlas');
      expect(repo.reviewedSuggestions, ['ctxlinksug-project:approve']);
      expect(repo.contextLinkSuggestions.single.id, 'ctxlinksug-other');
    });

    test('does not review pending link suggestions outside target filter',
        () async {
      await handler.submitCapture({
        'text': 'Alex confirmed the Project Atlas launch timing.',
      });

      final result = await handler.reviewFirstPendingLinkSuggestion({
        'approve': 'true',
        'targetId': 'anchor-missing',
      });

      expect(result['reviewed'], false);
      expect(repo.reviewedSuggestions, isEmpty);
      expect(repo.contextLinkSuggestions.single.id, 'ctxlinksug-1');
    });

    test('creates a manual context link from a pending suggestion', () async {
      await handler.submitCapture({
        'text': 'Alex confirmed the Project Atlas launch timing.',
      });

      final result = await handler.createManualContextLinkFromSuggestion({
        'suggestionTargetId': 'anchor-project-atlas',
        'targetType': 'anchor',
        'targetId': 'anchor-manual-project',
        'relationType': 'supports',
        'confidence': 'medium',
        'reason': 'manual override',
      });

      expect(result['manualLinked'], true);
      expect(result['manualLinkSuggestionId'], 'ctxlinksug-1');
      expect(result['manualLinkTargetId'], 'anchor-manual-project');
      expect(result['pendingLinkSuggestionCount'], 0);
      expect(result['memoryBrowserContextLinkCount'], 1);
      expect(repo.createdContextLinks, [
        {
          'source_type': 'capture',
          'source_id': 'capture-1',
          'target_type': 'anchor',
          'target_id': 'anchor-manual-project',
          'relation_type': 'supports',
          'confidence': 'medium',
          'reason': 'manual override',
        },
      ]);
      expect(repo.reviewedSuggestions, ['ctxlinksug-1:reject']);
      expect(
        repo.reviewedSuggestionReasons['ctxlinksug-1'],
        'replaced by manual link',
      );
    });

    test('drives memory anchor lifecycle for live e2e checks', () async {
      var result = await handler.createMemoryAnchor({
        'memoryScopeExternalRef': 'project-atlas',
        'memoryScopeName': 'Project Atlas',
        'kind': 'person',
        'label': 'Alex Key',
        'aliases': 'Alex, AK',
        'description': 'Launch stakeholder',
      });

      expect(result['memoryBrowserAnchorCount'], 1);
      expect(result['pendingAnchorMergeSuggestionCount'], 0);
      final created = result['anchor'] as Map<String, dynamic>;
      expect(created['label'], 'Alex Key');
      expect(created['aliases'], ['Alex', 'AK']);

      result = await handler.updateMemoryAnchor({
        'anchorId': created['id'] as String,
        'label': 'Alex Key',
        'aliases': 'Alex, Sasha, AK',
        'description': 'Launch and memory stakeholder',
      });

      final updated = result['anchor'] as Map<String, dynamic>;
      expect(updated['description'], 'Launch and memory stakeholder');
      expect(updated['aliases'], ['Alex', 'Sasha', 'AK']);

      result = await handler.splitMemoryAnchorAlias({
        'anchorId': created['id'] as String,
        'alias': 'AK',
        'newLabel': 'Alex Krasnov',
      });

      expect(result['memoryBrowserAnchorCount'], 2);
      final split = result['splitAnchor'] as Map<String, dynamic>;
      expect(split['label'], 'Alex Krasnov');

      repo.anchorMergeSuggestions = [
        marionetteMergeSuggestion(
          repo.anchors.firstWhere((anchor) => anchor.id == split['id']),
          repo.anchors.firstWhere((anchor) => anchor.id == created['id']),
        ),
      ];

      result = await handler.mergeFirstAnchorSuggestion({});

      expect(result['merged'], true);
      expect(result['memoryBrowserAnchorCount'], 1);
      expect(result['pendingAnchorMergeSuggestionCount'], 0);

      result = await handler.deleteMemoryAnchor({
        'label': 'Alex Key',
        'reason': 'cleanup after e2e',
      });

      expect(result['deletedAnchorLabel'], 'Alex Key');
      expect(result['memoryBrowserAnchorCount'], 0);
    });
  });
}

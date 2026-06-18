import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/src/features/chat/application/services/downloaded_file_opener.dart';
import 'package:frontend/src/features/chat/application/services/open_extraction_artifact.dart';
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
import 'package:frontend/src/features/chat/presentation/screen/chat_list_overlay_screen.dart';
import 'package:frontend/src/features/chat/presentation/widgets/chat_list_sidebar.dart';
import 'package:frontend/src/features/chat/presentation/widgets/chat_messages_list.dart';
import 'package:frontend/src/presentation/theme/app_theme.dart';
import 'package:provider/provider.dart';

void main() {
  testWidgets('compact list can create a memory scope', (tester) async {
    final repo = _UxFakeChatRepository();
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await _pumpWithStore(
      tester,
      store: store,
      child: const ChatListOverlayScreen(),
    );

    expect(find.text('Scopes & threads'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('memory_scope_create_overlay_button')),
      findsOneWidget,
    );

    await tester.tap(
      find.byKey(const ValueKey('memory_scope_create_overlay_button')),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const ValueKey('memory_scope_name_field')),
      'Research',
    );
    await tester.enterText(
      find.byKey(const ValueKey('memory_scope_ref_field')),
      'research',
    );
    await tester.tap(find.byKey(const ValueKey('memory_scope_save_button')));
    await tester.pumpAndSettle();

    expect(repo.scopesByRef.containsKey('research'), isTrue);
    expect(find.text('Research'), findsOneWidget);
  });

  testWidgets('editing a memory scope ref keeps its local threads grouped', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    final scope = (await store.createMemoryScope(
      externalRef: 'research',
      name: 'Research',
    ))!;
    final originalThreadId = store.activeChatId;

    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    expect(find.byKey(const ValueKey('memory_scope_group_research')),
        findsOneWidget);
    expect(
        find.byKey(ValueKey('chat_thread_$originalThreadId')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('memory_scope_menu_research')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Edit').last);
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const ValueKey('memory_scope_name_field')),
      'Client Research',
    );
    await tester.enterText(
      find.byKey(const ValueKey('memory_scope_ref_field')),
      'client-research',
    );
    await tester.tap(find.byKey(const ValueKey('memory_scope_save_button')));
    await tester.pumpAndSettle();

    expect(scope.externalRef, 'research');
    expect(store.activeMemoryScopeExternalRef, 'client-research');
    expect(
      store.sessions
          .where(
              (session) => session.memoryScopeExternalRef == 'client-research')
          .map((session) => session.id),
      contains(originalThreadId),
    );
    expect(find.byKey(const ValueKey('memory_scope_group_client_research')),
        findsOneWidget);
    expect(
        find.byKey(ValueKey('chat_thread_$originalThreadId')), findsOneWidget);
  });

  testWidgets('save progress is visible while memory linking runs', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await _pumpWithStore(
      tester,
      store: store,
      child: const SizedBox(width: 420, height: 520, child: ChatMessagesList()),
    );

    repo.emitMessage(
      ChatMessage(
        id: 'thinking-1',
        role: 'assistant',
        ts: DateTime.now(),
        kind: 'thought',
        text: 'Saving and finding related context...',
        meta: const {'thinking': true},
      ),
    );
    await tester.pump();

    expect(find.text('Saving and finding related context...'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('memory_save_progress_bar')),
      findsOneWidget,
    );
    await tester.pump(const Duration(milliseconds: 300));
  });

  testWidgets('sidebar shows extraction history actions for active scope', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    repo.extractions = [
      _job(
        id: 'extract-ready',
        status: 'succeeded',
        artifacts: [_artifact('artifact-ready', 'extract-ready')],
      ),
      _job(
        id: 'extract-failed',
        status: 'failed',
        metadata: const {
          'cancellation_status': 'ignored_after_document_commit',
          'cancellation_message': 'finalizing extraction',
        },
      ),
    ];
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    expect(find.byKey(const ValueKey('memory_operations_console_panel')),
        findsOneWidget);
    expect(find.textContaining('Failed'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('memory_operations_reprocess_extract_failed')),
      findsOneWidget,
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_operations_open_button')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Ready'), findsOneWidget);
    expect(find.text('cancel: ignored_after_document_commit'), findsOneWidget);
    expect(find.text('cancel note: finalizing extraction'), findsOneWidget);
    expect(find.byKey(const ValueKey('asset_extraction_open_artifact_ready')),
        findsOneWidget);
  });

  testWidgets('operations console dialog keeps backend errors visible', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository()
      ..operationsConsoleError = Exception('backend offline');
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    expect(
        find.textContaining('Operations console unavailable'), findsOneWidget);

    await tester
        .tap(find.byKey(const ValueKey('memory_operations_open_button')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('memory_operations_error_banner')),
        findsOneWidget);
    expect(find.textContaining('backend offline'), findsWidgets);
  });

  testWidgets('operations console explains empty link suggestions', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_operations_open_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Link suggestions'));
    await tester.pumpAndSettle();

    expect(find.text('No pending links'), findsOneWidget);
    expect(find.textContaining('No visible same-scope memory'), findsOneWidget);
  });

  testWidgets('operations console shows suggestion matched terms', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    repo.contextLinkSuggestions = [_suggestion('ctxlinksug-1')];
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_operations_open_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Link suggestions'));
    await tester.pumpAndSettle();

    expect(find.textContaining('matched: alex, q3'), findsOneWidget);
  });

  testWidgets('operations console shows reviewed suggestion feedback', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    repo.contextLinkSuggestions = [
      _suggestion(
        'ctxlinksug-1',
        status: 'rejected',
        reviewReason: 'not relevant',
        reviewedAt: DateTime(2026, 1, 2, 3, 4),
      ),
    ];
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_operations_open_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Link suggestions'));
    await tester.pumpAndSettle();

    expect(find.textContaining('status: rejected'), findsOneWidget);
    expect(find.textContaining('review: not relevant'), findsOneWidget);
    expect(find.textContaining('reviewed: 2026-01-02 03:04'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('memory_operations_approve_ctxlinksug_1')),
      findsNothing,
    );
    expect(
      find.byKey(const ValueKey('memory_operations_edit_ctxlinksug_1')),
      findsNothing,
    );
    expect(
      find.byKey(const ValueKey('memory_operations_evidence_ctxlinksug_1')),
      findsOneWidget,
    );
  });

  testWidgets('operations console filters review history by status and type', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    repo.contextLinkSuggestions = [
      _suggestion(
        'ctxlinksug-pending',
        metadata: const {
          'target_label': 'Q3 roadmap',
          'target_preview': 'Alex confirmed Q3 rollout.',
          'matched_terms': ['alex', 'q3'],
          'policy_decision': 'needs_review',
          'review_gate': 'required',
          'review_gate_reason': 'mime_content_type_mismatch',
          'auto_approve_eligible': true,
          'reason_codes': [
            'text_match',
            'visual_text_match',
            'keyframe_match',
          ],
          'policy_reason_codes': ['score_threshold_met', 'text_match'],
          'evidence_modalities': ['image', 'video', 'time_range'],
          'evidence_kinds': ['ocr_text', 'video_keyframe'],
          'mime_content_type_mismatch': true,
          'mime_declared_content_type': 'image/png',
          'mime_detected_content_type': 'text/plain',
        },
      ),
      _suggestion(
        'ctxlinksug-anchor',
        status: 'rejected',
        targetType: 'anchor',
        targetId: 'anchor-alex',
        metadata: const {
          'target_label': 'Alex',
          'target_preview': 'Person anchor observed from capture text.',
          'anchor_kind': 'person',
          'normalized_key': 'alex',
          'matched_terms': ['alex'],
        },
      ),
      _suggestion(
        'ctxlinksug-approved',
        status: 'approved',
        targetType: 'document',
        targetId: 'doc-1',
        metadata: const {
          'target_label': 'Architecture notes',
          'target_preview': 'Document about memory architecture.',
        },
      ),
    ];
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_operations_open_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Link suggestions'));
    await tester.pumpAndSettle();

    expect(find.text('All 3'), findsOneWidget);
    expect(find.text('Pending 1'), findsOneWidget);
    expect(find.text('Rejected 1'), findsOneWidget);
    expect(find.text('person anchor 1'), findsOneWidget);
    expect(find.textContaining('policy: needs_review'), findsOneWidget);
    expect(
      find.textContaining('signals: text match, visual text, keyframe'),
      findsOneWidget,
    );
    expect(find.textContaining('evidence: image, video, time range'),
        findsOneWidget);
    expect(
      find.textContaining('evidence kinds: ocr_text, video_keyframe'),
      findsOneWidget,
    );
    expect(find.textContaining('gate: required'), findsOneWidget);
    expect(find.textContaining('risk: MIME mismatch'), findsOneWidget);
    expect(
        find.textContaining('mime: image/png -> text/plain'), findsOneWidget);
    expect(find.text('auto eligible'), findsOneWidget);
    expect(
      find.textContaining('policy codes: score_threshold_met, text_match'),
      findsOneWidget,
    );

    await tester.tap(
      find.byKey(const ValueKey('memory_link_status_filter_rejected')),
    );
    await tester.pumpAndSettle();

    expect(find.text('Alex'), findsOneWidget);
    expect(
      find.byKey(
          const ValueKey('memory_operations_suggestion_ctxlinksug_pending')),
      findsNothing,
    );

    await tester.tap(
      find.byKey(const ValueKey('memory_link_type_filter_person_anchor')),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('anchor: person'), findsOneWidget);
    expect(find.textContaining('key: alex'), findsOneWidget);
  });

  testWidgets('operations console batch approves only visible pending links', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    repo.contextLinkSuggestions = [
      _suggestion(
        'ctxlinksug-pending-fact',
        metadata: const {
          'target_label': 'Q3 roadmap',
          'target_preview': 'Alex confirmed Q3 rollout.',
        },
      ),
      _suggestion(
        'ctxlinksug-pending-anchor',
        targetType: 'anchor',
        targetId: 'anchor-alex',
        metadata: const {
          'target_label': 'Alex',
          'target_preview': 'Person anchor observed from capture text.',
          'anchor_kind': 'person',
          'normalized_key': 'alex',
        },
      ),
      _suggestion(
        'ctxlinksug-rejected-anchor',
        status: 'rejected',
        targetType: 'anchor',
        targetId: 'anchor-old-alex',
        metadata: const {
          'target_label': 'Old Alex',
          'target_preview': 'Rejected person anchor.',
          'anchor_kind': 'person',
          'normalized_key': 'old-alex',
        },
      ),
    ];
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_operations_open_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Link suggestions'));
    await tester.pumpAndSettle();

    await tester.tap(
      find.byKey(const ValueKey('memory_link_type_filter_person_anchor')),
    );
    await tester.pumpAndSettle();

    expect(find.text('Approve visible (1)'), findsOneWidget);

    await tester.tap(
      find.byKey(const ValueKey('memory_link_batch_approve_visible_button')),
    );
    await tester.pumpAndSettle();

    expect(repo.batchReviewedSuggestionIds, [
      ['ctxlinksug-pending-anchor'],
    ]);
    expect(repo.reviewedSuggestions, ['ctxlinksug-pending-anchor:approve']);
    expect(
      repo.contextLinkSuggestions.map((item) => item.id),
      contains('ctxlinksug-pending-fact'),
    );
    expect(
      repo.contextLinkSuggestions.map((item) => item.id),
      contains('ctxlinksug-rejected-anchor'),
    );
  });

  testWidgets('operations console opens suggestion evidence modal', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    repo.contextLinkSuggestions = [_suggestion('ctxlinksug-1')];
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_operations_open_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Link suggestions'));
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const ValueKey('memory_operations_evidence_ctxlinksug_1')),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('memory_link_evidence_dialog')),
        findsOneWidget);
    expect(find.text('Link evidence'), findsOneWidget);
    expect(find.text('capture capture-1'), findsOneWidget);
    expect(find.textContaining('matched_terms: alex, q3'), findsOneWidget);
  });

  testWidgets('operations console opens source and target from review modal', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    repo.contextLinkSuggestions = [
      _suggestion(
        'ctxlinksug-1',
        metadata: const {
          'source_label': 'Call note',
          'source_preview': 'Alex said Q3 rollout is approved.',
          'target_label': 'Q3 roadmap',
          'target_preview': 'Alex confirmed Q3 rollout.',
          'matched_terms': ['alex', 'q3'],
        },
      ),
    ];
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_operations_open_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Link suggestions'));
    await tester.pumpAndSettle();

    await tester.tap(
      find.byKey(const ValueKey('memory_operations_source_ctxlinksug_1')),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('context_link_endpoint_dialog')),
        findsOneWidget);
    expect(find.text('Source evidence'), findsOneWidget);
    expect(find.text('Call note'), findsOneWidget);
    expect(find.text('capture-1'), findsOneWidget);
    expect(find.text('Alex said Q3 rollout is approved.'), findsOneWidget);

    await tester.tap(
      find.byKey(const ValueKey('context_link_endpoint_close_button')),
    );
    await tester.pumpAndSettle();

    await tester.tap(
      find.byKey(const ValueKey('memory_operations_target_ctxlinksug_1')),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('context_link_endpoint_dialog')),
        findsOneWidget);
    expect(find.text('Target memory'), findsOneWidget);
    expect(find.text('Q3 roadmap'), findsWidgets);
    expect(find.text('fact-1'), findsOneWidget);
    expect(find.text('Alex confirmed Q3 rollout.'), findsWidgets);
  });

  testWidgets('operations console approves edited link from suggestion', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    repo.contextLinkSuggestions = [_suggestion('ctxlinksug-1')];
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_operations_open_button')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Link suggestions'));
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const ValueKey('memory_operations_edit_ctxlinksug_1')),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('memory_manual_link_dialog')),
        findsOneWidget);
    await tester.enterText(
      find.byKey(const ValueKey('memory_manual_link_target_id_field')),
      'fact-edited',
    );
    await tester.enterText(
      find.byKey(const ValueKey('memory_manual_link_reason_field')),
      'manual override',
    );
    await tester
        .tap(find.byKey(const ValueKey('memory_manual_link_save_button')));
    await tester.pumpAndSettle();

    expect(repo.createdContextLinks, isEmpty);
    expect(repo.reviewedSuggestions, ['ctxlinksug-1:approve']);
    expect(
      repo.reviewedSuggestionReasons['ctxlinksug-1'],
      'approved by user with target override',
    );
    expect(repo.reviewedSuggestionOverrides['ctxlinksug-1'], {
      'target_type': 'fact',
      'target_id': 'fact-edited',
      'relation_type': 'related_to',
      'confidence': 'high',
      'link_reason': 'manual override',
    });
    expect(
      repo.contextLinkSuggestions.map((item) => item.id),
      isNot(contains('ctxlinksug-1')),
    );
  });

  testWidgets('sidebar reviews pending context link suggestions', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    repo.contextLinkSuggestions = [_suggestion('ctxlinksug-1')];
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    expect(find.byKey(const ValueKey('memory_operations_console_panel')),
        findsOneWidget);
    expect(find.text('Q3 roadmap'), findsOneWidget);

    await tester.tap(
      find.byKey(
        const ValueKey('memory_operations_approve_ctxlinksug_1'),
      ),
    );
    await tester.pump();

    expect(repo.reviewedSuggestions, ['ctxlinksug-1:approve']);
    expect(
      repo.reviewedSuggestionReasons['ctxlinksug-1'],
      'approved by user from review queue',
    );
    expect(store.contextLinkSuggestions, isEmpty);
  });

  testWidgets('sidebar opens extraction artifact through file opener service', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    final opener = _FakeDownloadedFileOpener();
    repo.extractions = [
      _job(
        id: 'extract-ready',
        status: 'succeeded',
        artifacts: [_artifact('artifact-ready', 'extract-ready')],
      ),
    ];
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      opener: opener,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_operations_open_button')));
    await tester.pumpAndSettle();
    await tester.tap(
        find.byKey(const ValueKey('asset_extraction_open_artifact_ready')));
    await tester.pump();

    expect(repo.downloadedArtifactIds, ['artifact-ready']);
    expect(opener.requests, hasLength(1));
    expect(opener.requests.single.suggestedName, 'extracted.md');
    expect(opener.requests.single.bytes, [1, 2, 3]);
    expect(opener.requests.single.namespace, 'artifact-ready');
  });

  testWidgets('sidebar reports artifact open failures', (tester) async {
    final repo = _UxFakeChatRepository();
    final opener = _FakeDownloadedFileOpener(throwOnOpen: true);
    repo.extractions = [
      _job(
        id: 'extract-ready',
        status: 'succeeded',
        artifacts: [_artifact('artifact-ready', 'extract-ready')],
      ),
    ];
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshOperationsConsole();
    await _pumpWithStore(
      tester,
      store: store,
      opener: opener,
      child: const Scaffold(
        body: SizedBox(width: 340, height: 620, child: ChatListSidebar()),
      ),
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_operations_open_button')));
    await tester.pumpAndSettle();
    await tester.tap(
        find.byKey(const ValueKey('asset_extraction_open_artifact_ready')));
    await tester.pump();

    expect(
      find.textContaining('Open extraction artifact failed'),
      findsOneWidget,
    );
  });

  testWidgets('sidebar opens saved memory detail with context links', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    repo.captures = [_capture('capture-1')];
    repo.contextLinks = [_link('link-1', sourceId: 'capture-1')];
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshMemoryCaptures();
    await _pumpWithStore(
      tester,
      store: store,
      child: const Scaffold(
        body: SizedBox(width: 360, height: 680, child: ChatListSidebar()),
      ),
    );

    expect(find.byKey(const ValueKey('memory_history_panel')), findsOneWidget);
    expect(find.textContaining('Alex confirmed Q3 rollout'), findsOneWidget);
    expect(find.textContaining('1 files'), findsOneWidget);

    await tester
        .tap(find.byKey(const ValueKey('memory_capture_open_capture_1')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('memory_capture_detail_dialog')),
        findsOneWidget);
    expect(find.text('Saved memory'), findsWidgets);
    expect(find.textContaining('File asset'), findsOneWidget);
    expect(
        find.textContaining('Q3 roadmap - selected by user'), findsOneWidget);
  });

  testWidgets('memory evidence viewer filters files and opens artifacts', (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    final opener = _FakeDownloadedFileOpener();
    final store = ChatStore(repo, null);
    addTearDown(store.dispose);
    addTearDown(repo.close);
    repo.captures = [
      _capture('capture-1', threadId: store.activeChatId),
      _capture('capture-other', threadId: 'other-thread'),
    ];
    repo.extractions = [
      _job(
        id: 'extract-ready',
        status: 'succeeded',
        threadId: store.activeChatId,
        artifacts: [_artifact('artifact-ready', 'extract-ready')],
      ),
      _job(id: 'extract-failed', status: 'failed'),
      _job(id: 'extract-other', status: 'succeeded', threadId: 'other-thread'),
    ];

    await store.refreshMemoryCaptures();
    await store.refreshAssetExtractions();
    await _pumpWithStore(
      tester,
      store: store,
      opener: opener,
      child: const Scaffold(
        body: SizedBox(width: 430, height: 760, child: ChatListSidebar()),
      ),
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_evidence_viewer_button')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('memory_evidence_viewer_dialog')),
        findsOneWidget);
    expect(find.byKey(const ValueKey('memory_evidence_capture_capture_1')),
        findsOneWidget);
    expect(
      find.byKey(const ValueKey('memory_evidence_extraction_extract_ready')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('memory_evidence_capture_capture_other')),
        findsOneWidget);
    expect(
      find.byKey(const ValueKey('memory_evidence_extraction_extract_other')),
      findsOneWidget,
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_evidence_range_thread')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('memory_evidence_capture_capture_1')),
        findsOneWidget);
    expect(find.byKey(const ValueKey('memory_evidence_capture_capture_other')),
        findsNothing);
    expect(
      find.byKey(const ValueKey('memory_evidence_extraction_extract_ready')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('memory_evidence_extraction_extract_other')),
      findsNothing,
    );

    await tester.tap(
        find.byKey(const ValueKey('memory_evidence_artifact_artifact_ready')));
    await tester.pumpAndSettle();
    expect(repo.downloadedArtifactIds, ['artifact-ready']);
    expect(opener.requests.single.namespace, 'artifact-ready');

    await tester
        .tap(find.byKey(const ValueKey('memory_evidence_filter_files')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('memory_evidence_capture_capture_1')),
        findsNothing);
    expect(
      find.byKey(const ValueKey('memory_evidence_extraction_extract_ready')),
      findsOneWidget,
    );

    await tester
        .tap(find.byKey(const ValueKey('memory_evidence_filter_issues')));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('memory_evidence_extraction_extract_failed')),
      findsOneWidget,
    );
    expect(
      find.byKey(const ValueKey('memory_evidence_extraction_extract_ready')),
      findsNothing,
    );

    await tester.tap(
        find.byKey(const ValueKey('memory_evidence_retry_extract_failed')));
    await tester.pumpAndSettle();
    expect(
        store.assetExtractions.any((job) => job.status == 'pending'), isTrue);
    store.dispose();
  });

  testWidgets('store polls pending extraction until it reaches terminal status',
      (
    tester,
  ) async {
    final repo = _UxFakeChatRepository();
    repo.extractions = [_job(id: 'extract-pending', status: 'pending')];
    final store = ChatStore(
      repo,
      null,
      assetExtractionPollInterval: const Duration(milliseconds: 20),
    );
    addTearDown(store.dispose);
    addTearDown(repo.close);

    await store.refreshAssetExtractions();
    expect(store.assetExtractions.single.status, 'pending');
    expect(repo.listExtractionCalls, 1);

    repo.extractions = [
      _job(
        id: 'extract-pending',
        status: 'succeeded',
        artifacts: [_artifact('artifact-ready', 'extract-pending')],
      ),
    ];
    await tester.pump(const Duration(milliseconds: 30));
    await tester.pump();

    expect(store.assetExtractions.single.status, 'succeeded');
    expect(repo.listExtractionCalls, 2);

    await tester.pump(const Duration(milliseconds: 40));
    await tester.pump();

    expect(repo.listExtractionCalls, 2);
  });
}

Future<void> _pumpWithStore(
  WidgetTester tester, {
  required ChatStore store,
  required Widget child,
  DownloadedFileOpener? opener,
}) async {
  await tester.pumpWidget(
    MultiProvider(
      providers: [
        Provider<ChatRepository>.value(value: store.repo),
        Provider<ChatStore>.value(value: store),
        if (opener != null) ...[
          Provider<DownloadedFileOpener>.value(value: opener),
          Provider<OpenExtractionArtifact>(
            create: (_) => OpenExtractionArtifact(
              repo: store.repo,
              opener: opener,
            ),
          ),
        ],
      ],
      child: MaterialApp(
        theme: _testTheme(),
        home: child,
      ),
    ),
  );
}

ThemeData _testTheme() {
  return ThemeData(
    useMaterial3: true,
    colorSchemeSeed: Colors.blue,
    splashFactory: InkRipple.splashFactory,
    extensions: [
      const AppThemeColors(
        userBubbleBg: Color(0xFF1565C0),
        userBubbleFg: Colors.white,
        assistantBubbleBg: Color(0xFFF3F4F6),
        assistantBubbleFg: Color(0xFF111827),
        surfaceBorder: Color(0xFFE5E7EB),
        usageBorder: Color(0xFFFFB74D),
        usageFill: Color(0xFFFFF3E0),
        actionTealBorder: Color(0xFF26A69A),
        actionTealFill: Color(0xFFE0F2F1),
        actionIndigoBorder: Color(0xFF5C6BC0),
        actionIndigoFill: Color(0xFFE8EAF6),
        actionPurpleBorder: Color(0xFF9575CD),
        actionPurpleFill: Color(0xFFF3E5F5),
        actionBlueGreyBorder: Color(0xFF78909C),
        actionBlueGreyFill: Color(0xFFECEFF1),
        actionGreenBorder: Color(0xFF66BB6A),
        actionGreenFill: Color(0xFFE8F5E9),
        actionOrangeBorder: Color(0xFFFFA726),
        actionOrangeFill: Color(0xFFFFF3E0),
      ),
      const AppThemeStyles(
        body: TextStyle(fontSize: 14, height: 1.35),
        bodySmall: TextStyle(fontSize: 12, height: 1.30),
        caption: TextStyle(fontSize: 11, height: 1.25),
        labelSmall: TextStyle(
          fontSize: 10,
          height: 1.20,
          fontWeight: FontWeight.w600,
        ),
      ),
    ],
  );
}

class _UxFakeChatRepository implements ChatRepository {
  final _messages = StreamController<ChatMessage>.broadcast();
  final _usage = StreamController<CostUsage>.broadcast();
  final _running = StreamController<bool>.broadcast();
  final _connection = StreamController<ConnectionStatus>.broadcast();

  String activeMemoryScopeExternalRef = 'default';
  List<AssetExtractionJob> extractions = const <AssetExtractionJob>[];
  List<MemoryCapture> captures = const <MemoryCapture>[];
  List<MemoryContextLink> contextLinks = const <MemoryContextLink>[];
  List<MemoryContextLinkSuggestion> contextLinkSuggestions =
      const <MemoryContextLinkSuggestion>[];
  Object? operationsConsoleError;
  int listExtractionCalls = 0;
  final downloadedArtifactIds = <String>[];
  final createdContextLinks = <Map<String, String>>[];
  final reviewedSuggestions = <String>[];
  final batchReviewedSuggestionIds = <List<String>>[];
  final reviewedSuggestionReasons = <String, String?>{};
  final reviewedSuggestionOverrides = <String, Map<String, String>>{};
  final Map<String, MemoryScope> scopesByRef = {
    'default': _scope('scope-default', 'default', 'Default'),
  };

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
    return true;
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
    scopesByRef[scope.externalRef] = scope;
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
  }) async {
    createdContextLinks.add({
      'sourceType': sourceType,
      'sourceId': sourceId,
      'targetType': targetType,
      'targetId': targetId,
      'relationType': relationType,
      'confidence': confidence,
      'reason': reason,
    });
  }

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
    listExtractionCalls += 1;
    return extractions
        .where((job) => status == null || job.status == status)
        .take(limit)
        .toList(growable: false);
  }

  @override
  Future<AssetExtractionJob> getAssetExtraction(String jobId) async {
    return extractions.firstWhere((job) => job.id == jobId);
  }

  @override
  Future<AssetExtractionJob> retryAssetExtraction(String jobId) async {
    final idx = extractions.indexWhere((job) => job.id == jobId);
    final updated = _job(id: jobId, status: 'pending');
    if (idx >= 0) {
      extractions = [
        ...extractions.take(idx),
        updated,
        ...extractions.skip(idx + 1),
      ];
    }
    return updated;
  }

  @override
  Future<AssetExtractionJob> cancelAssetExtraction(String jobId) async {
    final idx = extractions.indexWhere((job) => job.id == jobId);
    final updated = _job(id: jobId, status: 'canceled');
    if (idx >= 0) {
      extractions = [
        ...extractions.take(idx),
        updated,
        ...extractions.skip(idx + 1),
      ];
    }
    return updated;
  }

  @override
  Future<MemoryOperationsConsole> getOperationsConsole({int limit = 50}) async {
    final error = operationsConsoleError;
    if (error != null) throw error;
    listExtractionCalls += 1;
    return MemoryOperationsConsole(
      generatedAt: DateTime.now(),
      scope: const <String, dynamic>{},
      extractionStatusCounts: _statusCounts(extractions),
      linkSuggestionStatusCounts: _statusCounts(contextLinkSuggestions),
      extractionJobs: extractions.take(limit).toList(growable: false),
      contextLinkSuggestions:
          contextLinkSuggestions.take(limit).toList(growable: false),
      diagnostics: const <String, dynamic>{
        'link_suggestion_explainability': {
          'no_suggestion_note': 'No pending links',
          'no_suggestion_reasons': [
            {
              'code': 'no_visible_same_scope_candidate',
              'label':
                  'No visible same-scope memory matched the source text strongly enough.',
            },
            {
              'code': 'already_linked',
              'label': 'An active link may already exist.',
            },
          ],
        },
      },
    );
  }

  @override
  Future<MemoryBrowserSnapshot> getMemoryBrowser({int limit = 50}) async {
    return MemoryBrowserSnapshot.empty();
  }

  @override
  Future<MemoryBrowserAnchor> createMemoryAnchor({
    required String kind,
    required String label,
    List<String> aliases = const <String>[],
    String? description,
  }) async {
    return MemoryBrowserAnchor.fromMap({
      'id': 'anchor-fake',
      'space_id': 'space-1',
      'memory_scope_id': 'scope-1',
      'kind': kind,
      'normalized_key': label.toLowerCase(),
      'label': label,
      'aliases': aliases,
      'description': description,
      'status': 'active',
      'metadata': <String, dynamic>{},
      'created_at': '2026-06-14T10:00:00Z',
      'updated_at': '2026-06-14T10:00:00Z',
    });
  }

  @override
  Future<MemoryBrowserAnchor> updateMemoryAnchor({
    required String anchorId,
    required String label,
    List<String> aliases = const <String>[],
    String? description,
  }) async {
    return MemoryBrowserAnchor.fromMap({
      'id': anchorId,
      'space_id': 'space-1',
      'memory_scope_id': 'scope-1',
      'kind': 'person',
      'normalized_key': label.toLowerCase(),
      'label': label,
      'aliases': aliases,
      'description': description,
      'status': 'active',
      'metadata': <String, dynamic>{},
      'created_at': '2026-06-14T10:00:00Z',
      'updated_at': '2026-06-14T10:05:00Z',
    });
  }

  @override
  Future<void> deleteMemoryAnchor({
    required String anchorId,
    String reason = 'manual delete',
  }) async {}

  @override
  Future<List<MemoryAnchorMergeSuggestion>> listMemoryAnchorMergeSuggestions({
    int limit = 50,
  }) async {
    return const <MemoryAnchorMergeSuggestion>[];
  }

  @override
  Future<MemoryBrowserAnchor> mergeMemoryAnchors({
    required String sourceAnchorId,
    required String targetAnchorId,
    required String reason,
  }) async {
    return MemoryBrowserAnchor.fromMap({
      'id': targetAnchorId,
      'space_id': 'space-1',
      'memory_scope_id': 'scope-1',
      'kind': 'person',
      'normalized_key': targetAnchorId,
      'label': targetAnchorId,
      'aliases': const <String>[],
      'description': null,
      'status': 'active',
      'metadata': <String, dynamic>{},
      'created_at': '2026-06-14T10:00:00Z',
      'updated_at': '2026-06-14T10:05:00Z',
    });
  }

  @override
  Future<MemoryBrowserAnchor> splitMemoryAnchor({
    required String anchorId,
    required String alias,
    String? newLabel,
    String reason = 'manual split',
  }) async {
    return MemoryBrowserAnchor.fromMap({
      'id': 'anchor-split',
      'space_id': 'space-1',
      'memory_scope_id': 'scope-1',
      'kind': 'person',
      'normalized_key': (newLabel ?? alias).toLowerCase(),
      'label': newLabel ?? alias,
      'aliases': const <String>[],
      'description': null,
      'status': 'active',
      'metadata': <String, dynamic>{},
      'created_at': '2026-06-14T10:00:00Z',
      'updated_at': '2026-06-14T10:05:00Z',
    });
  }

  @override
  Future<void> backfillMemoryAnchors({int limitPerSource = 100}) async {}

  @override
  Future<List<int>> downloadExtractionArtifact(String artifactId) async {
    downloadedArtifactIds.add(artifactId);
    return <int>[1, 2, 3];
  }

  @override
  Future<List<DocumentChunk>> listDocumentChunks(String documentId) async {
    return const <DocumentChunk>[];
  }

  @override
  Future<List<MemoryCapture>> listMemoryCaptures({int limit = 50}) async {
    return captures.take(limit).toList(growable: false);
  }

  @override
  Future<List<MemoryContextLink>> listContextLinks({
    required String sourceType,
    required String sourceId,
    int limit = 50,
  }) async {
    return contextLinks
        .where(
          (link) => link.sourceType == sourceType && link.sourceId == sourceId,
        )
        .take(limit)
        .toList(growable: false);
  }

  @override
  Future<List<MemoryContextLinkSuggestion>> listContextLinkSuggestions({
    String status = 'pending',
    int limit = 50,
  }) async {
    return contextLinkSuggestions
        .where((item) => item.status == status)
        .take(limit)
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
    reviewedSuggestions.add('$suggestionId:$action');
    reviewedSuggestionReasons[suggestionId] = reason;
    reviewedSuggestionOverrides[suggestionId] = {
      if (targetType != null) 'target_type': targetType,
      if (targetId != null) 'target_id': targetId,
      if (relationType != null) 'relation_type': relationType,
      if (confidence != null) 'confidence': confidence,
      if (linkReason != null) 'link_reason': linkReason,
    };
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
      'target_type': targetType ?? suggestion.targetType,
      'target_id': targetId ?? suggestion.targetId,
      'relation_type': relationType ?? suggestion.relationType,
      'confidence': confidence ?? suggestion.confidence,
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

  @override
  Future<List<MemoryContextLinkSuggestion>> reviewContextLinkSuggestionsBatch({
    required List<String> suggestionIds,
    required String action,
    String? reason,
  }) async {
    batchReviewedSuggestionIds.add(List<String>.from(suggestionIds));
    final reviewed = <MemoryContextLinkSuggestion>[];
    for (final suggestionId in suggestionIds) {
      reviewed.add(
        await reviewContextLinkSuggestion(
          suggestionId: suggestionId,
          action: action,
          reason: reason,
        ),
      );
    }
    return reviewed;
  }
}

class _OpenRequest {
  final String suggestedName;
  final List<int> bytes;
  final String? namespace;

  const _OpenRequest({
    required this.suggestedName,
    required this.bytes,
    required this.namespace,
  });
}

class _FakeDownloadedFileOpener implements DownloadedFileOpener {
  final bool throwOnOpen;
  final requests = <_OpenRequest>[];

  _FakeDownloadedFileOpener({this.throwOnOpen = false});

  @override
  Future<OpenedDownloadedFile> openBytes({
    required String suggestedName,
    required List<int> bytes,
    String? namespace,
  }) async {
    requests.add(
      _OpenRequest(
        suggestedName: suggestedName,
        bytes: List<int>.of(bytes),
        namespace: namespace,
      ),
    );
    if (throwOnOpen) {
      throw StateError('open failed');
    }
    return const OpenedDownloadedFile(path: '/tmp/opened');
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

MemoryCapture _capture(String id, {String threadId = 'thread-1'}) {
  final now = DateTime.now();
  return MemoryCapture.fromMap({
    'id': id,
    'space_id': 'space-1',
    'memory_scope_id': 'scope-default',
    'thread_id': threadId,
    'source_agent': 'memo-stack-frontend',
    'source_kind': 'manual',
    'event_type': 'QuickCapture',
    'actor_role': 'user',
    'text_preview': 'Alex confirmed Q3 rollout after the product review.',
    'status': 'accepted',
    'consolidation_status': 'pending',
    'trust_level': 'medium',
    'source_authority': 'user_statement',
    'sensitivity': 'medium',
    'data_classification': 'internal',
    'evidence_refs': [
      {'source_type': 'asset', 'source_id': 'asset-1'},
    ],
    'metadata': {
      'asset_ids': ['asset-1'],
    },
    'created_at': now.toIso8601String(),
    'updated_at': now.toIso8601String(),
    'occurred_at': now.toIso8601String(),
  });
}

MemoryContextLink _link(String id, {required String sourceId}) {
  final now = DateTime.now();
  return MemoryContextLink.fromMap({
    'id': id,
    'space_id': 'space-1',
    'memory_scope_id': 'scope-default',
    'source_type': 'capture',
    'source_id': sourceId,
    'target_type': 'thread',
    'target_id': 'thread-1',
    'relation_type': 'related_to',
    'confidence': 'high',
    'reason': 'selected by user',
    'status': 'active',
    'metadata': {'target_label': 'Q3 roadmap'},
    'created_at': now.toIso8601String(),
    'updated_at': now.toIso8601String(),
  });
}

MemoryContextLinkSuggestion _suggestion(
  String id, {
  String status = 'pending',
  String targetType = 'fact',
  String targetId = 'fact-1',
  Map<String, dynamic>? metadata,
  String? reviewReason,
  DateTime? reviewedAt,
}) {
  final now = DateTime.now();
  return MemoryContextLinkSuggestion(
    id: id,
    spaceId: 'space-1',
    memoryScopeId: 'scope-default',
    sourceType: 'capture',
    sourceId: 'capture-1',
    targetType: targetType,
    targetId: targetId,
    relationType: 'related_to',
    confidence: 'high',
    reason: 'matching text',
    score: 88,
    status: status,
    metadata: metadata ??
        const {
          'target_label': 'Q3 roadmap',
          'target_preview': 'Alex confirmed Q3 rollout.',
          'matched_terms': ['alex', 'q3'],
        },
    createdAt: now,
    updatedAt: now,
    reviewedAt: reviewedAt,
    reviewReason: reviewReason,
  );
}

AssetExtractionJob _job({
  required String id,
  required String status,
  List<ExtractionArtifact> artifacts = const <ExtractionArtifact>[],
  String? threadId,
  Map<String, dynamic> metadata = const <String, dynamic>{},
}) {
  final now = DateTime.now();
  return AssetExtractionJob(
    id: id,
    assetId: 'asset-$id',
    spaceId: 'space-1',
    memoryScopeId: 'scope-default',
    threadId: threadId,
    parserProfile: 'standard_local',
    parserConfigHash: 'hash',
    sourceSha256Hex: 'sha',
    status: status,
    attemptCount: 1,
    safeErrorCode: status == 'failed' ? 'asset_extraction.failed' : null,
    safeErrorMessage: status == 'failed' ? 'Parser failed' : null,
    parserName: 'simple_text',
    parserVersion: '1',
    modelVersion: null,
    resultDocumentIds: status == 'succeeded' ? const ['doc-1'] : const [],
    artifacts: artifacts,
    metadata: metadata,
    progress: ExtractionProgress.fromMap(
      const <String, dynamic>{},
      status: status,
    ),
    usage: ExtractionUsage.fromMap(const <String, dynamic>{}),
    createdAt: now,
    updatedAt: now,
    startedAt: null,
    finishedAt: status == 'pending' ? null : now,
  );
}

Map<String, int> _statusCounts(Iterable<dynamic> items) {
  final counts = <String, int>{};
  for (final item in items) {
    final status = item.status.toString();
    counts[status] = (counts[status] ?? 0) + 1;
  }
  return counts;
}

ExtractionArtifact _artifact(String id, String jobId) {
  return ExtractionArtifact(
    id: id,
    jobId: jobId,
    assetId: 'asset-$jobId',
    artifactType: 'markdown',
    storageBackend: 'local',
    storageKey: 'artifact.md',
    sha256Hex: 'sha',
    byteSize: 12,
    metadata: const {'filename': 'extracted.md'},
    createdAt: DateTime.now(),
  );
}

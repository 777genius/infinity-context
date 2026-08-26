import { HttpClient, type InfinityContextClientOptions } from "./client.js";
import { AnchorsClient } from "./resources/anchors.js";
import { AssetsClient } from "./resources/assets.js";
import { CapturesClient } from "./resources/captures.js";
import { ContextClient } from "./resources/context.js";
import { CodeRepositoriesClient } from "./resources/code-repositories.js";
import { DerivedEvidenceClient } from "./resources/derived-evidence.js";
import { FactLifecycleClient } from "./resources/fact-lifecycle.js";
import { MemoryComparisonRunsClient } from "./resources/memory-comparison-runs.js";
import { ContextLinksClient } from "./resources/context-links.js";
import { DiagnosticsClient } from "./resources/diagnostics.js";
import { DocumentsClient } from "./resources/documents.js";
import { ExportsClient } from "./resources/exports.js";
import { FactsClient } from "./resources/facts.js";
import { ReadModelsClient } from "./resources/read-models.js";
import { SpacesClient } from "./resources/spaces.js";
import { SuggestionsClient } from "./resources/suggestions.js";
import { SystemClient } from "./resources/system.js";
import { ThreadMemoryClient } from "./resources/thread-memory.js";
import { UsageClient } from "./resources/usage.js";
import { UsersClient } from "./resources/users.js";
import { MemoryWorkflows } from "./workflows/memory.js";

export class InfinityContextClient {
  readonly system: SystemClient;
  readonly spaces: SpacesClient;
  readonly facts: FactsClient;
  readonly documents: DocumentsClient;
  readonly context: ContextClient;
  readonly codeRepositories: CodeRepositoriesClient;
  readonly derivedEvidence: DerivedEvidenceClient;
  readonly factLifecycle: FactLifecycleClient;
  readonly memoryComparisonRuns: MemoryComparisonRunsClient;
  readonly contextLinks: ContextLinksClient;
  readonly suggestions: SuggestionsClient;
  readonly assets: AssetsClient;
  readonly captures: CapturesClient;
  readonly anchors: AnchorsClient;
  readonly users: UsersClient;
  readonly diagnostics: DiagnosticsClient;
  readonly exports: ExportsClient;
  readonly readModels: ReadModelsClient;
  readonly threadMemory: ThreadMemoryClient;
  readonly usage: UsageClient;
  readonly workflows: MemoryWorkflows;

  constructor(options: InfinityContextClientOptions = {}) {
    const http = new HttpClient(options);
    this.system = new SystemClient(http);
    this.spaces = new SpacesClient(http);
    this.facts = new FactsClient(http);
    this.documents = new DocumentsClient(http);
    this.context = new ContextClient(http);
    this.codeRepositories = new CodeRepositoriesClient(http);
    this.derivedEvidence = new DerivedEvidenceClient(http);
    this.factLifecycle = new FactLifecycleClient(http);
    this.memoryComparisonRuns = new MemoryComparisonRunsClient(http);
    this.contextLinks = new ContextLinksClient(http);
    this.suggestions = new SuggestionsClient(http);
    this.assets = new AssetsClient(http);
    this.captures = new CapturesClient(http);
    this.anchors = new AnchorsClient(http);
    this.users = new UsersClient(http);
    this.diagnostics = new DiagnosticsClient(http);
    this.exports = new ExportsClient(http);
    this.readModels = new ReadModelsClient(http);
    this.threadMemory = new ThreadMemoryClient(http);
    this.usage = new UsageClient(http);
    this.workflows = new MemoryWorkflows({
      anchors: this.anchors,
      assets: this.assets,
      captures: this.captures,
      context: this.context,
      contextLinks: this.contextLinks,
      diagnostics: this.diagnostics,
      documents: this.documents,
      exports: this.exports,
      facts: this.facts,
      readModels: this.readModels,
      spaces: this.spaces,
      suggestions: this.suggestions,
      system: this.system,
      usage: this.usage,
      users: this.users,
    });
  }
}

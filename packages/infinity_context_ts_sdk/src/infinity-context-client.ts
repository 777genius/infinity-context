import { HttpClient, type InfinityContextClientOptions } from "./client.js";
import { AnchorsClient } from "./resources/anchors.js";
import { AssetsClient } from "./resources/assets.js";
import { CapturesClient } from "./resources/captures.js";
import { ContextClient } from "./resources/context.js";
import { ContextLinksClient } from "./resources/context-links.js";
import { DiagnosticsClient } from "./resources/diagnostics.js";
import { DocumentsClient } from "./resources/documents.js";
import { ExportsClient } from "./resources/exports.js";
import { FactsClient } from "./resources/facts.js";
import { ReadModelsClient } from "./resources/read-models.js";
import { SpacesClient } from "./resources/spaces.js";
import { SuggestionsClient } from "./resources/suggestions.js";
import { SystemClient } from "./resources/system.js";
import { UsersClient } from "./resources/users.js";

export class InfinityContextClient {
  readonly system: SystemClient;
  readonly spaces: SpacesClient;
  readonly facts: FactsClient;
  readonly documents: DocumentsClient;
  readonly context: ContextClient;
  readonly contextLinks: ContextLinksClient;
  readonly suggestions: SuggestionsClient;
  readonly assets: AssetsClient;
  readonly captures: CapturesClient;
  readonly anchors: AnchorsClient;
  readonly users: UsersClient;
  readonly diagnostics: DiagnosticsClient;
  readonly exports: ExportsClient;
  readonly readModels: ReadModelsClient;

  constructor(options: InfinityContextClientOptions = {}) {
    const http = new HttpClient(options);
    this.system = new SystemClient(http);
    this.spaces = new SpacesClient(http);
    this.facts = new FactsClient(http);
    this.documents = new DocumentsClient(http);
    this.context = new ContextClient(http);
    this.contextLinks = new ContextLinksClient(http);
    this.suggestions = new SuggestionsClient(http);
    this.assets = new AssetsClient(http);
    this.captures = new CapturesClient(http);
    this.anchors = new AnchorsClient(http);
    this.users = new UsersClient(http);
    this.diagnostics = new DiagnosticsClient(http);
    this.exports = new ExportsClient(http);
    this.readModels = new ReadModelsClient(http);
  }
}

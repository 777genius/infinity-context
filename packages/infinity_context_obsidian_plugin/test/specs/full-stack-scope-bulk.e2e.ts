import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import { browser } from "@wdio/globals";

const repoRoot = path.resolve("../../");
const realCliPath = path.resolve("test/fixtures/real-infinity-context-obsidian.cjs");
const token = "wdio-full-e2e-token";
const spaceSlug = "wdio-scope-bulk";
const memoryScopeExternalRef = "default";
const otherSpaceSlug = "wdio-other-scope-bulk";
const otherMemoryScopeExternalRef = "other-memory_scope";
const sameSpaceOtherMemoryScopeRef = "hidden-memory_scope";
const rootFolder = "Infinity Context";
const scopedRoot = path.join(
  rootFolder,
  "spaces",
  spaceSlug,
  "memory_scopes",
  memoryScopeExternalRef,
);
const otherScopeRoot = path.join(
  rootFolder,
  "spaces",
  otherSpaceSlug,
  "memory_scopes",
  otherMemoryScopeExternalRef,
);
const sameSpaceOtherMemoryScopeRoot = path.join(
  rootFolder,
  "spaces",
  spaceSlug,
  "memory_scopes",
  sameSpaceOtherMemoryScopeRef,
);
const textStart = "<!-- infinity-context-managed:fact-text:start -->";
const textEnd = "<!-- infinity-context-managed:fact-text:end -->";

describe("Infinity Context multi-scope bulk Obsidian E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "infinity-context-wdio-scope-bulk-"));
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    server = startInfinityContextServer(path.join(tempDir, "memory.db"), port);
    await waitForHealth(baseUrl);
  });

  afterEach(function () {
    server?.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  it("keeps a large vault isolated to the configured project and memory_scope", async function () {
    const visibleFacts = await createFacts(baseUrl, {
      count: 12,
      textPrefix: "Obsidian WDIO bulk visible fact",
      sourcePrefix: "wdio-bulk-visible",
      space: spaceSlug,
      memory_scope: memoryScopeExternalRef,
    });
    const hiddenOtherSpaceFacts = await createFacts(baseUrl, {
      count: 4,
      textPrefix: "Obsidian WDIO hidden other project fact",
      sourcePrefix: "wdio-bulk-hidden-other-space",
      space: otherSpaceSlug,
      memory_scope: otherMemoryScopeExternalRef,
    });
    const hiddenOtherMemoryScopeFact = await createFact(baseUrl, {
      text: "Obsidian WDIO hidden same project other memory_scope fact.",
      sourceId: "wdio-bulk-hidden-other-memory_scope",
      space: spaceSlug,
      memory_scope: sameSpaceOtherMemoryScopeRef,
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);

    const currentInboxMarker = "WDIO bulk current scoped inbox marker";
    const secondInboxMarker = "WDIO bulk second current scoped inbox marker";
    const hiddenOtherSpaceInbox = "WDIO bulk hidden other project inbox marker";
    const hiddenOtherMemoryScopeInbox = "WDIO bulk hidden other memory_scope inbox marker";
    const foreignGeneratedMarkdown = [
      "# Foreign generated note",
      "",
      "This pre-existing note belongs to another Infinity Context project.",
      hiddenOtherSpaceInbox,
      "",
    ].join("\n");
    writeVaultFile(
      vaultPath,
      path.join(otherScopeRoot, "generated", "facts", "foreign-owned.md"),
      foreignGeneratedMarkdown,
    );
    writeVaultFile(
      vaultPath,
      path.join(otherScopeRoot, "inbox", "foreign-inbox.md"),
      hiddenOtherSpaceInbox,
    );
    writeVaultFile(
      vaultPath,
      path.join(sameSpaceOtherMemoryScopeRoot, "inbox", "foreign-memory_scope-inbox.md"),
      hiddenOtherMemoryScopeInbox,
    );

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    writeVaultFile(vaultPath, path.join(scopedRoot, "inbox", "bulk-current.md"), currentInboxMarker);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, currentInboxMarker, 1);

    assert.equal(factFiles(vaultPath).length, visibleFacts.length);
    for (const [index, fact] of visibleFacts.entries()) {
      const markdown = fs.readFileSync(factFileForId(vaultPath, fact.id), "utf8");
      assert.match(markdown, new RegExp(`Obsidian WDIO bulk visible fact ${index + 1}`));
      assert.match(markdown, /infinity_context_version: 1/);
    }
    assertNoExportedText(vaultPath, "Obsidian WDIO hidden other project fact");
    assertNoExportedText(vaultPath, "Obsidian WDIO hidden same project other memory_scope fact");
    assert.equal(
      readVaultFile(vaultPath, path.join(otherScopeRoot, "generated", "facts", "foreign-owned.md")),
      foreignGeneratedMarkdown,
    );
    assert.equal(markdownFiles(vaultPath, path.join(otherScopeRoot, "generated", "facts")).length, 1);
    assert.equal(conflictFiles(vaultPath).length, 0);

    assert.equal((await suggestionsContaining(baseUrl, currentInboxMarker)).length, 1);
    assert.equal(
      (
        await suggestionsContaining(baseUrl, hiddenOtherSpaceInbox, {
          space: spaceSlug,
          memory_scope: memoryScopeExternalRef,
        })
      ).length,
      0,
    );
    assert.equal(
      (
        await suggestionsContaining(baseUrl, hiddenOtherSpaceInbox, {
          space: otherSpaceSlug,
          memory_scope: otherMemoryScopeExternalRef,
        })
      ).length,
      0,
    );
    assert.equal(
      (
        await suggestionsContaining(baseUrl, hiddenOtherMemoryScopeInbox, {
          space: spaceSlug,
          memory_scope: sameSpaceOtherMemoryScopeRef,
        })
      ).length,
      0,
    );

    const localUpdate = "Obsidian WDIO bulk local update applied only to visible scope.";
    replaceManagedText(factFileForId(vaultPath, visibleFacts[5].id), localUpdate);
    writeVaultFile(vaultPath, path.join(scopedRoot, "inbox", "bulk-second.md"), secondInboxMarker);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForBackendFactText(baseUrl, visibleFacts[5].id, localUpdate);
    await waitForSuggestionsContaining(baseUrl, secondInboxMarker, 1);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await sleep(300);

    const updatedFact = await getFact(baseUrl, visibleFacts[5].id);
    assert.equal(updatedFact.version, 2);
    assert.equal(updatedFact.text, localUpdate);
    assert.equal((await suggestionsContaining(baseUrl, currentInboxMarker)).length, 1);
    assert.equal((await suggestionsContaining(baseUrl, secondInboxMarker)).length, 1);
    assert.equal(factFiles(vaultPath).length, visibleFacts.length);
    assert.equal(conflictFiles(vaultPath).length, 0);
    assert.match(fs.readFileSync(factFileForId(vaultPath, visibleFacts[5].id), "utf8"), /infinity_context_version: 2/);
    assert.equal(
      readVaultFile(vaultPath, path.join(otherScopeRoot, "generated", "facts", "foreign-owned.md")),
      foreignGeneratedMarkdown,
    );
    for (const fact of hiddenOtherSpaceFacts) {
      assert.match((await getFact(baseUrl, fact.id)).text, /hidden other project fact/);
    }
    assert.equal(
      (await getFact(baseUrl, hiddenOtherMemoryScopeFact.id)).text,
      "Obsidian WDIO hidden same project other memory_scope fact.",
    );

    await browser.executeObsidianCommand("infinity-context:open-inbox");
    assert.equal(await activeFilePath(), posixPath(path.join(scopedRoot, "inbox", "README.md")));

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync", "sync", "sync"]);
    assert.ok(calls.every((call) => call.status === 0));
    assert.ok(calls.every((call) => call.args.includes("--space")));
    assert.ok(calls.every((call) => call.args.includes(spaceSlug)));
    assert.ok(calls.every((call) => call.args.includes("--memory_scope")));
    assert.ok(calls.every((call) => call.args.includes(memoryScopeExternalRef)));
    assert.ok(!calls.some((call) => call.args.includes(otherSpaceSlug)));
    assert.ok(!calls.some((call) => call.args.includes(sameSpaceOtherMemoryScopeRef)));
  });
});

async function resetVaultAndConfigure(apiUrl: string): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nScope bulk E2E vault.\n",
  });
  const vaultPath = obsidianPage.getVaultPath();
  await configurePlugin(vaultPath, apiUrl);
  return vaultPath;
}

async function configurePlugin(vaultPath: string, apiUrl: string): Promise<void> {
  const settings = {
    apiUrl,
    token,
    cliPath: realCliPath,
    vaultPathOverride: vaultPath,
    spaceSlug,
    memoryScopeExternalRef,
    rootFolder,
    layoutVersion: "v2",
    applyImportOnSync: true,
    commandTimeoutMs: 20000,
  };
  writeVaultFile(
    vaultPath,
    path.join(".obsidian", "plugins", "infinity-context", "data.json"),
    JSON.stringify(settings, null, 2),
  );
  await browser.executeObsidian(
    async ({ plugins }, persistedSettings) => {
      const plugin = plugins.infinityContext as any;
      Object.assign(plugin.settings, persistedSettings);
      await plugin.saveSettings();
    },
    settings,
  );
}

function startInfinityContextServer(dbPath: string, port: number): ChildProcess {
  const code = `
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app
import uvicorn

app = create_app(Settings(
    deploy_profile=DeployProfile.TEST,
    database_url="sqlite+aiosqlite:///${dbPath}",
    auto_create_schema=True,
    host="127.0.0.1",
    port=${port},
    service_token="${token}",
    qdrant_enabled=False,
    graphiti_enabled=False,
    embeddings_enabled=False,
    ui_enabled=False,
))
uvicorn.run(app, host="127.0.0.1", port=${port}, log_level="warning")
`;
  return spawn(path.join(repoRoot, ".venv/bin/python"), ["-c", code], {
    cwd: repoRoot,
    env: {
      ...process.env,
      PYTHONPATH: pythonpath(),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
}

async function freePort(): Promise<number> {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (typeof address !== "object" || address === null) {
        reject(new Error("Could not allocate free port"));
        return;
      }
      const port = address.port;
      server.close(() => resolve(port));
    });
  });
}

async function waitForHealth(apiUrl: string): Promise<void> {
  await waitUntil(async () => {
    try {
      const response = await requestJson("GET", `${apiUrl}/v1/health`);
      return response.status === 200;
    } catch (_error) {
      return false;
    }
  }, "Infinity Context server did not become healthy");
}

async function createFacts(
  apiUrl: string,
  {
    count,
    textPrefix,
    sourcePrefix,
    space,
    memory_scope,
  }: {
    count: number;
    textPrefix: string;
    sourcePrefix: string;
    space: string;
    memory_scope: string;
  },
): Promise<Record<string, any>[]> {
  const facts: Record<string, any>[] = [];
  for (let index = 0; index < count; index += 1) {
    const number = index + 1;
    facts.push(
      await createFact(apiUrl, {
        text: `${textPrefix} ${number}.`,
        sourceId: `${sourcePrefix}-${number}`,
        space,
        memory_scope,
      }),
    );
  }
  return facts;
}

async function createFact(
  apiUrl: string,
  {
    text,
    sourceId,
    space,
    memory_scope,
  }: {
    text: string;
    sourceId: string;
    space: string;
    memory_scope: string;
  },
): Promise<Record<string, any>> {
  const response = await requestJson("POST", `${apiUrl}/v1/facts`, {
    space_slug: space,
    memory_scope_external_ref: memory_scope,
    text,
    kind: "note",
    source_refs: [
      {
        source_type: "manual",
        source_id: sourceId,
        quote_preview: text,
      },
    ],
  });
  assert.equal(response.status, 201);
  return response.body.data;
}

async function getFact(apiUrl: string, factId: string): Promise<Record<string, any>> {
  const response = await requestJson("GET", `${apiUrl}/v1/facts/${factId}`);
  assert.equal(response.status, 200);
  return response.body.data;
}

async function waitForBackendFactText(
  apiUrl: string,
  factId: string,
  expectedText: string,
): Promise<void> {
  await waitUntil(async () => {
    const fact = await getFact(apiUrl, factId);
    return fact.text === expectedText;
  }, `Backend fact did not reach expected text: ${expectedText}`);
}

async function waitForSuggestionsContaining(
  apiUrl: string,
  marker: string,
  count: number,
): Promise<void> {
  await waitUntil(
    async () => (await suggestionsContaining(apiUrl, marker)).length >= count,
    "Suggestion was not created",
  );
}

async function suggestionsContaining(
  apiUrl: string,
  marker: string,
  scope: { space: string; memory_scope: string } = {
    space: spaceSlug,
    memory_scope: memoryScopeExternalRef,
  },
): Promise<Record<string, any>[]> {
  const query = new URLSearchParams({
    space_slug: scope.space,
    memory_scope_external_ref: scope.memory_scope,
    status: "pending",
  });
  const response = await requestJson("GET", `${apiUrl}/v1/suggestions?${query.toString()}`);
  assert.equal(response.status, 200);
  return response.body.data.filter((item: Record<string, any>) =>
    String(item.candidate_text).includes(marker),
  );
}

async function requestJson(
  method: "GET" | "POST",
  url: string,
  body?: Record<string, any>,
): Promise<{ status: number; body: any }> {
  return await new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const requestBody = body ? JSON.stringify(body) : undefined;
    const request = http.request(
      {
        method,
        hostname: parsed.hostname,
        port: parsed.port,
        path: `${parsed.pathname}${parsed.search}`,
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/json",
          ...(requestBody
            ? { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(requestBody) }
            : {}),
        },
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
        response.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          resolve({
            status: response.statusCode ?? 0,
            body: text ? JSON.parse(text) : {},
          });
        });
      },
    );
    request.on("error", reject);
    if (requestBody) {
      request.write(requestBody);
    }
    request.end();
  });
}

async function waitForCliCalls(vaultPath: string, count: number): Promise<void> {
  await browser.waitUntil(() => readCliCalls(vaultPath).length >= count, {
    timeout: 20000,
    timeoutMsg: `Expected ${count} connector CLI calls`,
  });
}

async function waitForPluginIdle(): Promise<void> {
  await browser.waitUntil(async () => (await infinityContextSnapshot()).busyLabel === "", {
    timeout: 20000,
    timeoutMsg: "Infinity Context plugin did not become idle",
  });
}

async function infinityContextSnapshot(): Promise<any> {
  return await browser.executeObsidian(({ plugins }) => {
    return (plugins.infinityContext as any).snapshot();
  });
}

async function activeFilePath(): Promise<string> {
  return await browser.executeObsidian(({ app }) => app.workspace.getActiveFile()?.path ?? "");
}

async function waitUntil(check: () => Promise<boolean>, message: string): Promise<void> {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (await check()) {
      return;
    }
    await sleep(150);
  }
  throw new Error(message);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function factFiles(vaultPath: string): string[] {
  return markdownFiles(vaultPath, path.join(scopedRoot, "generated", "facts"));
}

function factFileForId(vaultPath: string, factId: string): string {
  const files = factFiles(vaultPath).filter((filePath) =>
    fs.readFileSync(filePath, "utf8").includes(`infinity_context_id: ${factId}`),
  );
  assert.equal(files.length, 1);
  return files[0];
}

function conflictFiles(vaultPath: string): string[] {
  return markdownFiles(vaultPath, path.join(scopedRoot, "conflicts")).filter(
    (filePath) => path.basename(filePath) !== "README.md",
  );
}

function markdownFiles(vaultPath: string, relativeDir: string): string[] {
  const absoluteDir = path.join(vaultPath, relativeDir);
  if (!fs.existsSync(absoluteDir)) {
    return [];
  }
  return fs
    .readdirSync(absoluteDir)
    .filter((name) => name.endsWith(".md") && !name.startsWith("."))
    .map((name) => path.join(absoluteDir, name))
    .sort();
}

function assertNoExportedText(vaultPath: string, text: string): void {
  for (const filePath of factFiles(vaultPath)) {
    assert.doesNotMatch(fs.readFileSync(filePath, "utf8"), new RegExp(text));
  }
}

function replaceManagedText(filePath: string, text: string): void {
  const old = fs.readFileSync(filePath, "utf8");
  const start = old.indexOf(textStart) + textStart.length;
  const end = old.indexOf(textEnd);
  assert.ok(start >= textStart.length);
  assert.ok(end > start);
  fs.writeFileSync(filePath, `${old.slice(0, start)}\n${text}\n${old.slice(end)}`, "utf8");
}

function readVaultFile(vaultPath: string, relativePath: string): string {
  return fs.readFileSync(path.join(vaultPath, relativePath), "utf8");
}

function writeVaultFile(vaultPath: string, relativePath: string, content: string): void {
  const target = path.join(vaultPath, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content, "utf8");
}

function readCliCalls(vaultPath: string): Array<{ command: string; args: string[]; status: number }> {
  const logPath = path.join(vaultPath, ".infinity-context/real-plugin-cli-calls.jsonl");
  if (!fs.existsSync(logPath)) {
    return [];
  }
  return fs
    .readFileSync(logPath, "utf8")
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function posixPath(filePath: string): string {
  return filePath.split(path.sep).join("/");
}

function pythonpath(): string {
  return [
    "packages/infinity_context_core",
    "packages/infinity_context_adapters",
    "packages/infinity_context_server",
    "packages/infinity_context_benchmarks",
    "packages/infinity_context_sdk",
    "packages/infinity_context_obsidian",
  ]
    .map((relativePath) => path.join(repoRoot, relativePath))
    .join(path.delimiter);
}

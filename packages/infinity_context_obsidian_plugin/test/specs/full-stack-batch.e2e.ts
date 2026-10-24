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
const spaceSlug = "wdio-full-e2e";
const memoryScopeExternalRef = "default";
const rootFolder = "Infinity Context";
const scopedRoot = path.join(
  rootFolder,
  "spaces",
  spaceSlug,
  "memory_scopes",
  memoryScopeExternalRef,
);
const textStart = "<!-- infinity-context-managed:fact-text:start -->";
const textEnd = "<!-- infinity-context-managed:fact-text:end -->";

describe("Infinity Context batch sync E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "infinity-context-wdio-batch-"));
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    server = startInfinityContextServer(path.join(tempDir, "memory.db"), port);
    await waitForHealth(baseUrl);
  });

  afterEach(function () {
    server?.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  it("syncs backend facts, managed edits, and inbox notes idempotently", async function () {
    const facts = await Promise.all(
      Array.from({ length: 5 }, async (_item, index) => {
        const number = index + 1;
        return await createFact(baseUrl, {
          text: `Obsidian WDIO batch exported fact ${number}.`,
          sourceId: `wdio-batch-export-${number}`,
        });
      }),
    );
    const vaultPath = await resetVaultAndConfigure(baseUrl);

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 2);

    assert.equal(factFiles(vaultPath).length, 5);
    for (const [index, fact] of facts.entries()) {
      const markdown = fs.readFileSync(factFileForId(vaultPath, fact.id), "utf8");
      assert.match(markdown, new RegExp(`Obsidian WDIO batch exported fact ${index + 1}`));
      assert.match(markdown, /infinity_context_version: 1/);
    }

    const firstUpdate = "Obsidian WDIO batch local edit one applied.";
    const secondUpdate = "Obsidian WDIO batch local edit two applied.";
    replaceManagedText(factFileForId(vaultPath, facts[1].id), firstUpdate);
    replaceManagedText(factFileForId(vaultPath, facts[3].id), secondUpdate);
    const inboxOne = "WDIO batch inbox marker one";
    const inboxTwo = "WDIO batch inbox marker two";
    writeVaultFile(vaultPath, path.join(scopedRoot, "inbox", "batch-one.md"), inboxOne);
    writeVaultFile(vaultPath, path.join(scopedRoot, "inbox", "batch-two.md"), inboxTwo);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForBackendFactText(baseUrl, facts[1].id, firstUpdate);
    await waitForBackendFactText(baseUrl, facts[3].id, secondUpdate);
    await waitForSuggestionsContaining(baseUrl, inboxOne, 1);
    await waitForSuggestionsContaining(baseUrl, inboxTwo, 1);

    let calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 0);
    assert.equal(conflictFiles(vaultPath).length, 0);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await sleep(300);

    calls = readCliCalls(vaultPath);
    assert.deepEqual(
      calls.map((call) => call.command),
      ["connect", "sync", "sync", "sync"],
    );
    assert.ok(calls.every((call) => call.status === 0));
    assert.equal(factFiles(vaultPath).length, 5);
    assert.equal((await suggestionsContaining(baseUrl, inboxOne)).length, 1);
    assert.equal((await suggestionsContaining(baseUrl, inboxTwo)).length, 1);
    assert.equal(conflictFiles(vaultPath).length, 0);

    const firstUpdatedMarkdown = fs.readFileSync(factFileForId(vaultPath, facts[1].id), "utf8");
    const secondUpdatedMarkdown = fs.readFileSync(factFileForId(vaultPath, facts[3].id), "utf8");
    const untouchedMarkdown = fs.readFileSync(factFileForId(vaultPath, facts[0].id), "utf8");
    assert.match(firstUpdatedMarkdown, new RegExp(firstUpdate));
    assert.match(firstUpdatedMarkdown, /infinity_context_version: 2/);
    assert.match(secondUpdatedMarkdown, new RegExp(secondUpdate));
    assert.match(secondUpdatedMarkdown, /infinity_context_version: 2/);
    assert.match(untouchedMarkdown, /Obsidian WDIO batch exported fact 1/);
    assert.match(untouchedMarkdown, /infinity_context_version: 1/);
  });

  it("keeps clean vault and inbox suggestions idempotent after local sync state is lost", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO state loss exported fact.",
      sourceId: "wdio-state-loss-export",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    const inboxMarker = "WDIO state loss inbox marker";

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 2);
    writeVaultFile(vaultPath, path.join(scopedRoot, "inbox", "state-loss.md"), inboxMarker);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForSuggestionsContaining(baseUrl, inboxMarker, 1);
    assert.equal(factFiles(vaultPath).length, 1);
    assert.match(fs.readFileSync(factFileForId(vaultPath, fact.id), "utf8"), /infinity_context_version: 1/);
    assert.equal(conflictFiles(vaultPath).length, 0);

    removeSyncState(vaultPath);
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await sleep(300);

    const calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 0);
    assert.equal(factFiles(vaultPath).length, 1);
    assert.equal((await suggestionsContaining(baseUrl, inboxMarker)).length, 1);
    assert.equal(conflictFiles(vaultPath).length, 0);
    assert.match(fs.readFileSync(factFileForId(vaultPath, fact.id), "utf8"), /infinity_context_version: 1/);
  });

  it("surfaces corrupted local sync state and recovers after state reset", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO corrupt state initial fact.",
      sourceId: "wdio-corrupt-state-export",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const exportedFact = factFileForId(vaultPath, fact.id);
    const localDraft = "Obsidian WDIO corrupt state local draft must survive.";
    replaceManagedText(exportedFact, localDraft);
    corruptSyncState(vaultPath);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();

    let calls = readCliCalls(vaultPath);
    let snapshot = await infinityContextSnapshot();
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 1);
    assert.equal(snapshot.lastCommand, "sync");
    assert.equal(snapshot.lastResult.exitCode, 1);
    assert.match(snapshot.lastResult.stderr, /file is not a database|database disk image is malformed/);
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO corrupt state initial fact.");
    assert.match(fs.readFileSync(exportedFact, "utf8"), new RegExp(localDraft));
    assert.equal(conflictFiles(vaultPath).length, 0);

    removeSyncState(vaultPath);
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await waitForBackendFactText(baseUrl, fact.id, localDraft);

    calls = readCliCalls(vaultPath);
    snapshot = await infinityContextSnapshot();
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 0);
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.equal(conflictFiles(vaultPath).length, 0);
    const recoveredFact = await getFact(baseUrl, fact.id);
    assert.equal(recoveredFact.version, 2);
    assert.equal(recoveredFact.text, localDraft);
    const recoveredMarkdown = fs.readFileSync(factFileForId(vaultPath, fact.id), "utf8");
    assert.match(recoveredMarkdown, new RegExp(localDraft));
    assert.match(recoveredMarkdown, /infinity_context_version: 2/);
  });
});

async function resetVaultAndConfigure(apiUrl: string): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nBatch E2E vault.\n",
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

async function createFact(
  apiUrl: string,
  { text, sourceId }: { text: string; sourceId: string },
): Promise<Record<string, any>> {
  const response = await requestJson("POST", `${apiUrl}/v1/facts`, {
    space_slug: spaceSlug,
    memory_scope_external_ref: memoryScopeExternalRef,
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
    `Suggestion was not created for marker: ${marker}`,
  );
}

async function suggestionsContaining(apiUrl: string, marker: string): Promise<Record<string, any>[]> {
  const query = new URLSearchParams({
    space_slug: spaceSlug,
    memory_scope_external_ref: memoryScopeExternalRef,
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
  const factsDir = path.join(vaultPath, scopedRoot, "generated", "facts");
  if (!fs.existsSync(factsDir)) {
    return [];
  }
  return fs
    .readdirSync(factsDir)
    .filter((name) => name.endsWith(".md") && !name.startsWith("."))
    .map((name) => path.join(factsDir, name));
}

function factFileForId(vaultPath: string, factId: string): string {
  const files = factFiles(vaultPath).filter((filePath) =>
    fs.readFileSync(filePath, "utf8").includes(`infinity_context_id: ${factId}`),
  );
  assert.equal(files.length, 1);
  return files[0];
}

function conflictFiles(vaultPath: string): string[] {
  const conflictsDir = path.join(vaultPath, scopedRoot, "conflicts");
  if (!fs.existsSync(conflictsDir)) {
    return [];
  }
  return fs
    .readdirSync(conflictsDir)
    .filter((name) => name.endsWith(".md") && !name.startsWith(".") && name !== "README.md")
    .map((name) => path.join(conflictsDir, name));
}

function removeSyncState(vaultPath: string): void {
  for (const suffix of ["", "-wal", "-shm"]) {
    fs.rmSync(path.join(vaultPath, ".infinity-context", `obsidian-sync.sqlite3${suffix}`), {
      force: true,
    });
  }
}

function corruptSyncState(vaultPath: string): void {
  removeSyncState(vaultPath);
  writeVaultFile(vaultPath, path.join(".infinity-context", "obsidian-sync.sqlite3"), "not a sqlite database");
}

function replaceManagedText(filePath: string, text: string): void {
  const old = fs.readFileSync(filePath, "utf8");
  const start = old.indexOf(textStart) + textStart.length;
  const end = old.indexOf(textEnd);
  assert.ok(start >= textStart.length);
  assert.ok(end > start);
  fs.writeFileSync(filePath, `${old.slice(0, start)}\n${text}\n${old.slice(end)}`, "utf8");
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

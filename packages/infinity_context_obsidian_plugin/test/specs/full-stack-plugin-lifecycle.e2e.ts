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
const pluginId = "infinity-context";
const token = "wdio-lifecycle-token";
const spaceSlug = "wdio-lifecycle";
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

describe("Infinity Context plugin lifecycle full-stack E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "infinity-context-wdio-lifecycle-"));
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    server = startInfinityContextServer(path.join(tempDir, "memory.db"), port);
    await waitForHealth(baseUrl);
  });

  afterEach(function () {
    server?.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  it("resumes real sync after plugin disable and enable without losing local changes", async function () {
    const initialFact = await createFact(baseUrl, {
      text: "Obsidian WDIO lifecycle initial fact.",
      sourceId: "wdio-lifecycle-initial",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    const obsidianPage = await browser.getObsidianPage();

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const exportedFact = factFileForId(vaultPath, initialFact.id);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /Obsidian WDIO lifecycle initial fact/);
    assert.equal(conflictFiles(vaultPath).length, 0);

    await obsidianPage.disablePlugin(pluginId);
    await waitForPluginDisabled();
    assert.equal(readCliCalls(vaultPath).length, 2);

    const disabledLocalEdit = "Obsidian WDIO lifecycle local edit while plugin disabled.";
    const disabledInboxMarker = "WDIO lifecycle inbox note written while plugin disabled";
    replaceManagedText(exportedFact, disabledLocalEdit);
    writeVaultFile(
      vaultPath,
      path.join(scopedRoot, "inbox", "disabled-lifecycle-inbox.md"),
      disabledInboxMarker,
    );
    const lateFact = await createFact(baseUrl, {
      text: "Obsidian WDIO lifecycle backend fact created while plugin disabled.",
      sourceId: "wdio-lifecycle-disabled-backend",
    });
    assert.equal(readCliCalls(vaultPath).length, 2);

    await obsidianPage.enablePlugin(pluginId);
    await waitForPluginScope();
    await waitForPluginIdle();

    let snapshot = await infinityContextSnapshot();
    assert.equal(snapshot.spaceSlug, spaceSlug);
    assert.equal(snapshot.memoryScopeExternalRef, memoryScopeExternalRef);
    assert.equal(snapshot.paths.generatedFacts, posixPath(path.join(scopedRoot, "generated", "facts")));
    assert.equal(snapshot.paths.inbox, posixPath(path.join(scopedRoot, "inbox")));
    assert.equal(snapshot.generatedFactsExists, true);
    assert.equal(snapshot.inboxExists, true);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForBackendFactText(baseUrl, initialFact.id, disabledLocalEdit);
    await waitForSuggestionsContaining(baseUrl, disabledInboxMarker, 1);

    assert.equal(factFiles(vaultPath).length, 2);
    assert.match(fs.readFileSync(factFileForId(vaultPath, initialFact.id), "utf8"), /infinity_context_version: 2/);
    assert.match(
      fs.readFileSync(factFileForId(vaultPath, lateFact.id), "utf8"),
      /backend fact created while plugin disabled/,
    );
    assert.equal(conflictFiles(vaultPath).length, 0);

    await obsidianPage.disablePlugin(pluginId);
    await waitForPluginDisabled();
    const secondDisabledEdit = "Obsidian WDIO lifecycle second disabled edit persists.";
    replaceManagedText(factFileForId(vaultPath, initialFact.id), secondDisabledEdit);

    await obsidianPage.enablePlugin(pluginId);
    await waitForPluginScope();
    await waitForPluginIdle();
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await waitForBackendFactText(baseUrl, initialFact.id, secondDisabledEdit);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 5);
    await waitForPluginIdle();

    snapshot = await infinityContextSnapshot();
    assert.equal(snapshot.lastCommand, "sync");
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.equal((await suggestionsContaining(baseUrl, disabledInboxMarker)).length, 1);
    assert.equal(factFiles(vaultPath).length, 2);
    assert.equal(conflictFiles(vaultPath).length, 0);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync", "sync", "sync", "sync"]);
    assert.ok(calls.every((call) => call.status === 0));
    assert.ok(calls.every((call) => call.args.includes("--space")));
    assert.ok(calls.every((call) => call.args.includes(spaceSlug)));
    assert.ok(calls.every((call) => call.args.includes("--memory_scope")));
    assert.ok(calls.every((call) => call.args.includes(memoryScopeExternalRef)));
  });
});

async function resetVaultAndConfigure(apiUrl: string): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nPlugin lifecycle E2E vault.\n",
  });
  const vaultPath = obsidianPage.getVaultPath();
  installPluginArtifacts(vaultPath);
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
    path.join(".obsidian", "plugins", pluginId, "data.json"),
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
    "Suggestion was not created",
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

async function waitForPluginDisabled(): Promise<void> {
  await browser.waitUntil(async () => !(await pluginRuntime()).loaded, {
    timeout: 20000,
    timeoutMsg: "Infinity Context plugin did not disable",
  });
}

async function waitForPluginScope(): Promise<void> {
  await browser.waitUntil(
    async () => {
      const runtime = await pluginRuntime();
      return (
        runtime.loaded &&
        runtime.enabled &&
        runtime.snapshot.spaceSlug === spaceSlug &&
        runtime.snapshot.memoryScopeExternalRef === memoryScopeExternalRef
      );
    },
    {
      timeout: 20000,
      timeoutMsg: "Infinity Context plugin did not enable with lifecycle settings",
    },
  );
}

async function infinityContextSnapshot(): Promise<any> {
  return await browser.executeObsidian(({ plugins }) => {
    return (plugins.infinityContext as any).snapshot();
  });
}

async function pluginRuntime(): Promise<{ loaded: boolean; enabled: boolean; snapshot: any }> {
  return await browser.executeObsidian(({ app, plugins }) => {
    const plugin = (plugins as any).infinityContext as any;
    const enabledPlugins = Array.from(((app as any).plugins.enabledPlugins ?? []) as Iterable<string>);
    return {
      loaded: Boolean(plugin),
      enabled: enabledPlugins.includes("infinity-context"),
      snapshot: plugin?.snapshot?.() ?? {},
    };
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
    .map((name) => path.join(factsDir, name))
    .sort();
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

function installPluginArtifacts(vaultPath: string): void {
  const pluginDir = path.join(vaultPath, ".obsidian", "plugins", pluginId);
  fs.mkdirSync(pluginDir, { recursive: true });
  for (const fileName of ["manifest.json", "main.js", "styles.css"]) {
    fs.copyFileSync(path.join(process.cwd(), fileName), path.join(pluginDir, fileName));
  }
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

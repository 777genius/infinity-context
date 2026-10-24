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
const token = "wdio-import-toggle-token";
const spaceSlug = "wdio-import-toggle";
const memoryScopeExternalRef = "default";
const rootFolder = "Import Toggle Memory";
const scopedRoot = path.join(rootFolder, "spaces", spaceSlug, "memory_scopes", memoryScopeExternalRef);
const textStart = "<!-- infinity-context-managed:fact-text:start -->";
const textEnd = "<!-- infinity-context-managed:fact-text:end -->";

describe("Infinity Context import toggle E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "infinity-context-wdio-import-toggle-"));
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    server = startInfinityContextServer(path.join(tempDir, "memory.db"), port);
    await waitForHealth(baseUrl);
  });

  afterEach(function () {
    server?.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  it("pauses and resumes local imports through the Obsidian settings UI", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO import toggle initial fact.",
      sourceId: "wdio-import-toggle-seed",
    });
    const vaultPath = await resetVault();
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "infinity-context"), { recursive: true });

    await openInfinityContextSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", vaultPath);
    await setSettingsInput("rootFolder", rootFolder);
    await setSettingsInput("spaceSlug", spaceSlug);
    await setSettingsInput("memoryScopeExternalRef", memoryScopeExternalRef);
    await setSettingsToggle("applyImportOnSync", true);
    await waitForApplyImport(true);
    await setSettingsToggle("applyImportOnSync", false);
    await waitForApplyImport(false);
    await setSettingsInput("commandTimeoutMs", "20000");

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const exportedFact = factFileForId(vaultPath, fact.id);
    const pausedEdit = "Obsidian WDIO import toggle paused local draft.";
    const pausedInboxMarker = "WDIO import toggle paused inbox marker";
    replaceManagedText(exportedFact, pausedEdit);
    writeVaultFile(vaultPath, path.join(scopedRoot, "inbox", "paused-import-inbox.md"), pausedInboxMarker);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();

    let calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 1);
    assert.ok(!calls.at(-1)?.args.includes("--apply-import"));
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO import toggle initial fact.");
    assert.match(fs.readFileSync(exportedFact, "utf8"), /paused local draft/);
    assert.equal((await suggestionsContaining(baseUrl, pausedInboxMarker)).length, 0);
    assert.equal(conflictFiles(vaultPath).length, 0);

    await openInfinityContextSettings();
    await setSettingsToggle("applyImportOnSync", true);
    await waitForApplyImport(true);
    await waitForSettingsFile(vaultPath, '"applyImportOnSync": true');

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await waitForBackendFactText(baseUrl, fact.id, pausedEdit);
    await waitForSuggestionsContaining(baseUrl, pausedInboxMarker, 1);

    calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 0);
    assert.ok(calls.at(-1)?.args.includes("--apply-import"));
    assert.match(fs.readFileSync(exportedFact, "utf8"), /infinity_context_version: 2/);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 5);
    await waitForPluginIdle();

    calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync", "sync", "sync", "sync"]);
    assert.equal((await suggestionsContaining(baseUrl, pausedInboxMarker)).length, 1);
    assert.equal(conflictFiles(vaultPath).length, 0);
    assert.equal(factFiles(vaultPath).length, 1);
  });

  it("keeps imports paused across reload and imports the latest inbox text once", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO import toggle reload backend fact.",
      sourceId: "wdio-import-toggle-reload-seed",
    });
    const vaultPath = await resetVault();
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "infinity-context"), { recursive: true });

    await openInfinityContextSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", vaultPath);
    await setSettingsInput("rootFolder", rootFolder);
    await setSettingsInput("spaceSlug", spaceSlug);
    await setSettingsInput("memoryScopeExternalRef", memoryScopeExternalRef);
    await setSettingsToggle("applyImportOnSync", false);
    await waitForApplyImport(false);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForSettingsFile(vaultPath, '"applyImportOnSync": false');

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const exportedFact = factFileForId(vaultPath, fact.id);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /import toggle reload backend fact/);
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO import toggle reload backend fact.");

    const firstMarker = "WDIO import toggle reload stale inbox text";
    const latestMarker = "WDIO import toggle reload latest inbox text";
    const inboxRelativePath = path.join(scopedRoot, "inbox", "reload-paused-import.md");
    writeVaultFile(vaultPath, inboxRelativePath, firstMarker);

    await browser.reloadObsidian();
    await waitForApplyImport(false);
    await waitForPluginIdle();
    writeVaultFile(vaultPath, inboxRelativePath, latestMarker);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();

    let calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 0);
    assert.ok(!calls.at(-1)?.args.includes("--apply-import"));
    assert.equal((await suggestionsContaining(baseUrl, firstMarker)).length, 0);
    assert.equal((await suggestionsContaining(baseUrl, latestMarker)).length, 0);

    await openInfinityContextSettings();
    await setSettingsToggle("applyImportOnSync", true);
    await waitForApplyImport(true);
    await waitForSettingsFile(vaultPath, '"applyImportOnSync": true');
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, latestMarker, 1);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 5);
    await waitForPluginIdle();
    await sleep(300);

    calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync", "sync", "sync", "sync"]);
    assert.equal(calls[1].status, 0);
    assert.equal(calls[2].status, 0);
    assert.equal(calls[3].status, 0);
    assert.equal(calls[4].status, 0);
    assert.equal((await suggestionsContaining(baseUrl, firstMarker)).length, 0);
    assert.equal((await suggestionsContaining(baseUrl, latestMarker)).length, 1);
    assert.equal(conflictFiles(vaultPath).length, 0);
    assert.equal(factFiles(vaultPath).length, 1);
  });
});

async function resetVault(): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nImport toggle E2E vault.\n",
  });
  return obsidianPage.getVaultPath();
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

async function waitForApplyImport(value: boolean): Promise<void> {
  await browser.waitUntil(async () => {
    return await browser.executeObsidian(({ plugins }, expected) => {
      return (plugins.infinityContext as any).settings.applyImportOnSync === expected;
    }, value);
  }, {
    timeout: 20000,
    timeoutMsg: `Infinity Context plugin did not apply import toggle ${value}`,
  });
}

async function waitForSettingsFile(vaultPath: string, expectedText: string): Promise<void> {
  const settingsPath = path.join(vaultPath, ".obsidian", "plugins", "infinity-context", "data.json");
  await waitUntil(
    async () => fs.existsSync(settingsPath) && fs.readFileSync(settingsPath, "utf8").includes(expectedText),
    "Infinity Context settings UI did not persist import toggle",
  );
}

async function openInfinityContextSettings(): Promise<void> {
  await browser.executeObsidian(({ app }) => {
    const setting = (app as any).setting;
    setting.open();
    setting.openTabById("infinity-context");
  });
  await browser.waitUntil(
    async () =>
      await browser.execute(() =>
        Boolean(document.querySelector('input[data-infinity-context-setting="apiUrl"]')),
      ),
    {
      timeout: 20000,
      timeoutMsg: "Infinity Context settings UI did not open",
    },
  );
}

async function setSettingsInput(name: string, value: string): Promise<void> {
  const changed = await browser.execute(
    (settingName, nextValue) => {
      const input = document.querySelector<HTMLInputElement>(
        `input[data-infinity-context-setting="${settingName}"]`,
      );
      if (!input) {
        return false;
      }
      input.focus();
      input.value = nextValue;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      input.blur();
      return true;
    },
    name,
    value,
  );
  assert.equal(changed, true, `Could not change Infinity Context settings input ${name}`);
}

async function setSettingsToggle(name: string, value: boolean): Promise<void> {
  const changed = await browser.execute(
    (settingName, nextValue) => {
      const toggle = document.querySelector<HTMLElement>(
        `[data-infinity-context-setting="${settingName}"]`,
      );
      if (!toggle) {
        return false;
      }
      const active = toggle.classList.contains("is-enabled");
      if (active !== nextValue) {
        toggle.click();
      }
      return true;
    },
    name,
    value,
  );
  assert.equal(changed, true, `Could not change Infinity Context settings toggle ${name}`);
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

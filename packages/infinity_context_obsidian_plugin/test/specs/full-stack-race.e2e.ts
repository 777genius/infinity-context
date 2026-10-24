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
const realEnvKeys = ["INFINITY_CONTEXT_REAL_OBSIDIAN_DELAY_MS"];

describe("Infinity Context real sync race E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "infinity-context-wdio-race-"));
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    server = startInfinityContextServer(path.join(tempDir, "memory.db"), port);
    await waitForHealth(baseUrl);
    await clearRealEnv();
  });

  afterEach(async function () {
    await clearRealEnv();
    server?.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  it("blocks overlapping real sync commands while preserving one backend update", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO real overlap initial fact.",
      sourceId: "wdio-real-overlap-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    const exportedFact = await connectAndExportFact(vaultPath);
    const appliedText = "Obsidian WDIO real overlap local edit applied once.";
    replaceManagedText(exportedFact, appliedText);
    await setRealEnv({ INFINITY_CONTEXT_REAL_OBSIDIAN_DELAY_MS: "1200" });

    const snapshots = await browser.executeObsidian(async ({ plugins }) => {
      const plugin = plugins.infinityContext as any;
      void plugin.syncNow();
      await new Promise((resolve) => setTimeout(resolve, 100));
      const duringFirst = plugin.snapshot();
      await plugin.syncNow();
      const afterSecond = plugin.snapshot();
      return { duringFirst, afterSecond };
    });

    assert.equal(snapshots.duringFirst.busyLabel, "syncing vault");
    assert.equal(snapshots.afterSecond.busyLabel, "syncing vault");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForBackendFactText(baseUrl, fact.id, appliedText);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(
      calls.map((call) => call.command),
      ["connect", "sync", "sync"],
    );
    assert.ok(calls.every((call) => call.status === 0));
    assert.equal(factFiles(vaultPath).length, 1);
    assert.equal(conflictFiles(vaultPath).length, 0);

    const updatedFact = await getFact(baseUrl, fact.id);
    assert.equal(updatedFact.version, 2);
    assert.equal(updatedFact.text, appliedText);
    const markdown = fs.readFileSync(onlyFactFile(vaultPath), "utf8");
    assert.match(markdown, new RegExp(appliedText));
    assert.match(markdown, /infinity_context_version: 2/);
  });

  it("recovers dirty local edits after the backend dies during real sync", async function () {
    const dbPath = path.join(tempDir, "memory.db");
    const port = Number(new URL(baseUrl).port);
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO backend restart initial fact.",
      sourceId: "wdio-backend-restart-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    const exportedFact = await connectAndExportFact(vaultPath);
    const recoveredText = "Obsidian WDIO backend restart local draft recovered.";
    replaceManagedText(exportedFact, recoveredText);
    await setRealEnv({ INFINITY_CONTEXT_REAL_OBSIDIAN_DELAY_MS: "900" });

    const duringSync = await browser.executeObsidian(async ({ plugins }) => {
      const plugin = plugins.infinityContext as any;
      void plugin.syncNow();
      await new Promise((resolve) => setTimeout(resolve, 100));
      return plugin.snapshot();
    });
    assert.equal(duringSync.busyLabel, "syncing vault");

    server?.kill("SIGTERM");
    server = undefined;
    await waitForUnhealthy(baseUrl);
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();

    let calls = readCliCalls(vaultPath);
    assert.deepEqual(
      calls.map((call) => call.command),
      ["connect", "sync", "sync"],
    );
    assert.equal(calls.at(-1)?.status, 1);
    assert.match(fs.readFileSync(exportedFact, "utf8"), new RegExp(recoveredText));
    assert.equal(conflictFiles(vaultPath).length, 0);

    await clearRealEnv();
    server = startInfinityContextServer(dbPath, port);
    await waitForHealth(baseUrl);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await waitForBackendFactText(baseUrl, fact.id, recoveredText);

    calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 0);
    assert.equal(conflictFiles(vaultPath).length, 0);
    const recoveredFact = await getFact(baseUrl, fact.id);
    assert.equal(recoveredFact.version, 2);
    assert.equal(recoveredFact.text, recoveredText);
    const markdown = fs.readFileSync(onlyFactFile(vaultPath), "utf8");
    assert.match(markdown, new RegExp(recoveredText));
    assert.match(markdown, /infinity_context_version: 2/);
  });

  it("keeps inbox notes pending when the backend is down and imports once after recovery", async function () {
    const dbPath = path.join(tempDir, "memory.db");
    const port = Number(new URL(baseUrl).port);
    await createFact(baseUrl, {
      text: "Obsidian WDIO inbox backend recovery seed.",
      sourceId: "wdio-inbox-backend-recovery-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();

    const inboxRelativePath = path.join(scopedRoot, "inbox", "backend-recovery-inbox.md");
    const inboxPath = path.join(vaultPath, inboxRelativePath);
    const marker = "WDIO backend down inbox marker must import once";
    writeVaultFile(vaultPath, inboxRelativePath, marker);

    server?.kill("SIGTERM");
    server = undefined;
    await waitForUnhealthy(baseUrl);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    let calls = readCliCalls(vaultPath);
    let snapshot = await infinityContextSnapshot();
    assert.deepEqual(calls.map((call) => `${call.command}:${call.status}`), ["connect:0", "sync:1"]);
    assert.equal(snapshot.lastCommand, "sync");
    assert.equal(snapshot.lastResult.exitCode, 1);
    assert.match(fs.readFileSync(inboxPath, "utf8"), new RegExp(marker));
    assert.equal(conflictFiles(vaultPath).length, 0);

    server = startInfinityContextServer(dbPath, port);
    await waitForHealth(baseUrl);
    assert.equal((await suggestionsContaining(baseUrl, marker)).length, 0);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, marker, 1);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await sleep(300);

    calls = readCliCalls(vaultPath);
    snapshot = await infinityContextSnapshot();
    assert.deepEqual(
      calls.map((call) => `${call.command}:${call.status}`),
      ["connect:0", "sync:1", "sync:0", "sync:0"],
    );
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.match(fs.readFileSync(inboxPath, "utf8"), new RegExp(marker));
    assert.equal((await suggestionsContaining(baseUrl, marker)).length, 1);
    assert.equal(conflictFiles(vaultPath).length, 0);
  });

  it("does not import backend-down inbox notes deleted before recovery", async function () {
    const dbPath = path.join(tempDir, "memory.db");
    const port = Number(new URL(baseUrl).port);
    await createFact(baseUrl, {
      text: "Obsidian WDIO deleted pending inbox recovery seed.",
      sourceId: "wdio-deleted-pending-inbox-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();

    const inboxRelativePath = path.join(scopedRoot, "inbox", "deleted-pending-inbox.md");
    const marker = "WDIO backend down inbox marker deleted before recovery";
    writeVaultFile(vaultPath, inboxRelativePath, marker);

    server?.kill("SIGTERM");
    server = undefined;
    await waitForUnhealthy(baseUrl);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    let calls = readCliCalls(vaultPath);
    let snapshot = await infinityContextSnapshot();
    assert.deepEqual(calls.map((call) => `${call.command}:${call.status}`), ["connect:0", "sync:1"]);
    assert.equal(snapshot.lastCommand, "sync");
    assert.equal(snapshot.lastResult.exitCode, 1);
    assert.match(fs.readFileSync(path.join(vaultPath, inboxRelativePath), "utf8"), new RegExp(marker));

    await deleteVaultFileInObsidian(inboxRelativePath);
    await waitForVaultFileMissing(vaultPath, inboxRelativePath);

    server = startInfinityContextServer(dbPath, port);
    await waitForHealth(baseUrl);
    assert.equal((await suggestionsContaining(baseUrl, marker)).length, 0);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await sleep(300);

    calls = readCliCalls(vaultPath);
    snapshot = await infinityContextSnapshot();
    assert.deepEqual(calls.map((call) => `${call.command}:${call.status}`), ["connect:0", "sync:1", "sync:0"]);
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.equal((await suggestionsContaining(baseUrl, marker)).length, 0);
    assert.equal(conflictFiles(vaultPath).length, 0);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await sleep(300);

    calls = readCliCalls(vaultPath);
    assert.deepEqual(
      calls.map((call) => `${call.command}:${call.status}`),
      ["connect:0", "sync:1", "sync:0", "sync:0"],
    );
    assert.equal((await suggestionsContaining(baseUrl, marker)).length, 0);
    assert.equal(fs.existsSync(path.join(vaultPath, inboxRelativePath)), false);
    assert.equal(conflictFiles(vaultPath).length, 0);
  });

  it("recovers dirty local edits after a real connector timeout", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO real timeout initial fact.",
      sourceId: "wdio-real-timeout-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    const exportedFact = await connectAndExportFact(vaultPath);
    const recoveredText = "Obsidian WDIO real timeout local draft recovered.";
    replaceManagedText(exportedFact, recoveredText);
    await updatePluginSettings({ commandTimeoutMs: 1000 });
    await setRealEnv({ INFINITY_CONTEXT_REAL_OBSIDIAN_DELAY_MS: "3000" });

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForPluginIdle();

    let calls = readCliCalls(vaultPath);
    let snapshot = await infinityContextSnapshot();
    assert.deepEqual(
      calls.map((call) => call.command),
      ["connect", "sync"],
    );
    assert.equal(snapshot.lastCommand, "sync");
    assert.equal(snapshot.lastResult.exitCode, 1);
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO real timeout initial fact.");
    assert.match(fs.readFileSync(exportedFact, "utf8"), new RegExp(recoveredText));
    assert.equal(conflictFiles(vaultPath).length, 0);

    await clearRealEnv();
    await updatePluginSettings({ commandTimeoutMs: 5000 });
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForBackendFactText(baseUrl, fact.id, recoveredText);

    calls = readCliCalls(vaultPath);
    snapshot = await infinityContextSnapshot();
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 0);
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.equal(conflictFiles(vaultPath).length, 0);
    const recoveredFact = await getFact(baseUrl, fact.id);
    assert.equal(recoveredFact.version, 2);
    assert.equal(recoveredFact.text, recoveredText);
    const markdown = fs.readFileSync(onlyFactFile(vaultPath), "utf8");
    assert.match(markdown, new RegExp(recoveredText));
    assert.match(markdown, /infinity_context_version: 2/);
  });

  it("recovers timeout edits after the user raises command timeout through settings", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO settings timeout initial fact.",
      sourceId: "wdio-settings-timeout-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    const exportedFact = await connectAndExportFact(vaultPath);
    const recoveredText = "Obsidian WDIO settings timeout local draft recovered.";
    replaceManagedText(exportedFact, recoveredText);
    await setRealEnv({ INFINITY_CONTEXT_REAL_OBSIDIAN_DELAY_MS: "3000" });

    await openInfinityContextSettings();
    await setSettingsInput("commandTimeoutMs", "1000");
    await waitForCommandTimeout(1000);
    await clickSettingsButton("Vault sync", "Sync");
    await waitForPluginIdle();

    let calls = readCliCalls(vaultPath);
    let snapshot = await infinityContextSnapshot();
    assert.deepEqual(
      calls.map((call) => call.command),
      ["connect", "sync"],
    );
    assert.equal(snapshot.lastCommand, "sync");
    assert.equal(snapshot.lastResult.exitCode, 1);
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO settings timeout initial fact.");
    assert.match(fs.readFileSync(exportedFact, "utf8"), new RegExp(recoveredText));
    assert.equal(conflictFiles(vaultPath).length, 0);

    await openInfinityContextSettings();
    await setSettingsInput("commandTimeoutMs", "5000");
    await waitForCommandTimeout(5000);
    await clickSettingsButton("Vault sync", "Sync");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForBackendFactText(baseUrl, fact.id, recoveredText);

    calls = readCliCalls(vaultPath);
    snapshot = await infinityContextSnapshot();
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 0);
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.equal(conflictFiles(vaultPath).length, 0);
    const recoveredFact = await getFact(baseUrl, fact.id);
    assert.equal(recoveredFact.version, 2);
    assert.equal(recoveredFact.text, recoveredText);
    const markdown = fs.readFileSync(onlyFactFile(vaultPath), "utf8");
    assert.match(markdown, new RegExp(recoveredText));
    assert.match(markdown, /infinity_context_version: 2/);
  });
});

async function resetVaultAndConfigure(apiUrl: string): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nRace E2E vault.\n",
  });
  const vaultPath = obsidianPage.getVaultPath();
  await configurePlugin(vaultPath, apiUrl);
  return vaultPath;
}

async function connectAndExportFact(vaultPath: string): Promise<string> {
  await browser.executeObsidianCommand("infinity-context:connect-vault");
  await waitForCliCalls(vaultPath, 1);
  await waitForPluginIdle();
  await browser.executeObsidianCommand("infinity-context:sync-now");
  await waitForCliCalls(vaultPath, 2);
  await waitForPluginIdle();
  return onlyFactFile(vaultPath);
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
    commandTimeoutMs: 5000,
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

async function waitForUnhealthy(apiUrl: string): Promise<void> {
  await waitUntil(async () => {
    try {
      const response = await requestJson("GET", `${apiUrl}/v1/health`);
      return response.status !== 200;
    } catch (_error) {
      return true;
    }
  }, "Infinity Context server stayed healthy");
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

async function infinityContextSnapshot(): Promise<any> {
  return await browser.executeObsidian(({ plugins }) => {
    return (plugins.infinityContext as any).snapshot();
  });
}

async function updatePluginSettings(values: Record<string, unknown>): Promise<void> {
  await browser.executeObsidian(
    async ({ plugins }, payload) => {
      const plugin = plugins.infinityContext as any;
      Object.assign(plugin.settings, payload);
      await plugin.saveSettings();
    },
    values,
  );
}

async function waitForCommandTimeout(expectedMs: number): Promise<void> {
  await browser.waitUntil(
    async () =>
      await browser.executeObsidian(
        ({ plugins }, expected) => (plugins.infinityContext as any).settings.commandTimeoutMs === expected,
        expectedMs,
      ),
    {
      timeout: 20000,
      timeoutMsg: `Infinity Context plugin did not apply command timeout ${expectedMs}`,
    },
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

async function clickSettingsButton(settingName: string, buttonText: string): Promise<void> {
  const clicked = await browser.execute(
    (nextSettingName, nextButtonText) => {
      const items = Array.from(document.querySelectorAll<HTMLElement>(".setting-item"));
      for (const item of items) {
        const name = item.querySelector<HTMLElement>(".setting-item-name")?.innerText.trim();
        if (name !== nextSettingName) {
          continue;
        }
        const buttons = Array.from(item.querySelectorAll<HTMLButtonElement>("button"));
        const button = buttons.find((candidate) => candidate.innerText.trim() === nextButtonText);
        if (!button) {
          return false;
        }
        button.click();
        return true;
      }
      return false;
    },
    settingName,
    buttonText,
  );
  assert.equal(clicked, true, `Could not click Infinity Context settings button ${settingName}/${buttonText}`);
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

function onlyFactFile(vaultPath: string): string {
  const files = factFiles(vaultPath);
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

async function deleteVaultFileInObsidian(relativePath: string): Promise<void> {
  await browser.executeObsidian(
    async ({ app }, filePath) => {
      await app.vault.adapter.remove(filePath);
    },
    relativePath,
  );
}

async function waitForVaultFileMissing(vaultPath: string, relativePath: string): Promise<void> {
  await waitUntil(
    async () => !fs.existsSync(path.join(vaultPath, relativePath)),
    `Vault file was not deleted: ${relativePath}`,
  );
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

async function setRealEnv(values: Record<string, string>): Promise<void> {
  await browser.executeObsidian(
    (_context, payload) => {
      for (const key of payload.keys) {
        delete process.env[key];
      }
      for (const [key, value] of Object.entries(payload.values)) {
        process.env[key] = String(value);
      }
    },
    { keys: realEnvKeys, values },
  );
}

async function clearRealEnv(): Promise<void> {
  await setRealEnv({});
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

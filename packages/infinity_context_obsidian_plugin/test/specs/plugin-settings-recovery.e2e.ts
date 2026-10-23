import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import { browser } from "@wdio/globals";

const repoRoot = path.resolve("../../");
const pluginId = "infinity-context";
const fakeCliPath = path.resolve("test/fixtures/fake-infinity-context-obsidian.cjs");
const fakeLocalCliPath = path.resolve("test/fixtures/fake-infinity-context.cjs");
const realCliPath = path.resolve("test/fixtures/real-infinity-context-obsidian.cjs");
const defaultApiUrl = "http://127.0.0.1:7788";
const defaultSpaceSlug = "default";
const defaultMemoryScopeExternalRef = "default";
const defaultRootFolder = "Infinity Context";
const realToken = "wdio-settings-recovery-real-token";
const realSpaceSlug = "settings-recovery-real";
const realMemoryScopeExternalRef = "default";
const realRootFolder = "Recovered Real Memo";

describe("Infinity Context plugin settings recovery E2E", function () {
  it("loads with defaults after malformed data.json and can save usable settings", async function () {
    const obsidianPage = await browser.getObsidianPage();
    await obsidianPage.resetVault({
      "Welcome.md": "# Welcome\n\nMalformed settings E2E vault.\n",
    });
    const vaultPath = obsidianPage.getVaultPath();

    writePluginData(vaultPath, "{ not valid json");
    await browser.reloadObsidian();
    await waitForPluginLoaded();

    let runtime = await pluginRuntime();
    assert.equal(runtime.loaded, true);
    assert.ok(runtime.commandIds.includes("infinity-context:connect-vault"));
    assert.equal(runtime.snapshot.apiUrl, defaultApiUrl);
    assert.equal(runtime.snapshot.spaceSlug, defaultSpaceSlug);
    assert.equal(runtime.snapshot.memoryScopeExternalRef, defaultMemoryScopeExternalRef);
    assert.equal(runtime.snapshot.rootFolder, defaultRootFolder);
    assert.equal(runtime.snapshot.busyLabel, "");

    const recoveredSettings = {
      apiUrl: "http://127.0.0.1:65531",
      token: "recovered-token",
      localCliPath: fakeLocalCliPath,
      cliPath: fakeCliPath,
      vaultPathOverride: vaultPath,
      spaceSlug: "recovered-project",
      memoryScopeExternalRef: "recovered-memory_scope",
      rootFolder: "Recovered Memo",
      layoutVersion: "v2",
      applyImportOnSync: true,
      commandTimeoutMs: 10000,
    };
    await browser.executeObsidian(
      async ({ plugins }, settings) => {
        const plugin = plugins.infinityContext as any;
        Object.assign(plugin.settings, settings);
        await plugin.saveSettings();
      },
      recoveredSettings,
    );

    clearInfinityContextState(vaultPath);
    await browser.reloadObsidian();
    await browser.waitUntil(async () => (await pluginRuntime()).snapshot.spaceSlug === "recovered-project", {
      timeout: 20000,
      timeoutMsg: "Infinity Context plugin did not reload recovered settings",
    });

    runtime = await pluginRuntime();
    assert.equal(runtime.snapshot.apiUrl, recoveredSettings.apiUrl);
    assert.equal(runtime.snapshot.memoryScopeExternalRef, recoveredSettings.memoryScopeExternalRef);
    assert.equal(runtime.snapshot.rootFolder, recoveredSettings.rootFolder);

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => `${call.command}:${call.status}`), ["connect:0"]);
    assert.equal(calls[0].envToken, recoveredSettings.token);
    assert.ok(calls[0].args.includes(recoveredSettings.apiUrl));
    assert.ok(calls[0].args.includes(recoveredSettings.spaceSlug));
    assert.ok(calls[0].args.includes(recoveredSettings.memoryScopeExternalRef));
    assert.ok(calls[0].args.includes(recoveredSettings.rootFolder));
    assert.match(readVaultFile(vaultPath, "Recovered Memo/README.md"), /Connected by plugin E2E/);
  });

  it("normalizes invalid persisted setting types after reload", async function () {
    const obsidianPage = await browser.getObsidianPage();
    await obsidianPage.resetVault({
      "Welcome.md": "# Welcome\n\nInvalid setting types E2E vault.\n",
    });
    const vaultPath = obsidianPage.getVaultPath();

    writePluginData(
      vaultPath,
      JSON.stringify(
        {
          apiUrl: 42,
          token: ["not", "a", "token"],
          localCliPath: { bin: fakeLocalCliPath },
          cliPath: fakeCliPath,
          vaultPathOverride: vaultPath,
          rootFolder: "Typed Memo",
          layoutVersion: "v99",
          spaceSlug: 123,
          memoryScopeExternalRef: null,
          applyImportOnSync: "true",
          commandTimeoutMs: "fast",
        },
        null,
        2,
      ),
    );

    clearInfinityContextState(vaultPath);
    await browser.reloadObsidian();
    await waitForPluginLoaded();

    const runtime = await pluginRuntime();
    assert.equal(runtime.loaded, true);
    assert.equal(runtime.snapshot.apiUrl, defaultApiUrl);
    assert.equal(runtime.snapshot.spaceSlug, defaultSpaceSlug);
    assert.equal(runtime.snapshot.memoryScopeExternalRef, defaultMemoryScopeExternalRef);
    assert.equal(runtime.snapshot.rootFolder, "Typed Memo");
    assert.equal(runtime.snapshot.layoutVersion, "v2");
    assert.equal(runtime.snapshot.pathError, "");

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => `${call.command}:${call.status}`), ["connect:0"]);
    assert.equal(calls[0].envToken, "");
    assert.ok(calls[0].args.includes(defaultApiUrl));
    assert.ok(calls[0].args.includes(defaultSpaceSlug));
    assert.ok(calls[0].args.includes(defaultMemoryScopeExternalRef));
    assert.ok(calls[0].args.includes("Typed Memo"));
    assert.match(readVaultFile(vaultPath, "Typed Memo/README.md"), /Connected by plugin E2E/);
  });

  it("recovers malformed settings through settings UI and syncs real backend data", async function () {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "infinity-context-wdio-settings-recovery-real-"));
    const port = await freePort();
    const baseUrl = `http://127.0.0.1:${port}`;
    const server = startInfinityContextServer(path.join(tempDir, "memory.db"), port);

    try {
      await waitForHealth(baseUrl);
      const fact = await createFact(baseUrl, {
        text: "Obsidian WDIO malformed settings real recovery fact.",
        sourceId: "wdio-malformed-settings-real-recovery-seed",
      });
      const obsidianPage = await browser.getObsidianPage();
      await obsidianPage.resetVault({
        "Welcome.md": "# Welcome\n\nMalformed settings real recovery E2E vault.\n",
      });
      const vaultPath = obsidianPage.getVaultPath();

      writePluginData(vaultPath, "{ still not valid json");
      clearInfinityContextState(vaultPath);
      await browser.reloadObsidian();
      await waitForPluginLoaded();
      assert.equal((await pluginRuntime()).snapshot.apiUrl, defaultApiUrl);

      await openInfinityContextSettings();
      await setSettingsInput("apiUrl", baseUrl);
      await setSettingsInput("token", realToken);
      await setSettingsInput("cliPath", realCliPath);
      await setSettingsInput("vaultPathOverride", vaultPath);
      await setSettingsInput("rootFolder", realRootFolder);
      await setSettingsInput("spaceSlug", realSpaceSlug);
      await setSettingsInput("memoryScopeExternalRef", realMemoryScopeExternalRef);
      await setSettingsInput("commandTimeoutMs", "20000");
      await setSettingsToggle("applyImportOnSync", true);
      await waitForSettingsFile(vaultPath, baseUrl);
      await browser.waitUntil(async () => (await pluginRuntime()).snapshot.apiUrl === baseUrl, {
        timeout: 20000,
        timeoutMsg: "Infinity Context plugin did not apply recovered real API URL",
      });

      const inboxMarker = "WDIO malformed settings real recovery inbox imports once";
      writeVaultFile(
        vaultPath,
        path.join(scopedRoot(realRootFolder, realSpaceSlug, realMemoryScopeExternalRef), "inbox", "recovered-real-inbox.md"),
        inboxMarker,
      );

      await browser.executeObsidianCommand("infinity-context:connect-vault");
      await waitForRealCliCalls(vaultPath, 1);
      await waitForPluginIdle();
      await browser.executeObsidianCommand("infinity-context:sync-now");
      await waitForRealCliCalls(vaultPath, 2);
      await waitForPluginIdle();
      await waitForSuggestionsContaining(baseUrl, inboxMarker, 1);

      const calls = readRealCliCalls(vaultPath);
      assert.deepEqual(calls.map((call) => `${call.command}:${call.status}`), ["connect:0", "sync:0"]);
      assert.ok(calls.every((call) => call.args.includes(baseUrl)));
      assert.ok(calls.every((call) => call.args.includes(realSpaceSlug)));
      assert.ok(calls.every((call) => call.args.includes(realMemoryScopeExternalRef)));
      assert.ok(calls.every((call) => call.args.includes(realRootFolder)));
      assert.equal(factFiles(vaultPath).length, 1);
      assert.match(fs.readFileSync(onlyFactFile(vaultPath), "utf8"), /malformed settings real recovery fact/);
      assert.match(fs.readFileSync(onlyFactFile(vaultPath), "utf8"), new RegExp(`infinity_context_id: ${fact.id}`));

      await browser.executeObsidianCommand("infinity-context:sync-now");
      await waitForRealCliCalls(vaultPath, 3);
      await waitForPluginIdle();
      await sleep(300);
      assert.equal((await suggestionsContaining(baseUrl, inboxMarker)).length, 1);
      assert.equal(factFiles(vaultPath).length, 1);
    } finally {
      server.kill("SIGTERM");
      fs.rmSync(tempDir, { recursive: true, force: true });
    }
  });
});

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
    service_token="${realToken}",
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

async function waitForPluginLoaded(): Promise<void> {
  await browser.waitUntil(async () => (await pluginRuntime()).loaded, {
    timeout: 20000,
    timeoutMsg: "Infinity Context plugin did not load",
  });
}

async function waitForPluginIdle(): Promise<void> {
  await browser.waitUntil(async () => (await pluginRuntime()).snapshot.busyLabel === "", {
    timeout: 20000,
    timeoutMsg: "Infinity Context plugin did not become idle",
  });
}

async function pluginRuntime(): Promise<{
  loaded: boolean;
  commandIds: string[];
  snapshot: any;
}> {
  return await browser.executeObsidian(({ app, plugins }) => {
    const plugin = (plugins as any).infinityContext as any;
    return {
      loaded: Boolean(plugin),
      commandIds: Object.keys((app as any).commands.commands)
        .filter((id) => id.startsWith("infinity-context:"))
        .sort(),
      snapshot: plugin?.snapshot?.() ?? {},
    };
  });
}

async function waitForCliCalls(vaultPath: string, count: number): Promise<void> {
  await browser.waitUntil(() => readCliCalls(vaultPath).length >= count, {
    timeout: 10000,
    timeoutMsg: `Expected ${count} connector CLI calls`,
  });
}

async function waitForRealCliCalls(vaultPath: string, count: number): Promise<void> {
  await browser.waitUntil(() => readRealCliCalls(vaultPath).length >= count, {
    timeout: 20000,
    timeoutMsg: `Expected ${count} real connector CLI calls`,
  });
}

async function waitForSettingsFile(vaultPath: string, marker: string): Promise<void> {
  const settingsPath = path.join(vaultPath, ".obsidian", "plugins", pluginId, "data.json");
  await waitUntil(
    async () => fs.existsSync(settingsPath) && fs.readFileSync(settingsPath, "utf8").includes(marker),
    `Infinity Context settings UI did not persist ${marker}`,
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
    space_slug: realSpaceSlug,
    memory_scope_external_ref: realMemoryScopeExternalRef,
    status: "pending",
  });
  const response = await requestJson("GET", `${apiUrl}/v1/suggestions?${query.toString()}`);
  assert.equal(response.status, 200);
  return response.body.data.filter((item: Record<string, any>) =>
    String(item.candidate_text).includes(marker),
  );
}

async function createFact(
  apiUrl: string,
  { text, sourceId }: { text: string; sourceId: string },
): Promise<Record<string, any>> {
  const response = await requestJson("POST", `${apiUrl}/v1/facts`, {
    space_slug: realSpaceSlug,
    memory_scope_external_ref: realMemoryScopeExternalRef,
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
          Authorization: `Bearer ${realToken}`,
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

function writePluginData(vaultPath: string, content: string): void {
  writeVaultFile(vaultPath, path.join(".obsidian", "plugins", pluginId, "data.json"), content);
}

function clearInfinityContextState(vaultPath: string): void {
  fs.rmSync(path.join(vaultPath, ".infinity-context"), { recursive: true, force: true });
}

function writeVaultFile(vaultPath: string, relativePath: string, content: string): void {
  const target = path.join(vaultPath, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content, "utf8");
}

function readVaultFile(vaultPath: string, relativePath: string): string {
  return fs.readFileSync(path.join(vaultPath, relativePath), "utf8");
}

function readCliCalls(vaultPath: string): Array<{
  command: string;
  args: string[];
  envToken: string;
  status: number;
}> {
  const logPath = path.join(vaultPath, ".infinity-context/plugin-cli-calls.jsonl");
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

function readRealCliCalls(vaultPath: string): Array<{ command: string; args: string[]; status: number }> {
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

function factFiles(vaultPath: string): string[] {
  const factsDir = path.join(
    vaultPath,
    scopedRoot(realRootFolder, realSpaceSlug, realMemoryScopeExternalRef),
    "generated",
    "facts",
  );
  if (!fs.existsSync(factsDir)) {
    return [];
  }
  return fs
    .readdirSync(factsDir)
    .filter((name) => name.endsWith(".md") && !name.startsWith("."))
    .map((name) => path.join(factsDir, name))
    .sort();
}

function onlyFactFile(vaultPath: string): string {
  const files = factFiles(vaultPath);
  assert.equal(files.length, 1);
  return files[0];
}

function scopedRoot(rootFolder: string, spaceSlug: string, memoryScopeExternalRef: string): string {
  return path.join(rootFolder, "spaces", spaceSlug, "memory_scopes", memoryScopeExternalRef);
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

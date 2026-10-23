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
const fakeLocalCliPath = path.resolve("test/fixtures/fake-infinity-context.cjs");
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
const localEnvKeys = [
  "INFINITY_CONTEXT_FAKE_LOCAL_DELAY_MS",
  "INFINITY_CONTEXT_FAKE_LOCAL_FAIL_COMMAND",
  "INFINITY_CONTEXT_FAKE_LOCAL_STATUS_READY",
];

describe("Infinity Context prepare flow E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "infinity-context-wdio-prepare-"));
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    server = startInfinityContextServer(path.join(tempDir, "memory.db"), port);
    await waitForHealth(baseUrl);
    await clearLocalEnv();
  });

  afterEach(async function () {
    await clearLocalEnv();
    server?.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  it("prepares a vault through the plugin using the real connector and backend", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO prepare visible fact.",
      sourceId: "wdio-real-prepare-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);

    await browser.executeObsidianCommand("infinity-context:prepare-vault");
    await waitForLocalStackCalls(vaultPath, 2);
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const localCalls = readLocalStackCalls(vaultPath);
    assert.deepEqual(
      localCalls.map((call) => `${call.command}:${call.status}`),
      ["init:0", "status:0"],
    );
    assert.ok(localCalls.every((call) => call.envToken === token));
    assert.ok(localCalls.every((call) => call.apiUrl === baseUrl));
    assert.deepEqual(localCalls[0].args, ["init", "--api-url", baseUrl, "--json"]);
    assert.deepEqual(localCalls[1].args, ["status", "--json"]);

    const prepareCalls = readCliCalls(vaultPath);
    assert.deepEqual(
      prepareCalls.map((call) => `${call.command}:${call.status}`),
      ["connect:0", "preview:0"],
    );
    assert.ok(prepareCalls.every((call) => call.args.includes("--json")));
    assert.ok(prepareCalls.every((call) => call.args.includes("--api-url")));
    assert.ok(prepareCalls.every((call) => call.args.includes(baseUrl)));
    assert.ok(prepareCalls.every((call) => call.args.includes("--space")));
    assert.ok(prepareCalls.every((call) => call.args.includes(spaceSlug)));
    assert.ok(prepareCalls.every((call) => call.args.includes("--memory_scope")));
    assert.ok(prepareCalls.every((call) => call.args.includes(memoryScopeExternalRef)));
    assert.ok(prepareCalls.every((call) => call.args.includes("--root-folder")));
    assert.ok(prepareCalls.every((call) => call.args.includes(rootFolder)));
    assert.ok(prepareCalls.every((call) => call.args.includes("--layout")));
    assert.ok(prepareCalls.every((call) => call.args.includes("v2")));

    const snapshot = await infinityContextSnapshot();
    assert.equal(snapshot.busyLabel, "");
    assert.equal(snapshot.lastStackCommand, "status");
    assert.equal(snapshot.lastStackResult.exitCode, 0);
    assert.equal(snapshot.lastStackResult.payload.health.status_code, 200);
    assert.equal(snapshot.lastCommand, "preview");
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.ok(snapshot.lastResult.payload.export.would_export >= 1);
    assert.equal(snapshot.readmeExists, true);
    assert.equal(snapshot.generatedFactsExists, true);
    assert.equal(snapshot.inboxExists, true);
    assert.equal(snapshot.conflictsExists, true);

    assert.match(readVaultFile(vaultPath, path.join(rootFolder, "README.md")), /Infinity Context/);
    assert.match(readVaultFile(vaultPath, path.join(scopedRoot, "inbox", "README.md")), /Inbox/);
    assert.match(readVaultFile(vaultPath, path.join(scopedRoot, "conflicts", "README.md")), /Conflicts/);
    assert.equal(factFiles(vaultPath).length, 0, "prepare preview must not export facts");
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO prepare visible fact.");

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(
      calls.map((call) => `${call.command}:${call.status}`),
      ["connect:0", "preview:0", "sync:0"],
    );
    const exportedFact = onlyFactFile(vaultPath);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /Obsidian WDIO prepare visible fact/);
  });

  it("recovers prepare after the local stack becomes ready", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO prepare delayed stack fact.",
      sourceId: "wdio-delayed-prepare-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    await setLocalEnv({ INFINITY_CONTEXT_FAKE_LOCAL_STATUS_READY: "false" });

    await browser.executeObsidianCommand("infinity-context:prepare-vault");
    await waitForLocalStackCalls(vaultPath, 2);
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();

    let localCalls = readLocalStackCalls(vaultPath);
    let connectorCalls = readCliCalls(vaultPath);
    assert.deepEqual(
      localCalls.map((call) => `${call.command}:${call.status}`),
      ["init:0", "status:0"],
    );
    assert.deepEqual(
      connectorCalls.map((call) => `${call.command}:${call.status}`),
      ["connect:0"],
    );
    let snapshot = await infinityContextSnapshot();
    assert.equal(snapshot.lastStackCommand, "status");
    assert.equal(snapshot.lastStackResult.exitCode, 0);
    assert.equal(snapshot.lastStackResult.payload.health.status_code, 503);
    assert.equal(snapshot.lastCommand, "connect");
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.equal(snapshot.readmeExists, true);
    assert.equal(snapshot.inboxExists, true);
    assert.equal(snapshot.conflictsExists, true);
    assert.equal(factFiles(vaultPath).length, 0, "not-ready prepare must not preview-export facts");

    await setLocalEnv({ INFINITY_CONTEXT_FAKE_LOCAL_STATUS_READY: "true" });
    await browser.executeObsidianCommand("infinity-context:prepare-vault");
    await waitForLocalStackCalls(vaultPath, 4);
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();

    localCalls = readLocalStackCalls(vaultPath);
    connectorCalls = readCliCalls(vaultPath);
    assert.deepEqual(
      localCalls.map((call) => `${call.command}:${call.status}`),
      ["init:0", "status:0", "init:0", "status:0"],
    );
    assert.deepEqual(
      connectorCalls.map((call) => `${call.command}:${call.status}`),
      ["connect:0", "connect:0", "preview:0"],
    );
    snapshot = await infinityContextSnapshot();
    assert.equal(snapshot.lastStackResult.payload.health.status_code, 200);
    assert.equal(snapshot.lastCommand, "preview");
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.ok(snapshot.lastResult.payload.export.would_export >= 1);
    assert.equal(factFiles(vaultPath).length, 0, "recovered prepare preview must not export facts");

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();

    connectorCalls = readCliCalls(vaultPath);
    assert.deepEqual(
      connectorCalls.map((call) => `${call.command}:${call.status}`),
      ["connect:0", "connect:0", "preview:0", "sync:0"],
    );
    const exportedFact = onlyFactFile(vaultPath);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /Obsidian WDIO prepare delayed stack fact/);
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO prepare delayed stack fact.");
  });

  it("recovers prepare after the user fixes a missing local CLI path in settings", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO settings prepare local CLI recovery fact.",
      sourceId: "wdio-settings-prepare-local-cli-recovery-seed",
    });
    const vaultPath = await resetVault();
    const missingLocalCliPath = path.join(tempDir, "missing-infinity-context.cjs");
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "infinity-context"), { recursive: true });

    await openInfinityContextSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("localCliPath", missingLocalCliPath);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", vaultPath);
    await setSettingsInput("rootFolder", rootFolder);
    await setSettingsInput("spaceSlug", spaceSlug);
    await setSettingsInput("memoryScopeExternalRef", memoryScopeExternalRef);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForSettingsFile(vaultPath, missingLocalCliPath);

    await clickSettingsButton("Vault sync", "Prepare");
    await waitForPluginIdle();
    await sleep(500);

    let snapshot = await infinityContextSnapshot();
    assert.equal(snapshot.busyLabel, "");
    assert.equal(snapshot.lastStackCommand, "init");
    assert.equal(snapshot.lastStackResult.exitCode, 1);
    assert.equal(readLocalStackCalls(vaultPath).length, 0);
    assert.equal(readCliCalls(vaultPath).length, 0);
    assert.equal(snapshot.readmeExists, false);
    assert.equal(snapshot.inboxExists, false);
    assert.equal(snapshot.conflictsExists, false);
    assert.equal(factFiles(vaultPath).length, 0);

    await setSettingsInput("localCliPath", fakeLocalCliPath);
    await waitForSettingsFile(vaultPath, fakeLocalCliPath);

    await clickSettingsButton("Vault sync", "Prepare");
    await waitForLocalStackCalls(vaultPath, 2);
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    let localCalls = readLocalStackCalls(vaultPath);
    let connectorCalls = readCliCalls(vaultPath);
    assert.deepEqual(
      localCalls.map((call) => `${call.command}:${call.status}`),
      ["init:0", "status:0"],
    );
    assert.deepEqual(
      connectorCalls.map((call) => `${call.command}:${call.status}`),
      ["connect:0", "preview:0"],
    );
    assert.ok(localCalls.every((call) => call.envToken === token));
    assert.ok(localCalls.every((call) => call.apiUrl === baseUrl));
    assert.ok(connectorCalls.every((call) => call.args.includes(baseUrl)));
    assert.ok(connectorCalls.every((call) => call.args.includes(spaceSlug)));

    snapshot = await infinityContextSnapshot();
    assert.equal(snapshot.lastStackCommand, "status");
    assert.equal(snapshot.lastStackResult.exitCode, 0);
    assert.equal(snapshot.lastCommand, "preview");
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.equal(snapshot.readmeExists, true);
    assert.equal(snapshot.inboxExists, true);
    assert.equal(snapshot.conflictsExists, true);
    assert.equal(factFiles(vaultPath).length, 0, "settings prepare preview must not export facts");

    await clickSettingsButton("Vault sync", "Sync");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();

    connectorCalls = readCliCalls(vaultPath);
    assert.deepEqual(
      connectorCalls.map((call) => `${call.command}:${call.status}`),
      ["connect:0", "preview:0", "sync:0"],
    );
    const exportedFact = onlyFactFile(vaultPath);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /settings prepare local CLI recovery fact/);
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO settings prepare local CLI recovery fact.");
  });
});

async function resetVault(): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nPrepare E2E vault.\n",
  });
  return obsidianPage.getVaultPath();
}

async function resetVaultAndConfigure(apiUrl: string): Promise<string> {
  const vaultPath = await resetVault();
  await configurePlugin(vaultPath, apiUrl);
  return vaultPath;
}

async function configurePlugin(vaultPath: string, apiUrl: string): Promise<void> {
  const settings = {
    apiUrl,
    token,
    localCliPath: fakeLocalCliPath,
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

async function waitForLocalStackCalls(vaultPath: string, count: number): Promise<void> {
  await browser.waitUntil(() => readLocalStackCalls(vaultPath).length >= count, {
    timeout: 20000,
    timeoutMsg: `Expected ${count} local stack CLI calls`,
  });
}

async function waitForPluginIdle(): Promise<void> {
  await browser.waitUntil(async () => (await infinityContextSnapshot()).busyLabel === "", {
    timeout: 20000,
    timeoutMsg: "Infinity Context plugin did not become idle",
  });
}

async function waitForSettingsFile(vaultPath: string, marker: string): Promise<void> {
  const settingsPath = path.join(vaultPath, ".obsidian", "plugins", "infinity-context", "data.json");
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

function onlyFactFile(vaultPath: string): string {
  const files = factFiles(vaultPath);
  assert.equal(files.length, 1);
  return files[0];
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

function readLocalStackCalls(vaultPath: string): Array<{
  command: string;
  args: string[];
  apiUrl: string;
  envToken: string;
  status: number;
}> {
  const logPath = path.join(vaultPath, ".infinity-context/local-stack-calls.jsonl");
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

async function setLocalEnv(values: Record<string, string>): Promise<void> {
  await browser.executeObsidian(
    (_context, payload) => {
      for (const key of payload.keys) {
        delete process.env[key];
      }
      for (const [key, value] of Object.entries(payload.values)) {
        process.env[key] = String(value);
      }
    },
    { keys: localEnvKeys, values },
  );
}

async function clearLocalEnv(): Promise<void> {
  await setLocalEnv({});
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

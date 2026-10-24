import assert from "node:assert/strict";
import crypto from "node:crypto";
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
const realCliPath = path.resolve("test/fixtures/real-infinity-context-obsidian.cjs");
const token = "wdio-packaged-token";
const apiUrl = "http://127.0.0.1:65532";
const spaceSlug = "packaged-project";
const memoryScopeExternalRef = "packaged-memory_scope";
const rootFolder = "Packaged Memo";

describe("Infinity Context packaged plugin install E2E", function () {
  it("loads installed package artifacts after reload and runs connector commands", async function () {
    const obsidianPage = await browser.getObsidianPage();
    const vaultPath = obsidianPage.getVaultPath();

    assertInstalledArtifacts(vaultPath);
    let runtime = await pluginRuntime();
    assert.equal(runtime.loaded, true);
    assert.equal(runtime.enabled, true);
    assert.equal(runtime.manifest.id, pluginId);
    assert.equal(runtime.manifest.name, "Infinity Context");
    assert.deepEqual(runtime.commandIds, [
      "infinity-context:check-daemon-health",
      "infinity-context:connect-vault",
      "infinity-context:local-stack-doctor",
      "infinity-context:local-stack-init",
      "infinity-context:local-stack-status",
      "infinity-context:open-conflicts",
      "infinity-context:open-control-center",
      "infinity-context:open-inbox",
      "infinity-context:open-infinity-context-readme",
      "infinity-context:prepare-vault",
      "infinity-context:preview-sync",
      "infinity-context:run-doctor",
      "infinity-context:start-local-stack-lite",
      "infinity-context:sync-now",
    ]);

    await obsidianPage.resetVault({
      "Welcome.md": "# Welcome\n\nPackaged install E2E vault.\n",
    });
    writeVaultFile(
      vaultPath,
      path.join(".obsidian", "plugins", pluginId, "data.json"),
      JSON.stringify(
        {
          apiUrl,
          token,
          cliPath: fakeCliPath,
          vaultPathOverride: vaultPath,
          spaceSlug,
          memoryScopeExternalRef,
          rootFolder,
          layoutVersion: "v2",
          applyImportOnSync: true,
          commandTimeoutMs: 10000,
        },
        null,
        2,
      ),
    );

    await browser.reloadObsidian();
    await browser.waitUntil(async () => (await pluginRuntime()).snapshot.spaceSlug === spaceSlug, {
      timeout: 20000,
      timeoutMsg: "Infinity Context packaged plugin did not reload persisted settings",
    });

    assertInstalledArtifacts(vaultPath);
    runtime = await pluginRuntime();
    assert.equal(runtime.loaded, true);
    assert.equal(runtime.enabled, true);
    assert.equal(runtime.snapshot.apiUrl, apiUrl);
    assert.equal(runtime.snapshot.spaceSlug, spaceSlug);
    assert.equal(runtime.snapshot.memoryScopeExternalRef, memoryScopeExternalRef);
    assert.equal(runtime.snapshot.rootFolder, rootFolder);

    await obsidianPage.disablePlugin(pluginId);
    await browser.waitUntil(async () => !(await pluginRuntime()).loaded, {
      timeout: 20000,
      timeoutMsg: "Infinity Context packaged plugin did not disable",
    });
    await obsidianPage.enablePlugin(pluginId);
    await browser.waitUntil(async () => (await pluginRuntime()).snapshot.spaceSlug === spaceSlug, {
      timeout: 20000,
      timeoutMsg: "Infinity Context packaged plugin did not enable with persisted settings",
    });

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => `${call.command}:${call.status}`), ["connect:0"]);
    assert.equal(calls[0].envToken, token);
    assert.ok(calls[0].args.includes("--api-url"));
    assert.ok(calls[0].args.includes(apiUrl));
    assert.ok(calls[0].args.includes("--space"));
    assert.ok(calls[0].args.includes(spaceSlug));
    assert.ok(calls[0].args.includes("--memory_scope"));
    assert.ok(calls[0].args.includes(memoryScopeExternalRef));
    assert.ok(calls[0].args.includes("--root-folder"));
    assert.ok(calls[0].args.includes(rootFolder));
    assert.match(readVaultFile(vaultPath, path.join(rootFolder, "README.md")), /Connected by plugin E2E/);

    await browser.executeObsidianCommand("infinity-context:open-control-center");
    const panelOpened = await browser.executeObsidian(({ app }) => {
      return app.workspace.getLeavesOfType("infinity-context-control-center").length === 1;
    });
    assert.equal(panelOpened, true);
  });

  it("loads packaged artifacts and syncs through the real connector and backend", async function () {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "infinity-context-wdio-packaged-real-"));
    const port = await freePort();
    const baseUrl = `http://127.0.0.1:${port}`;
    const server = startInfinityContextServer(path.join(tempDir, "memory.db"), port);

    try {
      await waitForHealth(baseUrl);
      const fact = await createFact(baseUrl, {
        text: "Obsidian WDIO packaged real backend fact.",
        sourceId: "wdio-packaged-real-seed",
      });
      const obsidianPage = await browser.getObsidianPage();
      await obsidianPage.resetVault({
        "Welcome.md": "# Welcome\n\nPackaged real sync E2E vault.\n",
      });
      const vaultPath = obsidianPage.getVaultPath();

      writeVaultFile(
        vaultPath,
        path.join(".obsidian", "plugins", pluginId, "data.json"),
        JSON.stringify(
          {
            apiUrl: baseUrl,
            token,
            cliPath: realCliPath,
            vaultPathOverride: vaultPath,
            spaceSlug,
            memoryScopeExternalRef,
            rootFolder,
            layoutVersion: "v2",
            applyImportOnSync: true,
            commandTimeoutMs: 20000,
          },
          null,
          2,
        ),
      );

      await browser.reloadObsidian();
      await browser.waitUntil(async () => (await pluginRuntime()).snapshot.apiUrl === baseUrl, {
        timeout: 20000,
        timeoutMsg: "Infinity Context packaged plugin did not reload real sync settings",
      });

      assertInstalledArtifacts(vaultPath);
      let runtime = await pluginRuntime();
      assert.equal(runtime.loaded, true);
      assert.equal(runtime.enabled, true);
      assert.equal(runtime.snapshot.spaceSlug, spaceSlug);
      assert.equal(runtime.snapshot.memoryScopeExternalRef, memoryScopeExternalRef);
      assert.equal(runtime.snapshot.rootFolder, rootFolder);

      await browser.executeObsidianCommand("infinity-context:connect-vault");
      await waitForRealCliCalls(vaultPath, 1);
      await waitForPluginIdle();
      await browser.executeObsidianCommand("infinity-context:sync-now");
      await waitForRealCliCalls(vaultPath, 2);
      await waitForPluginIdle();

      const calls = readRealCliCalls(vaultPath);
      assert.deepEqual(calls.map((call) => `${call.command}:${call.status}`), ["connect:0", "sync:0"]);
      assert.ok(calls.every((call) => call.args.includes("--api-url")));
      assert.ok(calls.every((call) => call.args.includes(baseUrl)));
      assert.ok(calls.every((call) => call.args.includes("--space")));
      assert.ok(calls.every((call) => call.args.includes(spaceSlug)));
      assert.ok(calls.every((call) => call.args.includes("--memory_scope")));
      assert.ok(calls.every((call) => call.args.includes(memoryScopeExternalRef)));
      assert.ok(calls.every((call) => call.args.includes("--root-folder")));
      assert.ok(calls.every((call) => call.args.includes(rootFolder)));

      const exportedFact = onlyFactFile(vaultPath);
      assert.match(fs.readFileSync(exportedFact, "utf8"), /packaged real backend fact/);
      assert.match(fs.readFileSync(exportedFact, "utf8"), new RegExp(`infinity_context_id: ${fact.id}`));

      runtime = await pluginRuntime();
      assert.equal(runtime.snapshot.generatedFactsExists, true);
      assert.equal(runtime.snapshot.lastCommand, "sync");
      assert.equal(runtime.snapshot.lastResult.exitCode, 0);
    } finally {
      server.kill("SIGTERM");
      fs.rmSync(tempDir, { recursive: true, force: true });
    }
  });

  it("configures the packaged plugin through settings UI and syncs real backend data", async function () {
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "infinity-context-wdio-packaged-settings-"));
    const port = await freePort();
    const baseUrl = `http://127.0.0.1:${port}`;
    const server = startInfinityContextServer(path.join(tempDir, "memory.db"), port);

    try {
      await waitForHealth(baseUrl);
      const fact = await createFact(baseUrl, {
        text: "Obsidian WDIO packaged settings UI backend fact.",
        sourceId: "wdio-packaged-settings-ui-seed",
      });
      const obsidianPage = await browser.getObsidianPage();
      await obsidianPage.resetVault({
        "Welcome.md": "# Welcome\n\nPackaged settings UI E2E vault.\n",
      });
      const vaultPath = obsidianPage.getVaultPath();

      installPluginArtifacts(vaultPath);
      assertInstalledArtifacts(vaultPath);
      await browser.reloadObsidian();
      await browser.waitUntil(async () => (await pluginRuntime()).loaded, {
        timeout: 20000,
        timeoutMsg: "Infinity Context packaged plugin did not load before settings UI configuration",
      });

      await openInfinityContextSettings();
      await setSettingsInput("apiUrl", baseUrl);
      await setSettingsInput("token", token);
      await setSettingsInput("cliPath", realCliPath);
      await setSettingsInput("vaultPathOverride", vaultPath);
      await setSettingsInput("rootFolder", rootFolder);
      await setSettingsInput("spaceSlug", spaceSlug);
      await setSettingsInput("memoryScopeExternalRef", memoryScopeExternalRef);
      await setSettingsInput("commandTimeoutMs", "20000");
      await setSettingsToggle("applyImportOnSync", true);
      await waitForSettingsFile(vaultPath, baseUrl);
      await waitForSettingsFile(vaultPath, "\"applyImportOnSync\": true");
      await browser.waitUntil(async () => (await pluginRuntime()).snapshot.apiUrl === baseUrl, {
        timeout: 20000,
        timeoutMsg: "Infinity Context packaged plugin did not apply settings UI API URL",
      });

      const inboxMarker = "WDIO packaged settings UI inbox marker imports once";
      writeVaultFile(
        vaultPath,
        path.join(rootFolder, "spaces", spaceSlug, "memory_scopes", memoryScopeExternalRef, "inbox", "settings-ui-inbox.md"),
        inboxMarker,
      );

      await browser.executeObsidianCommand("infinity-context:connect-vault");
      await waitForRealCliCalls(vaultPath, 1);
      await waitForPluginIdle();
      await browser.executeObsidianCommand("infinity-context:sync-now");
      await waitForRealCliCalls(vaultPath, 2);
      await waitForPluginIdle();
      await waitForSuggestionsContaining(baseUrl, inboxMarker, 1);

      let calls = readRealCliCalls(vaultPath);
      assert.deepEqual(calls.map((call) => `${call.command}:${call.status}`), ["connect:0", "sync:0"]);
      assert.ok(calls.every((call) => call.args.includes(baseUrl)));
      assert.ok(calls.every((call) => call.args.includes(spaceSlug)));
      assert.ok(calls.every((call) => call.args.includes(memoryScopeExternalRef)));
      assert.ok(calls.every((call) => call.args.includes(rootFolder)));

      const exportedFact = onlyFactFile(vaultPath);
      assert.match(fs.readFileSync(exportedFact, "utf8"), /packaged settings UI backend fact/);
      assert.match(fs.readFileSync(exportedFact, "utf8"), new RegExp(`infinity_context_id: ${fact.id}`));

      await browser.executeObsidianCommand("infinity-context:sync-now");
      await waitForRealCliCalls(vaultPath, 3);
      await waitForPluginIdle();
      await sleep(300);

      calls = readRealCliCalls(vaultPath);
      assert.deepEqual(calls.map((call) => `${call.command}:${call.status}`), ["connect:0", "sync:0", "sync:0"]);
      assert.equal((await suggestionsContaining(baseUrl, inboxMarker)).length, 1);
      assert.equal(factFiles(vaultPath).length, 1);
    } finally {
      server.kill("SIGTERM");
      fs.rmSync(tempDir, { recursive: true, force: true });
    }
  });
});

function assertInstalledArtifacts(vaultPath: string): void {
  const pluginDir = path.join(vaultPath, ".obsidian", "plugins", pluginId);
  const sourceDir = process.cwd();
  const sourceManifest = readJson(path.join(sourceDir, "manifest.json"));
  const installedManifest = readJson(path.join(pluginDir, "manifest.json"));
  assert.deepEqual(installedManifest, sourceManifest);
  assert.equal(fileHash(path.join(pluginDir, "main.js")), fileHash(path.join(sourceDir, "main.js")));
  assert.equal(fileHash(path.join(pluginDir, "styles.css")), fileHash(path.join(sourceDir, "styles.css")));
  assert.match(fs.readFileSync(path.join(pluginDir, "main.js"), "utf8"), /Infinity Context Obsidian plugin/);

  const communityPlugins = readJson(path.join(vaultPath, ".obsidian", "community-plugins.json"));
  assert.ok(Array.isArray(communityPlugins));
  assert.ok(communityPlugins.includes(pluginId));
}

async function pluginRuntime(): Promise<{
  loaded: boolean;
  enabled: boolean;
  manifest: Record<string, any>;
  commandIds: string[];
  snapshot: any;
}> {
  return await browser.executeObsidian(({ app, plugins }) => {
    const plugin = (plugins as any).infinityContext as any;
    const enabledPlugins = Array.from(((app as any).plugins.enabledPlugins ?? []) as Iterable<string>);
    return {
      loaded: Boolean(plugin),
      enabled: enabledPlugins.includes("infinity-context"),
      manifest: (app as any).plugins.manifests["infinity-context"] ?? {},
      commandIds: Object.keys((app as any).commands.commands)
        .filter((id) => id.startsWith("infinity-context:"))
        .sort(),
      snapshot: plugin?.snapshot?.() ?? {},
    };
  });
}

async function waitForPluginIdle(): Promise<void> {
  await browser.waitUntil(async () => (await pluginRuntime()).snapshot.busyLabel === "", {
    timeout: 20000,
    timeoutMsg: "Infinity Context packaged plugin did not become idle",
  });
}

async function waitForCliCalls(vaultPath: string, count: number): Promise<void> {
  await browser.waitUntil(() => readCliCalls(vaultPath).length >= count, {
    timeout: 10000,
    timeoutMsg: `Expected ${count} packaged plugin CLI calls`,
  });
}

async function waitForRealCliCalls(vaultPath: string, count: number): Promise<void> {
  await browser.waitUntil(() => readRealCliCalls(vaultPath).length >= count, {
    timeout: 20000,
    timeoutMsg: `Expected ${count} packaged real connector calls`,
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

async function waitForHealth(baseUrl: string): Promise<void> {
  await waitUntil(async () => {
    try {
      const response = await requestJson("GET", `${baseUrl}/v1/health`);
      return response.status === 200;
    } catch (_error) {
      return false;
    }
  }, "Infinity Context server did not become healthy");
}

async function createFact(
  baseUrl: string,
  { text, sourceId }: { text: string; sourceId: string },
): Promise<Record<string, any>> {
  const response = await requestJson("POST", `${baseUrl}/v1/facts`, {
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

async function waitForSuggestionsContaining(
  baseUrl: string,
  marker: string,
  count: number,
): Promise<void> {
  await waitUntil(
    async () => (await suggestionsContaining(baseUrl, marker)).length >= count,
    "Suggestion was not created",
  );
}

async function suggestionsContaining(baseUrl: string, marker: string): Promise<Record<string, any>[]> {
  const query = new URLSearchParams({
    space_slug: spaceSlug,
    memory_scope_external_ref: memoryScopeExternalRef,
    status: "pending",
  });
  const response = await requestJson("GET", `${baseUrl}/v1/suggestions?${query.toString()}`);
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
  writeVaultFile(vaultPath, path.join(".obsidian", "community-plugins.json"), JSON.stringify([pluginId], null, 2));
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
    rootFolder,
    "spaces",
    spaceSlug,
    "memory_scopes",
    memoryScopeExternalRef,
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

function readJson(filePath: string): any {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function fileHash(filePath: string): string {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
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

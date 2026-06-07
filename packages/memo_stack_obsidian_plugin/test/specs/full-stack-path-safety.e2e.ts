import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import { browser } from "@wdio/globals";

const repoRoot = path.resolve("../../");
const realCliPath = path.resolve("test/fixtures/real-memo-stack-obsidian.cjs");
const token = "wdio-path-safety-token";
const spaceSlug = "wdio-path-safety";
const unsafeSpaceSlug = "unsafe\u200bproject";
const profileExternalRef = "default";
const rootFolder = "Safe Team Memory";
const scopedRoot = path.join(rootFolder, "spaces", spaceSlug, "profiles", profileExternalRef);

describe("Memo Stack path safety E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "memo-stack-wdio-path-safety-"));
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    server = startMemoStackServer(path.join(tempDir, "memory.db"), port);
    await waitForHealth(baseUrl);
  });

  afterEach(function () {
    server?.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  it("blocks unsafe settings before the connector runs and recovers after the user fixes them", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO path safety exported backend fact.",
      sourceId: "wdio-path-safety-seed",
    });
    const vaultPath = await resetVault();
    const outsideVaultRoot = path.join(tempDir, "outside-vault-memory");
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "memo-stack"), { recursive: true });

    await openMemoStackSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", vaultPath);
    await setSettingsInput("rootFolder", outsideVaultRoot);
    await setSettingsInput("spaceSlug", spaceSlug);
    await setSettingsInput("profileExternalRef", profileExternalRef);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForPathError(/Folder must be relative to the vault/);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForPluginIdle();
    await sleep(500);

    let snapshot = await memoStackSnapshot();
    assert.match(snapshot.pathError, /Folder must be relative to the vault/);
    assert.equal(snapshot.lastCommand, null);
    assert.equal(readCliCalls(vaultPath).length, 0);
    assert.equal(factFiles(vaultPath).length, 0);
    assert.equal(fs.existsSync(outsideVaultRoot), false);

    await setSettingsInput("rootFolder", rootFolder);
    await waitForPathReady(rootFolder, spaceSlug);
    await setSettingsInput("spaceSlug", unsafeSpaceSlug);
    await waitForPathError(/Project or profile contains unsafe formatting characters/);

    await clickSettingsButton("Vault sync", "Sync");
    await waitForPluginIdle();
    await sleep(500);

    snapshot = await memoStackSnapshot();
    assert.match(snapshot.pathError, /Project or profile contains unsafe formatting characters/);
    assert.equal(snapshot.lastCommand, null);
    assert.equal(readCliCalls(vaultPath).length, 0);
    assert.equal(factFiles(vaultPath).length, 0);

    await setSettingsInput("spaceSlug", spaceSlug);
    await waitForPathReady(rootFolder, spaceSlug);
    await waitForSettingsFile(vaultPath, rootFolder);
    await waitForSettingsFile(vaultPath, spaceSlug);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await clickSettingsButton("Vault sync", "Sync");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const exportedFact = factFileForId(vaultPath, fact.id);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /path safety exported backend fact/);

    snapshot = await memoStackSnapshot();
    assert.equal(snapshot.pathError, "");
    assert.equal(snapshot.rootFolder, rootFolder);
    assert.equal(snapshot.spaceSlug, spaceSlug);
    assert.equal(snapshot.profileExternalRef, profileExternalRef);
    assert.equal(snapshot.generatedFactsExists, true);
    assert.equal(snapshot.paths.generatedFacts, posixPath(path.join(scopedRoot, "generated", "facts")));

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync"]);
    assert.ok(calls.every((call) => call.status === 0));
    assert.ok(calls.every((call) => call.args.includes(rootFolder)));
    assert.ok(calls.every((call) => call.args.includes(spaceSlug)));
    assert.ok(calls.every((call) => call.args.includes(profileExternalRef)));
    assert.ok(calls.every((call) => !call.args.includes(outsideVaultRoot)));
    assert.ok(calls.every((call) => !call.args.includes(unsafeSpaceSlug)));
  });

  it("disables Control Center vault actions until the user fixes an unsafe path", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO path safety Control Center backend fact.",
      sourceId: "wdio-path-safety-control-center-seed",
    });
    const vaultPath = await resetVault();
    const outsideVaultRoot = path.join(tempDir, "outside-control-center-memory");
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "memo-stack"), { recursive: true });

    await openMemoStackSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", vaultPath);
    await setSettingsInput("rootFolder", outsideVaultRoot);
    await setSettingsInput("spaceSlug", spaceSlug);
    await setSettingsInput("profileExternalRef", profileExternalRef);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForPathError(/Folder must be relative to the vault/);

    await openMemoStackControlCenter();
    await waitForVaultActionDisabled("Connect", true);
    await waitForVaultActionDisabled("Preview", true);
    await waitForVaultActionDisabled("Sync", true);
    assert.equal(readCliCalls(vaultPath).length, 0);

    await openMemoStackSettings();
    await setSettingsInput("rootFolder", rootFolder);
    await waitForPathReady(rootFolder, spaceSlug);
    await openMemoStackControlCenter();
    await waitForVaultActionDisabled("Connect", false);
    await waitForVaultActionDisabled("Preview", false);
    await waitForVaultActionDisabled("Sync", false);

    await clickVaultActionButton("Connect");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await clickVaultActionButton("Sync");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const exportedFact = factFileForId(vaultPath, fact.id);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /path safety Control Center backend fact/);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync"]);
    assert.ok(calls.every((call) => call.status === 0));
  });

  it("recovers after the user fixes a missing connector CLI path in settings", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO connector path recovery backend fact.",
      sourceId: "wdio-connector-path-recovery-seed",
    });
    const vaultPath = await resetVault();
    const missingCliPath = path.join(tempDir, "missing-memo-stack-obsidian.cjs");
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "memo-stack"), { recursive: true });

    await openMemoStackSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", missingCliPath);
    await setSettingsInput("vaultPathOverride", vaultPath);
    await setSettingsInput("rootFolder", rootFolder);
    await setSettingsInput("spaceSlug", spaceSlug);
    await setSettingsInput("profileExternalRef", profileExternalRef);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForPathReady(rootFolder, spaceSlug);

    await clickSettingsButton("Vault sync", "Sync");
    await waitForPluginIdle();
    await sleep(500);

    let snapshot = await memoStackSnapshot();
    assert.equal(snapshot.pathError, "");
    assert.equal(snapshot.lastCommand, "sync");
    assert.equal(snapshot.lastResult.exitCode, 1);
    assert.equal(readCliCalls(vaultPath).length, 0);
    assert.equal(factFiles(vaultPath).length, 0);

    await setSettingsInput("cliPath", realCliPath);
    await waitForSettingsFile(vaultPath, realCliPath);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await clickSettingsButton("Vault sync", "Sync");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const exportedFact = factFileForId(vaultPath, fact.id);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /connector path recovery backend fact/);

    snapshot = await memoStackSnapshot();
    assert.equal(snapshot.lastCommand, "sync");
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.equal(snapshot.generatedFactsExists, true);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync"]);
    assert.ok(calls.every((call) => call.status === 0));
    assert.ok(calls.every((call) => call.args.includes(rootFolder)));
    assert.ok(calls.every((call) => call.args.includes(spaceSlug)));
    assert.ok(calls.every((call) => call.args.includes(profileExternalRef)));
  });

  it("uses the current Obsidian vault when the vault path override is blank", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO default vault path backend fact.",
      sourceId: "wdio-default-vault-path-seed",
    });
    const vaultPath = await resetVault();
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "memo-stack"), { recursive: true });

    await openMemoStackSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", "");
    await setSettingsInput("rootFolder", rootFolder);
    await setSettingsInput("spaceSlug", spaceSlug);
    await setSettingsInput("profileExternalRef", profileExternalRef);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForPathReady(rootFolder, spaceSlug);

    let snapshot = await memoStackSnapshot();
    assert.equal(snapshot.vaultPath, vaultPath);
    assert.equal(snapshot.pathError, "");

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await clickSettingsButton("Vault sync", "Sync");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const exportedFact = factFileForId(vaultPath, fact.id);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /default vault path backend fact/);

    snapshot = await memoStackSnapshot();
    assert.equal(snapshot.vaultPath, vaultPath);
    assert.equal(snapshot.generatedFactsExists, true);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync"]);
    assert.ok(calls.every((call) => call.status === 0));
    assert.ok(calls.every((call) => valueAfter(call.args, "--vault") === vaultPath));
    assert.ok(calls.every((call) => call.args.includes(rootFolder)));
    assert.ok(calls.every((call) => call.args.includes(spaceSlug)));
    assert.ok(calls.every((call) => call.args.includes(profileExternalRef)));
  });

  it("recovers when a wrong existing vault path override sends sync to another folder", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO wrong vault override recovery backend fact.",
      sourceId: "wdio-wrong-vault-override-seed",
    });
    const vaultPath = await resetVault();
    const wrongVaultPath = path.join(tempDir, "wrong-vault-override");
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "memo-stack"), { recursive: true });
    fs.mkdirSync(wrongVaultPath, { recursive: true });

    await openMemoStackSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", wrongVaultPath);
    await setSettingsInput("rootFolder", rootFolder);
    await setSettingsInput("spaceSlug", spaceSlug);
    await setSettingsInput("profileExternalRef", profileExternalRef);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForSettingsFile(vaultPath, wrongVaultPath);
    await waitForVaultPath(wrongVaultPath);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(wrongVaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(wrongVaultPath, 2);
    await waitForPluginIdle();

    let snapshot = await memoStackSnapshot();
    assert.equal(snapshot.vaultPath, wrongVaultPath);
    assert.equal(snapshot.pathError, "");
    assert.equal(snapshot.generatedFactsExists, false);
    assert.equal(readCliCalls(vaultPath).length, 0);
    assert.equal(factFiles(vaultPath).length, 0);

    let wrongFact = factFileForId(wrongVaultPath, fact.id);
    assert.match(fs.readFileSync(wrongFact, "utf8"), /wrong vault override recovery backend fact/);
    assert.deepEqual(readCliCalls(wrongVaultPath).map((call) => call.command), ["connect", "sync"]);
    assert.ok(readCliCalls(wrongVaultPath).every((call) => valueAfter(call.args, "--vault") === wrongVaultPath));

    await openMemoStackSettings();
    await setSettingsInput("vaultPathOverride", "");
    await waitForVaultPath(vaultPath);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const currentFact = factFileForId(vaultPath, fact.id);
    assert.match(fs.readFileSync(currentFact, "utf8"), /wrong vault override recovery backend fact/);
    wrongFact = factFileForId(wrongVaultPath, fact.id);
    assert.match(fs.readFileSync(wrongFact, "utf8"), /wrong vault override recovery backend fact/);
    assert.equal(factFiles(vaultPath).length, 1);
    assert.equal(factFiles(wrongVaultPath).length, 1);

    snapshot = await memoStackSnapshot();
    assert.equal(snapshot.vaultPath, vaultPath);
    assert.equal(snapshot.generatedFactsExists, true);

    await browser.executeObsidianCommand("memo-stack:open-inbox");
    assert.equal(await activeFilePath(), posixPath(path.join(scopedRoot, "inbox", "README.md")));

    const currentCalls = readCliCalls(vaultPath);
    assert.deepEqual(currentCalls.map((call) => call.command), ["connect", "sync"]);
    assert.ok(currentCalls.every((call) => valueAfter(call.args, "--vault") === vaultPath));
    assert.ok(currentCalls.every((call) => call.status === 0));
  });

  it("keeps current vault sync after reload when the vault path override is blank", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO blank override reload backend fact.",
      sourceId: "wdio-blank-override-reload-seed",
    });
    const vaultPath = await resetVault();
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "memo-stack"), { recursive: true });

    await openMemoStackSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", "");
    await setSettingsInput("rootFolder", rootFolder);
    await setSettingsInput("spaceSlug", spaceSlug);
    await setSettingsInput("profileExternalRef", profileExternalRef);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForPathReady(rootFolder, spaceSlug);
    await waitForSettingsFile(vaultPath, rootFolder);

    await browser.reloadObsidian();
    await waitForPathReady(rootFolder, spaceSlug);

    let snapshot = await memoStackSnapshot();
    assert.equal(snapshot.vaultPath, vaultPath);
    assert.equal(snapshot.pathError, "");
    assert.equal(readCliCalls(vaultPath).length, 0);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const exportedFact = factFileForId(vaultPath, fact.id);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /blank override reload backend fact/);

    snapshot = await memoStackSnapshot();
    assert.equal(snapshot.vaultPath, vaultPath);
    assert.equal(snapshot.generatedFactsExists, true);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync"]);
    assert.ok(calls.every((call) => call.status === 0));
    assert.ok(calls.every((call) => valueAfter(call.args, "--vault") === vaultPath));
  });
});

async function resetVault(): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nPath safety E2E vault.\n",
  });
  return obsidianPage.getVaultPath();
}

function startMemoStackServer(dbPath: string, port: number): ChildProcess {
  const code = `
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.main import create_app
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
  }, "Memo Stack server did not become healthy");
}

async function createFact(
  apiUrl: string,
  { text, sourceId }: { text: string; sourceId: string },
): Promise<Record<string, any>> {
  const response = await requestJson("POST", `${apiUrl}/v1/facts`, {
    space_slug: spaceSlug,
    profile_external_ref: profileExternalRef,
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
  await browser.waitUntil(async () => (await memoStackSnapshot()).busyLabel === "", {
    timeout: 20000,
    timeoutMsg: "Memo Stack plugin did not become idle",
  });
}

async function waitForPathError(pattern: RegExp): Promise<void> {
  await browser.waitUntil(
    async () => {
      try {
        return pattern.test((await memoStackSnapshot()).pathError);
      } catch (_error) {
        return false;
      }
    },
    {
      timeout: 20000,
      timeoutMsg: `Memo Stack plugin did not show path error ${pattern}`,
    },
  );
}

async function waitForPathReady(expectedRoot: string, expectedSpace: string): Promise<void> {
  await browser.waitUntil(
    async () => {
      try {
        const snapshot = await memoStackSnapshot();
        return (
          snapshot.pathError === "" &&
          snapshot.rootFolder === expectedRoot &&
          snapshot.spaceSlug === expectedSpace
        );
      } catch (_error) {
        return false;
      }
    },
    {
      timeout: 20000,
      timeoutMsg: `Memo Stack plugin did not accept path ${expectedRoot}/${expectedSpace}`,
    },
  );
}

async function waitForVaultPath(expectedVaultPath: string): Promise<void> {
  await browser.waitUntil(
    async () => {
      try {
        const snapshot = await memoStackSnapshot();
        return snapshot.pathError === "" && snapshot.vaultPath === expectedVaultPath;
      } catch (_error) {
        return false;
      }
    },
    {
      timeout: 20000,
      timeoutMsg: `Memo Stack plugin did not use vault path ${expectedVaultPath}`,
    },
  );
}

async function waitForSettingsFile(vaultPath: string, marker: string): Promise<void> {
  const settingsPath = path.join(vaultPath, ".obsidian", "plugins", "memo-stack", "data.json");
  await waitUntil(
    async () => fs.existsSync(settingsPath) && fs.readFileSync(settingsPath, "utf8").includes(marker),
    `Memo Stack settings UI did not persist ${marker}`,
  );
}

async function openMemoStackSettings(): Promise<void> {
  await browser.executeObsidian(({ app }) => {
    const setting = (app as any).setting;
    setting.open();
    setting.openTabById("memo-stack");
  });
  await browser.waitUntil(
    async () =>
      await browser.execute(() =>
        Boolean(document.querySelector('input[data-memo-stack-setting="apiUrl"]')),
      ),
    {
      timeout: 20000,
      timeoutMsg: "Memo Stack settings UI did not open",
    },
  );
}

async function openMemoStackControlCenter(): Promise<void> {
  await browser.executeObsidianCommand("memo-stack:open-control-center");
  await browser.waitUntil(
    async () =>
      await browser.execute(() =>
        Boolean(document.querySelector(".memo-stack-panel .memo-stack-vault-actions")),
      ),
    {
      timeout: 20000,
      timeoutMsg: "Memo Stack Control Center did not open",
    },
  );
}

async function setSettingsInput(name: string, value: string): Promise<void> {
  const changed = await browser.execute(
    (settingName, nextValue) => {
      const input = document.querySelector<HTMLInputElement>(
        `input[data-memo-stack-setting="${settingName}"]`,
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
  assert.equal(changed, true, `Could not change Memo Stack settings input ${name}`);
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
  assert.equal(clicked, true, `Could not click Memo Stack settings button ${settingName}/${buttonText}`);
}

async function waitForVaultActionDisabled(buttonText: string, expected: boolean): Promise<void> {
  await browser.waitUntil(
    async () => {
      const state = await vaultActionButtonState(buttonText);
      return state.exists && state.disabled === expected;
    },
    {
      timeout: 20000,
      timeoutMsg: `Memo Stack Control Center button ${buttonText} disabled state did not become ${expected}`,
    },
  );
}

async function clickVaultActionButton(buttonText: string): Promise<void> {
  const clicked = await browser.execute((nextButtonText) => {
    const buttons = Array.from(
      document.querySelectorAll<HTMLButtonElement>(".memo-stack-vault-actions button"),
    );
    const button = buttons.find((candidate) => candidate.innerText.trim() === nextButtonText);
    if (!button || button.disabled) {
      return false;
    }
    button.click();
    return true;
  }, buttonText);
  assert.equal(clicked, true, `Could not click Memo Stack Control Center button ${buttonText}`);
}

async function vaultActionButtonState(buttonText: string): Promise<{ exists: boolean; disabled: boolean }> {
  return await browser.execute((nextButtonText) => {
    const buttons = Array.from(
      document.querySelectorAll<HTMLButtonElement>(".memo-stack-vault-actions button"),
    );
    const button = buttons.find((candidate) => candidate.innerText.trim() === nextButtonText);
    return {
      exists: Boolean(button),
      disabled: button?.disabled ?? false,
    };
  }, buttonText);
}

async function memoStackSnapshot(): Promise<any> {
  return await browser.executeObsidian(({ plugins }) => {
    return (plugins.memoStack as any).snapshot();
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
    fs.readFileSync(filePath, "utf8").includes(`memo_stack_id: ${factId}`),
  );
  assert.equal(files.length, 1);
  return files[0];
}

function readCliCalls(vaultPath: string): Array<{ command: string; args: string[]; status: number }> {
  const logPath = path.join(vaultPath, ".memo-stack/real-plugin-cli-calls.jsonl");
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

function valueAfter(args: string[], flag: string): string {
  const index = args.indexOf(flag);
  assert.ok(index >= 0, `Missing argument ${flag}`);
  assert.ok(index + 1 < args.length, `Missing value after ${flag}`);
  return args[index + 1];
}

function pythonpath(): string {
  return [
    "packages/memo_stack_core",
    "packages/memo_stack_adapters",
    "packages/memo_stack_server",
    "packages/memo_stack_sdk",
    "packages/memo_stack_obsidian",
  ]
    .map((relativePath) => path.join(repoRoot, relativePath))
    .join(path.delimiter);
}

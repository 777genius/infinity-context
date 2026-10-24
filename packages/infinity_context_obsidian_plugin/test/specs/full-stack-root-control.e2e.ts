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
const token = "wdio-root-control-token";
const spaceSlug = "wdio-root-control";
const memoryScopeExternalRef = "default";
const primaryRoot = "Team Memory";
const secondaryRoot = "Client Knowledge/Research Notes";
const textStart = "<!-- infinity-context-managed:fact-text:start -->";
const textEnd = "<!-- infinity-context-managed:fact-text:end -->";

describe("Infinity Context root folder control E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "infinity-context-wdio-root-control-"));
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    server = startInfinityContextServer(path.join(tempDir, "memory.db"), port);
    await waitForHealth(baseUrl);
  });

  afterEach(function () {
    server?.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  it("moves sync output to a new settings UI root without mixing old and new folders", async function () {
    const primaryFact = await createFact(baseUrl, {
      text: "Obsidian WDIO primary root backend fact.",
      sourceId: "wdio-root-primary-seed",
    });
    const vaultPath = await resetVault();
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "infinity-context"), { recursive: true });

    await openInfinityContextSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", vaultPath);
    await setSettingsInput("rootFolder", primaryRoot);
    await setSettingsInput("spaceSlug", spaceSlug);
    await setSettingsInput("memoryScopeExternalRef", memoryScopeExternalRef);
    await setSettingsToggle("applyImportOnSync", true);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForPluginRoot(primaryRoot);

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const primaryFactFile = factFileForId(vaultPath, primaryRoot, primaryFact.id);
    assert.match(fs.readFileSync(primaryFactFile, "utf8"), /primary root backend fact/);
    assert.equal(factFiles(vaultPath, primaryRoot).length, 1);
    assert.equal(fs.existsSync(path.join(vaultPath, secondaryRoot)), false);

    const primaryInboxMarker = "WDIO primary root inbox marker";
    writeVaultFile(
      vaultPath,
      path.join(scopedRootFor(primaryRoot), "inbox", "primary-root-inbox.md"),
      primaryInboxMarker,
    );
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, primaryInboxMarker, 1);

    await openInfinityContextSettings();
    await setSettingsInput("rootFolder", secondaryRoot);
    await waitForPluginRoot(secondaryRoot);
    await waitForSettingsFile(vaultPath, secondaryRoot);
    const secondaryFact = await createFact(baseUrl, {
      text: "Obsidian WDIO secondary root backend fact.",
      sourceId: "wdio-root-secondary-seed",
    });

    let snapshot = await infinityContextSnapshot();
    assert.equal(snapshot.rootFolder, secondaryRoot);
    assert.equal(snapshot.paths.generatedFacts, posixPath(path.join(scopedRootFor(secondaryRoot), "generated", "facts")));
    assert.equal(snapshot.generatedFactsExists, false);
    assert.equal(factFiles(vaultPath, primaryRoot).length, 1);

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 5);
    await waitForPluginIdle();

    assert.equal(factFiles(vaultPath, primaryRoot).length, 1);
    assert.equal(factFiles(vaultPath, secondaryRoot).length, 2);
    assert.match(fs.readFileSync(factFileForId(vaultPath, secondaryRoot, primaryFact.id), "utf8"), /primary root backend fact/);
    assert.match(fs.readFileSync(factFileForId(vaultPath, secondaryRoot, secondaryFact.id), "utf8"), /secondary root backend fact/);
    assert.equal(conflictFiles(vaultPath, primaryRoot).length, 0);
    assert.equal(conflictFiles(vaultPath, secondaryRoot).length, 0);

    const secondaryInboxMarker = "WDIO secondary root inbox marker";
    writeVaultFile(
      vaultPath,
      path.join(scopedRootFor(secondaryRoot), "inbox", "secondary-root-inbox.md"),
      secondaryInboxMarker,
    );
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 6);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, secondaryInboxMarker, 1);
    assert.equal((await suggestionsContaining(baseUrl, primaryInboxMarker)).length, 1);

    await browser.executeObsidianCommand("infinity-context:open-inbox");
    assert.equal(await activeFilePath(), posixPath(path.join(scopedRootFor(secondaryRoot), "inbox", "README.md")));
    snapshot = await infinityContextSnapshot();
    assert.equal(snapshot.inboxExists, true);
    assert.equal(snapshot.conflictsExists, true);
    assert.equal(snapshot.paths.conflicts, posixPath(path.join(scopedRootFor(secondaryRoot), "conflicts")));

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync", "sync", "connect", "sync", "sync"]);
    assertCallsUseRoot(calls.slice(0, 3), primaryRoot);
    assertCallsUseRoot(calls.slice(3), secondaryRoot);
    assert.ok(calls.every((call) => call.args.includes("--space")));
    assert.ok(calls.every((call) => call.args.includes(spaceSlug)));
    assert.ok(calls.every((call) => call.args.includes("--memory_scope")));
    assert.ok(calls.every((call) => call.args.includes(memoryScopeExternalRef)));
    assert.ok(calls.every((call) => call.status === 0));
  });

  it("preserves unsynced old-root edits and inbox notes across root switches", async function () {
    const initialText = "Obsidian WDIO root switch pending initial fact.";
    const recoveredText = "Obsidian WDIO root switch pending local edit recovered.";
    const fact = await createFact(baseUrl, {
      text: initialText,
      sourceId: "wdio-root-switch-pending-seed",
    });
    const vaultPath = await resetVault();
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "infinity-context"), { recursive: true });

    await openInfinityContextSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", vaultPath);
    await setSettingsInput("rootFolder", primaryRoot);
    await setSettingsInput("spaceSlug", spaceSlug);
    await setSettingsInput("memoryScopeExternalRef", memoryScopeExternalRef);
    await setSettingsToggle("applyImportOnSync", true);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForPluginRoot(primaryRoot);

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const primaryFactFile = factFileForId(vaultPath, primaryRoot, fact.id);
    replaceManagedText(primaryFactFile, recoveredText);
    const primaryInboxMarker = "WDIO root switch pending inbox imports only after return";
    writeVaultFile(
      vaultPath,
      path.join(scopedRootFor(primaryRoot), "inbox", "root-switch-pending-inbox.md"),
      primaryInboxMarker,
    );

    await openInfinityContextSettings();
    await setSettingsInput("rootFolder", secondaryRoot);
    await waitForPluginRoot(secondaryRoot);
    await waitForSettingsFile(vaultPath, secondaryRoot);
    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();

    assert.equal((await getFact(baseUrl, fact.id)).text, initialText);
    assert.equal((await suggestionsContaining(baseUrl, primaryInboxMarker)).length, 0);
    assert.match(fs.readFileSync(primaryFactFile, "utf8"), new RegExp(recoveredText));
    assert.match(fs.readFileSync(factFileForId(vaultPath, secondaryRoot, fact.id), "utf8"), new RegExp(initialText));
    assert.equal(conflictFiles(vaultPath, primaryRoot).length, 0);
    assert.equal(conflictFiles(vaultPath, secondaryRoot).length, 0);

    await openInfinityContextSettings();
    await setSettingsInput("rootFolder", primaryRoot);
    await waitForPluginRoot(primaryRoot);
    await waitForSettingsFile(vaultPath, primaryRoot);
    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 5);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 6);
    await waitForPluginIdle();
    await waitForBackendFactText(baseUrl, fact.id, recoveredText);
    await waitForSuggestionsContaining(baseUrl, primaryInboxMarker, 1);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 7);
    await waitForPluginIdle();
    await sleep(300);
    assert.equal((await suggestionsContaining(baseUrl, primaryInboxMarker)).length, 1);
    assert.match(fs.readFileSync(factFileForId(vaultPath, primaryRoot, fact.id), "utf8"), /infinity_context_version: 2/);

    await openInfinityContextSettings();
    await setSettingsInput("rootFolder", secondaryRoot);
    await waitForPluginRoot(secondaryRoot);
    await waitForSettingsFile(vaultPath, secondaryRoot);
    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 8);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 9);
    await waitForPluginIdle();

    const secondaryFactFile = factFileForId(vaultPath, secondaryRoot, fact.id);
    assert.match(fs.readFileSync(secondaryFactFile, "utf8"), new RegExp(recoveredText));
    assert.match(fs.readFileSync(secondaryFactFile, "utf8"), /infinity_context_version: 2/);
    assert.equal(conflictFiles(vaultPath, primaryRoot).length, 0);
    assert.equal(conflictFiles(vaultPath, secondaryRoot).length, 0);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(
      calls.map((call) => call.command),
      ["connect", "sync", "connect", "sync", "connect", "sync", "sync", "connect", "sync"],
    );
    assertCallsUseRoot(calls.slice(0, 2), primaryRoot);
    assertCallsUseRoot(calls.slice(2, 4), secondaryRoot);
    assertCallsUseRoot(calls.slice(4, 7), primaryRoot);
    assertCallsUseRoot(calls.slice(7), secondaryRoot);
    assert.ok(calls.every((call) => call.status === 0));
  });

  it("uses the legacy flat layout when selected through settings", async function () {
    const legacyRoot = "Legacy Flat Memory";
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO legacy flat layout backend fact.",
      sourceId: "wdio-root-legacy-layout-seed",
    });
    const vaultPath = await resetVault();
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "infinity-context"), { recursive: true });

    await openInfinityContextSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", vaultPath);
    await setSettingsInput("rootFolder", legacyRoot);
    await setSettingsDropdown("Layout", "v1");
    await setSettingsInput("spaceSlug", spaceSlug);
    await setSettingsInput("memoryScopeExternalRef", memoryScopeExternalRef);
    await setSettingsToggle("applyImportOnSync", true);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForPluginRoot(legacyRoot);
    await waitForPluginLayout("v1");
    await waitForSettingsFile(vaultPath, '"layoutVersion": "v1"');

    await browser.executeObsidianCommand("infinity-context:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await waitForConnectedLegacyLayout(legacyRoot);
    let snapshot = await infinityContextSnapshot();
    assert.equal(snapshot.layoutVersion, "v1");
    assert.equal(snapshot.paths.generatedFacts, posixPath(path.join(legacyRoot, "generated", "facts")));
    assert.equal(snapshot.paths.inbox, posixPath(path.join(legacyRoot, "inbox")));
    assert.equal(snapshot.paths.conflicts, posixPath(path.join(legacyRoot, "conflicts")));
    assert.equal(snapshot.inboxExists, true);
    assert.equal(fs.existsSync(path.join(vaultPath, scopedRootFor(legacyRoot))), false);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const legacyFactFile = legacyFactFileForId(vaultPath, legacyRoot, fact.id);
    assert.match(fs.readFileSync(legacyFactFile, "utf8"), /legacy flat layout backend fact/);
    assert.match(fs.readFileSync(legacyFactFile, "utf8"), /infinity_context_space_slug: wdio-root-control/);
    assert.equal(factFiles(vaultPath, legacyRoot).length, 0);

    const inboxMarker = "WDIO legacy flat layout inbox marker";
    writeVaultFile(vaultPath, path.join(legacyRoot, "inbox", "legacy-flat-inbox.md"), inboxMarker);
    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, inboxMarker, 1);

    await browser.executeObsidianCommand("infinity-context:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await sleep(300);
    assert.equal((await suggestionsContaining(baseUrl, inboxMarker)).length, 1);

    await browser.executeObsidianCommand("infinity-context:open-inbox");
    assert.equal(await activeFilePath(), posixPath(path.join(legacyRoot, "inbox", "README.md")));
    await browser.executeObsidianCommand("infinity-context:open-conflicts");
    assert.equal(await activeFilePath(), posixPath(path.join(legacyRoot, "conflicts", "README.md")));

    snapshot = await infinityContextSnapshot();
    assert.equal(snapshot.layoutVersion, "v1");
    assert.equal(legacyConflictFiles(vaultPath, legacyRoot).length, 0);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync", "sync", "sync"]);
    assertCallsUseRoot(calls, legacyRoot);
    assert.ok(calls.every((call) => call.args.includes("--layout")));
    assert.ok(calls.every((call) => call.args.includes("v1")));
    assert.ok(calls.every((call) => call.status === 0));
  });
});

async function resetVault(): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nRoot control E2E vault.\n",
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

async function waitForPluginRoot(rootFolder: string): Promise<void> {
  await browser.waitUntil(
    async () => {
      try {
        const snapshot = await infinityContextSnapshot();
        return snapshot.rootFolder === rootFolder;
      } catch (_error) {
        return false;
      }
    },
    {
      timeout: 20000,
      timeoutMsg: `Infinity Context plugin did not apply root folder ${rootFolder}`,
    },
  );
}

async function waitForPluginLayout(layoutVersion: "v1" | "v2"): Promise<void> {
  await browser.waitUntil(
    async () => {
      try {
        const snapshot = await infinityContextSnapshot();
        return snapshot.layoutVersion === layoutVersion;
      } catch (_error) {
        return false;
      }
    },
    {
      timeout: 20000,
      timeoutMsg: `Infinity Context plugin did not apply layout ${layoutVersion}`,
    },
  );
}

async function waitForConnectedLegacyLayout(rootFolder: string): Promise<void> {
  await browser.waitUntil(
    async () => {
      try {
        const snapshot = await infinityContextSnapshot();
        return (
          snapshot.layoutVersion === "v1" &&
          snapshot.rootFolder === rootFolder &&
          snapshot.paths.generatedFacts === posixPath(path.join(rootFolder, "generated", "facts")) &&
          snapshot.paths.inbox === posixPath(path.join(rootFolder, "inbox")) &&
          snapshot.paths.conflicts === posixPath(path.join(rootFolder, "conflicts")) &&
          snapshot.readmeExists === true &&
          snapshot.generatedFactsExists === true &&
          snapshot.inboxExists === true &&
          snapshot.conflictsExists === true
        );
      } catch (_error) {
        return false;
      }
    },
    {
      timeout: 20000,
      timeoutMsg: "Infinity Context plugin did not observe the connected legacy layout",
    },
  );
}

async function waitForSettingsFile(vaultPath: string, rootFolder: string): Promise<void> {
  const settingsPath = path.join(vaultPath, ".obsidian", "plugins", "infinity-context", "data.json");
  await waitUntil(
    async () => fs.existsSync(settingsPath) && fs.readFileSync(settingsPath, "utf8").includes(rootFolder),
    "Infinity Context settings UI did not persist root folder",
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

async function setSettingsDropdown(settingName: string, value: string): Promise<void> {
  const changed = await browser.execute(
    (nextSettingName, nextValue) => {
      const items = Array.from(document.querySelectorAll<HTMLElement>(".setting-item"));
      for (const item of items) {
        const name = item.querySelector<HTMLElement>(".setting-item-name")?.innerText.trim();
        if (name !== nextSettingName) {
          continue;
        }
        const select = item.querySelector<HTMLSelectElement>("select");
        if (!select) {
          return false;
        }
        select.value = nextValue;
        select.dispatchEvent(new Event("input", { bubbles: true }));
        select.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }
      return false;
    },
    settingName,
    value,
  );
  assert.equal(changed, true, `Could not change Infinity Context settings dropdown ${settingName}`);
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

function factFiles(vaultPath: string, rootFolder: string): string[] {
  const factsDir = path.join(vaultPath, scopedRootFor(rootFolder), "generated", "facts");
  if (!fs.existsSync(factsDir)) {
    return [];
  }
  return fs
    .readdirSync(factsDir)
    .filter((name) => name.endsWith(".md") && !name.startsWith("."))
    .map((name) => path.join(factsDir, name))
    .sort();
}

function factFileForId(vaultPath: string, rootFolder: string, factId: string): string {
  const files = factFiles(vaultPath, rootFolder).filter((filePath) =>
    fs.readFileSync(filePath, "utf8").includes(`infinity_context_id: ${factId}`),
  );
  assert.equal(files.length, 1);
  return files[0];
}

function legacyFactFiles(vaultPath: string, rootFolder: string): string[] {
  const factsDir = path.join(vaultPath, rootFolder, "generated", "facts");
  if (!fs.existsSync(factsDir)) {
    return [];
  }
  return fs
    .readdirSync(factsDir)
    .filter((name) => name.endsWith(".md") && !name.startsWith("."))
    .map((name) => path.join(factsDir, name))
    .sort();
}

function legacyFactFileForId(vaultPath: string, rootFolder: string, factId: string): string {
  const files = legacyFactFiles(vaultPath, rootFolder).filter((filePath) =>
    fs.readFileSync(filePath, "utf8").includes(`infinity_context_id: ${factId}`),
  );
  assert.equal(files.length, 1);
  return files[0];
}

function conflictFiles(vaultPath: string, rootFolder: string): string[] {
  const conflictsDir = path.join(vaultPath, scopedRootFor(rootFolder), "conflicts");
  if (!fs.existsSync(conflictsDir)) {
    return [];
  }
  return fs
    .readdirSync(conflictsDir)
    .filter((name) => name.endsWith(".md") && !name.startsWith(".") && name !== "README.md")
    .map((name) => path.join(conflictsDir, name));
}

function legacyConflictFiles(vaultPath: string, rootFolder: string): string[] {
  const conflictsDir = path.join(vaultPath, rootFolder, "conflicts");
  if (!fs.existsSync(conflictsDir)) {
    return [];
  }
  return fs
    .readdirSync(conflictsDir)
    .filter((name) => name.endsWith(".md") && !name.startsWith(".") && name !== "README.md")
    .map((name) => path.join(conflictsDir, name));
}

function writeVaultFile(vaultPath: string, relativePath: string, content: string): void {
  const target = path.join(vaultPath, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content, "utf8");
}

function replaceManagedText(filePath: string, text: string): void {
  const old = fs.readFileSync(filePath, "utf8");
  const start = old.indexOf(textStart) + textStart.length;
  const end = old.indexOf(textEnd);
  assert.ok(start >= textStart.length);
  assert.ok(end > start);
  fs.writeFileSync(filePath, `${old.slice(0, start)}\n${text}\n${old.slice(end)}`, "utf8");
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

function assertCallsUseRoot(
  calls: Array<{ command: string; args: string[]; status: number }>,
  rootFolder: string,
): void {
  assert.ok(calls.every((call) => call.args.includes("--root-folder")));
  assert.ok(calls.every((call) => call.args.includes(rootFolder)));
}

function scopedRootFor(rootFolder: string): string {
  return path.join(rootFolder, "spaces", spaceSlug, "memory_scopes", memoryScopeExternalRef);
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

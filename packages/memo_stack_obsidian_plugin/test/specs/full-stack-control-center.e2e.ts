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
const token = "wdio-full-e2e-token";
const spaceSlug = "wdio-control-center";
const profileExternalRef = "default";
const rootFolder = "Memo Stack";
const scopedRoot = path.join(
  rootFolder,
  "spaces",
  spaceSlug,
  "profiles",
  profileExternalRef,
);

describe("Memo Stack Control Center E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";
  let dbPath = "";
  let port = 0;

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "memo-stack-wdio-control-center-"));
    port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    dbPath = path.join(tempDir, "memory.db");
    server = startMemoStackServer(dbPath, port);
    await waitForHealth(baseUrl);
  });

  afterEach(async function () {
    await stopMemoStackServer(server);
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  it("runs connect, preview, sync and navigation through Control Center buttons", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO Control Center visible fact.",
      sourceId: "wdio-control-center-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);

    await browser.executeObsidianCommand("memo-stack:open-control-center");
    await waitForPanelText("Memo Stack");
    let panel = await panelState();
    assert.match(panel.text, /Project\s+wdio-control-center/);
    assert.match(panel.text, /Connected\s+Run Connect/);
    assert.equal(panel.buttons.Connect.disabled, false);
    assert.equal(panel.buttons.Preview.disabled, false);
    assert.equal(panel.buttons.Sync.disabled, false);
    assert.equal(panel.buttons.README.disabled, true);
    assert.equal(panel.buttons.Inbox.disabled, true);
    assert.equal(panel.buttons.Conflicts.disabled, true);

    await clickVaultAction("Connect");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await waitForPanelText("Connected Ready");

    panel = await panelState();
    assert.equal(panel.buttons.README.disabled, false);
    assert.equal(panel.buttons.Inbox.disabled, false);
    assert.equal(panel.buttons.Conflicts.disabled, false);
    assert.match(panel.text, /Generated\s+Memo Stack\/spaces\/wdio-control-center\/profiles\/default\/generated\/facts/);
    assert.match(readVaultFile(vaultPath, path.join(rootFolder, "README.md")), /Memo Stack/);

    await clickVaultAction("Preview");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();
    await waitForPanelText("Last run: ok");
    assert.equal(factFiles(vaultPath).length, 0, "Control Center preview must not export facts");

    await clickVaultAction("Sync");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForPanelText("exported");

    const exportedFact = onlyFactFile(vaultPath);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /Control Center visible fact/);
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO Control Center visible fact.");

    await clickVaultAction("Inbox");
    assert.equal(await activeFilePath(), posixPath(path.join(scopedRoot, "inbox", "README.md")));
    await browser.executeObsidianCommand("memo-stack:open-control-center");
    await waitForPanelText("Vault sync");
    await clickVaultAction("Conflicts");
    assert.equal(await activeFilePath(), posixPath(path.join(scopedRoot, "conflicts", "README.md")));
    await browser.executeObsidianCommand("memo-stack:open-control-center");
    await waitForPanelText("Vault sync");
    await clickVaultAction("README");
    assert.equal(await activeFilePath(), "Memo Stack/README.md");

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(
      calls.map((call) => `${call.command}:${call.status}`),
      ["connect:0", "preview:0", "sync:0"],
    );
    assert.ok(calls.every((call) => call.args.includes("--api-url")));
    assert.ok(calls.every((call) => call.args.includes(baseUrl)));
    assert.ok(calls.every((call) => call.args.includes("--space")));
    assert.ok(calls.every((call) => call.args.includes(spaceSlug)));
    assert.ok(calls.every((call) => call.args.includes("--profile")));
    assert.ok(calls.every((call) => call.args.includes(profileExternalRef)));
    assert.ok(calls[2].args.includes("--apply-import"));
  });

  it("recovers Control Center sync after the backend goes offline and returns", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO Control Center backend recovery fact.",
      sourceId: "wdio-control-center-recovery-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);

    await browser.executeObsidianCommand("memo-stack:open-control-center");
    await waitForPanelText("Vault sync");

    await clickVaultAction("Connect");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await waitForPanelText("Connected Ready");

    await stopMemoStackServer(server);
    server = undefined;
    await waitForServerDown(baseUrl);

    await clickVaultAction("Sync");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();
    await waitForPanelText("Last run: failed");
    assert.equal(factFiles(vaultPath).length, 0, "failed sync must not export partial facts");

    server = startMemoStackServer(dbPath, port);
    await waitForHealth(baseUrl);

    await clickVaultAction("Sync");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForPanelText("Last run: ok");
    await waitForPanelText("exported");

    const exportedFact = onlyFactFile(vaultPath);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /Control Center backend recovery fact/);
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO Control Center backend recovery fact.");

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(
      calls.map((call) => `${call.command}:${call.status}`),
      ["connect:0", "sync:1", "sync:0"],
    );
  });
});

async function resetVaultAndConfigure(apiUrl: string): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nControl Center E2E vault.\n",
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
    profileExternalRef,
    rootFolder,
    layoutVersion: "v2",
    applyImportOnSync: true,
    commandTimeoutMs: 20000,
  };
  writeVaultFile(
    vaultPath,
    path.join(".obsidian", "plugins", "memo-stack", "data.json"),
    JSON.stringify(settings, null, 2),
  );
  await browser.executeObsidian(
    async ({ plugins }, persistedSettings) => {
      const plugin = plugins.memoStack as any;
      Object.assign(plugin.settings, persistedSettings);
      await plugin.saveSettings();
    },
    settings,
  );
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

async function stopMemoStackServer(server: ChildProcess | undefined): Promise<void> {
  if (!server || server.exitCode !== null) {
    return;
  }
  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => {
      server.kill("SIGKILL");
      resolve();
    }, 5000);
    server.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
    server.kill("SIGTERM");
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

async function waitForServerDown(apiUrl: string): Promise<void> {
  await waitUntil(async () => {
    try {
      await requestJson("GET", `${apiUrl}/v1/health`);
      return false;
    } catch (_error) {
      return true;
    }
  }, "Memo Stack server did not stop");
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

async function waitForPluginIdle(): Promise<void> {
  await browser.waitUntil(async () => (await memoStackSnapshot()).busyLabel === "", {
    timeout: 20000,
    timeoutMsg: "Memo Stack plugin did not become idle",
  });
}

async function memoStackSnapshot(): Promise<any> {
  return await browser.executeObsidian(({ plugins }) => {
    return (plugins.memoStack as any).snapshot();
  });
}

async function activeFilePath(): Promise<string> {
  return await browser.executeObsidian(({ app }) => app.workspace.getActiveFile()?.path ?? "");
}

async function panelState(): Promise<{
  text: string;
  buttons: Record<string, { disabled: boolean }>;
}> {
  return await browser.execute(() => {
    const panel = document.querySelector(".memo-stack-panel");
    if (!panel) {
      return { text: "", buttons: {} };
    }
    const buttons: Record<string, { disabled: boolean }> = {};
    for (const button of Array.from(panel.querySelectorAll("button"))) {
      const key = button.textContent?.trim() || "";
      buttons[key] = { disabled: (button as HTMLButtonElement).disabled };
    }
    return {
      text: ((panel as HTMLElement).innerText || panel.textContent || "")
        .replace(/\s+/g, " ")
        .trim(),
      buttons,
    };
  });
}

async function waitForPanelText(text: string): Promise<void> {
  await browser.waitUntil(async () => (await panelState()).text.includes(text), {
    timeout: 20000,
    timeoutMsg: `Control Center panel did not contain: ${text}`,
  });
}

async function clickVaultAction(label: string): Promise<void> {
  await browser.waitUntil(async () => {
    return await browser.execute((buttonLabel) => {
      const buttons = Array.from(
        document.querySelectorAll(".memo-stack-vault-actions button"),
      ) as HTMLButtonElement[];
      const button = buttons.find((item) => item.textContent?.trim() === buttonLabel);
      return Boolean(button && !button.disabled);
    }, label);
  }, {
    timeout: 20000,
    timeoutMsg: `Control Center button was not clickable: ${label}`,
  });
  await browser.execute((buttonLabel) => {
    const buttons = Array.from(
      document.querySelectorAll(".memo-stack-vault-actions button"),
    ) as HTMLButtonElement[];
    const button = buttons.find((item) => item.textContent?.trim() === buttonLabel);
    if (!button) {
      throw new Error(`Button not found: ${buttonLabel}`);
    }
    button.click();
  }, label);
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

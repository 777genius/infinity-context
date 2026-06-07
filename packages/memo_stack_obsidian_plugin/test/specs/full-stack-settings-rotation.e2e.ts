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
const wrongToken = "wrong-wdio-full-e2e-token";
const spaceSlug = "wdio-settings-rotation";
const profileExternalRef = "default";
const rootFolder = "Memo Stack";
const scopedRoot = path.join(
  rootFolder,
  "spaces",
  spaceSlug,
  "profiles",
  profileExternalRef,
);

describe("Memo Stack settings rotation E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "memo-stack-wdio-settings-rotation-"));
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    server = startMemoStackServer(path.join(tempDir, "memory.db"), port);
    await waitForHealth(baseUrl);
  });

  afterEach(function () {
    server?.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  it("recovers the same vault after the user fixes an invalid token", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO token rotation visible fact.",
      sourceId: "wdio-token-rotation-seed",
    });
    const vaultPath = await resetVaultAndConfigure({
      apiUrl: baseUrl,
      serviceToken: wrongToken,
    });

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    let calls = readCliCalls(vaultPath);
    let snapshot = await memoStackSnapshot();
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync"]);
    assert.equal(calls.at(-1)?.status, 1);
    assert.equal(snapshot.lastResult.exitCode, 1);
    assert.equal(factFiles(vaultPath).length, 0);
    assert.equal(conflictFiles(vaultPath).length, 0);

    await updatePluginSettings({ apiUrl: baseUrl, serviceToken: token, vaultPath });
    await browser.reloadObsidian();
    await waitForMemoStackApiUrl(baseUrl);
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();

    calls = readCliCalls(vaultPath);
    snapshot = await memoStackSnapshot();
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 0);
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.equal(factFiles(vaultPath).length, 1);
    assert.match(fs.readFileSync(onlyFactFile(vaultPath), "utf8"), /token rotation visible fact/);
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO token rotation visible fact.");
  });

  it("recovers the same vault after the user fixes an unavailable API URL", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO API URL rotation visible fact.",
      sourceId: "wdio-api-url-rotation-seed",
    });
    const deadUrl = `http://127.0.0.1:${await freePort()}`;
    const vaultPath = await resetVaultAndConfigure({
      apiUrl: deadUrl,
      serviceToken: token,
    });

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    let calls = readCliCalls(vaultPath);
    let snapshot = await memoStackSnapshot();
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync"]);
    assert.ok(calls.every((call) => call.args.includes(deadUrl)));
    assert.equal(calls.at(-1)?.status, 1);
    assert.equal(snapshot.lastResult.exitCode, 1);
    assert.equal(factFiles(vaultPath).length, 0);
    assert.equal(conflictFiles(vaultPath).length, 0);

    await updatePluginSettings({ apiUrl: baseUrl, serviceToken: token, vaultPath });
    await browser.reloadObsidian();
    await waitForMemoStackApiUrl(baseUrl);
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();

    calls = readCliCalls(vaultPath);
    snapshot = await memoStackSnapshot();
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 0);
    assert.ok(calls.at(-1)?.args.includes(baseUrl));
    assert.equal(snapshot.lastResult.exitCode, 0);
    assert.equal(factFiles(vaultPath).length, 1);
    assert.match(fs.readFileSync(onlyFactFile(vaultPath), "utf8"), /API URL rotation visible fact/);
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO API URL rotation visible fact.");
  });
});

async function resetVaultAndConfigure({
  apiUrl,
  serviceToken,
}: {
  apiUrl: string;
  serviceToken: string;
}): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nSettings rotation E2E vault.\n",
  });
  const vaultPath = obsidianPage.getVaultPath();
  await updatePluginSettings({ apiUrl, serviceToken, vaultPath });
  return vaultPath;
}

async function updatePluginSettings({
  apiUrl,
  serviceToken,
  vaultPath,
}: {
  apiUrl: string;
  serviceToken: string;
  vaultPath: string;
}): Promise<void> {
  const settings = {
    apiUrl,
    token: serviceToken,
    cliPath: realCliPath,
    vaultPathOverride: vaultPath,
    spaceSlug,
    profileExternalRef,
    rootFolder,
    layoutVersion: "v2",
    applyImportOnSync: true,
    commandTimeoutMs: 10000,
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

async function waitForMemoStackApiUrl(apiUrl: string): Promise<void> {
  await browser.waitUntil(async () => (await memoStackSnapshot()).apiUrl === apiUrl, {
    timeout: 20000,
    timeoutMsg: "Memo Stack plugin did not reload corrected API URL",
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

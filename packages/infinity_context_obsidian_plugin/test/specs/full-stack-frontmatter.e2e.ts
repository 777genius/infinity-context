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

const frontmatterCorruptions = [
  {
    name: "missing infinity_context_id",
    mutate: (filePath: string) => removeFrontmatterLine(filePath, "infinity_context_id"),
    reason: /Missing infinity_context_id/,
  },
  {
    name: "non-integer infinity_context_version",
    mutate: (filePath: string) =>
      replaceFrontmatterValue(filePath, "infinity_context_version", "not-a-number"),
    reason: /infinity_context_version must be an integer/,
  },
  {
    name: "unsupported infinity_context_sync_mode",
    mutate: (filePath: string) =>
      replaceFrontmatterValue(filePath, "infinity_context_sync_mode", "teleport"),
    reason: /Unsupported sync mode: teleport/,
  },
];

describe("Infinity Context frontmatter corruption E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "infinity-context-wdio-frontmatter-"));
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    server = startInfinityContextServer(path.join(tempDir, "memory.db"), port);
    await waitForHealth(baseUrl);
  });

  afterEach(function () {
    server?.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  for (const scenario of frontmatterCorruptions) {
    it(`keeps ${scenario.name} as a stable visible conflict`, async function () {
      const fact = await createFact(baseUrl, {
        text: `Obsidian WDIO ${scenario.name} protected backend fact.`,
        sourceId: `wdio-${scenario.name.replace(/[^a-z0-9]+/gi, "-")}-seed`,
      });
      const vaultPath = await resetVaultAndConfigure(baseUrl);
      const exportedFact = await connectAndExportFact(vaultPath);
      scenario.mutate(exportedFact);

      await browser.executeObsidianCommand("infinity-context:sync-now");
      await waitForCliCalls(vaultPath, 3);
      await waitForPluginIdle();
      await browser.executeObsidianCommand("infinity-context:sync-now");
      await waitForCliCalls(vaultPath, 4);
      await waitForPluginIdle();

      const calls = readCliCalls(vaultPath);
      assert.equal(calls.at(-2)?.command, "sync");
      assert.equal(calls.at(-1)?.command, "sync");
      assert.equal(calls.at(-2)?.status, 1);
      assert.equal(calls.at(-1)?.status, 1);
      assert.equal(factFiles(vaultPath).length, 1);
      assert.equal(fs.existsSync(exportedFact), true);
      assert.equal(
        (await getFact(baseUrl, fact.id)).text,
        `Obsidian WDIO ${scenario.name} protected backend fact.`,
      );

      const conflicts = conflictFiles(vaultPath);
      assert.equal(conflicts.length, 1);
      const conflict = fs.readFileSync(conflicts[0], "utf8");
      assert.match(conflict, /Infinity Context Sync Conflict/);
      assert.match(conflict, scenario.reason);
      assert.match(conflict, new RegExp(path.basename(exportedFact).replace(".", "\\.")));
    });
  }
});

async function resetVaultAndConfigure(apiUrl: string): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nFrontmatter E2E vault.\n",
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

function replaceFrontmatterValue(filePath: string, key: string, value: string): void {
  const old = fs.readFileSync(filePath, "utf8");
  const pattern = new RegExp(`^${key}: .*$`, "m");
  assert.match(old, pattern);
  fs.writeFileSync(filePath, old.replace(pattern, `${key}: ${value}`), "utf8");
}

function removeFrontmatterLine(filePath: string, key: string): void {
  const old = fs.readFileSync(filePath, "utf8");
  const pattern = new RegExp(`^${key}: .*\n`, "m");
  assert.match(old, pattern);
  fs.writeFileSync(filePath, old.replace(pattern, ""), "utf8");
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

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
const spaceSlug = "wdio-full-e2e";
const profileExternalRef = "default";
const rootFolder = "Memo Stack";
const scopedRoot = path.join(
  rootFolder,
  "spaces",
  spaceSlug,
  "profiles",
  profileExternalRef,
);
const textStart = "<!-- memo-stack-managed:fact-text:start -->";
const textEnd = "<!-- memo-stack-managed:fact-text:end -->";

describe("Memo Stack conflict review UX E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "memo-stack-wdio-conflict-ux-"));
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    server = startMemoStackServer(path.join(tempDir, "memory.db"), port);
    await waitForHealth(baseUrl);
  });

  afterEach(function () {
    server?.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  it("keeps stale conflicts reviewable in Obsidian and recoverable after user resolution", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO conflict UX initial fact.",
      sourceId: "wdio-conflict-ux-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    const exportedFact = await connectAndExportFact(vaultPath);
    const exportedRelativePath = vaultRelativePath(vaultPath, exportedFact);
    const localDraft = "Obsidian WDIO conflict UX local draft remains reviewable.";
    const backendText = "Obsidian WDIO conflict UX backend moved first.";

    replaceManagedText(exportedFact, localDraft);
    await updateFact(baseUrl, fact.id, {
      expectedVersion: fact.version,
      text: backendText,
      reason: "External WDIO conflict UX update",
    });

    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForMemoStackIdle();

    let calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 1);
    assert.equal((await getFact(baseUrl, fact.id)).text, backendText);
    assert.match(fs.readFileSync(exportedFact, "utf8"), new RegExp(localDraft));

    let conflicts = conflictFiles(vaultPath);
    assert.equal(conflicts.length, 1);
    const conflictFile = conflicts[0];
    const conflictRelativePath = vaultRelativePath(vaultPath, conflictFile);
    const conflictMarkdown = fs.readFileSync(conflictFile, "utf8");
    assert.match(conflictMarkdown, /Memo Stack Sync Conflict/);
    assert.match(conflictMarkdown, /Stale version/);
    assert.match(conflictMarkdown, new RegExp(fact.id));
    assert.match(conflictMarkdown, new RegExp(escapeRegExp(exportedRelativePath)));

    await browser.executeObsidianCommand("memo-stack:open-conflicts");
    assert.equal(
      await activeFilePath(),
      posixPath(path.join(scopedRoot, "conflicts", "README.md")),
    );

    await openVaultFileInObsidian(conflictRelativePath);
    assert.equal(await activeFilePath(), conflictRelativePath);
    assert.match(await activeMarkdown(), /Review the source note and Memo Stack fact/);

    await openVaultFileInObsidian(exportedRelativePath);
    assert.equal(await activeFilePath(), exportedRelativePath);
    assert.match(await activeMarkdown(), new RegExp(localDraft));

    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForMemoStackIdle();
    calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.status, 1);
    assert.deepEqual(conflictFiles(vaultPath).map((file) => vaultRelativePath(vaultPath, file)), [
      conflictRelativePath,
    ]);

    fs.unlinkSync(exportedFact);
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 5);
    await waitForMemoStackIdle();

    calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.status, 0);
    const recoveredFact = onlyFactFile(vaultPath);
    const recoveredMarkdown = fs.readFileSync(recoveredFact, "utf8");
    assert.match(recoveredMarkdown, new RegExp(backendText));
    assert.doesNotMatch(recoveredMarkdown, new RegExp(localDraft));
    assert.match(recoveredMarkdown, /memo_stack_version: 2/);
    assert.equal((await getFact(baseUrl, fact.id)).text, backendText);

    conflicts = conflictFiles(vaultPath);
    assert.equal(conflicts.length, 1);
    fs.unlinkSync(conflicts[0]);
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 6);
    await waitForMemoStackIdle();

    calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.status, 0);
    assert.equal(conflictFiles(vaultPath).length, 0);
    assert.match(fs.readFileSync(onlyFactFile(vaultPath), "utf8"), new RegExp(backendText));
  });

  it("syncs managed and inbox edits made through the Obsidian workspace", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO workspace edit initial fact.",
      sourceId: "wdio-workspace-edit-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    const exportedFact = await connectAndExportFact(vaultPath);
    const exportedRelativePath = vaultRelativePath(vaultPath, exportedFact);
    const workspaceEdit = "Obsidian WDIO workspace edit applied through vault modify.";
    const inboxMarker = "WDIO workspace-created inbox marker imports once";
    const inboxRelativePath = posixPath(path.join(scopedRoot, "inbox", "workspace-created.md"));

    await openVaultFileInObsidian(exportedRelativePath);
    assert.equal(await activeFilePath(), exportedRelativePath);
    await replaceManagedTextInObsidian(exportedRelativePath, workspaceEdit);
    assert.match(await activeMarkdown(), new RegExp(workspaceEdit));

    await createOrModifyVaultFileInObsidian(inboxRelativePath, inboxMarker);
    assert.equal(await activeFilePath(), inboxRelativePath);
    assert.equal(await activeMarkdown(), inboxMarker);

    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForMemoStackIdle();
    await waitForBackendFactText(baseUrl, fact.id, workspaceEdit);
    await waitForSuggestionsContaining(baseUrl, inboxMarker, 1);

    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForMemoStackIdle();
    await sleep(300);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => `${call.command}:${call.status}`), [
      "connect:0",
      "sync:0",
      "sync:0",
      "sync:0",
    ]);
    const updatedFact = await getFact(baseUrl, fact.id);
    assert.equal(updatedFact.version, 2);
    assert.equal(updatedFact.text, workspaceEdit);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /memo_stack_version: 2/);
    assert.equal((await suggestionsContaining(baseUrl, inboxMarker)).length, 1);
    assert.equal(conflictFiles(vaultPath).length, 0);
  });

  it("recreates deleted conflict artifacts while the source note remains unresolved", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO deleted conflict artifact initial fact.",
      sourceId: "wdio-deleted-conflict-artifact-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    const exportedFact = await connectAndExportFact(vaultPath);
    const exportedRelativePath = vaultRelativePath(vaultPath, exportedFact);
    const localDraft = "Obsidian WDIO deleted conflict artifact local draft remains.";
    const backendText = "Obsidian WDIO deleted conflict artifact backend moved first.";

    replaceManagedText(exportedFact, localDraft);
    await updateFact(baseUrl, fact.id, {
      expectedVersion: fact.version,
      text: backendText,
      reason: "External WDIO deleted conflict artifact update",
    });

    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForMemoStackIdle();

    let calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.status, 1);
    let conflicts = conflictFiles(vaultPath);
    assert.equal(conflicts.length, 1);
    const conflictRelativePath = vaultRelativePath(vaultPath, conflicts[0]);
    assert.match(fs.readFileSync(conflicts[0], "utf8"), /Stale version/);
    assert.match(fs.readFileSync(conflicts[0], "utf8"), new RegExp(escapeRegExp(exportedRelativePath)));

    await deleteVaultFileInObsidian(conflictRelativePath);
    await waitForVaultFileMissing(vaultPath, conflictRelativePath);
    assert.match(fs.readFileSync(exportedFact, "utf8"), new RegExp(localDraft));

    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForMemoStackIdle();

    calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.status, 1);
    conflicts = conflictFiles(vaultPath);
    assert.equal(conflicts.length, 1);
    assert.deepEqual(conflicts.map((file) => vaultRelativePath(vaultPath, file)), [conflictRelativePath]);
    const recreatedConflict = fs.readFileSync(conflicts[0], "utf8");
    assert.match(recreatedConflict, /Memo Stack Sync Conflict/);
    assert.match(recreatedConflict, /Stale version/);
    assert.match(recreatedConflict, new RegExp(fact.id));
    assert.match(recreatedConflict, new RegExp(escapeRegExp(exportedRelativePath)));
    assert.match(fs.readFileSync(exportedFact, "utf8"), new RegExp(localDraft));
    assert.equal((await getFact(baseUrl, fact.id)).text, backendText);

    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 5);
    await waitForMemoStackIdle();

    calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.status, 1);
    assert.deepEqual(conflictFiles(vaultPath).map((file) => vaultRelativePath(vaultPath, file)), [
      conflictRelativePath,
    ]);
  });

  it("turns Obsidian workspace renames into recoverable non-canonical path conflicts", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO workspace rename initial fact.",
      sourceId: "wdio-workspace-rename-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);
    const exportedFact = await connectAndExportFact(vaultPath);
    const exportedRelativePath = vaultRelativePath(vaultPath, exportedFact);
    const renamedRelativePath = posixPath(
      path.join(scopedRoot, "generated", "facts", "workspace-renamed-managed-note.md"),
    );
    const renamedFact = path.join(vaultPath, renamedRelativePath);

    await openVaultFileInObsidian(exportedRelativePath);
    assert.equal(await activeFilePath(), exportedRelativePath);
    await renameVaultFileInObsidian(exportedRelativePath, renamedRelativePath);
    assert.equal(await activeFilePath(), renamedRelativePath);

    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForMemoStackIdle();

    let calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 1);
    assert.equal(fs.existsSync(exportedFact), false);
    assert.equal(fs.existsSync(renamedFact), true);
    assert.equal(factFiles(vaultPath).length, 1);
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO workspace rename initial fact.");

    const conflicts = conflictFiles(vaultPath);
    assert.equal(conflicts.length, 1);
    const conflict = fs.readFileSync(conflicts[0], "utf8");
    assert.match(conflict, /Memo Stack Sync Conflict/);
    assert.match(conflict, /non-canonical path/);
    assert.match(conflict, /workspace-renamed-managed-note\.md/);
    assert.match(conflict, new RegExp(fact.id));

    await renameVaultFileInObsidian(renamedRelativePath, exportedRelativePath);
    assert.equal(await activeFilePath(), exportedRelativePath);
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForMemoStackIdle();

    calls = readCliCalls(vaultPath);
    assert.equal(calls.at(-1)?.command, "sync");
    assert.equal(calls.at(-1)?.status, 0);
    assert.equal(fs.existsSync(exportedFact), true);
    assert.equal(fs.existsSync(renamedFact), false);
    assert.equal(factFiles(vaultPath).length, 1);
  });
});

async function resetVaultAndConfigure(apiUrl: string): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nConflict UX E2E vault.\n",
  });
  const vaultPath = obsidianPage.getVaultPath();
  await configurePlugin(vaultPath, apiUrl);
  return vaultPath;
}

async function connectAndExportFact(vaultPath: string): Promise<string> {
  await browser.executeObsidianCommand("memo-stack:connect-vault");
  await waitForCliCalls(vaultPath, 1);
  await waitForMemoStackIdle();
  await browser.executeObsidianCommand("memo-stack:sync-now");
  await waitForCliCalls(vaultPath, 2);
  await waitForMemoStackIdle();
  return onlyFactFile(vaultPath);
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

async function updateFact(
  apiUrl: string,
  factId: string,
  {
    expectedVersion,
    text,
    reason,
  }: {
    expectedVersion: number;
    text: string;
    reason: string;
  },
): Promise<Record<string, any>> {
  const response = await requestJson("PATCH", `${apiUrl}/v1/facts/${factId}`, {
    expected_version: expectedVersion,
    text,
    reason,
    source_refs: [
      {
        source_type: "manual",
        source_id: `${factId}-external-wdio`,
        quote_preview: text,
      },
    ],
  });
  assert.equal(response.status, 200);
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
    profile_external_ref: profileExternalRef,
    status: "pending",
  });
  const response = await requestJson("GET", `${apiUrl}/v1/suggestions?${query.toString()}`);
  assert.equal(response.status, 200);
  return response.body.data.filter((item: Record<string, any>) =>
    String(item.candidate_text).includes(marker),
  );
}

async function requestJson(
  method: "GET" | "POST" | "PATCH",
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

async function waitForMemoStackIdle(): Promise<void> {
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

async function activeMarkdown(): Promise<string> {
  return await browser.executeObsidian(async ({ app }) => {
    const file = app.workspace.getActiveFile();
    return file ? await app.vault.cachedRead(file) : "";
  });
}

async function openVaultFileInObsidian(relativePath: string): Promise<void> {
  await browser.executeObsidian(
    async ({ app }, filePath) => {
      const file = app.vault.getAbstractFileByPath(filePath);
      if (!file || !("extension" in file)) {
        throw new Error(`Vault file not found: ${filePath}`);
      }
      await app.workspace.getLeaf(false).openFile(file as any);
    },
    relativePath,
  );
}

async function replaceManagedTextInObsidian(relativePath: string, text: string): Promise<void> {
  await browser.executeObsidian(
    async ({ app }, payload) => {
      const file = app.vault.getAbstractFileByPath(payload.relativePath);
      if (!file || !("extension" in file)) {
        throw new Error(`Vault file not found: ${payload.relativePath}`);
      }
      const old = await app.vault.cachedRead(file as any);
      const start = old.indexOf(payload.textStart) + payload.textStart.length;
      const end = old.indexOf(payload.textEnd);
      if (start < payload.textStart.length || end <= start) {
        throw new Error("Managed text markers not found");
      }
      await app.vault.modify(
        file as any,
        `${old.slice(0, start)}\n${payload.text}\n${old.slice(end)}`,
      );
    },
    { relativePath, text, textStart, textEnd },
  );
}

async function createOrModifyVaultFileInObsidian(relativePath: string, content: string): Promise<void> {
  await browser.executeObsidian(
    async ({ app }, payload) => {
      const existing = app.vault.getAbstractFileByPath(payload.relativePath);
      if (existing && "extension" in existing) {
        await app.vault.modify(existing as any, payload.content);
        await app.workspace.getLeaf(false).openFile(existing as any);
        return;
      }
      const file = await app.vault.create(payload.relativePath, payload.content);
      await app.workspace.getLeaf(false).openFile(file as any);
    },
    { relativePath, content },
  );
}

async function renameVaultFileInObsidian(fromPath: string, toPath: string): Promise<void> {
  await browser.executeObsidian(
    async ({ app }, payload) => {
      const file = app.vault.getAbstractFileByPath(payload.fromPath);
      if (!file || !("extension" in file)) {
        throw new Error(`Vault file not found: ${payload.fromPath}`);
      }
      if ((app as any).fileManager?.renameFile) {
        await (app as any).fileManager.renameFile(file, payload.toPath);
      } else {
        await app.vault.rename(file as any, payload.toPath);
      }
      const renamed = app.vault.getAbstractFileByPath(payload.toPath);
      if (!renamed || !("extension" in renamed)) {
        throw new Error(`Renamed vault file not found: ${payload.toPath}`);
      }
      await app.workspace.getLeaf(false).openFile(renamed as any);
    },
    { fromPath, toPath },
  );
}

async function deleteVaultFileInObsidian(relativePath: string): Promise<void> {
  await browser.executeObsidian(
    async ({ app }, filePath) => {
      const file = app.vault.getAbstractFileByPath(filePath);
      if (!file || !("extension" in file)) {
        throw new Error(`Vault file not found: ${filePath}`);
      }
      await app.vault.delete(file as any, true);
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
    .map((name) => path.join(conflictsDir, name))
    .sort();
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

function vaultRelativePath(vaultPath: string, filePath: string): string {
  return posixPath(path.relative(vaultPath, filePath));
}

function posixPath(filePath: string): string {
  return filePath.split(path.sep).join("/");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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

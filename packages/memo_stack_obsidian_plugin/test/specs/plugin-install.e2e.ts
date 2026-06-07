import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { browser } from "@wdio/globals";

const pluginId = "memo-stack";
const fakeCliPath = path.resolve("test/fixtures/fake-memo-stack-obsidian.cjs");
const token = "wdio-packaged-token";
const apiUrl = "http://127.0.0.1:65532";
const spaceSlug = "packaged-project";
const profileExternalRef = "packaged-profile";
const rootFolder = "Packaged Memo";

describe("Memo Stack packaged plugin install E2E", function () {
  it("loads installed package artifacts after reload and runs connector commands", async function () {
    const obsidianPage = await browser.getObsidianPage();
    const vaultPath = obsidianPage.getVaultPath();

    assertInstalledArtifacts(vaultPath);
    let runtime = await pluginRuntime();
    assert.equal(runtime.loaded, true);
    assert.equal(runtime.enabled, true);
    assert.equal(runtime.manifest.id, pluginId);
    assert.equal(runtime.manifest.name, "Memo Stack");
    assert.deepEqual(runtime.commandIds, [
      "memo-stack:check-daemon-health",
      "memo-stack:connect-vault",
      "memo-stack:local-stack-doctor",
      "memo-stack:local-stack-init",
      "memo-stack:local-stack-status",
      "memo-stack:open-conflicts",
      "memo-stack:open-control-center",
      "memo-stack:open-inbox",
      "memo-stack:open-memo-stack-readme",
      "memo-stack:prepare-vault",
      "memo-stack:preview-sync",
      "memo-stack:run-doctor",
      "memo-stack:start-local-stack-lite",
      "memo-stack:sync-now",
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
          profileExternalRef,
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
      timeoutMsg: "Memo Stack packaged plugin did not reload persisted settings",
    });

    assertInstalledArtifacts(vaultPath);
    runtime = await pluginRuntime();
    assert.equal(runtime.loaded, true);
    assert.equal(runtime.enabled, true);
    assert.equal(runtime.snapshot.apiUrl, apiUrl);
    assert.equal(runtime.snapshot.spaceSlug, spaceSlug);
    assert.equal(runtime.snapshot.profileExternalRef, profileExternalRef);
    assert.equal(runtime.snapshot.rootFolder, rootFolder);

    await obsidianPage.disablePlugin(pluginId);
    await browser.waitUntil(async () => !(await pluginRuntime()).loaded, {
      timeout: 20000,
      timeoutMsg: "Memo Stack packaged plugin did not disable",
    });
    await obsidianPage.enablePlugin(pluginId);
    await browser.waitUntil(async () => (await pluginRuntime()).snapshot.spaceSlug === spaceSlug, {
      timeout: 20000,
      timeoutMsg: "Memo Stack packaged plugin did not enable with persisted settings",
    });

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => `${call.command}:${call.status}`), ["connect:0"]);
    assert.equal(calls[0].envToken, token);
    assert.ok(calls[0].args.includes("--api-url"));
    assert.ok(calls[0].args.includes(apiUrl));
    assert.ok(calls[0].args.includes("--space"));
    assert.ok(calls[0].args.includes(spaceSlug));
    assert.ok(calls[0].args.includes("--profile"));
    assert.ok(calls[0].args.includes(profileExternalRef));
    assert.ok(calls[0].args.includes("--root-folder"));
    assert.ok(calls[0].args.includes(rootFolder));
    assert.match(readVaultFile(vaultPath, path.join(rootFolder, "README.md")), /Connected by plugin E2E/);

    await browser.executeObsidianCommand("memo-stack:open-control-center");
    const panelOpened = await browser.executeObsidian(({ app }) => {
      return app.workspace.getLeavesOfType("memo-stack-control-center").length === 1;
    });
    assert.equal(panelOpened, true);
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
  assert.match(fs.readFileSync(path.join(pluginDir, "main.js"), "utf8"), /Memo Stack Obsidian plugin/);

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
    const plugin = (plugins as any).memoStack as any;
    const enabledPlugins = Array.from(((app as any).plugins.enabledPlugins ?? []) as Iterable<string>);
    return {
      loaded: Boolean(plugin),
      enabled: enabledPlugins.includes("memo-stack"),
      manifest: (app as any).plugins.manifests["memo-stack"] ?? {},
      commandIds: Object.keys((app as any).commands.commands)
        .filter((id) => id.startsWith("memo-stack:"))
        .sort(),
      snapshot: plugin?.snapshot?.() ?? {},
    };
  });
}

async function waitForPluginIdle(): Promise<void> {
  await browser.waitUntil(async () => (await pluginRuntime()).snapshot.busyLabel === "", {
    timeout: 20000,
    timeoutMsg: "Memo Stack packaged plugin did not become idle",
  });
}

async function waitForCliCalls(vaultPath: string, count: number): Promise<void> {
  await browser.waitUntil(() => readCliCalls(vaultPath).length >= count, {
    timeout: 10000,
    timeoutMsg: `Expected ${count} packaged plugin CLI calls`,
  });
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
  const logPath = path.join(vaultPath, ".memo-stack/plugin-cli-calls.jsonl");
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

function readJson(filePath: string): any {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function fileHash(filePath: string): string {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

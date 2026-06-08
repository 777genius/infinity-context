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
const realCliPath = path.resolve("test/fixtures/real-memo-stack-obsidian.cjs");
const token = "wdio-full-e2e-token";
type Scope = { spaceSlug: string; profileExternalRef: string };
const primaryScope: Scope = {
  spaceSlug: "Client Alpha / Research 2026",
  profileExternalRef: "Default User+Agent",
};
const secondaryScope: Scope = {
  spaceSlug: "Client Beta / Field Notes",
  profileExternalRef: "Research Lead+Ops",
};
const rawSpaceSlug = primaryScope.spaceSlug;
const rawProfileExternalRef = primaryScope.profileExternalRef;
const rootFolder = "Team Memory";
const safeSpaceSlug = safeScopeSegment(rawSpaceSlug);
const safeProfileExternalRef = safeScopeSegment(rawProfileExternalRef);
const scopedRoot = scopedRootFor(primaryScope);
const textStart = "<!-- memo-stack-managed:fact-text:start -->";
const textEnd = "<!-- memo-stack-managed:fact-text:end -->";

describe("Memo Stack friendly project names E2E", function () {
  let server: ChildProcess | undefined;
  let tempDir = "";
  let baseUrl = "";

  beforeEach(async function () {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "memo-stack-wdio-friendly-names-"));
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    server = startMemoStackServer(path.join(tempDir, "memory.db"), port);
    await waitForHealth(baseUrl);
  });

  afterEach(function () {
    server?.kill("SIGTERM");
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  it("stores friendly project and profile names in safe scoped vault folders", async function () {
    const fact = await createFact(baseUrl, {
      text: "Obsidian WDIO friendly project visible fact.",
      sourceId: "wdio-friendly-names-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await waitForConnectedLayout(primaryScope);

    let snapshot = await memoStackSnapshot();
    assert.equal(snapshot.spaceSlug, rawSpaceSlug);
    assert.equal(snapshot.profileExternalRef, rawProfileExternalRef);
    assert.equal(snapshot.paths.generatedFacts, posixPath(path.join(scopedRoot, "generated", "facts")));
    assert.equal(snapshot.paths.inbox, posixPath(path.join(scopedRoot, "inbox")));
    assert.equal(snapshot.paths.conflicts, posixPath(path.join(scopedRoot, "conflicts")));
    assert.equal(snapshot.inboxExists, true);
    assert.equal(snapshot.conflictsExists, true);
    assert.equal(fs.existsSync(path.join(vaultPath, rootFolder, "spaces", "Client Alpha")), false);

    await browser.executeObsidianCommand("memo-stack:preview-sync");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();
    assert.equal(factFiles(vaultPath).length, 0, "friendly-name preview must not export facts");

    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();

    const exportedFact = onlyFactFile(vaultPath);
    assert.equal(path.dirname(exportedFact), path.join(vaultPath, scopedRoot, "generated", "facts"));
    assert.match(fs.readFileSync(exportedFact, "utf8"), /friendly project visible fact/);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /memo_stack_space_slug: Client Alpha \/ Research 2026/);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /memo_stack_profile_external_ref: Default User\+Agent/);
    assert.equal((await getFact(baseUrl, fact.id)).text, "Obsidian WDIO friendly project visible fact.");

    const inboxMarker = "WDIO friendly project inbox marker";
    writeVaultFile(vaultPath, path.join(scopedRoot, "inbox", "friendly-inbox.md"), inboxMarker);
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, inboxMarker, 1);

    await browser.executeObsidianCommand("memo-stack:open-inbox");
    assert.equal(await activeFilePath(), posixPath(path.join(scopedRoot, "inbox", "README.md")));

    snapshot = await memoStackSnapshot();
    assert.equal(snapshot.paths.inbox, posixPath(path.join(scopedRoot, "inbox")));
    assert.equal(conflictFiles(vaultPath).length, 0);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "preview", "sync", "sync"]);
    assert.ok(calls.every((call) => call.args.includes("--space")));
    assert.ok(calls.every((call) => call.args.includes(rawSpaceSlug)));
    assert.ok(calls.every((call) => call.args.includes("--profile")));
    assert.ok(calls.every((call) => call.args.includes(rawProfileExternalRef)));
    assert.ok(calls.every((call) => call.args.includes("--root-folder")));
    assert.ok(calls.every((call) => call.args.includes(rootFolder)));
    assert.ok(calls.slice(2).every((call) => call.args.includes("--apply-import")));
    assert.ok(calls.every((call) => call.status === 0));
  });

  it("switches friendly project scopes in one vault without mixing notes or imports", async function () {
    await createFact(baseUrl, {
      text: "Primary friendly scope backend fact.",
      sourceId: "wdio-friendly-primary-seed",
      scope: primaryScope,
    });
    await createFact(baseUrl, {
      text: "Secondary friendly scope backend fact.",
      sourceId: "wdio-friendly-secondary-seed",
      scope: secondaryScope,
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl, primaryScope);
    const secondaryRoot = scopedRootFor(secondaryScope);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const primaryFile = onlyFactFile(vaultPath, primaryScope);
    assert.match(fs.readFileSync(primaryFile, "utf8"), /Primary friendly scope backend fact/);
    assert.equal(factFiles(vaultPath, secondaryScope).length, 0);
    assert.equal(fs.existsSync(path.join(vaultPath, rootFolder, "spaces", "Client Alpha")), false);

    const primaryInboxMarker = "WDIO primary friendly scope inbox marker";
    writeVaultFile(vaultPath, path.join(scopedRoot, "inbox", "primary-inbox.md"), primaryInboxMarker);
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, primaryInboxMarker, 1, primaryScope);
    assert.equal((await suggestionsContaining(baseUrl, primaryInboxMarker, secondaryScope)).length, 0);

    await configurePlugin(vaultPath, baseUrl, secondaryScope);
    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await waitForConnectedLayout(secondaryScope);

    let snapshot = await memoStackSnapshot();
    assert.equal(snapshot.spaceSlug, secondaryScope.spaceSlug);
    assert.equal(snapshot.profileExternalRef, secondaryScope.profileExternalRef);
    assert.equal(snapshot.paths.generatedFacts, posixPath(path.join(secondaryRoot, "generated", "facts")));
    assert.equal(snapshot.paths.inbox, posixPath(path.join(secondaryRoot, "inbox")));
    assert.equal(snapshot.inboxExists, true);
    assert.equal(fs.existsSync(path.join(vaultPath, rootFolder, "spaces", "Client Beta")), false);

    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 5);
    await waitForPluginIdle();

    const secondaryFile = onlyFactFile(vaultPath, secondaryScope);
    assert.match(fs.readFileSync(secondaryFile, "utf8"), /Secondary friendly scope backend fact/);
    assert.equal(factFiles(vaultPath, primaryScope).length, 1);
    assert.equal(factFiles(vaultPath, secondaryScope).length, 1);
    assert.match(fs.readFileSync(primaryFile, "utf8"), /Primary friendly scope backend fact/);

    const secondaryInboxMarker = "WDIO secondary friendly scope inbox marker";
    writeVaultFile(vaultPath, path.join(secondaryRoot, "inbox", "secondary-inbox.md"), secondaryInboxMarker);
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 6);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, secondaryInboxMarker, 1, secondaryScope);
    assert.equal((await suggestionsContaining(baseUrl, secondaryInboxMarker, primaryScope)).length, 0);

    await browser.executeObsidianCommand("memo-stack:open-inbox");
    assert.equal(await activeFilePath(), posixPath(path.join(secondaryRoot, "inbox", "README.md")));
    snapshot = await memoStackSnapshot();
    assert.equal(snapshot.paths.conflicts, posixPath(path.join(secondaryRoot, "conflicts")));
    assert.equal(conflictFiles(vaultPath, primaryScope).length, 0);
    assert.equal(conflictFiles(vaultPath, secondaryScope).length, 0);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync", "sync", "connect", "sync", "sync"]);
    assertCallsUseScope(calls.slice(0, 3), primaryScope);
    assertCallsUseScope(calls.slice(3), secondaryScope);
    assert.ok(calls.every((call) => call.args.includes(rootFolder)));
    assert.ok(calls.every((call) => call.status === 0));
  });

  it("keeps friendly scoped sync state after an Obsidian reload", async function () {
    await createFact(baseUrl, {
      text: "Friendly reload persisted backend fact.",
      sourceId: "wdio-friendly-reload-seed",
    });
    const vaultPath = await resetVaultAndConfigure(baseUrl);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const exportedFact = onlyFactFile(vaultPath);
    const inboxPath = path.join(scopedRoot, "inbox", "reload-friendly-inbox.md");
    const firstMarker = "WDIO friendly reload inbox first marker";
    const secondMarker = "WDIO friendly reload inbox second marker";
    writeVaultFile(vaultPath, inboxPath, firstMarker);
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, firstMarker, 1);

    await browser.reloadObsidian();
    await waitForPluginScope(primaryScope);
    await waitForPluginIdle();

    let snapshot = await memoStackSnapshot();
    assert.equal(snapshot.apiUrl, baseUrl);
    assert.equal(snapshot.spaceSlug, rawSpaceSlug);
    assert.equal(snapshot.profileExternalRef, rawProfileExternalRef);
    assert.equal(snapshot.paths.generatedFacts, posixPath(path.join(scopedRoot, "generated", "facts")));
    assert.equal(snapshot.paths.inbox, posixPath(path.join(scopedRoot, "inbox")));
    assert.equal(factFiles(vaultPath).length, 1);
    assert.match(fs.readFileSync(exportedFact, "utf8"), /Friendly reload persisted backend fact/);

    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    assert.equal((await suggestionsContaining(baseUrl, firstMarker)).length, 1);

    writeVaultFile(vaultPath, inboxPath, secondMarker);
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 5);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, secondMarker, 1);
    assert.equal((await suggestionsContaining(baseUrl, firstMarker)).length, 1);

    await browser.executeObsidianCommand("memo-stack:open-inbox");
    assert.equal(await activeFilePath(), posixPath(path.join(scopedRoot, "inbox", "README.md")));
    snapshot = await memoStackSnapshot();
    assert.equal(snapshot.paths.conflicts, posixPath(path.join(scopedRoot, "conflicts")));
    assert.equal(conflictFiles(vaultPath).length, 0);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync", "sync", "sync", "sync"]);
    assertCallsUseScope(calls, primaryScope);
    assert.ok(calls.every((call) => call.status === 0));
  });

  it("configures a friendly scoped vault through the Obsidian settings UI", async function () {
    await createFact(baseUrl, {
      text: "Friendly settings UI backend fact.",
      sourceId: "wdio-friendly-settings-ui-seed",
    });
    const vaultPath = await resetVault();
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "memo-stack"), { recursive: true });

    await openMemoStackSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", vaultPath);
    await setSettingsInput("rootFolder", rootFolder);
    await setSettingsInput("spaceSlug", rawSpaceSlug);
    await setSettingsInput("profileExternalRef", rawProfileExternalRef);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForPluginScope(primaryScope);

    let snapshot = await memoStackSnapshot();
    assert.equal(snapshot.apiUrl, baseUrl);
    assert.equal(snapshot.rootFolder, rootFolder);
    assert.equal(snapshot.paths.generatedFacts, posixPath(path.join(scopedRoot, "generated", "facts")));
    await waitForSettingsFile(vaultPath);
    assert.match(readVaultFile(vaultPath, path.join(".obsidian", "plugins", "memo-stack", "data.json")), /Client Alpha/);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const exportedFact = onlyFactFile(vaultPath);
    assert.equal(path.dirname(exportedFact), path.join(vaultPath, scopedRoot, "generated", "facts"));
    assert.match(fs.readFileSync(exportedFact, "utf8"), /Friendly settings UI backend fact/);

    await browser.executeObsidianCommand("memo-stack:open-inbox");
    assert.equal(await activeFilePath(), posixPath(path.join(scopedRoot, "inbox", "README.md")));
    snapshot = await memoStackSnapshot();
    assert.equal(snapshot.inboxExists, true);
    assert.equal(snapshot.conflictsExists, true);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync"]);
    assertCallsUseScope(calls, primaryScope);
    assert.ok(calls.every((call) => call.args.includes(baseUrl)));
    assert.ok(calls.every((call) => call.args.includes(rootFolder)));
    assert.ok(calls.every((call) => call.status === 0));
  });

  it("switches profiles inside one friendly project through settings without mixing notes", async function () {
    const teamProfileScope: Scope = {
      spaceSlug: primaryScope.spaceSlug,
      profileExternalRef: "Research Lead+Ops",
    };
    await createFact(baseUrl, {
      text: "Primary profile same project backend fact.",
      sourceId: "wdio-same-project-primary-profile-seed",
      scope: primaryScope,
    });
    await createFact(baseUrl, {
      text: "Team profile same project backend fact.",
      sourceId: "wdio-same-project-team-profile-seed",
      scope: teamProfileScope,
    });
    const vaultPath = await resetVault();
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "memo-stack"), { recursive: true });

    await openMemoStackSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", vaultPath);
    await setSettingsInput("rootFolder", rootFolder);
    await setSettingsInput("spaceSlug", primaryScope.spaceSlug);
    await setSettingsInput("profileExternalRef", primaryScope.profileExternalRef);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForPluginScope(primaryScope);
    await waitForSettingsFile(vaultPath, primaryScope.profileExternalRef);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const primaryFile = onlyFactFile(vaultPath, primaryScope);
    assert.match(fs.readFileSync(primaryFile, "utf8"), /Primary profile same project backend fact/);
    assert.equal(factFiles(vaultPath, teamProfileScope).length, 0);

    const primaryInboxMarker = "WDIO same project primary profile inbox marker";
    writeVaultFile(vaultPath, path.join(scopedRootFor(primaryScope), "inbox", "primary-profile.md"), primaryInboxMarker);
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, primaryInboxMarker, 1, primaryScope);
    assert.equal((await suggestionsContaining(baseUrl, primaryInboxMarker, teamProfileScope)).length, 0);

    await openMemoStackSettings();
    await setSettingsInput("profileExternalRef", teamProfileScope.profileExternalRef);
    await waitForPluginScope(teamProfileScope);
    await waitForSettingsFile(vaultPath, teamProfileScope.profileExternalRef);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 5);
    await waitForPluginIdle();

    const teamFile = onlyFactFile(vaultPath, teamProfileScope);
    assert.match(fs.readFileSync(teamFile, "utf8"), /Team profile same project backend fact/);
    assert.match(fs.readFileSync(primaryFile, "utf8"), /Primary profile same project backend fact/);
    assert.equal(factFiles(vaultPath, primaryScope).length, 1);
    assert.equal(factFiles(vaultPath, teamProfileScope).length, 1);
    assert.equal(path.dirname(primaryFile).includes(safeScopeSegment(primaryScope.spaceSlug)), true);
    assert.equal(path.dirname(teamFile).includes(safeScopeSegment(primaryScope.spaceSlug)), true);
    assert.notEqual(path.dirname(primaryFile), path.dirname(teamFile));

    const teamInboxMarker = "WDIO same project team profile inbox marker";
    writeVaultFile(vaultPath, path.join(scopedRootFor(teamProfileScope), "inbox", "team-profile.md"), teamInboxMarker);
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 6);
    await waitForPluginIdle();
    await waitForSuggestionsContaining(baseUrl, teamInboxMarker, 1, teamProfileScope);
    assert.equal((await suggestionsContaining(baseUrl, teamInboxMarker, primaryScope)).length, 0);

    await browser.executeObsidianCommand("memo-stack:open-inbox");
    assert.equal(await activeFilePath(), posixPath(path.join(scopedRootFor(teamProfileScope), "inbox", "README.md")));

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(calls.map((call) => call.command), ["connect", "sync", "sync", "connect", "sync", "sync"]);
    assertCallsUseScope(calls.slice(0, 3), primaryScope);
    assertCallsUseScope(calls.slice(3), teamProfileScope);
    assert.ok(calls.every((call) => call.args.includes(rootFolder)));
    assert.ok(calls.every((call) => call.status === 0));
  });

  it("preserves pending old-profile edits and inbox notes across profile switches", async function () {
    const teamProfileScope: Scope = {
      spaceSlug: primaryScope.spaceSlug,
      profileExternalRef: "Research Lead+Ops",
    };
    const initialText = "Obsidian WDIO profile switch pending initial fact.";
    const recoveredText = "Obsidian WDIO profile switch pending local edit recovered.";
    const primaryFact = await createFact(baseUrl, {
      text: initialText,
      sourceId: "wdio-profile-switch-pending-primary-seed",
      scope: primaryScope,
    });
    await createFact(baseUrl, {
      text: "Team profile switch backend fact stays isolated.",
      sourceId: "wdio-profile-switch-pending-team-seed",
      scope: teamProfileScope,
    });
    const vaultPath = await resetVault();
    fs.mkdirSync(path.join(vaultPath, ".obsidian", "plugins", "memo-stack"), { recursive: true });

    await openMemoStackSettings();
    await setSettingsInput("apiUrl", baseUrl);
    await setSettingsInput("token", token);
    await setSettingsInput("cliPath", realCliPath);
    await setSettingsInput("vaultPathOverride", vaultPath);
    await setSettingsInput("rootFolder", rootFolder);
    await setSettingsInput("spaceSlug", primaryScope.spaceSlug);
    await setSettingsInput("profileExternalRef", primaryScope.profileExternalRef);
    await setSettingsInput("commandTimeoutMs", "20000");
    await waitForPluginScope(primaryScope);
    await waitForSettingsFile(vaultPath, primaryScope.profileExternalRef);

    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 1);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 2);
    await waitForPluginIdle();

    const primaryFile = onlyFactFile(vaultPath, primaryScope);
    replaceManagedText(primaryFile, recoveredText);
    const primaryInboxMarker = "WDIO profile switch pending inbox imports only after return";
    writeVaultFile(
      vaultPath,
      path.join(scopedRootFor(primaryScope), "inbox", "profile-switch-pending.md"),
      primaryInboxMarker,
    );

    await openMemoStackSettings();
    await setSettingsInput("profileExternalRef", teamProfileScope.profileExternalRef);
    await waitForPluginScope(teamProfileScope);
    await waitForSettingsFile(vaultPath, teamProfileScope.profileExternalRef);
    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 3);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 4);
    await waitForPluginIdle();

    assert.equal((await getFact(baseUrl, primaryFact.id)).text, initialText);
    assert.equal((await suggestionsContaining(baseUrl, primaryInboxMarker, primaryScope)).length, 0);
    assert.equal((await suggestionsContaining(baseUrl, primaryInboxMarker, teamProfileScope)).length, 0);
    assert.match(fs.readFileSync(primaryFile, "utf8"), new RegExp(recoveredText));
    const teamFile = onlyFactFile(vaultPath, teamProfileScope);
    assert.match(fs.readFileSync(teamFile, "utf8"), /Team profile switch backend fact stays isolated/);
    assert.doesNotMatch(fs.readFileSync(teamFile, "utf8"), new RegExp(recoveredText));
    assert.equal(conflictFiles(vaultPath, primaryScope).length, 0);
    assert.equal(conflictFiles(vaultPath, teamProfileScope).length, 0);

    await openMemoStackSettings();
    await setSettingsInput("profileExternalRef", primaryScope.profileExternalRef);
    await waitForPluginScope(primaryScope);
    await waitForSettingsFile(vaultPath, primaryScope.profileExternalRef);
    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 5);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 6);
    await waitForPluginIdle();
    await waitForBackendFactText(baseUrl, primaryFact.id, recoveredText);
    await waitForSuggestionsContaining(baseUrl, primaryInboxMarker, 1, primaryScope);

    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 7);
    await waitForPluginIdle();
    await sleep(300);
    assert.equal((await suggestionsContaining(baseUrl, primaryInboxMarker, primaryScope)).length, 1);
    assert.match(fs.readFileSync(onlyFactFile(vaultPath, primaryScope), "utf8"), /memo_stack_version: 2/);

    await openMemoStackSettings();
    await setSettingsInput("profileExternalRef", teamProfileScope.profileExternalRef);
    await waitForPluginScope(teamProfileScope);
    await waitForSettingsFile(vaultPath, teamProfileScope.profileExternalRef);
    await browser.executeObsidianCommand("memo-stack:connect-vault");
    await waitForCliCalls(vaultPath, 8);
    await waitForPluginIdle();
    await browser.executeObsidianCommand("memo-stack:sync-now");
    await waitForCliCalls(vaultPath, 9);
    await waitForPluginIdle();

    assert.doesNotMatch(fs.readFileSync(onlyFactFile(vaultPath, teamProfileScope), "utf8"), new RegExp(recoveredText));
    assert.equal((await suggestionsContaining(baseUrl, primaryInboxMarker, teamProfileScope)).length, 0);
    assert.equal(conflictFiles(vaultPath, primaryScope).length, 0);
    assert.equal(conflictFiles(vaultPath, teamProfileScope).length, 0);

    const calls = readCliCalls(vaultPath);
    assert.deepEqual(
      calls.map((call) => call.command),
      ["connect", "sync", "connect", "sync", "connect", "sync", "sync", "connect", "sync"],
    );
    assertCallsUseScope(calls.slice(0, 2), primaryScope);
    assertCallsUseScope(calls.slice(2, 4), teamProfileScope);
    assertCallsUseScope(calls.slice(4, 7), primaryScope);
    assertCallsUseScope(calls.slice(7), teamProfileScope);
    assert.ok(calls.every((call) => call.args.includes(rootFolder)));
    assert.ok(calls.every((call) => call.status === 0));
  });
});

async function resetVaultAndConfigure(apiUrl: string, scope: Scope = primaryScope): Promise<string> {
  const vaultPath = await resetVault();
  await configurePlugin(vaultPath, apiUrl, scope);
  return vaultPath;
}

async function resetVault(): Promise<string> {
  const obsidianPage = await browser.getObsidianPage();
  await obsidianPage.resetVault({
    "Welcome.md": "# Welcome\n\nFriendly names E2E vault.\n",
  });
  return obsidianPage.getVaultPath();
}

async function configurePlugin(vaultPath: string, apiUrl: string, scope: Scope = primaryScope): Promise<void> {
  const settings = {
    apiUrl,
    token,
    cliPath: realCliPath,
    vaultPathOverride: vaultPath,
    spaceSlug: scope.spaceSlug,
    profileExternalRef: scope.profileExternalRef,
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
  { text, sourceId, scope = primaryScope }: { text: string; sourceId: string; scope?: Scope },
): Promise<Record<string, any>> {
  const response = await requestJson("POST", `${apiUrl}/v1/facts`, {
    space_slug: scope.spaceSlug,
    profile_external_ref: scope.profileExternalRef,
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
  scope: Scope = primaryScope,
): Promise<void> {
  await waitUntil(
    async () => (await suggestionsContaining(apiUrl, marker, scope)).length >= count,
    "Suggestion was not created",
  );
}

async function suggestionsContaining(
  apiUrl: string,
  marker: string,
  scope: Scope = primaryScope,
): Promise<Record<string, any>[]> {
  const query = new URLSearchParams({
    space_slug: scope.spaceSlug,
    profile_external_ref: scope.profileExternalRef,
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
  await browser.waitUntil(async () => (await memoStackSnapshot()).busyLabel === "", {
    timeout: 20000,
    timeoutMsg: "Memo Stack plugin did not become idle",
  });
}

async function waitForPluginScope(scope: Scope): Promise<void> {
  await browser.waitUntil(
    async () => {
      try {
        const snapshot = await memoStackSnapshot();
        return snapshot.spaceSlug === scope.spaceSlug && snapshot.profileExternalRef === scope.profileExternalRef;
      } catch (_error) {
        return false;
      }
    },
    {
      timeout: 20000,
      timeoutMsg: "Memo Stack plugin did not reload friendly scope settings",
    },
  );
}

async function waitForConnectedLayout(scope: Scope): Promise<void> {
  await browser.waitUntil(
    async () => {
      try {
        const snapshot = await memoStackSnapshot();
        return (
          snapshot.spaceSlug === scope.spaceSlug &&
          snapshot.profileExternalRef === scope.profileExternalRef &&
          snapshot.paths.generatedFacts === posixPath(path.join(scopedRootFor(scope), "generated", "facts")) &&
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
      timeoutMsg: "Memo Stack plugin did not observe the connected friendly layout",
    },
  );
}

async function waitForSettingsFile(vaultPath: string, marker: string = rawSpaceSlug): Promise<void> {
  const settingsPath = path.join(vaultPath, ".obsidian", "plugins", "memo-stack", "data.json");
  await waitUntil(
    async () => fs.existsSync(settingsPath) && fs.readFileSync(settingsPath, "utf8").includes(marker),
    "Memo Stack settings UI did not persist data.json",
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

function factFiles(vaultPath: string, scope: Scope = primaryScope): string[] {
  const factsDir = path.join(vaultPath, scopedRootFor(scope), "generated", "facts");
  if (!fs.existsSync(factsDir)) {
    return [];
  }
  return fs
    .readdirSync(factsDir)
    .filter((name) => name.endsWith(".md") && !name.startsWith("."))
    .map((name) => path.join(factsDir, name))
    .sort();
}

function onlyFactFile(vaultPath: string, scope: Scope = primaryScope): string {
  const files = factFiles(vaultPath, scope);
  assert.equal(files.length, 1);
  return files[0];
}

function conflictFiles(vaultPath: string, scope: Scope = primaryScope): string[] {
  const conflictsDir = path.join(vaultPath, scopedRootFor(scope), "conflicts");
  if (!fs.existsSync(conflictsDir)) {
    return [];
  }
  return fs
    .readdirSync(conflictsDir)
    .filter((name) => name.endsWith(".md") && !name.startsWith(".") && name !== "README.md")
    .map((name) => path.join(conflictsDir, name));
}

function readVaultFile(vaultPath: string, relativePath: string): string {
  return fs.readFileSync(path.join(vaultPath, relativePath), "utf8");
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

function assertCallsUseScope(
  calls: Array<{ command: string; args: string[]; status: number }>,
  scope: Scope,
): void {
  assert.ok(calls.every((call) => call.args.includes("--space")));
  assert.ok(calls.every((call) => call.args.includes(scope.spaceSlug)));
  assert.ok(calls.every((call) => call.args.includes("--profile")));
  assert.ok(calls.every((call) => call.args.includes(scope.profileExternalRef)));
}

function scopedRootFor(scope: Scope): string {
  return path.join(
    rootFolder,
    "spaces",
    safeScopeSegment(scope.spaceSlug),
    "profiles",
    safeScopeSegment(scope.profileExternalRef),
  );
}

function safeScopeSegment(value: string): string {
  const raw = value.trim();
  const normalized = raw.toLocaleLowerCase();
  let slug = normalized.replace(/[^a-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "");
  slug = slug.replace(/-{2,}/g, "-").replace(/^[._-]+|[._-]+$/g, "");
  if (!slug) {
    slug = "scope";
  }
  const changed = slug !== normalized || slug.length > 72;
  slug = slug.slice(0, 72).replace(/^[._-]+|[._-]+$/g, "") || "scope";
  if (changed) {
    slug = `${slug}--${contentHash(raw).slice(0, 8)}`;
  }
  return slug;
}

function contentHash(value: string): string {
  return crypto
    .createHash("sha256")
    .update(value.replace(/\r\n/g, "\n").replace(/\r/g, "\n"))
    .digest("hex");
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

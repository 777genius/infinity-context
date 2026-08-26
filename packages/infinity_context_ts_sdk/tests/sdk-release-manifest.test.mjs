import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { chmod, mkdir, mkdtemp, readFile, symlink, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { describe, expect, test } from "vitest";

const execFileAsync = promisify(execFile);
const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const cli = join(packageRoot, "scripts", "sdk-release-manifest.mjs");

describe("SDK release manifest workflow CLI", () => {
  test("creates deterministic canonical SDK-only provenance from exact fixture bytes", async () => {
    const fixture = await releaseFixture();
    await runCli(fixture.createArgs);
    const bytes = await readFile(fixture.manifestPath, "utf8");
    const manifest = JSON.parse(bytes);

    expect(bytes).toBe(`${canonicalJson(manifest)}\n`);
    expect(manifest).toMatchObject({
      artifact_byte_length: fixture.artifact.length,
      artifact_name: "infinity-context-sdk-0.2.1.tgz",
      artifact_sha256_hex: sha256(fixture.artifact),
      build_profile: "node24-npm-ci-pack-once.v1",
      build_workflow_run_attempt: 2,
      build_workflow_run_id: 12345,
      git_object_format: "sha1",
      node_version: "24.18.0",
      package_name: "@infinity-context/sdk",
      package_version: "0.2.1",
      release_tag: "sdk-v0.2.1",
      repository: "777genius/infinity-context",
      schema_version: "infinity-context-typescript-sdk-release.v1",
    });
    expect(manifest.contract_fixture_inventory.map((item) => item.path)).toEqual([
      "fixtures/context_retrieval_v2/request.json", "src/client.ts",
    ]);
    for (const forbidden of ["timestamp", "service_revision", "capability_fingerprint", "qualification", "discord", "corpus", "model"]) {
      expect(bytes.toLowerCase()).not.toContain(forbidden);
    }
  });

  test.each([
    ["artifact tamper", async (fixture) => writeFile(fixture.artifactPath, "tampered")],
    ["lock drift", async (fixture) => writeFile(join(fixture.packageDir, "package-lock.json"), JSON.stringify(lock("0.2.0")))],
    ["fixture drift", async (fixture) => writeFile(join(fixture.packageDir, "fixtures/context_retrieval_v2/request.json"), "{}\n")],
    ["workflow drift", async (fixture) => writeFile(fixture.workflowPath, "name: changed\n")],
  ])("verification rejects %s", async (_label, mutate) => {
    const fixture = await releaseFixture();
    await runCli(fixture.createArgs);
    await mutate(fixture);
    await expect(runCli(fixture.verifyArgs)).rejects.toMatchObject({ code: 1 });
  });

  test("rejects tree/tag target drift and version/tag drift", async () => {
    const tree = await releaseFixture();
    await writeFile(join(tree.root, "drift.txt"), "drift\n");
    await git(tree.root, "add", "drift.txt");
    await git(tree.root, "commit", "-m", "tree drift");
    await expect(runCli(tree.createArgs)).rejects.toThrow(/tag target drift/u);

    const tag = await releaseFixture();
    const wrongTag = replaceArg(tag.createArgs, "--tag", "sdk-v0.2.2");
    await expect(runCli(wrongTag)).rejects.toThrow(/tag.version drift|unknown revision|ambiguous argument/u);

    const version = await releaseFixture();
    await writeFile(join(version.packageDir, "package.json"), JSON.stringify(metadata("0.2.2")));
    await expect(runCli(version.createArgs)).rejects.toThrow(/tag.version drift/u);
  });

  test("rejects symlinks and allowed-root path escapes", async () => {
    const symlinkFixture = await releaseFixture();
    const actual = join(symlinkFixture.artifactDir, "actual.tgz");
    await writeFile(actual, "bytes");
    await writeFile(symlinkFixture.artifactPath, "replace");
    await unlink(symlinkFixture.artifactPath);
    await symlink(actual, symlinkFixture.artifactPath);
    await expect(runCli(symlinkFixture.createArgs)).rejects.toThrow(/non-symlink/u);

    const escape = await releaseFixture();
    const outside = join(escape.root, "outside", "infinity-context-sdk-0.2.1.tgz");
    await mkdir(dirname(outside));
    await writeFile(outside, "outside");
    await expect(runCli(replaceArg(escape.createArgs, "--artifact", outside))).rejects.toThrow(/escapes its allowed root/u);

    const outputEscape = await releaseFixture();
    const escapedOutput = join(outputEscape.root, "outside-manifest", "infinity-context-sdk-release-manifest.json");
    await mkdir(dirname(escapedOutput));
    await expect(runCli(replaceArg(outputEscape.createArgs, "--output", escapedOutput))).rejects.toThrow(/escapes its allowed root/u);
  }, 15_000);

  test("exclusive-create output never overwrites existing evidence", async () => {
    const fixture = await releaseFixture();
    await runCli(fixture.createArgs);
    await chmod(fixture.manifestPath, 0o644);
    const before = await readFile(fixture.manifestPath);
    await expect(runCli(fixture.createArgs)).rejects.toMatchObject({ code: 1 });
    expect(await readFile(fixture.manifestPath)).toEqual(before);
  });

  test("semantic verification rejects forbidden quality fields and noncanonical JSON", async () => {
    const fixture = await releaseFixture();
    await runCli(fixture.createArgs);
    const manifest = JSON.parse(await readFile(fixture.manifestPath, "utf8"));
    manifest.service_revision = "a".repeat(40);
    await chmod(fixture.manifestPath, 0o644);
    await writeFile(fixture.manifestPath, `${canonicalJson(manifest)}\n`);
    await expect(runCli(fixture.verifyArgs)).rejects.toThrow(/semantic binding drift/u);

    const duplicates = await releaseFixture();
    await runCli(duplicates.createArgs);
    await chmod(duplicates.manifestPath, 0o644);
    await writeFile(duplicates.manifestPath, '{"schema_version":"one","schema_version":"two"}\n');
    await expect(runCli(duplicates.verifyArgs)).rejects.toThrow(/canonical JSON without duplicate keys/u);

    const unsafe = await releaseFixture();
    await runCli(unsafe.createArgs);
    await chmod(unsafe.manifestPath, 0o644);
    await writeFile(unsafe.manifestPath, '{"unsafe":9007199254740992}\n');
    await expect(runCli(unsafe.verifyArgs)).rejects.toThrow(/unsafe numbers/u);
  }, 15_000);

  test("rejects missing flags, output injection, and legacy manual revision flags", async () => {
    const fixture = await releaseFixture();
    await expect(runCli(["--artifact", fixture.artifactPath])).rejects.toMatchObject({ code: 1 });
    await expect(runCli(replaceArg(fixture.createArgs, "--repository", "owner/repo\nkey=value"))).rejects.toThrow(/single-line/u);
    await expect(runCli([...fixture.createArgs, "--service-revision", "a".repeat(40)])).rejects.toMatchObject({ code: 1 });
  });

  test("package metadata retains the independent 0.2.1 consumer release", async () => {
    const metadata = JSON.parse(await readFile(join(packageRoot, "package.json"), "utf8"));
    const packageLock = JSON.parse(await readFile(join(packageRoot, "package-lock.json"), "utf8"));
    expect(metadata.version).toBe("0.2.1");
    expect(packageLock.version).toBe(metadata.version);
    expect(packageLock.packages[""].version).toBe(metadata.version);
    expect(metadata.files).not.toContain("scripts/sdk-release-manifest.mjs");
    expect(metadata).not.toHaveProperty("publishConfig");
  });
});

async function releaseFixture() {
  const root = await mkdtemp(join(tmpdir(), "infinity-sdk-release-"));
  const packageDir = join(root, "packages", "infinity_context_ts_sdk");
  const artifactDir = join(root, "artifacts");
  const outputDir = join(root, "output");
  const workflowPath = join(root, ".github", "workflows", "typescript-sdk-release.yml");
  await Promise.all([
    mkdir(join(packageDir, "src"), { recursive: true }),
    mkdir(join(packageDir, "fixtures/context_retrieval_v2"), { recursive: true }),
    mkdir(artifactDir, { recursive: true }), mkdir(outputDir, { recursive: true }),
    mkdir(dirname(workflowPath), { recursive: true }),
  ]);
  await writeFile(join(packageDir, "package.json"), JSON.stringify(metadata("0.2.1")));
  await writeFile(join(packageDir, "package-lock.json"), JSON.stringify(lock("0.2.1")));
  await writeFile(join(packageDir, "src", "client.ts"), "export const contract = 1;\n");
  await writeFile(join(packageDir, "fixtures/context_retrieval_v2/request.json"), '{"contract":"v2"}\n');
  await writeFile(workflowPath, "name: TypeScript SDK release\n");
  await git(root, "init");
  await git(root, "config", "user.email", "release-test@example.invalid");
  await git(root, "config", "user.name", "Release Test");
  await git(root, "add", ".");
  await git(root, "commit", "-m", "fixture");
  await git(root, "tag", "-a", "sdk-v0.2.1", "-m", "SDK 0.2.1");
  const artifact = Buffer.from("exact packed SDK bytes\n");
  const artifactPath = join(artifactDir, "infinity-context-sdk-0.2.1.tgz");
  const manifestPath = join(outputDir, "infinity-context-sdk-release-manifest.json");
  await writeFile(artifactPath, artifact);
  const common = [
    "--artifact", artifactPath, "--artifact-root", artifactDir,
    "--build-profile", "node24-npm-ci-pack-once.v1",
    "--node-version", "24.18.0", "--output-root", outputDir,
    "--package-root", packageDir, "--repository", "777genius/infinity-context",
    "--repository-root", root, "--tag", "sdk-v0.2.1",
    "--workflow-path", ".github/workflows/typescript-sdk-release.yml",
    "--workflow-run-attempt", "2", "--workflow-run-id", "12345",
    "--workflow-sha256", sha256(await readFile(workflowPath)),
  ];
  return {
    artifact, artifactDir, artifactPath, createArgs: [...common, "--output", manifestPath],
    manifestPath, outputDir, packageDir, root, verifyArgs: [...common, "--manifest", manifestPath], workflowPath,
  };
}

function metadata(version) {
  return { name: "@infinity-context/sdk", version, repository: { url: "git+https://github.com/777genius/infinity-context.git" } };
}
function lock(version) { return { name: "@infinity-context/sdk", version, lockfileVersion: 3, packages: { "": { version } } }; }
function replaceArg(args, flag, value) { const copy = [...args]; copy[copy.indexOf(flag) + 1] = value; return copy; }
async function runCli(args) { return execFileAsync(process.execPath, [cli, ...args], { cwd: packageRoot }); }
async function git(root, ...args) { return execFileAsync("git", ["-C", root, ...args]); }
function sha256(bytes) { return createHash("sha256").update(bytes).digest("hex"); }
function canonicalJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
}

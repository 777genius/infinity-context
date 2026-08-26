import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { chmod, mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { describe, expect, test } from "vitest";
import { createReleaseManifest } from "../scripts/retrieval-v2-artifact-provenance.mjs";

const execFileAsync = promisify(execFile);
const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const repositoryRoot = resolve(packageRoot, "../..");
const scriptPath = join(packageRoot, "scripts", "retrieval-v2-artifact-provenance.mjs");
const artifactName = "infinity-context-sdk-0.2.0.tgz";
const qualificationName = "retrieval-v2-qualification-manifest.json";

describe("Retrieval V2 SDK release provenance", () => {
  test("renders deterministic canonical metadata for the checkout and exact bytes", async () => {
    const fixture = await releaseFixture();
    const first = await createReleaseManifest(fixture.paths);
    const outputBytes = await readFile(fixture.paths.outputPath, "utf8");
    const expected = {
      artifact_byte_length: fixture.artifact.byteLength,
      artifact_name: artifactName,
      artifact_sha256_hex: digest("sha256", fixture.artifact, "hex"),
      artifact_sri_sha512: `sha512-${digest("sha512", fixture.artifact, "base64")}`,
      capability_fingerprint: "c".repeat(64),
      git_object_format: fixture.git.objectFormat,
      immutable_distribution_locator: `https://github.com/777genius/infinity-context/releases/download/sdk-v0.2.0/${artifactName}`,
      package_name: "@infinity-context/sdk",
      package_version: "0.2.0",
      qualification_manifest_digest: fixture.qualification.qualification_manifest_digest,
      qualification_manifest_name: qualificationName,
      qualification_manifest_sha256_hex: digest("sha256", fixture.qualificationBytes, "hex"),
      release_tag: "sdk-v0.2.0",
      schema_version: "infinity-context-typescript-sdk-release.v1",
      sdk_revision: fixture.git.commit,
      service_revision: fixture.git.commit,
      source_commit: fixture.git.commit,
      source_git_tree_oid: fixture.git.tree,
    };

    expect(first.releaseManifest).toEqual(expected);
    expect(outputBytes).toBe(`${canonicalJson(expected)}\n`);
    expect(outputBytes).not.toMatch(/timestamp|created_at|generated_at/u);
    expect((await stat(fixture.paths.outputPath)).mode & 0o777).toBe(0o444);
  });

  test("binds changed tarball and qualification bytes to different digests", async () => {
    const original = await releaseFixture(Buffer.from("exact npm tarball bytes\n"));
    const changed = await releaseFixture(Buffer.from("tampered npm tarball bytes\n"));
    const originalManifest = (await createReleaseManifest(original.paths)).releaseManifest;
    const changedManifest = (await createReleaseManifest(changed.paths)).releaseManifest;

    expect(changedManifest.artifact_sha256_hex).not.toBe(originalManifest.artifact_sha256_hex);
    expect(changedManifest.artifact_sri_sha512).not.toBe(originalManifest.artifact_sri_sha512);
    expect(changedManifest.artifact_byte_length).toBe(changed.artifact.byteLength);

    const qualificationChanged = await releaseFixture();
    const tamperedQualification = JSON.parse(
      await readFile(qualificationChanged.paths.qualificationManifestPath, "utf8"),
    );
    tamperedQualification.capability_fingerprint = "f".repeat(64);
    await writeFile(
      qualificationChanged.paths.qualificationManifestPath,
      `${canonicalJson(tamperedQualification)}\n`,
    );
    await expect(createReleaseManifest(qualificationChanged.paths)).rejects.toThrow(/digest does not match/u);
  });

  test.each([
    ["source_revision", "revision", "a"],
    ["service_revision", "revision", "b"],
    ["sdk_revision", "revision", "d"],
    ["source_git_tree_oid", "tree", "e"],
    ["capability_fingerprint", "capability", "not-a-digest"],
  ])("rejects tampered %s authority", async (field, message, replacement) => {
    const fixture = await releaseFixture(undefined, { [field]: replacement.length === 1 ? replacement.repeat(fixtureOidLength(field)) : replacement });
    await expect(createReleaseManifest(fixture.paths)).rejects.toThrow(new RegExp(message, "u"));
  });

  test("rejects a version-discordant artifact name", async () => {
    const fixture = await releaseFixture(undefined, {}, "infinity-context-sdk-0.2.1.tgz");
    await expect(createReleaseManifest(fixture.paths)).rejects.toThrow(/artifact name must be .*0\.2\.0/u);
  });

  test("preserves exclusive-create output and never overwrites it", async () => {
    const fixture = await releaseFixture();
    await createReleaseManifest(fixture.paths);
    await chmod(fixture.paths.outputPath, 0o644);
    const before = await readFile(fixture.paths.outputPath);
    await expect(createReleaseManifest(fixture.paths)).rejects.toMatchObject({ code: "EEXIST" });
    expect(await readFile(fixture.paths.outputPath)).toEqual(before);
  });

  test("CLI rejects legacy manual authority flags and ignores legacy authority environment", async () => {
    const fixture = await releaseFixture();
    const env = {
      ...process.env,
      RETRIEVAL_V2_SOURCE_REVISION: "f".repeat(40),
      RETRIEVAL_V2_SERVICE_REVISION: "f".repeat(40),
      RETRIEVAL_V2_SDK_REVISION: "f".repeat(40),
      RETRIEVAL_V2_CAPABILITY_FINGERPRINT: "f".repeat(64),
    };
    await execFileAsync(process.execPath, [
      scriptPath,
      "--artifact", fixture.paths.artifactPath,
      "--qualification-manifest", fixture.paths.qualificationManifestPath,
      "--output", fixture.paths.outputPath,
    ], { cwd: packageRoot, env });
    const manifest = JSON.parse(await readFile(fixture.paths.outputPath, "utf8"));
    expect(manifest.capability_fingerprint).toBe("c".repeat(64));

    await expect(execFileAsync(process.execPath, [scriptPath, "--service-revision", "f".repeat(40)], {
      cwd: packageRoot,
    })).rejects.toMatchObject({ code: 1 });
  });

  test("package metadata is release-consumer metadata without publisher tooling", async () => {
    const metadata = JSON.parse(await readFile(join(packageRoot, "package.json"), "utf8"));
    expect(metadata.license).toBe("Apache-2.0");
    expect(metadata.repository).toEqual({
      type: "git",
      url: "git+https://github.com/777genius/infinity-context.git",
      directory: "packages/infinity_context_ts_sdk",
    });
    expect(metadata.files).not.toContain("scripts/retrieval-v2-artifact-provenance.mjs");
    expect(metadata).not.toHaveProperty("publishConfig");
  });
});

async function releaseFixture(artifact = Buffer.from("exact npm tarball bytes\n"), overrides = {}, artifactFilename = artifactName) {
  const root = await mkdtemp(join(tmpdir(), "infinity-context-sdk-provenance-"));
  const git = await gitIdentity();
  const qualificationPayload = {
    capability_fingerprint: "c".repeat(64),
    schema_version: "infinity-context-retrieval-v2-production-qualification.v1",
    sdk_revision: git.commit,
    service_revision: git.commit,
    source_git_tree_oid: git.tree,
    source_revision: git.commit,
    ...overrides,
  };
  const qualification = {
    ...qualificationPayload,
    qualification_manifest_digest: `sha256:${digest("sha256", Buffer.from(canonicalJson(qualificationPayload)), "hex")}`,
  };
  const qualificationBytes = Buffer.from(`${canonicalJson(qualification)}\n`);
  const paths = {
    artifactPath: join(root, artifactFilename),
    qualificationManifestPath: join(root, qualificationName),
    outputPath: join(root, "infinity-context-sdk-release-manifest.json"),
  };
  await writeFile(paths.artifactPath, artifact);
  await writeFile(paths.qualificationManifestPath, qualificationBytes);
  return { artifact, git, paths, qualification, qualificationBytes };
}

async function gitIdentity() {
  const [{ stdout: commit }, { stdout: tree }, { stdout: objectFormat }] = await Promise.all([
    execFileAsync("git", ["rev-parse", "HEAD"], { cwd: repositoryRoot }),
    execFileAsync("git", ["rev-parse", "HEAD^{tree}"], { cwd: repositoryRoot }),
    execFileAsync("git", ["rev-parse", "--show-object-format"], { cwd: repositoryRoot }),
  ]);
  return { commit: commit.trim(), tree: tree.trim(), objectFormat: objectFormat.trim() };
}

function fixtureOidLength(field) {
  return field === "source_git_tree_oid" ? 40 : 40;
}

function digest(algorithm, bytes, encoding) {
  return createHash(algorithm).update(bytes).digest(encoding);
}

function canonicalJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
}

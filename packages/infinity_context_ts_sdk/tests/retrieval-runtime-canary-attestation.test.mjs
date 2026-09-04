import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { verifyLocalSdkAttestation } from "../scripts/retrieval-runtime-canary-attestation.mjs";

describe("installed retrieval canary SDK attestation", () => {
  it("accepts an installed package bound to the pinned artifact and manifest", async () => {
    const fixture = await localFixture();
    await expect(verifyLocalSdkAttestation(fixture)).resolves.toMatchObject({
      identity: { source_commit: fixture.env.RETRIEVAL_SDK_REVISION },
    });
  });

  it("rejects a stale loaded SDK even when caller and manifest revision pins agree", async () => {
    const fixture = await localFixture();
    await writeFile(join(fixture.packageRoot, "dist", "index.js"), "export const stale = true;\n");
    await expect(verifyLocalSdkAttestation(fixture)).rejects.toThrow(/Loaded SDK files differ/u);
  });

  it("rejects repacked SDK bytes and a mismatched local manifest", async () => {
    const repacked = await localFixture();
    await writeFile(repacked.env.RETRIEVAL_SDK_ARTIFACT, "repacked bytes\n");
    await expect(verifyLocalSdkAttestation(repacked)).rejects.toThrow(/artifact differs from its pin/u);

    const manifestDrift = await localFixture();
    const manifest = JSON.parse(await readFile(manifestDrift.env.RETRIEVAL_SDK_RELEASE_MANIFEST, "utf8"));
    manifest.artifact_sha256_hex = "0".repeat(64);
    const driftedBytes = Buffer.from(`${canonicalJson(manifest)}\n`);
    await writeFile(manifestDrift.env.RETRIEVAL_SDK_RELEASE_MANIFEST, driftedBytes);
    manifestDrift.env.RETRIEVAL_SDK_MANIFEST_SHA256 = sha256(driftedBytes);
    await expect(verifyLocalSdkAttestation(manifestDrift)).rejects.toThrow(/artifact and release manifest do not match/u);
  });
});

async function localFixture() {
  const root = await mkdtemp(join(tmpdir(), "sdk-canary-attestation-"));
  const packageRoot = join(root, "installed");
  const dist = join(packageRoot, "dist");
  await mkdir(dist, { recursive: true });
  const runtimeBytes = Buffer.from("export const loaded = true;\n");
  await writeFile(join(dist, "index.js"), runtimeBytes);
  const commit = "a".repeat(40);
  const tree = "b".repeat(40);
  const identityBytes = Buffer.from(`${canonicalJson({
    files: [{ path: "dist/index.js", sha256_hex: sha256(runtimeBytes) }],
    package_name: "@infinity-context/sdk",
    package_version: "0.2.1",
    schema_version: "infinity-context-typescript-sdk-artifact-identity.v1",
    source_commit: commit,
    source_git_tree_oid: tree,
  })}\n`);
  await writeFile(join(dist, "sdk-artifact-identity.json"), identityBytes);
  const artifactPath = join(root, "infinity-context-sdk-0.2.1.tgz");
  const artifactBytes = Buffer.from("immutable packed bytes\n");
  await writeFile(artifactPath, artifactBytes);
  const manifestPath = join(root, "infinity-context-sdk-release-manifest.json");
  const manifestBytes = Buffer.from(`${canonicalJson({
    artifact_byte_length: artifactBytes.byteLength,
    artifact_identity_sha256_hex: sha256(identityBytes),
    artifact_name: "infinity-context-sdk-0.2.1.tgz",
    artifact_sha256_hex: sha256(artifactBytes),
    artifact_sri_sha512: `sha512-${createHash("sha512").update(artifactBytes).digest("base64")}`,
    build_profile: "node24-npm-ci-pack-once.v1",
    build_workflow_path: ".github/workflows/typescript-sdk-release.yml",
    build_workflow_run_attempt: 1,
    build_workflow_run_id: 1,
    build_workflow_sha256_hex: "c".repeat(64),
    contract_fixture_inventory: [{ path: "src/index.ts", sha256_hex: "d".repeat(64) }],
    contract_fixture_inventory_sha256_hex: sha256(Buffer.from(canonicalJson([
      { path: "src/index.ts", sha256_hex: "d".repeat(64) },
    ]))),
    git_object_format: "sha1",
    node_version: "24.18.0",
    package_lock_sha256_hex: "e".repeat(64),
    package_name: "@infinity-context/sdk",
    package_version: "0.2.1",
    release_tag: "sdk-v0.2.1",
    repository: "777genius/infinity-context",
    repository_url: "https://github.com/777genius/infinity-context",
    schema_version: "infinity-context-typescript-sdk-release.v1",
    source_commit: commit,
    source_git_tree_oid: tree,
    tag_object_oid: "f".repeat(40),
  })}\n`);
  await writeFile(manifestPath, manifestBytes);
  return {
    packageRoot,
    env: {
      RETRIEVAL_SDK_REVISION: commit,
      RETRIEVAL_SDK_SOURCE_TREE: tree,
      RETRIEVAL_SDK_ARTIFACT: artifactPath,
      RETRIEVAL_SDK_ARTIFACT_SHA256: sha256(artifactBytes),
      RETRIEVAL_SDK_RELEASE_MANIFEST: manifestPath,
      RETRIEVAL_SDK_MANIFEST_SHA256: sha256(manifestBytes),
    },
  };
}

function sha256(bytes) { return createHash("sha256").update(bytes).digest("hex"); }
function canonicalJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
}

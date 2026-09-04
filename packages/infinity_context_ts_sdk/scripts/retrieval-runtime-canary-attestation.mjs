import { createHash } from "node:crypto";
import { lstat, readFile, realpath } from "node:fs/promises";
import { basename, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const defaultPackageRoot = fileURLToPath(new URL("..", import.meta.url));
const MAX_MANIFEST_BYTES = 10 * 1024 * 1024;
const MAX_ARTIFACT_BYTES = 100 * 1024 * 1024;

export async function verifyLocalSdkAttestation({ env, packageRoot = defaultPackageRoot }) {
  const expectedRevision = revision(required(env, "RETRIEVAL_SDK_REVISION"));
  const expectedTree = oid(required(env, "RETRIEVAL_SDK_SOURCE_TREE"), "SDK source tree");
  const expectedArtifactSha256 = digest(required(env, "RETRIEVAL_SDK_ARTIFACT_SHA256"), "SDK artifact pin");
  const expectedManifestSha256 = digest(required(env, "RETRIEVAL_SDK_MANIFEST_SHA256"), "SDK manifest pin");
  const manifestPath = required(env, "RETRIEVAL_SDK_RELEASE_MANIFEST");
  const artifactPath = required(env, "RETRIEVAL_SDK_ARTIFACT");
  if (basename(resolve(manifestPath)) !== "infinity-context-sdk-release-manifest.json") {
    throw new Error("Local SDK release manifest name is invalid");
  }
  const root = await realpath(packageRoot);
  const [identityBytes, manifestBytes, artifactBytes] = await Promise.all([
    safeRead(resolve(root, "dist", "sdk-artifact-identity.json"), root, MAX_MANIFEST_BYTES, "SDK identity"),
    safeRead(manifestPath, undefined, MAX_MANIFEST_BYTES, "SDK release manifest"),
    safeRead(artifactPath, undefined, MAX_ARTIFACT_BYTES, "SDK artifact"),
  ]);
  if (sha256(manifestBytes) !== expectedManifestSha256) throw new Error("Local SDK release manifest differs from its pin");
  if (sha256(artifactBytes) !== expectedArtifactSha256) throw new Error("Local SDK artifact differs from its pin");

  const identity = parseCanonicalObject(identityBytes, "SDK identity");
  const manifest = parseCanonicalObject(manifestBytes, "SDK release manifest");
  assertAttestationShapes(identity, manifest);
  if (manifest.schema_version !== "infinity-context-typescript-sdk-release.v1" ||
      identity.schema_version !== "infinity-context-typescript-sdk-artifact-identity.v1") {
    throw new Error("Local SDK attestation schema is unsupported");
  }
  if (manifest.artifact_sha256_hex !== expectedArtifactSha256 ||
      manifest.artifact_sri_sha512 !== `sha512-${createHash("sha512").update(artifactBytes).digest("base64")}` ||
      manifest.artifact_byte_length !== artifactBytes.byteLength ||
      manifest.artifact_name !== basename(resolve(artifactPath)) ||
      manifest.artifact_identity_sha256_hex !== sha256(identityBytes)) {
    throw new Error("Local SDK artifact and release manifest do not match");
  }
  if (identity.source_commit !== expectedRevision || manifest.source_commit !== expectedRevision ||
      identity.source_git_tree_oid !== expectedTree || manifest.source_git_tree_oid !== expectedTree ||
      identity.package_name !== manifest.package_name || identity.package_version !== manifest.package_version) {
    throw new Error("Loaded SDK identity differs from immutable local pins");
  }
  await verifyInstalledFiles(identity.files, root);
  return { identity, manifest };
}

function assertAttestationShapes(identity, manifest) {
  const identityKeys = ["files", "package_name", "package_version", "schema_version", "source_commit", "source_git_tree_oid"];
  const manifestKeys = [
    "artifact_byte_length", "artifact_identity_sha256_hex", "artifact_name", "artifact_sha256_hex",
    "artifact_sri_sha512", "build_profile", "build_workflow_path", "build_workflow_run_attempt",
    "build_workflow_run_id", "build_workflow_sha256_hex", "contract_fixture_inventory",
    "contract_fixture_inventory_sha256_hex", "git_object_format", "node_version", "package_lock_sha256_hex",
    "package_name", "package_version", "release_tag", "repository", "repository_url", "schema_version",
    "source_commit", "source_git_tree_oid", "tag_object_oid",
  ];
  if (Object.keys(identity).sort().join(",") !== identityKeys.join(",") ||
      Object.keys(manifest).sort().join(",") !== manifestKeys.join(",")) {
    throw new Error("Local SDK attestation fields are malformed");
  }
  if (manifest.repository !== "777genius/infinity-context" ||
      manifest.repository_url !== "https://github.com/777genius/infinity-context" ||
      manifest.build_profile !== "node24-npm-ci-pack-once.v1" ||
      manifest.build_workflow_path !== ".github/workflows/typescript-sdk-release.yml" ||
      manifest.node_version !== "24.18.0" || manifest.release_tag !== `sdk-v${manifest.package_version}` ||
      !Number.isSafeInteger(manifest.build_workflow_run_id) || manifest.build_workflow_run_id <= 0 ||
      !Number.isSafeInteger(manifest.build_workflow_run_attempt) || manifest.build_workflow_run_attempt <= 0) {
    throw new Error("Local SDK release provenance is malformed");
  }
  for (const value of [manifest.artifact_identity_sha256_hex, manifest.artifact_sha256_hex,
    manifest.build_workflow_sha256_hex, manifest.contract_fixture_inventory_sha256_hex,
    manifest.package_lock_sha256_hex]) digest(value, "release manifest digest");
  oid(manifest.source_commit, "manifest source commit");
  oid(manifest.source_git_tree_oid, "manifest source tree");
  oid(manifest.tag_object_oid, "manifest tag object");
  if (manifest.git_object_format !== "sha1" ||
      !Array.isArray(manifest.contract_fixture_inventory) || manifest.contract_fixture_inventory.length === 0 ||
      manifest.contract_fixture_inventory_sha256_hex !==
        sha256(Buffer.from(canonicalJson(manifest.contract_fixture_inventory)))) {
    throw new Error("Local SDK release inventory is malformed");
  }
}

async function verifyInstalledFiles(files, root) {
  if (!Array.isArray(files) || files.length === 0) throw new Error("Loaded SDK file identity is empty");
  let previous = "";
  for (const item of files) {
    if (item === null || typeof item !== "object" || Object.keys(item).sort().join(",") !== "path,sha256_hex" ||
        typeof item.path !== "string" || item.path === "" || item.path.startsWith("/") ||
        item.path.split("/").includes("..") || item.path <= previous) {
      throw new Error("Loaded SDK file identity is malformed");
    }
    previous = item.path;
    const bytes = await safeRead(resolve(root, item.path), root, MAX_ARTIFACT_BYTES, "installed SDK file");
    if (sha256(bytes) !== digest(item.sha256_hex, "installed SDK file digest")) {
      throw new Error("Loaded SDK files differ from the packed artifact identity");
    }
  }
}

async function safeRead(path, allowedRoot, maximumBytes, label) {
  const resolved = resolve(path);
  const actual = await realpath(resolved);
  if (allowedRoot !== undefined && actual !== allowedRoot && !actual.startsWith(`${allowedRoot}${sep}`)) {
    throw new Error(`${label} escapes its allowed root`);
  }
  const status = await lstat(resolved);
  if (status.isSymbolicLink() || !status.isFile()) throw new Error(`${label} must be a regular non-symlink file`);
  if (status.size > maximumBytes) throw new Error(`${label} exceeds its byte limit`);
  return readFile(resolved);
}

function parseCanonicalObject(bytes, label) {
  let value;
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
    value = JSON.parse(text);
  }
  catch { throw new Error(`${label} is not valid JSON`); }
  if (value === null || Array.isArray(value) || typeof value !== "object") throw new Error(`${label} must be an object`);
  const canonical = canonicalJson(value);
  if (text !== canonical && text !== `${canonical}\n`) throw new Error(`${label} must be canonical JSON`);
  return value;
}

function canonicalJson(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new Error("canonical JSON rejects unsafe numbers");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object") return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  throw new Error("canonical JSON contains an unsupported value");
}

function required(env, name) {
  const value = env[name];
  if (typeof value !== "string" || value.trim() === "" || /[\r\n]/u.test(value)) throw new Error(`${name} is required`);
  return value;
}
function digest(value, label) {
  if (!/^[0-9a-f]{64}$/u.test(value)) throw new Error(`${label} must be lowercase SHA-256`);
  return value;
}
function oid(value, label) {
  if (!/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/u.test(value)) throw new Error(`${label} is malformed`);
  return value;
}
function revision(value) {
  if (!/^[0-9a-f]{40}$/u.test(value)) throw new Error("SDK revision is malformed");
  return value;
}
function sha256(bytes) { return createHash("sha256").update(bytes).digest("hex"); }

#!/usr/bin/env node
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs, promisify } from "node:util";

const execFileAsync = promisify(execFile);
const scriptPath = fileURLToPath(import.meta.url);
const packageRoot = resolve(dirname(scriptPath), "..");
const repositoryRoot = resolve(packageRoot, "../..");
const RELEASE_SCHEMA = "infinity-context-typescript-sdk-release.v1";
const QUALIFICATION_SCHEMA = "infinity-context-retrieval-v2-production-qualification.v1";

export async function createReleaseManifest({ artifactPath, qualificationManifestPath, outputPath }) {
  const artifact = resolve(artifactPath);
  const qualificationPath = resolve(qualificationManifestPath);
  const output = resolve(outputPath);
  const packageMetadata = parseObject(await readFile(resolve(packageRoot, "package.json"), "utf8"), "package metadata");
  const packageName = requiredString(packageMetadata.name, "package name");
  const packageVersion = semver(packageMetadata.version, "package version");
  const releaseTag = `sdk-v${packageVersion}`;
  const expectedArtifactName = npmArtifactName(packageName, packageVersion);
  if (basename(artifact) !== expectedArtifactName) {
    throw new Error(`artifact name must be ${expectedArtifactName}`);
  }

  const qualificationBytes = await readFile(qualificationPath);
  if (basename(qualificationPath) !== "retrieval-v2-qualification-manifest.json") {
    throw new Error("qualification manifest name must be retrieval-v2-qualification-manifest.json");
  }
  const qualification = parseCanonicalObject(qualificationBytes, "qualification manifest");
  if (qualification.schema_version !== QUALIFICATION_SCHEMA) {
    throw new Error(`qualification manifest schema_version must be ${QUALIFICATION_SCHEMA}`);
  }
  const qualificationDigest = prefixedDigest(
    qualification.qualification_manifest_digest,
    "qualification_manifest_digest",
  );
  const qualificationPayload = { ...qualification };
  delete qualificationPayload.qualification_manifest_digest;
  const calculatedQualificationDigest = `sha256:${sha256(Buffer.from(canonicalJson(qualificationPayload)))}`;
  if (qualificationDigest !== calculatedQualificationDigest) {
    throw new Error("qualification manifest digest does not match its canonical payload");
  }

  const sourceCommit = await git("rev-parse", "HEAD");
  const sourceTree = await git("rev-parse", "HEAD^{tree}");
  const objectFormat = await git("rev-parse", "--show-object-format");
  const oidPattern = objectFormat === "sha1" ? /^[0-9a-f]{40}$/u : objectFormat === "sha256" ? /^[0-9a-f]{64}$/u : null;
  if (oidPattern === null || !oidPattern.test(sourceCommit) || !oidPattern.test(sourceTree)) {
    throw new Error("checkout uses an unsupported or malformed Git object format");
  }
  const sourceRevision = revision(qualification.source_revision, "qualification source_revision", oidPattern);
  const serviceRevision = revision(qualification.service_revision, "qualification service_revision", oidPattern);
  const sdkRevision = revision(qualification.sdk_revision, "qualification sdk_revision", oidPattern);
  if (sourceRevision !== sourceCommit || serviceRevision !== sourceCommit || sdkRevision !== sourceCommit) {
    throw new Error("qualification source, service, and SDK revisions must equal checkout HEAD");
  }
  if (revision(qualification.source_git_tree_oid, "qualification source_git_tree_oid", oidPattern) !== sourceTree) {
    throw new Error("qualification source Git tree must equal checkout HEAD tree");
  }
  const capabilityFingerprint = hexDigest(qualification.capability_fingerprint, "qualification capability_fingerprint");

  const artifactBytes = await readFile(artifact);
  const repositoryUrl = repositoryHttpsUrl(packageMetadata.repository);
  const releaseManifest = {
    artifact_byte_length: artifactBytes.byteLength,
    artifact_name: expectedArtifactName,
    artifact_sha256_hex: sha256(artifactBytes),
    artifact_sri_sha512: `sha512-${createHash("sha512").update(artifactBytes).digest("base64")}`,
    capability_fingerprint: capabilityFingerprint,
    git_object_format: objectFormat,
    immutable_distribution_locator: `${repositoryUrl}/releases/download/${releaseTag}/${expectedArtifactName}`,
    package_name: packageName,
    package_version: packageVersion,
    qualification_manifest_digest: qualificationDigest,
    qualification_manifest_name: basename(qualificationPath),
    qualification_manifest_sha256_hex: sha256(qualificationBytes),
    release_tag: releaseTag,
    schema_version: RELEASE_SCHEMA,
    sdk_revision: sdkRevision,
    service_revision: serviceRevision,
    source_commit: sourceCommit,
    source_git_tree_oid: sourceTree,
  };
  await writeFile(output, `${canonicalJson(releaseManifest)}\n`, {
    encoding: "utf8",
    flag: "wx",
    mode: 0o444,
  });
  return { output, releaseManifest };
}

async function main() {
  const { values } = parseArgs({
    options: {
      artifact: { type: "string" },
      "qualification-manifest": { type: "string" },
      output: { type: "string" },
    },
    strict: true,
    allowPositionals: false,
  });
  const { output } = await createReleaseManifest({
    artifactPath: requiredOption(values.artifact, "--artifact"),
    qualificationManifestPath: requiredOption(values["qualification-manifest"], "--qualification-manifest"),
    outputPath: requiredOption(values.output, "--output"),
  });
  process.stdout.write(`${output}\n`);
}

function canonicalJson(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new Error("canonical JSON forbids non-integer or unsafe numbers");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  throw new Error("canonical JSON contains an unsupported value");
}

function parseCanonicalObject(bytes, label) {
  const text = bytes.toString("utf8");
  const value = parseObject(text, label);
  if (text !== canonicalJson(value) && text !== `${canonicalJson(value)}\n`) {
    throw new Error(`${label} must use canonical key-sorted JSON`);
  }
  return value;
}

function parseObject(text, label) {
  let value;
  try {
    value = JSON.parse(text);
  } catch (error) {
    throw new Error(`${label} is not valid JSON`, { cause: error });
  }
  if (value === null || Array.isArray(value) || typeof value !== "object") {
    throw new Error(`${label} must be a JSON object`);
  }
  return value;
}

function requiredOption(value, name) {
  if (typeof value !== "string" || value.trim() === "") throw new Error(`${name} is required`);
  return value;
}

function requiredString(value, label) {
  if (typeof value !== "string" || value.trim() === "") throw new Error(`${label} must be a non-empty string`);
  return value;
}

function semver(value, label) {
  const version = requiredString(value, label);
  if (!/^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$/u.test(version)) {
    throw new Error(`${label} must be an exact SemVer version`);
  }
  return version;
}

function revision(value, label, pattern) {
  if (typeof value !== "string" || !pattern.test(value)) throw new Error(`${label} is malformed`);
  return value;
}

function hexDigest(value, label) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/u.test(value)) throw new Error(`${label} must be lowercase 64-hex`);
  return value;
}

function prefixedDigest(value, label) {
  if (typeof value !== "string" || !/^sha256:[0-9a-f]{64}$/u.test(value)) throw new Error(`${label} must be a sha256 digest`);
  return value;
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function npmArtifactName(name, version) {
  const normalizedName = name.startsWith("@") ? name.slice(1).replace("/", "-") : name;
  if (!/^[a-z0-9][a-z0-9._-]*$/u.test(normalizedName)) throw new Error("package name cannot form an npm artifact name");
  return `${normalizedName}-${version}.tgz`;
}

function repositoryHttpsUrl(repository) {
  const raw = typeof repository === "string" ? repository : repository?.url;
  const value = requiredString(raw, "repository.url")
    .replace(/^git\+https:\/\//u, "https://")
    .replace(/^git@github\.com:/u, "https://github.com/")
    .replace(/\.git$/u, "");
  if (!/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/u.test(value)) {
    throw new Error("repository.url must identify a GitHub HTTPS repository");
  }
  return value;
}

async function git(...args) {
  const { stdout } = await execFileAsync("git", ["-C", repositoryRoot, ...args], { encoding: "utf8" });
  return stdout.trim();
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === scriptPath) {
  await main();
}

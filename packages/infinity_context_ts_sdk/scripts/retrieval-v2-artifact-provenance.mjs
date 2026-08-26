#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { basename, resolve } from "node:path";

const artifactPath = requiredPath("RETRIEVAL_V2_SDK_ARTIFACT");
const outputPath = requiredPath("RETRIEVAL_V2_PROVENANCE_OUTPUT");
const sourceRevision = revision("RETRIEVAL_V2_SOURCE_REVISION");
const serviceRevision = revision("RETRIEVAL_V2_SERVICE_REVISION");
const sdkRevision = revision("RETRIEVAL_V2_SDK_REVISION");
if (sourceRevision !== sdkRevision || sourceRevision !== serviceRevision) {
  throw new Error("Service and SDK revisions must equal the immutable source revision");
}

const packageMetadata = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
const expectedFingerprint = digest("RETRIEVAL_V2_CAPABILITY_FINGERPRINT");

const artifact = await readFile(artifactPath);
const provenance = {
  schema_version: "infinity-context-retrieval-v2-sdk-provenance.v1",
  source_revision: sourceRevision,
  service_revision: serviceRevision,
  sdk_revision: sdkRevision,
  capability_fingerprint: expectedFingerprint,
  package_name: packageMetadata.name,
  package_version: packageMetadata.version,
  artifact_name: basename(artifactPath),
  artifact_sha256: createHash("sha256").update(artifact).digest("hex"),
  artifact_byte_length: artifact.byteLength,
};

await writeFile(outputPath, `${JSON.stringify(provenance, null, 2)}\n`, {
  encoding: "utf8",
  flag: "wx",
  mode: 0o444,
});
process.stdout.write(`${resolve(outputPath)}\n`);

function requiredPath(name) {
  const value = process.env[name];
  if (value === undefined || value.trim() === "") throw new Error(`${name} is required`);
  return resolve(value);
}

function revision(name) {
  const value = process.env[name];
  if (typeof value !== "string" || !/^[0-9a-f]{40}$/.test(value)) {
    throw new Error(`${name} must be an exact lowercase 40-hex source revision`);
  }
  return value;
}

function digest(name) {
  const value = process.env[name];
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${name} must be an exact lowercase SHA-256 digest`);
  }
  return value;
}

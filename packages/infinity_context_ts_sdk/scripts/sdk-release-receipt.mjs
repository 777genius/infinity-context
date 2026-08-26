#!/usr/bin/env node
import { createHash } from "node:crypto";
import { lstat, readFile, realpath, writeFile } from "node:fs/promises";
import { basename, dirname, resolve, sep } from "node:path";
import { parseArgs } from "node:util";

const EXPECTED_MANIFEST = "infinity-context-sdk-release-manifest.json";
const MAX_BYTES = 100 * 1024 * 1024;

const { values } = parseArgs({
  options: {
    "asset-dir": { type: "string" },
    "asset-attestations-verified": { type: "boolean" },
    output: { type: "string" },
    "output-root": { type: "string" },
    repository: { type: "string" },
    "release-attestation-verified": { type: "boolean" },
    "release-json": { type: "string" },
    "run-attempt": { type: "string" },
    "run-id": { type: "string" },
    tag: { type: "string" },
  },
  strict: true,
  allowPositionals: false,
});

const required = (name) => requiredString(values[name], `--${name}`);
const assetDir = resolve(required("asset-dir"));
const outputRoot = resolve(required("output-root"));
const output = resolve(required("output"));
const releaseJsonPath = resolve(required("release-json"));
if (values["release-attestation-verified"] !== true || values["asset-attestations-verified"] !== true) {
  throw new Error("successful release and asset attestation verification flags are required");
}
await assertDirectory(assetDir, assetDir, "asset directory");
await assertDirectory(outputRoot, outputRoot, "output root");
const release = parseObject(await safeRead(releaseJsonPath, outputRoot, "release JSON"), "release JSON");
const tag = required("tag");
if (release.tag_name !== tag || release.draft !== false || release.immutable !== true) {
  throw new Error("published release identity/state drift");
}
const repository = required("repository");
const manifestBytes = await safeRead(resolve(assetDir, EXPECTED_MANIFEST), assetDir, "release manifest");
const manifest = parseObject(manifestBytes, "release manifest");
const expectedNames = [manifest.artifact_name, EXPECTED_MANIFEST].sort();
if (!expectedNames[0] || expectedNames.length !== 2) throw new Error("release manifest artifact identity is missing");
const assets = Array.isArray(release.assets) ? release.assets : [];
const names = assets.map((asset) => asset.name).sort();
if (canonicalJson(names) !== canonicalJson(expectedNames)) throw new Error("release must contain exactly two assets");
const receiptAssets = [];
for (const name of expectedNames) {
  const asset = assets.find((item) => item.name === name);
  const bytes = await safeRead(resolve(assetDir, name), assetDir, `asset ${name}`);
  const digest = `sha256:${sha256(bytes)}`;
  if (!Number.isSafeInteger(asset.id) || asset.id <= 0 || asset.digest !== digest) {
    throw new Error(`release API binding drift for ${name}`);
  }
  receiptAssets.push({ id: asset.id, name, sha256_hex: sha256(bytes), attestation_verified: true });
}
const receipt = {
  assets: receiptAssets,
  release_attestation_verified: true,
  release_id: positiveInteger(release.id, "release id"),
  release_url: requiredString(release.html_url, "release URL"),
  repository,
  run_attempt: positiveIntegerString(required("run-attempt"), "run attempt"),
  run_id: positiveIntegerString(required("run-id"), "run id"),
  schema_version: "infinity-context-typescript-sdk-release-verification-receipt.v1",
  tag,
};
await assertProspective(output, outputRoot);
await writeFile(output, `${canonicalJson(receipt)}\n`, { encoding: "utf8", flag: "wx", mode: 0o444 });
process.stdout.write(`created=${output}\n`);

async function safeRead(path, root, label) {
  await assertContained(path, root, label);
  const status = await lstat(path);
  if (status.isSymbolicLink() || !status.isFile()) throw new Error(`${label} must be a regular non-symlink file`);
  if (status.size > MAX_BYTES) throw new Error(`${label} exceeds the size limit`);
  return readFile(path);
}

async function assertDirectory(path, root, label) {
  await assertContained(path, root, label);
  const status = await lstat(path);
  if (status.isSymbolicLink() || !status.isDirectory()) throw new Error(`${label} must be a regular directory`);
}

async function assertContained(path, rootPath, label) {
  const [actual, root] = await Promise.all([realpath(path), realpath(rootPath)]);
  if (actual !== root && !actual.startsWith(`${root}${sep}`)) throw new Error(`${label} escapes its allowed root`);
}

async function assertProspective(path, rootPath) {
  const [parent, root] = await Promise.all([realpath(dirname(path)), realpath(rootPath)]);
  if (parent !== root && !parent.startsWith(`${root}${sep}`)) throw new Error("output escapes its allowed root");
  if (basename(path) !== "infinity-context-sdk-release-verification-receipt.json") {
    throw new Error("unexpected receipt output name");
  }
}

function parseObject(bytes, label) {
  let value;
  try { value = JSON.parse(bytes.toString("utf8")); }
  catch (error) { throw new Error(`${label} is not valid JSON`, { cause: error }); }
  if (value === null || Array.isArray(value) || typeof value !== "object") throw new Error(`${label} must be an object`);
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
  throw new Error("unsupported JSON value");
}

function requiredString(value, label) {
  if (typeof value !== "string" || value.trim() === "" || /[\r\n]/u.test(value)) throw new Error(`${label} is required`);
  return value;
}

function positiveInteger(value, label) {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`${label} must be a positive safe integer`);
  return value;
}

function positiveIntegerString(value, label) { return positiveInteger(Number(value), label); }
function sha256(bytes) { return createHash("sha256").update(bytes).digest("hex"); }
